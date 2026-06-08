# Algo Trading

Daily US stock strategy based on `us-stock.md`.

The first filter layer uses `finvizfinance` instead of hard-coded valuation
targets. It runs this Finviz screen:

- <https://finviz.com/screener?v=161&f=cap_midover,fa_eps5years_o20,fa_roe_o15&ft=4&o=-marketcap>
- Market cap over $2bln, 5-year EPS growth over 20%, ROE over 15%, sorted by market cap descending.

Run:

```sh
uv run python main.py
```

Show only the Finviz screener results without calling Futu:

```sh
uv run python main.py --limit 10
```

Dry-run the strategy plan for the first 10 filtered US stocks using Futu OpenD
quotes, history, and positions:

```sh
uv run python main.py --limit 10 --cash 10000 --plan
```

The strategy buys only when the stock and SPY are in uptrends, and sells current
positions on an 8% hard stop or 50-day SMA break. Position sizing uses Futu
account assets, available cash, target weight, rebalance threshold, max position
weight, and max gross exposure.

Place simulated orders:

```sh
uv run python main.py --cash 10000 --execute
```

Run guarded automation:

```sh
uv run python main.py --cash 100000 --auto --cancel-open-orders --max-gross-exposure 0.8 --max-position-weight 0.12 --rebalance-threshold 0.03
```

Safety controls:

- `STOP_TRADING` file stops all execution when present.
- `trade_journal.json` records submitted orders.
- Open orders block new orders.
- `--cancel-open-orders` cancels bot journal open orders before revalidating and placing a new plan.
- `--cancel-all-open-orders` also cancels manual open orders when used with `--cancel-open-orders`.
- Daily order count, daily notional, and single-order notional limits are checked before execution.
- `--target-weight` overrides equal-weight sizing; otherwise target weight is `1 / limit`.
- `--max-gross-exposure` caps total target stock exposure.
- `--max-position-weight` caps each position.
- `--rebalance-threshold` avoids tiny rebalance orders.
- `--sell-non-universe` liquidates holdings that are no longer in the filtered universe; it is off by default.

Place real market buy orders:

```sh
FUTU_TRADE_PASSWORD=... uv run python main.py --cash 10000 --execute --real
```
