"""CLI: dump THS board memberships to a CSV backup file.

Walks every THS board row currently in the local ``stock_board`` table
(``WHERE source='ths'``) and calls ``ThsFetcher.get_board_stocks_full`` to
fetch the full membership (F10 page tier, platecode-addressed, no 50-row
cap). Writes a 7-column CSV that the startup loader
(``persistence.board_csv.seed_ths_membership_from_csv``) can consume at the
next cold start.

Why a new tool and not reuse ``build_membership_index``?
    ``build_membership_index`` calls ``manager.get_board_stocks`` (the
    50-row AJAX tier, addressable by THS internal **cid**) and writes to
    SQLite via ``upsert_membership_bulk``. We need:
      - F10 tier (``get_board_stocks_full``, platecode-addressed, full
        membership, no quote columns)
      - CSV output, not SQLite
      - A predictable single-source walk (no cross-source thread pool)

Usage:
    .venv/Scripts/python.exe -m stock_data.tools.build_ths_membership_csv \\
        [--output PATH] [--inter-call-sleep-min SEC] [--inter-call-sleep-max SEC]

Output CSV (7 cols; ``subtype`` intentionally omitted because for THS
it's always ``同花顺概念`` or ``同花顺行业`` and is recoverable from
``board_type`` at read time):
    board_code,stock_code,source,board_name,stock_name,board_type,refreshed_at

Reference: docs/superpowers/plans/2026-09-15-ths-membership-csv-backup.md
"""

from __future__ import annotations

import argparse
import csv
import logging
import random
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from ..data_provider.base import DataFetchError
from ..data_provider.fetchers.ths_fetcher import ThsFetcher
from ..data_provider.persistence import board as board_mod

logger = logging.getLogger(__name__)

VALID_BOARD_TYPES = ("concept", "industry")

CSV_HEADER = (
    "board_code",
    "stock_code",
    "source",
    "board_name",
    "stock_name",
    "board_type",
    "refreshed_at",
)

DEFAULT_OUTPUT = (
    Path(__file__).resolve().parents[1] / "stock_data_backup" / "stock_board_membership_ths.csv"
)


@dataclass
class BuildReport:
    """Per-board outcome. Aggregated into ``RunReport`` for CLI feedback."""

    total_boards: int = 0
    success_count: int = 0
    empty_count: int = 0
    error_count: int = 0
    error_samples: list[str] = field(default_factory=list)
    rows_written: int = 0
    duration_seconds: float = 0.0


def _read_ths_boards(board_types: tuple[str, ...] = VALID_BOARD_TYPES) -> list[dict]:
    """Read THS board rows from the local ``stock_board`` table.

    Equivalent to ``_read_ths_boards`` in the original plan; inlined because
    the helper would have only one caller and is two ``_read_boards_from_db``
    calls long. Returns the union of (board_type, source='ths') rows.
    """
    out: list[dict] = []
    for bt in board_types:
        out.extend(board_mod._read_boards_from_db(bt, "ths"))
    return out


def _throttle_seconds(inter_call_sleep: tuple[float, float]) -> float:
    """Sample one jitter value (caller sleeps). Pulled into a helper so tests
    can monkeypatch the deterministic return value.
    """
    return random.uniform(*inter_call_sleep)


def build_ths_membership_csv(
    output_path: Path,
    *,
    inter_call_sleep: tuple[float, float] = (1.0, 3.0),
    board_types: tuple[str, ...] = VALID_BOARD_TYPES,
    fetcher: ThsFetcher | None = None,
    on_progress: Callable[[int, int], None] | None = None,
) -> BuildReport:
    """Walk THS boards, fetch each via F10 page, write CSV.

    Args:
        output_path: Destination CSV path. Overwritten on every call.
        inter_call_sleep: (min, max) jitter range in seconds between
            board fetches. Defaults to (1.0, 3.0) to match
            ``build_membership_index``'s deterministic 1.0-3.0s per-board
            jitter (THS single-IP is easy to flag without it).
        board_types: tuple of board_types to include. Defaults to
            ``("concept", "industry")`` — the only two supported by the THS
            forward-board path (board.py:147-152).
        fetcher: optional pre-built ``ThsFetcher`` instance (test seam).
        on_progress: optional ``(done, total)`` callback for CLI progress.

    Returns:
        ``BuildReport`` describing the run.
    """
    started = time.monotonic()
    board_mod.init_schema()
    boards = _read_ths_boards(board_types)
    if fetcher is None:
        fetcher = ThsFetcher()

    report = BuildReport(total_boards=len(boards))
    rows_out: list[tuple] = []
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    output_path.parent.mkdir(parents=True, exist_ok=True)

    for idx, b in enumerate(boards, start=1):
        board_code = b["board_code"]
        board_name = b["name"]
        board_type = b.get("board_type")
        try:
            stocks = fetcher.get_board_stocks_full(
                board_code=board_code, board_type=board_type
            )
        except DataFetchError as e:
            report.error_count += 1
            if len(report.error_samples) < 3:
                report.error_samples.append(f"{board_code}: DataFetchError: {e}")
            logger.warning(
                "[ThsMembershipCSV] %s upstream failed: %s; skip", board_code, e
            )
            continue
        if not stocks:
            report.empty_count += 1
            logger.info("[ThsMembershipCSV] %s returned 0 rows; skip", board_code)
            continue
        for s in stocks:
            stock_code = s.get("stock_code", "")
            stock_name = s.get("stock_name", "")
            if not stock_code or not stock_name:
                # F10 shouldn't emit empty fields, but defensive: skip the
                # row rather than INSERT NULLs into NOT NULL columns.
                continue
            rows_out.append(
                (
                    board_code,
                    stock_code,
                    "ths",
                    board_name,
                    stock_name,
                    board_type,
                    now_str,
                )
            )
        report.success_count += 1
        # Cross-board jitter — THS single-IP use is easy to fingerprint at
        # uniform request cadence. Skip the sleep on the final iteration so
        # the cold-path latency is unaffected.
        if idx < len(boards):
            time.sleep(_throttle_seconds(inter_call_sleep))
        if on_progress is not None:
            on_progress(idx, len(boards))

    # CSV write (overwrite mode). Use default QUOTE_MINIMAL dialect so
    # Chinese punctuation / commas / newlines in board_name/stock_name are
    # correctly escaped.
    with output_path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(CSV_HEADER)
        writer.writerows(rows_out)
    report.rows_written = len(rows_out)
    report.duration_seconds = time.monotonic() - started
    return report


def _format_progress(done: int, total: int) -> None:
    pct = (done / total * 100.0) if total else 100.0
    sys.stdout.write(f"\r[ThsMembershipCSV] {done}/{total} ({pct:.1f}%)")
    sys.stdout.flush()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="build_ths_membership_csv",
        description=(
            "Dump THS board memberships to CSV via F10 page tier. "
            "Idempotent — overwrites the destination file. "
            "Add random inter-board jitter (1-3s by default) to avoid "
            "THS single-IP rate limiting."
        ),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help=f"Destination CSV path (default: {DEFAULT_OUTPUT})",
    )
    parser.add_argument(
        "--inter-call-sleep-min",
        type=float,
        default=1.0,
        help="Min seconds to sleep between board fetches (default: 1.0)",
    )
    parser.add_argument(
        "--inter-call-sleep-max",
        type=float,
        default=3.0,
        help="Max seconds to sleep between board fetches (default: 3.0)",
    )
    parser.add_argument(
        "--board-type",
        action="append",
        choices=VALID_BOARD_TYPES,
        help=(
            "Restrict to one or more board types. Repeat for multiple. "
            f"Default: all of {VALID_BOARD_TYPES}"
        ),
    )
    parser.add_argument(
        "--no-progress",
        action="store_true",
        help="Suppress the per-board progress line (useful for cron / log capture)",
    )
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

    board_types = tuple(args.board_type) if args.board_type else VALID_BOARD_TYPES

    report = build_ths_membership_csv(
        output_path=args.output,
        inter_call_sleep=(args.inter_call_sleep_min, args.inter_call_sleep_max),
        board_types=board_types,
        on_progress=None if args.no_progress else _format_progress,
    )

    if not args.no_progress:
        # Move to a fresh line after the \r progress line above.
        sys.stdout.write("\n")
        sys.stdout.flush()

    logger.info(
        "[ThsMembershipCSV] DONE: %d boards (%d ok, %d empty, %d error); "
        "%d rows → %s in %.1fs",
        report.total_boards,
        report.success_count,
        report.empty_count,
        report.error_count,
        report.rows_written,
        args.output,
        report.duration_seconds,
    )
    if report.error_samples:
        logger.warning(
            "[ThsMembershipCSV] error samples: %s", report.error_samples
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
