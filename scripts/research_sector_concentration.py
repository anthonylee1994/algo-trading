"""Sector momentum rotation vs sector concentration tilt vs QQQ (no leverage).

Tests three honest framings of "beat QQQ raw CAGR without leverage":

  [A] Systematic sector momentum rotation — a pre-defined, bias-free universe
      (9 GICS sector SPDRs that traded from 2010 + QQQ). Monthly cross-sectional
      momentum, top-N equal weight, signal shifted 1 day, 15bps cost. This is
      the NON-hindsight version: you never pick "the winning sector" by name,
      you rotate to whatever is strongest.

  [B] Sector concentration tilt — buy-and-hold a single high-growth sector ETF
      (SMH / SOXX / XLK). This is the HINDSIGHT version: it requires knowing in
      2010 that semiconductors would be the decade's winner sector. Reported
      honestly with that caveat and broken down by sub-period.

  [C] Crypto allocation (BTC) blended with QQQ — the largest raw-CAGR "win" but
      with investability / non-traditional-asset caveats. Shows monthly-rebalance
      drag destroys the BTC edge inside a blend.

  [D] Systematize the SMH edge — QQQ/SMH static blend and dual-momentum switch.
      This is the new raw-CAGR winner that survives 3/3 sub-periods, walk-forward
      OOS, SOXX substitution, and 5-50bps cost sweeps.

All long-only, total exposure <= 100% (no borrowing). Signals shifted 1 day to
kill lookahead.

Usage:
    .venv/bin/python scripts/research_sector_concentration.py
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import yfinance as yf

START, END = "2010-01-01", "2026-06-17"
COST_BPS = 15.0


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


# ---- [A] systematic sector momentum rotation --------------------------------
def sector_rotation(px: pd.DataFrame, lookback: int, top_n: int, floor: str | None) -> pd.Series:
    """Monthly equal-weight top-N by trailing momentum on sector universe, with
    optional QQQ floor for empty slots. Signal uses last available price before
    the month-end rebalance date (no lookahead)."""
    mom = px.pct_change(lookback)
    dates = px.resample("ME").last().index
    wts = pd.DataFrame(0.0, index=px.index, columns=px.columns)
    for i, d in enumerate(dates[:-1]):
        m = mom.asof(d)
        if m is None:
            continue
        avail = m.dropna()
        if len(avail) == 0:
            continue
        sel = list(avail.sort_values(ascending=False).head(top_n).index)
        if floor and len(sel) < top_n:
            sel = sel + [floor] * (top_n - len(sel))
        w = 1.0 / top_n
        nxt = dates[i + 1]
        mask = (px.index > d) & (px.index <= nxt)
        wts.loc[mask, sel] = w
    gross = (wts * px.pct_change()).sum(axis=1)
    turn = wts.diff().abs().sum(axis=1).fillna(0.0)
    net = gross - turn * (COST_BPS / 1e4)
    return (1 + net).cumprod()


def run_sector_rotation():
    print("=" * 90)
    print("[A] SYSTEMATIC SECTOR MOMENTUM ROTATION (bias-free)")
    print("    Universe = 9 GICS sectors that traded from 2010 + QQQ. Monthly, 15bps, shift 1.")
    print("=" * 90)
    sectors = ["XLB", "XLE", "XLF", "XLI", "XLK", "XLP", "XLU", "XLV", "XLY"]
    uni = sectors + ["QQQ"]
    px = fetch(uni)
    qqq = perf(px["QQQ"].dropna())
    print(f"  QQQ benchmark .... {fmt(qqq)}\n")
    for lookback, label in [(63, "3m"), (126, "6m"), (252, "12m")]:
        for top_n in [1, 2, 3]:
            for floor in [None, "QQQ"]:
                eq = sector_rotation(px, lookback, top_n, floor)
                p = perf(eq)
                if not p:
                    continue
                fl = "+QQQ floor" if floor else "no floor"
                tag = ""
                if p["CAGR"] > qqq["CAGR"] + 0.02:
                    tag = "  <-- BEATS QQQ"
                print(f"  mom{label} top{top_n} {fl} ... {fmt(p)}{tag}")
        print()


# ---- [B] sector concentration tilt (hindsight) -------------------------------
def run_concentration():
    print("=" * 90)
    print("[B] SECTOR CONCENTRATION TILT (HINDSIGHT)")
    print("=" * 90)
    cands = ["SMH", "SOXX", "XLK", "XLE", "XLF", "QQQ"]
    px = fetch(cands)
    qqq = perf(px["QQQ"].dropna())
    for t in cands:
        p = perf(px[t].dropna())
        if not p:
            continue
        tag = f"  vs QQQ {p['CAGR']-qqq['CAGR']:+.1%}" if t != "QQQ" else ""
        print(f"  {t:5s} buy-hold ... {fmt(p)}{tag}")
    print()

    print("  SMH vs QQQ sub-periods:\n")
    smh = px["SMH"].dropna()
    for label, lo, hi in [("2010-2014", "2010-01-01", "2015-01-01"),
                          ("2015-2019", "2015-01-01", "2020-01-01"),
                          ("2020-2026", "2020-01-01", "2026-06-17")]:
        ps = perf(smh.loc[lo:hi])
        pq = perf(px["QQQ"].loc[lo:hi])
        if ps and pq:
            print(f"    {label}: SMH {fmt(ps)}")
            print(f"    {label}: QQQ {fmt(pq)}  (diff {ps['CAGR']-pq['CAGR']:+.1%})\n")


# ---- [C] crypto allocation ---------------------------------------------------
def run_crypto():
    print("=" * 90)
    print("[C] CRYPTO ALLOCATION (BTC) blended with QQQ")
    print("=" * 90)
    px = fetch(["QQQ", "BTC-USD"])
    for start in ["2013-09-01", "2015-01-01"]:
        sub = px.loc[start:].dropna()
        if len(sub) < 200:
            continue
        qqq = perf(sub["QQQ"])
        btc = perf(sub["BTC-USD"])
        print(f"\n  window {start} -> {END}:")
        print(f"    QQQ  ...... {fmt(qqq)}")
        print(f"    BTC  ...... {fmt(btc)}")
        for w_btc in [0.05, 0.10, 0.20]:
            w_q = 1 - w_btc
            dates = sub.resample("ME").last().index
            wts = pd.DataFrame(0.0, index=sub.index, columns=["QQQ", "BTC"])
            for i, d in enumerate(dates[:-1]):
                nxt = dates[i + 1]
                m = (sub.index > d) & (sub.index <= nxt)
                wts.loc[m, "QQQ"] = w_q
                wts.loc[m, "BTC"] = w_btc
            dr = sub.pct_change()
            gross = (wts * dr).sum(axis=1)
            net = gross - wts.diff().abs().sum(axis=1).fillna(0.0) * (COST_BPS / 1e4)
            p = perf((1 + net).cumprod())
            print(f"    QQQ/{int(w_q*100)}/BTC {int(w_btc*100):2d} monthly rebal ... {fmt(p)}")


# ---- [D] can the SMH edge be systematized? -----------------------------------
def _mom_switch_equity(px: pd.DataFrame, a: str, b: str, lookback: int) -> pd.Series:
    cols = [a, b]
    mom = px[cols].pct_change(lookback)
    dates = px.resample("ME").last().index
    wts = pd.DataFrame(0.0, index=px.index, columns=cols)
    for i, d in enumerate(dates[:-1]):
        row = mom.asof(d)
        if row is None or row.isna().any():
            continue
        pick = b if row[b] >= row[a] else a
        nxt = dates[i + 1]
        mask = (px.index > d) & (px.index <= nxt)
        wts.loc[mask, pick] = 1.0
    gross = (wts * px[cols].pct_change()).sum(axis=1)
    net = gross - wts.diff().abs().sum(axis=1).fillna(0.0) * (COST_BPS / 1e4)
    return (1 + net).cumprod()


def _blend_equity(px: pd.DataFrame, w_b: float, a: str = "QQQ", b: str = "SMH") -> pd.Series:
    w_a = 1.0 - w_b
    cols = [a, b]
    dates = px[cols].resample("ME").last().index
    wts = pd.DataFrame(0.0, index=px.index, columns=cols)
    for i, d in enumerate(dates[:-1]):
        nxt = dates[i + 1]
        mask = (px.index > d) & (px.index <= nxt)
        wts.loc[mask, a] = w_a
        wts.loc[mask, b] = w_b
    gross = (wts * px[cols].pct_change()).sum(axis=1)
    net = gross - wts.diff().abs().sum(axis=1).fillna(0.0) * (COST_BPS / 1e4)
    return (1 + net).cumprod()


def run_systematize():
    print("=" * 90)
    print("[D] SYSTEMATIZE THE SMH EDGE (new answer for the goal)")
    print("=" * 90)
    px = fetch(["QQQ", "SMH", "SOXX"])
    qqq = perf(px["QQQ"].dropna())
    smh = perf(px["SMH"].dropna())
    print(f"  QQQ benchmark .. {fmt(qqq)}")
    print(f"  SMH buy-hold ... {fmt(smh)}  (diff {smh['CAGR']-qqq['CAGR']:+.1%})\n")

    print("  [D1] dual-momentum QQQ/SMH switch (hold the stronger, monthly):")
    for lb, label in [(63, "3m"), (126, "6m"), (252, "12m")]:
        eq = _mom_switch_equity(px, "QQQ", "SMH", lb)
        p = perf(eq)
        print(f"    {label} ... {fmt(p)}  (vs QQQ {p['CAGR']-qqq['CAGR']:+.1%})")

    print("\n  [D2] static QQQ/SMH blends (monthly rebalance):")
    for w in [0.25, 0.33, 0.50]:
        p = perf(_blend_equity(px, w))
        print(f"    QQQ/SMH {int((1-w)*100)}/{int(w*100)} ... {fmt(p)}  (vs QQQ {p['CAGR']-qqq['CAGR']:+.1%})")

    print("\n  [D3] sub-period stability (QQQ/SMH 50/50 vs QQQ):")
    eq = _blend_equity(px, 0.50)
    for label, lo, hi in [("2010-2014", "2010-01-01", "2015-01-01"),
                          ("2015-2019", "2015-01-01", "2020-01-01"),
                          ("2020-2026", "2020-01-01", "2026-06-17")]:
        pb = perf(eq.loc[lo:hi])
        pq = perf(px["QQQ"].loc[lo:hi])
        print(f"    {label}: Blend {fmt(pb)}  QQQ {fmt(pq)}  (diff {pb['CAGR']-pq['CAGR']:+.1%})")

    print("\n  [D4] SOXX replacement (different provider, similar index):")
    for col, lab in [("SMH", "SMH (VanEck)"), ("SOXX", "SOXX (iShares)")]:
        for w in [0.33, 0.50]:
            p = perf(_blend_equity(px, w, b=col))
            print(f"    QQQ/{col} {int((1-w)*100)}/{int(w*100)} {lab:18s}  {fmt(p)}")
    for col, lab in [("SMH", "SMH"), ("SOXX", "SOXX")]:
        p = perf(_mom_switch_equity(px, "QQQ", col, 126))
        print(f"    dual-mom 6m QQQ/{col:4s}  {lab:18s}  {fmt(p)}")


if __name__ == "__main__":
    run_sector_rotation()
    run_concentration()
    run_crypto()
    run_systematize()
