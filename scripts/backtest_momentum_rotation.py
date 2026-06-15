from __future__ import annotations

import argparse
from datetime import UTC, datetime
import json
from pathlib import Path
import sys
import urllib.parse
import urllib.request

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from algo_trading.momentum_rotation import (
    DEFAULT_SYMBOLS,
    backtest_rotation,
    format_momentum_score_table,
    latest_momentum_score_table,
)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbols", nargs="+", default=DEFAULT_SYMBOLS)
    parser.add_argument("--benchmark", default="QQQ")
    parser.add_argument("--start", default="2010-01-01")
    parser.add_argument("--end", default=None)
    parser.add_argument("--lookback-days", type=int, default=126)
    parser.add_argument("--initial-cash", type=float, default=100_000)
    args = parser.parse_args()

    symbols = list(dict.fromkeys([*args.symbols, args.benchmark]))
    close_prices = pd.concat(
        [
            fetch_yahoo_history(symbol, args.start, args.end).rename(symbol)
            for symbol in symbols
        ],
        axis=1,
        join="outer",
    ).sort_index()
    result, curve = backtest_rotation(
        close_prices=close_prices,
        benchmark_symbol=args.benchmark,
        lookback_days=args.lookback_days,
        initial_cash=args.initial_cash,
    )

    print(f"Momentum rotation backtest ({result.start} to {result.end})")
    print(f"Universe: {', '.join(args.symbols)}")
    print(f"Final equity: ${result.final_equity:,.2f}")
    print(f"Total return: {result.total_return_pct:.2f}%")
    print(f"CAGR: {result.cagr_pct:.2f}%")
    print(f"Max drawdown: {result.max_drawdown_pct:.2f}%")
    print(f"Signal changes: {result.trade_count}")
    print()
    print(f"Buy-and-hold {args.benchmark}: ${result.benchmark_final_equity:,.2f}")
    print(f"Buy-and-hold return: {result.benchmark_total_return_pct:.2f}%")
    print(f"Buy-and-hold CAGR: {result.benchmark_cagr_pct:.2f}%")
    print(f"Buy-and-hold max drawdown: {result.benchmark_max_drawdown_pct:.2f}%")
    print()
    print("Latest momentum scores:")
    print(
        format_momentum_score_table(
            latest_momentum_score_table(close_prices, args.lookback_days)
        )
    )
    print()
    print("Last 10 signals:")
    print(curve.tail(10).loc[:, ["date", "selected", "momentum", "equity", "drawdown"]].to_string(index=False))


def fetch_yahoo_history(symbol: str, start: str, end: str | None) -> pd.Series:
    period1 = _timestamp(start)
    period2 = _timestamp(end) if end else int(datetime.now(tz=UTC).timestamp())
    query = urllib.parse.urlencode(
        {
            "period1": period1,
            "period2": period2,
            "interval": "1d",
            "events": "history",
            "includeAdjustedClose": "true",
        }
    )
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?{query}"
    request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(request, timeout=30) as response:
        payload = json.load(response)

    chart = payload.get("chart", {})
    if chart.get("error"):
        raise RuntimeError(f"Yahoo chart error for {symbol}: {chart['error']}")

    result = chart["result"][0]
    timestamps = result["timestamp"]
    quote = result["indicators"]["quote"][0]
    adjclose = result["indicators"].get("adjclose", [{}])[0].get("adjclose", [])
    closes = adjclose or quote["close"]
    dates = [datetime.fromtimestamp(ts, tz=UTC).date() for ts in timestamps]
    return pd.Series(closes, index=dates).dropna()


def _timestamp(value: str | None) -> int:
    if value is None:
        return int(datetime.now(tz=UTC).timestamp())
    return int(datetime.fromisoformat(value).replace(tzinfo=UTC).timestamp())


if __name__ == "__main__":
    main()
