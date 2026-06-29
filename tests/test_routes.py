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
            assert s["name"].upper().replace("FETCHER", "") in reason.upper() or \
                   "TOKEN" in reason.upper() or \
                   "SDK" in reason.upper(), (
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
            f"status flipped to 'unhealthy' just because Tushare/Zhitu "
            f"aren't registered — but those are optional (token-gated). "
            f"The probe must stay 'ok' or 'degraded' for k8s/lb readiness."
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


class TestHistory:
    """Tests for /api/v1/stocks/{code}/history endpoint."""

    def test_history_returns_503_for_invalid_stock(self, client):
        """Invalid stock code should fail all fetchers and return 503."""
        response = client.get("/api/v1/stocks/INVALID/history?period=daily&days=5")
        assert response.status_code == 503

    def test_history_with_adjust(self, client):
        """Test history with adjustment parameter."""
        response = client.get("/api/v1/stocks/600519/history?period=daily&days=5&adjust=qfq")
        assert response.status_code == 200
        data = response.json()
        assert data["code"] == "600519"
        assert "data" in data


class TestIntraday:
    """Tests for /api/v1/stocks/{code}/intraday endpoint."""

    def test_intraday_unsupported_market(self, client):
        """US stocks not supported for intraday."""
        response = client.get("/api/v1/stocks/AAPL/intraday?period=5")
        assert response.status_code == 400


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
        assert "change_percent" in data

    def test_index_quote_399006(self, client):
        response = client.get("/api/v1/indices/399006/quote")
        assert response.status_code == 200
        data = response.json()
        assert data["code"] == "399006"


class TestIndexHistory:
    """Tests for /api/v1/indices/{code}/history endpoint."""

    def test_index_history_daily(self, client):
        response = client.get("/api/v1/indices/000300/history?period=daily&days=5")
        assert response.status_code == 200
        data = response.json()
        assert data["code"] == "000300"
        assert data["period"] == "daily"
        assert len(data["data"]) <= 5

    def test_index_history_weekly(self, client):
        response = client.get("/api/v1/indices/000300/history?period=weekly&days=10")
        assert response.status_code == 200
        data = response.json()
        assert data["period"] == "weekly"


class TestIndexIntraday:
    """Tests for /api/v1/indices/{code}/intraday endpoint."""

    def test_index_intraday_period_5(self, client):
        response = client.get("/api/v1/indices/000300/intraday?period=5")
        # 200 = success, 503 = data unavailable (market closed / upstream failure)
        # 500 = implementation bug and should always fail the test
        assert response.status_code in (200, 503)

    def test_index_intraday_invalid_period(self, client):
        response = client.get("/api/v1/indices/000300/intraday?period=999")
        assert response.status_code == 422


class TestStocksBlocksIndices:
    """Tests that /stocks/{code}/* endpoints reject index codes."""

    def test_stocks_quote_blocks_index(self, client):
        response = client.get("/api/v1/stocks/000300/quote")
        assert response.status_code == 400
        assert "indices" in response.json()["detail"]["message"]

    def test_stocks_history_blocks_index(self, client):
        response = client.get("/api/v1/stocks/000300/history?period=daily&days=5")
        assert response.status_code == 400
        assert "indices" in response.json()["detail"]["message"]

    def test_stocks_intraday_blocks_index(self, client):
        response = client.get("/api/v1/stocks/000300/intraday?period=5")
        assert response.status_code == 400

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
        response = client.get("/api/v1/stocks/INVALID/kline?period=daily&days=5")
        assert response.status_code == 503


class TestIndicesBlocksStocks:
    """Tests that /indices/{code}/* endpoints reject stock codes (and other non-index codes).

    Symmetric to TestStocksBlocksIndices above. Regression coverage for the bug
    where `/indices/600519/intraday` returned 503 with a leaked
    ``[MyquantFetcher] ... Not an index code: 600519`` message instead of a
    clean 400.
    """

    def test_indices_quote_blocks_stock(self, client):
        """600519 is Kweichow Moutai (A-share), not an index."""
        response = client.get("/api/v1/indices/600519/quote")
        assert response.status_code == 400
        detail = response.json()["detail"]
        assert detail["error"] == "invalid_request"
        assert "stocks" in detail["message"]

    def test_indices_history_blocks_stock(self, client):
        response = client.get("/api/v1/indices/600519/history?period=daily&days=5")
        assert response.status_code == 400
        detail = response.json()["detail"]
        assert detail["error"] == "invalid_request"
        assert "stocks" in detail["message"]

    def test_indices_intraday_blocks_stock(self, client):
        """The original bug report: 600519 → /indices/{code}/intraday should be 400, not 503."""
        response = client.get("/api/v1/indices/600519/intraday?period=5")
        assert response.status_code == 400
        detail = response.json()["detail"]
        assert detail["error"] == "invalid_request"
        assert "stocks" in detail["message"]

    def test_indices_intraday_blocks_garbage(self, client):
        """Non-index, non-stock gibberish should also be 400 (clearer than 503)."""
        response = client.get("/api/v1/indices/NOTACODE/intraday?period=5")
        assert response.status_code == 400
        assert response.json()["detail"]["error"] == "invalid_request"


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
            # All 19 fields present
            expected_fields = {
                "code", "name", "ename", "market",
                "listed_date", "delisted_date", "total_shares", "float_shares",
                "industry", "concepts",
                "registered_address", "registered_capital", "legal_representative",
                "business_scope", "established_date",
                "secretary", "secretary_phone", "secretary_email",
                "source",
            }
            assert set(data.keys()) == expected_fields
            assert data["code"] == "600519"
            assert data["market"] == "csi"
            assert isinstance(data["concepts"], list)
            assert data["source"] in ("ZhituFetcher", "MyquantFetcher", "")
        else:
            assert response.status_code == 503
