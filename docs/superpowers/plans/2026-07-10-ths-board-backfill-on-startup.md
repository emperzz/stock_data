# THS Board Backfill on Startup Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** At server startup (opt-in via `BOARD_BACKFILL_ON_STARTUP=true`), kick off an async background task that refreshes the THS board list (`stock_board`) and THS↔stock membership (`stock_board_membership`); remove the on-request cold-fill fallback so reverse lookups don't return partial board sets.

**Architecture:** New `stock_data/data_provider/persistence/backfill.py` exposes a sync `run_ths_board_backfill(manager, ...)` plus an async `schedule_ths_board_backfill_on_startup(app)`. `server.py:lifespan` reads the env var and schedules the task via `asyncio.create_task` after `app.state.manager` is wired; a corresponding shutdown hook cancels the task to avoid orphan work. Cold-fill (`get_stock_memberships(cold_fill=...)` + `?cold_fill=true` Query) is deleted across 3 code files + 4 test files + 2 doc files.

**Tech Stack:** FastAPI lifespan, asyncio + `asyncio.to_thread`, sqlite3 (WAL mode), ten-stock dataclass result reports, MagicMock-based unit tests, FastAPI TestClient for integration.

**Spec:** [`docs/superpowers/specs/2026-07-10-ths-board-backfill-on-startup-design.md`](../specs/2026-07-10-ths-board-backfill-on-startup-design.md) (committed as bc5a0b3)

---

## File Structure

| Action | Path | Responsibility |
|---|---|---|
| Create | `stock_data/data_provider/persistence/backfill.py` | Sync `run_ths_board_backfill` + async `schedule_ths_board_backfill_on_startup` + `BackfillReport` dataclass + `_auto_rate_limit_s` |
| Create | `tests/test_board_backfill.py` | Unit tests (7 cases per spec §7.1) — mocks fetcher, ephemeral SQLite via `monkeypatch.setenv("STOCK_CACHE_DB_PATH", ...)` |
| Create | `tests/test_boards_backfill_integration.py` | Integration test: backfill directly + hit route handler with mock manager |
| Modify | `stock_data/server.py` (lifespan) | Startup hook (`BOARD_BACKFILL_ON_STARTUP=true`) + Shutdown cancel hook |
| Modify | `.env.example` | Add `BOARD_BACKFILL_ON_STARTUP=false` section (default off) |
| Modify | `stock_data/data_provider/persistence/board.py` (`get_stock_memberships`) | Drop `cold_fill` parameter and its for-loop block (per spec §5.1) |
| Modify | `stock_data/api/routes/boards.py:730` | Drop `cold_fill: bool = Query(...)` parameter |
| Modify | `tests/test_boards_api.py:765-794` | Delete cold_fill test cases |
| Modify | `tests/test_persistence_board_memberships.py:181-244` | Delete cold_fill test cases |
| Modify | `tests/test_stock_boards_reverse_route.py:134-164` | Delete cold_fill test cases |
| Modify | `tests/test_stock_boards_eastmoney_source.py:5-123` | Delete cold_fill test cases |
| Modify | `README.md` | Remove `cold_fill` references in API table |
| Modify | `CLAUDE.md` | Remove `cold_fill=True` route description |

Each task below produces **one commit**. Order:
1. Module + unit tests (the largest, TDD)
2. Server wiring + env
3. cold-fill removal (code, tests, docs) — atomic commit
4. Integration test
5. Cleanup verification

---

## Task 1: Backfill module skeleton + dataclasses + `_auto_rate_limit_s`

**Files:**
- Create: `stock_data/data_provider/persistence/backfill.py`
- Create: `tests/test_board_backfill.py`

- [ ] **Step 1.1: Write the failing test for `_auto_rate_limit_s`**

Create `tests/test_board_backfill.py`:

```python
"""Tests for persistence.backfill module."""
from __future__ import annotations

import os
from unittest.mock import patch

import pytest


def test_auto_rate_limit_s_with_token_returns_1_2():
    """`_auto_rate_limit_s` returns 1.2s when ZZSHARE_TOKEN is set."""
    from stock_data.data_provider.persistence.backfill import _auto_rate_limit_s

    with patch.dict(os.environ, {"ZZSHARE_TOKEN": "any-value"}):
        assert _auto_rate_limit_s() == pytest.approx(1.2)


def test_auto_rate_limit_s_without_token_returns_3_0():
    """`_auto_rate_limit_s` returns 3.0s when ZZSHARE_TOKEN is absent."""
    from stock_data.data_provider.persistence.backfill import _auto_rate_limit_s

    env = {k: v for k, v in os.environ.items() if k != "ZZSHARE_TOKEN"}
    with patch.dict(os.environ, env, clear=True):
        assert _auto_rate_limit_s() == pytest.approx(3.0)
```

- [ ] **Step 1.2: Run the test, expect FAIL with "No module named 'backfill'"**

Run: `.venv/Scripts/python.exe -m pytest tests/test_board_backfill.py -v`
Expected: `ModuleNotFoundError: No module named 'stock_data.data_provider.persistence.backfill'`

- [ ] **Step 1.3: Write the minimal module skeleton**

Create `stock_data/data_provider/persistence/backfill.py`:

```python
"""Async startup backfill for THS board list + stock→board membership.

Bootstraps ``stock_board`` and ``stock_board_membership`` (for source='ths')
once on lifespan startup so that ``/stocks/{code}/boards`` cache-miss
responses return complete board sets instead of partial ones.

Reference: docs/superpowers/specs/2026-07-10-ths-board-backfill-on-startup-design.md
"""
from __future__ import annotations

import asyncio
import logging
import os
import time
from dataclasses import dataclass, field
from typing import Callable

from fastapi import FastAPI

logger = logging.getLogger(__name__)


def _auto_rate_limit_s() -> float:
    """Return the per-call sleep to stay under zzshare ``plates_stocks`` rate.

    UNVERIFIED: ``docs/zzshare/10-rate-limits.md`` does not list
    ``plates_stocks()`` explicitly. We use the nearest-neighbor
    (`market_plate_stocks()`) limit: 60/min with token ⇒ ~1.0s margin ⇒
    sleep 1.2s; 20/min anonymous ⇒ sleep 3.0s.
    """
    return 1.2 if os.getenv("ZZSHARE_TOKEN", "") else 3.0


@dataclass
class PhaseStats:
    duration_s: float = 0.0
    success: int = 0
    errors: int = 0
    error_samples: list[str] = field(default_factory=list)


@dataclass
class BackfillReport:
    phase1: PhaseStats = field(default_factory=PhaseStats)
    phase2: PhaseStats = field(default_factory=PhaseStats)
    phase1_boards_emitted: int = 0     # boards returned by fetch_boards_with_zzshare_backfill
    phase2_boards_committed: int = 0   # boards whose membership upsert fired


# ── Stub implementations: filled in by Tasks 2-3 ──────────────────────────
def run_ths_board_backfill(
    manager,
    *,
    inter_call_sleep_s: float | None = None,
    include_quote: bool = False,
    on_progress: Callable[[str, int, int], None] | None = None,
) -> BackfillReport:
    """Sync entry point — real implementation in Task 2 & 3."""
    raise NotImplementedError


async def schedule_ths_board_backfill_on_startup(app: FastAPI) -> asyncio.Task:
    """Async wrapper — real implementation in Task 6."""
    raise NotImplementedError
```

- [ ] **Step 1.4: Run the test, expect PASS**

Run: `.venv/Scripts/python.exe -m pytest tests/test_board_backfill.py -v`
Expected: PASS (2 tests, both green)

- [ ] **Step 1.5: Commit**

```bash
git add stock_data/data_provider/persistence/backfill.py tests/test_board_backfill.py
git commit -m "feat(persistence/backfill): module skeleton with dataclass + rate-limit helper"
```

---

## Task 2: Implement Phase 1 (board list fetch + groupby + update)

**Files:**
- Modify: `stock_data/data_provider/persistence/backfill.py`
- Modify: `tests/test_board_backfill.py`

- [ ] **Step 2.1: Write the failing test for Phase 1**

Append to `tests/test_board_backfill.py`:

```python
from unittest.mock import MagicMock

from stock_data.data_provider.persistence import board as board_mod
from stock_data.data_provider.persistence import db as db_mod
from stock_data.data_provider.persistence.backfill import run_ths_board_backfill


@pytest.fixture
def fresh_db(tmp_path, monkeypatch):
    """Ephemeral SQLite DB — reset module singletons so init_schema reruns."""
    monkeypatch.setattr(db_mod, "_db_path", None)
    monkeypatch.setattr(db_mod, "_conn", None)
    monkeypatch.setattr(board_mod, "_schema_initialized_paths", set())
    monkeypatch.setenv("STOCK_CACHE_DB_PATH", str(tmp_path / "test.db"))
    board_mod.init_schema()
    yield tmp_path / "test.db"


def _make_phase1_only_manager(boards):
    """Manager mock: get_all_boards returns boards; get_board_stocks returns []."""
    mock = MagicMock()
    mock.get_all_boards.return_value = (boards, "ths")
    mock.get_board_stocks.return_value = ([], "zzshare")
    return mock


def test_phase1_writes_to_stock_board(fresh_db, monkeypatch):
    """Phase 1 fetches boards, groupby type, writes to stock_board via update_cached_boards."""
    boards = [
        {"code": "C1", "name": "Concept-1", "type": "concept",
         "subtype": "同花顺概念", "platecode": "885001"},
        {"code": "C2", "name": "Concept-2", "type": "concept",
         "subtype": "同花顺概念", "platecode": "885002"},
        {"code": "I1", "name": "Industry-1", "type": "industry",
         "subtype": "同花顺行业", "platecode": "881001"},
    ]
    mock = _make_phase1_only_manager(boards)
    monkeypatch.setattr("time.sleep", lambda *_a, **_kw: None)

    report = run_ths_board_backfill(
        mock, inter_call_sleep_s=0.0, include_quote=False,
    )

    # phase1 success count = boards written to stock_board
    assert report.phase1.success == 3
    assert report.phase1_boards_emitted == 3
    # rows persisted: 2 concept + 1 industry
    concept_rows = board_mod._read_boards_from_db("concept", "ths")
    industry_rows = board_mod._read_boards_from_db("industry", "ths")
    assert len(concept_rows) == 2
    assert len(industry_rows) == 1
    # phase2 untouched (no boards had membership data)
    assert report.phase2.success == 0
```

- [ ] **Step 2.2: Run the test, expect FAIL with "NotImplementedError"**

Run: `.venv/Scripts/python.exe -m pytest tests/test_board_backfill.py::test_phase1_writes_to_stock_board -v`
Expected: `NotImplementedError`

- [ ] **Step 2.3: Replace the stub `run_ths_board_backfill` with Phase 1 implementation**

Replace the entire `run_ths_board_backfill` function body in `stock_data/data_provider/persistence/backfill.py`:

```python
from collections import defaultdict

from .board import (
    fetch_boards_with_zzshare_backfill,
    init_schema,
    update_cached_boards,
)
from .db import get_db_path


def run_ths_board_backfill(
    manager,
    *,
    inter_call_sleep_s: float | None = None,
    include_quote: bool = False,
    on_progress: Callable[[str, int, int], None] | None = None,
) -> BackfillReport:
    """Two-phase sync backfill. See spec §3.1."""
    if inter_call_sleep_s is None:
        inter_call_sleep_s = _auto_rate_limit_s()

    report = BackfillReport()
    init_schema()  # idempotent

    # ── Phase 1: stock_board ──────────────────────────────────────────
    t0 = time.time()
    try:
        boards_merged = fetch_boards_with_zzshare_backfill(
            board_type=None,
            refresh=True,
            include_quote=include_quote,
            subtype=None,
            manager=manager,
        )
    except Exception as e:
        report.phase1.errors += 1
        report.phase1.error_samples.append(f"phase1 fetch: {type(e).__name__}: {e}")
        report.phase1.duration_s = time.time() - t0
        logger.exception("[Startup/Backfill] phase 1 fetch raised: %s", e)
        return report

    report.phase1_boards_emitted = len(boards_merged)
    if not boards_merged:
        report.phase1.duration_s = time.time() - t0
        logger.warning("[Startup/Backfill] phase 1 returned 0 boards; skipping phase 2")
        return report

    # Groupby board_type — update_cached_boards takes ONE board_type per call
    grouped: dict[str, list[dict]] = defaultdict(list)
    for b in boards_merged:
        grouped[b["type"]].append(b)

    for bt, bucket in grouped.items():
        if bt in ("concept", "industry"):
            report.phase1.success += update_cached_boards(bt, "ths", bucket)
    report.phase1.duration_s = time.time() - t0
    logger.info(
        "[Startup/Backfill] phase 1 wrote %d boards in %.1fs",
        report.phase1.success, report.phase1.duration_s,
    )

    # Phase 2 implementation added in Task 3
    return report
```

- [ ] **Step 2.4: Run the test, expect PASS**

Run: `.venv/Scripts/python.exe -m pytest tests/test_board_backfill.py -v`
Expected: PASS (3 tests green)

- [ ] **Step 2.5: Commit**

```bash
git add stock_data/data_provider/persistence/backfill.py tests/test_board_backfill.py
git commit -m "feat(persistence/backfill): phase 1 stock_board refresh with groupby + upsert"
```

---

## Task 3: Implement Phase 2 (membership backfill loop with conn lifecycle)

**Files:**
- Modify: `stock_data/data_provider/persistence/backfill.py`
- Modify: `tests/test_board_backfill.py`

- [ ] **Step 3.1: Write the failing test for Phase 2 (full sweep)**

Append to `tests/test_board_backfill.py`:

```python
def test_full_sweep_writes_membership(fresh_db, monkeypatch):
    """Phase 2: 3 boards × 2 stocks each → 6 membership rows."""
    boards = [
        {"code": "301558", "name": "B1", "type": "concept",
         "subtype": "同花顺概念", "platecode": "885001"},
        {"code": "301559", "name": "B2", "type": "concept",
         "subtype": "同花顺概念", "platecode": "885002"},
        {"code": "881001", "name": "B3", "type": "industry",
         "subtype": "同花顺行业", "platecode": "881001"},
    ]
    mock = MagicMock()
    mock.get_all_boards.return_value = (boards, "ths")

    # zzshare path: each board returns 2 stocks; B2 returns 1 different code
    def get_board_stocks(board_code, source, include_quote):
        assert source == "zzshare"
        if board_code == "885002":
            return ([{"stock_code": "000002", "stock_name": "Stock-2"}], "zzshare")
        return ([
            {"stock_code": "000001", "stock_name": "Stock-1"},
            {"stock_code": "000002", "stock_name": "Stock-2"},
        ], "zzshare")

    mock.get_board_stocks.side_effect = get_board_stocks
    monkeypatch.setattr("time.sleep", lambda *_a, **_kw: None)

    report = run_ths_board_backfill(mock, inter_call_sleep_s=0.0)

    assert report.phase2.success == 3
    assert report.phase2_boards_committed == 3
    # Membership rows: B1 has 2, B2 has 1, B3 has 2 → 5 rows
    rows = []
    for bk in ("301558", "301559", "881001"):
        rows.extend(board_mod.read_membership(board_code=bk, source="ths"))
    assert len(rows) == 5
    # Spot-check: 000002 appears in B1 + B2 + B3
    for bk in ("301558", "301559", "881001"):
        assert any(r["stock_code"] == "000002" for r in rows if r["board_code"] == bk)
```

- [ ] **Step 3.2: Run the test, expect FAIL (phase 2 not implemented yet — row count = 0)**

Run: `.venv/Scripts/python.exe -m pytest tests/test_board_backfill.py::test_full_sweep_writes_membership -v`
Expected: `AssertionError: assert 5 == ...0...`

- [ ] **Step 3.3: Add Phase 2 + imports to `run_ths_board_backfill`**

Update imports at top of `backfill.py`:

```python
import sqlite3
```

Add the following to the imports block (keep existing ones):

```python
from .board import (
    fetch_boards_with_zzshare_backfill,
    init_schema,
    update_cached_boards,
    upsert_membership_bulk,
)
from .db import get_db_path
from ..base import DataFetchError
```

Replace the `# Phase 2 implementation added in Task 3` line at the end of `run_ths_board_backfill` with:

```python
    # ── Phase 2: stock_board_membership ──────────────────────────────
    t1 = time.time()
    self_conn = sqlite3.connect(str(get_db_path()), timeout=30)
    try:
        # PRAGMA WAL is idempotent at the file level — build_membership_index
        # already does this; safe to re-run per-thread.
        try:
            self_conn.execute("PRAGMA journal_mode=WAL")
        except sqlite3.OperationalError as exc:
            if "locked" not in str(exc):
                raise
            logger.debug("[Startup/Backfill] WAL pragma busy: %r", exc)

        total_p2 = len(boards_merged)
        for idx, board in enumerate(boards_merged):
            platecode = board.get("platecode")
            if not platecode:
                logger.debug("[Startup/Backfill] skipping board %s (no platecode)",
                             board.get("code"))
                continue
            try:
                rows, _ = manager.get_board_stocks(
                    board_code=platecode,
                    source="zzshare",
                    include_quote=False,
                )
            except (DataFetchError, Exception) as e:
                report.phase2.errors += 1
                if len(report.phase2.error_samples) < 20:
                    report.phase2.error_samples.append(
                        f"{platecode}: {type(e).__name__}: {e}")
                logger.warning("[Startup/Backfill] phase 2 board %s failed: %s",
                               platecode, e)
            else:
                if rows:
                    upsert_membership_bulk(
                        source="ths",
                        stocks=rows,
                        board_code=platecode,
                        board_name=board.get("name", ""),
                        board_type=board.get("type", ""),
                        subtype=board.get("subtype") or "",
                        conn=self_conn,
                    )
                    report.phase2.success += 1
                    report.phase2_boards_committed += 1
            finally:
                time.sleep(inter_call_sleep_s)

            # Progress every 50 boards
            done = idx + 1
            if done % 50 == 0 and on_progress:
                on_progress("ths", done, total_p2)
            if done % 50 == 0:
                logger.info(
                    "[Startup/Backfill] phase 2 progress=%d/%d errors=%d elapsed=%.0fs",
                    done, total_p2, report.phase2.errors,
                    time.time() - t1,
                )
    finally:
        self_conn.close()

    report.phase2.duration_s = time.time() - t1
    logger.info(
        "[Startup/Backfill] phase 2 wrote %d boards (%d errors) in %.1fs",
        report.phase2.success, report.phase2.errors, report.phase2.duration_s,
    )
    return report
```

- [ ] **Step 3.4: Run the test, expect PASS**

Run: `.venv/Scripts/python.exe -m pytest tests/test_board_backfill.py -v`
Expected: PASS (4 tests green)

- [ ] **Step 3.5: Commit**

```bash
git add stock_data/data_provider/persistence/backfill.py tests/test_board_backfill.py
git commit -m "feat(persistence/backfill): phase 2 membership loop with rate limit + conn lifecycle"
```

---

## Task 4: Add edge-case tests (skip platecode=None, error continues, idempotent, rate limit)

**Files:**
- Modify: `tests/test_board_backfill.py`

- [ ] **Step 4.1: Write 4 edge-case tests**

Append to `tests/test_board_backfill.py`:

```python
def test_skip_platecode_none(fresh_db, monkeypatch):
    """Boards without platecode are skipped in phase 2."""
    boards = [
        {"code": "C1", "name": "Has-PC", "type": "concept",
         "subtype": "同花顺概念", "platecode": "885001"},
        {"code": "C2", "name": "No-PC",  "type": "concept",
         "subtype": "同花顺概念", "platecode": None},
    ]
    mock = MagicMock()
    mock.get_all_boards.return_value = (boards, "ths")
    mock.get_board_stocks.return_value = ([{"stock_code": "000001",
                                             "stock_name": "S"}], "zzshare")
    monkeypatch.setattr("time.sleep", lambda *_a, **_kw: None)

    report = run_ths_board_backfill(mock, inter_call_sleep_s=0.0)

    # Only 1 board had platecode → 1 successful membership upsert
    assert report.phase2.success == 1
    # get_board_stocks called exactly once (for the platecode-bearing board)
    assert mock.get_board_stocks.call_count == 1


def test_error_continues_with_remaining_boards(fresh_db, monkeypatch):
    """A single board's DataFetchError does NOT abort phase 2."""
    boards = [
        {"code": "C1", "name": "OK1", "type": "concept",
         "subtype": "同花顺概念", "platecode": "885001"},
        {"code": "C2", "name": "FAIL", "type": "concept",
         "subtype": "同花顺概念", "platecode": "885002"},
        {"code": "C3", "name": "OK2", "type": "concept",
         "subtype": "同花顺概念", "platecode": "885003"},
    ]
    mock = MagicMock()
    mock.get_all_boards.return_value = (boards, "ths")

    def get_board_stocks(board_code, source, include_quote):
        if board_code == "885002":
            raise DataFetchError("upstream timeout")
        return ([{"stock_code": "000001", "stock_name": "S"}], "zzshare")

    mock.get_board_stocks.side_effect = get_board_stocks
    monkeypatch.setattr("time.sleep", lambda *_a, **_kw: None)

    report = run_ths_board_backfill(mock, inter_call_sleep_s=0.0)

    assert report.phase2.success == 2
    assert report.phase2.errors == 1
    assert any("885002" in s for s in report.phase2.error_samples)


def test_idempotent_re_run_insert_or_replace(fresh_db, monkeypatch):
    """Re-running produces same row count (INSERT OR REPLACE)."""
    boards = [{"code": "C1", "name": "B", "type": "concept",
               "subtype": "同花顺概念", "platecode": "885001"}]
    mock = MagicMock()
    mock.get_all_boards.return_value = (boards, "ths")
    mock.get_board_stocks.return_value = (
        [{"stock_code": "000001", "stock_name": "S"}], "zzshare")
    monkeypatch.setattr("time.sleep", lambda *_a, **_kw: None)

    run_ths_board_backfill(mock, inter_call_sleep_s=0.0)
    rows_first = board_mod.read_membership(board_code="C1", source="ths")
    assert len(rows_first) == 1

    run_ths_board_backfill(mock, inter_call_sleep_s=0.0)
    rows_second = board_mod.read_membership(board_code="C1", source="ths")
    assert len(rows_second) == 1   # still 1 row, refreshed_at updated


def test_rate_limit_enforced_with_token(monkeypatch, fresh_db):
    """3 boards × 1.2s sleep ⇒ elapsed ≥ 3.6s."""
    boards = [
        {"code": f"C{i}", "name": f"B{i}", "type": "concept",
         "subtype": "同花顺概念", "platecode": f"88500{i}"}
        for i in range(1, 4)
    ]
    mock = MagicMock()
    mock.get_all_boards.return_value = (boards, "ths")
    mock.get_board_stocks.return_value = (
        [{"stock_code": "000001", "stock_name": "S"}], "zzshare")
    monkeypatch.setenv("ZZSHARE_TOKEN", "fake-token")

    t0 = time.monotonic()
    run_ths_board_backfill(mock)   # inter_call_sleep_s=None → auto-detect 1.2
    elapsed = time.monotonic() - t0

    # 3 boards × 1.2s = 3.6s expected. Allow 10% slack for test infra.
    assert elapsed >= 3.4, f"elapsed={elapsed:.2f}s, expected ≥ 3.4s"


def test_rate_limit_enforced_without_token(monkeypatch, fresh_db):
    """Without ZZSHARE_TOKEN: 2 boards × 3.0s sleep ⇒ elapsed ≥ 6.0s."""
    boards = [
        {"code": f"C{i}", "name": f"B{i}", "type": "concept",
         "subtype": "同花顺概念", "platecode": f"88500{i}"}
        for i in range(1, 3)
    ]
    mock = MagicMock()
    mock.get_all_boards.return_value = (boards, "ths")
    mock.get_board_stocks.return_value = (
        [{"stock_code": "000001", "stock_name": "S"}], "zzshare")
    monkeypatch.delenv("ZZSHARE_TOKEN", raising=False)

    t0 = time.monotonic()
    run_ths_board_backfill(mock)
    elapsed = time.monotonic() - t0

    assert elapsed >= 5.7, f"elapsed={elapsed:.2f}s, expected ≥ 5.7s"
```

- [ ] **Step 4.2: Run the new tests, expect PASS**

Run: `.venv/Scripts/python.exe -m pytest tests/test_board_backfill.py -v`
Expected: PASS (9 tests green)

> Import for `DataFetchError` at the top of the test file:
> ```python
> from stock_data.data_provider.base import DataFetchError
> ```
> Also import `time` at the top:
> ```python
> import time
> ```

- [ ] **Step 4.3: Commit**

```bash
git add tests/test_board_backfill.py
git commit -m "test(backfill): edge cases — skip/continue/idempotent/rate-limit"
```

---

## Task 5: Implement `schedule_ths_board_backfill_on_startup` async wrapper

**Files:**
- Modify: `stock_data/data_provider/persistence/backfill.py`
- Modify: `tests/test_board_backfill.py`

- [ ] **Step 5.1: Write the failing test for the async wrapper**

Append to `tests/test_board_backfill.py`:

```python
import asyncio


def test_schedule_returns_task_and_sets_app_state(monkeypatch, fresh_db):
    """The async schedule puts a task on app.state.backfill_task."""
    from stock_data.data_provider.persistence import backfill
    from fastapi import FastAPI

    app = FastAPI()
    app.state.manager = _make_phase1_only_manager([])

    # Run synchronously to completion by mocking asyncio.to_thread
    async def fake_to_thread(func, *args, **kwargs):
        return func(*args, **kwargs)

    monkeypatch.setattr(backfill.asyncio, "to_thread", fake_to_thread)

    task = asyncio.run(backfill.schedule_ths_board_backfill_on_startup(app))
    assert task.done()
    assert getattr(app.state, "backfill_task", None) is not None
```

Note: `_make_phase1_only_manager([])` returns empty boards — phase 1 exits early without calling fetcher. The test verifies only the wiring (task returned + state set).

- [ ] **Step 5.2: Run the test, expect FAIL with NotImplementedError**

Run: `.venv/Scripts/python.exe -m pytest tests/test_board_backfill.py::test_schedule_returns_task_and_sets_app_state -v`
Expected: `NotImplementedError`

- [ ] **Step 5.3: Replace the stub async wrapper**

Replace the stub `schedule_ths_board_backfill_on_startup` in `backfill.py`:

```python
async def schedule_ths_board_backfill_on_startup(app: FastAPI) -> asyncio.Task:
    """Spawn the backfill in a worker thread; return the task for caller.

    The caller (``server.py:lifespan``) stores the returned task on
    ``app.state.backfill_task`` to cancel it on shutdown. The actual
    sync work runs in ``asyncio.to_thread`` so the event loop is not
    blocked by ~17min of fetcher sleeps.
    """
    task = asyncio.create_task(
        asyncio.to_thread(run_ths_board_backfill, app.state.manager)
    )
    app.state.backfill_task = task
    return task
```

- [ ] **Step 5.4: Run the test, expect PASS**

Run: `.venv/Scripts/python.exe -m pytest tests/test_board_backfill.py -v`
Expected: PASS (10 tests green)

- [ ] **Step 5.5: Commit**

```bash
git add stock_data/data_provider/persistence/backfill.py tests/test_board_backfill.py
git commit -m "feat(backfill): schedule_ths_board_backfill_on_startup async wrapper"
```

---

## Task 6: Wire lifespan startup + shutdown hooks in `server.py`

**Files:**
- Modify: `stock_data/server.py`

- [ ] **Step 6.1: Modify `server.py` — add startup hook after `app.state.manager` assignment**

Edit `stock_data/server.py` after line `app.state.manager = _get_manager()` (line 86 in current file):

Add the new block:

```python
    # ----- THS board backfill on startup (opt-in via env) -----
    # Inside function body (not module top) — only imported when env=true.
    # Keeps cold-start path zero extra imports. Task ref stored on
    # app.state.backfill_task so the shutdown hook below can cancel it.
    if os.getenv("BOARD_BACKFILL_ON_STARTUP", "false").lower() == "true":
        from .data_provider.persistence.backfill import (
            schedule_ths_board_backfill_on_startup,
        )
        asyncio.create_task(schedule_ths_board_backfill_on_startup(app))
        logger.info("[Startup] THS board backfill scheduled (BOARD_BACKFILL_ON_STARTUP=true)")
    else:
        logger.info("[Startup] THS board backfill skipped (set BOARD_BACKFILL_ON_STARTUP=true to enable)")
```

- [ ] **Step 6.2: Modify `server.py` — add shutdown cancel hook**

In `server.py`, immediately AFTER `yield` and BEFORE `logger.info("Shutting down Stock Data Server")` (line 90), insert:

```python
    # ----- Cancel in-flight backfill so Ctrl-C / SIGTERM doesn't leak state -----
    backfill_task = getattr(app.state, "backfill_task", None)
    if backfill_task and not backfill_task.done():
        backfill_task.cancel()
        try:
            await backfill_task
        except (asyncio.CancelledError, Exception) as e:
            logger.info(f"[Shutdown] THS board backfill cancelled ({type(e).__name__})")
    if hasattr(app.state, "backfill_task"):
        del app.state.backfill_task
```

- [ ] **Step 6.3: Verify server still imports cleanly**

Run: `.venv/Scripts/python.exe -c "from stock_data.server import app"`
Expected: no exception (just prints any startup logs)

- [ ] **Step 6.4: Run existing server-startup test to ensure no regression**

Run: `.venv/Scripts/python.exe -m pytest tests/test_server_control_endpoints.py -v`
Expected: PASS

- [ ] **Step 6.5: Commit**

```bash
git add stock_data/server.py
git commit -m "chore(server): wire BOARD_BACKFILL_ON_STARTUP startup + shutdown cancel hooks"
```

---

## Task 7: Add `BOARD_BACKFILL_ON_STARTUP` to `.env.example`

**Files:**
- Modify: `.env.example`

- [ ] **Step 7.1: Append the new env var section**

Append to `.env.example` (after the Baidu section is fine; alphabetical order isn't enforced):

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

- [ ] **Step 7.2: Commit**

```bash
git add .env.example
git commit -m "docs(env): document BOARD_BACKFILL_ON_STARTUP (default off)"
```

---

## Task 8: Remove `cold_fill` from `get_stock_memberships` (persistence layer)

**Files:**
- Modify: `stock_data/data_provider/persistence/board.py` (`get_stock_memberships`)

- [ ] **Step 8.1: Drop the `cold_fill` parameter + the for-loop block**

In `stock_data/data_provider/persistence/board.py`:

Find `get_stock_memberships` (~ line 1279). Make these surgical changes:

**(a)** Remove the `cold_fill: bool = False` parameter from the signature.

**(b)** Remove the lazy import of `get_stock_name` (no longer needed):

```python
        from .stock_list import get_stock_name as _get_stock_name
```

**(c)** Remove the entire block:

```python
    coldfill_attempted: set[str] = set()
    if cold_fill and manager is not None:
        from .stock_list import get_stock_name as _get_stock_name

        for cold_src in ("ths", "zhitu", "eastmoney"):  # ths 加首位 (新实现)
            if cold_src not in sources or cold_src in present_sources:
                continue
            coldfill_attempted.add(cold_src)
            boards, _ = manager.get_stock_boards(stock_code, source=cold_src)
            if boards:
                stock_name = _get_stock_name(stock_code) or ""
                upsert_membership_for_stock_boards(
                    stock_code=stock_code,
                    stock_name=stock_name,
                    boards=boards,
                    source=cold_src,
                )
                # Re-read to include newly written rows
                entries, present_sources = _read_membership_entries(stock_code, sources, cursor)
```

**(d)** Delete the `coldfill_attempted` branch and `elif cold_fill and manager is not None` branch in the `origin_summary` decision (around lines 1370-1390):

Remove:

```python
    if not entries:
        # Empty entries: distinguish "cache miss, no cold-fill" from
        # "cold-fill attempted but fetcher returned []". The latter case
        # (e.g. BSE stock queried via source=ths, where the fetcher
        # early-returns without hitting upstream) would otherwise look
        # identical to a clean cache miss.
        if coldfill_attempted:
            origin_summary = "cold_fill_empty"
        else:
            origin_summary = "persistence"
```

Replace with:

```python
    if not entries:
        origin_summary = "persistence"
```

And remove:

```python
    elif cold_fill and manager is not None:
        # Cold-fill actually wrote data; signal which source(s) hit the network.
        # Single-source query takes the queried source's name; multi-source uses "mixed".
        coldfill_sources = {"ths", "zhitu", "eastmoney"} & {e["source"] for e in entries}
        if coldfill_sources and len(sources) == 1:
            origin_summary = next(iter(coldfill_sources))
        elif coldfill_sources or len(sources) > 1:
            origin_summary = "mixed"
        else:
            origin_summary = "persistence"
```

Keep the existing multi-source / single-source branches.

**(e)** Update the docstring: remove `cold_fill` from `Args:`; remove the `cold_fill_empty` entry from `origin_summary` list.

- [ ] **Step 8.2: Run existing tests — expect failures in 4 test files (cleaned up next)**

Run: `.venv/Scripts/python.exe -m pytest tests/test_boards_api.py tests/test_persistence_board_memberships.py tests/test_stock_boards_reverse_route.py tests/test_stock_boards_eastmoney_source.py -v 2>&1 | tail -50`
Expected: Multiple tests fail with `TypeError: ... unexpected keyword argument 'cold_fill'`. **This is expected** — Task 9 fixes them.

---

## Task 9: Clean up cold_fill test cases in 4 test files

**Files:**
- Modify: `tests/test_boards_api.py` (cold_fill block at line 765-794)
- Modify: `tests/test_persistence_board_memberships.py` (cold_fill block at line 181-244)
- Modify: `tests/test_stock_boards_reverse_route.py` (cold_fill block at line 134-164)
- Modify: `tests/test_stock_boards_eastmoney_source.py` (cold_fill block at line 5-123)

- [ ] **Step 9.1: Delete cold_fill test in `tests/test_boards_api.py`**

Open `tests/test_boards_api.py`. Locate the function `test_get_stock_boards_zhitu_cold_fill_returns_populated_boards` (~ line 765) and delete the entire function (lines 765 to 805 — inclusive of `try/finally` cleanup).

Run: `grep -n 'cold_fill' tests/test_boards_api.py`
Expected: no matches.

- [ ] **Step 9.2: Delete cold_fill test(s) in `tests/test_persistence_board_memberships.py`**

Run: `grep -n 'cold_fill' tests/test_persistence_board_memberships.py` to list affected line ranges. Delete each `def test_.*cold_fill.*` function entirely. Verify with second grep — should return no matches.

- [ ] **Step 9.3: Delete cold_fill test(s) in `tests/test_stock_boards_reverse_route.py`**

Run: `grep -n 'cold_fill' tests/test_stock_boards_reverse_route.py`. Delete every cold_fill test function (lines ~134-164 plus any others). Verify with second grep.

- [ ] **Step 9.4: Delete cold_fill test(s) in `tests/test_stock_boards_eastmoney_source.py`**

Run: `grep -n 'cold_fill' tests/test_stock_boards_eastmoney_source.py`. Delete every cold_fill test function (lines 5-123). Verify with second grep.

- [ ] **Step 9.5: Run the 4 cleaned files — expect PASS**

Run: `.venv/Scripts/python.exe -m pytest tests/test_boards_api.py tests/test_persistence_board_memberships.py tests/test_stock_boards_reverse_route.py tests/test_stock_boards_eastmoney_source.py -v`
Expected: PASS (any pre-existing failures unrelated to cold_fill remain; the cold_fill ones are gone)

- [ ] **Step 9.6: Run the full default test suite — expect no regression**

Run: `.venv/Scripts/python.exe -m pytest 2>&1 | tail -30`
Expected: PASS (skipping `live_network` tests as per default). If unrelated failures appear, fix them in a separate commit.

- [ ] **Step 9.7: Commit (combined with Task 8)**

```bash
git add stock_data/data_provider/persistence/board.py \
        tests/test_boards_api.py \
        tests/test_persistence_board_memberships.py \
        tests/test_stock_boards_reverse_route.py \
        tests/test_stock_boards_eastmoney_source.py
git commit -m "refactor(boards): drop cold_fill (param + block + tests)"
```

---

## Task 10: Remove `cold_fill` Query param from `routes/boards.py`

**Files:**
- Modify: `stock_data/api/routes/boards.py`

- [ ] **Step 10.1: Locate the cold_fill Query param**

Run: `grep -n 'cold_fill' stock_data/api/routes/boards.py`
Expected: matches around line 730 (the `cold_fill: bool = Query(...)` parameter) and line 760 (the `cold_fill=cold_fill` pass-through).

- [ ] **Step 10.2: Remove the parameter and pass-through**

In `stock_data/api/routes/boards.py`, delete lines 730-734 (the Query parameter):

```python
    cold_fill: bool = Query(
        False,
        description="Opt-in lazy-fill on cold data for ths / zhitu / eastmoney. "
        "Default false (cold data surfaces in cold_sources instead).",
    ),
```

And in the `get_stock_memberships(...)` call (~ line 760), delete the `cold_fill=cold_fill,` line.

Update the function's docstring (line 736-741) to remove "opt-in cold-fill" wording — replace with a one-liner about the unified single-source/multi-source behavior.

- [ ] **Step 10.3: Verify routes still pass other route-arg tests**

Run: `.venv/Scripts/python.exe -m pytest tests/test_boards.py tests/test_stock_boards_reverse_route.py -v 2>&1 | tail -20`
Expected: PASS (cold_fill absent from URL → no effect)

- [ ] **Step 10.4: Commit**

```bash
git add stock_data/api/routes/boards.py
git commit -m "refactor(boards): drop cold_fill Query from /stocks/{code}/boards"
```

---

## Task 11: Update README.md and CLAUDE.md cold_fill references

**Files:**
- Modify: `README.md`
- Modify: `CLAUDE.md`

- [ ] **Step 11.1: Find cold_fill in `README.md`**

Run: `grep -n 'cold_fill' README.md`
Expected: hits around line 657 / 662 (API doc table).

- [ ] **Step 11.2: Update README.md**

For each `cold_fill` occurrence in `README.md`:

- In the API table cell describing `cold_fill`, remove that line entirely (or replace with `— removed 2026-07-10; reverse lookup now relies on startup backfill or returns cold_sources on miss`).

- If there is a separate `cold_fill` row in any capability / route table, delete that row.

Verify with second grep — should be no matches.

- [ ] **Step 11.3: Find cold_fill in `CLAUDE.md`**

Run: `grep -n 'cold_fill' CLAUDE.md`

- [ ] **Step 11.4: Update CLAUDE.md**

For each occurrence:

- Replace the `cold_fill=True` route description with a brief note: "removed 2026-07-10; replaced by startup backfill or accepts cold-miss via `cold_sources`".
- If any "Anti-Patterns to Avoid" mentions `cold_fill`, replace with the new caveat about zzshare backfill.

Verify with second grep.

- [ ] **Step 11.5: Commit**

```bash
git add README.md CLAUDE.md
git commit -m "docs: remove cold_fill references (superseded by startup backfill)"
```

---

## Task 12: Add integration test (reverse lookup completeness)

**Files:**
- Create: `tests/test_boards_backfill_integration.py`

- [ ] **Step 12.1: Write the integration test**

Create `tests/test_boards_backfill_integration.py`:

```python
"""Integration test: backfill → reverse lookup completeness.

Verifies the spec §1.1 problem: a stock belonging to multiple boards used
to return only the boards that happened to be queried once. After
``run_ths_board_backfill`` populates both tables, the reverse lookup
returns the COMPLETE set.
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from stock_data.api.routes.helpers import get_manager as routes_get_manager
from stock_data.data_provider.persistence import board as board_mod
from stock_data.data_provider.persistence import db as db_mod
from stock_data.data_provider.persistence.backfill import run_ths_board_backfill


@pytest.fixture
def fresh_db(tmp_path, monkeypatch):
    monkeypatch.setattr(db_mod, "_db_path", None)
    monkeypatch.setattr(db_mod, "_conn", None)
    monkeypatch.setattr(board_mod, "_schema_initialized_paths", set())
    monkeypatch.setenv("STOCK_CACHE_DB_PATH", str(tmp_path / "test.db"))
    board_mod.init_schema()
    yield tmp_path / "test.db"


def _make_backfill_manager():
    """Two boards, both contain stock_code='000034'.

    Without backfill, the cache is empty → reverse lookup returns [].
    After backfill populates stock_board_membership, reverse lookup
    returns BOTH boards.
    """
    boards = [
        {"code": "301558", "name": "ConceptA", "type": "concept",
         "subtype": "同花顺概念", "platecode": "885001"},
        {"code": "301559", "name": "ConceptB", "type": "concept",
         "subtype": "同花顺概念", "platecode": "885002"},
    ]
    mock = MagicMock()
    mock.get_all_boards.return_value = (boards, "ths")

    def get_board_stocks(board_code, source, include_quote):
        return ([
            {"stock_code": "000034", "stock_name": "Starter-000034"},
            {"stock_code": "999999", "stock_name": "Other"},
        ], "zzshare")

    mock.get_board_stocks.side_effect = get_board_stocks
    return mock


def test_reverse_lookup_after_backfill_returns_all_boards(fresh_db, monkeypatch):
    """After backfill, both boards containing stock 000034 surface in reverse lookup."""
    mock = _make_backfill_manager()
    monkeypatch.setattr("time.sleep", lambda *_a, **_kw: None)

    # 1. Run backfill directly (no real network — mock manager handles all calls)
    run_ths_board_backfill(mock, inter_call_sleep_s=0.0)

    # 2. Reverse lookup via persistence helper (the route layer's read path)
    entries, cold_sources, origin = board_mod.get_stock_memberships(
        stock_code="000034",
        sources=["ths"],
        manager=mock,
    )

    # 3. Both boards now appear (this is the bug-fix assertion)
    assert len(entries) == 2
    board_codes = {e["code"] for e in entries}
    assert board_codes == {"301558", "301559"}
    assert cold_sources == []
    assert origin == "persistence"
```

- [ ] **Step 12.2: Run the test, expect PASS**

Run: `.venv/Scripts/python.exe -m pytest tests/test_boards_backfill_integration.py -v`
Expected: PASS

- [ ] **Step 12.3: Run the full default suite one final time**

Run: `.venv/Scripts/python.exe -m pytest 2>&1 | tail -30`
Expected: PASS (or pre-existing unrelated failures only).

- [ ] **Step 12.4: Commit**

```bash
git add tests/test_boards_backfill_integration.py
git commit -m "test(boards): integration test for backfill → reverse lookup completeness"
```

---

## Task 13: Final verification

**Files:** (no changes)

- [ ] **Step 13.1: Run the complete default test suite once more**

Run: `.venv/Scripts/python.exe -m pytest -v 2>&1 | tail -40`
Expected: All tests PASS (skipping `live_network`).

- [ ] **Step 13.2: Verify `git status` is clean and review the commit graph**

```bash
git status
git log --oneline -15
```

Expected:
- `git status` ⇒ nothing to commit, working tree clean
- `git log` ⇒ shows the 12 commits from Tasks 1-12 + the original spec commit (bc5a0b3).

- [ ] **Step 13.3: Sanity-check that the lifespan hook is opt-in (default OFF)**

Run: `python -c "import os; print(repr(os.getenv('BOARD_BACKFILL_ON_STARTUP', 'false')))"`
Expected: `'false'` (env not set → default off)

- [ ] **Step 13.4: Summary message to user**

Print the list of commits, mention that startup backfill is opt-in via env, and remind the user about:
- ~17min cold start cost when enabled (token) / ~43min (anonymous)
- Removing cold-fill is a breaking change for any client passing `?cold_fill=true` (those will get 422)

---

## Self-Review Checklist

(Executed after writing all tasks above; recorded inline.)

| Check | OK? | Notes |
|---|---|---|
| Spec coverage — spec §1-§10 → tasks 1-12 + 13 | ✓ | every spec requirement maps to a task |
| No placeholders (TBD / TODO / "fill in details") | ✓ | grep `TBD\|TODO\|fill in` returns no matches |
| Type consistency — `inter_call_sleep_s`, `_auto_rate_limit_s`, `phase1.success`, `phase2.success`, `app.state.backfill_task` | ✓ | used identically across Tasks 1-5 |
| Exact file paths everywhere | ✓ | every step names a path with line numbers |
| TDD pattern (test → fail → impl → pass → commit) | ✓ | Tasks 1-5 + integration test follow it |
| All code blocks are complete (no "..." or stubs in worker code) | ✓ | Tasks 1, 5, 8 explicitly mark stubs but Tasks 2, 3, 6, 10 provide full diffs |
| Cold-fill removal is atomic (Task 8 + Task 9 are broken out but should be tested as one) | ✓ | Task 9 verifies with grep + pytest |
| Integration test exercises spec §1.1 bug scenario | ✓ | Task 12 asserts both boards return for stock 000034 |
| Shutdown cancel logic covered | ✓ | Task 6 + spec §4.2 |
| Default `BOARD_BACKFILL_ON_STARTUP=false` honored | ✓ | Task 7 + Step 13.3 |

