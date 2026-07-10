"""綜合最佳策略回測: 雙引擎 (突破+RSI2) + 研究驗證嘅強化.

核心 (FINDINGS + dual-engine tune):
  BO: N日新高 + 淨MACD(5,35)>0 入場, 跌穿 M 日新低出場
  MR: 空倉時 RSI(2)<buy 且 close>200MA, RSI(2)>sell 出場
  同一時間只持一個模式; 突破優先

強化 (逐項 A/B, 只保留有幫助嘅):
  - 調參: mrBuy=15, mrSell=75, MR 專用緊止蝕 4%
  - BO: ATR Chandelier 同新低取較緊 (可選)
  - 唔加 200MA 喺突破 (已驗證有害)
  - 唔用放量

用法:
  uv run python scripts/backtest_best_composite.py
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import yfinance as yf

COMM = 0.0005
START = "1999-03-01"


def fetch(ticker: str) -> pd.DataFrame:
    df = yf.download(ticker, start=START, auto_adjust=True, progress=False)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    out = df[["Open", "High", "Low", "Close"]].dropna().copy()
    out.index = pd.to_datetime(out.index).tz_localize(None)
    return out


def prep(df: pd.DataFrame, bo: int, ex: int, fast: int, slow: int, ma: int) -> pd.DataFrame:
    d = df.copy()
    c = d["Close"]
    d["macd"] = c.ewm(span=fast, adjust=False).mean() - c.ewm(span=slow, adjust=False).mean()
    d["hh"] = d["High"].rolling(bo).max().shift(1)
    d["ll"] = d["Low"].rolling(ex).min().shift(1)
    d["ma"] = c.rolling(ma).mean()
    # RSI(2) Wilder-ish via ewm alpha=1/n
    delta = c.diff()
    up = delta.clip(lower=0).ewm(alpha=1 / 2, adjust=False).mean()
    dn = (-delta.clip(upper=0)).ewm(alpha=1 / 2, adjust=False).mean()
    d["rsi2"] = 100 - 100 / (1 + up / dn.replace(0, np.nan))
    tr = np.maximum(
        d["High"] - d["Low"],
        np.maximum((d["High"] - c.shift(1)).abs(), (d["Low"] - c.shift(1)).abs()),
    )
    d["atr"] = tr.ewm(alpha=1 / 22, adjust=False).mean()
    # Weinstein-ish soft stage: price>ma and ma rising
    d["ma_up"] = d["ma"] > d["ma"].shift(10)
    d["stage2ish"] = (c > d["ma"]) & d["ma_up"]
    return d


def run(
    df: pd.DataFrame,
    *,
    bo: int = 15,
    ex: int = 20,
    fast: int = 5,
    slow: int = 35,
    ma: int = 200,
    mr_buy: float = 10,
    mr_sell: float = 70,
    use_mr: bool = True,
    use_bo: bool = True,
    bo_stop_pct: float | None = 8.0,  # None = off
    mr_stop_pct: float | None = None,
    chandelier: float | None = None,  # ATR mult; None = off
    bo_require_stage: bool = False,  # 有害候選
    mr_only_stage2: bool = False,
) -> dict:
    d = prep(df, bo, ex, fast, slow, ma)
    o = d["Open"].to_numpy()
    h = d["High"].to_numpy()
    lo = d["Low"].to_numpy()
    c = d["Close"].to_numpy()
    macd = d["macd"].to_numpy()
    hh = d["hh"].to_numpy()
    ll = d["ll"].to_numpy()
    ma_a = d["ma"].to_numpy()
    rsi = d["rsi2"].to_numpy()
    atr = d["atr"].to_numpy()
    st2 = d["stage2ish"].fillna(False).to_numpy()
    n = len(d)

    cash, shares = 100_000.0, 0.0
    pending = 0  # 1 buy BO, 2 buy MR, -1 sell
    mode = ""
    stop_px = np.nan
    peak = np.nan
    equity = np.empty(n)
    trades = 0
    wins = 0
    entry_px = 0.0
    warm = max(bo, ex, slow, ma, 25) + 2

    for i in range(n):
        if pending in (1, 2) and shares == 0.0:
            px = o[i] * (1 + COMM)
            shares = cash / px
            cash = 0.0
            entry_px = px
            peak = c[i]
            mode = "BO" if pending == 1 else "MR"
            if mode == "BO" and bo_stop_pct:
                stop_px = entry_px * (1 - bo_stop_pct / 100)
            elif mode == "MR" and mr_stop_pct:
                stop_px = entry_px * (1 - mr_stop_pct / 100)
            else:
                stop_px = np.nan
            pending = 0
        elif pending == -1 and shares > 0.0:
            px = o[i] * (1 - COMM)
            cash = shares * px
            if px > entry_px:
                wins += 1
            trades += 1
            shares = 0.0
            mode = ""
            pending = 0
            stop_px = np.nan

        if shares > 0:
            peak = max(peak, c[i]) if not np.isnan(peak) else c[i]

        if i < warm:
            equity[i] = cash + shares * c[i]
            continue

        flat = shares == 0.0 and pending == 0
        long = shares > 0.0 and pending == 0

        if flat:
            bo_ok = (
                use_bo
                and (not np.isnan(hh[i]))
                and h[i] > hh[i]
                and macd[i] > 0
            )
            if bo_require_stage:
                bo_ok = bo_ok and st2[i]
            mr_ok = (
                use_mr
                and (not np.isnan(rsi[i]))
                and rsi[i] < mr_buy
                and c[i] > ma_a[i]
            )
            if mr_only_stage2:
                mr_ok = mr_ok and st2[i]
            if bo_ok:
                pending = 1
            elif mr_ok:
                pending = 2
        elif long:
            exit_sig = False
            if mode == "BO":
                if (not np.isnan(ll[i])) and lo[i] < ll[i]:
                    exit_sig = True
                if chandelier and not np.isnan(atr[i]) and not np.isnan(peak):
                    ch = peak - chandelier * atr[i]
                    if lo[i] < ch:
                        exit_sig = True
                if bo_stop_pct and not np.isnan(stop_px) and lo[i] < stop_px:
                    exit_sig = True
            elif mode == "MR":
                if (not np.isnan(rsi[i])) and rsi[i] > mr_sell:
                    exit_sig = True
                if mr_stop_pct and not np.isnan(stop_px) and lo[i] < stop_px:
                    exit_sig = True
            if exit_sig:
                pending = -1

        equity[i] = cash + shares * c[i]

    eq = pd.Series(equity, index=d.index)
    m = stats(eq)
    m["trades"] = trades
    m["win"] = wins / trades if trades else 0.0
    m["equity"] = eq
    return m


def stats(eq: pd.Series) -> dict:
    eq = eq.dropna()
    years = max((eq.index[-1] - eq.index[0]).days / 365.25, 1e-9)
    ret = eq.pct_change().dropna()
    cagr = (eq.iloc[-1] / eq.iloc[0]) ** (1 / years) - 1
    sharpe = float(ret.mean() / ret.std() * np.sqrt(252)) if ret.std() > 0 else 0.0
    dd = float((eq / eq.cummax() - 1).min())
    return {"cagr": float(cagr), "sharpe": sharpe, "maxdd": dd}


def seg(eq: pd.Series, start=None) -> dict:
    s = eq.loc[start:] if start else eq
    return stats(s)


def fmt(m: dict) -> str:
    extra = ""
    if "trades" in m:
        extra = f"  n={m['trades']} win={m.get('win', 0):.0%}"
    return f"CAGR {m['cagr']:.2%}  Sh {m['sharpe']:.2f}  DD {m['maxdd']:.1%}{extra}"


def buy_hold(df: pd.DataFrame) -> dict:
    eq = 100_000 * df["Close"] / df["Close"].iloc[0]
    return stats(eq) | {"equity": eq, "trades": 1, "win": 1.0}


# Named configs from research
CONFIGS: dict[str, dict] = {
    "BH": {},
    "Dual_classic (現版雙引擎)": dict(
        bo=15, ex=20, mr_buy=10, mr_sell=70, bo_stop_pct=8.0, mr_stop_pct=None
    ),
    "Dual_tuned (15/75 + MR止4%)": dict(
        bo=15, ex=20, mr_buy=15, mr_sell=75, bo_stop_pct=8.0, mr_stop_pct=4.0
    ),
    "Dual_tuned_noBOstop": dict(
        bo=15, ex=20, mr_buy=15, mr_sell=75, bo_stop_pct=None, mr_stop_pct=4.0
    ),
    "BEST: tuned + Chandelier3": dict(
        bo=15, ex=20, mr_buy=15, mr_sell=75, bo_stop_pct=None, mr_stop_pct=4.0, chandelier=3.0
    ),
    "BEST+: tuned + Chand3 + BO stop8": dict(
        bo=15, ex=20, mr_buy=15, mr_sell=75, bo_stop_pct=8.0, mr_stop_pct=4.0, chandelier=3.0
    ),
    "壞: BO要stage2": dict(
        bo=15, ex=20, mr_buy=15, mr_sell=75, bo_stop_pct=None, mr_stop_pct=4.0, bo_require_stage=True
    ),
    "壞: BO加200MA filter": dict(
        bo=15, ex=20, mr_buy=15, mr_sell=75, bo_stop_pct=None, mr_stop_pct=4.0, bo_require_stage=True
    ),
    "MR only RSI2": dict(
        bo=15, ex=20, mr_buy=15, mr_sell=75, use_bo=False, use_mr=True, mr_stop_pct=4.0
    ),
    "Chand2.5 + tuned": dict(
        bo=15, ex=20, mr_buy=15, mr_sell=75, bo_stop_pct=None, mr_stop_pct=4.0, chandelier=2.5
    ),
    "Chand3.5 + tuned": dict(
        bo=15, ex=20, mr_buy=15, mr_sell=75, bo_stop_pct=None, mr_stop_pct=4.0, chandelier=3.5
    ),
}


def main() -> None:
    tickers = ["SPY", "QQQ", "SMH"]
    data = {t: fetch(t) for t in tickers}
    for t, df in data.items():
        print(f"{t}: {df.index[0].date()} → {df.index[-1].date()}")

    # pure BO-only for reference
    CONFIGS["BO only 15/20 MACD"] = dict(
        bo=15, ex=20, use_mr=False, bo_stop_pct=None, mr_stop_pct=None
    )

    rows = []
    print("\n" + "=" * 100)
    for name, cfg in CONFIGS.items():
        print(f"\n### {name}")
        for t, df in data.items():
            if name == "BH":
                m = buy_hold(df)
                m09 = seg(m["equity"], "2009-01-01")
                m19 = seg(m["equity"], "2019-01-01")
            else:
                m = run(df, **cfg)
                m09 = seg(m["equity"], "2009-01-01")
                m19 = seg(m["equity"], "2019-01-01")
            print(f"  {t:4s} full {fmt(m)}")
            print(f"       09+  CAGR {m09['cagr']:.2%} Sh {m09['sharpe']:.2f} DD {m09['maxdd']:.1%}")
            print(f"       19+  CAGR {m19['cagr']:.2%} Sh {m19['sharpe']:.2f} DD {m19['maxdd']:.1%}")
            rows.append(
                {
                    "config": name,
                    "ticker": t,
                    "cagr": m["cagr"],
                    "sharpe": m["sharpe"],
                    "maxdd": m["maxdd"],
                    "trades": m.get("trades", 0),
                    "win": m.get("win", 0),
                    "sh09": m09["sharpe"],
                    "cagr09": m09["cagr"],
                    "dd09": m09["maxdd"],
                    "sh19": m19["sharpe"],
                    "cagr19": m19["cagr"],
                }
            )

    res = pd.DataFrame(rows)
    res.to_csv("output/best_composite_compare.csv", index=False)

    # score: avg across tickers of (sh09 + sh_full + sh19) with DD penalty
    print("\n" + "=" * 100)
    print("### Ranking (avg SPY/QQQ/SMH): score = sh_full + sh09 + sh19 + min(0, dd+0.35)")
    rank_rows = []
    for name in res["config"].unique():
        sub = res[res["config"] == name]
        if name == "BH":
            continue
        score = (
            sub["sharpe"].mean()
            + sub["sh09"].mean()
            + sub["sh19"].mean()
            + min(0.0, sub["maxdd"].min() + 0.35) * 0.5
        )
        rank_rows.append(
            {
                "config": name,
                "score": score,
                "avg_sh": sub["sharpe"].mean(),
                "avg_sh09": sub["sh09"].mean(),
                "avg_sh19": sub["sh19"].mean(),
                "worst_dd": sub["maxdd"].min(),
                "avg_cagr09": sub["cagr09"].mean(),
            }
        )
    rank = pd.DataFrame(rank_rows).sort_values("score", ascending=False)
    show = rank.copy()
    show["avg_cagr09"] = show["avg_cagr09"].map(lambda x: f"{x:.1%}")
    show["worst_dd"] = show["worst_dd"].map(lambda x: f"{x:.1%}")
    for c in ["score", "avg_sh", "avg_sh09", "avg_sh19"]:
        show[c] = show[c].map(lambda x: f"{x:.2f}")
    print(show.to_string(index=False))
    rank.to_csv("output/best_composite_rank.csv", index=False)
    print("\n→ output/best_composite_compare.csv")
    print("→ output/best_composite_rank.csv")

    best = rank.iloc[0]["config"]
    print(f"\n★ 綜合冠軍: {best}")
    print("  寫入 Pine 預設用呢組邏輯。")


if __name__ == "__main__":
    main()
