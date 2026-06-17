# 跑贏 QQQ 研究總結（FINDINGS）

> 目的：記低「乜嘢 work、乜嘢唔 work」，避免將來重複試同一批假 edge。
> 基準：長揸 QQQ，2010-2026 約 **19.4% CAGR / 0.96 Sharpe / -35% MaxDD**。
> 方法：信號延後 1 日、含交易成本、避免 universe membership 前視；有壓力測試就用壓力測試，唔睇單一靚 backtest。

---

## TL;DR

**無槓桿大幅 raw CAGR 跑贏 QQQ —— 試勻 6 個方向都證唔到。大幅 raw CAGR 贏必須輕槓桿（§1-2）。**
**無槓桿 risk-adjusted 贏有兩條 robust 路：QQQ/Gold ~80/20 月度再平衡（§9.2）、QQQ + 5% OTM 月度 covered call（§10.2）。**

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

### 3.4 無槓桿「集中版」—— 後來證實主要係 survivorship 幻覺（見 §3.5）

> ⚠️ **2026-06 重大修正**：下面呢段聲稱「無槓桿集中版贏 QQQ CAGR」嘅證據，喺
> 真 point-in-time（含退市股）數據下**證偽**。詳見 **§3.5**。以下保留作紀錄，但結論已被推翻。

闊池 S&P 500（date-added，無槓桿，monthly，+QQQ floor）按 top_n 集中度：

| 配置     | CAGR      | Sharpe | 最大回撤 |
| -------- | --------- | ------ | -------- |
| **top5** | **24.9%** | 0.88   | -37.8%   |
| top10    | 20.4%     | 0.84   | -37.3%   |
| 長揸 QQQ | 19.3%     | 0.96   | -35.1%   |

top5 **CAGR 贏 QQQ 5.6pp，無槓桿**，而且 OOS(23.4% vs 20.4%)、walk-forward(22.1% vs 20.4%)都贏 CAGR。

**官方 datasets S&P 500 list（503 隻）確認 — 集中度 ↔ 回撤 trade-off：**

| 配置（無槓桿,+QQQ floor,2010+） | CAGR      | Sharpe | 最大回撤   | OOS16 CAGR |
| ------------------------------- | --------- | ------ | ---------- | ---------- |
| top3                            | **31.6%** | 0.93   | **-52.4%** | 34.9%      |
| top5                            | 25.7%     | 0.89   | -41.7%     | 26.4%      |
| top10（最務實）                 | 23.9%     | 0.94   | -36.9%     | 24.8%      |
| 長揸 QQQ                        | 19.3%     | 0.96   | -35.1%     | 20.4%      |

兩個獨立 list（hanshof + datasets）top3/5/10 **全部贏 QQQ CAGR（full + OOS）** → 集中 beat robust。**top10 最划算**（贏 4.6pp、Sharpe 0.94 ≈ QQQ、回撤只深 2pp）；越集中（top3）CAGR 越高但回撤越爆（-52%）。

**關鍵分別**：窄池（市值 top-10）top5 同 QQQ 打和（top5 ≈ QQQ 重磅股）；**闊池** top5 = 揀全市場最強 5 隻，集中度遠高過 cap-weighted QQQ → CAGR 跑贏。**breadth 係關鍵。**

**可重複性測試（repeatability，2010+，無槓桿，15bps）**：

_參數網格 — 9/9 組合全部贏 QQQ CAGR（18.9%），唔係靠單一參數 → 對參數穩健、唔係 overfit：_

| lookback ＼ top_n | top5  | top10 | top15 |
| ----------------- | ----- | ----- | ----- |
| 63d               | 23.0% | 20.8% | 19.5% |
| 126d              | 27.6% | 22.4% | 20.8% |
| 252d              | 28.1% | 22.7% | 22.7% |

（lb126 top10 改 quarterly rebalance 仲高：29.6% / Sharpe 1.07 / -42.9%。）

_非重疊 3 年子區間（lb126 top10）— 4/6 贏：_

| 區間      | 策略  | QQQ   | 結果 |
| --------- | ----- | ----- | ---- |
| 2010-2012 | 20.0% | 15.5% | WIN  |
| 2013-2015 | 26.4% | 19.8% | WIN  |
| 2016-2018 | 9.5%  | 11.3% | lose |
| 2019-2021 | 20.0% | 37.1% | lose |
| 2022-2024 | 12.3% | 8.8%  | WIN  |
| 2025-2027\* | 86.7% | 27.1% | WIN  |

\*2025-2027 係部分窗 + 半導體超級周期，幅度誇張，唔好過度睇重。**輸嗰兩段都係 QQQ mega-cap 大牛市（2019-21 melt-up），動量分散食虧** —— 即係呢個策略喺「少數巨型股帶動全市場」嘅環境會跑輸，呢個係佢嘅 regime 弱點。

→ **「可重複」成立：對參數（9/9）同大部分時段（4/6）都贏 raw CAGR。** 但仍然係下面講嘅 risk-for-return，唔係免費 alpha。

**當時嘅 caveat（依然啱，但低估咗）**：

1. **Sharpe 低過 QQQ**（0.88 vs 0.96）—— 即使數字成立，CAGR 贏都係靠承受更大波動 / 更深回撤。
2. **Survivorship caveat**：上面兩個 list 都係**今日** S&P 500 成員，缺晒歷史退市股 → 絕對 CAGR 偏高。當時以為「相對 beat 企得住」，**§3.5 證明連相對 beat 都企唔住**。

### 3.5 Survivorship 修正：集中版 raw-CAGR edge 證偽（決定性）

§3.4 唯一未做嘅驗證 = 用**真 point-in-time membership + 含退市股**嘅數據重跑。而家做咗：

- `scripts/build_pit_sp500_membership.py`：由 Wikipedia 成份變動表（399 條 add/remove 紀錄）**向後重建** point-in-time membership → 826 隻歷史成員（今日 503 + **323 隻已被踢走/退市**），每隻有真實 start/end。
- `scripts/fetch_pit_prices.py`：yfinance 抽埋退市股價格；關鍵兩步清洗 ——（a）**clip 落各自 membership 窗口**，剷走 yfinance *ticker-recycling* junk（退市後個 symbol 派咗畀第二隻證券，e.g. TIE 退市後變咗交易喺 8000+ 嘅嘢）；（b）scrub 殘留單日 >±50-60% 嘅壞 print。最後 **634 隻成員有價（含 ~181 隻退市股入返測試）**。
- `scripts/pit_backtest_momentum_rotation.py`：survivorship-free engine（退市後 ffill 最後價當套現、跌幅照計）。

**結果（2009-01 → 2026-06，無槓桿，monthly，15bps，+QQQ floor）：**

| 配置（PIT，含退市股） | §3.4 舊數（survivorship） | **乾淨 CAGR** | Sharpe | 最大回撤   | vs QQQ |
| --------------------- | ------------------------: | ------------: | -----: | ---------- | ------ |
| top3                  |                     31.6% |     **18.9%** |   0.62 | **-70.2%** | ❌ 輸  |
| top5                  |                     25.7% |     **20.0%** |   0.70 | -59.4%     | ❌ 輸  |
| top10                 |                     23.9% |     **19.0%** |   0.76 | -36.4%     | ❌ 輸  |
| 長揸 QQQ（同窗）      |                         — |     **21.0%** |   1.02 | -35.1%     | —      |

**每個 top_n 而家 CAGR、Sharpe、回撤三項全輸 QQQ。** 穩健性（同樣全輸）：lb252 top10 = 19.2%、weekly top10 = 15.2%、top5 無 floor = 17.9%。（lb63 出 57%/波幅 4425% 係短 lookback 放大殘留數據噪音嘅 artifact，唔計。）

**結論（推翻 §3.4）**：

1. **「無槓桿闊池集中贏 QQQ」係 survivorship bias 砌出嚟。** 之前 24-31% CAGR 靠今日生存者組成嘅 universe；含返退市/被踢走股之後，集中度越高（top3）回撤越爆（-70%）但 raw CAGR 跌穿 QQQ。
2. 殘留局限：仲有 192 隻退市股 Yahoo 完全摷唔到（混合破產 + 被溢價收購如 YHOO/ATVI/CELG），bias 方向兩面都有，但**最乾淨嘅版本已經令 edge 消失**。要再 confirm 絕對數字要 Norgate/CRSP。
3. **對 goal 嘅誠實答案**：純無槓桿選股（即使係之前最強嘅集中版）**冇穩健跑贏 QQQ 嘅證據**。真正企得住嘅得返 §1-2 嗰種「QQQ floor 減回撤 + vol-target 動態曝險」，但 vol-target 本質係 ≤2x 動態槓桿，唔算純無槓桿。

復現：

```sh
.venv/bin/python scripts/build_pit_sp500_membership.py
.venv/bin/python scripts/fetch_pit_prices.py
.venv/bin/python scripts/pit_backtest_momentum_rotation.py \
  --prices output/sp500_pit_prices.csv --membership output/sp500_pit_membership.csv \
  --benchmark QQQ --index-floor QQQ --lookback-days 126 --top-n 10 \
  --rebalance monthly --cost-bps 15
```

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

### 5.4 Walk-forward 驗證：vol-target 唔係 Sharpe alpha（重要修正）

對 base（top5+QQQ floor）做 vol-target 參數驗證（36 組 grid：target_vol × window × cap）：

**[A] 參數穩定性（full-sample）**

- vol-target Sharpe 範圍 **0.87–0.97**（中位 0.93）vs **QQQ 0.96**。
- **只有 7/36 組 Sharpe ≥ QQQ。** CAGR 17–28%（由 leverage/cap 拉開）。
- → vol-target Sharpe **≈ QQQ（打和）**；CAGR 越高純粹係越大槓桿，唔係 risk-adjusted edge。

**[B] Walk-forward（3y train→1y OOS，揀 train Sharpe 最佳參數）**

|                     | CAGR  | Sharpe   | 最大回撤 |
| ------------------- | ----- | -------- | -------- |
| WF 自適應（揀參數） | 17.1% | **0.82** | -30.5%   |
| 固定 26%/40/2       | 24.3% | 0.94     | -30.1%   |
| base 未槓桿         | 19.8% | 0.93     | -30.6%   |
| 長揸 QQQ            | 20.4% | **1.00** | -35.1%   |

→ **自適應揀 vol-target 參數會 overfit**：OOS Sharpe 0.82，仲衰過 base、衰過固定、更衰過 QQQ；每段揀中嘅參數跳嚟跳去，冇穩定贏家。

**修正後嘅誠實結論：**

1. vol-target + 槓桿**唔係 Sharpe-beating alpha** —— full-sample 同 walk-forward 都顯示 Sharpe ≈ QQQ。CAGR 嘅「贏」係 **leverage（多冒風險）**，唔係 alpha。
2. **唔好 tune vol-target 參數**（walk-forward 證咗 adaptive 會 overfit）。要用就**固定一個合理值**，唔好優化。
3. **真正 robust 嘅得一樣：回撤** —— 36 組都穩定 ~-30%（< QQQ -35%）。vol-target 可靠嘅好處 = **減回撤，唔係加 Sharpe**。
4. 落注理由應該係「想要 QQQ 級回報但跌市痛少啲，並接受用槓桿放大 = 放大風險」，**唔係**「我搵到 alpha」。

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
| `scripts/multi_asset_no_leverage.py`             | 無槓桿跨資產配置 vs QQQ（rotation/risk-parity/blend/VT-cap1x）           |
| `scripts/multi_asset_robustness.py`              | QQQ/GLD blend sweep + 子時段 + blend+VT robustness                       |
| `scripts/research_tsmom_no_leverage.py`          | time-series momentum per-stock trend（broad PIT / mega，cash/floor mode） |
| `scripts/research_option_income.py`              | option income：CBOE 真實 PUT/BXM index + QQQ BS covered call/put-write model（haircut / sigma-mode / weekly） |
| `scripts/research_basket_options.py`             | 高-IV mega-cap basket covered call / put-write（lagged realized vol 做 IV proxy） |

---

## 8. 數據局限

- 價格用 Yahoo，仍有 survivorship 風險；真正乾淨要 Norgate/CRSP。
- 市值 universe 係年度快照；理想係季度 point-in-time market cap。
- Finviz 係 current snapshot；歷史基本面因子要 SimFin/Sharadar/Compustat。
- 所有結果都係 backtest；真錢要先細注跑 execution、滑點、融資利率。

---

## 9. 跨資產配置：無槓桿 risk-adjusted 嘅唯一出路（2026-06 新方向）

> 之前所有研究都係「**美股選股** vs QQQ」。本節試唯一未探索過嘅維度：**multi-asset allocation**
> （bonds / gold / commodities / intl / defensive sectors），用 ETF，數據乾淨、**無 survivorship bias**。
> 理論支撐：分散化係唯一 free lunch；QQQ 2010-2026 咁強係因為佢就係嗰段時間嘅贏家 asset，
> 加入低相關 asset 係 long-only 無槓桿下唯一可能提升 risk-adjusted return 嘅路。

數據：14 隻 ETF（QQQ/SPY/IWM/EFA/EEM/VNQ/XLU/XLP/TLT/IEF/AGG/GLD/DBC/BIL），2009-10→2026-06，
月度 rebalance、15bps、信號 shift(1)、總曝險 ≤100% **無借貸**。
script：`scripts/multi_asset_no_leverage.py` + `scripts/multi_asset_robustness.py`。

### 9.1 其他配置：CAGR 全輸，分散有價但追唔上 QQQ 回報

| 配置                       |  CAGR | Sharpe | 最大回撤 | 判斷                              |
| -------------------------- | ----: | -----: | -------: | --------------------------------- |
| 跨資產動量 top3/top5       | 5-8%  | 0.5-0.8| -19~-26% | 慘敗：揀到 IWM/EEM/DBC 長期弱勢 + whipsaw |
| Dual momentum (QQQ/TLT)    | 16.0% |  0.85  | -37.2%   | 跌市轉 TLT 反而 whipsaw，DD 更深   |
| Risk parity (inv-vol)      |  5.7% |  0.80  | -18.5%   | 大量低回報 asset，CAGR 太低        |
| 60/40 (SPY/TLT)            | 10.1% |  1.00  | -27.6%   | Sharpe 微贏，CAGR 輸 9pp           |
| All-Weather 風格            |  7.0% |  0.90  | -23.6%   | 同上，CAGR 更低                    |
| QQQ/TLT 50/50              | 11.5% |  1.02  | -34.5%   | Sharpe 微贏，CAGR 輸 8pp、Calmar 輸 |

跨資產動量 rotation / risk parity / 60/40 / All-Weather **CAGR 全輸 QQQ（19.3%）**。
分散確實降咗波幅同回撤，但回報被低增長 asset（bonds/commodities）拖死。Sharpe 偶爾微贏，
Calmar 全輸。

### 9.2 QQQ/Gold blend = 無槓桿 risk-adjusted 跑贏 QQQ 嘅 robust 答案

| 配置            |  CAGR | Sharpe | 最大回撤 | Calmar |
| --------------- | ----: | -----: | -------: | -----: |
| QQQ 90 / GLD 10 | 18.4% |  1.00  |  -32.9%  |  0.56  |
| QQQ 85 / GLD 15 | 17.9% |  1.02  |  -31.8%  |  0.56  |
| **QQQ 80 / GLD 20** | **17.5%** | **1.03** | **-30.6%** | **0.57** |
| QQQ 75 / GLD 25 | 17.0% |  1.05  |  -29.5%  |  0.58  |
| QQQ 70 / GLD 30 | 16.5% |  1.06  |  -28.4%  |  0.58  |
| 長揸 QQQ        | 19.3% |  0.96  |  -35.1%  |  0.55  |

- **Sharpe 同 Calmar 隨 gold 比例穩定上升**（1.00→1.06、0.56→0.58），CAGR 線性下降 18.4→16.5%。
  整個 blend surface 平滑傾斜 —— **唔靠單一參數，唔係 overfit**。
- **80/20**：Sharpe 1.03 vs 0.96、Calmar 0.57 vs 0.55、DD -30.6% vs -35.1%、CAGR 17.5% vs 19.3%（**輸 1.8pp**）。
- 加 TLT（QQQ 70/GLD20/TLT10 等）反而差（Calmar 跌到 0.50-0.52，因 TLT 2022 暴跌）→ **gold 係比長債更好嘅 QQQ 分散劑**。

**子時段穩定性（決定性，QQQ 80/GLD 20 vs QQQ）：**

| 時段      | 80/20 CAGR/Sharpe/Calmar | QQQ CAGR/Sharpe/Calmar | 判斷                       |
| --------- | ------------------------ | ---------------------- | -------------------------- |
| 2010-2017 | 14.6% / 1.08 / 1.24      | 17.6% / 1.06 / 1.09    | Sharpe 打和，Calmar + DD 贏 |
| 2018-2026 | 20.0% / 1.02 / 0.65      | 20.6% / 0.90 / 0.59    | **Sharpe 明顯贏 + Calmar 贏** |

→ **兩個獨立子時段 risk-adjusted 都企得住**，唔係靠單一年份。機制：gold 喺股市危機
（2020 COVID、2022 加息熊市）低相關，降 drawdown；月度再平衡喺兩者間再平衡。CAGR 犧牲
1-3pp 換更平滑 equity curve。

### 9.3 QQQ/GLD blend + vol-target cap1x（純減曝險，唔借錢）

| 配置               |  CAGR | Sharpe | 最大回撤 | Calmar |
| ------------------ | ----: | -----: | -------: | -----: |
| blend VT cap1x 15% | 14.2% |  1.00  |  -21.7%  |  0.65  |
| blend VT cap1x 20% | 15.6% |  0.99  |  -27.0%  |  0.58  |

進一步降 drawdown（-21.7%），但 CAGR 跌到 14-16%。cap1x 唔借錢，算無槓桿，但牛市少賺。

### 9.4 對 goal 嘅誠實總結

1. **raw CAGR 無槓桿贏 QQQ 經四個獨立方法確認基本不可能**：mega-cap 選股（§3.1-3.2）、
   闊池選股（§3.5）、基本面因子 ETF（§4.4）、跨資產配置（§9.1）。QQQ 2010-2026 太強。
2. **但 risk-adjusted（Sharpe/Calmar/Drawdown）可以靠 QQQ/Gold ~80/20 月度再平衡無槓桿贏，而且 robust**
   （§9.2 子時段 + 平滑 surface 雙重確認）。呢個係之前所有「靠槓桿放大」策略嘅無槓桿替代：
   唔使借錢、唔使選股、數據乾淨。
3. 若硬要 raw CAGR 贏，唯一出路仍係 §1-2 嘅輕槓桿（top5+QQQ ×1.15）。無免費 raw CAGR。

---

## 10. 新一輪：未試過嘅 alpha class（TSMOM / option income / calendar / multi-factor）

> §1-9 用咗 4 個方向（mega-cap 選股、闊池 PIT 選股、因子 ETF、跨資產配置）證明無槓桿 raw CAGR 贏唔到 QQQ。
> 本節專攻**之前完全未掂過嘅 alpha class**：per-stock trend following、option income（VRP）、
> calendar effect、price-derived multi-factor。目標：搵到一條「大幅跑贏」嘅新路，或者徹底關門。

工具：`scripts/research_tsmom_no_leverage.py`、`scripts/research_option_income.py`、
`scripts/research_basket_options.py`（已加落 §7 工具表）。全部信號 `shift(1)`、含成本、PIT 數據。

### 10.1 Time-series momentum（per-stock trend）—— 唔贏 raw CAGR

之前所有 momentum 都係 **cross-sectional**（揀最強 top N）。TSMOM 係 **time-series**：每隻股票獨立判斷
自己趨勢（升緊先揸、跌穿轉 cash/QQQ），文獻（Moskowitz/Ooi/Pedersen 2012）support 有 persistent premium。
long-only 版保留 upside、靠 cut losses 控制 drawdown。

| 配置（2010-2026，15bps） | CAGR | Sharpe | 最大回撤 | vs QQQ |
| ------------------------ | ---: | -----: | -------: | ------ |
| mega TSMOM + QQQ floor（最好） | 16.7% | 0.91 | -26.8% | ❌ 輸 2.7pp，但 DD 贏 |
| mega tsmom floor weekly       | 15.1% | 0.84 | -31.0% | ❌ 輸 |
| broad PIT cash-mode max50     | 10.4% | 0.62 | -41.7% | ❌ 大輸（dilute mega-cap） |
| broad PIT + QQQ floor         | 10.7% | 0.71 | -37.1% | ❌ 大輸 |
| mega cash-mode max10          |  9.5% | 0.78 | -25.0% | ❌ 大輸（cash drag 69% 曝險） |

**結論**：TSMOM 全部輸 raw CAGR（最好 16.7% vs QQQ 19.4%）。機制同 §3.5 一致：broad TSMOM 稀釋咗
cap-weighted QQQ 嘅 mega-cap 集中度（upside）；mega TSMOM 用 equal-weight 10 隻都稀釋咗 QQQ 重磅強勢股。
最好嘅 mega combo（TSMOM+MA200 filter）Sharpe 0.91 ≈ QQQ、DD -26.8% < -35.1% —— **又係 risk-adjusted only，
唔加 raw CAGR**。TSMOM 唔係新 alpha。

### 10.2 Option income（VRP harvesting）—— 最接近 raw CAGR 贏嘅新路（但薄）

唯一完全未試過嘅 alpha class：**賣 option 收 premium**（covered call / put-write，無借貸）。
兩層證據：CBOE 真實 strategy index（無 modeling 假設）+ 自己 BS model（QQQ + VXN）。

**[A] CBOE 真實 index（2007-2026，daily）—— option selling raw CAGR 長期輸 buy-hold：**

| 策略 | CAGR | Sharpe | 最大回撤 |
| ---- | ---: | -----: | -------: |
| QQQ（買揸） | 16.2% | 0.79 | -53.4% |
| S&P 500（買揸） | 8.6% | 0.52 | -56.8% |
| **PUT 指數**（賣 ATM put，S&P） | 6.9% | 0.47 | -37.1% |
| **BXM 指數**（covered call，S&P） | 5.7% | 0.45 | -40.1% |

→ 真實 ATM option selling（PUT/BXM）**raw CAGR 輸 buy-hold**（5.7-6.9% vs 8.6%），只係 DD 細。
**ATM covered call / put-write 唔係 raw-CAGR alpha**（global + 多年期 confirm）。

**[B] QQQ option-income model（BS + VXN IV，actual QQQ 月度 payoff）—— 5% OTM covered call 係例外：**

| 配置（2010-2026，monthly） | CAGR | Sharpe | 最大回撤 | vs QQQ 19.9% |
| -------------------------- | ---: | -----: | -------: | ------------ |
| QQQ covered call K=105%（haircut 1.0） | **20.7%** | **1.50** | **-25.7%** | ✅ 雙贏 +0.8pp |
| QQQ covered call K=105%（haircut 0.9） | 19.5% | 1.42 | -27.0% | ⚠️ 邊緣輸 raw、大贏 risk-adjusted |
| QQQ covered call K=105%（haircut 0.85） | ~18.9% | ~1.35 | ~-28% | ❌ 邊緣輸 raw、大贏 risk-adjusted |
| QQQ put-write K=105%（haircut 1.0） | 20.6% | 1.50 | -25.8% | ✅ 雙贏（≈ CC） |
| ATM（K=100%）haircut 1.0 | 13.6% | 1.76 | -19.1% | ❌ 輸 raw（cap 晒 upside） |
| weekly / sigma-mode / mega basket | 10-17% | — | — | ❌ 全部更差 |

**為乜 5% OTM 例外**：ATM（BXM）cap 晒 upside → melt-up 大輸。**5% OTM 保留每月 5% upside**——
2010-2026 大部分月份 QQQ 月度回報 < 5%，所以保留 full upside + 收 premium；只有 melt-up month（>5%）被 cap。
QQQ 高 IV（22%）→ OTM call premium 仍可觀。Sweet spot = K=105%。

**[C] Premium robustness —— raw-CAGR edge 極薄、極依賴收到 full theoretical premium：**

| haircut（BS premium 打折） | 2010-2026 CAGR | 2007-2026 CAGR |
| -------------------------- | -------------: | -------------: |
| 1.0（理想） | 20.7% ✅ | 18.9% ✅ |
| 0.9 | 19.5% ❌ | 17.6% ✅ |
| 0.85 | 18.9% ❌ | **16.9% ✅** |
| 0.8 | 18.2% ❌ | 16.2% ❌（邊緣） |

- **2010-2026**：10% haircut（0.9）已消除 raw-CAGR edge。現實 OTM call IV < ATM VXN（equity index call skew）
  + bid-ask → 實際 haircut ~0.85-0.9 → **大概率 raw CAGR 打和 / 邊緣輸，但 Sharpe ~1.35、DD ~-28% 大幅 risk-adjusted 贏**。
- **2007-2026（含 GFC）更 robust**：haircut 0.85 仍雙贏 QQQ 16.5%（+0.4pp raw + 大幅 risk-adjusted）。
  機制：GFC 時 premium cushion + 無 melt-up 可 cap → 相對優勢更大；QQQ -49.7% DD vs CC -34.1%。

**[D] Option income 誠實總結**：
1. **真實 ATM option selling（CBOE BXM/PUT）長期 raw CAGR 輸 buy-hold**（global confirm，唔係 QQQ-specific artifact）。
2. **5% OTM covered call on 高-IV QQQ** 係唯一例外——理想 premium（haircut 1.0）下 2010-2026 雙贏 +0.8pp、
   2007-2026 +2.4pp；但 **raw-CAGR edge 對 premium realization 極敏感**，2010-2026 要 haircut ≥0.93 先贏。
3. **robust 嘅部分**：option income **大幅贏 risk-adjusted**（Sharpe 1.3-1.5 vs 1.1、DD -26~-28% vs -33%），
   喺所有 haircut（甚至 0.6）都成立。呢個係同 QQQ/GLD blend（§9.2）並列嘅**第二條無槓桿 risk-adjusted 路**。
4. weekly / put-write / sigma-mode / 高-IV basket 全部更差（weekly capping 過頻、put-write cap 晒 upside、
   basket base 弱、sigma-mode 賣太 OTM）。

### 10.3 Calendar effect（Sell in May）—— QQQ 上完全反轉

「Sell in May and go away」（Nov-Apr 揸股、May-Oct 揸 cash）係經典 S&P anomaly。但：

| 配置（2010-2026） | CAGR | Sharpe | 最大回撤 |
| ---------------- | ---: | -----: | -------: |
| QQQ buy-hold | 19.3% | 0.96 | -35.1% |
| Sell-in-May（Nov-Apr QQQ，rest cash） | 8.6% | 0.61 | -28.6% |
| Sell-in-May + TLT off-season | 10.1% | 0.61 | -41.7% |

**QQQ Nov-Apr annualized 18.9% vs May-Oct 20.6%**——off-season 反而更強！因為 modern tech bull market
（2020 summer melt-up 等）喺 May-Oct 都強。Calendar effect 喺 QQQ **完全唔 work**。Gold momentum overlay
（QQQ + 0/20 GLD）= 18.5%/1.01/-31.4%，又係 risk-adjusted only。

### 10.4 Multi-factor（momentum × low-vol，price-derived）—— 輸

PIT 闊池，composite score = 0.6 × momentum rank + 0.4 × (1 − vol rank)，top10 + QQQ floor：

| 配置 | CAGR | Sharpe | 最大回撤 |
| ---- | ---: | -----: | -------: |
| composite mom+lowvol top10 | 8.1% | 0.58 | -36.0% |
| QQQ | 19.4% | 0.96 | -35.1% |

低-vol tilt 拉低回報（low-vol stocks 喺 mega-cap tech 牛市跑輸）。price-derived multi-factor 收斂返 momentum，
已被 §3.5 證偽。**blend（QQQ/GLD）+ covered call** 組合 raw CAGR 更低（blend 本身已輸 QQQ，CC 再 cap upside）→ 10-16%。

### 10.5 本輪總結：第六個方法 confirm，option income 係新嘅 risk-adjusted 路

| 本輪試嘅 alpha class | raw CAGR vs QQQ | risk-adjusted vs QQQ |
| -------------------- | :-------------: | :------------------: |
| TSMOM per-stock trend（§10.1） | ❌ 輸（最好 16.7%） | ⚠️ 接近（DD 贏） |
| Option income ATM（真實 BXM/PUT，§10.2[A]） | ❌ 輸（5.7-6.9% vs 8.6% S&P） | ✅ DD 贏 |
| **Option income 5% OTM CC on QQQ（§10.2[B]）** | **⚠️ 邊緣**（h1.0 +0.8pp，h0.85 邊緣輸） | **✅ 大幅贏**（Sharpe 1.5、DD -26%） |
| Calendar / Sell in May（§10.3） | ❌ 反轉（8.6%） | ❌ |
| Multi-factor mom+lowvol（§10.4） | ❌ 輸（8.1%） | ❌ |

**新增嘅 robust 無槓桿 risk-adjusted 路：QQQ + monthly 5% OTM covered call**（同 §9.2 QQQ/GLD blend 並列）：
- raw CAGR 喺理想 premium 下邊緣贏（2010-2026 +0.8pp）、現實 premium 下打和；
- risk-adjusted 喺所有 haircut 下大幅贏（Sharpe +0.3、DD -7pp、Calmar 明顯高）；
- 2007-2026（含 GFC）更 robust，haircut 0.85 都雙贏。

但**「大幅跑贏 raw CAGR」呢條 bar 仍然跨唔過**——option income 嘅 raw edge 薄到 10% premium haircut 就消失。
連同 §3.1-3.2、§3.5、§4.4、§9.1，**已經用咗 6 個獨立方法**（mega-cap 選股、闊池 PIT 選股、TSMOM、
因子 ETF、跨資產、option income）confirm：純無槓桿大幅跑贏 QQQ raw CAGR 喺 2010-2026 基本唔存在。

---

## 最終一句

**跑贏 QQQ 有三條誠實嘅路。**
1. **大幅 raw CAGR 贏** → 冇免費午餐，**必須輕槓桿**（§1-2，top5+QQQ ×1.15 = 21.7%）。6 個無槓桿方向都證唔到大幅 raw 贏。
2. **無槓桿 risk-adjusted 贏（首選，乾淨）** → **QQQ/Gold ~80/20 月度再平衡**（§9.2），唔使選股、唔使 options，Sharpe/Calmar/DD 全贏，CAGR 只蝕 1-3pp。
3. **無槓桿 risk-adjusted 贏（次選，要 options）** → **QQQ + monthly 5% OTM covered call**（§10.2），Sharpe 1.5、DD -26%，CAGR 喺理想 premium 下邊緣贏、現實下打和。同 QQQ/GLD blend 二選一，視乎你接唔接受賣 option 嘅執行複雜度。

純無槓桿**大幅** raw CAGR 跑贏 QQQ —— 試勻 6 個方向都證唔到；唯一可靠嘅 raw-CAGR 槓桿仍係 §1-2。
