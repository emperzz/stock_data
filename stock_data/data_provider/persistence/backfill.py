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
    phase1_boards_emitted: int = 0
    phase2_boards_committed: int = 0


# Stub implementations: filled in by later tasks
def run_ths_board_backfill(
    manager,
    *,
    inter_call_sleep_s: float | None = None,
    include_quote: bool = False,
    on_progress=None,
):
    raise NotImplementedError


async def schedule_ths_board_backfill_on_startup(app: FastAPI) -> asyncio.Task:
    raise NotImplementedError
