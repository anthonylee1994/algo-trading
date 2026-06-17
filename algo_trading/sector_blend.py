"""Static sector-tilt blend strategy (QQQ + SMH by default).

Wraps FINDINGS §11[D]: QQQ/SMH 50/50 monthly rebalance, 5pp threshold band,
no leverage. Equal-weight two-ETF blend that raises effective semis exposure
to ~60% (QQQ is ~20% semis itself) while keeping QQQ as a diversification
backstop in semis-weak periods (2010-14 it lost 3.6pp to QQQ; the QQQ half
cushions the drawdown so the blend still beat QQQ +1.0pp that sub-period).

Public surface:
    BlendTarget              — frozen dataclass per leg
    select_blend_targets()   — static list of legs (e.g. QQQ, SMH)
    build_blend_rebal_plan() — TradePlanItem list with 5pp no-trade band
    format_blend_status()    — human-readable current vs target weight table

Honest caveats (from FINDINGS §11):
    - The 50/50 split is the validated sweet spot; do not dynamic-tune.
    - SMH + MA200 trend filter WORSE (whipsaw drag) — don't add it.
    - Edge comes from 2020+ AI/semis super-cycle; 2010-14 only beat by 1pp.
    - MaxDD -40% vs QQQ -35% (5pp deeper) — psychological cost to budget for.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

import pandas as pd

from algo_trading.futu_trader import (
    TradePlanItem,
    futu_us_code,
    normalize_us_order_price,
)


DEFAULT_BLEND_SYMBOLS = ["QQQ", "SMH"]


@dataclass(frozen=True)
class BlendTarget:
    ticker: str
    target_weight: float
    reason: str


def select_blend_targets(
    symbols: list[str] | None = None,
) -> list[BlendTarget]:
    """Static equal-weight blend across `symbols` (default QQQ + SMH, 1/N each)."""
    symbols = list(dict.fromkeys(symbols or DEFAULT_BLEND_SYMBOLS))
    if not symbols:
        return []
    per_weight = 1.0 / len(symbols)
    return [
        BlendTarget(
            ticker=symbol,
            target_weight=per_weight,
            reason=f"static blend target {per_weight:.0%}",
        )
        for symbol in symbols
    ]


def _current_position_values(
    positions: dict[str, dict[str, float]],
    prices: dict[str, float],
    target_codes: set[str],
) -> dict[str, float]:
    values: dict[str, float] = {}
    for code, position in positions.items():
        if code not in target_codes:
            continue
        quantity = math.floor(float(position.get("quantity") or 0))
        price = float(prices.get(code, position.get("nominal_price") or 0))
        if quantity > 0 and price > 0:
            values[code] = quantity * price
    return values


def build_blend_rebal_plan(
    targets: list[BlendTarget],
    prices: dict[str, float],
    positions: dict[str, dict[str, float]],
    account: dict[str, float],
    rebal_band: float = 0.05,
    min_trade_notional: float = 100,
) -> list[TradePlanItem]:
    """Build a rebalance plan with a threshold no-trade band.

    Returns an empty list if every leg is within `rebal_band` of its target
    weight. Otherwise emits SELLs for overweight legs (using close price) and
    BUYs for underweight legs (limit at close * 1.003) — matches the buffer
    style of build_equal_weight_rotation_plan. Non-target positions (e.g.
    leftover from a previous strategy) are ignored.

    Cash is tracked across BUY orders; if available cash runs out before the
    full underweight is filled, partial fills are emitted and the next
    rebalance will continue.
    """
    if not targets:
        return []

    total_assets = float(account.get("total_assets") or 0.0)
    available_cash = float(account.get("available_cash") or 0.0)
    if total_assets <= 0:
        return []

    target_weight_by_code = {
        futu_us_code(t.ticker): t.target_weight for t in targets
    }
    target_codes = set(target_weight_by_code)
    reason_by_code = {futu_us_code(t.ticker): t.reason for t in targets}

    current_values = _current_position_values(positions, prices, target_codes)
    current_weights = {code: v / total_assets for code, v in current_values.items()}

    needs_rebal = any(
        abs(current_weights.get(code, 0.0) - w) > rebal_band
        for code, w in target_weight_by_code.items()
    )
    if not needs_rebal:
        return []

    plan: list[TradePlanItem] = []

    # SELLs first — release cash before sizing BUYs.
    for code, position in positions.items():
        if code not in target_codes:
            continue
        target_w = target_weight_by_code[code]
        actual_w = current_weights.get(code, 0.0)
        if actual_w <= target_w + rebal_band:
            continue  # not overweight
        target_value = target_w * total_assets
        current_value = current_values[code]
        excess_value = current_value - target_value
        if excess_value < min_trade_notional:
            continue
        price = float(prices.get(code, position.get("nominal_price") or 0))
        if price <= 0:
            continue
        sell_quantity = min(
            math.floor(float(position.get("quantity") or 0)),
            math.floor(excess_value / price),
        )
        if sell_quantity <= 0:
            continue
        sell_price = normalize_us_order_price(price, "SELL")
        plan.append(
            TradePlanItem(
                action="SELL",
                ticker=code.removeprefix("US."),
                code=code,
                company="",
                price=sell_price,
                quantity=sell_quantity,
                notional=sell_price * sell_quantity,
                reason=(
                    f"blend rebal {actual_w:.1%}→{target_w:.0%} "
                    f"({reason_by_code[code]})"
                ),
            )
        )

    # BUYs — size against initial cash + SELL proceeds that will land first.
    sell_proceeds = sum(item.notional for item in plan)
    effective_cash = available_cash + sell_proceeds
    planned_buy_notional = 0.0
    for code in target_codes:
        target_w = target_weight_by_code[code]
        actual_w = current_weights.get(code, 0.0)
        if actual_w >= target_w - rebal_band:
            continue
        target_value = target_w * total_assets
        current_value = current_values.get(code, 0.0)
        underweight = target_value - current_value
        if underweight < min_trade_notional:
            continue
        price = prices.get(code)
        if price is None or price <= 0:
            continue
        buy_price = normalize_us_order_price(price * 1.003, "BUY")
        full_quantity = math.floor(underweight / buy_price)
        if full_quantity <= 0:
            continue
        full_notional = buy_price * full_quantity
        if planned_buy_notional + full_notional > effective_cash:
            remaining_cash = max(0.0, effective_cash - planned_buy_notional)
            full_quantity = math.floor(remaining_cash / buy_price)
            full_notional = buy_price * full_quantity
        if full_quantity <= 0 or full_notional < min_trade_notional:
            continue
        planned_buy_notional += full_notional
        plan.append(
            TradePlanItem(
                action="BUY",
                ticker=code.removeprefix("US."),
                code=code,
                company="",
                price=buy_price,
                quantity=full_quantity,
                notional=full_notional,
                reason=(
                    f"blend rebal {actual_w:.1%}→{target_w:.0%} "
                    f"({reason_by_code[code]})"
                ),
            )
        )
    return plan


def format_blend_status(
    targets: list[BlendTarget],
    prices: dict[str, float],
    positions: dict[str, dict[str, float]],
    account: dict[str, float],
    rebal_band: float = 0.05,
) -> str:
    """One-line-per-leg summary of current vs target weight.

    Returns a markdown-ish table string suitable for printing pre/post trade.
    """
    total_assets = float(account.get("total_assets") or 0.0)
    available_cash = float(account.get("available_cash") or 0.0)
    target_weight_by_code = {
        futu_us_code(t.ticker): t.target_weight for t in targets
    }
    target_codes = set(target_weight_by_code)
    current_values = _current_position_values(positions, prices, target_codes)

    rows: list[dict[str, str]] = []
    for code in sorted(target_codes):
        ticker = code.removeprefix("US.")
        target_w = target_weight_by_code[code]
        position = positions.get(code) or {}
        quantity = math.floor(float(position.get("quantity") or 0))
        price = float(prices.get(code, position.get("nominal_price") or 0))
        value = current_values.get(code, 0.0)
        actual_w = value / total_assets if total_assets > 0 else 0.0
        deviation = abs(actual_w - target_w)
        flag = "REBAL" if deviation > rebal_band else "ok"
        rows.append(
            {
                "代號": ticker,
                "現價": f"{price:.2f}" if price > 0 else "n/a",
                "持倉": f"{quantity:d}",
                "市值": f"{value:,.2f}",
                "目標": f"{target_w:.0%}",
                "實際": f"{actual_w:.1%}",
                "差距": f"{actual_w - target_w:+.1%}",
                "狀態": flag,
            }
        )
    cash_row = {
        "代號": "CASH",
        "現價": "",
        "持倉": "",
        "市值": f"{available_cash:,.2f}",
        "目標": "",
        "實際": f"{available_cash / total_assets:.1%}" if total_assets > 0 else "n/a",
        "差距": "",
        "狀態": "",
    }
    rows.append(cash_row)
    df = pd.DataFrame(rows)
    return df.to_string(index=False)
