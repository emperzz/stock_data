"""Smoke test: /stocks/{code}/boards?source=eastmoney routing.

Verifies the eastmoney branch in ``stock_board_cache.get_stock_memberships``
when the persistence cache is empty for eastmoney. When the fetcher returns
``None`` (invalid stock code), the response is a 200 with eastmoney in
``cold_sources`` (no 500).

The live test at the bottom (``test_stocks_boards_eastmoney_source_live``)
hits the real upstream and is tagged ``@pytest.mark.live_network`` so the
default ``pytest`` run skips it via ``pyproject.toml addopts = ["-m", "not
live_network"]``. To run it: ``pytest -m live_network
tests/test_stock_boards_eastmoney_source.py``.
"""
from unittest.mock import patch

import pytest


def _make_fake_manager(*, boards, fetcher_name="EastMoneyFetcher"):
    """Build a MagicMock manager whose get_stock_boards returns (boards, name)."""
    from unittest.mock import MagicMock

    mgr = MagicMock()
    mgr.get_stock_boards = MagicMock(return_value=(boards, fetcher_name))
    return mgr




def test_eastmoney_source_invalid_code_returns_200_with_cold_sources(client):
    """If eastmoney returns None (invalid code), surface as cold_sources, not error.

    The route returns 200 with empty data and eastmoney in cold_sources —
    never 500. This mirrors the pre-existing 800998 case in
    ``test_get_stock_boards_eastmoney_returns_200_with_cold_sources_when_empty``.
    """
    r = client.get("/api/v1/stocks/800998/boards?source=eastmoney")
    assert r.status_code == 200
    body = r.json()
    assert body["data"] == []
    assert "eastmoney" in body["cold_sources"]




def test_eastmoney_source_routes_through_persistence_layer(client):
    """Sanity check: the route delegates to ``stock_board_cache.get_stock_memberships``,
    not directly to ``manager.get_stock_boards``. We patch the persistence helper
    and confirm the route picks it up.
    """
    from stock_data.api.routes import boards as boards_route

    fake_entries = [
        {"code": "BK0001", "name": "测试板块",
         "type": "industry", "subtype": "industry", "source": "eastmoney"},
    ]
    with patch.object(
        boards_route.stock_board_cache,
        "get_stock_memberships",
        return_value=(fake_entries, [], "persistence"),
    ):
        r = client.get("/api/v1/stocks/600519/boards?source=eastmoney")
    assert r.status_code == 200
    body = r.json()
    assert len(body["data"]) == 1
    assert body["data"][0]["code"] == "BK0001"
    assert body["cold_sources"] == []


# ---------------------------------------------------------------------------
# Live network tests (skipped by default; see module docstring).
# ---------------------------------------------------------------------------


@pytest.mark.live_network
def test_stocks_boards_eastmoney_source_live(client):
    """End-to-end: ?source=eastmoney returns eastmoney data via persistence cold-fill."""
    resp = client.get("/api/v1/stocks/600519/boards?source=eastmoney")
    # Acceptable: 200 (data) or 502 (no fetcher in env)
    assert resp.status_code in (200, 502), f"Got {resp.status_code}: {resp.text}"
    if resp.status_code == 200:
        body = resp.json()
        assert "data" in body
        # Should have at least one board
        assert len(body["data"]) > 0, "Live boards should not be empty"
