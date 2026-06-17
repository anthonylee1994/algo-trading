"""Live execution script for the QQQ/SMH static blend (FINDINGS §11[D]).

Mirror of scripts/simulate_momentum_rotation.py but for a static equal-weight
sector blend (default 50/50 QQQ + SMH). Monthly rebalance with 5pp
threshold band, signal shifted 1 day via close price, no leverage.

Reuses:
    algo_trading.futu_trader          — place_orders, get_positions, etc.
    algo_trading.risk_manager         — validate_plan, record_order_results
    algo_trading.rebalance_state      — should_rebalance_today, load/save state
    algo_trading.sector_blend         — select_blend_targets, build_blend_rebal_plan

Usage:
    .venv/bin/python scripts/simulate_sector_blend.py --dry-run
    .venv/bin/python scripts/simulate_sector_blend.py --execute
    .venv/bin/python scripts/simulate_sector_blend.py --symbols QQQ SOXX --target-weight 0.5

First run (no positions yet): use --force-rebalance so it opens the basket
even outside the monthly gate. Subsequent runs respect the cadence.
"""
from __future__ import annotations

import argparse
from datetime import date
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from futu import OrderType, SysConfig, TrdEnv

from algo_trading.futu_trader import (
    futu_us_code,
    get_latest_prices,
    get_positions,
    place_orders,
)
from algo_trading.rebalance_state import (
    load_strategy_state,
    save_rebalance_state,
    should_rebalance_today,
)
from algo_trading.risk_manager import (
    cancel_open_orders,
    get_account_summary,
    record_cancel_results,
    record_order_results,
    validate_plan,
)
from algo_trading.sector_blend import (
    DEFAULT_BLEND_SYMBOLS,
    build_blend_rebal_plan,
    format_blend_status,
    select_blend_targets,
)


STATE_PATH = Path("sector_blend_state.json")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--symbols",
        nargs="+",
        default=None,
        help="blend universe（默認 QQQ SMH；可改 QQQ SOXX）",
    )
    parser.add_argument(
        "--rebal-band",
        type=float,
        default=0.05,
        help="no-trade band，預設 5pp。FINDINGS §11[D3] sweep 確認 5-50bps cost 對 blend 完全 robust。",
    )
    parser.add_argument(
        "--rebalance",
        choices=["daily", "weekly", "monthly"],
        default="monthly",
        help="執行 cadence；預設 monthly。",
    )
    parser.add_argument(
        "--state-path",
        default=str(STATE_PATH),
        help="記錄 monthly/weekly rebalance 嘅 state file。",
    )
    parser.add_argument(
        "--force-rebalance",
        action="store_true",
        help="無視 cadence gate，今次強制 rebalance（首次上倉用）。",
    )
    parser.add_argument("--futu-host", default="127.0.0.1")
    parser.add_argument("--futu-port", type=int, default=11111)
    parser.add_argument("--futu-rsa-file", default=None)
    parser.add_argument("--min-trade-notional", type=float, default=100)
    parser.add_argument("--max-daily-orders", type=int, default=10)
    parser.add_argument("--max-daily-notional", type=float, default=1_000_000)
    parser.add_argument("--max-single-order-notional", type=float, default=1_000_000)
    parser.add_argument("--cancel-open-orders", action="store_true")
    parser.add_argument(
        "--order-type",
        choices=[OrderType.MARKET, OrderType.NORMAL],
        default=OrderType.NORMAL,
        help="NORMAL = limit 落單（item.price 設為 close * 1.003 buy / close sell）；"
        "MARKET = market 落單（item.price 忽略）。預設 NORMAL。",
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        help="落模擬盤 order；唔加就係 dry-run。",
    )
    args = parser.parse_args()

    if args.futu_rsa_file:
        SysConfig.enable_proto_encrypt(True)
        SysConfig.set_init_rsa_file(args.futu_rsa_file)

    symbols = list(dict.fromkeys(args.symbols or DEFAULT_BLEND_SYMBOLS))
    trade_codes = [futu_us_code(symbol) for symbol in symbols]
    trd_env = TrdEnv.SIMULATE

    targets = select_blend_targets(symbols)
    prices = get_latest_prices(
        host=args.futu_host, port=args.futu_port, codes=trade_codes
    )
    account = get_account_summary(
        host=args.futu_host, port=args.futu_port, trd_env=trd_env
    )
    positions = get_positions(
        host=args.futu_host, port=args.futu_port, trd_env=trd_env
    )

    print({"模式": "模擬盤", "universe": symbols, "帳戶": account})

    print("\n當前 blend 狀態：")
    print(format_blend_status(targets, prices, positions, account, rebal_band=args.rebal_band))

    state = load_strategy_state(Path(args.state_path))
    rebalance_due = args.force_rebalance or should_rebalance_today(
        rebalance=args.rebalance, state=state
    )

    if not rebalance_due:
        print(
            f"\n今日唔係 {args.rebalance} rebalance day，無 plan。"
            "加 --force-rebalance 強制執行。"
        )
        return

    plan = build_blend_rebal_plan(
        targets=targets,
        prices=prices,
        positions=positions,
        account=account,
        rebal_band=args.rebal_band,
        min_trade_notional=args.min_trade_notional,
    )

    if not plan:
        print(
            f"\n所有 leg 喺 ±{args.rebal_band:.0%} band 內，無需要 rebalance。"
        )
        if args.execute:
            save_rebalance_state(
                path=Path(args.state_path), rebalance=args.rebalance
            )
        return

    print(f"\nRebalance plan（{len(plan)} 個 order）：")
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
        print("\n只係 dry-run。加 --execute 先會落模擬盤 order。")
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
    save_rebalance_state(path=Path(args.state_path), rebalance=args.rebalance)
    for result in results:
        print(result)


if __name__ == "__main__":
    main()
