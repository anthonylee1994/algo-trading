from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pandas as pd
from finvizfinance.screener.custom import Custom


BASE_FILTERS = {
    "Market Cap.": "+Mid (over $2bln)",
    "EPS growthpast 5 years": "Over 20%",
    "Return on Equity": "Over +15%",
}


SUMMARY_COLUMNS = [
    "Ticker",
    "Company",
    "Sector",
    "Market Cap",
    "P/E",
    "PEG",
    "P/S",
    "ROE",
    "EPS growthpast 5 years",
]

CUSTOM_COLUMNS = [1, 2, 3, 6, 7, 9, 10, 19, 33]


@dataclass(frozen=True)
class ScreenerPreset:
    name: str
    filters: dict[str, str]


SCREENER_PRESETS = [
    ScreenerPreset(
        name="mid_cap_eps_roe",
        filters=BASE_FILTERS,
    ),
]


def fetch_preset(preset: ScreenerPreset) -> pd.DataFrame:
    custom = Custom()
    custom.set_filter(filters_dict=preset.filters)
    data = custom.screener_view(
        order="Market Cap.",
        ascend=False,
        columns=CUSTOM_COLUMNS,
    )

    if data is None or data.empty:
        return pd.DataFrame(columns=["Ticker"])

    data = data.rename(
        columns={
            "Market Cap.": "Market Cap",
            "Return on Equity": "ROE",
            "EPS Past 5Y": "EPS growthpast 5 years",
            "EPS growth past 5 years": "EPS growthpast 5 years",
        }
    )
    return data


def fetch_candidates() -> pd.DataFrame:
    frames = [fetch_preset(preset) for preset in SCREENER_PRESETS]
    candidates = pd.concat(frames, ignore_index=True)

    if candidates.empty:
        return candidates

    return candidates.drop_duplicates(subset=["Ticker"]).sort_values(
        "Market Cap", ascending=False
    )


def summarize_candidates(candidates: pd.DataFrame) -> list[dict[str, Any]]:
    if candidates.empty:
        return []

    columns = [column for column in SUMMARY_COLUMNS if column in candidates.columns]
    return candidates[columns].to_dict(orient="records")
