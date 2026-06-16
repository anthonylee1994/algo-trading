from __future__ import annotations

import argparse
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
    build_target_weights,
    build_vol_target_exposure,
    fetch_yahoo_chart,
    run_bt_backtest,
)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--start", default="2010-01-01")
    parser.add_argument("--end", default=None)
    parser.add_argument("--benchmark", default="QQQ")
    parser.add_argument("--lookback", type=int, default=126)
    parser.add_argument("--top-n", type=int, default=5)
    parser.add_argument("--vol-target", type=float, default=0.30)
    parser.add_argument("--vol-window", type=int, default=40)
    parser.add_argument("--max-leverage", type=float, default=2.0)
    parser.add_argument("--rebal-band", type=float, default=0.05)
    parser.add_argument("--cost-bps", type=float, default=15.0)
    parser.add_argument("--financing-rate", type=float, default=0.03)
    parser.add_argument("--output-csv", default="output/vol_target_regime_attribution.csv")
    args = parser.parse_args()

    close_prices, universe_symbols, loaded = load_close_prices(
        start=args.start,
        end=args.end,
        benchmark=args.benchmark,
    )
    weights = build_target_weights(
        close_prices=close_prices,
        symbols=universe_symbols,
        universe_resolver=lambda date: symbols_for_date(
            date,
            universe_symbols,
            loaded,
            lag_years=1,
        ),
        lookback_days=args.lookback,
        top_n=args.top_n,
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
    base_prices = result.prices["Momentum Rotation"].dropna()
    base_returns = base_prices.pct_change().dropna()
    exposure = build_vol_target_exposure(
        base_returns=base_returns,
        target_vol=args.vol_target,
        vol_window=args.vol_window,
        max_leverage=args.max_leverage,
        rebal_band=args.rebal_band,
    )
    components = build_exposure_return_components(
        base_returns=base_returns,
        exposure=exposure,
        financing_rate=args.financing_rate,
        cost_bps=args.cost_bps,
    )
    vt_returns = components["net"]
    benchmark = close_prices[args.benchmark].reindex(vt_returns.index).dropna()
    benchmark_returns = benchmark.pct_change().dropna()
    aligned = pd.concat(
        [
            vt_returns.rename("strategy"),
            base_returns.rename("base"),
            exposure.rename("exposure"),
            benchmark_returns.rename("qqq"),
            components["gross"].rename("gross"),
            components["financing"].rename("financing"),
            components["rebalance_cost"].rename("rebalance_cost"),
        ],
        axis=1,
        join="inner",
    ).dropna()
    realized_vol = aligned["base"].rolling(args.vol_window).std() * (252.0**0.5)
    realized_vol = realized_vol.reindex(aligned.index)
    aligned["vol_bucket"] = pd.qcut(
        realized_vol.rank(method="first"),
        q=4,
        labels=["Q1 low vol", "Q2", "Q3", "Q4 high vol"],
    )
    aligned["year"] = aligned.index.year
    aligned["strategy_excess"] = aligned["strategy"] - aligned["qqq"]
    aligned["strategy_growth"] = 1.0 + aligned["strategy"]
    aligned["qqq_growth"] = 1.0 + aligned["qqq"]

    by_bucket = (
        aligned.groupby("vol_bucket")
        .agg(
            days=("strategy", "size"),
            avg_exposure=("exposure", "mean"),
            avg_strategy=("strategy", "mean"),
            avg_qqq=("qqq", "mean"),
            avg_excess=("strategy_excess", "mean"),
        )
        .reset_index()
    )
    by_bucket["avg_strategy"] = by_bucket["avg_strategy"] * 252.0 * 100
    by_bucket["avg_qqq"] = by_bucket["avg_qqq"] * 252.0 * 100
    by_bucket["avg_excess"] = by_bucket["avg_excess"] * 252.0 * 100
    by_bucket["avg_strategy"] = by_bucket["avg_strategy"].map(lambda value: f"{value:.2f}%")
    by_bucket["avg_qqq"] = by_bucket["avg_qqq"].map(lambda value: f"{value:.2f}%")
    by_bucket["avg_excess"] = by_bucket["avg_excess"].map(lambda value: f"{value:.2f}%")
    by_bucket["avg_exposure"] = by_bucket["avg_exposure"].map(lambda value: f"{value:.2f}x")

    by_year = (
        aligned.groupby("year")
        .apply(
            lambda g: pd.Series(
                {
                    "strategy": period_return(g["strategy"]),
                    "qqq": period_return(g["qqq"]),
                    "excess": period_return(g["strategy"]) - period_return(g["qqq"]),
                    "avg_exposure": g["exposure"].mean(),
                    "high_vol_days": int((g["vol_bucket"] == "Q4 high vol").sum()),
                }
            )
        )
        .reset_index()
    )
    by_year["strategy"] = by_year["strategy"].map(_pct)
    by_year["qqq"] = by_year["qqq"].map(_pct)
    by_year["excess"] = by_year["excess"].map(_pct)
    by_year["avg_exposure"] = by_year["avg_exposure"].map(lambda value: f"{value:.2f}x")

    raw_by_year = (
        aligned.groupby("year")
        .apply(
            lambda g: pd.Series(
                {
                    "strategy_return": period_return(g["strategy"]),
                    "qqq_return": period_return(g["qqq"]),
                    "excess_return": period_return(g["strategy"])
                    - period_return(g["qqq"]),
                    "days": len(g),
                }
            )
        )
        .reset_index()
    )
    leave_one_out = build_leave_one_year_out(aligned)
    component_rows = build_component_rows(aligned)

    result_rows = [
        {
            "metric": "CAGR",
            "strategy": f"{cagr(vt_returns) * 100:.2f}%",
            "qqq": f"{cagr(benchmark_returns) * 100:.2f}%",
            "excess": f"{(cagr(vt_returns) - cagr(benchmark_returns)) * 100:.2f}%",
        },
        {
            "metric": "MaxDD",
            "strategy": f"{max_drawdown(vt_returns):.2f}%",
            "qqq": f"{max_drawdown(benchmark_returns):.2f}%",
            "excess": f"{(max_drawdown(vt_returns) - max_drawdown(benchmark_returns)):.2f}%",
        },
        {
            "metric": "Sharpe",
            "strategy": f"{sharpe(vt_returns):.2f}",
            "qqq": f"{sharpe(benchmark_returns):.2f}",
            "excess": "",
        },
        {
            "metric": "AvgExpo",
            "strategy": f"{float(exposure.mean()):.2f}x",
            "qqq": "1.00x",
            "excess": "",
        },
    ]

    output = Path(args.output_csv)
    output.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(result_rows).to_csv(output, index=False)

    print("Vol-target regime attribution")
    print(format_bordered_table(pd.DataFrame(result_rows)))
    print()
    print("By vol bucket:")
    print(format_bordered_table(by_bucket))
    print()
    print("Return components:")
    print(format_bordered_table(component_rows))
    print()
    print("By year:")
    print(format_bordered_table(by_year.sort_values("year")))
    print()
    print("Top excess years:")
    print(format_bordered_table(format_year_contribution(raw_by_year, ascending=False)))
    print()
    print("Worst excess years:")
    print(format_bordered_table(format_year_contribution(raw_by_year, ascending=True)))
    print()
    print("Leave-one-year-out CAGR sensitivity:")
    print(format_bordered_table(format_leave_one_out(leave_one_out)))
    print()
    print(f"CSV: {output}")


def load_close_prices(start: str, end: str | None, benchmark: str):
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


def apply_exposure_returns(
    base_returns: pd.Series,
    exposure: pd.Series,
    financing_rate: float,
    cost_bps: float,
) -> pd.Series:
    return build_exposure_return_components(
        base_returns=base_returns,
        exposure=exposure,
        financing_rate=financing_rate,
        cost_bps=cost_bps,
    )["net"]


def build_exposure_return_components(
    base_returns: pd.Series,
    exposure: pd.Series,
    financing_rate: float,
    cost_bps: float,
) -> pd.DataFrame:
    aligned = pd.concat(
        [base_returns.rename("base"), exposure.rename("exposure")],
        axis=1,
        join="inner",
    ).dropna()
    borrow = aligned["exposure"].sub(1.0).clip(lower=0.0)
    financing = borrow * financing_rate / 252.0
    exposure_turnover = aligned["exposure"].diff().abs().fillna(
        aligned["exposure"].abs()
    )
    rebalance_cost = exposure_turnover * max(cost_bps, 0.0) / 10_000.0
    gross = aligned["exposure"] * aligned["base"]
    return pd.DataFrame(
        {
            "base": aligned["base"],
            "exposure": aligned["exposure"],
            "gross": gross,
            "financing": financing,
            "rebalance_cost": rebalance_cost,
            "net": gross - financing - rebalance_cost,
        },
        index=aligned.index,
    )


def period_return(returns: pd.Series) -> float:
    return (float((1.0 + returns).prod()) - 1.0) * 100


def build_leave_one_year_out(aligned: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for year in sorted(aligned["year"].unique()):
        subset = aligned[aligned["year"] != year]
        rows.append(
            {
                "removed_year": int(year),
                "strategy_cagr": cagr(subset["strategy"]) * 100,
                "qqq_cagr": cagr(subset["qqq"]) * 100,
                "excess_cagr": (cagr(subset["strategy"]) - cagr(subset["qqq"]))
                * 100,
            }
        )
    return pd.DataFrame(rows)


def build_component_rows(aligned: pd.DataFrame) -> pd.DataFrame:
    base_cagr = cagr(aligned["base"]) * 100
    qqq_cagr = cagr(aligned["qqq"]) * 100
    gross_cagr = cagr(aligned["gross"]) * 100
    net_cagr = cagr(aligned["strategy"]) * 100
    annual_financing = aligned["financing"].mean() * 252.0 * 100
    annual_rebalance_cost = aligned["rebalance_cost"].mean() * 252.0 * 100
    rows = [
        {
            "component": "QQQ buy hold",
            "cagr_or_drag": _pct(qqq_cagr),
            "explanation": "benchmark",
        },
        {
            "component": "Base top5+QQQ",
            "cagr_or_drag": _pct(base_cagr),
            "explanation": "selection + QQQ floor before dynamic exposure",
        },
        {
            "component": "Gross vol-target",
            "cagr_or_drag": _pct(gross_cagr),
            "explanation": "base returns multiplied by dynamic exposure before costs",
        },
        {
            "component": "Financing drag",
            "cagr_or_drag": _pct(-annual_financing),
            "explanation": "annualized borrow cost approximation",
        },
        {
            "component": "Rebalance cost",
            "cagr_or_drag": _pct(-annual_rebalance_cost),
            "explanation": "annualized exposure-change cost approximation",
        },
        {
            "component": "Net vol-target",
            "cagr_or_drag": _pct(net_cagr),
            "explanation": "after financing and rebalancing costs",
        },
    ]
    return pd.DataFrame(rows)


def format_year_contribution(frame: pd.DataFrame, ascending: bool) -> pd.DataFrame:
    table = frame.sort_values("excess_return", ascending=ascending).head(5).copy()
    table["strategy_return"] = table["strategy_return"].map(_pct)
    table["qqq_return"] = table["qqq_return"].map(_pct)
    table["excess_return"] = table["excess_return"].map(_pct)
    return table.loc[
        :,
        ["year", "strategy_return", "qqq_return", "excess_return", "days"],
    ]


def format_leave_one_out(frame: pd.DataFrame) -> pd.DataFrame:
    table = frame.sort_values("excess_cagr").copy()
    table["strategy_cagr"] = table["strategy_cagr"].map(_pct)
    table["qqq_cagr"] = table["qqq_cagr"].map(_pct)
    table["excess_cagr"] = table["excess_cagr"].map(_pct)
    return table.head(8).loc[
        :,
        ["removed_year", "strategy_cagr", "qqq_cagr", "excess_cagr"],
    ]


def cagr(returns: pd.Series) -> float:
    growth = float((1.0 + returns).prod())
    years = len(returns) / 252.0
    return growth ** (1.0 / years) - 1.0 if years > 0 else float("nan")


def max_drawdown(returns: pd.Series) -> float:
    equity = (1.0 + returns).cumprod()
    return float((equity / equity.cummax() - 1.0).min()) * 100


def sharpe(returns: pd.Series) -> float:
    std = float(returns.std())
    return float(returns.mean() / std * (252.0**0.5)) if std > 0 else float("nan")


def _pct(value: float) -> str:
    return f"{float(value):.2f}%"


if __name__ == "__main__":
    main()
