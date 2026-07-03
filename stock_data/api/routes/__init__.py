"""Routes package — public API surface of ``stock_data.api.routes``.

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
