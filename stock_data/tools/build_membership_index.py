"""CLI: build stock_board_membership by walking all boards per source.

Usage:
    python -m stock_data.tools.build_membership_index [--source=SRC] [--type=TYPE]

Architecture:
    - Returns list[BuildReport] (one per source). For source=None, walks
      all 3 sources and aggregates into MultiSourceReport for the CLI.
    - ThreadPoolExecutor per source with --max-workers-per-source=N.
      Default 1 (serial). 2-3 is acceptable; higher risks upstream rate limits.
    - Per-board failures are logged and skipped (build continues).
    - Inter-call sleep (jittered) respects upstream rate limits.

Reference: docs/superpowers/specs/2026-07-01-stock-board-membership-design.md §3 Step 6.
"""

from __future__ import annotations

import argparse
import logging
import random
import sqlite3
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from typing import Callable

from ..data_provider.persistence import board as board_mod
from ..data_provider.persistence import db as db_mod

logger = logging.getLogger(__name__)

VALID_BOARD_TYPES = ("concept", "industry", "index", "special")
VALID_SOURCES = ("eastmoney", "zhitu", "zzshare")


@dataclass
class BuildReport:
    source: str
    total_boards: int = 0
    success_count: int = 0
    error_count: int = 0
    error_samples: list[str] = field(default_factory=list)
    duration_seconds: float = 0.0


@dataclass
class MultiSourceReport:
    reports: list[BuildReport]
    total_boards: int = 0
    total_success: int = 0
    total_errors: int = 0
    duration_seconds: float = 0.0


def build_membership_index(
    source: str | None = None,
    board_type: str | None = None,
    *,
    inter_call_sleep: tuple[float, float] = (1.0, 2.0),
    on_progress: Callable[[str, int, int], None] | None = None,
    manager=None,
    max_workers_per_source: int = 1,
) -> list[BuildReport]:
    """Walk (source, board_type) and upsert all stocks to membership.

    Args:
        source: 'eastmoney' | 'zhitu' | 'zzshare' or None for all
        board_type: 'concept' | 'industry' | 'index' | 'special' or None for all
        inter_call_sleep: (min, max) jitter range in seconds
        on_progress: optional callback(source, done, total)
        manager: DataFetcherManager instance
        max_workers_per_source: 1 (serial within a source). Higher values
            (2-3) are safe; >4 risks upstream rate limits.

    Returns:
        list[BuildReport], one per source walked. For source=None, returns
        3 reports (one per VALID_SOURCES).
    """
    if manager is None:
        raise ValueError("manager is required")
    if inter_call_sleep[0] > inter_call_sleep[1]:
        raise ValueError(
            f"inter_call_sleep min ({inter_call_sleep[0]}) > max ({inter_call_sleep[1]})"
        )
    if inter_call_sleep[0] < 0:
        raise ValueError("inter_call_sleep values must be non-negative")

    sources = [source] if source else list(VALID_SOURCES)
    types = [board_type] if board_type else list(VALID_BOARD_TYPES)

    reports: list[BuildReport] = []
    for src in sources:
        report = _build_one_source(
            source=src,
            types=types,
            inter_call_sleep=inter_call_sleep,
            on_progress=on_progress,
            manager=manager,
            max_workers=max_workers_per_source,
        )
        reports.append(report)
        logger.info(
            f"[build_membership_index] {src}: {report.success_count}/{report.total_boards} "
            f"boards OK in {report.duration_seconds:.1f}s"
        )
    return reports


def _build_one_source(
    source: str,
    types: list[str],
    inter_call_sleep: tuple[float, float],
    on_progress: Callable | None,
    manager,
    max_workers: int,
) -> BuildReport:
    report = BuildReport(source=source)
    t0 = time.time()

    # 1) Enumerate all boards for this source
    all_boards: list[dict] = []
    for bt in types:
        boards, _ = manager.get_all_boards(
            source=source,
            board_type=bt,
            subtype=None,
            include_quote=False,
        )
        all_boards.extend(boards)
    report.total_boards = len(all_boards)

    if not all_boards:
        report.duration_seconds = time.time() - t0
        return report

    # 2) Per-board fetch + upsert via ThreadPoolExecutor with per-thread connections
    done_lock = threading.Lock()
    done_count = [0]

    def _process_board(board: dict) -> None:
        # Each thread opens its own SQLite connection (per spec §4.3).
        # WAL mode allows concurrent writers; the connection's own
        # mutex serializes access within the thread.
        conn = sqlite3.connect(str(db_mod.get_db_path()), timeout=30)
        try:
            try:
                stocks, _ = manager.get_board_stocks(
                    board["code"],
                    source=source,
                    include_quote=False,
                )
                if stocks:
                    board_mod.upsert_membership_bulk(
                        source=source,
                        stocks=stocks,
                        board_code=board["code"],
                        board_name=board.get("name", ""),
                        board_type=board.get("board_type", ""),
                        subtype=board.get("subtype") or "",
                        conn=conn,
                    )
                sleep_s = random.uniform(*inter_call_sleep)
                time.sleep(sleep_s)
                with done_lock:
                    done_count[0] += 1
                    report.success_count += 1
                    if on_progress:
                        on_progress(source, done_count[0], report.total_boards)
            except Exception as e:
                with done_lock:
                    done_count[0] += 1
                    report.error_count += 1
                    if len(report.error_samples) < 20:
                        report.error_samples.append(f"{board['code']}: {e!r}")
                logger.warning(f"[build_membership_index] {source}/{board['code']}: {e!r}")
        finally:
            conn.close()

    if max_workers <= 1:
        for board in all_boards:
            _process_board(board)
    else:
        with ThreadPoolExecutor(max_workers=max_workers) as pool:
            futures = [pool.submit(_process_board, board) for board in all_boards]
            for f in as_completed(futures):
                f.result()  # surface exceptions (per-board errors already absorbed)

    report.duration_seconds = time.time() - t0
    return report


def _aggregate(reports: list[BuildReport]) -> MultiSourceReport:
    return MultiSourceReport(
        reports=reports,
        total_boards=sum(r.total_boards for r in reports),
        total_success=sum(r.success_count for r in reports),
        total_errors=sum(r.error_count for r in reports),
        duration_seconds=sum(r.duration_seconds for r in reports),
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Build stock_board_membership reverse index by walking all boards per source."
    )
    parser.add_argument(
        "--source", choices=VALID_SOURCES, default=None, help="Limit to one source (default: all 3)"
    )
    parser.add_argument(
        "--type",
        choices=VALID_BOARD_TYPES,
        default=None,
        help="Limit to one board_type (default: all 4)",
    )
    parser.add_argument("--inter-call-sleep-min", type=float, default=1.0)
    parser.add_argument("--inter-call-sleep-max", type=float, default=2.0)
    parser.add_argument(
        "--max-workers-per-source",
        type=int,
        default=1,
        help="Threads per source (1=serial, 2-3=safe, >4 risky)",
    )
    parser.add_argument("--verbose", "-v", action="store_true")
    args = parser.parse_args(argv)

    if args.inter_call_sleep_max < 0.5:
        logger.warning(
            f"inter_call_sleep_max={args.inter_call_sleep_max}s is risky for upstream "
            "rate limits; consider >=0.5s, especially with --max-workers-per-source>1"
        )

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )

    from stock_data.data_provider.manager import create_default_manager

    manager = create_default_manager()

    def _on_progress(src: str, done: int, total: int):
        pct = (done / total * 100) if total else 0
        print(f"\r[{src}] {done}/{total} ({pct:.1f}%)", end="", flush=True)

    print("Building membership index...")
    reports = build_membership_index(
        source=args.source,
        board_type=args.type,
        inter_call_sleep=(args.inter_call_sleep_min, args.inter_call_sleep_max),
        on_progress=_on_progress,
        manager=manager,
        max_workers_per_source=args.max_workers_per_source,
    )
    print()  # newline after progress

    agg = _aggregate(reports)
    for r in reports:
        status = "OK" if r.error_count == 0 else f"{r.error_count} ERRORS"
        print(
            f"  {r.source}: {r.success_count}/{r.total_boards} OK ({status}) {r.duration_seconds:.1f}s"
        )
        for s in r.error_samples:
            print(f"    {s}")
    print(
        f"Total: {agg.total_success}/{agg.total_boards} OK, {agg.total_errors} errors "
        f"in {agg.duration_seconds:.1f}s across {len(reports)} source(s)"
    )

    return 0 if agg.total_errors == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
