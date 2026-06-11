"""API Explorer subpackage: interactive HTML UI at /explorer/ and /control/* endpoints.

Mounts the static HTML frontend at /explorer/ and the Test Instance
management endpoints at /control/*. Used by stock_data.server via
the single-line mount(app) entry point.
"""

from __future__ import annotations

import logging
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from .routes import build_control_router

logger = logging.getLogger(__name__)


def mount(app: FastAPI) -> None:
    """Mount the API Explorer static UI at /explorer/ and /control/* endpoints.

    Failure mode: if static/ is missing, log a warning and skip the static
    mount, but still register /control/* routes (they don't need the HTML).

    Reentrancy: NOT protected. FastAPI's app.mount() raises RuntimeError on
    duplicate mount, which is sufficient. Call exactly once per FastAPI app.
    """
    # Static mount (failure → warn + continue, data API still works)
    try:
        static_dir = Path(__file__).resolve().parent / "static"
        if static_dir.is_dir():
            app.mount(
                "/explorer",
                StaticFiles(directory=str(static_dir), html=True),
                name="explorer",
            )
            logger.info(f"[Explorer] Mounted /explorer → {static_dir}")
        else:
            logger.warning(
                f"[Explorer] static/ not found at {static_dir}, /explorer not mounted"
            )
    except Exception as e:
        logger.warning(f"[Explorer] Failed to mount /explorer: {e}")

    # Control router (any failure here is fatal — re-raise to abort server startup)
    app.include_router(build_control_router())
    logger.info("[Explorer] Mounted /control/* (5 endpoints)")
