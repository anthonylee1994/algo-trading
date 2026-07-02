"""Parameter sweep: 順勢突破策略 — 邊啲改動保得住回報.

全部 variant 都用: stop 單於突破價入場, 0.05% commission, 100% equity.
Sweep 維度:
  - breakoutLen x exitLen (Turtle S1=20/10, S2=55/20, 再試更長出場)
  - 濾網組合: MACD / 200MA / 兩者 / 冇
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import yfinance as yf

COMMISSION = 0.0005


def fetch(ticker: str, start: str) -> pd.DataFrame:
    df = yf.download(ticker, start=start, auto_adjust=True, progress=False)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    return df[["Open", "High", "Low", "Close"]].dropna()


def add_indicators(df: pd.DataFrame, breakout_len: int, exit_len: int) -> pd.DataFrame:
    df = df.copy()
    ema_fast = df["Close"].ewm(span=5, adjust=False).mean()
    ema_slow = df["Close"].ewm(span=35, adjust=False).mean()
    df["macd"] = ema_fast - ema_slow
    df["ma200"] = df["Close"].rolling(200).mean()
    df["hh"] = df["High"].rolling(breakout_len).max().shift(1)
    df["ll"] = df["Low"].rolling(exit_len).min().shift(1)
    return df.dropna()


def run(df: pd.DataFrame, use_macd: bool, use_ma: bool) -> dict:
    cash = 100_000.0
    shares = 0.0
    entry_px = np.nan
    curve = []
    trades = []
    rows = list(df.itertuples())
    for i, r in enumerate(rows):
        if shares == 0:
            prev = rows[i - 1] if i > 0 else None
            trend_ok = (
                prev is not None
                and (not use_macd or prev.macd > 0)
                and (not use_ma or prev.Close > prev.ma200)
            )
            if trend_ok and r.High > r.hh:
                fill = max(r.hh, r.Open)
                shares = cash / (fill * (1 + COMMISSION))
                cash = 0.0
                entry_px = fill
        elif r.Low < r.ll:
            fill = min(r.ll, r.Open)
            cash = shares * fill * (1 - COMMISSION)
            trades.append(fill / entry_px - 1)
            shares = 0.0
        curve.append(cash + shares * r.Close)

    eq = pd.Series(curve, index=df.index)
    ret = eq.pct_change().dropna()
    years = (eq.index[-1] - eq.index[0]).days / 365.25
    cagr = (eq.iloc[-1] / eq.iloc[0]) ** (1 / years) - 1
    dd = (eq / eq.cummax() - 1).min()
    sharpe = ret.mean() / ret.std() * np.sqrt(252) if ret.std() > 0 else 0
    tr = np.array(trades)
    return {
        "cagr": cagr,
        "sharpe": sharpe,
        "maxdd": dd,
        "trades": len(tr),
        "win": (tr > 0).mean() if len(tr) else np.nan,
    }


def main() -> None:
    combos = [
        # (breakout, exit, macd, ma, label)
        (20, 10, True, True, "現版 20/10 MACD+MA"),
        (20, 10, True, False, "20/10 淨MACD"),
        (20, 10, False, True, "20/10 淨MA"),
        (20, 10, False, False, "20/10 冇濾網"),
        (20, 20, True, True, "20/20 MACD+MA"),
        (20, 40, True, True, "20/40 MACD+MA"),
        (55, 20, True, True, "55/20 MACD+MA (Turtle S2)"),
        (55, 20, False, True, "55/20 淨MA"),
        (55, 40, False, True, "55/40 淨MA"),
        (20, 40, False, True, "20/40 淨MA"),
        (20, 60, False, True, "20/60 淨MA"),
    ]
    for ticker in ["QQQ", "SPY", "SMH"]:
        raw = fetch(ticker, "2009-01-01")
        years = (raw.index[-1] - raw.index[0]).days / 365.25
        bh = (raw["Close"].iloc[-1] / raw["Close"].iloc[0]) ** (1 / years) - 1
        bh_dd = (raw["Close"] / raw["Close"].cummax() - 1).min()
        print(f"\n=== {ticker}  buy-hold CAGR {bh:.2%}, MaxDD {bh_dd:.1%} ===")
        out = []
        for b, e, macd, ma, label in combos:
            df = add_indicators(raw, b, e)
            r = run(df, macd, ma)
            out.append(
                {
                    "variant": label,
                    "CAGR": f"{r['cagr']:6.2%}",
                    "Sharpe": f"{r['sharpe']:5.2f}",
                    "MaxDD": f"{r['maxdd']:7.2%}",
                    "Trades": r["trades"],
                    "Win": f"{r['win']:5.1%}" if not np.isnan(r["win"]) else "-",
                }
            )
        print(pd.DataFrame(out).set_index("variant").to_string())


if __name__ == "__main__":
    main()
