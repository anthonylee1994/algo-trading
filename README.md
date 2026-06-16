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

FUTU 模擬交易預設揀 momentum 最高嗰兩隻做等權；目前建議執行版會用 `--top-n 5 --index-floor QQQ --vol-target 0.30 --max-leverage 2`：

```text
如果有 2 隻或以上 momentum > 0:
  目標倉位 = 50% 第一名 + 50% 第二名

如果只有 1 隻 momentum > 0:
  目標倉位 = 100% 該 symbol

如果全部 momentum <= 0:
  目標倉位 = 100% 現金
```

即係：預設 Top 2 係簡單版；而家跑贏 QQQ 嘅主策略係 Top 5 分散持倉，正動量股票唔夠 5 隻時用 QQQ 補位，再用 vol-target 調整總曝險。

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
- 如啟用 `--vol-target`：raw target exposure、cap 後 target、現有策略 gross exposure、band 後 effective exposure，同今日係 `hold` 定 `rebalance`

## Execute

落 Futu 模擬盤 order（`TrdEnv.SIMULATE`）：

```sh
uv run python main.py \
  --top-n 5 \
  --index-floor QQQ \
  --vol-target 0.30 \
  --vol-window 40 \
  --max-leverage 2 \
  --rebal-band 0.05 \
  --rebalance monthly \
  --state-path strategy_state.json \
  --min-trade-notional 100 \
  --max-daily-orders 20 \
  --max-daily-notional 1000000 \
  --max-single-order-notional 1000000 \
  --cancel-open-orders \
  --execute
```

## Backtest

用 Yahoo adjusted close data + `bt` 跑同一條 momentum rotation 公式。Backtest 預設會讀
`sp500_top_10_market_cap_2010_2026.json`，每年只喺該年 S&P 500 市值最高嗰
10 隻入面揀 momentum 最高嘅 `--top-n` 隻做交易：

```sh
uv run python scripts/backtest_momentum_rotation.py --start 2010-01-01 --end 2026-06-14 --output-csv output/backtest_trades.csv
```

### 方法學（睇數字前必讀）

- **無前視偏差**：用 `close[t]` 計嘅 momentum 信號會推遲一個交易日先成交（`weights.shift(1)`），唔會「用收市價計、又用同一個收市價成交」。
- **有交易成本**：每次成交收 `--cost-bps`（預設 `15` = 0.15%，佣金 + 滑點）。設 `--cost-bps 0` 先係舊版嘅「零成本」幻覺。
- **重新平衡頻率**：`--rebalance {daily,weekly,monthly}`，預設 `monthly`。Momentum rotation 高換手，daily rebalance 喺真錢交易會被成本食凸。
  Live execution 都用同一個 cadence：每日可以跑 `main.py` 做監測，但 `--rebalance monthly` 只會喺新月份換 basket；月內只會因 vol-target 需要而按現有持倉比例調整總曝險。`strategy_state.json` 會記錄已處理過嘅 month/week，避免「月初冇成交」之後每日重複觸發 basket rebalance。
- **動態 universe（無 membership 前視）**：預設每年用市值 Top 10，但**滯後 1 年**（`--universe-lag-years 1`）——因為 Y 年底個快照要到 Y 年完先知道，所以 Y 年只可以用 Y−1 年底嘅名單。設 `--universe-lag-years 0` 會還原舊行為（有前視，數字會虛高，淨係用嚟對照）。想返去舊式固定名單，傳 `--symbols AAPL MSFT NVDA ...`。
- **季度／point-in-time universe**：`--universe-json` 除咗年度格式（`{"2010":[...]}`），亦支援**日期 key**（`{"2014-03-31":[...]}`）。日期格式會按「快照生效日 + `--universe-publication-lag-days`」之後至可用，granularity 更幼、更貼近真實可交易。有 Norgate / Sharadar 季度市值就用呢個。
- **倖存者偏差**：Yahoo 只有現存上市股票，已退市嘅唔會出現；啟動時會印出每隻 symbol 真實數據起始日，遲上市嘅會標 ⚠️。早年 universe 細咗 → 回報會偏高，自己打個折扣。
- **過度擬合檢查**：用 `--sweep-lookback 63 126 252 504` 跑多個 lookback，睇 CAGR／回撤對參數有幾敏感。差距大 = 揀中嘅參數靠彩數。
- **指數托底（贏 QQQ 嘅最穩配置）**：`--index-floor QQQ`。正動量股票唔夠 `top_n` 隻時，空倉位用 QQQ 補（而唔係攤分／揸現金）。配 `--top-n 5`，無前視無倖存者偏差之下仍然跑贏 QQQ：CAGR 19.4% vs 19.2%、最大回撤 -30.6% vs -35.1%（回報微贏、回撤明顯細）。`--top-n 1` 喺乾淨數據反而最差，集中唔等於賺多。

- **槓桿（真正跑贏 QQQ 回報）**：`--leverage 1.15 --financing-rate 0.03`。`top5 + QQQ 托底` 嘅回撤本身細過 QQQ（-30.6% vs -35.1%），加 1.15x 槓桿把呢個裕度換成超額回報：CAGR 21.7% vs QQQ 19.2%，而回撤 -34.6% 仍 ≤ QQQ。即係同樣風險、更高回報。對融資成本好硬淨（5% 都只蝕 ~0.3pp）。
- **Vol-target（目前最強「住半山」版本）**：先跑 `top5 + QQQ 托底` base portfolio，再按 40 日 realized volatility 調曝險。保守版係 `--vol-target 0.26 --max-leverage 2`，約 CAGR 24.4%、最大回撤 -30.1%；大幅跑贏版係 `--vol-target 0.30 --max-leverage 2`，約 CAGR 26.1%、最大回撤 -33.9%。啟用 `--vol-target` 時，輸出會用 vol-target summary；固定 `--leverage` 只作舊版固定槓桿比較。
  主回測會同時印出「最新實際波幅 / 最新目標曝險 / 最新有效曝險」，用嚟判斷今日應該企喺山腰邊個高度。
  注意：QQQ-only VT30 cap2 CAGR 其實更高（約 27.0%），但最大回撤去到 -41.1%。Top5 + QQQ 嘅作用唔係加速，而係降低 base 回撤，令 vol-target 槓桿後仍然似「住半山」。
  實盤選擇可以當成回撤預算：`VT26 cap2` 係保守主線（約 24.2% CAGR / -30.1% 回撤），`VT30 cap2` 係進取主線（約 26.1% CAGR / -33.9% 回撤）。
  如果你要「更大幅跑贏」，可以轉去 QLD/TQQQ 呢類槓桿 ETF；但研究結果顯示，CAGR 上到 30-40% 時，最大回撤通常會去到 -40% 到 -80%，唔再係可長期持有嘅半山版。
  暫時最強「高風險但未到 TQQQ」候選係 `--top-n 10 --vol-target 0.34 --max-leverage 2.5`：約 30.3% CAGR / -39.8% 回撤；5% 融資後仍約 27.6% CAGR。
  可以用 `scripts/stress_test_momentum_candidates.py` 重跑融資、成本、起始年同 leverage cap 壓力測試；現有結果顯示 Top5 VT30 cap2 係實盤主攻，Top10 VT34 cap2.5 係高風險研究候選，唔係預設落單策略。

```sh
# 修正後最穩、跑贏 QQQ 嘅配置（風險調整 + 回報都贏）
uv run python scripts/backtest_momentum_rotation.py \
  --universe-json sp500_top_10_market_cap_2010_2026.json \
  --top-n 5 --index-floor QQQ --leverage 1.15 --start 2010-01-01
```

```sh
# 大幅跑贏版：Top5 + QQQ 托底，再用 vol-target 30%、cap 2x 管理曝險
uv run python scripts/backtest_momentum_rotation.py \
  --universe-json sp500_top_10_market_cap_2010_2026.json \
  --top-n 5 --index-floor QQQ \
  --vol-target 0.30 --vol-window 40 --max-leverage 2 --rebal-band 0.05 \
  --financing-rate 0.03 --rebalance monthly --cost-bps 15 \
  --start 2010-01-01
```

```sh
# 進取大幅跑贏版：Top10 + QQQ 托底，target vol 34%、cap 2.5x
uv run python scripts/backtest_momentum_rotation.py \
  --universe-json sp500_top_10_market_cap_2010_2026.json \
  --top-n 10 --index-floor QQQ \
  --vol-target 0.34 --vol-window 40 --max-leverage 2.5 --rebal-band 0.05 \
  --financing-rate 0.03 --rebalance monthly --cost-bps 15 \
  --start 2010-01-01
```

```sh
# 壓力測試：比較 Top5 / Top10 候選喺融資、成本、起始年、cap 改變下仲贏唔贏 QQQ
uv run python scripts/stress_test_momentum_candidates.py \
  --start 2010-01-01 \
  --output-csv output/momentum_candidate_stress.csv
```

```sh
# 保守半山版：回撤更低，但 CAGR 都低啲
uv run python scripts/backtest_momentum_rotation.py \
  --universe-json sp500_top_10_market_cap_2010_2026.json \
  --top-n 5 --index-floor QQQ \
  --vol-target 0.26 --vol-window 40 --max-leverage 2 --rebal-band 0.05 \
  --financing-rate 0.03 --rebalance monthly --cost-bps 15 \
  --start 2010-01-01
```

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
