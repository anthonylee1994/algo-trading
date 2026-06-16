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

| 做法                                              | CAGR  | Sharpe | 最大回撤 | 性質                         |
| ------------------------------------------------- | ----- | ------ | -------- | ---------------------------- |
| top5 動量 + QQQ 托底（乾淨，無槓桿）              | 19.5% | 0.95   | -30.6%   | risk-adjusted 微贏（回撤細） |
| 上者 + **1.15x 槓桿**                             | 21.7% | 0.93   | -34.6%   | 同風險、更高回報             |
| 上者 + **vol-target 26%**（vol-managed momentum） | 24.3% | 0.95   | -29.6%   | 最強組合（2010+）            |
| 單一 QQQ + vol-target（**要槓桿**，cap 2x）       | ~25%  | ~0.95  | ~-36%    | 無槓桿則輸（18.1% < 19.7%）  |

**機制**：

- **波動率目標**（Moreira-Muir 2017）：曝險 = 目標波幅 / 實際波幅。平靜加注、波動減注。唯一有學術根據又跨參數穩健嘅 TA，但本質係**擇時槓桿 + 減回撤**。
- **槓桿**：把「回撤比 QQQ 細」嘅裕度換成回報。
- 兩者 raw return 提升都靠 leverage，唔係無中生有嘅 alpha；融資成本 + 跌市槓桿放大損失要計。

### 5.1 「住半山」嘅秘密：唔係永遠加槓桿，而係低波上山、高波落山

用 `scripts/research_vol_target_secret.py` 拆開固定槓桿 vs vol-target 後，最清楚嘅答案係：

| Case                      | CAGR  | 最大回撤 | Sharpe | 平均曝險 | 低波曝險 | 高波曝險 | 融資 drag | 調倉成本 |
| ------------------------- | ----- | -------- | ------ | -------- | -------- | -------- | --------- | -------- |
| QQQ buy hold              | 19.4% | -35.1%   | 0.96   | 1.00x    | 1.00x    | 1.00x    | 0.00%     | 0.01%    |
| QQQ fixed 1.5x            | 26.5% | -50.6%   | 0.92   | 1.50x    | 1.50x    | 1.50x    | 1.50%     | 0.01%    |
| QQQ VT 26 cap2            | 24.2% | -36.7%   | 0.95   | 1.51x    | 1.77x    | 1.16x    | 1.66%     | 0.56%    |
| top5+QQQ fixed 1.15x      | 21.9% | -34.6%   | 0.94   | 1.15x    | 1.15x    | 1.15x    | 0.45%     | 0.01%    |
| **top5+QQQ VT 26 cap2**   | 24.4% | -30.1%   | 0.95   | 1.49x    | 1.78x    | 1.08x    | 1.61%     | 0.53%    |
| top5+QQQ VT 22 cap2       | 21.8% | -25.7%   | 0.96   | 1.33x    | 1.57x    | 0.99x    | 1.21%     | 0.63%    |

**秘密唔係「1.5x 長揸」**。固定 1.5x QQQ CAGR 高，但最大回撤去到 -50% 左右，Sharpe 反而差。真正有用嘅係 **vol-timed leverage**：

- 平靜市（低 realized vol）升到約 **1.7-1.8x**，食足牛市 trend。
- 風大時（高 realized vol）降到約 **1.0-1.2x**，唔係清倉，係「住半山」：仲有 exposure，但唔企山頂硬食瀑布。
- 配合 `top5 + QQQ 托底` 本身回撤細過 QQQ，vol-target 26% cap2 先做到 **24% CAGR 但回撤約 -30%**。
- 5% 融資壓力下仍然成立：`top5+QQQ VT 26 cap2` 約 **23.1% CAGR / -30.1% 回撤**；edge 會縮，但唔係靠 3% 融資假設先有。

所以「跑贏 QQQ」嘅實際結構係：**先搵一個 Sharpe 接近 QQQ、回撤較細嘅 base portfolio，再用 vol-target 把曝險搬去低波 regime；唔係再搵 RSI/MACD 呢啲訊號。**

---

## 6. 想贏 QQQ 嘅三條真路（唔係搵指標）

1. **加槓桿** —— 認清係借風險。對住 Sharpe ≈ QQQ 嘅組合，1.15-2x 把回撤裕度換回報。
2. **賭 value/regime 轉勢** —— 用基本面 screener 揀平靚資產，等成長股 regime 終結。係 regime bet。
3. **換場** —— 去 QQQ 唔覆蓋、效率較低嘅市場（mid/small cap、期貨 CTA trend、crypto）。要 survivorship-clean point-in-time 數據先驗到。

---

## 7. 已建立嘅工具

| 檔案                                        | 用途                                                                                                                                                   |
| ------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `scripts/backtest_momentum_rotation.py`     | 主回測：修前視（shift 1）、成本（--cost-bps）、monthly rebalance、`--top-n`、`--index-floor`、`--leverage`、`--universe-lag-years`、`--sweep-lookback` |
| `scripts/pit_backtest_momentum_rotation.py` | survivorship-free 闊池 engine：point-in-time membership + 退市股票處理（食 Norgate/CRSP CSV，`--demo` 有合成示範）                                     |
| `scripts/simulate_momentum_rotation.py`     | Futu 模擬盤落單：`--top-n --index-floor --leverage`                                                                                                    |
| `algo_trading/market_cap_universe.py`       | 年度 + 季度（dated）point-in-time universe，含 lag                                                                                                     |
| `pine/vol_target_strategy.pine`             | TradingView vol-target strategy（單一標的；要開 margin 先贏，靠槓桿）                                                                                  |
| `STRATEGY.md`                               | top5 + QQQ 托底 × 1.15 完整規格                                                                                                                        |

---

## 8. 數據局限（未完成嘅嚴謹度）

- 價格用 Yahoo（survivorship：只有現存上市股）。真正乾淨要 Norgate/CRSP（含退市股票全價）。
- 市值 universe = 年度快照；理想要季度 point-in-time。
- 基本面只得當前快照（Finviz），冇歷史 → 因子 backtest 要 SimFin/Sharadar 歷史基本面，或者用因子 ETF 代理（已做）。
- 所有結果仍係 backtest；真錢未行過。落注前細注實盤跑一排，確認成交/滑點/融資利率夾到。

---

## 9. 最終一句

> **冇捷徑跑贏 QQQ。** 認清 QQQ 已經係極強嘅基準、用乾淨紀律避免自欺、想要更多回報就誠實咁加槓桿或換場 —— 呢個就係成個調查由技術分析掘到基本面、始終如一嘅答案。
