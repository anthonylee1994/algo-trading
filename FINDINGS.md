# 跑贏 QQQ 研究總結（FINDINGS）

> 目的：記低「乜嘢 work、乜嘢唔 work」，避免將來重複試同一批假 edge。
> 基準：長揸 QQQ，2010-2026 約 **19.4% CAGR / 0.96 Sharpe / -35% MaxDD**。
> 方法：信號延後 1 日、含交易成本、避免 universe membership 前視；有壓力測試就用壓力測試，唔睇單一靚 backtest。

---

## TL;DR

**無槓桿嘅純選股，穩健跑贏 QQQ 好難；大幅跑贏 QQQ 要靠動態曝險 / 槓桿。**

最可落地嘅主策略：

1. 用上一年已知嘅 S&P 500 市值 Top 10 做候選池。
2. 每月計 126 日 momentum。
3. 買正 momentum 最高 5 隻，等權；唔夠 5 隻就用 QQQ 補位。
4. 用 40 日 realized volatility 做 vol-target，低波加注、高波減注。

| 版本     | 參數                           |  CAGR |  MaxDD | 判斷                               |
| -------- | ------------------------------ | ----: | -----: | ---------------------------------- |
| 保守半山 | Top5 + QQQ floor, VT26 cap2    | 24.2% | -30.1% | 回撤明顯低過 QQQ                   |
| 主攻半山 | Top5 + QQQ floor, VT30 cap2    | 26.1% | -33.9% | 主策略；大幅跑贏，回撤仍略細過 QQQ |
| 進取候選 | Top10 + QQQ floor, VT34 cap2.5 | 30.3% | -39.8% | 更快，但回撤同 margin 壓力高過 QQQ |

Finviz / `finvizfinance` 只做**今日候選池**，唔當歷史 alpha 證據。預設 forward screener：

```text
https://finviz.com/screener.ashx?v=161&f=cap_midover,fa_eps5years_o20,fa_roe_o15&ft=4&o=-marketcap
```

即係：市值 $2B 以上、EPS 5Y growth >20%、ROE >15%，按市值由大到細攞候選，再用 126D momentum 排 Top5/Top10。

---

## 1. 可執行策略

### 1.1 主攻版：Top5 + QQQ floor + VT30 cap2

```sh
uv run python scripts/backtest_momentum_rotation.py \
  --universe-json sp500_top_10_market_cap_2010_2026.json \
  --top-n 5 --index-floor QQQ \
  --vol-target 0.30 --vol-window 40 --max-leverage 2 --rebal-band 0.05 \
  --financing-rate 0.03 --rebalance monthly --cost-bps 15 \
  --start 2010-01-01
```

最新重跑結果：

| 指標     |   策略 |    QQQ |
| -------- | -----: | -----: |
| CAGR     |  26.1% |  19.4% |
| MaxDD    | -33.9% | -35.1% |
| Sharpe   |   0.94 |   0.96 |
| 平均曝險 |  1.62x |  1.00x |
| 低波曝險 |  2.00x |  1.00x |
| 高波曝險 |  1.02x |  1.00x |

結論：呢個係主策略。大幅跑贏 QQQ，但唔係靠神奇選股；係靠 base portfolio 回撤較細，再用 vol-target 喺低波 regime 放大曝險。

### 1.2 進取版：Top10 + QQQ floor + VT34 cap2.5

```sh
uv run python scripts/backtest_momentum_rotation.py \
  --universe-json sp500_top_10_market_cap_2010_2026.json \
  --top-n 10 --index-floor QQQ \
  --vol-target 0.34 --vol-window 40 --max-leverage 2.5 --rebal-band 0.05 \
  --financing-rate 0.03 --rebalance monthly --cost-bps 15 \
  --start 2010-01-01
```

最新重跑結果：

| 指標     |   策略 |    QQQ |
| -------- | -----: | -----: |
| CAGR     |  30.3% |  19.4% |
| MaxDD    | -39.8% | -35.1% |
| Sharpe   |   0.97 |   0.96 |
| 平均曝險 |  2.02x |  1.00x |
| 低波曝險 |  2.47x |  1.00x |
| 高波曝險 |  1.25x |  1.00x |

結論：呢個係「大幅跑贏」最強候選，但唔係預設實盤主線。5% 融資後仍約 27.6% CAGR；8% 融資後仍跑贏，但 edge 明顯縮。最大回撤長期比 QQQ 深 4-6pp，平均曝險約 2x。

### 1.3 今日 Finviz 候選

```sh
uv run python scripts/finviz_momentum_candidates.py \
  --preset eps-roe-mid \
  --limit 80 \
  --top-n 5 \
  --aggressive-top-n 10 \
  --lookback-days 126
```

用途：

- 用 Finviz 快速搵「有增長、ROE 夠、規模唔太細」嘅當前股票池。
- 再用 126D momentum 排序，輸出今日 Top5 / Top10。
- 只作 forward deployment，不作歷史回測證據。

---

## 2. 點解呢套 work

### 2.1 真正 edge 係 exposure timing

Top5 + QQQ floor 嘅 base portfolio 本身幾乎只係同 QQQ 打和：

| Component        | CAGR / drag | 解讀                                    |
| ---------------- | ----------: | --------------------------------------- |
| QQQ buy hold     |       19.4% | 基準                                    |
| Base top5+QQQ    |       19.5% | 選股 + QQQ floor，本身唔係 alpha engine |
| Gross vol-target |       29.1% | 動態曝險放大 base return，未扣成本      |
| Financing drag   |    -1.9%/年 | 借入部分融資成本                        |
| Rebalance cost   |    -0.5%/年 | 調整曝險成本                            |
| Net vol-target   |       26.1% | 扣成本後結果                            |

重點：**選股係避震器，vol-target 先係加速器。**

### 2.2 贏喺低波 regime

`VT30 cap2` 按 realized vol 分組：

| 波幅分位 | 日數 | 平均曝險 | 策略年化日均 | QQQ 年化日均 | 年化超額 |
| -------- | ---: | -------: | -----------: | -----------: | -------: |
| Q1 低波  | 1025 |    2.00x |        33.1% |        19.1% |   +14.0% |
| Q2       | 1024 |    1.97x |        44.2% |        27.6% |   +16.6% |
| Q3       | 1024 |    1.54x |        18.5% |        18.0% |    +0.6% |
| Q4 高波  | 1024 |    1.02x |        15.2% |        16.1% |    -0.9% |

真正超額嚟自低波加注。高波時只係防守，唔係賺 alpha。

### 2.3 QQQ-only 對照

| Case               |  CAGR |  MaxDD | Sharpe | 解讀                            |
| ------------------ | ----: | -----: | -----: | ------------------------------- |
| QQQ VT30 cap2      | 27.0% | -41.1% |   0.96 | 更快，但回撤明顯深過 QQQ        |
| Top5+QQQ VT30 cap2 | 26.1% | -33.9% |   0.94 | 慢少少，但先符合「半山」風險    |
| QQQ VT26 cap2      | 24.2% | -36.7% |   0.95 | 接近半山，但回撤仍高過 Top5+QQQ |
| Top5+QQQ VT26 cap2 | 24.2% | -30.1% |   0.95 | 保守半山版                      |

所以：只追 CAGR，QQQ-only VT30 夠快；但如果要「跑贏兼唔企山頂」，Top5+QQQ 更合理。

---

## 3. 純選股結論

### 3.1 相對 SPY：有用

如果 benchmark 係 SPY，純選股策略係搵到嘅。用 lagged annual market-cap Top10、monthly rebalance、15bps 成本、不用槓桿、不用 vol-target：

| 策略                           |       CAGR |            MaxDD |    Sharpe | 年份贏 SPY | vs SPY |   vs QQQ |
| ------------------------------ | ---------: | ---------------: | --------: | ---------: | -----: | -------: |
| Momentum L126 top5             |      18.9% |           -30.5% |      0.94 |        69% | +4.9pp |   -0.5pp |
| Momentum L126 top5 + SPY floor |      18.7% |           -30.5% |      0.93 |        69% | +4.6pp |   -0.7pp |
| Momentum L126 top10            |      17.6% |           -29.1% |      0.96 |        69% | +3.5pp |   -1.8pp |
| Equal weight lagged Top10      |      17.5% |           -34.7% |      0.94 |        63% | +3.4pp |   -2.0pp |
| Low volatility top5            | 12.9-13.3% | -25.8% 至 -27.1% | 0.85-0.87 |     44-50% | 輸 SPY | 大輸 QQQ |

結論：相對 SPY，mega-cap momentum / growth tilt work。

### 3.2 相對 QQQ：純選股唔夠

最好純選股只係慢 QQQ 約 0.5pp。要跑贏 QQQ，需要：

- QQQ floor 減少空倉拖累。
- vol-target 放大低波 regime。
- 或者接受更高槓桿 / 更深回撤。

### 3.3 闊池選股證偽

| Universe                         |   結果 | 備註                  |
| -------------------------------- | -----: | --------------------- |
| 手揀今日 20 隻贏家               |  41.6% | survivorship 幻覺     |
| 每年市值 Top10，同年快照         |  30.8% | membership 前視       |
| 每年市值 Top10，滯後 1 年        |  15.6% | 乾淨後輸 QQQ          |
| 103 隻手揀今日大盤股             | 24-41% | selection bias        |
| 完整 S&P 500 date-added universe | 14-25% | 無一個穩贏 QQQ Sharpe |

結論：闊 universe + momentum 並無穩定 alpha；好多靚數係 bias。

---

## 4. 已試過但唔 work

### 4.1 技術分析

| 方法                                   | 結果 vs QQQ               |
| -------------------------------------- | ------------------------- |
| 動量輪動 63/126/252                    | 輸 Sharpe                 |
| Skip-month 12-1                        | 更差                      |
| 多時框 blend / inverse-vol             | 更差                      |
| 200D trend filter                      | 減回撤但 whipsaw，CAGR 輸 |
| SCTR                                   | 更差                      |
| Faber 10-month SMA                     | 減回撤但 CAGR 大跌        |
| MACD                                   | whipsaw + 成本，慘敗      |
| Connors RSI / Bollinger mean reversion | CAGR 1-3%，長期空倉       |
| Donchian breakout                      | CAGR 約 5%                |
| ICT FVG / BOS / liquidity sweep        | 可機械化部分無 edge       |
| OBV / MFI / 放量訊號                   | 噪音內或幫倒手            |

共通原因：強趨勢牛市入面，任何擇時只要踏空幾次，回報就輸。

### 4.2 高勝率均值回歸

TDX「布林 %B + RSI + 成交量 + 橫行濾網 + 背馳 + 冷卻」：

| QQQ 日線 2007-2026 |  CAGR | Sharpe | MaxDD |
| ------------------ | ----: | -----: | ----: |
| Long-only          |  7.1% |   0.47 |  -47% |
| Long/Short         | -3.0% |  -0.03 |  -59% |
| Buy hold QQQ       | 16.7% |   0.81 |  -53% |

勝率 84%、平均每筆 +4.6%，但長期輸爆 buy-hold。高勝率唔等於跑贏。

### 4.3 買恐慌 / dip call

| 方法                    | 結論                                                                 |
| ----------------------- | -------------------------------------------------------------------- |
| VIX 高位加槓桿          | 2010+ raw CAGR 略高，但 Sharpe 差、回撤更深；含 2008 會 -72% 至 -76% |
| 回撤越深越加碼          | 牛市有時 work，熊市會放大災難                                        |
| 1 年 ITM long call 撈底 | 單筆有爆發，但組合層輸 QQQ，回撤更差                                 |

結論：機械化撈底容易喺熊市初段連環中招。

### 4.4 基本面因子 ETF

2016-2026 代理測試：

| 因子 ETF |  CAGR | Sharpe |
| -------- | ----: | -----: |
| QQQ      | 22.1% |   0.99 |
| MTUM     | 18.2% |   0.88 |
| QUAL     | 14.6% |   0.83 |
| VLUE     | 14.7% |   0.78 |
| COWZ     | 12.8% |   0.70 |
| USMV     | 10.3% |   0.74 |
| VTV      | 12.1% |   0.76 |

結論：value / quality / FCF flavor 係 regime bet，唔係 QQQ-killer。

### 4.5 主題 ETF 輪動

| ETF 輪動                         | CAGR / Sharpe | 備註                      |
| -------------------------------- | ------------- | ------------------------- |
| 手揀 7 隻含 SMH/QTUM + top3 + VT | 28.3% / 1.04  | 贏 QQQ，但 selection bias |
| 抽走 SMH/QTUM                    | 11.1% / 0.61  | edge 即刻冚               |
| 中性 29 隻主題/板塊 top3         | 16.1% / 0.71  | 輸 QQQ                    |
| 中性 29 隻 walk-forward          | 14.8% / 0.66  | 輸 QQQ                    |

結論：主題 ETF 輪動有分散價值，但唔係 QQQ-killer。

---

## 5. 風險同心理成本

### 5.1 逐年唔會穩贏

Top5+QQQ VT30 cap2 大贏年份：

| 年份 |  策略 |   QQQ |   超額 |
| ---- | ----: | ----: | -----: |
| 2024 | 83.7% | 25.6% | +58.1% |
| 2013 | 68.0% | 36.6% | +31.4% |
| 2019 | 61.9% | 39.0% | +23.0% |
| 2010 | 33.0% | 18.4% | +14.6% |
| 2011 | 16.9% |  3.5% | +13.5% |

最差超額年份：

| 年份     |  策略 |   QQQ |   超額 |
| -------- | ----: | ----: | -----: |
| 2026 YTD | -6.6% | 21.3% | -27.9% |
| 2020     | 30.4% | 48.4% | -18.0% |
| 2023     | 39.5% | 54.9% | -15.3% |
| 2015     |  4.2% |  9.4% |  -5.2% |
| 2018     | -1.4% | -0.1% |  -1.2% |

心理成本：QQQ 單邊爆升、高波又追唔晒嘅年份，策略會明顯落後。

### 5.2 2024 好重要，但唔係唯一支柱

剔除單一年重新計 CAGR：

| 剔除年份 | 策略 CAGR | QQQ CAGR |   超額 |
| -------- | --------: | -------: | -----: |
| 2024     |     23.0% |    19.1% | +4.0pp |
| 2013     |     23.8% |    18.4% | +5.4pp |
| 2019     |     24.1% |    18.3% | +5.8pp |

冇咗 2024，edge 由約 +6.6pp 收窄到 +4.0pp，但仍然跑贏。

### 5.3 今日山腰位

2026-06-15 Top5+QQQ VT30 cap2 snapshot：

| 指標         |  數值 |
| ------------ | ----: |
| 最新實際波幅 | 21.8% |
| 最新目標曝險 | 1.37x |
| 最新有效曝險 | 1.38x |

解讀：而家唔係低波滿 2x，也唔係高波縮到 1x；係約 1.4x 山腰位。

---

## 6. 方法論紀律

| 偏差                           | 例子                       | 影響                       |
| ------------------------------ | -------------------------- | -------------------------- |
| Survivorship                   | 手揀今日贏家做 universe    | CAGR 虛高                  |
| Lookahead：信號同成交同一根    | 用收市計又用收市成交       | momentum 虛高              |
| Lookahead：universe membership | 用年底市值名單交易同一年   | CAGR 可由 15.6% 谷到 30.8% |
| Selection bias                 | 手揀 103 隻今日大盤股      | 換成真 S&P 500 即失效      |
| In-sample overfit              | tune lookback/top_n 到最靚 | OOS 即衰                   |

必守規則：

- 信號要 `shift(1)`。
- 成本至少計 15bps。
- Universe 要用已知資料，年度市值要 lag 1 年。
- Finviz 只有 current snapshot，唔可以扮歷史基本面 backtest。
- 靚參數要做融資、成本、起始年、cap 壓力測試。

---

## 7. 工具索引

| 檔案                                             | 用途                                                                    |
| ------------------------------------------------ | ----------------------------------------------------------------------- |
| `scripts/backtest_momentum_rotation.py`          | 主回測：momentum、QQQ floor、leverage、vol-target、成本、月度 rebalance |
| `scripts/sweep_vol_target_momentum.py`           | 掃 lookback/top_n/vol-target/window/cap                                 |
| `scripts/stress_test_momentum_candidates.py`     | 對 Top5/Top10 候選做融資、成本、起始年、cap 壓力測試                    |
| `scripts/finviz_momentum_candidates.py`          | 用 `finvizfinance` 跑今日候選，再用 126D momentum 排名                  |
| `scripts/research_stock_selection_strategies.py` | 純選股研究：lagged Top10 vs SPY/QQQ                                     |
| `scripts/research_vol_target_secret.py`          | 拆解固定槓桿 vs vol-target                                              |
| `scripts/attribute_vol_target_regime.py`         | 拆低波/高波/逐年/leave-one-year-out attribution                         |
| `scripts/research_leveraged_etf_vol_target.py`   | 測 QQQ/QLD/TQQQ buy-hold、trend filter、vol-target                      |
| `scripts/pit_backtest_momentum_rotation.py`      | point-in-time membership + delisting-aware 闊池 engine                  |
| `scripts/simulate_momentum_rotation.py`          | Futu 模擬盤落單                                                         |
| `algo_trading/market_cap_universe.py`            | 年度 / dated point-in-time universe helper                              |
| `pine/vol_target_strategy.pine`                  | TradingView 單標的 vol-target strategy                                  |

---

## 8. 數據局限

- 價格用 Yahoo，仍有 survivorship 風險；真正乾淨要 Norgate/CRSP。
- 市值 universe 係年度快照；理想係季度 point-in-time market cap。
- Finviz 係 current snapshot；歷史基本面因子要 SimFin/Sharadar/Compustat。
- 所有結果都係 backtest；真錢要先細注跑 execution、滑點、融資利率。

---

## 最終一句

**跑贏 QQQ 無捷徑。** 無槓桿純選股唔夠；真正可落地嘅路係先建立一個回撤較細、行為接近 QQQ 嘅 base portfolio，再用 vol-target 喺低波 regime 放大曝險。想要更高 CAGR，就要誠實接受更高槓桿、更深回撤同更大心理成本。
