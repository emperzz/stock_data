"""CSV seed for stock_board / stock_board_membership tables.

Public API:
- seed_stock_board_from_csv(source, csv_path) -> int
- seed_membership_from_csv(csv_path) -> int
- seed_all_from_backup_dir(backup_dir) -> dict[str, int]

Loaders are pure functions (modulo the singleton get_connection()) — safe
to call from server.py lifespan, CLI tools, or unit tests with a fresh
test DB fixture.

Reference: docs/superpowers/specs/2026-07-12-csv-seed-for-board-cache-design.md
"""

from __future__ import annotations

import csv
import logging
import re
import sqlite3
from datetime import datetime
from pathlib import Path

from . import board as board_mod
from .db import get_connection

# Exceptions caught per-file by seed_all_from_backup_dir's per-source try/except.
# Anything outside this set propagates out of the orchestrator (and is the
# server.py lifespan caller's responsibility to handle — see server.py:73-79).
_NON_FATAL_SEED_EXCEPTIONS: tuple[type[BaseException], ...] = (
    ValueError,
    OSError,  # FileNotFoundError, PermissionError, disk-full mid-iteration
    UnicodeDecodeError,  # malformed UTF-8 byte mid-CSV
    csv.Error,  # malformed row, wrong delimiter, etc.
    sqlite3.Error,  # IntegrityError, OperationalError, DatabaseError
    KeyError,  # malformed row with missing column (DictReader yields None normally,
    #         but explicit r["x"] on an empty header would raise)
    IndexError,  # defensive: row shorter than header
)

logger = logging.getLogger(__name__)

_STOCK_BOARD_COLS = {"code", "name", "board_type", "subtype", "source", "cid"}
_MEMBERSHIP_COLS = {
    "board_code",
    "stock_code",
    "source",
    "board_name",
    "stock_name",
    "board_type",
    "subtype",
}
# Sources supported by seed_stock_board_from_csv. All currently
# supported sources share the same 7-col schema; post-2026-07-20
# the legacy 3-col eastmoney loader was deleted (its dispatch branch
# in seed_stock_board_from_csv was removed when the schema unified).
# Any other source value would silently filter every row.
_SUPPORTED_STOCK_BOARD_SOURCES: frozenset[str] = frozenset({"ths", "eastmoney"})

# 6-digit ASCII stock code pattern, used to filter membership CSV rows.
_VALID_STOCK_CODE = re.compile(r"^\d{6}$")

# Cap on how many sample rows are retained for the EOF summary warning.
# Without this, a 100k+ row CSV with all-bad rows would accumulate 100k
# sample strings in memory (each ~30 chars) just to log 3 of them.
_MAX_SAMPLE_RETAINED: int = 3


def _open_csv(path: Path) -> csv.DictReader:
    """Open CSV with utf-8-sig (handles BOM from Excel exports)."""
    f = path.open("r", encoding="utf-8-sig", newline="")
    return csv.DictReader(f)


def _validate_csv_columns(path: Path, required: set[str]) -> None:
    """Raise ValueError if required columns missing. Single error message."""
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.reader(f)
        try:
            header = next(reader)
        except StopIteration:
            raise ValueError(f"{path} is empty") from None
    missing = required - set(header)
    if missing:
        raise ValueError(f"{path} missing required columns: {sorted(missing)}")


def seed_stock_board_from_csv(source: str, csv_path: Path) -> int:
    """Insert/REPLACE rows from a stock_board-style CSV into the DB.

    Args:
        source: One of ``{'ths', 'eastmoney'}``. Both now use the
            unified 7-col schema; legacy 3-col eastmoney was removed
            2026-07-20 when the schema unified across sources.
        csv_path: Path to the CSV file.

    Returns:
        Number of rows inserted/updated.

    Raises:
        ValueError: source not in {'ths', 'eastmoney'} or schema mismatch.
        FileNotFoundError: csv_path doesn't exist.
    """
    if source not in _SUPPORTED_STOCK_BOARD_SOURCES:
        raise ValueError(
            f"Unsupported source {source!r}. Valid sources: "
            f"{sorted(_SUPPORTED_STOCK_BOARD_SOURCES)}"
        )
    if not csv_path.exists():
        raise FileNotFoundError(csv_path)
    board_mod.init_schema()  # idempotent; safe to call before INSERT

    _validate_csv_columns(csv_path, _STOCK_BOARD_COLS)
    return _seed_full_schema_board_csv(source, csv_path)


def _seed_full_schema_board_csv(source: str, csv_path: Path) -> int:
    """Full-schema 7-col CSV loader (THS + eastmoney use this).

    Wrong-source rows are collected and reported as ONE summary warning at
    EOF (with first 3 samples) — avoids WARN spam with 5000+ rows.
    Empty ``code`` rows are counted (no sample collection — the wrong-source
    case above already proves the value is `r["code"]`-shaped; an empty
    string isn't worth logging verbatim) and skipped, since
    UNIQUE(code, source) would silently collapse them otherwise.
    """
    conn = get_connection()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    rows = []
    skipped_wrong_source_samples: list[str] = []
    skipped_wrong_source_count = 0
    skipped_empty_code_count = 0
    for r in _open_csv(csv_path):
        if r["source"] != source:
            if len(skipped_wrong_source_samples) < _MAX_SAMPLE_RETAINED:
                skipped_wrong_source_samples.append(
                    f"code={r.get('code')!r} source={r['source']!r}"
                )
            skipped_wrong_source_count += 1
            continue
        if not r.get("code"):
            skipped_empty_code_count += 1
            continue
        rows.append(
            (
                r["code"],
                r["name"],
                r["board_type"],
                r["subtype"] or "",
                r["source"],
                # Post-2026-07-20: THS concept rows carry `cid` here
                # (was the `platecode` column). The CSV's `cid` column
                # holds the THS internal concept id (3xxxxx) for concept
                # rows; empty / NULL for industry / eastmoney / zhitu rows.
                # The matching CSV migration swaps old `platecode` data
                # into the `cid` column header.
                r.get("cid") or None,
                now,
            )
        )
    if skipped_wrong_source_count:
        logger.warning(
            "[CSVSeed] %s: %d rows had wrong source (expected %r); first samples: %s",
            csv_path.name,
            skipped_wrong_source_count,
            source,
            skipped_wrong_source_samples,
        )
    if skipped_empty_code_count:
        logger.warning(
            "[CSVSeed] %s: %d rows had empty code; skipped (would collide on UNIQUE)",
            csv_path.name,
            skipped_empty_code_count,
        )
    if not rows:
        logger.warning("[CSVSeed] %s: 0 rows after validation", csv_path.name)
        return 0
    with conn:
        conn.executemany(
            """INSERT OR REPLACE INTO stock_board
               (code, name, board_type, subtype, source, cid, updated_at)
               VALUES (?,?,?,?,?,?,?)""",
            rows,
        )
    logger.info(
        "[CSVSeed] %s: wrote %d boards (source=%s, wrong_source=%d, empty_code=%d)",
        csv_path.name,
        len(rows),
        source,
        skipped_wrong_source_count,
        skipped_empty_code_count,
    )
    return len(rows)


def seed_membership_from_csv(csv_path: Path) -> int:
    """Insert/REPLACE rows from a stock_board_membership-style CSV.

    Rows with invalid stock_code (not 6 ASCII digits) are aggregated and
    reported as ONE summary warning at EOF (with first 3 samples) — same
    defense pattern as ``_seed_full_schema_board_csv`` to avoid WARN spam
    on the 100k+ row membership CSV.

    Returns:
        Number of rows inserted/updated.

    Raises:
        FileNotFoundError, ValueError.
    """
    if not csv_path.exists():
        raise FileNotFoundError(csv_path)
    board_mod.init_schema()
    _validate_csv_columns(csv_path, _MEMBERSHIP_COLS)

    conn = get_connection()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    rows = []
    skipped_invalid_code_samples: list[str] = []
    skipped_invalid_code_count = 0
    for r in _open_csv(csv_path):
        code = r["stock_code"]
        if not (isinstance(code, str) and _VALID_STOCK_CODE.match(code)):
            if len(skipped_invalid_code_samples) < _MAX_SAMPLE_RETAINED:
                skipped_invalid_code_samples.append(repr(code))
            skipped_invalid_code_count += 1
            continue
        rows.append(
            (
                r["board_code"],
                code,
                r["source"],
                r["board_name"],
                r["stock_name"],
                r["board_type"],
                r["subtype"] or "",
                now,
            )
        )
    if skipped_invalid_code_count:
        logger.warning(
            "[CSVSeed] %s: %d rows had invalid stock_code (non-6-digit); first samples: %s",
            csv_path.name,
            skipped_invalid_code_count,
            skipped_invalid_code_samples,
        )
    if not rows:
        logger.warning("[CSVSeed] %s: 0 rows after validation", csv_path.name)
        return 0
    with conn:
        conn.executemany(
            """INSERT OR REPLACE INTO stock_board_membership
               (board_code, stock_code, source, board_name, stock_name,
                board_type, subtype, refreshed_at)
               VALUES (?,?,?,?,?,?,?,?)""",
            rows,
        )
    logger.info(
        "[CSVSeed] %s: wrote %d membership rows (skipped=%d)",
        csv_path.name,
        len(rows),
        skipped_invalid_code_count,
    )
    return len(rows)


def seed_all_from_backup_dir(backup_dir: Path) -> dict[str, int]:
    """Seed both stock_board (THS+eastmoney) and stock_board_membership (THS).

    Missing files: log a warning, skip that source. Don't raise.
    Schema errors (missing columns), encoding errors, malformed rows, and
    SQLite integrity errors: log error, skip that source. Don't raise.
    Anything outside ``_NON_FATAL_SEED_EXCEPTIONS`` propagates so the
    caller (server.py lifespan) can decide whether to crash or continue
    with a partial/empty board cache.

    Returns:
        {'stock_board_ths': N, 'stock_board_eastmoney': M,
         'stock_board_membership_ths': K}. Missing entries are absent.

    Side effect: when files exist but ALL fail (schema/IO error), emits
    one summary ERROR log so the caller can distinguish "no CSVs in the
    backup dir" from "CSVs present but unparseable" — both produce {}.
    """
    results: dict[str, int] = {}
    if not backup_dir.exists():
        logger.warning("[CSVSeed] backup_dir %s does not exist; skipping all", backup_dir)
        return results

    failed_files: list[str] = []
    missing_files: list[str] = []

    ths_board = backup_dir / "stock_board_ths.csv"
    if ths_board.exists():
        try:
            results["stock_board_ths"] = seed_stock_board_from_csv("ths", ths_board)
        except _NON_FATAL_SEED_EXCEPTIONS as e:
            logger.error(
                "[CSVSeed] %s: %s: %s; skipping",
                ths_board.name,
                type(e).__name__,
                e,
            )
            failed_files.append(ths_board.name)
    else:
        logger.warning("[CSVSeed] %s not found; skipping ths stock_board seed", ths_board)
        missing_files.append(ths_board.name)

    ths_member = backup_dir / "stock_board_membership_ths.csv"
    if ths_member.exists():
        try:
            results["stock_board_membership_ths"] = seed_membership_from_csv(ths_member)
        except _NON_FATAL_SEED_EXCEPTIONS as e:
            logger.error(
                "[CSVSeed] %s: %s: %s; skipping",
                ths_member.name,
                type(e).__name__,
                e,
            )
            failed_files.append(ths_member.name)
    else:
        logger.warning("[CSVSeed] %s not found; skipping ths membership seed", ths_member)
        missing_files.append(ths_member.name)

    em_board = backup_dir / "stock_board_eastmoney.csv"
    if em_board.exists():
        try:
            results["stock_board_eastmoney"] = seed_stock_board_from_csv("eastmoney", em_board)
        except _NON_FATAL_SEED_EXCEPTIONS as e:
            logger.error(
                "[CSVSeed] %s: %s: %s; skipping",
                em_board.name,
                type(e).__name__,
                e,
            )
            failed_files.append(em_board.name)
    else:
        logger.warning("[CSVSeed] %s not found; skipping eastmoney stock_board seed", em_board)
        missing_files.append(em_board.name)

    # Distinguish "no CSVs shipped" from "CSVs shipped but ALL failed".
    # Both cases produce results={}; without this summary the operator
    # cannot tell from the high-level log whether to fix CSV format or
    # restore missing files. server.py uses results emptiness alone,
    # so we need this side log. We only emit when NOTHING succeeded —
    # a partial failure is already covered by the per-file ERROR logs above.
    if failed_files and not results:
        logger.error(
            "[CSVSeed] All %d CSV file(s) failed to load: %s. "
            "Board cache will be empty until files are fixed or upstream "
            "backfill runs.",
            len(failed_files),
            failed_files,
        )

    return results


__all__ = [
    "seed_stock_board_from_csv",
    "seed_membership_from_csv",
    "seed_all_from_backup_dir",
]
