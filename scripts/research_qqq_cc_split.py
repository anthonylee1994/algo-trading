"""Realistic split: CC on QQQ leg only, SMH leg stays raw.

The previous 'covered_call_overlay' applied CC to a blended equity curve using a
single IV. That's a theoretical max. In practice, you'd:
  - Sell 5% OTM monthly CCs on the QQQ half (liquid options, ~22% IV)
  - Hold the SMH half raw (less liquid options, wider bid-ask)

This script does that split honestly and stress-tests the result.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import yfinance as yf
from math import log, sqrt
from statistics import NormalDist

START, END = "2010-01-01", "2026-06-17"
COST_BPS = 15.0
REBAL_FREQ = "ME"

nd = NormalDist()


def fetch(t):
    px = yf.download(t, start=START, end=END, progress=False, auto_adjust=True)["Close"]
    return px.sort_index().ffill()


def perf(s):
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


def fmt(d):
    if not d:
        return "n/a"
    return (f"CAGR {d['CAGR']:5.1%}  Sh {d['Sharpe']:.2f}  "
            f"Vol {d['Vol']:5.1%}  MaxDD {d['MaxDD']:6.1%}  Cal {d['Calmar']:.2f}")


def cc_on_single_asset(px: pd.Series, otm_pct: float = 0.05, haircut: float = 1.0) -> pd.Series:
    """Sell monthly OTM CC on a single asset. Premium collected ONCE per period."""
    r = px.pct_change().fillna(0.0)
    iv = r.rolling(21).std() * np.sqrt(252)
    iv = iv.fillna(0.20)

    dates = px.resample(REBAL_FREQ).last().index
    out_eq = pd.Series(np.nan, index=px.index, dtype=float)

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

        prev_mask = (px.index <= d)
        if out_eq.loc[prev_mask].notna().any():
            start_eq = out_eq.loc[prev_mask].dropna().iloc[-1]
        else:
            start_eq = 1.0

        capped_cum = (1.0 + period_r.clip(upper=otm_pct)).cumprod()
        period_eq = start_eq * capped_cum * (1.0 + call_premium)
        out_eq.loc[mask] = period_eq.values

    return out_eq.bfill().fillna(1.0)


def static_blend(px: pd.DataFrame, weights: dict[str, float]) -> pd.Series:
    cols = list(weights.keys())
    assert abs(sum(weights.values()) - 1.0) < 1e-6
    dates = px[cols].resample(REBAL_FREQ).last().index
    wts = pd.DataFrame(0.0, index=px.index, columns=cols)
    for i, d in enumerate(dates[:-1]):
        nxt = dates[i + 1]
        mask = (px.index > d) & (px.index <= nxt)
        for c, w in weights.items():
            wts.loc[mask, c] = w
    wts = wts.fillna(0.0)
    dr = px[cols].pct_change().fillna(0.0)
    gross = (wts * dr).sum(axis=1)
    net = gross - wts.diff().abs().sum(axis=1).fillna(0.0) * (COST_BPS / 1e4)
    return (1 + net).cumprod()


def main():
    px = fetch(["QQQ", "SMH"])
    qqq_px = px["QQQ"].dropna()
    smh_px = px["SMH"].dropna()

    # QQQ half with CC
    qqq_cc_h1 = cc_on_single_asset(qqq_px, haircut=1.0)
    qqq_cc_h09 = cc_on_single_asset(qqq_px, haircut=0.9)
    qqq_cc_h085 = cc_on_single_asset(qqq_px, haircut=0.85)
    qqq_cc_h08 = cc_on_single_asset(qqq_px, haircut=0.8)

    # QQQ baseline (no CC)
    qqq = (1 + qqq_px.pct_change().fillna(0)).cumprod()

    # SMH half raw
    smh = (1 + smh_px.pct_change().fillna(0)).cumprod()

    print("=" * 90)
    print("REALISTIC: CC ON QQQ LEG ONLY, SMH LEG STAYS RAW")
    print("=" * 90)
    print(f"  QQQ raw buy-hold ........ {fmt(perf(qqq))}\n")

    print(f"  {'config':<40} | CAGR    Sharpe  MaxDD    Calmar | vs QQQ")
    # QQQ/SMH 50/50 with various CC haircuts on QQQ leg
    for label, qqq_eq, h in [
        ("QQQ/SMH 50/50 (no CC)", qqq, 0.0),
        ("QQQ-CC-h1.0 / SMH 50/50", qqq_cc_h1, 1.0),
        ("QQQ-CC-h0.9 / SMH 50/50", qqq_cc_h09, 0.9),
        ("QQQ-CC-h0.85 / SMH 50/50", qqq_cc_h085, 0.85),
        ("QQQ-CC-h0.8 / SMH 50/50", qqq_cc_h08, 0.8),
    ]:
        # Blend the two
        df = pd.DataFrame({"q": qqq_eq, "s": smh})
        blend = 0.5 * qqq_eq + 0.5 * smh
        p = perf(blend)
        diff = p["CAGR"] - perf(qqq)["CAGR"]
        marker = "✅" if diff > 0.02 else ("⚠️" if diff > 0 else "❌")
        print(f"  {label:<40} | {p['CAGR']:>5.1%}  {p['Sharpe']:>5.2f}  {p['MaxDD']:>6.1%}  "
              f"{p['Calmar']:>5.2f}  | {diff:+.1%}pp {marker}")
    print()

    print("=" * 90)
    print("SUB-PERIOD (realistic CC-on-QQQ-only, h=0.9)")
    print("=" * 90)
    blend_h09 = 0.5 * qqq_cc_h09 + 0.5 * smh
    for label, lo, hi in [("2010-2014", "2010-01-01", "2015-01-01"),
                          ("2015-2019", "2015-01-01", "2020-01-01"),
                          ("2020-2026", "2020-01-01", "2026-06-17")]:
        ps = blend_h09.loc[lo:hi].dropna()
        qs = qqq.loc[lo:hi].dropna()
        if len(ps) < 200:
            continue
        ps = ps / ps.iloc[0]
        qs = qs / qs.iloc[0]
        pp = perf(ps)
        pq = perf(qs)
        if not pp or not pq:
            continue
        diff = pp["CAGR"] - pq["CAGR"]
        marker = "✅" if diff > 0.02 else ("⚠️" if diff > 0 else "❌")
        print(f"    {label}: blend {fmt(pp)}  vs QQQ {pq['CAGR']:5.1%}  (diff {diff:+.1%}pp) {marker}")
    print()

    print("=" * 90)
    print("SUB-PERIOD (realistic CC-on-QQQ-only, h=0.85)")
    print("=" * 90)
    blend_h085 = 0.5 * qqq_cc_h085 + 0.5 * smh
    for label, lo, hi in [("2010-2014", "2010-01-01", "2015-01-01"),
                          ("2015-2019", "2015-01-01", "2020-01-01"),
                          ("2020-2026", "2020-01-01", "2026-06-17")]:
        ps = blend_h085.loc[lo:hi].dropna()
        qs = qqq.loc[lo:hi].dropna()
        if len(ps) < 200:
            continue
        ps = ps / ps.iloc[0]
        qs = qs / qs.iloc[0]
        pp = perf(ps)
        pq = perf(qs)
        if not pp or not pq:
            continue
        diff = pp["CAGR"] - pq["CAGR"]
        marker = "✅" if diff > 0.02 else ("⚠️" if diff > 0 else "❌")
        print(f"    {label}: blend {fmt(pp)}  vs QQQ {pq['CAGR']:5.1%}  (diff {diff:+.1%}pp) {marker}")
    print()

    # Also QQQ/SMH 60/40 / 70/30 with CC
    print("=" * 90)
    print("WEIGHT GRID + QQQ-CC (h=0.9)")
    print("=" * 90)
    print(f"  {'SMH wt':<6} | {'CAGR':>6} {'Sharpe':>7} {'MaxDD':>7} {'Calmar':>7} | vs QQQ")
    for w in [0.0, 0.10, 0.20, 0.30, 0.40, 0.50, 0.60, 0.70]:
        if w == 0:
            # QQQ-CC only
            blend_eq = qqq_cc_h09
        else:
            # 1-w in QQQ-CC, w in SMH raw
            blend_eq = (1 - w) * qqq_cc_h09 + w * smh
        p = perf(blend_eq)
        if not p:
            continue
        diff = p["CAGR"] - perf(qqq)["CAGR"]
        marker = "✅" if diff > 0.02 else ("⚠️" if diff > 0 else "❌")
        print(f"  {w:>5.0%} | {p['CAGR']:>5.1%} {p['Sharpe']:>7.2f} {p['MaxDD']:>6.1%} "
              f"{p['Calmar']:>7.2f} | {diff:+.1%}pp {marker}")


if __name__ == "__main__":
    main()
