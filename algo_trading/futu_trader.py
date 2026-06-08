from __future__ import annotations

import math
from dataclasses import dataclass
from decimal import Decimal, ROUND_CEILING, ROUND_FLOOR

import pandas as pd
from futu import (
    AuType,
    KLType,
    OpenQuoteContext,
    OpenSecTradeContext,
    OrderType,
    RET_OK,
    TrdEnv,
    TrdMarket,
    TrdSide,
)


@dataclass(frozen=True)
class TradePlanItem:
    action: str
    ticker: str
    code: str
    company: str
    price: float
    quantity: int
    notional: float
    reason: str


@dataclass(frozen=True)
class StrategyInputs:
    candidate_codes: list[str]
    positions: dict[str, dict[str, float]]
    histories: dict[str, pd.DataFrame]
    prices: dict[str, float]
    spy_history: pd.DataFrame
    available_cash: float
    target_position_value: float
    rebalance_value: float


def futu_us_code(ticker: str) -> str:
    return f"US.{ticker}"


def normalize_us_order_price(price: float, action: str) -> float:
    rounding = ROUND_CEILING if action == "BUY" else ROUND_FLOOR
    return float(Decimal(str(price)).quantize(Decimal("0.01"), rounding=rounding))


def get_top_candidates(candidates: pd.DataFrame, limit: int) -> pd.DataFrame:
    if candidates.empty:
        return candidates
    return candidates.head(limit).reset_index(drop=True)


def _get_latest_prices(host: str, port: int, codes: list[str]) -> dict[str, float]:
    quote_ctx = OpenQuoteContext(host=host, port=port)
    try:
        ret, data = quote_ctx.get_market_snapshot(codes)
        if ret != RET_OK:
            raise RuntimeError(f"Futu quote error: {data}")

        prices: dict[str, float] = {}
        for row in data.to_dict(orient="records"):
            price = float(row.get("last_price") or 0)
            if price > 0:
                prices[str(row["code"])] = price
        return prices
    finally:
        quote_ctx.close()


def get_price_history(
    host: str,
    port: int,
    codes: list[str],
    max_count: int = 260,
) -> dict[str, pd.DataFrame]:
    quote_ctx = OpenQuoteContext(host=host, port=port)
    try:
        histories: dict[str, pd.DataFrame] = {}
        for code in codes:
            ret, data, _ = quote_ctx.request_history_kline(
                code,
                ktype=KLType.K_DAY,
                autype=AuType.QFQ,
                max_count=max_count,
            )
            if ret != RET_OK:
                raise RuntimeError(f"Futu history error for {code}: {data}")
            histories[code] = data
        return histories
    finally:
        quote_ctx.close()


def get_positions(
    host: str,
    port: int,
    trd_env: str = TrdEnv.SIMULATE,
) -> dict[str, dict[str, float]]:
    trade_ctx = OpenSecTradeContext(
        filter_trdmarket=TrdMarket.US,
        host=host,
        port=port,
    )
    try:
        ret, data = trade_ctx.position_list_query(
            trd_env=trd_env,
            refresh_cache=True,
        )
        if ret != RET_OK:
            raise RuntimeError(f"Futu position error: {data}")

        positions: dict[str, dict[str, float]] = {}
        for row in data.to_dict(orient="records"):
            qty = float(row.get("qty") or 0)
            if qty <= 0:
                continue
            positions[str(row["code"])] = {
                "quantity": qty,
                "cost_price": float(row.get("cost_price") or 0),
                "nominal_price": float(row.get("nominal_price") or 0),
            }
        return positions
    finally:
        trade_ctx.close()


def _sma(history: pd.DataFrame, window: int) -> float:
    if len(history) < window:
        return math.nan
    return float(history["close"].tail(window).mean())


def _highest_close(history: pd.DataFrame, window: int) -> float:
    if history.empty:
        return math.nan
    return float(history["close"].tail(window).max())


def _buy_signal(history: pd.DataFrame, spy_history: pd.DataFrame) -> tuple[bool, str]:
    if len(history) < 200 or len(spy_history) < 200:
        return False, "not enough history"

    close = float(history["close"].iloc[-1])
    sma50 = _sma(history, 50)
    sma200 = _sma(history, 200)
    spy_close = float(spy_history["close"].iloc[-1])
    spy_sma200 = _sma(spy_history, 200)
    high_252 = _highest_close(history, 252)

    if spy_close <= spy_sma200:
        return False, "SPY below 200D SMA"
    if close <= sma50:
        return False, "close below 50D SMA"
    if sma50 <= sma200:
        return False, "50D SMA below 200D SMA"
    if close < high_252 * 0.85:
        return False, "more than 15% below 52W high"
    return True, "trend entry"


def _sell_signal(history: pd.DataFrame, position: dict[str, float]) -> tuple[bool, str]:
    if len(history) < 50:
        return False, "not enough history"

    close = float(history["close"].iloc[-1])
    cost_price = float(position.get("cost_price") or 0)
    sma50 = _sma(history, 50)

    if cost_price > 0 and close <= cost_price * 0.92:
        return True, "hard stop -8%"
    if close <= sma50:
        return True, "close below 50D SMA"
    return False, "hold"


def build_equal_weight_buy_plan(
    candidates: pd.DataFrame,
    total_cash: float,
    host: str = "127.0.0.1",
    port: int = 11111,
) -> list[TradePlanItem]:
    if candidates.empty:
        return []

    codes = [futu_us_code(str(ticker)) for ticker in candidates["Ticker"].tolist()]
    prices = _get_latest_prices(host=host, port=port, codes=codes)
    cash_per_stock = total_cash / len(candidates)

    plan: list[TradePlanItem] = []
    for row in candidates.to_dict(orient="records"):
        ticker = str(row["Ticker"])
        code = futu_us_code(ticker)
        price = prices.get(code)
        if price is None:
            continue

        quantity = math.floor(cash_per_stock / price)
        if quantity <= 0:
            continue

        plan.append(
            TradePlanItem(
                action="BUY",
                ticker=ticker,
                code=code,
                company=str(row.get("Company", "")),
                price=price,
                quantity=quantity,
                notional=price * quantity,
                reason="equal weight buy",
            )
        )
    return plan


def _prepare_strategy_inputs(
    candidates: pd.DataFrame,
    total_cash: float,
    host: str,
    port: int,
    trd_env: str,
    account_summary: dict[str, float] | None,
    target_weight: float | None,
    max_position_weight: float,
    max_gross_exposure: float,
    rebalance_threshold: float,
) -> StrategyInputs:
    candidate_codes = [
        futu_us_code(str(ticker)) for ticker in candidates["Ticker"].tolist()
    ]
    positions = get_positions(host=host, port=port, trd_env=trd_env)
    position_codes = list(positions)
    codes = sorted(set(candidate_codes + position_codes + ["US.SPY"]))
    histories = get_price_history(host=host, port=port, codes=codes)
    prices = _get_latest_prices(host=host, port=port, codes=codes)

    summary = account_summary or {}
    total_assets = float(summary.get("total_assets") or total_cash)
    available_cash = float(summary.get("available_cash") or total_cash)
    portfolio_target_value = min(total_cash, total_assets * max_gross_exposure)
    effective_target_weight = target_weight or (1 / len(candidates))
    effective_target_weight = min(effective_target_weight, max_position_weight)

    return StrategyInputs(
        candidate_codes=candidate_codes,
        positions=positions,
        histories=histories,
        prices=prices,
        spy_history=histories["US.SPY"],
        available_cash=available_cash,
        target_position_value=portfolio_target_value * effective_target_weight,
        rebalance_value=total_assets * rebalance_threshold,
    )


def _price_for_code(
    code: str,
    history: pd.DataFrame,
    prices: dict[str, float],
) -> float:
    return prices.get(code, float(history["close"].iloc[-1]))


def _build_sell_plan(
    inputs: StrategyInputs,
    sell_non_universe: bool,
) -> list[TradePlanItem]:
    plan: list[TradePlanItem] = []

    for code, position in inputs.positions.items():
        history = inputs.histories.get(code)
        if history is None:
            continue

        ticker = code.removeprefix("US.")
        price = _price_for_code(code, history, inputs.prices)
        quantity = math.floor(float(position["quantity"]))
        if quantity <= 0:
            continue

        in_universe = code in inputs.candidate_codes
        position_value = price * quantity
        should_sell, reason = _sell_signal(history, position)
        if sell_non_universe and not in_universe:
            should_sell = True
            reason = "not in filtered universe"
        elif not in_universe:
            continue
        elif not should_sell:
            excess_value = position_value - inputs.target_position_value
            if excess_value < inputs.rebalance_value:
                continue
            sell_quantity = math.floor(excess_value / price)
            if sell_quantity <= 0:
                continue
            quantity = min(quantity, sell_quantity)
            reason = "rebalance overweight"

        plan.append(
            TradePlanItem(
                action="SELL",
                ticker=ticker,
                code=code,
                company="",
                price=price,
                quantity=quantity,
                notional=price * quantity,
                reason=reason,
            )
        )

    return plan


def _build_buy_plan(
    candidates: pd.DataFrame,
    inputs: StrategyInputs,
) -> list[TradePlanItem]:
    plan: list[TradePlanItem] = []
    planned_buy_notional = 0.0

    for row in candidates.to_dict(orient="records"):
        ticker = str(row["Ticker"])
        code = futu_us_code(ticker)
        history = inputs.histories.get(code)
        if history is None:
            continue

        should_buy, reason = _buy_signal(history, inputs.spy_history)
        if not should_buy:
            continue

        price = _price_for_code(code, history, inputs.prices)
        limit_price = normalize_us_order_price(price * 1.003, "BUY")
        current_quantity = float(inputs.positions.get(code, {}).get("quantity") or 0)
        current_value = current_quantity * price
        underweight_value = inputs.target_position_value - current_value
        if underweight_value < inputs.rebalance_value:
            continue

        buy_value = min(underweight_value, inputs.available_cash - planned_buy_notional)
        if buy_value <= 0:
            continue

        quantity = math.floor(buy_value / limit_price)
        if quantity <= 0:
            continue

        planned_buy_notional += limit_price * quantity
        plan.append(
            TradePlanItem(
                action="BUY",
                ticker=ticker,
                code=code,
                company=str(row.get("Company", "")),
                price=limit_price,
                quantity=quantity,
                notional=limit_price * quantity,
                reason=reason if current_quantity <= 0 else "rebalance underweight",
            )
        )

    return plan


def build_strategy_plan(
    candidates: pd.DataFrame,
    total_cash: float,
    host: str = "127.0.0.1",
    port: int = 11111,
    trd_env: str = TrdEnv.SIMULATE,
    account_summary: dict[str, float] | None = None,
    target_weight: float | None = None,
    rebalance_threshold: float = 0.03,
    max_position_weight: float = 0.12,
    max_gross_exposure: float = 0.8,
    sell_non_universe: bool = False,
) -> list[TradePlanItem]:
    if candidates.empty:
        return []

    inputs = _prepare_strategy_inputs(
        candidates=candidates,
        total_cash=total_cash,
        host=host,
        port=port,
        trd_env=trd_env,
        account_summary=account_summary,
        target_weight=target_weight,
        max_position_weight=max_position_weight,
        max_gross_exposure=max_gross_exposure,
        rebalance_threshold=rebalance_threshold,
    )
    return [
        *_build_sell_plan(inputs=inputs, sell_non_universe=sell_non_universe),
        *_build_buy_plan(candidates=candidates, inputs=inputs),
    ]


def place_orders(
    plan: list[TradePlanItem],
    host: str = "127.0.0.1",
    port: int = 11111,
    trd_env: str = TrdEnv.SIMULATE,
    password: str | None = None,
    password_md5: str | None = None,
    order_type: str = OrderType.NORMAL,
) -> list[dict[str, object]]:
    if not plan:
        return []

    trade_ctx = OpenSecTradeContext(
        filter_trdmarket=TrdMarket.US,
        host=host,
        port=port,
    )
    try:
        if trd_env == TrdEnv.REAL:
            ret, data = trade_ctx.unlock_trade(
                password=password,
                password_md5=password_md5,
            )
            if ret != RET_OK:
                raise RuntimeError(f"Futu unlock trade error: {data}")

        results: list[dict[str, object]] = []
        for item in plan:
            price = (
                0
                if order_type == OrderType.MARKET
                else normalize_us_order_price(item.price, item.action)
            )
            ret, data = trade_ctx.place_order(
                price=price,
                qty=item.quantity,
                code=item.code,
                trd_side=TrdSide.BUY if item.action == "BUY" else TrdSide.SELL,
                order_type=order_type,
                trd_env=trd_env,
            )
            if ret != RET_OK:
                raise RuntimeError(f"Futu place order error for {item.code}: {data}")

            results.append(
                {
                    "action": item.action,
                    "code": item.code,
                    "quantity": item.quantity,
                    "price": price,
                    "reason": item.reason,
                    "result": data,
                }
            )
        return results
    finally:
        trade_ctx.close()


def place_buy_orders(
    plan: list[TradePlanItem],
    host: str = "127.0.0.1",
    port: int = 11111,
    trd_env: str = TrdEnv.SIMULATE,
    password: str | None = None,
    password_md5: str | None = None,
    order_type: str = OrderType.MARKET,
) -> list[dict[str, object]]:
    return place_orders(
        plan=plan,
        host=host,
        port=port,
        trd_env=trd_env,
        password=password,
        password_md5=password_md5,
        order_type=order_type,
    )
