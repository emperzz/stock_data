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
from pathlib import Path

from dotenv import load_dotenv
from fastapi import APIRouter, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

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
# Mount docs/ as static resources. /docs/API.html is the interactive explorer.
# Failure mode: if docs/ is missing, log a warning and continue without the
# mount — the data API still works.
try:
    _DOCS_DIR = Path(__file__).resolve().parent.parent / "docs"
    if _DOCS_DIR.is_dir():
        app.mount("/docs", StaticFiles(directory=str(_DOCS_DIR), html=True), name="docs")
        logger.info(f"[Startup] Mounted /docs → {_DOCS_DIR}")
    else:
        logger.warning(f"[Startup] docs/ not found at {_DOCS_DIR}, /docs not mounted")
except Exception as e:
    logger.warning(f"[Startup] Failed to mount /docs: {e}")


# --- /control/* endpoints (new) -----------------------------------------
# Bound to 127.0.0.1 — never expose on 0.0.0.0. The control router gives the
# HTML explorer the ability to read config, query status, and start/stop
# an independent Test Instance subprocess.
import time as _time  # for uptime tracking  # noqa: E402

from . import control as _control  # noqa: E402

_CONTROL_STARTED_AT = _time.time()


def _read_server_port() -> int:
    try:
        return int(os.getenv("SERVER_PORT", "8888"))
    except ValueError:
        return 8888


def _read_server_host() -> str:
    return os.getenv("SERVER_HOST", "127.0.0.1")


_control_router = APIRouter(prefix="/control", tags=["control"])


@_control_router.get("/config")
def control_config() -> dict:
    """Static config used by the HTML explorer to initialize itself."""
    port = _read_server_port()
    test_port = int(os.getenv("STOCK_TEST_INSTANCE_PORT", str(port + 1)))
    return {
        "port": port,
        "host": _read_server_host(),
        "test_port": test_port,
        "version": __version__,
        "env_keys": [
            "TUSHARE_TOKEN", "BAOSTOCK_PRIORITY", "AKSHARE_PRIORITY",
            "YFINANCE_PRIORITY", "ZHITU_TOKEN", "ZHITU_PRIORITY",
            "MYQUANT_TOKEN", "MYQUANT_PRIORITY", "TENCENT_PRIORITY",
            "EASTMONEY_PRIORITY", "THS_PRIORITY", "CNINFO_PRIORITY",
            "ENABLE_API_CACHE", "STOCK_CACHE_DB_PATH", "STOCK_DB_INIT",
        ],
    }


@_control_router.get("/server/status")
def control_server_status() -> dict:
    """Status of the main server (the one serving the HTML)."""
    return {
        "running": True,
        "pid": os.getpid(),
        "port": _read_server_port(),
        "uptime_sec": int(_time.time() - _CONTROL_STARTED_AT),
    }


@_control_router.get("/test-instance/status")
def control_test_instance_status() -> dict:
    """Status of the optional Test Instance subprocess."""
    status = _control.get_test_instance_status()
    # Include the configured test port so the UI can show it
    port = int(os.getenv("STOCK_TEST_INSTANCE_PORT",
                         str(_read_server_port() + 1)))
    return {**status, "port": port}


@_control_router.post("/test-instance/start")
def control_test_instance_start() -> dict:
    """Start the Test Instance subprocess. Idempotent."""
    port = int(os.getenv("STOCK_TEST_INSTANCE_PORT",
                         str(_read_server_port() + 1)))
    host = _read_server_host()
    return _control.start_test_instance(port=port, host=host, wait_seconds=1.0)


@_control_router.post("/test-instance/stop")
def control_test_instance_stop() -> dict:
    """Stop the Test Instance subprocess. Idempotent."""
    return _control.stop_test_instance()


app.include_router(_control_router)


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
