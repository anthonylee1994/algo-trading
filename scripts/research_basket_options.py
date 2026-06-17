"""無槓桿高-IV basket option-income 研究 —— 用高 IV underlying 放大 VRP premium。

QQQ（IV ~22%）covered call 嘅 premium 淨收益太薄（edge 10% haircut 就消失）。
本節用**高 IV mega-cap basket**（NVDA/TSLA/AMD/META/NFLX 等，IV 35-60%）做
covered call／put-write —— premium yield 翻倍，令 raw-CAGR edge 對 haircut 更 robust。

關鍵設計（無前視、無 survivorship）：
- universe：每年滯後市值 top-10（同主策略個池，point-in-time，無 membership 前視）。
- IV proxy：**前 60 個交易日 realized vol × iv_mult**（lagged，月初未知未來，無前視）。
  iv_mult>1 模擬 IV>realized（VRP），default 1.10。
- 每月 roll，每隻成份 equal weight；covered call = 揸實股（無借貸）+ sell call。
- premium × haircut 模擬 bid-ask / skew。
- 信號 shift(1)（用月初已知資料）。

建模 caveat：IV proxy 係 lagged realized vol（唔係真實 option chain IV），誤差 ~15-25%；
covered call 嘅 crash 風險 = 揸股票本身（已含喺 actual return），所以呢部分乾淨；
premium 估計嘅系統誤差用 haircut + iv_mult sensitivity 控制。
"""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

import numpy as np
import pandas as pd
from scipy.stats import norm

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from algo_trading.momentum_rotation import format_bordered_table

TRADING_DAYS = 252


def bs_call(S, K, T, r, sigma):
    if sigma <= 0:
        return max(S - K, 0.0)
    d1 = (np.log(S / K) + (r + 0.5 * sigma**2) * T) / (sigma * np.sqrt(T))
    d2 = d1 - sigma * np.sqrt(T)
    return S * norm.cdf(d1) - K * np.exp(-r * T) * norm.cdf(d2)


def bs_put(S, K, T, r, sigma):
    if sigma <= 0:
        return max(K - S, 0.0)
    d1 = (np.log(S / K) + (r + 0.5 * sigma**2) * T) / (sigma * np.sqrt(T))
    d2 = d1 - sigma * np.sqrt(T)
    return K * np.exp(-r * T) * norm.cdf(-d2) - S * norm.cdf(-d1)


def load_prices(path: Path) -> pd.DataFrame:
    frame = pd.read_csv(path)
    date_col = frame.columns[0]
    frame[date_col] = pd.to_datetime(frame[date_col])
    return frame.set_index(date_col).sort_index().astype(float)


def lagged_realized_vol(prices: pd.DataFrame, window: int, ppy: int = 252) -> pd.DataFrame:
    """每日：過去 window 日 realized vol（已 shift 1，無前視）。"""
    logret = np.log(prices / prices.shift(1))
    rvol = logret.rolling(window).std() * np.sqrt(ppy)
    return rvol.shift(1)  # 用到 t-1 嘅資料計 t 嘅 IV


def basket_option_backtest(
    prices: pd.DataFrame,
    membership_mask: pd.DataFrame,
    members: list[str],
    moneyness: float,
    option: str,
    iv_window: int,
    iv_mult: float,
    haircut: float,
    rf: float,
    dte: int,
    cost_bps: float,
) -> tuple[pd.Series, float]:
    """回測 basket covered-call / put-write，回傳（月度 portfolio return, 平均曝險）。"""
    rvol = lagged_realized_vol(prices[members], iv_window) * iv_mult
    # 月度 rebalance：用每月最後交易日嘅 IV / membership 為下個月定倉，shift(1)
    monthly_iv = rvol.resample("ME").last()
    monthly_mask = membership_mask.reindex(rvol.index).resample("ME").last().fillna(False)
    monthly_prices = prices.reindex(rvol.index).resample("ME").last()
    # 對齊到「下個月生效」：shift 1（用本月末已知資料，下月成交）
    iv_eff = monthly_iv.shift(1)
    mask_eff = monthly_mask.shift(1).fillna(False)
    px_eff = monthly_prices  # return 用相鄰月末價

    rets = px_eff.pct_change()
    T = dte / 365.0
    K_factor = moneyness
    cost = cost_bps / 1e4

    port_rows = []
    exposures = []
    for i in range(1, len(rets)):
        date = rets.index[i]
        active = [s for s in members if mask_eff.at[date, s] if s in rets.columns]
        if not active:
            port_rows.append((date, 0.0))
            continue
        per_stock_rets = []
        for s in active:
            r = rets.at[date, s]
            sigma = iv_eff.at[date, s]
            if not np.isfinite(sigma) or sigma <= 0 or not np.isfinite(r):
                continue
            if option == "call":
                prem = bs_call(1.0, K_factor, T, rf, sigma) * haircut
                capped = max(0.0, r - (K_factor - 1.0))
                per_stock_rets.append(r + prem - capped - cost)
            else:  # put-write，cash 擔保
                prem = bs_put(1.0, K_factor, T, rf, sigma) * haircut
                loss = max(0.0, (K_factor - 1.0) - r)
                per_stock_rets.append(rf * T + prem - loss - cost)
        if per_stock_rets:
            port_rows.append((date, float(np.mean(per_stock_rets))))
            exposures.append(1.0)
        else:
            port_rows.append((date, 0.0))
    series = pd.Series(dict(port_rows))
    return series, float(np.mean(exposures)) if exposures else 0.0


def build_mega_mask(index, schedule, columns):
    from scripts.research_tsmom_no_leverage import build_mega_membership_mask
    return build_mega_membership_mask(index, schedule, columns)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--prices", default="output/sp500_pit_prices.csv")
    parser.add_argument("--mega-json", default="sp500_top_10_market_cap_2010_2026.json")
    parser.add_argument("--start", default="2010-01-01")
    parser.add_argument("--option", choices=["call", "put"], default="call")
    parser.add_argument("--moneyness", type=float, default=1.05)
    parser.add_argument("--iv-window", type=int, default=60)
    parser.add_argument("--iv-mult", type=float, default=1.10)
    parser.add_argument("--haircut", type=float, default=1.0)
    parser.add_argument("--rf", type=float, default=0.02)
    parser.add_argument("--dte", type=int, default=30)
    parser.add_argument("--cost-bps", type=float, default=15.0)
    args = parser.parse_args()

    prices = load_prices(Path(args.prices)).loc[args.start:]
    prices = prices.ffill()
    from algo_trading.market_cap_universe import load_yearly_market_cap_universe
    schedule = load_yearly_market_cap_universe(Path(args.mega_json))
    members = sorted({s for syms in schedule.values() for s in syms if s in prices.columns})
    mask = build_mega_mask(prices.index, schedule, prices.columns)

    port, avg_exp = basket_option_backtest(
        prices, mask, members, args.moneyness, args.option,
        args.iv_window, args.iv_mult, args.haircut, args.rf, args.dte, args.cost_bps,
    )
    bench = prices["QQQ"].resample("ME").last().pct_change().dropna()
    common = port.index.intersection(bench.index)
    port, bench = port.loc[common], bench.loc[common]

    opt_label = "covered call" if args.option == "call" else "put-write"
    label = (f"mega top-10 {opt_label} K={args.moneyness:.0%} ivw={args.iv_window} "
             f"ivm={args.iv_mult} h={args.haircut}")
    print(f"\n=== {label} ===")
    print(f"Period {common[0].date()} → {common[-1].date()}｜平均曝險 {avg_exp*100:.0f}%｜universe {len(members)} 隻")
    rows = [
        _stats_row(f"basket {opt_label}", port, ppy=12),
        _stats_row("長揸 QQQ（月度）", bench, ppy=12),
    ]
    summary = pd.DataFrame(rows)
    for c in ["CAGR", "年化波幅", "Sharpe", "最大回撤", "Calmar", "總回報"]:
        summary[c] = summary[c].map(_fmt(c))
    print(format_bordered_table(summary))
    pc, bc = _cagr(port, 12) * 100, _cagr(bench, 12) * 100
    ps, bs = _sharpe(port, 12), _sharpe(bench, 12)
    tag = "✅ 雙贏" if pc > bc and ps > bs else ("⚠️ CAGR 贏" if pc > bc else "❌ 輸 CAGR")
    print(f"{tag}：portfolio CAGR {pc:.1f}% vs QQQ {bc:.1f}%，Sharpe {ps:.2f} vs {bs:.2f}")


def _stats_row(name, returns, ppy=252):
    returns = returns.dropna()
    dd = _max_drawdown(returns)
    cagr = _cagr(returns, ppy)
    return {
        "策略": name, "CAGR": cagr * 100,
        "年化波幅": float(returns.std() * np.sqrt(ppy)) * 100,
        "Sharpe": _sharpe(returns, ppy), "最大回撤": dd * 100,
        "Calmar": (cagr / abs(dd)) if dd < 0 else float("nan"),
        "總回報": _period_return(returns) * 100,
    }


def _sharpe(r, ppy=252):
    if r.empty or r.std() == 0:
        return float("nan")
    return float(r.mean() / r.std() * np.sqrt(ppy))


def _cagr(r, ppy=252):
    if r.empty:
        return float("nan")
    g = float((1 + r).prod())
    years = len(r) / ppy
    if years <= 0 or g <= 0:
        return float("nan")
    return g ** (1 / years) - 1


def _max_drawdown(r):
    if r.empty:
        return 0.0
    eq = (1 + r).cumprod()
    return float((eq / eq.cummax() - 1).min())


def _period_return(r):
    if r.empty:
        return float("nan")
    return float((1 + r).prod() - 1)


def _fmt(column):
    if column in ("Sharpe", "Calmar"):
        return lambda v: f"{v:.2f}"
    return lambda v: f"{v:.1f}%"


if __name__ == "__main__":
    main()
