import pandas as pd

from algo_trading.market_cap_universe import (
    latest_universe_symbols,
    load_yearly_market_cap_universe,
    symbols_for_date,
)
from scripts.backtest_momentum_rotation import build_target_weights


def test_symbols_for_date_uses_matching_year_universe() -> None:
    universe_by_year = {
        2020: ["AAPL", "MSFT"],
        2021: ["NVDA", "TSLA"],
    }

    assert symbols_for_date(pd.Timestamp("2020-06-01"), ["IBM"], universe_by_year) == [
        "AAPL",
        "MSFT",
    ]
    assert symbols_for_date(pd.Timestamp("2021-06-01"), ["IBM"], universe_by_year) == [
        "NVDA",
        "TSLA",
    ]


def test_load_yearly_market_cap_universe_and_latest_symbols(tmp_path) -> None:
    path = tmp_path / "universe.json"
    path.write_text(
        """
{
  "data": {
    "2025": [
      { "rank": 1, "symbol": "AAPL" },
      { "rank": 2, "symbol": "MSFT" }
    ],
    "2026": [
      { "rank": 1, "symbol": "NVDA" },
      { "rank": 2, "symbol": "GOOGL" }
    ]
  }
}
""".strip()
    )

    universe_by_year = load_yearly_market_cap_universe(path)

    assert universe_by_year == {
        2025: ["AAPL", "MSFT"],
        2026: ["NVDA", "GOOGL"],
    }
    assert latest_universe_symbols(["IBM"], universe_by_year) == ["NVDA", "GOOGL"]


def test_build_target_weights_limits_candidates_to_yearly_universe() -> None:
    close_prices = pd.DataFrame(
        {
            "AAPL": [100.0, 110.0, 120.0, 130.0],
            "MSFT": [100.0, 105.0, 110.0, 115.0],
            "NVDA": [100.0, 300.0, 390.0, 500.0],
            "TSLA": [100.0, 200.0, 210.0, 220.0],
        },
        index=pd.to_datetime(
            ["2020-12-30", "2020-12-31", "2021-01-01", "2021-01-04"]
        ),
    )

    weights = build_target_weights(
        close_prices=close_prices,
        symbols=["AAPL", "MSFT", "NVDA", "TSLA"],
        universe_by_year={
            2020: ["AAPL", "MSFT"],
            2021: ["NVDA", "TSLA"],
        },
        lookback_days=1,
        top_n=1,
    )

    assert weights.loc["2021-01-01", "AAPL"] == 1.0
    assert weights.loc["2021-01-01", "NVDA"] == 0.0
    assert weights.loc["2021-01-04", "NVDA"] == 1.0
    assert weights.loc["2021-01-04", "AAPL"] == 0.0
