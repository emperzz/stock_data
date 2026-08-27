"""Integration tests for GET /api/v1/agent/market-stats.

All tests mock at the FastAPI route layer (manager + stock_board_cache)
so they're fast and don't touch the network.
"""
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from stock_data.api.cache import make_market_stats_cache_key
from stock_data.api.routes import agent as agent_module
from stock_data.data_provider.base import DataFetchError
from stock_data.data_provider.core.types import UnifiedRealtimeQuote

# ----- fixtures -----


@pytest.fixture
def client():
    """Fresh FastAPI TestClient per test.

    Per-test cache isolation is provided by the autouse ``_clear_quote_cache``
    fixture below — the app module's ``_ENABLE_CACHE`` is read once at import
    time, so toggling ``ENABLE_API_CACHE`` inside this fixture would be a
    no-op (the import already happened) and is deliberately not done.
    """
    from stock_data.server import app

    return TestClient(app)


@pytest.fixture(autouse=True)
def _clear_quote_cache():
    """Reset the in-memory quote cache between tests so a 60s TTL
    doesn't leak state across tests."""
    from stock_data.api.cache import get_quote_cache

    cache = get_quote_cache()
    cache.clear()
    yield
    cache.clear()


def _make_quote(code: str, change_pct, name: str = "—"):
    """Build a UnifiedRealtimeQuote with the fields the route reads."""
    return UnifiedRealtimeQuote(
        code=code,
        name=name,
        price=10.0,
        open_price=10.0,
        high=10.0,
        low=10.0,
        pre_close=10.0,
        volume=0,
        amount=0,
        change_pct=change_pct,
        change_amount=0.0,
        turnover_rate=0.0,
        amplitude=0.0,
        pe_ratio=None,
        pb_ratio=None,
        total_mv=None,
        circ_mv=None,
    )


def _patch_manager(monkeypatch, *, quotes):
    """Patch the manager method the stocks block uses.

    NOTE: the route only calls ``manager.get_realtime_quotes`` here; the
    boards block goes through ``stock_board_cache.get_board_list`` (see
    ``_patch_board_cache``), so no ``get_all_boards`` stub is needed.
    """
    fake_manager = MagicMock()
    fake_manager.get_realtime_quotes.return_value = (quotes, "akshare")
    monkeypatch.setattr(agent_module, "get_manager", lambda: fake_manager)
    return fake_manager


def _patch_board_cache(monkeypatch, *, all_boards_payload):
    """Patch stock_board_cache.get_board_list used inside the route.

    NOTE: the route calls ``stock_board_cache.get_board_list(...)`` — not
    ``manager.get_all_boards(...)``. Patching the wrong attribute would
    silently pass tests while the route crashes at runtime, so we patch
    the right one and (in test_format_md_returns_markdown) also assert
    via the patched fake_cache.get_board_list call count.
    """
    fake_cache = MagicMock()
    fake_cache.get_board_list.return_value = all_boards_payload
    monkeypatch.setattr(agent_module, "stock_board_cache", fake_cache)
    return fake_cache


# ----- happy path -----


def test_market_stats_returns_200(client, monkeypatch):
    """Happy path — both blocks populated, summary reports 2/2 ok."""
    quotes = [_make_quote("600000", 1.0), _make_quote("600001", -1.0), _make_quote("600002", 0.0)]
    boards = [{"code": "BK0001", "name": "X", "change_pct": 0.5}]
    _patch_manager(monkeypatch, quotes=quotes)
    _patch_board_cache(monkeypatch, all_boards_payload=(boards, "ths"))

    resp = client.get("/api/v1/agent/market-stats")
    assert resp.status_code == 200
    body = resp.json()
    assert body["stocks"]["sample_size"] == 3
    assert body["stocks"]["up_count"] == 1
    assert body["stocks"]["down_count"] == 1
    assert body["stocks"]["flat_count"] == 1
    assert body["boards"]["sample_size"] == 1
    assert body["boards"]["source"] == "ths"
    assert body["errors"] == []
    assert body["summary"]["requested"] == 2
    assert body["summary"]["ok"] == 2


# ----- error isolation -----


def test_stocks_upstream_failure_does_not_affect_boards(client, monkeypatch):
    """When get_realtime_quotes raises, stocks=null but boards is still populated."""
    fake_manager = MagicMock()
    fake_manager.get_realtime_quotes.side_effect = DataFetchError("upstream down")
    monkeypatch.setattr(agent_module, "get_manager", lambda: fake_manager)
    boards = [{"code": "BK0001", "name": "X", "change_pct": 0.5}]
    _patch_board_cache(monkeypatch, all_boards_payload=(boards, "ths"))

    resp = client.get("/api/v1/agent/market-stats")
    assert resp.status_code == 200
    body = resp.json()
    assert body["stocks"] is None
    assert body["boards"] is not None
    assert body["boards"]["sample_size"] == 1
    assert any(e["block"] == "stocks" for e in body["errors"])
    assert body["summary"]["ok"] == 1
    assert body["summary"]["failed"] == 1


def test_boards_upstream_failure_does_not_affect_stocks(client, monkeypatch):
    """Symmetric — boards=null but stocks still populated."""
    quotes = [_make_quote("600000", 1.0)]
    _patch_manager(monkeypatch, quotes=quotes)
    fake_cache = MagicMock()
    fake_cache.get_board_list.side_effect = ValueError("cid_unresolved")
    monkeypatch.setattr(agent_module, "stock_board_cache", fake_cache)

    resp = client.get("/api/v1/agent/market-stats")
    assert resp.status_code == 200
    body = resp.json()
    assert body["stocks"] is not None
    assert body["boards"] is None
    assert any(e["block"] == "boards" for e in body["errors"])
    assert body["summary"]["ok"] == 1


def test_both_blocks_fail(client, monkeypatch):
    """Both upstream failures — both null, 2 errors, summary.ok=0."""
    fake_manager = MagicMock()
    fake_manager.get_realtime_quotes.side_effect = DataFetchError("stocks down")
    monkeypatch.setattr(agent_module, "get_manager", lambda: fake_manager)
    fake_cache = MagicMock()
    fake_cache.get_board_list.side_effect = RuntimeError("boards down")
    monkeypatch.setattr(agent_module, "stock_board_cache", fake_cache)

    resp = client.get("/api/v1/agent/market-stats")
    assert resp.status_code == 200
    body = resp.json()
    assert body["stocks"] is None
    assert body["boards"] is None
    assert len(body["errors"]) == 2
    assert body["summary"]["ok"] == 0
    assert body["summary"]["requested"] == 2


# ----- include_boards toggle -----


def test_include_boards_false_skips_boards_upstream(client, monkeypatch):
    """?include_boards=false must NOT invoke any boards upstream call."""
    quotes = [_make_quote("600000", 1.0)]
    fake_manager = MagicMock()
    fake_manager.get_realtime_quotes.return_value = (quotes, "akshare")
    monkeypatch.setattr(agent_module, "get_manager", lambda: fake_manager)
    fake_cache = MagicMock()
    monkeypatch.setattr(agent_module, "stock_board_cache", fake_cache)

    resp = client.get("/api/v1/agent/market-stats?include_boards=false")
    assert resp.status_code == 200
    body = resp.json()
    assert body["stocks"] is not None
    assert body["boards"] is None
    assert body["errors"] == []
    assert body["summary"]["requested"] == 1
    assert body["summary"]["ok"] == 1
    # Boards upstream NEVER called — fake_cache.get_board_list.assert_not_called()
    fake_cache.get_board_list.assert_not_called()


# ----- format dispatch -----


def test_format_md_returns_markdown(client, monkeypatch):
    """?format=md → text/markdown; body contains expected section headers."""
    quotes = [_make_quote("600000", 1.0)]
    boards = [{"code": "BK0001", "name": "白酒", "change_pct": 0.5}]
    _patch_manager(monkeypatch, quotes=quotes)
    _patch_board_cache(monkeypatch, all_boards_payload=(boards, "ths"))

    resp = client.get("/api/v1/agent/market-stats?format=md")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/markdown")
    body = resp.text
    assert "# 市场全量统计" in body
    assert "## 个股" in body
    assert "## 板块" in body
    assert "## 失败列表" in body
    assert "## 汇总" in body


def test_format_invalid_returns_422(client):
    """Unknown format → 422 (handled by Query pattern in the handler)."""
    resp = client.get("/api/v1/agent/market-stats?format=xml")
    assert resp.status_code == 422


# ----- cache key -----


def test_cache_key_includes_include_boards():
    assert make_market_stats_cache_key(True) == "agent_market_stats:True"
    assert make_market_stats_cache_key(False) == "agent_market_stats:False"
    assert make_market_stats_cache_key(True) != make_market_stats_cache_key(False)


def test_market_stats_cache_hit_skips_upstream(monkeypatch):
    """Second call within 60s does NOT re-invoke upstream methods.

    Pins the cache wiring in `cached_lookup` / `cached_store`. Without
    this test, a regression that bypasses the cache layer would pass
    every other test in this file.

    Uses a fresh client built without the cache-disabled override so
    the route's `cached_lookup` actually finds an entry on the second
    call.
    """
    # Override the cache-disabled default just for THIS test.
    monkeypatch.setenv("ENABLE_API_CACHE", "true")
    # Force a fresh app import so the env var takes effect.
    import importlib

    import stock_data.server as server_module
    importlib.reload(server_module)
    fresh_client = TestClient(server_module.app)

    quotes = [_make_quote("600000", 1.0)]
    boards = [{"code": "BK0001", "name": "X", "change_pct": 0.5}]
    fake_manager = MagicMock()
    fake_manager.get_realtime_quotes.return_value = (quotes, "akshare")
    monkeypatch.setattr(agent_module, "get_manager", lambda: fake_manager)
    fake_cache = MagicMock()
    fake_cache.get_board_list.return_value = (boards, "ths")
    monkeypatch.setattr(agent_module, "stock_board_cache", fake_cache)

    from stock_data.api.cache import get_quote_cache
    get_quote_cache().clear()

    # First call → upstream invoked
    resp1 = fresh_client.get("/api/v1/agent/market-stats")
    assert resp1.status_code == 200
    assert fake_manager.get_realtime_quotes.call_count == 1
    assert fake_cache.get_board_list.call_count == 1

    # Second call within 60s → cache hit, NO upstream calls
    resp2 = fresh_client.get("/api/v1/agent/market-stats")
    assert resp2.status_code == 200
    assert resp2.json() == resp1.json()  # bit-for-bit identical payload
    assert fake_manager.get_realtime_quotes.call_count == 1  # still 1
    assert fake_cache.get_board_list.call_count == 1        # still 1

    # Restore cache-disabled state so other tests don't see TTL leaks.
    monkeypatch.setenv("ENABLE_API_CACHE", "false")
