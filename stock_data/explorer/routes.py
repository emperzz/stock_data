"""Control endpoints for the API Explorer (/control/*).

Exposes server config, server status, and the API manifest. Bound to
127.0.0.1 only — never expose on 0.0.0.0.
"""

from __future__ import annotations

import os
import time
import traceback as _traceback
from datetime import datetime, timezone

from fastapi import APIRouter, Body, Request
from pydantic import BaseModel, Field

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


def _json_safe(value):
    """Best-effort JSON-safe coercion for fetcher return values."""
    import pandas as pd
    if isinstance(value, pd.DataFrame):
        return value.to_dict(orient="records")
    if hasattr(value, "to_dict"):
        try:
            return value.to_dict()
        except Exception:
            pass
    if isinstance(value, (list, tuple)):
        return [_json_safe(v) for v in value]
    if isinstance(value, dict):
        return {k: _json_safe(v) for k, v in value.items()}
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return repr(value)


class FetcherTestRequest(BaseModel):
    """Body schema for POST /control/fetcher-test.

    Defined at MODULE level (not inside build_control_router) because
    Pydantic v2 + FastAPI 0.136 can't resolve ForwardRefs for closure-
    scoped models. See test_fetcher_test_endpoint.py for the contract.
    """
    fetcher: str = Field(..., description="Fetcher name (e.g. 'baostock')")
    method: str = Field(..., description="Method name on the fetcher")
    kwargs: dict = Field(default_factory=dict, description="kwargs unpacked into the method call")


def _instantiate_unregistered_fetcher(fetcher_name: str):
    """Instantiate a fetcher class by name even if the manager skipped it.

    The explorer manifest surfaces ALL `BaseFetcher` subclasses that declare
    the capability (so users see the full failover chain), including ones
    the manager skipped at registration because ``is_available()`` returned
    False (e.g. ZhituFetcher when ZHITU_TOKEN is unset). When the user clicks
    Test on such a row, we still want the existing graceful
    ``FetcherUnavailable`` error path to fire — so instantiate the class on
    demand and let line 158's availability check reject it.

    Returns None if no class matches the name (caller should still respond
    with ``UnknownFetcher``).
    """
    from ..data_provider.base import BaseFetcher

    stack: list[type] = list(BaseFetcher.__subclasses__())
    while stack:
        cls = stack.pop()
        if getattr(cls, "name", None) == fetcher_name:
            try:
                return cls()
            except Exception:
                return None
        stack.extend(cls.__subclasses__())
    return None


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

    @router.post("/fetcher-test")
    def control_fetcher_test(
        request: Request,
        req: FetcherTestRequest = Body(...),
    ) -> dict:
        """Invoke a single fetcher method directly, bypassing manager failover.

        Always returns HTTP 200; success/failure is encoded in the body's
        `ok` field. Errors are classified into UnknownFetcher / UnknownMethod /
        FetcherUnavailable / TypeError / <ExceptionClassName>; each carries
        a traceback for debugging (127.0.0.1-only endpoint, no leak risk).
        """
        manager = request.app.state.manager
        # Whitelist comes from the live manifest's fetchers[*].method union
        # (CAPABILITY_TO_METHOD values + endpoint-declared overrides).
        manifest = build_manifest(request.app)
        allowed_methods = {
            f["method"]
            for sec in manifest["sections"]
            for ep in sec["endpoints"]
            for f in ep["fetchers"]
        }

        def _err(type_: str, message: str, *, with_tb: bool = False, elapsed_ms: int = 0) -> dict:
            return {
                "ok": False,
                "fetcher": req.fetcher,
                "method": req.method,
                "elapsed_ms": elapsed_ms,
                "result": None,
                "error": {
                    "type": type_,
                    "message": message,
                    "traceback": _traceback.format_exc() if with_tb else "",
                },
            }

        # 1. Unknown fetcher
        fetcher = manager.get_fetcher(req.fetcher)
        if fetcher is None:
            # The manifest now surfaces unregistered fetchers too (with
            # available: false), so the user may legitimately Test a class
            # the manager didn't register — try to instantiate on demand so
            # the same `FetcherUnavailable` path fires instead of misleading
            # "no fetcher named X; loaded: [...]".
            fetcher = _instantiate_unregistered_fetcher(req.fetcher)
            if fetcher is None:
                loaded = sorted(f.name for f in manager._fetchers)
                return _err(
                    "UnknownFetcher",
                    f"no fetcher named '{req.fetcher}'; loaded: {loaded}",
                )

        # 2. Unknown method (not in whitelist)
        if req.method not in allowed_methods:
            return _err(
                "UnknownMethod",
                f"method '{req.method}' not allowed; allowed: {sorted(allowed_methods)}",
            )

        # 3. Fetcher unavailable
        if hasattr(fetcher, "is_available") and not fetcher.is_available():
            return _err(
                "FetcherUnavailable",
                f"{req.fetcher}.is_available() returned False (check token / SDK install)",
            )

        # 4. Lookup the method on the fetcher
        method = getattr(fetcher, req.method, None)
        if method is None or not callable(method):
            return _err(
                "UnknownMethod",
                f"fetcher {req.fetcher} has no callable attribute '{req.method}'",
            )

        # 5. Invoke and classify exceptions
        start = time.monotonic()
        try:
            result = method(**req.kwargs)
        except TypeError as e:
            elapsed_ms = int((time.monotonic() - start) * 1000)
            return _err("TypeError", str(e), with_tb=True, elapsed_ms=elapsed_ms)
        except Exception as e:
            elapsed_ms = int((time.monotonic() - start) * 1000)
            return _err(type(e).__name__, str(e), with_tb=True, elapsed_ms=elapsed_ms)
        elapsed_ms = int((time.monotonic() - start) * 1000)
        return {
            "ok": True,
            "fetcher": req.fetcher,
            "method": req.method,
            "elapsed_ms": elapsed_ms,
            "result": _json_safe(result),
            "error": None,
        }

    return router
