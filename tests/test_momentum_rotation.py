import pandas as pd

from algo_trading.momentum_rotation import (
    RotationSignal,
    build_rotation_plan,
    calculate_momentum,
    select_rotation_signal,
)


def test_calculate_momentum_uses_lookback_close() -> None:
    history = pd.DataFrame({"close": list(range(100, 228))})

    assert calculate_momentum(history, lookback_days=126) == 227 / 101 - 1


def test_select_rotation_signal_returns_cash_when_best_momentum_is_negative() -> None:
    histories = {
        "MSFT": pd.DataFrame({"close": [100] * 126 + [90]}),
        "NVDA": pd.DataFrame({"close": [100] * 126 + [95]}),
    }

    signal = select_rotation_signal(histories, lookback_days=126)

    assert signal.ticker is None
    assert signal.reason == "best momentum <= 0, hold cash"


def test_build_rotation_plan_sells_non_target_and_buys_target() -> None:
    plan = build_rotation_plan(
        signal=RotationSignal(ticker="NVDA", momentum=0.5, reason="best 126D momentum"),
        prices={"US.NVDA": 100, "US.MSFT": 50},
        positions={"US.MSFT": {"quantity": 10, "nominal_price": 50}},
        available_cash=1_000,
        symbols=["MSFT", "NVDA"],
    )

    assert [item.action for item in plan] == ["SELL", "BUY"]
    assert plan[0].code == "US.MSFT"
    assert plan[1].code == "US.NVDA"


def test_build_rotation_plan_cash_signal_sells_universe_positions_only() -> None:
    plan = build_rotation_plan(
        signal=RotationSignal(ticker=None, momentum=-0.1, reason="hold cash"),
        prices={"US.MSFT": 50, "US.SPY": 100},
        positions={
            "US.MSFT": {"quantity": 10, "nominal_price": 50},
            "US.SPY": {"quantity": 10, "nominal_price": 100},
        },
        available_cash=1_000,
        symbols=["MSFT", "NVDA"],
    )

    assert len(plan) == 1
    assert plan[0].action == "SELL"
    assert plan[0].code == "US.MSFT"
