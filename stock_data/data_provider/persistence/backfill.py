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
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Callable

from fastapi import FastAPI

from .board import (
    fetch_boards_with_zzshare_backfill,
    init_schema,
    update_cached_boards,
)

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
    """Two-phase sync backfill. See spec §3.1."""
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

    return report


async def schedule_ths_board_backfill_on_startup(app: FastAPI) -> asyncio.Task:
    raise NotImplementedError
