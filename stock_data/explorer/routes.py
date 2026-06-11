"""Control endpoints for the API Explorer (/control/*).

Exposes server config, server status, and Test Instance subprocess
management. Bound to 127.0.0.1 only — never expose on 0.0.0.0.
"""

from __future__ import annotations

import os
import time

from fastapi import APIRouter

from .. import __version__
from . import control as _control

_CONTROL_STARTED_AT = time.time()


def _read_server_port() -> int:
    try:
        return int(os.getenv("SERVER_PORT", "8888"))
    except ValueError:
        return 8888


def _read_server_host() -> str:
    return os.getenv("SERVER_HOST", "127.0.0.1")


def build_control_router() -> APIRouter:
    """Build the /control/* APIRouter. Called once by explorer.mount()."""
    router = APIRouter(prefix="/control", tags=["control"])

    @router.get("/config")
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

    @router.get("/server/status")
    def control_server_status() -> dict:
        """Status of the main server (the one serving the HTML)."""
        return {
            "running": True,
            "pid": os.getpid(),
            "port": _read_server_port(),
            "uptime_sec": int(time.time() - _CONTROL_STARTED_AT),
        }

    @router.get("/test-instance/status")
    def control_test_instance_status() -> dict:
        """Status of the optional Test Instance subprocess."""
        status = _control.get_test_instance_status()
        port = int(os.getenv("STOCK_TEST_INSTANCE_PORT",
                             str(_read_server_port() + 1)))
        return {**status, "port": port}

    @router.post("/test-instance/start")
    def control_test_instance_start() -> dict:
        """Start the Test Instance subprocess. Idempotent."""
        port = int(os.getenv("STOCK_TEST_INSTANCE_PORT",
                             str(_read_server_port() + 1)))
        host = _read_server_host()
        return _control.start_test_instance(port=port, host=host, wait_seconds=1.0)

    @router.post("/test-instance/stop")
    def control_test_instance_stop() -> dict:
        """Stop the Test Instance subprocess. Idempotent."""
        return _control.stop_test_instance()

    return router
