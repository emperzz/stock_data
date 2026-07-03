"""Control endpoints for the API Explorer (/control/*).

Exposes server config, server status, and the API manifest. Bound to
127.0.0.1 only — never expose on 0.0.0.0.
"""

from __future__ import annotations

import inspect
import os
import time
import traceback as _traceback
import types
import typing
from datetime import datetime, timezone

from fastapi import APIRouter, Body, Request
from pydantic import BaseModel, Field

from .. import __version__
from .manifest import build_manifest


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


def _unwrap_optional(ann):
    """Strip ``Optional[X]`` / ``X | None`` wrappers down to the inner type.

    The fetcher-test HTML form submits every input as a JSON string. If a
    method signature declares ``days: int = 365``, we want to coerce
    ``"30"`` → ``30`` before calling the method. With
    ``days: int | None = None`` we still want the same coercion when the
    user supplies a value — only the ``None`` branch is unaffected.
    """
    if ann is inspect.Parameter.empty:
        return ann
    origin = getattr(ann, "__origin__", None)
    # typing.Union / typing.Optional (older annotation style)
    if origin is typing.Union:
        non_none = [a for a in typing.get_args(ann) if a is not type(None)]
        if len(non_none) == 1:
            return non_none[0]
        return ann  # Union of multiple non-None types — leave alone
    # types.UnionType (PEP 604 `X | None` syntax, Python 3.10+)
    if hasattr(types, "UnionType") and isinstance(ann, types.UnionType):
        non_none = [a for a in typing.get_args(ann) if a is not type(None)]
        if len(non_none) == 1:
            return non_none[0]
        return ann
    return ann


def _coerce_kwarg_value(value, ann):
    """Coerce a string kwarg to the annotation type.

    HTML form inputs always submit as strings. The fetcher method signature
    is the contract — coerce string → declared primitive when the
    annotation says so. ``bool`` is checked before ``int`` because
    ``bool`` is a subclass of ``int`` in Python.

    Leaves the value untouched when:
      - it's not a string (already the right Python type from JSON),
      - the annotation is unknown / unannotated,
      - coercion fails (let the method raise its own error rather than
        masking the original input with a default).
    """
    if not isinstance(value, str):
        return value
    ann = _unwrap_optional(ann)
    if ann is bool:
        return value.strip().lower() in ("true", "1", "yes", "on")
    if ann is int:
        try:
            return int(value)
        except (TypeError, ValueError):
            return value
    if ann is float:
        try:
            return float(value)
        except (TypeError, ValueError):
            return value
    if ann is str:
        return value
    return value


def _coerce_kwargs_to_signature(method, kwargs: dict) -> dict:
    """Coerce HTML-string kwargs to match ``method``'s declared annotations.

    See ``_coerce_kwarg_value`` for the per-value rules. Unknown params
    (not in the signature, e.g. extra ``**kwargs`` consumers don't care)
    pass through unchanged so methods that accept arbitrary keyword
    arguments still work.

    PEP 563 note: several fetcher modules use ``from __future__ import
    annotations``, which makes annotations lazy strings. ``inspect.signature``
    alone returns those raw strings; we resolve via ``typing.get_type_hints``
    so the ``ann is int`` / ``origin is typing.Union`` checks below see
    real types. Falls back to the raw annotation if resolution fails
    (e.g. forward reference that's not importable at runtime).
    """
    try:
        sig = inspect.signature(method)
    except (TypeError, ValueError):
        return kwargs
    try:
        resolved = typing.get_type_hints(method)
    except Exception:
        resolved = {}
    coerced: dict = {}
    for key, value in kwargs.items():
        param = sig.parameters.get(key)
        if param is None:
            coerced[key] = value
            continue
        ann = resolved.get(key, param.annotation)
        coerced[key] = _coerce_kwarg_value(value, ann)
    return coerced


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
    def control_server_status(request: Request) -> dict:
        """Status of the main server (the one serving the HTML)."""
        started_at = getattr(request.app.state, "started_at", None)
        uptime = int(time.time() - started_at) if started_at else 0
        return {
            "running": True,
            "pid": os.getpid(),
            "port": _read_server_port(),
            "uptime_sec": uptime,
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
        req: FetcherTestRequest = Body(...),  # noqa: B008 (FastAPI idiom)
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
            # HTML form inputs are always strings; coerce to the method's
            # declared annotation types so e.g. `days="30"` reaches
            # `timedelta(days=30)` instead of raising TypeError. Without
            # this, every numeric method parameter is broken when invoked
            # from the explorer's Test button.
            coerced_kwargs = _coerce_kwargs_to_signature(method, req.kwargs)
            result = method(**coerced_kwargs)
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
