from __future__ import annotations

import argparse
from datetime import UTC, datetime
import json
from pathlib import Path
import sys
import urllib.parse
import urllib.request

import bt
import matplotlib.pyplot as plt
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from algo_trading.momentum_rotation import (
    DEFAULT_SYMBOLS,
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
    parser.add_argument("--top-n", type=int, default=2)
    parser.add_argument("--initial-cash", type=float, default=100_000)
    parser.add_argument(
        "--output-csv",
        default="output/backtest_trades.csv",
        help="交易紀錄 CSV output path；用空字串可跳過輸出。",
    )
    parser.add_argument(
        "--plot-path",
        default="output/backtest_chart.png",
        help="bt equity curve chart output path；用空字串可跳過輸出。",
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
    close_prices.index = pd.to_datetime(close_prices.index)
    raw_close_prices = pd.concat(
        [
            charts[symbol]["close"].rename(symbol)
            for symbol in symbols
        ],
        axis=1,
        join="outer",
    ).sort_index()
    raw_close_prices.index = pd.to_datetime(raw_close_prices.index)

    weights = build_target_weights(
        close_prices=close_prices,
        symbols=args.symbols,
        lookback_days=args.lookback_days,
        top_n=args.top_n,
    )
    bt_result = run_bt_backtest(
        close_prices=close_prices,
        weights=weights,
        benchmark_symbol=args.benchmark,
        initial_cash=args.initial_cash,
    )
    summary = build_backtest_summary(
        bt_result=bt_result,
        initial_cash=args.initial_cash,
    )
    curve = build_curve(
        bt_result=bt_result,
        weights=weights,
        close_prices=close_prices,
        lookback_days=args.lookback_days,
        initial_cash=args.initial_cash,
    )
    summary["trade_count"] = max(
        int(curve["selected"].ne(curve["selected"].shift()).sum()) - 1,
        0,
    )

    print(f"Momentum rotation 回測（{summary['start']} 至 {summary['end']}）")
    print(f"交易範圍：{', '.join(args.symbols)}")
    print(f"持倉數量：Top {args.top_n}")
    print(f"最終資產：${summary['final_equity']:,.2f}")
    print(f"總回報：{summary['total_return_pct']:.2f}%")
    print(f"年化回報：{summary['cagr_pct']:.2f}%")
    print(f"最大回撤：{summary['max_drawdown_pct']:.2f}%")
    print(f"訊號切換次數：{summary['trade_count']}")
    print()
    print(f"長揸 {args.benchmark}：${summary['benchmark_final_equity']:,.2f}")
    print(f"長揸回報：{summary['benchmark_total_return_pct']:.2f}%")
    print(f"長揸年化回報：{summary['benchmark_cagr_pct']:.2f}%")
    print(f"長揸最大回撤：{summary['benchmark_max_drawdown_pct']:.2f}%")
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
    if args.plot_path:
        plot_path = Path(args.plot_path)
        plot_path.parent.mkdir(parents=True, exist_ok=True)
        plot_bt_result(bt_result, plot_path)
        print(f"回測圖表：{plot_path}")
        print()

    print("最後 10 筆交易：")
    print(format_bordered_table(format_trade_table_for_console(trades.tail(10))))


def build_target_weights(
    close_prices: pd.DataFrame,
    symbols: list[str],
    lookback_days: int,
    top_n: int = 1,
) -> pd.DataFrame:
    symbols = list(dict.fromkeys(symbols))
    momentum = close_prices.loc[:, symbols].pct_change(lookback_days)
    weights = pd.DataFrame(0.0, index=close_prices.index, columns=symbols)
    top_n = max(top_n, 1)
    for date, row in momentum.iterrows():
        ranking = row.dropna().sort_values(ascending=False)
        ranking = ranking[ranking > 0]
        if ranking.empty:
            continue
        selected = list(ranking.head(top_n).index)
        weight = 1.0 / len(selected)
        for symbol in selected:
            weights.loc[date, str(symbol)] = weight
    return weights


def run_bt_backtest(
    close_prices: pd.DataFrame,
    weights: pd.DataFrame,
    benchmark_symbol: str,
    initial_cash: float,
) -> bt.backtest.Result:
    strategy = bt.Strategy(
        "Momentum Rotation",
        [
            bt.algos.RunDaily(),
            bt.algos.WeighTarget(weights),
            bt.algos.Rebalance(),
        ],
    )
    benchmark_weights = pd.DataFrame(
        {benchmark_symbol: 1.0},
        index=close_prices.index,
    )
    benchmark_strategy = bt.Strategy(
        f"Buy Hold {benchmark_symbol}",
        [
            bt.algos.RunDaily(),
            bt.algos.WeighTarget(benchmark_weights),
            bt.algos.Rebalance(),
        ],
    )
    return bt.run(
        bt.Backtest(
            strategy,
            close_prices,
            initial_capital=initial_cash,
            integer_positions=False,
        ),
        bt.Backtest(
            benchmark_strategy,
            close_prices.loc[:, [benchmark_symbol]],
            initial_capital=initial_cash,
            integer_positions=False,
        ),
    )


def plot_bt_result(bt_result: bt.backtest.Result, output_path: Path) -> None:
    axis = bt_result.plot(title="Momentum Rotation vs Benchmark")
    figure = axis.get_figure()
    figure.set_size_inches(12, 7)
    figure.tight_layout()
    figure.savefig(output_path, dpi=160)
    plt.close(figure)


def build_backtest_summary(
    bt_result: bt.backtest.Result,
    initial_cash: float,
) -> dict[str, float | int | str]:
    strategy_name = "Momentum Rotation"
    benchmark_name = next(name for name in bt_result.prices.columns if name != strategy_name)
    strategy_prices = bt_result.prices[strategy_name].dropna()
    benchmark_prices = bt_result.prices[benchmark_name].dropna()
    stats = bt_result.stats
    return {
        "start": strategy_prices.index[0].date().isoformat(),
        "end": strategy_prices.index[-1].date().isoformat(),
        "final_equity": _bt_price_to_equity(strategy_prices.iloc[-1], initial_cash),
        "total_return_pct": float(stats.loc["total_return", strategy_name]) * 100,
        "cagr_pct": float(stats.loc["cagr", strategy_name]) * 100,
        "max_drawdown_pct": float(stats.loc["max_drawdown", strategy_name]) * 100,
        "trade_count": 0,
        "benchmark_final_equity": _bt_price_to_equity(benchmark_prices.iloc[-1], initial_cash),
        "benchmark_total_return_pct": float(stats.loc["total_return", benchmark_name]) * 100,
        "benchmark_cagr_pct": float(stats.loc["cagr", benchmark_name]) * 100,
        "benchmark_max_drawdown_pct": float(stats.loc["max_drawdown", benchmark_name]) * 100,
    }


def build_curve(
    bt_result: bt.backtest.Result,
    weights: pd.DataFrame,
    close_prices: pd.DataFrame,
    lookback_days: int,
    initial_cash: float,
) -> pd.DataFrame:
    strategy_prices = bt_result.prices["Momentum Rotation"].dropna()
    equity = strategy_prices.map(lambda value: _bt_price_to_equity(value, initial_cash))
    equity = equity.reindex(weights.index).ffill().dropna()
    weights = weights.reindex(equity.index).fillna(0)
    momentum = close_prices.pct_change(lookback_days).reindex(equity.index)
    rows = []
    previous_symbols: list[str] = []
    for date in equity.index:
        current_symbols = _symbols_from_weight_row(weights.loc[date])
        bought_symbols = [symbol for symbol in current_symbols if symbol not in previous_symbols]
        sold_symbols = [symbol for symbol in previous_symbols if symbol not in current_symbols]
        rows.append(
            {
                "date": date.date().isoformat(),
                "signal_date": date.date().isoformat(),
                "selected": _format_symbols(current_symbols),
                "previous_selected": _format_symbols(previous_symbols),
                "momentum": _max_momentum(momentum, date, current_symbols),
                "buy_price": _format_symbol_prices(close_prices, date, bought_symbols),
                "sell_price": _format_symbol_prices(close_prices, date, sold_symbols),
                "equity": float(equity.loc[date]),
                "drawdown": float(equity.loc[date] / equity.loc[:date].max() - 1),
                "day_return": float(equity.pct_change().fillna(0).loc[date]),
            }
        )
        previous_symbols = current_symbols
    curve = pd.DataFrame(rows)
    return curve


def _symbols_from_weight_row(row: pd.Series) -> list[str]:
    if row.empty or float(row.max()) <= 0:
        return []
    selected = row[row > 0].sort_values(ascending=False)
    return [str(symbol) for symbol in selected.index]


def _format_symbols(symbols: list[str]) -> str:
    return ", ".join(symbols) if symbols else "CASH"


def _max_momentum(values: pd.DataFrame, date: pd.Timestamp, symbols: list[str]) -> float:
    if not symbols or date not in values.index:
        return float("nan")
    row = values.loc[date, [symbol for symbol in symbols if symbol in values.columns]]
    if row.empty:
        return float("nan")
    value = row.max()
    return float(value) if not pd.isna(value) else float("nan")


def _format_symbol_prices(
    values: pd.DataFrame,
    date: pd.Timestamp,
    symbols: list[str],
) -> str:
    if not symbols or date not in values.index:
        return ""
    parts = []
    for symbol in symbols:
        if symbol not in values.columns:
            continue
        value = values.loc[date, symbol]
        if pd.isna(value):
            continue
        parts.append(f"{symbol}:{float(value):,.2f}")
    return "; ".join(parts)


def _bt_price_to_equity(price: float, initial_cash: float) -> float:
    return float(price) / 100 * initial_cash


def build_trade_table(curve: pd.DataFrame) -> pd.DataFrame:
    trade_rows = curve[curve["selected"].ne(curve["selected"].shift())].copy()
    columns = [
        "date",
        "signal_date",
        "previous_selected",
        "sell_price",
        "selected",
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
            "previous_selected": "賣出持倉",
            "sell_price": "賣出價",
            "selected": "買入持倉",
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
    if isinstance(value, str):
        return value
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
