# Algo Trading

Daily US simulated momentum rotation strategy.

See [DEPLOY.md](DEPLOY.md) for server deployment with Futu OpenD Docker.

The simulated momentum rotation strategy uses this universe:

- `MSFT`, `GOOG`, `AVGO`, `TSM`, `AMZN`, `NVDA`, `SMH`, `QQQ`, `QTUM`, `ROBO`,
  `XLV`, `SHLD`, `TAN`, `IGV`

It calculates 126-day momentum for each symbol using Futu daily adjusted
history. If the strongest symbol has positive momentum, the strategy targets
100% simulated exposure to that symbol. If the strongest momentum is zero or
negative, it sells the strategy universe and holds cash.

Dry-run the simulated rotation plan:

```sh
uv run python main.py
```

Place simulated orders through Futu OpenD:

```sh
uv run python main.py --execute
```

Safety controls:

- `STOP_TRADING` file stops all execution when present.
- `trade_journal.json` records submitted orders.
- Open orders block new orders.
- `--cancel-open-orders` cancels bot journal open orders before revalidating and placing a new plan.
- Daily order count, daily notional, and single-order notional limits are checked before execution.
- Only `TrdEnv.SIMULATE` is used; there is no real-money execution path.
