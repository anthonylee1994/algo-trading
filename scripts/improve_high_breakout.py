"""升級實驗: 順勢突破 MACD 策略 (baseline 15/20 + MACD 5/35).

全部 variant 忠實模擬 pine 執行 (訊號收市確認, 下一根開市價成交,
0.05% 佣金, 100% equity, 冇 pyramiding).

實驗方向:
  A. 突破確認: intraday high (現版) vs 收市價
  B. Chandelier exit: 入場後最高收市 - k*ATR(22), 同 20日低取較緊者
  C. 入場初始止損: 入場價 - k*ATR
  D. 動態出場: MACD>0 用長出場, MACD<0 收緊
  E. MACD histogram 上升確認入場
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from tune_high_breakout_macd import SPLIT, fetch, seg, stats

COMMISSION = 0.0005


def prep(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    ema_fast = df["Close"].ewm(span=5, adjust=False).mean()
    ema_slow = df["Close"].ewm(span=35, adjust=False).mean()
    df["macd"] = ema_fast - ema_slow
    df["signal"] = df["macd"].ewm(span=5, adjust=False).mean()
    df["hist"] = df["macd"] - df["signal"]
    df["hh"] = df["High"].rolling(15).max().shift(1)
    df["hh_c"] = df["Close"].rolling(15).max().shift(1)
    tr = np.maximum(
        df["High"] - df["Low"],
        np.maximum(
            (df["High"] - df["Close"].shift(1)).abs(),
            (df["Low"] - df["Close"].shift(1)).abs(),
        ),
    )
    df["atr"] = tr.ewm(alpha=1 / 22, adjust=False).mean()
    for n in (10, 15, 20, 30, 40):
        df[f"ll{n}"] = df["Low"].rolling(n).min().shift(1)
    return df


def backtest(
    df: pd.DataFrame,
    entry_mode: str = "high",        # "high" | "close"
    exit_len: int = 20,
    chand_mult: float | None = None,  # None = off
    init_stop_atr: float | None = None,
    dyn_exit: tuple[int, int] | None = None,  # (macd>0 用, macd<0 用)
    hist_rising: bool = False,
) -> pd.Series:
    o = df["Open"].to_numpy()
    h = df["High"].to_numpy()
    lo = df["Low"].to_numpy()
    c = df["Close"].to_numpy()
    macd = df["macd"].to_numpy()
    hist = df["hist"].to_numpy()
    hh = df["hh"].to_numpy()
    hh_c = df["hh_c"].to_numpy()
    atr = df["atr"].to_numpy()
    ll = {n: df[f"ll{n}"].to_numpy() for n in (10, 15, 20, 30, 40)}

    cash, shares = 100_000.0, 0.0
    pending = 0
    entry_px = high_close = stop_px = np.nan
    curve = np.empty(len(df))
    n_trades = 0
    warm = 220

    for i in range(len(df)):
        if pending == 1 and shares == 0.0:
            shares = cash / (o[i] * (1 + COMMISSION))
            cash = 0.0
            entry_px = o[i]
            high_close = c[i]
            stop_px = entry_px - init_stop_atr * atr[i] if init_stop_atr else -np.inf
            pending = 0
        elif pending == -1 and shares > 0.0:
            cash = shares * o[i] * (1 - COMMISSION)
            shares = 0.0
            pending = 0
            n_trades += 1

        if i >= warm and not np.isnan(hh[i]):
            if shares == 0.0 and pending == 0:
                brk = c[i] > hh_c[i] if entry_mode == "close" else h[i] > hh[i]
                ok = brk and macd[i] > 0
                if hist_rising:
                    ok = ok and hist[i] > hist[i - 1]
                if ok:
                    pending = 1
            elif shares > 0.0 and pending == 0:
                high_close = max(high_close, c[i])
                e_len = exit_len
                if dyn_exit is not None:
                    e_len = dyn_exit[0] if macd[i] > 0 else dyn_exit[1]
                exit_now = lo[i] < ll[e_len][i]
                if chand_mult is not None:
                    exit_now = exit_now or c[i] < high_close - chand_mult * atr[i]
                if init_stop_atr is not None:
                    exit_now = exit_now or c[i] < stop_px
                if exit_now:
                    pending = -1
        curve[i] = cash + shares * c[i]

    eq = pd.Series(curve, index=df.index)
    eq.attrs["trades"] = n_trades
    return eq


VARIANTS: list[tuple[str, dict]] = [
    ("baseline 15/20+MACD", {}),
    ("A. 收市價突破", {"entry_mode": "close"}),
    ("B. +Chandelier 3.0 ATR", {"chand_mult": 3.0}),
    ("B. +Chandelier 4.0 ATR", {"chand_mult": 4.0}),
    ("B. +Chandelier 5.0 ATR", {"chand_mult": 5.0}),
    ("B'. 淨Chandelier4 (出場40)", {"chand_mult": 4.0, "exit_len": 40}),
    ("C. +初始止損 2 ATR", {"init_stop_atr": 2.0}),
    ("C. +初始止損 3 ATR", {"init_stop_atr": 3.0}),
    ("D. 動態出場 30/10", {"dyn_exit": (30, 10)}),
    ("D. 動態出場 40/15", {"dyn_exit": (40, 15)}),
    ("D. 動態出場 20/10", {"dyn_exit": (20, 10)}),
    ("E. +hist 上升確認", {"hist_rising": True}),
    ("A+B. 收市突破+Chand4", {"entry_mode": "close", "chand_mult": 4.0}),
    ("B+D. Chand4+動態40/15", {"chand_mult": 4.0, "dyn_exit": (40, 15)}),
]


def main() -> None:
    tickers = ["QQQ", "SPY", "SMH"]
    data = {t: prep(fetch(t)) for t in tickers}
    summary = []
    for t in tickers:
        print(f"\n=== {t} ===")
        rows = []
        for label, kw in VARIANTS:
            eq = backtest(data[t], **kw)
            fu, tr, te = stats(eq), seg(eq, None, SPLIT), seg(eq, SPLIT, None)
            rows.append(
                {
                    "variant": label,
                    "CAGR": f"{fu['cagr']:.2%}",
                    "Sharpe": f"{fu['sharpe']:.2f}",
                    "MaxDD": f"{fu['maxdd']:.1%}",
                    "trainSh": f"{tr['sharpe']:.2f}",
                    "testSh": f"{te['sharpe']:.2f}",
                    "trades": eq.attrs["trades"],
                }
            )
            summary.append({"ticker": t, "variant": label, "sharpe": fu["sharpe"],
                            "cagr": fu["cagr"], "maxdd": fu["maxdd"],
                            "te_sh": te["sharpe"], "tr_sh": tr["sharpe"]})
        print(pd.DataFrame(rows).set_index("variant").to_string())

    s = pd.DataFrame(summary)
    agg = s.groupby("variant").agg(
        Sharpe=("sharpe", "mean"), CAGR=("cagr", "mean"), wDD=("maxdd", "min"),
        teSh=("te_sh", "mean"), trSh=("tr_sh", "mean"),
    )
    agg["score"] = agg.Sharpe + agg.teSh - (agg.trSh - agg.teSh).clip(lower=0)
    agg = agg.sort_values("score", ascending=False)
    print("\n=== 三 ETF 平均 (score = Sharpe + testSh - overfit懲罰) ===")
    print(agg.to_string(float_format=lambda x: f"{x:.3f}"))


if __name__ == "__main__":
    main()
