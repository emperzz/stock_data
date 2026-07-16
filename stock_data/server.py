"""
Stock Data Server - FastAPI entry point.

Usage:
    python -m stock_data.server

Or with uvicorn directly:
    uvicorn stock_data.server:app --host 0.0.0.0 --port 8888
"""

# Must be set BEFORE any import that transitively loads gm.api / protobuf.
# gm 3.x is incompatible with protobuf's C++ descriptor parser; the pure-Python
# parser is the only working path. Tests set this in conftest.py; the server
# entry point must do the same.
import os

os.environ.setdefault("PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION", "python")

import asyncio
import logging
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from . import __version__
from .api.routes import health_router, news_router, router
from .api.routes.cls import cls_router


class _UTF8JSONResponse(JSONResponse):
    """JSON response that advertises ``charset=utf-8`` explicitly.

    Starlette's default ``JSONResponse`` ships ``Content-Type: application/json``
    with no charset. RFC 8259 says JSON *is* UTF-8, but HTTP/1.1 §3.7.1 still
    tells well-behaved clients to default ``text/*`` (and many treat
    ``application/json`` the same) to ISO-8859-1 when the charset is missing.
    Browsers and curl running on Windows then mis-decode Chinese payloads
    (财联社早报 title, news flash text, ...) as the classic
    UTF-8→Latin-1 mojibake ("ãç¦ç¹..."). Announcing the charset fixes the
    client side without touching the actual response bytes (they were already
    correct UTF-8 — the fetcher never had a bug).
    """

    media_type = "application/json; charset=utf-8"

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan handler."""
    import time as _time

    app.state.started_at = _time.time()
    logger.info(f"Starting Stock Data Server v{__version__}")
    logger.info(f"Server port: {os.getenv('SERVER_PORT', '8888')}")

    # ----- Persistence layer startup -----
    # STOCK_DB_INIT=true  → DROP + recreate every persistence table (full reset).
    # STOCK_DB_INIT=false → idempotent CREATE IF NOT EXISTS only.
    # Any other value is treated as false (lenient parsing; no startup failure).
    from .data_provider import persistence

    db_init = os.getenv("STOCK_DB_INIT", "false").lower() == "true"
    if db_init:
        logger.warning(
            "[Startup] STOCK_DB_INIT=true — DROPPING and recreating ALL persistence "
            "tables. All previously cached metadata will be lost."
        )
        persistence.reset_all()

        # ----- CSV seed from stock_data_backup/ (opt-out via missing files) -----
        # When STOCK_DB_INIT=true, after reset_all() the tables are empty. Re-seed
        # from the repo-managed CSV backups so the server has data immediately,
        # without paying the ~17min upstream backfill cost. If
        # BOARD_BACKFILL_ON_STARTUP=true also fires below, the upstream refresh
        # will overwrite the CSV data shortly after.
        from pathlib import Path

        backup_dir = Path(__file__).parent / "stock_data_backup"
        # Outer try/except: per-file errors are caught inside
        # seed_all_from_backup_dir (logged + skipped), but an unexpected
        # exception (e.g. NoneType, MemoryError on a giant CSV) would
        # otherwise crash lifespan and leave the DB in a reset+partial
        # state. Server should boot with empty cache rather than not at all.
        seed_results: dict = {}
        try:
            seed_results = persistence.seed_all_from_backup_dir(backup_dir)
        except Exception:
            logger.exception(
                "[Startup] CSV seed crashed mid-iteration; DB is in "
                "reset+partial state. Server continuing with partial or "
                "empty board cache — set BOARD_BACKFILL_ON_STARTUP=true or "
                "restore stock_data_backup/*.csv to recover."
            )
        if seed_results:
            logger.info("[Startup] CSV seed complete: %s", seed_results)
        elif backup_dir.exists() and any(backup_dir.glob("*.csv")):
            # CSVs present but seed produced {} — seed_all_from_backup_dir
            # already logged a summary ERROR ("All N CSV file(s) failed").
            # Avoid the misleading "no files in ..." message here.
            logger.error(
                "[Startup] CSV seed produced 0 rows; check ERROR logs above for details."
            )
        else:
            logger.info("[Startup] CSV seed skipped (no files in %s)", backup_dir)
    else:
        persistence.init_schema()
        logger.info("[Startup] Persistence schema ensured (STOCK_DB_INIT=false)")

    # ----- Trade-calendar warm-up (non-fatal) -----
    # The /zt-pools endpoint needs is_trade_date() and
    # get_latest_trade_date_on_or_before() to work, and both depend on the
    # trade_calendar table being populated. If it's empty on startup, kick
    # off a one-shot fetch. Failure here is non-fatal: the /calendar
    # endpoint will retry on first access.
    from .api.routes import get_manager as _get_manager
    from .data_provider.persistence import trade_calendar

    cached_dates, _ = trade_calendar.get_cached_calendar()
    if not cached_dates:
        logger.info("[Startup] Trade calendar empty, fetching from upstream")
        try:
            _get_manager().get_trade_calendar()
        except Exception as e:
            logger.warning(f"[Startup] Trade calendar warm-up failed (non-fatal): {e}")

    # ----- Expose manager via app.state for the explorer manifest builder -----
    # The manifest needs to enumerate fetchers per (market, capability).
    # Using app.state avoids importing the global get_manager() into manifest.py,
    # which would make manifest.py harder to unit-test (couldn't inject a mock).
    app.state.manager = _get_manager()
    logger.info("[Startup] app.state.manager wired for explorer manifest")

    # ----- THS board backfill on startup (opt-in via env) -----
    # Inside function body (not module top) — only imported when env=true.
    # Keeps cold-start path zero extra imports. schedule_*_on_startup itself
    # wraps the worker in asyncio.create_task and stores the task ref on
    # app.state.backfill_task; the shutdown hook below awaits it.
    if os.getenv("BOARD_BACKFILL_ON_STARTUP", "false").lower() == "true":
        from .data_provider.persistence.backfill import (
            schedule_ths_board_backfill_on_startup,
        )

        schedule_ths_board_backfill_on_startup(app)
        logger.info("[Startup] THS board backfill scheduled (BOARD_BACKFILL_ON_STARTUP=true)")
    else:
        logger.info(
            "[Startup] THS board backfill skipped (set BOARD_BACKFILL_ON_STARTUP=true to enable)"
        )

    yield

    # ----- Cancel in-flight backfill so Ctrl-C / SIGTERM doesn't leak state -----
    # Two-step cancel: (1) flip the cooperative cancel event the worker
    # checks between boards so the sync loop exits within at most one
    # iteration; (2) await the task so the asyncio.Task transitions to done
    # and the done_callback logs any exception. Task.cancel() alone won't
    # interrupt the asyncio.to_thread worker — sync code can't observe
    # CancelledError — so the event is what actually stops the worker.
    backfill_cancel = getattr(app.state, "backfill_cancel", None)
    if backfill_cancel is not None:
        backfill_cancel.set()

    backfill_task = getattr(app.state, "backfill_task", None)
    if backfill_task is not None and not backfill_task.done():
        try:
            await backfill_task
        except (asyncio.CancelledError, Exception) as e:
            logger.info(f"[Shutdown] THS board backfill task ended ({type(e).__name__})")
    if hasattr(app.state, "backfill_task"):
        del app.state.backfill_task
    if hasattr(app.state, "backfill_cancel"):
        del app.state.backfill_cancel

    logger.info("Shutting down Stock Data Server")


# Create FastAPI app
app = FastAPI(
    title="Stock Data API",
    description="Local stock data aggregation server for AI agents",
    version=__version__,
    lifespan=lifespan,
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
    # Announce charset=utf-8 on every JSON response (see _UTF8JSONResponse
    # docstring for the mojibake rationale). Affects API + /control/* +
    # /explorer/* JSON responses; legacy `application/json` (no charset)
    # behavior is still produced for explicit `JSONResponse(...)` usages
    # inside the app.
    default_response_class=_UTF8JSONResponse,
)


# FastAPI's built-in RequestValidationError handler returns its own
# ``application/json`` (no charset) and bypasses `default_response_class`,
# which leaks the mojibake-prone Content-Type on every 422. Override it with
# the same UTF-8 class so the charset contract is universal. The body shape
# ({"detail": [...]}) matches FastAPI's default exactly — clients that
# already parse 422 bodies continue to work.
@app.exception_handler(RequestValidationError)
async def _validation_exception_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    return _UTF8JSONResponse(status_code=422, content={"detail": exc.errors()})


# FastAPI's default ``HTTPException`` handler also bypasses the
# default-response-class charset hint, so 4xx/5xx responses raised via
# ``raise HTTPException(...)`` (404 from ``map_errors``, 503 from upstream
# ``DataFetchError`` mappings, 400 from validation in route handlers) leak
# the same mojibake-prone ``application/json`` without ``charset=utf-8``.
# Map it to ``_UTF8JSONResponse`` so error bodies — which frequently contain
# Chinese strings (e.g. "No 财联社早报 article for ...") — round-trip cleanly.
# Body shape ``{"detail": <exc.detail>}`` matches Starlette's default.
@app.exception_handler(StarletteHTTPException)
async def _http_exception_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    return _UTF8JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})


# CORS — restrict to localhost only (unchanged)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost",
        "http://localhost:*",
        "http://127.0.0.1",
        "http://127.0.0.1:*",
    ],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Data routes (versioned under /api/v1)
app.include_router(router, prefix="/api/v1")
app.include_router(cls_router, prefix="/api/v1")

# News endpoints (also versioned under /api/v1 — the router's own paths start
# with `/news/...`, so the final URL is `/api/v1/news/...`).
app.include_router(news_router, prefix="/api/v1")

# Health check (mounted at root, k8s/lb convention — `/healthz`).
app.include_router(health_router)

# --- API Explorer (new) -------------------------------------------------
# stock_data/explorer/ subpackage owns the /explorer/ static UI and the
# /control/* management endpoints. See stock_data/explorer/__init__.py.
from .explorer import mount as mount_explorer  # noqa: E402

mount_explorer(app)


# --- main() — change default host ---------------------------------------
def main():
    """Run the server."""
    import uvicorn

    port = int(os.getenv("SERVER_PORT", "8888"))
    # Default host changed from 0.0.0.0 to 127.0.0.1 — /control/* endpoints
    # must not be exposed on a public interface. Set SERVER_HOST=0.0.0.0
    # explicitly if you need remote access.
    host = os.getenv("SERVER_HOST", "127.0.0.1")

    logger.info(f"Starting server on {host}:{port}")
    uvicorn.run(
        "stock_data.server:app",
        host=host,
        port=port,
        reload=False,
    )


if __name__ == "__main__":
    main()
