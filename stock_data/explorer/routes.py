"""Control endpoints for the API Explorer (/control/*).

Exposes server config, server status, and the API manifest. Bound to
127.0.0.1 only — never expose on 0.0.0.0.
"""

from __future__ import annotations

import os
import time
from datetime import datetime, timezone

from fastapi import APIRouter, Request

from .. import __version__
from .manifest import build_manifest

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
        """Static config used by external tools (smoke tests, AI agents).

        The HTML explorer derives baseUrl from location.origin, so it does
        not consume this endpoint.
        """
        return {
            "port": _read_server_port(),
            "host": _read_server_host(),
            "version": __version__,
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

    @router.get("/api-manifest")
    def control_api_manifest(request: Request) -> dict:
        """The /explorer/ HTML fetches this on load.

        返回 build_manifest(request.app) 的结果,加 generated_at 时间戳。
        不缓存(每次重新反射),保证"加 endpoint 不重启不生效"成为陷阱
        不存在——重启 server 才会触发新 route 注册,这是预期。
        """
        manifest = build_manifest(request.app)
        manifest["meta"]["generated_at"] = datetime.now(timezone.utc).isoformat()
        return manifest

    return router
