import pandas as pd

from algo_trading.market_cap_universe import (
    latest_universe_symbols,
    load_dated_market_cap_universe,
    load_market_cap_universe,
    load_yearly_market_cap_universe,
    symbols_for_date,
    symbols_for_schedule,
)
from scripts.backtest_momentum_rotation import (
    apply_exposure_returns,
    apply_rebalance_band,
    build_target_weights,
    build_vol_target_exposure,
)


def test_symbols_for_date_lags_one_year_to_avoid_lookahead() -> None:
    universe_by_year = {
        2020: ["AAPL", "MSFT"],
        2021: ["NVDA", "TSLA"],
    }

    # 預設滯後 1 年：2022 年只可以用 2021 年底快照，2021 年用 2020 年底快照。
    assert symbols_for_date(pd.Timestamp("2022-06-01"), ["IBM"], universe_by_year) == [
        "NVDA",
        "TSLA",
    ]
    assert symbols_for_date(pd.Timestamp("2021-06-01"), ["IBM"], universe_by_year) == [
        "AAPL",
        "MSFT",
    ]
    # 最早期未有更早快照，退而用最早一份。
    assert symbols_for_date(pd.Timestamp("2020-06-01"), ["IBM"], universe_by_year) == [
        "AAPL",
        "MSFT",
    ]


def test_symbols_for_date_lag_zero_restores_same_year() -> None:
    universe_by_year = {2020: ["AAPL", "MSFT"], 2021: ["NVDA", "TSLA"]}
    assert symbols_for_date(
        pd.Timestamp("2021-06-01"), ["IBM"], universe_by_year, lag_years=0
    ) == ["NVDA", "TSLA"]


def test_symbols_for_schedule_respects_effective_and_publication_lag() -> None:
    schedule = [
        (pd.Timestamp("2014-12-31"), ["AAPL", "XOM"]),
        (pd.Timestamp("2015-03-31"), ["AAPL", "GOOGL"]),
    ]
    # 2015-04-01 + 0 lag：用返 2015-03-31 快照。
    assert symbols_for_schedule(pd.Timestamp("2015-04-01"), [], schedule) == [
        "AAPL",
        "GOOGL",
    ]
    # 加 60 日 publication lag，2015-04-01 仲未用得 2015-03-31，要返上一份。
    assert symbols_for_schedule(
        pd.Timestamp("2015-04-01"), [], schedule, publication_lag_days=60
    ) == ["AAPL", "XOM"]


def test_load_market_cap_universe_autodetects_format(tmp_path) -> None:
    annual = tmp_path / "annual.json"
    annual.write_text('{"data": {"2025": [{"symbol": "AAPL"}]}}')
    dated = tmp_path / "dated.json"
    dated.write_text('{"data": {"2015-03-31": [{"symbol": "GOOGL"}]}}')

    kind_a, loaded_a = load_market_cap_universe(annual)
    kind_d, loaded_d = load_market_cap_universe(dated)

    assert kind_a == "annual" and loaded_a == {2025: ["AAPL"]}
    assert kind_d == "dated"
    assert loaded_d == load_dated_market_cap_universe(dated)


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


def test_build_target_weights_limits_candidates_to_lagged_universe() -> None:
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
    universe_by_year = {2020: ["AAPL", "MSFT"], 2021: ["NVDA", "TSLA"]}

    weights = build_target_weights(
        close_prices=close_prices,
        symbols=["AAPL", "MSFT", "NVDA", "TSLA"],
        universe_resolver=lambda date: symbols_for_date(
            date, [], universe_by_year, lag_years=1
        ),
        lookback_days=1,
        top_n=1,
    )

    # 滯後 1 年：2021 年只可以揀 2020 年底嘅 [AAPL, MSFT]，
    # 就算 NVDA 喺 2021 動量爆炸都唔會入選（呢個正正係修咗嘅前視）。
    assert weights.loc["2021-01-01", "AAPL"] == 1.0
    assert weights.loc["2021-01-01", "NVDA"] == 0.0
    assert weights.loc["2021-01-04", "AAPL"] == 1.0
    assert weights.loc["2021-01-04", "NVDA"] == 0.0


def test_build_vol_target_exposure_uses_shifted_realized_vol() -> None:
    returns = pd.Series(
        [0.01, 0.01, 0.01, 0.03, -0.02],
        index=pd.date_range("2024-01-01", periods=5),
    )

    exposure = build_vol_target_exposure(
        base_returns=returns,
        target_vol=0.20,
        vol_window=2,
        max_leverage=2.0,
        rebal_band=0.0,
    )

    raw = (0.20 / (returns.rolling(2).std() * (252.0**0.5))).clip(
        lower=0.0,
        upper=2.0,
    )
    expected = raw.shift(1).fillna(0.0)

    pd.testing.assert_series_equal(exposure, expected)


def test_build_vol_target_exposure_respects_rebalance_band() -> None:
    target = pd.Series(
        [0.0, 1.00, 1.03, 1.10],
        index=pd.date_range("2024-01-01", periods=4),
    )

    # 1.00 -> 1.03 差距細過 band，應維持 1.00；到 1.10 先調。
    banded = apply_rebalance_band(target, rebal_band=0.05)

    assert list(banded.round(2)) == [0.0, 1.0, 1.0, 1.1]


def test_apply_exposure_returns_deducts_financing_and_turnover_cost() -> None:
    returns = pd.Series(
        [0.01, 0.02],
        index=pd.date_range("2024-01-01", periods=2),
    )
    exposure = pd.Series(
        [1.5, 1.0],
        index=returns.index,
    )

    result = apply_exposure_returns(
        base_returns=returns,
        exposure=exposure,
        financing_rate=0.252,
        cost_bps=10,
    )

    expected = pd.Series(
        [
            1.5 * 0.01 - 0.5 * 0.252 / 252 - 1.5 * 0.001,
            1.0 * 0.02 - 0.0 * 0.252 / 252 - 0.5 * 0.001,
        ],
        index=returns.index,
    )
    pd.testing.assert_series_equal(result, expected)
