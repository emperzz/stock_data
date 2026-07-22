"""Ponytail-style one-shot CSV repair for stock_board_ths.csv.

Two truth sources, in priority order:
  1. THS q.10jqka.com.cn/gn/ — primary. Gives (cid, platecode, name).
  2. zzshare SDK `plates_rank` (plate_type 15+17) — fallback. Gives plate_code
     only (no cid); cid column is left blank.

Probes both, rewrites every 801xxx row. THS-retired boards are NOT deleted —
they're matched against zzshare instead. Rows still unmatched after both
sources are kept verbatim with a [unresolved] tag for manual review.

Run from repo root:  python tools/fix_stock_board_ths_csv.py
"""

from __future__ import annotations

import argparse
import csv
import html as html_mod
import io
import json
import re
import sys
import urllib.request
from pathlib import Path

CSV_PATH = Path("stock_data/stock_data_backup/stock_board_ths.csv")
GN_INDEX_URL = "https://q.10jqka.com.cn/gn/"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Referer": "https://www.10jqka.com.cn/",
}
ZZSHARE_DATE = "2026-07-21"


def fetch(url: str, timeout: int = 30) -> bytes:
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def parse_gn_index(raw: bytes) -> tuple[dict[str, str], dict[str, str]]:
    """Parse /gn/ into (platecode_truth, cid_truth).

    - platecode_truth: name → platecode (only gnSection rows carry this)
    - cid_truth: name → cid (gnSection + sidebar merged; sidebar carries cid only)

    Returned as separate dicts so callers can mix sources: zzshare gives
    platecode, THS /gn/ gives cid.
    """
    platecode_truth: dict[str, str] = {}
    cid_truth: dict[str, str] = {}

    # gnSection: ASCII \u-escape JSON inside <input id="gnSection" value='...'>
    m = re.search(rb'gnSection"\s+value=\'(.*?)\'', raw, re.S)
    if m:
        val = m.group(1).decode("ascii", errors="replace")
        val = html_mod.unescape(val)
        for v in json.loads(val).values():
            nm = v.get("platename", "").strip()
            cid = str(v.get("cid", "")).strip()
            pc = str(v.get("platecode", "")).strip()
            if nm and pc:
                platecode_truth[nm] = pc
            if nm and cid:
                cid_truth.setdefault(nm, cid)

    # sidebar: <a href=".../gn/detail/code/<slug>/">GBK-text</a> (cid only)
    pat = re.compile(
        rb'<a\s+href="https?://q\.10jqka\.com\.cn/gn/detail/code/(\d+)/"[^>]*>([^<]+)</a>'
    )
    for slug_b, text_b in pat.findall(raw):
        try:
            text = text_b.decode("gbk")
        except UnicodeDecodeError:
            text = text_b.decode("gbk", errors="replace")
        cid_truth.setdefault(text, slug_b.decode("ascii"))

    return platecode_truth, cid_truth


def fetch_zzshare_truth() -> dict[str, str]:
    """Return {name: plate_code} from zzshare plates_rank (pt 15 + 17).

    pt=15 (concept) wins on collision — pt=17 (题材) is the fallback that
    fills the 801xxx rows the THS index has retired. zzshare has no cid.
    """
    from zzshare.client import DataApi  # type: ignore

    api = DataApi()
    truth: dict[str, str] = {}
    for pt in (15, 17):
        rows = api.plates_rank(plate_type=pt, date1=ZZSHARE_DATE, limit=10000) or []
        for r in rows:
            nm = str(r.get("plate_name", "")).strip()
            code = str(r.get("plate_code", "")).strip()
            if nm and code:
                truth.setdefault(nm, code)
    return truth


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="print plan, don't write")
    ap.add_argument("--in", dest="in_path", default=str(CSV_PATH))
    ap.add_argument("--out", dest="out_path", default=None,
                    help="output path (default: overwrite --in unless --dry-run)")
    args = ap.parse_args()

    # ensure stdout honors utf-8 on Windows git-bash (terminal otherwise mojibakes)
    if hasattr(sys.stdout, "buffer"):
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", line_buffering=True)

    in_path = Path(args.in_path)
    out_path = Path(args.out_path) if args.out_path else in_path

    raw = fetch(GN_INDEX_URL)
    ths_pc, ths_cid = parse_gn_index(raw)
    print(f"[probe] THS /gn/: {len(ths_pc)} platecodes, {len(ths_cid)} cids")

    try:
        zz_truth = fetch_zzshare_truth()
        print(f"[probe] zzshare plates_rank: {len(zz_truth)} (pt 15 + 17)")
    except Exception as e:
        print(f"[probe] zzshare failed: {type(e).__name__}: {e}; falling back to THS only")
        zz_truth = {}

    with in_path.open(encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))

    fixed: list[tuple[dict, str, str]] = []     # (row, platecode, cid)
    unresolved: list[dict] = []
    other_rows: list[dict] = []

    for r in rows:
        if r["board_type"] != "concept" or not r["code"].startswith("801"):
            other_rows.append(r)
            continue
        nm = r["name"].strip()
        # zzshare is the primary platecode source; THS /gn/ is fallback.
        pc = zz_truth.get(nm) or ths_pc.get(nm)
        if not pc:
            unresolved.append(r)
            continue
        cid = ths_cid.get(nm, "")  # empty if zzshare-only or THS missed
        fixed.append((r, pc, cid))

    print(f"[scan] {len(fixed)} resolvable, {len(unresolved)} unresolved")
    print("[fix] samples:")
    for r, pc, cid in fixed[:5]:
        print(f"       {r['code']} -> {pc}  cid={cid or '(blank)'}  name={r['name']}")
    if unresolved:
        print(f"[unresolved] {len(unresolved)} rows kept verbatim")
        for r in unresolved[:5]:
            print(f"       code={r['code']}  cid={r['cid']}  name={r['name']}")

    if args.dry_run:
        print("[dry-run] no writes")
        return 0

    # Apply: rewrite fixed rows; keep unresolved rows as-is.
    today = "2026-07-22 10:19:30"
    new_rows: list[dict] = list(other_rows)
    for r, pc, cid in fixed:
        r["code"] = pc
        r["cid"] = cid
        r["updated_at"] = today
        new_rows.append(r)
    new_rows.extend(unresolved)

    fieldnames = list(rows[0].keys())
    with out_path.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(new_rows)

    print(f"[write] {out_path}: {len(new_rows)} rows ({len(fixed)} fixed, {len(unresolved)} kept verbatim)")
    return 0


if __name__ == "__main__":
    sys.exit(main())