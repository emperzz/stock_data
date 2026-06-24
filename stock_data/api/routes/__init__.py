"""Routes package — public API surface of ``stock_data.api.routes``.

Why this exists
---------------

Before this refactor, ``stock_data/api/routes.py`` was 2268 lines containing
3 FastAPI routers, 30+ endpoint handlers, and a pile of shared helpers. Two
real problems lived in that file:

1. ``cached_endpoint`` was dead code on 14 endpoints (verified via runtime
   test): FastAPI captures ``route.endpoint`` at ``@router.get`` decoration
   time, so the ``cached_endpoint(...)`` re-bind that happened on the next
   line never reached the request path. The TTLCache for stock_info /
   dragon_tiger / margin / block_trade / holder_num / dividend / fund_flow /
   fund_flow_daily / hot_topics / north_flow / reports / announcements was
   never hit in production.

2. Error contracts were inconsistent: ``get_quote`` and ``get_index_quote``
   caught only generic ``Exception → 500``, while ``get_history`` and others
   caught ``DataFetchError → 503``. Same upstream failure, different HTTP
   code, depending on which endpoint you hit.

What's in this package
----------------------

- ``router``: the main ``/api/v1`` data APIRouter. Domain modules do
  ``from ._router import router`` and register routes via ``@router.get(...)``.
  The shared-router pattern keeps URL prefixes and tag-based routing identical
  to the pre-refactor behaviour.
- ``news_router``: mounted at ``/api/v1/news/*``. Declared by ``news.py``.
- ``health_router``: mounted at root ``/healthz`` (k8s convention). Declared
  by ``health.py``.
- ``get_manager`` / ``reset_manager``: lifecycle for the global
  ``DataFetcherManager`` singleton. Tests use ``reset_manager`` to wipe
  state between cases.

Public re-exports
-----------------

``server.py`` and the test files import ``health_router``, ``news_router``,
``router``, ``get_manager``, and ``reset_manager`` from
``stock_data.api.routes``. This module keeps that surface stable.

Import ordering note
--------------------

Each domain module does ``from ._router import router`` to pick up the
shared ``APIRouter`` instance. ``_router.py`` is a leaf module (no
imports from the routes package), so there is no circular import.
Submodule decorator code runs against the shared router during
``__init__.py``'s own initialisation, so by the time ``server.py`` calls
``include_router(router, prefix="/api/v1")``, every endpoint is already
registered.
"""

# ---- domain module side-effect imports ----

# Each import is a side-effect import: we don't need the names, only for the
# decorators to register. The noqa comments suppress the unused-import warning.
from . import (
    boards,  # noqa: F401
    calendar,  # noqa: F401
    data,  # noqa: F401
    indices,  # noqa: F401
    stocks,  # noqa: F401
)

# ---- shared routers ----
# The main ``APIRouter`` lives in ``_router.py`` so domain modules can
# ``from ._router import router`` without triggering a circular import back
# through ``__init__.py``. We re-export it as ``router`` for the public
# surface (server.py mounts it via ``include_router(router, prefix="/api/v1")``).
from ._router import router
from .health import health_router

# ---- helpers used by server.py / tests / domain modules ----
from .helpers import get_manager, reset_manager

# news.py and health.py each declare their OWN router (mounted at different
# prefixes by server.py). Importing them runs their decorators, after which
# we re-export ``news_router`` and ``health_router`` for server.py.
from .news import news_router

__all__ = [
    "router",
    "news_router",
    "health_router",
    "get_manager",
    "reset_manager",
]
