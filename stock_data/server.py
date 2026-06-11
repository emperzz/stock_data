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

import logging
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from . import __version__
from .api.routes import router

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
    else:
        persistence.init_schema()
        logger.info("[Startup] Persistence schema ensured (STOCK_DB_INIT=false)")

    # ----- Trade-calendar warm-up (non-fatal) -----
    # The /pools endpoint needs is_trade_date() and
    # get_latest_trade_date_on_or_before() to work, and both depend on the
    # trade_calendar table being populated. If it's empty on startup, kick
    # off a one-shot fetch. Failure here is non-fatal: the /calendar
    # endpoint will retry on first access.
    from .data_provider.persistence import trade_calendar
    if not trade_calendar.get_cached_calendar():
        logger.info("[Startup] Trade calendar empty, fetching from upstream")
        try:
            # Import lazily to avoid pulling in fetchers at module-import time
            from .api.routes import get_manager
            get_manager().get_trade_calendar()
        except Exception as e:
            logger.warning(f"[Startup] Trade calendar warm-up failed (non-fatal): {e}")

    yield
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
)

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

# Data routes (unchanged)
app.include_router(router, prefix="/api/v1")

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
