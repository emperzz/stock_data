# Stock Board Membership Reverse Index Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a `stock_board_membership` reverse-index table so any STOCK_BOARD source can answer stock→boards queries with <10ms latency, without changing any fetcher interface.

**Architecture:** Single new SQLite table replaces `stock_board_stock` after a one-shot migration. Forward path (`/boards/{code}/stocks`) writes both tables during a transition window; reverse path (`/stocks/{code}/boards`) reads the new table and falls back to a single zhitu upstream call. A new CLI tool (`tools/build_membership_index.py`) walks all boards per-source in worker threads for full bootstrap.

**Tech Stack:** Python 3.x, SQLite (WAL mode), FastAPI, Pydantic, pytest, ruff. No new third-party deps.

**Reference:**
- Spec: `docs/superpowers/specs/2026-07-01-stock-board-membership-design.md`
- Design doc: `docs/stock-board-reverse-index-design-2026-07-01.md`

---

## File Structure

### Files to Create

| Path | Responsibility |
|---|---|
| `stock_data/tools/__init__.py` | Mark `stock_data.tools` as a package |
| `stock_data/tools/build_membership_index.py` | CLI: per-source worker thread walker + upsert |
| `stock_data/tools/README.md` | CLI usage doc |
| `scripts/__init__.py` | Mark `scripts` as a package (allows test discovery) |
| `scripts/migrate_to_membership.py` | Verify diff + DROP legacy `stock_board_stock` |
| `tests/test_board_membership_migration.py` | DDL + migration tests |
| `tests/test_board_membership_readwrite.py` | `read_membership` + `upsert_membership_bulk` unit tests |
| `tests/test_board_membership_double_write.py` | `update_cached_board_stocks` dual-write |
| `tests/test_board_stocks_forward_route.py` | Forward route integration (httpx) |
| `tests/test_stock_boards_reverse_route.py` | Reverse route integration |
| `tests/test_stock_board_memberships_view.py` | Cross-source view integration |
| `tests/test_build_membership_index.py` | CLI tool unit tests (mocked fetcher) |
| `tests/test_migrate_to_membership.py` | Migrate script tests |

### Files to Modify

| Path | Change |
|---|---|
| `stock_data/data_provider/persistence/board.py` | Add DDL + migration + `read_membership` + `upsert_membership_bulk`; dual-write in `update_cached_board_stocks`; switch `get_board_stocks` to read membership |
| `stock_data/api/routes/boards.py` | Extend `/stocks/{code}/boards` to all sources + add `/stocks/{code}/board-memberships` view |
| `stock_data/api/schemas.py` | Add `BoardMembershipsResponse`, `BoardMembershipEntry`, `CrossSourceMemberships` |
| `CLAUDE.md` | Add "Server routes → persistence is the only call target" to Key Design Patterns |

### New Memory Files (preflight)

| Path | Content |
|---|---|
| `~/.claude/projects/.../memory/persistence-is-the-only-call-target.md` | Server routes call persistence; fetcher only via persistence or CLI |
| `~/.claude/projects/.../memory/ttl-is-board-level-not-row-level.md` | TTL is board-granularity |
| `~/.claude/projects/.../memory/daily-refresh-tracker-is-lazy-not-scheduled.md` | `DailyRefreshTracker.is_first_call` is lazy, not scheduled |

---

## Task 0: Preflight — Memory + CLAUDE.md sync

**Files:**
- Create: `C:\Users\Admin\.claude\projects\E--GitRepo-stock-data\memory\persistence-is-the-only-call-target.md`
- Create: `C:\Users\Admin\.claude\projects\E--GitRepo-stock-data\memory\ttl-is-board-level-not-row-level.md`
- Create: `C:\Users\Admin\.claude\projects\E--GitRepo-stock-data\memory\daily-refresh-tracker-is-lazy-not-scheduled.md`
- Modify: `C:\Users\Admin\.claude\projects\E--GitRepo-stock-data\memory\MEMORY.md` (append 3 one-line pointers)
- Modify: `CLAUDE.md` (Key Design Patterns section)

- [ ] **Step 1: Write memory file `persistence-is-the-only-call-target.md`**

```markdown
---
name: persistence-is-the-only-call-target
description: Server routes must call persistence (not fetcher directly); fetcher API surface is only consumed by persistence lazy fill and CLI build tools.
metadata:
  type: feedback
---

Server routes call `stock_data.data_provider.persistence` modules, never `DataFetcherManager` directly (except `/control/fetcher-test` which is a debug endpoint). The fetcher API surface (`manager.*`) has exactly two consumers:
1. `persistence/board.py` lazy fill (cold-path single upstream call → upsert)
2. `tools/build_membership_index.py` (full-source bootstrap, per-source worker threads)

**Why:** Centralizes cold-fill strategy in persistence; routes are pure cache reads or single-call cold fills. Predictable latency (no full rebuild hidden in HTTP path). Eases reasoning about write paths.

**How to apply:** When adding a new endpoint that needs board data, route through `stock_board_cache.get_board_stocks()` etc. If you find yourself wanting to call `manager.get_*` from a route handler, surface a new method on the persistence module instead. Anti-pattern grep target: `manager.get_` in `api/routes/*.py`.
```

- [ ] **Step 2: Write memory file `ttl-is-board-level-not-row-level.md`**

```markdown
---
name: ttl-is-board-level-not-row-level
description: Membership table TTL applies at board granularity, not per-stock row.
metadata:
  type: feedback
---

`stock_board_membership.refreshed_at` records the **last time the parent board was upserted**, not per-stock-row granularity. All rows for a given `(board_code, source)` share the same timestamp because writes are always bulk per-board.

**Why:** Documenting the design review's TTL clarification (2026-07-01). Prevents future readers from implementing per-row TTL (which would never trigger — row-level refresh never happens in this design).

**How to apply:** When writing staleness checks against membership, query `MAX(refreshed_at) GROUP BY board_code WHERE stock_code = ?`, not row-level comparisons. v1.1 may add per-board snapshots; until then, "row-level TTL" is a non-concept.
```

- [ ] **Step 3: Write memory file `daily-refresh-tracker-is-lazy-not-scheduled.md`**

```markdown
---
name: daily-refresh-tracker-is-lazy-not-scheduled
description: `DailyRefreshTracker.is_first_call(key)` is lazy-trigger semantics, not an active scheduler. To get true scheduled walks, use cron or APScheduler.
metadata:
  type: feedback
---

`DailyRefreshTracker.is_first_call(key)` returns True on the first call today for that key, False thereafter. It does NOT wake up on a schedule to walk all keys.

**Why:** Misleading name — readers assume it's a scheduled task. It's purely a "did someone already call this today?" gate, used by lazy refresh to skip redundant upstream calls within the same day.

**How to apply:** If you need "21:00 every day, walk all boards", introduce `apscheduler` or a system cron entry — not a `DailyRefreshTracker` change. v1.1 of the membership design may add such a scheduler; v1 explicitly skips it.
```

- [ ] **Step 4: Append 3 lines to `MEMORY.md`**

Read `MEMORY.md` (path: `C:\Users\Admin\.claude\projects\E--GitRepo-stock-data\memory\MEMORY.md`). Append at end:

```markdown
- [Server routes → persistence](persistence-is-the-only-call-target.md) — fetcher API surface is consumed by persistence lazy fill + CLI, not by route handlers.
- [Membership TTL is board-level](ttl-is-board-level-not-row-level.md) — `refreshed_at` is board granularity; row-level TTL is not a concept.
- [DailyRefreshTracker is lazy, not scheduled](daily-refresh-tracker-is-lazy-not-scheduled.md) — `is_first_call(key)` does not walk on a schedule; use cron/apscheduler for that.
```

- [ ] **Step 5: Update `CLAUDE.md` Key Design Patterns section**

Open `CLAUDE.md`. Find the "### Indicator Computation" section. Above it, add a new subsection:

```markdown
### Persistence-Only Routing (board endpoints)

**Rule**: Board-related route handlers (`/boards/...`, `/stocks/.../boards`, `/stocks/.../board-memberships`) call into `stock_data.data_provider.persistence.board` (`stock_board_cache.get_*`), **not** `DataFetcherManager` directly. Exceptions: `/control/fetcher-test` is a debug endpoint that intentionally bypasses this rule.

The fetcher API surface (`manager.*`) has exactly two consumers:
1. `persistence/board.py` lazy fill (cold-path single upstream call → upsert)
2. `tools/build_membership_index.py` (full-source bootstrap, per-source worker threads)

Anti-pattern: `manager.get_board_stocks(...)` in `api/routes/boards.py`. Add a new method to `stock_board_cache` instead.
```

- [ ] **Step 6: Commit preflight**

```bash
git add CLAUDE.md
git commit -m "docs(architecture): persistence-only routing rule for board endpoints"
```

Note: the three new memory files live outside the repo (`~/.claude/projects/...`), so they aren't committed. The CLAUDE.md update is the only git-visible change for this task.

---

## Task 1: New table DDL + auto-migration from `stock_board_stock`

**Files:**
- Modify: `stock_data/data_provider/persistence/board.py:78-137` (extend `init_schema()`)
- Test: `tests/test_board_membership_migration.py`

- [ ] **Step 1: Write the failing test — cold-start creates membership table**

```python
"""Tests for stock_board_membership DDL + auto-migration from stock_board_stock."""

from __future__ import annotations

import sqlite3

import pytest

from stock_data.data_provider.persistence import board as board_mod
from stock_data.data_provider.persistence import db as db_mod


@pytest.fixture
def fresh_db(tmp_path, monkeypatch):
    """Point persistence at a fresh temp DB; close existing connection first."""
    monkeypatch.setattr(db_mod, "_db_path", None)
    monkeypatch.setattr(db_mod, "_conn", None)
    monkeypatch.setattr(board_mod, "_schema_initialized_paths", set())
    test_db = tmp_path / "test.db"
    monkeypatch.setenv("STOCK_CACHE_DB_PATH", str(test_db))
    # _db_path was reset; env var will be re-read on next get_db_path() call
    yield test_db


def test_init_schema_creates_membership_table(fresh_db):
    """Cold start: init_schema() creates stock_board_membership + 2 indexes."""
    board_mod.init_schema()
    conn = db_mod.get_connection()
    cur = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='stock_board_membership'"
    )
    assert cur.fetchone() is not None
    # Check indexes
    idx_rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='stock_board_membership'"
    ).fetchall()
    idx_names = {r["name"] for r in idx_rows}
    assert "idx_membership_reverse" in idx_names
    assert "idx_membership_forward" in idx_names
```

- [ ] **Step 2: Run test, verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_board_membership_migration.py::test_init_schema_creates_membership_table -v`

Expected: FAIL with `sqlite3.OperationalError: no such table: stock_board_membership` (or `AssertionError` if table name check fails).

- [ ] **Step 3: Add DDL to `init_schema()` in `persistence/board.py`**

In `stock_data/data_provider/persistence/board.py`, locate `init_schema()` (currently lines 78-137). After the existing `idx_stock_board_type_subtype_source` index creation (around line 120), add:

```python
    # Membership table — bidirectional stock <-> board index. See
    # docs/superpowers/specs/2026-07-01-stock-board-membership-design.md §2.1.
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS stock_board_membership (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            board_code  TEXT NOT NULL,
            stock_code  TEXT NOT NULL,
            source      TEXT NOT NULL,
            board_name  TEXT NOT NULL,
            stock_name  TEXT NOT NULL,
            board_type  TEXT NOT NULL,
            subtype     TEXT,
            refreshed_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(board_code, source, stock_code)
        )
    """)
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_membership_reverse
            ON stock_board_membership(stock_code, source)
    """)
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_membership_forward
            ON stock_board_membership(board_code, source)
    """)
```

- [ ] **Step 4: Run test, verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/test_board_membership_migration.py::test_init_schema_creates_membership_table -v`

Expected: PASS

- [ ] **Step 5: Write failing test — auto-migration from `stock_board_stock`**

Append to `tests/test_board_membership_migration.py`:

```python
def test_init_schema_migrates_from_legacy_stock_board_stock(fresh_db):
    """If stock_board_stock exists, init_schema() migrates rows into membership."""
    # Seed legacy table with 2 rows
    conn = db_mod.get_connection()
    conn.executescript("""
        CREATE TABLE stock_board (
            code TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            board_type TEXT NOT NULL,
            subtype TEXT,
            source TEXT NOT NULL
        );
        INSERT INTO stock_board VALUES
            ('BK1001', '白酒', 'concept', 'concept', 'eastmoney'),
            ('BK1002', '银行', 'industry', 'industry', 'eastmoney');

        CREATE TABLE stock_board_stock (
            board_code TEXT NOT NULL,
            source TEXT NOT NULL,
            stock_code TEXT NOT NULL,
            stock_name TEXT NOT NULL,
            UNIQUE(board_code, source, stock_code)
        );
        INSERT INTO stock_board_stock VALUES
            ('BK1001', 'eastmoney', '600519', '贵州茅台'),
            ('BK1002', 'eastmoney', '601398', '工商银行');
    """)
    conn.commit()
    # Reset schema guard so init_schema() re-runs
    board_mod._schema_initialized_paths.clear()
    board_mod.init_schema()
    # Verify membership has the rows with joined board metadata
    rows = conn.execute(
        "SELECT board_code, stock_code, board_name, board_type FROM stock_board_membership ORDER BY board_code"
    ).fetchall()
    assert len(rows) == 2
    assert rows[0]["board_code"] == "BK1001"
    assert rows[0]["stock_code"] == "600519"
    assert rows[0]["board_name"] == "白酒"
    assert rows[0]["board_type"] == "concept"
```

- [ ] **Step 6: Run test, verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_board_membership_migration.py::test_init_schema_migrates_from_legacy_stock_board_stock -v`

Expected: FAIL with `AssertionError: 0 != 2` (membership table exists but is empty; migration logic not yet added).

- [ ] **Step 7: Add migration logic to `init_schema()`**

In `init_schema()`, immediately after the DDL block from Step 3, add:

```python
    # Auto-migration: if legacy stock_board_stock exists, copy its rows
    # into stock_board_membership with joined board metadata. One-shot —
    # subsequent runs find stock_board_stock absent and skip.
    cursor.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='stock_board_stock'"
    )
    if cursor.fetchone() is not None:
        cursor.execute("""
            INSERT OR IGNORE INTO stock_board_membership
                (board_code, source, stock_code, stock_name,
                 board_name, board_type, subtype, refreshed_at)
            SELECT bs.board_code, bs.source, bs.stock_code, bs.stock_name,
                   COALESCE(b.name, ''),
                   COALESCE(b.board_type, ''),
                   b.subtype,
                   CURRENT_TIMESTAMP
            FROM stock_board_stock bs
            LEFT JOIN stock_board b
              ON b.code = bs.board_code AND b.source = bs.source
        """)
```

- [ ] **Step 8: Run test, verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/test_board_membership_migration.py::test_init_schema_migrates_from_legacy_stock_board_stock -v`

Expected: PASS

- [ ] **Step 9: Write failing test — migration is idempotent**

Append to `tests/test_board_membership_migration.py`:

```python
def test_init_schema_migration_is_idempotent(fresh_db):
    """Re-running init_schema() with legacy table present must not duplicate rows."""
    conn = db_mod.get_connection()
    conn.executescript("""
        CREATE TABLE stock_board (
            code TEXT PRIMARY KEY, name TEXT NOT NULL,
            board_type TEXT NOT NULL, subtype TEXT, source TEXT NOT NULL
        );
        INSERT INTO stock_board VALUES ('BK1', 'X', 'concept', 'concept', 'eastmoney');
        CREATE TABLE stock_board_stock (
            board_code TEXT, source TEXT, stock_code TEXT, stock_name TEXT
        );
        INSERT INTO stock_board_stock VALUES ('BK1', 'eastmoney', '1', 'A');
    """)
    conn.commit()
    board_mod._schema_initialized_paths.clear()
    board_mod.init_schema()
    board_mod._schema_initialized_paths.clear()  # force re-run
    board_mod.init_schema()
    count = conn.execute("SELECT COUNT(*) FROM stock_board_membership").fetchone()[0]
    assert count == 1  # INSERT OR IGNORE prevented duplicates
```

- [ ] **Step 10: Run test, verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/test_board_membership_migration.py -v`

Expected: all 3 tests PASS

- [ ] **Step 11: Commit**

```bash
git add stock_data/data_provider/persistence/board.py tests/test_board_membership_migration.py
git commit -m "feat(persistence/board): add stock_board_membership table + auto-migrate from stock_board_stock"
```

---

## Task 2: `read_membership` function

**Files:**
- Modify: `stock_data/data_provider/persistence/board.py` (append `read_membership` after `get_board_stocks`)
- Test: `tests/test_board_membership_readwrite.py`

- [ ] **Step 1: Write the failing test — read by board_code**

```python
"""Tests for read_membership + upsert_membership_bulk."""

from __future__ import annotations

import pytest

from stock_data.data_provider.persistence import board as board_mod
from stock_data.data_provider.persistence import db as db_mod


@pytest.fixture
def fresh_db(tmp_path, monkeypatch):
    monkeypatch.setattr(db_mod, "_db_path", None)
    monkeypatch.setattr(db_mod, "_conn", None)
    monkeypatch.setattr(board_mod, "_schema_initialized_paths", set())
    monkeypatch.setenv("STOCK_CACHE_DB_PATH", str(tmp_path / "test.db"))
    board_mod.init_schema()
    yield tmp_path / "test.db"


def test_read_membership_by_board_code(fresh_db):
    """read_membership(board_code=...) returns forward-direction rows for that board."""
    board_mod.upsert_membership_bulk(
        source="eastmoney",
        stocks=[{"stock_code": "600519", "stock_name": "贵州茅台"}],
        board_code="BK1001", board_name="白酒", board_type="concept", subtype="concept",
    )
    rows = board_mod.read_membership(board_code="BK1001", source="eastmoney")
    assert len(rows) == 1
    assert rows[0]["stock_code"] == "600519"
    assert rows[0]["stock_name"] == "贵州茅台"
    assert rows[0]["board_name"] == "白酒"
```

- [ ] **Step 2: Run test, verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_board_membership_readwrite.py::test_read_membership_by_board_code -v`

Expected: FAIL with `AttributeError: module 'stock_data.data_provider.persistence.board' has no attribute 'read_membership'` (or `AttributeError` for `upsert_membership_bulk`).

- [ ] **Step 3: Implement `read_membership` and `upsert_membership_bulk` stubs (write the real ones below)**

In `stock_data/data_provider/persistence/board.py`, append after the existing `_get_board_type` function (after line 279):

```python
def read_membership(
    board_code: str | None = None,
    stock_code: str | None = None,
    source: str | None = None,
) -> list:
    """Read membership rows. Exactly one of board_code / stock_code must be set.

    Args:
        board_code: forward direction — return all stocks in this board.
        stock_code: reverse direction — return all boards this stock belongs to.
        source: optional filter (e.g. 'eastmoney' / 'zhitu' / 'zzshare').

    Returns:
        List of membership rows with keys:
            board_code, stock_code, source, board_name, stock_name,
            board_type, subtype, refreshed_at
    """
    init_schema()
    if (board_code is None) == (stock_code is None):
        raise ValueError(
            "Exactly one of board_code or stock_code must be set, not both/neither."
        )

    conn = get_connection()
    cursor = conn.cursor()

    if board_code is not None:
        sql = """SELECT board_code, stock_code, source, board_name, stock_name,
                        board_type, subtype, refreshed_at
                 FROM stock_board_membership
                 WHERE board_code = ?"""
        params: tuple = (board_code,)
    else:
        sql = """SELECT board_code, stock_code, source, board_name, stock_name,
                        board_type, subtype, refreshed_at
                 FROM stock_board_membership
                 WHERE stock_code = ?"""
        params = (stock_code,)

    if source is not None:
        sql += " AND source = ?"
        params = params + (source,)

    sql += " ORDER BY board_code, stock_code"

    cursor.execute(sql, params)
    rows = cursor.fetchall()
    return [
        {
            "board_code": r["board_code"],
            "stock_code": r["stock_code"],
            "source": r["source"],
            "board_name": r["board_name"],
            "stock_name": r["stock_name"],
            "board_type": r["board_type"],
            "subtype": r["subtype"],
            "refreshed_at": r["refreshed_at"],
        }
        for r in rows
    ]


def upsert_membership_bulk(
    source: str,
    stocks: list[dict],
    board_code: str,
    board_name: str,
    board_type: str,
    subtype: str | None,
) -> int:
    """Bulk upsert all stocks for one board. Returns count of rows affected.

    Args:
        source: 'eastmoney' | 'zhitu' | 'zzshare'
        stocks: list of {stock_code, stock_name}
        board_code: e.g. 'BK1001' (eastmoney) or 'sw_yx' (zhitu)
        board_name: e.g. '白酒' (denormalized for read perf)
        board_type: 'concept' | 'industry' | 'index' | 'special'
        subtype: source-specific subtype string

    Implementation notes:
        - Uses INSERT OR REPLACE so refreshed_at = CURRENT_TIMESTAMP.
        - One executemany call (one transaction) for the whole batch.
        - Returns the number of stock rows passed in (rows upserted).
    """
    if not stocks:
        return 0

    init_schema()
    conn = get_connection()
    with conn:
        cursor = conn.cursor()
        rows = [
            (board_code, source, s["stock_code"],
             s.get("stock_name", ""), board_name, board_type, subtype)
            for s in stocks
        ]
        cursor.executemany(
            """INSERT OR REPLACE INTO stock_board_membership
               (board_code, source, stock_code, stock_name,
                board_name, board_type, subtype, refreshed_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)""",
            rows,
        )
    return len(rows)
```

- [ ] **Step 4: Run test, verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/test_board_membership_readwrite.py::test_read_membership_by_board_code -v`

Expected: PASS

- [ ] **Step 5: Write failing test — read by stock_code + source isolation**

Append to `tests/test_board_membership_readwrite.py`:

```python
def test_read_membership_by_stock_code(fresh_db):
    """read_membership(stock_code=...) returns reverse-direction rows for that stock."""
    # Stock 600519 in 2 boards, 2 sources
    board_mod.upsert_membership_bulk(
        source="eastmoney",
        stocks=[{"stock_code": "600519", "stock_name": "贵州茅台"}],
        board_code="BK1001", board_name="白酒", board_type="concept", subtype="concept",
    )
    board_mod.upsert_membership_bulk(
        source="zhitu",
        stocks=[{"stock_code": "600519", "stock_name": "贵州茅台"}],
        board_code="sw_yx_baijiu", board_name="白酒", board_type="industry", subtype="申万行业",
    )
    rows = board_mod.read_membership(stock_code="600519")
    assert len(rows) == 2
    sources = {r["source"] for r in rows}
    assert sources == {"eastmoney", "zhitu"}


def test_read_membership_source_isolation(fresh_db):
    """source= filter limits results to one source."""
    board_mod.upsert_membership_bulk(
        source="eastmoney",
        stocks=[{"stock_code": "600519", "stock_name": "贵州茅台"}],
        board_code="BK1001", board_name="白酒", board_type="concept", subtype="concept",
    )
    board_mod.upsert_membership_bulk(
        source="zhitu",
        stocks=[{"stock_code": "600519", "stock_name": "贵州茅台"}],
        board_code="sw_yx", board_name="白酒", board_type="industry", subtype="申万行业",
    )
    rows = board_mod.read_membership(stock_code="600519", source="eastmoney")
    assert len(rows) == 1
    assert rows[0]["source"] == "eastmoney"


def test_read_membership_validates_one_of_keys(fresh_db):
    """read_membership without board_code and stock_code (or with both) raises ValueError."""
    with pytest.raises(ValueError, match="Exactly one"):
        board_mod.read_membership()
    with pytest.raises(ValueError, match="Exactly one"):
        board_mod.read_membership(board_code="X", stock_code="Y")
```

- [ ] **Step 6: Run tests, verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_board_membership_readwrite.py -v`

Expected: 4 tests PASS

- [ ] **Step 7: Commit**

```bash
git add stock_data/data_provider/persistence/board.py tests/test_board_membership_readwrite.py
git commit -m "feat(persistence/board): add read_membership bidirectional query"
```

---

## Task 3: `upsert_membership_bulk` insert vs update semantics

**Files:**
- Test: `tests/test_board_membership_readwrite.py` (extend existing file)

- [ ] **Step 1: Write failing test — upsert refreshes existing rows**

Append to `tests/test_board_membership_readwrite.py`:

```python
def test_upsert_inserts_new_rows(fresh_db):
    """upsert_membership_bulk with new stock inserts a row."""
    n = board_mod.upsert_membership_bulk(
        source="eastmoney",
        stocks=[
            {"stock_code": "600519", "stock_name": "贵州茅台"},
            {"stock_code": "000858", "stock_name": "五粮液"},
        ],
        board_code="BK1001", board_name="白酒", board_type="concept", subtype="concept",
    )
    assert n == 2
    rows = board_mod.read_membership(board_code="BK1001")
    assert len(rows) == 2


def test_upsert_refreshes_existing_row(fresh_db):
    """upsert with same (board_code, source, stock_code) updates refreshed_at + denorm fields."""
    import time
    board_mod.upsert_membership_bulk(
        source="eastmoney",
        stocks=[{"stock_code": "600519", "stock_name": "贵州茅台"}],
        board_code="BK1001", board_name="白酒-OldName", board_type="concept", subtype="concept",
    )
    rows_before = board_mod.read_membership(board_code="BK1001")
    assert rows_before[0]["board_name"] == "白酒-OldName"

    # Sleep to ensure refreshed_at differs (SQLite CURRENT_TIMESTAMP has 1s precision)
    time.sleep(1.1)

    board_mod.upsert_membership_bulk(
        source="eastmoney",
        stocks=[{"stock_code": "600519", "stock_name": "贵州茅台"}],
        board_code="BK1001", board_name="白酒-NewName", board_type="concept", subtype="concept",
    )
    rows_after = board_mod.read_membership(board_code="BK1001")
    assert len(rows_after) == 1  # no duplicate
    assert rows_after[0]["board_name"] == "白酒-NewName"
    assert rows_after[0]["refreshed_at"] != rows_before[0]["refreshed_at"]


def test_upsert_handles_empty_stocks(fresh_db):
    """upsert with empty list returns 0 and writes nothing."""
    n = board_mod.upsert_membership_bulk(
        source="eastmoney", stocks=[],
        board_code="BK1001", board_name="白酒", board_type="concept", subtype="concept",
    )
    assert n == 0
    rows = board_mod.read_membership(board_code="BK1001")
    assert len(rows) == 0
```

- [ ] **Step 2: Run tests, verify all pass (implementation already in Task 2)**

Run: `.venv/Scripts/python.exe -m pytest tests/test_board_membership_readwrite.py -v`

Expected: 7 tests PASS (4 from Task 2 + 3 new)

- [ ] **Step 3: Commit**

```bash
git add tests/test_board_membership_readwrite.py
git commit -m "test(persistence/board): cover upsert insert/update/empty cases"
```

---

## Task 4: Dual-write `update_cached_board_stocks`

**Files:**
- Modify: `stock_data/data_provider/persistence/board.py:412-452` (`update_cached_board_stocks`)
- Test: `tests/test_board_membership_double_write.py`

- [ ] **Step 1: Write the failing test — dual-write writes to both tables**

```python
"""Tests for dual-write in update_cached_board_stocks."""

from __future__ import annotations

import pytest

from stock_data.data_provider.persistence import board as board_mod
from stock_data.data_provider.persistence import db as db_mod


@pytest.fixture
def fresh_db(tmp_path, monkeypatch):
    monkeypatch.setattr(db_mod, "_db_path", None)
    monkeypatch.setattr(db_mod, "_conn", None)
    monkeypatch.setattr(board_mod, "_schema_initialized_paths", set())
    monkeypatch.setenv("STOCK_CACHE_DB_PATH", str(tmp_path / "test.db"))
    board_mod.init_schema()
    yield tmp_path / "test.db"


def test_update_cached_board_stocks_writes_both_tables(fresh_db):
    """update_cached_board_stocks must insert into stock_board_stock AND stock_board_membership."""
    # Seed stock_board so dual-write can join board_name/board_type
    conn = db_mod.get_connection()
    conn.execute("""
        INSERT INTO stock_board (code, name, board_type, subtype, source)
        VALUES ('BK1001', '白酒', 'concept', 'concept', 'eastmoney')
    """)
    conn.commit()

    stocks = [
        {"stock_code": "600519", "stock_name": "贵州茅台"},
        {"stock_code": "000858", "stock_name": "五粮液"},
    ]
    n = board_mod.update_cached_board_stocks(
        board_code="BK1001", source="eastmoney", stocks=stocks,
    )
    assert n == 2

    # Check legacy table
    legacy = conn.execute(
        "SELECT stock_code FROM stock_board_stock WHERE board_code='BK1001' ORDER BY stock_code"
    ).fetchall()
    assert [r["stock_code"] for r in legacy] == ["000858", "600519"]

    # Check new table
    new_rows = conn.execute(
        """SELECT stock_code, board_name, board_type, subtype FROM stock_board_membership
           WHERE board_code='BK1001' ORDER BY stock_code"""
    ).fetchall()
    assert len(new_rows) == 2
    assert new_rows[0]["stock_name"] == "五粮液"  # populated from input dict
    assert new_rows[0]["board_name"] == "白酒"    # populated via JOIN
    assert new_rows[0]["board_type"] == "concept"
```

- [ ] **Step 2: Run test, verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_board_membership_double_write.py::test_update_cached_board_stocks_writes_both_tables -v`

Expected: FAIL — legacy table populated but `stock_board_membership` count is 0 (since dual-write not yet added).

- [ ] **Step 3: Modify `update_cached_board_stocks` to dual-write**

In `stock_data/data_provider/persistence/board.py`, locate `update_cached_board_stocks` (lines 412-452). Replace the function body (keep signature) with:

```python
def update_cached_board_stocks(board_code: str, source: str, stocks: list) -> int:
    """
    Update cached stocks metadata for a board (dual-write window).

    Writes to BOTH `stock_board_stock` (legacy) and `stock_board_membership`
    (new reverse-index table). After `scripts/migrate_to_membership.py
    --execute` drops the legacy table, this function will be simplified
    to single-write (see Task 9).

    Args:
        board_code: Board code
        source: Data source
        stocks: List of dicts [{"stock_code": "600519", "stock_name": "贵州茅台"}, ...]

    Returns:
        Number of stocks written.
    """
    if not stocks:
        return 0

    init_schema()

    # Resolve board metadata for denormalization (board_name, board_type, subtype)
    conn = get_connection()
    board_row = conn.execute(
        "SELECT name, board_type, subtype FROM stock_board WHERE code = ? AND source = ?",
        (board_code, source),
    ).fetchone()
    board_name = board_row["name"] if board_row else board_code
    board_type = board_row["board_type"] if board_row else ""
    subtype = board_row["subtype"] if board_row else None

    try:
        with conn:
            cursor = conn.cursor()
            now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

            # Legacy table (will be dropped in Task 9)
            cursor.executemany(
                """INSERT OR REPLACE INTO stock_board_stock
                (board_code, source, stock_code, stock_name, updated_at)
                VALUES (?, ?, ?, ?, ?)""",
                [
                    (board_code, source, s["stock_code"], s["stock_name"], now)
                    for s in stocks
                ],
            )

            # New reverse-index table (denormalized: board_name / board_type / subtype)
            cursor.executemany(
                """INSERT OR REPLACE INTO stock_board_membership
                   (board_code, source, stock_code, stock_name,
                    board_name, board_type, subtype, refreshed_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                [
                    (board_code, source, s["stock_code"], s["stock_name"],
                     board_name, board_type, subtype, now)
                    for s in stocks
                ],
            )

            logger.info(
                f"[BoardCache] Updated {len(stocks)} stocks for board {board_code}/{source} (dual-write)"
            )
            return len(stocks)
    except Exception as e:
        logger.error(f"[BoardCache] Update board stocks failed: {e}")
        raise
```

- [ ] **Step 4: Run test, verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/test_board_membership_double_write.py -v`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add stock_data/data_provider/persistence/board.py tests/test_board_membership_double_write.py
git commit -m "feat(persistence/board): dual-write update_cached_board_stocks to membership table"
```

---

## Task 5: Forward route reads membership table

**Files:**
- Modify: `stock_data/data_provider/persistence/board.py:349-366` (`_read_board_stocks_from_db`)
- Modify: `stock_data/data_provider/persistence/board.py:214-266` (`get_board_stocks`)
- Test: `tests/test_board_stocks_forward_route.py`

- [ ] **Step 1: Write the failing integration test**

```python
"""Integration test: /boards/{code}/stocks reads from membership table."""

from __future__ import annotations

import pytest
from unittest.mock import MagicMock

from stock_data.data_provider.persistence import board as board_mod
from stock_data.data_provider.persistence import db as db_mod


@pytest.fixture
def fresh_db(tmp_path, monkeypatch):
    monkeypatch.setattr(db_mod, "_db_path", None)
    monkeypatch.setattr(db_mod, "_conn", None)
    monkeypatch.setattr(board_mod, "_schema_initialized_paths", set())
    monkeypatch.setenv("STOCK_CACHE_DB_PATH", str(tmp_path / "test.db"))
    board_mod.init_schema()
    yield tmp_path / "test.db"


def test_get_board_stocks_reads_from_membership_table(fresh_db):
    """get_board_stocks returns rows from stock_board_membership, not stock_board_stock."""
    # Seed membership directly
    board_mod.upsert_membership_bulk(
        source="eastmoney",
        stocks=[
            {"stock_code": "600519", "stock_name": "贵州茅台"},
            {"stock_code": "000858", "stock_name": "五粮液"},
        ],
        board_code="BK1001", board_name="白酒", board_type="concept", subtype="concept",
    )
    # Mock manager so cold path would fail if triggered
    mock_manager = MagicMock()
    mock_manager.get_board_stocks.side_effect = AssertionError(
        "Cold path should NOT trigger when membership has data"
    )

    stocks, origin = board_mod.get_board_stocks(
        board_code="BK1001", source="eastmoney", manager=mock_manager,
    )
    assert origin == "persistence"
    assert len(stocks) == 2
    assert {s["stock_code"] for s in stocks} == {"600519", "000858"}
    mock_manager.get_board_stocks.assert_not_called()


def test_get_board_stocks_lazy_fill_when_membership_empty(fresh_db):
    """Cold path: membership empty → fetcher called → upsert → return."""
    # Seed stock_board so board_name/board_type resolve
    conn = db_mod.get_connection()
    conn.execute("""
        INSERT INTO stock_board (code, name, board_type, subtype, source)
        VALUES ('BK1001', '白酒', 'concept', 'concept', 'eastmoney')
    """)
    conn.commit()

    # Mock manager returns 3 stocks
    mock_manager = MagicMock()
    mock_manager.get_board_stocks.return_value = (
        [
            {"stock_code": "600519", "stock_name": "贵州茅台"},
            {"stock_code": "000858", "stock_name": "五粮液"},
            {"stock_code": "600809", "stock_name": "山西汾酒"},
        ],
        "eastmoney",
    )

    stocks, origin = board_mod.get_board_stocks(
        board_code="BK1001", source="eastmoney", manager=mock_manager,
    )
    assert origin == "eastmoney"
    assert len(stocks) == 3
    # Verify membership was populated
    rows = board_mod.read_membership(board_code="BK1001", source="eastmoney")
    assert len(rows) == 3
```

- [ ] **Step 2: Run tests, verify second one fails (or both fail)**

Run: `.venv/Scripts/python.exe -m pytest tests/test_board_stocks_forward_route.py -v`

Expected: First test FAILS — `get_board_stocks` still reads from `stock_board_stock`, which is empty.

- [ ] **Step 3: Modify `_read_board_stocks_from_db` to read from membership**

In `stock_data/data_provider/persistence/board.py`, locate `_read_board_stocks_from_db` (lines 349-366). Replace with:

```python
def _read_board_stocks_from_db(board_code: str, source: str) -> list:
    """Read board-stock list from membership table."""
    return [
        {
            "stock_code": r["stock_code"],
            "stock_name": r["stock_name"],
            "updated_at": r["refreshed_at"],
        }
        for r in read_membership(board_code=board_code, source=source)
    ]
```

- [ ] **Step 4: Modify `get_board_stocks` to upsert membership on lazy fill**

In `stock_data/data_provider/persistence/board.py`, locate `get_board_stocks` (lines 214-266). The existing code already calls `update_cached_board_stocks(board_code, source, stocks)` on cold-path success — and Task 4 made that function dual-write. So no further change is needed; `update_cached_board_stocks` already populates `stock_board_membership`.

To make this explicit and self-documenting, add a comment block above the existing `update_cached_board_stocks` call:

```python
        # Cold-fill: this single call updates BOTH stock_board_stock (legacy)
        # AND stock_board_membership (new reverse index) — see
        # update_cached_board_stocks in this module. After Task 9 drops the
        # legacy table, this call's behavior simplifies to a single
        # upsert_membership_bulk.
        update_cached_board_stocks(board_code, source, stocks)
```

- [ ] **Step 5: Run tests, verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_board_stocks_forward_route.py -v`

Expected: 2 tests PASS

- [ ] **Step 6: Commit**

```bash
git add stock_data/data_provider/persistence/board.py tests/test_board_stocks_forward_route.py
git commit -m "refactor(persistence/board): route forward reads through membership table"
```

---

## Task 6: Reverse route `/stocks/{code}/boards` supports all sources

**Files:**
- Modify: `stock_data/api/routes/boards.py:295-377` (`get_stock_boards`)
- Test: `tests/test_stock_boards_reverse_route.py`

- [ ] **Step 1: Write the failing integration test**

```python
"""Integration test: /stocks/{code}/boards reads membership, fallback to zhitu fetcher."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from stock_data.data_provider.persistence import board as board_mod
from stock_data.data_provider.persistence import db as db_mod
from stock_data.data_provider.persistence import stock_list as stock_list_mod
from stock_data.server import app


@pytest.fixture
def fresh_db(tmp_path, monkeypatch):
    monkeypatch.setattr(db_mod, "_db_path", None)
    monkeypatch.setattr(db_mod, "_conn", None)
    monkeypatch.setattr(board_mod, "_schema_initialized_paths", set())
    monkeypatch.setattr(stock_list_mod, "_schema_initialized_paths", set())
    monkeypatch.setenv("STOCK_CACHE_DB_PATH", str(tmp_path / "test.db"))
    board_mod.init_schema()
    stock_list_mod.init_schema()
    # Seed stock_list with one entry
    conn = db_mod.get_connection()
    conn.execute("""
        INSERT INTO stock_list (code, name, market) VALUES ('600519', '贵州茅台', 'csi')
    """)
    conn.commit()
    yield tmp_path / "test.db"


def test_reverse_route_returns_persisted_zhitu_boards(fresh_db):
    """Stock with rows in membership table → route returns them with source='persistence'."""
    board_mod.upsert_membership_bulk(
        source="zhitu",
        stocks=[{"stock_code": "600519", "stock_name": "贵州茅台"}],
        board_code="sw_yx_baijiu", board_name="白酒", board_type="industry", subtype="申万行业",
    )
    with TestClient(app) as client:
        r = client.get("/stocks/600519/boards?source=zhitu")
    assert r.status_code == 200
    body = r.json()
    assert body["source"] == "persistence"
    assert len(body["data"]) == 1
    assert body["data"][0]["code"] == "sw_yx_baijiu"


def test_reverse_route_zhitu_cold_path_populates_membership(fresh_db):
    """Cold path for zhitu: membership empty → fetcher called → upsert → return."""
    # Mock the fetcher layer via patch on app.state.manager
    from stock_data.api.routes import helpers as helpers_mod

    fake_boards = [
        {"code": "sw_yx_baijiu", "name": "白酒", "type": "industry", "subtype": "申万行业"},
    ]
    mock_manager = MagicMock()
    mock_manager.get_stock_boards.return_value = (fake_boards, "zhitu")

    with TestClient(app) as client:
        # Patch get_manager to return our mock for this request
        import stock_data.api.routes.boards as boards_route
        original_get_manager = boards_route.get_manager
        boards_route.get_manager = lambda: mock_manager
        try:
            r = client.get("/stocks/600519/boards?source=zhitu")
        finally:
            boards_route.get_manager = original_get_manager

    assert r.status_code == 200
    body = r.json()
    assert body["source"] == "zhitu"
    # Verify membership was populated
    rows = board_mod.read_membership(stock_code="600519", source="zhitu")
    assert len(rows) == 1
    assert rows[0]["stock_name"] == "贵州茅台"  # from stock_list lookup


def test_reverse_route_eastmoney_404_with_cold_source_true(fresh_db):
    """Cold path for non-zhitu: no fetcher available → 404 + cold_source=true."""
    with TestClient(app) as client:
        r = client.get("/stocks/600519/boards?source=eastmoney")
    assert r.status_code == 404
    detail = r.json()["detail"]
    assert detail["error"] == "cold_stock_board_data"
    assert detail["cold_source"] is True
    assert "build_membership_index" in detail["message"]
```

- [ ] **Step 2: Run tests, verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_stock_boards_reverse_route.py -v`

Expected: All 3 fail — current route restricts to `source='zhitu'` only.

- [ ] **Step 3: Modify `get_stock_boards` route**

In `stock_data/api/routes/boards.py`, replace the entire `get_stock_boards` function (lines 277-377) with:

```python
@router.get(
    "/stocks/{stock_code}/boards",
    response_model=StockBoardsResponse,
    responses={
        400: {"model": ErrorResponse, "description": "Invalid source/type/subtype"},
        404: {"model": ErrorResponse, "description": "Stock not in any known board"},
        500: {"model": ErrorResponse, "description": "Server error"},
    },
    tags=["boards"],
)
@endpoint_meta(
    summary="股票所属板块（所有 source 都支持）",
    markets=["csi"],
    capabilities=["STOCK_BOARD"],
    fetcher_method="get_stock_boards",
)
@map_errors
def get_stock_boards(
    stock_code: str = Path(max_length=20, description="Stock code (e.g. 000001)"),
    source: Literal["zhitu", "eastmoney", "zzshare"] = Query(
        ..., description="Data source (zhitu has native API; eastmoney/zzshare served from membership table only)"
    ),
    type: Literal["concept", "industry", "index", "special"] | None = Query(
        None, description="Filter by board type"
    ),
    subtype: str | None = Query(
        None, description="Filter by source-specific subtype"
    ),
) -> StockBoardsResponse:
    """Get boards a stock belongs to.

    All sources supported. Reads from `stock_board_membership` (built by
    forward-path lazy fill or `tools/build_membership_index` bootstrap).
    For `source=zhitu`, the cold-path fallback calls the fetcher's native
    reverse API and writes the result to membership.
    """
    _resolve_source(source)

    if type is not None:
        _resolve_type(type)
        stock_board_cache._validate_subtype(source, type, subtype)

    # ① Try membership table first (fast path)
    rows = stock_board_cache.read_membership(stock_code=stock_code, source=source)
    if rows:
        # Filter type/subtype in Python (small list)
        if type is not None:
            rows = [r for r in rows if r["board_type"] == type]
        if subtype is not None:
            rows = [r for r in rows if r["subtype"] == subtype]
        if rows:
            return StockBoardsResponse(
                stock_code=stock_code, source="persistence",
                data=[
                    StockBoardInfo(
                        code=r["board_code"], name=r["board_name"],
                        type=r["board_type"], subtype=r["subtype"] or "",
                    )
                    for r in rows
                ],
            )

    # ② zhitu cold path: native API → upsert membership
    if source == "zhitu":
        manager = get_manager()
        boards, origin = manager.get_stock_boards(stock_code, source=source)
        if boards is not None and len(boards) > 0:
            # Resolve stock_name from stock_list (zhitu API doesn't return it)
            from stock_data.data_provider.persistence.stock_list import (
                get_stock_name as _get_stock_name,
            )
            stock_name = _get_stock_name(stock_code) or ""
            # Upsert each board as a separate membership row
            for b in boards:
                stock_board_cache.upsert_membership_bulk(
                    source="zhitu",
                    stocks=[{"stock_code": stock_code, "stock_name": stock_name}],
                    board_code=b["code"],
                    board_name=b["name"],
                    board_type=b.get("type", ""),
                    subtype=b.get("subtype"),
                )
            # Apply type/subtype filters for response
            if type is not None:
                boards = [b for b in boards if b.get("type") == type]
            if subtype is not None:
                boards = [b for b in boards if b.get("subtype") == subtype]
            return StockBoardsResponse(
                stock_code=stock_code, source=origin,
                data=[
                    StockBoardInfo(
                        code=b["code"], name=b["name"],
                        type=b.get("type", ""), subtype=b.get("subtype", ""),
                    )
                    for b in boards
                ],
            )

    # ③ Non-zhitu cold path: no upstream API → 404 + cold_source hint
    raise HTTPException(
        status_code=404,
        detail={
            "error": "cold_stock_board_data",
            "message": (
                f"No reverse-index for {stock_code} in {source}. "
                f"Run `python -m stock_data.tools.build_membership_index "
                f"--source={source}` to populate."
            ),
            "cold_source": True,
        },
    )
```

- [ ] **Step 4: Run tests, verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_stock_boards_reverse_route.py -v`

Expected: 3 tests PASS

- [ ] **Step 5: Commit**

```bash
git add stock_data/api/routes/boards.py tests/test_stock_boards_reverse_route.py
git commit -m "feat(api/boards): extend stock->boards reverse lookup to all sources"
```

---

## Task 7: CLI `build_membership_index` with per-source threading

**Files:**
- Create: `stock_data/tools/__init__.py`
- Create: `stock_data/tools/build_membership_index.py`
- Create: `stock_data/tools/README.md`
- Test: `tests/test_build_membership_index.py`

- [ ] **Step 1: Create `stock_data/tools/__init__.py`**

```python
"""CLI tools for stock_data persistence maintenance."""
```

- [ ] **Step 2: Write the failing test — basic single-source build**

```python
"""Tests for build_membership_index CLI."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from stock_data.data_provider.persistence import board as board_mod
from stock_data.data_provider.persistence import db as db_mod
from stock_data.tools import build_membership_index as cli_mod


@pytest.fixture
def fresh_db(tmp_path, monkeypatch):
    monkeypatch.setattr(db_mod, "_db_path", None)
    monkeypatch.setattr(db_mod, "_conn", None)
    monkeypatch.setattr(board_mod, "_schema_initialized_paths", set())
    monkeypatch.setenv("STOCK_CACHE_DB_PATH", str(tmp_path / "test.db"))
    board_mod.init_schema()
    yield tmp_path / "test.db"


def _make_manager_mock(boards_per_source: dict[str, list[str]]):
    """Mock manager whose get_all_boards returns a list of board_codes per source."""
    mock = MagicMock()
    def get_all_boards(source, board_type, subtype, include_quote):
        return (
            [{"code": code, "name": f"Board-{code}",
              "board_type": board_type, "subtype": subtype or board_type}
             for code in boards_per_source.get(source, [])],
            source,
        )
    def get_board_stocks(board_code, source, include_quote):
        return (
            [
                {"stock_code": f"S{i}", "stock_name": f"Stock-{i}"}
                for i in range(3)
            ],
            source,
        )
    mock.get_all_boards.side_effect = get_all_boards
    mock.get_board_stocks.side_effect = get_board_stocks
    return mock


def test_build_one_source_populates_membership(fresh_db, monkeypatch):
    """Single source: enumerate boards, fetch stocks, upsert to membership."""
    mock = _make_manager_mock({"eastmoney": ["BK1", "BK2", "BK3"]})
    # Patch time.sleep so test runs fast
    monkeypatch.setattr(cli_mod.time, "sleep", lambda *a, **kw: None)
    monkeypatch.setattr(cli_mod.random, "uniform", lambda *a: 0.0)

    report = cli_mod.build_membership_index(
        source="eastmoney", board_type="concept",
        manager=mock,
    )[0]
    assert report.source == "eastmoney"
    assert report.total_boards == 3
    assert report.success_count == 3
    assert report.error_count == 0
    # Verify membership has rows for all 3 boards × 3 stocks
    rows = board_mod.read_membership(source="eastmoney")
    assert len(rows) == 9
```

- [ ] **Step 3: Run test, verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_build_membership_index.py::test_build_one_source_populates_membership -v`

Expected: FAIL with `ModuleNotFoundError: No module named 'stock_data.tools'`.

- [ ] **Step 4: Implement `build_membership_index.py`**

Create `stock_data/tools/build_membership_index.py`:

```python
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
    inter_call_sleep: tuple[float, float] = (1.0, 3.0),
    on_progress: Callable[[str, int, int], None] | None = None,
    manager=None,
) -> list[BuildReport]:
    """Walk (source, board_type) and upsert all stocks to membership.

    Args:
        source: 'eastmoney' | 'zhitu' | 'zzshare' or None for all
        board_type: 'concept' | 'industry' | 'index' | 'special' or None for all
        inter_call_sleep: (min, max) jitter range in seconds
        on_progress: optional callback(source, done, total)
        manager: DataFetcherManager instance

    Returns:
        list[BuildReport], one per source walked. For source=None, returns
        3 reports (one per VALID_SOURCES). Each source runs on its own
        worker thread; intra-source fetching stays serial.
    """
    if manager is None:
        raise ValueError("manager is required")

    sources = [source] if source else list(VALID_SOURCES)
    types = [board_type] if board_type else list(VALID_BOARD_TYPES)

    reports: list[BuildReport] = [None] * len(sources)  # type: ignore[list-item]

    def _run_one(i: int, src: str) -> None:
        report = _build_one_source(
            source=src, types=types,
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
                f.result()  # surface exceptions

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

    # Intra-source: serial. Concurrent threads against the same upstream
    # would just hit its rate limit harder.
    for board in all_boards:
        _process_board(board)

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
    parser.add_argument("--inter-call-sleep-max", type=float, default=3.0)
    parser.add_argument("--verbose", "-v", action="store_true")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )

    # Lazy import to avoid loading the entire server stack at module-import time
    from stock_data.data_provider.manager import get_default_manager
    manager = get_default_manager()

    def _on_progress(src: str, done: int, total: int):
        pct = (done / total * 100) if total else 0
        print(f"\r[{src}] {done}/{total} ({pct:.1f}%)", end="", flush=True)

    print(f"Building membership index...")
    reports = build_membership_index(
        source=args.source, board_type=args.type,
        inter_call_sleep=(args.inter_call_sleep_min, args.inter_call_sleep_max),
        on_progress=_on_progress,
        manager=manager,
    )
    print()  # newline after progress
    agg = _aggregate(reports)
    for r in reports:
        status = "OK" if r.error_count == 0 else f"{r.error_count} ERRORS"
        print(f"  {r.source}: {r.success_count}/{r.total_boards} OK ({status}) {r.duration_seconds:.1f}s")
        for s in r.error_samples:
            print(f"    {s}")
    print(f"Total: {agg.total_success}/{agg.total_boards} OK, {agg.total_errors} errors "
          f"in {agg.duration_seconds:.1f}s across {len(reports)} source(s)")
        for s in report.error_samples:
            print(f"  {s}")
    return 0 if report.error_count == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 5: Run test, verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/test_build_membership_index.py::test_build_one_source_populates_membership -v`

Expected: PASS

- [ ] **Step 6: Write more tests — error isolation + multi-source**

Append to `tests/test_build_membership_index.py`:

```python
def test_per_board_failure_does_not_abort_build(fresh_db, monkeypatch):
    """Single board failure: logged, counted, others still processed."""
    mock = MagicMock()
    mock.get_all_boards.return_value = (
        [
            {"code": "BK_OK1", "name": "OK1", "board_type": "concept", "subtype": "concept"},
            {"code": "BK_FAIL", "name": "FAIL", "board_type": "concept", "subtype": "concept"},
            {"code": "BK_OK2", "name": "OK2", "board_type": "concept", "subtype": "concept"},
        ],
        "eastmoney",
    )
    def get_board_stocks(board_code, source, include_quote):
        if board_code == "BK_FAIL":
            raise RuntimeError("upstream timeout")
        return ([{"stock_code": "X", "stock_name": "X"}], source)
    mock.get_board_stocks.side_effect = get_board_stocks
    monkeypatch.setattr(cli_mod.time, "sleep", lambda *a, **kw: None)
    monkeypatch.setattr(cli_mod.random, "uniform", lambda *a: 0.0)

    report = cli_mod.build_membership_index(
        source="eastmoney", board_type="concept",
        manager=mock,
    )[0]
    assert report.total_boards == 3
    assert report.success_count == 2
    assert report.error_count == 1
    assert "BK_FAIL" in report.error_samples[0]


def test_all_sources_single_call(fresh_db, monkeypatch):
    """source=None iterates all 3 sources and returns a list of reports."""
    mock = _make_manager_mock({
        "eastmoney": ["BK1"], "zhitu": ["sw1"], "zzshare": ["th1"],
    })
    monkeypatch.setattr(cli_mod.time, "sleep", lambda *a, **kw: None)
    monkeypatch.setattr(cli_mod.random, "uniform", lambda *a: 0.0)
    reports = cli_mod.build_membership_index(
        source=None, board_type="concept", manager=mock,
    )
    assert {r.source for r in reports} == {"eastmoney", "zhitu", "zzshare"}
    assert all(r.success_count == 1 for r in reports)
    total_rows = board_mod.read_membership()
    assert len(total_rows) == 9  # 3 sources × 1 board × 3 stocks
```

- [ ] **Step 7: Run tests, verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_build_membership_index.py -v`

Expected: 3 tests PASS

- [ ] **Step 8: Create `stock_data/tools/README.md`**

```markdown
# `stock_data.tools` — Maintenance CLI

## `build_membership_index`

Builds `stock_board_membership` reverse index by walking all boards per source.

### Usage

```bash
# Bootstrap all sources (~10-15 min on per-source workers, ~30-45 min serial)
python -m stock_data.tools.build_membership_index

# Single source, faster iteration during dev
python -m stock_data.tools.build_membership_index --source=zhitu

# Single board_type within a source
python -m stock_data.tools.build_membership_index --source=eastmoney --type=concept

# Adjust rate limit (default 1.0-2.0s jitter)
python -m stock_data.tools.build_membership_index --inter-call-sleep-min 0.5 --inter-call-sleep-max 1.0

# Verbose logging
python -m stock_data.tools.build_membership_index -v
```

### Exit codes

- `0`: All boards succeeded
- `1`: At least one board failed (errors printed at end)

### Notes

- Idempotent: re-running upserts existing rows. `refreshed_at` is updated.
- Cross-source parallel (3 sources → 3 worker threads via top-level
  `ThreadPoolExecutor`); serial within each source (concurrent threads
  against the same upstream just hits its rate limit harder).
- After first bootstrap, membership data is kept fresh by forward-path lazy fill
  (`/boards/{code}/stocks` calls upsert). Long-tail boards never queried require
  `?refresh=true` or this CLI.
```

- [ ] **Step 9: Commit**

```bash
git add stock_data/tools/ tests/test_build_membership_index.py
git commit -m "feat(tools): add build_membership_index CLI with per-source threading"
```

---

## Task 8: Cross-source view `/stocks/{code}/board-memberships`

**Files:**
- Modify: `stock_data/api/schemas.py` (add response models)
- Modify: `stock_data/api/routes/boards.py` (add new route)
- Test: `tests/test_stock_board_memberships_view.py`

- [ ] **Step 1: Write the failing integration test**

```python
"""Integration test: /stocks/{code}/board-memberships cross-source view."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from stock_data.data_provider.persistence import board as board_mod
from stock_data.data_provider.persistence import db as db_mod
from stock_data.server import app


@pytest.fixture
def fresh_db(tmp_path, monkeypatch):
    monkeypatch.setattr(db_mod, "_db_path", None)
    monkeypatch.setattr(db_mod, "_conn", None)
    monkeypatch.setattr(board_mod, "_schema_initialized_paths", set())
    monkeypatch.setenv("STOCK_CACHE_DB_PATH", str(tmp_path / "test.db"))
    board_mod.init_schema()
    yield tmp_path / "test.db"


def test_view_returns_per_source_groups(fresh_db):
    """Cross-source view groups membership rows by source."""
    board_mod.upsert_membership_bulk(
        source="eastmoney",
        stocks=[{"stock_code": "600519", "stock_name": "贵州茅台"}],
        board_code="BK1001", board_name="白酒", board_type="concept", subtype="concept",
    )
    board_mod.upsert_membership_bulk(
        source="zhitu",
        stocks=[{"stock_code": "600519", "stock_name": "贵州茅台"}],
        board_code="sw_yx", board_name="白酒", board_type="industry", subtype="申万行业",
    )
    # zzshare has no data for this stock

    with TestClient(app) as client:
        r = client.get("/stocks/600519/board-memberships")
    assert r.status_code == 200
    body = r.json()
    assert "eastmoney" in body["memberships"]
    assert "zhitu" in body["memberships"]
    assert "zzshare" not in body["memberships"]
    assert "zzshare" in body["cold_sources"]
    assert body["cold_sources"] == ["zzshare"]


def test_view_filters_by_type(fresh_db):
    """?type=concept limits results to concept boards."""
    board_mod.upsert_membership_bulk(
        source="eastmoney",
        stocks=[{"stock_code": "600519", "stock_name": "贵州茅台"}],
        board_code="BK1", board_name="白酒", board_type="concept", subtype="concept",
    )
    board_mod.upsert_membership_bulk(
        source="eastmoney",
        stocks=[{"stock_code": "600519", "stock_name": "贵州茅台"}],
        board_code="BK2", board_name="饮料制造", board_type="industry", subtype="industry",
    )
    with TestClient(app) as client:
        r = client.get("/stocks/600519/board-memberships?type=concept")
    body = r.json()
    eastmoney = body["memberships"]["eastmoney"]
    assert len(eastmoney) == 1
    assert eastmoney[0]["board_code"] == "BK1"


def test_view_empty_stock_returns_all_cold_sources(fresh_db):
    """Stock not in any membership row → all sources cold."""
    with TestClient(app) as client:
        r = client.get("/stocks/999999/board-memberships")
    body = r.json()
    assert body["memberships"] == {}
    assert set(body["cold_sources"]) == {"eastmoney", "zhitu", "zzshare"}
```

- [ ] **Step 2: Run tests, verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_stock_board_memberships_view.py -v`

Expected: All 3 fail with 404 (route doesn't exist yet).

- [ ] **Step 3: Add response models to `schemas.py`**

In `stock_data/api/schemas.py`, after `StockBoardsResponse` (around line 355), add:

```python
class BoardMembershipEntry(BaseModel):
    """Single board entry in the cross-source membership view."""

    board_code: str = Field(description="Source-specific board code")
    board_name: str = Field(description="Board full name")
    board_type: str = Field(description="Board type: concept / industry / index / special")
    subtype: str = Field(
        default="",
        description="Source-specific subtype (raw string, not normalized)",
    )


class BoardMembershipsResponse(BaseModel):
    """Response for /stocks/{stock_code}/board-memberships (cross-source view)."""

    stock_code: str = Field(description="Stock code queried")
    memberships: dict[str, list[BoardMembershipEntry]] = Field(
        default_factory=dict,
        description="Memberships grouped by source. Empty group means no data for that source.",
    )
    cold_sources: list[str] = Field(
        default_factory=list,
        description="Sources with no membership data for this stock. "
        "Run `python -m stock_data.tools.build_membership_index --source=<src>` to populate.",
    )
```

- [ ] **Step 4: Add the route in `routes/boards.py`**

In `stock_data/api/routes/boards.py`, after `get_stock_boards` (around line 377) and before `get_board_history`, add:

```python
@router.get(
    "/stocks/{stock_code}/board-memberships",
    response_model=BoardMembershipsResponse,
    responses={
        400: {"model": ErrorResponse, "description": "Invalid type/subtype"},
        500: {"model": ErrorResponse, "description": "Server error"},
    },
    tags=["boards"],
)
@endpoint_meta(
    summary="股票所属板块（跨源视图）",
    markets=["csi"],
    capabilities=["STOCK_BOARD"],
    # No fetcher_method: this endpoint is pure DB aggregation, never calls a fetcher.
)
@map_errors
def get_stock_board_memberships(
    stock_code: str = Path(max_length=20, description="Stock code (e.g. 000001)"),
    type: Literal["concept", "industry", "index", "special"] | None = Query(
        None, description="Filter by board type"
    ),
    subtype: str | None = Query(
        None, description="Filter by source-specific subtype"
    ),
) -> BoardMembershipsResponse:
    """Cross-source view of all known boards a stock belongs to.

    Reads `stock_board_membership` directly. Does NOT call any fetcher —
    sources without data are returned in `cold_sources` so the caller
    can decide whether to bootstrap via CLI.
    """
    if type is not None:
        _resolve_type(type)

    # Read all rows for this stock (one query, indexed by stock_code)
    rows = stock_board_cache.read_membership(stock_code=stock_code)

    # SQL-level filtering (well, post-SQL Python filtering — small list)
    if type is not None:
        rows = [r for r in rows if r["board_type"] == type]
    if subtype is not None:
        rows = [r for r in rows if r["subtype"] == subtype]

    # Group by source
    by_source: dict[str, list[BoardMembershipEntry]] = {}
    for r in rows:
        by_source.setdefault(r["source"], []).append(
            BoardMembershipEntry(
                board_code=r["board_code"],
                board_name=r["board_name"],
                board_type=r["board_type"],
                subtype=r["subtype"] or "",
            )
        )

    # cold_sources: known sources without data for this stock
    cold = [s for s in _VALID_SOURCES if s not in by_source]

    return BoardMembershipsResponse(
        stock_code=stock_code,
        memberships=by_source,
        cold_sources=cold,
    )
```

Also update the imports at the top of `boards.py`:

```python
from ..schemas import (
    BoardInfo,
    BoardKlineResponse,
    BoardListResponse,
    BoardMembershipEntry,        # NEW
    BoardMembershipsResponse,    # NEW
    BoardStockInfo,
    BoardStocksResponse,
    ErrorResponse,
    KLineData,
    StockBoardInfo,
    StockBoardsResponse,
    ZTPoolResponse,
    ZTPoolStock,
)
```

- [ ] **Step 5: Run tests, verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_stock_board_memberships_view.py -v`

Expected: 3 tests PASS

- [ ] **Step 6: Commit**

```bash
git add stock_data/api/schemas.py stock_data/api/routes/boards.py tests/test_stock_board_memberships_view.py
git commit -m "feat(api/boards): add cross-source board-memberships view"
```

---

## Task 9: Migrate script — verify diff + DROP legacy table

**Files:**
- Create: `scripts/__init__.py`
- Create: `scripts/migrate_to_membership.py`
- Modify: `stock_data/data_provider/persistence/board.py` (simplify `update_cached_board_stocks` to single-write)
- Test: `tests/test_migrate_to_membership.py`

- [ ] **Step 1: Create `scripts/__init__.py`**

```python
"""Project-level maintenance scripts."""
```

- [ ] **Step 2: Write the failing test for migrate script**

```python
"""Tests for scripts/migrate_to_membership.py."""

from __future__ import annotations

import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

from stock_data.data_provider.persistence import board as board_mod
from stock_data.data_provider.persistence import db as db_mod


SCRIPT_PATH = Path(__file__).resolve().parent.parent / "scripts" / "migrate_to_membership.py"


@pytest.fixture
def fresh_db(tmp_path, monkeypatch):
    monkeypatch.setattr(db_mod, "_db_path", None)
    monkeypatch.setattr(db_mod, "_conn", None)
    monkeypatch.setattr(board_mod, "_schema_initialized_paths", set())
    monkeypatch.setenv("STOCK_CACHE_DB_PATH", str(tmp_path / "test.db"))
    board_mod.init_schema()
    yield tmp_path / "test.db"


def _run_script(*args: str, env: dict) -> subprocess.CompletedProcess:
    """Run the migrate script as a subprocess with the given env (incl. STOCK_CACHE_DB_PATH)."""
    return subprocess.run(
        [sys.executable, str(SCRIPT_PATH), *args],
        env=env, capture_output=True, text=True,
    )


def test_dry_run_does_not_drop(fresh_db, monkeypatch):
    """--dry-run (default): prints diff, does NOT drop the legacy table."""
    # Seed legacy table with rows already migrated
    conn = db_mod.get_connection()
    conn.execute("""
        INSERT INTO stock_board_stock (board_code, source, stock_code, stock_name)
        VALUES ('BK1', 'eastmoney', 'X', 'X')
    """)
    conn.commit()
    # Use env var path directly
    env = {"STOCK_CACHE_DB_PATH": str(fresh_db), "PATH": "/usr/bin:/bin"}
    proc = _run_script("--dry-run", env=env)
    assert proc.returncode == 0
    # Legacy table still exists
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='stock_board_stock'"
    ).fetchall()
    assert len(rows) == 1


def test_execute_drops_when_diff_empty(fresh_db):
    """--execute with empty diff: drops legacy table."""
    conn = db_mod.get_connection()
    # Membership has the row, legacy doesn't — diff is empty
    board_mod.upsert_membership_bulk(
        source="eastmoney",
        stocks=[{"stock_code": "X", "stock_name": "X"}],
        board_code="BK1", board_name="B", board_type="concept", subtype="concept",
    )
    env = {"STOCK_CACHE_DB_PATH": str(fresh_db), "PATH": "/usr/bin:/bin"}
    proc = _run_script("--execute", env=env)
    assert proc.returncode == 0
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='stock_board_stock'"
    ).fetchall()
    assert len(rows) == 0  # dropped


def test_execute_refuses_when_diff_nonempty(fresh_db):
    """--execute with non-empty diff: refuses, prints message, exit code 2."""
    conn = db_mod.get_connection()
    # Legacy has a row not in membership
    conn.execute("""
        INSERT INTO stock_board_stock (board_code, source, stock_code, stock_name)
        VALUES ('BK_LEGACY_ONLY', 'eastmoney', 'X', 'X')
    """)
    conn.commit()
    env = {"STOCK_CACHE_DB_PATH": str(fresh_db), "PATH": "/usr/bin:/bin"}
    proc = _run_script("--execute", env=env)
    assert proc.returncode == 2  # non-zero, not success
    assert "diff" in proc.stdout.lower() or "differ" in proc.stdout.lower()
    # Legacy still exists
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='stock_board_stock'"
    ).fetchall()
    assert len(rows) == 1


def test_force_drops_regardless(fresh_db):
    """--execute --force: drops legacy even with non-empty diff."""
    conn = db_mod.get_connection()
    conn.execute("""
        INSERT INTO stock_board_stock (board_code, source, stock_code, stock_name)
        VALUES ('BK_LEGACY_ONLY', 'eastmoney', 'X', 'X')
    """)
    conn.commit()
    env = {"STOCK_CACHE_DB_PATH": str(fresh_db), "PATH": "/usr/bin:/bin"}
    proc = _run_script("--execute", "--force", env=env)
    assert proc.returncode == 0
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='stock_board_stock'"
    ).fetchall()
    assert len(rows) == 0
```

- [ ] **Step 3: Run tests, verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_migrate_to_membership.py -v`

Expected: All fail with `FileNotFoundError` (script doesn't exist).

- [ ] **Step 4: Implement `scripts/migrate_to_membership.py`**

```python
"""Drop legacy `stock_board_stock` table after verifying no data divergence.

The migration `init_schema()` (Task 1) already copied legacy rows into
`stock_board_membership`. This script verifies that copy was complete,
then drops the legacy table.

Usage:
    python scripts/migrate_to_membership.py --dry-run   # Default. Print diff, no changes.
    python scripts/migrate_to_membership.py --execute   # Drop if diff is empty.
    python scripts/migrate_to_membership.py --execute --force  # Drop regardless.

Exit codes:
    0  -- Dry-run OK, OR execute succeeded (table dropped).
    1  -- Internal error (DB not found, etc.)
    2  -- Execute refused due to non-empty diff (use --force to override).
"""

from __future__ import annotations

import argparse
import os
import sqlite3
import sys
from pathlib import Path


def get_db_path() -> Path:
    env_path = os.getenv("STOCK_CACHE_DB_PATH")
    if env_path:
        return Path(env_path)
    # Default matches persistence/db.py
    return Path(__file__).resolve().parent.parent / "stock_data" / "stock_cache.db"


def compute_diff(conn: sqlite3.Connection) -> dict:
    """Compute row counts and key diff between legacy and new tables.

    Returns dict with:
        legacy_count: int — rows in stock_board_stock
        new_count: int — rows in stock_board_membership
        only_in_legacy: int — rows in legacy whose (board_code, source, stock_code)
                              does not appear in membership
    """
    legacy_count = conn.execute(
        "SELECT COUNT(*) FROM stock_board_stock"
    ).fetchone()[0]
    new_count = conn.execute(
        "SELECT COUNT(*) FROM stock_board_membership"
    ).fetchone()[0]

    only_in_legacy = conn.execute("""
        SELECT COUNT(*) FROM stock_board_stock bs
        WHERE NOT EXISTS (
            SELECT 1 FROM stock_board_membership m
            WHERE m.board_code = bs.board_code
              AND m.source = bs.source
              AND m.stock_code = bs.stock_code
        )
    """).fetchone()[0]

    return {
        "legacy_count": legacy_count,
        "new_count": new_count,
        "only_in_legacy": only_in_legacy,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", default=True,
                        help="Print diff; do not drop. (default)")
    parser.add_argument("--execute", action="store_true",
                        help="Drop legacy table if diff is empty.")
    parser.add_argument("--force", action="store_true",
                        help="With --execute, drop even if diff is non-empty.")
    args = parser.parse_args(argv)

    # --execute without --dry-run makes the script "live"; otherwise default to dry-run.
    if args.execute:
        args.dry_run = False

    db_path = get_db_path()
    if not db_path.exists():
        print(f"ERROR: DB not found at {db_path}", file=sys.stderr)
        return 1

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        # Sanity: legacy table exists?
        exists = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='stock_board_stock'"
        ).fetchone()
        if not exists:
            print(f"Legacy table stock_board_stock does not exist; nothing to do.")
            return 0

        diff = compute_diff(conn)
        print(f"stock_board_stock (legacy): {diff['legacy_count']} rows")
        print(f"stock_board_membership (new): {diff['new_count']} rows")
        print(f"Rows in legacy but not in new: {diff['only_in_legacy']}")

        if args.dry_run:
            print("\nDry-run; no changes made. Re-run with --execute to drop legacy table.")
            return 0

        # --execute path
        if diff["only_in_legacy"] > 0 and not args.force:
            print(
                f"\nRefusing to drop: {diff['only_in_legacy']} rows in legacy table "
                f"have no counterpart in new table. Investigate first, or use "
                f"--force to drop anyway."
            )
            return 2

        print("\nDropping stock_board_stock ...")
        conn.execute("DROP TABLE stock_board_stock")
        conn.commit()
        print("Done.")
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 5: Run tests, verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_migrate_to_membership.py -v`

Expected: 4 tests PASS

- [ ] **Step 6: Simplify `update_cached_board_stocks` to single-write**

In `stock_data/data_provider/persistence/board.py`, replace `update_cached_board_stocks` with:

```python
def update_cached_board_stocks(board_code: str, source: str, stocks: list) -> int:
    """
    Upsert stocks for a board into `stock_board_membership` (single-write).

    Note: prior to Task 9, this function dual-wrote to a now-deleted
    `stock_board_stock` table. After `scripts/migrate_to_membership.py
    --execute` ran, only `stock_board_membership` remains.

    Args:
        board_code: Board code
        source: Data source
        stocks: List of dicts [{"stock_code": "600519", "stock_name": "贵州茅台"}, ...]

    Returns:
        Number of stocks written.
    """
    if not stocks:
        return 0

    init_schema()

    conn = get_connection()
    board_row = conn.execute(
        "SELECT name, board_type, subtype FROM stock_board WHERE code = ? AND source = ?",
        (board_code, source),
    ).fetchone()
    board_name = board_row["name"] if board_row else board_code
    board_type = board_row["board_type"] if board_row else ""
    subtype = board_row["subtype"] if board_row else None

    try:
        with conn:
            cursor = conn.cursor()
            cursor.executemany(
                """INSERT OR REPLACE INTO stock_board_membership
                   (board_code, source, stock_code, stock_name,
                    board_name, board_type, subtype, refreshed_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)""",
                [
                    (board_code, source, s["stock_code"], s["stock_name"],
                     board_name, board_type, subtype)
                    for s in stocks
                ],
            )
            logger.info(
                f"[BoardCache] Updated {len(stocks)} stocks for board {board_code}/{source}"
            )
            return len(stocks)
    except Exception as e:
        logger.error(f"[BoardCache] Update board stocks failed: {e}")
        raise
```

- [ ] **Step 7: Re-run the full suite, verify nothing regressed**

Run: `.venv/Scripts/python.exe -m pytest tests/test_board_membership_double_write.py tests/test_board_stocks_forward_route.py -v`

Expected: All PASS (the dual-write tests still pass because they only assert that membership was populated, not that legacy table was).

- [ ] **Step 8: Commit**

```bash
git add scripts/ stock_data/data_provider/persistence/board.py tests/test_migrate_to_membership.py
git commit -m "chore: add migrate_to_membership.py script + simplify update_cached_board_stocks to single-write"
```

---

## Final verification

After all 9 tasks complete:

- [ ] **Run full test suite (default, skipping live_network)**

```bash
.venv/Scripts/python.exe -m pytest
```

Expected: all tests pass (live_network tests skipped by default per CLAUDE.md).

- [ ] **Run linter**

```bash
ruff check .
ruff format .
```

Expected: clean.

- [ ] **Smoke test the CLI**

```bash
# Verify CLI help works without hitting upstream (mock-only mode)
.venv/Scripts/python.exe -m stock_data.tools.build_membership_index --help
```

Expected: prints usage text.

- [ ] **Verify migration script dry-run is safe**

```bash
.venv/Scripts/python.exe scripts/migrate_to_membership.py --dry-run
```

Expected: prints row counts, returns 0, makes no DB changes.

- [ ] **Git log shows 8+ commits (preflight + 8 task commits)**

```bash
git log --oneline -10
```

Expected: clean, sequential commits with conventional commit prefixes.

---

## Reference

- Spec: `docs/superpowers/specs/2026-07-01-stock-board-membership-design.md`
- Design doc: `docs/stock-board-reverse-index-design-2026-07-01.md`
- Conventions: `CLAUDE.md` (anti-patterns + capability routing)