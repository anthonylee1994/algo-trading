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
    build_target_weights,
    fetch_yahoo_chart,
    run_bt_backtest,
)


TRADING_DAYS = 252


@dataclass(frozen=True)
class ReturnCase:
    name: str
    returns: pd.Series
    exposure: pd.Series
    note: str


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--start", default="2010-01-01")
    parser.add_argument("--end", default=None)
    parser.add_argument("--benchmark", default="QQQ")
    parser.add_argument("--cost-bps", type=float, default=15.0)
    parser.add_argument("--financing-rate", type=float, default=0.03)
    parser.add_argument("--output-csv", default="output/vol_target_secret.csv")
    args = parser.parse_args()

    close_prices = load_close_prices(args.start, args.end, args.benchmark)
    qqq_returns = close_prices[args.benchmark].pct_change().dropna()
    top5_returns = build_top5_momentum_returns(
        close_prices=close_prices,
        benchmark=args.benchmark,
        cost_bps=args.cost_bps,
    )
    cases = build_return_cases(
        qqq_returns=qqq_returns,
        top5_returns=top5_returns,
        financing_rate=args.financing_rate,
        cost_bps=args.cost_bps,
    )
    rows = [
        summarize_case(
            case,
            financing_rate=args.financing_rate,
            cost_bps=args.cost_bps,
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

    print("Vol-target secret research")
    print(f"Period: {result['Start'].iloc[0]} to {result['End'].iloc[0]}")
    print(
        f"Financing: {args.financing_rate * 100:.1f}%/yr; "
        f"exposure change cost: {args.cost_bps:.1f} bps"
    )
    print()
    print(
        format_bordered_table(
            result.assign(
                CAGR=result["CAGR"].map(_pct),
                MaxDD=result["MaxDD"].map(_pct),
                Sharpe=result["Sharpe"].map(lambda value: f"{value:.2f}"),
                Vol=result["Vol"].map(_pct),
                AvgExpo=result["AvgExpo"].map(lambda value: f"{value:.2f}x"),
                LowVolExpo=result["LowVolExpo"].map(lambda value: f"{value:.2f}x"),
                HighVolExpo=result["HighVolExpo"].map(lambda value: f"{value:.2f}x"),
                FinancingDrag=result["FinancingDrag"].map(_pct),
                RebalanceCost=result["RebalanceCost"].map(_pct),
            ).loc[
                :,
                [
                    "Case",
                    "CAGR",
                    "MaxDD",
                    "Sharpe",
                    "Vol",
                    "AvgExpo",
                    "LowVolExpo",
                    "HighVolExpo",
                    "FinancingDrag",
                    "RebalanceCost",
                    "Note",
                ],
            ]
        )
    )
    print()
    print(f"CSV: {output_path}")


def load_close_prices(start: str, end: str | None, benchmark: str) -> pd.DataFrame:
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
    ).sort_index()
    close_prices.index = pd.to_datetime(close_prices.index)
    return close_prices


def build_top5_momentum_returns(
    close_prices: pd.DataFrame,
    benchmark: str,
    cost_bps: float,
) -> pd.Series:
    kind, loaded = load_market_cap_universe(DEFAULT_MARKET_CAP_UNIVERSE_PATH)
    if kind != "annual":
        raise RuntimeError("expected checked-in annual market-cap universe")
    universe_symbols = sorted({symbol for symbols in loaded.values() for symbol in symbols})
    weights = build_target_weights(
        close_prices=close_prices,
        symbols=universe_symbols,
        universe_resolver=lambda date: symbols_for_date(
            date,
            universe_symbols,
            loaded,
            lag_years=1,
        ),
        lookback_days=126,
        top_n=5,
        index_floor=benchmark,
    )
    result = run_bt_backtest(
        close_prices=close_prices.loc[:, sorted(set(weights.columns) | {benchmark})],
        weights=weights,
        benchmark_symbol=benchmark,
        initial_cash=100_000,
        cost_bps=cost_bps,
        rebalance="monthly",
    )
    return result.prices["Momentum Rotation"].dropna().pct_change().dropna()


def build_return_cases(
    qqq_returns: pd.Series,
    top5_returns: pd.Series,
    financing_rate: float,
    cost_bps: float,
) -> list[ReturnCase]:
    cases = [
        constant_exposure_case("QQQ buy hold", qqq_returns, 1.0, financing_rate),
        constant_exposure_case("QQQ fixed 1.15x", qqq_returns, 1.15, financing_rate),
        constant_exposure_case("QQQ fixed 1.5x", qqq_returns, 1.5, financing_rate),
        constant_exposure_case("Top5 + QQQ base", top5_returns, 1.0, financing_rate),
        constant_exposure_case("Top5 + QQQ fixed 1.15x", top5_returns, 1.15, financing_rate),
    ]
    for base_name, returns in [
        ("QQQ", qqq_returns),
        ("Top5 + QQQ", top5_returns),
    ]:
        for target_vol in [0.18, 0.22, 0.26, 0.30]:
            cases.append(
                vol_target_case(
                    name=f"{base_name} VT {int(target_vol * 100)} cap2",
                    base_returns=returns,
                    target_vol=target_vol,
                    vol_window=40,
                    max_leverage=2.0,
                    financing_rate=financing_rate,
                    cost_bps=cost_bps,
                    rebal_band=0.05,
                )
            )
        cases.append(
            vol_target_case(
                name=f"{base_name} VT 26 cap1",
                base_returns=returns,
                target_vol=0.26,
                vol_window=40,
                max_leverage=1.0,
                financing_rate=financing_rate,
                cost_bps=cost_bps,
                rebal_band=0.05,
            )
        )
        cases.append(
            vol_target_case(
                name=f"{base_name} VT 26 cap1.5",
                base_returns=returns,
                target_vol=0.26,
                vol_window=40,
                max_leverage=1.5,
                financing_rate=financing_rate,
                cost_bps=cost_bps,
                rebal_band=0.05,
            )
        )
    return cases


def constant_exposure_case(
    name: str,
    base_returns: pd.Series,
    exposure: float,
    financing_rate: float,
) -> ReturnCase:
    expo = pd.Series(exposure, index=base_returns.index)
    returns = apply_exposure_returns(
        base_returns=base_returns,
        exposure=expo,
        financing_rate=financing_rate,
        cost_bps=0.0,
    )
    return ReturnCase(
        name=name,
        returns=returns,
        exposure=expo.reindex(returns.index),
        note=f"constant {exposure:g}x",
    )


def vol_target_case(
    name: str,
    base_returns: pd.Series,
    target_vol: float,
    vol_window: int,
    max_leverage: float,
    financing_rate: float,
    cost_bps: float,
    rebal_band: float,
) -> ReturnCase:
    realized_vol = base_returns.rolling(vol_window).std() * (TRADING_DAYS**0.5)
    raw_exposure = (target_vol / realized_vol).replace([float("inf"), -float("inf")], pd.NA)
    target_exposure = raw_exposure.clip(lower=0.0, upper=max_leverage)
    # 用今日收市計到嘅波幅，下一日先用，避免前視。
    target_exposure = target_exposure.shift(1).fillna(0.0)
    exposure = apply_rebalance_band(target_exposure, rebal_band)
    returns = apply_exposure_returns(
        base_returns=base_returns,
        exposure=exposure,
        financing_rate=financing_rate,
        cost_bps=cost_bps,
    )
    return ReturnCase(
        name=name,
        returns=returns,
        exposure=exposure.reindex(returns.index),
        note=f"target {target_vol:.0%}, cap {max_leverage:g}x, window {vol_window}D",
    )


def apply_rebalance_band(target_exposure: pd.Series, rebal_band: float) -> pd.Series:
    current = 0.0
    values = []
    for target in target_exposure.fillna(0.0):
        target = float(target)
        if abs(target - current) > rebal_band:
            current = target
        values.append(current)
    return pd.Series(values, index=target_exposure.index)


def apply_exposure_returns(
    base_returns: pd.Series,
    exposure: pd.Series,
    financing_rate: float,
    cost_bps: float,
) -> pd.Series:
    aligned = pd.concat(
        [base_returns.rename("base"), exposure.rename("exposure")],
        axis=1,
        join="inner",
    ).dropna()
    borrow = aligned["exposure"].sub(1.0).clip(lower=0.0)
    financing = borrow * financing_rate / TRADING_DAYS
    exposure_turnover = aligned["exposure"].diff().abs().fillna(aligned["exposure"].abs())
    rebalance_cost = exposure_turnover * max(cost_bps, 0.0) / 10_000.0
    return aligned["exposure"] * aligned["base"] - financing - rebalance_cost


def summarize_case(
    case: ReturnCase,
    financing_rate: float,
    cost_bps: float,
) -> dict[str, object]:
    returns = case.returns.dropna()
    equity = (1.0 + returns).cumprod()
    exposure = case.exposure.reindex(returns.index).fillna(0.0)
    vol = returns.std() * (TRADING_DAYS**0.5)
    base_vol = returns.rolling(40).std() * (TRADING_DAYS**0.5)
    low_vol_cutoff = base_vol.quantile(0.25)
    high_vol_cutoff = base_vol.quantile(0.75)
    low_vol_expo = exposure[base_vol <= low_vol_cutoff].mean()
    high_vol_expo = exposure[base_vol >= high_vol_cutoff].mean()
    borrow = exposure.sub(1.0).clip(lower=0.0)
    financing_drag = float(
        (borrow * financing_rate / TRADING_DAYS).sum() / len(returns) * TRADING_DAYS
    )
    rebal_cost = float(
        (
            exposure.diff().abs().fillna(exposure.abs())
            * max(cost_bps, 0.0)
            / 10_000.0
        ).sum()
        / len(returns)
        * TRADING_DAYS
    )
    return {
        "Case": case.name,
        "Start": str(returns.index[0].date()),
        "End": str(returns.index[-1].date()),
        "CAGR": cagr(returns) * 100,
        "MaxDD": max_drawdown(equity) * 100,
        "Sharpe": sharpe(returns),
        "Vol": vol * 100,
        "AvgExpo": float(exposure.mean()),
        "LowVolExpo": float(low_vol_expo),
        "HighVolExpo": float(high_vol_expo),
        "FinancingDrag": financing_drag * 100,
        "RebalanceCost": rebal_cost * 100,
        "Note": case.note,
    }


def cagr(returns: pd.Series) -> float:
    growth = float((1.0 + returns).prod())
    years = len(returns) / TRADING_DAYS
    return growth ** (1.0 / years) - 1.0


def max_drawdown(equity: pd.Series) -> float:
    return float((equity / equity.cummax() - 1.0).min())


def sharpe(returns: pd.Series) -> float:
    std = float(returns.std())
    if std <= 0:
        return float("nan")
    return float(returns.mean() / std * (TRADING_DAYS**0.5))


def _pct(value: float) -> str:
    return f"{float(value):.2f}%"


if __name__ == "__main__":
    main()
