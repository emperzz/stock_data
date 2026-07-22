"""Live-network probe for P3-a4 (M17): Zhitu holder_num_change sign semantics.

Background (architecture-review-2026-07-16.md §M17):
  Zhitu's ``bh`` field is free text like "减少28718" or "新增1702".
  Current code in zhitu_fetcher.py:1048-1052 flips the sign so:
    "新增" → -change_num  (intuitive: 增加 should be positive)
    "减少" → keeps positive (intuitive: 减少 should be negative)
  This looks INVERTED, but the docstring claims it "matches the docs example".

This probe verifies the actual semantic by computing
``gdhs[D] - gdhs[D-1]`` across two consecutive report periods and
comparing against the parsed sign of the ``bh`` text.

Run with:
    .venv/Scripts/python.exe scripts/probe_zhitu_holder_num.py
"""

from __future__ import annotations

import os
import re
import sys

# Force UTF-8 stdout so unicode glyphs (✓/✗) print on Windows
try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

import requests

ZHITU_BASE = "https://api.zhituapi.com"
TOKEN = os.getenv("ZHITU_TOKEN", "")

# Use 600519 (贵州茅台) — large cap, multiple report periods, low noise.
STOCK_CODE = "600519"


def fetch_zhitu(code: str) -> list[dict]:
    """Hit Zhitu /hs/gs/gdbh/{code} with token as query param (matches fetcher)."""
    url = f"{ZHITU_BASE}/hs/gs/gdbh/{code}"
    params = {"token": TOKEN}
    print(f"GET {url}?token=...")
    r = requests.get(url, params=params, timeout=15)
    r.raise_for_status()
    data = r.json()
    if not isinstance(data, list):
        raise SystemExit(f"Unexpected payload shape: {type(data).__name__}: {data}")
    return data


def parse_change(bh_raw: str) -> tuple[int, str]:
    """Mirror zhitu_fetcher.py:1057-1062 (post-P3-a4 fix).

    Post-fix logic: "新增N" → keep magnitude positive (intuitive: more holders),
    "减少N" → negate (intuitive: fewer holders). The pre-fix logic was
    inverted across all probed rows; this probe confirms the new convention.

    Returns (change_num, keyword) so callers can compare against the actual
    gdhs[D] - gdhs[D-1] delta.
    """
    m = re.search(r"-?\d+", bh_raw.replace(",", ""))
    change_num = int(m.group(0)) if m else 0
    if "减少" in bh_raw and change_num > 0:
        change_num = -change_num
    elif "新增" in bh_raw and change_num > 0:
        pass  # already positive — 新增 means actual increase
    keyword = "新增" if "新增" in bh_raw else ("减少" if "减少" in bh_raw else "?")
    return change_num, keyword


def main() -> int:
    if not TOKEN:
        print("ZHITU_TOKEN not set; cannot run probe.", file=sys.stderr)
        return 2

    data = fetch_zhitu(STOCK_CODE)
    if len(data) < 2:
        print(f"Need ≥2 records, got {len(data)}")
        return 1

    print(f"\nGot {len(data)} records. Checking sign semantics...\n")
    print(
        f"{'date':<12} {'gdhs':>10} {'gdhs_prev':>10} {'actual':>10} "
        f"{'bh_text':>14} {'current_code':>14} {'match':>6}"
    )
    print("-" * 84)

    mismatches = 0
    for i in range(len(data)):
        prev = data[i + 1] if i + 1 < len(data) else None
        if prev is None:
            continue
        gdhs = int(data[i].get("gdhs", 0) or 0)
        gdhs_prev = int(prev.get("gdhs", 0) or 0)
        actual_change = gdhs - gdhs_prev
        bh_raw = str(data[i].get("bh", ""))
        code_change, _keyword = parse_change(bh_raw)
        match = "✓" if (actual_change > 0) == (code_change > 0) else "✗"
        if match == "✗":
            mismatches += 1
        print(
            f"{data[i].get('jzrq', ''):<12} {gdhs:>10} {gdhs_prev:>10} "
            f"{actual_change:>+10} {bh_raw:>14} {code_change:>+14} {match:>6}"
        )

    print()
    if mismatches == 0:
        print("VERDICT: current code is CORRECT — sign convention matches the")
        print("  actual gdhs delta. The 'intuitive reading' was wrong; Zhitu's")
        print("  bh text means opposite of naive English interpretation, OR the")
        print("  code is reading it backwards relative to its own intent.")
        return 0
    else:
        print(f"VERDICT: BUG CONFIRMED — {mismatches}/{len(data) - 1} rows have")
        print("  current_code sign opposite to actual gdhs delta. The intuitive")
        print("  semantic (新增→+, 减少→-) IS the upstream convention; current")
        print("  code flips them. Should be inverted.")
        return 1


if __name__ == "__main__":
    sys.exit(main())
