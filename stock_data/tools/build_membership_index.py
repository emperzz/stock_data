"""CLI: build stock_board_membership by walking all boards per source.

Usage:
    python -m stock_data.tools.build_membership_index [--source=SRC] [--type=TYPE]

Architecture:
    - Returns list[BuildReport] (one per source). For source=None, walks
      all VALID_SOURCES (eastmoney / zhitu / zzshare / ths) and aggregates
      into MultiSourceReport for the CLI.
    - Cross-source: each source runs on its own thread (per spec §3 Step 6).
      N sources → N worker threads, each owning one fetcher.
    - Intra-source: serial for-loop over boards. Opening concurrent threads
      against the same upstream would just hit its rate limit harder; one
      board at a time per source is the safe pattern.
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
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field

from ..data_provider.persistence import board as board_mod
from ..data_provider.persistence import db as db_mod

logger = logging.getLogger(__name__)

# Re-export from the canonical source (persistence.board)
VALID_BOARD_TYPES = board_mod.VALID_BOARD_TYPES
VALID_SOURCES = board_mod.VALID_SOURCES


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
    inter_call_sleep: tuple[float, float] = (1.0, 3.0),
    on_progress: Callable[[str, int, int], None] | None = None,
    manager=None,
) -> list[BuildReport]:
    """Walk (source, board_type) and upsert all stocks to membership.

    Args:
        source: one of VALID_SOURCES ('eastmoney' | 'zhitu' | 'zzshare' | 'ths')
            or None for all
        board_type: 'concept' | 'industry' | 'index' | 'special' or None for all
        inter_call_sleep: (min, max) jitter range in seconds
        on_progress: optional callback(source, done, total)
        manager: DataFetcherManager instance

    Returns:
        list[BuildReport], one per source walked. For source=None, returns
        len(VALID_SOURCES) reports (one per VALID_SOURCES). Each source runs
        on its own worker thread; intra-source fetching stays serial (see
        module docstring).
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

    reports: list[BuildReport] = [None] * len(sources)  # type: ignore[list-item]

    def _run_one(i: int, src: str) -> None:
        report = _build_one_source(
            source=src,
            types=types,
            inter_call_sleep=inter_call_sleep,
            on_progress=on_progress,
            manager=manager,
        )
        reports[i] = report
        logger.info(
            f"[build_membership_index] {src}: {report.success_count}/{report.total_boards} "
            f"boards OK in {report.duration_seconds:.1f}s"
        )

    if len(sources) == 1:
        _run_one(0, sources[0])
    else:
        with ThreadPoolExecutor(max_workers=len(sources)) as pool:
            futures = [pool.submit(_run_one, i, src) for i, src in enumerate(sources)]
            for f in as_completed(futures):
                f.result()  # surface exceptions from per-source threads

    return reports  # type: ignore[return-value]


def _build_one_source(
    source: str,
    types: list[str],
    inter_call_sleep: tuple[float, float],
    on_progress: Callable | None,
    manager,
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

    # 2) Per-board fetch + upsert (serial within this source; cross-source
    #    parallelism is handled by build_membership_index's outer pool).
    done_count = 0

    def _process_board(board: dict) -> None:
        nonlocal done_count
        # Each source-level worker thread opens its own SQLite connection
        # (per spec §4.3). WAL mode allows concurrent writers across
        # threads; the connection's own mutex serializes access within the
        # thread. Intra-source processing is serial, so we only ever have
        # one writer per source at a time.
        conn = sqlite3.connect(str(db_mod.get_db_path()), timeout=30)
        # Ensure WAL mode is enabled (per-thread connection; main db may
        # not have been initialized by the server). Once one writer sets
        # the file's journal_mode to WAL, the setting persists at the file
        # level — concurrent threads racing to set it again may hit
        # "database is locked" transiently; the timeout=30 above handles
        # contention, but we still tolerate a rare failure since WAL is
        # already active on the file.
        try:
            conn.execute("PRAGMA journal_mode=WAL")
        except sqlite3.OperationalError as exc:
            if "locked" not in str(exc):
                raise
            logger.debug(f"[build_membership_index] WAL pragma busy (already set): {exc!r}")
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
                        board_type=board.get("type", ""),
                        subtype=board.get("subtype") or "",
                        conn=conn,
                    )
                sleep_s = random.uniform(*inter_call_sleep)
                time.sleep(sleep_s)
                done_count += 1
                report.success_count += 1
                if on_progress:
                    on_progress(source, done_count, report.total_boards)
            except Exception as e:
                done_count += 1
                report.error_count += 1
                if len(report.error_samples) < 20:
                    report.error_samples.append(f"{board['code']}: {e!r}")
                logger.warning(f"[build_membership_index] {source}/{board['code']}: {e!r}")
        finally:
            conn.close()

    for board in all_boards:
        _process_board(board)

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
        "--source",
        choices=VALID_SOURCES,
        default=None,
        help=f"Limit to one source (default: all {len(VALID_SOURCES)})",
    )
    parser.add_argument(
        "--type",
        choices=VALID_BOARD_TYPES,
        default=None,
        help="Limit to one board_type (default: all 4)",
    )
    parser.add_argument("--inter-call-sleep-min", type=float, default=1.0)
    parser.add_argument("--inter-call-sleep-max", type=float, default=3.0)
    parser.add_argument("--verbose", "-v", action="store_true")
    args = parser.parse_args(argv)

    if args.inter_call_sleep_max < 0.5:
        logger.warning(
            f"inter_call_sleep_max={args.inter_call_sleep_max}s is risky for upstream "
            "rate limits; consider >=0.5s"
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
