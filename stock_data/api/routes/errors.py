"""Centralised DataFetchError / ValueError / HTTPException / Exception → HTTPException translator.

Apply to every FastAPI route handler so the server has a uniform error contract:
``DataFetchError → 503`` (upstream failure, retryable), ``ValueError → 400``
(user-input validation — e.g. SSRF / URL-scheme rejection from
``news_extractor._validate_url``), ``HTTPException`` is re-raised unchanged
(lets route-level validation surface its own status code), and any other
exception is wrapped as a 500 (with ``logger.error(..., exc_info=True)`` so
the traceback lands in the log).

**Contract on ``ValueError``**: since this clause will swallow *any*
``ValueError`` reaching the handler, handler bodies must only raise it for
client-input errors. Upstream failure modes must use ``DataFetchError``.
Pydantic ``ValidationError`` is a ``ValueError`` subclass, so model
construction failures inside a handler body will also map to 400 — keep
such construction behind FastAPI's request-validation layer where possible.

Usage:
    @router.get('/path', ...)
    @endpoint_meta(...)         # OUTER (above @map_errors / @cache_endpoint)
    @map_errors
    @cache_endpoint(...)        # optional; INNERMOST
    def handler(...): ...       # or  async def handler(...): ...

The order matters: ``@endpoint_meta`` must be the **outermost** non-router
decorator so FastAPI captures the same function object that ``REGISTRY[f]``
was keyed on. ``@map_errors`` sits **outside** ``@cache_endpoint`` so the
exception handler catches anything either layer raises. (Documented 2026-07-16;
the previous "INNER" wording was inverted relative to the actual order used
in every route file under ``api/routes/``.)

**Coroutine handlers (fixed 2026-09-10)**: ``map_errors`` branches on
``inspect.iscoroutinefunction(func)`` and returns an ``async def`` wrapper that
``await``s *inside* the same mapping. This is load-bearing, not cosmetic: a
**sync** wrapper around an ``async def`` handler still "works" on the happy
path — FastAPI decides whether to await by unwrapping ``__wrapped__``, so the
coroutine does run — but it runs at FastAPI's ``await`` site, *outside* this
try/except. The mapping then silently never fires and every escape becomes a
plain-text 500. That latent hole sat on ``/agent/market-recap`` and
``/agent/correlation/matrix`` from 2026-09-03 and was extended to
``/agent/market-stats`` when it went async on 2026-09-10. Do not "simplify"
this back to a single sync wrapper.
"""

import inspect
import logging
from functools import wraps
from typing import NoReturn

from fastapi import HTTPException

from ...data_provider.base import DataFetchError

logger = logging.getLogger(__name__)


def _raise_mapped_error(exc: Exception) -> NoReturn:
    """Map ``exc`` onto the uniform contract and raise the ``HTTPException``.

    Clause order is significant and mirrors the historical inline handler:
    ``DataFetchError`` is checked before ``ValueError`` (Pydantic
    ``ValidationError`` is a ``ValueError`` subclass, and upstream failure
    modes must use ``DataFetchError`` — see the module docstring).
    """
    if isinstance(exc, DataFetchError):
        logger.warning(f"Upstream data unavailable: {exc}")
        raise HTTPException(
            status_code=503,
            detail={"error": "data_unavailable", "message": str(exc)},
        ) from exc
    if isinstance(exc, ValueError):
        logger.warning(f"Bad request: {exc}")
        raise HTTPException(
            status_code=400,
            detail={"error": "bad_request", "message": str(exc)},
        ) from exc
    logger.error(f"Internal error: {exc}", exc_info=True)
    raise HTTPException(
        status_code=500,
        detail={"error": "internal_error", "message": str(exc)},
    ) from exc


def map_errors(func):
    """Wrap ``func`` with the uniform error contract (sync or coroutine)."""
    if inspect.iscoroutinefunction(func):

        @wraps(func)
        async def wrapper(*args, **kwargs):
            try:
                return await func(*args, **kwargs)
            except HTTPException:
                raise
            except Exception as exc:
                _raise_mapped_error(exc)

    else:

        @wraps(func)
        def wrapper(*args, **kwargs):
            try:
                return func(*args, **kwargs)
            except HTTPException:
                raise
            except Exception as exc:
                _raise_mapped_error(exc)

    return wrapper
