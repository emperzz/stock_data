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
    @map_errors
    @cache_endpoint(...)        # optional
    @endpoint_meta(...)
    def handler(...): ...

The order matters: ``@map_errors`` must be **outside** ``@cache_endpoint``
(both are outside ``@endpoint_meta``) so the exception handler catches
anything either layer raises.
"""

import logging
from functools import wraps

from fastapi import HTTPException

from ...data_provider.base import DataFetchError

logger = logging.getLogger(__name__)


def map_errors(func):
    """Wrap ``func`` with the uniform error contract."""

    @wraps(func)
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except DataFetchError as e:
            logger.warning(f"Upstream data unavailable: {e}")
            raise HTTPException(
                status_code=503,
                detail={"error": "data_unavailable", "message": str(e)},
            ) from e
        except ValueError as e:
            logger.warning(f"Bad request: {e}")
            raise HTTPException(
                status_code=400,
                detail={"error": "bad_request", "message": str(e)},
            ) from e
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Internal error: {e}", exc_info=True)
            raise HTTPException(
                status_code=500,
                detail={"error": "internal_error", "message": str(e)},
            ) from e

    return wrapper
