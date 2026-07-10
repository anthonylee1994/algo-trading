# 最佳策略：Vol-Target

> 2026-07 驗證：要同時贏 `QQQ`、`SPY`、`GOOG` buy-and-hold CAGR，預設唔再用雙引擎；改用長期持倉加波動率目標槓桿。

---

## 預設規則

```text
每日計 40 日日回報的年化波動率
exposure = clip(40% / realizedVol, 0x, 2x)
每天按目標 exposure 加倉或減倉（預設再平衡帶 = 0），但不因技術訊號清倉
```

- 交易成本：每次調倉 5 bps
- 融資：超過 1x 的部分按年利率 3% 計
- 訊號只使用前一日已知波動率，下一日才承受回報，冇前視。
- 這個策略的 edge 是 **vol-timed leverage**，不是預測股價。

## 回測結果

2026-07-09 Yahoo 調整後日線，`VT40 cap2`，5 bps + 3% 融資：

| 標的 | 時段         | Vol-Target CAGR | Buy-and-hold CAGR | 結果 |
| ---- | ------------ | --------------: | ----------------: | ---- |
| SPY  | Full         |           16.2% |             10.9% | 贏   |
| SPY  | 2009+        |           22.5% |             14.7% | 贏   |
| SPY  | 2019+        |           25.7% |             17.5% | 贏   |
| QQQ  | Full         |           23.4% |             15.1% | 贏   |
| QQQ  | 2009+        |           32.7% |             20.7% | 贏   |
| QQQ  | 2019+        |           35.0% |             23.5% | 贏   |
| GOOG | Full (2014+) |           32.3% |             23.1% | 贏   |
| GOOG | 2019+        |           39.4% |             29.2% | 贏   |

重跑驗證：

```bash
uv run python scripts/research_stock_beat_bh.py
```

輸出在 `output/stock_beat_bh_research.csv`。`GOOG` 2014 才有 Class C 歷史，所以 2009+ 與 Full 相同。

## TradingView

1. 開 QQQ、SPY 或 GOOG 日線。
2. 貼 `pine/best_strategy.pine`。
3. 保持預設模式 `Vol-Target (QQQ/SPY/GOOG)`，目標波動 40%、40 日窗口、最高 2x。
4. strategy properties 需要容許保證金，檔案已設 `margin_long = 50`。

Pine 只會用已完成日線計波動，訂單下一根開市才執行；會按目標曝險與現有股數的差額落單，所以下調槓桿只是減倉，不會反手做空。

## 富途 MAI

`futu/best_strategy_mai.txt` 預設 `USEVT:=1`，顯示每日建議槓桿及加減倉提示。MAI 只是指標，不會代你執行融資或調倉。

只需要 Vol-Target 的精簡 MAI 版可用 `futu/best_strategy_vol_target_mai.txt`；設 `SHOWLABEL:=0` 可隱藏所有圖上文字，只在數據欄看建議槓桿。

富途量化回測 / 交易版在 `futu/best_strategy_vol_target_quant.py`。驅動標的要設為**日 K 收市**觸發，回測起始日要預留至少 41 個交易日 warm-up，並在回測設定填入佣金、滑點及融資利息。

## 舊雙引擎

突破 + RSI2 雙引擎仍然保留為 legacy 模式，適合想細回撤的人；但它會離場，對長期牛市有明顯空倉成本，回測未能達到贏 QQQ、SPY、GOOG buy-and-hold CAGR 的目標。

## 代價

1. 贏 CAGR 靠槓桿。唔借錢、曝險上限 1x，呢個目標做唔到。
2. 回撤可以好深；不能把 2x 視為低風險。
3. TradingView 沒有直接扣每日融資，Python 結果才是包括 3% 融資的可比較數字。
4. 回測不保證未來仍然有效；每次要用新市場資料重跑三個 benchmark。
