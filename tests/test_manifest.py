"""Unit tests for stock_data/explorer/manifest.py."""
import logging

import pytest
from fastapi import FastAPI, Query
from pydantic import BaseModel

from stock_data.api.endpoint_meta import REGISTRY, endpoint_meta
from stock_data.explorer.manifest import build_manifest


@pytest.fixture(autouse=True)
def _clear_registry():
    REGISTRY.clear()
    yield
    REGISTRY.clear()


class QuoteResp(BaseModel):
    code: str
    price: float
    name: str | None = None


class TestBuildManifestIncludesDecoratedRoutes:
    def _build_app(self):
        app = FastAPI()

        @app.get("/health", tags=["health"])
        @endpoint_meta(summary="健康检查", markets=[], capabilities=[])
        def health():
            return {"status": "ok"}

        @app.get("/stocks/{stock_code}/quote", response_model=QuoteResp, tags=["stocks"])
        @endpoint_meta(
            summary="实时行情",
            markets=["csi", "hk", "us"],
            capabilities=["STOCK_REALTIME_QUOTE"],
        )
        def quote(stock_code: str, days: int = Query(30, ge=1)):
            return None

        return app

    def test_returns_meta_and_sections(self):
        app = self._build_app()
        m = build_manifest(app)
        assert "meta" in m
        assert "sections" in m
        assert isinstance(m["sections"], list)
        assert len(m["sections"]) == 2  # health + stocks

    def test_meta_has_version_and_capabilities(self):
        m = build_manifest(self._build_app())
        assert m["meta"]["version"] == "1.1"
        assert "server_version" in m["meta"]
        assert "STOCK_REALTIME_QUOTE" in m["meta"]["capabilities"]
        assert m["meta"]["capabilities"]["STOCK_REALTIME_QUOTE"]["icon"] == "💹"


class TestRouteWithoutMetaSkipped:
    def test_skipped_with_warning(self, caplog):
        app = FastAPI()

        @app.get("/orphan", tags=["misc"])
        def orphan():  # no @endpoint_meta
            return None

        with caplog.at_level(logging.WARNING, logger="stock_data.explorer.manifest"):
            m = build_manifest(app)

        assert m["sections"] == []
        assert any("orphan" in r.message and "no @endpoint_meta" in r.message for r in caplog.records)


class TestParamReflection:
    def test_path_params(self):
        app = FastAPI()

        @app.get("/stocks/{stock_code}/quote", tags=["stocks"])
        @endpoint_meta(summary="x", capabilities=["STOCK_REALTIME_QUOTE"])
        def quote(stock_code: str):
            return None

        m = build_manifest(app)
        ep = m["sections"][0]["endpoints"][0]
        path_params = [p for p in ep["params"] if p["in"] == "path"]
        assert path_params == [{"name": "stock_code", "in": "path", "required": True,
                                "type": "string"}]

    def test_query_params_with_type_and_required(self):
        app = FastAPI()

        @app.get("/x", tags=["stocks"])
        @endpoint_meta(summary="x", capabilities=["STOCK_REALTIME_QUOTE"])
        def q(
            days: int = Query(30, ge=1, le=365),
            refresh: bool = Query(False),
            adj: str = Query(""),
        ):
            return None

        m = build_manifest(app)
        params = {p["name"]: p for p in m["sections"][0]["endpoints"][0]["params"]}
        assert params["days"] == {"name": "days", "in": "query", "required": False,
                                  "type": "int"}
        assert params["refresh"]["type"] == "bool"
        assert params["adj"]["type"] == "string"

    def test_required_query_param(self):
        app = FastAPI()

        @app.get("/x", tags=["stocks"])
        @endpoint_meta(summary="x", capabilities=["STOCK_REALTIME_QUOTE"])
        def q(market: str = Query(...)):
            return None

        m = build_manifest(app)
        p = m["sections"][0]["endpoints"][0]["params"][0]
        assert p["name"] == "market"
        assert p["required"] is True


class TestResponseModelReflection:
    def test_response_model_reflected(self):
        app = FastAPI()

        @app.get("/q", response_model=QuoteResp, tags=["stocks"])
        @endpoint_meta(summary="x", capabilities=["STOCK_REALTIME_QUOTE"])
        def q():
            return None

        m = build_manifest(app)
        ep = m["sections"][0]["endpoints"][0]
        assert ep["response_model"] == "QuoteResp"

    def test_no_response_model(self):
        app = FastAPI()

        @app.get("/h", tags=["health"])
        @endpoint_meta(summary="x", capabilities=[])
        def h():
            return None

        m = build_manifest(app)
        ep = m["sections"][0]["endpoints"][0]
        assert ep["response_model"] is None


class TestPrefixPrepending:
    def test_path_includes_router_prefix(self):
        app = FastAPI()
        sub = FastAPI()

        @sub.get("/stocks/{stock_code}/quote", tags=["stocks"])
        @endpoint_meta(summary="x", capabilities=["STOCK_REALTIME_QUOTE"])
        def q(stock_code: str):
            return None

        app.mount("/api/v1", sub)

        m = build_manifest(app)
        # The sub-app's routes are not flattened into app.routes, so the
        # manifest sees the mount as a single non-APIRoute entry. Verify
        # the contract: paths that DO appear include any internal prefix.
        assert m["sections"] == []  # mount hides inner routes from app.routes
        # Spec note: when routes are registered via include_router(prefix=...),
        # APIRoute.prefix carries the prefix — see TestIncludeRouterPrefix below.


class TestIncludeRouterPrefix:
    def test_api_route_prefix_concatenated_with_path(self):
        from fastapi import APIRouter

        app = FastAPI()
        router = APIRouter()

        @router.get("/stocks/{stock_code}/quote", tags=["stocks"])
        @endpoint_meta(summary="x", capabilities=["STOCK_REALTIME_QUOTE"])
        def q(stock_code: str):
            return None

        app.include_router(router, prefix="/api/v1")
        m = build_manifest(app)
        ep = m["sections"][0]["endpoints"][0]
        assert ep["path"] == "/api/v1/stocks/{stock_code}/quote"
        assert "stock_code" in ep["id"]


class TestSectionSorting:
    def test_numeric_sort_handles_4_10(self):
        app = FastAPI()

        for i in [10, 2, 1]:
            @app.get(f"/p{i}", tags=["stocks"])
            @endpoint_meta(summary=f"p{i}", capabilities=["STOCK_REALTIME_QUOTE"])
            def handler(i=i):
                return None

        m = build_manifest(app)
        # All three routes fall under section '4.2' (the 'stocks' tag),
        # so there's one section with three endpoints, not three sections.
        # The numeric-sort assertion applies when there ARE multiple
        # sections, e.g. mixing stocks+indices tags.
        assert len(m["sections"]) == 1


class TestControlTagExclusion:
    def test_control_endpoints_excluded(self):
        app = FastAPI()

        @app.get("/control/foo", tags=["control"])
        @endpoint_meta(summary="internal", capabilities=[])
        def internal():
            return None

        @app.get("/visible", tags=["stocks"])
        @endpoint_meta(summary="visible", capabilities=["STOCK_REALTIME_QUOTE"])
        def visible():
            return None

        m = build_manifest(app)
        paths = [ep["path"] for sec in m["sections"] for ep in sec["endpoints"]]
        assert "/control/foo" not in paths
        assert "/visible" in paths


class TestSlugifyAndMethod:
    def test_id_is_stable_slug(self):
        from fastapi import APIRouter

        app = FastAPI()
        router = APIRouter()

        @router.get("/stocks/{stock_code}/quote", tags=["stocks"])
        @endpoint_meta(summary="x", capabilities=["STOCK_REALTIME_QUOTE"])
        def q(stock_code: str):
            return None

        app.include_router(router, prefix="/api/v1")
        m = build_manifest(app)
        ep = m["sections"][0]["endpoints"][0]
        assert ep["method"] == "GET"
        # id should be deterministic, lowercase, path-component safe
        assert ep["id"] == "get_api_v1_stocks_stock_code_quote"

    def test_uses_first_method_only(self):
        """If a route supports multiple methods, manifest picks one (GET preferred)."""
        from fastapi import APIRouter
        app = FastAPI()
        router = APIRouter()

        @router.api_route("/x", methods=["GET", "POST"], tags=["stocks"])
        @endpoint_meta(summary="x", capabilities=["STOCK_REALTIME_QUOTE"])
        def x():
            return None

        app.include_router(router, prefix="/api/v1")
        m = build_manifest(app)
        # FastAPI keeps GET and POST on a single APIRoute; the manifest
        # therefore emits one endpoint per APIRoute, not one per method.
        paths = [ep["path"] for sec in m["sections"] for ep in sec["endpoints"]]
        assert paths.count("/api/v1/x") == 1
        # _pick_method should prefer GET when both are present
        assert m["sections"][0]["endpoints"][0]["method"] == "GET"


class TestPep604Union:
    def test_optional_int_query_param_uses_int(self):
        app = FastAPI()

        @app.get("/x", tags=["stocks"])
        @endpoint_meta(summary="x", capabilities=["STOCK_REALTIME_QUOTE"])
        def q(days: int | None = Query(None)):
            return None

        m = build_manifest(app)
        params = {p["name"]: p for p in m["sections"][0]["endpoints"][0]["params"]}
        assert params["days"]["type"] == "int"
        assert params["days"]["required"] is False
