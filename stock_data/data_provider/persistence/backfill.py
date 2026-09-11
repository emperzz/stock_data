"""Async startup backfill for the THS board list + stock→board membership.

Bootstraps ``stock_board`` and ``stock_board_membership`` (for source='ths')
once on lifespan startup so that ``/stocks/{code}/boards`` cache-miss
responses return complete board sets instead of partial ones.

**THS-only since the 2026-09-11 board source split.** Both phases used to
route through helpers that blended zzshare rows into the ``ths`` namespace
(and stamped them ``source='ths'``); those helpers are gone (spec §1.4,
spec §2 D2). Phase 2 now reads the THS F10 page, which server-renders the
full membership without the AJAX endpoint's 50-row cap — so it is both more
complete and single-source.

Reference: docs/superpowers/specs/2026-07-10-ths-board-backfill-on-startup-design.md
"""

from __future__ import annotations

import asyncio
import logging
import random
import sqlite3
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from .board import (
    init_schema,
    update_cached_boards,
    upsert_membership_bulk,
)
from .db import get_db_path

logger = logging.getLogger(__name__)


if TYPE_CHECKING:
    from fastapi import FastAPI


# After this many consecutive phase-2 fetch failures, short-circuit the rest
# of the loop. With ~1.5-3.0s sleep per successful attempt and ~380 boards
# total, 10 consecutive errors is ~30s of wasted startup; beyond that we trust
# the upstream is down and abort to let the server accept requests sooner.
MAX_CONSECUTIVE_ERRORS = 10

# THS q.10jqka.com.cn is the project's weakest link under single-IP
# high-frequency use (CLAUDE.md → Key Design Patterns). The value is
# deliberately the same shape as ``ThsFetcher._THS_PAGING_JITTER_S``
# (ths_fetcher.py:1740) — kept as a local copy rather than an import so this
# module does not gain a fetcher dependency.
THS_BOARD_FETCH_JITTER_S = (1.5, 3.0)


def _auto_rate_limit_s() -> float:
    """Floor of the THS board-page inter-call jitter, in seconds.

    Pre-2026-09-11 this returned 1.2/3.0 based on ``ZZSHARE_TOKEN``, because
    phase 2's primary leg was zzshare's ``plates_stocks``. That leg is gone
    (spec §2 D2); the backfill is now an opt-in THS-only sweep, so the THS
    figure applies. ``ZZSHARE_TOKEN`` is no longer consulted.
    """
    return THS_BOARD_FETCH_JITTER_S[0]


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
    phase1_boards_emitted: int = 0  # boards returned by the THS get_all_boards sweep
    phase2_boards_committed: int = 0  # boards whose membership upsert fired


def run_ths_board_backfill(
    manager,
    *,
    inter_call_sleep_s: float | None = None,
    include_quote: bool = False,
    on_progress: Callable[[str, int, int], None] | None = None,
    cancel_event: threading.Event | None = None,
) -> BackfillReport:
    """Two-phase sync backfill. See spec §3.1.

    ``inter_call_sleep_s`` is the FLOOR of a per-board jitter that runs
    ``[floor, 2×floor)``; passing ``0.0`` disables sleeping entirely (tests
    do this). There is no rate-limit evidence for THS's board pages
    comparable to zzshare's, but this is a one-off opt-in sweep where a
    conservative jitter costs minutes, not hours — so the knob stays.

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

    # Phase 1: stock_board. One THS call per board_type — no merge pass, so
    # no board can arrive without a board_type (the groupby's defensive
    # "skip rows without type" branch is gone with the merge itself).
    t0 = time.time()
    merged_by_type: dict[str, list[dict]] = {}
    try:
        for bt in ("concept", "industry"):
            rows_b, _origin = manager.get_all_boards(
                source="ths",
                board_type=bt,
                subtype=None,
                include_quote=include_quote,
            )
            merged_by_type[bt] = rows_b or []
    except Exception as e:
        report.phase1.errors += 1
        report.phase1.error_samples.append(f"phase1 fetch: {type(e).__name__}: {e}")
        report.phase1.duration_s = time.time() - t0
        logger.exception("[Startup/Backfill] phase 1 fetch raised: %s", e)
        return report

    boards_merged = [r for rows_b in merged_by_type.values() for r in rows_b]
    report.phase1_boards_emitted = len(boards_merged)
    if not boards_merged:
        report.phase1.duration_s = time.time() - t0
        logger.warning("[Startup/Backfill] phase 1 returned 0 boards; skipping phase 2")
        return report

    for bt, bucket in merged_by_type.items():
        if bucket:
            report.phase1.success += update_cached_boards(bt, "ths", bucket)
    report.phase1.duration_s = time.time() - t0
    logger.info(
        "[Startup/Backfill] phase 1 wrote %d boards in %.1fs",
        report.phase1.success,
        report.phase1.duration_s,
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
                    idx,
                    total_p2,
                )
                break

            board_code = board.get("board_code")
            if not board_code:
                logger.debug(
                    "[Startup/Backfill] skipping board %r (no board_code)",
                    board.get("name"),
                )
                continue

            try:
                # Single THS leg: the F10 page carries the full membership
                # with no 50-row cap, and it is addressed by the public
                # platecode (no cid translation). Pre-split this called
                # fetch_board_stocks_with_zzshare_fallback, which for
                # include_quote=False preferred ZZSHARE and then wrote the
                # result under source='ths' — the mislabelling at spec §1.4.
                rows, _source_label = manager.get_board_stocks_full(
                    board_code=board_code,
                    source="ths",
                    board_type=board.get("board_type"),
                )
            except Exception as e:
                report.phase2.errors += 1
                report.phase2.consecutive_errors += 1
                if len(report.phase2.error_samples) < 20:
                    report.phase2.error_samples.append(f"{board_code}: {type(e).__name__}: {e}")
                logger.warning(
                    "[Startup/Backfill] phase 2 board %s failed: %s",
                    board_code,
                    e,
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
                        board_code=board_code,
                        board_name=board.get("name", ""),
                        board_type=board.get("board_type", ""),
                        subtype=board.get("subtype") or "",
                        conn=self_conn,
                    )
                    report.phase2.success += 1
                    report.phase2_boards_committed += 1
                # Reset consecutive-error counter on any successful response
                # (including empty — at least the upstream responded).
                report.phase2.consecutive_errors = 0
                # Jitter, not a fixed delay: [floor, 2×floor). `0.0` stays a
                # no-op (uniform(0, 0) == 0), so every
                # `inter_call_sleep_s=0.0` test call site is unaffected.
                time.sleep(random.uniform(inter_call_sleep_s, inter_call_sleep_s * 2))

            # Progress every 50 boards
            done = idx + 1
            if done % 50 == 0 and on_progress:
                on_progress("ths", done, total_p2)
            if done % 50 == 0:
                logger.info(
                    "[Startup/Backfill] phase 2 progress=%d/%d errors=%d elapsed=%.0fs",
                    done,
                    total_p2,
                    report.phase2.errors,
                    time.time() - t1,
                )
    finally:
        self_conn.close()

    report.phase2.duration_s = time.time() - t1
    logger.info(
        "[Startup/Backfill] phase 2 wrote %d boards (%d errors) in %.1fs",
        report.phase2.success,
        report.phase2.errors,
        report.phase2.duration_s,
    )
    return report


def schedule_ths_board_backfill_on_startup(app: FastAPI) -> asyncio.Task:
    """Spawn the backfill in a worker thread; return the task for caller.

    The caller (``server.py:lifespan``) stores the returned task on
    ``app.state.backfill_task`` for shutdown coordination. Sync work runs
    in ``asyncio.to_thread`` so the event loop is not blocked by the ~17
    minute wall-clock budget of fetcher sleeps.

    Note: NOT ``async def`` — the body only builds a sync ``threading.Event``
    and calls the sync ``asyncio.create_task()``. Declaring it ``async def``
    would return a coroutine that the caller must ``await``; ``server.py``
    calls it without ``await`` from inside the lifespan asyncgen, and a
    missed ``await`` silently swallows the whole startup backfill
    (``RuntimeWarning: coroutine ... was never awaited``).

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
