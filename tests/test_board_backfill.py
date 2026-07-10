"""Tests for persistence.backfill module."""
from __future__ import annotations

import os
import time
from unittest.mock import patch, MagicMock

import pytest

from stock_data.data_provider.base import DataFetchError
from stock_data.data_provider.persistence import board as board_mod
from stock_data.data_provider.persistence import db as db_mod
from stock_data.data_provider.persistence.backfill import run_ths_board_backfill


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
    """Manager mock: get_all_boards returns boards for ths filtered by board_type;
    returns [] for zzshare (best-effort platecode backfill). get_board_stocks returns []
    (phase 1 doesn't fetch stocks)."""
    mock = MagicMock()

    def get_all_boards(source, board_type=None, subtype=None, include_quote=False):
        if source == "ths":
            filtered = [b for b in boards if board_type is None or b.get("type") == board_type]
            return (filtered, "ths")
        return ([], source)

    mock.get_all_boards.side_effect = get_all_boards
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


def test_full_sweep_writes_membership(fresh_db, monkeypatch):
    """Phase 2: 3 boards × 2 stocks each → membership rows written."""
    boards = [
        {"code": "301558", "name": "B1", "type": "concept",
         "subtype": "同花顺概念", "platecode": "885001"},
        {"code": "301559", "name": "B2", "type": "concept",
         "subtype": "同花顺概念", "platecode": "885002"},
        {"code": "881001", "name": "B3", "type": "industry",
         "subtype": "同花顺行业", "platecode": "881001"},
    ]
    mock = MagicMock()

    # filter by board_type so fetch_boards_with_zzshare_backfill's per-type
    # loop emits each board exactly once across the (concept, industry) sweep.
    def get_all_boards(source, board_type=None, subtype=None, include_quote=False):
        if source == "ths":
            filtered = [b for b in boards if board_type is None or b.get("type") == board_type]
            return (filtered, "ths")
        return ([], source)

    mock.get_all_boards.side_effect = get_all_boards

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
    # membership upserts key on platecode (not the THS board code), so query by platecode.
    rows = []
    for bk in ("885001", "885002", "881001"):
        rows.extend(board_mod.read_membership(board_code=bk, source="ths"))
    assert len(rows) == 5
    for bk in ("885001", "885002", "881001"):
        assert any(r["stock_code"] == "000002" for r in rows if r["board_code"] == bk)


def test_skip_platecode_none(fresh_db, monkeypatch):
    """Boards without platecode are skipped in phase 2."""
    boards = [
        {"code": "C1", "name": "Has-PC", "type": "concept",
         "subtype": "同花顺概念", "platecode": "885001"},
        {"code": "C2", "name": "No-PC",  "type": "concept",
         "subtype": "同花顺概念", "platecode": None},
    ]
    mock = MagicMock()

    def get_all_boards(source, board_type=None, subtype=None, include_quote=False):
        # fetch_boards_with_zzshare_backfill iterates (concept, industry).
        # Per-type loop only sees boards whose type matches; zzshare call
        # contributes nothing (no platecode backfill expected here).
        if source == "ths":
            filtered = [b for b in boards
                        if board_type is None or b.get("type") == board_type]
            return (filtered, "ths")
        return ([], source)

    mock.get_all_boards.side_effect = get_all_boards
    mock.get_board_stocks.return_value = ([{"stock_code": "000001",
                                             "stock_name": "S"}], "zzshare")
    monkeypatch.setattr("time.sleep", lambda *_a, **_kw: None)

    report = run_ths_board_backfill(mock, inter_call_sleep_s=0.0)

    assert report.phase2.success == 1
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

    def get_all_boards(source, board_type=None, subtype=None, include_quote=False):
        if source == "ths":
            filtered = [b for b in boards
                        if board_type is None or b.get("type") == board_type]
            return (filtered, "ths")
        return ([], source)

    mock.get_all_boards.side_effect = get_all_boards

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

    def get_all_boards(source, board_type=None, subtype=None, include_quote=False):
        if source == "ths":
            filtered = [b for b in boards
                        if board_type is None or b.get("type") == board_type]
            return (filtered, "ths")
        return ([], source)

    mock.get_all_boards.side_effect = get_all_boards
    mock.get_board_stocks.return_value = (
        [{"stock_code": "000001", "stock_name": "S"}], "zzshare")
    monkeypatch.setattr("time.sleep", lambda *_a, **_kw: None)

    run_ths_board_backfill(mock, inter_call_sleep_s=0.0)
    rows_first = board_mod.read_membership(board_code="885001", source="ths")
    assert len(rows_first) == 1

    run_ths_board_backfill(mock, inter_call_sleep_s=0.0)
    rows_second = board_mod.read_membership(board_code="885001", source="ths")
    assert len(rows_second) == 1


def test_rate_limit_enforced_with_token(monkeypatch, fresh_db):
    """3 boards × 1.2s sleep ⇒ elapsed >= 3.6s."""
    boards = [
        {"code": f"C{i}", "name": f"B{i}", "type": "concept",
         "subtype": "同花顺概念", "platecode": f"88500{i}"}
        for i in range(1, 4)
    ]
    mock = MagicMock()

    def get_all_boards(source, board_type=None, subtype=None, include_quote=False):
        if source == "ths":
            filtered = [b for b in boards
                        if board_type is None or b.get("type") == board_type]
            return (filtered, "ths")
        return ([], source)

    mock.get_all_boards.side_effect = get_all_boards
    mock.get_board_stocks.return_value = (
        [{"stock_code": "000001", "stock_name": "S"}], "zzshare")
    monkeypatch.setenv("ZZSHARE_TOKEN", "fake-token")

    t0 = time.monotonic()
    run_ths_board_backfill(mock)
    elapsed = time.monotonic() - t0

    assert elapsed >= 3.4, f"elapsed={elapsed:.2f}s, expected >= 3.4s"


def test_rate_limit_enforced_without_token(monkeypatch, fresh_db):
    """Without ZZSHARE_TOKEN: 2 boards × 3.0s sleep ⇒ elapsed >= 6.0s."""
    boards = [
        {"code": f"C{i}", "name": f"B{i}", "type": "concept",
         "subtype": "同花顺概念", "platecode": f"88500{i}"}
        for i in range(1, 3)
    ]
    mock = MagicMock()

    def get_all_boards(source, board_type=None, subtype=None, include_quote=False):
        if source == "ths":
            filtered = [b for b in boards
                        if board_type is None or b.get("type") == board_type]
            return (filtered, "ths")
        return ([], source)

    mock.get_all_boards.side_effect = get_all_boards
    mock.get_board_stocks.return_value = (
        [{"stock_code": "000001", "stock_name": "S"}], "zzshare")
    monkeypatch.delenv("ZZSHARE_TOKEN", raising=False)

    t0 = time.monotonic()
    run_ths_board_backfill(mock)
    elapsed = time.monotonic() - t0

    assert elapsed >= 5.7, f"elapsed={elapsed:.2f}s, expected >= 5.7s"


def test_schedule_returns_task_and_sets_app_state(monkeypatch, fresh_db):
    """The async schedule puts a task on app.state.backfill_task."""
    import asyncio
    from stock_data.data_provider.persistence import backfill
    from fastapi import FastAPI

    app = FastAPI()
    app.state.manager = MagicMock()
    app.state.manager.get_all_boards.return_value = ([], "ths")
    app.state.manager.get_board_stocks.return_value = ([], "zzshare")

    async def fake_to_thread(func, *args, **kwargs):
        return func(*args, **kwargs)

    monkeypatch.setattr(backfill.asyncio, "to_thread", fake_to_thread)

    task = asyncio.run(backfill.schedule_ths_board_backfill_on_startup(app))
    assert task.done()
    assert getattr(app.state, "backfill_task", None) is not None
