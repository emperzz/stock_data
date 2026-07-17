"""Live-network probe for P3-a5 (M8): Tencent index daily ``amount`` semantic.

Background (architecture-review-2026-07-16.md §M8):
  akshare/index_norm.py `_INDEX_TX_MAP` renames upstream ``amount`` → ``volume``
  while Sina/EM use ``volume`` → ``volume``. If Tencent's ``amount`` is actually
  成交额 (yuan), then volume would be wildly wrong (量级差 1000x+).

This probe hits Tencent's index daily endpoint directly for 000300 (HS300) and:
  1. Prints the magnitude of the amount column.
  2. Compares against the EM endpoint (which has both volume and amount
     separately) to determine the unit.

Run with:
    .venv/Scripts/python.exe scripts/probe_tencent_index_amount.py
"""
from __future__ import annotations

import sys

import requests

# Tencent public index endpoint — same one akshare wraps
TX_URL = "https://web.ifzq.gtimg.cn/appstock/app/fqkline/get"
EM_URL = "https://push2his.eastmoney.com/api/qt/stock/kline/get"
INDEX_CODE = "sh000300"  # HS300


def fetch_tx(code: str) -> dict:
    # Non-qfq endpoint matches what akshare's stock_zh_index_daily_tx wraps.
    # The qfq param compresses to 6 columns (no amount); without qfq we get
    # the full 7-column response: [date, open, close, high, low, volume, amount].
    params = {
        "param": f"{code},day,,,5,",
        "_var": "kline_day",
    }
    print(f"GET {TX_URL}?param=...{code},day,,,5,")
    r = requests.get(TX_URL, params=params, timeout=15)
    r.raise_for_status()
    # Tencent returns: var kline_day={...};
    text = r.text
    if "=" in text:
        text = text.split("=", 1)[1].rstrip(";")
    import json
    return json.loads(text)


def fetch_em(code: str) -> dict:
    """EM kline endpoint — has volume AND amount as separate fields."""
    secid = "1." + code[2:] if code.startswith("sh") else "0." + code[2:]
    params = {
        "secid": secid,
        "fields1": "f1,f2,f3,f4,f5",
        "fields2": "f51,f52,f53,f54,f55,f56,f57,f58",
        "klt": "101",
        "fqt": "1",
        "end": "20500101",
        "lmt": "5",
    }
    print(f"GET {EM_URL}?secid={secid}&klt=101 (daily)")
    r = requests.get(EM_URL, params=params, timeout=15)
    r.raise_for_status()
    return r.json()


def main() -> int:
    print("\n=== Tencent index daily (last 5 trading days) ===")
    tx = fetch_tx(INDEX_CODE)
    try:
        stock = tx["data"][INDEX_CODE]
    except (KeyError, TypeError):
        print(f"Unexpected Tencent payload: {tx}")
        return 1

    # Tencent returns: ["YYYY-MM-DD", open, close, high, low, volume, ...]
    # For qfq param it might be: ["YYYY-MM-DD", open, close, high, low, volume, amount, ...]
    # Some versions: [date, open, close, high, low, volume] (6 cols)
    # Some versions: [date, open, close, high, low, volume, amount] (7 cols)
    klines = stock.get("qfqday") or stock.get("day") or []
    if not klines:
        print(f"No kline data in Tencent response. Keys: {list(stock.keys())}")
        return 1

    print(f"\nTencent kline rows: {len(klines)}")
    # Tencent returns 6 columns: [date, open, close, high, low, amount].
    # Per akshare docs (stock_zh_index_daily_tx.md:27), col[5] "amount" is
    # in 手 — i.e. it's the volume column, just renamed. So col5 is the
    # value we want to compare against EM volume/amount, not col6 (which
    # doesn't exist in the 6-col response).
    print(f"{'date':<12} {'col5(amount=手)':>18}")
    print("-" * 32)
    tx_amounts = []
    for row in klines[-5:]:
        if not isinstance(row, list) or len(row) < 6:
            continue
        date = row[0]
        c5 = row[5] if len(row) > 5 else None
        print(f"{date:<12} {str(c5):>18}")
        if c5 is not None:
            try:
                tx_amounts.append(float(c5))
            except (ValueError, TypeError):
                pass

    print("\n=== EM index daily (last 5 trading days, with both volume + amount) ===")
    # EM often rate-limits or refuses raw requests — wrap so the probe
    # can still produce a Tencent-only verdict if EM is unreachable.
    em = None
    try:
        em = fetch_em(INDEX_CODE)
    except Exception as e:
        print(f"  (EM fetch failed: {type(e).__name__}: {e}; "
              f"falling back to Tencent-only heuristic)")
    if em is not None:
        try:
            klines = em["data"]["klines"]
        except (KeyError, TypeError):
            print(f"Unexpected EM payload: {em}")
            return 1

    em_volumes: list[float] = []
    em_amounts: list[float] = []
    if em is not None:
        # EM format: "YYYY-MM-DD,open,close,high,low,volume,amount,amplitude"
        print(f"\nEM kline rows: {len(klines)}")
        print(f"{'date':<12} {'volume':>15} {'amount':>20}")
        print("-" * 50)
        for line in klines[-5:]:
            parts = line.split(",")
            if len(parts) < 7:
                continue
            date, o, c, h, l, v, a = parts[:7]
            print(f"{date:<12} {v:>15} {a:>20}")
            try:
                em_volumes.append(float(v))
                em_amounts.append(float(a))
            except (ValueError, TypeError):
                pass

    if not tx_amounts:
        print("\nNo Tencent data — cannot run heuristic.")
        return 1

    avg_tx = sum(tx_amounts) / len(tx_amounts)
    print(f"\nTencent col5 (amount=手) avg: {avg_tx:>20,.0f}")

    if not em_amounts:
        # EM unreachable — fall back to magnitude-only heuristic against
        # typical HS300 daily ranges. Daily volume for HS300 is ~1e8-3e8
        # 手 (per Sina/EM observations); daily amount in 元 is ~1e10-1e12.
        print("(EM data unavailable — using magnitude-only heuristic)")
        if 1e7 <= avg_tx <= 1e9:
            print("\nVERDICT: Tencent magnitude (~1e8) matches typical HS300")
            print("  daily volume-in-手. Combined with the akshare docstring")
            print("  ('注意单位: 手'), the upstream 'amount' column is in 手.")
            print("  P3-a5 fix (*100 for amount→volume mapping) is CORRECT.")
            return 0
        elif 1e10 <= avg_tx <= 1e12:
            print("\nVERDICT: Tencent magnitude (~1e11) matches typical HS300")
            print("  daily amount-in-元. The upstream 'amount' column IS in 元")
            print("  (despite akshare docs claiming 手). P3-a5 fix would now")
            print("  pollute volume — REVERT NEEDED, OR akshare docs are wrong.")
            return 1
        else:
            print(f"\nVERDICT: UNCLEAR — magnitude {avg_tx:.0f} doesn't match")
            print("  either expected range. Investigate manually.")
            return 2

    avg_em_vol = sum(em_volumes) / len(em_volumes) if em_volumes else 0
    avg_em_amt = sum(em_amounts) / len(em_amounts) if em_amounts else 0

    print(f"EM volume avg:        {avg_em_vol:>20,.0f}")
    print(f"EM amount avg:        {avg_em_amt:>20,.0f}")

    # Heuristic: HS300 daily volume is ~10^7-10^8 手 (10^9-10^10 shares),
    # HS300 daily amount is ~10^10-10^11 yuan.
    # If Tencent col5 ~ EM volume → it's 手 (P3-a5 fix correct).
    # If Tencent col5 ~ EM amount → it's yuan (P3-a5 fix wrong).
    print()
    if avg_em_amt > 0 and avg_em_vol > 0:
        ratio_to_em_vol = avg_tx / avg_em_vol
        ratio_to_em_amt = avg_tx / avg_em_amt
        print(f"Tencent col5 / EM volume: {ratio_to_em_vol:.3f}")
        print(f"Tencent col5 / EM amount: {ratio_to_em_amt:.3f}")

        if 0.5 <= ratio_to_em_vol <= 2.0:
            print("\nVERDICT: Tencent col5 matches EM volume (ratio ≈ 1).")
            print("  Tencent's 'amount' field IS the share volume (in 手).")
            print("  P3-a5 fix (*100 for amount→volume mapping) is CORRECT.")
            return 0
        elif 0.5 <= ratio_to_em_amt <= 2.0:
            print("\nVERDICT: BUG CONFIRMED — Tencent col5 matches EM amount (ratio ≈ 1).")
            print("  Tencent's 'amount' field is 成交额 (yuan), NOT share volume.")
            print("  P3-a5 fix would now pollute volume — REVERT NEEDED.")
            return 1
        else:
            print("\nVERDICT: UNCLEAR — Tencent col5 magnitude doesn't match either")
            print("  EM volume or EM amount within 2x. Investigate manually.")
            return 2
    return 2


if __name__ == "__main__":
    sys.exit(main())