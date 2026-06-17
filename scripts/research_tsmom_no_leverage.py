"""無槓桿 time-series momentum（TSMOM）per-stock trend following 回測。

同之前 cross-sectional momentum（揀最強 top N）嘅分別：
- cross-sectional：全市場揀 momentum 最強嗰幾隻，跌市都要揀「相對最強」→ 食跌市虧損。
- **time-series**：每隻股票獨立判斷自己嘅趨勢（升緊先揸，跌穿就轉 cash/QQQ）→
  避開個股崩盤（META 2022 -76%、NFLX -70%），同時保留升緊嗰啲嘅 upside。

文獻支撐：Moskowitz, Ooi & Pedersen (2012) "Time Series Momentum" 喺 58 個資產類別
搵到顯著 TSMOM premium；long-only 版本保留 equity upside、靠 cut losses 控制 drawdown。

兩種構造（都無借貸，總曝險 ≤ 100%）：
1. cash-mode（`--max-n`，固定 notional）：每隻 on 股票 1/max_n，off 部分揸 cash。
   → 經典 CTA 固定 fractional sizing，drawdown 控制靠 cash。
2. floor-mode（`--index-floor`，fully invested）：on 股票之間 equal weight，off → QQQ。
   → keep invested、靠轉去 QQQ 避免「揸住一籃弱勢股」。

universe：`pit`（S&P 500 點-in-time，含退市股，真 survivorship-free）或 `mega`
（每年滯後 1 年市值 top-10，同主策略個池）。
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from algo_trading.market_cap_universe import (
    load_yearly_market_cap_universe,
    symbols_for_date,
)
from algo_trading.momentum_rotation import format_bordered_table
from scripts.backtest_momentum_rotation import run_bt_backtest
from scripts.pit_backtest_momentum_rotation import (
    build_membership_mask,
    load_membership,
    load_prices,
)

TRADING_DAYS = 252


def build_mega_membership_mask(
    index: pd.DatetimeIndex,
    schedule: dict[int, list[str]],
    columns: pd.Index,
) -> pd.DataFrame:
    """mega-cap universe：每個交易日，用滯後 1 年市值 top-10 做合資格成份。"""
    available_years = sorted(schedule)
    col_set = set(columns)

    def syms_for_year(year: int) -> list[str]:
        target = year - 1  # lag_years=1：Y 年淨係用 Y-1（或更早）年底快照。
        usable = [y for y in available_years if y <= target]
        src = schedule[usable[-1]] if usable else schedule[available_years[0]]
        return [s for s in src if s in col_set]

    by_year = {y: set(syms_for_year(y)) for y in set(int(d.year) for d in index)}
    data = pd.DataFrame(False, index=index, columns=columns)
    for year, sym_set in by_year.items():
        year_mask = index.year == year
        if sym_set:
            data.loc[year_mask, list(sym_set)] = True
    return data


def build_tsmom_weights(
    raw_prices: pd.DataFrame,
    membership_mask: pd.DataFrame,
    member_symbols: list[str],
    lookback_days: int,
    ma_days: int,
    signal: str,
    max_n: int,
    index_floor: str | None,
) -> pd.DataFrame:
    """每隻股票獨立 trend signal，on 股票分配權重，off 轉 cash 或 floor。"""
    universe = list(dict.fromkeys(member_symbols))
    prices = raw_prices.loc[:, universe]
    ret_signal = prices.pct_change(lookback_days)
    if ma_days > 0:
        ma_signal = prices / prices.rolling(ma_days).mean() - 1.0
    else:
        ma_signal = pd.DataFrame(0.0, index=prices.index, columns=prices.columns)

    def is_on(r_val: float, m_val: float) -> bool:
        if signal == "tsmom":
            return r_val > 0
        if signal == "ma":
            return m_val > 0
        if signal == "combo":
            return r_val > 0 and m_val > 0
        raise ValueError(signal)

    eligible = membership_mask.loc[:, universe] & prices.notna() & ret_signal.notna()
    if signal in ("ma", "combo"):
        eligible = eligible & ma_signal.notna()
    weights = pd.DataFrame(0.0, index=raw_prices.index, columns=raw_prices.columns)
    ret_values = ret_signal.to_numpy()
    ma_values = ma_signal.to_numpy()
    elig_values = eligible.to_numpy()

    for row_i, date in enumerate(raw_prices.index):
        elig_cols = np.where(elig_values[row_i])[0]
        if elig_cols.size == 0:
            if index_floor is not None:
                weights.at[date, index_floor] = 1.0
            continue
        on_cols = [
            c
            for c in elig_cols
            if is_on(float(ret_values[row_i, c]), float(ma_values[row_i, c]))
        ]
        if not on_cols:
            if index_floor is not None:
                weights.at[date, index_floor] = 1.0
            continue
        # 最多 max_n 隻；多過就按 momentum 強度揀最強嗰批。
        if max_n > 0 and len(on_cols) > max_n:
            scores = ret_values[row_i, on_cols]
            on_cols = [on_cols[i] for i in np.argsort(scores)[::-1][:max_n]]
        k = len(on_cols)
        if index_floor is not None and max_n <= 0:
            # floor-mode：on 股票之間 equal weight，總曝險 100%。
            per = 1.0 / k
            for c in on_cols:
                weights.at[date, universe[c]] += per
        elif index_floor is not None and max_n > 0:
            # floor-mode + 固定 notional：每隻 1/max_n，空位用 floor 補。
            per = 1.0 / max_n
            for c in on_cols:
                weights.at[date, universe[c]] += per
            weights.at[date, index_floor] += (max_n - k) * per
        else:
            # cash-mode：每隻 1/max_n（無 floor 時 max_n 必須 > 0），空位 cash。
            per = 1.0 / (max_n if max_n > 0 else k)
            for c in on_cols:
                weights.at[date, universe[c]] += per
    # 修前視：信號推遲一日成交。
    weights = weights.shift(1).fillna(0.0)
    # 未上市嘅日子強制 0，避免 bt 揸 NaN。
    weights = weights.where(raw_prices.notna().reindex_like(weights).fillna(False), 0.0)
    return weights


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--prices", default="output/sp500_pit_prices.csv")
    parser.add_argument("--membership", default="output/sp500_pit_membership.csv")
    parser.add_argument("--mega-json", default="sp500_top_10_market_cap_2010_2026.json")
    parser.add_argument(
        "--universe", choices=["pit", "mega"], default="mega",
        help="pit = S&P 500 點-in-time 闊池；mega = 滯後市值 top-10。",
    )
    parser.add_argument(
        "--signal", choices=["tsmom", "ma", "combo"], default="tsmom",
        help="tsmom = lookback 回報 > 0；ma = 價格 > MA(ma_days)；combo = 兩者皆要。",
    )
    parser.add_argument("--lookback-days", type=int, default=126)
    parser.add_argument("--ma-days", type=int, default=200)
    parser.add_argument(
        "--max-n", type=int, default=0,
        help=">0 = 固定 notional（每隻 1/max_n）；0 = on 股票之間 equal weight（要配 floor）。",
    )
    parser.add_argument("--index-floor", default="QQQ")
    parser.add_argument("--benchmark", default="QQQ")
    parser.add_argument("--initial-cash", type=float, default=100_000)
    parser.add_argument("--cost-bps", type=float, default=15.0)
    parser.add_argument("--rebalance", choices=["daily", "weekly", "monthly"], default="weekly")
    parser.add_argument("--start", default="2010-01-01")
    parser.add_argument("--label", default="")
    args = parser.parse_args()

    raw_prices = load_prices(Path(args.prices))
    raw_prices = raw_prices.loc[args.start:]
    benchmark = args.benchmark
    index_floor = args.index_floor if args.index_floor else None
    for sym in [benchmark] + ([index_floor] if index_floor else []):
        if sym not in raw_prices.columns:
            parser.error(f"{sym} 唔喺價格數據入面。")

    if args.universe == "pit":
        membership = load_membership(Path(args.membership))
        member_symbols = [
            s for s in membership["symbol"].unique() if s in raw_prices.columns
        ]
        membership_mask = build_membership_mask(
            raw_prices.index, membership, raw_prices.columns
        )
    else:
        schedule = load_yearly_market_cap_universe(Path(args.mega_json))
        member_symbols = sorted(
            {s for syms in schedule.values() for s in syms if s in raw_prices.columns}
        )
        membership_mask = build_mega_membership_mask(
            raw_prices.index, schedule, raw_prices.columns
        )

    weights = build_tsmom_weights(
        raw_prices=raw_prices,
        membership_mask=membership_mask,
        member_symbols=member_symbols,
        lookback_days=args.lookback_days,
        ma_days=args.ma_days,
        signal=args.signal,
        max_n=args.max_n,
        index_floor=index_floor,
    )

    panel = raw_prices.ffill()
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

    floor_label = f", floor={index_floor}" if index_floor else ""
    sizing = f"max_n={args.max_n}" if args.max_n > 0 else "equal-weight-on"
    label = args.label or f"{args.universe}/{args.signal}/lb{args.lookback_days}/{sizing}{floor_label}"
    print(f"\n=== TSMOM [{label}] rebalance={args.rebalance} cost={args.cost_bps:.0f}bps ===")
    print(
        f"Period {common[0].date()} → {common[-1].date()}（{len(common)} 日，"
        f"{len(common)/TRADING_DAYS:.1f} 年）"
    )
    avg_exp = float(weights.sum(axis=1).mean())
    print(f"平均總曝險 {avg_exp*100:.0f}%｜universe 大細 {len(member_symbols)} 隻")

    summary = pd.DataFrame(
        [
            _stats_row(f"TSMOM [{label}]", strat),
            _stats_row(f"長揸 {benchmark}", bench),
        ]
    )
    for column in ["CAGR", "年化波幅", "Sharpe", "最大回撤", "Calmar", "總回報"]:
        summary[column] = summary[column].map(_fmt(column))
    print(format_bordered_table(summary))

    s_cagr, b_cagr = _cagr(strat) * 100, _cagr(bench) * 100
    s_sharpe, b_sharpe = _sharpe(strat), _sharpe(bench)
    s_dd, b_dd = _max_drawdown(strat) * 100, _max_drawdown(bench) * 100
    if s_cagr > b_cagr and s_sharpe > b_sharpe:
        print(f"✅ CAGR {s_cagr:.1f}% vs {b_cagr:.1f}%、Sharpe {s_sharpe:.2f} vs {b_sharpe:.2f} 雙贏。")
    elif s_cagr > b_cagr:
        print(f"⚠️ CAGR {s_cagr:.1f}% 贏 {b_cagr:.1f}%，但 Sharpe {s_sharpe:.2f} vs {b_sharpe:.2f}（多數靠多冒風險，DD {s_dd:.1f}% vs {b_dd:.1f}%）。")
    else:
        print(f"❌ CAGR {s_cagr:.1f}% 輸 {b_cagr:.1f}%（Sharpe {s_sharpe:.2f} vs {b_sharpe:.2f}，DD {s_dd:.1f}% vs {b_dd:.1f}%）。")
    print(f"result_cagr={s_cagr:.2f} result_sharpe={s_sharpe:.3f} result_dd={s_dd:.2f} "
          f"bench_cagr={b_cagr:.2f} bench_sharpe={b_sharpe:.3f} avg_exp={avg_exp:.3f}")


def _stats_row(name: str, returns: pd.Series) -> dict:
    dd = _max_drawdown(returns)
    return {
        "策略": name,
        "CAGR": _cagr(returns) * 100,
        "年化波幅": float(returns.std() * np.sqrt(TRADING_DAYS)) * 100,
        "Sharpe": _sharpe(returns),
        "最大回撤": dd * 100,
        "Calmar": (_cagr(returns) / abs(dd)) if dd < 0 else float("nan"),
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
    if column == "Calmar":
        return lambda v: f"{v:.2f}"
    return lambda v: f"{v:.1f}%"


if __name__ == "__main__":
    main()
