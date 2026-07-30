"""
Integration tests for API routes using FastAPI TestClient.

These tests exercise real API routes end-to-end; some fan out to upstream
fetchers and may hit network flakiness. The module-level
``@pytest.mark.live_network`` marker lets ``tests/conftest.py`` reclassify
upstream/network errors as ``x`` (xfail) rather than ``F`` (failed). See
``tests/_network_guard.py`` for the full legend.
"""

import pytest
from fastapi.testclient import TestClient

from stock_data.api.routes import reset_manager
from stock_data.server import app

# Mark the whole module: routes that fan out to fetchers may hit upstream
# flakiness. The hook reclassifies network errors to xfail.
pytestmark = pytest.mark.live_network


@pytest.fixture(autouse=True)
def reset_before_test():
    """Reset manager state before each test."""
    reset_manager()
    # Clear the route-level TTLCaches so per-test monkeypatched fetchers
    # aren't masked by a previous test's cached payload. Without this,
    # the new TestListStocks cases (which patch manager.get_realtime_quotes
    # and stock_list.get_stock_list) see stale rows from earlier tests.
    from stock_data.api.cache import get_stock_list_cache, get_stock_list_quote_cache
    get_stock_list_cache().clear()
    get_stock_list_quote_cache().clear()
    yield


@pytest.fixture
def client():
    return TestClient(app)


class TestHealthCheck:
    """Tests for /healthz endpoint (k8s/lb convention; root path, not under /api/v1)."""

    def test_health_returns_ok(self, client):
        response = client.get("/healthz")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        # New schema: `sources` is None unless ?details=true
        assert "sources" in data
        assert data["sources"] is None

    def test_health_with_details_returns_sources(self, client):
        response = client.get("/healthz?details=true")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] in ("ok", "degraded", "unhealthy")
        assert isinstance(data["sources"], list)
        for s in data["sources"]:
            assert "name" in s
            assert "state" in s
            assert "available" in s

    def test_health_includes_unregistered_fetchers(self, client):
        """/healthz must surface ALL BaseFetcher subclasses, not just registered ones.

        Without TUSHARE_TOKEN / ZHITU_TOKEN, those fetchers aren't registered
        with the manager — but operators still need to see them in the health
        report so they can tell missing-config from a runtime outage. The
        field is `available: false` plus a logic-driven `unavailable_reason`.
        """
        from stock_data.data_provider.base import BaseFetcher

        # Compute the full expected set of fetcher names.
        expected: set[str] = set()
        stack: list[type] = list(BaseFetcher.__subclasses__())
        while stack:
            c = stack.pop()
            expected.add(getattr(c, "name", c.__name__))
            stack.extend(c.__subclasses__())

        response = client.get("/healthz?details=true")
        data = response.json()
        actual_names = {s["name"] for s in data["sources"]}
        # Must include every BaseFetcher subclass, registered or not.
        missing = expected - actual_names
        assert not missing, (
            f"/healthz omitted these fetcher classes: {sorted(missing)}. "
            f"Expected all BaseFetcher subclasses to appear in sources[]. "
            f"Got: {sorted(actual_names)}"
        )

    def test_health_unavailable_fetchers_have_logic_driven_reason(self, client):
        """For unregistered fetchers (Tushare/Zhitu without tokens),
        `unavailable_reason` must be a non-empty string derived from real
        state, not a hardcoded label. Tests the same logic-driven contract
        enforced for /control/api-manifest's fetchers[].
        """
        response = client.get("/healthz?details=true")
        data = response.json()

        unavailable = [s for s in data["sources"] if s["available"] is False]
        assert unavailable, (
            "Expected at least TushareFetcher or ZhituFetcher to appear with "
            "available=False when their tokens aren't configured; otherwise "
            "this test isn't exercising the unregistered path."
        )
        for s in unavailable:
            reason = s.get("unavailable_reason")
            assert reason, (
                f"{s['name']} reported available=false but no "
                f"unavailable_reason — operators need actionable guidance."
            )
            # The reason must mention the env var that gates this fetcher
            # (logic-driven, derived from real _token state).
            assert (
                s["name"].upper().replace("FETCHER", "") in reason.upper()
                or "TOKEN" in reason.upper()
                or "SDK" in reason.upper()
            ), (
                f"{s['name']} reason {reason!r} doesn't name the env var or "
                f"SDK that's missing — should be derived from real state."
            )

    def test_health_status_ignores_unregistered_fetchers(self, client):
        """A missing optional token (Tushare/Zhitu) must NOT flip status to unhealthy.

        Status determination only considers registered fetchers, so operators
        running with no premium tokens still see status='ok' (or 'degraded'
        if a registered fetcher's circuit is open). This matches the
        original pre-refactor contract for k8s/lb probes.
        """
        # Sanity: we know TushareFetcher and ZhituFetcher are unregistered in
        # the default test env (no tokens). Verify the probe isn't unhealthy.
        response = client.get("/healthz")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] != "unhealthy", (
            "status flipped to 'unhealthy' just because Tushare/Zhitu "
            "aren't registered — but those are optional (token-gated). "
            "The probe must stay 'ok' or 'degraded' for k8s/lb readiness."
        )


class TestListIndices:
    """Tests for /api/v1/indices endpoint."""

    def test_list_indices(self, client):
        response = client.get("/api/v1/indices")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        assert len(data) > 0
        # Check structure
        idx = data[0]
        assert "code" in idx
        assert "name" in idx
        assert "market" in idx


class TestListStocks:
    """Tests for /api/v1/stocks endpoint."""

    def test_list_stocks_csi(self, client):
        response = client.get("/api/v1/stocks?market=csi")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        assert len(data) > 0
        # Every record now has the exchange field (may be null)
        for stock in data:
            assert "exchange" in stock
            assert stock["exchange"] is None or isinstance(stock["exchange"], str)

    def test_list_stocks_with_pagination(self, client):
        response = client.get("/api/v1/stocks?market=csi&offset=0&limit=5")
        assert response.status_code == 200
        data = response.json()
        assert len(data) <= 5

    def test_list_stocks_invalid_market(self, client):
        response = client.get("/api/v1/stocks?market=invalid")
        assert response.status_code == 422

    def test_list_stocks_response_has_quote_field(self, client):
        """Backward compat: quote field always present, null when not requested."""
        response = client.get("/api/v1/stocks?market=csi&limit=3")
        assert response.status_code == 200
        data = response.json()
        assert len(data) > 0
        for stock in data:
            assert "quote" in stock
            assert stock["quote"] is None

    def test_list_stocks_response_has_source_field(self, client):
        """Backward compat: source field exists in response (may be empty
        until Task 9 route relocation populates it)."""
        response = client.get("/api/v1/stocks?market=csi&limit=3")
        assert response.status_code == 200
        data = response.json()
        assert len(data) > 0
        for stock in data:
            assert "source" in stock
            assert isinstance(stock["source"], str)

    def test_list_stocks_include_quote_csi_cache_miss(self, client, monkeypatch):
        """include_quote=true with cold cache → manager.get_realtime_quotes called once
        with market="csi" (regression: never accidentally called with hk/us)."""
        from stock_data.data_provider.core.types import (
            RealtimeSource,
            UnifiedRealtimeQuote,
        )
        fake_quotes = [
            UnifiedRealtimeQuote(code="600519", name="贵州茅台",
                                 source=RealtimeSource.AKSHARE, price=1680.5,
                                 change_pct=1.23, amount=2.07e8,
                                 turnover_rate=0.5, total_mv=2.16e12),
            UnifiedRealtimeQuote(code="000001", name="平安银行",
                                 source=RealtimeSource.AKSHARE, price=12.5,
                                 change_pct=-0.5, amount=1.0e8,
                                 turnover_rate=0.3, total_mv=2.4e11),
        ]
        call_log = []
        def fake_get_rt_quotes(market):
            call_log.append(market)
            return list(fake_quotes), "akshare"
        from stock_data.api.routes.helpers import get_manager
        mgr = get_manager()
        monkeypatch.setattr(mgr, "get_realtime_quotes", fake_get_rt_quotes)

        response = client.get("/api/v1/stocks?market=csi&include_quote=true&limit=10")
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 2
        assert data[0]["code"] == "600519"
        assert data[0]["quote"] is not None
        assert data[0]["quote"]["current_price"] == 1680.5
        assert data[0]["source"] == "akshare"
        assert call_log == ["csi"]  # regression: must call with market="csi" exactly once

    def test_list_stocks_include_quote_csi_cache_hit(self, client, monkeypatch):
        """Second request within TTL window → manager.get_realtime_quotes NOT called."""
        from stock_data.data_provider.core.types import (
            RealtimeSource,
            UnifiedRealtimeQuote,
        )
        fake_quotes = [
            UnifiedRealtimeQuote(code="600519", name="贵州茅台",
                                 source=RealtimeSource.AKSHARE, price=1680.5),
        ]
        call_count = {"n": 0}
        def fake_get_rt_quotes(market):
            call_count["n"] += 1
            return list(fake_quotes), "akshare"
        from stock_data.api.routes.helpers import get_manager
        mgr = get_manager()
        monkeypatch.setattr(mgr, "get_realtime_quotes", fake_get_rt_quotes)

        # First request → cache miss → fetcher called
        r1 = client.get("/api/v1/stocks?market=csi&include_quote=true&limit=10")
        assert r1.status_code == 200
        assert call_count["n"] == 1
        # Second request → cache hit → fetcher NOT called again
        r2 = client.get("/api/v1/stocks?market=csi&include_quote=true&limit=10")
        assert r2.status_code == 200
        assert call_count["n"] == 1   # unchanged

    def test_list_stocks_include_quote_exchange_from_code_prefix(self, client, monkeypatch):
        """REGRESSION for code_to_exchange usage: SH/SZ/BJ derived from code prefix."""
        from stock_data.data_provider.core.types import (
            RealtimeSource,
            UnifiedRealtimeQuote,
        )
        fake_quotes = [
            UnifiedRealtimeQuote(code="600519", name="贵州茅台",
                                 source=RealtimeSource.AKSHARE),
            UnifiedRealtimeQuote(code="000001", name="平安银行",
                                 source=RealtimeSource.AKSHARE),
            UnifiedRealtimeQuote(code="830799", name="北交所某股",
                                 source=RealtimeSource.AKSHARE),
        ]
        from stock_data.api.routes.helpers import get_manager
        mgr = get_manager()
        monkeypatch.setattr(mgr, "get_realtime_quotes",
                            lambda market: (fake_quotes, "akshare"))

        response = client.get("/api/v1/stocks?market=csi&include_quote=true")
        assert response.status_code == 200
        data = {s["code"]: s for s in response.json()}
        assert data["600519"]["exchange"] == "SH"
        assert data["000001"]["exchange"] == "SZ"
        assert data["830799"]["exchange"] == "BJ"

    def test_list_stocks_include_quote_does_not_call_stock_list(self, client, monkeypatch):
        """REGRESSION: path B MUST NOT call stock_list.get_stock_list.

        Spec §3.4 explicit decision — joining with persistence would add an
        upstream call and re-introduce the join logic. If a future refactor
        adds the call, this test fails (detected via call_count==0).
        """
        from stock_data.data_provider.core.types import (
            RealtimeSource,
            UnifiedRealtimeQuote,
        )
        from stock_data.data_provider.persistence import stock_list as sl_mod
        fake_quotes = [
            UnifiedRealtimeQuote(code="600519", name="贵州茅台",
                                 source=RealtimeSource.AKSHARE),
        ]
        from stock_data.api.routes.helpers import get_manager
        mgr = get_manager()
        monkeypatch.setattr(mgr, "get_realtime_quotes",
                            lambda market: (fake_quotes, "akshare"))

        call_count = {"n": 0}
        real_get = sl_mod.get_stock_list
        def counting_get(*args, **kwargs):
            call_count["n"] += 1
            return real_get(*args, **kwargs)
        monkeypatch.setattr(sl_mod, "get_stock_list", counting_get)

        response = client.get("/api/v1/stocks?market=csi&include_quote=true")
        assert response.status_code == 200
        assert call_count["n"] == 0   # path B MUST NOT touch persistence

    def test_list_stocks_path_a_persistence_hit(self, client, monkeypatch):
        """REGRESSION: path A + DB hit → every row's source == 'persistence'."""
        from stock_data.data_provider.persistence import stock_list as sl_mod
        fake_meta = [
            {"code": "600519", "name": "贵州茅台", "exchange": "SH"},
            {"code": "000001", "name": "平安银行", "exchange": "SZ"},
        ]
        monkeypatch.setattr(sl_mod, "get_stock_list",
                            lambda market, manager, refresh=False: (fake_meta, "persistence"))

        response = client.get("/api/v1/stocks?market=csi&limit=10")
        assert response.status_code == 200
        data = response.json()
        assert all(s["source"] == "persistence" for s in data)
        assert all(s["quote"] is None for s in data)

    def test_list_stocks_path_a_upstream_refresh(self, client, monkeypatch):
        """REGRESSION: path A + DB miss → fetcher called → source == fetcher name."""
        from stock_data.data_provider.persistence import stock_list as sl_mod
        fake_meta = [
            {"code": "600519", "name": "贵州茅台", "exchange": "SH"},
        ]
        monkeypatch.setattr(sl_mod, "get_stock_list",
                            lambda market, manager, refresh=False: (fake_meta, "akshare"))

        response = client.get("/api/v1/stocks?market=csi&limit=10")
        assert response.status_code == 200
        data = response.json()
        assert data[0]["source"] == "akshare"
        assert data[0]["code"] == "600519"

    def test_list_stocks_include_quote_hk_returns_422(self, client):
        response = client.get("/api/v1/stocks?market=hk&include_quote=true")
        assert response.status_code == 422
        body = response.json()
        assert body["detail"]["error"] == "include_quote_unsupported"

    def test_list_stocks_include_quote_us_returns_422(self, client):
        response = client.get("/api/v1/stocks?market=us&include_quote=true")
        assert response.status_code == 422

    def test_list_stocks_sort_without_quote_returns_400(self, client):
        response = client.get("/api/v1/stocks?market=csi&sort_by=change_pct")
        assert response.status_code == 400
        body = response.json()
        assert body["detail"]["error"] == "sort_requires_quote"

    def test_list_stocks_invalid_sort_by_returns_422(self, client):
        response = client.get("/api/v1/stocks?market=csi&include_quote=true&sort_by=foobar")
        assert response.status_code == 422

    def test_list_stocks_limit_exceeds_max_returns_422(self, client):
        response = client.get("/api/v1/stocks?market=csi&limit=10001")
        assert response.status_code == 422

    def test_list_stocks_include_quote_all_fetchers_fail_returns_503(self, client, monkeypatch):
        from unittest.mock import MagicMock

        from stock_data.api.routes.helpers import get_manager
        from stock_data.data_provider.base import DataFetchError
        mgr = get_manager()
        monkeypatch.setattr(mgr, "get_realtime_quotes",
                            MagicMock(side_effect=DataFetchError("all failed")))
        response = client.get("/api/v1/stocks?market=csi&include_quote=true")
        assert response.status_code == 503

    def test_list_stocks_offset_out_of_range_returns_empty(self, client):
        response = client.get("/api/v1/stocks?market=csi&offset=100000")
        assert response.status_code == 200
        assert response.json() == []

    def test_list_stocks_refresh_param_removed(self, client):
        """?refresh= was removed; our hand-rolled whitelist 422s on it.

        FastAPI itself ignores unknown query params, so this 422 (and its
        `{"error", "message"}` body) is the route's own contract, not
        FastAPI's RequestValidationError shape.
        """
        response = client.get("/api/v1/stocks?market=csi&refresh=true")
        assert response.status_code == 422
        assert response.json()["detail"]["error"] == "unknown_query_param"

    def test_list_stocks_sort_by_change_pct_desc(self, client, monkeypatch):
        """Path B: sort by quote.change_pct desc — applied after cache hit."""
        from stock_data.data_provider.core.types import (
            RealtimeSource,
            UnifiedRealtimeQuote,
        )
        fake_quotes = [
            UnifiedRealtimeQuote(code="000001", name="平安银行",
                                 source=RealtimeSource.AKSHARE, change_pct=-1.0),
            UnifiedRealtimeQuote(code="600519", name="贵州茅台",
                                 source=RealtimeSource.AKSHARE, change_pct=2.0),
            UnifiedRealtimeQuote(code="300750", name="宁德时代",
                                 source=RealtimeSource.AKSHARE, change_pct=0.5),
        ]
        from stock_data.api.routes.helpers import get_manager
        mgr = get_manager()
        monkeypatch.setattr(mgr, "get_realtime_quotes",
                            lambda market: (fake_quotes, "akshare"))

        response = client.get("/api/v1/stocks?market=csi&include_quote=true&sort_by=change_pct&sort_order=desc")
        assert response.status_code == 200
        data = response.json()
        codes = [s["code"] for s in data]
        assert codes == ["600519", "300750", "000001"]  # 2.0, 0.5, -1.0

    def test_list_stocks_sort_by_change_pct_asc(self, client, monkeypatch):
        from stock_data.data_provider.core.types import (
            RealtimeSource,
            UnifiedRealtimeQuote,
        )
        fake_quotes = [
            UnifiedRealtimeQuote(code="000001", name="平安银行",
                                 source=RealtimeSource.AKSHARE, change_pct=-1.0),
            UnifiedRealtimeQuote(code="600519", name="贵州茅台",
                                 source=RealtimeSource.AKSHARE, change_pct=2.0),
        ]
        from stock_data.api.routes.helpers import get_manager
        mgr = get_manager()
        monkeypatch.setattr(mgr, "get_realtime_quotes",
                            lambda market: (fake_quotes, "akshare"))

        response = client.get("/api/v1/stocks?market=csi&include_quote=true&sort_by=change_pct&sort_order=asc")
        assert response.status_code == 200
        codes = [s["code"] for s in response.json()]
        assert codes == ["000001", "600519"]

    def test_list_stocks_sort_by_amount(self, client, monkeypatch):
        """sort_by=amount exercises a non-change_pct sort key."""
        from stock_data.data_provider.core.types import (
            RealtimeSource,
            UnifiedRealtimeQuote,
        )
        fake_quotes = [
            UnifiedRealtimeQuote(code="000001", name="平安银行",
                                 source=RealtimeSource.AKSHARE, amount=1.0e8),
            UnifiedRealtimeQuote(code="600519", name="贵州茅台",
                                 source=RealtimeSource.AKSHARE, amount=2.07e9),
            UnifiedRealtimeQuote(code="300750", name="宁德时代",
                                 source=RealtimeSource.AKSHARE, amount=5.0e8),
        ]
        from stock_data.api.routes.helpers import get_manager
        mgr = get_manager()
        monkeypatch.setattr(mgr, "get_realtime_quotes",
                            lambda market: (fake_quotes, "akshare"))

        response = client.get("/api/v1/stocks?market=csi&include_quote=true&sort_by=amount")
        assert response.status_code == 200
        codes = [s["code"] for s in response.json()]
        # desc by amount: 600519 (2.07e9) > 300750 (5e8) > 000001 (1e8)
        assert codes == ["600519", "300750", "000001"]

    def test_list_stocks_sort_treats_zero_as_zero_not_missing(self, client, monkeypatch):
        """REGRESSION: a flat (0.0%) stock must sort between negative and positive.

        The sort key used to be `getattr(...) or float("-inf")`, and `0.0 or -inf`
        is `-inf` in Python — so a flat stock sank to the bottom under BOTH desc
        and asc, and the client could never get it in the middle. Only None may
        map to -inf.
        """
        from stock_data.data_provider.core.types import (
            RealtimeSource,
            UnifiedRealtimeQuote,
        )
        fake_quotes = [
            UnifiedRealtimeQuote(code="600519", name="涨",
                                 source=RealtimeSource.AKSHARE, change_pct=2.0),
            UnifiedRealtimeQuote(code="000001", name="跌",
                                 source=RealtimeSource.AKSHARE, change_pct=-1.0),
            UnifiedRealtimeQuote(code="300750", name="平",
                                 source=RealtimeSource.AKSHARE, change_pct=0.0),
            UnifiedRealtimeQuote(code="000002", name="停牌",
                                 source=RealtimeSource.AKSHARE, change_pct=None),
        ]
        from stock_data.api.routes.helpers import get_manager
        mgr = get_manager()
        monkeypatch.setattr(mgr, "get_realtime_quotes",
                            lambda market: (fake_quotes, "akshare"))

        desc = client.get(
            "/api/v1/stocks?market=csi&include_quote=true&sort_by=change_pct&sort_order=desc"
        )
        assert desc.status_code == 200
        # 2.0 > 0.0 > -1.0 > None(-inf); the flat stock is NOT at the bottom
        assert [s["code"] for s in desc.json()] == ["600519", "300750", "000001", "000002"]

        asc = client.get(
            "/api/v1/stocks?market=csi&include_quote=true&sort_by=change_pct&sort_order=asc"
        )
        assert asc.status_code == 200
        assert [s["code"] for s in asc.json()] == ["000002", "000001", "300750", "600519"]

    def test_list_stocks_include_quote_respects_limit(self, client, monkeypatch):
        """limit=2 on 5400 upstream quotes → response has 2 rows."""
        from stock_data.data_provider.core.types import (
            RealtimeSource,
            UnifiedRealtimeQuote,
        )
        fake_quotes = [
            UnifiedRealtimeQuote(code=f"{600000+i:06d}", name=f"测试{i}",
                                 source=RealtimeSource.AKSHARE)
            for i in range(5400)
        ]
        from stock_data.api.routes.helpers import get_manager
        mgr = get_manager()
        monkeypatch.setattr(mgr, "get_realtime_quotes",
                            lambda market: (fake_quotes, "akshare"))

        response = client.get("/api/v1/stocks?market=csi&include_quote=true&limit=2")
        assert response.status_code == 200
        assert len(response.json()) == 2


class TestQuote:
    """Tests for /api/v1/stocks/{code}/quote endpoint."""

    def test_quote_baostock_returns_404(self, client):
        """Baostock does not support realtime - should 404 if no other sources."""
        response = client.get("/api/v1/stocks/600519/quote")
        # May be 200 if Akshare succeeds, 404 if all fail
        assert response.status_code in (200, 404)

    def test_quote_invalid_code_too_long(self, client):
        response = client.get("/api/v1/stocks/" + "A" * 30 + "/quote")
        assert response.status_code == 422


class TestCalendar:
    """Tests for /api/v1/calendar endpoint."""

    def test_calendar(self, client):
        response = client.get("/api/v1/calendar")
        assert response.status_code == 200
        data = response.json()
        assert "trade_dates" in data
        assert "total" in data


class TestIndexQuote:
    """Tests for /api/v1/indices/{code}/quote endpoint."""

    def test_index_quote_returns_data(self, client):
        response = client.get("/api/v1/indices/000300/quote")
        assert response.status_code == 200
        data = response.json()
        assert data["code"] == "000300"
        assert "name" in data
        assert "current_price" in data
        assert "change_pct" in data

    def test_index_quote_399006(self, client):
        response = client.get("/api/v1/indices/399006/quote")
        assert response.status_code == 200
        data = response.json()
        assert data["code"] == "399006"


class TestStocksBlocksIndices:
    """Tests that /stocks/{code}/* endpoints reject index codes."""

    def test_stocks_quote_blocks_index(self, client):
        response = client.get("/api/v1/stocks/000300/quote")
        assert response.status_code == 400
        assert "indices" in response.json()["detail"]["message"]

    def test_stocks_kline_blocks_index(self, client):
        response = client.get("/api/v1/stocks/000300/kline?period=daily")
        assert response.status_code == 400
        assert "indices" in response.json()["detail"]["message"]


class TestKline:
    """Tests for /api/v1/stocks/{code}/kline endpoint."""

    def test_kline_daily(self, client):
        response = client.get("/api/v1/stocks/600519/kline?period=daily&days=5")
        assert response.status_code == 200
        data = response.json()
        assert data["code"] == "600519"
        assert data["period"] == "daily"
        assert "data" in data

    def test_kline_weekly(self, client):
        response = client.get("/api/v1/stocks/600519/kline?period=weekly&days=10")
        # 200 if a fetcher succeeds; 503 if upstream unavailable
        assert response.status_code in (200, 503)
        if response.status_code == 200:
            assert response.json()["period"] == "weekly"

    def test_kline_monthly(self, client):
        response = client.get("/api/v1/stocks/600519/kline?period=monthly&days=5")
        # 200 if a fetcher succeeds; 503 if upstream unavailable
        assert response.status_code in (200, 503)
        if response.status_code == 200:
            assert response.json()["period"] == "monthly"

    def test_kline_5m(self, client):
        response = client.get("/api/v1/stocks/600519/kline?period=5m&days=1")
        # 200 if a fetcher supports minute kline; 422/503 if none available
        assert response.status_code in (200, 422, 503)

    def test_kline_with_adjust(self, client):
        response = client.get("/api/v1/stocks/600519/kline?period=daily&days=5&adjust=qfq")
        assert response.status_code == 200
        data = response.json()
        assert data["code"] == "600519"

    def test_kline_invalid_period(self, client):
        response = client.get("/api/v1/stocks/600519/kline?period=invalid")
        assert response.status_code == 422

    def test_kline_with_indicators(self, client):
        response = client.get("/api/v1/stocks/600519/kline?period=daily&days=30&indicators=ma")
        assert response.status_code == 200
        data = response.json()
        assert data["code"] == "600519"
        assert len(data["data"]) <= 30

    def test_kline_invalid_stock(self, client):
        """A code that's neither in ``CSI_INDEX_MAP`` nor in ``stock_list`` gets a
        "stock-not-found" 400, NOT the misleading "Index X is not supported" message.

        The 5f41aee helper used to emit the same "Index X is not supported"
        template regardless of whether ``code`` looked like an index. After the
        helpers.py disambiguation, this branch (no index-code match) reads as a
        plain not-found error.
        """
        response = client.get("/api/v1/stocks/INVALID/kline?period=daily&days=5")
        assert response.status_code == 400
        detail = response.json()["detail"]
        assert detail["error"] == "invalid_request"
        assert "INVALID" in detail["message"]
        assert "not found" in detail["message"]
        assert "Index" not in detail["message"]

    def test_kline_index_coded_input_redirects_message(self, client, monkeypatch):
        """A CSI-index code that isn't in ``stock_list`` (cold cache or upstream
        down) still hits the *index redirect* branch — message reads as
        "Index X is not supported via this endpoint. Use /indices/.../kline
        instead." rather than the misleading not-found text.

        ``is_index_code("000300")`` is True (CSI_INDEX_MAP), and we simulate
        a stock_list miss by patching ``stock_list.get_stock_name`` to return
        ``""``. This is the realistic trigger for the redirect branch in
        production: e.g. zzshare upstream is briefly unavailable so
        ``manager.get_all_stocks`` returns empty, and the auto-warm in
        ``stock_list.get_stock_name`` silently fails (its ``except Exception:
        pass`` swallow).
        """
        from stock_data.api.routes import helpers as route_helpers

        monkeypatch.setattr(
            route_helpers.stock_list, "get_stock_name", lambda *a, **kw: ""
        )
        response = client.get("/api/v1/stocks/000300/kline?period=daily&days=5")
        assert response.status_code == 400
        detail = response.json()["detail"]
        assert detail["error"] == "invalid_request"
        assert "Index 000300" in detail["message"]
        assert "/indices/000300/kline" in detail["message"]


    def test_kline_unknown_code_gets_not_found_message(self, client, monkeypatch):
        """A code that's neither in CSI_INDEX_MAP nor in stock_list gets the
        "stock-not-found" message — NOT the index-redirect hint.

        Same monkeypatch mechanism as above; uses ``NOTASTOCK`` so ``is_index_code``
        returns False.
        """
        from stock_data.api.routes import helpers as route_helpers

        monkeypatch.setattr(
            route_helpers.stock_list, "get_stock_name", lambda *a, **kw: ""
        )
        response = client.get("/api/v1/stocks/NOTASTOCK/kline?period=daily&days=5")
        assert response.status_code == 400
        detail = response.json()["detail"]
        assert detail["error"] == "invalid_request"
        assert "NOTASTOCK" in detail["message"]
        assert "not found" in detail["message"]
        assert "Index" not in detail["message"]
        assert "/indices/" not in detail["message"]


    def test_kline_ambiguous_000001_routes_as_stock(self, client):
        """``000001`` is both Ping An Bank (stock) and 上证综指 (CSI index).

        ``/stocks/000001/kline`` must NOT 400 (the old guard rejected it via
        ``is_index_code``), and the manager must propagate ``asset="stock"``
        to the fetcher so the stock upstream API is used instead of the
        index one. We can't assert the actual upstream payload here without
        mocking, so we assert status != 400 and, more importantly, that the
        route accepts the request (not 400) — the fetcher-level plumbing is
        covered by unit tests in test_base_unit / test_manager_two_stage_filter.
        """
        response = client.get("/api/v1/stocks/000001/kline?period=daily&days=5")
        # Was 400 before the fix. Now 200 (real data via zzshare/akshare) or
        # 503 (all upstreams down) — but never 400.
        assert response.status_code != 400
        assert response.status_code in (200, 503)


class TestIndicesBlocksStocks:
    """Tests that /indices/{code}/* endpoints reject stock codes (and other non-index codes).

    Symmetric to TestStocksBlocksIndices above.
    """

    def test_indices_quote_blocks_stock(self, client):
        """600519 is Kweichow Moutai (A-share), not an index."""
        response = client.get("/api/v1/indices/600519/quote")
        assert response.status_code == 400
        detail = response.json()["detail"]
        assert detail["error"] == "invalid_request"
        assert "stocks" in detail["message"]

    def test_indices_kline_blocks_stock(self, client):
        """600519 is a stock — /indices/{code}/kline should reject with 400."""
        response = client.get("/api/v1/indices/600519/kline?period=daily")
        assert response.status_code == 400
        detail = response.json()["detail"]
        assert detail["error"] == "invalid_request"
        assert "stocks" in detail["message"]


class TestStockInfoRoute:
    """Tests for /api/v1/stocks/{code}/info endpoint."""

    def test_info_rejects_hk_market(self, client):
        # HK market is not csi → no fetcher handles STOCK_INFO → 503
        response = client.get("/api/v1/stocks/HK00700/info")
        assert response.status_code == 503

    def test_info_returns_503_for_invalid_stock(self, client):
        # Invalid code → all fetchers fail → 503
        response = client.get("/api/v1/stocks/INVALID/info")
        assert response.status_code == 503

    def test_info_response_shape(self, client):
        # 200 if any fetcher succeeds, 503 if all fail — accept either.
        # We assert the response shape ONLY on 200, else assert 503.
        response = client.get("/api/v1/stocks/600519/info")
        if response.status_code == 200:
            data = response.json()
            # All 19 fields present (incl. `exchange` added by route layer
            # via code_to_exchange() — the fetcher payload itself does not
            # carry it).
            expected_fields = {
                "code",
                "name",
                "ename",
                "market",
                "listed_date",
                "delisted_date",
                "total_shares",
                "float_shares",
                "concepts",
                "registered_address",
                "registered_capital",
                "legal_representative",
                "business_scope",
                "established_date",
                "secretary",
                "secretary_phone",
                "secretary_email",
                "exchange",
                "source",
            }
            assert set(data.keys()) == expected_fields
            assert data["code"] == "600519"
            assert data["market"] == "csi"
            assert isinstance(data["concepts"], list)
            assert data["exchange"] in ("SH", "SZ", "BJ", None)
            assert data["source"] in ("ZhituFetcher", "MyquantFetcher", "")
        else:
            assert response.status_code == 503


class TestIndexKline:
    """Tests for /api/v1/indices/{code}/kline endpoint (Task 10)."""

    def test_index_kline_daily(self, client):
        """GET /indices/{code}/kline?period=daily returns index K-line data."""
        response = client.get("/api/v1/indices/000300/kline?period=daily&days=5")
        assert response.status_code == 200
        data = response.json()
        assert data["code"] == "000300"
        assert data["period"] == "daily"
        assert "data" in data

    def test_index_kline_weekly(self, client):
        response = client.get("/api/v1/indices/000300/kline?period=weekly&days=10")
        assert response.status_code in (200, 503)
        if response.status_code == 200:
            assert response.json()["period"] == "weekly"

    def test_index_kline_5m(self, client):
        """GET /indices/{code}/kline?period=5m returns minute K-line data."""
        response = client.get("/api/v1/indices/000300/kline?period=5m&days=1")
        # 200 if a fetcher supports index minute kline; 422/503 if none available
        assert response.status_code in (200, 422, 503)

    def test_index_kline_rejects_stock_code(self, client):
        """Stock codes must use /stocks/{code}/kline."""
        response = client.get("/api/v1/indices/600519/kline?period=daily")
        assert response.status_code == 400
        detail = response.json()["detail"]
        assert detail["error"] == "invalid_request"
        assert "stocks" in detail["message"]

    def test_index_kline_rejects_adjust_qfq(self, client):
        """Indices have no qfq/hfq concept — 422 user input error."""
        response = client.get("/api/v1/indices/000300/kline?period=daily&adjust=qfq")
        assert response.status_code == 422
        detail = response.json()["detail"]
        assert detail["error"] == "adjust_not_supported"

    def test_index_kline_rejects_adjust_hfq(self, client):
        """Indices have no hfq concept either."""
        response = client.get("/api/v1/indices/000300/kline?period=daily&adjust=hfq")
        assert response.status_code == 422
        detail = response.json()["detail"]
        assert detail["error"] == "adjust_not_supported"

    def test_index_kline_invalid_period(self, client):
        response = client.get("/api/v1/indices/000300/kline?period=invalid")
        assert response.status_code == 422

    def test_index_kline_with_indicators(self, client):
        response = client.get("/api/v1/indices/000300/kline?period=daily&days=30&indicators=ma")
        assert response.status_code == 200
        data = response.json()
        assert data["code"] == "000300"
        assert len(data["data"]) <= 30

    def test_index_kline_response_shape(self, client):
        """Verify response has code, name, period, data, source fields."""
        response = client.get("/api/v1/indices/000300/kline?period=daily&days=3")
        assert response.status_code == 200
        data = response.json()
        assert "code" in data
        assert "name" in data
        assert "period" in data
        assert "data" in data
        assert "source" in data


# ============================================================
# Board stocks schema rename + 4 new fields E2E (spec 2026-07-30)
# ============================================================
#
# Added 2026-07-30 alongside the cross-endpoint quote-cache fillup.
# These tests pin two contract changes in /boards/{code}/stocks:
#   1. `amplitude` field renamed to `amplitude_pct` (BoardStockInfo model).
#   2. 4 new fields `open` / `high` / `low` / `prev_close` default None
#      (populated for suffix rows by _project_unified_quote_to_dict;
#      THS top-50 rows stay None since THS 14 columns don't include them).
# Tests live in Task 2 (not Task 5) because they verify the schema
# changes that ship with the rename + new fields; Task 5 tests suffix
# fillup behavior (a different concern).


class TestBoardStocksAmplitudeRenameE2E:
    """E2E for amplitude → amplitude_pct rename + 4 new field defaults."""

    def test_amplitude_field_in_response_is_amplitude_pct(self, client, monkeypatch):
        """amplitude field is renamed to amplitude_pct in the JSON response."""
        from stock_data.data_provider.persistence import board as pb

        # Stub the persistence helper to return one row with amplitude set;
        # route layer should read s.get("amplitude") and write into
        # amplitude_pct.
        monkeypatch.setattr(
            pb, "get_board_stocks",
            lambda *a, **kw: (
                [{
                    "stock_code": "600519", "stock_name": "贵州茅台",
                    "price": 1700.0, "change_pct": 1.5,
                    "amplitude": 2.0,  # upstream-style key (THS column 9)
                }],
                "persistence", "ths", None, False, 1,
            ),
        )

        r = client.get("/api/v1/boards/885595/stocks?source=ths&include_quote=true")
        assert r.status_code == 200
        stock = r.json()["stocks"][0]
        assert "amplitude_pct" in stock
        assert "amplitude" not in stock
        assert stock["amplitude_pct"] == 2.0

    def test_new_fields_open_high_low_prev_close_default_none(self, client, monkeypatch):
        """4 new fields appear in the JSON response with None default."""
        from stock_data.data_provider.persistence import board as pb

        # Stub without open/high/low/prev_close → these default to None
        # in the route's _build_board_stock_info since THS upstream
        # doesn't carry them.
        monkeypatch.setattr(
            pb, "get_board_stocks",
            lambda *a, **kw: (
                [{"stock_code": "600519", "stock_name": "M"}],
                "persistence", "ths", None, False, 1,
            ),
        )
        r = client.get("/api/v1/boards/885595/stocks?source=ths")
        assert r.status_code == 200
        stock = r.json()["stocks"][0]
        for f in ("open", "high", "low", "prev_close"):
            assert f in stock and stock[f] is None, (
                f"{f} should be present and None"
            )
