"""研究：個股 apply best-strategy 家族，邊種打得贏 buy&hold。

核心發現（見 STOCK_BEAT_BH.md）:
  - 雙引擎 / MA 濾網：長牛個股 CAGR 大輸 B&H（空倉成本）
  - Vol-Target 長期 long：GOOGL/AAPL/MSFT/SMH 等多隻可三段贏
  - 高波股 (NVDA)：固定 VT35 平均槓桿 <1 → 輸；要用更高 targetVol

用法:
  uv run python scripts/research_stock_beat_bh.py
  uv run python scripts/research_stock_beat_bh.py --tickers SPY,QQQ,GOOG
"""

from __future__ import annotations

import argparse

import numpy as np
import pandas as pd
import yfinance as yf

COST = 0.0005
FIN = 0.03


def fetch(ticker: str, start: str = "2004-01-01") -> pd.DataFrame:
    df = yf.download(ticker, start=start, auto_adjust=True, progress=False)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    out = df[["Open", "High", "Low", "Close"]].dropna().copy()
    out.index = pd.to_datetime(out.index).tz_localize(None)
    return out


def stats(eq: pd.Series) -> dict:
    eq = eq.dropna()
    if len(eq) < 50 or eq.iloc[0] <= 0:
        return {"cagr": np.nan, "sharpe": np.nan, "maxdd": np.nan}
    years = max((eq.index[-1] - eq.index[0]).days / 365.25, 1e-9)
    r = eq.pct_change().dropna()
    return {
        "cagr": float((eq.iloc[-1] / eq.iloc[0]) ** (1 / years) - 1),
        "sharpe": float(r.mean() / r.std() * np.sqrt(252)) if r.std() > 0 else 0.0,
        "maxdd": float((eq / eq.cummax() - 1).min()),
    }


def run_weights(close: pd.Series, w: pd.Series, fin: float = FIN, cost: float = COST) -> pd.Series:
    ret = close.pct_change().fillna(0.0).to_numpy()
    ww = w.fillna(0.0).to_numpy()
    n = len(close)
    eq = np.empty(n)
    eq[0] = 100_000.0
    prev = 0.0
    for i in range(1, n):
        wi = float(ww[i - 1])
        eq[i] = eq[i - 1] * (1.0 + wi * ret[i] - max(wi - 1.0, 0.0) * (fin / 252)) * (
            1.0 - abs(wi - prev) * cost
        )
        prev = wi
    return pd.Series(eq, index=close.index)


def prep(df: pd.DataFrame) -> pd.DataFrame:
    d = df.copy()
    c = d["Close"]
    d["macd"] = c.ewm(span=5, adjust=False).mean() - c.ewm(span=35, adjust=False).mean()
    d["hh"] = d["High"].rolling(15).max().shift(1)
    d["ll"] = d["Low"].rolling(20).min().shift(1)
    d["ma"] = c.rolling(200).mean()
    delta = c.diff()
    up = delta.clip(lower=0).ewm(alpha=0.5, adjust=False).mean()
    dn = (-delta.clip(upper=0)).ewm(alpha=0.5, adjust=False).mean()
    d["rsi2"] = 100 - 100 / (1 + up / dn.replace(0, np.nan))
    d["ret"] = c.pct_change()
    d["vol"] = d["ret"].rolling(40).std() * np.sqrt(252)
    return d


def dual_w(d: pd.DataFrame, mr_buy: float = 15, mr_sell: float = 75) -> pd.Series:
    n = len(d)
    pos = np.zeros(n)
    mode = 0
    entry = 0.0
    h, lo, c = d["High"].to_numpy(), d["Low"].to_numpy(), d["Close"].to_numpy()
    hh, ll, macd = d["hh"].to_numpy(), d["ll"].to_numpy(), d["macd"].to_numpy()
    rsi, ma = d["rsi2"].to_numpy(), d["ma"].to_numpy()
    for i in range(220, n):
        if mode == 0:
            if not np.isnan(hh[i]) and h[i] > hh[i] and macd[i] > 0:
                mode, entry = 1, c[i]
            elif not np.isnan(rsi[i]) and rsi[i] < mr_buy and c[i] > ma[i]:
                mode, entry = 2, c[i]
        elif mode == 1:
            if (not np.isnan(ll[i]) and lo[i] < ll[i]) or lo[i] < entry * 0.92:
                mode = 0
        elif mode == 2:
            if (not np.isnan(rsi[i]) and rsi[i] > mr_sell) or lo[i] < entry * 0.96:
                mode = 0
        pos[i] = 1.0 if mode else 0.0
    return pd.Series(pos, index=d.index)


def vt_w(vol: pd.Series, target: float, cap: float, floor: float = 0.0) -> pd.Series:
    lev = (target / vol.replace(0, np.nan)).clip(lower=floor, upper=cap)
    return lev.fillna(1.0)


def period_stats(eq: pd.Series, bh: pd.Series, start: str | None) -> tuple[dict, dict, bool]:
    s = eq if start is None else eq.loc[start:]
    b = bh if start is None else bh.loc[start:]
    if len(s) < 100:
        return {"cagr": np.nan}, {"cagr": np.nan}, False
    ms, mb = stats(s), stats(b)
    return ms, mb, ms["cagr"] > mb["cagr"]


def analyze_ticker(ticker: str, start: str) -> pd.DataFrame:
    df = fetch(ticker, start)
    d = prep(df)
    close = df["Close"]
    bh = 100_000.0 * close / close.iloc[0]
    always = pd.Series(1.0, index=close.index)
    med_vol = float(d["vol"].median())

    configs: dict[str, pd.Series] = {
        "B&H": run_weights(close, always),
        "Dual_tuned": run_weights(close, dual_w(d)),
        "MA200": run_weights(close, (close > d["ma"]).astype(float)),
        "VT30_cap1.5": run_weights(close, vt_w(d["vol"], 0.30, 1.5)),
        "VT40_cap1.5": run_weights(close, vt_w(d["vol"], 0.40, 1.5)),
        "VT35_cap2": run_weights(close, vt_w(d["vol"], 0.35, 2.0)),
        "VT40_cap2": run_weights(close, vt_w(d["vol"], 0.40, 2.0)),
        "VT_adapt_1.3med": run_weights(close, vt_w(d["vol"], max(0.25, med_vol * 1.3), 2.5)),
        "Dual*VT35": run_weights(close, dual_w(d) * vt_w(d["vol"], 0.35, 2.0)),
        "Fixed_1.5x": run_weights(close, always * 1.5),
    }

    rows = []
    print(f"\n### {ticker}  n={len(df)}  {df.index[0].date()}→{df.index[-1].date()}  medVol={med_vol:.1%}")
    print(f"{'config':20s} {'full':>14s} {'09+':>14s} {'19+':>14s} beat")
    for name, eq in configs.items():
        beats = 0
        parts = []
        rec = {"ticker": ticker, "config": name, "med_vol": med_vol}
        for lab, start_p in [("full", None), ("09", "2009-01-01"), ("19", "2019-01-01")]:
            ms, mb, win = period_stats(eq, bh, start_p)
            beats += int(win)
            rec[f"cagr_{lab}"] = ms.get("cagr", np.nan)
            rec[f"sh_{lab}"] = ms.get("sharpe", np.nan)
            rec[f"dd_{lab}"] = ms.get("maxdd", np.nan)
            rec[f"bh_{lab}"] = mb.get("cagr", np.nan)
            rec[f"beat_{lab}"] = win
            if ms.get("cagr") == ms.get("cagr"):
                parts.append(f"{ms['cagr']:.1%}{'*' if win else ''}")
            else:
                parts.append("n/a")
        rec["beats"] = beats
        rows.append(rec)
        print(f"{name:20s} {parts[0]:>14s} {parts[1]:>14s} {parts[2]:>14s}  {beats}/3")

    # recommendation
    viable = [r for r in rows if r["config"] != "B&H" and r["beats"] >= 2]
    viable.sort(key=lambda r: (-r["beats"], -r.get("cagr_09", 0) or 0))
    if viable:
        best = viable[0]
        print(
            f"→ 建議: {best['config']}  "
            f"(beats {best['beats']}/3, 09 CAGR {best['cagr_09']:.1%} vs BH {best['bh_09']:.1%})"
        )
        if med_vol > 0.38 and best["config"].startswith("VT35"):
            print("  注意: 中位波動偏高，VT35 可能平均槓桿<1；可優先試 VT_adapt_1.3med")
    else:
        print("→ 無配置穩贏兩段以上；考慮 B&H 或提高 targetVol／接受更大 DD")
    return pd.DataFrame(rows)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--tickers",
        default="SPY,QQQ,GOOG",
        help="comma-separated",
    )
    args = ap.parse_args()
    tickers = [t.strip().upper() for t in args.tickers.split(",") if t.strip()]
    starts = {
        "META": "2012-05-18",
        "GOOGL": "2004-08-19",
        "GOOG": "2014-03-27",
    }

    all_rows = []
    for t in tickers:
        try:
            all_rows.append(analyze_ticker(t, starts.get(t, "2004-01-01")))
        except Exception as e:
            print(f"fail {t}: {e}")

    if all_rows:
        out = pd.concat(all_rows, ignore_index=True)
        out.to_csv("output/stock_beat_bh_research.csv", index=False)
        print("\n→ output/stock_beat_bh_research.csv")
        print("說明文件: STOCK_BEAT_BH.md")


if __name__ == "__main__":
    main()
