from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path
import sys

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from algo_trading.momentum_rotation import format_bordered_table
from scripts.backtest_momentum_rotation import (
    apply_exposure_returns,
    build_vol_target_exposure,
    fetch_yahoo_chart,
)


TRADING_DAYS = 252


@dataclass(frozen=True)
class Case:
    name: str
    returns: pd.Series
    exposure: pd.Series
    note: str


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--start", default="2010-01-01")
    parser.add_argument("--end", default=None)
    parser.add_argument("--symbols", nargs="+", default=["QQQ", "QLD", "TQQQ"])
    parser.add_argument("--financing-rate", type=float, default=0.03)
    parser.add_argument("--cost-bps", type=float, default=15.0)
    parser.add_argument("--output-csv", default="output/leveraged_etf_vol_target.csv")
    args = parser.parse_args()

    prices = load_prices(args.symbols, args.start, args.end)
    cases = build_cases(
        prices=prices,
        financing_rate=args.financing_rate,
        cost_bps=args.cost_bps,
    )
    rows = [summarize_case(case) for case in cases]
    output = pd.DataFrame(rows).sort_values(
        by=["cagr", "max_drawdown"],
        ascending=[False, False],
    )
    output_path = Path(args.output_csv)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output.to_csv(output_path, index=False)

    print("Leveraged ETF vol-target research")
    print(f"Period: {output['start'].iloc[0]} to {output['end'].iloc[0]}")
    print()
    print(format_bordered_table(format_rows(output)))
    print()
    print(f"CSV: {output_path}")


def load_prices(symbols: list[str], start: str, end: str | None) -> pd.DataFrame:
    charts = {symbol: fetch_yahoo_chart(symbol, start, end) for symbol in symbols}
    prices = pd.concat(
        [charts[symbol]["adj_close"].rename(symbol) for symbol in symbols],
        axis=1,
        join="outer",
    ).sort_index().ffill().dropna(how="all")
    prices.index = pd.to_datetime(prices.index)
    return prices


def build_cases(
    prices: pd.DataFrame,
    financing_rate: float,
    cost_bps: float,
) -> list[Case]:
    cases: list[Case] = []
    qqq_returns = prices["QQQ"].pct_change().dropna() if "QQQ" in prices else None
    for symbol in prices.columns:
        returns = prices[symbol].pct_change().dropna()
        cases.append(
            Case(
                name=f"{symbol} buy hold",
                returns=returns,
                exposure=pd.Series(1.0, index=returns.index),
                note="actual ETF price; no external leverage",
            )
        )
        for target_vol in [0.30, 0.45, 0.60]:
            for max_leverage in [1.0, 1.5]:
                exposure = build_vol_target_exposure(
                    base_returns=returns,
                    target_vol=target_vol,
                    vol_window=40,
                    max_leverage=max_leverage,
                    rebal_band=0.05,
                )
                vt_returns = apply_exposure_returns(
                    base_returns=returns,
                    exposure=exposure,
                    financing_rate=financing_rate,
                    cost_bps=cost_bps,
                )
                cases.append(
                    Case(
                        name=f"{symbol} VT{int(target_vol * 100)} cap{max_leverage:g}",
                        returns=vt_returns,
                        exposure=exposure.reindex(vt_returns.index).fillna(0.0),
                        note="vol-target on actual ETF returns",
                    )
                )
        if symbol == "QQQ":
            continue
        for sma_days in [100, 200]:
            trend = prices["QQQ"] > prices["QQQ"].rolling(sma_days).mean()
            shifted_trend = trend.shift(1).reindex(returns.index).fillna(False)
            cash_returns = returns.where(shifted_trend, 0.0)
            cases.append(
                Case(
                    name=f"{symbol} QQQ>{sma_days}D else cash",
                    returns=apply_turnover_cost(
                        cash_returns,
                        shifted_trend.astype(float),
                        cost_bps,
                    ),
                    exposure=shifted_trend.astype(float),
                    note=f"hold {symbol} only when QQQ above {sma_days}D SMA",
                )
            )
            if qqq_returns is not None:
                aligned = pd.concat(
                    [returns.rename(symbol), qqq_returns.rename("QQQ"), shifted_trend.rename("trend")],
                    axis=1,
                    join="inner",
                ).dropna()
                fallback_returns = aligned[symbol].where(aligned["trend"], aligned["QQQ"])
                position_code = pd.Series(
                    [1.0 if value else 0.5 for value in aligned["trend"]],
                    index=aligned.index,
                )
                cases.append(
                    Case(
                        name=f"{symbol} QQQ>{sma_days}D else QQQ",
                        returns=apply_turnover_cost(
                            fallback_returns,
                            position_code,
                            cost_bps,
                        ),
                        exposure=position_code,
                        note=f"risk-off switches from {symbol} to QQQ",
                    )
                )
    return cases


def apply_turnover_cost(
    returns: pd.Series,
    position_code: pd.Series,
    cost_bps: float,
) -> pd.Series:
    turnover = position_code.diff().abs().fillna(position_code.abs())
    cost = turnover * max(cost_bps, 0.0) / 10_000.0
    return returns.reindex(cost.index).fillna(0.0) - cost


def summarize_case(case: Case) -> dict[str, object]:
    returns = case.returns.dropna()
    equity = (1.0 + returns).cumprod()
    exposure = case.exposure.reindex(returns.index).fillna(0.0)
    return {
        "case": case.name,
        "start": returns.index[0].date().isoformat(),
        "end": returns.index[-1].date().isoformat(),
        "cagr": cagr(returns) * 100,
        "max_drawdown": max_drawdown(equity) * 100,
        "sharpe": sharpe(returns),
        "vol": float(returns.std() * (TRADING_DAYS**0.5) * 100),
        "avg_exposure": float(exposure.mean()),
        "low_exposure": float(exposure.quantile(0.75)),
        "high_vol_exposure": float(exposure.quantile(0.25)),
        "note": case.note,
    }


def cagr(returns: pd.Series) -> float:
    growth = float((1.0 + returns).prod())
    years = len(returns) / TRADING_DAYS
    return growth ** (1.0 / years) - 1.0 if years > 0 and growth > 0 else float("nan")


def max_drawdown(equity: pd.Series) -> float:
    return float((equity / equity.cummax() - 1.0).min())


def sharpe(returns: pd.Series) -> float:
    std = float(returns.std())
    return float(returns.mean() / std * (TRADING_DAYS**0.5)) if std > 0 else float("nan")


def format_rows(frame: pd.DataFrame) -> pd.DataFrame:
    return frame.assign(
        cagr=frame["cagr"].map(lambda value: f"{value:.2f}%"),
        max_drawdown=frame["max_drawdown"].map(lambda value: f"{value:.2f}%"),
        sharpe=frame["sharpe"].map(lambda value: f"{value:.2f}"),
        vol=frame["vol"].map(lambda value: f"{value:.2f}%"),
        avg_exposure=frame["avg_exposure"].map(lambda value: f"{value:.2f}x"),
    ).loc[
        :,
        [
            "case",
            "cagr",
            "max_drawdown",
            "sharpe",
            "vol",
            "avg_exposure",
            "note",
        ],
    ]


if __name__ == "__main__":
    main()
