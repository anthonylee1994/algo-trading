from datetime import date

from algo_trading.futu_trader import TradePlanItem
from algo_trading import risk_manager
from algo_trading.risk_manager import _today_risk_orders


def test_today_risk_orders_excludes_cancelled_trade_orders() -> None:
    today = date.today().isoformat()
    journal = {
        "orders": [
            {
                "action": "BUY",
                "created_at": f"{today}T10:00:00+00:00",
                "notional": 100,
                "result": {
                    "result": [
                        {
                            "order_id": "1",
                        }
                    ],
                },
            },
            {
                "action": "CANCEL",
                "created_at": f"{today}T10:01:00+00:00",
                "order_id": "1",
                "result": {
                    "order_id": "1",
                },
            },
            {
                "action": "BUY",
                "created_at": f"{today}T10:02:00+00:00",
                "notional": 300,
                "result": {
                    "result": [
                        {
                            "order_id": "3",
                        }
                    ],
                },
            },
            {
                "action": "BUY",
                "created_at": "2000-01-01T10:00:00+00:00",
                "notional": 200,
                "result": {
                    "result": [
                        {
                            "order_id": "2",
                        }
                    ],
                },
            },
        ],
    }

    assert _today_risk_orders(journal) == [journal["orders"][2]]


def test_validate_plan_counts_sell_proceeds_before_buys(monkeypatch) -> None:
    monkeypatch.setattr(risk_manager, "check_kill_switch", lambda: None)
    monkeypatch.setattr(risk_manager, "get_open_orders", lambda **_: [])
    monkeypatch.setattr(risk_manager, "load_journal", lambda: {"orders": []})
    monkeypatch.setattr(risk_manager, "get_available_cash", lambda **_: 100)
    plan = [
        TradePlanItem(
            action="SELL",
            ticker="MSFT",
            code="US.MSFT",
            company="",
            price=50,
            quantity=10,
            notional=500,
            reason="非 Top 2 目標持倉",
        ),
        TradePlanItem(
            action="BUY",
            ticker="NVDA",
            code="US.NVDA",
            company="",
            price=100,
            quantity=3,
            notional=300,
            reason="Top 2 等權",
        ),
        TradePlanItem(
            action="BUY",
            ticker="TSM",
            code="US.TSM",
            company="",
            price=100,
            quantity=3,
            notional=300,
            reason="Top 2 等權",
        ),
    ]

    validated = risk_manager.validate_plan(
        plan=plan,
        host="127.0.0.1",
        port=11111,
        trd_env="SIMULATE",
        max_daily_orders=20,
        max_daily_notional=1_000_000,
        max_single_order_notional=1_000_000,
    )

    assert validated == plan
