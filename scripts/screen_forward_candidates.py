"""Forward-deployment screener: combine fundamental (moat + growth) + technical (momentum + trend).

Reads the Finviz snapshot DB at ../stock-screener/data/db.sqlite (1331 US stocks, current
snapshot ONLY — no history) and ranks today's candidates by a transparent fundamental +
technical filter. This is a FORWARD candidate generator, NOT a backtest alpha source:
the evidence for "beat QQQ raw CAGR without leverage" lives in the lagged-universe /
sector-blend backtest scripts (see FINDINGS §11[D] QQQ/SMH 50/50). This script's job is to
(a) produce today's deployable basket, and (b) cross-confirm which sector the screen itself
favours today.

Scales in the DB (verified): ROE / EPS-5Y / Sales-5Y / Gross-Margin / Debt-Equity /
Target-Upside are DECIMAL ratios (0.15 = 15%); RSI14 is 0..100; ROC125 is decimal but has
noisy outlier values for some small-caps, so we rank it by percentile instead of threshold.

Usage:
    .venv/bin/python scripts/screen_forward_candidates.py
    .venv/bin/python scripts/screen_forward_candidates.py --top-n 30 --output-csv output/forward_candidates.csv
"""
from __future__ import annotations

import argparse
import bisect
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

REPO = Path(__file__).resolve().parents[1]
DEFAULT_DB = REPO.parent / "stock-screener" / "data" / "db.sqlite"

# Hand-picked high-conviction tickers from ../stock-notes/us-stock.md (for tagging only).
WATCHLIST = {
    "NVDA", "AVGO", "TSM", "MSFT", "GOOG", "GOOGL", "META", "AMZN", "AAPL", "LLY", "MRK",
    "AMGN", "JPM", "GS", "AXP", "COIN", "NET", "NBIS", "HPE", "IBM", "NTES", "MRVL", "AMD",
    "SNDK", "MU", "V", "MA", "GE", "CAT", "HON", "BA",
}


def num(row: sqlite3.Row, key: str) -> float | None:
    v = row[key]
    return v if isinstance(v, int | float) else None


def roc_percentiles(rows: list[sqlite3.Row]) -> dict[str, float]:
    """Percentile rank (0..1) of ROC125 across the universe — robust to scaler noise."""
    vals = sorted(n for n in (num(r, "ROC125") for r in rows) if n is not None)
    total = len(vals)
    out: dict[str, float] = {}
    for r in rows:
        v = num(r, "ROC125")
        out[r["Ticker"]] = bisect.bisect_left(vals, v) / total if (v is not None and total) else 0.0
    return out


def passes_fundamental(row: sqlite3.Row, a: argparse.Namespace) -> bool:
    mc = num(row, "Market Cap")
    roe = num(row, "ROE")
    e5 = num(row, "EPS Past 5Y")
    s5 = num(row, "Sales Past 5Y")
    de = num(row, "Debt/Equity")
    gm = num(row, "Gross Margin")
    if not (mc and mc >= a.min_mcap_bn * 1e9):
        return False
    if not (roe and roe >= a.min_roe):
        return False
    if not ((e5 and e5 >= a.min_eps5y) or (s5 and s5 >= a.min_sales5y)):
        return False
    if not (de is not None and de < a.max_de):
        return False
    if not (gm and gm >= a.min_gm):
        return False
    return True


def passes_technical(row: sqlite3.Row, a: argparse.Namespace, roc_pcts: dict[str, float]) -> bool:
    rsi = num(row, "RSI14")
    ema = num(row, "EMA200Distance")
    rp = roc_pcts.get(row["Ticker"], 0.0)
    return bool(
        rsi and a.rsi_min <= rsi <= a.rsi_max
        and ema and ema > 0
        and rp >= a.roc_pct
    )


def fmt_row(row: sqlite3.Row, roc_pcts: dict[str, float]) -> str:
    mc = num(row, "Market Cap")
    mc_s = f"{mc / 1e9:.0f}B" if mc else "?"

    def pct(key: str) -> str:
        v = num(row, key)
        return f"{v * 100:.0f}%" if v is not None else "-"

    def raw(key: str, w: int = 5) -> str:
        v = num(row, key)
        return f"{v:.0f}".rjust(w) if v is not None else "-".rjust(w)

    wl = "  <WL>" if row["Ticker"] in WATCHLIST else ""
    above = "Y" if (num(row, "EMA200Distance") or 0) > 0 else "N"
    pe = num(row, "Forward P/E")
    pe_s = f"{pe:.0f}".rjust(5) if pe else "-".rjust(5)
    return (
        f"{row['Ticker']:<6}|{mc_s:>7}|{(row['Sector'] or '')[:16]:<16}"
        f"|PE{pe_s}|ROE{pct('ROE'):>5}|EPS5Y{pct('EPS Past 5Y'):>5}"
        f"|S5Y{pct('Sales Past 5Y'):>5}|DE{raw('Debt/Equity'):>5}"
        f"|GM{pct('Gross Margin'):>5}|Tgt{pct('Target Price Upside'):>5}"
        f"|RSI{raw('RSI14'):>4}|>E200{above}|FSc{raw('Fundamental Score'):>4}"
        f"|TSc{raw('Technical Score'):>4}|roc{roc_pcts.get(row['Ticker'], 0) * 100:>3.0f}%{wl}"
    )


def sector_breakdown(rows: list[sqlite3.Row]) -> dict[str, int]:
    out: dict[str, int] = {}
    for r in rows:
        out[r["Sector"] or "?"] = out.get(r["Sector"] or "?", 0) + 1
    return dict(sorted(out.items(), key=lambda kv: -kv[1]))


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--db", default=str(DEFAULT_DB))
    p.add_argument("--min-mcap-bn", type=float, default=15.0, help="min market cap in $B (default 15)")
    p.add_argument("--min-roe", type=float, default=0.18, help="min ROE as decimal (default 0.18)")
    p.add_argument("--min-eps5y", type=float, default=0.15, help="min EPS 5Y growth decimal (default 0.15)")
    p.add_argument("--min-sales5y", type=float, default=0.18, help="min Sales 5Y growth decimal (default 0.18)")
    p.add_argument("--max-de", type=float, default=1.5, help="max Debt/Equity (default 1.5)")
    p.add_argument("--min-gm", type=float, default=0.40, help="min Gross Margin decimal (default 0.40)")
    p.add_argument("--roc-pct", type=float, default=0.60, help="min ROC125 percentile (default 0.60)")
    p.add_argument("--rsi-min", type=float, default=40.0)
    p.add_argument("--rsi-max", type=float, default=78.0)
    p.add_argument("--top-n", type=int, default=25)
    p.add_argument("--output-csv", default="output/forward_candidates.csv")
    args = p.parse_args()

    db = Path(args.db)
    if not db.exists():
        raise SystemExit(f"DB not found: {db}")
    con = sqlite3.connect(db)
    con.row_factory = sqlite3.Row
    rows = con.execute("SELECT * FROM stocks").fetchall()
    con.close()

    roc_pcts = roc_percentiles(rows)
    fund = [r for r in rows if passes_fundamental(r, args)]
    tech = [r for r in rows if passes_technical(r, args, roc_pcts)]
    both = [r for r in rows if passes_fundamental(r, args) and passes_technical(r, args, roc_pcts)]

    fund.sort(key=lambda r: -(num(r, "Fundamental Score") or 0))
    tech.sort(key=lambda r: -(num(r, "Technical Score") or 0))
    both.sort(key=lambda r: -(0.5 * (num(r, "Fundamental Score") or 0) + 0.5 * (num(r, "Technical Score") or 0)))

    print(f"Forward screener — {datetime.now(tz=UTC).date().isoformat()}  |  DB: {db.name}")
    print(
        f"硬篩: MktCap>={args.min_mcap_bn}B, ROE>={args.min_roe:.0%}, "
        f"(EPS5Y>={args.min_eps5y:.0%} OR Sales5Y>={args.min_sales5y:.0%}), "
        f"D/E<{args.max_de}, GM>={args.min_gm:.0%}"
    )
    print(
        f"技術: ROC125>={args.roc_pct:.0%}pct, >EMA200, RSI {args.rsi_min:.0f}-{args.rsi_max:.0f}"
    )
    print(f"Universe {len(rows)} | Fundamental-pass {len(fund)} | Technical-pass {len(tech)} | BOTH {len(both)}\n")

    print("=" * 120)
    print(f"LIST 1 — 基本面雙強 Top{args.top_n}  [Fundamental Score desc]")
    print("=" * 120)
    for r in fund[: args.top_n]:
        print(fmt_row(r, roc_pcts))
    print("  sector:", sector_breakdown(fund))
    print("  屬筆記WL:", sorted(r["Ticker"] for r in fund if r["Ticker"] in WATCHLIST))

    print("\n" + "=" * 120)
    print(f"LIST 2 — 技術動量強勢 Top{args.top_n}  [Technical Score desc]")
    print("=" * 120)
    for r in tech[: args.top_n]:
        print(fmt_row(r, roc_pcts))

    print("\n" + "=" * 120)
    print(f"LIST 3 — 基本面+技術 交匯 雙強 {len(both)} 隻  [0.5*FSc+0.5*TSc desc]  ★ 最理想")
    print("=" * 120)
    for r in both:
        print(fmt_row(r, roc_pcts))
    print("  sector:", sector_breakdown(both))
    print("  屬筆記WL:", sorted(r["Ticker"] for r in both if r["Ticker"] in WATCHLIST))

    print("\n" + "=" * 120)
    print("LIST 4 — 筆記 watchlist 技術健康分類（執行參考）")
    print("=" * 120)
    wl_rows = sorted((r for r in rows if r["Ticker"] in WATCHLIST), key=lambda r: r["Ticker"])
    for r in wl_rows:
        ema = num(r, "EMA200Distance")
        rsi = num(r, "RSI14")
        above = ema and ema > 0
        if above and rsi and 40 <= rsi <= 78:
            tag = "STRONG"
        elif rsi and rsi > 78:
            tag = "OVERBOUGHT"
        elif not above:
            tag = "WEAK/downtrend"
        else:
            tag = "other"
        rsi_s = f"{rsi:.0f}" if rsi else "-"
        print(f"  {r['Ticker']:<6}{(r['Sector'] or '')[:18]:<18} RSI{rsi_s:>5} EMA{'ABOVE' if above else 'below'} {tag}")

    # CSV output (the deployable basket = LIST 3 both-pass).
    out_path = Path(args.output_csv)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    cols = [
        "Ticker", "Sector", "Market Cap", "Forward P/E", "ROE", "EPS Past 5Y",
        "Sales Past 5Y", "Debt/Equity", "Gross Margin", "ROC125_pct", "RSI14",
        "EMA200Distance", "Target Price Upside", "Fundamental Score",
        "Technical Score", "Total Score", "in_notes_watchlist",
    ]
    records = []
    for r in both:
        records.append({c: (r[c] if c != "ROC125_pct" and c != "in_notes_watchlist"
                            else (roc_pcts.get(r["Ticker"], 0.0) if c == "ROC125_pct"
                                  else r["Ticker"] in WATCHLIST)) for c in cols})
    pd.DataFrame(records, columns=cols).to_csv(out_path, index=False)

    print()
    print(f"CSV basket (LIST 3): {out_path}")
    print()
    print("注意: DB 係 Finviz current snapshot（無歷史）。呢個係 forward 候選生成器 + regime")
    print("cross-check，唔係 backtest alpha。大幅跑贏 QQQ raw CAGR 嘅證據來自 §11[D] QQQ/SMH 50/50。")
    print("用 LIST 3 個股做 tilt 要記住 §3.5：PIT 含退市股下選股冇獨立 alpha，只係加強同向 sector tilt。")


if __name__ == "__main__":
    main()
