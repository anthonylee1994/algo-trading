from __future__ import annotations

import argparse
from collections.abc import Callable
from pathlib import Path
import sys

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from algo_trading.market_cap_universe import (
    DEFAULT_MARKET_CAP_UNIVERSE_PATH,
    load_market_cap_universe,
    symbols_for_date,
)
from algo_trading.momentum_rotation import format_bordered_table
from scripts.backtest_momentum_rotation import (
    build_backtest_summary,
    fetch_yahoo_chart,
    run_bt_backtest,
)

UniverseResolver = Callable[[pd.Timestamp], list[str]]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--start", default="2010-01-01")
    parser.add_argument("--end", default=None)
    parser.add_argument("--benchmark", default="SPY")
    parser.add_argument("--secondary-benchmark", default="QQQ")
    parser.add_argument("--cost-bps", type=float, default=15.0)
    parser.add_argument("--rebalance", choices=["weekly", "monthly"], default="monthly")
    parser.add_argument("--output-csv", default="output/stock_selection_research.csv")
    args = parser.parse_args()

    close_prices, universe_symbols, loaded = load_prices_and_universe(
        start=args.start,
        end=args.end,
        benchmarks=[args.benchmark, args.secondary_benchmark],
    )
    resolver = lambda date: symbols_for_date(  # noqa: E731
        date,
        universe_symbols,
        loaded,
        lag_years=1,
    )
    cases = build_cases(
        close_prices=close_prices,
        universe_symbols=universe_symbols,
        universe_resolver=resolver,
        primary_benchmark=args.benchmark,
    )
    rows = [
        run_case(
            name=name,
            weights=weights,
            close_prices=close_prices,
            benchmark=args.benchmark,
            secondary_benchmark=args.secondary_benchmark,
            cost_bps=args.cost_bps,
            rebalance=args.rebalance,
            note=note,
        )
        for name, weights, note in cases
    ]
    output = pd.DataFrame(rows).sort_values(
        by=["cagr_over_benchmark", "sharpe"],
        ascending=[False, False],
    )
    output_path = Path(args.output_csv)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output.to_csv(output_path, index=False)

    print("Stock selection strategy research")
    print(
        f"Universe: lagged annual S&P 500 market-cap Top 10; "
        f"benchmark: {args.benchmark}; secondary: {args.secondary_benchmark}; "
        f"rebalance: {args.rebalance}; cost: {args.cost_bps:.0f} bps"
    )
    print()
    print(format_bordered_table(format_rows(output)))
    print()
    print(f"CSV: {output_path}")


def build_cases(
    close_prices: pd.DataFrame,
    universe_symbols: list[str],
    universe_resolver: UniverseResolver,
    primary_benchmark: str,
) -> list[tuple[str, pd.DataFrame, str]]:
    cases: list[tuple[str, pd.DataFrame, str]] = [
        (
            "Equal weight lagged Top10",
            build_equal_weight_universe(
                close_prices=close_prices,
                symbols=universe_symbols,
                universe_resolver=universe_resolver,
            ),
            "No ranking; size factor baseline",
        ),
    ]
    for lookback in [63, 126, 252]:
        for top_n in [3, 5, 10]:
            cases.append(
                (
                    f"Momentum L{lookback} top{top_n}",
                    build_ranked_weights(
                        close_prices=close_prices,
                        symbols=universe_symbols,
                        universe_resolver=universe_resolver,
                        score=momentum_score(close_prices, lookback),
                        top_n=top_n,
                        positive_only=True,
                    ),
                    "Pure stock momentum; cash if no positive score",
                )
            )
            cases.append(
                (
                    f"Momentum L{lookback} top{top_n} + {primary_benchmark} floor",
                    build_ranked_weights(
                        close_prices=close_prices,
                        symbols=universe_symbols,
                        universe_resolver=universe_resolver,
                        score=momentum_score(close_prices, lookback),
                        top_n=top_n,
                        positive_only=True,
                        index_floor=primary_benchmark,
                    ),
                    "Stock momentum plus broad-market floor for empty slots",
                )
            )
        cases.append(
            (
                f"Risk-adjusted momentum L{lookback} top5",
                build_ranked_weights(
                    close_prices=close_prices,
                    symbols=universe_symbols,
                    universe_resolver=universe_resolver,
                    score=risk_adjusted_momentum_score(close_prices, lookback),
                    top_n=5,
                    positive_only=True,
                ),
                "Momentum divided by realized volatility",
            )
        )
    for vol_window in [63, 126, 252]:
        cases.append(
            (
                f"Low volatility W{vol_window} top5",
                build_ranked_weights(
                    close_prices=close_prices,
                    symbols=universe_symbols,
                    universe_resolver=universe_resolver,
                    score=low_volatility_score(close_prices, vol_window),
                    top_n=5,
                    positive_only=False,
                ),
                "Lowest realized volatility among current mega caps",
            )
        )
    return cases


def build_equal_weight_universe(
    close_prices: pd.DataFrame,
    symbols: list[str],
    universe_resolver: UniverseResolver,
) -> pd.DataFrame:
    weights = pd.DataFrame(0.0, index=close_prices.index, columns=symbols)
    for date in close_prices.index:
        current = [symbol for symbol in universe_resolver(date) if symbol in weights.columns]
        if not current:
            continue
        weight = 1.0 / len(current)
        for symbol in current:
            weights.at[date, symbol] = weight
    return weights.shift(1).fillna(0.0)


def build_ranked_weights(
    close_prices: pd.DataFrame,
    symbols: list[str],
    universe_resolver: UniverseResolver,
    score: pd.DataFrame,
    top_n: int,
    positive_only: bool,
    index_floor: str | None = None,
) -> pd.DataFrame:
    columns = list(dict.fromkeys([*symbols, *([index_floor] if index_floor else [])]))
    weights = pd.DataFrame(0.0, index=close_prices.index, columns=columns)
    top_n = max(top_n, 1)
    for date, row in score.iterrows():
        current = [symbol for symbol in universe_resolver(date) if symbol in row.index]
        ranked = row.loc[current].dropna().sort_values(ascending=False)
        if positive_only:
            ranked = ranked[ranked > 0]
        selected = list(ranked.head(top_n).index)
        if index_floor:
            for symbol in selected:
                weights.at[date, symbol] += 1.0 / top_n
            empty = top_n - len(selected)
            if empty > 0:
                weights.at[date, index_floor] += empty / top_n
            continue
        if not selected:
            continue
        weight = 1.0 / len(selected)
        for symbol in selected:
            weights.at[date, symbol] = weight
    return weights.shift(1).fillna(0.0)


def momentum_score(close_prices: pd.DataFrame, lookback: int) -> pd.DataFrame:
    return close_prices.pct_change(lookback)


def risk_adjusted_momentum_score(close_prices: pd.DataFrame, lookback: int) -> pd.DataFrame:
    returns = close_prices.pct_change()
    realized_vol = returns.rolling(lookback).std() * (252.0**0.5)
    return close_prices.pct_change(lookback) / realized_vol


def low_volatility_score(close_prices: pd.DataFrame, window: int) -> pd.DataFrame:
    realized_vol = close_prices.pct_change().rolling(window).std() * (252.0**0.5)
    return -realized_vol


def run_case(
    name: str,
    weights: pd.DataFrame,
    close_prices: pd.DataFrame,
    benchmark: str,
    secondary_benchmark: str,
    cost_bps: float,
    rebalance: str,
    note: str,
) -> dict[str, float | str]:
    required = sorted(set(weights.columns) | {benchmark, secondary_benchmark})
    result = run_bt_backtest(
        close_prices=close_prices.loc[:, required],
        weights=weights,
        benchmark_symbol=benchmark,
        initial_cash=100_000,
        cost_bps=cost_bps,
        rebalance=rebalance,
    )
    summary = build_backtest_summary(result, initial_cash=100_000)
    returns = result.prices["Momentum Rotation"].dropna().pct_change().dropna()
    strategy_prices = result.prices["Momentum Rotation"].dropna()
    secondary_prices = close_prices[secondary_benchmark].dropna()
    secondary_returns = secondary_prices.pct_change().dropna()
    secondary_cagr = cagr(secondary_returns) * 100
    secondary_max_dd = max_drawdown(secondary_prices) * 100
    return {
        "strategy": name,
        "cagr": summary["cagr_pct"],
        "max_drawdown": summary["max_drawdown_pct"],
        "sharpe": sharpe(returns),
        "beat_years_vs_benchmark": yearly_beat_rate(strategy_prices, result.prices[f"Buy Hold {benchmark}"].dropna()),
        "benchmark": benchmark,
        "benchmark_cagr": summary["benchmark_cagr_pct"],
        "benchmark_max_drawdown": summary["benchmark_max_drawdown_pct"],
        "cagr_over_benchmark": summary["cagr_pct"] - summary["benchmark_cagr_pct"],
        "dd_vs_benchmark": summary["max_drawdown_pct"] - summary["benchmark_max_drawdown_pct"],
        "secondary_benchmark": secondary_benchmark,
        "secondary_cagr": secondary_cagr,
        "cagr_over_secondary": summary["cagr_pct"] - secondary_cagr,
        "secondary_max_drawdown": secondary_max_dd,
        "note": note,
    }


def load_prices_and_universe(
    start: str,
    end: str | None,
    benchmarks: list[str],
) -> tuple[pd.DataFrame, list[str], dict[str, list[str]]]:
    kind, loaded = load_market_cap_universe(DEFAULT_MARKET_CAP_UNIVERSE_PATH)
    if kind != "annual":
        raise RuntimeError("expected checked-in annual market-cap universe")
    universe_symbols = sorted({symbol for symbols in loaded.values() for symbol in symbols})
    symbols = list(dict.fromkeys([*universe_symbols, *benchmarks]))
    charts = {symbol: fetch_yahoo_chart(symbol, start, end) for symbol in symbols}
    close_prices = pd.concat(
        [charts[symbol]["adj_close"].rename(symbol) for symbol in symbols],
        axis=1,
        join="outer",
    ).sort_index().ffill().dropna(how="all")
    close_prices.index = pd.to_datetime(close_prices.index)
    return close_prices, universe_symbols, loaded


def cagr(returns: pd.Series) -> float:
    growth = float((1.0 + returns).prod())
    years = len(returns) / 252.0
    return growth ** (1.0 / years) - 1.0 if years > 0 and growth > 0 else float("nan")


def max_drawdown(prices: pd.Series) -> float:
    return float((prices / prices.cummax() - 1.0).min())


def sharpe(returns: pd.Series) -> float:
    std = float(returns.std())
    return float(returns.mean() / std * (252.0**0.5)) if std > 0 else float("nan")


def yearly_beat_rate(strategy_prices: pd.Series, benchmark_prices: pd.Series) -> float:
    aligned = pd.concat(
        [strategy_prices.rename("strategy"), benchmark_prices.rename("benchmark")],
        axis=1,
        join="inner",
    ).dropna()
    yearly = aligned.resample("YE").last().pct_change().dropna()
    if yearly.empty:
        return float("nan")
    return float((yearly["strategy"] > yearly["benchmark"]).mean() * 100.0)


def format_rows(frame: pd.DataFrame) -> pd.DataFrame:
    return frame.assign(
        cagr=frame["cagr"].map(lambda value: f"{value:.2f}%"),
        max_drawdown=frame["max_drawdown"].map(lambda value: f"{value:.2f}%"),
        sharpe=frame["sharpe"].map(lambda value: f"{value:.2f}"),
        beat_years_vs_benchmark=frame["beat_years_vs_benchmark"].map(
            lambda value: f"{value:.0f}%"
        ),
        benchmark_cagr=frame["benchmark_cagr"].map(lambda value: f"{value:.2f}%"),
        cagr_over_benchmark=frame["cagr_over_benchmark"].map(
            lambda value: f"{value:+.2f}pp"
        ),
        cagr_over_secondary=frame["cagr_over_secondary"].map(
            lambda value: f"{value:+.2f}pp"
        ),
    ).loc[
        :,
        [
            "strategy",
            "cagr",
            "max_drawdown",
            "sharpe",
            "beat_years_vs_benchmark",
            "benchmark_cagr",
            "cagr_over_benchmark",
            "cagr_over_secondary",
            "note",
        ],
    ]


if __name__ == "__main__":
    main()
