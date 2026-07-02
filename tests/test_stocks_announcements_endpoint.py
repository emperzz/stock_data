"""Tests for /stocks/{code}/announcements endpoint.

The live test at the bottom (``test_stocks_announcements_endpoint_live``)
hits the real upstream and is tagged ``@pytest.mark.live_network`` so the
default ``pytest`` run skips it via ``pyproject.toml addopts = ["-m", "not
live_network"]``. To run it: ``pytest -m live_network
tests/test_stocks_announcements_endpoint.py``.

The failover mechanism itself is tested in
``test_announcements_eastmoney_failover.py`` (mock-based).
"""
import pytest
from fastapi.testclient import TestClient

from stock_data.server import app


@pytest.fixture
def client():
    return TestClient(app)


# ---------------------------------------------------------------------------
# Live network tests (skipped by default; see module docstring).
# ---------------------------------------------------------------------------


@pytest.mark.live_network
def test_stocks_announcements_endpoint_live(client):
    """End-to-end: /api/v1/stocks/600519/announcements returns eastmoney/cninfo data."""
    resp = client.get("/api/v1/stocks/600519/announcements?page_size=5")
    assert resp.status_code == 200, f"Got {resp.status_code}: {resp.text}"
    body = resp.json()
    assert body["code"] == "600519"
    assert "announcements" in body
    assert len(body["announcements"]) > 0
    # source should be either EastMoneyFetcher or CninfoFetcher (failover)
    assert body["source"] in ("EastMoneyFetcher", "CninfoFetcher"), \
        f"Unexpected source: {body['source']}"
