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
) -> list[str]:
    if not universe_by_year:
        return default_symbols
    year = int(pd.Timestamp(date).year)
    if year in universe_by_year:
        return universe_by_year[year]
    available_years = sorted(universe_by_year)
    prior_years = [
        available_year for available_year in available_years if available_year <= year
    ]
    if prior_years:
        return universe_by_year[prior_years[-1]]
    return universe_by_year[available_years[0]]


def latest_universe_symbols(
    default_symbols: list[str],
    universe_by_year: dict[int, list[str]] | None,
) -> list[str]:
    if not universe_by_year:
        return default_symbols
    return universe_by_year[max(universe_by_year)]
