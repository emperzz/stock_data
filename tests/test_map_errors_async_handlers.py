"""Pins the coroutine-handler branch of ``map_errors``.

Regression guard for the 2026-09-10 review finding. ``map_errors`` used to be a
sync-only wrapper (``def wrapper: return func(*args, **kwargs)``). Wrapping an
``async def`` handler with it still "worked" on the happy path — FastAPI decides
whether to await by unwrapping ``__wrapped__``, so the coroutine *did* run — but
it then ran at FastAPI's ``await`` site, i.e. **outside** the try/except. Every
escape therefore became a plain-text 500: ``DataFetchError → 503``,
``ValueError → 400`` and the generic ``Exception → 500`` JSON envelope were all
silently lost.

Blast radius at fix time: latent on ``/agent/market-recap`` and
``/agent/correlation/matrix`` since 2026-09-03 (both already ``async def``), and
newly introduced on ``/agent/market-stats`` when it went ``async`` on 2026-09-10.

``TestNoRouteRegressesToSyncWrapper`` at the bottom is the load-bearing one: it
fails for ANY route whose decorator stack wraps a coroutine handler in a sync
wrapper, including routes that don't exist yet.
"""

import inspect

import pytest
from fastapi import HTTPException

from stock_data.api.routes.errors import map_errors
from stock_data.data_provider.base import DataFetchError

# (exception class, expected status, expected `detail.error` code)
MAPPED_ESCAPES = [
    (DataFetchError, 503, "data_unavailable"),
    (ValueError, 400, "bad_request"),
    (RuntimeError, 500, "internal_error"),
]


def _raiser(exc_cls):
    """Patch target that raises ``exc_cls`` when the handler body reaches it."""

    def _raise(*args, **kwargs):
        raise exc_cls("probe")

    return _raise


# ----- the decorator itself -----


@pytest.mark.parametrize("exc_cls, status, error_code", MAPPED_ESCAPES)
def test_sync_handler_maps_every_escape(exc_cls, status, error_code):
    @map_errors
    def handler():
        raise exc_cls("probe")

    with pytest.raises(HTTPException) as excinfo:
        handler()

    assert excinfo.value.status_code == status
    assert excinfo.value.detail["error"] == error_code


@pytest.mark.parametrize("exc_cls, status, error_code", MAPPED_ESCAPES)
async def test_coroutine_handler_maps_every_escape(exc_cls, status, error_code):
    @map_errors
    async def handler():
        raise exc_cls("probe")

    with pytest.raises(HTTPException) as excinfo:
        await handler()

    assert excinfo.value.status_code == status
    assert excinfo.value.detail["error"] == error_code


async def test_coroutine_wrapper_is_a_coroutine_function():
    """The mechanism under test: the *wrapper* must be awaitable, otherwise
    FastAPI awaits the inner coroutine past the try/except."""

    @map_errors
    async def handler():
        return "ok"

    assert inspect.iscoroutinefunction(handler)
    assert await handler() == "ok"


def test_sync_wrapper_keeps_calling_synchronously():
    @map_errors
    def handler():
        return "ok"

    assert not inspect.iscoroutinefunction(handler)
    assert handler() == "ok"


def test_sync_handler_preserves_httpexception():
    """Route-level validation keeps its own status code rather than being
    re-mapped onto the 400/503/500 contract."""

    @map_errors
    def handler():
        raise HTTPException(status_code=422, detail={"error": "invalid_request"})

    with pytest.raises(HTTPException) as excinfo:
        handler()

    assert excinfo.value.status_code == 422
    assert excinfo.value.detail["error"] == "invalid_request"


async def test_coroutine_handler_preserves_httpexception():
    @map_errors
    async def handler():
        raise HTTPException(status_code=422, detail={"error": "invalid_request"})

    with pytest.raises(HTTPException) as excinfo:
        await handler()

    assert excinfo.value.status_code == 422
    assert excinfo.value.detail["error"] == "invalid_request"


def test_wraps_metadata_is_preserved():
    """`@wraps` keeps `__name__`/`__wrapped__`, which is also what lets the
    manifest registry and `TestNoRouteRegressesToSyncWrapper` see through."""

    @map_errors
    async def named_handler():
        return "ok"

    assert named_handler.__name__ == "named_handler"
    assert named_handler.__wrapped__ is not None


# ----- the routes -----


class TestAsyncRouteEscapeMapping:
    """End-to-end: an exception escaping one of the three coroutine routes must
    come back as the uniform JSON envelope, not FastAPI's plain-text 500.

    Each case injects a raise at a call the handler body reaches before it can
    possibly succeed, so the mapping is exercised on the real route rather than
    on a synthetic handler.
    """

    @pytest.mark.parametrize("exc_cls, status, error_code", MAPPED_ESCAPES)
    def test_market_stats_maps(self, client, monkeypatch, exc_cls, status, error_code):
        from stock_data.api.routes import agent as agent_mod

        monkeypatch.setattr(agent_mod, "cached_lookup", _raiser(exc_cls))

        response = client.get("/api/v1/agent/market-stats")

        assert response.status_code == status
        assert response.json()["detail"]["error"] == error_code

    @pytest.mark.parametrize("exc_cls, status, error_code", MAPPED_ESCAPES)
    def test_market_recap_maps(self, client, monkeypatch, exc_cls, status, error_code):
        from stock_data.api.routes import agent as agent_mod

        monkeypatch.setattr(agent_mod, "cached_lookup", _raiser(exc_cls))

        response = client.get("/api/v1/agent/market-recap")

        assert response.status_code == status
        assert response.json()["detail"]["error"] == error_code

    @pytest.mark.parametrize("exc_cls, status, error_code", MAPPED_ESCAPES)
    def test_correlation_matrix_maps(self, client, monkeypatch, exc_cls, status, error_code):
        from stock_data.api.routes import agent_correlation as corr_mod

        monkeypatch.setattr(corr_mod, "_fetch_stock_series", _raiser(exc_cls))

        response = client.post(
            "/api/v1/agent/correlation/matrix",
            # 2 assets minimum — the route 422s on fewer before reaching any fetch.
            json={"stocks": ["600519", "000001"], "boards": [], "frequency": "d", "days": 30},
        )

        assert response.status_code == status
        assert response.json()["detail"]["error"] == error_code


def _sync_ness_changes_down_the_wrapper_chain(endpoint) -> bool:
    """True if any ``__wrapped__`` link flips sync↔coroutine.

    A sync wrapper around a coroutine handler is exactly the 2026-09-10 bug:
    FastAPI still awaits the inner coroutine (`Dependant.is_coroutine_callable`
    unwraps ``__wrapped__``), but the await happens outside the wrapper's
    try/except, so `map_errors` stops mapping anything.
    """
    current = endpoint
    while hasattr(current, "__wrapped__"):
        inner = current.__wrapped__
        if inspect.iscoroutinefunction(current) != inspect.iscoroutinefunction(inner):
            return True
        current = inner
    return False


class TestNoRouteRegressesToSyncWrapper:
    def test_every_route_endpoint_matches_its_handler_kind(self):
        """Covers all three known coroutine routes (and any future one) without
        needing a per-route injection point."""
        from stock_data.server import app

        mismatched = [
            getattr(route, "path", "?")
            for route in app.routes
            if getattr(route, "endpoint", None) is not None
            and _sync_ness_changes_down_the_wrapper_chain(route.endpoint)
        ]

        assert mismatched == [], (
            "routes whose decorator stack wraps a coroutine handler in a sync "
            f"wrapper (map_errors would silently stop mapping): {mismatched}"
        )

    def test_the_three_coroutine_routes_are_covered(self):
        """Guards the guard: if the routes above ever stop being coroutine
        functions, the structural test above becomes vacuous."""
        from stock_data.server import app

        coroutine_paths = {
            getattr(route, "path", "")
            for route in app.routes
            if getattr(route, "endpoint", None) is not None
            and inspect.iscoroutinefunction(route.endpoint)
        }

        assert "/api/v1/agent/market-stats" in coroutine_paths
        assert "/api/v1/agent/market-recap" in coroutine_paths
        assert "/api/v1/agent/correlation/matrix" in coroutine_paths
