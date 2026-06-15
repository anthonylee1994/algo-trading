from __future__ import annotations

import math
import unicodedata
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


@dataclass(frozen=True)
class BacktestResult:
    start: str
    end: str
    final_equity: float
    total_return_pct: float
    cagr_pct: float
    max_drawdown_pct: float
    benchmark_final_equity: float
    benchmark_total_return_pct: float
    benchmark_cagr_pct: float
    benchmark_max_drawdown_pct: float
    trade_count: int


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
    score_table = momentum_score_table(histories, lookback_days)
    valid_scores = score_table.dropna(subset=["momentum"])
    if valid_scores.empty:
        return RotationSignal(
            ticker=None,
            momentum=math.nan,
            reason="歷史數據不足",
        )

    row = valid_scores.iloc[0]
    ticker = str(row["ticker"])
    momentum = float(row["momentum"])
    if momentum <= 0:
        return RotationSignal(
            ticker=None,
            momentum=momentum,
            reason="最高 momentum <= 0，持現金",
        )
    return RotationSignal(
        ticker=ticker,
        momentum=momentum,
        reason=f"最高 {lookback_days} 日 momentum",
    )


def momentum_score_table(
    histories: dict[str, pd.DataFrame],
    lookback_days: int = 126,
    latest_prices: dict[str, float] | None = None,
) -> pd.DataFrame:
    rows: list[dict[str, float | str | int]] = []
    for ticker, history in histories.items():
        latest_close = (
            float(history["close"].iloc[-1]) if not history.empty else math.nan
        )
        latest_date = _latest_history_date(history)
        lookback_close = (
            float(history["close"].iloc[-lookback_days - 1])
            if len(history) > lookback_days
            else math.nan
        )
        momentum = calculate_momentum(history, lookback_days)
        rows.append(
            {
                "ticker": ticker,
                "latest_date": latest_date,
                "latest_close": latest_close,
                "lookback_close": lookback_close,
                "momentum": momentum,
                "history_days": len(history),
            }
        )
    table = (
        pd.DataFrame(rows)
        .sort_values(
            by=["momentum", "ticker"],
            ascending=[False, True],
            na_position="last",
        )
        .reset_index(drop=True)
    )
    if latest_prices:
        normalized_latest_prices = _normalize_latest_prices(latest_prices)
        table["raw_latest_close"] = table["ticker"].map(normalized_latest_prices)
        table["raw_latest_date"] = table["latest_date"]
    return table


def format_momentum_score_table(score_table: pd.DataFrame) -> str:
    table = score_table.copy()
    table["latest_close"] = table["latest_close"].map(_format_price)
    table["lookback_close"] = table["lookback_close"].map(_format_price)
    if "raw_latest_close" in table.columns:
        table["raw_latest_close"] = table["raw_latest_close"].map(_format_price)
    table["momentum"] = table["momentum"].map(_format_percent)
    if "raw_latest_close" in table.columns:
        table = table.loc[
            :,
            [
                "ticker",
                "raw_latest_date",
                "raw_latest_close",
                "latest_close",
                "lookback_close",
                "momentum",
                "history_days",
            ],
        ].rename(
            columns={
                "ticker": "代號",
                "raw_latest_date": "最新日期",
                "raw_latest_close": "最新收市價",
                "latest_close": "最新調整收市價",
                "lookback_close": "回望調整收市價",
                "momentum": "momentum",
                "history_days": "歷史日數",
            }
        )
    else:
        table = table.rename(
            columns={
                "ticker": "代號",
                "latest_date": "最新日期",
                "latest_close": "最新調整收市價",
                "lookback_close": "回望調整收市價",
                "momentum": "momentum",
                "history_days": "歷史日數",
            }
        )
    return format_bordered_table(table)


def format_bordered_table(table: pd.DataFrame) -> str:
    string_table = table.map(_format_table_cell)
    headers = [str(column) for column in string_table.columns]
    rows = string_table.values.tolist()
    widths = [
        max(_display_width(value) for value in [header, *[row[index] for row in rows]])
        for index, header in enumerate(headers)
    ]
    border = "+" + "+".join("-" * (width + 2) for width in widths) + "+"
    header_row = _format_bordered_row(headers, widths)
    body_rows = [_format_bordered_row(row, widths) for row in rows]
    return "\n".join([border, header_row, border, *body_rows, border])


def _format_bordered_row(values: list[str], widths: list[int]) -> str:
    cells = [
        f" {_pad_table_cell(value, width)} " for value, width in zip(values, widths)
    ]
    return "|" + "|".join(cells) + "|"


def _format_table_cell(value: object) -> str:
    if pd.isna(value):
        return ""
    return str(value)


def _pad_table_cell(value: str, width: int) -> str:
    return value + " " * (width - _display_width(value))


def _display_width(value: str) -> int:
    width = 0
    for char in value:
        width += 2 if unicodedata.east_asian_width(char) in {"F", "W"} else 1
    return width


def _latest_history_date(history: pd.DataFrame) -> str:
    if history.empty:
        return ""
    for column in ["time_key", "date", "datetime"]:
        if column in history.columns:
            value = history[column].iloc[-1]
            return _format_history_date(value)
    return _format_history_date(history.index[-1])


def _normalize_latest_prices(latest_prices: dict[str, float]) -> dict[str, float]:
    return {str(key).removeprefix("US."): value for key, value in latest_prices.items()}


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
        raise RuntimeError(f"{target_code} 缺少目標價格")

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


def latest_momentum_score_table(
    close_prices: pd.DataFrame,
    lookback_days: int = 126,
    latest_close_prices: pd.DataFrame | None = None,
) -> pd.DataFrame:
    histories = {
        symbol: pd.DataFrame({"close": close_prices[symbol].dropna()})
        for symbol in close_prices.columns
    }
    table = momentum_score_table(histories=histories, lookback_days=lookback_days)
    if latest_close_prices is None:
        return table

    latest_raw = {}
    latest_dates = {}
    for symbol in latest_close_prices.columns:
        series = latest_close_prices[symbol].dropna()
        if series.empty:
            continue
        latest_raw[symbol] = float(series.iloc[-1])
        latest_dates[symbol] = _format_history_date(series.index[-1])

    table["raw_latest_close"] = table["ticker"].map(latest_raw)
    table["raw_latest_date"] = table["ticker"].map(latest_dates)
    return table


def backtest_rotation(
    close_prices: pd.DataFrame,
    benchmark_symbol: str = "QQQ",
    lookback_days: int = 126,
    initial_cash: float = 100_000,
) -> tuple[BacktestResult, pd.DataFrame]:
    if benchmark_symbol not in close_prices.columns:
        raise RuntimeError(f"缺少 benchmark 欄位：{benchmark_symbol}")

    benchmark_prices = close_prices[benchmark_symbol].dropna()
    close_prices = close_prices.reindex(benchmark_prices.index)
    returns = close_prices.pct_change()
    momentum = close_prices.pct_change(lookback_days)
    equity = initial_cash
    peak = initial_cash
    max_drawdown = 0.0
    previous_selection: str | None = None
    trade_count = 0
    rows: list[dict[str, float | str]] = []

    for index in range(1, len(close_prices)):
        date = close_prices.index[index]
        signal_index = index - 1
        ranking = momentum.iloc[signal_index].dropna().sort_values(ascending=False)
        selected = None
        selected_momentum = math.nan
        if not ranking.empty and float(ranking.iloc[0]) > 0:
            selected = str(ranking.index[0])
            selected_momentum = float(ranking.iloc[0])

        previous_selected = previous_selection
        selected_price = (
            float(close_prices.iloc[index][selected])
            if selected is not None and not math.isnan(float(close_prices.iloc[index][selected]))
            else math.nan
        )
        previous_price = (
            float(close_prices.iloc[index][previous_selected])
            if previous_selected is not None
            and previous_selected in close_prices.columns
            and not math.isnan(float(close_prices.iloc[index][previous_selected]))
            else math.nan
        )

        day_return = 0.0
        if selected is not None:
            selected_return = returns.iloc[index][selected]
            if not math.isnan(float(selected_return)):
                day_return = float(selected_return)

        if selected != previous_selection:
            trade_count += 1
        previous_selection = selected
        equity *= 1 + day_return
        peak = max(peak, equity)
        drawdown = equity / peak - 1
        max_drawdown = min(max_drawdown, drawdown)
        rows.append(
            {
                "date": date.isoformat(),
                "signal_date": close_prices.index[signal_index].isoformat(),
                "selected": selected or "CASH",
                "momentum": selected_momentum,
                "buy_price": selected_price,
                "sell_price": previous_price,
                "equity": equity,
                "drawdown": drawdown,
                "day_return": day_return,
            }
        )

    curve = pd.DataFrame(rows)
    benchmark_curve = _benchmark_curve(
        benchmark_prices=benchmark_prices.iloc[1:],
        initial_cash=initial_cash,
    )
    years = len(curve) / 252
    benchmark_final_equity = float(benchmark_curve.iloc[-1]["equity"])
    result = BacktestResult(
        start=str(curve.iloc[0]["date"]),
        end=str(curve.iloc[-1]["date"]),
        final_equity=float(curve.iloc[-1]["equity"]),
        total_return_pct=(float(curve.iloc[-1]["equity"]) / initial_cash - 1) * 100,
        cagr_pct=(float(curve.iloc[-1]["equity"]) / initial_cash) ** (1 / years) * 100
        - 100,
        max_drawdown_pct=max_drawdown * 100,
        benchmark_final_equity=benchmark_final_equity,
        benchmark_total_return_pct=(benchmark_final_equity / initial_cash - 1) * 100,
        benchmark_cagr_pct=(benchmark_final_equity / initial_cash) ** (1 / years) * 100
        - 100,
        benchmark_max_drawdown_pct=float(benchmark_curve["drawdown"].min()) * 100,
        trade_count=trade_count,
    )
    return result, curve


def _benchmark_curve(benchmark_prices: pd.Series, initial_cash: float) -> pd.DataFrame:
    first_price = float(benchmark_prices.iloc[0])
    peak = initial_cash
    rows: list[dict[str, float | str]] = []
    for date, price in benchmark_prices.items():
        equity = initial_cash * float(price) / first_price
        peak = max(peak, equity)
        rows.append(
            {
                "date": date.isoformat() if hasattr(date, "isoformat") else str(date),
                "equity": equity,
                "drawdown": equity / peak - 1,
            }
        )
    return pd.DataFrame(rows)


def _format_price(value: float) -> str:
    if math.isnan(float(value)):
        return "n/a"
    return f"{float(value):.2f}"


def _format_percent(value: float) -> str:
    if math.isnan(float(value)):
        return "n/a"
    return f"{float(value) * 100:.2f}%"


def _format_history_date(value: object) -> str:
    return value.isoformat() if hasattr(value, "isoformat") else str(value)
