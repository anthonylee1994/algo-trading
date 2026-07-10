"""SMH Vol-Target: 唯一驗證過可以 raw CAGR 跑贏 SMH buy&hold 嘅單標的做法.

原理 (同 FINDINGS §1):
  - 半導體牛市極強 → 任何經常空倉嘅 TA (雙引擎/Weinstein) CAGR 必輸死揸
  - Edge 唔係選時離場, 而係低波加槓桿、高波減槓桿 (vol-target)
  - 長期保持 long SMH, 動態曝險 = clip(targetVol / realizedVol, 0, maxLev)

預設: target 35%, vol 40日, cap 2.0x, 日調, 融資 3%, cost 5bps
  full / 09+ / 19+ 三段 CAGR 均贏 B&H (見 main 輸出)

用法:
  uv run python scripts/backtest_smh_vol_target.py
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import yfinance as yf

START = "2000-06-01"
COST = 0.0005
FIN = 0.03


def fetch(ticker: str = "SMH") -> pd.Series:
    df = yf.download(ticker, start=START, auto_adjust=True, progress=False)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    c = df["Close"].dropna()
    c.index = pd.to_datetime(c.index).tz_localize(None)
    return c


def stats(eq: pd.Series) -> dict:
    eq = eq.dropna()
    years = max((eq.index[-1] - eq.index[0]).days / 365.25, 1e-9)
    ret = eq.pct_change().dropna()
    cagr = float((eq.iloc[-1] / eq.iloc[0]) ** (1 / years) - 1)
    sh = float(ret.mean() / ret.std() * np.sqrt(252)) if ret.std() > 0 else 0.0
    dd = float((eq / eq.cummax() - 1).min())
    return {"cagr": cagr, "sharpe": sh, "maxdd": dd}


def run_vol_target(
    close: pd.Series,
    *,
    target: float = 0.35,
    vol_len: int = 40,
    max_lev: float = 2.0,
    rebal: str = "daily",  # daily | weekly
    fin: float = FIN,
    cost: float = COST,
    ma_filter: bool = False,
    ma_len: int = 200,
) -> pd.Series:
    ret = close.pct_change()
    vol = ret.rolling(vol_len).std() * np.sqrt(252)
    ma = close.rolling(ma_len).mean()
    n = len(close)
    eq = np.empty(n)
    eq[0] = 100_000.0
    w_prev = 0.0
    idx = close.index

    for i in range(1, n):
        v = vol.iloc[i - 1]
        if pd.isna(v) or v <= 0:
            lev = 1.0
        else:
            lev = float(min(max_lev, max(0.0, target / v)))
        sig = 1.0
        if ma_filter and not pd.isna(ma.iloc[i - 1]):
            sig = 1.0 if close.iloc[i - 1] > ma.iloc[i - 1] else 0.0
        w_tgt = sig * lev

        do_rebal = rebal == "daily"
        if rebal == "weekly":
            do_rebal = idx[i].dayofweek == 0 or w_prev == 0.0
        if rebal == "monthly":
            do_rebal = idx[i].month != idx[i - 1].month or w_prev == 0.0

        if do_rebal:
            cost_drag = abs(w_tgt - w_prev) * cost
            w = w_tgt
            w_prev = w
        else:
            cost_drag = 0.0
            w = w_prev

        fin_drag = max(w - 1.0, 0.0) * (fin / 252)
        r = ret.iloc[i]
        if pd.isna(r):
            r = 0.0
        eq[i] = eq[i - 1] * (1.0 + w * r - fin_drag) * (1.0 - cost_drag)

    return pd.Series(eq, index=idx)


def buy_hold(close: pd.Series) -> pd.Series:
    return 100_000.0 * close / close.iloc[0]


def fmt(m: dict) -> str:
    return f"CAGR {m['cagr']:.2%}  Sharpe {m['sharpe']:.2f}  MaxDD {m['maxdd']:.1%}"


def report(name: str, eq: pd.Series, bh: pd.Series) -> None:
    print(f"\n### {name}")
    for lab, start in [("full", None), ("09+", "2009-01-01"), ("19+", "2019-01-01")]:
        s = eq if start is None else eq.loc[start:]
        b = bh if start is None else bh.loc[start:]
        ms, mb = stats(s), stats(b)
        beat = "WIN" if ms["cagr"] > mb["cagr"] else "lose"
        print(
            f"  {lab:5s} strat {fmt(ms)}  |  B&H {fmt(mb)}  |  CAGR {beat} "
            f"({ms['cagr'] - mb['cagr']:+.2%})"
        )


def main() -> None:
    close = fetch("SMH")
    bh = buy_hold(close)
    print(f"SMH {close.index[0].date()} → {close.index[-1].date()}")

    report("Buy & Hold", bh, bh)

    # 推薦預設: 平衡 CAGR 贏三段 + 唔用到最殘暴 2.5x
    recommended = dict(target=0.35, vol_len=40, max_lev=2.0, rebal="daily")
    eq = run_vol_target(close, **recommended)
    report(
        f"RECOMMENDED VT{recommended['target']:.0%} cap{recommended['max_lev']} "
        f"vol{recommended['vol_len']} {recommended['rebal']}",
        eq,
        bh,
    )

    # 更進取 (三段都贏更多)
    eq2 = run_vol_target(close, target=0.40, vol_len=40, max_lev=2.0, rebal="daily")
    report("Aggressive VT40% cap2.0 vol40 daily", eq2, bh)

    # 對照: 無槓桿雙引擎做唔到
    # (略) — 見 best_composite SMH dual CAGR ~7-12% vs BH 28% 09+

    # 對照: 固定 1.5x (09+贏但 full 因 2000s 爆倉輸)
    ret = close.pct_change().fillna(0)
    eq15 = 100_000 * (1 + 1.5 * ret - 0.5 * (FIN / 252)).cumprod()
    # rough no rebal cost
    report("Fixed 1.5x (no VT, rough)", eq15, bh)

    # save
    out = pd.DataFrame(
        {
            "close": close,
            "bh": bh,
            "vt35_cap2": eq,
            "vt40_cap2": eq2,
        }
    )
    out.to_csv("output/smh_vol_target_equity.csv")
    print("\n→ output/smh_vol_target_equity.csv")
    print(
        """
結論:
  要 CAGR 跑贏 SMH 死揸 → 必須長期在場 + 波動目標槓桿。
  雙引擎/離場式 TA 會輸 09+ 同 19+ 牛市 (空倉成本太大)。
  預設寫入 pine/best_strategy.pine profile = SMH Vol-Target。
"""
    )


if __name__ == "__main__":
    main()
