"""Tests for persistence.backfill module."""

from __future__ import annotations

import contextlib
import os
import threading
import time
from unittest.mock import MagicMock, patch

import pytest

from stock_data.data_provider.base import DataFetchError
from stock_data.data_provider.persistence import board as board_mod
from stock_data.data_provider.persistence import db as db_mod
from stock_data.data_provider.persistence.backfill import run_ths_board_backfill


def test_auto_rate_limit_s_is_stable_at_1_5():
    """`_auto_rate_limit_s` is a flat 1.5s — ZZSHARE_TOKEN no longer matters.

    Pre-2026-09-11 it returned 1.2s with a zzshare token and 3.0s without
    one, because phase 2's primary leg was zzshare's ``plates_stocks``.
    That leg is gone (the backfill is THS-only), so the THS board-page
    jitter floor applies unconditionally. Asserted in BOTH env states so a
    future change cannot silently re-introduce a token-dependent branch.
    """
    from stock_data.data_provider.persistence.backfill import _auto_rate_limit_s

    with patch.dict(os.environ, {"ZZSHARE_TOKEN": "any-value"}):
        assert _auto_rate_limit_s() == pytest.approx(1.5)

    env = {k: v for k, v in os.environ.items() if k != "ZZSHARE_TOKEN"}
    with patch.dict(os.environ, env, clear=True):
        assert _auto_rate_limit_s() == pytest.approx(1.5)


def test_ths_board_fetch_jitter_bounds():
    """Inter-call sleep is ``uniform(*THS_BOARD_FETCH_JITTER_S)``.

    ``_auto_rate_limit_s`` is the floor of that window, so the two values
    cannot drift apart without this test noticing.
    """
    from stock_data.data_provider.persistence.backfill import (
        THS_BOARD_FETCH_JITTER_S,
        _auto_rate_limit_s,
    )

    floor, ceiling = THS_BOARD_FETCH_JITTER_S
    assert floor > 0
    assert ceiling > floor
    assert floor == pytest.approx(_auto_rate_limit_s())


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
    """Manager mock: ``get_all_boards`` returns THS rows filtered by
    ``board_type``; ``get_board_stocks_full`` returns ``([], "ths")``
    (phase 1 never fetches stocks).

    Board rows use the internal ``get_all_boards`` shape — ``board_code`` /
    ``name`` / ``board_type`` / ``subtype`` / ``ths_cid``. For THS industry
    rows ``board_code == ths_cid`` (881xxx)."""
    mock = MagicMock()

    def get_all_boards(source, board_type=None, subtype=None, include_quote=False):
        if source == "ths":
            filtered = [
                b for b in boards if board_type is None or b.get("board_type") == board_type
            ]
            return (filtered, "ths")
        return ([], source)

    mock.get_all_boards.side_effect = get_all_boards
    mock.get_board_stocks_full.return_value = ([], "ths")
    return mock


def test_phase1_writes_to_stock_board(fresh_db, monkeypatch):
    """Phase 1 fetches one THS sweep per board_type, writes stock_board."""
    boards = [
        {
            "board_code": "885001",
            "name": "Concept-1",
            "board_type": "concept",
            "subtype": "同花顺概念",
            "ths_cid": "301546",
        },
        {
            "board_code": "885002",
            "name": "Concept-2",
            "board_type": "concept",
            "subtype": "同花顺概念",
            "ths_cid": "301547",
        },
        {
            "board_code": "881001",
            "name": "Industry-1",
            "board_type": "industry",
            "subtype": "同花顺行业",
            "ths_cid": "881001",
        },
    ]
    mock = _make_phase1_only_manager(boards)
    monkeypatch.setattr("time.sleep", lambda *_a, **_kw: None)

    report = run_ths_board_backfill(
        mock,
        inter_call_sleep_s=0.0,
        include_quote=False,
    )

    # phase1 success count = boards written to stock_board
    assert report.phase1.success == 3
    assert report.phase1_boards_emitted == 3
    # rows persisted: 2 concept + 1 industry
    concept_rows = board_mod._read_boards_from_db("concept", "ths")
    industry_rows = board_mod._read_boards_from_db("industry", "ths")
    assert len(concept_rows) == 2
    assert len(industry_rows) == 1
    # The THS cid survives the round trip under its new key: 3xxxxx for
    # concept rows, == board_code for industry rows.
    assert {r["ths_cid"] for r in concept_rows} == {"301546", "301547"}
    assert {r["ths_cid"] for r in industry_rows} == {"881001"}
    # phase2 untouched (get_board_stocks_full returns [])
    assert report.phase2.success == 0


def test_full_sweep_writes_membership(fresh_db, monkeypatch):
    """Phase 2: 3 boards × 2 stocks each → membership rows written."""
    boards = [
        {
            "board_code": "885001",
            "name": "B1",
            "board_type": "concept",
            "subtype": "同花顺概念",
            "ths_cid": "301558",
        },
        {
            "board_code": "885002",
            "name": "B2",
            "board_type": "concept",
            "subtype": "同花顺概念",
            "ths_cid": "301559",
        },
        {
            "board_code": "881001",
            "name": "B3",
            "board_type": "industry",
            "subtype": "同花顺行业",
            "ths_cid": "881001",
        },
    ]
    mock = MagicMock()

    # filter by board_type so the phase-1 per-type loop emits each board
    # exactly once across the (concept, industry) sweep.
    def get_all_boards(source, board_type=None, subtype=None, include_quote=False):
        if source == "ths":
            filtered = [
                b for b in boards if board_type is None or b.get("board_type") == board_type
            ]
            return (filtered, "ths")
        return ([], source)

    mock.get_all_boards.side_effect = get_all_boards

    def get_board_stocks_full(board_code, source="ths", *, board_type=None):
        # THS-only leg: the F10 page is addressed by the public board_code
        # (885xxx concept / 881xxx industry) and by the board's own type.
        assert source == "ths"
        assert board_type in ("concept", "industry")
        if board_code == "885002":
            return ([{"stock_code": "000002", "stock_name": "Stock-2"}], "ths")
        return (
            [
                {"stock_code": "000001", "stock_name": "Stock-1"},
                {"stock_code": "000002", "stock_name": "Stock-2"},
            ],
            "ths",
        )

    mock.get_board_stocks_full.side_effect = get_board_stocks_full
    monkeypatch.setattr("time.sleep", lambda *_a, **_kw: None)

    report = run_ths_board_backfill(mock, inter_call_sleep_s=0.0)

    assert report.phase2.success == 3
    assert report.phase2_boards_committed == 3
    # Membership upserts key on the THS board_code and are stamped
    # source='ths' — the single labeled source post-split.
    rows = []
    for bk in ("885001", "885002", "881001"):
        rows.extend(board_mod.read_membership(board_code=bk, source="ths"))
    assert len(rows) == 5
    for bk in ("885001", "885002", "881001"):
        assert any(r["stock_code"] == "000002" for r in rows if r["board_code"] == bk)


def test_skip_board_without_board_code(fresh_db, monkeypatch):
    """Boards without a board_code are not addressable → skipped in phase 2."""
    boards = [
        {
            "board_code": "885001",
            "name": "Has-Code",
            "board_type": "concept",
            "subtype": "同花顺概念",
            "ths_cid": "301546",
        },
        {
            "board_code": "",
            "name": "No-Code",
            "board_type": "concept",
            "subtype": "同花顺概念",
            "ths_cid": None,
        },
    ]
    mock = MagicMock()

    def get_all_boards(source, board_type=None, subtype=None, include_quote=False):
        # phase 1 iterates (concept, industry); per-type loop only sees
        # boards whose board_type matches.
        if source == "ths":
            filtered = [
                b for b in boards if board_type is None or b.get("board_type") == board_type
            ]
            return (filtered, "ths")
        return ([], source)

    mock.get_all_boards.side_effect = get_all_boards
    mock.get_board_stocks_full.return_value = (
        [{"stock_code": "000001", "stock_name": "S"}],
        "ths",
    )
    monkeypatch.setattr("time.sleep", lambda *_a, **_kw: None)

    report = run_ths_board_backfill(mock, inter_call_sleep_s=0.0)

    assert report.phase2.success == 1
    assert mock.get_board_stocks_full.call_count == 1


def test_error_continues_with_remaining_boards(fresh_db, monkeypatch):
    """A single board's DataFetchError does NOT abort phase 2."""
    boards = [
        {
            "board_code": "885001",
            "name": "OK1",
            "board_type": "concept",
            "subtype": "同花顺概念",
            "ths_cid": "301546",
        },
        {
            "board_code": "885002",
            "name": "FAIL",
            "board_type": "concept",
            "subtype": "同花顺概念",
            "ths_cid": "301547",
        },
        {
            "board_code": "885003",
            "name": "OK2",
            "board_type": "concept",
            "subtype": "同花顺概念",
            "ths_cid": "301548",
        },
    ]
    mock = MagicMock()

    def get_all_boards(source, board_type=None, subtype=None, include_quote=False):
        if source == "ths":
            filtered = [
                b for b in boards if board_type is None or b.get("board_type") == board_type
            ]
            return (filtered, "ths")
        return ([], source)

    mock.get_all_boards.side_effect = get_all_boards

    # Single THS leg post-split — there is no second source to fall back to,
    # so one failing board must not abort the remaining sweep.
    def get_board_stocks_full(board_code, source="ths", *, board_type=None):
        if board_code == "885002":
            raise DataFetchError("upstream timeout")
        return ([{"stock_code": "000001", "stock_name": "S"}], "ths")

    mock.get_board_stocks_full.side_effect = get_board_stocks_full
    monkeypatch.setattr("time.sleep", lambda *_a, **_kw: None)

    report = run_ths_board_backfill(mock, inter_call_sleep_s=0.0)

    assert report.phase2.success == 2
    assert report.phase2.errors == 1
    assert any("885002" in s for s in report.phase2.error_samples)


def test_idempotent_re_run_insert_or_replace(fresh_db, monkeypatch):
    """Re-running produces same row count (INSERT OR REPLACE)."""
    boards = [
        {
            "board_code": "885001",
            "name": "B",
            "board_type": "concept",
            "subtype": "同花顺概念",
            "ths_cid": "301546",
        }
    ]
    mock = MagicMock()

    def get_all_boards(source, board_type=None, subtype=None, include_quote=False):
        if source == "ths":
            filtered = [
                b for b in boards if board_type is None or b.get("board_type") == board_type
            ]
            return (filtered, "ths")
        return ([], source)

    mock.get_all_boards.side_effect = get_all_boards
    mock.get_board_stocks_full.return_value = (
        [{"stock_code": "000001", "stock_name": "S"}],
        "ths",
    )
    monkeypatch.setattr("time.sleep", lambda *_a, **_kw: None)

    run_ths_board_backfill(mock, inter_call_sleep_s=0.0)
    rows_first = board_mod.read_membership(board_code="885001", source="ths")
    assert len(rows_first) == 1

    run_ths_board_backfill(mock, inter_call_sleep_s=0.0)
    rows_second = board_mod.read_membership(board_code="885001", source="ths")
    assert len(rows_second) == 1


def test_rate_limit_enforced_with_token(monkeypatch, fresh_db):
    """3 boards × ≥1.5s jitter floor ⇒ elapsed >= 4.5s.

    ZZSHARE_TOKEN is set here purely to pin that it no longer *shortens*
    the wait (it used to select a 1.2s floor).
    """
    boards = [
        {
            "board_code": f"88500{i}",
            "name": f"B{i}",
            "board_type": "concept",
            "subtype": "同花顺概念",
            "ths_cid": f"30154{i}",
        }
        for i in range(1, 4)
    ]
    mock = MagicMock()

    def get_all_boards(source, board_type=None, subtype=None, include_quote=False):
        if source == "ths":
            filtered = [
                b for b in boards if board_type is None or b.get("board_type") == board_type
            ]
            return (filtered, "ths")
        return ([], source)

    mock.get_all_boards.side_effect = get_all_boards
    mock.get_board_stocks_full.return_value = (
        [{"stock_code": "000001", "stock_name": "S"}],
        "ths",
    )
    monkeypatch.setenv("ZZSHARE_TOKEN", "fake-token")

    t0 = time.monotonic()
    run_ths_board_backfill(mock)
    elapsed = time.monotonic() - t0

    assert elapsed >= 4.4, f"elapsed={elapsed:.2f}s, expected >= 4.4s"


def test_rate_limit_enforced_without_token(monkeypatch, fresh_db):
    """Without ZZSHARE_TOKEN the floor is the same 1.5s ⇒ elapsed >= 3.0s."""
    boards = [
        {
            "board_code": f"88500{i}",
            "name": f"B{i}",
            "board_type": "concept",
            "subtype": "同花顺概念",
            "ths_cid": f"30154{i}",
        }
        for i in range(1, 3)
    ]
    mock = MagicMock()

    def get_all_boards(source, board_type=None, subtype=None, include_quote=False):
        if source == "ths":
            filtered = [
                b for b in boards if board_type is None or b.get("board_type") == board_type
            ]
            return (filtered, "ths")
        return ([], source)

    mock.get_all_boards.side_effect = get_all_boards
    mock.get_board_stocks_full.return_value = (
        [{"stock_code": "000001", "stock_name": "S"}],
        "ths",
    )
    monkeypatch.delenv("ZZSHARE_TOKEN", raising=False)

    t0 = time.monotonic()
    run_ths_board_backfill(mock)
    elapsed = time.monotonic() - t0

    assert elapsed >= 2.9, f"elapsed={elapsed:.2f}s, expected >= 2.9s"


def test_schedule_returns_task_and_sets_app_state(monkeypatch, fresh_db):
    """The async schedule puts a task on app.state.backfill_task."""
    import asyncio

    from fastapi import FastAPI

    from stock_data.data_provider.persistence import backfill

    app = FastAPI()
    app.state.manager = MagicMock()
    app.state.manager.get_all_boards.return_value = ([], "ths")
    app.state.manager.get_board_stocks_full.return_value = ([], "ths")

    async def fake_to_thread(func, *args, **kwargs):
        return func(*args, **kwargs)

    monkeypatch.setattr(backfill.asyncio, "to_thread", fake_to_thread)

    async def _run_and_drain():
        # schedule_* is intentionally sync (NOT async def) — body only calls
        # asyncio.create_task() which needs a running loop, hence the wrapper.
        task = backfill.schedule_ths_board_backfill_on_startup(app)
        await task  # let fake_to_thread run the sync body to completion
        return task

    task = asyncio.run(_run_and_drain())
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
    # Provide boards for phase 1 fetch (success), then make the
    # update_cached_boards step raise — that path is NOT wrapped in
    # try/except, so the exception escapes run_ths_board_backfill.
    app.state.manager.get_all_boards.return_value = (
        [
            {
                "board_code": "885001",
                "name": "B1",
                "board_type": "concept",
                "subtype": "同花顺概念",
                "ths_cid": "301546",
            }
        ],
        "ths",
    )

    def raise_in_phase1(*_a, **_kw):
        raise RuntimeError("simulated sqlite failure in phase 1 write")

    monkeypatch.setattr(backfill, "update_cached_boards", raise_in_phase1)

    async def fake_to_thread(func, *args, **kwargs):
        return func(*args, **kwargs)

    monkeypatch.setattr(backfill.asyncio, "to_thread", fake_to_thread)

    with caplog.at_level(logging.ERROR, logger="stock_data.data_provider.persistence.backfill"):

        async def _run_and_drain():
            # schedule_* is intentionally sync (NOT async def) — see note in
            # the schedule_smoke test above.
            task = backfill.schedule_ths_board_backfill_on_startup(app)
            # We deliberately raised inside the worker to verify
            # done_callback logs it; the await re-raises, but that's
            # expected — the log capture is what we assert on below.
            with contextlib.suppress(RuntimeError):
                await task

        asyncio.run(_run_and_drain())

    # The done_callback fires _on_done which calls logger.exception —
    # message must mention "unhandled" or "raised".
    assert any(
        ("unhandled exception" in r.message or "raised" in r.message) for r in caplog.records
    ), f"expected exception to be logged; got records: {[r.message for r in caplog.records]}"


# ── Fix #2: cooperative cancel via threading.Event ──────────────────────


def test_cancel_event_breaks_phase2_loop(fresh_db, monkeypatch):
    """Setting cancel_event exits phase 2 early."""
    from stock_data.data_provider.persistence.backfill import (
        run_ths_board_backfill,
    )

    boards = [
        {
            "board_code": f"8850{i:02d}",
            "name": f"B{i}",
            "board_type": "concept",
            "subtype": "同花顺概念",
            "ths_cid": f"3015{i:02d}",
        }
        for i in range(1, 51)  # 50 boards — too many to finish naturally
    ]
    mock = MagicMock()

    def get_all_boards(source, board_type=None, subtype=None, include_quote=False):
        if source == "ths":
            filtered = [
                b for b in boards if board_type is None or b.get("board_type") == board_type
            ]
            return (filtered, "ths")
        return ([], source)

    mock.get_all_boards.side_effect = get_all_boards
    mock.get_board_stocks_full.return_value = (
        [{"stock_code": "000001", "stock_name": "S"}],
        "ths",
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
        mock,
        inter_call_sleep_s=0.0,
        cancel_event=cancel_event,
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
        {
            "board_code": f"8850{i:02d}",
            "name": f"B{i}",
            "board_type": "concept",
            "subtype": "同花顺概念",
            "ths_cid": f"3015{i:02d}",
        }
        for i in range(1, 51)
    ]
    mock = MagicMock()

    def get_all_boards(source, board_type=None, subtype=None, include_quote=False):
        if source == "ths":
            filtered = [
                b for b in boards if board_type is None or b.get("board_type") == board_type
            ]
            return (filtered, "ths")
        return ([], source)

    mock.get_all_boards.side_effect = get_all_boards

    def get_board_stocks_full(board_code, source="ths", *, board_type=None):
        # Every board fails — upstream is down.
        raise DataFetchError("upstream timeout")

    mock.get_board_stocks_full.side_effect = get_board_stocks_full
    monkeypatch.setattr("time.sleep", lambda *_a, **_kw: None)

    report = run_ths_board_backfill(mock, inter_call_sleep_s=0.0)

    # Aborted at MAX_CONSECUTIVE_ERRORS (not 50).
    assert report.phase2.errors == MAX_CONSECUTIVE_ERRORS
    assert report.phase2.success == 0


def test_sleep_not_called_on_error_path(fresh_db, monkeypatch):
    """time.sleep is skipped when the board fetch raises.

    Old code put sleep in `finally:` which paid the full rate-limit wait
    even on the error path — wasted ~12s per failed board during a
    sustained outage.
    """
    from stock_data.data_provider.persistence.backfill import (
        run_ths_board_backfill,
    )

    boards = [
        {
            "board_code": "885001",
            "name": "FAIL",
            "board_type": "concept",
            "subtype": "同花顺概念",
            "ths_cid": "301546",
        },
    ]
    mock = MagicMock()

    def get_all_boards(source, board_type=None, subtype=None, include_quote=False):
        if source == "ths":
            return (
                [b for b in boards if b.get("board_type") == board_type],
                "ths",
            )
        return ([], source)

    mock.get_all_boards.side_effect = get_all_boards
    mock.get_board_stocks_full.side_effect = DataFetchError("boom")

    sleep_calls = []
    monkeypatch.setattr(
        "time.sleep",
        lambda s: sleep_calls.append(s),
    )

    run_ths_board_backfill(mock, inter_call_sleep_s=1.5)

    # The only board errored and triggered the consecutive-error abort;
    # no successful iteration means no sleep.
    assert sleep_calls == [], f"sleep was called on error path: {sleep_calls}"


# ── Removed 2026-09-11: per-board zzshare → ths fallback ────────────────
#
# ``test_zzshare_empty_falls_back_to_ths`` and
# ``test_zzshare_raises_falls_back_to_ths`` were deleted together with the
# behavior they pinned. Phase 2 no longer calls
# ``fetch_board_stocks_with_zzshare_fallback``: the board source split
# (2026-09-11, spec §2 D2) made the backfill THS-only, so there is no
# ZZSHARE-primary leg and no cross-source fallback contract left to assert.
