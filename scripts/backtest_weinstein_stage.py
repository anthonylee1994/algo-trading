"""Backtest + 優化: Stan Weinstein 股價四階段 (30週線 / 日線 150SMA).

忠實復刻 pine/weinstein_stage_strategy.pine:
  Stage 2: close > MA and MA rising  → 好倉
  Stage 4: close < MA and MA falling → 空倉
  過渡: 離開 2 → 3 (頂); 離開 4 → 1 (底)

執行: 收市確認 → 下一根開市成交 (同 TV 預設, 比 process_orders_on_close 更保守)
佣金: 0.05% 單邊 (主 sweep); 另報 2bps 對照

改進變體:
  - exit_mode: leave2 (離第二即走) | stage4 (撑到第四) | partial3 (第三減倉)
  - entry_mode: anytime (stage==2) | transition (剛入第二) | after_stage1 (完整循環)
  - use_base / base_len 橫行突破
  - hysteresis 緩衝帶減 whipsaw
  - weekly 重採樣 (更貼原著週線)

用法:
  uv run python scripts/backtest_weinstein_stage.py
  uv run python scripts/backtest_weinstein_stage.py --quick
"""

from __future__ import annotations

import argparse
import itertools
from dataclasses import dataclass

import numpy as np
import pandas as pd
import yfinance as yf

COMMISSION = 0.0005  # 5 bps; Pine 註 2bps 另報
START = "1999-03-01"
TRAIN_END = "2018-12-31"
TEST_START = "2019-01-01"


def fetch(ticker: str, start: str = START) -> pd.DataFrame:
    df = yf.download(ticker, start=start, auto_adjust=True, progress=False)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    out = df[["Open", "High", "Low", "Close", "Volume"]].dropna().copy()
    out.index = pd.to_datetime(out.index).tz_localize(None)
    return out


def to_weekly(df: pd.DataFrame) -> pd.DataFrame:
    o = df["Open"].resample("W-FRI").first()
    h = df["High"].resample("W-FRI").max()
    lo = df["Low"].resample("W-FRI").min()
    c = df["Close"].resample("W-FRI").last()
    v = df["Volume"].resample("W-FRI").sum()
    w = pd.DataFrame({"Open": o, "High": h, "Low": lo, "Close": c, "Volume": v}).dropna()
    return w


@dataclass(frozen=True)
class Params:
    ma_len: int = 150
    slope_lb: int = 10
    use_base: bool = False
    base_len: int = 30
    use_vol: bool = False
    vol_mult: float = 1.3
    # leave2: stage!=2 即走 (現版 Pine)
    # stage4: 只喺 stage==4 全出 (第三階段繼續揸)
    # partial3: stage3 減 partial_pct, stage4 全出
    exit_mode: str = "leave2"
    partial_pct: float = 0.5
    # anytime: stage==2 即入
    # transition: 剛由非2進入2
    # after_stage1: 必須經過 stage1 後先入 stage2 (完整循環)
    entry_mode: str = "anytime"
    hysteresis: float = 0.0  # e.g. 0.01 = 要 close > ma*1.01 先算線上
    min_stage2_bars: int = 0  # 入場後最少持倉 bars (防抖)
    weekly: bool = False


def compute_stages(df: pd.DataFrame, p: Params) -> pd.DataFrame:
    out = df.copy()
    close = out["Close"]
    ma = close.rolling(p.ma_len).mean()
    out["ma"] = ma
    rising = ma > ma.shift(p.slope_lb)
    falling = ma < ma.shift(p.slope_lb)
    out["rising"] = rising
    out["falling"] = falling

    band = p.hysteresis
    above = close > ma * (1.0 + band)
    below = close < ma * (1.0 - band)

    n = len(out)
    stage = np.ones(n, dtype=np.int8)
    st = 1
    ab = above.fillna(False).to_numpy()
    be = below.fillna(False).to_numpy()
    ri = rising.fillna(False).to_numpy()
    fa = falling.fillna(False).to_numpy()

    for i in range(n):
        if ab[i] and ri[i]:
            st = 2
        elif be[i] and fa[i]:
            st = 4
        else:
            st = 3 if st in (2, 3) else 1
        stage[i] = st
    out["stage"] = stage

    # 橫行區頂 (前 bar)
    out["base_high"] = out["High"].rolling(p.base_len).max().shift(1)
    vol_ma = out["Volume"].rolling(50).mean()
    out["vol_ok"] = (not p.use_vol) | (out["Volume"] > p.vol_mult * vol_ma)

    return out


def run(df: pd.DataFrame, p: Params, commission: float = COMMISSION) -> dict:
    d = compute_stages(df, p)
    stage = d["stage"].to_numpy()
    close = d["Close"].to_numpy()
    opn = d["Open"].to_numpy()
    high = d["High"].to_numpy()
    base_high = d["base_high"].to_numpy()
    vol_ok = d["vol_ok"].fillna(True).to_numpy()
    n = len(d)

    prev_stage = np.roll(stage, 1)
    prev_stage[0] = 1
    enter_s2 = (stage == 2) & (prev_stage != 2)
    # after_stage1: track if saw stage 1 since last exit from 2
    saw_s1 = True  # allow first entry

    cash = 100_000.0
    shares = 0.0
    pending = 0  # 1 buy, -1 full sell, -2 partial
    partial_done = False
    hold_bars = 0
    equity = np.empty(n)
    trade_pnls: list[float] = []
    entry_px = 0.0
    warm = p.ma_len + p.slope_lb + 5

    # annualization: weekly vs daily
    ann = 52.0 if p.weekly else 252.0

    for i in range(n):
        if pending == 1 and shares == 0.0:
            px = opn[i] * (1 + commission)
            shares = cash / px
            cash = 0.0
            entry_px = px
            partial_done = False
            hold_bars = 0
            pending = 0
            saw_s1 = False
        elif pending == -1 and shares > 0.0:
            px = opn[i] * (1 - commission)
            cash += shares * px
            trade_pnls.append(px / entry_px - 1.0 if entry_px > 0 else 0.0)
            shares = 0.0
            pending = 0
        elif pending == -2 and shares > 0.0:
            px = opn[i] * (1 - commission)
            sell = shares * p.partial_pct
            cash += sell * px
            shares -= sell
            partial_done = True
            pending = 0

        if shares > 0:
            hold_bars += 1

        if stage[i] == 1:
            saw_s1 = True

        if i < warm:
            equity[i] = cash + shares * close[i]
            continue

        flat = shares == 0.0 and pending == 0
        long = shares > 0.0 and pending == 0

        # --- entry ---
        if flat:
            s2 = stage[i] == 2
            if p.entry_mode == "transition":
                s2 = bool(enter_s2[i])
            elif p.entry_mode == "after_stage1":
                s2 = bool(enter_s2[i]) and saw_s1

            base_ok = (not p.use_base) or (
                not np.isnan(base_high[i]) and high[i] > base_high[i]
            )
            if s2 and base_ok and vol_ok[i]:
                pending = 1

        # --- exit ---
        elif long:
            can_exit = hold_bars >= p.min_stage2_bars
            st = int(stage[i])
            if not can_exit:
                pass
            elif p.exit_mode == "leave2":
                if st != 2:
                    pending = -1
            elif p.exit_mode == "stage4":
                if st == 4:
                    pending = -1
            elif p.exit_mode == "partial3":
                if st == 4:
                    pending = -1
                elif st == 3 and not partial_done:
                    pending = -2
            else:
                if st != 2:
                    pending = -1

        equity[i] = cash + shares * close[i]

    if shares > 0 and entry_px > 0:
        trade_pnls.append(close[-1] / entry_px - 1.0)

    eq = pd.Series(equity, index=d.index)
    return metrics(eq, trade_pnls, ann) | {"equity": eq, "stages": d["stage"]}


def metrics(eq: pd.Series, trade_pnls: list[float] | None, ann: float = 252.0) -> dict:
    eq = eq.dropna()
    if len(eq) < 5 or eq.iloc[0] <= 0:
        return {
            "cagr": 0.0,
            "sharpe": 0.0,
            "maxdd": 0.0,
            "trades": 0,
            "win": 0.0,
            "final": 0.0,
            "exposure": 0.0,
        }
    years = max((eq.index[-1] - eq.index[0]).days / 365.25, 1e-9)
    ret = eq.pct_change().dropna()
    cagr = (eq.iloc[-1] / eq.iloc[0]) ** (1 / years) - 1
    sharpe = float(ret.mean() / ret.std() * np.sqrt(ann)) if ret.std() > 0 else 0.0
    dd = float((eq / eq.cummax() - 1).min())
    exposure = float((ret.abs() > 1e-12).mean()) if len(ret) else 0.0
    n_tr = len(trade_pnls) if trade_pnls else 0
    win = (sum(1 for x in trade_pnls if x > 0) / n_tr) if n_tr else 0.0
    return {
        "cagr": float(cagr),
        "sharpe": sharpe,
        "maxdd": dd,
        "trades": n_tr,
        "win": float(win),
        "final": float(eq.iloc[-1]),
        "exposure": exposure,
    }


def buy_hold(df: pd.DataFrame, ann: float = 252.0) -> dict:
    eq = 100_000.0 * (df["Close"] / df["Close"].iloc[0])
    return metrics(eq, None, ann) | {"equity": eq}


def seg(eq: pd.Series, start=None, end=None, ann: float = 252.0) -> dict:
    s = eq
    if start is not None:
        s = s.loc[start:]
    if end is not None:
        s = s.loc[:end]
    return metrics(s, None, ann)


def fmt(m: dict) -> str:
    return (
        f"CAGR {m['cagr']:.2%}  Sharpe {m['sharpe']:.2f}  "
        f"MaxDD {m['maxdd']:.1%}  trades {m['trades']}  win {m['win']:.0%}  "
        f"exp {m.get('exposure', 0):.0%}"
    )


def param_grid(quick: bool) -> list[Params]:
    if quick:
        ma_lens = [100, 150, 200]
        slopes = [5, 10, 20]
        bases = [(False, 30), (True, 30)]
        exits = ["leave2", "stage4", "partial3"]
        entries = ["anytime", "transition"]
        hyst = [0.0, 0.01]
        weeklys = [False]
        min_bars = [0]
    else:
        ma_lens = [100, 120, 150, 180, 200]
        slopes = [5, 10, 15, 20]
        bases = [(False, 30), (True, 20), (True, 30), (True, 60)]
        exits = ["leave2", "stage4", "partial3"]
        entries = ["anytime", "transition", "after_stage1"]
        hyst = [0.0, 0.005, 0.01, 0.02]
        weeklys = [False, True]
        min_bars = [0, 5]

    out: list[Params] = []
    for ma, sl, (ub, bl), ex, em, hy, wk, mb in itertools.product(
        ma_lens, slopes, bases, exits, entries, hyst, weeklys, min_bars
    ):
        # weekly: ma_len 應用週單位
        ma_eff = ma
        if wk:
            # 30週 ≈ 原著; 映射 150日→30週, 100→20, 200→40
            ma_eff = max(10, round(ma / 5))
            sl_eff = max(1, round(sl / 2)) if sl >= 5 else sl
            bl_eff = max(3, round(bl / 5))
            mb_eff = max(0, round(mb / 5)) if mb else 0
        else:
            sl_eff = sl
            bl_eff = bl
            mb_eff = mb
        out.append(
            Params(
                ma_len=ma_eff if wk else ma,
                slope_lb=sl_eff,
                use_base=ub,
                base_len=bl_eff,
                exit_mode=ex,
                entry_mode=em,
                hysteresis=hy,
                min_stage2_bars=mb_eff,
                weekly=wk,
                partial_pct=0.5,
            )
        )
    # de-dupe
    seen: set[Params] = set()
    uniq: list[Params] = []
    for p in out:
        if p not in seen:
            seen.add(p)
            uniq.append(p)
    return uniq


def score_row(r: pd.Series) -> float:
    if r["trades"] < 8:
        return -9.0
    te = r["te_sharpe"]
    fu = r["sharpe"]
    tr = r["tr_sharpe"]
    dd = r["maxdd"]
    # 偏好: 全期+測試 Sharpe, 懲罰過擬合同過大 DD
    return float(fu + te - max(0.0, tr - te) + min(0.0, dd + 0.30) * 0.4)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--quick", action="store_true")
    ap.add_argument("--tickers", default="SPY,QQQ,SMH")
    args = ap.parse_args()
    tickers = [t.strip() for t in args.tickers.split(",") if t.strip()]

    print("Downloading…")
    daily: dict[str, pd.DataFrame] = {}
    for t in tickers:
        df = fetch(t)
        if len(df) < 400:
            print(f"  skip {t}: {len(df)} bars")
            continue
        daily[t] = df
        print(f"  {t}: {df.index[0].date()} → {df.index[-1].date()} ({len(df)})")

    if not daily:
        raise SystemExit("no data")

    # cache weekly
    weekly = {t: to_weekly(df) for t, df in daily.items()}

    def data_for(p: Params, t: str) -> pd.DataFrame:
        return weekly[t] if p.weekly else daily[t]

    # ---- Baseline (現版 Pine 預設) ----
    base = Params()
    print("\n========== Baseline Pine 預設 (MA150 slope10 leave2 anytime) ==========")
    for t, df in daily.items():
        m = run(df, base)
        bh = buy_hold(df)
        eq = m["equity"]
        m09 = seg(eq, "2009-01-01", None)
        print(f"{t:6s} strat {fmt(m)}")
        print(f"{'':6s} 09+   {fmt(m09)}")
        print(f"{'':6s} B&H   {fmt(bh)}")

    # ---- 已知改進單點對照 ----
    print("\n========== 單點改進對照 (相對 baseline, 平均 SPY/QQQ) ==========")
    variants = {
        "baseline": Params(),
        "stage4_hold": Params(exit_mode="stage4"),
        "partial3": Params(exit_mode="partial3"),
        "entry_transition": Params(entry_mode="transition"),
        "after_stage1": Params(entry_mode="after_stage1"),
        "hyst_1pct": Params(hysteresis=0.01),
        "base_breakout": Params(use_base=True, base_len=30),
        "ma200": Params(ma_len=200),
        "ma100": Params(ma_len=100),
        "slope20": Params(slope_lb=20),
        "weekly30": Params(ma_len=30, slope_lb=4, weekly=True),
        "weekly30_s4": Params(ma_len=30, slope_lb=4, weekly=True, exit_mode="stage4"),
        "best_guess": Params(
            ma_len=150, slope_lb=10, exit_mode="stage4", entry_mode="transition", hysteresis=0.0
        ),
    }
    core = [t for t in ["SPY", "QQQ"] if t in daily]
    rows_v = []
    for name, p in variants.items():
        shs, cgs, dds = [], [], []
        for t in core:
            df = data_for(p, t)
            m = run(df, p)
            shs.append(m["sharpe"])
            cgs.append(m["cagr"])
            dds.append(m["maxdd"])
        rows_v.append(
            {
                "variant": name,
                "sharpe": np.mean(shs),
                "cagr": np.mean(cgs),
                "maxdd": np.min(dds),
            }
        )
    vv = pd.DataFrame(rows_v).sort_values("sharpe", ascending=False)
    show = vv.copy()
    show["cagr"] = show["cagr"].map(lambda x: f"{x:.2%}")
    show["maxdd"] = show["maxdd"].map(lambda x: f"{x:.1%}")
    show["sharpe"] = show["sharpe"].map(lambda x: f"{x:.2f}")
    print(show.to_string(index=False))

    # ---- Full sweep ----
    grid = param_grid(args.quick)
    print(f"\n========== Sweep {len(grid)} configs × {list(daily)} ==========")
    core3 = [t for t in ["SPY", "QQQ", "SMH"] if t in daily]
    if not core3:
        core3 = list(daily.keys())

    rows = []
    for p in grid:
        per = {}
        ok = True
        for t in core3:
            df = data_for(p, t)
            ann = 52.0 if p.weekly else 252.0
            m = run(df, p)
            if m["trades"] < (5 if p.weekly else 8):
                ok = False
                break
            eq = m["equity"]
            tr = seg(eq, None, TRAIN_END, ann)
            te = seg(eq, TEST_START, None, ann)
            per[t] = {
                **m,
                "tr_sharpe": tr["sharpe"],
                "te_sharpe": te["sharpe"],
                "te_cagr": te["cagr"],
            }
        if not ok:
            continue
        row = {
            "ma": p.ma_len,
            "slope": p.slope_lb,
            "base": p.use_base,
            "base_len": p.base_len,
            "exit": p.exit_mode,
            "entry": p.entry_mode,
            "hyst": p.hysteresis,
            "min_bars": p.min_stage2_bars,
            "weekly": p.weekly,
            "sharpe": float(np.mean([per[t]["sharpe"] for t in core3])),
            "cagr": float(np.mean([per[t]["cagr"] for t in core3])),
            "maxdd": float(min(per[t]["maxdd"] for t in core3)),
            "tr_sharpe": float(np.mean([per[t]["tr_sharpe"] for t in core3])),
            "te_sharpe": float(np.mean([per[t]["te_sharpe"] for t in core3])),
            "te_cagr": float(np.mean([per[t]["te_cagr"] for t in core3])),
            "trades": float(np.mean([per[t]["trades"] for t in core3])),
            "win": float(np.mean([per[t]["win"] for t in core3])),
            "exposure": float(np.mean([per[t]["exposure"] for t in core3])),
        }
        row["score"] = score_row(pd.Series(row))
        rows.append(row)

    res = pd.DataFrame(rows).sort_values("score", ascending=False)
    out_csv = "output/weinstein_stage_sweep.csv"
    res.to_csv(out_csv, index=False)

    top = res.head(30).copy()
    for c in ["cagr", "maxdd", "te_cagr", "win", "exposure"]:
        top[c] = top[c].map(lambda v: f"{v:.1%}")
    for c in ["sharpe", "tr_sharpe", "te_sharpe", "score"]:
        top[c] = top[c].map(lambda v: f"{v:.2f}")
    top["trades"] = top["trades"].map(lambda v: f"{v:.0f}")
    pd.set_option("display.width", 240)
    print(f"\n=== Top 30 by robust score (core={core3}) ===")
    print(top.to_string(index=False))
    print(f"\nsaved → {out_csv} ({len(res)} rows)")

    if res.empty:
        return

    # Prefer simple daily configs near top
    simple = res[(res["weekly"] == False) & (res["base"] == False)].copy()  # noqa: E712
    if simple.empty:
        simple = res.copy()
    best_row = simple.iloc[0]
    best_p = Params(
        ma_len=int(best_row["ma"]),
        slope_lb=int(best_row["slope"]),
        use_base=bool(best_row["base"]),
        base_len=int(best_row["base_len"]),
        exit_mode=str(best_row["exit"]),
        entry_mode=str(best_row["entry"]),
        hysteresis=float(best_row["hyst"]),
        min_stage2_bars=int(best_row["min_bars"]),
        weekly=bool(best_row["weekly"]),
    )

    print("\n========== BEST simple (daily preferred) full report ==========")
    print(best_p)
    summary = []
    for t in daily:
        df = data_for(best_p, t)
        ann = 52.0 if best_p.weekly else 252.0
        m = run(df, best_p)
        bh = buy_hold(df, ann)
        eq = m["equity"]
        tr = seg(eq, None, TRAIN_END, ann)
        te = seg(eq, TEST_START, None, ann)
        m09 = seg(eq, "2009-01-01", None, ann)
        print(f"\n{t}")
        print(f"  full  {fmt(m)}")
        print(f"  train {fmt(tr)}")
        print(f"  test  {fmt(te)}")
        print(f"  09+   {fmt(m09)}")
        print(f"  B&H   {fmt(bh)}")
        summary.append(
            {
                "ticker": t,
                "cagr": m["cagr"],
                "sharpe": m["sharpe"],
                "maxdd": m["maxdd"],
                "win": m["win"],
                "trades": m["trades"],
                "te_sharpe": te["sharpe"],
                "te_cagr": te["cagr"],
                "cagr_09": m09["cagr"],
                "sharpe_09": m09["sharpe"],
                "bh_cagr": bh["cagr"],
                "bh_sharpe": bh["sharpe"],
                "bh_maxdd": bh["maxdd"],
            }
        )

    # Absolute best including weekly
    abs_best = res.iloc[0]
    print("\n========== Absolute best (may be weekly) ==========")
    print(abs_best.to_dict())

    # Recommended defaults for Pine
    # Rank by: daily, leave2 or stage4 explainable, high score
    rec = res[
        (res["weekly"] == False)  # noqa: E712
        & (res["exit"].isin(["leave2", "stage4", "partial3"]))
    ]
    if not rec.empty:
        r0 = rec.iloc[0]
        print("\n========== 建議寫入 Pine 嘅預設 ==========")
        print(
            f"MA={int(r0['ma'])} slope={int(r0['slope'])} exit={r0['exit']} "
            f"entry={r0['entry']} hyst={r0['hyst']} base={r0['base']} "
            f"score={r0['score']:.2f} Sh={r0['sharpe']:.2f} teSh={r0['te_sharpe']:.2f}"
        )
        pd.Series(
            {
                "ma_len": int(r0["ma"]),
                "slope_lb": int(r0["slope"]),
                "exit_mode": str(r0["exit"]),
                "entry_mode": str(r0["entry"]),
                "hysteresis": float(r0["hyst"]),
                "use_base": bool(r0["base"]),
                "base_len": int(r0["base_len"]),
                "min_stage2_bars": int(r0["min_bars"]),
            }
        ).to_json("output/weinstein_stage_best.json")
        print("→ output/weinstein_stage_best.json")

    pd.DataFrame(summary).to_csv("output/weinstein_stage_best_summary.csv", index=False)
    print("→ output/weinstein_stage_best_summary.csv")

    # 2bps commission check on recommended
    if not rec.empty:
        r0 = rec.iloc[0]
        p2 = Params(
            ma_len=int(r0["ma"]),
            slope_lb=int(r0["slope"]),
            use_base=bool(r0["base"]),
            base_len=int(r0["base_len"]),
            exit_mode=str(r0["exit"]),
            entry_mode=str(r0["entry"]),
            hysteresis=float(r0["hyst"]),
            min_stage2_bars=int(r0["min_bars"]),
        )
        print("\n========== 2bps commission (貼 Pine 註解) ==========")
        for t, df in daily.items():
            m = run(df, p2, commission=0.0002)
            print(f"{t:6s} {fmt(m)}")


if __name__ == "__main__":
    main()
