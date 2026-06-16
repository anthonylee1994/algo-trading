from datetime import date

from scripts.simulate_momentum_rotation import (
    apply_exposure_rebalance_band,
    build_exposure_adjustment_plan,
    current_gross_exposure,
    decide_vol_target_exposure,
    load_strategy_state,
    save_rebalance_state,
    should_rebalance_today,
)


def test_current_gross_exposure_counts_strategy_symbols_only() -> None:
    exposure = current_gross_exposure(
        positions={
            "US.NVDA": {"quantity": 10, "nominal_price": 100},
            "US.QQQ": {"quantity": 5, "nominal_price": 200},
            "US.SPY": {"quantity": 50, "nominal_price": 100},
        },
        prices={"US.NVDA": 110, "US.QQQ": 210, "US.SPY": 100},
        account={"total_assets": 10_000},
        symbols=["NVDA", "QQQ"],
    )

    assert exposure == (10 * 110 + 5 * 210) / 10_000


def test_current_gross_exposure_returns_zero_without_assets() -> None:
    assert (
        current_gross_exposure(
            positions={"US.NVDA": {"quantity": 10, "nominal_price": 100}},
            prices={"US.NVDA": 100},
            account={"total_assets": 0},
            symbols=["NVDA"],
        )
        == 0.0
    )


def test_apply_exposure_rebalance_band_keeps_current_exposure_inside_band() -> None:
    exposure = apply_exposure_rebalance_band(
        target_exposure=1.37,
        current_exposure=1.34,
        rebal_band=0.05,
    )

    assert exposure == 1.34


def test_apply_exposure_rebalance_band_uses_target_outside_band() -> None:
    exposure = apply_exposure_rebalance_band(
        target_exposure=1.50,
        current_exposure=1.34,
        rebal_band=0.05,
    )

    assert exposure == 1.50


def test_apply_exposure_rebalance_band_uses_target_when_no_current_exposure() -> None:
    exposure = apply_exposure_rebalance_band(
        target_exposure=1.50,
        current_exposure=0.0,
        rebal_band=0.05,
    )

    assert exposure == 1.50


def test_decide_vol_target_exposure_reports_hold_inside_band() -> None:
    exposure, state = decide_vol_target_exposure(
        raw_target_exposure=1.38,
        capped_target_exposure=1.38,
        current_exposure=1.34,
        rebal_band=0.05,
    )

    assert exposure == 1.34
    assert state == {
        "raw_target_exposure": 1.38,
        "capped_target_exposure": 1.38,
        "current_exposure": 1.34,
        "effective_exposure": 1.34,
        "action": "hold",
    }


def test_decide_vol_target_exposure_reports_rebalance_outside_band() -> None:
    exposure, state = decide_vol_target_exposure(
        raw_target_exposure=2.40,
        capped_target_exposure=2.00,
        current_exposure=1.34,
        rebal_band=0.05,
    )

    assert exposure == 2.00
    assert state == {
        "raw_target_exposure": 2.40,
        "capped_target_exposure": 2.00,
        "current_exposure": 1.34,
        "effective_exposure": 2.00,
        "action": "rebalance",
    }


def test_should_rebalance_today_respects_monthly_cadence() -> None:
    state = {"last_monthly_rebalance_period": "2026-06"}

    assert not should_rebalance_today(
        "monthly",
        state=state,
        today=date(2026, 6, 16),
    )
    assert should_rebalance_today(
        "monthly",
        state=state,
        today=date(2026, 7, 1),
    )


def test_should_rebalance_today_is_due_without_state() -> None:
    assert should_rebalance_today(
        "monthly",
        state={},
        today=date(2026, 6, 16),
    )


def test_should_rebalance_today_respects_weekly_cadence() -> None:
    state = {"last_weekly_rebalance_period": "2026-W25"}

    assert not should_rebalance_today(
        "weekly",
        state=state,
        today=date(2026, 6, 16),
    )
    assert should_rebalance_today(
        "weekly",
        state=state,
        today=date(2026, 6, 22),
    )


def test_save_rebalance_state_records_monthly_period(tmp_path) -> None:
    path = tmp_path / "strategy_state.json"

    save_rebalance_state(path=path, rebalance="monthly", today=date(2026, 6, 16))

    assert load_strategy_state(path) == {"last_monthly_rebalance_period": "2026-06"}


def test_save_rebalance_state_preserves_other_periods(tmp_path) -> None:
    path = tmp_path / "strategy_state.json"
    path.write_text('{"last_monthly_rebalance_period": "2026-06"}\n')

    save_rebalance_state(path=path, rebalance="weekly", today=date(2026, 6, 22))

    assert load_strategy_state(path) == {
        "last_monthly_rebalance_period": "2026-06",
        "last_weekly_rebalance_period": "2026-W26",
    }


def test_build_exposure_adjustment_plan_scales_existing_basket_only() -> None:
    plan = build_exposure_adjustment_plan(
        positions={
            "US.NVDA": {"quantity": 10, "nominal_price": 100},
            "US.QQQ": {"quantity": 5, "nominal_price": 200},
            "US.SPY": {"quantity": 10, "nominal_price": 100},
        },
        prices={"US.NVDA": 100, "US.QQQ": 200, "US.SPY": 100},
        account={"total_assets": 2_000},
        symbols=["NVDA", "QQQ"],
        target_exposure=1.5,
        min_trade_notional=100,
    )

    assert [item.action for item in plan] == ["BUY", "BUY"]
    assert {item.code for item in plan} == {"US.NVDA", "US.QQQ"}


def test_build_exposure_adjustment_plan_sells_down_when_target_lower() -> None:
    plan = build_exposure_adjustment_plan(
        positions={
            "US.NVDA": {"quantity": 10, "nominal_price": 100},
            "US.QQQ": {"quantity": 5, "nominal_price": 200},
        },
        prices={"US.NVDA": 100, "US.QQQ": 200},
        account={"total_assets": 2_000},
        symbols=["NVDA", "QQQ"],
        target_exposure=0.5,
        min_trade_notional=100,
    )

    assert [item.action for item in plan] == ["SELL", "SELL"]
    assert {item.code for item in plan} == {"US.NVDA", "US.QQQ"}
