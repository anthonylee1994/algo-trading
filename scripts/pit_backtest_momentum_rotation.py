"""Point-in-time（survivorship-free）闊池 momentum rotation 回測 —— 真正 alpha 路。

同 backtest_momentum_rotation.py 嘅分別：
- universe 唔係今日揀好嘅生存者，而係「每個時點實際喺 index / 篩選入面嘅成份股，
  包括之後被踢走 / 退市嗰啲」。
- 食你 Norgate / CRSP 嘅闊池數據（幾百隻），momentum 喺成個橫截面揀最強嗰 top_n。

要兩份數據（Norgate / CRSP 可以 export）：

1. 價格 CSV（--prices）：寬表，第一欄日期，其餘每欄一隻 symbol，total-return
   adjusted close。一定要包埋已退市 symbol，退市前最後一格 = 真實 delisting 價
   （破產接近零）。未上市 / 退市後留空 (NaN)。

   date,AAPL,MSFT,YHOO,LEH,...
   2010-01-04,6.5,23.1,16.7,62.3,...

2. 成份股 CSV（--membership）：point-in-time membership（symbol,start,end）。
   end 留空 = 至今仍係成份；一隻 symbol 可多行。

   symbol,start,end
   AAPL,2010-01-01,
   LEH,2008-01-01,2008-09-15

退市處理：退市後嘅最後價會 forward-fill（以退市價套現、之後當現金），所以 bt
唔會因為「揸住 NaN」報錯，而退市前嗰段跌幅照計。
"""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from algo_trading.momentum_rotation import format_bordered_table
from scripts.backtest_momentum_rotation import run_bt_backtest

TRADING_DAYS = 252


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--prices", help="寬表價格 CSV（date + 每欄一隻 symbol）。")
    parser.add_argument(
        "--membership", help="point-in-time 成份股 CSV（symbol,start,end）。"
    )
    parser.add_argument(
        "--benchmark", default="QQQ", help="benchmark symbol，要喺價格 CSV 入面。"
    )
    parser.add_argument("--lookback-days", type=int, default=126)
    parser.add_argument("--top-n", type=int, default=10)
    parser.add_argument(
        "--index-floor",
        default=None,
        help="正動量股票唔夠 top_n 隻時，空倉位用呢個 symbol（通常 benchmark）補返。",
    )
    parser.add_argument("--initial-cash", type=float, default=100_000)
    parser.add_argument("--cost-bps", type=float, default=15.0)
    parser.add_argument(
        "--rebalance", choices=["daily", "weekly", "monthly"], default="monthly"
    )
    parser.add_argument(
        "--demo",
        action="store_true",
        help="用合成闊池（含退市股票）示範 engine，唔需要真數據。",
    )
    args = parser.parse_args()

    if args.demo:
        raw_prices, membership = make_demo_dataset()
        benchmark = "BENCH"
    else:
        if not args.prices or not args.membership:
            parser.error("非 --demo 模式要俾 --prices 同 --membership。")
        raw_prices = load_prices(Path(args.prices))
        membership = load_membership(Path(args.membership))
        benchmark = args.benchmark

    if benchmark not in raw_prices.columns:
        parser.error(f"benchmark {benchmark} 唔喺價格數據入面。")
    index_floor = args.index_floor
    if index_floor is not None and index_floor not in raw_prices.columns:
        parser.error(f"index-floor {index_floor} 唔喺價格數據入面。")

    member_symbols = [
        s for s in membership["symbol"].unique() if s in raw_prices.columns
    ]
    membership_mask = build_membership_mask(
        raw_prices.index, membership, raw_prices.columns
    )

    print_survivorship_report(raw_prices, membership, member_symbols)

    weights = build_pit_weights(
        raw_prices=raw_prices,
        membership_mask=membership_mask,
        member_symbols=member_symbols,
        lookback_days=args.lookback_days,
        top_n=args.top_n,
        index_floor=index_floor,
    )

    panel = raw_prices.ffill()  # 退市後 hold 最後價；未上市保持 NaN（權重 0）。
    bt_result = run_bt_backtest(
        close_prices=panel,
        weights=weights,
        benchmark_symbol=benchmark,
        initial_cash=args.initial_cash,
        cost_bps=args.cost_bps,
        rebalance=args.rebalance,
    )

    strat = bt_result.prices["Momentum Rotation"].dropna().pct_change().dropna()
    bench = panel[benchmark].dropna().pct_change().dropna()
    common = strat.index.intersection(bench.index)
    strat, bench = strat.loc[common], bench.loc[common]

    floor_label = f", index-floor={index_floor}" if index_floor else ""
    print(
        f"Point-in-time 回測（{common[0].date()} → {common[-1].date()}，"
        f"top_n={args.top_n}, lookback={args.lookback_days}, "
        f"rebalance={args.rebalance}, cost={args.cost_bps:.0f} bps{floor_label}）：\n"
    )
    summary = pd.DataFrame(
        [
            _stats_row("Momentum Rotation（PIT）", strat),
            _stats_row(f"長揸 {benchmark}", bench),
        ]
    )
    for column in ["CAGR", "年化波幅", "Sharpe", "最大回撤", "總回報"]:
        summary[column] = summary[column].map(_fmt(column))
    print(format_bordered_table(summary))
    print()

    strat_cagr, bench_cagr = _cagr(strat) * 100, _cagr(bench) * 100
    strat_sharpe, bench_sharpe = _sharpe(strat), _sharpe(bench)
    if strat_cagr > bench_cagr and strat_sharpe > bench_sharpe:
        print(
            f"✅ Survivorship-free 之下 CAGR {strat_cagr:.1f}% 同 Sharpe {strat_sharpe:.2f} "
            f"都贏 {benchmark}（{bench_cagr:.1f}% / {bench_sharpe:.2f}）—— 真 alpha。"
        )
    elif strat_cagr > bench_cagr:
        print(
            f"⚠️ CAGR {strat_cagr:.1f}% 贏 {benchmark}（{bench_cagr:.1f}%），但 Sharpe "
            f"{strat_sharpe:.2f} vs {bench_sharpe:.2f} —— 多數係靠多冒風險。"
        )
    else:
        print(
            f"❌ Survivorship-free 之下 CAGR {strat_cagr:.1f}% 輸 {benchmark}"
            f"（{bench_cagr:.1f}%）—— 之前闊池嘅靚數字主要係倖存者偏差。"
        )


def load_prices(path: Path) -> pd.DataFrame:
    frame = pd.read_csv(path)
    date_col = frame.columns[0]
    frame[date_col] = pd.to_datetime(frame[date_col])
    return frame.set_index(date_col).sort_index().astype(float)


def load_membership(path: Path) -> pd.DataFrame:
    frame = pd.read_csv(path, dtype={"symbol": str})
    frame["start"] = pd.to_datetime(frame["start"])
    frame["end"] = pd.to_datetime(frame["end"]) if "end" in frame.columns else pd.NaT
    return frame


def build_membership_mask(
    index: pd.DatetimeIndex,
    membership: pd.DataFrame,
    columns: pd.Index,
) -> pd.DataFrame:
    mask = pd.DataFrame(False, index=index, columns=columns)
    for _, row in membership.iterrows():
        symbol = row["symbol"]
        if symbol not in columns:
            continue
        start = row["start"] if not pd.isna(row["start"]) else index[0]
        end = row["end"] if not pd.isna(row["end"]) else index[-1]
        mask.loc[(index >= start) & (index <= end), symbol] = True
    return mask


def build_pit_weights(
    raw_prices: pd.DataFrame,
    membership_mask: pd.DataFrame,
    member_symbols: list[str],
    lookback_days: int,
    top_n: int,
    index_floor: str | None = None,
) -> pd.DataFrame:
    top_n = max(top_n, 1)
    universe = list(dict.fromkeys(member_symbols))
    prices = raw_prices.loc[:, universe]
    momentum = prices.pct_change(lookback_days)
    # 合資格 = 當日係成份 + 有真實價 + 有足夠歷史計到 momentum。
    eligible = membership_mask.loc[:, universe] & prices.notna() & momentum.notna()
    weights = pd.DataFrame(0.0, index=raw_prices.index, columns=raw_prices.columns)
    momentum_values = momentum.to_numpy()
    eligible_values = eligible.to_numpy()
    {symbol: i for i, symbol in enumerate(universe)}
    for row_i, date in enumerate(raw_prices.index):
        elig_cols = np.where(eligible_values[row_i])[0]
        if elig_cols.size == 0 and index_floor is None:
            continue
        scores = momentum_values[row_i, elig_cols]
        order = elig_cols[np.argsort(scores)[::-1]]
        selected = [universe[c] for c in order if momentum_values[row_i, c] > 0][:top_n]
        if index_floor is not None:
            for symbol in selected:
                weights.at[date, symbol] += 1.0 / top_n
            empty = top_n - len(selected)
            if empty > 0:
                weights.at[date, index_floor] += empty / top_n
            continue
        if not selected:
            continue
        weight = 1.0 / len(selected)
        for symbol in selected:
            weights.at[date, symbol] = weight
    # 修前視：信號推遲一日成交。
    weights = weights.shift(1).fillna(0.0)
    # 安全網：未上市（panel 仍 NaN）嘅日子強制 0，避免 bt 揸住 NaN 報錯。
    weights = weights.where(raw_prices.notna().reindex_like(weights).fillna(False), 0.0)
    return weights


def print_survivorship_report(
    raw_prices: pd.DataFrame,
    membership: pd.DataFrame,
    member_symbols: list[str],
) -> None:
    all_members = set(membership["symbol"].unique())
    have_prices = set(member_symbols)
    missing = sorted(all_members - have_prices)
    ended = (
        membership.dropna(subset=["end"])
        if "end" in membership.columns
        else membership.iloc[0:0]
    )
    ended_symbols = sorted(set(ended["symbol"]) & have_prices)
    print("Survivorship 覆蓋報告：")
    print(f"  歷史成份股總數：{len(all_members)}")
    print(f"  有價格數據：{len(have_prices)}")
    print(f"  其中曾被踢走 / 退市（已含返入測試）：{len(ended_symbols)}")
    if missing:
        print(
            f"  ⚠️ 缺價格數據：{len(missing)} 隻 → 會被忽略，仍有殘留倖存者偏差："
            f"{', '.join(missing[:15])}" + ("…" if len(missing) > 15 else "")
        )
    else:
        print("  ✅ 所有歷史成份股都有價格，測試乾淨。")
    print()


def make_demo_dataset() -> tuple[pd.DataFrame, pd.DataFrame]:
    """合成闊池（40 隻，含多隻中途退市），示範 engine 處理 survivorship + 規模。"""
    rng = np.random.default_rng(7)
    index = pd.bdate_range("2010-01-01", "2023-12-31")
    n = len(index)
    data: dict[str, pd.Series] = {}
    rows = []
    for i in range(40):
        drift = rng.normal(0.10, 0.12)  # 有啲贏有啲輸
        vol = rng.uniform(0.25, 0.55)
        rets = rng.normal(drift / TRADING_DAYS, vol / np.sqrt(TRADING_DAYS), n)
        price = 100 * np.exp(np.cumsum(rets))
        series = pd.Series(price, index=index)
        symbol = f"S{i:02d}"
        start_i = 0 if rng.random() > 0.3 else int(rng.uniform(200, 1500))
        dead_i = None if rng.random() > 0.35 else int(rng.uniform(1500, n - 50))
        if start_i > 0:
            series.iloc[:start_i] = np.nan
        if dead_i is not None:
            series.iloc[dead_i:] = np.nan
        data[symbol] = series
        rows.append(
            {
                "symbol": symbol,
                "start": index[start_i].date().isoformat(),
                "end": index[dead_i].date().isoformat() if dead_i is not None else "",
            }
        )
    bench_rets = rng.normal(0.10 / TRADING_DAYS, 0.18 / np.sqrt(TRADING_DAYS), n)
    data["BENCH"] = pd.Series(100 * np.exp(np.cumsum(bench_rets)), index=index)
    raw_prices = pd.DataFrame(data)
    membership = pd.DataFrame(rows)
    membership["start"] = pd.to_datetime(membership["start"])
    membership["end"] = pd.to_datetime(membership["end"].replace("", pd.NaT))
    return raw_prices, membership


def _stats_row(name: str, returns: pd.Series) -> dict:
    return {
        "策略": name,
        "CAGR": _cagr(returns) * 100,
        "年化波幅": float(returns.std() * np.sqrt(TRADING_DAYS)) * 100,
        "Sharpe": _sharpe(returns),
        "最大回撤": _max_drawdown(returns) * 100,
        "總回報": _period_return(returns) * 100,
    }


def _sharpe(returns: pd.Series) -> float:
    if returns.empty or returns.std() == 0:
        return float("nan")
    return float(returns.mean() / returns.std() * np.sqrt(TRADING_DAYS))


def _cagr(returns: pd.Series) -> float:
    if returns.empty:
        return float("nan")
    growth = float((1 + returns).prod())
    years = len(returns) / TRADING_DAYS
    if years <= 0 or growth <= 0:
        return float("nan")
    return growth ** (1 / years) - 1


def _max_drawdown(returns: pd.Series) -> float:
    if returns.empty:
        return 0.0
    equity = (1 + returns).cumprod()
    return float((equity / equity.cummax() - 1).min())


def _period_return(returns: pd.Series) -> float:
    if returns.empty:
        return float("nan")
    return float((1 + returns).prod() - 1)


def _fmt(column: str):
    if column == "Sharpe":
        return lambda v: f"{v:.2f}"
    return lambda v: f"{v:.1f}%"


if __name__ == "__main__":
    main()
