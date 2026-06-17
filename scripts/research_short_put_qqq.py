"""Short put (cash-secured put-write) on QQQ vs QQQ buy-hold vs covered call.

§10.2 covered call was 5% OTM on QQQ. Put-call parity says a 5% OTM put has the
SAME BS premium as a 5% OTM call, but the P&L is mirrored:

  - CC:  capped upside at K (K = 1.05*S); downside = stock - K - premium (you own stock)
  - SP:  capped upside = premium; downside = -K/S + S_next/S + premium (you can be assigned)

Short put is "wanting to buy the dip with yield". Regimes:
  - Bull:  SP underperforms (misses upside, only collects premium)
  - Bear:  SP can outperform (collects premium until assigned, then buys at strike)
  - Crash: Both lose; SP is worse if assigned + stock keeps falling

This script tests:
  [1] Short put on QQQ (5% OTM monthly) vs QQQ-CC vs QQQ buy-hold
  [2] OTM% sensitivity (3/5/10/15/20%)
  [3] Sub-period stability (incl 2008/2022 stress)
  [4] Haircut sensitivity (premium realization)
  [5] Combine with SMH 50/50 (replaces QQQ-CC with QQQ-SP, or layers)
  [6] Worst-case: what does SP do in 2008 and 2022?

All long-only, no leverage on the option leg (cash-secured equivalent).
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


def fetch_long(start):
    """Fetch from earlier start to capture 2008 + 2022 stress."""
    px = yf.download(["QQQ", "SMH", "^VIX"], start=start, end=END,
                     progress=False, auto_adjust=True)["Close"]
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


def bs_put_price(spot, strike, sigma, T=1/12):
    """BS put price as fraction of spot."""
    if sigma <= 0 or T <= 0:
        return max(0, strike - spot) / spot
    d1 = (log(spot / strike) + 0.5 * sigma**2 * T) / (sigma * sqrt(T))
    d2 = d1 - sigma * sqrt(T)
    put = strike * nd.cdf(-d2) - spot * nd.cdf(-d1)
    return put / spot


def bs_call_price(spot, strike, sigma, T=1/12):
    """BS call price as fraction of spot (put-call parity check)."""
    if sigma <= 0 or T <= 0:
        return max(0, spot - strike) / spot
    d1 = (log(spot / strike) + 0.5 * sigma**2 * T) / (sigma * sqrt(T))
    d2 = d1 - sigma * sqrt(T)
    call = spot * nd.cdf(d1) - strike * nd.cdf(d2)
    return call / spot


def short_put_equity(px: pd.Series, otm_pct: float = 0.05, haircut: float = 1.0,
                     rebal_freq: str = "ME") -> pd.Series:
    """Short put-write on QQQ (or any single asset).

    Each month:
      - Sell 1-month put at strike K = S * (1 - otm_pct)
      - Collect premium = BS_put * (1 + haircut adjustment)
      - If at expiry S_next < K: assigned. Take the loss (S_next - K)/S + premium
      - If at expiry S_next >= K: keep premium only

    Equity = compounded. Each $1 of equity rolls into 1 put on the next period.
    """
    r = px.pct_change().fillna(0.0)
    iv = r.rolling(21).std() * np.sqrt(252)
    iv = iv.fillna(0.20)

    dates = px.resample(rebal_freq).last().index
    out_eq = pd.Series(1.0, index=px.index, dtype=float)

    for i in range(len(dates) - 1):
        d = dates[i]
        nxt = dates[i + 1]
        mask = (px.index > d) & (px.index <= nxt)
        if mask.sum() == 0:
            continue

        S = px.asof(d)
        if pd.isna(S) or S <= 0:
            continue
        K = S * (1 - otm_pct)
        sigma = iv.asof(d)
        T = 1.0 / 12.0
        premium = bs_put_price(S, K, sigma, T) * haircut
        premium = max(premium, 0)

        # Expiry price
        S_exp = px.asof(nxt) if nxt in px.index else px.loc[:nxt].iloc[-1]
        if pd.isna(S_exp):
            S_exp = S

        if S_exp >= K:
            # Put expires worthless
            period_return = premium
        else:
            # Assigned: own 1 share at K. P&L = (S_exp - K)/S + premium
            # Note: negative if S_exp < K
            period_return = (S_exp - K) / S + premium

        # Get start equity (last known out_eq before this period)
        prev_mask = px.index <= d
        if out_eq.loc[prev_mask].notna().any():
            start_eq = out_eq.loc[prev_mask].dropna().iloc[-1]
        else:
            start_eq = 1.0

        out_eq.loc[mask] = start_eq * (1.0 + period_return)

    return out_eq


def covered_call_equity(px: pd.Series, otm_pct: float = 0.05, haircut: float = 1.0,
                        rebal_freq: str = "ME") -> pd.Series:
    """Covered call: own the underlying, sell OTM call, cap upside at K.

    Each month:
      - Buy 1 share, sell 1 call at K = S * (1 + otm_pct)
      - Period return = min(S_exp/S - 1, otm_pct) + premium
    """
    r = px.pct_change().fillna(0.0)
    iv = r.rolling(21).std() * np.sqrt(252)
    iv = iv.fillna(0.20)

    dates = px.resample(rebal_freq).last().index
    out_eq = pd.Series(1.0, index=px.index, dtype=float)

    for i in range(len(dates) - 1):
        d = dates[i]
        nxt = dates[i + 1]
        mask = (px.index > d) & (px.index <= nxt)
        if mask.sum() == 0:
            continue

        S = px.asof(d)
        if pd.isna(S) or S <= 0:
            continue
        K = S * (1 + otm_pct)
        sigma = iv.asof(d)
        T = 1.0 / 12.0
        premium = bs_call_price(S, K, sigma, T) * haircut
        premium = max(premium, 0)

        S_exp = px.asof(nxt) if nxt in px.index else px.loc[:nxt].iloc[-1]
        if pd.isna(S_exp):
            S_exp = S

        underlying_return = (S_exp - S) / S
        capped_return = min(underlying_return, otm_pct)
        period_return = capped_return + premium

        prev_mask = px.index <= d
        if out_eq.loc[prev_mask].notna().any():
            start_eq = out_eq.loc[prev_mask].dropna().iloc[-1]
        else:
            start_eq = 1.0

        out_eq.loc[mask] = start_eq * (1.0 + period_return)

    return out_eq


def sub_period(equity, qqq_equity, label, lo, hi):
    psub = equity.loc[lo:hi].dropna()
    qsub = qqq_equity.loc[lo:hi].dropna()
    if len(psub) < 200:
        return
    psub = psub / psub.iloc[0]
    qsub = qsub / qsub.iloc[0]
    pp = perf(psub)
    pq = perf(qsub)
    if not pp or not pq:
        return
    diff = pp["CAGR"] - pq["CAGR"]
    marker = "✅" if diff > 0.02 else ("⚠️" if diff > 0 else "❌")
    print(f"    {label}: {fmt(pp)}  vs QQQ {pq['CAGR']:5.1%}  (diff {diff:+.1%}pp) {marker}")


# ============================================================================
# [1] MAIN: Short put on QQQ vs CC vs buy-hold
# ============================================================================
def main_compare():
    px = fetch(["QQQ"])
    qqq = px["QQQ"].dropna()
    qqq_eq = (1 + qqq.pct_change().fillna(0)).cumprod()

    print("=" * 90)
    print("[1] QQQ: SHORT PUT vs COVERED CALL vs BUY-HOLD (5% OTM, monthly, h=1.0)")
    print("=" * 90)

    sp_5 = short_put_equity(qqq, otm_pct=0.05, haircut=1.0)
    cc_5 = covered_call_equity(qqq, otm_pct=0.05, haircut=1.0)

    for name, eq in [("QQQ buy-hold", qqq_eq),
                     ("QQQ + 5% CC (h=1.0)", cc_5),
                     ("QQQ Short 5% Put (h=1.0)", sp_5)]:
        p = perf(eq)
        diff = p["CAGR"] - perf(qqq_eq)["CAGR"]
        marker = "✅" if diff > 0.02 else ("⚠️" if diff > 0 else "❌")
        print(f"  {name:<35} {fmt(p)}  (vs QQQ {diff:+.1%}pp) {marker}")
    print()

    print("=" * 90)
    print("[2] OTM% SENSITIVITY (short put, h=1.0)")
    print("=" * 90)
    print(f"  {'OTM%':<6} | {'CAGR':>6} {'Sharpe':>7} {'MaxDD':>7} {'Calmar':>7} | vs QQQ")
    for otm in [0.03, 0.05, 0.08, 0.10, 0.15, 0.20]:
        sp = short_put_equity(qqq, otm_pct=otm, haircut=1.0)
        p = perf(sp)
        diff = p["CAGR"] - perf(qqq_eq)["CAGR"]
        marker = "✅" if diff > 0.02 else ("⚠️" if diff > 0 else "❌")
        print(f"  {otm:>5.0%} | {p['CAGR']:>5.1%} {p['Sharpe']:>7.2f} {p['MaxDD']:>6.1%} "
              f"{p['Calmar']:>7.2f} | {diff:+.1%}pp {marker}")
    print()

    print("=" * 90)
    print("[3] HAIRCUT SENSITIVITY (short 5% put)")
    print("=" * 90)
    print(f"  {'h':<6} | {'CAGR':>6} {'Sharpe':>7} {'MaxDD':>7} {'Calmar':>7} | vs QQQ")
    for h in [1.0, 0.9, 0.85, 0.8, 0.7]:
        sp = short_put_equity(qqq, otm_pct=0.05, haircut=h)
        p = perf(sp)
        diff = p["CAGR"] - perf(qqq_eq)["CAGR"]
        marker = "✅" if diff > 0.02 else ("⚠️" if diff > 0 else "❌")
        print(f"  {h:>5.0%} | {p['CAGR']:>5.1%} {p['Sharpe']:>7.2f} {p['MaxDD']:>6.1%} "
              f"{p['Calmar']:>7.2f} | {diff:+.1%}pp {marker}")
    print()

    print("=" * 90)
    print("[4] SUB-PERIOD (short 5% put, h=1.0 vs h=0.85)")
    print("=" * 90)
    sp_h1 = short_put_equity(qqq, otm_pct=0.05, haircut=1.0)
    sp_h09 = short_put_equity(qqq, otm_pct=0.05, haircut=0.9)
    sp_h085 = short_put_equity(qqq, otm_pct=0.05, haircut=0.85)
    cc_h1 = covered_call_equity(qqq, otm_pct=0.05, haircut=1.0)

    for name, eq in [("Short 5% put h=1.0", sp_h1),
                     ("Short 5% put h=0.9", sp_h09),
                     ("Short 5% put h=0.85", sp_h085),
                     ("CC 5% h=1.0 (ref)", cc_h1)]:
        print(f"\n  {name}")
        sub_period(eq, qqq_eq, "2010-2014", "2010-01-01", "2015-01-01")
        sub_period(eq, qqq_eq, "2015-2019", "2015-01-01", "2020-01-01")
        sub_period(eq, qqq_eq, "2020-2026", "2020-01-01", "2026-06-17")
    print()


# ============================================================================
# [5] STRESS: include 2008 GFC and 2022 bear
# ============================================================================
def main_stress():
    print("=" * 90)
    print("[5] STRESS TEST (include 2008 GFC + 2022 bear market)")
    print("=" * 90)
    px = fetch_long("2007-01-01")
    qqq = px["QQQ"].dropna()
    qqq_eq = (1 + qqq.pct_change().fillna(0)).cumprod()

    sp_h1 = short_put_equity(qqq, otm_pct=0.05, haircut=1.0)
    sp_h09 = short_put_equity(qqq, otm_pct=0.05, haircut=0.9)
    cc_h1 = covered_call_equity(qqq, otm_pct=0.05, haircut=1.0)

    print(f"  QQQ buy-hold ... {fmt(perf(qqq_eq))}\n")
    for name, eq in [("Short 5% put h=1.0", sp_h1),
                     ("Short 5% put h=0.9", sp_h09),
                     ("CC 5% h=1.0 (ref)", cc_h1)]:
        p = perf(eq)
        diff = p["CAGR"] - perf(qqq_eq)["CAGR"]
        marker = "✅" if diff > 0.02 else ("⚠️" if diff > 0 else "❌")
        print(f"  {name:<35} {fmt(p)}  (vs QQQ {diff:+.1%}pp) {marker}")
    print()

    # Worst single-year
    print("  Worst single year for Short 5% put (h=1.0):")
    yearly_sp = sp_h1.resample("YE").last().pct_change().dropna()
    worst = yearly_sp.nsmallest(3)
    for d, r in worst.items():
        print(f"    {d.year}: {r:+.1%}")
    print()
    print("  Worst single year for Short 5% put (h=0.85):")
    yearly_sp = short_put_equity(qqq, otm_pct=0.05, haircut=0.85).resample("YE").last().pct_change().dropna()
    worst = yearly_sp.nsmallest(3)
    for d, r in worst.items():
        print(f"    {d.year}: {r:+.1%}")
    print()

    # Sub-period including 2008/2022 stress
    print("  Sub-period stability (incl 2008 + 2022 stress):\n")
    sp_h1 = short_put_equity(qqq, otm_pct=0.05, haircut=1.0)
    sp_h09 = short_put_equity(qqq, otm_pct=0.05, haircut=0.9)
    cc_h1 = covered_call_equity(qqq, otm_pct=0.05, haircut=1.0)
    for name, eq in [("Short 5% put h=1.0", sp_h1),
                     ("Short 5% put h=0.9", sp_h09),
                     ("CC 5% h=1.0 (ref)", cc_h1)]:
        print(f"  {name}")
        sub_period(eq, qqq_eq, "2007-2009 (GFC)", "2007-01-01", "2010-01-01")
        sub_period(eq, qqq_eq, "2010-2014", "2010-01-01", "2015-01-01")
        sub_period(eq, qqq_eq, "2015-2019", "2015-01-01", "2020-01-01")
        sub_period(eq, qqq_eq, "2020-2026", "2020-01-01", "2026-06-17")
    print()


# ============================================================================
# [6] QQQ-SP + SMH 50/50 blend (mirror of §12[5] but with SP instead of CC)
# ============================================================================
def main_smh_combo():
    print("=" * 90)
    print("[6] QQQ-SHORT-PUT + SMH 50/50 BLEND (mirror of §12[5])")
    print("=" * 90)
    px = fetch(["QQQ", "SMH"])
    qqq = px["QQQ"].dropna()
    smh = px["SMH"].dropna()
    qqq_eq = (1 + qqq.pct_change().fillna(0)).cumprod()
    smh_eq = (1 + smh.pct_change().fillna(0)).cumprod()

    print(f"  QQQ benchmark ... {fmt(perf(qqq_eq))}\n")

    for h in [1.0, 0.9, 0.85]:
        sp = short_put_equity(qqq, otm_pct=0.05, haircut=h)
        blend = 0.5 * sp + 0.5 * smh_eq
        p = perf(blend)
        diff = p["CAGR"] - perf(qqq_eq)["CAGR"]
        marker = "✅" if diff > 0.02 else ("⚠️" if diff > 0 else "❌")
        print(f"  QQQ-SP (h={h}) + SMH 50/50 ... {fmt(p)}  (vs QQQ {diff:+.1%}pp) {marker}")
    print()

    # Sub-period for the best (h=0.9)
    print("  Sub-period (QQQ-SP h=0.9 + SMH 50/50):\n")
    sp_h09 = short_put_equity(qqq, otm_pct=0.05, haircut=0.9)
    blend = 0.5 * sp_h09 + 0.5 * smh_eq
    sub_period(blend, qqq_eq, "2010-2014", "2010-01-01", "2015-01-01")
    sub_period(blend, qqq_eq, "2015-2019", "2015-01-01", "2020-01-01")
    sub_period(blend, qqq_eq, "2020-2026", "2020-01-01", "2026-06-17")
    print()

    # Weight grid
    print("  Weight grid (QQQ-SP h=0.9 + SMH):\n")
    print(f"  {'SMH wt':<6} | {'CAGR':>6} {'Sharpe':>7} {'MaxDD':>7} {'Calmar':>7} | vs QQQ")
    for w in [0.0, 0.20, 0.33, 0.50, 0.70]:
        blend = (1 - w) * sp_h09 + w * smh_eq
        p = perf(blend)
        diff = p["CAGR"] - perf(qqq_eq)["CAGR"]
        marker = "✅" if diff > 0.02 else ("⚠️" if diff > 0 else "❌")
        print(f"  {w:>5.0%} | {p['CAGR']:>5.1%} {p['Sharpe']:>7.2f} {p['MaxDD']:>6.1%} "
              f"{p['Calmar']:>7.2f} | {diff:+.1%}pp {marker}")
    print()


if __name__ == "__main__":
    main_compare()
    main_stress()
    main_smh_combo()
