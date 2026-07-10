"""Backtest + 優化: Larry Williams 三規律 (SMA 趨勢 + %R 進場 + ROC 動量出場).

邏輯 (long-only, 同 TradingView 風格):
  Filter: close > trendMA
  Entry:  %R 超賣 (cross 進入 / level 處於超賣區)
  Exit:   ROC 穿自身 MA (roc / roc_pos) 或 跌穿 trendMA (trend_only / 兼用)
  禁止:  動量出場後同一次「超賣狀態」再入 (reentry=False 時)

執行: 收市確認訊號 → 下一根開市成交, commission 0.05% 單邊, 100% equity.

用法:
  uv run python scripts/backtest_wpr_three_rules.py
  uv run python scripts/backtest_wpr_three_rules.py --quick
"""

from __future__ import annotations

import argparse
import itertools
from dataclasses import dataclass

import numpy as np
import pandas as pd
import yfinance as yf

COMMISSION = 0.0005
START = "2005-01-01"
TRAIN_END = "2018-12-31"
TEST_START = "2019-01-01"


# ---------------------------------------------------------------------------
# Data / indicators
# ---------------------------------------------------------------------------


def fetch(ticker: str, start: str = START) -> pd.DataFrame:
    df = yf.download(ticker, start=start, auto_adjust=True, progress=False)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    out = df[["Open", "High", "Low", "Close"]].dropna().copy()
    out.index = pd.to_datetime(out.index).tz_localize(None)
    return out


def wpr(df: pd.DataFrame, length: int) -> pd.Series:
    """Williams %R: -100 (oversold) .. 0 (overbought). Matches TV ta.wpr."""
    hh = df["High"].rolling(length).max()
    ll = df["Low"].rolling(length).min()
    return -100.0 * (hh - df["Close"]) / (hh - ll).replace(0, np.nan)


def crossunder(a: pd.Series, b: pd.Series | float) -> pd.Series:
    b_s = a * 0 + b if np.isscalar(b) else b
    return (a < b_s) & (a.shift(1) >= b_s.shift(1) if isinstance(b_s, pd.Series) else a.shift(1) >= b)


def crossover(a: pd.Series, b: pd.Series | float) -> pd.Series:
    b_s = a * 0 + b if np.isscalar(b) else b
    return (a > b_s) & (a.shift(1) <= b_s.shift(1) if isinstance(b_s, pd.Series) else a.shift(1) <= b)


@dataclass(frozen=True)
class Params:
    trend_len: int = 200
    wpr_len: int = 10
    os_lv: float = -90.0
    ob_lv: float = -10.0
    roc_len: int = 25
    roc_ma_len: int = 10
    entry_mode: str = "level"  # cross | level
    exit_mode: str = "roc_pos"  # roc | roc_pos | trend_only
    use_ma_stop: bool = True
    partial_pct: float = 0.0  # 0..1 of position
    mom_reentry: bool = False  # re-enter on mom recover without new OS
    trend_reentry: bool = False  # re-enter when price reclaims MA


def prep(df: pd.DataFrame, p: Params) -> pd.DataFrame:
    out = df.copy()
    out["trend_ma"] = out["Close"].rolling(p.trend_len).mean()
    out["wpr"] = wpr(out, p.wpr_len)
    roc = out["Close"].pct_change(p.roc_len) * 100.0
    out["roc"] = roc
    out["roc_ma"] = roc.rolling(p.roc_ma_len).mean()
    out["trend_up"] = out["Close"] > out["trend_ma"]

    in_os = out["wpr"] <= p.os_lv
    out["entry_cross"] = crossunder(out["wpr"], p.os_lv) & out["trend_up"]
    out["entry_level"] = in_os & out["trend_up"]
    # first bar of oversold-while-uptrend (edge for level mode to avoid hold-flag spam)
    out["entry_level_edge"] = out["entry_level"] & ~out["entry_level"].shift(1).fillna(False)

    out["mom_weak"] = crossunder(out["roc"], out["roc_ma"])
    out["mom_weak_pos"] = out["mom_weak"] & (out["roc"] > 0)
    out["mom_recover"] = crossover(out["roc"], out["roc_ma"])
    out["break_ma"] = crossunder(out["Close"], out["trend_ma"])
    out["trend_resume"] = crossover(out["Close"], out["trend_ma"])
    out["partial_sig"] = crossover(out["wpr"], p.ob_lv)
    return out


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------


def run(df: pd.DataFrame, p: Params) -> dict:
    """Return metrics + equity curve. Long only."""
    d = prep(df, p)
    close = d["Close"].to_numpy()
    opn = d["Open"].to_numpy()
    n = len(d)

    if p.entry_mode == "cross":
        entry_sig = d["entry_cross"].fillna(False).to_numpy()
    else:
        # level: enter on first day of OS+uptrend, or every OS day while flat
        # (flat-only handled in loop; using level truth is fine)
        entry_sig = d["entry_level"].fillna(False).to_numpy()

    if p.exit_mode == "roc":
        mom_exit = d["mom_weak"].fillna(False).to_numpy()
    elif p.exit_mode == "roc_pos":
        mom_exit = d["mom_weak_pos"].fillna(False).to_numpy()
    else:
        mom_exit = np.zeros(n, dtype=bool)

    break_ma = d["break_ma"].fillna(False).to_numpy() if p.use_ma_stop else np.zeros(n, dtype=bool)
    partial_sig = d["partial_sig"].fillna(False).to_numpy()
    mom_recover = d["mom_recover"].fillna(False).to_numpy()
    trend_resume = d["trend_resume"].fillna(False).to_numpy()
    in_os = (d["wpr"] <= p.os_lv).fillna(False).to_numpy()
    trend_up = d["trend_up"].fillna(False).to_numpy()

    cash = 100_000.0
    shares = 0.0
    pending = 0  # +1 buy, -1 full sell, -2 partial
    partial_done = False
    # after mom exit, block re-entry until leave OS (unless mom_reentry)
    block_until_fresh_os = False
    was_in_os = False

    equity = np.empty(n)
    trade_pnls: list[float] = []
    entry_px = 0.0
    entry_shares = 0.0
    warm = max(p.trend_len, p.wpr_len, p.roc_len + p.roc_ma_len) + 2

    for i in range(n):
        # execute pending at open
        if pending == 1 and shares == 0.0:
            px = opn[i] * (1 + COMMISSION)
            shares = cash / px
            cash = 0.0
            entry_px = px
            entry_shares = shares
            partial_done = False
            pending = 0
        elif pending == -1 and shares > 0.0:
            px = opn[i] * (1 - COMMISSION)
            # 必須 += : partial 止賺後 cash 已有現金, 唔可以覆蓋
            cash += shares * px
            trade_pnls.append((px / entry_px - 1.0) if entry_px > 0 else 0.0)
            shares = 0.0
            pending = 0
        elif pending == -2 and shares > 0.0 and p.partial_pct > 0:
            px = opn[i] * (1 - COMMISSION)
            sell_sh = shares * p.partial_pct
            cash += sell_sh * px
            shares -= sell_sh
            partial_done = True
            pending = 0

        if i < warm:
            equity[i] = cash + shares * close[i]
            continue

        # track OS for reentry gate
        if block_until_fresh_os:
            if was_in_os and not in_os[i]:
                block_until_fresh_os = False
        was_in_os = in_os[i]

        flat = shares == 0.0 and pending == 0
        long = shares > 0.0 and pending == 0

        if flat:
            allow = True
            if not p.mom_reentry and block_until_fresh_os:
                allow = False
            # optional trend reclaim reentry (without OS)
            if p.trend_reentry and trend_resume[i] and trend_up[i]:
                pending = 1
            elif allow and entry_sig[i]:
                pending = 1
        elif long:
            do_full = False
            reason_mom = False
            if p.exit_mode != "trend_only" and mom_exit[i]:
                do_full = True
                reason_mom = True
            if p.use_ma_stop and break_ma[i]:
                do_full = True
            if p.exit_mode == "trend_only" and break_ma[i]:
                do_full = True

            if do_full:
                pending = -1
                if reason_mom and not p.mom_reentry:
                    block_until_fresh_os = True
            elif p.partial_pct > 0 and not partial_done and partial_sig[i]:
                pending = -2

        equity[i] = cash + shares * close[i]

    # mark-to-market open trade
    if shares > 0:
        trade_pnls.append(close[-1] / entry_px - 1.0 if entry_px > 0 else 0.0)

    eq = pd.Series(equity, index=d.index)
    return metrics(eq, trade_pnls) | {"equity": eq}


def metrics(eq: pd.Series, trade_pnls: list[float] | None = None) -> dict:
    eq = eq.dropna()
    if len(eq) < 10 or eq.iloc[0] <= 0:
        return {
            "cagr": 0.0,
            "sharpe": 0.0,
            "maxdd": 0.0,
            "trades": 0,
            "win": 0.0,
            "final": float(eq.iloc[-1]) if len(eq) else 0.0,
            "exposure": 0.0,
        }
    years = max((eq.index[-1] - eq.index[0]).days / 365.25, 1e-9)
    ret = eq.pct_change().dropna()
    cagr = (eq.iloc[-1] / eq.iloc[0]) ** (1 / years) - 1
    sharpe = float(ret.mean() / ret.std() * np.sqrt(252)) if ret.std() > 0 else 0.0
    dd = float((eq / eq.cummax() - 1).min())
    # exposure: days not flat at cash-only (approx equity != initial flat growth)
    # simpler: fraction of days with non-zero daily risk vs cash
    # use days where abs return differs from 0 after warm
    exposure = float((ret.abs() > 1e-12).mean()) if len(ret) else 0.0

    wins = 0.0
    n_tr = 0
    if trade_pnls:
        n_tr = len(trade_pnls)
        wins = sum(1 for x in trade_pnls if x > 0) / n_tr if n_tr else 0.0

    return {
        "cagr": float(cagr),
        "sharpe": sharpe,
        "maxdd": dd,
        "trades": n_tr,
        "win": float(wins),
        "final": float(eq.iloc[-1]),
        "exposure": exposure,
    }


def buy_hold(df: pd.DataFrame) -> dict:
    eq = 100_000.0 * (df["Close"] / df["Close"].iloc[0])
    return metrics(eq, None) | {"equity": eq, "trades": 1, "win": 1.0}


def fmt(m: dict) -> str:
    return (
        f"CAGR {m['cagr']:.2%}  Sharpe {m['sharpe']:.2f}  "
        f"MaxDD {m['maxdd']:.1%}  trades {m['trades']}  win {m['win']:.0%}"
    )


# ---------------------------------------------------------------------------
# Sweep / report
# ---------------------------------------------------------------------------


def segment(eq: pd.Series, start=None, end=None) -> dict:
    s = eq
    if start is not None:
        s = s.loc[start:]
    if end is not None:
        s = s.loc[:end]
    return metrics(s, None)


BASELINE = Params(
    trend_len=50,
    wpr_len=20,
    os_lv=-90,
    entry_mode="cross",
    exit_mode="roc",
    partial_pct=0.5,
    mom_reentry=False,
    trend_reentry=False,
)

# From prior sweep + theory: 200MA filter, short %R, roc_pos, no reentry/partial
CANDIDATE = Params(
    trend_len=200,
    wpr_len=10,
    os_lv=-90,
    entry_mode="level",
    exit_mode="roc_pos",
    partial_pct=0.0,
    mom_reentry=False,
    trend_reentry=False,
)


def param_grid(quick: bool) -> list[Params]:
    if quick:
        trends = [50, 100, 200]
        wpr_sets = [(10, -90), (14, -85), (20, -80)]
        exits = ["roc", "roc_pos"]
        entries = ["cross", "level"]
        partials = [0.0, 0.5]
        reentries = [False]
        trend_res = [False]
        roc_sets = [(25, 10)]
    else:
        trends = [50, 100, 150, 200]
        wpr_sets = [(7, -90), (10, -90), (10, -85), (14, -85), (20, -80), (20, -90)]
        exits = ["roc", "roc_pos", "trend_only"]
        entries = ["cross", "level"]
        partials = [0.0, 0.5]
        reentries = [False, True]
        trend_res = [False, True]
        roc_sets = [(20, 10), (25, 10), (25, 5)]

    out: list[Params] = []
    for tr, (wl, os), ex, em, pp, re, tre, (rl, rm) in itertools.product(
        trends, wpr_sets, exits, entries, partials, reentries, trend_res, roc_sets
    ):
        # skip nonsense combos to shrink grid
        if ex == "trend_only" and re:
            continue
        if tre and re:
            continue
        out.append(
            Params(
                trend_len=tr,
                wpr_len=wl,
                os_lv=float(os),
                roc_len=rl,
                roc_ma_len=rm,
                entry_mode=em,
                exit_mode=ex,
                partial_pct=pp,
                mom_reentry=re,
                trend_reentry=tre,
            )
        )
    return out


def score_row(row: pd.Series) -> float:
    """Robust score: test sharpe + full sharpe - overfitting penalty - DD penalty."""
    te = row.get("te_sharpe", 0.0)
    fu = row.get("sharpe", 0.0)
    tr = row.get("tr_sharpe", 0.0)
    dd = row.get("maxdd", 0.0)
    trades = row.get("trades", 0)
    if trades < 20:
        return -9.0
    return float(fu + te - max(0.0, tr - te) + min(0.0, dd + 0.25) * 0.5)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--quick", action="store_true", help="較細 grid, 快")
    ap.add_argument(
        "--tickers",
        default="SPY,QQQ,SMH,9988.HK",
        help="comma-separated",
    )
    args = ap.parse_args()
    tickers = [t.strip() for t in args.tickers.split(",") if t.strip()]

    print("Downloading…")
    data: dict[str, pd.DataFrame] = {}
    for t in tickers:
        try:
            df = fetch(t)
            if len(df) < 400:
                print(f"  skip {t}: only {len(df)} bars")
                continue
            data[t] = df
            print(f"  {t}: {df.index[0].date()} → {df.index[-1].date()}  ({len(df)} bars)")
        except Exception as e:
            print(f"  fail {t}: {e}")

    if not data:
        raise SystemExit("no data")

    # ---- Baselines ----
    print("\n========== Baseline (原裝筆記: SMA50 %R20 cross -90 / ROC / partial50%) ==========")
    for t, df in data.items():
        m = run(df, BASELINE)
        bh = buy_hold(df)
        print(f"{t:8s}  strat {fmt(m)}")
        print(f"{'':8s}  B&H   {fmt(bh)}")

    print("\n========== Prior best candidate (SMA200 %R10 level -90 / roc_pos / no partial) ==========")
    for t, df in data.items():
        m = run(df, CANDIDATE)
        eq = m["equity"]
        tr = segment(eq, None, TRAIN_END)
        te = segment(eq, TEST_START, None)
        print(f"{t:8s}  full {fmt(m)}")
        print(f"{'':8s}  train {fmt(tr)} | test {fmt(te)}")

    # ---- Sweep ----
    grid = param_grid(args.quick)
    print(f"\n========== Sweep {len(grid)} configs × {len(data)} tickers ==========")
    rows = []
    # focus robustness on liquid US ETFs if present
    core = [t for t in ["SPY", "QQQ", "SMH"] if t in data]
    if not core:
        core = list(data.keys())[:2]

    for p in grid:
        per: dict[str, dict] = {}
        ok = True
        for t in core:
            m = run(data[t], p)
            if m["trades"] < 15:
                ok = False
                break
            eq = m["equity"]
            tr = segment(eq, None, TRAIN_END)
            te = segment(eq, TEST_START, None)
            per[t] = {**m, "tr_sharpe": tr["sharpe"], "te_sharpe": te["sharpe"], "te_cagr": te["cagr"]}
        if not ok:
            continue
        row = {
            "trend": p.trend_len,
            "wpr_len": p.wpr_len,
            "os": p.os_lv,
            "roc": f"{p.roc_len}/{p.roc_ma_len}",
            "exit": p.exit_mode,
            "entry": p.entry_mode,
            "reentry": p.mom_reentry,
            "trend_re": p.trend_reentry,
            "partial": p.partial_pct,
            "sharpe": float(np.mean([per[t]["sharpe"] for t in core])),
            "cagr": float(np.mean([per[t]["cagr"] for t in core])),
            "maxdd": float(min(per[t]["maxdd"] for t in core)),
            "tr_sharpe": float(np.mean([per[t]["tr_sharpe"] for t in core])),
            "te_sharpe": float(np.mean([per[t]["te_sharpe"] for t in core])),
            "te_cagr": float(np.mean([per[t]["te_cagr"] for t in core])),
            "trades": float(np.mean([per[t]["trades"] for t in core])),
            "win": float(np.mean([per[t]["win"] for t in core])),
        }
        row["score"] = score_row(pd.Series(row))
        rows.append(row)

    res = pd.DataFrame(rows).sort_values("score", ascending=False)
    out_path = "output/wpr_three_rules_sweep.csv"
    res.to_csv(out_path, index=False)

    show = res.head(25).copy()
    for c in ["cagr", "maxdd", "te_cagr", "win"]:
        if c in show.columns:
            show[c] = show[c].map(lambda v: f"{v:.1%}")
    for c in ["sharpe", "tr_sharpe", "te_sharpe", "score"]:
        if c in show.columns:
            show[c] = show[c].map(lambda v: f"{v:.2f}")
    show["trades"] = show["trades"].map(lambda v: f"{v:.0f}")

    print(f"\n=== Top 25 by robust score (core={core}) ===")
    pd.set_option("display.width", 220)
    pd.set_option("display.max_columns", 20)
    print(show.to_string(index=False))
    print(f"\nsaved → {out_path}  ({len(res)} rows)")

    if res.empty:
        print("no configs passed trade filter")
        return

    best = res.iloc[0]
    best_p = Params(
        trend_len=int(best["trend"]),
        wpr_len=int(best["wpr_len"]),
        os_lv=float(best["os"]),
        roc_len=int(str(best["roc"]).split("/")[0]),
        roc_ma_len=int(str(best["roc"]).split("/")[1]),
        entry_mode=str(best["entry"]),
        exit_mode=str(best["exit"]),
        partial_pct=float(best["partial"]),
        mom_reentry=bool(best["reentry"]),
        trend_reentry=bool(best["trend_re"]),
    )

    print("\n========== BEST config full report ==========")
    print(
        f"trend={best_p.trend_len}  %R({best_p.wpr_len})≤{best_p.os_lv}  "
        f"entry={best_p.entry_mode}  exit={best_p.exit_mode}  "
        f"ROC{best_p.roc_len}/MA{best_p.roc_ma_len}  partial={best_p.partial_pct}  "
        f"reentry={best_p.mom_reentry}  trend_re={best_p.trend_reentry}"
    )
    summary_rows = []
    for t, df in data.items():
        m = run(df, best_p)
        bh = buy_hold(df)
        eq = m["equity"]
        tr = segment(eq, None, TRAIN_END)
        te = segment(eq, TEST_START, None)
        print(f"\n{t}")
        print(f"  strat full  {fmt(m)}")
        print(f"  train       {fmt(tr)}")
        print(f"  test        {fmt(te)}")
        print(f"  B&H full    {fmt(bh)}")
        summary_rows.append(
            {
                "ticker": t,
                "cagr": m["cagr"],
                "sharpe": m["sharpe"],
                "maxdd": m["maxdd"],
                "win": m["win"],
                "trades": m["trades"],
                "te_sharpe": te["sharpe"],
                "te_cagr": te["cagr"],
                "bh_cagr": bh["cagr"],
                "bh_sharpe": bh["sharpe"],
                "bh_maxdd": bh["maxdd"],
            }
        )

    # also print candidate vs best side-by-side on core
    print("\n========== Usable rule of thumb (寫入 Pine 嘅預設) ==========")
    # Prefer a simple, explainable config near top if best is exotic
    simple = res[
        (res["reentry"] == False)  # noqa: E712
        & (res["trend_re"] == False)  # noqa: E712
        & (res["partial"] == 0.0)
        & (res["exit"].isin(["roc", "roc_pos"]))
    ]
    if not simple.empty:
        s0 = simple.iloc[0]
        print(
            f"建議: SMA{int(s0['trend'])} | %R({int(s0['wpr_len'])})≤{s0['os']} "
            f"| entry={s0['entry']} | exit={s0['exit']} | ROC {s0['roc']} | "
            f"no partial/reentry | score={s0['score']:.2f} "
            f"Sharpe={s0['sharpe']:.2f} teSh={s0['te_sharpe']:.2f}"
        )
        # write pine defaults hint
        pine_defaults = {
            "trend_len": int(s0["trend"]),
            "wpr_len": int(s0["wpr_len"]),
            "os": float(s0["os"]),
            "entry": str(s0["entry"]),
            "exit": str(s0["exit"]),
            "roc": str(s0["roc"]),
            "partial": 0.0,
        }
        pd.Series(pine_defaults).to_json("output/wpr_three_rules_best.json")
        print("defaults → output/wpr_three_rules_best.json")

    pd.DataFrame(summary_rows).to_csv("output/wpr_three_rules_best_summary.csv", index=False)
    print("summary → output/wpr_three_rules_best_summary.csv")


if __name__ == "__main__":
    main()
