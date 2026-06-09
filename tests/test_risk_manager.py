from datetime import date

from algo_trading.risk_manager import _today_risk_orders


def test_today_risk_orders_excludes_cancel_records() -> None:
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

    assert _today_risk_orders(journal) == [journal["orders"][0]]
