"""Aggressive individual-tilt portfolio vs QQQ (recent performance, no leverage).

Takes today's screener "dual-strong" basket (the LIST-3 names from
screen_forward_candidates.py) and asks: if you had HELD this exact basket over the
recent trailing windows, how would the aggressive tilt portfolio have done vs QQQ and
vs the pure QQQ/SMH 50/50 blend (§11[D])?

⚠️  SELECTION-BIAS WARNING (read before trusting any number below):
   The basket is chosen using TODAY's fundamental+technical snapshot. Backtesting today's
   strongest names over the past is mechanically favourable — these stocks are strong today
   LARGELY BECAUSE they ran up. So this is an UPPER-BOUND / sanity check ("does the tilt point
   the right way?"), NOT evidence of selection alpha. Selection alpha was already falsified on
   point-in-time delisting-aware data in FINDINGS §3.5. The honest read: this measures how much
   extra concentration the tilt would have added on top of the (already-validated) sector blend.

Portfolios (monthly rebalance, 15bps cost, total exposure <= 100%, no borrowing):
  - QQQ        : 100% QQQ                         (benchmark)
  - BLEND      : 50% QQQ + 50% SMH                 (§11[D] validated raw-CAGR winner)
  - TILT       : 50% QQQ + 20% SMH + 25% basket + 5% cash   (aggressive forward version)

Usage:
    .venv/bin/python scripts/research_individual_tilt_portfolio.py
"""
from __future__ import annotations

import argparse
from datetime import UTC, datetime, timedelta

import numpy as np
import pandas as pd
import yfinance as yf

# Today's screener LIST-3 "dual-strong" basket (large-cap, liquid representatives).
DEFAULT_BASKET = ["AVGO", "NVDA", "TSM", "MU", "LRCX", "ASML", "AMAT", "KLAC", "GOOG"]
COST_BPS = 15.0


def fetch(tickers: list[str], years: float, end: pd.Timestamp) -> pd.DataFrame:
    start = (end - timedelta(days=int(years * 365.25) + 10)).strftime("%Y-%m-%d")
    px = yf.download(tickers, start=start, end=end.strftime("%Y-%m-%d"),
                     progress=False, auto_adjust=True)["Close"]
    if isinstance(px, pd.Series):
        px = px.to_frame(name=tickers[0])
    return px.sort_index().ffill().dropna(how="all")


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
    return (f"CAGR {d['CAGR']:6.1%}  Sh {d['Sharpe']:.2f}  "
            f"Vol {d['Vol']:5.1%}  MaxDD {d['MaxDD']:7.1%}  Cal {d['Calmar']:.2f}")


def fixed_blend_equity(px: pd.DataFrame, weights: dict[str, float]) -> pd.Series:
    """Monthly-rebalanced fixed-weight portfolio with turnover cost. Cash weight earns 0."""
    cols = list(weights)
    w = pd.Series(weights, dtype=float)
    month_ends = px.resample("ME").last().index
    wts = pd.DataFrame(0.0, index=px.index, columns=cols)
    for i, d in enumerate(month_ends[:-1]):
        nxt = month_ends[i + 1]
        mask = (px.index > d) & (px.index <= nxt)
        for c in cols:
            wts.loc[mask, c] = w[c]
    avail = [c for c in cols if c in px.columns]
    gross = (wts[avail] * px[avail].pct_change()).sum(axis=1)
    turn = wts[avail].diff().abs().sum(axis=1).fillna(0.0)
    net = gross - turn * (COST_BPS / 1e4)
    return (1 + net).cumprod()


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--basket", nargs="+", default=DEFAULT_BASKET)
    p.add_argument("--years", nargs="+", type=float, default=[1, 2, 3, 5])
    p.add_argument("--end", default=None, help="end date YYYY-MM-DD (default today)")
    args = p.parse_args()

    basket = list(dict.fromkeys(args.basket))  # dedupe, keep order
    end = pd.Timestamp(args.end) if args.end else pd.Timestamp(datetime.now(tz=UTC).date())
    max_years = max(args.years)
    tickers = sorted(set(["QQQ", "SMH", *basket]))
    px = fetch(tickers, max_years, end)
    if "QQQ" not in px.columns:
        raise SystemExit("QQQ price missing — aborting")

    print(f"Aggressive individual-tilt portfolio vs QQQ  (end={end.date()}, cost={COST_BPS:.0f}bps, monthly rebal)")
    print(f"Basket ({len(basket)}): {', '.join(basket)}")
    print("Portfolios: QQQ=100% QQQ | BLEND=50% QQQ+50% SMH | TILT=50% QQQ+20% SMH+25% basket+5% cash\n")

    w_basket = 0.25 / len(basket)
    tilt_w = {"QQQ": 0.50, "SMH": 0.20, **{t: w_basket for t in basket}, "_CASH_": 0.05}
    blend_w = {"QQQ": 0.50, "SMH": 0.50}

    for yrs in args.years:
        start_cut = end - timedelta(days=int(yrs * 365.25))
        seg = px.loc[px.index >= start_cut].copy()
        if len(seg) < 200:
            print(f"--- trailing {yrs}Y: insufficient data ({len(seg)} bars), skip ---\n")
            continue
        qqq_eq = (1 + seg["QQQ"].pct_change()).cumprod()
        blend_eq = fixed_blend_equity(seg, blend_w)
        tilt_eq = fixed_blend_equity(seg, tilt_w)
        print("=" * 104)
        print(f"trailing {yrs}Y  ({seg.index[0].date()} -> {seg.index[-1].date()}, {len(seg)} bars)")
        print("=" * 104)
        for label, eq in [("QQQ  (bench) ", qqq_eq), ("BLEND 50/50   ", blend_eq), ("TILT forward ", tilt_eq)]:
            d = perf(eq)
            diff = f"  vs QQQ {d['CAGR'] - perf(qqq_eq)['CAGR']:+.1%}" if d and label.startswith(("BLEND", "TILT")) else ""
            print(f"  {label} ... {fmt(d)}{diff}")
        print()

    print("=" * 104)
    print("⚠️  SELECTION-BIAS WARNING")
    print("=" * 104)
    print("Basket = TODAY's screener dual-strong names. Backtesting today's strongest stocks over")
    print("the past is mechanically favourable (they're strong today BECAUSE they ran up).")
    print("=> TILT numbers above are an UPPER BOUND / sanity check, NOT selection alpha.")
    print("   PIT delisting-aware selection alpha was falsified in FINDINGS §3.5.")
    print("=> Honest read: TILT - BLEND isolates how much EXTRA concentration the individual")
    print("   names add on top of the (already-validated) QQQ/SMH sector blend. If TILT barely")
    print("   beats BLEND, the individual picking adds nothing beyond the sector tilt.")


if __name__ == "__main__":
    main()
