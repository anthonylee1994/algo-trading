from __future__ import annotations

import argparse
from datetime import UTC, datetime
from pathlib import Path
import sys

import pandas as pd
from finvizfinance.screener.financial import Financial

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from algo_trading.momentum_rotation import format_bordered_table
from scripts.backtest_momentum_rotation import fetch_yahoo_chart


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
    parser = argparse.ArgumentParser(
        description=(
            "用 finvizfinance 拉當前候選池，再用 126D momentum 排名。"
            " 呢個係 forward screener；歷史 alpha 證據仍然來自 backtest scripts。"
        )
    )
    parser.add_argument(
        "--preset",
        choices=sorted(PRESET_FILTERS),
        default=DEFAULT_PRESET,
    )
    parser.add_argument("--limit", type=int, default=80)
    parser.add_argument("--lookback-days", type=int, default=126)
    parser.add_argument("--top-n", type=int, default=5)
    parser.add_argument("--aggressive-top-n", type=int, default=10)
    parser.add_argument("--index-floor", default="QQQ")
    parser.add_argument("--benchmark", default="QQQ")
    parser.add_argument("--start", default="2023-01-01")
    parser.add_argument("--sleep-sec", type=float, default=0.2)
    parser.add_argument("--output-csv", default="output/finviz_momentum_candidates.csv")
    args = parser.parse_args()

    finviz = fetch_finviz_candidates(
        filters=PRESET_FILTERS[args.preset],
        limit=args.limit,
        sleep_sec=args.sleep_sec,
    )
    if finviz.empty:
        raise RuntimeError(f"Finviz preset {args.preset!r} 無候選結果")

    symbols = list(finviz["Ticker"].dropna().astype(str).drop_duplicates())
    prices = fetch_prices(
        symbols=list(dict.fromkeys([*symbols, args.index_floor, args.benchmark])),
        start=args.start,
    )
    ranked = rank_candidates(
        finviz=finviz,
        prices=prices,
        lookback_days=args.lookback_days,
    )

    output_path = Path(args.output_csv)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    ranked.to_csv(output_path, index=False)

    selected = ranked[ranked["momentum"] > 0].head(max(args.top_n, 1))
    aggressive = ranked[ranked["momentum"] > 0].head(max(args.aggressive_top_n, 1))
    weights = target_weights(
        selected_symbols=list(selected["Ticker"]),
        top_n=args.top_n,
        index_floor=args.index_floor,
    )

    print("Finviz momentum candidates")
    print(f"日期：{datetime.now(tz=UTC).date().isoformat()}")
    print(f"Preset：{args.preset}；候選：{len(ranked)}；lookback：{args.lookback_days}D")
    print()
    print("Finviz URL equivalent:")
    print(
        "https://finviz.com/screener.ashx?"
        "v=161&f=cap_midover,fa_eps5years_o20,fa_roe_o15&ft=4&o=-marketcap"
    )
    print()
    print("Finviz filters:")
    for key, value in PRESET_FILTERS[args.preset].items():
        print(f"- {key}: {value}")
    print()
    print(f"Top {args.top_n} current basket:")
    print(format_bordered_table(format_candidate_rows(selected)))
    print()
    print(f"Top {args.aggressive_top_n} aggressive basket:")
    print(format_bordered_table(format_candidate_rows(aggressive)))
    print()
    print("Base target weights before vol-target:")
    print(format_bordered_table(format_weight_rows(weights)))
    print()
    print("Backtested strategy params:")
    print(
        "- 實盤主攻：--top-n 5 --index-floor QQQ "
        "--vol-target 0.30 --vol-window 40 --max-leverage 2"
    )
    print(
        "- 高風險候選：--top-n 10 --index-floor QQQ "
        "--vol-target 0.34 --vol-window 40 --max-leverage 2.5"
    )
    print()
    print(f"CSV: {output_path}")
    print()
    print(
        "注意：Finviz 係 current snapshot，唔可以當歷史基本面 backtest。"
        " 大幅跑贏 QQQ 嘅證據來自 lagged market-cap universe + momentum + "
        "vol-target 回測；呢個 script 只係產生今日候選同部署清單。"
    )


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


def fetch_prices(symbols: list[str], start: str) -> pd.DataFrame:
    series = {}
    for symbol in symbols:
        try:
            chart = fetch_yahoo_chart(symbol, start=start, end=None)
        except Exception:
            continue
        if not chart.empty and "adj_close" in chart:
            series[symbol] = chart["adj_close"].rename(symbol)
    if not series:
        raise RuntimeError("攞唔到任何 Yahoo 價格")
    close = pd.concat(series.values(), axis=1, join="outer").sort_index().ffill()
    close.index = pd.to_datetime(close.index)
    return close


def rank_candidates(
    finviz: pd.DataFrame,
    prices: pd.DataFrame,
    lookback_days: int,
) -> pd.DataFrame:
    rows = []
    momentum = prices.pct_change(lookback_days).iloc[-1]
    latest = prices.iloc[-1]
    for row in finviz.to_dict("records"):
        symbol = str(row["Ticker"])
        if symbol not in prices.columns:
            continue
        rows.append(
            {
                **row,
                "latest_price": float(latest.get(symbol, float("nan"))),
                "momentum": float(momentum.get(symbol, float("nan"))),
            }
        )
    ranked = pd.DataFrame(rows)
    if ranked.empty:
        return ranked
    return ranked.sort_values(
        by=["momentum", market_cap_column(ranked), "Ticker"],
        ascending=[False, False, True],
        na_position="last",
    ).reset_index(drop=True)


def target_weights(
    selected_symbols: list[str],
    top_n: int,
    index_floor: str,
) -> dict[str, float]:
    slot = 1.0 / max(top_n, 1)
    weights = {symbol: slot for symbol in selected_symbols[:top_n]}
    empty = max(top_n - len(weights), 0)
    if empty:
        weights[index_floor] = weights.get(index_floor, 0.0) + empty * slot
    return weights


def format_candidate_rows(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        return pd.DataFrame(
            columns=[
                "Ticker",
                "Market Cap",
                "ROE",
                "ROA",
                "Oper M",
                "Price",
                "Momentum",
            ]
        )
    table = frame.copy()
    table["Market Cap"] = table[market_cap_column(table)].map(format_market_cap)
    for column in ["ROE", "ROA", "Oper M"]:
        if column not in table.columns:
            table[column] = float("nan")
        table[column] = table[column].map(format_percent_value)
    table["Price"] = table["latest_price"].map(
        lambda value: "" if pd.isna(value) else f"{value:,.2f}"
    )
    table["Momentum"] = table["momentum"].map(
        lambda value: "" if pd.isna(value) else f"{value * 100:+.1f}%"
    )
    return table.loc[
        :,
        ["Ticker", "Market Cap", "ROE", "ROA", "Oper M", "Price", "Momentum"],
    ]


def format_weight_rows(weights: dict[str, float]) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {"Ticker": symbol, "Weight": f"{weight * 100:.1f}%"}
            for symbol, weight in weights.items()
        ]
    )


def format_market_cap(value: object) -> str:
    if pd.isna(value):
        return ""
    number = float(value)
    if number >= 1_000_000_000_000:
        return f"${number / 1_000_000_000_000:.2f}T"
    return f"${number / 1_000_000_000:.1f}B"


def format_percent_value(value: object) -> str:
    if pd.isna(value):
        return ""
    number = float(value)
    if abs(number) <= 2:
        number *= 100
    return f"{number:.1f}%"


def market_cap_column(frame: pd.DataFrame) -> str:
    if "Market Cap" in frame.columns:
        return "Market Cap"
    return "Market Cap."


if __name__ == "__main__":
    main()
