"""掃描 finviz 候選股, 揾邊啲最近觸發 pine/spy_qqq_dual_engine_strategy.pine 嘅買入訊號.

獨立腳本, 淨係靠 finvizfinance / yfinance / pandas, 唔 import 專案其他 python 檔.

兩個引擎 (邏輯照抄 pine 腳本):
  1) 突破: high > 前 breakoutLen 日最高 (唔計今日) 且 淨MACD(fastLen,slowLen) > 0
  2) RSI2 撈底: RSI(rsiLen) < mrBuyTh 且 close > maLen 日 SMA
  出場: 突破倉跌穿 exitLen 日新低 / 撈底倉 RSI > mrSellTh / 止蝕 stopPct%

由 --start 開始逐日模擬持倉狀態 (跟 pine 一樣: 淨倉、突破優先、同一時間得一個倉),
先至判斷最近 --recent-days 日內係咪出現全新入場 (即之前係空倉, 嗰日先觸發). 如果之前
已經有倉未平 (例如突破咗好耐都未跌穿新低/止蝕), 就唔算做買入訊號, 因為策略實盤已經揸緊貨.
"""

from __future__ import annotations

import argparse
from pathlib import Path
import unicodedata

import pandas as pd
import yfinance as yf
from finvizfinance.screener.financial import Financial

DEFAULT_PRESET = "eps-roe-mid"

PRESET_FILTERS = {
    "eps-roe-mid": {
        "Market Cap.": "+Mid (over $2bln)",
        "EPS growthpast 5 years": "Over 20%",
        "Return on Equity": "Over +15%",
    },
    "quality-growth": {
        "Market Cap.": "+Large (over $10bln)",
        "Average Volume": "Over 1M",
        "Price": "Over $20",
        "EPS growthnext 5 years": "Over 10%",
        "Sales growthpast 5 years": "Over 10%",
        "Gross Margin": "Over 30%",
        "Operating Margin": "Positive (>0%)",
    },
    "liquid-large": {
        "Market Cap.": "+Large (over $10bln)",
        "Average Volume": "Over 1M",
        "Price": "Over $20",
    },
    "mega": {
        "Market Cap.": "Mega ($200bln and more)",
        "Average Volume": "Over 1M",
        "Price": "Over $20",
    },
    "nasdaq100": {
        "Index": "NASDAQ 100",
        "Average Volume": "Over 1M",
        "Price": "Over $20",
    },
}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--preset", choices=sorted(PRESET_FILTERS), default=DEFAULT_PRESET)
    parser.add_argument("--limit", type=int, default=200)
    parser.add_argument("--sleep-sec", type=float, default=0.2)
    parser.add_argument("--start", default="2023-01-01")
    parser.add_argument("--recent-days", type=int, default=3)
    parser.add_argument("--breakout-len", type=int, default=15)
    parser.add_argument("--exit-len", type=int, default=20)
    parser.add_argument("--fast-len", type=int, default=5)
    parser.add_argument("--slow-len", type=int, default=35)
    parser.add_argument("--rsi-len", type=int, default=2)
    parser.add_argument("--mr-buy-th", type=float, default=10)
    parser.add_argument("--mr-sell-th", type=float, default=70)
    parser.add_argument("--ma-len", type=int, default=200)
    parser.add_argument("--stop-pct", type=float, default=8.0)
    parser.add_argument("--output-csv", default="output/dual_engine_signal_scan.csv")
    args = parser.parse_args()

    finviz = fetch_finviz_candidates(
        filters=PRESET_FILTERS[args.preset],
        limit=args.limit,
        sleep_sec=args.sleep_sec,
    )
    if finviz.empty:
        raise RuntimeError(f"Finviz preset {args.preset!r} 無候選結果")

    symbols = list(finviz["Ticker"].dropna().astype(str).drop_duplicates())
    rows = []
    for symbol in symbols:
        df = fetch_ohlc(symbol, start=args.start)
        if df is None or len(df) < args.ma_len + 5:
            continue
        signal = simulate_signal(
            df,
            breakout_len=args.breakout_len,
            exit_len=args.exit_len,
            fast_len=args.fast_len,
            slow_len=args.slow_len,
            rsi_len=args.rsi_len,
            mr_buy_th=args.mr_buy_th,
            mr_sell_th=args.mr_sell_th,
            ma_len=args.ma_len,
            stop_pct=args.stop_pct,
            recent_days=args.recent_days,
        )
        if signal is None:
            continue
        rows.append({"Ticker": symbol, **signal})

    result = pd.DataFrame(rows)
    output_path = Path(args.output_csv)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    result.to_csv(output_path, index=False)

    triggered = result[result["signal"] != ""].sort_values(
        by=["days_ago", "signal", "close"], ascending=[True, True, False]
    )

    print("Dual-engine 買入訊號掃描 (pine/spy_qqq_dual_engine_strategy.pine)")
    print(f"Preset：{args.preset}；候選：{len(symbols)}；有效數據：{len(result)}")
    print()
    print(f"最近 {args.recent_days} 日內觸發買入訊號：{len(triggered)} 隻")
    print(
        format_bordered_table(
            triggered.loc[
                :, ["Ticker", "signal", "days_ago", "close", "macd", "rsi2", "ma200"]
            ].assign(
                close=lambda d: d["close"].map(lambda v: f"{v:,.2f}"),
                macd=lambda d: d["macd"].map(lambda v: f"{v:+.2f}"),
                rsi2=lambda d: d["rsi2"].map(lambda v: f"{v:.1f}"),
                ma200=lambda d: d["ma200"].map(lambda v: f"{v:,.2f}"),
            )
        )
    )
    print()
    print(f"CSV: {output_path}")


def fetch_finviz_candidates(
    filters: dict[str, str],
    limit: int,
    sleep_sec: float,
) -> pd.DataFrame:
    financial = Financial()
    financial.set_filter(filters_dict=filters)
    frame = financial.screener_view(
        order="Market Cap.",
        limit=limit,
        verbose=0,
        ascend=False,
        sleep_sec=sleep_sec,
    )
    if frame.empty:
        return frame
    return frame.drop_duplicates(subset=["Ticker"]).reset_index(drop=True)


def fetch_ohlc(symbol: str, start: str) -> pd.DataFrame | None:
    try:
        df = yf.download(symbol, start=start, auto_adjust=True, progress=False)
    except Exception:
        return None
    if df is None or df.empty:
        return None
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    df = df[["Open", "High", "Low", "Close"]].dropna()
    return df if not df.empty else None


def simulate_signal(
    df: pd.DataFrame,
    breakout_len: int,
    exit_len: int,
    fast_len: int,
    slow_len: int,
    rsi_len: int,
    mr_buy_th: float,
    mr_sell_th: float,
    ma_len: int,
    stop_pct: float,
    recent_days: int,
) -> dict | None:
    close = df["Close"]
    high = df["High"]
    low = df["Low"]

    macd_line = close.ewm(span=fast_len, adjust=False).mean() - close.ewm(
        span=slow_len, adjust=False
    ).mean()
    highest_high = high.rolling(breakout_len).max().shift(1)
    lowest_low = low.rolling(exit_len).min().shift(1)
    ma = close.rolling(ma_len).mean()
    rsi_val = rsi(close, rsi_len)

    warm = max(ma_len, breakout_len, exit_len, slow_len) + 1
    if len(df) <= warm:
        return None

    bo_cond = (high > highest_high) & (macd_line > 0)
    bo_exit_cond = low < lowest_low
    mr_cond = (rsi_val < mr_buy_th) & (close > ma)
    mr_exit_cond = rsi_val > mr_sell_th

    position = False
    mode = ""
    stop_price = float("nan")
    entries: dict[int, str] = {}  # bar index -> "BO"/"MR"

    for i in range(warm, len(df)):
        if pd.isna(bo_cond.iloc[i]) or pd.isna(mr_cond.iloc[i]):
            continue
        if not position:
            stop_price = float("nan")
            if bo_cond.iloc[i]:
                position, mode = True, "BO"
                stop_price = close.iloc[i] * (1 - stop_pct / 100)
                entries[i] = "BO"
            elif mr_cond.iloc[i]:
                position, mode = True, "MR"
                stop_price = close.iloc[i] * (1 - stop_pct / 100)
                entries[i] = "MR"
        else:
            if mode == "BO" and bo_exit_cond.iloc[i]:
                position, mode = False, ""
            elif mode == "MR" and mr_exit_cond.iloc[i]:
                position, mode = False, ""
            elif low.iloc[i] <= stop_price:
                position, mode = False, ""

    last_index = len(df) - 1
    signal = ""
    days_ago = ""
    if position and entries:
        entry_index = max(entries)
        age = last_index - entry_index
        if age < recent_days:
            signal = entries[entry_index]
            days_ago = age

    return {
        "signal": signal,
        "days_ago": days_ago,
        "in_position": mode if position else "",
        "close": float(close.iloc[-1]),
        "macd": float(macd_line.iloc[-1]),
        "rsi2": float(rsi_val.iloc[-1]),
        "ma200": float(ma.iloc[-1]),
    }


def rsi(close: pd.Series, length: int) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / length, adjust=False, min_periods=length).mean()
    avg_loss = loss.ewm(alpha=1 / length, adjust=False, min_periods=length).mean()
    rs = avg_gain / avg_loss.replace(0, float("nan"))
    return 100 - (100 / (1 + rs))


def format_bordered_table(table: pd.DataFrame) -> str:
    string_table = table.map(_format_table_cell)
    headers = [str(column) for column in string_table.columns]
    rows = string_table.values.tolist()
    widths = [
        max(_display_width(value) for value in [header, *[row[index] for row in rows]])
        for index, header in enumerate(headers)
    ]
    border = "+" + "+".join("-" * (width + 2) for width in widths) + "+"
    header_row = _format_bordered_row(headers, widths)
    body_rows = [_format_bordered_row(row, widths) for row in rows]
    return "\n".join([border, header_row, border, *body_rows, border])


def _format_bordered_row(values: list[str], widths: list[int]) -> str:
    cells = [f" {_pad_table_cell(value, width)} " for value, width in zip(values, widths)]
    return "|" + "|".join(cells) + "|"


def _format_table_cell(value: object) -> str:
    if pd.isna(value):
        return ""
    return str(value)


def _pad_table_cell(value: str, width: int) -> str:
    return value + " " * (width - _display_width(value))


def _display_width(value: str) -> int:
    width = 0
    for char in value:
        width += 2 if unicodedata.east_asian_width(char) in {"F", "W"} else 1
    return width


if __name__ == "__main__":
    main()
