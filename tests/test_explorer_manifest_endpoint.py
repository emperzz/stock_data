"""Integration tests for GET /control/api-manifest."""
import pytest
from fastapi.testclient import TestClient

from stock_data.api.endpoint_meta import REGISTRY
from stock_data.server import app


@pytest.fixture
def client():
    return TestClient(app)


# Snapshot REGISTRY at module-load time. The `from stock_data.server import
# app` above triggered `from stock_data.api.routes import router`, which
# ran all `@endpoint_meta(...)` decorators and populated REGISTRY. Other
# test files (test_manifest.py, test_endpoint_meta.py) clear REGISTRY in
# their teardown, so by the time TestManifestFetchersField runs, REGISTRY
# is empty. Restoring from this snapshot guarantees a populated registry
# without the previous implementer's AST-walking hack.
_REGISTRY_SNAPSHOT: dict = dict(REGISTRY)


class TestApiManifestEndpoint:
    @pytest.fixture(autouse=True)
    def _clear_registry(self):
        """Clear REGISTRY around each test in this class only.

        `TestManifestFetchersField` relies on REGISTRY being populated, so
        it must NOT be affected by this autouse clear. Its own class-level
        autouse (below) restores the module-load snapshot.
        """
        REGISTRY.clear()
        yield
        REGISTRY.clear()

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


def test_app_state_has_manager_after_startup():
    """app.state.manager must be wired during lifespan startup.

    The manifest builder (added in subsequent tasks) enumerates fetchers per
    (market, capability) via app.state.manager. Tests that mock fetchers
    also need this hook to inject a fake manager.
    """
    from stock_data.data_provider.manager import DataFetcherManager

    with TestClient(app) as client:
        # Trigger lifespan startup/shutdown explicitly via the context manager.
        # Calling an endpoint forces lifespan to run before the request.
        client.get("/control/server/status")
        assert hasattr(app.state, "manager"), (
            "app.state.manager not set — manifest builder will fail to "
            "enumerate fetchers"
        )
        assert isinstance(app.state.manager, DataFetcherManager)


class TestManifestFetchersField:
    """Verify the new fetchers[] field on each endpoint node.

    These tests need REGISTRY populated. A class-level autouse fixture
    restores REGISTRY from the module-load snapshot before each test, so
    any teardown clearing from other test classes (or from
    TestApiManifestEndpoint) doesn't affect us.
    """

    @pytest.fixture(autouse=True)
    def _restore_registry(self):
        REGISTRY.clear()
        REGISTRY.update(_REGISTRY_SNAPSHOT)
        yield

    def _manifest(self):
        with TestClient(app) as client:
            client.get("/control/server/status")  # trigger lifespan
            resp = client.get("/control/api-manifest")
            resp.raise_for_status()
            return resp.json()

    def _endpoint(self, manifest: dict, method: str, path: str) -> dict:
        for sec in manifest["sections"]:
            for ep in sec["endpoints"]:
                if ep["method"] == method and ep["path"].endswith(path):
                    return ep
        pytest.fail(f"endpoint not found: {method} {path}")

    def test_every_endpoint_has_fetchers_field(self):
        m = self._manifest()
        for sec in m["sections"]:
            for ep in sec["endpoints"]:
                assert "fetchers" in ep, f"endpoint {ep['path']} missing fetchers field"
                assert isinstance(ep["fetchers"], list)

    def test_kline_endpoint_has_expected_fetchers(self):
        m = self._manifest()
        ep = self._endpoint(m, "GET", "/stocks/{stock_code}/history")
        names = [f["name"] for f in ep["fetchers"]]
        # TushareFetcher is excluded — it requires TUSHARE_TOKEN and is
        # marked is_available()=False without it, so the manager skips
        # it. Assert only the token-free priorities: BaostockFetcher (1)
        # and AkshareFetcher (2). Both should always be present.
        for name in ("BaostockFetcher", "AkshareFetcher"):
            assert name in names, f"{name} missing from /stocks/.../history fetchers"

    def test_kline_baostock_merged_dwm_and_min(self):
        """Approach A: BaostockFetcher supports DWM+MIN, both map to get_kline_data → ONE row with merged caps."""
        m = self._manifest()
        ep = self._endpoint(m, "GET", "/stocks/{stock_code}/history")
        baostock = next((f for f in ep["fetchers"] if f["name"] == "BaostockFetcher"), None)
        assert baostock is not None
        assert set(baostock["capabilities"]) == {"HISTORICAL_DWM", "HISTORICAL_MIN"}
        assert baostock["method"] == "get_kline_data"

    def test_indicators_catalog_has_no_fetchers(self):
        m = self._manifest()
        ep = self._endpoint(m, "GET", "/indicators")
        assert ep["fetchers"] == []

    def test_dragon_tiger_daily_overrides_method(self):
        m = self._manifest()
        ep = self._endpoint(m, "GET", "/dragon-tiger")
        methods = {f["method"] for f in ep["fetchers"]}
        assert methods == {"get_daily_dragon_tiger"}, (
            f"expected only get_daily_dragon_tiger, got {methods}"
        )

    def test_fund_flow_daily_overrides_method(self):
        m = self._manifest()
        ep = self._endpoint(m, "GET", "/stocks/{stock_code}/fund-flow/daily")
        methods = {f["method"] for f in ep["fetchers"]}
        assert methods == {"get_fund_flow_120d"}

    def test_board_stocks_overrides_method(self):
        m = self._manifest()
        ep = self._endpoint(m, "GET", "/boards/{board_code}/stocks")
        methods = {f["method"] for f in ep["fetchers"]}
        assert methods == {"get_board_stocks"}

    def test_signature_has_code_field_for_kline(self):
        m = self._manifest()
        ep = self._endpoint(m, "GET", "/stocks/{stock_code}/history")
        baostock = next(f for f in ep["fetchers"] if f["name"] == "BaostockFetcher")
        sig = baostock["signature"]
        code_param = next((p for p in sig if p["name"] in ("code", "stock_code")), None)
        assert code_param is not None
        assert code_param["required"] is True
        assert code_param["type"] == "string"

    def test_unavailable_fetcher_surfaces_with_available_false_and_reason(self):
        """ZhituFetcher declares STOCK_INFO but is unavailable without ZHITU_TOKEN.

        The manifest must still list it under the STOCK_INFO endpoint with
        `available: false` and a non-empty `reason` string so users learn how
        to opt in. This is the test that would have caught the original gap
        ("only registered fetchers show up") which silently hid Zhitu from
        the explorer when its token wasn't set.
        """
        m = self._manifest()
        ep = self._endpoint(m, "GET", "/stocks/{code}/info")
        zhitu = next((f for f in ep["fetchers"] if f["name"] == "ZhituFetcher"), None)
        assert zhitu is not None, (
            "ZhituFetcher missing from /stocks/{code}/info fetchers[] — "
            "the explorer should surface it with available=false so users "
            "see the full failover chain even when ZHITU_TOKEN is unset."
        )
        assert zhitu.get("available") is False, (
            f"ZhituFetcher should report available=false without ZHITU_TOKEN; "
            f"got available={zhitu.get('available')!r}"
        )
        assert zhitu.get("reason"), (
            "ZhituFetcher.unavailable_reason() returned no reason string — "
            "users need actionable guidance ('set ZHITU_TOKEN to enable')"
        )
        assert "ZHITU_TOKEN" in zhitu["reason"], (
            f"reason should mention the env var name; got {zhitu['reason']!r}"
        )
        assert zhitu["method"] == "get_stock_info"
        # Myquant is currently the registered fallback for this endpoint —
        # confirm it shows up as available and that the manifest order
        # reflects the priority chain (Zhitu's 4 must come before Myquant's 9).
        # Asserting on the fetcher's own ``priority`` field is more durable
        # than an index check — it doesn't break if a third fetcher is
        # inserted in between.
        myquant = next(f for f in ep["fetchers"] if f["name"] == "MyquantFetcher")
        assert myquant.get("available") is True
        assert zhitu["priority"] < myquant["priority"]
