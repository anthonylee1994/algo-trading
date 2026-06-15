from __future__ import annotations

import json
from pathlib import Path

import pandas as pd


DEFAULT_MARKET_CAP_UNIVERSE_PATH = Path(
    "sp500_top_10_market_cap_2010_2026.json"
)


def load_yearly_market_cap_universe(path: Path) -> dict[int, list[str]]:
    payload = json.loads(path.read_text())
    data = payload.get("data", payload)
    universe_by_year: dict[int, list[str]] = {}
    for year, rows in data.items():
        symbols = [str(row["symbol"]) for row in rows]
        if not symbols:
            raise RuntimeError(f"{path} 入面 {year} 無 symbol")
        universe_by_year[int(year)] = list(dict.fromkeys(symbols))
    if not universe_by_year:
        raise RuntimeError(f"{path} 無可用 universe data")
    return dict(sorted(universe_by_year.items()))


def symbols_for_date(
    date: pd.Timestamp,
    default_symbols: list[str],
    universe_by_year: dict[int, list[str]] | None,
    lag_years: int = 1,
) -> list[str]:
    """揀某日嘅成份股。

    `lag_years` 預設 1：喺 Y 年只可以用 Y-1（或更早）年底嘅市值快照——
    因為 Y 年底個快照要到 Y 年完先知道。咁先避免「年頭就知道年尾邊隻最大」
    嘅 membership 前視偏差。`lag_years=0` 會還原舊行為（有前視，淨係用嚟對照）。
    """
    if not universe_by_year:
        return default_symbols
    target_year = int(pd.Timestamp(date).year) - max(lag_years, 0)
    available_years = sorted(universe_by_year)
    usable = [year for year in available_years if year <= target_year]
    if usable:
        return universe_by_year[usable[-1]]
    # 回測最初期未有更早快照可用，退而用最早一份（只影響開頭一小段）。
    return universe_by_year[available_years[0]]


def latest_universe_symbols(
    default_symbols: list[str],
    universe_by_year: dict[int, list[str]] | None,
) -> list[str]:
    if not universe_by_year:
        return default_symbols
    return universe_by_year[max(universe_by_year)]


# ---------------------------------------------------------------------------
# Point-in-time schedule（支援季度 / 任意日期嘅市值快照）
#
# 年度數據（year-end 快照）始終要滯後成年先用得，granularity 太粗。
# 如果你有季度 point-in-time 市值（Norgate / Sharadar / Compustat），用日期做
# key（"2014-03-31" 之類），engine 就會喺每個快照「生效日 + publication lag」之後
# 至開始用，無前視，亦可以季度更新 universe。
# ---------------------------------------------------------------------------

Snapshot = tuple[pd.Timestamp, list[str]]


def _looks_like_year(key: str) -> bool:
    text = str(key).strip()
    return len(text) == 4 and text.isdigit()


def load_dated_market_cap_universe(path: Path) -> list[Snapshot]:
    """讀日期 key 嘅快照 JSON，回傳按生效日排序嘅 (effective_date, symbols) list。"""
    payload = json.loads(path.read_text())
    data = payload.get("data", payload)
    schedule: list[Snapshot] = []
    for key, rows in data.items():
        symbols = list(dict.fromkeys(str(row["symbol"]) for row in rows))
        if not symbols:
            raise RuntimeError(f"{path} 入面 {key} 無 symbol")
        schedule.append((pd.Timestamp(key), symbols))
    if not schedule:
        raise RuntimeError(f"{path} 無可用 universe data")
    schedule.sort(key=lambda item: item[0])
    return schedule


def load_market_cap_universe(
    path: Path,
) -> tuple[str, dict[int, list[str]] | list[Snapshot]]:
    """自動辨認格式：年度（int key）→ ("annual", dict)；日期 key → ("dated", schedule)。"""
    payload = json.loads(path.read_text())
    data = payload.get("data", payload)
    keys = list(data.keys())
    if keys and all(_looks_like_year(key) for key in keys):
        return "annual", load_yearly_market_cap_universe(path)
    return "dated", load_dated_market_cap_universe(path)


def symbols_for_schedule(
    date: pd.Timestamp,
    default_symbols: list[str],
    schedule: list[Snapshot] | None,
    publication_lag_days: int = 0,
) -> list[str]:
    """揀某日可用嘅快照：生效日 + publication lag <= 當日，取最近一份。"""
    if not schedule:
        return default_symbols
    when = pd.Timestamp(date)
    lag = pd.Timedelta(days=max(publication_lag_days, 0))
    usable = [symbols for effective, symbols in schedule if effective + lag <= when]
    if usable:
        return usable[-1]
    return schedule[0][1]


def latest_schedule_symbols(
    default_symbols: list[str],
    schedule: list[Snapshot] | None,
) -> list[str]:
    if not schedule:
        return default_symbols
    return schedule[-1][1]
