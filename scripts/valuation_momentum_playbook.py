"""今日操作表（forward playbook）—— 把三樣經驗證 / 有用嘅嘢合埋：

1. 動量 top-N + QQQ 托底（揀邊隻持有）—— backtest 已驗證嘅核心
2. vol-target（今日該用幾多曝險）—— 低波加注、高波減注
3. 估值帶（每隻而家低估 / 合理 / 高估）—— 部署紀律，來自 valuation.on99.app 個 Google Sheet

呢個係【前向決策輔助】，唔係 backtest。原因：估值帶係人手 set、EPS 係當前、
watchlist 係後見之明揀嘅，歷史 backtest 必然帶 survivorship + lookahead 偏差。
所以呢度只用佢哋嚟輔助【今日】嘅判斷，唔扮可以驗證歷史 alpha。

數據：估值帶 = 公開 Google Sheet（valuation.on99.app）；價 / 動量 = Yahoo。
"""

from __future__ import annotations

import argparse
from datetime import UTC, datetime
import json
from pathlib import Path
import sys
import urllib.parse
import urllib.request

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from algo_trading.momentum_rotation import format_bordered_table

SHEET_ID = "1BnLiD1jwCQgwKFHNEJPpldQWEvnSRUN03eQdJEdJZ60"
SHEET_KEY = "AIzaSyClnKnQcoDQkBYPReeez2szV8rkdmtulOw"
TRADING_DAYS = 252


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tab", default="美股", help="Google Sheet 分頁（美股 / 港股）。")
    parser.add_argument("--benchmark", default="QQQ")
    parser.add_argument("--lookback-days", type=int, default=126)
    parser.add_argument("--top-n", type=int, default=5)
    parser.add_argument("--index-floor", default="QQQ")
    parser.add_argument("--vol-target", type=float, default=0.26)
    parser.add_argument("--vol-window", type=int, default=40)
    parser.add_argument("--max-leverage", type=float, default=2.0)
    args = parser.parse_args()

    bands = load_valuation_bands(args.tab)
    symbols = list(bands.keys())
    fetch = list(dict.fromkeys([*symbols, args.benchmark, args.index_floor]))
    prices = {}
    for symbol in fetch:
        try:
            prices[symbol] = fetch_yahoo_close(symbol)
        except Exception:
            print(f"⚠️ 攞唔到 {symbol} 價，略過")
    close = pd.concat(prices, axis=1).sort_index()
    close.index = pd.to_datetime(close.index)

    # 動量 + 排名
    candidates = [s for s in symbols if s in close.columns]
    momentum = close[candidates].pct_change(args.lookback_days).iloc[-1]
    ranked = momentum.dropna().sort_values(ascending=False)
    positive = ranked[ranked > 0]
    selected = list(positive.head(args.top_n).index)

    # base portfolio 權重（top_n + QQQ 托底）
    weights = {s: 1.0 / args.top_n for s in selected}
    empty = max(args.top_n - len(selected), 0)
    if empty > 0 and args.index_floor in close.columns:
        weights[args.index_floor] = weights.get(args.index_floor, 0.0) + empty / args.top_n

    # vol-target 曝險
    realized_vol, exposure = vol_target_exposure(
        close, weights, args.vol_window, args.vol_target, args.max_leverage
    )

    # ---- 輸出 ----
    print(f"日期：{close.index[-1].date()}　|　universe：{args.tab}（{len(candidates)} 隻）")
    print(
        f"vol-target {args.vol_target:.0%}：base 實際波幅 {realized_vol:.0%} → "
        f"今日建議曝險 ×{exposure:.2f}（封頂 {args.max_leverage:g}）\n"
    )

    rows = []
    for symbol in candidates:
        price = float(close[symbol].iloc[-1])
        band = bands[symbol]
        status = valuation_status(price, band["low"], band["high"])
        mom = momentum.get(symbol, float("nan"))
        in_hold = "✅" if symbol in selected else ""
        upside = (band["high"] / price - 1) * 100 if price > 0 else float("nan")
        rows.append(
            {
                "代號": symbol,
                "名": band["name"][:6],
                "持有": in_hold,
                "動量": mom,
                "現價": price,
                "合理區間": f"{band['low']:.0f}–{band['high']:.0f}",
                "估值": {"undervalued": "低估", "fair": "合理", "overvalued": "高估"}[status],
                "距上界": upside,
            }
        )
    table = pd.DataFrame(rows).sort_values("動量", ascending=False)
    table["動量"] = table["動量"].map(lambda v: f"{v * 100:+.1f}%" if pd.notna(v) else "—")
    table["現價"] = table["現價"].map(lambda v: f"{v:,.2f}")
    table["距上界"] = table["距上界"].map(lambda v: f"{v:+.0f}%" if pd.notna(v) else "—")
    print(format_bordered_table(table))

    print("\n【今日操作邏輯】")
    print(f"1. 持有（✅）= 動量最強 {args.top_n} 隻；唔夠就用 {args.index_floor} 托底。")
    print(f"2. 整體曝險 ×{exposure:.2f}（vol-target；低波加注、高波減注）。")
    print("3. 估值帶 = 紀律：")
    over_held = [
        s for s in selected
        if valuation_status(float(close[s].iloc[-1]), bands[s]["low"], bands[s]["high"]) == "overvalued"
    ]
    under_all = [
        s for s in candidates
        if valuation_status(float(close[s].iloc[-1]), bands[s]["low"], bands[s]["high"]) == "undervalued"
    ]
    if over_held:
        print(f"   ⚠️ 動量想持有但【高估】：{', '.join(over_held)} —— 追高風險，注碼收斂。")
    if under_all:
        print(f"   💰 而家【低估】（部署現金 watchlist）：{', '.join(under_all)}")
    print(
        "\n⚠️ 提醒：估值帶係人手判斷、EPS 係當前值，呢個係前向輔助唔係歷史 backtest。"
        "\n   核心 alpha 喺『動量 + vol-target』(已驗證)；估值帶幫你唔好追高、跌市有 buy-zone。"
    )


def load_valuation_bands(tab: str) -> dict[str, dict]:
    url = (
        f"https://sheets.googleapis.com/v4/spreadsheets/{SHEET_ID}"
        f"/values/{urllib.parse.quote(tab)}?key={SHEET_KEY}"
    )
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=30) as response:
        values = json.load(response)["values"]
    header = values[0]
    col = {name: i for i, name in enumerate(header)}
    bands: dict[str, dict] = {}
    for row in values[1:]:
        if not row or not row[col["Symbol"]]:
            continue
        try:
            low = float(row[col["Valuation Low"]])
            high = float(row[col["Valuation High"]])
        except (ValueError, IndexError):
            continue
        symbol = row[col["Symbol"]].strip()
        bands[symbol] = {
            "name": row[col["Name"]] if col["Name"] < len(row) else symbol,
            "metric": row[col["Metric Type"]] if col["Metric Type"] < len(row) else "",
            "low": low,
            "high": high,
        }
    return bands


def valuation_status(price: float, low: float, high: float) -> str:
    if price < low:
        return "undervalued"
    if price > high:
        return "overvalued"
    return "fair"


def vol_target_exposure(
    close: pd.DataFrame,
    weights: dict[str, float],
    window: int,
    target_vol: float,
    max_leverage: float,
) -> tuple[float, float]:
    cols = [s for s in weights if s in close.columns]
    if not cols:
        return float("nan"), 1.0
    returns = close[cols].pct_change().dropna().tail(window)
    weight_series = pd.Series({s: weights[s] for s in cols}, dtype=float)
    weight_series = weight_series / weight_series.sum()
    portfolio = (returns * weight_series).sum(axis=1)
    realized_vol = float(portfolio.std() * np.sqrt(TRADING_DAYS))
    if realized_vol <= 0:
        return realized_vol, 1.0
    exposure = min(target_vol / realized_vol, max_leverage)
    return realized_vol, exposure


def fetch_yahoo_close(symbol: str, start: str = "2023-01-01") -> pd.Series:
    period1 = int(datetime.fromisoformat(start).replace(tzinfo=UTC).timestamp())
    period2 = int(datetime.now(tz=UTC).timestamp())
    query = urllib.parse.urlencode(
        {"period1": period1, "period2": period2, "interval": "1d", "includeAdjustedClose": "true"}
    )
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol.replace('.', '-')}?{query}"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=30) as response:
        result = json.load(response)["chart"]["result"][0]
    timestamps = result["timestamp"]
    adj = result["indicators"].get("adjclose", [{}])[0].get(
        "adjclose", result["indicators"]["quote"][0]["close"]
    )
    dates = [datetime.fromtimestamp(t, tz=UTC).date() for t in timestamps]
    return pd.Series(adj, index=pd.to_datetime(dates), name=symbol).dropna()


if __name__ == "__main__":
    main()
