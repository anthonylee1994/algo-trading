"""無槓桿 option-income / VRP（volatility risk premium）研究 —— 唯一未試過嘅 alpha class。

之前所有方向都係「揸 underlying 揀股／擇時」。本節試**賣 option 收 premium**：
- covered call（long QQQ + sell call）：收 premium 換放棄部分 upside。
- put-write（cash-secured short put）：收 premium + T-bill 利息，承擔跌市。
- 兩者都**無借貸**（covered call 揸實股；put-write 100% cash 擔保）。

兩層證據：
1. **CBOE 真實 strategy index**（^PUT PutWrite、^BXM BuyWrite，S&P base，2007+）——
   直接 compare option-selling vs buy-hold，無 modeling 假設。
2. **自己 model QQQ covered call / put-write**（Black-Scholes + VXN 做 IV，actual QQQ
   月度回報做 payoff）—— directly on QQQ，可控參數（moneyness、DTE）。

建模限制（誠實 caveats）：BS 假設 lognormal，put-write 喺極端 crash（fat left tail）
嘅實際虧損會大過模型；但 2007-2026 含 2008/2020/2022 real crash，actual 月度回報已
反映尾部，premium 用 VXN（IV）估、payoff 用 actual —— 唯一系統誤差係 BS ATM quote
同實際市場 quote（skew、bid-ask）嘅差，premium 估計誤差約 ±10-20%。
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
RISK_FREE_DEFAULT = 0.02  # T-bill 近年約 0-5%，2007-2026 平均約 2%


def fetch_price(tickers: list[str], start: str, end: str) -> pd.DataFrame:
    import yfinance as yf

    raw = yf.download(tickers, start=start, end=end, progress=False, auto_adjust=True)
    if isinstance(raw.columns, pd.MultiIndex):
        close = raw["Close"]
    else:
        close = raw[["Close"]].rename(columns={"Close": tickers[0]})
    return close.dropna(how="all").sort_index()


def norm_cdf(x: np.ndarray) -> np.ndarray:
    return norm.cdf(x)


def bs_call(S, K, T, r, sigma, q=0.0):
    d1 = (np.log(S / K) + (r - q + 0.5 * sigma**2) * T) / (sigma * np.sqrt(T))
    d2 = d1 - sigma * np.sqrt(T)
    return S * np.exp(-q * T) * norm_cdf(d1) - K * np.exp(-r * T) * norm_cdf(d2)


def bs_put(S, K, T, r, sigma, q=0.0):
    d1 = (np.log(S / K) + (r - q + 0.5 * sigma**2) * T) / (sigma * np.sqrt(T))
    d2 = d1 - sigma * np.sqrt(T)
    return K * np.exp(-r * T) * norm_cdf(-d2) - S * np.exp(-q * T) * norm_cdf(-d1)


def _k_factor(moneyness_mode: str, moneyness: float, sigma_z: float, sigma: float, T: float) -> float:
    """strike 係數（K/S）。fixed = 固定 % OTM；sigma = z-sigma OTM（隨 vol 自動 scale）。"""
    if moneyness_mode == "sigma":
        return float(np.exp(sigma_z * sigma * np.sqrt(T)))
    return float(moneyness)


def monthly_covered_call(qqq_ret: pd.Series, iv: pd.Series, moneyness: float,
                          rf: float, dte: int = 30, premium_haircut: float = 1.0,
                          moneyness_mode: str = "fixed", sigma_z: float = 1.0) -> pd.Series:
    """每月 long QQQ + sell OTM call。

    fixed mode：strike = moneyness * S（固定 % OTM）。
    sigma mode：strike = S * exp(sigma_z * sigma * sqrt(T))（z-sigma OTM，
    低 vol regime 自動賣近收多 premium、高 vol 自動賣遠減 capping）。
    """
    out = pd.Series(index=qqq_ret.index, dtype=float)
    iv_arr = iv.reindex(qqq_ret.index).ffill().bfill().to_numpy()
    T = dte / 365.0
    for i, r in enumerate(qqq_ret.to_numpy()):
        sigma = iv_arr[i]
        if not np.isfinite(sigma) or sigma <= 0:
            out.iloc[i] = r
            continue
        K_factor = _k_factor(moneyness_mode, moneyness, sigma_z, sigma, T)
        # premium = BS call（S=1 notional, K=moneyness）作為 notional 比例
        prem = bs_call(1.0, K_factor, T, rf, sigma) * premium_haircut
        capped = max(0.0, r - (K_factor - 1.0))  # 放棄 strike 以上 upside
        out.iloc[i] = r + prem - capped
    return out


def monthly_put_write(qqq_ret: pd.Series, iv: pd.Series, moneyness: float,
                       rf: float, dte: int = 30, premium_haircut: float = 1.0,
                       moneyness_mode: str = "fixed", sigma_z: float = 1.0) -> pd.Series:
    """每月 cash-secured short put。cash 擔保收 T-bill。"""
    out = pd.Series(index=qqq_ret.index, dtype=float)
    iv_arr = iv.reindex(qqq_ret.index).ffill().bfill().to_numpy()
    T = dte / 365.0
    for i, r in enumerate(qqq_ret.to_numpy()):
        sigma = iv_arr[i]
        if not np.isfinite(sigma) or sigma <= 0:
            out.iloc[i] = rf * T  # fallback: cash
            continue
        K_factor = _k_factor(moneyness_mode, moneyness, sigma_z, sigma, T)
        prem = bs_put(1.0, K_factor, T, rf, sigma) * premium_haircut
        loss = max(0.0, (K_factor - 1.0) - r)  # put assigned：跌市虧損
        out.iloc[i] = rf * T + prem - loss
    return out


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--start", default="2007-01-01")
    parser.add_argument("--end", default="2026-06-17")
    parser.add_argument("--rf", type=float, default=RISK_FREE_DEFAULT)
    parser.add_argument("--dte", type=int, default=30)
    parser.add_argument("--freq", choices=["monthly", "weekly"], default="monthly",
                        help="option roll 頻率（weekly = 7DTE short-dated，premium/√T 但 roll 52x）。")
    parser.add_argument("--moneyness", type=float, nargs="+",
                        default=[1.0, 1.02, 1.05, 1.10, 1.15])
    parser.add_argument("--moneyness-mode", choices=["fixed", "sigma"], default="fixed",
                        help="fixed = 固定百分比 OTM；sigma = z-sigma OTM（隨 vol scale）。")
    parser.add_argument("--sigma-z", type=float, default=1.0,
                        help="sigma mode 下嘅 OTM sigma 倍數（1.0 = 1σ OTM）。")
    parser.add_argument("--premium-haircut", type=float, default=1.0,
                        help="BS premium 乘呢個系數（0.8 = 模擬兩成 bid-ask/slippage）。")
    parser.add_argument("--cost-bps", type=float, default=15.0)
    parser.add_argument("--no-fetch", action="store_true",
                        help="skip yfinance；要用 output/option_income_index.csv（要先存）。")
    args = parser.parse_args()

    if args.no_fetch:
        idx = pd.read_csv("output/option_income_index.csv", index_col=0, parse_dates=True)
    else:
        tickers = ["QQQ", "^GSPC", "^PUT", "^BXM", "^VXN", "^VIX", "^IRX"]
        idx = fetch_price(tickers, args.start, args.end)
        idx.to_csv("output/option_income_index.csv")
        print(f"已存 output/option_income_index.csv（{idx.index[0].date()} → {idx.index[-1].date()}）")
    idx = idx.loc[args.start:]

    # --- Part 1: CBOE 真實 index comparison ---
    print("\n" + "=" * 78)
    print("Part 1：CBOE 真實 strategy index vs buy-hold（無 modeling 假設）")
    print("=" * 78)
    daily = idx.pct_change().dropna()
    rows = []
    for col in ["QQQ", "^GSPC", "^PUT", "^BXM"]:
        if col not in daily.columns:
            continue
        s = daily[col].dropna()
        label = {"QQQ": "QQQ（買揸）", "^GSPC": "S&P 500（買揸）",
                 "^PUT": "PUT 指數（賣 ATM put）", "^BXM": "BXM 指數（covered call）"}[col]
        rows.append(_stats_row(label, s, ppy=252))
    summary = pd.DataFrame(rows)
    for c in ["CAGR", "年化波幅", "Sharpe", "最大回撤", "Calmar", "總回報"]:
        summary[c] = summary[c].map(_fmt(c))
    print(format_bordered_table(summary))

    # --- Part 2: QQQ covered call / put-write model ---
    print("\n" + "=" * 78)
    print(f"Part 2：QQQ option-income model（BS + VXN 做 IV，actual QQQ 月度 payoff，rf={args.rf:.1%}）")
    print("=" * 78)
    qqq = idx["QQQ"].dropna()
    vxn = (idx["^VXN"].dropna() / 100.0) if "^VXN" in idx.columns else None
    vix = (idx["^VIX"].dropna() / 100.0) if "^VIX" in idx.columns else None
    # 用 VIX fallback 若 VXN 缺（早期）
    if vxn is not None and vix is not None:
        vol = vxn.reindex(qqq.index).ffill()
    else:
        vol = (vxn or vix).reindex(qqq.index).ffill()

    freq_rule = "W-FRI" if args.freq == "weekly" else "ME"
    qqq_m = qqq.resample(freq_rule).last()
    qqq_m_ret = qqq_m.pct_change().dropna()
    vol_m = vol.reindex(qqq.index).groupby(pd.Grouper(freq=freq_rule)).last().reindex(qqq_m_ret.index).ffill()
    cost = args.cost_bps / 1e4
    dte = 7 if args.freq == "weekly" else args.dte
    ppy = 52 if args.freq == "weekly" else 12
    freq_label = "週度" if args.freq == "weekly" else "月度"

    rows2 = [_stats_row(f"QQQ（買揸，{freq_label}）", qqq_m_ret, ppy=ppy)]
    for m in args.moneyness:
        cc = monthly_covered_call(qqq_m_ret, vol_m, m, args.rf, dte, args.premium_haircut,
                                  args.moneyness_mode, args.sigma_z)
        cc = cc - cost  # 每次 roll 成本
        klab = f"σ{args.sigma_z:g}" if args.moneyness_mode == "sigma" else f"{m:.0%}"
        rows2.append(_stats_row(f"QQQ covered call K={klab}", cc, ppy=ppy))
    for m in args.moneyness:
        pw = monthly_put_write(qqq_m_ret, vol_m, m, args.rf, dte, args.premium_haircut,
                               args.moneyness_mode, args.sigma_z)
        pw = pw - cost
        klab = f"σ{args.sigma_z:g}" if args.moneyness_mode == "sigma" else f"{m:.0%}"
        rows2.append(_stats_row(f"QQQ put-write K={klab}", pw, ppy=ppy))
    summary2 = pd.DataFrame(rows2)
    for c in ["CAGR", "年化波幅", "Sharpe", "最大回撤", "Calmar", "總回報"]:
        summary2[c] = summary2[c].map(_fmt(c))
    print(format_bordered_table(summary2))

    bench_cagr = _cagr(qqq_m_ret, ppy) * 100
    bench_sharpe = _sharpe(qqq_m_ret, ppy)
    print(f"\n基準 QQQ：CAGR {bench_cagr:.1f}% / Sharpe {bench_sharpe:.2f}")
    for _, r in summary2.iloc[1:].iterrows():
        tag = "✅ 雙贏" if r["CAGR_num"] > bench_cagr and r["Sharpe_num"] > bench_sharpe else (
              "⚠️ CAGR 贏" if r["CAGR_num"] > bench_cagr else "❌ 輸 CAGR")
        print(f"  {r['策略']:28s} CAGR {r['CAGR']:>7s} Sharpe {r['Sharpe']:>5s} DD {r['最大回撤']:>7s} → {tag}")


def _stats_row(name: str, returns: pd.Series, ppy: int = 252) -> dict:
    returns = returns.dropna()
    dd = _max_drawdown(returns)
    cagr = _cagr(returns, ppy)
    return {
        "策略": name,
        "CAGR": cagr * 100,
        "CAGR_num": cagr * 100,
        "Sharpe_num": _sharpe(returns, ppy),
        "年化波幅": float(returns.std() * np.sqrt(ppy)) * 100,
        "Sharpe": _sharpe(returns, ppy),
        "最大回撤": dd * 100,
        "Calmar": (cagr / abs(dd)) if dd < 0 else float("nan"),
        "總回報": _period_return(returns) * 100,
    }


def _sharpe(returns: pd.Series, ppy: int = 252) -> float:
    if returns.empty or returns.std() == 0:
        return float("nan")
    return float(returns.mean() / returns.std() * np.sqrt(ppy))


def _cagr(returns: pd.Series, ppy: int = 252) -> float:
    if returns.empty:
        return float("nan")
    growth = float((1 + returns).prod())
    years = len(returns) / ppy
    if years <= 0 or growth <= 0:
        return float("nan")
    return growth ** (1 / years) - 1


def _max_drawdown(returns: pd.Series) -> float:
    if returns.empty:
        return 0.0
    equity = (1 + returns).cumprod()
    return float((equity / equity.cummax() - 1).min())


def _period_return(returns: pd.Series) -> float:
    if returns.empty:
        return float("nan")
    return float((1 + returns).prod() - 1)


def _fmt(column: str):
    if column in ("Sharpe", "Calmar"):
        return lambda v: f"{v:.2f}"
    return lambda v: f"{v:.1f}%"


if __name__ == "__main__":
    main()
