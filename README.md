# Algo Trading

每日美股 FUTU 模擬交易策略。依家 `main.py` 只做一件事：跑 126 日 momentum rotation，並且只會用 `TrdEnv.SIMULATE`，無真錢落單路徑。

部署 Futu OpenD Docker 可睇 [DEPLOY.md](DEPLOY.md)。

## 策略

交易 universe：

- `MSFT`, `GOOG`, `AVGO`, `TSM`, `AMZN`, `NVDA`

每日用 FUTU QFQ 日線計每隻股票 / ETF 嘅 126 日 momentum：

```text
momentum = 今日收市價 / 126 個交易日前收市價 - 1
```

揀 momentum 最高嗰隻：

```text
如果最高 momentum > 0:
  目標倉位 = 100% 該 symbol

如果最高 momentum <= 0:
  目標倉位 = 100% 現金
```

即係：只持有一隻最強勢標的；如果成個 universe 都轉弱，就清倉持現金。

## Dry Run

只計 signal 同交易計劃，唔落單：

```sh
uv run python main.py
```

輸出會包括：

- 當前 signal
- 所有 symbols 嘅 momentum score table
- 需要買 / 賣嘅模擬交易計劃

## Backtest

用 Yahoo adjusted close data 跑同一條公式：

```sh
uv run python scripts/backtest_momentum_rotation.py --start 2010-01-01 --end 2026-06-14 --output-csv output/backtest_trades.csv
```

預設會輸出交易紀錄 CSV：

```text
backtest_trades.csv
```

想指定 output path：

```sh
uv run python scripts/backtest_momentum_rotation.py \
  --start 2010-01-01 \
  --end 2026-06-14 \
  --output-csv output/backtest_trades.csv
```

可以改 benchmark，例如同 strong hold `MSFT` 比：

```sh
uv run python scripts/backtest_momentum_rotation.py --benchmark MSFT --start 2010-01-01 --end 2026-06-14
```

或者同 strong hold `NVDA` 比：

```sh
uv run python scripts/backtest_momentum_rotation.py --benchmark NVDA --start 2010-01-01 --end 2026-06-14
```

## 模擬落單

透過 Futu OpenD 落模擬盤 order：

```sh
uv run python main.py --execute
```

取消 bot journal 入面記錄嘅 open orders，再重新驗證同落模擬單：

```sh
uv run python main.py --execute --cancel-open-orders
```

## 安全制

- `STOP_TRADING` file 存在時會停止落單。
- `trade_journal.json` 會記錄已提交 order。
- 有 open orders 時會阻止新 order。
- `--cancel-open-orders` 只會取消 bot journal 記錄過嘅 open orders。
- 會檢查每日 order 數量、每日 notional、單筆 order notional。
- 只用 `TrdEnv.SIMULATE`；無真錢交易 path。

## 常用參數

```sh
uv run python main.py \
  --lookback-days 126 \
  --max-daily-orders 20 \
  --max-daily-notional 1000000 \
  --max-single-order-notional 1000000
```
