# 跑贏 QQQ 研究總結（FINDINGS）

> 一份「乜嘢 work、乜嘢唔 work」嘅實測紀錄，避免將來又由零試一次、又掉入同一個偏差陷阱。
> 全部測試：**無前視（信號 shift 1 日）+ 含成本（15 bps）+ 處理 survivorship + 睇 OOS / walk-forward**。
> 基準：長揸 QQQ，2010-2026 約 **CAGR 19.2%、Sharpe 0.96、最大回撤 -35%**。

---

## TL;DR（一句總結）

**無槓桿之下，冇任何技術分析、闊池選股、或基本面因子，喺 2010s-2020s 成長主導年代，穩健跑贏 QQQ 嘅風險調整回報。**
技術分析喺大盤指數係**風險工具（減回撤），唔係 alpha 引擎（加回報）**。想贏多過 QQQ，數學上只有三條路：**加槓桿 / 賭 value regime 轉勢 / 去低效率市場**——冇下一個神奇指標。

---

## 1. 方法論紀律（呢個先係真正嘅 edge）

調查途中，每個睇落靚到震嘅策略，擠走偏差之後都貼返地：

| 偏差                                    | 例子                                | 影響                            |
| --------------------------------------- | ----------------------------------- | ------------------------------- |
| **Survivorship（倖存者）**              | 手揀今日 20 隻贏家做 universe       | CAGR 虛高到 41%，乾淨後 ~15-30% |
| **Lookahead（前視）— 信號同成交同一根** | 用收市計又用收市成交                | momentum 虛高                   |
| **Lookahead — universe membership**     | 用「年底」市值名單交易嗰一整年      | CAGR 由 15.6% 谷到 30.8%        |
| **Selection bias（自選樣本）**          | 我自己揀 103 隻今日大盤股做「闊池」 | 假裝大贏，換成真 S&P 500 即失效 |
| **In-sample 過度擬合**                  | tune lookback / top_n 到最靚        | OOS 即衰過唔 tune               |

**結論：紀律慳你錢多過幫你贏錢。** 大部分人蝕錢，係因為信咗一個未擠走偏差嘅 backtest。

---

## 2. 技術分析 —— 全軍覆沒

| 方法                                                             | 結果 vs 長揸 QQQ       |
| ---------------------------------------------------------------- | ---------------------- |
| 動量輪動（126/63/252 日）                                        | 輸 Sharpe              |
| Skip-month 12-1（學術經典）                                      | 更差                   |
| 多時框 blend / inverse-vol 加權                                  | 更差                   |
| 200 日趨勢濾網                                                   | whipsaw，更差          |
| **SCTR**（StockCharts 綜合排名）                                 | 更差                   |
| **Faber 10 個月 SMA 擇時**                                       | 減回撤但 CAGR 大跌     |
| **MACD**（金叉/零軸/長短）                                       | 慘敗（whipsaw + 成本） |
| Connors RSI(2) / 布林帶 mean-reversion                           | CAGR 1-3%，長期空倉    |
| Donchian 突破（海龜式）                                          | CAGR ~5%               |
| 雙均線 50/200                                                    | 打和略輸               |
| **ICT**（Fair Value Gap / Break of Structure / Liquidity Sweep） | 全部大輸（1-11% CAGR） |
| 成交量訊號（OBV / MFI / 放量避險 / 量價齊升）                    | 噪音內或幫倒手         |

**共通原因**：任何擇時/形態都會喺某啲時候減倉；喺強趨勢牛市，每次踏空 = 直接蝕回報。

### 2a. 高勝率均值回歸指標（TDX 通達信公式）

一段「布林 %B + RSI + 成交量 + 橫行濾網 + RSI 背馳 + 冷卻」嘅買賣箭咀指標。Port 落 Python、補出場、計 15bps：

| QQQ 日線（2007-2026） | CAGR      | Sharpe | 最大回撤 |
| --------------------- | --------- | ------ | -------- |
| Long-only（買→賣）    | 7.1%      | 0.47   | -47%     |
| Long/Short            | **-3.0%** | -0.03  | -59%     |
| 買入持有 QQQ          | 16.7%     | 0.81   | -53%     |

逐筆交易：**勝率 84%、平均每筆 +4.6%**，睇落係印鈔機 —— 但 19 年總和 +173% vs QQQ +1609%。死因：(1) 橫行濾網令大部分時間揸現金、踏空大牛；(2) 負偏態，一次 -30.6% 食返 6 次贏。
1 小時日內測試（2024-26）結論一樣：long-only 5%、long/short -11%，全輸 buy-hold 25%。
**教訓：高勝率 ≠ 賺錢 ≠ 跑贏 buy-hold。高勝率正正係令人 all-in 嘅心理陷阱。**

### 2b. ICT Fair Value Gap（FVG）日內 event study

FVG 係 ICT 最可機械化嘅概念（3 根 K imbalance）。QQQ 1h（2 年）+ 15m（2 個月），直接睇 FVG 之後嘅 forward return：

| FVG 後 h 根（1h） | Bullish 均值 | Bearish 均值 | 無條件均值 |
| ----------------- | ------------ | ------------ | ---------- |
| 1                 | -0.026%      | -0.000%      | +0.014%    |
| 5                 | +0.015%      | +0.065%      | +0.070%    |
| 10                | +0.167%      | +0.188%      | +0.138%    |

**Bullish FVG 後回報唔升反而略低過基準；Bearish FVG 後仲係正數。勝率 50-60% = 市場自然 base rate。** 即係 FVG 方向 = 噪音，冇預測力。可交易版：continuation long-only 3%、long/short -17%，全輸 buy-hold。
**Scope**：呢個係 FVG **孤立**測試。正宗 ICT 要 HTF bias + liquidity + structure + kill zone confluence，嗰套係自由心證、不可證偽。證到嘅係「**FVG 單獨冇 edge**」。

### 2c. VIX 擇時 / 買恐慌（contrarian）—— 同 vol-target 啱啱相反

筆記思路「VIX 30+ 買股、跌深加碼」= 高波加倉。實測（QQQ + ^VIX，含融資）：

| 2010+                                  | CAGR      | Sharpe   | 最大回撤 |
| -------------------------------------- | --------- | -------- | -------- |
| 買入持有 QQQ                           | 19.5%     | **0.97** | -35%     |
| VIX 高位加槓桿（買恐慌）               | 20.8%     | 0.86     | -43%     |
| 回撤加槓桿（跌越深揸越多）             | 21.9%     | 0.89     | -45%     |
| 回撤加碼（持現金版）                   | 17.1%     | 0.94     | -32%     |
| **對照：vol-target（高波減倉，相反）** | **23.7%** | 0.93     | -36%     |

全期（含 2008）「買恐慌」最大回撤 **-72% 到 -76%**（喺崩盤中途加槓桿，仲跌就放大）。**raw CAGR 牛市有時高啲，但 Sharpe 更差、回撤恐怖；用 margin 做會爆倉。** 反而相反嘅 vol-target（高波減倉）先風險調整最優。持現金版輸（cash drag）。

### 2d. Long Call 撈底（筆記核心，BS 定價）

筆記嗰套「QQQ 回 15% → 買 1 年 15% 價內 Long Call」。Black-Scholes 定價（IV 用 VIX×1.1）：

逐筆（18 次撈底訊號）：Long Call 平均 **+44.7%** vs 正股 +15.9%，但**最大蝕 -92%**、勝率 61%。成敗 100% 取決於「個 dip 係咪近底」—— 熊市初段 -15% 觸發會連環中招（2008 連 4 鋪 -90%）。

組合層（90% QQQ + 每 dip 5% call，每日 MTM，扣摩擦）：

|                      | CAGR  | Sharpe | 最大回撤 |
| -------------------- | ----- | ------ | -------- |
| 純 QQQ（全期 2007+） | 16.7% | 0.81   | -53%     |
| 核心 + 5% dip call   | 16.5% | 0.76   | -62%     |
| 核心 + 10% dip call  | 16.0% | 0.69   | -71%     |

**機械化嘅撈底 call overlay 三項全輸 buy-hold**（2008 連環 -90% call 拖累 + 惡化回撤）。2010+ 只加 ~1pp CAGR 但 Sharpe 更低、回撤更深。
**但對筆記公道**：呢個測試冇咗筆記精髓 —— discretionary 止蝕（feel 唔對就走）、避開熊市第一個 dip、同**個股 call 選股**（「贏五倍靠 MU/SNDK/AMD」）。即係策略能唔能贏，100% 取決於 **backtest 唔到嘅擇時/止蝕/選股紀律**，唔係機械規則。

---

## 3. Universe / 選股 —— 闊池都贏唔到

| Universe                                            | CAGR      | Sharpe    | 備註                        |
| --------------------------------------------------- | --------- | --------- | --------------------------- |
| 手揀 20 隻贏家                                      | 41.6%     | —         | survivorship 幻覺           |
| 每年市值 Top 10（同年快照）                         | 30.8%     | 1.04      | membership 前視             |
| 每年市值 Top 10（**滯後 1 年，乾淨**）              | **15.6%** | 0.69      | **輸 QQQ**                  |
| 103 隻手揀今日大盤股                                | 24-41%    | 1.1+      | 我自己 selection bias       |
| 完整 S&P 500（497 隻，date-added，仍 survivorship） | 14-25%    | 0.78-0.91 | **冇一個贏 QQQ Sharpe**     |
| 齊頭持有全 S&P 500                                  | 18.0%     | 1.01      | momentum overlay 都贏佢唔到 |

**結論**：momentum 篩選喺廣泛大盤股冇加風險調整價值。「闊 universe = 真 alpha」假設**證偽**。

### 3b. 跑贏「大盤」嘅選股策略：有，但本質係 mega-cap momentum / growth tilt

如果 benchmark 由 QQQ 改做大盤 `SPY`，純選股策略係搵到嘅。用 `scripts/research_stock_selection_strategies.py`，只用年度市值 Top 10（滯後 1 年）+ Yahoo 價格，monthly rebalance、15bps 成本、不用槓桿、不用 vol-target：

| 策略                           |       CAGR |            MaxDD |    Sharpe | 年份贏 SPY |     vs SPY |   vs QQQ | 解讀                                       |
| ------------------------------ | ---------: | ---------------: | --------: | ---------: | ---------: | -------: | ------------------------------------------ |
| **Momentum L126 top5**         |  **18.9%** |       **-30.5%** |      0.94 |        69% | **+4.9pp** |   -0.5pp | 目前最好純選股版                           |
| Momentum L126 top5 + SPY floor |      18.7% |           -30.5% |      0.93 |        69% |     +4.6pp |   -0.7pp | 空位用 SPY 補，稍慢                        |
| Momentum L126 top3 + SPY floor |      18.7% |           -30.6% |      0.85 |        63% |     +4.6pp |   -0.7pp | 更集中但 Sharpe 差啲                       |
| Momentum L126 top10            |      17.6% |           -29.1% |  **0.96** |        69% |     +3.5pp |   -1.8pp | 分散、Sharpe 最高                          |
| Equal weight lagged Top10      |      17.5% |           -34.7% |      0.94 |        63% |     +3.4pp |   -2.0pp | 唔 ranking 都贏 SPY，size/growth tilt 好大 |
| Low volatility top5            | 12.9-13.3% | -25.8% 至 -27.1% | 0.85-0.87 |     44-50% |     輸 SPY | 大輸 QQQ | 低波唔係增長年代 alpha                     |

具體規則：

1. 每年只用上一年已知嘅 S&P 500 市值 Top 10，避免同年 membership 前視。
2. 每月計各股票 126 日 momentum。
3. 只買正 momentum 入面最高 5 隻，等權。
4. 如果正 momentum 唔夠 5 隻，純選股版保留現金；floor 版用 SPY 補空位。
5. 信號延後一日成交，交易成本 15bps。

結論要分開講：

- **相對 SPY：有可用選股策略。** `Momentum L126 top5` 做到約 **18.9% CAGR / -30.5% DD**，比 SPY 約 **14.1% CAGR / -33.7% DD** 好。
- **相對 QQQ：未算贏。** 同期 QQQ 約 **19.4% CAGR / -35.1% DD**；最好純選股只係慢 QQQ 約 0.5pp，但回撤細啲。
- **真正 edge 好可能唔係神奇選股，而係 mega-cap growth / quality tilt。** Equal-weight lagged Top10 已經 17.5% CAGR，代表「長期持有最大市值贏家」本身已經解釋咗好多超額。
- **純選股主線可以用 `Momentum L126 top5`；若目標係跑贏 QQQ，就要加上 QQQ floor / vol-target / leverage。**

### 3a. 板塊 / 主題 ETF 輪動 —— selection bias 嘅活教材

| ETF 輪動（動量 top-N, monthly, 含成本）                                | CAGR       | Sharpe    | 備註                                 |
| ---------------------------------------------------------------------- | ---------- | --------- | ------------------------------------ |
| 手揀 7 隻（含 SMH/QTUM）+ top3 + vol-target                            | 28.3%      | 1.04      | ✅ 贏 QQQ —— **但係 selection bias** |
| 上者抽走 SMH+QTUM（剩 4 隻）                                           | 11.1%      | 0.61      | edge 即刻冚                          |
| **中性 29 隻（11 板塊 + 一籃主題含 TAN/ICLN/ARKK/JETS 等衰嘅），top3** | 16.1%      | 0.71      | **輸 QQQ**                           |
| 中性 29 隻 walk-forward（自適應 top_n）                                | 14.8%      | 0.66      | **輸 QQQ**                           |
| 買入持有 QQQ（同期）                                                   | 19.7-22.3% | 0.95-1.00 | —                                    |

**鐵證**：手揀含 SMH/QTUM 嘅 basket 贏 QQQ（28%），抽走嗰兩隻後見之明贏家即刻變 11%；用中性規則 universe（point-in-time、含死過嘅主題）+ walk-forward 公正測試 → 16% / Sharpe 0.71，**輸 QQQ**。
**但有分散價值**：2020 +97%、2022 喺 QQQ 崩盤時仲 +4%。性格同 QQQ 唔同，可做配置一部分降回撤，但**唔係 QQQ-killer**。牛市踏空、亂世防守、全週期淨輸。

---

## 4. 基本面因子 —— 同樣輸 QQQ

用投資得到嘅因子 ETF 做乾淨測試（2016-2026，無 survivorship/前視）：

| 因子 ETF        | CAGR      | Sharpe   |
| --------------- | --------- | -------- |
| **QQQ（基準）** | **22.1%** | **0.99** |
| MTUM 動量       | 18.2%     | 0.88     |
| QUAL 質素       | 14.6%     | 0.83     |
| VLUE 價值       | 14.7%     | 0.78     |
| COWZ 自由現金流 | 12.8%     | 0.70     |
| USMV 低波動     | 10.3%     | 0.74     |
| VTV 大型價值    | 12.1%     | 0.76     |

**全部輸。** `../stock-screener` 個 screen 嘅 value+quality+FCF flavor（≈ VLUE/QUAL/COWZ）正正係最弱嗰批。
**注意**：呢個係 regime bet —— value 喺 value 當道年代會反贏，但你揀 QQQ 做對手就係揀咗 value 最唔利嘅戰場。screener 唔廢，係 regime hedge / value watchlist，唔係 QQQ-killer。

---

## 5. 唯一 work 嘅嘢（全部唔係「新指標」）

| 做法                                                   | CAGR  | Sharpe | 最大回撤 | 性質                         |
| ------------------------------------------------------ | ----- | ------ | -------- | ---------------------------- |
| top5 動量 + QQQ 托底（乾淨，無槓桿）                   | 19.5% | 0.95   | -30.6%   | risk-adjusted 微贏（回撤細） |
| 上者 + **1.15x 槓桿**                                  | 21.7% | 0.93   | -34.6%   | 同風險、更高回報             |
| 上者 + **vol-target 26% cap2**（vol-managed momentum） | 24.2% | 0.95   | -30.1%   | 穩陣「住半山」版本           |
| 上者 + **vol-target 30% cap2**                         | 26.1% | 0.94   | -33.9%   | 大幅跑贏版，回撤仍細過 QQQ   |
| 上者 + **vol-target 30% cap2.5**                       | 27.4% | 0.93   | -33.9%   | 進取版，低波貼近 2.5x        |
| 單一 QQQ + vol-target（**要槓桿**，cap 2x）            | ~25%  | ~0.95  | ~-36%    | 無槓桿則輸（18.1% < 19.7%）  |

**機制**：

- **波動率目標**（Moreira-Muir 2017）：曝險 = 目標波幅 / 實際波幅。平靜加注、波動減注。唯一有學術根據又跨參數穩健嘅 TA，但本質係**擇時槓桿 + 減回撤**。
- **槓桿**：把「回撤比 QQQ 細」嘅裕度換成回報。
- 兩者 raw return 提升都靠 leverage，唔係無中生有嘅 alpha；融資成本 + 跌市槓桿放大損失要計。

### 5.1 「住半山」嘅秘密：唔係永遠加槓桿，而係低波上山、高波落山

用 `scripts/research_vol_target_secret.py` 同 `scripts/sweep_vol_target_momentum.py` 拆開固定槓桿 vs vol-target 後，最清楚嘅答案係：

| Case                      | CAGR  | 最大回撤 | Sharpe | 平均曝險 | 低波曝險 | 高波曝險 | 融資 drag | 調倉成本 |
| ------------------------- | ----- | -------- | ------ | -------- | -------- | -------- | --------- | -------- |
| QQQ buy hold              | 19.4% | -35.1%   | 0.96   | 1.00x    | 1.00x    | 1.00x    | 0.00%     | 0.01%    |
| QQQ fixed 1.5x            | 26.5% | -50.6%   | 0.92   | 1.50x    | 1.50x    | 1.50x    | 1.50%     | 0.01%    |
| QQQ VT 30 cap2            | 27.0% | -41.1%   | 0.96   | 1.64x    | 1.90x    | 1.27x    | 2.01%     | 0.47%    |
| QQQ VT 26 cap2            | 24.2% | -36.7%   | 0.95   | 1.51x    | 1.77x    | 1.16x    | 1.66%     | 0.56%    |
| top5+QQQ fixed 1.15x      | 21.9% | -34.6%   | 0.94   | 1.15x    | 1.15x    | 1.15x    | 0.45%     | 0.01%    |
| **top5+QQQ VT 26 cap2**   | 24.4% | -30.1%   | 0.95   | 1.49x    | 1.78x    | 1.08x    | 1.61%     | 0.53%    |
| **top5+QQQ VT 30 cap2**   | 26.1% | -33.9%   | 0.94   | 1.62x    | 2.00x    | 1.02x    | 1.92%     | 0.46%    |
| **top5+QQQ VT 30 cap2.5** | 27.4% | -33.9%   | 0.93   | 1.77x    | 2.48x    | 1.02x    | 2.40%     | 0.76%    |
| top5+QQQ VT 22 cap2       | 21.8% | -25.7%   | 0.96   | 1.33x    | 1.57x    | 0.99x    | 1.21%     | 0.63%    |

**秘密唔係「1.5x 長揸」**。固定 1.5x QQQ CAGR 高，但最大回撤去到 -50% 左右，Sharpe 反而差。真正有用嘅係 **vol-timed leverage**：

- 平靜市（低 realized vol）升到約 **1.7-1.8x**，食足牛市 trend。
- 風大時（高 realized vol）降到約 **1.0-1.2x**，唔係清倉，係「住半山」：仲有 exposure，但唔企山頂硬食瀑布。
- 配合 `top5 + QQQ 托底` 本身回撤細過 QQQ，vol-target 26% cap2 做到 **24% CAGR / -30% 回撤**；再提高到 30% target vol，做到 **26% CAGR / -34% 回撤**，仍細過 QQQ 約 -35%。
- 5% 融資壓力下仍然成立，但 edge 會縮：`top5+QQQ VT 30 cap2` 約 **24.5% CAGR / -34.0% 回撤**；`cap2.5` 約 **25.4% CAGR / -34.0% 回撤**。
- `VT30 cap2.5` 係目前最高可接受候選，但低波會貼住 **2.5x**，融資同 margin 壓力大；實盤更合理嘅第一版本係 `VT30 cap2` 或保守嘅 `VT26 cap2`。
- **更精準講：Top5+QQQ 唔係加速器，係避震器。** 單用 QQQ 做 VT30 cap2 其實 CAGR 更高（27.0% vs 26.1%），但回撤惡化到 **-41.1%**；Top5+QQQ 用約 0.9pp CAGR 換返約 7.2pp 回撤改善（-33.9%），先做到「跑贏但唔企山頂」。

所以「跑贏 QQQ」嘅實際結構係：**先搵一個 Sharpe 接近 QQQ、回撤較細嘅 base portfolio，再用 vol-target 把曝險搬去低波 regime；唔係再搵 RSI/MACD 呢啲訊號。**

### 5.2 進一步拆解：alpha 來自低波 regime，高波只係防守

用 `scripts/attribute_vol_target_regime.py --vol-target 0.30 --max-leverage 2` 拆 daily return：

| 波幅分位 | 日數 | 平均曝險 | 策略年化日均 | QQQ 年化日均 | 年化超額 |
| -------- | ---- | -------- | ------------ | ------------ | -------- |
| Q1 低波  | 1025 | 2.00x    | 33.1%        | 19.1%        | +14.0%   |
| Q2       | 1024 | 1.97x    | 44.2%        | 27.6%        | +16.6%   |
| Q3       | 1024 | 1.54x    | 18.5%        | 18.0%        | +0.6%    |
| Q4 高波  | 1024 | 1.02x    | 15.2%        | 16.1%        | -0.9%    |

**真正賺超額嘅地方係 Q1/Q2 低波：幾乎滿 2x，食低波趨勢延續。** 到 Q4 高波，策略只係降到約 1x，目的係保命而唔係賺 alpha；高波 regime 本身仲略輸 QQQ。

逐年亦唔係穩贏：2020、2023、2026 YTD 都輸 QQQ，因為 QQQ 單邊強升但策略因高波/選股冇滿倉追晒。真正大贏年份係 2013、2019、2022（少跌）、2024。即係呢套策略嘅心理成本係：**你會喺某啲強 QQQ 年份明顯落後，但長期靠低波加注 + 高波少跌追返。**

### 5.2b 成分拆解：唔係選股 alpha，係 exposure timing

`VT30 cap2` 嘅 return component：

| Component        | CAGR / drag | 解讀                                   |
| ---------------- | ----------: | -------------------------------------- |
| QQQ buy hold     |       19.4% | 基準                                   |
| Base top5+QQQ    |       19.5% | 選股 + QQQ floor，本身幾乎只係打和 QQQ |
| Gross vol-target |       29.1% | 把 base return 乘動態曝險，未扣成本    |
| Financing drag   |    -1.9%/年 | 借入部分融資成本                       |
| Rebalance cost   |    -0.5%/年 | 調整曝險成本                           |
| Net vol-target   |       26.1% | 扣成本後結果                           |

呢張表係最重要嘅反直覺位：**Top5 選股本身唔係 alpha engine；真正 alpha-like 效果係「低波時放大 beta，高波時收縮 beta」嘅 exposure timing。** 選股 + QQQ floor 嘅作用係提供一個回撤略細、行為接近 QQQ 嘅 base，方便 vol-target 用槓桿放大，而唔係靠選股本身大幅跑贏。

### 5.2c QQQ-only 對照：更快，但唔係「住半山」

`scripts/research_vol_target_secret.py` 修正咗最新日價格 `ffill()` 後，可重現 QQQ-only vs Top5+QQQ：

| Case               |  CAGR |  MaxDD | Sharpe | 解讀                                       |
| ------------------ | ----: | -----: | -----: | ------------------------------------------ |
| QQQ VT30 cap2      | 27.0% | -41.1% |   0.96 | 最快，但風險已明顯高過 QQQ；似山頂多過半山 |
| Top5+QQQ VT30 cap2 | 26.1% | -33.9% |   0.94 | 慢少少，但回撤細過 QQQ；先係可落地半山版   |
| QQQ VT26 cap2      | 24.2% | -36.7% |   0.95 | 接近半山，但回撤仍大過 Top5+QQQ VT26       |
| Top5+QQQ VT26 cap2 | 24.2% | -30.1% |   0.95 | 保守半山版                                 |

所以如果目標只係「最高 CAGR」，QQQ-only VT30 反而贏；但如果目標係「跑贏 QQQ 同時回撤唔大過 QQQ」，Top5+QQQ 先有用。**Top5+QQQ 嘅 edge 係把 base portfolio 變得更適合加槓桿，而唔係本身大幅跑贏。**

### 5.2d 實盤揀 VT22 / VT26 / VT30：其實係回撤預算

呢幾個版本唔係「邊個最醒」，而係你肯接受幾多回撤：

| 版本               |  CAGR |  MaxDD | 平均曝險 | 適合情境                              |
| ------------------ | ----: | -----: | -------: | ------------------------------------- |
| Top5+QQQ VT22 cap2 | 21.6% | -25.7% |    1.33x | 想明顯低過 QQQ 回撤，接受只係小幅跑贏 |
| Top5+QQQ VT26 cap2 | 24.2% | -30.1% |    1.49x | 保守主線；回撤 cushion 最大           |
| Top5+QQQ VT30 cap2 | 26.1% | -33.9% |    1.62x | 進取主線；仍保持回撤細過 QQQ          |
| QQQ VT30 cap2      | 27.0% | -41.1% |    1.64x | 只追 CAGR；唔符合「半山」風險要求     |

實盤規則可以好簡單：

- 如果你最怕 -35% 以上回撤：用 **VT26 cap2**。
- 如果你接受接近 QQQ 嘅回撤，想要更高 CAGR：用 **VT30 cap2**。
- 如果你想先細注試 execution / 融資 / 滑點：用 **VT22 cap2** 或 VT26。
- 唔好用 **QQQ-only VT30** 當主策略；佢證明 vol-target 有力，但回撤已經超出「住半山」定義。

換句話講：**VT30 cap2 係而家最好嘅主攻版；VT26 cap2 係心理同 margin 更易頂嘅長跑版。**

### 5.2e 真正「大幅跑贏」有兩類：半山版 vs 山頂版

如果目標由「跑贏 QQQ 但回撤唔差過 QQQ」放寬到「大幅跑贏 QQQ」，答案會變清楚：

| 類型              | 代表                       |       CAGR |        MaxDD | 解讀                                                 |
| ----------------- | -------------------------- | ---------: | -----------: | ---------------------------------------------------- |
| 半山主攻          | Top5+QQQ VT30 cap2         |      26.1% |       -33.9% | 大幅跑贏，同時回撤仍細過 QQQ                         |
| 半山進取          | Top5+QQQ VT30 cap2.5       |      27.5% |       -33.9% | 更高 CAGR，但低波貼 2.5x，margin 壓力大              |
| 參數進取主候選    | L126 top10 VT34 W40 cap2.5 |      30.3% |       -39.8% | 現有 sweep 最高；5% 融資後仍 27.6%，但平均 2.0x 曝險 |
| 槓桿 ETF 受控     | QLD/TQQQ VT30 cap1-1.5     | 26.5-27.9% | -41% 至 -43% | 用槓桿 ETF 降曝險，仍比 QQQ 深回撤                   |
| 槓桿 ETF 趨勢濾網 | TQQQ QQQ>200D else QQQ     |      39.4% |       -58.8% | 200D filter 改善 TQQQ，但仍係深回撤                  |
| 槓桿 ETF 趨勢濾網 | QLD QQQ>200D else QQQ      |      29.4% |       -48.0% | 比 QLD buy-hold 好頂啲，但仍非半山                   |
| 山頂版            | QLD buy hold               |      32.4% |       -63.7% | 大幅跑贏，但要頂 -60% 以上                           |
| 山頂爆裂版        | TQQQ buy hold              |      43.9% |       -81.7% | CAGR 最誇張，但心理同倉位風險極端                    |

結論唔係「TQQQ 最好」。**大幅跑贏一定係用更多 convex beta / leverage 換返嚟。** 200D trend filter 確實可以改善 TQQQ buy-hold（-81.7% → -58.8%），但仍然唔係可輕鬆長期持有。 如果要保留「可以長期執行」呢個條件，最合理仍係 Top5+QQQ VT30 cap2；如果只問「點樣大幅跑贏」，QLD/TQQQ buy-hold 或 trend-filter 版本會贏更多，但回撤會深到好多投資者中途斬倉。

`L126 top10 VT34 W40 cap2.5` 係暫時最強「高風險但未到 TQQQ」候選：

```sh
uv run python scripts/backtest_momentum_rotation.py \
  --universe-json sp500_top_10_market_cap_2010_2026.json \
  --top-n 10 --index-floor QQQ \
  --vol-target 0.34 --vol-window 40 --max-leverage 2.5 --rebal-band 0.05 \
  --financing-rate 0.03 --rebalance monthly --cost-bps 15 \
  --start 2010-01-01 --output-csv '' --plot-path ''
```

關鍵數字：

- 3% 融資：**30.3% CAGR / -39.8% MaxDD / Sharpe 0.97 / 平均曝險 2.02x**。
- 5% 融資：**27.6% CAGR / -40.2% MaxDD / Sharpe 0.91**。
- 剔除 2024 後仍有 **26.7% CAGR**，超 QQQ 約 **+7.7pp**；唔係完全靠 2024，但大年份集中度高。
- 輸 QQQ 年份包括 2011、2015、2018、2020、2026 YTD；心理成本係高波/單邊 QQQ 年份會明顯落後。

`scripts/stress_test_momentum_candidates.py` 再用融資、成本、起始年、cap 做壓力測試：

| 測試                          |         Top5 VT30 cap2 |          Top10 VT34 cap2.5 | 解讀                                        |
| ----------------------------- | ---------------------: | -------------------------: | ------------------------------------------- |
| 3% 融資                       | 26.1% CAGR / -33.9% DD |     30.3% CAGR / -39.8% DD | baseline                                    |
| 5% 融資                       |         24.5% / -34.0% |             27.6% / -40.2% | 兩者仍明顯跑贏 QQQ                          |
| 8% 融資                       |         22.1% / -34.1% |             23.7% / -40.7% | edge 大幅縮，但仍贏 QQQ；Top10 回撤更深     |
| 50bps 成本                    |         21.2% / -34.7% |             25.2% / -41.8% | 高成本會食走好多 edge                       |
| 2014 起步                     |         23.5% / -33.9% |             29.9% / -39.8% | Top10 起始年敏感度較低                      |
| 2020 起步                     |         26.3% / -33.9% |             35.7% / -39.8% | Top10 受惠 2024 大年更明顯                  |
| Top10 cap2 / cap2.25 / cap2.5 |                      — | 27.5% / 29.1% / 30.3% CAGR | cap 越高越快，但回撤由 -38.7% 加深到 -39.8% |

壓力測試後嘅排序更清楚：

- **實盤主攻**：Top5 VT30 cap2。5% 融資仍有約 +5.1pp CAGR 超額，回撤仍略細過 QQQ；成本升到 50bps 後只剩 +1.8pp，代表實盤滑點要嚴控。
- **高風險主候選**：Top10 VT34 cap2.5。CAGR 明顯高一截，8% 融資仍約 +4.3pp 超額；但最大回撤長期比 QQQ 深約 4-6pp，平均曝險約 2x，唔係「半山」。
- **cap2 折衷版**：Top10 VT34 cap2 有 **27.5% CAGR / -38.7% DD**，比 cap2.5 少約 2.7pp CAGR，但回撤同 margin 壓力細啲。

### 5.2f 今日應該企山腰邊度

主回測而家會輸出最新 realized vol 同 target exposure：

```sh
uv run python scripts/backtest_momentum_rotation.py \
  --universe-json sp500_top_10_market_cap_2010_2026.json \
  --top-n 5 --index-floor QQQ \
  --vol-target 0.30 --vol-window 40 --max-leverage 2 --rebal-band 0.05 \
  --financing-rate 0.03 --rebalance monthly --cost-bps 15 \
  --start 2010-01-01 --output-csv '' --plot-path ''
```

2026-06-15 snapshot：

| 指標         | 數值  |
| ------------ | ----- |
| 最新實際波幅 | 21.8% |
| 最新目標曝險 | 1.37x |
| 最新有效曝險 | 1.38x |

解讀：而家唔係低波滿倉 2x，也唔係高波縮到 1x；係中間偏保守嘅 **1.4x 山腰位**。呢個數先係實盤每日要跟嘅核心，不係長期平均 1.62x。

### 5.3 年份集中度：2024 好重要，但唔係唯一支柱

`attribute_vol_target_regime.py` 加咗 leave-one-year-out 後，`VT30 cap2` 嘅超額來源更清楚：

| 最強超額年份 | 策略  | QQQ   | 超額   |
| ------------ | ----- | ----- | ------ |
| 2024         | 83.7% | 25.6% | +58.1% |
| 2013         | 68.0% | 36.6% | +31.4% |
| 2019         | 61.9% | 39.0% | +23.0% |
| 2010         | 33.0% | 18.4% | +14.6% |
| 2011         | 16.9% | 3.5%  | +13.5% |

| 最差超額年份 | 策略  | QQQ   | 超額   |
| ------------ | ----- | ----- | ------ |
| 2026 YTD     | -6.6% | 21.3% | -27.9% |
| 2020         | 30.4% | 48.4% | -18.0% |
| 2023         | 39.5% | 54.9% | -15.3% |
| 2015         | 4.2%  | 9.4%  | -5.2%  |
| 2018         | -1.4% | -0.1% | -1.2%  |

剔除單一年重新計 CAGR：

| 剔除年份 | 策略 CAGR | QQQ CAGR | 超額 CAGR |
| -------- | --------- | -------- | --------- |
| 2024     | 23.0%     | 19.1%    | +4.0pp    |
| 2013     | 23.8%     | 18.4%    | +5.4pp    |
| 2019     | 24.1%     | 18.3%    | +5.8pp    |

即係：**2024 係最大貢獻年，冇咗 2024，edge 由 +6.6pp 收窄到 +4.0pp，但仍然跑贏。** 呢套唔係完全靠單一年神蹟，但確實靠少數「低波 + base portfolio 大贏」年份拉開距離。實盤心理上要接受 2020/2023 呢類 QQQ 爆升年份會輸一大截。

---

## 6. 想贏 QQQ 嘅三條真路（唔係搵指標）

1. **加槓桿** —— 認清係借風險。對住 Sharpe ≈ QQQ 嘅組合，1.15-2x 把回撤裕度換回報。
2. **賭 value/regime 轉勢** —— 用基本面 screener 揀平靚資產，等成長股 regime 終結。係 regime bet。
3. **換場** —— 去 QQQ 唔覆蓋、效率較低嘅市場（mid/small cap、期貨 CTA trend、crypto）。要 survivorship-clean point-in-time 數據先驗到。

---

## 7. 已建立嘅工具

| 檔案                                             | 用途                                                                                                                                                                    |
| ------------------------------------------------ | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `scripts/backtest_momentum_rotation.py`          | 主回測：修前視（shift 1）、成本（--cost-bps）、monthly rebalance、`--top-n`、`--index-floor`、`--leverage`、`--universe-lag-years`、`--sweep-lookback`                  |
| `scripts/sweep_vol_target_momentum.py`           | 掃 `lookback/top_n/vol-target/window/cap`，搵大幅跑贏 QQQ 但回撤不差過 QQQ 嘅候選                                                                                       |
| `scripts/finviz_momentum_candidates.py`          | 用 `finvizfinance` 跑 `cap_midover,fa_eps5years_o20,fa_roe_o15`，按市值由大到細攞今日候選，再用 126D momentum 排 Top5/Top10；只係 forward screener，唔當歷史 alpha 證據 |
| `scripts/research_stock_selection_strategies.py` | 純選股研究：lagged Top10 universe 入面比較 momentum / risk-adjusted momentum / low-vol 選股，對 SPY 同 QQQ 做 benchmark                                                 |
| `scripts/research_vol_target_secret.py`          | 拆解固定槓桿 vs vol-target，輸出平均/低波/高波曝險、融資 drag、調倉成本                                                                                                 |
| `scripts/research_leveraged_etf_vol_target.py`   | 測 QQQ/QLD/TQQQ buy-hold 同 vol-target，確認「大幅跑贏」其實係更深回撤換回報                                                                                            |
| `scripts/attribute_vol_target_regime.py`         | 拆解 vol-target 策略喺低波/高波/逐年嘅 return attribution，確認「住半山」贏喺邊、輸喺邊                                                                                 |
| `scripts/stress_test_momentum_candidates.py`     | 對 Top5/Top10 vol-target 候選做融資、成本、起始年、cap 壓力測試                                                                                                         |
| `scripts/pit_backtest_momentum_rotation.py`      | survivorship-free 闊池 engine：point-in-time membership + 退市股票處理（食 Norgate/CRSP CSV，`--demo` 有合成示範）                                                      |
| `scripts/simulate_momentum_rotation.py`          | Futu 模擬盤落單：`--top-n --index-floor --leverage` / `--vol-target` / `--rebal-band`                                                                                   |
| `algo_trading/market_cap_universe.py`            | 年度 + 季度（dated）point-in-time universe，含 lag                                                                                                                      |
| `pine/vol_target_strategy.pine`                  | TradingView vol-target strategy（單一標的；要開 margin 先贏，靠槓桿）                                                                                                   |
| `STRATEGY.md`                                    | top5 + QQQ 托底 × 1.15 完整規格                                                                                                                                         |

---

## 8. 數據局限（未完成嘅嚴謹度）

- 價格用 Yahoo（survivorship：只有現存上市股）。真正乾淨要 Norgate/CRSP（含退市股票全價）。
- 市值 universe = 年度快照；理想要季度 point-in-time。
- 基本面只得當前快照（Finviz），冇歷史 → 因子 backtest 要 SimFin/Sharadar 歷史基本面，或者用因子 ETF 代理（已做）。
- 所有結果仍係 backtest；真錢未行過。落注前細注實盤跑一排，確認成交/滑點/融資利率夾到。

---

## 9. 最終一句

> **冇捷徑跑贏 QQQ。** 認清 QQQ 已經係極強嘅基準、用乾淨紀律避免自欺、想要更多回報就誠實咁加槓桿或換場 —— 呢個就係成個調查由技術分析掘到基本面、始終如一嘅答案。
