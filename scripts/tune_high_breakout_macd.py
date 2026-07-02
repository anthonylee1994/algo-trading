"""Tune 順勢突破 MACD 策略 (pine/high_breakout_macd_strategy.pine).

忠實模擬 TradingView 執行:
  - 訊號喺收市確認 (high > 前N日最高, MACD line > 0, close > MA)
  - strategy.entry / strategy.close 喺下一根開市價成交
  - 冇 pyramiding, 100% equity, 0.05% commission 每邊

Sweep: breakoutLen, exitLen, MACD(fast,slow,signal), maLen, 濾網開關.
驗證: train 2009-2018 / test 2019-now, 跨 QQQ/SPY/SMH robustness.
"""

from __future__ import annotations

import itertools

import numpy as np
import pandas as pd
import yfinance as yf

COMMISSION = 0.0005
START = "2009-01-01"
SPLIT = "2019-01-01"


def fetch(ticker: str) -> pd.DataFrame:
    df = yf.download(ticker, start=START, auto_adjust=True, progress=False)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    return df[["Open", "High", "Low", "Close"]].dropna()


def backtest(
    df: pd.DataFrame,
    breakout_len: int,
    exit_len: int,
    fast: int,
    slow: int,
    ma_len: int,
    use_macd: bool,
    use_ma: bool,
) -> pd.Series:
    """Return daily equity curve, pine-style next-open execution."""
    close = df["Close"].to_numpy()
    high = df["High"].to_numpy()
    low = df["Low"].to_numpy()
    opn = df["Open"].to_numpy()

    macd = (
        df["Close"].ewm(span=fast, adjust=False).mean()
        - df["Close"].ewm(span=slow, adjust=False).mean()
    ).to_numpy()
    ma = df["Close"].rolling(ma_len).mean().to_numpy()
    hh = df["High"].rolling(breakout_len).max().shift(1).to_numpy()
    ll = df["Low"].rolling(exit_len).min().shift(1).to_numpy()

    buy_sig = (high > hh) & ((not use_macd) | (macd > 0)) & ((not use_ma) | (close > ma))
    sell_sig = low < ll

    cash = 100_000.0
    shares = 0.0
    pending = 0  # +1 buy at next open, -1 sell at next open
    curve = np.empty(len(df))
    n_trades = 0
    warm = max(ma_len if use_ma else 0, breakout_len, exit_len, slow) + 1

    for i in range(len(df)):
        if pending == 1 and shares == 0.0:
            shares = cash / (opn[i] * (1 + COMMISSION))
            cash = 0.0
            pending = 0
        elif pending == -1 and shares > 0.0:
            cash = shares * opn[i] * (1 - COMMISSION)
            shares = 0.0
            pending = 0
            n_trades += 1
        if i >= warm and not np.isnan(hh[i]):
            if shares == 0.0 and pending == 0 and buy_sig[i]:
                pending = 1
            elif shares > 0.0 and pending == 0 and sell_sig[i]:
                pending = -1
        curve[i] = cash + shares * close[i]

    eq = pd.Series(curve, index=df.index)
    eq.attrs["trades"] = n_trades
    return eq


def stats(eq: pd.Series) -> dict:
    years = (eq.index[-1] - eq.index[0]).days / 365.25
    ret = eq.pct_change().dropna()
    cagr = (eq.iloc[-1] / eq.iloc[0]) ** (1 / years) - 1
    dd = (eq / eq.cummax() - 1).min()
    sharpe = ret.mean() / ret.std() * np.sqrt(252) if ret.std() > 0 else 0.0
    return {"cagr": cagr, "sharpe": sharpe, "maxdd": dd}


def seg(eq: pd.Series, start=None, end=None) -> dict:
    s = eq.loc[start:end]
    return stats(s)


def main() -> None:
    tickers = ["QQQ", "SPY", "SMH"]
    data = {t: fetch(t) for t in tickers}
    for t, df in data.items():
        b = stats(df["Close"].to_frame("eq")["eq"])
        print(f"{t} buy-hold: CAGR {b['cagr']:.2%}  Sharpe {b['sharpe']:.2f}  MaxDD {b['maxdd']:.1%}")

    breakout_lens = [10, 15, 20, 30, 40, 55]
    exit_lens = [5, 10, 15, 20, 30, 40, 60]
    macd_sets = [(5, 35), (12, 26), (8, 24)]
    ma_lens = [100, 150, 200]
    filters = [(True, True), (True, False), (False, True), (False, False)]

    rows = []
    for b, e, (f, s), m, (um, uma) in itertools.product(
        breakout_lens, exit_lens, macd_sets, ma_lens, filters
    ):
        if not um and (f, s) != (5, 35):
            continue  # macd off → macd params 冇意義
        if not uma and m != 200:
            continue
        per = {}
        ok = True
        for t in tickers:
            eq = backtest(data[t], b, e, f, s, m, um, uma)
            tr = seg(eq, None, SPLIT)
            te = seg(eq, SPLIT, None)
            fu = stats(eq)
            if eq.attrs["trades"] < 8:
                ok = False
                break
            per[t] = (fu, tr, te)
        if not ok:
            continue
        # score: 全期 Sharpe 平均 - 過擬合懲罰 (train/test Sharpe 落差)
        full_sharpe = np.mean([per[t][0]["sharpe"] for t in tickers])
        test_sharpe = np.mean([per[t][2]["sharpe"] for t in tickers])
        train_sharpe = np.mean([per[t][1]["sharpe"] for t in tickers])
        full_cagr = np.mean([per[t][0]["cagr"] for t in tickers])
        worst_dd = min(per[t][0]["maxdd"] for t in tickers)
        score = full_sharpe + test_sharpe - max(0, train_sharpe - test_sharpe)
        rows.append(
            {
                "b": b, "e": e, "macd": f"{f}/{s}" if um else "off",
                "ma": m if uma else "off",
                "CAGR": full_cagr, "Sharpe": full_sharpe,
                "trSh": train_sharpe, "teSh": test_sharpe,
                "wDD": worst_dd, "score": score,
            }
        )

    res = pd.DataFrame(rows).sort_values("score", ascending=False)
    pd.set_option("display.width", 200)
    fmt = res.copy()
    fmt["CAGR"] = fmt["CAGR"].map("{:.2%}".format)
    fmt["wDD"] = fmt["wDD"].map("{:.1%}".format)
    for c in ["Sharpe", "trSh", "teSh", "score"]:
        fmt[c] = fmt[c].map("{:.2f}".format)
    print("\n=== Top 25 by robust score (跨 QQQ/SPY/SMH 平均) ===")
    print(fmt.head(25).to_string(index=False))
    print("\n=== 現版 20/10 MACD5-35 MA200 ===")
    cur = fmt[(res.b == 20) & (res.e == 10) & (res.macd == "5/35") & (res.ma == 200)]
    print(cur.to_string(index=False))
    res.to_csv("output/tune_high_breakout_full.csv", index=False)
    print("\nfull grid saved to output/tune_high_breakout_full.csv")


if __name__ == "__main__":
    main()
