"""/healthz endpoint.

Mounted at root (k8s/lb convention) rather than under ``/api/v1``. The
``server.py`` entry point includes this router without a prefix.
"""

import logging

from fastapi import APIRouter

from ...data_provider.base import BaseFetcher
from ...data_provider.core.types import REALTIME_CIRCUIT_BREAKER
from ..endpoint_meta import endpoint_meta
from ..schemas import HealthResponse, SourceHealth
from .errors import map_errors
from .helpers import get_manager

logger = logging.getLogger(__name__)

health_router = APIRouter()


@health_router.get(
    "/healthz",
    response_model=HealthResponse,
    tags=["health"],
)
@endpoint_meta(
    summary="健康检查 + fetcher 断路器状态",
    markets=["csi", "hk", "us"],
    capabilities=[],
)
@map_errors
def health_check(details: bool = False) -> HealthResponse:
    """Health check endpoint.

    Lightweight mode (default): returns overall status for k8s/lb probes.
    Detailed mode (?details=true): returns per-source circuit breaker state
    for AI agents.

    Both modes are READ-ONLY — they use ``CircuitBreaker.snapshot_state()``
    which does not transition states or consume half-open probe budgets, so
    frequent probes cannot starve real fetches.

    Coverage: enumerates **all** ``BaseFetcher`` subclasses (not just
    registered ones) so missing-config fetchers (Tushare/Zhitu without their
    tokens) are surfaced with ``available: false`` and an
    ``unavailable_reason`` from the fetcher's own logic-driven method.
    k8s/lb probes see the same status as before — only **registered**
    fetchers count toward ``ok/degraded/unhealthy``, so a missing optional
    token doesn't flip the probe to unhealthy.
    """
    manager = get_manager()
    # Map registered fetcher instances by name so we can pull circuit-breaker
    # state for those, and synthesize a "not registered" entry for the rest.
    registered_by_name: dict[str, object] = {f.name: f for f in manager.fetchers}

    # Walk every concrete subclass — same recursion shape as the manifest
    # builder.
    all_classes: list[type] = []
    stack: list[type] = list(BaseFetcher.__subclasses__())
    while stack:
        cls = stack.pop()
        all_classes.append(cls)
        stack.extend(cls.__subclasses__())

    source_states: list[SourceHealth] = []
    registered_available_count = 0
    registered_open_count = 0

    for fetcher_cls in all_classes:
        fetcher_name = getattr(fetcher_cls, "name", fetcher_cls.__name__)
        registered = registered_by_name.get(fetcher_name)

        if registered is not None:
            # Registered: pull live circuit-breaker state.
            snap = REALTIME_CIRCUIT_BREAKER.snapshot_state(fetcher_name)
            available = snap["available"]
            if available:
                registered_available_count += 1
            if snap["state"] in ("open", "half_open"):
                registered_open_count += 1
            last_success = snap["last_success_time"] if snap["last_success_time"] > 0 else None
            last_failure = snap["last_failure_time"] if snap["last_failure_time"] > 0 else None
            source_states.append(
                SourceHealth(
                    name=fetcher_name,
                    state=snap["state"],
                    available=available,
                    last_success_time=last_success,
                    last_failure_time=last_failure,
                    failure_count=snap["failures"],
                    unavailable_reason=None,
                )
            )
        else:
            # Not registered: instantiate on demand to read the same
            # is_available()/unavailable_reason() the manifest uses.
            # Construction is side-effect-free (env-var reads only).
            try:
                instance = fetcher_cls()
            except Exception:
                source_states.append(
                    SourceHealth(
                        name=fetcher_name,
                        state="closed",
                        available=False,
                        unavailable_reason=f"{fetcher_name} could not be instantiated",
                    )
                )
                continue
            available = bool(instance.is_available())
            reason = None if available else instance.unavailable_reason()
            source_states.append(
                SourceHealth(
                    name=fetcher_name,
                    state="closed",
                    available=available,
                    unavailable_reason=reason,
                )
            )

    # Status determination is intentionally driven ONLY by registered
    # fetchers — missing optional tokens (Tushare/Zhitu) must not flip the
    # probe to unhealthy.
    if registered_available_count == 0:
        status = "unhealthy"
    elif registered_open_count > 0:
        status = "degraded"
    else:
        status = "ok"

    return HealthResponse(
        status=status,
        sources=source_states if details else None,
    )
