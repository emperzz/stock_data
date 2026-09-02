"""Drift detection for @endpoint_meta(depends_on=...) on agent routes.

depends_on is hand-declared (mirrors fetcher_method's manual-override model).
These tests pin:
  - every agent route declares a non-empty depends_on
  - every endpoint-path ref (kind:"endpoint") resolves to a real route in the
    manifest (catches: deleted/renamed endpoint, typo in the path, param-name
    drift the normalizer can't paper over)
  - at least one endpoint ref per agent (so the graph draws a composed-of edge)
"""

import pytest
from fastapi.testclient import TestClient

from stock_data.api.endpoint_meta import REGISTRY
from stock_data.server import app

_REGISTRY_SNAPSHOT: dict = dict(REGISTRY)


# 9 agent routes (8 in agent.py + 1 in agent_correlation.py). method+path
# exactly as registered (router prefix /api/v1 already merged).
AGENT_ROUTES = [
    ("POST", "/api/v1/agent/boards/stock-overlap"),
    ("POST", "/api/v1/agent/stocks/board-overlap"),
    ("POST", "/api/v1/agent/boards/filter-stocks"),
    ("GET", "/api/v1/agent/indices/batch-profile"),
    ("GET", "/api/v1/agent/market-context"),
    ("POST", "/api/v1/agent/stocks/batch-profile"),
    ("POST", "/api/v1/agent/boards/batch-profile"),
    ("GET", "/api/v1/agent/market-stats"),
    ("POST", "/api/v1/agent/correlation/matrix"),
]


@pytest.fixture(autouse=True)
def _restore_registry():
    REGISTRY.clear()
    REGISTRY.update(_REGISTRY_SNAPSHOT)
    yield


def _manifest():
    with TestClient(app) as client:
        client.get("/control/server/status")  # trigger lifespan
        resp = client.get("/control/api-manifest")
        resp.raise_for_status()
        return resp.json()


def _agent_endpoint(manifest: dict, method: str, path: str) -> dict:
    for sec in manifest["sections"]:
        for ep in sec["endpoints"]:
            if ep["method"] == method and ep["path"] == path:
                return ep
    pytest.fail(f"agent endpoint not found: {method} {path}")


def _all_endpoint_paths(manifest: dict) -> set[str]:
    return {ep["path"] for sec in manifest["sections"] for ep in sec["endpoints"]}


@pytest.mark.parametrize("method,path", AGENT_ROUTES)
def test_every_agent_route_declares_depends_on(method, path):
    m = _manifest()
    ep = _agent_endpoint(m, method, path)
    assert ep["depends_on"], f"{method} {path} has empty depends_on"


@pytest.mark.parametrize("method,path", AGENT_ROUTES)
def test_agent_depends_on_endpoint_refs_resolve(method, path):
    m = _manifest()
    ep = _agent_endpoint(m, method, path)
    all_paths = _all_endpoint_paths(m)
    endpoint_refs = [d for d in ep["depends_on"] if d["kind"] == "endpoint"]
    assert endpoint_refs, f"{method} {path} has no endpoint-kind depends_on (no composed-of edge)"
    for d in endpoint_refs:
        assert d["target_path"] in all_paths, (
            f"{method} {path} depends_on ref {d['label']!r} resolves to "
            f"{d['target_path']!r} which is not in the manifest — "
            f"target endpoint was deleted/renamed, or param-name drift."
        )
