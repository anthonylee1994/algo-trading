"""非 Futu 價格來源（yfinance）。

動量信號只需要日線收市價，唔使靠 Futu —— Futu 嘅歷史 K 線有 60 次/30 秒頻率
限制同每月可拉股票數配額，抽成個 S&P 500（500+ 隻）一定撞爆。yfinance 批量抽冇
呢啲限制，所以用佢計信號；Futu 淨係留返查帳戶/持倉 + 落單。

回傳格式刻意同 `futu_trader.get_price_history` / `get_latest_prices` 一致：
- histories: dict[「US.XXX」 -> DataFrame(含 'close' column, DatetimeIndex)]
- prices:    dict[「US.XXX」 -> float（最新收市價）]
"""

from __future__ import annotations

from datetime import date, timedelta

import pandas as pd


def _yf_symbol(ticker: str) -> str:
    """yfinance 用 dash 表示 class share（BRK.B -> BRK-B）。"""
    return ticker.replace(".", "-")


def _history_start_date(max_count: int) -> str:
    days = max(3 * max_count, 365)
    return (date.today() - timedelta(days=days)).isoformat()


def _download_closes(symbols: list[str], start: str) -> pd.DataFrame:
    import yfinance as yf

    query = [_yf_symbol(s) for s in symbols]
    raw = yf.download(
        tickers=query,
        start=start,
        end=(date.today() + timedelta(days=1)).isoformat(),
        auto_adjust=True,
        progress=False,
        group_by="ticker",
        threads=True,
    )
    if raw.empty:
        return pd.DataFrame()

    closes: dict[str, pd.Series] = {}
    for original in symbols:
        yf_sym = _yf_symbol(original)
        try:
            if isinstance(raw.columns, pd.MultiIndex):
                series = raw[yf_sym]["Close"]
            else:  # 單一 ticker 時 yfinance 唔會分層
                series = raw["Close"]
        except KeyError:
            continue
        series = series.dropna()
        if not series.empty:
            closes[original] = series.astype(float)

    if not closes:
        return pd.DataFrame()
    return pd.DataFrame(closes)


def get_price_history_yf(
    codes: list[str],
    max_count: int = 260,
) -> dict[str, pd.DataFrame]:
    """同 futu_trader.get_price_history 同樣 signature / 回傳，但用 yfinance。"""
    symbols = [code.removeprefix("US.") for code in codes]
    start = _history_start_date(max_count)
    frame = _download_closes(symbols, start)

    histories: dict[str, pd.DataFrame] = {}
    for symbol in symbols:
        code = f"US.{symbol}"
        if symbol not in frame.columns:
            histories[code] = pd.DataFrame()
            continue
        series = frame[symbol].dropna().tail(max_count)
        histories[code] = pd.DataFrame({"close": series.values}, index=series.index)
    return histories


def get_latest_prices_yf(codes: list[str]) -> dict[str, float]:
    """最新收市價（yfinance）。key 用 Futu code 格式以便落單時對得返。"""
    histories = get_price_history_yf(codes, max_count=5)
    prices: dict[str, float] = {}
    for code, history in histories.items():
        if not history.empty:
            prices[code] = float(history["close"].iloc[-1])
    return prices
