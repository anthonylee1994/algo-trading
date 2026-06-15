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
    format_bordered_table,
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
    parser.add_argument(
        "--output-csv",
        default="backtest_trades.csv",
        help="交易紀錄 CSV output path；用空字串可跳過輸出。",
    )
    args = parser.parse_args()

    symbols = list(dict.fromkeys([*args.symbols, args.benchmark]))
    charts = {
        symbol: fetch_yahoo_chart(symbol, args.start, args.end)
        for symbol in symbols
    }
    close_prices = pd.concat(
        [
            charts[symbol]["adj_close"].rename(symbol)
            for symbol in symbols
        ],
        axis=1,
        join="outer",
    ).sort_index()
    raw_close_prices = pd.concat(
        [
            charts[symbol]["close"].rename(symbol)
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

    print(f"Momentum rotation 回測（{result.start} 至 {result.end}）")
    print(f"交易範圍：{', '.join(args.symbols)}")
    print(f"最終資產：${result.final_equity:,.2f}")
    print(f"總回報：{result.total_return_pct:.2f}%")
    print(f"年化回報：{result.cagr_pct:.2f}%")
    print(f"最大回撤：{result.max_drawdown_pct:.2f}%")
    print(f"訊號切換次數：{result.trade_count}")
    print()
    print(f"長揸 {args.benchmark}：${result.benchmark_final_equity:,.2f}")
    print(f"長揸回報：{result.benchmark_total_return_pct:.2f}%")
    print(f"長揸年化回報：{result.benchmark_cagr_pct:.2f}%")
    print(f"長揸最大回撤：{result.benchmark_max_drawdown_pct:.2f}%")
    print()
    print("最新 momentum 分數：")
    print(
        format_momentum_score_table(
            latest_momentum_score_table(
                close_prices,
                args.lookback_days,
                latest_close_prices=raw_close_prices,
            )
        )
    )
    print()
    trades = build_trade_table(curve)
    if args.output_csv:
        output_path = Path(args.output_csv)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        trades.to_csv(output_path, index=False)
        print(f"交易紀錄 CSV：{output_path}")
        print()

    print("最後 10 筆交易：")
    print(format_bordered_table(format_trade_table_for_console(trades.tail(10))))


def build_trade_table(curve: pd.DataFrame) -> pd.DataFrame:
    trade_rows = curve[curve["selected"].ne(curve["selected"].shift())].copy()
    columns = [
        "date",
        "signal_date",
        "selected",
        "sell_price",
        "buy_price",
        "momentum",
        "equity",
        "drawdown",
        "day_return",
    ]
    return trade_rows.loc[:, columns].rename(
        columns={
            "date": "日期",
            "signal_date": "訊號日期",
            "selected": "持倉",
            "sell_price": "賣出價",
            "buy_price": "買入價",
            "momentum": "momentum",
            "equity": "資產",
            "drawdown": "回撤",
            "day_return": "日回報",
        }
    )


def format_trade_table_for_console(trades: pd.DataFrame) -> pd.DataFrame:
    table = trades.copy()
    table["賣出價"] = table["賣出價"].map(_format_price)
    table["買入價"] = table["買入價"].map(_format_price)
    table["momentum"] = table["momentum"].map(_format_percent)
    table["資產"] = table["資產"].map(lambda value: f"{float(value):,.2f}")
    table["回撤"] = table["回撤"].map(_format_percent)
    table["日回報"] = table["日回報"].map(_format_percent)
    return table


def _format_percent(value: float) -> str:
    if pd.isna(value):
        return ""
    return f"{float(value) * 100:.2f}%"


def _format_price(value: float) -> str:
    if pd.isna(value):
        return ""
    return f"{float(value):,.2f}"


def fetch_yahoo_history(symbol: str, start: str, end: str | None) -> pd.Series:
    return fetch_yahoo_chart(symbol, start, end)["adj_close"]


def fetch_yahoo_chart(symbol: str, start: str, end: str | None) -> pd.DataFrame:
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
        raise RuntimeError(f"{symbol} Yahoo 圖表數據錯誤：{chart['error']}")

    result = chart["result"][0]
    timestamps = result["timestamp"]
    quote = result["indicators"]["quote"][0]
    adjclose = result["indicators"].get("adjclose", [{}])[0].get("adjclose", [])
    closes = quote["close"]
    adjusted_closes = adjclose or closes
    dates = [datetime.fromtimestamp(ts, tz=UTC).date() for ts in timestamps]
    return pd.DataFrame(
        {
            "close": closes,
            "adj_close": adjusted_closes,
        },
        index=dates,
    ).dropna(subset=["close", "adj_close"])


def _timestamp(value: str | None) -> int:
    if value is None:
        return int(datetime.now(tz=UTC).timestamp())
    return int(datetime.fromisoformat(value).replace(tzinfo=UTC).timestamp())


if __name__ == "__main__":
    main()
