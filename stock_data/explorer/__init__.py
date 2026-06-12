"""API Explorer subpackage: interactive HTML UI at /explorer/ and /control/* endpoints.

Mounts the static HTML frontend at /explorer/ and the Test Instance
management endpoints at /control/*. Used by stock_data.server via
the single-line mount(app) entry point.
"""

from __future__ import annotations

import logging
from pathlib import Path

from fastapi import FastAPI
from fastapi.routing import APIRoute
from fastapi.staticfiles import StaticFiles

from ..api.endpoint_meta import REGISTRY
from ..data_provider.base import (
    BaseFetcher,
    CAPABILITY_TO_METHOD,
    DataCapability,
    _NO_FETCHER_METHOD,
)
from .routes import build_control_router
from .tags import _INTERNAL_TAGS, TAG_TO_TITLE

logger = logging.getLogger(__name__)


def _collect_concrete_fetcher_classes() -> list[type]:
    """Find all concrete BaseFetcher subclasses for the sanity check.

    Walks BaseFetcher.__subclasses__() recursively. Returns only classes
    that have been imported by the time this is called (relies on
    fetcher modules having been imported during manager init).
    """
    found: list[type] = []
    stack = list(BaseFetcher.__subclasses__())
    while stack:
        cls = stack.pop()
        found.append(cls)
        stack.extend(cls.__subclasses__())
    return found


def mount(app: FastAPI) -> None:
    """Mount the API Explorer static UI at /explorer/ and /control/* endpoints.

    Failure mode: if static/ is missing, log a warning and skip the static
    mount, but still register /control/* routes (they don't need the HTML).

    Startup validation: every non-control APIRoute must be decorated with
    @endpoint_meta AND its primary tag must appear in TAG_TO_TITLE.
    Violations are logged at WARNING level — they don't abort server start
    (the data API still works), but they're a deployment bug worth fixing.

    Reentrancy: NOT protected. FastAPI's app.mount() raises RuntimeError on
    duplicate mount, which is sufficient. Call exactly once per FastAPI app.
    """
    # Static mount (failure → warn + continue, data API still works)
    try:
        static_dir = Path(__file__).resolve().parent / "static"
        if static_dir.is_dir():
            app.mount(
                "/explorer",
                StaticFiles(directory=str(static_dir), html=True),
                name="explorer",
            )
            logger.info(f"[Explorer] Mounted /explorer → {static_dir}")
        else:
            logger.warning(
                f"[Explorer] static/ not found at {static_dir}, /explorer not mounted"
            )
    except Exception as e:
        logger.warning(f"[Explorer] Failed to mount /explorer: {e}")

    # Control router. include_router() has no try/except here: any error
    # propagates naturally and aborts server startup, which is the desired
    # behavior (a broken /control/* surface is a deployment bug, not
    # something to silently degrade past).
    control_router = build_control_router()
    app.include_router(control_router)
    logger.info(f"[Explorer] Mounted /control/* ({len(control_router.routes)} endpoints)")

    # Startup sanity: every visible APIRoute must be registered in
    # REGISTRY and its primary tag must be mapped to a title. This is
    # the early-warning net for the "developer forgot to decorate" /
    # "developer added a new tag without updating TAG_TO_TITLE" cases.
    _validate_manifest_invariants(app)


def _validate_manifest_invariants(app: FastAPI) -> None:
    """Log warnings for any APIRoute that would be missing/broken in the manifest."""
    undecorated: list[str] = []
    untitled_tags: set[str] = set()
    for route in app.routes:
        if not isinstance(route, APIRoute):
            continue
        if not route.tags or any(t in _INTERNAL_TAGS for t in route.tags):
            continue
        if route.endpoint not in REGISTRY:
            undecorated.append(f"{list(route.methods)[0]} {route.path}")
        elif route.tags[0] not in TAG_TO_TITLE:
            untitled_tags.add(route.tags[0])
    if undecorated:
        logger.warning(
            f"[Explorer] {len(undecorated)} route(s) missing @endpoint_meta; "
            f"they will not appear in the explorer: {undecorated}"
        )
    if untitled_tags:
        logger.warning(
            f"[Explorer] tag(s) not in TAG_TO_TITLE (sidebar will use tag name "
            f"as fallback title): {sorted(untitled_tags)}"
        )

    # ----- CAPABILITY_TO_METHOD invariants -----
    # Concrete fetchers may define methods not on the abstract BaseFetcher
    # (e.g. get_dragon_tiger only exists on EastMoneyFetcher). Check both.
    _concrete_fetcher_classes = _collect_concrete_fetcher_classes()

    def _method_exists_anywhere(method_name: str) -> bool:
        if hasattr(BaseFetcher, method_name):
            return True
        return any(hasattr(cls, method_name) for cls in _concrete_fetcher_classes)

    for cap, method_name in CAPABILITY_TO_METHOD.items():
        if not _method_exists_anywhere(method_name):
            logger.warning(
                f"[explorer/sanity] CAPABILITY_TO_METHOD[{cap.name}] = "
                f"{method_name!r} but no fetcher class has such attribute. "
                f"Manifest will silently skip this capability."
            )

    for cap in DataCapability:
        if cap not in CAPABILITY_TO_METHOD and cap not in _NO_FETCHER_METHOD:
            logger.warning(
                f"[explorer/sanity] DataCapability.{cap.name} is neither in "
                f"CAPABILITY_TO_METHOD nor in _NO_FETCHER_METHOD. Add it to one "
                f"of them to declare intent."
            )

    # ----- @endpoint_meta(fetcher_method=...) sanity -----
    for func, meta in REGISTRY.items():
        if meta.fetcher_method is not None and not _method_exists_anywhere(meta.fetcher_method):
            logger.warning(
                f"[explorer/sanity] {func.__qualname__} declares "
                f"fetcher_method={meta.fetcher_method!r}, but no fetcher class has "
                f"such attribute. Stage 2 testing for this endpoint will fail."
            )
