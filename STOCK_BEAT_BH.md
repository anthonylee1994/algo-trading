# 個股點 apply Best Strategy 又打得贏 Buy&Hold？

> 研究對象：GOOGL（Alphabet／GOOG 同系）+ 一籃 mega-cap 對照  
> 腳本：`scripts/research_stock_beat_bh.py`  
> 日期：2026-07

---

## TL;DR（GOOG／GOOGL）

| 做法                              | Full CAGR |       09+ |       19+ | 打唔打得贏死揸？           |
| --------------------------------- | --------: | --------: | --------: | -------------------------- |
| **Buy&Hold**                      |     25.5% |     24.3% |     29.2% | 基準                       |
| 雙引擎（best dual）               |     12.3% |     14.2% |     21.1% | **大輸**（三期全輸）       |
| MA200 濾網                        |     14.2% |     15.6% |     21.7% | **輸**                     |
| Dual × Vol-Target                 |     19.1% |     20.5% |     27.6% | **仍輸**（仲有空倉）       |
| **Vol-Target 35% cap2 長期 long** | **34.8%** | **31.8%** | **36.1%** | **三期全贏**               |
| 固定 1.5x                         |     33.8% |     32.6% |     39.5% | 贏，但 DD 更殘、無波動調節 |

**結論：個股（尤其 GOOG 呢類長牛 mega-cap）唔好用「雙引擎離場」去贏死揸 CAGR。  
要用「長期在場 + Vol-Target 槓桿」。**

GOOGL 上 VT35 平均槓桿約 **1.38x**（約 79% 時間 >1x）——贏就贏喺呢度，唔係贏喺選時。

---

## 1. 點解雙引擎 apply 落 GOOG 會輸？

同 SMH 同一病理：

1. **長牛 + 高漂移**：死揸 exposure ≈ 100%
2. **雙引擎**經常空倉（假突破、等 RSI、止蝕）→ exposure 往往得六成
3. 避過嘅回撤 **補唔返** 錯過嘅升幅

GOOGL 數字極清楚：死揸 full **25.5%** vs 雙引擎 **12.3%** —— 差一截。

所以：

- Best dual 仍然適合 **指數風險管理**（QQQ/SPY）
- **唔適合**當「贏 GOOG 死揸」嘅工具

---

## 2. 邊條先係「個股 best」？

### 推薦（GOOGL／類似中低波 mega-cap）

```
永久 long 該股票
每日（或每週）:
  realizedVol = stdev(日回報, 40) * sqrt(252)
  lev = clamp( targetVol / realizedVol, minLev, maxLev )
  持倉市值 = 帳戶權益 × lev
```

| 參數       | GOOGL 建議            | 說明                         |
| ---------- | --------------------- | ---------------------------- |
| targetVol  | **30–35%**            | 接近或略高過股自身中位波動   |
| vol window | 40 日                 | 同組合研究一致               |
| maxLev     | **1.5–2.0**           | 2.0 更進取；1.5 保守啲       |
| minLev     | 0.25–0.5              | 高波減倉但唔清倉（保持在場） |
| 融資       | 實盤要計（回測用 3%） | TV/MAI 往往唔扣利息          |

GOOGL 驗證（5bps + 3% fin）：

| 配置          | 09+ CAGR vs BH       | 19+ vs BH            |
| ------------- | -------------------- | -------------------- |
| VT30 cap1.5   | 27.9% vs 24.3% ✓     | 30.8% vs 29.2% ✓     |
| **VT35 cap2** | **31.8% vs 24.3% ✓** | **36.1% vs 29.2% ✓** |
| VT40 cap2     | 34.7% vs 24.3% ✓     | 38.8% ✓（更進取）    |

### 固定槓桿？

`Fixed 1.25x / 1.5x` 喺 GOOGL 都贏，但：

- 2000 型熊市／個股閃崩會更易爆
- 無「高波自動減碼」
- **優先 VT，其次先考慮固定槓桿**

---

## 3. 唔係每隻股 VT35 都 win——先量波動

| 股票     | 平均實現波動 | VT35 平均槓桿 | 09+ VT vs BH          |
| -------- | -----------: | ------------: | --------------------- |
| MSFT     |          24% |         1.55x | **贏**                |
| GOOGL    |          28% |         1.38x | **贏**                |
| SMH      |          27% |         1.42x | **贏**                |
| AAPL     |          30% |         1.31x | **贏**                |
| AMZN     |          35% |         1.15x | 09 贏、19 可能輸      |
| META     |          36% |         1.13x | **容易輸**            |
| **NVDA** |      **45%** |     **0.89x** | **輸**（常年低於 1x） |

**法則：**

```
若 中位年化波動 ≲ 32–35%  →  targetVol=35%, cap=2  通常可試贏死揸
若 中位波動 ≳ 40%（NVDA 類）→  固定 35% 會令平均槓桿 <1 → 輸死揸
                              →  改用 adaptive：
                                 targetVol ≈ 1.3 × 中位波動
                                 或 targetVol=50%, cap=2.5
                                 （CAGR 可贏，DD 會好醜）
```

NVDA 例：`target = medianVol × 1.3 ≈ 54%` → 09+ 可贏死揸，但 MaxDD 可去到 **-70%** 級。

---

## 4. 落地流程（拿 GOOG 當例）

### Step 0：標的

- 長歷史回測用 **GOOGL**（2004+）
- 實盤 Class C 用 **GOOG** 同一套參數即可（價位不同、波幅結構極近）

### Step 1：量自身波動（40 日年化）

```text
中位 vol ≈ 26%（GOOGL 歷史）→ 屬「VT35 友好」區
```

### Step 2：揀 profile

| 你嘅目標                     | Profile                                |
| ---------------------------- | -------------------------------------- |
| CAGR 打得贏死揸，接受 margin | **Stock Vol-Target**（長期 long + VT） |
| 少操作、瞓得着               | **老實 B&H**（唔好假積極）             |
| 減回撤、接受少賺             | 雙引擎／MA 濾網（**唔係**為贏 CAGR）   |

### Step 3：參數（GOOG 預設）

```text
targetVol = 35%
volLen    = 40
maxLev    = 2.0
minLev    = 0.25
rebalance = daily 或 weekly（weekly 摩擦少啲）
financing = 你券商實際利率
```

### Step 4：執行

- 富途：`futu/best_strategy_mai.txt` 設 `USEVT:=1`（顯示建議槓桿；要自己按帳戶調倉）
- TV：`pine/best_strategy.pine` → 模式 **SMH Vol-Target**（邏輯通用，唔限 SMH）
- 手動：每週一看「建議 lev」，把 GOOG 市值調到 `權益 × lev`

### Step 5：風控紅線

1. 單股 VT 係 **集中度風險** —— 建議只佔組合一部分（例如總權益 10–25% 做呢套）
2. MaxDD 仍可 **-45%～-65%**（GOOGL VT full 約 -62%）
3. 融資斷供／強制平倉 = 遊戲結束
4. 除淨／拆股：用調整後價格計 vol

---

## 5. 決策樹（可複用到其他個股）

```
想 CAGR 贏該股 B&H？
│
├─ 可以借錢 / 用 margin？
│   ├─ NO → 幾乎只好 B&H（技術離場長期輸長牛）
│   └─ YES
│         ├─ 計 40D 中位年化 vol
│         ├─ vol ≲ 35% → VT target 30–35%, cap 1.5–2.0
│         ├─ vol ≳ 40% → target ≈ 1.3×medianVol, cap 2–2.5（接受更大 DD）
│         └─ 回測 full / 09 / 19 三段 CAGR 同 DD，三段都贏先上實盤
│
└─ 只想風險管理、唔搶 CAGR
      → 雙引擎 / MA200（接受輸死揸報酬）
```

---

## 6. 咩唔好做

1. **硬套雙引擎贏 GOOG 死揸** —— 數據否定
2. **Dual 訊號先准許加 VT** —— 空倉拖死，GOOGL 三期仍輸
3. **無腦 2x 永久槓桿** —— 09+ 可能靚，遇結構性熊會更慘
4. **NVDA 用 VT35 當聖盃** —— 高波股會被「系統性減碼」
5. **全部身家一隻股 VT** —— 單票 + 槓桿 = 爆倉輪盤

---

## 7. 重跑研究

```bash
uv run python scripts/research_stock_beat_bh.py
# 或指定
uv run python scripts/research_stock_beat_bh.py --tickers GOOGL,AAPL,MSFT
```

輸出：

- `output/googl_beat_bh_detail.csv`
- `output/goog_beat_bh_cross.csv`

---

## 8. 一句收尾

> **GOOG 要打得贏 buy&hold：唔係改入場指標，而係「唔離場 + 低波加槓桿」。**  
> 雙引擎留給指數減風險；個股長牛用 **Vol-Target 版 best strategy**。
