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
    build_target_weights,
    build_vol_target_summary,
    fetch_yahoo_chart,
    run_bt_backtest,
)


@dataclass(frozen=True)
class Candidate:
    name: str
    lookback: int
    top_n: int
    vol_target: float
    vol_window: int
    max_leverage: float


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--start", default="2010-01-01")
    parser.add_argument("--end", default=None)
    parser.add_argument("--benchmark", default="QQQ")
    parser.add_argument("--cost-bps", type=float, default=15.0)
    parser.add_argument("--financing-rate", type=float, default=0.03)
    parser.add_argument("--output-csv", default="output/momentum_candidate_stress.csv")
    args = parser.parse_args()

    close_prices, universe_symbols, loaded = load_prices_and_universe(
        start=args.start,
        end=args.end,
        benchmark=args.benchmark,
    )
    rows: list[dict[str, float | str]] = []
    candidates = [
        Candidate(
            name="Top5 VT30 cap2",
            lookback=126,
            top_n=5,
            vol_target=0.30,
            vol_window=40,
            max_leverage=2.0,
        ),
        Candidate(
            name="Top10 VT34 cap2.5",
            lookback=126,
            top_n=10,
            vol_target=0.34,
            vol_window=40,
            max_leverage=2.5,
        ),
    ]

    for candidate in candidates:
        rows.extend(
            evaluate_financing_sensitivity(
                close_prices=close_prices,
                universe_symbols=universe_symbols,
                loaded=loaded,
                candidate=candidate,
                benchmark=args.benchmark,
                start=args.start,
                cost_bps=args.cost_bps,
            )
        )
        rows.extend(
            evaluate_cost_sensitivity(
                close_prices=close_prices,
                universe_symbols=universe_symbols,
                loaded=loaded,
                candidate=candidate,
                benchmark=args.benchmark,
                start=args.start,
                financing_rate=args.financing_rate,
            )
        )
        rows.extend(
            evaluate_start_sensitivity(
                close_prices=close_prices,
                universe_symbols=universe_symbols,
                loaded=loaded,
                candidate=candidate,
                benchmark=args.benchmark,
                cost_bps=args.cost_bps,
                financing_rate=args.financing_rate,
            )
        )

    rows.extend(
        evaluate_cap_sensitivity(
            close_prices=close_prices,
            universe_symbols=universe_symbols,
            loaded=loaded,
            benchmark=args.benchmark,
            start=args.start,
            cost_bps=args.cost_bps,
            financing_rate=args.financing_rate,
        )
    )

    output = pd.DataFrame(rows)
    output_path = Path(args.output_csv)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output.to_csv(output_path, index=False)

    print("Momentum candidate stress test")
    print(format_bordered_table(format_rows(output)))
    print()
    print(f"CSV: {output_path}")


def evaluate_financing_sensitivity(
    close_prices: pd.DataFrame,
    universe_symbols: list[str],
    loaded: dict[str, list[str]],
    candidate: Candidate,
    benchmark: str,
    start: str,
    cost_bps: float,
) -> list[dict[str, float | str]]:
    rows = []
    for financing_rate in [0.03, 0.05, 0.06, 0.08]:
        rows.append(
            run_candidate(
                close_prices=close_prices,
                universe_symbols=universe_symbols,
                loaded=loaded,
                candidate=candidate,
                benchmark=benchmark,
                start=start,
                cost_bps=cost_bps,
                financing_rate=financing_rate,
                scenario="financing",
                scenario_value=f"{financing_rate:.0%}",
            )
        )
    return rows


def evaluate_cost_sensitivity(
    close_prices: pd.DataFrame,
    universe_symbols: list[str],
    loaded: dict[str, list[str]],
    candidate: Candidate,
    benchmark: str,
    start: str,
    financing_rate: float,
) -> list[dict[str, float | str]]:
    rows = []
    for cost_bps in [15.0, 25.0, 50.0]:
        rows.append(
            run_candidate(
                close_prices=close_prices,
                universe_symbols=universe_symbols,
                loaded=loaded,
                candidate=candidate,
                benchmark=benchmark,
                start=start,
                cost_bps=cost_bps,
                financing_rate=financing_rate,
                scenario="cost",
                scenario_value=f"{cost_bps:.0f}bps",
            )
        )
    return rows


def evaluate_start_sensitivity(
    close_prices: pd.DataFrame,
    universe_symbols: list[str],
    loaded: dict[str, list[str]],
    candidate: Candidate,
    benchmark: str,
    cost_bps: float,
    financing_rate: float,
) -> list[dict[str, float | str]]:
    rows = []
    for start in ["2010-01-01", "2011-01-01", "2014-01-01", "2018-01-01", "2020-01-01"]:
        rows.append(
            run_candidate(
                close_prices=close_prices,
                universe_symbols=universe_symbols,
                loaded=loaded,
                candidate=candidate,
                benchmark=benchmark,
                start=start,
                cost_bps=cost_bps,
                financing_rate=financing_rate,
                scenario="start",
                scenario_value=start[:4],
            )
        )
    return rows


def evaluate_cap_sensitivity(
    close_prices: pd.DataFrame,
    universe_symbols: list[str],
    loaded: dict[str, list[str]],
    benchmark: str,
    start: str,
    cost_bps: float,
    financing_rate: float,
) -> list[dict[str, float | str]]:
    rows = []
    for max_leverage in [2.0, 2.25, 2.5]:
        candidate = Candidate(
            name=f"Top10 VT34 cap{max_leverage:g}",
            lookback=126,
            top_n=10,
            vol_target=0.34,
            vol_window=40,
            max_leverage=max_leverage,
        )
        rows.append(
            run_candidate(
                close_prices=close_prices,
                universe_symbols=universe_symbols,
                loaded=loaded,
                candidate=candidate,
                benchmark=benchmark,
                start=start,
                cost_bps=cost_bps,
                financing_rate=financing_rate,
                scenario="cap",
                scenario_value=f"{max_leverage:g}x",
            )
        )
    return rows


def run_candidate(
    close_prices: pd.DataFrame,
    universe_symbols: list[str],
    loaded: dict[str, list[str]],
    candidate: Candidate,
    benchmark: str,
    start: str,
    cost_bps: float,
    financing_rate: float,
    scenario: str,
    scenario_value: str,
) -> dict[str, float | str]:
    prices = close_prices.loc[close_prices.index >= pd.Timestamp(start)].copy()
    weights = build_target_weights(
        close_prices=prices,
        symbols=universe_symbols,
        universe_resolver=lambda date: symbols_for_date(
            date,
            universe_symbols,
            loaded,
            lag_years=1,
        ),
        lookback_days=candidate.lookback,
        top_n=candidate.top_n,
        index_floor=benchmark,
    )
    result = run_bt_backtest(
        close_prices=prices.loc[:, sorted(set(weights.columns) | {benchmark})],
        weights=weights,
        benchmark_symbol=benchmark,
        initial_cash=100_000,
        cost_bps=cost_bps,
        rebalance="monthly",
    )
    benchmark_summary = build_backtest_summary(result, initial_cash=100_000)
    summary = build_vol_target_summary(
        bt_result=result,
        target_vol=candidate.vol_target,
        vol_window=candidate.vol_window,
        max_leverage=candidate.max_leverage,
        financing_rate=financing_rate,
        cost_bps=cost_bps,
        rebal_band=0.05,
        initial_cash=100_000,
    )
    return {
        "scenario": scenario,
        "scenario_value": scenario_value,
        "candidate": candidate.name,
        "start": start,
        "cost_bps": cost_bps,
        "financing_rate": financing_rate,
        "cagr": summary["cagr_pct"],
        "max_drawdown": summary["max_drawdown_pct"],
        "sharpe": summary["sharpe"],
        "avg_exposure": summary["avg_exposure"],
        "qqq_cagr": benchmark_summary["benchmark_cagr_pct"],
        "qqq_max_drawdown": benchmark_summary["benchmark_max_drawdown_pct"],
        "cagr_over_qqq": summary["cagr_pct"] - benchmark_summary["benchmark_cagr_pct"],
        "dd_vs_qqq": summary["max_drawdown_pct"]
        - benchmark_summary["benchmark_max_drawdown_pct"],
    }


def load_prices_and_universe(
    start: str,
    end: str | None,
    benchmark: str,
) -> tuple[pd.DataFrame, list[str], dict[str, list[str]]]:
    kind, loaded = load_market_cap_universe(DEFAULT_MARKET_CAP_UNIVERSE_PATH)
    if kind != "annual":
        raise RuntimeError("expected checked-in annual market-cap universe")
    universe_symbols = sorted({symbol for symbols in loaded.values() for symbol in symbols})
    symbols = list(dict.fromkeys([*universe_symbols, benchmark]))
    charts = {symbol: fetch_yahoo_chart(symbol, start, end) for symbol in symbols}
    close_prices = pd.concat(
        [charts[symbol]["adj_close"].rename(symbol) for symbol in symbols],
        axis=1,
        join="outer",
    ).sort_index().ffill().dropna(how="all")
    close_prices.index = pd.to_datetime(close_prices.index)
    return close_prices, universe_symbols, loaded


def format_rows(frame: pd.DataFrame) -> pd.DataFrame:
    return frame.assign(
        cost_bps=frame["cost_bps"].map(lambda value: f"{value:.0f}"),
        financing_rate=frame["financing_rate"].map(lambda value: f"{value:.0%}"),
        cagr=frame["cagr"].map(lambda value: f"{value:.2f}%"),
        max_drawdown=frame["max_drawdown"].map(lambda value: f"{value:.2f}%"),
        sharpe=frame["sharpe"].map(lambda value: f"{value:.2f}"),
        avg_exposure=frame["avg_exposure"].map(lambda value: f"{value:.2f}x"),
        qqq_cagr=frame["qqq_cagr"].map(lambda value: f"{value:.2f}%"),
        cagr_over_qqq=frame["cagr_over_qqq"].map(lambda value: f"{value:+.2f}pp"),
        dd_vs_qqq=frame["dd_vs_qqq"].map(lambda value: f"{value:+.2f}pp"),
    ).loc[
        :,
        [
            "scenario",
            "scenario_value",
            "candidate",
            "cagr",
            "max_drawdown",
            "sharpe",
            "avg_exposure",
            "qqq_cagr",
            "cagr_over_qqq",
            "dd_vs_qqq",
        ],
    ]


if __name__ == "__main__":
    main()
