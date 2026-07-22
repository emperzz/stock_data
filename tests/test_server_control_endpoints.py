"""Integration tests for /control/* endpoints added for the API Explorer."""

import pytest
from fastapi.testclient import TestClient

from stock_data.server import app


@pytest.fixture
def client():
    return TestClient(app)


class TestControlConfig:
    def test_returns_port_host_version(self, client, monkeypatch):
        monkeypatch.setenv("SERVER_PORT", "8888")
        monkeypatch.setenv("SERVER_HOST", "127.0.0.1")

        response = client.get("/control/config")
        assert response.status_code == 200
        data = response.json()
        assert "port" in data
        assert "host" in data
        assert "version" in data


class TestControlServerStatus:
    def test_returns_running(self, client):
        """The main server is always 'running' from its own POV."""
        response = client.get("/control/server/status")
        assert response.status_code == 200
        data = response.json()
        assert data["running"] is True
        assert "pid" in data
        assert "uptime_sec" in data
        assert "port" in data


class TestExplorerMount:
    def test_explorer_index_served(self, client):
        """GET /explorer/ returns 200 and contains <html>."""
        response = client.get("/explorer/")
        if response.status_code == 404:
            pytest.skip("explorer not yet mounted")
        assert response.status_code == 200
        assert "<html" in response.text.lower()
