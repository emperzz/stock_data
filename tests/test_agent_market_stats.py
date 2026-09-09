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
    """Patch the manager method the route uses.

    NOTE: the route calls ``manager.get_realtime_quotes`` (stocks
    block) AND ``manager.get_zt_pool`` (limit_pools block, when
    ``include_pools=True`` — the default). The boards block goes
    through ``stock_board_cache.get_board_list`` (see
    ``_patch_board_cache``), so no ``get_all_boards`` stub is needed.
    """
    fake_manager = MagicMock()
    fake_manager.get_realtime_quotes.return_value = (quotes, "akshare")
    # zt/dt pools: default to empty pool (route treats this as success).
    # Tuple shape matches manager.get_zt_pool: (pool, source, warning).
    fake_manager.get_zt_pool.return_value = ([], "akshare", None)
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
            "| 代码 | 名称 | 涨跌幅 | 首次涨停时间 | 最后涨停时间 | 连板数 | 换手率 | 封单金额 |"
        ) in body
        # DT 7 列：跌停无 封单金额 字段，schema 未声明。
        assert ("| 代码 | 名称 | 涨跌幅 | 首次跌停时间 | 最后跌停时间 | 连板数 | 换手率 |") in body
        # ZT 行：换手率 2 位小数无符号 + 封单金额用千分位整数（元）。
        assert (
            "| 600519 | 茅台 | +10.00% | 09:30:00 | 09:30:00 | 2 | 0.85% | 12,345,678 |"
        ) in body
        # DT 行：连板数 = 1，跌停时长字段直接打印上游字符串。
        assert ("| 000001 | 平安 | -10.00% | 14:00:00 | 14:00:00 | 1 | 0.42% |") in body
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


# ============================================================================
# 2026-09-09: top-3 gainers / top-3 losers helpers
# ============================================================================


def test_build_minimal_quote_from_list_row_dict_populates_six_fields():
    """Only the 6 board-relevant fields present in upstream are filled."""
    from stock_data.api.routes.agent import _build_minimal_quote_from_list_row_dict

    row = {
        "code": "881154",
        "name": "半导体",
        "change_pct": 5.82,
        "volume": 2345678,
        "amount": 12.0,           # THS upstream in 亿元
        "net_inflow": 4.5,        # upstream in 亿元
        "up_count": 23,
        "down_count": 5,
    }
    quote = _build_minimal_quote_from_list_row_dict(row)
    assert quote.change_pct == 5.82
    assert quote.volume == 2345678
    assert quote.volume_unit == "wan_shou"
    assert quote.amount == 12.0 * 1e8            # ×1e8 conversion
    assert quote.up_count == 23
    assert quote.down_count == 5
    assert quote.net_inflow == 4.5               # pass-through (NOT ×1e8)
    # sparse fields stay None
    assert quote.price is None
    assert quote.open is None
    assert quote.high is None
    assert quote.low is None
    assert quote.prev_close is None
    assert quote.change_amount is None
    assert quote.rank is None


def test_build_minimal_quote_handles_missing_fields():
    """All-None quote when row has no quote fields at all."""
    from stock_data.api.routes.agent import _build_minimal_quote_from_list_row_dict

    row = {"code": "BK0001", "name": "X"}  # no quote fields
    quote = _build_minimal_quote_from_list_row_dict(row)
    assert quote.change_pct is None
    assert quote.amount is None
    assert quote.up_count is None
    assert quote.volume_unit == "wan_shou"  # always set


def test_select_top_board_movers_sorts_correctly():
    """Top 3 by change_pct DESC, bottom 3 by ASC.

    Per spec §3.1 — BOTH lists mirror the same eligible set. With 6
    eligible rows and top_n=3, both lists have length 3 (NOT a sign
    filter that would yield 3 gainers + 3 losers from a pos/neg split).
    This test pins that invariant.
    """
    from stock_data.api.routes.agent import _select_top_board_movers

    rows = [
        {"code": "BK0001", "name": "A", "type": "industry", "subtype": "881", "source": "ths", "change_pct": 1.0},
        {"code": "BK0002", "name": "B", "type": "industry", "subtype": "881", "source": "ths", "change_pct": 5.0},
        {"code": "BK0003", "name": "C", "type": "industry", "subtype": "881", "source": "ths", "change_pct": -2.0},
        {"code": "BK0004", "name": "D", "type": "industry", "subtype": "881", "source": "ths", "change_pct": 3.0},
        {"code": "BK0005", "name": "E", "type": "industry", "subtype": "881", "source": "ths", "change_pct": -5.0},
        {"code": "BK0006", "name": "F", "type": "industry", "subtype": "881", "source": "ths", "change_pct": 2.0},
    ]
    gainers, losers = _select_top_board_movers(rows, top_n=3)
    assert len(gainers) == 3
    assert len(losers) == 3
    # gainers sorted DESC: BK0002 (5.0), BK0004 (3.0), BK0006 (2.0)
    assert [g.code for g in gainers] == ["BK0002", "BK0004", "BK0006"]
    # losers sorted ASC: BK0005 (-5.0), BK0003 (-2.0), BK0001 (1.0)
    assert [l.code for l in losers] == ["BK0005", "BK0003", "BK0001"]


def test_select_top_board_movers_excludes_none_change_pct():
    """Rows with None / non-numeric change_pct are skipped."""
    from stock_data.api.routes.agent import _select_top_board_movers

    rows = [
        {"code": "BK0001", "change_pct": 2.0},
        {"code": "BK0002", "change_pct": None},
        {"code": "BK0003", "change_pct": "—"},        # upstream sentinel
        {"code": "BK0004", "change_pct": 1.0},
        {"code": "BK0005"},                          # missing key
    ]
    gainers, losers = _select_top_board_movers(rows, top_n=3)
    codes = {g.code for g in gainers}
    assert codes == {"BK0001", "BK0004"}            # only 2 valid rows
    assert all(l.code in {"BK0001", "BK0004"} for l in losers)


def test_select_top_board_movers_tie_break_code_asc():
    """Identical change_pct → sorted by code ASC (deterministic)."""
    from stock_data.api.routes.agent import _select_top_board_movers

    rows = [
        {"code": "BK0009", "change_pct": 2.0},
        {"code": "BK0001", "change_pct": 2.0},
        {"code": "BK0005", "change_pct": 2.0},
        {"code": "BK0003", "change_pct": 2.0},
    ]
    gainers, _ = _select_top_board_movers(rows, top_n=3)
    assert [g.code for g in gainers] == ["BK0001", "BK0003", "BK0005"]


def test_select_top_board_movers_fewer_than_three():
    """When fewer than 3 rows qualify, both lists mirror the available rows.

    Per spec §3.1 — there is NO sign filter. With 2 eligible rows and
    top_n=3, both lists have length 2 (NOT 1 gainer + 1 loser); the 2
    rows appear in both lists at different ranks. This test pins that
    invariant.
    """
    from stock_data.api.routes.agent import _select_top_board_movers

    rows = [
        {"code": "BK0001", "change_pct": 2.0},
        {"code": "BK0002", "change_pct": -1.0},
    ]
    gainers, losers = _select_top_board_movers(rows, top_n=3)
    assert len(gainers) == 2
    assert len(losers) == 2
    # gainers sorted DESC: BK0001 (+2.0), BK0002 (-1.0)
    assert [g.code for g in gainers] == ["BK0001", "BK0002"]
    # losers sorted ASC: BK0002 (-1.0), BK0001 (+2.0) — same set, reversed order
    assert [l.code for l in losers] == ["BK0002", "BK0001"]


def test_select_top_board_movers_empty_input():
    """Empty / None input → two empty lists (no exception)."""
    from stock_data.api.routes.agent import _select_top_board_movers

    assert _select_top_board_movers([], top_n=3) == ([], [])
    assert _select_top_board_movers(None, top_n=3) == ([], [])


def test_select_top_board_movers_entry_carries_minimal_quote():
    """Each BoardMoverEntry.quote is built via the quote helper."""
    from stock_data.api.routes.agent import _select_top_board_movers

    rows = [{"code": "BK0001", "name": "半导体", "type": "industry", "subtype": "881",
             "source": "ths", "change_pct": 5.82, "volume": 2345678, "amount": 12.0,
             "up_count": 23, "down_count": 5, "net_inflow": 4.5}]
    gainers, _ = _select_top_board_movers(rows, top_n=3)
    assert gainers[0].code == "BK0001"
    assert gainers[0].name == "半导体"
    assert gainers[0].type == "industry"
    assert gainers[0].source == "ths"
    assert gainers[0].quote is not None
    assert gainers[0].quote.change_pct == 5.82
    assert gainers[0].quote.amount == 12.0 * 1e8


# ============================================================================
# 2026-09-09: boards block integration tests for top_gainers / top_losers
# ============================================================================


def test_boards_top_gainers_top_losers_in_response(client, monkeypatch):
    """Happy path: top_gainers and top_losers appear on the boards block.

    Per spec §3.1 — both lists mirror the same eligible set. With 3
    eligible rows + top_n=3, BOTH lists have length 3 (NOT a sign
    filter that would yield 3 gainers + 1 loser). This test pins that
    invariant.
    """
    boards_payload = (
        [
            {"code": "BK0001", "name": "A", "type": "industry", "subtype": "881",
             "source": "ths", "change_pct": 5.82, "volume": 100, "amount": 1.0,
             "up_count": 10, "down_count": 2, "net_inflow": 0.5},
            {"code": "BK0002", "name": "B", "type": "industry", "subtype": "881",
             "source": "ths", "change_pct": -3.0, "volume": 50, "amount": 0.5,
             "up_count": 2, "down_count": 8, "net_inflow": -0.3},
            {"code": "BK0003", "name": "C", "type": "industry", "subtype": "881",
             "source": "ths", "change_pct": 2.0, "volume": 80, "amount": 0.8,
             "up_count": 8, "down_count": 4, "net_inflow": 0.2},
        ],
        "ths",
    )
    _patch_manager(monkeypatch, quotes=[_make_quote("600519", 1.0)])
    _patch_board_cache(monkeypatch, all_boards_payload=boards_payload)

    resp = client.get("/api/v1/agent/market-stats")
    assert resp.status_code == 200
    data = resp.json()
    assert data["boards"] is not None
    assert len(data["boards"]["top_gainers"]) == 3       # mirrors all 3 eligible rows
    assert len(data["boards"]["top_losers"]) == 3
    # gainers sorted DESC: BK0001 (5.82), BK0003 (2.0), BK0002 (-3.0)
    assert [g["code"] for g in data["boards"]["top_gainers"]] == ["BK0001", "BK0003", "BK0002"]
    # losers sorted ASC: BK0002 (-3.0), BK0003 (2.0), BK0001 (5.82)
    assert [l["code"] for l in data["boards"]["top_losers"]] == ["BK0002", "BK0003", "BK0001"]
    # quote fields populated correctly
    top1 = data["boards"]["top_gainers"][0]
    assert top1["code"] == "BK0001"
    assert top1["quote"]["change_pct"] == 5.82
    assert top1["quote"]["amount"] == 1.0 * 1e8
    assert top1["quote"]["net_inflow"] == 0.5           # ×1e8 conversion only applies to `amount`


def test_boards_top_movers_absent_when_upstream_raises(client, monkeypatch):
    """Boards block fails → boards=None → top_gainers field absent in JSON."""
    _patch_manager(monkeypatch, quotes=[_make_quote("600519", 1.0)])
    fake_cache = MagicMock()
    fake_cache.get_board_list.side_effect = DataFetchError("ths down")
    monkeypatch.setattr(agent_module, "stock_board_cache", fake_cache)

    resp = client.get("/api/v1/agent/market-stats")
    assert resp.status_code == 200
    body_text = resp.text
    assert '"boards": null' in body_text or '"boards":null' in body_text
    assert "top_gainers" not in body_text               # field absent because parent is absent
    assert any(e["block"] == "boards" for e in resp.json()["errors"])


def test_boards_top_movers_empty_when_upstream_returns_empty(client, monkeypatch):
    """Boards upstream returns [] → boards block present but top_* empty."""
    _patch_manager(monkeypatch, quotes=[_make_quote("600519", 1.0)])
    _patch_board_cache(monkeypatch, all_boards_payload=([], "ths"))

    resp = client.get("/api/v1/agent/market-stats")
    assert resp.status_code == 200
    data = resp.json()
    assert data["boards"] is not None
    assert data["boards"]["top_gainers"] == []
    assert data["boards"]["top_losers"] == []
    assert data["boards"]["sample_size"] == 0           # existing aggregate still works
    assert not any(e["block"] == "boards" for e in data["errors"])  # empty != error


def test_boards_top_movers_skipped_when_include_boards_false(client, monkeypatch):
    """include_boards=False → no boards block, no top_movers, no upstream call."""
    _patch_manager(monkeypatch, quotes=[_make_quote("600519", 1.0)])
    fake_cache = MagicMock()
    fake_cache.get_board_list.return_value = ([], "ths")
    monkeypatch.setattr(agent_module, "stock_board_cache", fake_cache)

    resp = client.get("/api/v1/agent/market-stats?include_boards=false")
    assert resp.status_code == 200
    body_text = resp.text
    assert "top_gainers" not in body_text
    assert "top_losers" not in body_text
    fake_cache.get_board_list.assert_not_called()       # upstream must be skipped


# ============================================================================
# 2026-09-09: MD renderer for top movers
# ============================================================================


def test_market_stats_md_includes_top_movers_sections(client, monkeypatch):
    """MD output contains ### 涨幅前三 + ### 跌幅前三 with data rows.

    Pins the 8-column table contract per spec §5.2 — a regression that
    emits 7 or 9 columns would silently pass the loose substring
    checks, so we pin the exact header row + separator row.
    """
    from stock_data.api.schemas import BoardMoverEntry, MinimalQuote
    boards_payload = (
        [
            {"code": "BK0001", "name": "半导体", "type": "industry", "subtype": "881",
             "source": "ths", "change_pct": 5.82, "volume": 2345678, "amount": 12.0,
             "up_count": 23, "down_count": 5, "net_inflow": 4.5},
            {"code": "BK0002", "name": "煤炭", "type": "industry", "subtype": "881",
             "source": "ths", "change_pct": -3.15, "volume": 1000000, "amount": 5.0,
             "up_count": 2, "down_count": 18, "net_inflow": -2.1},
        ],
        "ths",
    )
    _patch_manager(monkeypatch, quotes=[_make_quote("600519", 1.0)])
    _patch_board_cache(monkeypatch, all_boards_payload=boards_payload)

    resp = client.get("/api/v1/agent/market-stats?format=md")
    assert resp.status_code == 200
    md = resp.text
    assert "### 涨幅前三" in md
    assert "### 跌幅前三" in md
    assert "BK0001" in md
    assert "半导体" in md
    assert "+5.82%" in md                                  # signed pct
    assert "BK0002" in md
    assert "煤炭" in md
    assert "-3.15%" in md
    # 8-column contract pin: exact header + separator row.
    # CLAUDE.md no-data-dropped invariant is enforced via the literal
    # header string match (not just `"| 代码 |" in md` which would also
    # match 7- or 9-column variants).
    expected_header = "| 代码 | 名称 | 涨跌幅 | 成交额(亿) | 成交量(万手) | 上涨 | 下跌 | 资金净流入(亿) |"
    expected_sep = "|---|---|---|---|---|---|---|---|"
    assert expected_header in md
    assert expected_sep in md
    # net_inflow unit clarification: pass-through 亿元 (NOT ×1e8 to 元)
    assert "4.50" in md                                     # upstream 4.5 → "4.50" via _md_num(2)
    assert "-2.10" in md


def test_market_stats_md_empty_movers_emits_explicit_marker(client, monkeypatch):
    """MD output emits ### 涨幅前三 + （无数据）, NOT a bare empty table skeleton."""
    _patch_manager(monkeypatch, quotes=[_make_quote("600519", 1.0)])
    _patch_board_cache(monkeypatch, all_boards_payload=([], "ths"))

    resp = client.get("/api/v1/agent/market-stats?format=md")
    assert resp.status_code == 200
    md = resp.text
    assert "### 涨幅前三" in md
    assert "### 跌幅前三" in md
    # Two explicit empty markers (one per heading) — NOT a bare "| 代码 |..." header
    # followed by zero data rows.
    assert md.count("（无数据）") >= 2


def test_market_stats_md_no_top_movers_when_include_boards_false(client, monkeypatch):
    """include_boards=false → no boards MD section, no top_movers headings."""
    _patch_manager(monkeypatch, quotes=[_make_quote("600519", 1.0)])
    fake_cache = MagicMock()
    fake_cache.get_board_list.return_value = ([], "ths")
    monkeypatch.setattr(agent_module, "stock_board_cache", fake_cache)

    resp = client.get("/api/v1/agent/market-stats?include_boards=false&format=md")
    assert resp.status_code == 200
    md = resp.text
    assert "### 涨幅前三" not in md
    assert "### 跌幅前三" not in md
