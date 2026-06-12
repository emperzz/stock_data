"""Integration tests for GET /control/api-manifest."""
import pytest
from fastapi.testclient import TestClient

from stock_data.api.endpoint_meta import REGISTRY
from stock_data.server import app


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture(autouse=True)
def _clear_registry():
    REGISTRY.clear()
    yield
    REGISTRY.clear()


class TestApiManifestEndpoint:
    def test_returns_200_and_expected_shape(self, client):
        response = client.get("/control/api-manifest")
        assert response.status_code == 200
        data = response.json()
        assert "meta" in data
        assert "sections" in data
        assert isinstance(data["sections"], list)
        assert "version" in data["meta"]
        assert "server_version" in data["meta"]
        assert "capabilities" in data["meta"]
        assert "generated_at" in data["meta"]
        assert data["meta"]["generated_at"] is not None
        # ISO 8601 string ending in 'Z' or '+00:00'
        assert data["meta"]["generated_at"].endswith(("Z", "+00:00"))

    def test_meta_capabilities_contain_known_flags(self, client):
        data = client.get("/control/api-manifest").json()
        caps = data["meta"]["capabilities"]
        for flag in ("REALTIME_QUOTE", "HISTORICAL_DWM", "STOCK_BOARD"):
            assert flag in caps
            assert "label" in caps[flag]
            assert "icon" in caps[flag]

    def test_no_routes_yet_yields_empty_sections(self, client):
        # Registry is cleared by the autouse fixture, so no endpoints
        # carry @endpoint_meta in this test. Manifest should have 0
        # sections (control/* is excluded by tag filter).
        data = client.get("/control/api-manifest").json()
        assert data["sections"] == []
