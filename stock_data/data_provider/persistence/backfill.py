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
import sqlite3
import threading
import time
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass, field

from fastapi import FastAPI

from .board import (
    fetch_board_stocks_with_zzshare_fallback,
    fetch_boards_with_zzshare_backfill,
    init_schema,
    update_cached_boards,
    upsert_membership_bulk,
)
from .db import get_db_path

logger = logging.getLogger(__name__)


# After this many consecutive phase-2 fetch failures, short-circuit the rest
# of the loop. With ~1.2-3.0s sleep per failed attempt and ~380 boards total,
# 10 consecutive errors is ~30s of wasted startup; beyond that we trust the
# upstream is down and abort to let the server accept requests sooner.
MAX_CONSECUTIVE_ERRORS = 10


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
    consecutive_errors: int = 0  # running count; reset on every success
    error_samples: list[str] = field(default_factory=list)


@dataclass
class BackfillReport:
    phase1: PhaseStats = field(default_factory=PhaseStats)
    phase2: PhaseStats = field(default_factory=PhaseStats)
    phase1_boards_emitted: int = 0     # boards returned by fetch_boards_with_zzshare_backfill
    phase2_boards_committed: int = 0   # boards whose membership upsert fired


def run_ths_board_backfill(
    manager,
    *,
    inter_call_sleep_s: float | None = None,
    include_quote: bool = False,
    on_progress: Callable[[str, int, int], None] | None = None,
    cancel_event: threading.Event | None = None,
) -> BackfillReport:
    """Two-phase sync backfill. See spec §3.1.

    Args:
        cancel_event: optional ``threading.Event`` checked between boards.
            When set, the worker exits phase 2 early (before the next fetch).
            Sync code running in ``asyncio.to_thread`` cannot be cancelled by
            ``Task.cancel()``; the caller signals cooperative cancel via this
            event from the asyncio event loop.
    """
    if inter_call_sleep_s is None:
        inter_call_sleep_s = _auto_rate_limit_s()

    report = BackfillReport()
    init_schema()  # idempotent

    # Phase 1: stock_board
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

    # Defensive: skip boards missing 'type' instead of KeyError-ing the loop.
    # A missing 'type' would otherwise escape run_ths_board_backfill and fail
    # the inner asyncio.Task silently (no logger.exception without a
    # done_callback — see schedule_ths_board_backfill_on_startup).
    grouped: dict[str, list[dict]] = defaultdict(list)
    for b in boards_merged:
        bt = b.get("type")
        if not bt:
            logger.debug(
                "[Startup/Backfill] skipping board %s in phase 1 groupby (no 'type' field)",
                b.get("code"),
            )
            continue
        grouped[bt].append(b)

    for bt, bucket in grouped.items():
        if bt in ("concept", "industry"):
            report.phase1.success += update_cached_boards(bt, "ths", bucket)
    report.phase1.duration_s = time.time() - t0
    logger.info(
        "[Startup/Backfill] phase 1 wrote %d boards in %.1fs",
        report.phase1.success, report.phase1.duration_s,
    )

    # ── Phase 2: stock_board_membership ──────────────────────────────
    t1 = time.time()
    self_conn = sqlite3.connect(str(get_db_path()), timeout=30)
    try:
        try:
            self_conn.execute("PRAGMA journal_mode=WAL")
        except sqlite3.OperationalError as exc:
            if "locked" not in str(exc):
                raise
            logger.debug("[Startup/Backfill] WAL pragma busy: %r", exc)

        total_p2 = len(boards_merged)
        for idx, board in enumerate(boards_merged):
            # Cooperative cancel: checked between boards. asyncio.to_thread
            # runs sync code in a worker thread; Task.cancel() cannot
            # interrupt it. The shutdown hook sets cancel_event to signal
            # early exit so the worker stops before its current iteration
            # finishes.
            if cancel_event is not None and cancel_event.is_set():
                logger.info(
                    "[Startup/Backfill] phase 2 cancelled at board %d/%d (cooperative)",
                    idx, total_p2,
                )
                break

            platecode = board.get("platecode")
            if not platecode:
                logger.debug(
                    "[Startup/Backfill] skipping board %s (no platecode)",
                    board.get("code"),
                )
                continue

            try:
                # Use the route-layer helper so a single zzshare failure OR
                # empty response falls back to ths per-board — matches the
                # /boards/{code}/stocks behavior so cache completeness
                # mirrors what users see.
                rows, _source_label, _effective_source, _reason = (
                    fetch_board_stocks_with_zzshare_fallback(
                        board_code=platecode,
                        source="ths",
                        include_quote=False,
                        manager=manager,
                    )
                )
            except Exception as e:
                report.phase2.errors += 1
                report.phase2.consecutive_errors += 1
                if len(report.phase2.error_samples) < 20:
                    report.phase2.error_samples.append(
                        f"{platecode}: {type(e).__name__}: {e}")
                logger.warning(
                    "[Startup/Backfill] phase 2 board %s failed: %s",
                    platecode, e,
                )
                # Short-circuit on sustained outage — the upstream is down,
                # no point burning the remaining startup window sleeping
                # between failed calls.
                if report.phase2.consecutive_errors >= MAX_CONSECUTIVE_ERRORS:
                    logger.error(
                        "[Startup/Backfill] aborting phase 2: %d consecutive "
                        "errors (upstream appears down). Skipping remaining "
                        "%d boards.",
                        report.phase2.consecutive_errors,
                        total_p2 - (idx + 1),
                    )
                    break
                # No sleep on error path — failed fetches don't deserve the
                # full rate-limit wait. The next iteration will retry.
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
                # Reset consecutive-error counter on any successful response
                # (including empty — at least the upstream responded).
                report.phase2.consecutive_errors = 0
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


async def schedule_ths_board_backfill_on_startup(app: FastAPI) -> asyncio.Task:
    """Spawn the backfill in a worker thread; return the task for caller.

    The caller (``server.py:lifespan``) stores the returned task on
    ``app.state.backfill_task`` for shutdown coordination. Sync work runs
    in ``asyncio.to_thread`` so the event loop is not blocked by ~17min of
    fetcher sleeps.

    Two startup-bug fixes live here:

    * **Silent task failure.** Any unhandled exception in the worker
      (e.g. ``sqlite3.OperationalError`` on a read-only FS, KeyError on a
      malformed board row, an exception in ``update_cached_boards`` that
      escapes the per-board try/except) would previously fail the inner
      task silently — asyncio logs only "Task exception was never
      retrieved" to stderr and the operator never sees the real failure.
      We attach a ``done_callback`` that logs the exception via
      ``logger.exception``.

    * **Cancellation reaches the worker.** ``Task.cancel()`` only cancels
      the asyncio wrapper around ``to_thread``; the sync worker thread
      keeps executing until the current iteration's ``time.sleep``
      finishes. We create a ``threading.Event`` (``app.state.backfill_cancel``)
      that the worker checks between boards. ``server.py`` sets this event
      before awaiting the task on shutdown, so the worker exits within at
      most one iteration of the cancel signal.
    """
    cancel_event = threading.Event()
    app.state.backfill_cancel = cancel_event

    task = asyncio.create_task(
        asyncio.to_thread(
            run_ths_board_backfill,
            app.state.manager,
            cancel_event=cancel_event,
        )
    )
    app.state.backfill_task = task

    def _on_done(t: asyncio.Task) -> None:
        if t.cancelled():
            logger.info("[Shutdown] THS board backfill task cancelled")
            return
        exc = t.exception()
        if exc is not None:
            logger.exception(
                "[Startup/Backfill] task raised unhandled exception: %s",
                exc,
            )

    task.add_done_callback(_on_done)
    return task
