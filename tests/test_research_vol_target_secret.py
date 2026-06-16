import pandas as pd

from scripts.research_vol_target_secret import build_top5_momentum_returns


def test_build_top5_momentum_returns_handles_trailing_nan_prices(monkeypatch) -> None:
    dates = pd.date_range("2024-01-01", periods=150, freq="B")
    close_prices = pd.DataFrame(
        {
            "AAPL": [100.0 + i for i in range(149)] + [float("nan")],
            "MSFT": [100.0] * 150,
            "QQQ": [100.0 + i * 0.5 for i in range(150)],
        },
        index=dates,
    )
    universe = {2023: ["AAPL", "MSFT"]}

    monkeypatch.setattr(
        "scripts.research_vol_target_secret.load_market_cap_universe",
        lambda _: ("annual", universe),
    )

    returns = build_top5_momentum_returns(
        close_prices=close_prices.ffill().dropna(how="all"),
        benchmark="QQQ",
        cost_bps=0.0,
    )

    assert not returns.empty
    assert returns.notna().all()
