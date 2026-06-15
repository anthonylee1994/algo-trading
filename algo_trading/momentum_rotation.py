from __future__ import annotations

import math
from dataclasses import dataclass

import pandas as pd

from algo_trading.futu_trader import (
    TradePlanItem,
    futu_us_code,
    normalize_us_order_price,
)


DEFAULT_SYMBOLS = [
    "MSFT",
    "GOOG",
    "AVGO",
    "TSM",
    "AMZN",
    "NVDA",
    "SMH",
    "QQQ",
    "QTUM",
    "ROBO",
    "XLV",
    "SHLD",
    "TAN",
    "IGV",
]


@dataclass(frozen=True)
class RotationSignal:
    ticker: str | None
    momentum: float
    reason: str


def calculate_momentum(history: pd.DataFrame, lookback_days: int = 126) -> float:
    if len(history) <= lookback_days:
        return math.nan
    latest_close = float(history["close"].iloc[-1])
    lookback_close = float(history["close"].iloc[-lookback_days - 1])
    if lookback_close <= 0:
        return math.nan
    return latest_close / lookback_close - 1


def select_rotation_signal(
    histories: dict[str, pd.DataFrame],
    lookback_days: int = 126,
) -> RotationSignal:
    scores = {
        ticker: calculate_momentum(history, lookback_days)
        for ticker, history in histories.items()
    }
    valid_scores = {
        ticker: score
        for ticker, score in scores.items()
        if not math.isnan(score)
    }
    if not valid_scores:
        return RotationSignal(
            ticker=None,
            momentum=math.nan,
            reason="not enough history",
        )

    ticker = max(valid_scores, key=valid_scores.get)
    momentum = valid_scores[ticker]
    if momentum <= 0:
        return RotationSignal(
            ticker=None,
            momentum=momentum,
            reason="best momentum <= 0, hold cash",
        )
    return RotationSignal(
        ticker=ticker,
        momentum=momentum,
        reason=f"best {lookback_days}D momentum",
    )


def build_rotation_plan(
    signal: RotationSignal,
    prices: dict[str, float],
    positions: dict[str, dict[str, float]],
    available_cash: float,
    symbols: list[str] | None = None,
    min_trade_notional: float = 100,
) -> list[TradePlanItem]:
    symbols = symbols or DEFAULT_SYMBOLS
    universe_codes = {futu_us_code(symbol) for symbol in symbols}
    target_code = futu_us_code(signal.ticker) if signal.ticker else None
    plan: list[TradePlanItem] = []
    cash_after_sells = available_cash

    for code, position in positions.items():
        if code not in universe_codes:
            continue
        if target_code and code == target_code:
            continue

        quantity = math.floor(float(position.get("quantity") or 0))
        price = prices.get(code, float(position.get("nominal_price") or 0))
        if quantity <= 0 or price <= 0:
            continue

        notional = quantity * price
        if notional < min_trade_notional:
            continue
        cash_after_sells += notional
        plan.append(
            TradePlanItem(
                action="SELL",
                ticker=code.removeprefix("US."),
                code=code,
                company="",
                price=normalize_us_order_price(price, "SELL"),
                quantity=quantity,
                notional=notional,
                reason=signal.reason,
            )
        )

    if target_code is None:
        return plan

    target_price = prices.get(target_code)
    if target_price is None or target_price <= 0:
        raise RuntimeError(f"Missing target price for {target_code}")

    current_quantity = math.floor(
        float(positions.get(target_code, {}).get("quantity") or 0)
    )
    current_value = current_quantity * target_price
    buy_notional = cash_after_sells - current_value
    if buy_notional < min_trade_notional:
        return plan

    limit_price = normalize_us_order_price(target_price * 1.003, "BUY")
    quantity = math.floor(buy_notional / limit_price)
    if quantity <= 0:
        return plan

    plan.append(
        TradePlanItem(
            action="BUY",
            ticker=signal.ticker,
            code=target_code,
            company="",
            price=limit_price,
            quantity=quantity,
            notional=limit_price * quantity,
            reason=f"{signal.reason}: {signal.momentum:.2%}",
        )
    )
    return plan
