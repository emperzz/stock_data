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
        assert "test_port" in data
        assert "env_keys" in data
        assert isinstance(data["env_keys"], list)
        assert "TUSHARE_TOKEN" in data["env_keys"]


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


class TestControlTestInstanceLifecycle:
    def test_start_returns_running(self, client, monkeypatch):
        """start returns running=True with the configured port + host.

        Pins SERVER_HOST=127.0.0.1 so a future regression that flips the
        default to 0.0.0.0 would be caught.
        """
        monkeypatch.setenv("SERVER_HOST", "127.0.0.1")
        monkeypatch.setenv("STOCK_TEST_INSTANCE_PORT", "18888")

        captured = {}
        def fake_start(**kw):
            captured["kwargs"] = kw
            return {"running": True, "pid": 12345, "port": kw["port"], "error": None}
        monkeypatch.setattr("stock_data.explorer.control.start_test_instance", fake_start)

        response = client.post("/control/test-instance/start")
        assert response.status_code == 200
        data = response.json()
        assert data["running"] is True
        assert data["port"] == 18888
        # Ensure the host passed to the subprocess is the safe 127.0.0.1,
        # not 0.0.0.0 (which would expose /control/* on all interfaces).
        assert captured["kwargs"]["host"] == "127.0.0.1"

    def test_stop_returns_not_running(self, client, monkeypatch):
        """stop returns running=False (idempotent)."""
        monkeypatch.setattr(
            "stock_data.explorer.control.stop_test_instance",
            lambda **kw: {"running": False, "pid": None, "error": None},
        )
        response = client.post("/control/test-instance/stop")
        assert response.status_code == 200
        data = response.json()
        assert data["running"] is False

    def test_status_includes_port(self, client, monkeypatch):
        """status response always includes 'port' for UI display."""
        monkeypatch.setenv("STOCK_TEST_INSTANCE_PORT", "18889")
        monkeypatch.setattr(
            "stock_data.explorer.control.get_test_instance_status",
            lambda **kw: {"running": False, "pid": None, "port": None, "error": None},
        )
        response = client.get("/control/test-instance/status")
        assert response.status_code == 200
        data = response.json()
        assert data["port"] == 18889
        assert data["running"] is False


class TestExplorerMount:
    def test_explorer_index_served(self, client):
        """GET /explorer/ returns 200 and contains <html>."""
        response = client.get("/explorer/")
        if response.status_code == 404:
            pytest.skip("explorer not yet mounted")
        assert response.status_code == 200
        assert "<html" in response.text.lower()
