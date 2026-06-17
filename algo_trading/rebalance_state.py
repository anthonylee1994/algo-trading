"""Shared rebalance cadence helpers.

Strategy-agnostic state read/write for monthly/weekly rebalance gates. Lives
outside simulate_momentum_rotation.py so any strategy script can import it
without pulling in momentum-specific code.
"""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path


def _monthly_period(day: date) -> str:
    return f"{day.year:04d}-{day.month:02d}"


def _weekly_period(day: date) -> str:
    iso = day.isocalendar()
    return f"{iso.year:04d}-W{iso.week:02d}"


def should_rebalance_today(
    rebalance: str,
    state: dict,
    today: date | None = None,
) -> bool:
    """Live execution 只喺對應 rebalance cadence 先換 basket。"""
    if rebalance == "daily":
        return True
    today = today or date.today()
    if rebalance == "weekly":
        return state.get("last_weekly_rebalance_period") != _weekly_period(today)
    return state.get("last_monthly_rebalance_period") != _monthly_period(today)


def load_strategy_state(path: Path) -> dict:
    if not path.exists():
        return {}
    return json.loads(path.read_text())


def save_rebalance_state(
    path: Path,
    rebalance: str,
    today: date | None = None,
) -> None:
    state = load_strategy_state(path)
    today = today or date.today()
    if rebalance == "weekly":
        state["last_weekly_rebalance_period"] = _weekly_period(today)
    elif rebalance == "monthly":
        state["last_monthly_rebalance_period"] = _monthly_period(today)
    else:
        return
    path.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n")
