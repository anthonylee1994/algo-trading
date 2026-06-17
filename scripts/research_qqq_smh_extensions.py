"""Fresh angles to extend §11[D] QQQ/SMH blend finding.

Things NOT tried in prior research:

  [1] QQQ/SMH/GLD 3-way blend — combine §11[D] raw edge with §9.2 risk-adjusted edge
  [2] QQQ/SMH blend + 5% OTM monthly covered call on the QQQ half — combine §11[D]
      with §10.2 risk-adjusted edge
  [3] AIQ / BOTZ / ROBO as AI basket instead of SMH — fresh systematic angle
  [4] SMH weight grid 10%-90% to see if 50/50 is really optimal

All long-only, total exposure <= 100% (no borrowing). Monthly rebalance, 15bps cost,
signal shift 1 day.

Usage:
    .venv/bin/python scripts/research_qqq_smh_extensions.py
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import yfinance as yf

START, END = "2010-01-01", "2026-06-17"
COST_BPS = 15.0
REBAL_FREQ = "ME"


def fetch(tickers: list[str]) -> pd.DataFrame:
    px = yf.download(tickers, start=START, end=END, progress=False, auto_adjust=True)["Close"]
    return px.sort_index().ffill()


def perf(s: pd.Series) -> dict | None:
    s = s.dropna()
    if len(s) < 200:
        return None
    yrs = (s.index[-1] - s.index[0]).days / 365.25
    cagr = (s.iloc[-1] / s.iloc[0]) ** (1 / yrs) - 1
    r = s.pct_change().dropna()
    sharpe = r.mean() / r.std() * np.sqrt(252) if r.std() > 0 else np.nan
    vol = r.std() * np.sqrt(252)
    dd = (s / s.cummax() - 1).min()
    calmar = cagr / abs(dd) if dd < 0 else np.nan
    return {"CAGR": cagr, "Sharpe": sharpe, "Vol": vol, "MaxDD": dd, "Calmar": calmar}


def fmt(d: dict | None) -> str:
    if not d:
        return "n/a"
    return (
        f"CAGR {d['CAGR']:5.1%}  Sh {d['Sharpe']:.2f}  "
        f"Vol {d['Vol']:5.1%}  MaxDD {d['MaxDD']:6.1%}  Cal {d['Calmar']:.2f}"
    )


def static_blend(px: pd.DataFrame, weights: dict[str, float]) -> pd.Series:
    """Static blend with monthly rebalance."""
    cols = list(weights.keys())
    assert abs(sum(weights.values()) - 1.0) < 1e-6, f"weights must sum to 1: {weights}"
    dates = px[cols].resample(REBAL_FREQ).last().index
    wts = pd.DataFrame(0.0, index=px.index, columns=cols)
    for i, d in enumerate(dates[:-1]):
        nxt = dates[i + 1]
        mask = (px.index > d) & (px.index <= nxt)
        for c, w in weights.items():
            wts.loc[mask, c] = w
    # Fill NaN weights (assets with no data yet) with 0 — they shouldn't contribute
    wts = wts.fillna(0.0)
    # For NaN prices, set return to 0
    dr = px[cols].pct_change().fillna(0.0)
    gross = (wts * dr).sum(axis=1)
    net = gross - wts.diff().abs().sum(axis=1).fillna(0.0) * (COST_BPS / 1e4)
    return (1 + net).cumprod()


def covered_call_overlay(equity: pd.Series, vix_proxy: pd.Series,
                         otm_pct: float = 0.05, haircut: float = 1.0,
                         rebal_freq: str = "ME") -> pd.Series:
    """Black-Scholes approximation of monthly covered call overlay.

    For each monthly period, sell ATM+otm_pct call, collect BS premium (haircut applied),
    cap period return at the upside. Premium is collected ONCE per period, not daily.
    """
    px = equity.copy()
    r = px.pct_change().fillna(0.0)
    # realized vol as IV proxy
    iv = r.rolling(21).std() * np.sqrt(252)
    iv = iv.fillna(0.20)

    dates = px.resample(rebal_freq).last().index
    out_eq = pd.Series(np.nan, index=px.index, dtype=float)

    from math import log, sqrt
    from statistics import NormalDist
    nd = NormalDist()

    for i in range(len(dates) - 1):
        d = dates[i]
        nxt = dates[i + 1]
        mask = (px.index > d) & (px.index <= nxt)
        period_r = r.loc[mask]
        if len(period_r) == 0:
            continue
        T = 1.0 / 12.0
        sigma = iv.asof(d)
        K = 1.0 + otm_pct
        if sigma > 0:
            d1 = (log(1.0 / K) + 0.5 * sigma ** 2 * T) / (sigma * sqrt(T))
            d2 = d1 - sigma * sqrt(T)
            call_premium = (nd.cdf(d1) - K * nd.cdf(d2))
        else:
            call_premium = max(0, 1.0 - K)
        call_premium = max(call_premium, 0.0) * haircut

        # Get the starting equity for this period (last known out_eq, or 1.0 for first period)
        prev_mask = (px.index <= d)
        if out_eq.loc[prev_mask].notna().any():
            start_eq = out_eq.loc[prev_mask].dropna().iloc[-1]
        else:
            start_eq = 1.0

        # Compound capped daily returns
        capped_cum = (1.0 + period_r.clip(upper=otm_pct)).cumprod()
        period_eq = start_eq * capped_cum * (1.0 + call_premium)
        out_eq.loc[mask] = period_eq.values

    # Backfill first period with raw equity scaled to 1.0
    out_eq = out_eq.bfill().fillna(1.0)
    return out_eq


def grid_smih_weight(px: pd.DataFrame) -> None:
    print("=" * 90)
    print("[4] SMH WEIGHT GRID (QQQ + SMH blend, monthly rebal, 15bps)")
    print("=" * 90)
    qqq = perf(px["QQQ"].dropna())
    print(f"  QQQ benchmark .. {fmt(qqq)}\n")
    print(f"  {'SMH wt':<6} | {'CAGR':>6} {'Sharpe':>7} {'MaxDD':>7} {'Calmar':>7} | vs QQQ")
    for w in [0.10, 0.20, 0.30, 0.40, 0.50, 0.60, 0.70, 0.80, 0.90]:
        eq = static_blend(px, {"QQQ": 1 - w, "SMH": w})
        p = perf(eq)
        if not p:
            continue
        diff = p["CAGR"] - qqq["CAGR"]
        marker = "✅" if diff > 0.02 else ("⚠️" if diff > 0 else "❌")
        print(f"  {w:>5.0%} | {p['CAGR']:>5.1%} {p['Sharpe']:>7.2f} {p['MaxDD']:>6.1%} "
              f"{p['Calmar']:>7.2f} | {diff:+.1%}pp {marker}")
    print()


def three_way_blend(px: pd.DataFrame) -> None:
    print("=" * 90)
    print("[1] QQQ/SMH/GLD 3-WAY BLEND (raw edge + risk-adjusted edge combined)")
    print("=" * 90)
    qqq = perf(px["QQQ"].dropna())
    smh = perf(px["SMH"].dropna())
    gld = perf(px["GLD"].dropna())
    print(f"  QQQ ... {fmt(qqq)}")
    print(f"  SMH ... {fmt(smh)}")
    print(f"  GLD ... {fmt(gld)}\n")
    print(f"  {'weights':<25} | CAGR    Sharpe  MaxDD    Calmar | vs QQQ")
    for w in [
        {"QQQ": 1.00, "SMH": 0.00, "GLD": 0.00},  # baseline
        {"QQQ": 0.50, "SMH": 0.50, "GLD": 0.00},  # existing best
        {"QQQ": 0.45, "SMH": 0.45, "GLD": 0.10},  # 3-way
        {"QQQ": 0.40, "SMH": 0.40, "GLD": 0.20},
        {"QQQ": 0.40, "SMH": 0.50, "GLD": 0.10},
        {"QQQ": 0.50, "SMH": 0.40, "GLD": 0.10},
        {"QQQ": 0.70, "SMH": 0.20, "GLD": 0.10},
        {"QQQ": 0.60, "SMH": 0.30, "GLD": 0.10},
        {"QQQ": 0.80, "SMH": 0.00, "GLD": 0.20},  # §9.2 ref
    ]:
        eq = static_blend(px, w)
        p = perf(eq)
        if not p:
            continue
        diff = p["CAGR"] - qqq["CAGR"]
        marker = "✅" if diff > 0.02 else ("⚠️" if diff > 0 else "❌")
        label = "/".join(f"{int(v*100)}" for v in w.values())
        print(f"  Q/S/G {label:<18} | {p['CAGR']:>5.1%}  {p['Sharpe']:>5.2f}  {p['MaxDD']:>6.1%}  "
              f"{p['Calmar']:>5.2f}  | {diff:+.1%}pp {marker}")
    print()


def blend_with_cc(px: pd.DataFrame) -> None:
    print("=" * 90)
    print("[2] QQQ/SMH BLEND + 5% OTM MONTHLY CC (combine §11 + §10.2)")
    print("=" * 90)
    qqq = perf(px["QQQ"].dropna())
    print(f"  QQQ benchmark .. {fmt(qqq)}\n")
    print(f"  {'config':<40} | CAGR    Sharpe  MaxDD    Calmar | vs QQQ")
    for w_smh in [0.0, 0.25, 0.33, 0.50]:
        # Build blend equity
        eq = static_blend(px, {"QQQ": 1 - w_smh, "SMH": w_smh})
        # Apply CC on full equity
        for haircut in [1.0, 0.9, 0.85]:
            eq_cc = covered_call_overlay(eq, px.get("^VIX", pd.Series()), otm_pct=0.05, haircut=haircut)
            p = perf(eq_cc)
            if not p:
                continue
            diff = p["CAGR"] - qqq["CAGR"]
            sharpe_diff = p["Sharpe"] - qqq["Sharpe"]
            marker = "✅" if diff > 0.02 else ("⚠️" if diff > 0 else "❌")
            label = f"SMH={int(w_smh*100):>2d}% CC h={haircut}"
            print(f"  {label:<40} | {p['CAGR']:>5.1%}  {p['Sharpe']:>5.2f}  {p['MaxDD']:>6.1%}  "
                  f"{p['Calmar']:>5.2f}  | {diff:+.1%}pp {marker}")
    print()


def ai_etf_alternatives() -> None:
    print("=" * 90)
    print("[3] AI ETF BASKETS vs SMH (substitute the AI exposure)")
    print("=" * 90)
    tickers = ["QQQ", "SMH", "SOXX", "AIQ", "BOTZ", "ROBO", "IRBO", "KOMP"]
    px = fetch(tickers)
    qqq = perf(px["QQQ"].dropna())
    print(f"  QQQ ... {fmt(qqq)}\n")
    print(f"  {'ETF':<6} | {'buy-hold':<48} | QQQ/SMH-style 50/50 blend")
    for t in ["SMH", "SOXX", "AIQ", "BOTZ", "ROBO", "IRBO", "KOMP"]:
        if t not in px.columns:
            print(f"  {t:<6} | (no data)")
            continue
        p = perf(px[t].dropna())
        if not p:
            print(f"  {t:<6} | (insufficient data)")
            continue
        # 50/50 with QQQ
        eq = static_blend(px[["QQQ", t]], {"QQQ": 0.5, t: 0.5})
        pb = perf(eq)
        if pb:
            blend_str = f"CAGR {pb['CAGR']:5.1%}  Sh {pb['Sharpe']:.2f}  DD {pb['MaxDD']:>6.1%}  (vs QQQ {pb['CAGR']-qqq['CAGR']:+.1%}pp)"
        else:
            blend_str = "(blend failed)"
        print(f"  {t:<6} | {fmt(p)} | {blend_str}")
    print()


if __name__ == "__main__":
    print("\n>>> QQQ/SMH BLEND EXTENSIONS — fresh angles not in prior research <<<\n")

    # [4] SMH weight grid (QQQ + SMH only)
    px_qs = fetch(["QQQ", "SMH"])
    grid_smih_weight(px_qs)

    # [1] 3-way blend
    px_qsg = fetch(["QQQ", "SMH", "GLD"])
    three_way_blend(px_qsg)

    # [2] Blend + covered call
    blend_with_cc(px_qs)

    # [3] AI ETF alternatives
    ai_etf_alternatives()
