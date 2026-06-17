"""Stress test for the top extensions: sub-period + cost + haircut robustness.

Top candidates to verify:

  [A] QQQ/SMH 50/50 (baseline, §11[D])
  [B] QQQ/SMH 50/50 + 5% OTM CC h=1.0 / 0.9 / 0.85
  [C] QQQ/SMH 40/40/20 GLD 3-way
  [D] QQQ/SMH 70/25 (lean)

Tests:
  - Sub-period stability (2010-14, 2015-19, 2020-26)
  - Cost sensitivity (5-30bps)
  - CC haircut sensitivity (0.7-1.0)
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import yfinance as yf
from research_qqq_smh_extensions import static_blend, covered_call_overlay, perf, fmt

START, END = "2010-01-01", "2026-06-17"


def fetch(t):
    px = yf.download(t, start=START, end=END, progress=False, auto_adjust=True)["Close"]
    return px.sort_index().ffill()


def sub_period(p, label, lo, hi, qqq_eq):
    psub = p.loc[lo:hi].dropna()
    qsub = qqq_eq.loc[lo:hi].dropna()
    if len(psub) < 200:
        return
    # Re-base to 1.0 at start of sub-period
    psub = psub / psub.iloc[0]
    qsub = qsub / qsub.iloc[0]
    pp = perf(psub)
    pq = perf(qsub)
    if not pp or not pq:
        return
    diff = pp["CAGR"] - pq["CAGR"]
    marker = "✅" if diff > 0.02 else ("⚠️" if diff > 0 else "❌")
    print(f"    {label}: {fmt(pp)}  vs QQQ {pq['CAGR']:5.1%}  (diff {diff:+.1%}pp) {marker}")


def main():
    px = fetch(["QQQ", "SMH", "GLD"])

    print("=" * 90)
    print("CANDIDATES")
    print("=" * 90)

    # A: QQQ/SMH 50/50 baseline
    a = static_blend(px, {"QQQ": 0.5, "SMH": 0.5})

    # B: QQQ/SMH 50/50 + CC at various haircuts
    b_eqs = {}
    for h in [1.0, 0.9, 0.85, 0.8]:
        b_eqs[h] = covered_call_overlay(a, px.get("^VIX", pd.Series()), otm_pct=0.05, haircut=h)

    # C: QQQ/SMH/GLD 40/40/20
    c = static_blend(px, {"QQQ": 0.4, "SMH": 0.4, "GLD": 0.2})

    # D: QQQ/SMH 70/25 (lean)
    d = static_blend(px, {"QQQ": 0.75, "SMH": 0.25})

    qqq = px["QQQ"].dropna()
    qqq_eq = (1 + qqq.pct_change().fillna(0)).cumprod()

    candidates = {
        "[A] QQQ/SMH 50/50 (base)": a,
        "[B-h1.0] QQQ/SMH 50/50 + 5%CC h=1.0": b_eqs[1.0],
        "[B-h0.9]  QQQ/SMH 50/50 + 5%CC h=0.9":  b_eqs[0.9],
        "[B-h0.85] QQQ/SMH 50/50 + 5%CC h=0.85": b_eqs[0.85],
        "[B-h0.8]  QQQ/SMH 50/50 + 5%CC h=0.8":  b_eqs[0.8],
        "[C] QQQ/SMH/GLD 40/40/20":  c,
        "[D] QQQ/SMH 75/25 (lean)": d,
    }

    print(f"  QQQ benchmark ... {fmt(perf(qqq_eq))}\n")
    for name, eq in candidates.items():
        p = perf(eq)
        diff = p["CAGR"] - perf(qqq_eq)["CAGR"]
        marker = "✅" if diff > 0.02 else ("⚠️" if diff > 0 else "❌")
        print(f"  {name:<40} {fmt(p)}  (vs QQQ {diff:+.1%}pp) {marker}")
    print()

    print("=" * 90)
    print("SUB-PERIOD STABILITY (per candidate, vs QQQ re-based at sub-period start)")
    print("=" * 90)
    for name, eq in candidates.items():
        print(f"\n  {name}")
        sub_period(eq, "2010-2014", "2010-01-01", "2015-01-01", qqq_eq)
        sub_period(eq, "2015-2019", "2015-01-01", "2020-01-01", qqq_eq)
        sub_period(eq, "2020-2026", "2020-01-01", "2026-06-17", qqq_eq)
    print()

    print("=" * 90)
    print("COST SENSITIVITY (5/15/30 bps) for top CC combo")
    print("=" * 90)
    # Already used 15bps. Test by adding different cost to the leg turnover
    for cost_bps in [5, 15, 30]:
        # Re-blend with different cost
        from research_qqq_smh_extensions import static_blend as sb
        # We need to re-run static_blend with different cost — let me just monkey-patch
        import research_qqq_smh_extensions as ext
        original_cost = ext.COST_BPS
        ext.COST_BPS = float(cost_bps)
        a_new = sb(px, {"QQQ": 0.5, "SMH": 0.5})
        b_new = covered_call_overlay(a_new, px.get("^VIX", pd.Series()), otm_pct=0.05, haircut=0.9)
        ext.COST_BPS = original_cost

        p = perf(b_new)
        diff = p["CAGR"] - perf(qqq_eq)["CAGR"]
        print(f"  cost={cost_bps:>2d}bps | {fmt(p)}  (vs QQQ {diff:+.1%}pp)")


if __name__ == "__main__":
    main()
