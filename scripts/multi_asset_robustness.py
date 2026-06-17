"""QQQ/GLD blend robustness check —— 80/20 個 Sharpe+Calmar edge 好薄（0.57 vs 0.55）。

要答三條：
1. Calmar/Sharpe edge 喺唔同子時段（2010s vs 2020s）穩唔穩？定係靠單一時段。
2. 有冇更好嘅 QQQ/TLT/GLD 三資產 blend？
3. QQQ/GLD + vol-target cap1x 結合有冇更好？
"""

from __future__ import annotations

from pathlib import Path
import sys

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.multi_asset_no_leverage import (
    CASH,
    _cagr,
    _max_drawdown,
    _sharpe,
    fixed_weights,
    load_prices,
    run_strategy,
    vol_target_cap1_weights,
)

TRADING_DAYS = 252


def row(name: str, returns: pd.Series, qqq: pd.Series) -> dict:
    return {
        "配置": name,
        "CAGR": _cagr(returns) * 100,
        "Sharpe": _sharpe(returns),
        "最大回撤": _max_drawdown(returns) * 100,
        "Calmar": _cagr(returns) / abs(_max_drawdown(returns)),
        "vs QQQ CAGR": _cagr(returns) * 100 - _cagr(qqq) * 100,
        "vs QQQ Calmar": _cagr(returns) / abs(_max_drawdown(returns))
        - _cagr(qqq) / abs(_max_drawdown(qqq)),
    }


def get_returns(weights, prices, benchmark="QQQ"):
    res = run_strategy("x", weights, prices, 15.0, benchmark)
    # 重跑取 returns：直接用 bt prices
    return res


def main() -> None:
    prices = load_prices(Path("output/multi_asset_prices.csv"))

    blends = [
        ("QQQ 90 / GLD 10", {"QQQ": 0.9, "GLD": 0.1}),
        ("QQQ 85 / GLD 15", {"QQQ": 0.85, "GLD": 0.15}),
        ("QQQ 80 / GLD 20", {"QQQ": 0.8, "GLD": 0.2}),
        ("QQQ 75 / GLD 25", {"QQQ": 0.75, "GLD": 0.25}),
        ("QQQ 70 / GLD 30", {"QQQ": 0.7, "GLD": 0.3}),
        ("QQQ 70 / GLD20 / TLT10", {"QQQ": 0.7, "GLD": 0.2, "TLT": 0.1}),
        ("QQQ 70 / GLD15 / TLT15", {"QQQ": 0.7, "GLD": 0.15, "TLT": 0.15}),
        ("QQQ 80 / GLD10 / TLT10", {"QQQ": 0.8, "GLD": 0.1, "TLT": 0.1}),
    ]

    # [1] full-sample blend sweep
    print("=" * 90)
    print("[1] Full-sample blend sweep（2010-01 → 2026-06，月度，15bps）")
    print("=" * 90)
    full = prices.loc["2010-01-01":]
    rows = []
    for name, alloc in blends:
        print(f"  跑 {name} ...", flush=True)
        r = run_strategy(name, fixed_weights(full, alloc), full, 15.0, "QQQ")
        rows.append(r)
    qq = rows[0]
    print(
        f"\nQQQ bench: CAGR {qq['qqq_cagr']:.1f}% / Sharpe {qq['qqq_sharpe']:.2f} / "
        f"DD {qq['qqq_maxdd']:.1f}% / Calmar {qq['qqq_calmar']:.2f}\n"
    )
    df = pd.DataFrame(rows)[["策略", "CAGR", "Sharpe", "最大回撤", "Calmar"]].copy()
    df["CAGR"] = df["CAGR"].map(lambda v: f"{v:.1f}%")
    df["最大回撤"] = df["最大回撤"].map(lambda v: f"{v:.1f}%")
    df["Sharpe"] = df["Sharpe"].map(lambda v: f"{v:.2f}")
    df["Calmar"] = df["Calmar"].map(lambda v: f"{v:.2f}")
    print(df.to_string(index=False))

    # [2] 子時段：揀最佳 blend + 80/20，分 2010-2017 / 2018-2026 睇穩定性
    print("\n" + "=" * 90)
    print("[2] 子時段穩定性（QQQ 80/GLD 20 vs QQQ）")
    print("=" * 90)
    for seg_label, start, end in [
        ("2010-2017", "2010-01-01", "2017-12-31"),
        ("2018-2026", "2018-01-01", "2026-06-16"),
    ]:
        seg = prices.loc[start:end]
        r_blend = run_strategy(
            "blend", fixed_weights(seg, {"QQQ": 0.8, "GLD": 0.2}), seg, 15.0, "QQQ"
        )
        print(
            f"\n  {seg_label}: 80/20 → CAGR {r_blend['CAGR']:.1f}% / Sharpe {r_blend['Sharpe']:.2f} / "
            f"DD {r_blend['最大回撤']:.1f}% / Calmar {r_blend['Calmar']:.2f}"
        )
        print(
            f"  {seg_label}:  QQQ → CAGR {r_blend['qqq_cagr']:.1f}% / Sharpe {r_blend['qqq_sharpe']:.2f} / "
            f"DD {r_blend['qqq_maxdd']:.1f}% / Calmar {r_blend['qqq_calmar']:.2f}"
        )

    # [3] QQQ/GLD + vol-target cap1x
    print("\n" + "=" * 90)
    print("[3] QQQ 80/GLD 20 + vol-target cap1x（cap1x 唔借錢）")
    print("=" * 90)
    # 簡化：對 80/20 blend 嘅成個組合做 vol-target cap1x
    blend_prices = prices.loc["2010-01-01":].copy()
    # 先計 80/20 blend 淨值序列，再對佢做 cap1x vol-target
    r = pd.Series(0.8, index=blend_prices.index)
    w_blend = fixed_weights(blend_prices, {"QQQ": 0.8, "GLD": 0.2})
    blend_ret = (w_blend.shift(1).fillna(0) * blend_prices.pct_change().fillna(0)).sum(
        axis=1
    )
    blend_equity = (1 + blend_ret).cumprod()
    # 將 blend 當一個 synthetic asset 加入 prices
    synth = blend_prices.copy()
    synth["BLEND"] = blend_equity
    for tv in (0.15, 0.20):
        r2 = run_strategy(
            f"blend VT cap1x {int(tv * 100)}%",
            vol_target_cap1_weights(synth, "BLEND", tv, 40, CASH),
            synth,
            15.0,
            "QQQ",
        )
        print(
            f"  blend VT cap1x {int(tv * 100)}%: CAGR {r2['CAGR']:.1f}% / Sharpe {r2['Sharpe']:.2f} / "
            f"DD {r2['最大回撤']:.1f}% / Calmar {r2['Calmar']:.2f}  "
            f"(QQQ: {r2['qqq_cagr']:.1f}% / {r2['qqq_sharpe']:.2f} / {r2['qqq_maxdd']:.1f}% / {r2['qqq_calmar']:.2f})"
        )


if __name__ == "__main__":
    main()
