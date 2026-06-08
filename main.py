import argparse
import os

from algo_trading.finviz_screener import fetch_candidates, summarize_candidates
from algo_trading.futu_trader import build_strategy_plan, place_orders
from algo_trading.risk_manager import (
    cancel_open_orders,
    get_account_summary,
    record_cancel_results,
    record_order_results,
    validate_plan,
)
from futu import OrderType, TrdEnv


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument("--cash", type=float, default=10_000)
    parser.add_argument("--futu-host", default="127.0.0.1")
    parser.add_argument("--futu-port", type=int, default=11111)
    parser.add_argument("--plan", action="store_true")
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--auto", action="store_true")
    parser.add_argument("--cancel-open-orders", action="store_true")
    parser.add_argument("--cancel-all-open-orders", action="store_true")
    parser.add_argument("--real", action="store_true")
    parser.add_argument("--max-daily-orders", type=int, default=100)
    parser.add_argument("--max-daily-notional", type=float, default=1_000_000)
    parser.add_argument("--max-single-order-notional", type=float, default=1_000_000)
    parser.add_argument("--target-weight", type=float, default=None)
    parser.add_argument("--rebalance-threshold", type=float, default=0.03)
    parser.add_argument("--max-position-weight", type=float, default=0.12)
    parser.add_argument("--max-gross-exposure", type=float, default=0.8)
    parser.add_argument("--sell-non-universe", action="store_true")
    parser.add_argument("--password", default=os.getenv("FUTU_TRADE_PASSWORD"))
    parser.add_argument("--password-md5", default=os.getenv("FUTU_TRADE_PASSWORD_MD5"))
    parser.add_argument(
        "--order-type",
        choices=[OrderType.MARKET, OrderType.NORMAL],
        default=OrderType.NORMAL,
    )
    args = parser.parse_args()

    candidates = fetch_candidates()
    candidates = candidates.head(args.limit)
    summary = summarize_candidates(candidates)

    for candidate in summary:
        print(candidate)

    if not (args.plan or args.execute or args.auto):
        print("Screener only. Add --plan for a Futu-backed dry-run strategy plan.")
        return

    trd_env = TrdEnv.REAL if args.real else TrdEnv.SIMULATE
    account_summary = get_account_summary(
        host=args.futu_host,
        port=args.futu_port,
        trd_env=trd_env,
    )

    plan = build_strategy_plan(
        candidates=candidates,
        total_cash=args.cash,
        host=args.futu_host,
        port=args.futu_port,
        trd_env=trd_env,
        account_summary=account_summary,
        target_weight=args.target_weight,
        rebalance_threshold=args.rebalance_threshold,
        max_position_weight=args.max_position_weight,
        max_gross_exposure=args.max_gross_exposure,
        sell_non_universe=args.sell_non_universe,
    )

    print({"account": account_summary})
    for item in plan:
        print(
            {
                "action": item.action,
                "code": item.code,
                "price": item.price,
                "quantity": item.quantity,
                "notional": item.notional,
                "reason": item.reason,
            }
        )

    if args.plan and not (args.execute or args.auto):
        print(
            "DRY RUN only. Add --execute to place orders, or --auto for guarded automation."
        )
        return

    if not plan:
        raise RuntimeError("No trade plan generated. No orders placed.")

    if trd_env == TrdEnv.REAL and not (args.password or args.password_md5):
        raise RuntimeError("Real trade needs --password or FUTU_TRADE_PASSWORD.")

    if args.cancel_open_orders:
        cancel_results = cancel_open_orders(
            host=args.futu_host,
            port=args.futu_port,
            trd_env=trd_env,
            only_journal_orders=not args.cancel_all_open_orders,
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
        raise RuntimeError("No orders passed the risk guard. No orders placed.")

    print(
        {
            "mode": "EXECUTE",
            "trd_env": trd_env,
            "order_type": args.order_type,
            "orders": len(guarded_plan),
        }
    )

    results = place_orders(
        plan=guarded_plan,
        host=args.futu_host,
        port=args.futu_port,
        trd_env=trd_env,
        password=args.password,
        password_md5=args.password_md5,
        order_type=args.order_type,
    )
    record_order_results(guarded_plan, results)
    for result in results:
        print(result)


if __name__ == "__main__":
    main()
