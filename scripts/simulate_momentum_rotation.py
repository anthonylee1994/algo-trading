from __future__ import annotations

import argparse
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from futu import OrderType, SysConfig, TrdEnv

from algo_trading.futu_trader import (
    futu_us_code,
    get_latest_prices,
    get_positions,
    get_price_history,
    place_orders,
)
from algo_trading.momentum_rotation import (
    DEFAULT_SYMBOLS,
    build_rotation_plan,
    format_momentum_score_table,
    momentum_score_table,
    select_rotation_signal,
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
    parser.add_argument("--symbols", nargs="+", default=DEFAULT_SYMBOLS)
    parser.add_argument("--lookback-days", type=int, default=126)
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

    trd_env = TrdEnv.SIMULATE
    codes = [futu_us_code(symbol) for symbol in args.symbols]
    histories_by_code = get_price_history(
        host=args.futu_host,
        port=args.futu_port,
        codes=codes,
        max_count=args.lookback_days + 2,
    )
    histories = {
        code.removeprefix("US."): history
        for code, history in histories_by_code.items()
    }
    signal = select_rotation_signal(
        histories=histories,
        lookback_days=args.lookback_days,
    )
    score_table = momentum_score_table(
        histories=histories,
        lookback_days=args.lookback_days,
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
    prices = get_latest_prices(
        host=args.futu_host,
        port=args.futu_port,
        codes=codes,
    )
    plan = build_rotation_plan(
        signal=signal,
        prices=prices,
        positions=positions,
        available_cash=float(account["available_cash"]),
        symbols=args.symbols,
        min_trade_notional=args.min_trade_notional,
    )

    print(
        {
            "模式": "模擬盤",
            "訊號": signal.ticker or "現金",
            "momentum": signal.momentum,
            "原因": signal.reason,
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


if __name__ == "__main__":
    main()
