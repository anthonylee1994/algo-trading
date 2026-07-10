# 最佳策略（綜合結論）

> 2026-07 更新：**想 CAGR 跑贏 SMH 死揸，要用 Vol-Target，唔係雙引擎。**

---

## 核心真相

| 目標                       | 做法                                | 點解                              |
| -------------------------- | ----------------------------------- | --------------------------------- |
| **CAGR 跑贏 SMH buy&hold** | **長期 long SMH + Vol-Target 槓桿** | 半導體牛極強；空倉 = 錯過升浪     |
| QQQ/SPY 風險管理           | 雙引擎（突破+RSI2）                 | 減 DD、Sharpe 佳；CAGR 未必贏死揸 |
| 組合贏 QQQ                 | Top5 動量 + QQQ floor × VT          | `STRATEGY.md`                     |

**雙引擎喺 SMH 上 09+ CAGR ~12% vs 死揸 ~28%——輸到仆街。**  
再調 %R / 均線 / 止蝕都救唔到，因為問題係 **不在場**，唔係入場準唔準。

---

## Profile A（預設）：SMH Vol-Target ← 贏死揸

### 公式

```
realizedVol = stdev(daily_return, 40) * sqrt(252)
leverage    = clip( targetVol / realizedVol, minLev, maxLev )
每天（或每週）把 SMH 曝險調到 equity × leverage
```

預設：`targetVol = 35%`，`maxLev = 2.0`，`minLev = 0.25`（高波只減倉唔清倉），`vol = 40 日`

### 回測（5bps + 3% 融資）

```bash
uv run python scripts/backtest_smh_vol_target.py
```

| 時段 | B&H CAGR | VT35 cap2（約） | 結果 |
| ---- | -------- | --------------- | ---- |
| Full | ~10.8%   | **~14%**        | 贏   |
| 09+  | ~28.2%   | **~32%**        | 贏   |
| 19+  | ~42.8%   | **~49%**        | 贏   |

進取版 VT40% 贏更多，DD 更深。

### 代價（一定要知）

1. **靠槓桿贏 CAGR**，唔係預測神技
2. Sharpe 未必贏 B&H；MaxDD 仍然可以 -70%～-85%
3. 要 **margin / 融資**；TV 回測往往 **唔扣融資利息** → 實盤 CAGR 會低啲
4. 只用 **SMH**（或極類似半導體 ETF）

### TradingView

1. 開 **SMH 日線**
2. 貼 `pine/best_strategy.pine`
3. 模式 = **SMH Vol-Target**
4. Properties 開 margin（策略已設 margin_long=50 ≈ 最多 2x）

---

## Profile B：雙引擎（QQQ/SPY）

```
突破: 15日新高 + MACD(5,35)>0 → 入; 20日新低 / -8% → 出
撈底: RSI2<15 + >200MA → 入; RSI2>75 / -4% → 出
```

適合：唔借錢、想細回撤。  
**唔適合：硬要 CAGR 贏 SMH 死揸。**

---

## 點解雙引擎改到贏唔到 SMH？

SMH 09+ 幾乎單邊牛：

- 死揸 exposure ≈ 100%
- 雙引擎 exposure ≈ 60–70%，仲要俾假突破打止蝕
- 錯過嘅升幅 > 避過嘅跌幅

所以要贏 CAGR 只有：

1. **減少空倉**（最好係唔空）
2. **低波加槓桿** 放大報酬

= Vol-Target。同 FINDINGS §1「raw CAGR 贏要靠曝險 timing」完全一致。

---

## 檔案

| 檔                                   | 用途                         |
| ------------------------------------ | ---------------------------- |
| `pine/best_strategy.pine`            | TradingView：雙引擎 + SMH VT |
| **`futu/best_strategy_mai.txt`**     | **富途 MAI 主圖指標**        |
| `scripts/backtest_smh_vol_target.py` | SMH 跑贏死揸驗證             |
| `scripts/backtest_best_composite.py` | 雙引擎對照                   |
| `STRATEGY.md`                        | 多資產真主策略               |

### 富途 MAI 用法

1. 牛牛 → 行情 → 技術指標 → 自訂指標 → 新建主圖
2. 貼上 `futu/best_strategy_mai.txt` 全文 → 儲存
3. `USEVT:=0` 雙引擎（突破買／撈底買／止蝕）；`USEVT:=1` SMH Vol-Target（加倉↑／減倉↓）
4. 雙引擎已係調參版：RSI **15/75**、BO 止 **8%**、MR 止 **4%**
5. 報錯 `SQRT` → 改 `*POWER(252,0.5)`；報錯 `NODRAW` → 刪檔案最底幾行數值輸出

---

## 期望管理

- 「跑贏 SMH 死揸」= 接受槓桿同大回撤
- 想瞓得着、少借錢 → 死揸 SMH 或者雙引擎減風險，**唔好硬贏 CAGR**
- 槓桿唔係免費 alpha；只係把波動換 CAGR
