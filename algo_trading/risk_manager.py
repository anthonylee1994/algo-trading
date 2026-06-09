from __future__ import annotations

import json
import socket
from dataclasses import asdict
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import pandas as pd
from futu import (
    Currency,
    ModifyOrderOp,
    OpenSecTradeContext,
    OrderStatus,
    RET_OK,
    TrdMarket,
)

from algo_trading.futu_trader import TradePlanItem


JOURNAL_PATH = Path("trade_journal.json")
KILL_SWITCH_PATH = Path("STOP_TRADING")
OPEN_ORDER_STATUSES = {
    OrderStatus.SUBMITTING,
    OrderStatus.SUBMITTED,
    OrderStatus.FILLED_PART,
}
FUTU_CONNECTION_HINT = (
    "Check that Futu OpenD is running, logged in, listening on the configured "
    "host/port, and using the same RSA key expected by the Docker container."
)


def load_journal(path: Path = JOURNAL_PATH) -> dict[str, Any]:
    if not path.exists():
        return {"orders": []}
    return json.loads(path.read_text())


def save_journal(journal: dict[str, Any], path: Path = JOURNAL_PATH) -> None:
    path.write_text(json.dumps(_json_safe(journal), indent=2, sort_keys=True) + "\n")


def _json_safe(value: Any) -> Any:
    if isinstance(value, pd.DataFrame):
        return value.to_dict(orient="records")
    if isinstance(value, pd.Series):
        return value.to_dict()
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if hasattr(value, "item"):
        try:
            return value.item()
        except (TypeError, ValueError):
            pass
    return value


def check_kill_switch(path: Path = KILL_SWITCH_PATH) -> None:
    if path.exists():
        raise RuntimeError(f"Kill switch exists: {path}. No orders placed.")


def _to_float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def check_futu_connection(host: str, port: int, timeout: float = 5.0) -> None:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return
    except OSError as exc:
        raise RuntimeError(
            f"Cannot connect to Futu OpenD at {host}:{port}. {FUTU_CONNECTION_HINT}"
        ) from exc


def _query_account_info(
    host: str,
    port: int,
    trd_env: str,
) -> pd.Series | None:
    trade_ctx = OpenSecTradeContext(
        filter_trdmarket=TrdMarket.US,
        host=host,
        port=port,
    )
    try:
        ret, data = trade_ctx.accinfo_query(
            trd_env=trd_env,
            refresh_cache=True,
            currency=Currency.USD,
        )
        if ret != RET_OK:
            raise RuntimeError(f"Futu account info error: {data}")
        if data.empty:
            return None
        return data.iloc[0]
    except RuntimeError:
        raise
    except Exception as exc:
        raise RuntimeError(
            f"Futu account info query failed at {host}:{port}. {FUTU_CONNECTION_HINT}"
        ) from exc
    finally:
        trade_ctx.close()


def _account_summary_from_row(row: pd.Series | None) -> dict[str, float]:
    if row is None:
        return {
            "available_cash": 0,
            "cash": 0,
            "market_value": 0,
            "total_assets": 0,
        }

    cash = max(
        _to_float(row.get("cash")),
        _to_float(row.get("us_cash")),
    )
    available_cash = max(
        _to_float(row.get("available_funds")),
        cash,
        _to_float(row.get("usd_net_cash_power")),
    )
    market_value = max(
        _to_float(row.get("market_val")),
        _to_float(row.get("long_mv")),
    )
    total_assets = max(
        _to_float(row.get("total_assets")),
        cash + market_value,
        available_cash + market_value,
    )
    return {
        "available_cash": available_cash,
        "cash": cash,
        "market_value": market_value,
        "total_assets": total_assets,
    }


def get_available_cash(
    host: str,
    port: int,
    trd_env: str,
) -> float:
    row = _query_account_info(host=host, port=port, trd_env=trd_env)
    return _account_summary_from_row(row)["available_cash"]


def get_account_summary(
    host: str,
    port: int,
    trd_env: str,
) -> dict[str, float]:
    row = _query_account_info(host=host, port=port, trd_env=trd_env)
    return _account_summary_from_row(row)


def get_open_orders(
    host: str,
    port: int,
    trd_env: str,
) -> list[dict[str, Any]]:
    trade_ctx = OpenSecTradeContext(
        filter_trdmarket=TrdMarket.US,
        host=host,
        port=port,
    )
    try:
        ret, data = trade_ctx.order_list_query(
            status_filter_list=list(OPEN_ORDER_STATUSES),
            trd_env=trd_env,
            refresh_cache=True,
        )
        if ret != RET_OK:
            raise RuntimeError(f"Futu open order error: {data}")
        return data.to_dict(orient="records")
    finally:
        trade_ctx.close()


def _journal_order_ids(journal: dict[str, Any]) -> set[str]:
    order_ids: set[str] = set()
    for order in journal.get("orders", []):
        if order.get("order_id") is not None:
            order_ids.add(str(order["order_id"]))

        result = order.get("result")
        if isinstance(result, dict):
            if result.get("order_id") is not None:
                order_ids.add(str(result["order_id"]))
            nested = result.get("result")
            if isinstance(nested, list):
                for item in nested:
                    if isinstance(item, dict) and item.get("order_id") is not None:
                        order_ids.add(str(item["order_id"]))
    return order_ids


def cancel_open_orders(
    host: str,
    port: int,
    trd_env: str,
    only_journal_orders: bool = True,
) -> list[dict[str, Any]]:
    open_orders = get_open_orders(host=host, port=port, trd_env=trd_env)
    if only_journal_orders:
        journal_order_ids = _journal_order_ids(load_journal())
        open_orders = [
            order for order in open_orders if str(order.get("order_id")) in journal_order_ids
        ]
    if not open_orders:
        return []

    trade_ctx = OpenSecTradeContext(
        filter_trdmarket=TrdMarket.US,
        host=host,
        port=port,
    )
    try:
        results: list[dict[str, Any]] = []
        for order in open_orders:
            ret, data = trade_ctx.modify_order(
                modify_order_op=ModifyOrderOp.CANCEL,
                order_id=str(order["order_id"]),
                qty=float(order.get("qty") or 0),
                price=float(order.get("price") or 0),
                trd_env=trd_env,
            )
            result = {
                "action": "CANCEL",
                "code": order.get("code"),
                "order_id": order.get("order_id"),
                "original_order": order,
                "result": data,
            }
            if ret != RET_OK:
                raise RuntimeError(f"Futu cancel order error: {result}")
            results.append(result)
        return results
    finally:
        trade_ctx.close()


def _today_journal_orders(journal: dict[str, Any]) -> list[dict[str, Any]]:
    today = date.today().isoformat()
    return [
        order
        for order in journal.get("orders", [])
        if str(order.get("created_at", "")).startswith(today)
    ]


def _is_submitted_trade_order(order: dict[str, Any]) -> bool:
    if order.get("action") not in {"BUY", "SELL"}:
        return False

    result = order.get("result")
    if not isinstance(result, dict):
        return False

    nested = result.get("result")
    if isinstance(nested, list):
        return any(isinstance(item, dict) and item.get("order_id") for item in nested)

    return bool(result.get("order_id"))


def _order_ids_from_journal_entry(order: dict[str, Any]) -> set[str]:
    order_ids: set[str] = set()
    if order.get("order_id") is not None:
        order_ids.add(str(order["order_id"]))

    result = order.get("result")
    if not isinstance(result, dict):
        return order_ids

    if result.get("order_id") is not None:
        order_ids.add(str(result["order_id"]))

    nested = result.get("result")
    if isinstance(nested, list):
        for item in nested:
            if isinstance(item, dict) and item.get("order_id") is not None:
                order_ids.add(str(item["order_id"]))

    return order_ids


def _today_risk_orders(journal: dict[str, Any]) -> list[dict[str, Any]]:
    today_orders = _today_journal_orders(journal)
    cancelled_order_ids = {
        order_id
        for order in today_orders
        if order.get("action") == "CANCEL"
        for order_id in _order_ids_from_journal_entry(order)
    }

    return [
        order
        for order in today_orders
        if _is_submitted_trade_order(order)
        and not (_order_ids_from_journal_entry(order) & cancelled_order_ids)
    ]


def validate_plan(
    plan: list[TradePlanItem],
    host: str,
    port: int,
    trd_env: str,
    max_daily_orders: int,
    max_daily_notional: float,
    max_single_order_notional: float,
) -> list[TradePlanItem]:
    check_kill_switch()

    open_orders = get_open_orders(host=host, port=port, trd_env=trd_env)
    if open_orders:
        raise RuntimeError(f"Open orders exist. No new orders placed: {open_orders}")

    journal = load_journal()
    today_orders = _today_risk_orders(journal)
    if len(today_orders) >= max_daily_orders:
        raise RuntimeError("Daily order count limit reached. No orders placed.")

    used_notional = sum(float(order.get("notional") or 0) for order in today_orders)
    remaining_orders = max_daily_orders - len(today_orders)
    remaining_notional = max_daily_notional - used_notional

    if remaining_orders <= 0 or remaining_notional <= 0:
        raise RuntimeError("Daily risk limit reached. No orders placed.")

    available_cash = get_available_cash(host=host, port=port, trd_env=trd_env)
    buy_notional = 0.0
    rejected: list[dict[str, Any]] = []
    validated: list[TradePlanItem] = []

    for item in plan:
        if len(validated) >= remaining_orders:
            rejected.append(
                {
                    "code": item.code,
                    "action": item.action,
                    "reason": "remaining order count reached",
                }
            )
            break
        if item.notional > max_single_order_notional:
            rejected.append(
                {
                    "code": item.code,
                    "action": item.action,
                    "notional": item.notional,
                    "reason": "single order notional limit",
                }
            )
            continue
        if item.notional > remaining_notional:
            rejected.append(
                {
                    "code": item.code,
                    "action": item.action,
                    "notional": item.notional,
                    "reason": "remaining daily notional limit",
                }
            )
            continue
        if item.action == "BUY":
            if buy_notional + item.notional > available_cash:
                rejected.append(
                    {
                        "code": item.code,
                        "action": item.action,
                        "notional": item.notional,
                        "available_cash": available_cash,
                        "reason": "insufficient available cash",
                    }
                )
                continue
            buy_notional += item.notional
        validated.append(item)

    if not validated and rejected:
        raise RuntimeError(
            "Risk guard filtered out all orders. "
            f"available_cash={available_cash}, "
            f"remaining_orders={remaining_orders}, "
            f"remaining_notional={remaining_notional}, "
            f"rejected={rejected}"
        )

    return validated


def record_order_results(
    plan: list[TradePlanItem],
    results: list[dict[str, Any]],
    path: Path = JOURNAL_PATH,
) -> None:
    journal = load_journal(path)
    created_at = datetime.now(UTC).isoformat()
    by_code_action = {(item.code, item.action): item for item in plan}

    for result in results:
        item = by_code_action.get((str(result.get("code")), str(result.get("action"))))
        payload: dict[str, Any] = {
            "created_at": created_at,
            "result": result,
        }
        if item is not None:
            payload.update(asdict(item))
        journal.setdefault("orders", []).append(payload)

    save_journal(journal, path)


def record_cancel_results(
    results: list[dict[str, Any]],
    path: Path = JOURNAL_PATH,
) -> None:
    if not results:
        return

    journal = load_journal(path)
    created_at = datetime.now(UTC).isoformat()
    for result in results:
        journal.setdefault("orders", []).append(
            {
                "action": "CANCEL",
                "code": result.get("code"),
                "created_at": created_at,
                "order_id": result.get("order_id"),
                "result": result,
            }
        )
    save_journal(journal, path)
