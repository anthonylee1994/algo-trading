"""無槓桿跨資產配置 vs QQQ —— 之前所有研究都係「美股選股 vs QQQ」。

呢個 script 試一個未探索過嘅維度：multi-asset allocation（bonds / gold / commodities /
intl / defensive sectors）。理論支撐：分散化係唯一 free lunch；QQQ 2010-2026 咁強係因為
佢就係嗰段時間嘅贏家 asset，加入低相關 asset 係 long-only 無槓桿下唯一可能提升
risk-adjusted return 嘅路。用 ETF，數據乾淨、無 survivorship bias。

全部策略 long-only、總曝險 ≤ 100%、無借貸、月度 rebalance、15bps 成本、信號 shift(1)。
基準：長揸 QQQ。
"""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from algo_trading.momentum_rotation import format_bordered_table
from scripts.backtest_momentum_rotation import run_bt_backtest

TRADING_DAYS = 252

# 跨資產 universe（唔含 QQQ bench、唔含 BIL cash——佢哋做 benchmark / floor）。
RISK_UNIVERSE = [
    "SPY", "IWM", "EFA", "EEM", "VNQ", "XLU", "XLP",
    "TLT", "IEF", "AGG", "GLD", "DBC",
]
CASH = "BIL"


def load_prices(path: Path) -> pd.DataFrame:
    frame = pd.read_csv(path)
    date_col = frame.columns[0]
    frame[date_col] = pd.to_datetime(frame[date_col])
    return frame.set_index(date_col).sort_index().astype(float)


def momentum_rotation_weights(
    prices: pd.DataFrame,
    universe: list[str],
    lookback: int,
    top_n: int,
    floor: str | None,
) -> pd.DataFrame:
    mom = prices[universe].pct_change(lookback)
    weights = pd.DataFrame(0.0, index=prices.index, columns=prices.columns)
    for date in prices.index:
        m = mom.loc[date].dropna()
        selected = m[m > 0].sort_values(ascending=False).head(top_n).index.tolist()
        for s in selected:
            weights.at[date, s] += 1.0 / top_n
        empty = top_n - len(selected)
        if empty > 0 and floor is not None:
            weights.at[date, floor] += empty / top_n
    return weights.shift(1).fillna(0.0)


def dual_momentum_weights(prices: pd.DataFrame, lookback: int) -> pd.DataFrame:
    """Antonacci dual momentum（簡化）：QQQ 絕對動量 > 0 揸 QQQ，否則避險去 TLT。"""
    qqq_mom = prices["QQQ"].pct_change(lookback)
    weights = pd.DataFrame(0.0, index=prices.index, columns=prices.columns)
    for date in prices.index:
        m = qqq_mom.loc[date]
        if pd.notna(m) and m > 0:
            weights.at[date, "QQQ"] = 1.0
        else:
            weights.at[date, "TLT"] = 1.0
    return weights.shift(1).fillna(0.0)


def risk_parity_weights(
    prices: pd.DataFrame, universe: list[str], vol_window: int
) -> pd.DataFrame:
    vol = prices[universe].pct_change().rolling(vol_window).std()
    inv = 1.0 / vol
    w = inv.div(inv.sum(axis=1), axis=0)
    out = pd.DataFrame(0.0, index=prices.index, columns=prices.columns)
    out[universe] = w
    return out.shift(1).fillna(0.0)


def vol_target_cap1_weights(
    prices: pd.DataFrame,
    symbol: str,
    target_vol: float,
    vol_window: int,
    cash: str,
) -> pd.DataFrame:
    """Vol-target 但 cap 1x（唔借錢）：高波減倉去現金，低波滿倉。純防守，無借貸。"""
    rvol = prices[symbol].pct_change().rolling(vol_window).std() * np.sqrt(TRADING_DAYS)
    exposure = (target_vol / rvol).clip(upper=1.0, lower=0.0)
    weights = pd.DataFrame(0.0, index=prices.index, columns=prices.columns)
    weights[symbol] = exposure
    weights[cash] = 1.0 - exposure
    return weights.shift(1).fillna(0.0)


def fixed_weights(prices: pd.DataFrame, alloc: dict[str, float]) -> pd.DataFrame:
    weights = pd.DataFrame(0.0, index=prices.index, columns=prices.columns)
    for symbol, share in alloc.items():
        weights[symbol] = share
    return weights


def stats_row(name: str, returns: pd.Series) -> dict:
    cagr = _cagr(returns)
    vol = float(returns.std() * np.sqrt(TRADING_DAYS))
    sharpe = _sharpe(returns)
    maxdd = _max_drawdown(returns)
    calmar = cagr / abs(maxdd) if maxdd < 0 else float("nan")
    return {
        "策略": name,
        "CAGR": cagr * 100,
        "年化波幅": vol * 100,
        "Sharpe": sharpe,
        "最大回撤": maxdd * 100,
        "Calmar": calmar,
    }


def _sharpe(returns: pd.Series) -> float:
    if returns.empty or returns.std() == 0:
        return float("nan")
    return float(returns.mean() / returns.std() * np.sqrt(TRADING_DAYS))


def _cagr(returns: pd.Series) -> float:
    if returns.empty:
        return float("nan")
    growth = float((1 + returns).prod())
    years = len(returns) / TRADING_DAYS
    if years <= 0 or growth <= 0:
        return float("nan")
    return growth ** (1 / years) - 1


def _max_drawdown(returns: pd.Series) -> float:
    if returns.empty:
        return 0.0
    equity = (1 + returns).cumprod()
    return float((equity / equity.cummax() - 1).min())


def _fmt(column: str):
    if column in ("Sharpe", "Calmar"):
        return lambda v: f"{v:.2f}"
    return lambda v: f"{v:.1f}%"


def run_strategy(
    name: str,
    weights: pd.DataFrame,
    prices: pd.DataFrame,
    cost_bps: float,
    benchmark: str,
) -> dict:
    bt_result = run_bt_backtest(
        close_prices=prices,
        weights=weights,
        benchmark_symbol=benchmark,
        initial_cash=100_000,
        cost_bps=cost_bps,
        rebalance="monthly",
    )
    strat = bt_result.prices["Momentum Rotation"].dropna().pct_change().dropna()
    bench = bt_result.prices[f"Buy Hold {benchmark}"].dropna().pct_change().dropna()
    common = strat.index.intersection(bench.index)
    strat, bench = strat.loc[common], bench.loc[common]
    row = stats_row(name, strat)
    row["benchmark"] = benchmark
    row["qqq_cagr"] = _cagr(bench) * 100
    row["qqq_sharpe"] = _sharpe(bench)
    row["qqq_maxdd"] = _max_drawdown(bench) * 100
    row["qqq_calmar"] = _cagr(bench) / abs(_max_drawdown(bench))
    return row


def build_strategies(prices: pd.DataFrame) -> list[tuple[str, pd.DataFrame]]:
    lookback = 126
    return [
        ("跨資產動量 top3", momentum_rotation_weights(prices, RISK_UNIVERSE, lookback, 3, CASH)),
        ("跨資產動量 top5", momentum_rotation_weights(prices, RISK_UNIVERSE, lookback, 5, CASH)),
        ("Dual momentum (QQQ/TLT)", dual_momentum_weights(prices, lookback=252)),
        ("Risk parity (inv-vol)", risk_parity_weights(prices, RISK_UNIVERSE, vol_window=63)),
        ("60/40 (SPY/TLT)", fixed_weights(prices, {"SPY": 0.6, "TLT": 0.4})),
        (
            "All-Weather 風格",
            fixed_weights(
                prices, {"SPY": 0.30, "TLT": 0.40, "IEF": 0.15, "GLD": 0.075, "DBC": 0.075}
            ),
        ),
        ("QQQ/TLT 50/50", fixed_weights(prices, {"QQQ": 0.5, "TLT": 0.5})),
        # 高 QQQ 比例 + 少量 defensive —— 搵 CAGR 接近但 DD 更細嘅 Calmar sweet spot。
        ("QQQ 80 / TLT 20", fixed_weights(prices, {"QQQ": 0.8, "TLT": 0.2})),
        ("QQQ 70 / TLT 30", fixed_weights(prices, {"QQQ": 0.7, "TLT": 0.3})),
        ("QQQ 80 / GLD 20", fixed_weights(prices, {"QQQ": 0.8, "GLD": 0.2})),
        ("QQQ 80 / TLT10 / GLD10", fixed_weights(prices, {"QQQ": 0.8, "TLT": 0.1, "GLD": 0.1})),
        # QQQ vol-target cap 1x —— 純減曝險唔借錢。
        ("QQQ VT cap1x (15%)", vol_target_cap1_weights(prices, "QQQ", 0.15, 40, CASH)),
        ("QQQ VT cap1x (20%)", vol_target_cap1_weights(prices, "QQQ", 0.20, 40, CASH)),
    ]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--prices", default="output/multi_asset_prices.csv")
    parser.add_argument("--benchmark", default="QQQ")
    parser.add_argument("--cost-bps", type=float, default=15.0)
    parser.add_argument("--start", default="2010-01-01")
    args = parser.parse_args()

    prices = load_prices(Path(args.prices))
    prices = prices.loc[args.start:]
    if args.benchmark not in prices.columns:
        parser.error(f"benchmark {args.benchmark} 唔喺數據入面。")

    strategies = build_strategies(prices)
    rows = []
    for name, weights in strategies:
        print(f"跑緊：{name} ...", flush=True)
        rows.append(run_strategy(name, weights, prices, args.cost_bps, args.benchmark))

    qqq = rows[0]  # 每個 row 都有同一個 QQQ 數字
    print(
        f"\n無槓桿跨資產配置 vs QQQ（{rows[0]['qqq_cagr']:.1f}% CAGR / "
        f"{rows[0]['qqq_sharpe']:.2f} Sharpe / {rows[0]['qqq_maxdd']:.1f}% DD / "
        f"{rows[0]['qqq_calmar']:.2f} Calmar），{prices.index[0].date()} → "
        f"{prices.index[-1].date()}，月度，{args.cost_bps:.0f}bps：\n"
    )

    summary = pd.DataFrame(rows)[
        ["策略", "CAGR", "年化波幅", "Sharpe", "最大回撤", "Calmar"]
    ]
    for column in ["CAGR", "年化波幅", "Sharpe", "最大回撤", "Calmar"]:
        summary[column] = summary[column].map(_fmt(column))
    print(format_bordered_table(summary))

    print("\nvs QQQ 判斷：")
    bench_cagr, bench_sharpe = qqq["qqq_cagr"], qqq["qqq_sharpe"]
    bench_calmar = qqq["qqq_calmar"]
    for r in rows:
        cagr_beat = r["CAGR"] > bench_cagr
        sharpe_beat = r["Sharpe"] > bench_sharpe
        calmar_beat = r["Calmar"] > bench_calmar
        tags = []
        if cagr_beat:
            tags.append("CAGR✓")
        if sharpe_beat:
            tags.append("Sharpe✓")
        if calmar_beat:
            tags.append("Calmar✓")
        verdict = " ".join(tags) if tags else "全輸 QQQ"
        print(
            f"  {r['策略']:<28} CAGR {r['CAGR']:5.1f}% vs {bench_cagr:5.1f}%  "
            f"Sharpe {r['Sharpe']:.2f} vs {bench_sharpe:.2f}  "
            f"DD {r['最大回撤']:6.1f}% vs {qqq['qqq_maxdd']:5.1f}%  "
            f"Calmar {r['Calmar']:.2f} vs {bench_calmar:.2f}  → {verdict}"
        )


if __name__ == "__main__":
    main()
