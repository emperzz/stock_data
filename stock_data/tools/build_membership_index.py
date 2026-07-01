"""CLI: build stock_board_membership by walking all boards per source.

Usage:
    python -m stock_data.tools.build_membership_index [--source=SRC] [--type=TYPE]

Architecture:
    - One worker thread per source (3 threads for eastmoney + zhitu + zzshare)
    - Each worker enumerates boards via manager.get_all_boards, then for each
      board calls manager.get_board_stocks and upserts to membership.
    - Per-board failures are logged and skipped (build continues).
    - Inter-call sleep (jittered) respects upstream rate limits.

Reference: docs/superpowers/specs/2026-07-01-stock-board-membership-design.md §3 Step 7.
"""

from __future__ import annotations

import argparse
import logging
import random
import sys
import threading
import time
from dataclasses import dataclass
from typing import Callable

from ..data_provider.persistence import board as board_mod

logger = logging.getLogger(__name__)

VALID_BOARD_TYPES = ("concept", "industry", "index", "special")
VALID_SOURCES = ("eastmoney", "zhitu", "zzshare")


@dataclass
class BuildReport:
    source: str
    total_boards: int = 0
    success_count: int = 0
    error_count: int = 0
    error_samples: list[str] = None  # type: ignore
    duration_seconds: float = 0.0

    def __post_init__(self):
        if self.error_samples is None:
            self.error_samples = []


def build_membership_index(
    source: str | None = None,
    board_type: str | None = None,
    *,
    inter_call_sleep: tuple[float, float] = (1.0, 2.0),
    on_progress: Callable[[str, int, int], None] | None = None,
    manager=None,
    max_workers_per_source: int = 1,
) -> BuildReport:
    """Walk (source, board_type) and upsert all stocks to membership.

    Args:
        source: 'eastmoney' | 'zhitu' | 'zzshare' or None for all
        board_type: 'concept' | 'industry' | 'index' | 'special' or None for all
        inter_call_sleep: (min, max) jitter range in seconds
        on_progress: optional callback(source, done, total)
        manager: DataFetcherManager instance
        max_workers_per_source: 1 (single thread per source is the safe default;
            higher values risk upstream rate limits)

    Returns:
        BuildReport with counts. For multi-source builds, returns the LAST
        source's report (call once per source to get all reports).
    """
    if manager is None:
        raise ValueError("manager is required")

    sources = [source] if source else list(VALID_SOURCES)
    types = [board_type] if board_type else list(VALID_BOARD_TYPES)

    last_report: BuildReport | None = None
    for src in sources:
        report = _build_one_source(
            source=src, types=types,
            inter_call_sleep=inter_call_sleep,
            on_progress=on_progress,
            manager=manager,
            max_workers=max_workers_per_source,
        )
        last_report = report
        logger.info(
            f"[build_membership_index] {src}: {report.success_count}/{report.total_boards} "
            f"boards OK in {report.duration_seconds:.1f}s"
        )
    return last_report


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
            source=source, board_type=bt, subtype=None, include_quote=False,
        )
        all_boards.extend(boards)
    report.total_boards = len(all_boards)

    if not all_boards:
        report.duration_seconds = time.time() - t0
        return report

    # 2) Per-board fetch + upsert
    done_lock = threading.Lock()
    done_count = [0]

    def _process_board(board: dict):
        try:
            stocks, _ = manager.get_board_stocks(
                board["code"], source=source, include_quote=False,
            )
            if stocks:
                board_mod.upsert_membership_bulk(
                    source=source, stocks=stocks,
                    board_code=board["code"], board_name=board.get("name", ""),
                    board_type=board.get("board_type", ""),
                    subtype=board.get("subtype"),
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
                if len(report.error_samples) < 5:
                    report.error_samples.append(f"{board['code']}: {e!r}")
            logger.warning(f"[build_membership_index] {source}/{board['code']}: {e!r}")

    if max_workers <= 1:
        for board in all_boards:
            _process_board(board)
    else:
        threads = []
        for board in all_boards:
            t = threading.Thread(target=_process_board, args=(board,))
            t.start()
            threads.append(t)
        for t in threads:
            t.join()

    report.duration_seconds = time.time() - t0
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Build stock_board_membership reverse index by walking all boards per source."
    )
    parser.add_argument("--source", choices=VALID_SOURCES, default=None,
                        help="Limit to one source (default: all 3)")
    parser.add_argument("--type", choices=VALID_BOARD_TYPES, default=None,
                        help="Limit to one board_type (default: all 4)")
    parser.add_argument("--inter-call-sleep-min", type=float, default=1.0)
    parser.add_argument("--inter-call-sleep-max", type=float, default=2.0)
    parser.add_argument("--max-workers-per-source", type=int, default=1)
    parser.add_argument("--verbose", "-v", action="store_true")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )

    # Lazy import to avoid loading the entire server stack at module-import time
    from stock_data.data_provider.manager import create_default_manager
    manager = create_default_manager()

    def _on_progress(src: str, done: int, total: int):
        pct = (done / total * 100) if total else 0
        print(f"\r[{src}] {done}/{total} ({pct:.1f}%)", end="", flush=True)

    print(f"Building membership index...")
    report = build_membership_index(
        source=args.source, board_type=args.type,
        inter_call_sleep=(args.inter_call_sleep_min, args.inter_call_sleep_max),
        on_progress=_on_progress,
        manager=manager,
        max_workers_per_source=args.max_workers_per_source,
    )
    print()  # newline after progress
    print(f"Done: {report.source} "
          f"({report.success_count}/{report.total_boards} OK, "
          f"{report.error_count} errors, {report.duration_seconds:.1f}s)")
    if report.error_samples:
        print("Sample errors:")
        for s in report.error_samples:
            print(f"  {s}")
    return 0 if report.error_count == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
