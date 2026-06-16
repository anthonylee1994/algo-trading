from __future__ import annotations

import argparse
from itertools import product
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


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--start", default="2010-01-01")
    parser.add_argument("--end", default=None)
    parser.add_argument("--benchmark", default="QQQ")
    parser.add_argument("--cost-bps", type=float, default=15.0)
    parser.add_argument("--financing-rate", type=float, default=0.03)
    parser.add_argument("--output-csv", default="output/vol_target_momentum_sweep.csv")
    args = parser.parse_args()

    close_prices, universe_symbols, loaded = load_prices_and_universe(
        start=args.start,
        end=args.end,
        benchmark=args.benchmark,
    )
    benchmark_summary = run_benchmark_summary(
        close_prices=close_prices,
        benchmark=args.benchmark,
        cost_bps=args.cost_bps,
    )
    rows = []
    for lookback, top_n in product([63, 126, 252], [3, 5, 10]):
        weights = build_target_weights(
            close_prices=close_prices,
            symbols=universe_symbols,
            universe_resolver=lambda date: symbols_for_date(
                date,
                universe_symbols,
                loaded,
                lag_years=1,
            ),
            lookback_days=lookback,
            top_n=top_n,
            index_floor=args.benchmark,
        )
        result = run_bt_backtest(
            close_prices=close_prices.loc[:, sorted(set(weights.columns) | {args.benchmark})],
            weights=weights,
            benchmark_symbol=args.benchmark,
            initial_cash=100_000,
            cost_bps=args.cost_bps,
            rebalance="monthly",
        )
        base = build_backtest_summary(result, initial_cash=100_000)
        rows.append(
            {
                "strategy": f"L{lookback} top{top_n} base",
                "lookback": lookback,
                "top_n": top_n,
                "vol_target": 0.0,
                "vol_window": 0,
                "max_leverage": 1.0,
                "cagr": base["cagr_pct"],
                "max_drawdown": base["max_drawdown_pct"],
                "sharpe": result.stats.loc["daily_sharpe", "Momentum Rotation"],
                "avg_exposure": 1.0,
                "low_vol_exposure": 1.0,
                "high_vol_exposure": 1.0,
                "cagr_over_qqq": float(base["cagr_pct"]) - benchmark_summary["cagr"],
                "dd_over_qqq": float(base["max_drawdown_pct"]) - benchmark_summary["max_drawdown"],
            }
        )
        for target_vol, vol_window, max_leverage in product(
            [0.22, 0.26, 0.30, 0.34],
            [20, 40, 60],
            [1.5, 2.0, 2.5],
        ):
            summary = build_vol_target_summary(
                bt_result=result,
                target_vol=target_vol,
                vol_window=vol_window,
                max_leverage=max_leverage,
                financing_rate=args.financing_rate,
                cost_bps=args.cost_bps,
                rebal_band=0.05,
                initial_cash=100_000,
            )
            rows.append(
                {
                    "strategy": (
                        f"L{lookback} top{top_n} "
                        f"VT{int(target_vol * 100)} W{vol_window} cap{max_leverage:g}"
                    ),
                    "lookback": lookback,
                    "top_n": top_n,
                    "vol_target": target_vol,
                    "vol_window": vol_window,
                    "max_leverage": max_leverage,
                    "cagr": summary["cagr_pct"],
                    "max_drawdown": summary["max_drawdown_pct"],
                    "sharpe": summary["sharpe"],
                    "avg_exposure": summary["avg_exposure"],
                    "low_vol_exposure": summary["low_vol_exposure"],
                    "high_vol_exposure": summary["high_vol_exposure"],
                    "cagr_over_qqq": summary["cagr_pct"] - benchmark_summary["cagr"],
                    "dd_over_qqq": summary["max_drawdown_pct"] - benchmark_summary["max_drawdown"],
                }
            )

    output = pd.DataFrame(rows).sort_values(
        by=["cagr", "max_drawdown"],
        ascending=[False, False],
    )
    output_path = Path(args.output_csv)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output.to_csv(output_path, index=False)

    robust = output[
        (output["cagr_over_qqq"] >= 5.0)
        & (output["max_drawdown"] >= benchmark_summary["max_drawdown"])
    ].head(20)
    print("Vol-target momentum sweep")
    print(
        f"QQQ: CAGR {benchmark_summary['cagr']:.2f}%, "
        f"max DD {benchmark_summary['max_drawdown']:.2f}%"
    )
    print()
    print("Highest CAGR:")
    print(format_bordered_table(format_rows(output.head(15))))
    print()
    print("CAGR >= QQQ + 5pp and drawdown no worse than QQQ:")
    print(format_bordered_table(format_rows(robust)))
    print()
    print(f"CSV: {output_path}")


def load_prices_and_universe(
    start: str,
    end: str | None,
    benchmark: str,
) -> tuple[pd.DataFrame, list[str], object]:
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


def run_benchmark_summary(
    close_prices: pd.DataFrame,
    benchmark: str,
    cost_bps: float,
) -> dict[str, float]:
    weights = pd.DataFrame({benchmark: 1.0}, index=close_prices.index)
    result = run_bt_backtest(
        close_prices=close_prices.loc[:, [benchmark]],
        weights=weights,
        benchmark_symbol=benchmark,
        initial_cash=100_000,
        cost_bps=cost_bps,
        rebalance="monthly",
    )
    summary = build_backtest_summary(result, initial_cash=100_000)
    return {
        "cagr": float(summary["cagr_pct"]),
        "max_drawdown": float(summary["max_drawdown_pct"]),
    }


def format_rows(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        return pd.DataFrame(
            columns=[
                "strategy",
                "cagr",
                "max_drawdown",
                "sharpe",
                "avg_exposure",
                "low_vol_exposure",
                "high_vol_exposure",
            ]
        )
    return frame.assign(
        cagr=frame["cagr"].map(lambda value: f"{value:.2f}%"),
        max_drawdown=frame["max_drawdown"].map(lambda value: f"{value:.2f}%"),
        sharpe=frame["sharpe"].map(lambda value: f"{value:.2f}"),
        avg_exposure=frame["avg_exposure"].map(lambda value: f"{value:.2f}x"),
        low_vol_exposure=frame["low_vol_exposure"].map(lambda value: f"{value:.2f}x"),
        high_vol_exposure=frame["high_vol_exposure"].map(lambda value: f"{value:.2f}x"),
    ).loc[
        :,
        [
            "strategy",
            "cagr",
            "max_drawdown",
            "sharpe",
            "avg_exposure",
            "low_vol_exposure",
            "high_vol_exposure",
        ],
    ]


if __name__ == "__main__":
    main()
