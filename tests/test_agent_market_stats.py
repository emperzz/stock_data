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
    """Happy path — all 3 blocks populated, summary reports 3/3 ok."""
    quotes = [_make_quote("600000", 1.0), _make_quote("600001", -1.0), _make_quote("600002", 0.0)]
    boards = [{"code": "BK0001", "name": "X", "change_pct": 0.5}]
    fake_manager = _patch_manager(monkeypatch, quotes=quotes)
    fake_manager.get_zt_pool.return_value = ([], "akshare", None)
    _patch_board_cache(monkeypatch, all_boards_payload=(boards, "ths"))

    resp = client.get("/api/v1/agent/market-stats")
    assert resp.status_code == 200
    body = resp.json()
    assert body["stocks"]["sample_size"] == 3
    assert body["boards"]["sample_size"] == 1
    assert body["limit_pools"] is not None
    assert body["limit_pools"]["zt"] == []
    assert body["limit_pools"]["dt"] == []
    assert body["errors"] == []
    assert body["summary"]["requested"] == 3
    assert body["summary"]["ok"] == 3


# ----- error isolation -----


def test_stocks_upstream_failure_does_not_affect_boards(client, monkeypatch):
    """When get_realtime_quotes raises, stocks=null but boards + pools are still populated."""
    fake_manager = MagicMock()
    fake_manager.get_realtime_quotes.side_effect = DataFetchError("upstream down")
    fake_manager.get_zt_pool.return_value = ([], "akshare", None)
    monkeypatch.setattr(agent_module, "get_manager", lambda: fake_manager)
    boards = [{"code": "BK0001", "name": "X", "change_pct": 0.5}]
    _patch_board_cache(monkeypatch, all_boards_payload=(boards, "ths"))

    resp = client.get("/api/v1/agent/market-stats")
    assert resp.status_code == 200
    body = resp.json()
    assert body["stocks"] is None
    assert body["boards"] is not None
    assert body["limit_pools"] is not None
    assert any(e["block"] == "stocks" for e in body["errors"])
    assert body["summary"]["ok"] == 2
    assert body["summary"]["failed"] == 1


def test_boards_upstream_failure_does_not_affect_stocks(client, monkeypatch):
    """Symmetric — boards=null but stocks + pools still populated."""
    quotes = [_make_quote("600000", 1.0)]
    fake_manager = _patch_manager(monkeypatch, quotes=quotes)
    fake_manager.get_zt_pool.return_value = ([], "akshare", None)
    fake_cache = MagicMock()
    fake_cache.get_board_list.side_effect = ValueError("cid_unresolved")
    monkeypatch.setattr(agent_module, "stock_board_cache", fake_cache)

    resp = client.get("/api/v1/agent/market-stats")
    assert resp.status_code == 200
    body = resp.json()
    assert body["stocks"] is not None
    assert body["boards"] is None
    assert body["limit_pools"] is not None
    assert any(e["block"] == "boards" for e in body["errors"])
    assert body["summary"]["ok"] == 2


def test_both_blocks_fail(client, monkeypatch):
    """Stocks + boards fail, pools succeed — 2 errors, summary.ok=1, requested=3."""
    fake_manager = MagicMock()
    fake_manager.get_realtime_quotes.side_effect = DataFetchError("stocks down")
    fake_manager.get_zt_pool.return_value = ([], "akshare", None)
    monkeypatch.setattr(agent_module, "get_manager", lambda: fake_manager)
    fake_cache = MagicMock()
    fake_cache.get_board_list.side_effect = RuntimeError("boards down")
    monkeypatch.setattr(agent_module, "stock_board_cache", fake_cache)

    resp = client.get("/api/v1/agent/market-stats")
    assert resp.status_code == 200
    body = resp.json()
    assert body["stocks"] is None
    assert body["boards"] is None
    assert body["limit_pools"] is not None
    assert len(body["errors"]) == 2
    assert body["summary"]["ok"] == 1
    assert body["summary"]["requested"] == 3


# ----- include_boards toggle -----


def test_include_boards_false_skips_boards_upstream(client, monkeypatch):
    """?include_boards=false must NOT invoke any boards upstream call (pools still on)."""
    quotes = [_make_quote("600000", 1.0)]
    fake_manager = MagicMock()
    fake_manager.get_realtime_quotes.return_value = (quotes, "akshare")
    fake_manager.get_zt_pool.return_value = ([], "akshare", None)
    monkeypatch.setattr(agent_module, "get_manager", lambda: fake_manager)
    fake_cache = MagicMock()
    monkeypatch.setattr(agent_module, "stock_board_cache", fake_cache)

    resp = client.get("/api/v1/agent/market-stats?include_boards=false")
    assert resp.status_code == 200
    body = resp.json()
    assert body["stocks"] is not None
    assert body["boards"] is None
    assert body["limit_pools"] is not None
    assert body["errors"] == []
    assert body["summary"]["requested"] == 2
    assert body["summary"]["ok"] == 2
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


def test_cache_key_includes_all_three_dimensions():
    """Cache key includes include_boards, include_pools, and trade_date.

    All three knobs produce distinct cache entries because changing
    any of them produces a materially different response.
    """
    assert make_market_stats_cache_key(True, True, "2026-09-02") == (
        "agent_market_stats:True:True:2026-09-02"
    )
    assert make_market_stats_cache_key(False, True, "2026-09-02") == (
        "agent_market_stats:False:True:2026-09-02"
    )
    assert make_market_stats_cache_key(True, False, "2026-09-02") == (
        "agent_market_stats:True:False:2026-09-02"
    )
    assert make_market_stats_cache_key(True, True, "2026-09-01") == (
        "agent_market_stats:True:True:2026-09-01"
    )
    # All four are distinct entries
    keys = {
        make_market_stats_cache_key(True, True, "2026-09-02"),
        make_market_stats_cache_key(False, True, "2026-09-02"),
        make_market_stats_cache_key(True, False, "2026-09-02"),
        make_market_stats_cache_key(True, True, "2026-09-01"),
    }
    assert len(keys) == 4


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
    fake_manager.get_zt_pool.return_value = ([], "akshare", None)
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
    assert fake_manager.get_zt_pool.call_count == 2  # zt + dt

    # Second call within 60s → cache hit, NO upstream calls
    resp2 = fresh_client.get("/api/v1/agent/market-stats")
    assert resp2.status_code == 200
    assert resp2.json() == resp1.json()  # bit-for-bit identical payload
    assert fake_manager.get_realtime_quotes.call_count == 1  # still 1
    assert fake_cache.get_board_list.call_count == 1  # still 1
    assert fake_manager.get_zt_pool.call_count == 2  # cache hit

    # Restore cache-disabled state so other tests don't see TTL leaks.
    monkeypatch.setenv("ENABLE_API_CACHE", "false")


# ----- pools block (post-2026-09-02) -----


def _patch_zt_pool(monkeypatch, *, zt_value=([], "akshare", None), dt_value=([], "akshare", None)):
    """Patch manager.get_zt_pool + the other market-stats upstreams.

    Each of ``zt_value`` / ``dt_value`` is either:
    - a 3-tuple ``(rows, src, error_reason)`` — returned to the caller
      at the matching call
    - an ``Exception`` instance — raised at the matching call

    MagicMock's ``side_effect`` accepts a list of mixed return-or-raise
    values, so we just pass the args straight through.
    """
    fake_manager = MagicMock()
    fake_manager.get_zt_pool.side_effect = [zt_value, dt_value]
    fake_manager.get_realtime_quotes.return_value = (
        [_make_quote("600000", 1.0)],
        "akshare",
    )
    monkeypatch.setattr(agent_module, "get_manager", lambda: fake_manager)
    fake_cache = MagicMock()
    fake_cache.get_board_list.return_value = (
        [{"code": "BK0001", "name": "X", "change_pct": 0.5}],
        "ths",
    )
    monkeypatch.setattr(agent_module, "stock_board_cache", fake_cache)
    return fake_manager


class TestMarketStatsPoolsBlock:
    def test_happy_path_includes_pools(self, client, monkeypatch):
        """Default request includes pools block; summary.requested=3."""
        _patch_zt_pool(
            monkeypatch,
            zt_value=([{"code": "600519", "name": "茅台"}], "akshare", None),
            dt_value=([{"code": "000001", "name": "平安"}], "akshare", None),
        )
        resp = client.get("/api/v1/agent/market-stats")
        assert resp.status_code == 200
        body = resp.json()
        assert body["limit_pools"] is not None
        assert len(body["limit_pools"]["zt"]) == 1
        assert len(body["limit_pools"]["dt"]) == 1
        assert body["limit_pools"]["zt"][0]["code"] == "600519"
        assert body["errors"] == []
        assert body["summary"]["requested"] == 3
        assert body["summary"]["ok"] == 3

    def test_zt_pool_failure_isolates_dt(self, client, monkeypatch):
        """zt upstream raises → zt=null, dt populated, errors[] has zt_pool entry."""
        _patch_zt_pool(
            monkeypatch,
            zt_value=DataFetchError("zt down"),
            dt_value=([{"code": "000001"}], "akshare", None),
        )
        resp = client.get("/api/v1/agent/market-stats")
        assert resp.status_code == 200
        body = resp.json()
        assert body["limit_pools"]["zt"] is None
        assert body["limit_pools"]["dt"] is not None
        assert len(body["limit_pools"]["dt"]) == 1
        zt_errs = [e for e in body["errors"] if e["block"] == "zt_pool"]
        assert len(zt_errs) == 1
        assert "zt down" in zt_errs[0]["message"]
        assert body["summary"]["ok"] == 3

    def test_dt_pool_failure_isolates_zt(self, client, monkeypatch):
        """Symmetric — dt fails, zt populated."""
        _patch_zt_pool(
            monkeypatch,
            zt_value=([{"code": "600519"}], "akshare", None),
            dt_value=DataFetchError("dt down"),
        )
        resp = client.get("/api/v1/agent/market-stats")
        assert resp.status_code == 200
        body = resp.json()
        assert body["limit_pools"]["zt"] is not None
        assert body["limit_pools"]["dt"] is None
        dt_errs = [e for e in body["errors"] if e["block"] == "dt_pool"]
        assert len(dt_errs) == 1
        assert body["summary"]["ok"] == 3

    def test_both_pools_fail(self, client, monkeypatch):
        """Both raise → both null, 2 pool errors, ok still 3."""
        _patch_zt_pool(
            monkeypatch,
            zt_value=DataFetchError("zt down"),
            dt_value=DataFetchError("dt down"),
        )
        resp = client.get("/api/v1/agent/market-stats")
        body = resp.json()
        assert body["limit_pools"]["zt"] is None
        assert body["limit_pools"]["dt"] is None
        assert len(body["errors"]) == 2
        blocks = {e["block"] for e in body["errors"]}
        assert blocks == {"zt_pool", "dt_pool"}
        assert body["summary"]["ok"] == 3

    def test_pools_empty_passthrough(self, client, monkeypatch):
        """Upstream returns [] for both → both [] in response, no errors."""
        _patch_zt_pool(monkeypatch)
        resp = client.get("/api/v1/agent/market-stats")
        body = resp.json()
        assert body["limit_pools"]["zt"] == []
        assert body["limit_pools"]["dt"] == []
        assert body["errors"] == []
        assert body["summary"]["ok"] == 3

    def test_include_pools_false_skips_pools_upstream(self, client, monkeypatch):
        """?include_pools=false → no upstream pool call, field present with both null, requested=2."""
        fake_manager = MagicMock()
        fake_manager.get_realtime_quotes.return_value = ([_make_quote("600000", 1.0)], "akshare")
        monkeypatch.setattr(agent_module, "get_manager", lambda: fake_manager)
        fake_cache = MagicMock()
        fake_cache.get_board_list.return_value = (
            [{"code": "BK0001", "name": "X", "change_pct": 0.5}],
            "ths",
        )
        monkeypatch.setattr(agent_module, "stock_board_cache", fake_cache)

        resp = client.get("/api/v1/agent/market-stats?include_pools=false")
        body = resp.json()
        assert body["limit_pools"] is not None
        assert body["limit_pools"]["zt"] is None
        assert body["limit_pools"]["dt"] is None
        assert body["errors"] == []
        assert body["summary"]["requested"] == 2
        assert body["summary"]["ok"] == 2
        fake_manager.get_zt_pool.assert_not_called()

    def test_pools_trade_date_passed_through(self, client, monkeypatch):
        """?trade_date=2026-09-01 → manager.get_zt_pool called twice with date='2026-09-01'."""
        fake_manager = _patch_zt_pool(
            monkeypatch,
            zt_value=([{"code": "600519"}], "akshare", None),
            dt_value=([{"code": "000001"}], "akshare", None),
        )
        client.get("/api/v1/agent/market-stats?trade_date=2026-09-01")
        calls = fake_manager.get_zt_pool.call_args_list
        assert len(calls) == 2, f"expected 2 calls, got {len(calls)}"
        seen_pool_types = set()
        for call in calls:
            assert call.kwargs.get("date") == "2026-09-01", (
                f"expected date=2026-09-01, got {call.kwargs.get('date')!r}"
            )
            seen_pool_types.add(call.kwargs.get("pool_type"))
        assert seen_pool_types == {"zt", "dt"}

    def test_pools_trade_date_malformed_400(self, client):
        """?trade_date=not-a-date → 400 with invalid_trade_date code (matches market-context)."""
        resp = client.get("/api/v1/agent/market-stats?trade_date=not-a-date")
        assert resp.status_code == 400
        body = resp.json()
        # FastAPI wraps HTTPException(detail=...) so the error is at body["detail"]
        assert body["detail"]["error"] == "invalid_trade_date"
        assert "trade_date" in body["detail"]["message"]

    def test_pools_trade_date_default_to_latest_trade_date(self, client, monkeypatch):
        """Omit ?trade_date → handler resolves via get_latest_trade_date_on_or_before."""
        fake_manager = _patch_zt_pool(
            monkeypatch,
            zt_value=([{"code": "600519"}], "akshare", None),
            dt_value=([{"code": "000001"}], "akshare", None),
        )
        client.get("/api/v1/agent/market-stats")
        for call in fake_manager.get_zt_pool.call_args_list:
            assert call.kwargs.get("date"), "date must be non-empty (trade_calendar default)"

    def test_pools_cache_hit(self, client, monkeypatch):
        """Second call with same params → cache hit, no new pool upstream calls."""
        monkeypatch.setenv("ENABLE_API_CACHE", "true")
        import importlib

        import stock_data.server as server_module

        importlib.reload(server_module)
        from fastapi.testclient import TestClient

        fresh_client = TestClient(server_module.app)

        fake_manager = _patch_zt_pool(
            monkeypatch,
            zt_value=([{"code": "600519"}], "akshare", None),
            dt_value=([{"code": "000001"}], "akshare", None),
        )
        from stock_data.api.cache import get_quote_cache

        get_quote_cache().clear()

        fresh_client.get("/api/v1/agent/market-stats?trade_date=2026-09-01")
        assert fake_manager.get_zt_pool.call_count == 2

        fresh_client.get("/api/v1/agent/market-stats?trade_date=2026-09-01")
        assert fake_manager.get_zt_pool.call_count == 2  # cache hit

        monkeypatch.setenv("ENABLE_API_CACHE", "false")

    def test_format_md_renders_pools_section(self, client, monkeypatch):
        """?format=md → body contains ## 涨跌停 + zt 8-col + dt 7-col tables.

        Field names match ZTPoolStock (schemas.py) — see spec
        docs/superpowers/specs/2026-09-02-market-context-and-market-stats-redesign-design.md.
        Renderer previously looked up fossil names (limit_time / limit_count / industry)
        that no fetcher populates; this test pins the real names.
        """
        _patch_zt_pool(
            monkeypatch,
            zt_value=(
                [
                    {
                        "code": "600519",
                        "name": "茅台",
                        "change_pct": 10.0,
                        "first_seal_time": "09:30:00",
                        "last_seal_time": "09:30:00",
                        "lb_count": 2,
                        "turnover_pct": 0.85,
                        "seal_amount": 12345678.0,
                    }
                ],
                "akshare",
                None,
            ),
            dt_value=(
                [
                    {
                        "code": "000001",
                        "name": "平安",
                        "change_pct": -10.0,
                        "first_seal_time": "14:00:00",
                        "last_seal_time": "14:00:00",
                        "lb_count": 1,
                        "turnover_pct": 0.42,
                    }
                ],
                "akshare",
                None,
            ),
        )
        resp = client.get("/api/v1/agent/market-stats?format=md")
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("text/markdown")
        body = resp.text
        assert "## 涨跌停" in body
        assert "**涨停池**: 1 只" in body
        assert "**跌停池**: 1 只" in body
        # ZT 8 列：首次/最后涨停时间 是独立两列；封单金额与换手率补全；所属行业不在 schema。
        assert (
            "| 代码 | 名称 | 涨跌幅 | 首次涨停时间 | 最后涨停时间 | "
            "连板数 | 换手率 | 封单金额 |"
        ) in body
        # DT 7 列：跌停无 封单金额 字段，schema 未声明。
        assert (
            "| 代码 | 名称 | 涨跌幅 | 首次跌停时间 | 最后跌停时间 | "
            "连板数 | 换手率 |"
        ) in body
        # ZT 行：换手率 2 位小数无符号 + 封单金额用千分位整数（元）。
        assert (
            "| 600519 | 茅台 | +10.00% | 09:30:00 | 09:30:00 | "
            "2 | 0.85% | 12,345,678 |"
        ) in body
        # DT 行：连板数 = 1，跌停时长字段直接打印上游字符串。
        assert (
            "| 000001 | 平安 | -10.00% | 14:00:00 | 14:00:00 | "
            "1 | 0.42% |"
        ) in body
        # 负向：旧的化石列头不应再出现。
        assert "涨停时间 | 连板数 | 所属行业" not in body
        assert "跌停时间 | 所属行业" not in body

    def test_format_md_renders_null_pools_when_disabled(self, client, monkeypatch):
        """?include_pools=false&format=md → body contains ## 涨跌停 + null markers."""
        _patch_zt_pool(monkeypatch)
        resp = client.get("/api/v1/agent/market-stats?include_pools=false&format=md")
        body = resp.text
        assert "## 涨跌停" in body
        assert "**涨停池**: null" in body
        assert "**跌停池**: null" in body
