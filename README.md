# Algo Trading

每日美股 FUTU 模擬交易策略。依家 `main.py` 只做一件事：跑 126 日 momentum rotation，並且只會用 `TrdEnv.SIMULATE`，無真錢落單路徑。

部署 Futu OpenD Docker 可睇 [DEPLOY.md](DEPLOY.md)。

## 策略

交易 universe：

- 模擬盤 dry-run / execute：預設用 `sp500_top_10_market_cap_2010_2026.json`
  入面最新年份嘅 S&P 500 市值 Top 10。
- Backtest：預設逐年切換，用每一年 S&P 500 市值 Top 10。
- 想手動固定 universe，可以傳 `--symbols AAPL MSFT NVDA ...`。

每日用 FUTU QFQ 日線計每隻股票 / ETF 嘅 126 日 momentum：

```text
momentum = 今日收市價 / 126 個交易日前收市價 - 1
```

FUTU 模擬交易預設揀 momentum 最高嗰兩隻做等權：

```text
如果有 2 隻或以上 momentum > 0:
  目標倉位 = 50% 第一名 + 50% 第二名

如果只有 1 隻 momentum > 0:
  目標倉位 = 100% 該 symbol

如果全部 momentum <= 0:
  目標倉位 = 100% 現金
```

即係：用 Top 2 分散單一股票風險；如果成個 universe 都轉弱，就清倉持現金。

## Dry Run

只計 signal 同交易計劃，唔落單：

```sh
uv run python main.py
```

預設會用最新年份市值 Top 10；想手動指定交易範圍：

```sh
uv run python main.py --symbols AAPL MSFT NVDA GOOGL AMZN META AVGO TSLA LLY WMT
```

想改返 Top 1 或試 Top 3：

```sh
uv run python main.py --top-n 1
uv run python main.py --top-n 3
```

輸出會包括：

- 當前 signal
- 所有 symbols 嘅 momentum score table
- 需要買 / 賣嘅模擬交易計劃

## Backtest

用 Yahoo adjusted close data + `bt` 跑同一條 Top 2 等權公式。Backtest 預設會讀
`sp500_top_10_market_cap_2010_2026.json`，每年只喺該年 S&P 500 市值最高嗰
10 隻入面揀 momentum 最高嘅 `--top-n` 隻做交易：

```sh
uv run python scripts/backtest_momentum_rotation.py --start 2010-01-01 --end 2026-06-14 --output-csv output/backtest_trades.csv
```

### 方法學（睇數字前必讀）

- **無前視偏差**：用 `close[t]` 計嘅 momentum 信號會推遲一個交易日先成交（`weights.shift(1)`），唔會「用收市價計、又用同一個收市價成交」。
- **有交易成本**：每次成交收 `--cost-bps`（預設 `15` = 0.15%，佣金 + 滑點）。設 `--cost-bps 0` 先係舊版嘅「零成本」幻覺。
- **重新平衡頻率**：`--rebalance {daily,weekly,monthly}`，預設 `monthly`。Momentum rotation 高換手，daily rebalance 喺真錢交易會被成本食凸。
- **動態 universe**：預設每個年份用該年 S&P 500 市值 Top 10。即係 2010 只會喺 2010 Top 10 入面揀，2026 就用 2026 snapshot。想返去舊式固定名單，可以傳 `--symbols AAPL MSFT NVDA ...`。
- **倖存者偏差**：Yahoo 只有現存上市股票，已退市嘅唔會出現；啟動時會印出每隻 symbol 真實數據起始日，遲上市嘅會標 ⚠️。早年 universe 細咗 → 回報會偏高，自己打個折扣。
- **過度擬合檢查**：用 `--sweep-lookback 63 126 252 504` 跑多個 lookback，睇 CAGR／回撤對參數有幾敏感。差距大 = 揀中嘅參數靠彩數。

```sh
# 例：monthly rebalance、0.15% 成本、順便做 lookback 敏感度分析
uv run python scripts/backtest_momentum_rotation.py \
  --start 2010-01-01 --end 2026-06-14 \
  --rebalance monthly --cost-bps 15 \
  --sweep-lookback 63 126 252 504
```

預設會輸出交易紀錄 CSV：

```text
output/backtest_trades.csv
```

同時會用 `bt` 輸出 equity curve 圖：

```text
output/backtest_chart.png
```

想指定 output path：

```sh
uv run python scripts/backtest_momentum_rotation.py \
  --start 2010-01-01 \
  --end 2026-06-14 \
  --output-csv output/backtest_trades.csv \
  --plot-path output/backtest_chart.png
```

想改返 Top 1 或試 Top 3：

```sh
uv run python scripts/backtest_momentum_rotation.py \
  --top-n 1 \
  --start 2010-01-01 \
  --end 2026-06-14 \
  --output-csv output/backtest_trades_top1.csv \
  --plot-path output/backtest_chart_top1.png

uv run python scripts/backtest_momentum_rotation.py \
  --top-n 3 \
  --start 2010-01-01 \
  --end 2026-06-14 \
  --output-csv output/backtest_trades_top3.csv \
  --plot-path output/backtest_chart_top3.png
```

可以改 benchmark，例如同 strong hold `MSFT` 比：

```sh
uv run python scripts/backtest_momentum_rotation.py --benchmark MSFT --start 2010-01-01 --end 2026-06-14
```

或者同 strong hold `NVDA` 比：

```sh
uv run python scripts/backtest_momentum_rotation.py --benchmark NVDA --start 2010-01-01 --end 2026-06-14
```

## TradingView Signal

Pine Script signal 版喺：

```text
pine/momentum_rotation_signal.pine
```

TradingView 可以用佢顯示 126 日 momentum rotation signal 同 alert。不過 Pine Script 做唔到真正 multi-asset rotation execution backtest；完整回測仍然用 Python script。

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
