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
from datetime import datetime
from pathlib import Path

from . import board as board_mod
from .db import get_connection

logger = logging.getLogger(__name__)

_STOCK_BOARD_COLS = {"code", "name", "board_type", "subtype", "source",
                     "platecode", "updated_at"}
_MEMBERSHIP_COLS = {"board_code", "stock_code", "source", "board_name",
                    "stock_name", "board_type", "subtype", "refreshed_at"}
_EASTMONEY_COLS = {"board_type", "board_code", "board_name"}

_VALID_STOCK_CODE = re.compile(r"^\d{6}$")


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
            raise ValueError(f"{path} is empty")
    missing = required - set(header)
    if missing:
        raise ValueError(f"{path} missing required columns: {sorted(missing)}")


def seed_stock_board_from_csv(source: str, csv_path: Path) -> int:
    """Insert/REPLACE rows from a stock_board-style CSV into the DB.

    Args:
        source: 'ths' (full-schema 7-col CSV) or 'eastmoney' (legacy 3-col).
        csv_path: Path to the CSV file.

    Returns:
        Number of rows inserted/updated.

    Raises:
        FileNotFoundError: csv_path doesn't exist.
        ValueError: schema mismatch (missing required columns).
    """
    board_mod.init_schema()  # idempotent; safe to call before INSERT
    if not csv_path.exists():
        raise FileNotFoundError(csv_path)

    if source == "eastmoney":
        return _seed_eastmoney_board_csv(csv_path)
    _validate_csv_columns(csv_path, _STOCK_BOARD_COLS)
    return _seed_full_schema_board_csv(source, csv_path)


def _seed_full_schema_board_csv(source: str, csv_path: Path) -> int:
    """Full-schema 7-col CSV path (THS uses this).

    Wrong-source rows are collected and reported as ONE summary warning at
    EOF (with first 3 samples) — avoids WARN spam with 5000+ rows.
    """
    board_mod.init_schema()  # idempotent; safe to call before INSERT
    conn = get_connection()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    rows = []
    skipped_wrong_source_samples: list[str] = []
    for r in _open_csv(csv_path):
        if r["source"] != source:
            skipped_wrong_source_samples.append(
                f"code={r.get('code')!r} source={r['source']!r}"
            )
            continue
        rows.append((
            r["code"], r["name"], r["board_type"], r["subtype"] or "",
            r["source"], r["platecode"] or None, now,
        ))
    if skipped_wrong_source_samples:
        logger.warning(
            "[CSVSeed] %s: %d rows had wrong source (expected %r); "
            "first samples: %s",
            csv_path.name, len(skipped_wrong_source_samples), source,
            skipped_wrong_source_samples[:3],
        )
    if not rows:
        logger.warning("[CSVSeed] %s: 0 rows after validation", csv_path.name)
        return 0
    with conn:
        conn.executemany(
            """INSERT OR REPLACE INTO stock_board
               (code, name, board_type, subtype, source, platecode, updated_at)
               VALUES (?,?,?,?,?,?,?)""",
            rows,
        )
    logger.info(
        "[CSVSeed] %s: wrote %d boards (source=%s, skipped=%d)",
        csv_path.name, len(rows), source, len(skipped_wrong_source_samples),
    )
    return len(rows)


def _seed_eastmoney_board_csv(csv_path: Path) -> int:
    """3-col CSV path. Fills source='eastmoney', subtype=board_type,
    platecode=NULL, updated_at=NOW."""
    board_mod.init_schema()
    _validate_csv_columns(csv_path, _EASTMONEY_COLS)
    conn = get_connection()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    rows = []
    for r in _open_csv(csv_path):
        rows.append((
            r["board_code"], r["board_name"], r["board_type"],
            r["board_type"],   # subtype = board_type (eastmoney 唯一合法 subtype)
            "eastmoney",       # source hardcoded
            None,              # platecode = NULL
            now,
        ))
    if not rows:
        return 0
    with conn:
        conn.executemany(
            """INSERT OR REPLACE INTO stock_board
               (code, name, board_type, subtype, source, platecode, updated_at)
               VALUES (?,?,?,?,?,?,?)""",
            rows,
        )
    logger.info("[CSVSeed] %s: wrote %d boards (eastmoney)",
                csv_path.name, len(rows))
    return len(rows)


def seed_membership_from_csv(csv_path: Path) -> int:
    """Insert/REPLACE rows from a stock_board_membership-style CSV.

    Rows with invalid stock_code (not 6 ASCII digits) are skipped with a
    warning — same defense as `_read_board_stocks_from_db`.

    Returns:
        Number of rows inserted/updated.

    Raises:
        FileNotFoundError, ValueError.
    """
    board_mod.init_schema()
    if not csv_path.exists():
        raise FileNotFoundError(csv_path)
    _validate_csv_columns(csv_path, _MEMBERSHIP_COLS)

    conn = get_connection()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    rows = []
    skipped_invalid_code = 0
    for r in _open_csv(csv_path):
        code = r["stock_code"]
        if not (isinstance(code, str) and _VALID_STOCK_CODE.match(code)):
            logger.warning(
                "[CSVSeed] %s: invalid stock_code=%r; skipped",
                csv_path.name, code,
            )
            skipped_invalid_code += 1
            continue
        rows.append((
            r["board_code"], code, r["source"], r["board_name"],
            r["stock_name"], r["board_type"], r["subtype"] or "", now,
        ))
    if not rows:
        return 0
    with conn:
        conn.executemany(
            """INSERT OR REPLACE INTO stock_board_membership
               (board_code, stock_code, source, board_name, stock_name,
                board_type, subtype, refreshed_at)
               VALUES (?,?,?,?,?,?,?,?)""",
            rows,
        )
    logger.info("[CSVSeed] %s: wrote %d membership rows (skipped=%d)",
                csv_path.name, len(rows), skipped_invalid_code)
    return len(rows)


def seed_all_from_backup_dir(backup_dir: Path) -> dict[str, int]:
    """Seed both stock_board (THS+eastmoney) and stock_board_membership (THS).

    Missing files: log a warning, skip that source. Don't raise.
    Schema errors (missing columns): log error, skip that source. Don't raise.

    Returns:
        {'stock_board_ths': N, 'stock_board_eastmoney': M,
         'stock_board_membership_ths': K}. Missing entries are absent.
    """
    results: dict[str, int] = {}
    if not backup_dir.exists():
        logger.warning("[CSVSeed] backup_dir %s does not exist; skipping all",
                       backup_dir)
        return results

    ths_board = backup_dir / "stock_board_ths.csv"
    if ths_board.exists():
        try:
            results["stock_board_ths"] = seed_stock_board_from_csv("ths", ths_board)
        except ValueError as e:
            logger.error("[CSVSeed] %s: schema error: %s; skipping",
                         ths_board.name, e)
    else:
        logger.warning("[CSVSeed] %s not found; skipping ths stock_board seed",
                       ths_board)

    ths_member = backup_dir / "stock_board_membership_ths.csv"
    if ths_member.exists():
        try:
            results["stock_board_membership_ths"] = seed_membership_from_csv(ths_member)
        except ValueError as e:
            logger.error("[CSVSeed] %s: schema error: %s; skipping",
                         ths_member.name, e)
    else:
        logger.warning("[CSVSeed] %s not found; skipping ths membership seed",
                       ths_member)

    em_board = backup_dir / "stock_board_eastmoney.csv"
    if em_board.exists():
        try:
            results["stock_board_eastmoney"] = seed_stock_board_from_csv(
                "eastmoney", em_board)
        except ValueError as e:
            logger.error("[CSVSeed] %s: schema error: %s; skipping",
                         em_board.name, e)
    else:
        logger.warning("[CSVSeed] %s not found; skipping eastmoney stock_board seed",
                       em_board)

    return results


__all__ = [
    "seed_stock_board_from_csv",
    "seed_membership_from_csv",
    "seed_all_from_backup_dir",
]
