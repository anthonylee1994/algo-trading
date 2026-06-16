"""為 point-in-time S&P 500 universe（含退市股）抽 yfinance 寬表價格。

食 build_pit_sp500_membership.py 出嘅 membership CSV，攞晒入面所有 symbol（含已退市）
+ benchmark（QQQ/SPY）嘅 total-return adjusted close，輸出寬表畀
pit_backtest_momentum_rotation.py。

退市股喺 Yahoo 多數仲查到佢上市期間嘅價（被收購嗰啲會有，純破產嗰啲可能冇）。
攞唔到嘅會報出嚟 = 殘留 survivorship（已盡量最小化）。
"""

from __future__ import annotations

import argparse
from datetime import date
from pathlib import Path

import pandas as pd


def yf_symbol(t: str) -> str:
    return t.replace(".", "-")


def fetch(symbols: list[str], start: str, end: str, chunk: int = 120) -> pd.DataFrame:
    import yfinance as yf

    closes: dict[str, pd.Series] = {}
    uniq = list(dict.fromkeys(symbols))
    for i in range(0, len(uniq), chunk):
        batch = uniq[i : i + chunk]
        q = [yf_symbol(s) for s in batch]
        raw = yf.download(
            tickers=q, start=start, end=end, auto_adjust=True,
            progress=False, group_by="ticker", threads=True,
        )
        if raw.empty:
            print(f"  batch {i//chunk}: 空")
            continue
        got = 0
        for s in batch:
            ys = yf_symbol(s)
            try:
                series = raw[ys]["Close"] if isinstance(raw.columns, pd.MultiIndex) else raw["Close"]
            except KeyError:
                continue
            series = series.dropna()
            if not series.empty:
                closes[s] = series.astype(float)
                got += 1
        print(f"  batch {i//chunk}: {got}/{len(batch)} 有數據")
    return pd.DataFrame(closes).sort_index()


def clip_to_membership(
    prices: pd.DataFrame,
    membership: pd.DataFrame,
    bench: list[str],
    lookback_buffer_days: int = 220,
) -> pd.DataFrame:
    """將每隻 symbol 嘅價格 clip 落佢嘅 membership 窗口內（+ lookback buffer）。

    關鍵 survivorship-data 修正：yfinance 對退市/被收購股有 *ticker recycling* ——
    個 symbol 退市後被派畀第二隻證券，下載返嚟嘅序列會喺退市後變成完全唔同
    （e.g. TIE 被收購後個 ticker 變咗交易喺 8000+ 嘅嘢）。clip 落 membership 窗口
    就剷走呢啲 post-delisting junk。benchmark 唔 clip。
    """
    out = prices.copy()
    idx = out.index
    keep = pd.DataFrame(False, index=idx, columns=out.columns)
    for b in bench:
        if b in keep.columns:
            keep[b] = True
    for _, row in membership.iterrows():
        sym = row["symbol"]
        if sym not in keep.columns:
            continue
        start = pd.Timestamp(row["start"]) - pd.Timedelta(days=lookback_buffer_days)
        end = pd.Timestamp(row["end"]) if not pd.isna(row["end"]) else idx[-1]
        keep.loc[(idx >= start) & (idx <= end), sym] = True
    return out.mask(~keep)


def sanitize(prices: pd.DataFrame, up: float = 0.60, down: float = -0.50) -> tuple[pd.DataFrame, int]:
    """清走窗口內殘留嘅 phantom jump（壞 adjusted close print）。

    大型股單日實際回報幾乎冇超過 ±40%；窗口內超出 [down, up] 嘅當數據壞點 null 咗
    （留 NaN，唔 ffill —— pit engine 會自己 ffill；亂 ffill 反而會延長 junk）。
    迭代到收斂。
    """
    clean = prices.copy()
    total = 0
    for _ in range(8):
        rets = clean.pct_change()
        bad = (rets > up) | (rets < down)
        n = int(bad.to_numpy().sum())
        if n == 0:
            break
        total += n
        clean = clean.mask(bad)
    return clean, total


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--membership", default="output/sp500_pit_membership.csv")
    p.add_argument("--benchmarks", nargs="*", default=["QQQ", "SPY"])
    p.add_argument("--start", default="2009-01-01")
    p.add_argument("--end", default=str(date.today()))
    p.add_argument("--out", default="output/sp500_pit_prices.csv")
    args = p.parse_args()

    membership = pd.read_csv(args.membership, dtype={"symbol": str})
    membership = membership.dropna(subset=["symbol"])
    symbols = sorted({s for s in membership["symbol"] if isinstance(s, str) and s.strip()})
    want = list(dict.fromkeys(args.benchmarks + symbols))
    print(f"抽 {len(want)} 隻（{len(symbols)} 成員 + {len(args.benchmarks)} benchmark），{args.start} → {args.end}")

    prices = fetch(want, args.start, args.end)

    raw_cols = prices.shape[1]
    prices = clip_to_membership(prices, membership, args.benchmarks)
    prices, n_scrub = sanitize(prices)
    prices = prices.dropna(axis=1, how="all")  # clip 後完全空嘅 symbol 掉走
    r = prices.pct_change()
    print(
        f"\n清洗：clip 落 membership 窗口 + scrub {n_scrub} 個壞點；"
        f"清洗後最大單日 +{float(r.max().max())*100:.0f}% / {float(r.min().min())*100:.0f}%；"
        f"剩 {prices.shape[1]}/{raw_cols} 隻"
    )

    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    prices.index.name = "date"
    prices.to_csv(args.out)

    got = set(prices.columns)
    missing = [s for s in symbols if s not in got]
    missing_bench = [b for b in args.benchmarks if b not in got]
    print(f"\n寫咗 {prices.shape[0]} 日 × {prices.shape[1]} 隻 → {args.out}")
    print(f"  成員有價：{len([s for s in symbols if s in got])}/{len(symbols)}")
    if missing_bench:
        print(f"  ⚠️ benchmark 缺：{missing_bench}")
    if missing:
        ended = set(membership[membership['end'].notna()]['symbol'])
        miss_ended = [s for s in missing if s in ended]
        print(f"  ⚠️ 缺價 {len(missing)} 隻（殘留 survivorship；其中 {len(miss_ended)} 隻係已退市）")
        print(f"     {', '.join(missing[:30])}" + ("…" if len(missing) > 30 else ""))


if __name__ == "__main__":
    main()
