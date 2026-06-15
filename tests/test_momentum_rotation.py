import pandas as pd

from algo_trading.momentum_rotation import (
    RotationSignal,
    backtest_rotation,
    build_equal_weight_rotation_plan,
    build_rotation_plan,
    calculate_momentum,
    momentum_score_table,
    select_rotation_targets,
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
    assert signal.reason == "最高 momentum <= 0，持現金"


def test_momentum_score_table_sorts_scores_descending() -> None:
    histories = {
        "MSFT": pd.DataFrame({"close": [100] * 126 + [110]}),
        "NVDA": pd.DataFrame({"close": [100] * 126 + [150]}),
        "NEW": pd.DataFrame({"close": [100]}),
    }

    table = momentum_score_table(histories, lookback_days=126)

    assert table.iloc[0]["ticker"] == "NVDA"
    assert table.iloc[1]["ticker"] == "MSFT"
    assert table.iloc[2]["ticker"] == "NEW"
    assert pd.isna(table.iloc[2]["momentum"])


def test_select_rotation_targets_returns_top_positive_momentum() -> None:
    histories = {
        "MSFT": pd.DataFrame({"close": [100] * 126 + [110]}),
        "NVDA": pd.DataFrame({"close": [100] * 126 + [150]}),
        "TSM": pd.DataFrame({"close": [100] * 126 + [130]}),
        "CRM": pd.DataFrame({"close": [100] * 126 + [90]}),
    }

    targets = select_rotation_targets(histories, lookback_days=126, top_n=2)

    assert [target.ticker for target in targets] == ["NVDA", "TSM"]


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


def test_build_equal_weight_rotation_plan_targets_top_two() -> None:
    plan = build_equal_weight_rotation_plan(
        targets=[
            RotationSignal(ticker="NVDA", momentum=0.5, reason="Top 2"),
            RotationSignal(ticker="TSM", momentum=0.3, reason="Top 2"),
        ],
        prices={"US.NVDA": 100, "US.TSM": 50, "US.MSFT": 25},
        positions={"US.MSFT": {"quantity": 20, "nominal_price": 25}},
        available_cash=500,
        symbols=["MSFT", "NVDA", "TSM"],
    )

    assert [item.action for item in plan] == ["SELL", "BUY", "BUY"]
    assert plan[0].code == "US.MSFT"
    assert {item.code for item in plan[1:]} == {"US.NVDA", "US.TSM"}


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


def test_backtest_rotation_uses_previous_day_signal() -> None:
    dates = pd.date_range("2024-01-01", periods=130)
    close_prices = pd.DataFrame(
        {
            "QQQ": [100.0] * 129 + [200.0],
            "NVDA": [100.0] * 129 + [200.0],
        },
        index=dates,
    )

    result, curve = backtest_rotation(
        close_prices=close_prices,
        benchmark_symbol="QQQ",
        lookback_days=126,
    )

    assert result.final_equity == 100_000
    assert curve.iloc[-1]["selected"] == "CASH"
