import pandas as pd

from algo_trading.futu_trader import StrategyInputs, _build_buy_plan


def _history() -> pd.DataFrame:
    return pd.DataFrame({"close": list(range(100, 360))})


def test_build_buy_plan_skips_existing_position_at_target_weight() -> None:
    candidates = pd.DataFrame(
        [
            {
                "Ticker": "NVDA",
                "Company": "NVIDIA Corp",
            }
        ]
    )
    history = _history()
    inputs = StrategyInputs(
        candidate_codes=["US.NVDA"],
        positions={
            "US.NVDA": {
                "quantity": 1000,
                "cost_price": 100,
                "nominal_price": 100,
            }
        },
        histories={
            "US.NVDA": history,
            "US.SPY": history,
        },
        prices={"US.NVDA": 359},
        spy_history=history,
        available_cash=100_000,
        target_position_value=359_000,
        rebalance_value=3_000,
    )

    assert _build_buy_plan(candidates, inputs) == []


def test_build_buy_plan_rebalances_existing_underweight_position() -> None:
    candidates = pd.DataFrame(
        [
            {
                "Ticker": "NVDA",
                "Company": "NVIDIA Corp",
            }
        ]
    )
    history = _history()
    inputs = StrategyInputs(
        candidate_codes=["US.NVDA"],
        positions={
            "US.NVDA": {
                "quantity": 500,
                "cost_price": 100,
                "nominal_price": 100,
            }
        },
        histories={
            "US.NVDA": history,
            "US.SPY": history,
        },
        prices={"US.NVDA": 359},
        spy_history=history,
        available_cash=100_000,
        target_position_value=359_000,
        rebalance_value=3_000,
    )

    plan = _build_buy_plan(candidates, inputs)

    assert len(plan) == 1
    assert plan[0].code == "US.NVDA"
    assert plan[0].reason == "rebalance underweight"
