"""Refresh ``stock_data/stock_data_backup/ths_board_id_map.csv``.

The map answers one question: given a THS board cid, what is its public
platecode? THS exposes the pair in two places, both THS-native:

1. ``GET /gn/`` → ``<input id="gnSection">`` carries ``platecode`` +
   ``cid`` together, but only for the day's "热门" subset (~292 of ~490).
2. ``GET /gn/detail/code/{cid}/`` → the detail page contains exactly one
   885/886 code (verified live 2026-09-11: cid 309121 → 886071).

This tool sweeps (1), then fills the remainder from (2), merges the result
over the CSV's existing contents, and reports a diff (added / changed /
removed). Live observations win over the file — the CSV is a snapshot,
never authoritative (spec §3.2).

The same two primitives are also used at runtime by
``ThsFetcher._resolve_platecode_from_detail``, but only for a single
board and only on a map miss; this tool is the batch path.

Usage:
    python -m stock_data.tools.refresh_ths_board_id_map --dry-run      # report only
    python -m stock_data.tools.refresh_ths_board_id_map --apply        # write the CSV
    python -m stock_data.tools.refresh_ths_board_id_map --apply --no-detail   # skip per-board fetches
"""

from __future__ import annotations

import argparse
import csv
import random
import sys
import time
from pathlib import Path

from stock_data.data_provider.fetchers.ths_fetcher import ThsFetcher

DEFAULT_OUT = (
    Path(__file__).resolve().parents[1]
    / "stock_data_backup"
    / "ths_board_id_map.csv"
)
CSV_FIELDS = ("cid", "platecode", "name", "board_type")

# The parsers and the index URL live on the real class. `ThsFetcher` itself
# stays the *construction* entry point (tests substitute it with a fake
# fetcher); these two private aliases keep the rest of the module working
# when that happens.
_FetcherClass = ThsFetcher
_GN_INDEX_URL = _FetcherClass._THS_CONCEPT_INDEX_URL


def read_map_csv(path: Path) -> dict[str, dict]:
    """Read a mapping CSV into ``{cid: {platecode, name, board_type}}``.

    Missing file → ``{}`` (first run bootstraps from live data alone).
    """
    if not path.exists():
        return {}
    with path.open(encoding="utf-8-sig", newline="") as f:
        return {
            r["cid"]: {
                "cid": r["cid"],
                "platecode": r["platecode"],
                "name": r.get("name") or "",
                "board_type": r.get("board_type") or "",
            }
            for r in csv.DictReader(f)
            if r.get("cid") and r.get("platecode")
        }


def write_map_csv(path: Path, rows: list[dict]) -> None:
    """Write mappings sorted by cid, with a stable column order."""
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(CSV_FIELDS), extrasaction="ignore")
        w.writeheader()
        for r in sorted(rows, key=lambda r: r["cid"]):
            w.writerow(r)


def snapshot_gn(fetcher) -> dict:
    """Sweep ``GET /gn/`` once.

    Returns ``{"mapped": {cid: platecode}, "names": {cid: name},
    "sidebar_cids": [...]}``. ``mapped`` comes from gnSection (cid and
    platecode live in the same JSON object); ``sidebar_cids`` is the full
    sidebar, which includes boards gnSection misses.
    """
    html = fetcher._http_get_ths_board_index(_GN_INDEX_URL)
    mapped: dict[str, str] = {}
    names: dict[str, str] = {}
    for row in _FetcherClass._parse_gn_section(html):
        cid = row.get("code")
        platecode = row.get("platecode")
        if cid and platecode:
            mapped[cid] = platecode
            names[cid] = row.get("name") or ""
    sidebar = _FetcherClass._parse_ths_gn_sidebar(html)
    sidebar_cids = [r["code"] for r in sidebar if r.get("code")]
    for r in sidebar:
        names.setdefault(r["code"], r.get("name") or "")
    return {"mapped": mapped, "names": names, "sidebar_cids": sidebar_cids}


def resolve_unmapped(
    fetcher,
    snapshot: dict,
    *,
    sleep_s: float,
    limit: int | None,
    log,
) -> tuple[dict, list[str]]:
    """Fill platecodes for sidebar cids missing from ``snapshot['mapped']``.

    Fetches ``/gn/detail/code/{cid}/`` one board at a time with a jittered
    sleep. Returns ``(added, failed_cids)`` — a detail page that does not
    yield exactly one candidate is reported as failed, never guessed.
    """
    mapped = dict(snapshot["mapped"])
    added: dict[str, str] = {}
    failed: list[str] = []
    todo = [c for c in snapshot["sidebar_cids"] if c not in mapped]
    if limit is not None:
        todo = todo[:limit]
    for i, cid in enumerate(todo):
        url = f"https://q.10jqka.com.cn/gn/detail/code/{cid}/"
        try:
            platecode = _FetcherClass.extract_platecode_from_detail(
                fetcher._http_get_ths_board_index(url)
            )
        except Exception as e:  # network / non-2xx — report, keep going
            log(f"  {cid}: fetch failed ({type(e).__name__}: {e})")
            failed.append(cid)
            continue
        if platecode:
            added[cid] = platecode
        else:
            failed.append(cid)
        if sleep_s and i + 1 < len(todo):
            time.sleep(random.uniform(sleep_s, sleep_s * 2))
    return added, failed


def diff_maps(old: dict[str, str], new: dict[str, str]) -> dict[str, list[str]]:
    """Compare two ``{cid: platecode}`` maps.

    ``changed`` is the renumbering detector — the only place a THS
    platecode reassignment becomes visible.
    """
    return {
        "added": sorted(set(new) - set(old)),
        "changed": sorted(c for c in set(old) & set(new) if old[c] != new[c]),
        "removed": sorted(set(old) - set(new)),
    }


def build_argparser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--out", type=Path, default=DEFAULT_OUT)
    p.add_argument("--apply", action="store_true", help="write the CSV (default: report only)")
    p.add_argument("--dry-run", action="store_true", help="explicit report-only mode")
    p.add_argument("--no-detail", action="store_true", help="skip per-board detail-page fetches")
    p.add_argument("--limit", type=int, default=None, help="cap detail fetches (debug)")
    p.add_argument("--sleep", type=float, default=1.5, help="min jitter seconds between detail fetches")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_argparser().parse_args(argv)
    log = print

    base = read_map_csv(args.out)
    log(f"base: {len(base)} mappings from {args.out}")

    fetcher = ThsFetcher()
    snap = snapshot_gn(fetcher)
    log(f"gnSection: {len(snap['mapped'])} pairs; sidebar: {len(snap['sidebar_cids'])} cids")

    added: dict[str, str] = {}
    failed: list[str] = []
    if not args.no_detail:
        added, failed = resolve_unmapped(
            fetcher, snap, sleep_s=args.sleep, limit=args.limit, log=log
        )
        log(f"detail pages: resolved {len(added)}, failed {len(failed)}")
        if failed:
            log(f"  unresolved (rerun later): {failed[:20]}")

    live = {**snap["mapped"], **added}
    merged: dict[str, dict] = dict(base)
    for cid, platecode in live.items():
        prev = merged.get(cid)
        merged[cid] = {
            "cid": cid,
            "platecode": platecode,  # live wins over the file
            "name": snap["names"].get(cid) or (prev or {}).get("name") or "",
            "board_type": (prev or {}).get("board_type") or "concept",
        }

    d = diff_maps(
        {c: r["platecode"] for c, r in base.items()},
        {c: r["platecode"] for c, r in merged.items()},
    )
    log(f"diff: +{len(d['added'])} added, ~{len(d['changed'])} changed, -{len(d['removed'])} removed")
    for label in ("changed", "removed"):
        for cid in d[label][:10]:
            log(
                f"  {label}: {cid} "
                f"{base.get(cid, {}).get('platecode')} → {merged.get(cid, {}).get('platecode')}"
            )

    if not args.apply:
        log("report-only (pass --apply to write)")
        return 0
    write_map_csv(args.out, list(merged.values()))
    log(f"wrote {len(merged)} mappings to {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
