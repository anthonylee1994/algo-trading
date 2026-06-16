from __future__ import annotations

import argparse
from pathlib import Path
import sys

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from futu import OrderType, SysConfig, TrdEnv

from algo_trading.futu_trader import (
    futu_us_code,
    get_latest_prices,
    get_positions,
    get_price_history,
    place_orders,
)
from algo_trading.market_cap_universe import (
    DEFAULT_MARKET_CAP_UNIVERSE_PATH,
    latest_schedule_symbols,
    latest_universe_symbols,
    load_market_cap_universe,
)
from algo_trading.momentum_rotation import (
    build_equal_weight_rotation_plan,
    format_momentum_score_table,
    momentum_score_table,
    select_rotation_targets,
)
from algo_trading.risk_manager import (
    cancel_open_orders,
    get_account_summary,
    record_cancel_results,
    record_order_results,
    validate_plan,
)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbols", nargs="+", default=None)
    parser.add_argument(
        "--universe-json",
        default=str(DEFAULT_MARKET_CAP_UNIVERSE_PATH),
        help="最新 S&P 500 市值 Top 10 universe JSON；如指定 --symbols 就會改用固定 universe。",
    )
    parser.add_argument("--lookback-days", type=int, default=126)
    parser.add_argument("--top-n", type=int, default=2)
    parser.add_argument(
        "--index-floor",
        default=None,
        help="正動量股票唔夠 top_n 隻時，空倉位用呢個 symbol（如 QQQ）補返而唔係揸現金。",
    )
    parser.add_argument(
        "--leverage",
        type=float,
        default=1.0,
        help="固定目標總曝險倍數（例 1.15）。>1 需要孖展戶口。如設 --vol-target 會被取代。",
    )
    parser.add_argument(
        "--vol-target",
        type=float,
        default=None,
        help="啟用波動率目標（例 0.26）：曝險 = 目標波幅 / base portfolio 實際波幅，封頂 --max-leverage。覆蓋 --leverage。",
    )
    parser.add_argument(
        "--vol-window",
        type=int,
        default=40,
        help="vol-target 計 realized volatility 用幾多個交易日（預設 40）。",
    )
    parser.add_argument(
        "--max-leverage",
        type=float,
        default=2.0,
        help="vol-target 曝險上限（預設 2.0 = 2x）。",
    )
    parser.add_argument("--futu-host", default="127.0.0.1")
    parser.add_argument("--futu-port", type=int, default=11111)
    parser.add_argument("--futu-rsa-file", default=None)
    parser.add_argument("--min-trade-notional", type=float, default=100)
    parser.add_argument("--max-daily-orders", type=int, default=20)
    parser.add_argument("--max-daily-notional", type=float, default=1_000_000)
    parser.add_argument("--max-single-order-notional", type=float, default=1_000_000)
    parser.add_argument("--cancel-open-orders", action="store_true")
    parser.add_argument(
        "--order-type",
        choices=[OrderType.MARKET, OrderType.NORMAL],
        default=OrderType.MARKET,
    )
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()

    if args.futu_rsa_file:
        SysConfig.enable_proto_encrypt(True)
        SysConfig.set_init_rsa_file(args.futu_rsa_file)

    if args.symbols:
        strategy_symbols = list(dict.fromkeys(args.symbols))
        universe_label = "固定 universe"
    else:
        kind, loaded = load_market_cap_universe(Path(args.universe_json))
        # 實盤用最新「已知」快照即可——過去數據，無前視問題。
        if kind == "annual":
            latest_label = max(loaded)
            strategy_symbols = latest_universe_symbols([], loaded)
        else:
            latest_label = loaded[-1][0].date().isoformat()
            strategy_symbols = latest_schedule_symbols([], loaded)
        universe_label = f"{latest_label} 市值 Top 10（{args.universe_json}）"

    trd_env = TrdEnv.SIMULATE
    # 動量候選 = universe；index-floor（如 QQQ）只係空倉位補位，唔計動量但要有價同倉位。
    candidate_symbols = list(strategy_symbols)
    trade_symbols = list(strategy_symbols)
    if args.index_floor and args.index_floor not in trade_symbols:
        trade_symbols.append(args.index_floor)
    candidate_codes = [futu_us_code(symbol) for symbol in candidate_symbols]
    trade_codes = [futu_us_code(symbol) for symbol in trade_symbols]
    histories_by_code = get_price_history(
        host=args.futu_host,
        port=args.futu_port,
        codes=trade_codes,  # 含 index-floor，vol-target 計 base portfolio 波幅要用
        max_count=args.lookback_days + 2,
    )
    histories_all = {
        code.removeprefix("US."): history
        for code, history in histories_by_code.items()
    }
    # 動量只睇 candidate（index-floor 唔計動量）。
    histories = {
        symbol: histories_all[symbol]
        for symbol in candidate_symbols
        if symbol in histories_all
    }
    targets = select_rotation_targets(
        histories=histories,
        lookback_days=args.lookback_days,
        top_n=args.top_n,
    )
    prices = get_latest_prices(
        host=args.futu_host,
        port=args.futu_port,
        codes=trade_codes,
    )
    score_table = momentum_score_table(
        histories=histories,
        lookback_days=args.lookback_days,
        latest_prices=prices,
    )
    account = get_account_summary(
        host=args.futu_host,
        port=args.futu_port,
        trd_env=trd_env,
    )
    positions = get_positions(
        host=args.futu_host,
        port=args.futu_port,
        trd_env=trd_env,
    )
    # vol-target：用 base portfolio 近 vol_window 日嘅 realized volatility 動態定槓桿。
    leverage_eff = args.leverage
    realized_vol = None
    if args.vol_target:
        base_weights = base_portfolio_weights(targets, args.top_n, args.index_floor)
        realized_vol = base_portfolio_realized_vol(
            histories_all, base_weights, args.vol_window
        )
        if realized_vol and realized_vol > 0:
            leverage_eff = min(args.vol_target / realized_vol, args.max_leverage)

    plan = build_equal_weight_rotation_plan(
        targets=targets,
        prices=prices,
        positions=positions,
        available_cash=float(account["available_cash"]),
        symbols=candidate_symbols,
        min_trade_notional=args.min_trade_notional,
        top_n=args.top_n,
        index_floor=args.index_floor,
        leverage=leverage_eff,
    )

    floor_note = f"，空位用 {args.index_floor} 托底" if args.index_floor else ""
    if args.vol_target and realized_vol:
        leverage_note = (
            f"，vol-target {args.vol_target:.0%}：實際波幅 {realized_vol:.0%}"
            f" → 曝險 ×{leverage_eff:.2f}（封頂 {args.max_leverage:g}）"
        )
    elif leverage_eff != 1.0:
        leverage_note = f"，槓桿 ×{leverage_eff:g}"
    else:
        leverage_note = ""
    print(
        {
            "模式": "模擬盤",
            "訊號": ", ".join(str(target.ticker) for target in targets) or "現金",
            "momentum": [target.momentum for target in targets],
            "原因": (
                f"Top {args.top_n} 等權 {args.lookback_days} 日 momentum"
                f"{floor_note}{leverage_note}"
            ),
            "交易範圍": universe_label,
            "symbols": strategy_symbols,
            "帳戶": account,
        }
    )
    print("Momentum 分數：")
    print(format_momentum_score_table(score_table))
    for item in plan:
        print(
            {
                "動作": item.action,
                "代號": item.code,
                "價格": item.price,
                "數量": item.quantity,
                "金額": item.notional,
                "原因": item.reason,
            }
        )

    if not args.execute:
        print("只係 dry-run。加 --execute 先會落模擬盤 order。")
        return

    if not plan:
        print("唔需要再平衡，無落任何模擬盤 order。")
        return

    if args.cancel_open_orders:
        cancel_results = cancel_open_orders(
            host=args.futu_host,
            port=args.futu_port,
            trd_env=trd_env,
            only_journal_orders=True,
        )
        record_cancel_results(cancel_results)
        for result in cancel_results:
            print(result)

    guarded_plan = validate_plan(
        plan=plan,
        host=args.futu_host,
        port=args.futu_port,
        trd_env=trd_env,
        max_daily_orders=args.max_daily_orders,
        max_daily_notional=args.max_daily_notional,
        max_single_order_notional=args.max_single_order_notional,
    )
    if not guarded_plan:
        raise RuntimeError("無 order 通過風控，無落單。")

    results = place_orders(
        plan=guarded_plan,
        host=args.futu_host,
        port=args.futu_port,
        trd_env=trd_env,
        order_type=args.order_type,
    )
    record_order_results(guarded_plan, results)
    for result in results:
        print(result)


def base_portfolio_weights(
    targets: list,
    top_n: int,
    index_floor: str | None,
) -> dict[str, float]:
    """重建 base portfolio（未槓桿）權重，同 build_equal_weight_rotation_plan 一致。"""
    weights: dict[str, float] = {}
    if index_floor and top_n:
        for target in targets:
            weights[str(target.ticker)] = weights.get(str(target.ticker), 0.0) + 1.0 / top_n
        empty = max(top_n - len(targets), 0)
        if empty > 0:
            weights[index_floor] = weights.get(index_floor, 0.0) + empty / top_n
    elif targets:
        per = 1.0 / len(targets)
        for target in targets:
            weights[str(target.ticker)] = per
    return weights


def base_portfolio_realized_vol(
    histories: dict,
    weights: dict[str, float],
    window: int,
    trading_days: int = 252,
) -> float | None:
    """用持倉成分嘅近 window 日加權回報，計 base portfolio 年化 realized volatility。"""
    if not weights:
        return None
    closes: dict[str, pd.Series] = {}
    for symbol in weights:
        history = histories.get(symbol)
        if history is None or "close" not in history:
            return None
        closes[symbol] = history["close"].astype(float).reset_index(drop=True)
    frame = pd.DataFrame(closes).dropna()
    if len(frame) < 6:
        return None
    window = min(window, len(frame) - 1)
    returns = frame.pct_change().dropna().tail(window)
    weight_series = pd.Series(weights, dtype=float)
    weight_series = weight_series / weight_series.sum()
    portfolio = (returns[list(weight_series.index)] * weight_series).sum(axis=1)
    std = float(portfolio.std())
    if std <= 0:
        return None
    return std * (trading_days**0.5)


if __name__ == "__main__":
    main()
