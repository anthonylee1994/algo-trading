"""由 Wikipedia 重建 point-in-time S&P 500 membership（含已被踢走 / 退市嘅 ticker）。

呢個係 survivorship 驗證嘅關鍵一步。`sp500_constituents.csv` 只係今日 503 隻成員，
缺咗歷史上加入又被踢走嘅股票（多數係表現差或被收購）。淨用今日名單做 universe
= survivorship bias，闊池集中策略嘅 raw CAGR 會偏高。

做法：
1. 食 Wikipedia 兩個表（已 curl 落 /tmp 或傳 --wiki-html）：
   - 表 0：今日 503 隻成員 + "Date added"。
   - 表 1：歷年變動（Effective Date, Added Ticker, Removed Ticker, Reason）。
2. 由今日名單**向後行** change log，砌返每隻 ticker 嘅 membership interval。
   - 一條變動喺 D 生效：D 之後個 set 包含 Added、剔走 Removed；
     即 D 之前個 set 唔包 Added、包返 Removed。
   - 一隻 ticker 可以加入又踢走又再加入（多段 interval）。
3. 輸出 membership CSV（symbol,start,end）；end 留空 = 至今仍係成員。

之後配 yfinance 落埋退市股價格（fetch_pit_prices.py），用
pit_backtest_momentum_rotation.py 跑乾淨闊池回測。
"""

from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

WINDOW_START = pd.Timestamp("2008-01-01")  # 1990 太早；2008 已足夠 cover 2010 起 + lookback


def parse_changes(table: pd.DataFrame) -> pd.DataFrame:
    """攤平 Wikipedia 變動表（MultiIndex header）→ date / added / removed。"""
    flat = table.copy()
    flat.columns = ["_".join(c).strip() if isinstance(c, tuple) else c for c in flat.columns]
    date_col = next(c for c in flat.columns if "Effective Date" in c)
    added_col = next(c for c in flat.columns if c.startswith("Added") and "Ticker" in c)
    removed_col = next(c for c in flat.columns if c.startswith("Removed") and "Ticker" in c)
    out = pd.DataFrame(
        {
            "date": pd.to_datetime(flat[date_col], errors="coerce"),
            "added": flat[added_col].astype(str).str.strip(),
            "removed": flat[removed_col].astype(str).str.strip(),
        }
    )
    out = out.dropna(subset=["date"])
    out.loc[out["added"].isin(["nan", "", "—"]), "added"] = None
    out.loc[out["removed"].isin(["nan", "", "—"]), "removed"] = None
    return out.sort_values("date").reset_index(drop=True)


def build_intervals(current: pd.DataFrame, changes: pd.DataFrame, today: pd.Timestamp):
    """向後行 change log 砌 membership interval。回傳 list[dict(symbol,start,end)]。

    cursor 由 today 向後行。`member_end[sym]` = 該 symbol 喺 cursor 時點所屬嗰段
    membership stint 嘅完結日（今日成員 = None）。行到一條變動（D, added=A, removed=R）：
      - A 喺 D 之後先係成員、之前唔係 → A 呢段 stint 喺 D 開始：閉合 (start=D, end=member_end[A])。
      - R 喺 D 之後唔係成員、之前係 → R 喺 D 完結咗一段：開一段新 stint (end=D)。
    """
    member_end: dict[str, pd.Timestamp | None] = {sym: None for sym in current["symbol"]}
    intervals: list[dict] = []

    for _, row in changes.iloc[::-1].iterrows():
        d = row["date"]
        added, removed = row["added"], row["removed"]
        if added and added in member_end:
            intervals.append({"symbol": added, "start": d, "end": member_end.pop(added)})
        if removed:
            if removed in member_end:
                # 罕有：cursor 時 R 仲開住又喺 D 被 remove（重新加入過）；先閉合現有 stint。
                intervals.append({"symbol": removed, "start": d, "end": member_end[removed]})
            member_end[removed] = d

    # 剩低仲開住嘅（行完晒 change log 都係成員）→ start = 進入窗口前已係成員。
    date_added = dict(zip(current["symbol"], current["date_added"]))
    for sym, end in member_end.items():
        da = date_added.get(sym)
        start = da if (da is not None and not pd.isna(da) and da >= WINDOW_START) else WINDOW_START
        intervals.append({"symbol": sym, "start": start, "end": end})

    # clip 落窗口，去掉完全喺窗口外嘅。
    rows = []
    for it in intervals:
        start = max(it["start"], WINDOW_START)
        end = it["end"]  # None = 至今
        if end is not None and end < WINDOW_START:
            continue
        rows.append({"symbol": it["symbol"], "start": start, "end": end})
    return rows


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--wiki-html", default="/tmp/sp500_wiki.html")
    p.add_argument("--today", default="2026-06-16")
    p.add_argument("--out", default="output/sp500_pit_membership.csv")
    args = p.parse_args()

    today = pd.Timestamp(args.today)
    tables = pd.read_html(args.wiki_html)
    cur_raw = tables[0]
    current = pd.DataFrame(
        {
            "symbol": cur_raw["Symbol"].astype(str).str.strip(),
            "date_added": pd.to_datetime(cur_raw["Date added"], errors="coerce"),
        }
    )
    changes = parse_changes(tables[1])
    changes = changes[(changes["date"] >= WINDOW_START) & (changes["date"] <= today)]

    intervals = build_intervals(current, changes, today)
    out = pd.DataFrame(intervals)
    out = out[out["symbol"].apply(lambda s: isinstance(s, str) and s.strip() not in ("", "nan", "None"))]
    out["start"] = pd.to_datetime(out["start"]).dt.date
    out["end"] = pd.to_datetime(out["end"]).dt.date  # NaT → 空
    out = out.sort_values(["symbol", "start"]).reset_index(drop=True)

    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(args.out, index=False)

    n_sym = out["symbol"].nunique()
    n_ended = out["end"].notna().sum()
    n_open = out["end"].isna().sum()
    print(f"寫咗 {len(out)} 段 interval、{n_sym} 隻獨立 symbol → {args.out}")
    print(f"  仍係成員（end 空）：{n_open} 段")
    print(f"  已被踢走 / 退市（end 有值）：{n_ended} 段")
    ever = set(out["symbol"])
    today_set = set(current["symbol"])
    print(f"  今日成員：{len(today_set)}；歷史上曾經係成員（窗口內）總數：{len(ever)}")
    print(f"  →  已被剔走但要含返入測試嘅 extra ticker：{len(ever - today_set)} 隻")


if __name__ == "__main__":
    main()
