"""經典技術分析方法大對決: 邊啲喺指數 ETF 上真係有效.

同一 harness: 訊號收市確認, 下一根開市價成交, 0.05% 佣金, 100% equity, long only.
QQQ 1999-2026 全歷史 + 2009 後分段.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import yfinance as yf

from tune_high_breakout_macd import stats

COMM = 0.0005


def fetch(ticker: str) -> pd.DataFrame:
    df = yf.download(ticker, start="1999-03-10", auto_adjust=True, progress=False)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    return df[["Open", "High", "Low", "Close"]].dropna()


def run_signals(df: pd.DataFrame, entry: np.ndarray, exit_: np.ndarray, warm: int = 260) -> pd.Series:
    """entry/exit: 收市確認嘅 bool array, 下一根開市價成交."""
    c, o = df["Close"].to_numpy(), df["Open"].to_numpy()
    cash, sh, pend = 100_000.0, 0.0, 0
    curve = np.full(len(df), 100_000.0)
    n = 0
    for i in range(warm, len(df)):
        if pend == 1 and sh == 0.0:
            sh = cash / (o[i] * (1 + COMM)); cash = 0.0; pend = 0
        elif pend == -1 and sh > 0.0:
            cash = sh * o[i] * (1 - COMM); sh = 0.0; pend = 0; n += 1
        if sh == 0.0 and pend == 0 and entry[i]:
            pend = 1
        elif sh > 0.0 and pend == 0 and exit_[i]:
            pend = -1
        curve[i] = cash + sh * c[i]
    eq = pd.Series(curve, index=df.index)
    eq.attrs["trades"] = n
    return eq


def rsi(close: pd.Series, n: int) -> pd.Series:
    d = close.diff()
    up = d.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean()
    dn = (-d.clip(upper=0)).ewm(alpha=1 / n, adjust=False).mean()
    return 100 - 100 / (1 + up / dn)


def build_strategies(df: pd.DataFrame) -> dict[str, tuple[np.ndarray, np.ndarray]]:
    c = df["Close"]
    h, lo = df["High"], df["Low"]
    s: dict[str, tuple[pd.Series, pd.Series]] = {}

    # --- 趨勢跟隨 ---
    sma50, sma200 = c.rolling(50).mean(), c.rolling(200).mean()
    s["黃金交叉 50/200"] = (sma50 > sma200, sma50 < sma200)
    s["200MA 擇時"] = (c > sma200, c < sma200)
    # Faber 10個月MA (用 210日 近似, 月尾先檢查)
    sma210 = c.rolling(210).mean()
    month_end = pd.Series(df.index, index=df.index).dt.month.diff().shift(-1).fillna(1) != 0
    s["Faber 10月MA (月尾檢查)"] = ((c > sma210) & month_end, (c < sma210) & month_end)
    macd = c.ewm(span=12, adjust=False).mean() - c.ewm(span=26, adjust=False).mean()
    sig = macd.ewm(span=9, adjust=False).mean()
    s["MACD 交叉 12/26/9"] = (macd > sig, macd < sig)
    # 時間序列動量: 12個月回報>0 (月尾檢查)
    mom12 = c.pct_change(252)
    s["12月動量 TSMOM (月尾)"] = ((mom12 > 0) & month_end, (mom12 < 0) & month_end)
    # 你嘅突破策略
    hh15 = h.rolling(15).max().shift(1)
    ll20 = lo.rolling(20).min().shift(1)
    macd535 = c.ewm(span=5, adjust=False).mean() - c.ewm(span=35, adjust=False).mean()
    s["突破 15/20 + MACD (你嘅)"] = ((h > hh15) & (macd535 > 0), lo < ll20)

    # --- 震盪指標 / 均值回歸 ---
    r14, r2 = rsi(c, 14), rsi(c, 2)
    s["RSI14 經典 30買/70賣"] = (r14 < 30, r14 > 70)
    s["RSI2 短線超賣 (Connors)"] = ((r2 < 10) & (c > sma200), r2 > 70)
    mid = c.rolling(20).mean()
    sd = c.rolling(20).std()
    s["Bollinger 落軌買/中軌賣"] = (c < mid - 2 * sd, c > mid)
    s["Bollinger 上軌突破"] = (c > mid + 2 * sd, c < mid)
    s["KDJ 金叉 (9,3,3) 20/80"] = (None, None)  # placeholder, 下面計
    low9, high9 = lo.rolling(9).min(), h.rolling(9).max()
    k = ((c - low9) / (high9 - low9) * 100).ewm(alpha=1 / 3, adjust=False).mean()
    d = k.ewm(alpha=1 / 3, adjust=False).mean()
    s["KDJ 金叉 (9,3,3) 20/80"] = ((k > d) & (k < 30), (k < d) & (k > 70))

    return {k: (v[0].fillna(False).to_numpy(), v[1].fillna(False).to_numpy()) for k, v in s.items()}


def main() -> None:
    df = fetch("QQQ")
    strategies = build_strategies(df)

    bh_full, bh_09 = stats(df["Close"]), stats(df["Close"].loc["2009":])
    print(f"QQQ buy-hold 全期: CAGR {bh_full['cagr']:.2%} Sharpe {bh_full['sharpe']:.2f} DD {bh_full['maxdd']:.0%}")
    print(f"QQQ buy-hold 09後: CAGR {bh_09['cagr']:.2%} Sharpe {bh_09['sharpe']:.2f} DD {bh_09['maxdd']:.0%}\n")

    rows = []
    for name, (ent, ex) in strategies.items():
        eq = run_signals(df, ent, ex)
        fu, late = stats(eq), stats(eq.loc["2009":])
        rows.append({
            "方法": name,
            "全期CAGR": f"{fu['cagr']:.1%}", "全期Sh": f"{fu['sharpe']:.2f}", "全期DD": f"{fu['maxdd']:.0%}",
            "09後CAGR": f"{late['cagr']:.1%}", "09後Sh": f"{late['sharpe']:.2f}", "09後DD": f"{late['maxdd']:.0%}",
            "交易": eq.attrs["trades"],
        })
    out = pd.DataFrame(rows).set_index("方法")
    pd.set_option("display.width", 200)
    pd.set_option("display.unicode.east_asian_width", True)
    print(out.to_string())


if __name__ == "__main__":
    main()
