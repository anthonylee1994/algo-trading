from __future__ import annotations

import argparse
from collections.abc import Callable
from datetime import UTC, datetime
import json
from pathlib import Path
import sys
from urllib.error import HTTPError
import urllib.parse
import urllib.request

import bt
import matplotlib.pyplot as plt
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from algo_trading.momentum_rotation import (
    format_bordered_table,
    format_momentum_score_table,
    latest_momentum_score_table,
)
from algo_trading.market_cap_universe import (
    DEFAULT_MARKET_CAP_UNIVERSE_PATH,
    load_market_cap_universe,
    symbols_for_date,
    symbols_for_schedule,
)

UniverseResolver = Callable[[pd.Timestamp], list[str]]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbols", nargs="+", default=None)
    parser.add_argument(
        "--universe-json",
        default=str(DEFAULT_MARKET_CAP_UNIVERSE_PATH),
        help="市值 Top N universe JSON；年度 key 或日期 key 都得。如指定 --symbols 就會改用固定 universe。",
    )
    parser.add_argument(
        "--universe-lag-years",
        type=int,
        default=1,
        help="年度 universe 滯後幾多年至可用（預設 1，避免 membership 前視）。設 0 還原舊行為（有前視）。",
    )
    parser.add_argument(
        "--universe-publication-lag-days",
        type=int,
        default=0,
        help="日期（季度）universe 嘅 publication lag 日數；快照生效日 + 呢個日數後至可用。",
    )
    parser.add_argument("--benchmark", default="QQQ")
    parser.add_argument("--start", default="2010-01-01")
    parser.add_argument("--end", default=None)
    parser.add_argument("--lookback-days", type=int, default=126)
    parser.add_argument("--top-n", type=int, default=2)
    parser.add_argument(
        "--index-floor",
        default=None,
        help="正動量股票唔夠 top_n 隻時，空倉位用呢個 symbol（通常 QQQ）補返而唔係揸現金。",
    )
    parser.add_argument("--initial-cash", type=float, default=100_000)
    parser.add_argument(
        "--leverage",
        type=float,
        default=1.0,
        help="組合槓桿倍數（例 1.15）。借入部分按 --financing-rate 收息。",
    )
    parser.add_argument(
        "--financing-rate",
        type=float,
        default=0.03,
        help="槓桿借入部分嘅年化融資成本（預設 3%%）。",
    )
    parser.add_argument(
        "--vol-target",
        type=float,
        default=None,
        help="啟用波動率目標曝險（例 0.26 = 26%% 年化波幅）。會覆蓋固定 --leverage summary。",
    )
    parser.add_argument(
        "--vol-window",
        type=int,
        default=40,
        help="vol-target 用幾多個交易日計 realized volatility（預設 40）。",
    )
    parser.add_argument(
        "--max-leverage",
        type=float,
        default=2.0,
        help="vol-target 最大曝險上限（例 2.0 = 2x）。",
    )
    parser.add_argument(
        "--rebal-band",
        type=float,
        default=0.05,
        help="vol-target 目標曝險變動超過呢個幅度先調整，減少換手（預設 0.05x）。",
    )
    parser.add_argument(
        "--rebalance",
        choices=["daily", "weekly", "monthly"],
        default="monthly",
        help="重新平衡頻率；momentum rotation 高換手，預設用 monthly 壓低成本。",
    )
    parser.add_argument(
        "--cost-bps",
        type=float,
        default=15.0,
        help="每次成交嘅佣金 + 滑點（基點）；15 = 0.15%%。設 0 即無成本。",
    )
    parser.add_argument(
        "--sweep-lookback",
        nargs="+",
        type=int,
        default=None,
        help="跑多個 lookback 做敏感度分析，例如 --sweep-lookback 63 126 252 504。",
    )
    parser.add_argument(
        "--output-csv",
        default="output/backtest_trades.csv",
        help="交易紀錄 CSV output path；用空字串可跳過輸出。",
    )
    parser.add_argument(
        "--plot-path",
        default="output/backtest_chart.png",
        help="bt equity curve chart output path；用空字串可跳過輸出。",
    )
    args = parser.parse_args()

    universe_resolver: UniverseResolver | None = None
    if args.symbols:
        strategy_symbols = list(dict.fromkeys(args.symbols))
        data_symbols = strategy_symbols
        universe_label = "固定 universe"
    else:
        kind, loaded = load_market_cap_universe(Path(args.universe_json))
        if kind == "annual":
            data_symbols = sorted(
                {symbol for symbols in loaded.values() for symbol in symbols}
            )
            strategy_symbols = data_symbols
            universe_resolver = lambda date: symbols_for_date(  # noqa: E731
                date, strategy_symbols, loaded, lag_years=args.universe_lag_years
            )
            universe_label = (
                f"每年 S&P 500 市值 Top 10（滯後 {args.universe_lag_years} 年，{args.universe_json}）"
            )
        else:
            data_symbols = sorted(
                {symbol for _, symbols in loaded for symbol in symbols}
            )
            strategy_symbols = data_symbols
            universe_resolver = lambda date: symbols_for_schedule(  # noqa: E731
                date,
                strategy_symbols,
                loaded,
                publication_lag_days=args.universe_publication_lag_days,
            )
            universe_label = (
                f"Point-in-time 市值 universe（{len(loaded)} 個快照，"
                f"publication lag {args.universe_publication_lag_days} 日）"
            )

    fetch_symbols = [*data_symbols, args.benchmark]
    if args.index_floor:
        fetch_symbols.append(args.index_floor)
    symbols = list(dict.fromkeys(fetch_symbols))
    charts = {
        symbol: fetch_yahoo_chart(symbol, args.start, args.end) for symbol in symbols
    }
    close_prices = pd.concat(
        [charts[symbol]["adj_close"].rename(symbol) for symbol in symbols],
        axis=1,
        join="outer",
    ).sort_index().ffill().dropna(how="all")
    close_prices.index = pd.to_datetime(close_prices.index)
    raw_close_prices = pd.concat(
        [charts[symbol]["close"].rename(symbol) for symbol in symbols],
        axis=1,
        join="outer",
    ).sort_index().ffill().dropna(how="all")
    raw_close_prices.index = pd.to_datetime(raw_close_prices.index)

    print_data_coverage(close_prices, strategy_symbols, args.start)

    if args.sweep_lookback:
        run_lookback_sweep(
            close_prices=close_prices,
            symbols=strategy_symbols,
            universe_resolver=universe_resolver,
            benchmark_symbol=args.benchmark,
            initial_cash=args.initial_cash,
            top_n=args.top_n,
            cost_bps=args.cost_bps,
            rebalance=args.rebalance,
            lookbacks=args.sweep_lookback,
            index_floor=args.index_floor,
        )
        print()

    weights = build_target_weights(
        close_prices=close_prices,
        symbols=strategy_symbols,
        universe_resolver=universe_resolver,
        lookback_days=args.lookback_days,
        top_n=args.top_n,
        index_floor=args.index_floor,
    )
    bt_result = run_bt_backtest(
        close_prices=close_prices,
        weights=weights,
        benchmark_symbol=args.benchmark,
        initial_cash=args.initial_cash,
        cost_bps=args.cost_bps,
        rebalance=args.rebalance,
    )
    summary = build_backtest_summary(
        bt_result=bt_result,
        initial_cash=args.initial_cash,
    )
    curve = build_curve(
        bt_result=bt_result,
        weights=weights,
        close_prices=close_prices,
        lookback_days=args.lookback_days,
        initial_cash=args.initial_cash,
    )
    summary["trade_count"] = max(
        int(curve["selected"].ne(curve["selected"].shift()).sum()) - 1,
        0,
    )

    print(f"Momentum rotation 回測（{summary['start']} 至 {summary['end']}）")
    print(f"交易範圍：{universe_label}")
    print(f"資料 symbols：{', '.join(strategy_symbols)}")
    print(f"持倉數量：Top {args.top_n}")
    print(f"重新平衡：{args.rebalance}；每次成交成本：{args.cost_bps:.1f} bps")
    print(f"最終資產：${summary['final_equity']:,.2f}")
    print(f"總回報：{summary['total_return_pct']:.2f}%")
    print(f"年化回報：{summary['cagr_pct']:.2f}%")
    print(f"最大回撤：{summary['max_drawdown_pct']:.2f}%")
    print(f"訊號切換次數：{summary['trade_count']}")
    print()
    print(f"長揸 {args.benchmark}：${summary['benchmark_final_equity']:,.2f}")
    print(f"長揸回報：{summary['benchmark_total_return_pct']:.2f}%")
    print(f"長揸年化回報：{summary['benchmark_cagr_pct']:.2f}%")
    print(f"長揸最大回撤：{summary['benchmark_max_drawdown_pct']:.2f}%")
    print()
    if args.vol_target:
        vol_target = build_vol_target_summary(
            bt_result=bt_result,
            target_vol=args.vol_target,
            vol_window=args.vol_window,
            max_leverage=args.max_leverage,
            financing_rate=args.financing_rate,
            cost_bps=args.cost_bps,
            rebal_band=args.rebal_band,
            initial_cash=args.initial_cash,
        )
        print(
            "Vol-target "
            f"{args.vol_target * 100:.1f}%（window {args.vol_window}D，"
            f"cap ×{args.max_leverage:g}，band {args.rebal_band:g}，"
            f"融資 {args.financing_rate * 100:.1f}%/年）："
        )
        print(f"最終資產：${vol_target['final_equity']:,.2f}")
        print(f"年化回報：{vol_target['cagr_pct']:.2f}%")
        print(f"最大回撤：{vol_target['max_drawdown_pct']:.2f}%")
        print(f"Sharpe：{vol_target['sharpe']:.2f}")
        print(f"平均曝險：{vol_target['avg_exposure']:.2f}x")
        print(f"低波曝險：{vol_target['low_vol_exposure']:.2f}x")
        print(f"高波曝險：{vol_target['high_vol_exposure']:.2f}x")
        print(f"最新實際波幅：{vol_target['latest_realized_vol_pct']:.2f}%")
        print(f"最新目標曝險：{vol_target['latest_target_exposure']:.2f}x")
        print(f"最新有效曝險：{vol_target['latest_effective_exposure']:.2f}x")
        print(f"融資 drag：約 {vol_target['financing_drag_pct']:.2f}%/年")
        print(f"調倉成本：約 {vol_target['rebalance_cost_pct']:.2f}%/年")
        print()
    elif args.leverage and args.leverage != 1.0:
        levered = build_levered_summary(
            bt_result=bt_result,
            leverage=args.leverage,
            financing_rate=args.financing_rate,
        )
        print(
            f"槓桿 ×{args.leverage:g}（融資 {args.financing_rate * 100:.1f}%/年）："
        )
        print(f"年化回報：{levered['cagr_pct']:.2f}%")
        print(f"最大回撤：{levered['max_drawdown_pct']:.2f}%")
        print(f"Sharpe：{levered['sharpe']:.2f}")
        print()
    print("最新 momentum 分數：")
    latest_symbols = (
        universe_resolver(close_prices.index[-1]) if universe_resolver else strategy_symbols
    )
    print(
        format_momentum_score_table(
            latest_momentum_score_table(
                close_prices.loc[:, latest_symbols],
                args.lookback_days,
                latest_close_prices=raw_close_prices.loc[:, latest_symbols],
            )
        )
    )
    print()
    trades = build_trade_table(curve)
    if args.output_csv:
        output_path = Path(args.output_csv)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        trades.to_csv(output_path, index=False)
        print(f"交易紀錄 CSV：{output_path}")
        print()
    if args.plot_path:
        plot_path = Path(args.plot_path)
        plot_path.parent.mkdir(parents=True, exist_ok=True)
        plot_bt_result(bt_result, plot_path)
        print(f"回測圖表：{plot_path}")
        print()

    print("最後 10 筆交易：")
    print(format_bordered_table(format_trade_table_for_console(trades.tail(10))))


def build_target_weights(
    close_prices: pd.DataFrame,
    symbols: list[str],
    lookback_days: int,
    top_n: int = 1,
    universe_resolver: UniverseResolver | None = None,
    index_floor: str | None = None,
) -> pd.DataFrame:
    """每個 rebalance 揀 momentum 最強嘅 top_n。

    `index_floor`：當正動量嘅 symbol 唔夠 top_n 隻，空出嚟嘅倉位用呢個 symbol
    （通常係 QQQ）補返，而唔係攤分／揸現金。即係「最強嗰幾隻 + 其餘跟指數」，
    令策略喺個別股票唔強時唔會輸大段畀指數。空位邏輯改用 1/top_n 等權。
    """
    symbols = list(dict.fromkeys(symbols))
    candidate_symbols = list(symbols)
    if index_floor is not None and index_floor not in candidate_symbols:
        # floor symbol（如 QQQ）唔係 momentum 候選，但要有 column 至補得到倉位。
        candidate_symbols.append(index_floor)
    momentum = close_prices.loc[:, candidate_symbols].pct_change(lookback_days)
    weights = pd.DataFrame(0.0, index=close_prices.index, columns=candidate_symbols)
    top_n = max(top_n, 1)
    for date, row in momentum.iterrows():
        universe_symbols = universe_resolver(date) if universe_resolver else symbols
        ranking = row.loc[
            [symbol for symbol in universe_symbols if symbol in row.index]
        ]
        ranking = ranking.dropna().sort_values(ascending=False)
        ranking = ranking[ranking > 0]
        selected = list(ranking.head(top_n).index)
        if index_floor is not None:
            # 每個槽位 1/top_n；空槽位歸 index_floor。
            for symbol in selected:
                weights.loc[date, str(symbol)] += 1.0 / top_n
            empty = top_n - len(selected)
            if empty > 0 and index_floor in weights.columns:
                weights.loc[date, index_floor] += empty / top_n
            continue
        if not selected:
            continue
        weight = 1.0 / len(selected)
        for symbol in selected:
            weights.loc[date, str(symbol)] = weight
    # 修正前視偏差：用 close[t] 計嘅信號，最快只可以喺 t+1 成交。
    # 將目標倉位推遲一個交易日，避免「用收市價計、又用同一個收市價成交」。
    weights = weights.shift(1).fillna(0.0)
    return weights


def _run_frequency_algo(rebalance: str) -> bt.algos.Algo:
    if rebalance == "weekly":
        return bt.algos.RunWeekly()
    if rebalance == "monthly":
        return bt.algos.RunMonthly()
    return bt.algos.RunDaily()


def _make_commission(cost_bps: float):
    """每次成交收 cost_bps 個基點（佣金 + 滑點）嘅成交金額。"""
    rate = max(cost_bps, 0.0) / 10_000.0

    def commission(quantity: float, price: float) -> float:
        return abs(float(quantity) * float(price)) * rate

    return commission


def run_bt_backtest(
    close_prices: pd.DataFrame,
    weights: pd.DataFrame,
    benchmark_symbol: str,
    initial_cash: float,
    cost_bps: float = 15.0,
    rebalance: str = "monthly",
) -> bt.backtest.Result:
    commission = _make_commission(cost_bps)
    strategy = bt.Strategy(
        "Momentum Rotation",
        [
            _run_frequency_algo(rebalance),
            bt.algos.WeighTarget(weights),
            bt.algos.Rebalance(),
        ],
    )
    benchmark_weights = pd.DataFrame(
        {benchmark_symbol: 1.0},
        index=close_prices.index,
    )
    benchmark_strategy = bt.Strategy(
        f"Buy Hold {benchmark_symbol}",
        [
            _run_frequency_algo(rebalance),
            bt.algos.WeighTarget(benchmark_weights),
            bt.algos.Rebalance(),
        ],
    )
    return bt.run(
        bt.Backtest(
            strategy,
            close_prices,
            initial_capital=initial_cash,
            integer_positions=False,
            commissions=commission,
        ),
        bt.Backtest(
            benchmark_strategy,
            close_prices.loc[:, [benchmark_symbol]],
            initial_capital=initial_cash,
            integer_positions=False,
            commissions=commission,
        ),
    )


def plot_bt_result(bt_result: bt.backtest.Result, output_path: Path) -> None:
    axis = bt_result.plot(title="Momentum Rotation vs Benchmark")
    figure = axis.get_figure()
    figure.set_size_inches(12, 7)
    figure.tight_layout()
    figure.savefig(output_path, dpi=160)
    plt.close(figure)


def build_backtest_summary(
    bt_result: bt.backtest.Result,
    initial_cash: float,
) -> dict[str, float | int | str]:
    strategy_name = "Momentum Rotation"
    benchmark_name = next(
        name for name in bt_result.prices.columns if name != strategy_name
    )
    strategy_prices = bt_result.prices[strategy_name].dropna()
    benchmark_prices = bt_result.prices[benchmark_name].dropna()
    stats = bt_result.stats
    return {
        "start": strategy_prices.index[0].date().isoformat(),
        "end": strategy_prices.index[-1].date().isoformat(),
        "final_equity": _bt_price_to_equity(strategy_prices.iloc[-1], initial_cash),
        "total_return_pct": float(stats.loc["total_return", strategy_name]) * 100,
        "cagr_pct": float(stats.loc["cagr", strategy_name]) * 100,
        "max_drawdown_pct": float(stats.loc["max_drawdown", strategy_name]) * 100,
        "trade_count": 0,
        "benchmark_final_equity": _bt_price_to_equity(
            benchmark_prices.iloc[-1], initial_cash
        ),
        "benchmark_total_return_pct": float(stats.loc["total_return", benchmark_name])
        * 100,
        "benchmark_cagr_pct": float(stats.loc["cagr", benchmark_name]) * 100,
        "benchmark_max_drawdown_pct": float(stats.loc["max_drawdown", benchmark_name])
        * 100,
    }


def build_levered_summary(
    bt_result: bt.backtest.Result,
    leverage: float,
    financing_rate: float,
) -> dict[str, float]:
    """喺策略每日回報上加槓桿：L×回報 − (L−1)×每日融資成本。"""
    returns = bt_result.prices["Momentum Rotation"].dropna().pct_change().dropna()
    daily_financing = (leverage - 1.0) * financing_rate / 252.0
    levered = leverage * returns - daily_financing
    growth = float((1.0 + levered).prod())
    years = len(levered) / 252.0
    cagr = growth ** (1.0 / years) - 1.0 if years > 0 and growth > 0 else float("nan")
    equity = (1.0 + levered).cumprod()
    max_drawdown = float((equity / equity.cummax() - 1.0).min())
    std = float(levered.std())
    sharpe = float(levered.mean() / std * (252.0**0.5)) if std > 0 else float("nan")
    return {
        "cagr_pct": cagr * 100,
        "max_drawdown_pct": max_drawdown * 100,
        "sharpe": sharpe,
    }


def build_vol_target_summary(
    bt_result: bt.backtest.Result,
    target_vol: float,
    vol_window: int,
    max_leverage: float,
    financing_rate: float,
    cost_bps: float,
    rebal_band: float,
    initial_cash: float,
) -> dict[str, float]:
    """用 base strategy 日回報計 vol-target 曝險，避免同日信號/成交前視。

    曝險 = target_vol / realized_vol，封頂 max_leverage；用 t 日收市前可知嘅
    realized vol 決定 t+1 曝險。回報再扣借入部分融資成本同曝險變動成本。
    """
    base_prices = bt_result.prices["Momentum Rotation"].dropna()
    base_returns = base_prices.pct_change().dropna()
    exposure = build_vol_target_exposure(
        base_returns=base_returns,
        target_vol=target_vol,
        vol_window=vol_window,
        max_leverage=max_leverage,
        rebal_band=rebal_band,
    )
    returns = apply_exposure_returns(
        base_returns=base_returns,
        exposure=exposure,
        financing_rate=financing_rate,
        cost_bps=cost_bps,
    )
    equity = (1.0 + returns).cumprod()
    years = len(returns) / 252.0
    growth = float(equity.iloc[-1])
    cagr = growth ** (1.0 / years) - 1.0 if years > 0 and growth > 0 else float("nan")
    max_drawdown = float((equity / equity.cummax() - 1.0).min())
    std = float(returns.std())
    sharpe = float(returns.mean() / std * (252.0**0.5)) if std > 0 else float("nan")
    realized_vol = base_returns.rolling(vol_window).std() * (252.0**0.5)
    latest_realized_vol = float(realized_vol.dropna().iloc[-1])
    latest_raw_exposure = (
        target_vol / latest_realized_vol if latest_realized_vol > 0 else 0.0
    )
    latest_target_exposure = min(latest_raw_exposure, max(max_leverage, 0.0))
    low_vol_cutoff = realized_vol.quantile(0.25)
    high_vol_cutoff = realized_vol.quantile(0.75)
    aligned_exposure = exposure.reindex(returns.index).fillna(0.0)
    borrow = aligned_exposure.sub(1.0).clip(lower=0.0)
    financing_drag = float(
        (borrow * financing_rate / 252.0).sum() / len(returns) * 252.0
    )
    rebalance_cost = float(
        (
            aligned_exposure.diff().abs().fillna(aligned_exposure.abs())
            * max(cost_bps, 0.0)
            / 10_000.0
        ).sum()
        / len(returns)
        * 252.0
    )
    return {
        "final_equity": growth * initial_cash,
        "cagr_pct": cagr * 100,
        "max_drawdown_pct": max_drawdown * 100,
        "sharpe": sharpe,
        "avg_exposure": float(aligned_exposure.mean()),
        "low_vol_exposure": float(
            aligned_exposure[realized_vol <= low_vol_cutoff].mean()
        ),
        "high_vol_exposure": float(
            aligned_exposure[realized_vol >= high_vol_cutoff].mean()
        ),
        "latest_realized_vol_pct": latest_realized_vol * 100,
        "latest_target_exposure": latest_target_exposure,
        "latest_effective_exposure": float(aligned_exposure.iloc[-1]),
        "financing_drag_pct": financing_drag * 100,
        "rebalance_cost_pct": rebalance_cost * 100,
    }


def build_vol_target_exposure(
    base_returns: pd.Series,
    target_vol: float,
    vol_window: int,
    max_leverage: float,
    rebal_band: float,
) -> pd.Series:
    realized_vol = base_returns.rolling(max(vol_window, 1)).std() * (252.0**0.5)
    raw_exposure = target_vol / realized_vol
    target_exposure = raw_exposure.clip(lower=0.0, upper=max(max_leverage, 0.0))
    target_exposure = target_exposure.shift(1).fillna(0.0)
    return apply_rebalance_band(target_exposure, rebal_band)


def apply_rebalance_band(target_exposure: pd.Series, rebal_band: float) -> pd.Series:
    current = 0.0
    values = []
    for target in target_exposure.fillna(0.0):
        target = float(target)
        if abs(target - current) > max(rebal_band, 0.0):
            current = target
        values.append(current)
    return pd.Series(values, index=target_exposure.index)


def apply_exposure_returns(
    base_returns: pd.Series,
    exposure: pd.Series,
    financing_rate: float,
    cost_bps: float,
) -> pd.Series:
    aligned = pd.concat(
        [base_returns.rename("base"), exposure.rename("exposure")],
        axis=1,
        join="inner",
    ).dropna()
    borrow = aligned["exposure"].sub(1.0).clip(lower=0.0)
    financing = borrow * financing_rate / 252.0
    exposure_turnover = aligned["exposure"].diff().abs().fillna(
        aligned["exposure"].abs()
    )
    rebalance_cost = exposure_turnover * max(cost_bps, 0.0) / 10_000.0
    return aligned["exposure"] * aligned["base"] - financing - rebalance_cost


def build_curve(
    bt_result: bt.backtest.Result,
    weights: pd.DataFrame,
    close_prices: pd.DataFrame,
    lookback_days: int,
    initial_cash: float,
) -> pd.DataFrame:
    strategy_prices = bt_result.prices["Momentum Rotation"].dropna()
    equity = strategy_prices.map(lambda value: _bt_price_to_equity(value, initial_cash))
    equity = equity.reindex(strategy_prices.index).ffill().dropna()
    # 用 bt 實際執行咗嘅持倉（已反映 rebalance 頻率），唔好用每日 target，
    # 否則交易表會把每日信號變化全部當成成交，嚴重高估換手。
    realized = bt_result.backtests["Momentum Rotation"].security_weights
    weights = realized.reindex(equity.index).ffill().fillna(0)
    momentum = close_prices.pct_change(lookback_days).reindex(equity.index)
    rows = []
    previous_symbols: list[str] = []
    for date in equity.index:
        current_symbols = _symbols_from_weight_row(weights.loc[date])
        bought_symbols = [
            symbol for symbol in current_symbols if symbol not in previous_symbols
        ]
        sold_symbols = [
            symbol for symbol in previous_symbols if symbol not in current_symbols
        ]
        rows.append(
            {
                "date": date.date().isoformat(),
                "signal_date": date.date().isoformat(),
                "selected": _format_symbols(current_symbols),
                "previous_selected": _format_symbols(previous_symbols),
                "momentum": _max_momentum(momentum, date, current_symbols),
                "buy_price": _format_symbol_prices(close_prices, date, bought_symbols),
                "sell_price": _format_symbol_prices(close_prices, date, sold_symbols),
                "equity": float(equity.loc[date]),
                "drawdown": float(equity.loc[date] / equity.loc[:date].max() - 1),
                "day_return": float(equity.pct_change().fillna(0).loc[date]),
            }
        )
        previous_symbols = current_symbols
    curve = pd.DataFrame(rows)
    return curve


def _symbols_from_weight_row(row: pd.Series, threshold: float = 1e-3) -> list[str]:
    # 用門檻過濾 drift／浮點殘留，再以字母排序固定次序，
    # 避免 realized weight 日日 drift 令排名互換而砌出假交易。
    if row.empty:
        return []
    held = [str(symbol) for symbol, value in row.items() if float(value) > threshold]
    return sorted(held)


def _format_symbols(symbols: list[str]) -> str:
    return ", ".join(symbols) if symbols else "CASH"


def _max_momentum(
    values: pd.DataFrame, date: pd.Timestamp, symbols: list[str]
) -> float:
    if not symbols or date not in values.index:
        return float("nan")
    row = values.loc[date, [symbol for symbol in symbols if symbol in values.columns]]
    if row.empty:
        return float("nan")
    value = row.max()
    return float(value) if not pd.isna(value) else float("nan")


def _format_symbol_prices(
    values: pd.DataFrame,
    date: pd.Timestamp,
    symbols: list[str],
) -> str:
    if not symbols or date not in values.index:
        return ""
    parts = []
    for symbol in symbols:
        if symbol not in values.columns:
            continue
        value = values.loc[date, symbol]
        if pd.isna(value):
            continue
        parts.append(f"{symbol}:{float(value):,.2f}")
    return "; ".join(parts)


def _bt_price_to_equity(price: float, initial_cash: float) -> float:
    return float(price) / 100 * initial_cash


def build_trade_table(curve: pd.DataFrame) -> pd.DataFrame:
    trade_rows = curve[curve["selected"].ne(curve["selected"].shift())].copy()
    columns = [
        "date",
        "signal_date",
        "previous_selected",
        "sell_price",
        "selected",
        "buy_price",
        "momentum",
        "equity",
        "drawdown",
        "day_return",
    ]
    return trade_rows.loc[:, columns].rename(
        columns={
            "date": "日期",
            "signal_date": "訊號日期",
            "previous_selected": "賣出持倉",
            "sell_price": "賣出價",
            "selected": "買入持倉",
            "buy_price": "買入價",
            "momentum": "momentum",
            "equity": "資產",
            "drawdown": "回撤",
            "day_return": "日回報",
        }
    )


def format_trade_table_for_console(trades: pd.DataFrame) -> pd.DataFrame:
    table = trades.copy()
    table["賣出價"] = table["賣出價"].map(_format_price)
    table["買入價"] = table["買入價"].map(_format_price)
    table["momentum"] = table["momentum"].map(_format_percent)
    table["資產"] = table["資產"].map(lambda value: f"{float(value):,.2f}")
    table["回撤"] = table["回撤"].map(_format_percent)
    table["日回報"] = table["日回報"].map(_format_percent)
    return table


def _format_percent(value: float) -> str:
    if pd.isna(value):
        return ""
    return f"{float(value) * 100:.2f}%"


def _format_price(value: float) -> str:
    if isinstance(value, str):
        return value
    if pd.isna(value):
        return ""
    return f"{float(value):,.2f}"


def print_data_coverage(
    close_prices: pd.DataFrame,
    symbols: list[str],
    requested_start: str,
) -> None:
    """列出每隻 symbol 真實有數據嘅起始日，提醒倖存者偏差／歷史唔齊。"""
    requested = pd.to_datetime(requested_start)
    print("數據覆蓋範圍（Yahoo 只有現存上市股票，已退市嘅唔會出現）：")
    late_starters = []
    for symbol in list(dict.fromkeys(symbols)):
        if symbol not in close_prices.columns:
            print(f"  {symbol:<6} 無數據")
            late_starters.append(symbol)
            continue
        series = close_prices[symbol].dropna()
        if series.empty:
            print(f"  {symbol:<6} 無數據")
            late_starters.append(symbol)
            continue
        first = series.index[0]
        flag = ""
        if first > requested + pd.Timedelta(days=7):
            flag = "  ⚠️ 遲過回測起點，早年唔會入選"
            late_starters.append(symbol)
        print(f"  {symbol:<6} {first.date().isoformat()}{flag}")
    if late_starters:
        print(
            f"  ⚠️ {len(late_starters)} 隻 symbol 冇齊歷史："
            f"早年 universe 細咗，回報會偏高，請當心解讀。"
        )
    print()


def run_lookback_sweep(
    close_prices: pd.DataFrame,
    symbols: list[str],
    universe_resolver: UniverseResolver | None,
    benchmark_symbol: str,
    initial_cash: float,
    top_n: int,
    cost_bps: float,
    rebalance: str,
    lookbacks: list[int],
    index_floor: str | None = None,
) -> None:
    """跑多個 lookback，睇下表現對參數有幾敏感（過度擬合檢查）。"""
    print(
        f"Lookback 敏感度分析（top_n={top_n}, rebalance={rebalance}, cost={cost_bps:.1f} bps）："
    )
    rows = []
    for lookback in lookbacks:
        weights = build_target_weights(
            close_prices=close_prices,
            symbols=symbols,
            universe_resolver=universe_resolver,
            lookback_days=lookback,
            top_n=top_n,
            index_floor=index_floor,
        )
        result = run_bt_backtest(
            close_prices=close_prices,
            weights=weights,
            benchmark_symbol=benchmark_symbol,
            initial_cash=initial_cash,
            cost_bps=cost_bps,
            rebalance=rebalance,
        )
        stats = result.stats
        rows.append(
            {
                "lookback": lookback,
                "CAGR": float(stats.loc["cagr", "Momentum Rotation"]) * 100,
                "最大回撤": float(stats.loc["max_drawdown", "Momentum Rotation"]) * 100,
                "總回報": float(stats.loc["total_return", "Momentum Rotation"]) * 100,
            }
        )
    table = pd.DataFrame(rows)
    table["CAGR"] = table["CAGR"].map(lambda v: f"{v:.2f}%")
    table["最大回撤"] = table["最大回撤"].map(lambda v: f"{v:.2f}%")
    table["總回報"] = table["總回報"].map(lambda v: f"{v:.2f}%")
    print(format_bordered_table(table))


def fetch_yahoo_history(symbol: str, start: str, end: str | None) -> pd.Series:
    return fetch_yahoo_chart(symbol, start, end)["adj_close"]


def fetch_yahoo_chart(symbol: str, start: str, end: str | None) -> pd.DataFrame:
    yahoo_symbol = yahoo_chart_symbol(symbol)
    period1 = _timestamp(start)
    period2 = _timestamp(end) if end else int(datetime.now(tz=UTC).timestamp())
    query = urllib.parse.urlencode(
        {
            "period1": period1,
            "period2": period2,
            "interval": "1d",
            "events": "history",
            "includeAdjustedClose": "true",
        }
    )
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{yahoo_symbol}?{query}"
    request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            payload = json.load(response)
    except HTTPError as error:
        raise RuntimeError(
            f"{symbol} Yahoo 圖表數據 HTTP {error.code}（Yahoo symbol: {yahoo_symbol}）"
        ) from error

    chart = payload.get("chart", {})
    if chart.get("error"):
        raise RuntimeError(f"{symbol} Yahoo 圖表數據錯誤：{chart['error']}")

    result = chart["result"][0]
    timestamps = result["timestamp"]
    quote = result["indicators"]["quote"][0]
    adjclose = result["indicators"].get("adjclose", [{}])[0].get("adjclose", [])
    closes = quote["close"]
    adjusted_closes = adjclose or closes
    dates = [datetime.fromtimestamp(ts, tz=UTC).date() for ts in timestamps]
    return pd.DataFrame(
        {
            "close": closes,
            "adj_close": adjusted_closes,
        },
        index=dates,
    ).dropna(subset=["close", "adj_close"])


def yahoo_chart_symbol(symbol: str) -> str:
    # Yahoo Finance 用 dash 表示 Berkshire B shares，策略/JSON 保留常見 ticker BRK.B。
    return {"BRK.B": "BRK-B"}.get(symbol, symbol)


def _timestamp(value: str | None) -> int:
    if value is None:
        return int(datetime.now(tz=UTC).timestamp())
    return int(datetime.fromisoformat(value).replace(tzinfo=UTC).timestamp())


if __name__ == "__main__":
    main()
