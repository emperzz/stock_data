# CSV Seed for Board Cache — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a CSV-based seed mechanism for `stock_board` and `stock_board_membership` tables. When `STOCK_DB_INIT=true`, the server loads CSVs from `stock_data/stock_data_backup/` into the freshly-reset DB, decoupling fast startup from the slow upstream backfill.

**Architecture:** New module `stock_data/data_provider/persistence/board_csv.py` exposes 3 pure functions (`seed_stock_board_from_csv`, `seed_membership_from_csv`, `seed_all_from_backup_dir`). `server.py` lifespan calls `seed_all_from_backup_dir` immediately after `persistence.reset_all()`. Two error tiers: per-file (warn + skip) and per-row (warn + skip). No fetcher involvement.

**Tech Stack:** Python stdlib (`csv`, `sqlite3`, `pathlib`, `datetime`), pytest fixtures (no new deps).

**Reference Spec:** `docs/superpowers/specs/2026-07-12-csv-seed-for-board-cache-design.md` (692 lines, 8 sections).

---

## File Structure

**New files (5):**
- `stock_data/data_provider/persistence/board_csv.py` — loader module (~150 lines)
- `stock_data/stock_data_backup/stock_board_ths.csv` — THS board list (7 cols, ~385 rows, ~50KB)
- `stock_data/stock_data_backup/stock_board_membership_ths.csv` — THS memberships (8 cols, ~5000 rows, ~500KB)
- `stock_data/stock_data_backup/stock_board_eastmoney.csv` — eastmoney boards (3 cols, 992 rows, ~31KB; renamed from `stock_data/boards_akshare_name_em.csv`)
- `tests/test_board_csv_seed.py` — 10 tests + `fresh_db` fixture (~250 lines)

**Modified files (4):**
- `stock_data/data_provider/persistence/__init__.py` — expose `board_csv` module + `seed_all_from_backup_dir`
- `stock_data/server.py` — add CSV seed call inside the `if db_init:` branch of `lifespan` (~6 lines)
- `.gitignore` — whitelist `stock_data/stock_data_backup/*.csv` (override `*.csv` rule)
- `.env.example` — append CSV seed documentation after `BOARD_BACKFILL_ON_STARTUP` block

**Renamed file (1):**
- `stock_data/boards_akshare_name_em.csv` → `stock_data/stock_data_backup/stock_board_eastmoney.csv` (via `git mv`)

---

## Task 1: Test infra + first failing test for THS stock_board CSV seed

**Files:**
- Create: `tests/test_board_csv_seed.py`

- [ ] **Step 1: Create test file with `fresh_db` fixture**

Write `tests/test_board_csv_seed.py`:

```python
"""Tests for persistence.board_csv module (CSV seed for stock_board + membership)."""
from __future__ import annotations

import logging
import os
import re
from pathlib import Path

import pytest

from stock_data.data_provider.persistence import board as board_mod
from stock_data.data_provider.persistence import board_csv
from stock_data.data_provider.persistence import db as db_mod


@pytest.fixture
def fresh_db(tmp_path, monkeypatch):
    """Ephemeral SQLite DB — reset module singletons so init_schema reruns.

    Mirrors the pattern in tests/test_board_backfill.py.
    """
    monkeypatch.setattr(db_mod, "_db_path", None)
    monkeypatch.setattr(db_mod, "_conn", None)
    monkeypatch.setattr(board_mod, "_schema_initialized_paths", set())
    monkeypatch.setenv("STOCK_CACHE_DB_PATH", str(tmp_path / "test.db"))
    board_mod.init_schema()
    yield tmp_path / "test.db"


def test_seed_stock_board_ths_full_schema(fresh_db, tmp_path):
    """7-col THS CSV → all rows written to stock_board with source='ths'."""
    csv_path = tmp_path / "stock_board_ths.csv"
    csv_path.write_text(
        "code,name,board_type,subtype,source,platecode,updated_at\n"
        "885001,煤炭,industry,同花顺行业,ths,881001,2026-07-12 17:30:00\n"
        "885002,白酒,concept,同花顺概念,ths,885002,2026-07-12 17:30:00\n",
        encoding="utf-8-sig",
    )

    n = board_csv.seed_stock_board_from_csv("ths", csv_path)
    assert n == 2

    industry_rows = board_mod._read_boards_from_db("industry", "ths")
    assert len(industry_rows) == 1
    assert industry_rows[0]["code"] == "885001"
    assert industry_rows[0]["platecode"] == "881001"

    concept_rows = board_mod._read_boards_from_db("concept", "ths")
    assert len(concept_rows) == 1
    assert concept_rows[0]["code"] == "885002"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_board_csv_seed.py::test_seed_stock_board_ths_full_schema -v`

Expected: FAIL with `ModuleNotFoundError: No module named 'stock_data.data_provider.persistence.board_csv'` (the module doesn't exist yet).

- [ ] **Step 3: Implement `board_csv.py` skeleton + helpers + `seed_stock_board_from_csv` THS path**

Create `stock_data/data_provider/persistence/board_csv.py`:

```python
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
```

Note: `re` is imported at top of file (instead of `__import__("re")` inline as in spec pseudocode).

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/test_board_csv_seed.py::test_seed_stock_board_ths_full_schema -v`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add tests/test_board_csv_seed.py stock_data/data_provider/persistence/board_csv.py
git -c core.autocrlf=false commit -m "feat(persistence): board_csv module + test infra + THS stock_board seed

Initial board_csv.py skeleton with:
- seed_stock_board_from_csv (THS full-schema 7-col path)
- _seed_eastmoney_board_csv (legacy 3-col eastmoney path)
- seed_membership_from_csv (8-col membership path)
- seed_all_from_backup_dir (orchestrator)
- helpers: _open_csv (utf-8-sig), _validate_csv_columns

All public functions call init_schema() so they work standalone
(not only when called from server.py after reset_all()).

Wrong-source rows in THS CSV emit ONE summary warning with first
3 samples (not per-row WARN that would spam).

Reference: docs/superpowers/specs/2026-07-12-csv-seed-for-board-cache-design.md §4

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 2: Add test + verify eastmoney 3-col path

**Files:**
- Modify: `tests/test_board_csv_seed.py`

- [ ] **Step 1: Add test for eastmoney 3-col default filling**

Append to `tests/test_board_csv_seed.py`:

```python
def test_seed_eastmoney_3col_fills_defaults(fresh_db, tmp_path):
    """3-col eastmoney CSV: source/subtype/platecode 由 loader 填充.

    Verifies both industry AND concept rows are written correctly
    (not just industry — avoids half-coverage regression).
    """
    csv_path = tmp_path / "stock_board_eastmoney.csv"
    csv_path.write_text(
        "board_type,board_code,board_name\n"
        "industry,BK1627,综合Ⅲ\n"
        "concept,BK1701,融资融券\n",
        encoding="utf-8-sig",
    )

    n = board_csv.seed_stock_board_from_csv("eastmoney", csv_path)
    assert n == 2

    industry_rows = board_mod._read_boards_from_db("industry", "eastmoney")
    assert len(industry_rows) == 1
    assert industry_rows[0]["code"] == "BK1627"
    assert industry_rows[0]["subtype"] == "industry"
    assert industry_rows[0]["platecode"] is None
    assert industry_rows[0]["source"] == "eastmoney"

    # concept 行也必须正确写入(否则只验了 industry 一半覆盖)
    concept_rows = board_mod._read_boards_from_db("concept", "eastmoney")
    assert len(concept_rows) == 1
    assert concept_rows[0]["code"] == "BK1701"
    assert concept_rows[0]["subtype"] == "concept"
```

- [ ] **Step 2: Run test to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/test_board_csv_seed.py::test_seed_eastmoney_3col_fills_defaults -v`

Expected: PASS (already implemented in Task 1). If FAIL, debug.

- [ ] **Step 3: Commit**

```bash
git add tests/test_board_csv_seed.py
git -c core.autocrlf=false commit -m "test(persistence): eastmoney 3-col CSV fills source/subtype/platecode defaults

Verifies both industry AND concept rows are handled — earlier draft
only asserted industry rows, leaving concept path untested.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 3: Add test + verify membership CSV loader

**Files:**
- Modify: `tests/test_board_csv_seed.py`

- [ ] **Step 1: Add test for membership with valid codes**

Append:

```python
def test_seed_membership_with_valid_codes(fresh_db, tmp_path):
    """8-col membership CSV → all rows written to stock_board_membership."""
    csv_path = tmp_path / "stock_board_membership_ths.csv"
    csv_path.write_text(
        "board_code,stock_code,source,board_name,stock_name,"
        "board_type,subtype,refreshed_at\n"
        "885002,600519,ths,白酒,贵州茅台,concept,同花顺概念,2026-07-12 17:30:00\n"
        "885002,000858,ths,白酒,五粮液,concept,同花顺概念,2026-07-12 17:30:00\n",
        encoding="utf-8-sig",
    )

    n = board_csv.seed_membership_from_csv(csv_path)
    assert n == 2

    rows = board_mod.read_membership(board_code="885002", source="ths")
    assert len(rows) == 2
    stock_codes = {r["stock_code"] for r in rows}
    assert stock_codes == {"600519", "000858"}
    assert any(r["stock_name"] == "贵州茅台" for r in rows)
```

- [ ] **Step 2: Run test to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/test_board_csv_seed.py::test_seed_membership_with_valid_codes -v`

Expected: PASS (already implemented in Task 1).

- [ ] **Step 3: Commit**

```bash
git add tests/test_board_csv_seed.py
git -c core.autocrlf=false commit -m "test(persistence): membership CSV with valid 6-digit stock_codes

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 4: Add test for invalid stock_code skip + wrong-source summary warn

**Files:**
- Modify: `tests/test_board_csv_seed.py`

- [ ] **Step 1: Add test for invalid stock_code skip**

Append:

```python
def test_seed_membership_skips_invalid_stock_code(fresh_db, tmp_path, caplog):
    """无效 stock_code (非 6 位数字) warning + skip, 其余行写入."""
    csv_path = tmp_path / "stock_board_membership_ths.csv"
    csv_path.write_text(
        "board_code,stock_code,source,board_name,stock_name,"
        "board_type,subtype,refreshed_at\n"
        "885002,600519,ths,白酒,贵州茅台,concept,同花顺概念,2026-07-12 17:30:00\n"
        "885002,贵州茅台,ths,白酒,五粮液,concept,同花顺概念,2026-07-12 17:30:00\n"
        "885002,000858,ths,白酒,五粮液,concept,同花顺概念,2026-07-12 17:30:00\n",
        encoding="utf-8-sig",
    )

    with caplog.at_level(
        logging.WARNING,
        logger="stock_data.data_provider.persistence.board_csv",
    ):
        n = board_csv.seed_membership_from_csv(csv_path)
    assert n == 2
    assert any(
        "invalid stock_code" in r.message and "贵州茅台" in r.message
        for r in caplog.records
    ), f"expected invalid_code warning; got: {[r.message for r in caplog.records]}"
```

- [ ] **Step 2: Add test for wrong-source summary warning**

Append:

```python
def test_seed_full_schema_skips_wrong_source_row(fresh_db, tmp_path, caplog):
    """CSV 里混一行 source='eastmoney' → 该行被 skip, summary warning 触发.

    验证 wrong-source 行被跳过(不写入 DB)+ 一条 summary warning(不是逐行
    warning, 避免 5000 行 spam)。
    """
    csv_path = tmp_path / "stock_board_ths.csv"
    csv_path.write_text(
        "code,name,board_type,subtype,source,platecode,updated_at\n"
        "885001,煤炭,industry,同花顺行业,ths,881001,2026-07-12 17:30:00\n"
        "885002,白酒,concept,同花顺概念,eastmoney,885002,2026-07-12 17:30:00\n"
        "885003,医药,concept,同花顺概念,ths,885003,2026-07-12 17:30:00\n",
        encoding="utf-8-sig",
    )

    with caplog.at_level(
        logging.WARNING,
        logger="stock_data.data_provider.persistence.board_csv",
    ):
        n = board_csv.seed_stock_board_from_csv("ths", csv_path)
    assert n == 2  # only 2 rows with source='ths'

    # Summary warning should mention count=1 and source='eastmoney'
    summary_records = [
        r for r in caplog.records
        if "wrong source" in r.message and "1 rows" in r.message
    ]
    assert len(summary_records) == 1, (
        f"expected exactly one summary warning; got: "
        f"{[r.message for r in caplog.records]}"
    )

    # Verify the wrong-source row was NOT inserted
    rows = board_mod.read_membership(
        board_code="885002", source="ths"
    )
    assert rows == []
```

- [ ] **Step 3: Run tests to verify both pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_board_csv_seed.py::test_seed_membership_skips_invalid_stock_code tests/test_board_csv_seed.py::test_seed_full_schema_skips_wrong_source_row -v`

Expected: 2 PASS (already implemented in Task 1).

- [ ] **Step 4: Commit**

```bash
git add tests/test_board_csv_seed.py
git -c core.autocrlf=false commit -m "test(persistence): invalid stock_code skip + wrong-source summary warn

Wrong-source rows: verifies the summary warning behavior (one
warning with first 3 samples + count) — not per-row WARN that
would spam logs with 5000+ rows.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 5: Add test for schema validation (missing columns)

**Files:**
- Modify: `tests/test_board_csv_seed.py`

- [ ] **Step 1: Add test for missing columns raises ValueError**

Append:

```python
def test_seed_missing_columns_raises_value_error(fresh_db, tmp_path):
    """缺必需列 → ValueError(被 seed_all_from_backup_dir 包成 log error, 不致命)."""
    csv_path = tmp_path / "stock_board_ths.csv"
    csv_path.write_text(
        "code,name,board_type,subtype,source,updated_at\n"  # missing platecode
        "885001,煤炭,industry,同花顺行业,ths,2026-07-12 17:30:00\n",
        encoding="utf-8-sig",
    )

    with pytest.raises(ValueError, match="missing required columns"):
        board_csv.seed_stock_board_from_csv("ths", csv_path)

    # seed_all_from_backup_dir should swallow the ValueError (log error + skip)
    backup_dir = tmp_path / "backup"
    backup_dir.mkdir()
    (backup_dir / "stock_board_ths.csv").write_text(
        csv_path.read_text(encoding="utf-8-sig"),
        encoding="utf-8-sig",
    )
    results = board_csv.seed_all_from_backup_dir(backup_dir)
    # ths board skipped due to schema error; nothing else to load
    assert "stock_board_ths" not in results
```

- [ ] **Step 2: Run test to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/test_board_csv_seed.py::test_seed_missing_columns_raises_value_error -v`

Expected: PASS (already implemented in Task 1).

- [ ] **Step 3: Commit**

```bash
git add tests/test_board_csv_seed.py
git -c core.autocrlf=false commit -m "test(persistence): missing columns raises ValueError, swallowed by orchestrator

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 6: Add tests for seed_all_from_backup_dir orchestration

**Files:**
- Modify: `tests/test_board_csv_seed.py`

- [ ] **Step 1: Add test for missing backup_dir**

Append:

```python
def test_seed_all_from_backup_dir_missing_dir(tmp_path, caplog):
    """backup_dir 不存在 → 返回空 dict, log warning."""
    missing = tmp_path / "does_not_exist"
    with caplog.at_level(
        logging.WARNING,
        logger="stock_data.data_provider.persistence.board_csv",
    ):
        results = board_csv.seed_all_from_backup_dir(missing)
    assert results == {}
    assert any("does not exist" in r.message for r in caplog.records)
```

- [ ] **Step 2: Add test for empty backup_dir (all files missing)**

Append:

```python
def test_seed_all_from_backup_dir_missing_files(tmp_path, caplog):
    """目录存在但 3 个文件全缺 → 每个都 warning, 返回空 dict."""
    empty_dir = tmp_path / "empty_backup"
    empty_dir.mkdir()
    with caplog.at_level(
        logging.WARNING,
        logger="stock_data.data_provider.persistence.board_csv",
    ):
        results = board_csv.seed_all_from_backup_dir(empty_dir)
    assert results == {}
    not_found_warnings = [
        r for r in caplog.records if "not found" in r.message
    ]
    assert len(not_found_warnings) == 3
```

- [ ] **Step 3: Add test for partial files (only ths board)**

Append:

```python
def test_seed_all_from_backup_dir_partial_files(fresh_db, tmp_path):
    """只有 ths board 在 → 返回 {'stock_board_ths': N}, 其余 key 不在 dict 里.

    关键: missing entries are absent (NOT present-with-zero) — spec §5.2.5
    """
    backup_dir = tmp_path / "partial_backup"
    backup_dir.mkdir()
    (backup_dir / "stock_board_ths.csv").write_text(
        "code,name,board_type,subtype,source,platecode,updated_at\n"
        "885001,煤炭,industry,同花顺行业,ths,881001,2026-07-12 17:30:00\n",
        encoding="utf-8-sig",
    )
    # membership + eastmoney files intentionally absent

    results = board_csv.seed_all_from_backup_dir(backup_dir)
    assert results == {"stock_board_ths": 1}
    # Explicitly assert the other two keys are absent (not present-with-zero)
    assert "stock_board_membership_ths" not in results
    assert "stock_board_eastmoney" not in results
```

- [ ] **Step 4: Run tests to verify all pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_board_csv_seed.py::test_seed_all_from_backup_dir_missing_dir tests/test_board_csv_seed.py::test_seed_all_from_backup_dir_missing_files tests/test_board_csv_seed.py::test_seed_all_from_backup_dir_partial_files -v`

Expected: 3 PASS.

- [ ] **Step 5: Commit**

```bash
git add tests/test_board_csv_seed.py
git -c core.autocrlf=false commit -m "test(persistence): seed_all_from_backup_dir orchestration tests

Covers missing dir, empty dir (all files missing), partial files.
Verifies missing keys are absent (not present-with-zero) per spec §5.2.5.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 7: Add test for idempotency (re-run produces same row count)

**Files:**
- Modify: `tests/test_board_csv_seed.py`

- [ ] **Step 1: Add idempotency test**

Append:

```python
def test_seed_idempotent_re_run(fresh_db, tmp_path):
    """同 CSV 跑两次 → 行数不变 (INSERT OR REPLACE)."""
    csv_path = tmp_path / "stock_board_ths.csv"
    csv_path.write_text(
        "code,name,board_type,subtype,source,platecode,updated_at\n"
        "885001,煤炭,industry,同花顺行业,ths,881001,2026-07-12 17:30:00\n"
        "885002,白酒,concept,同花顺概念,ths,885002,2026-07-12 17:30:00\n",
        encoding="utf-8-sig",
    )

    n1 = board_csv.seed_stock_board_from_csv("ths", csv_path)
    rows_after_first = board_mod._read_boards_from_db("industry", "ths")
    rows_after_first += board_mod._read_boards_from_db("concept", "ths")
    first_count = len(rows_after_first)

    n2 = board_csv.seed_stock_board_from_csv("ths", csv_path)
    rows_after_second = board_mod._read_boards_from_db("industry", "ths")
    rows_after_second += board_mod._read_boards_from_db("concept", "ths")
    second_count = len(rows_after_second)

    assert n1 == 2 and n2 == 2
    assert first_count == second_count == 2
```

- [ ] **Step 2: Run test to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/test_board_csv_seed.py::test_seed_idempotent_re_run -v`

Expected: PASS.

- [ ] **Step 3: Commit**

```bash
git add tests/test_board_csv_seed.py
git -c core.autocrlf=false commit -m "test(persistence): idempotent re-run produces same row count

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 8: Run all 10 tests together + fix any flakes

**Files:** none (verification only)

- [ ] **Step 1: Run all tests in the new file**

Run: `.venv/Scripts/python.exe -m pytest tests/test_board_csv_seed.py -v`

Expected: 10 PASSED (one test per row of spec §7.2 test table).

- [ ] **Step 2: Run ruff check + format on new files**

Run:
```bash
ruff check stock_data/data_provider/persistence/board_csv.py tests/test_board_csv_seed.py
ruff format --check stock_data/data_provider/persistence/board_csv.py tests/test_board_csv_seed.py
```

Expected: no lint errors, no format diffs. If either fails, fix inline and re-run.

- [ ] **Step 3: Commit any formatting fixes (if any)**

```bash
git add -u
git -c core.autocrlf=false commit -m "style: ruff format board_csv.py + test_board_csv_seed.py" || echo "no formatting changes"
```

---

## Task 9: Expose board_csv module via persistence/__init__.py

**Files:**
- Modify: `stock_data/data_provider/persistence/__init__.py`

- [ ] **Step 1: Add `board_csv` to imports**

Edit `stock_data/data_provider/persistence/__init__.py` line 14:

Change:
```python
from . import board, pool_daily, stock_list, trade_calendar
```

To:
```python
from . import board, board_csv, pool_daily, stock_list, trade_calendar
```

- [ ] **Step 2: Add `board_csv` to `__all__`**

Edit the `__all__` list in `stock_data/data_provider/persistence/__init__.py` (after `"board"` entry):

Insert:
```python
    "board_csv",
```

- [ ] **Step 3: Verify import works**

Run: `.venv/Scripts/python.exe -c "from stock_data.data_provider.persistence import board_csv, seed_all_from_backup_dir; print('imports OK')"`

Expected: `imports OK`. If `seed_all_from_backup_dir` is not in `__init__.py` yet, this will fail — also add to `__all__`:

```python
    # CSV seed
    "seed_all_from_backup_dir",
```

- [ ] **Step 4: Commit**

```bash
git add stock_data/data_provider/persistence/__init__.py
git -c core.autocrlf=false commit -m "feat(persistence): expose board_csv module + seed_all_from_backup_dir

Makes the new CSV seed API importable from stock_data.data_provider.persistence,
matching the existing pattern for board / stock_list / trade_calendar.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 10: Integrate seed_all_from_backup_dir into server.py lifespan

**Files:**
- Modify: `stock_data/server.py`

- [ ] **Step 1: Read current `if db_init:` block**

Locate lines 55-64 of `stock_data/server.py`. Current code:

```python
    db_init = os.getenv("STOCK_DB_INIT", "false").lower() == "true"
    if db_init:
        logger.warning(
            "[Startup] STOCK_DB_INIT=true — DROPPING and recreating ALL persistence "
            "tables. All previously cached metadata will be lost."
        )
        persistence.reset_all()
    else:
        persistence.init_schema()
        logger.info("[Startup] Persistence schema ensured (STOCK_DB_INIT=false)")
```

- [ ] **Step 2: Insert CSV seed call inside the `if db_init:` block**

Replace the `if db_init:` block with:

```python
    db_init = os.getenv("STOCK_DB_INIT", "false").lower() == "true"
    if db_init:
        logger.warning(
            "[Startup] STOCK_DB_INIT=true — DROPPING and recreating ALL persistence "
            "tables. All previously cached metadata will be lost."
        )
        persistence.reset_all()

        # ----- CSV seed from stock_data_backup/ (opt-out via missing files) -----
        # When STOCK_DB_INIT=true, after reset_all() the tables are empty. Re-seed
        # from the repo-managed CSV backups so the server has data immediately,
        # without paying the ~17min upstream backfill cost. If
        # BOARD_BACKFILL_ON_STARTUP=true also fires below, the upstream refresh
        # will overwrite the CSV data shortly after.
        from pathlib import Path
        backup_dir = Path(__file__).parent / "stock_data_backup"
        seed_results = persistence.seed_all_from_backup_dir(backup_dir)
        if seed_results:
            logger.info("[Startup] CSV seed complete: %s", seed_results)
        else:
            logger.info("[Startup] CSV seed skipped (no files in %s)", backup_dir)
    else:
        persistence.init_schema()
        logger.info("[Startup] Persistence schema ensured (STOCK_DB_INIT=false)")
```

- [ ] **Step 3: Verify server.py imports cleanly (no syntax errors)**

Run: `.venv/Scripts/python.exe -c "import ast; ast.parse(open('stock_data/server.py').read()); print('syntax OK')"`

Expected: `syntax OK`.

- [ ] **Step 4: Commit**

```bash
git add stock_data/server.py
git -c core.autocrlf=false commit -m "feat(server): CSV seed after reset_all() in lifespan

When STOCK_DB_INIT=true, after the drop+recreate the server now
loads CSVs from stock_data/stock_data_backup/ before any client
request can hit the empty tables. Decouples fast startup (CSV)
from upstream refresh (BOARD_BACKFILL_ON_STARTUP).

Reference: docs/superpowers/specs/2026-07-12-csv-seed-for-board-cache-design.md §4.2

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 11: Update .gitignore to whitelist stock_data_backup/

**Files:**
- Modify: `.gitignore`

- [ ] **Step 1: Add the negation pattern**

After the existing `/stock_data/stock_cache.db*` block (around line 99), append:

```gitignore

# Repo-managed CSV seed backups (force-tracked; loader reads on STOCK_DB_INIT=true).
# Negation pattern includes *.csv explicitly because gitignore rules match
# against the full path — a bare directory negation wouldn't override the
# project-wide *.csv exclusion above.
!stock_data/stock_data_backup/*.csv
```

- [ ] **Step 2: Verify the negation works**

Run: `git check-ignore -v stock_data/stock_data_backup/stock_board_ths.csv`

Expected: exit code 1 (file is NOT ignored — will be tracked). If exit code 0 with `*.csv` shown, the negation isn't taking effect; re-check pattern.

- [ ] **Step 3: Commit**

```bash
git add .gitignore
git -c core.autocrlf=false commit -m "build(gitignore): whitelist stock_data_backup/*.csv

Loader reads these CSVs on STOCK_DB_INIT=true — must be tracked
in the repo for fresh clones to have immediate data.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 12: Document CSV seed section in .env.example

**Files:**
- Modify: `.env.example`

- [ ] **Step 1: Locate BOARD_BACKFILL_ON_STARTUP block**

Open `.env.example`. The relevant block is around lines 115-125:

```bash
# === Board cache backfill on startup ===
# When true: at server startup, fully refresh stock_board (THS) and
# stock_board_membership (THS, via zzshare) so /stocks/{code}/boards
# cache-miss responses return the COMPLETE set of boards (instead of
# just the few that happened to be queried once).
#
# Adds ~17min at startup (rate-limited <=50/min for zzshare with token;
# ~43min anonymous at 20/min). Default disabled — opt in by setting
# to true when the server can afford the cold-start time.
# BOARD_BACKFILL_ON_STARTUP=false
```

- [ ] **Step 2: Append CSV seed section after this block**

After line 125 (the `# BOARD_BACKFILL_ON_STARTUP=false` line), append a blank line then:

```bash
# === CSV seed on STOCK_DB_INIT=true ===
# When STOCK_DB_INIT=true, the persistence layer ALSO loads CSVs from
# stock_data/stock_data_backup/ into the freshly-reset database. This
# gives the server immediate data without paying the ~17min upstream
# backfill cost. Files expected:
#   - stock_board_ths.csv            (full schema; 7 cols)
#   - stock_board_membership_ths.csv (full schema; 8 cols)
#   - stock_board_eastmoney.csv      (legacy 3-col schema; auto-filled defaults)
# Missing files log a warning and are skipped. Schema errors (missing
# columns) are non-fatal — that source is skipped, others still load.
#
# Typical combinations:
#   STOCK_DB_INIT=true,  BOARD_BACKFILL_ON_STARTUP=false  → fast: CSV only, ~0ms
#   STOCK_DB_INIT=true,  BOARD_BACKFILL_ON_STARTUP=true   → CSV seed then refresh
#   STOCK_DB_INIT=false, BOARD_BACKFILL_ON_STARTUP=true   → upstream refresh only
#   STOCK_DB_INIT=false, BOARD_BACKFILL_ON_STARTUP=false  → nothing happens
```

- [ ] **Step 3: Commit**

```bash
git add .env.example
git -c core.autocrlf=false commit -m "docs(env): document CSV seed behavior + flag combinations

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 13: Rename eastmoney CSV + export THS data CSVs

**Files:**
- Rename: `stock_data/boards_akshare_name_em.csv` → `stock_data/stock_data_backup/stock_board_eastmoney.csv`
- Create: `stock_data/stock_data_backup/stock_board_ths.csv`
- Create: `stock_data/stock_data_backup/stock_board_membership_ths.csv`

- [ ] **Step 1: Create the backup directory**

Run: `mkdir -p stock_data/stock_data_backup`

- [ ] **Step 2: Rename the eastmoney CSV (preserve git history)**

Run:
```bash
git mv stock_data/boards_akshare_name_em.csv stock_data/stock_data_backup/stock_board_eastmoney.csv
```

Expected: Git reports a rename (R) not a delete+add. Verify with `git status` — should show `R stock_data/boards_akshare_name_em.csv -> stock_data/stock_data_backup/stock_board_eastmoney.csv`.

- [ ] **Step 3: Export THS boards to CSV**

Run (from repo root):
```bash
.venv/Scripts/python.exe -c "
import sqlite3, csv
conn = sqlite3.connect('stock_data/stock_cache.db')
conn.row_factory = sqlite3.Row

with open('stock_data/stock_data_backup/stock_board_ths.csv', 'w',
          newline='', encoding='utf-8') as f:
    w = csv.writer(f)
    w.writerow(['code','name','board_type','subtype','source','platecode','updated_at'])
    for r in conn.execute(\"SELECT code,name,board_type,subtype,source,platecode,updated_at FROM stock_board WHERE source='ths' ORDER BY board_type, code\"):
        w.writerow([r['code'], r['name'], r['board_type'], r['subtype'], r['source'], r['platecode'], r['updated_at']])

print('ths board rows:', conn.execute(\"SELECT COUNT(*) FROM stock_board WHERE source='ths'\").fetchone()[0])
"
```

Expected: prints a row count (e.g., `ths board rows: 385`). Verify the CSV file exists with `wc -l stock_data/stock_data_backup/stock_board_ths.csv` showing N+1 lines (header + N data rows).

- [ ] **Step 4: Export THS membership to CSV**

Run:
```bash
.venv/Scripts/python.exe -c "
import sqlite3, csv
conn = sqlite3.connect('stock_data/stock_cache.db')
conn.row_factory = sqlite3.Row

with open('stock_data/stock_data_backup/stock_board_membership_ths.csv', 'w',
          newline='', encoding='utf-8') as f:
    w = csv.writer(f)
    w.writerow(['board_code','stock_code','source','board_name','stock_name','board_type','subtype','refreshed_at'])
    for r in conn.execute(\"SELECT board_code,stock_code,source,board_name,stock_name,board_type,subtype,refreshed_at FROM stock_board_membership WHERE source='ths' ORDER BY board_code, stock_code\"):
        w.writerow([r['board_code'], r['stock_code'], r['source'], r['board_name'], r['stock_name'], r['board_type'], r['subtype'], r['refreshed_at']])

print('ths membership rows:', conn.execute(\"SELECT COUNT(*) FROM stock_board_membership WHERE source='ths'\").fetchone()[0])
"
```

Expected: prints a row count (e.g., `ths membership rows: 5123`).

- [ ] **Step 5: Force-add the new CSVs (override .gitignore for these specific paths)**

Run:
```bash
git add -f stock_data/stock_data_backup/stock_board_ths.csv
git add -f stock_data/stock_data_backup/stock_board_membership_ths.csv
git add stock_data/stock_data_backup/stock_board_eastmoney.csv  # already added via git mv
git status
```

Expected: All 3 CSV files show as staged (under "Changes to be committed").

- [ ] **Step 6: Verify CSV contents look right (sanity check)**

Run: `head -3 stock_data/stock_data_backup/stock_board_ths.csv && echo "---" && head -3 stock_data/stock_data_backup/stock_board_membership_ths.csv && echo "---" && head -3 stock_data/stock_data_backup/stock_board_eastmoney.csv`

Expected: each shows a header row + 2 data rows. Confirm column names match the schema.

- [ ] **Step 7: Commit**

```bash
git add stock_data/stock_data_backup/
git -c core.autocrlf=false commit -m "feat(persistence): backup CSVs in stock_data_backup/

- stock_board_eastmoney.csv: renamed from boards_akshare_name_em.csv
  (preserves 992 rows of eastmoney BK-code boards with akshare names)
- stock_board_ths.csv: full 7-col schema, exported from current DB
- stock_board_membership_ths.csv: full 8-col schema, exported from current DB

These CSVs are loaded by stock_data.server lifespan when STOCK_DB_INIT=true,
giving the server immediate data without paying the ~17min upstream backfill.

Reference: docs/superpowers/specs/2026-07-12-csv-seed-for-board-cache-design.md §3

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 14: End-to-end smoke test + lint + final commit

**Files:** none (verification only)

- [ ] **Step 1: Run the full project test suite (default = no live_network)**

Run: `.venv/Scripts/python.exe -m pytest -v --tb=short 2>&1 | tail -50`

Expected: all tests pass (including the 10 new tests). No regressions in existing test_board_backfill.py or test_persistence_init.py.

- [ ] **Step 2: Run ruff check on changed files**

Run:
```bash
ruff check stock_data/data_provider/persistence/board_csv.py stock_data/data_provider/persistence/__init__.py stock_data/server.py tests/test_board_csv_seed.py
```

Expected: no lint errors.

- [ ] **Step 3: Run ruff format check on changed files**

Run:
```bash
ruff format --check stock_data/data_provider/persistence/board_csv.py stock_data/data_provider/persistence/__init__.py stock_data/server.py tests/test_board_csv_seed.py
```

Expected: no format diffs.

- [ ] **Step 4: Verify git status is clean**

Run: `git status`

Expected: `nothing to commit, working tree clean`. If any uncommitted changes, commit them with a descriptive message.

- [ ] **Step 5: (Optional) Manual smoke test — start server with STOCK_DB_INIT=true**

Run (in a separate terminal, then Ctrl-C after 5 seconds):
```bash
STOCK_DB_INIT=true .venv/Scripts/python.exe -m stock_data.server 2>&1 | grep -E "CSVSeed|Startup"
```

Expected log lines (subset):
```
[Startup] STOCK_DB_INIT=true — DROPPING and recreating ALL persistence tables...
[CSVSeed] stock_board_ths.csv: wrote 385 boards (source=ths, skipped=0)
[CSVSeed] stock_board_membership_ths.csv: wrote 5123 membership rows (skipped=0)
[CSVSeed] stock_board_eastmoney.csv: wrote 992 boards (eastmoney)
[Startup] CSV seed complete: {'stock_board_ths': 385, 'stock_board_membership_ths': 5123, 'stock_board_eastmoney': 992}
```

(Actual row counts may differ based on the DB state at the time of export.)

- [ ] **Step 6: Final commit (only if Step 1-4 surfaced fixes)**

```bash
git add -u
git -c core.autocrlf=false commit -m "fix: lint/format/test fixes from end-to-end smoke test" || echo "no fixes needed"
```

---

## Summary

**13 tasks, ~14 commits.** Total feature:

| Component | LoC |
|---|---|
| `board_csv.py` | ~155 lines |
| `test_board_csv_seed.py` | ~250 lines |
| `server.py` diff | +13 lines |
| `persistence/__init__.py` diff | +2 lines |
| `.gitignore` diff | +5 lines |
| `.env.example` diff | +18 lines |
| CSV data files | ~500KB binary |

After completion, the server starts up with full board cache data when `STOCK_DB_INIT=true`, without paying the ~17min upstream backfill cost.