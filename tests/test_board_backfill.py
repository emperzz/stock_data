"""Tests for persistence.backfill module."""
from __future__ import annotations

import os
import threading
import time
from unittest.mock import MagicMock, patch

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

    # Both zzshare (called with platecode) AND ths fallback (called with
    # the resolved THS cid from the just-written stock_board row) must
    # raise — fetch_board_stocks_with_zzshare_fallback tries both before
    # propagating. Trigger failure on EITHER board_code to simulate a
    # board that's broken in both fetches.
    def get_board_stocks(board_code, source, include_quote):
        if board_code in ("885002", "C2"):
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

    from fastapi import FastAPI

    from stock_data.data_provider.persistence import backfill

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
    # The shutdown coordination primitive — set by schedule_*, read by server.py.
    assert getattr(app.state, "backfill_cancel", None) is not None


# ── Fix #1: silent task failure is now logged via done_callback ──────────


def test_schedule_logs_exception_via_done_callback(monkeypatch, fresh_db, caplog):
    """Unhandled exception in the worker is logged via add_done_callback.

    Without this callback, asyncio logs only 'Task exception was never
    retrieved' to stderr and the operator never sees the real failure.
    """
    import asyncio
    import logging

    from fastapi import FastAPI

    from stock_data.data_provider.persistence import backfill

    app = FastAPI()
    app.state.manager = MagicMock()
    # Provide boards for phase 1 fetch (success), then make the groupby /
    # update_cached_boards step raise — that path is NOT wrapped in
    # try/except, so the exception escapes run_ths_board_backfill.
    app.state.manager.get_all_boards.return_value = (
        [{"code": "C1", "name": "B1", "type": "concept",
          "subtype": "同花顺概念", "platecode": "885001"}],
        "ths",
    )

    def raise_in_phase1(*_a, **_kw):
        raise RuntimeError("simulated sqlite failure in phase 1 groupby")

    monkeypatch.setattr(backfill, "update_cached_boards", raise_in_phase1)

    async def fake_to_thread(func, *args, **kwargs):
        return func(*args, **kwargs)

    monkeypatch.setattr(backfill.asyncio, "to_thread", fake_to_thread)

    with caplog.at_level(
        logging.ERROR, logger="stock_data.data_provider.persistence.backfill"
    ):
        asyncio.run(backfill.schedule_ths_board_backfill_on_startup(app))

    # The done_callback fires _on_done which calls logger.exception —
    # message must mention "unhandled" or "raised".
    assert any(
        ("unhandled exception" in r.message or "raised" in r.message)
        for r in caplog.records
    ), f"expected exception to be logged; got records: {[r.message for r in caplog.records]}"


# ── Fix #2: cooperative cancel via threading.Event ──────────────────────


def test_cancel_event_breaks_phase2_loop(fresh_db, monkeypatch):
    """Setting cancel_event exits phase 2 early."""
    from stock_data.data_provider.persistence.backfill import (
        run_ths_board_backfill,
    )

    boards = [
        {"code": f"C{i}", "name": f"B{i}", "type": "concept",
         "subtype": "同花顺概念", "platecode": f"8850{i:02d}"}
        for i in range(1, 51)  # 50 boards — too many to finish naturally
    ]
    mock = MagicMock()

    def get_all_boards(source, board_type=None, subtype=None, include_quote=False):
        if source == "ths":
            filtered = [
                b for b in boards if board_type is None or b.get("type") == board_type
            ]
            return (filtered, "ths")
        return ([], source)

    mock.get_all_boards.side_effect = get_all_boards
    mock.get_board_stocks.return_value = (
        [{"stock_code": "000001", "stock_name": "S"}], "zzshare"
    )

    cancel_event = threading.Event()

    sleep_count = [0]

    def mock_sleep(_s):
        sleep_count[0] += 1
        # Trip the cancel after 5 successful iterations.
        if sleep_count[0] >= 5:
            cancel_event.set()

    monkeypatch.setattr("time.sleep", mock_sleep)

    report = run_ths_board_backfill(
        mock, inter_call_sleep_s=0.0, cancel_event=cancel_event,
    )

    # Loop broke early — well below 50 boards.
    assert report.phase2.success < 50
    assert report.phase2.success >= 5  # at least the 5 before cancel fired


# ── Fix #3: consecutive-error short-circuit + sleep skipped on error ─────


def test_consecutive_errors_abort_phase2(fresh_db, monkeypatch):
    """MAX_CONSECUTIVE_ERRORS consecutive failures short-circuit the loop."""
    from stock_data.data_provider.persistence.backfill import (
        MAX_CONSECUTIVE_ERRORS,
        run_ths_board_backfill,
    )

    # 50 boards — way more than MAX_CONSECUTIVE_ERRORS, so the loop must
    # abort before processing all of them.
    boards = [
        {"code": f"C{i}", "name": f"B{i}", "type": "concept",
         "subtype": "同花顺概念", "platecode": f"8850{i:02d}"}
        for i in range(1, 51)
    ]
    mock = MagicMock()

    def get_all_boards(source, board_type=None, subtype=None, include_quote=False):
        if source == "ths":
            filtered = [
                b for b in boards if board_type is None or b.get("type") == board_type
            ]
            return (filtered, "ths")
        return ([], source)

    mock.get_all_boards.side_effect = get_all_boards

    def get_board_stocks(board_code, source, include_quote):
        # Every board fails — upstream is down.
        raise DataFetchError("upstream timeout")

    mock.get_board_stocks.side_effect = get_board_stocks
    monkeypatch.setattr("time.sleep", lambda *_a, **_kw: None)

    report = run_ths_board_backfill(mock, inter_call_sleep_s=0.0)

    # Aborted at MAX_CONSECUTIVE_ERRORS (not 50).
    assert report.phase2.errors == MAX_CONSECUTIVE_ERRORS
    assert report.phase2.success == 0


def test_sleep_not_called_on_error_path(fresh_db, monkeypatch):
    """time.sleep is skipped when fetch_board_stocks_with_zzshare_fallback raises.

    Old code put sleep in `finally:` which paid the full rate-limit wait
    even on the error path — wasted ~12s per failed board during a
    sustained outage.
    """
    from stock_data.data_provider.persistence.backfill import (
        run_ths_board_backfill,
    )

    boards = [
        {"code": "C1", "name": "FAIL", "type": "concept",
         "subtype": "同花顺概念", "platecode": "885001"},
    ]
    mock = MagicMock()

    def get_all_boards(source, board_type=None, subtype=None, include_quote=False):
        return (
            [b for b in boards if b.get("type") == board_type] if source == "ths" else [],
            source,
        )

    mock.get_all_boards.side_effect = get_all_boards
    mock.get_board_stocks.side_effect = DataFetchError("boom")

    sleep_calls = []
    monkeypatch.setattr(
        "time.sleep", lambda s: sleep_calls.append(s),
    )

    run_ths_board_backfill(mock, inter_call_sleep_s=1.5)

    # The only board errored and triggered the consecutive-error abort;
    # no successful iteration means no sleep.
    assert sleep_calls == [], (
        f"sleep was called on error path: {sleep_calls}"
    )


# ── Fix #7: per-board zzshare→ths fallback ──────────────────────────────


def test_zzshare_empty_falls_back_to_ths(fresh_db, monkeypatch):
    """When zzshare returns empty, fetch_board_stocks_with_zzshare_fallback
    transparently retries via ths — so the backfill mirrors the route layer's
    per-board fallback behavior and cache completeness matches what users see.
    """
    from stock_data.data_provider.persistence.backfill import (
        run_ths_board_backfill,
    )

    boards = [
        {"code": "C1", "name": "B1", "type": "concept",
         "subtype": "同花顺概念", "platecode": "885001"},
    ]
    mock = MagicMock()

    def get_all_boards(source, board_type=None, subtype=None, include_quote=False):
        if source == "ths":
            return (
                [b for b in boards if b.get("type") == board_type], "ths",
            )
        return ([], source)

    mock.get_all_boards.side_effect = get_all_boards

    ths_stocks = [{"stock_code": "000099", "stock_name": "From-THS"}]

    def get_board_stocks(board_code, source, include_quote):
        if source == "zzshare":
            return ([], "zzshare")  # empty — should fall back to ths
        return (ths_stocks, "ths")

    mock.get_board_stocks.side_effect = get_board_stocks
    monkeypatch.setattr("time.sleep", lambda *_a, **_kw: None)

    report = run_ths_board_backfill(mock, inter_call_sleep_s=0.0)

    # ths fallback succeeded — backfill wrote membership.
    assert report.phase2.success == 1
    rows = board_mod.read_membership(board_code="885001", source="ths")
    assert any(r["stock_code"] == "000099" for r in rows), (
        f"ths-fallback stocks not in membership cache; rows: {rows}"
    )


def test_zzshare_raises_falls_back_to_ths(fresh_db, monkeypatch):
    """When zzshare raises DataFetchError, the helper falls back to ths."""
    from stock_data.data_provider.persistence.backfill import (
        run_ths_board_backfill,
    )

    boards = [
        {"code": "C1", "name": "B1", "type": "concept",
         "subtype": "同花顺概念", "platecode": "885001"},
    ]
    mock = MagicMock()

    def get_all_boards(source, board_type=None, subtype=None, include_quote=False):
        if source == "ths":
            return (
                [b for b in boards if b.get("type") == board_type], "ths",
            )
        return ([], source)

    mock.get_all_boards.side_effect = get_all_boards

    ths_stocks = [{"stock_code": "000099", "stock_name": "From-THS"}]

    call_log = []

    def get_board_stocks(board_code, source, include_quote):
        call_log.append(source)
        if source == "zzshare":
            raise DataFetchError("zzshare 503")
        return (ths_stocks, "ths")

    mock.get_board_stocks.side_effect = get_board_stocks
    monkeypatch.setattr("time.sleep", lambda *_a, **_kw: None)

    report = run_ths_board_backfill(mock, inter_call_sleep_s=0.0)

    # Both fetches attempted; ths fallback succeeded.
    assert call_log == ["zzshare", "ths"]
    assert report.phase2.success == 1
    assert report.phase2.errors == 0
