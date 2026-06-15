from __future__ import annotations

import argparse
from dataclasses import dataclass
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
    build_levered_summary,
    build_target_weights,
    fetch_yahoo_chart,
    run_bt_backtest,
)


@dataclass(frozen=True)
class StrategyCase:
    name: str
    symbols: list[str]
    weights: pd.DataFrame
    leverage: float = 1.0
    financing_rate: float = 0.03
    note: str = ""


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--start", default="2010-01-01")
    parser.add_argument("--end", default=None)
    parser.add_argument("--benchmark", default="QQQ")
    parser.add_argument("--cost-bps", type=float, default=15.0)
    parser.add_argument("--rebalance", choices=["daily", "weekly", "monthly"], default="monthly")
    parser.add_argument("--initial-cash", type=float, default=100_000)
    parser.add_argument("--output-csv", default="output/qqq_strategy_comparison.csv")
    args = parser.parse_args()

    symbol_groups = [
        [args.benchmark],
        ["QQQ", "SMH", "XLK", "IGV", "IYW", "SOXX"],
        [
            "AAPL",
            "MSFT",
            "NVDA",
            "AMZN",
            "GOOG",
            "META",
            "AVGO",
            "TSM",
            "JPM",
            "V",
            "MA",
            "COST",
            "ASML",
            "UNH",
            "LLY",
        ],
    ]
    universe_symbols, universe_resolver = load_top_market_cap_universe()
    symbol_groups.append(universe_symbols)
    symbols = sorted({symbol for group in symbol_groups for symbol in group})

    charts = {symbol: fetch_yahoo_chart(symbol, args.start, args.end) for symbol in symbols}
    close_prices = pd.concat(
        [charts[symbol]["adj_close"].rename(symbol) for symbol in symbols],
        axis=1,
        join="outer",
    ).sort_index()
    close_prices.index = pd.to_datetime(close_prices.index)

    cases = build_cases(
        close_prices=close_prices,
        benchmark=args.benchmark,
        universe_symbols=universe_symbols,
        universe_resolver=universe_resolver,
    )
    rows = [
        run_case(
            case=case,
            close_prices=close_prices,
            benchmark=args.benchmark,
            initial_cash=args.initial_cash,
            cost_bps=args.cost_bps,
            rebalance=args.rebalance,
        )
        for case in cases
    ]
    result = pd.DataFrame(rows).sort_values(
        by=["CAGR", "MaxDD"],
        ascending=[False, False],
    )
    output_path = Path(args.output_csv)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    result.to_csv(output_path, index=False)

    print("QQQ strategy comparison")
    print(f"Period: {result['Start'].iloc[0]} to {result['End'].iloc[0]}")
    print(f"Benchmark: {args.benchmark}; rebalance: {args.rebalance}; cost: {args.cost_bps:.1f} bps")
    print()
    print(
        format_bordered_table(
            result.assign(
                CAGR=result["CAGR"].map(lambda value: f"{value:.2f}%"),
                MaxDD=result["MaxDD"].map(lambda value: f"{value:.2f}%"),
                Sharpe=result["Sharpe"].map(lambda value: f"{value:.2f}"),
                BeatYears=result["BeatYears"].map(lambda value: f"{value:.0f}%"),
            ).loc[
                :,
                [
                    "Strategy",
                    "CAGR",
                    "MaxDD",
                    "Sharpe",
                    "BeatYears",
                    "Trades",
                    "Note",
                ],
            ]
        )
    )
    print()
    print(f"CSV: {output_path}")


def load_top_market_cap_universe() -> tuple[list[str], object]:
    kind, loaded = load_market_cap_universe(DEFAULT_MARKET_CAP_UNIVERSE_PATH)
    if kind != "annual":
        raise RuntimeError("compare script expects the checked-in annual Top 10 universe JSON")
    universe_symbols = sorted({symbol for symbols in loaded.values() for symbol in symbols})
    return universe_symbols, loaded


def build_cases(
    close_prices: pd.DataFrame,
    benchmark: str,
    universe_symbols: list[str],
    universe_resolver: object,
) -> list[StrategyCase]:
    qqq_hold = pd.DataFrame({benchmark: 1.0}, index=close_prices.index)
    qqq_trend = build_trend_weights(close_prices, benchmark, benchmark, sma_days=200)
    qqq_trend_50 = build_trend_weights(
        close_prices,
        benchmark,
        benchmark,
        sma_days=200,
        defensive_weight=0.5,
    )
    etf_symbols = available_symbols(close_prices, ["QQQ", "SMH", "XLK", "IGV", "IYW", "SOXX"])
    compounder_symbols = available_symbols(
        close_prices,
        [
            "AAPL",
            "MSFT",
            "NVDA",
            "AMZN",
            "GOOG",
            "META",
            "AVGO",
            "TSM",
            "JPM",
            "V",
            "MA",
            "COST",
            "ASML",
            "UNH",
            "LLY",
        ],
    )

    return [
        StrategyCase("QQQ buy hold", [benchmark], qqq_hold, note="baseline"),
        StrategyCase("QQQ 200D trend cash", [benchmark], qqq_trend, note="below 200D = cash"),
        StrategyCase(
            "QQQ 200D trend 50%",
            [benchmark],
            qqq_trend_50,
            note="below 200D = 50% QQQ",
        ),
        StrategyCase(
            "QQQ trend cash x1.25",
            [benchmark],
            qqq_trend,
            leverage=1.25,
            note="trend return levered after costs",
        ),
        StrategyCase(
            "Top3 mega momentum + QQQ",
            universe_symbols,
            build_target_weights(
                close_prices=close_prices,
                symbols=universe_symbols,
                universe_resolver=lambda date: symbols_for_date(
                    date, universe_symbols, universe_resolver, lag_years=1
                ),
                lookback_days=126,
                top_n=3,
                index_floor=benchmark,
            ),
            note="more concentrated clean PIT-ish",
        ),
        StrategyCase(
            "Top5 mega momentum + QQQ",
            universe_symbols,
            build_target_weights(
                close_prices=close_prices,
                symbols=universe_symbols,
                universe_resolver=lambda date: symbols_for_date(
                    date, universe_symbols, universe_resolver, lag_years=1
                ),
                lookback_days=126,
                top_n=5,
                index_floor=benchmark,
            ),
            note="current clean baseline",
        ),
        StrategyCase(
            "Top5 mega momentum 63D + QQQ",
            universe_symbols,
            build_target_weights(
                close_prices=close_prices,
                symbols=universe_symbols,
                universe_resolver=lambda date: symbols_for_date(
                    date, universe_symbols, universe_resolver, lag_years=1
                ),
                lookback_days=63,
                top_n=5,
                index_floor=benchmark,
            ),
            note="faster 3-month momentum",
        ),
        StrategyCase(
            "Top5 mega momentum 252D + QQQ",
            universe_symbols,
            build_target_weights(
                close_prices=close_prices,
                symbols=universe_symbols,
                universe_resolver=lambda date: symbols_for_date(
                    date, universe_symbols, universe_resolver, lag_years=1
                ),
                lookback_days=252,
                top_n=5,
                index_floor=benchmark,
            ),
            note="slower 12-month momentum",
        ),
        StrategyCase(
            "Top5 mega momentum + QQQ x1.15",
            universe_symbols,
            build_target_weights(
                close_prices=close_prices,
                symbols=universe_symbols,
                universe_resolver=lambda date: symbols_for_date(
                    date, universe_symbols, universe_resolver, lag_years=1
                ),
                lookback_days=126,
                top_n=5,
                index_floor=benchmark,
            ),
            leverage=1.15,
            note="current levered baseline",
        ),
        StrategyCase(
            "Top5 mega momentum + QQQ x1.25",
            universe_symbols,
            build_target_weights(
                close_prices=close_prices,
                symbols=universe_symbols,
                universe_resolver=lambda date: symbols_for_date(
                    date, universe_symbols, universe_resolver, lag_years=1
                ),
                lookback_days=126,
                top_n=5,
                index_floor=benchmark,
            ),
            leverage=1.25,
            note="higher leverage stress",
        ),
        StrategyCase(
            "Top10 mega momentum + QQQ",
            universe_symbols,
            build_target_weights(
                close_prices=close_prices,
                symbols=universe_symbols,
                universe_resolver=lambda date: symbols_for_date(
                    date, universe_symbols, universe_resolver, lag_years=1
                ),
                lookback_days=126,
                top_n=10,
                index_floor=benchmark,
            ),
            note="more diversified",
        ),
        StrategyCase(
            "Top10 mega momentum + QQQ x1.15",
            universe_symbols,
            build_target_weights(
                close_prices=close_prices,
                symbols=universe_symbols,
                universe_resolver=lambda date: symbols_for_date(
                    date, universe_symbols, universe_resolver, lag_years=1
                ),
                lookback_days=126,
                top_n=10,
                index_floor=benchmark,
            ),
            leverage=1.15,
            note="diversified levered",
        ),
        StrategyCase(
            "ETF relative strength top1",
            etf_symbols,
            build_target_weights(
                close_prices=close_prices,
                symbols=etf_symbols,
                lookback_days=126,
                top_n=1,
                index_floor=None,
            ),
            note="QQQ/SMH/XLK/IGV/IYW/SOXX",
        ),
        StrategyCase(
            "ETF relative strength top2",
            etf_symbols,
            build_target_weights(
                close_prices=close_prices,
                symbols=etf_symbols,
                lookback_days=126,
                top_n=2,
                index_floor=None,
            ),
            note="equal-weight top 2 ETFs",
        ),
        StrategyCase(
            "ETF relative strength top2 x1.15",
            etf_symbols,
            build_target_weights(
                close_prices=close_prices,
                symbols=etf_symbols,
                lookback_days=126,
                top_n=2,
                index_floor=None,
            ),
            leverage=1.15,
            note="ETF RS with mild leverage",
        ),
        StrategyCase(
            "Compounder momentum top5",
            compounder_symbols,
            build_target_weights(
                close_prices=close_prices,
                symbols=compounder_symbols,
                lookback_days=126,
                top_n=5,
                index_floor=benchmark,
            ),
            note="fixed list, survivorship bias",
        ),
    ]


def build_trend_weights(
    close_prices: pd.DataFrame,
    symbol: str,
    output_symbol: str,
    sma_days: int,
    defensive_weight: float = 0.0,
) -> pd.DataFrame:
    price = close_prices[symbol]
    sma = price.rolling(sma_days).mean()
    exposure = pd.Series(defensive_weight, index=close_prices.index)
    exposure[price > sma] = 1.0
    exposure = exposure.shift(1).fillna(0.0)
    return pd.DataFrame({output_symbol: exposure}, index=close_prices.index)


def available_symbols(close_prices: pd.DataFrame, symbols: list[str]) -> list[str]:
    return [symbol for symbol in symbols if symbol in close_prices.columns]


def run_case(
    case: StrategyCase,
    close_prices: pd.DataFrame,
    benchmark: str,
    initial_cash: float,
    cost_bps: float,
    rebalance: str,
) -> dict[str, object]:
    required_symbols = sorted(set(case.weights.columns) | {benchmark})
    result = run_bt_backtest(
        close_prices=close_prices.loc[:, required_symbols],
        weights=case.weights.loc[:, case.weights.columns],
        benchmark_symbol=benchmark,
        initial_cash=initial_cash,
        cost_bps=cost_bps,
        rebalance=rebalance,
    )
    if case.leverage == 1.0:
        summary = build_backtest_summary(result, initial_cash)
        strategy_returns = result.prices["Momentum Rotation"].dropna().pct_change().dropna()
        cagr = float(summary["cagr_pct"])
        max_drawdown = float(summary["max_drawdown_pct"])
        sharpe = annualized_sharpe(strategy_returns)
        strategy_prices = result.prices["Momentum Rotation"].dropna()
    else:
        levered = build_levered_summary(result, case.leverage, case.financing_rate)
        base_returns = result.prices["Momentum Rotation"].dropna().pct_change().dropna()
        strategy_returns = case.leverage * base_returns - (
            case.leverage - 1.0
        ) * case.financing_rate / 252.0
        strategy_prices = (1.0 + strategy_returns).cumprod() * 100.0
        summary = build_backtest_summary(result, initial_cash)
        cagr = float(levered["cagr_pct"])
        max_drawdown = float(levered["max_drawdown_pct"])
        sharpe = float(levered["sharpe"])

    benchmark_name = next(name for name in result.prices.columns if name != "Momentum Rotation")
    benchmark_prices = result.prices[benchmark_name].dropna()
    return {
        "Strategy": case.name,
        "Start": str(strategy_prices.index[0].date()),
        "End": str(strategy_prices.index[-1].date()),
        "CAGR": cagr,
        "MaxDD": max_drawdown,
        "Sharpe": sharpe,
        "BeatYears": yearly_beat_rate(strategy_prices, benchmark_prices),
        "Trades": target_change_count(case.weights, rebalance),
        "BenchmarkCAGR": float(summary["benchmark_cagr_pct"]),
        "BenchmarkMaxDD": float(summary["benchmark_max_drawdown_pct"]),
        "Note": case.note,
    }


def annualized_sharpe(returns: pd.Series) -> float:
    std = float(returns.std())
    if std <= 0:
        return float("nan")
    return float(returns.mean() / std * (252.0**0.5))


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


def target_change_count(weights: pd.DataFrame, rebalance: str) -> int:
    if rebalance == "daily":
        sampled = weights
    elif rebalance == "weekly":
        sampled = weights.resample("W-FRI").last().dropna(how="all")
    else:
        sampled = weights.resample("ME").last().dropna(how="all")
    normalized = sampled.fillna(0).round(4)
    changed = normalized.ne(normalized.shift()).any(axis=1)
    return max(int(changed.sum()) - 1, 0)


if __name__ == "__main__":
    main()
