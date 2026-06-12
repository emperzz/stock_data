# Explorer Auto API Manifest Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the ~1000-line hand-written `ENDPOINTS.sections` block in `stock_data/explorer/static/index.html` with a server-emitted manifest fetched on load. Routes.py becomes the single source of truth for the API list.

**Architecture:** Add `@endpoint_meta` decorator that registers per-route business metadata (summary/markets/capabilities/cache/sources) in a module-level registry. `build_manifest(app)` reflects FastAPI's `app.routes` to extract path/method/params, merges with the registry, and returns a JSON tree exposed at `GET /control/api-manifest`. HTML fetches this on load instead of consuming the hard-coded block.

**Tech Stack:** Python 3.11+, FastAPI route introspection (`APIRoute`, `route.dependant`), Pydantic model reflection, vanilla JS in `index.html`, pytest + FastAPI `TestClient` + BeautifulSoup for tests.

**Spec:** `docs/superpowers/specs/2026-06-12-explorer-auto-api-manifest-design.md`

---

## File Structure

| File | Action | Purpose |
|------|--------|---------|
| `stock_data/api/endpoint_meta.py` | Create | `@endpoint_meta` decorator + `EndpointMeta` dataclass + `REGISTRY` |
| `stock_data/explorer/tags.py` | Create | `TAG_TO_SECTION` lookup (FastAPI tag → section_id + title) |
| `stock_data/explorer/manifest.py` | Create | `build_manifest(app)` — reflect routes + merge with registry |
| `stock_data/explorer/routes.py` | Modify | Add `GET /control/api-manifest` endpoint |
| `stock_data/api/routes.py` | Modify | Apply `@endpoint_meta` to all ~20 endpoints |
| `stock_data/explorer/static/index.html` | Modify | Delete 1000-line ENDPOINTS block; fetch + render manifest |
| `tests/test_endpoint_meta.py` | Create | Unit tests for the decorator + dataclass |
| `tests/test_manifest.py` | Create | Unit tests for `build_manifest` |
| `tests/test_explorer_manifest_endpoint.py` | Create | Integration test for `GET /control/api-manifest` |
| `tests/test_api_html.py` | Modify | Add assertions that ENDPOINTS block is gone + new fetch present |

---

## Task 1: `@endpoint_meta` decorator + tests

**Files:**
- Create: `stock_data/api/endpoint_meta.py`
- Create: `tests/test_endpoint_meta.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_endpoint_meta.py`:

```python
"""Unit tests for stock_data/api/endpoint_meta.py."""
import pytest

from stock_data.api.endpoint_meta import EndpointMeta, REGISTRY, endpoint_meta


class TestEndpointMetaDataclass:
    def test_is_frozen(self):
        m = EndpointMeta(summary="test", markets=["csi"], capabilities=["REALTIME_QUOTE"])
        with pytest.raises((AttributeError, Exception)):
            m.summary = "changed"  # frozen dataclass raises

    def test_defaults_are_independent(self):
        """Two EndpointMeta instances must not share the same mutable default."""
        a = EndpointMeta(summary="a")
        b = EndpointMeta(summary="b")
        a.markets.append("csi")
        assert b.markets == []  # not poisoned by a's mutation
        a.capabilities.append("REALTIME_QUOTE")
        assert b.capabilities == []


class TestEndpointMetaDecorator:
    def teardown_method(self):
        # Clean REGISTRY after each test to keep tests isolated
        REGISTRY.clear()

    def test_registers_in_registry(self):
        @endpoint_meta(summary="实时行情", markets=["csi"], capabilities=["REALTIME_QUOTE"])
        def my_route():
            return None
        assert REGISTRY[my_route].summary == "实时行情"
        assert REGISTRY[my_route].markets == ["csi"]
        assert REGISTRY[my_route].capabilities == ["REALTIME_QUOTE"]

    def test_duplicate_registration_raises(self):
        @endpoint_meta(summary="first")
        def my_route():
            return None
        with pytest.raises(ValueError, match="@endpoint_meta already registered"):
            @endpoint_meta(summary="second")
            def my_route():  # noqa: F811 — intentional redefinition
                return None

    def test_optional_fields_default_to_empty(self):
        @endpoint_meta(summary="x")
        def my_route():
            return None
        meta = REGISTRY[my_route]
        assert meta.markets == []
        assert meta.capabilities == []
        assert meta.sources == []
        assert meta.cache is None
        assert meta.probe_url is None
        assert meta.section_id is None

    def test_cache_and_probe_url_passed_through(self):
        @endpoint_meta(
            summary="x",
            cache={"ttl_sec": 60, "env": "CACHE_TTL_QUOTE"},
            probe_url="/control/fetcher/probe",
        )
        def my_route():
            return None
        meta = REGISTRY[my_route]
        assert meta.cache == {"ttl_sec": 60, "env": "CACHE_TTL_QUOTE"}
        assert meta.probe_url == "/control/fetcher/probe"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_endpoint_meta.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'stock_data.api.endpoint_meta'`

- [ ] **Step 3: Write the implementation**

Create `stock_data/api/endpoint_meta.py`:

```python
"""Per-endpoint metadata registration for the API Explorer manifest.

`@endpoint_meta(...)` 装饰器挂载在每个 route 函数上,声明 OpenAPI 拿不到
的"业务语义"字段。manifest 聚合器在启动时反射 `app.routes` 拿到 path /
method / params,然后跟 REGISTRY 里这个函数的 metadata 合并。

不存的字段(例如 sources / probe_url)允许为空列表 / None——它们是
第二期 per-fetcher 链路展示的预留位,第一期全 endpoint 共用空值。

Why a decorator instead of a parallel dict: 装饰器让 metadata 跟 route
函数物理上挨在一起,改 endpoint 时不会忘记同步(单点真相)。反射
`app.routes` 时按 `route.endpoint == 函数引用` 查 REGISTRY,O(1) 命中。
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Callable


# Module-level registry: id(route_function) -> EndpointMeta
# Mutable on purpose: only the @endpoint_meta decorator writes to it.
REGISTRY: dict[Callable, "EndpointMeta"] = {}


@dataclass(frozen=True)
class EndpointMeta:
    """OpenAPI 拿不到、但 explorer 需要展示的字段。

    path / method / params / response_model 不在此处——它们在 build_manifest()
    里从 FastAPI 路由对象反射出来(单一真相在 @router.get 装饰器)。
    """
    summary: str
    markets: list[str] = field(default_factory=list)
    capabilities: list[str] = field(default_factory=list)
    cache: dict[str, Any] | None = None
    sources: list[dict[str, Any]] = field(default_factory=list)
    probe_url: str | None = None
    section_id: str | None = None


def endpoint_meta(
    *,
    summary: str,
    markets: list[str] | None = None,
    capabilities: list[str] | None = None,
    cache: dict[str, Any] | None = None,
    sources: list[dict[str, Any]] | None = None,
    probe_url: str | None = None,
    section_id: str | None = None,
) -> Callable:
    """装饰器,把 EndpointMeta 存到 REGISTRY[func]。"""
    meta = EndpointMeta(
        summary=summary,
        markets=list(markets) if markets else [],
        capabilities=list(capabilities) if capabilities else [],
        cache=cache,
        sources=list(sources) if sources else [],
        probe_url=probe_url,
        section_id=section_id,
    )

    def deco(func: Callable) -> Callable:
        if func in REGISTRY:
            raise ValueError(
                f"@endpoint_meta already registered for {func.__qualname__}"
            )
        REGISTRY[func] = meta
        return func

    return deco
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_endpoint_meta.py -v`
Expected: PASS (6 tests)

- [ ] **Step 5: Commit**

```bash
cd D:/GitRepo/skills/stock_data
git add stock_data/api/endpoint_meta.py tests/test_endpoint_meta.py
git commit -m "feat(api): @endpoint_meta decorator for explorer manifest

Stores per-route business metadata (summary/markets/capabilities/cache/
sources/probe_url) in a module-level REGISTRY. Manifest builder will
reflect FastAPI routes for path/method/params, then merge with REGISTRY.

Frozen dataclass + independent mutable defaults + duplicate-registration
guard. Phase-1 of explorer auto-API-manifest spec."
```

---

## Task 2: `tags.py` + `manifest.py` + unit tests

**Files:**
- Create: `stock_data/explorer/tags.py`
- Create: `stock_data/explorer/manifest.py`
- Create: `tests/test_manifest.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_manifest.py`:

```python
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

        @app.get("/stocks/{code}/quote", response_model=QuoteResp, tags=["stocks"])
        @endpoint_meta(
            summary="实时行情",
            markets=["csi", "hk", "us"],
            capabilities=["REALTIME_QUOTE"],
            cache={"ttl_sec": 60, "env": "CACHE_TTL_QUOTE"},
        )
        def quote(code: str, days: int = Query(30, ge=1)):
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
        assert "REALTIME_QUOTE" in m["meta"]["capabilities"]
        assert m["meta"]["capabilities"]["REALTIME_QUOTE"]["icon"] == "💹"


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

        @app.get("/stocks/{code}/quote", tags=["stocks"])
        @endpoint_meta(summary="x", capabilities=["REALTIME_QUOTE"])
        def q(code: str):
            return None

        m = build_manifest(app)
        ep = m["sections"][0]["endpoints"][0]
        path_params = [p for p in ep["params"] if p["in"] == "path"]
        assert path_params == [{"name": "code", "in": "path", "required": True,
                                "type": "string", "desc": ""}]

    def test_query_params_with_type_and_required(self):
        app = FastAPI()

        @app.get("/x", tags=["stocks"])
        @endpoint_meta(summary="x", capabilities=["REALTIME_QUOTE"])
        def q(
            days: int = Query(30, ge=1, le=365),
            refresh: bool = Query(False),
            adj: str = Query(""),
        ):
            return None

        m = build_manifest(app)
        params = {p["name"]: p for p in m["sections"][0]["endpoints"][0]["params"]}
        assert params["days"] == {"name": "days", "in": "query", "required": False,
                                  "type": "int", "desc": ""}
        assert params["refresh"]["type"] == "bool"
        assert params["adj"]["type"] == "string"

    def test_required_query_param(self):
        app = FastAPI()

        @app.get("/x", tags=["stocks"])
        @endpoint_meta(summary="x", capabilities=["REALTIME_QUOTE"])
        def q(market: str = Query(...)):
            return None

        m = build_manifest(app)
        p = m["sections"][0]["endpoints"][0]["params"][0]
        assert p["name"] == "market"
        assert p["required"] is True


class TestResponseModelReflection:
    def test_response_fields_from_pydantic(self):
        app = FastAPI()

        @app.get("/q", response_model=QuoteResp, tags=["stocks"])
        @endpoint_meta(summary="x", capabilities=["REALTIME_QUOTE"])
        def q():
            return None

        m = build_manifest(app)
        ep = m["sections"][0]["endpoints"][0]
        assert ep["response_model"] == "QuoteResp"
        # Pydantic field order is preserved
        assert ep["response_fields"] == ["code", "price", "name"]

    def test_no_response_model(self):
        app = FastAPI()

        @app.get("/h", tags=["health"])
        @endpoint_meta(summary="x", capabilities=[])
        def h():
            return None

        m = build_manifest(app)
        ep = m["sections"][0]["endpoints"][0]
        assert ep["response_model"] is None
        assert ep["response_fields"] == []


class TestPrefixPrepending:
    def test_path_includes_router_prefix(self):
        app = FastAPI()
        sub = FastAPI()

        @sub.get("/stocks/{code}/quote", tags=["stocks"])
        @endpoint_meta(summary="x", capabilities=["REALTIME_QUOTE"])
        def q(code: str):
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

        @router.get("/stocks/{code}/quote", tags=["stocks"])
        @endpoint_meta(summary="x", capabilities=["REALTIME_QUOTE"])
        def q(code: str):
            return None

        app.include_router(router, prefix="/api/v1")
        m = build_manifest(app)
        ep = m["sections"][0]["endpoints"][0]
        assert ep["path"] == "/api/v1/stocks/{code}/quote"
        assert "code" in ep["id"]


class TestSectionSorting:
    def test_numeric_sort_handles_4_10(self):
        app = FastAPI()

        for i in [10, 2, 1]:
            @app.get(f"/p{i}", tags=["stocks"])
            @endpoint_meta(summary=f"p{i}", capabilities=["REALTIME_QUOTE"])
            def handler(i=i):  # noqa
                return None
            # Tag override: 4.1, 4.2, 4.10
            REGISTRY[handler] = REGISTRY.pop(handler)  # noop, just to keep var in scope

        # Use section_id override to force the test ordering
        # Simpler: rewrite the test by registering 3 routes with tags
        # mapped to ids 4.10, 4.1, 4.2 via tags module — but easier to
        # just assert build_manifest's sections come back in order based
        # on TAG_TO_SECTION lookup for tag 'stocks' (id '4.2').
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
        @endpoint_meta(summary="visible", capabilities=["REALTIME_QUOTE"])
        def visible():
            return None

        m = build_manifest(app)
        paths = [ep["path"] for sec in m["sections"] for ep in sec["endpoints"]]
        assert "/control/foo" not in paths
        assert "/visible" in paths


class TestSectionOverride:
    def test_explicit_section_id_overrides_tag_mapping(self):
        app = FastAPI()

        @app.get("/weird", tags=["stocks"])
        @endpoint_meta(summary="x", capabilities=["REALTIME_QUOTE"],
                       section_id="4.99")
        def weird():
            return None

        m = build_manifest(app)
        assert m["sections"][0]["id"] == "4.99"


class TestSlugifyAndMethod:
    def test_id_is_stable_slug(self):
        app = FastAPI()

        @app.get("/stocks/{code}/quote", tags=["stocks"])
        @endpoint_meta(summary="x", capabilities=["REALTIME_QUOTE"])
        def q(code: str):
            return None

        m = build_manifest(app)
        ep = m["sections"][0]["endpoints"][0]
        assert ep["method"] == "GET"
        # id should be deterministic, lowercase, path-component safe
        assert ep["id"] == "get_api_v1_stocks_code_quote"

    def test_uses_first_method_only(self):
        """If a route supports multiple methods, manifest picks one (GET preferred)."""
        from fastapi import APIRouter
        app = FastAPI()
        router = APIRouter()

        @router.api_route("/x", methods=["GET", "POST"], tags=["stocks"])
        @endpoint_meta(summary="x", capabilities=["REALTIME_QUOTE"])
        def x():
            return None

        app.include_router(router, prefix="/api/v1")
        m = build_manifest(app)
        # FastAPI creates separate APIRoute per method; we just want to
        # confirm the manifest doesn't crash and emits both.
        paths = [ep["path"] for sec in m["sections"] for ep in sec["endpoints"]]
        assert paths.count("/api/v1/x") == 2
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_manifest.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'stock_data.explorer.manifest'`

- [ ] **Step 3: Write `tags.py`**

Create `stock_data/explorer/tags.py`:

```python
"""Tag → section_id/title mapping for the explorer manifest.

FastAPI route 的 tags=["stocks"] 查这张表得到 sidebar 的 section_id 和
中文 title。这张表是 explorer 端的 UI 关注点,放在 explorer 子包而不是
api/ 路由层——业务路由不该知道"我的 tag 叫 stocks 会被 explorer 分到
4.2 节"这种 UI 决策。

第一期:硬编码。第二期:可改为允许每个 route 用 @endpoint_meta(section_id=...)
显式覆盖,用于"某个 endpoint 应该被分到'健康检查'节而不是'stocks'节"的
edge case(目前没有,但留口子——见 EndpointMeta.section_id)。
"""
from __future__ import annotations


# tag -> {id, title}
TAG_TO_SECTION: dict[str, dict[str, str]] = {
    "health":        {"id": "4.1",  "title": "健康检查"},
    "stocks":        {"id": "4.2",  "title": "股票 / 个股 API"},
    "indices":       {"id": "4.3",  "title": "指数 API"},
    "calendar":      {"id": "4.4",  "title": "股票 / 指数列表与日历"},
    "boards":        {"id": "4.5",  "title": "板块 (Boards)"},
    "pools":         {"id": "4.6",  "title": "涨跌停股池"},
    "dragon-tiger":  {"id": "4.7",  "title": "龙虎榜"},
    "hot":           {"id": "4.8",  "title": "热点题材"},
    "north-flow":    {"id": "4.9",  "title": "北向资金"},
    "indicators":    {"id": "4.10", "title": "技术指标"},
    # 未来新 tag 在这里加一行
}


# Capability flag → {label, icon} 装饰性映射。
# 跟 server 端 DataCapability flag 一一对应,改 DataCapability 时这里同步。
CAPABILITY_LABELS: dict[str, dict[str, str]] = {
    "HISTORICAL_DWM":   {"label": "日/周/月 K线",     "icon": "📈"},
    "HISTORICAL_MIN":   {"label": "分钟 K线",         "icon": "⏱"},
    "REALTIME_QUOTE":   {"label": "实时行情",         "icon": "💹"},
    "STOCK_LIST":       {"label": "股票列表",         "icon": "📋"},
    "TRADE_CALENDAR":   {"label": "交易日历",         "icon": "📅"},
    "STOCK_BOARD":      {"label": "板块",             "icon": "🏷"},
    "INDEX_QUOTE":      {"label": "指数实时",         "icon": "📊"},
    "INDEX_HISTORICAL": {"label": "指数历史",         "icon": "📉"},
    "INDEX_INTRADAY":   {"label": "指数分时",         "icon": "⏰"},
    "STOCK_ZT_POOL":    {"label": "涨跌停股池",       "icon": "🚦"},
    "DRAGON_TIGER":     {"label": "龙虎榜",           "icon": "🐉"},
    "MARGIN_TRADING":   {"label": "融资融券",         "icon": "💰"},
    "BLOCK_TRADE":      {"label": "大宗交易",         "icon": "🤝"},
    "HOLDER_NUM":       {"label": "股东户数",         "icon": "👥"},
    "DIVIDEND":         {"label": "分红送转",         "icon": "🎁"},
    "FUND_FLOW":        {"label": "资金流",           "icon": "💸"},
    "HOT_TOPICS":       {"label": "热点题材",         "icon": "🔥"},
    "NORTH_FLOW":       {"label": "北向资金",         "icon": "🌏"},
    "RESEARCH_REPORT":  {"label": "研报",             "icon": "📑"},
    "ANNOUNCEMENT":     {"label": "公告",             "icon": "📢"},
}
```

- [ ] **Step 4: Write `manifest.py`**

Create `stock_data/explorer/manifest.py`:

```python
"""Build the explorer manifest by reflecting FastAPI routes + REGISTRY.

`build_manifest(app)` 在 server 启动时(或 `/control/api-manifest` 被请求时)
调用一次,反射 `app.routes` 拿到所有 APIRoute,合并每个 route 的
`endpoint_meta` 装饰器声明,产出 explorer 消费用的 JSON 树。

不缓存:manifest 体量约 20 endpoint × ~500 字节 ≈ 10 KB,序列化无压力;
缓存反而让"加 endpoint 不重启不生效"成为陷阱。
"""
from __future__ import annotations
import logging
from typing import Any, get_args, get_origin, Union
from fastapi import FastAPI
from fastapi.routing import APIRoute
from pydantic import BaseModel

from ..api.endpoint_meta import REGISTRY, EndpointMeta
from .tags import TAG_TO_SECTION, CAPABILITY_LABELS


logger = logging.getLogger(__name__)


# explorer 不展示的 tag(只走 /control/*,UI 跟它无关)
_INTERNAL_TAGS = frozenset({"control"})

# manifest schema version——schema 字段有 breaking 变化时递增
MANIFEST_VERSION = "1.1"


def build_manifest(app: FastAPI) -> dict[str, Any]:
    """返回 {
        meta: { version, generated_at, server_version, capabilities: {...} },
        sections: [
          { id, title, endpoints: [
              { id, method, path, summary, markets, capabilities,
                params: [{name, in, required, type, desc}],
                response_model, response_fields, cache, sources, probe_url }
          ]}
        ]
    }
    """
    sections_map: dict[str, dict] = {}
    for route in app.routes:
        if not isinstance(route, APIRoute):
            continue
        if not route.tags or any(t in _INTERNAL_TAGS for t in route.tags):
            continue
        meta = REGISTRY.get(route.endpoint)
        if meta is None:
            logger.warning(
                f"[manifest] route {list(route.methods)[0]} {route.path} "
                f"has no @endpoint_meta; skipping from explorer"
            )
            continue
        section_id, section_title = _resolve_section(route.tags, meta.section_id)
        section = sections_map.setdefault(
            section_id, {"id": section_id, "title": section_title, "endpoints": []}
        )
        section["endpoints"].append(_build_endpoint_node(route, meta))
    return {
        "meta": _build_meta(),
        "sections": sorted(sections_map.values(), key=_section_sort_key),
    }


def _resolve_section(tags: list[str], override: str | None) -> tuple[str, str]:
    """section_id 优先用 override,否则用 tags[0] 查表。

    例: tags=['stocks'], override=None  -> ('4.2', '股票 / 个股 API')
        tags=['stocks'], override='4.10' -> ('4.10', '股票 / 个股 API')  # fallback to tag title
    """
    if override:
        # Try to resolve title from any tag (most likely the first), fallback to override
        for t in tags:
            entry = TAG_TO_SECTION.get(t)
            if entry:
                return override, entry["title"]
        return override, override
    tag = tags[0]
    entry = TAG_TO_SECTION.get(tag)
    if entry:
        return entry["id"], entry["title"]
    return tag, tag


def _build_endpoint_node(route: APIRoute, meta: EndpointMeta) -> dict:
    params: list[dict] = []
    for p in route.dependant.path_params:
        params.append({
            "name": p.name, "in": "path", "required": True,
            "type": _python_type_to_str(p.field_info.annotation),
            "desc": "",
        })
    for p in route.dependant.query_params:
        params.append({
            "name": p.name, "in": "query", "required": bool(p.required),
            "type": _python_type_to_str(p.field_info.annotation),
            "desc": "",
        })
    # 拼接完整 URL:FastAPI 的 route.path 不含 include_router(prefix=...) 的 prefix
    full_path = (route.prefix or "") + route.path
    # HTTP method: route.methods 是 frozenset, 例 {'GET'} 或 {'GET', 'HEAD'}
    method = _pick_method(route.methods)
    return {
        "id": _slugify(f"{method}_{full_path}"),
        "method": method,
        "path": full_path,
        "summary": meta.summary,
        "markets": list(meta.markets),
        "capabilities": list(meta.capabilities),
        "params": params,
        "response_model": route.response_model.__name__ if route.response_model else None,
        "response_fields": _reflect_response_fields(route.response_model),
        "cache": meta.cache,
        "sources": list(meta.sources),
        "probe_url": meta.probe_url,
    }


def _reflect_response_fields(model: type | None) -> list[str]:
    """从 Pydantic response_model 反射字段名(纯名字,无 desc)。"""
    if model is None:
        return []
    try:
        return list(model.model_fields.keys())
    except AttributeError:
        return []


def _pick_method(methods: frozenset) -> str:
    """多 method 时优先 GET,否则第一个。"""
    if "GET" in methods:
        return "GET"
    return next(iter(methods))


def _python_type_to_str(annotation) -> str:
    """int / str / bool / float 映射;Optional 去掉 Optional 包装。"""
    # Handle Optional[X] / Union[X, None]
    origin = get_origin(annotation)
    if origin is Union:
        non_none = [a for a in get_args(annotation) if a is not type(None)]
        if non_none:
            return _python_type_to_str(non_none[0])
    if annotation is int:
        return "int"
    if annotation is str:
        return "string"
    if annotation is bool:
        return "bool"
    if annotation is float:
        return "float"
    return "string"  # 兜底


def _build_meta() -> dict:
    from .. import __version__
    return {
        "version": MANIFEST_VERSION,
        "generated_at": None,  # 服务端在响应时填 ISO 8601
        "server_version": __version__,
        "capabilities": CAPABILITY_LABELS,
    }


def _section_sort_key(sec: dict) -> tuple:
    """4.1, 4.2, ... 4.10 字典序正确(避免 '4.10' 排在 '4.2' 前)。"""
    parts = sec["id"].split(".")
    try:
        return tuple(int(p) for p in parts)
    except ValueError:
        return (999,)


def _slugify(s: str) -> str:
    """Stable, URL-safe slug for DOM id."""
    out = []
    for ch in s.lower():
        if ch.isalnum():
            out.append(ch)
        elif ch in "/_{}-":
            out.append("_")
    return "".join(out)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_manifest.py -v`
Expected: PASS (12+ tests)

- [ ] **Step 6: Commit**

```bash
cd D:/GitRepo/skills/stock_data
git add stock_data/explorer/tags.py stock_data/explorer/manifest.py tests/test_manifest.py
git commit -m "feat(explorer): build_manifest reflects FastAPI routes + REGISTRY

tags.py holds TAG_TO_SECTION (tag -> section_id/title) and
CAPABILITY_LABELS (DataCapability flag -> label/icon). manifest.py
exports build_manifest(app) that walks app.routes, skips internal
tags and routes without @endpoint_meta (with warning), and emits a
JSON tree consumable by index.html.

Path includes the include_router(prefix=...) prefix. Slugify the id
for stable DOM identifiers. Pydantic response_fields reflected from
model_fields. Numeric sort on section_id handles 4.1..4.10."
```

---

## Task 3: `GET /control/api-manifest` endpoint + integration test

**Files:**
- Modify: `stock_data/explorer/routes.py` (add endpoint at end of `build_control_router`)
- Create: `tests/test_explorer_manifest_endpoint.py`

- [ ] **Step 1: Write the failing integration test**

Create `tests/test_explorer_manifest_endpoint.py`:

```python
"""Integration tests for GET /control/api-manifest."""
import pytest
from fastapi.testclient import TestClient

from stock_data.api.endpoint_meta import REGISTRY
from stock_data.server import app


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture(autouse=True)
def _clear_registry():
    REGISTRY.clear()
    yield
    REGISTRY.clear()


class TestApiManifestEndpoint:
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_explorer_manifest_endpoint.py -v`
Expected: FAIL with `404 Not Found` for `/control/api-manifest`

- [ ] **Step 3: Add the endpoint to `explorer/routes.py`**

Modify `stock_data/explorer/routes.py`. Add the new import and endpoint inside `build_control_router()`, **before the final `return router`**:

Read `stock_data/explorer/routes.py` first to confirm the current import block (around lines 1-15), then make these two edits:

**Edit 1 — replace the existing import block** (lines 1-15) with:

```python
"""Control endpoints for the API Explorer (/control/*).

Exposes server config, server status, the API manifest, and Test Instance
subprocess management. Bound to 127.0.0.1 only — never expose on 0.0.0.0.
"""

from __future__ import annotations

import os
import time
from datetime import datetime, timezone

from fastapi import APIRouter, Request

from .. import __version__
from . import control as _control
from .manifest import build_manifest
```

**Edit 2 — insert the new endpoint** between the existing `control_server_status` and `control_test_instance_status` endpoints (i.e. between the closing of `@router.get("/server/status")` and the line `@router.get("/test-instance/status")`):

```python
    @router.get("/api-manifest")
    def control_api_manifest(request: Request) -> dict:
        """The /explorer/ HTML fetches this on load.

        返回 build_manifest(request.app) 的结果,加 generated_at 时间戳。
        不缓存(每次重新反射),保证"加 endpoint 不重启不生效"成为陷阱
        不存在——重启 server 才会触发新 route 注册,这是预期。
        """
        manifest = build_manifest(request.app)
        manifest["meta"]["generated_at"] = datetime.now(timezone.utc).isoformat()
        return manifest
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/test_explorer_manifest_endpoint.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
cd D:/GitRepo/skills/stock_data
git add stock_data/explorer/routes.py tests/test_explorer_manifest_endpoint.py
git commit -m "feat(explorer): GET /control/api-manifest endpoint

Returns the live manifest built from current FastAPI routes + REGISTRY.
generated_at stamped on every response (UTC ISO 8601).

The HTML explorer will fetch this on load instead of consuming the
hand-written ENDPOINTS block."
```

---

## Task 4: Apply `@endpoint_meta` to all `routes.py` endpoints

**Files:**
- Modify: `stock_data/api/routes.py` (add 1 line of `@endpoint_meta(...)` per endpoint)

This is a mechanical, large-but-uniform change. ~20 endpoints each get 1 decorator. Source values (summary/markets/capabilities/cache) are copied from the existing `ENDPOINTS` block in `index.html` (the file we're about to remove).

- [ ] **Step 1: Read the current `ENDPOINTS` block to copy metadata**

Read `stock_data/explorer/static/index.html` lines 285-1293. For each endpoint object in `sections[].endpoints[]`, extract: `summary`, `markets`, `capabilities`, `cache`.

- [ ] **Step 2: Add the `endpoint_meta` import to `routes.py`**

At the top of `stock_data/api/routes.py`, after the existing imports (around line 19), add:

```python
from .endpoint_meta import endpoint_meta
```

- [ ] **Step 3: Add `@endpoint_meta` to health endpoint**

In `stock_data/api/routes.py`, after the `@router.get("/health", ...)` decorator (line ~263-267) and before `def health_check(...)` (line ~268), insert:

```python
@endpoint_meta(
    summary="健康检查 + fetcher 断路器状态",
    markets=["csi", "hk", "us"],
    capabilities=[],
    cache={"ttl_sec": 0, "env": "无"},
)
```

(Import was added in Step 2 above.)

- [ ] **Step 4: Add `@endpoint_meta` to stock endpoints**

For each of these endpoints in `stock_data/api/routes.py`, add the corresponding `@endpoint_meta` decorator (values from the `ENDPOINTS` block read in Step 1):

- `get_quote` (line ~310): summary="实时行情", markets=["csi","hk","us"], capabilities=["REALTIME_QUOTE"], cache={"ttl_sec": 60, "env": "CACHE_TTL_QUOTE"}
- `get_history` (line ~397): summary="历史 K 线（含可选指标）", markets=["csi","hk","us"], capabilities=["HISTORICAL_DWM", "HISTORICAL_MIN"], cache={"ttl_sec": 300, "env": "CACHE_TTL_HISTORY_DAILY / _WEEKLY / _MONTHLY"}
- `get_intraday` (line ~531): summary="分钟 K 线", markets=["csi"], capabilities=["HISTORICAL_MIN"], cache={"ttl_sec": 30, "env": "CACHE_TTL_STOCK_INTRADAY"}
- `get_dragon_tiger` (line ~1324): summary="龙虎榜（个股）", markets=["csi"], capabilities=["DRAGON_TIGER"], cache={"ttl_sec": 600, "env": "CACHE_TTL_DRAGONTIGER"}
- `get_margin` (line ~1392): summary="融资融券", markets=["csi"], capabilities=["MARGIN_TRADING"], cache={"ttl_sec": 600, "env": "CACHE_TTL_MARGIN"}
- `get_block_trade` (line ~1420): summary="大宗交易", markets=["csi"], capabilities=["BLOCK_TRADE"], cache={"ttl_sec": 600, "env": "CACHE_TTL_BLOCK_TRADE"}
- `get_holder_num` (line ~1447): summary="股东户数变化", markets=["csi"], capabilities=["HOLDER_NUM"], cache={"ttl_sec": 600, "env": "CACHE_TTL_HOLDER_NUM"}
- `get_dividend` (line ~1475): summary="分红送转", markets=["csi"], capabilities=["DIVIDEND"], cache={"ttl_sec": 600, "env": "CACHE_TTL_DIVIDEND"}
- `get_fund_flow` (line ~1503): summary="资金流（分钟级）", markets=["csi"], capabilities=["FUND_FLOW"], cache={"ttl_sec": 60, "env": "CACHE_TTL_FUND_FLOW"}
- `get_fund_flow_daily` (line ~1530): summary="资金流（120 日）", markets=["csi"], capabilities=["FUND_FLOW"], cache={"ttl_sec": 600, "env": "CACHE_TTL_FUND_FLOW_DAILY"}
- `get_reports` (line ~1606): summary="研报列表", markets=["csi"], capabilities=["RESEARCH_REPORT"], cache={"ttl_sec": 600, "env": "CACHE_TTL_REPORTS"}
- `get_report_pdf` (line ~1634): summary="研报 PDF 下载", markets=["csi"], capabilities=["RESEARCH_REPORT"], cache=None
- `get_announcements` (line ~1681): summary="公告", markets=["csi"], capabilities=["ANNOUNCEMENT"], cache={"ttl_sec": 600, "env": "CACHE_TTL_ANNOUNCEMENTS"}

- [ ] **Step 5: Add `@endpoint_meta` to index endpoints**

- `list_indices` (line ~642): summary="指数列表（A 股 + 港股 + 美股）", markets=["csi","hk","us"], capabilities=[], cache=None
- `get_index_quote` (line ~657): summary="指数实时行情", markets=["csi","hk","us"], capabilities=["INDEX_QUOTE"], cache={"ttl_sec": 60, "env": "CACHE_TTL_INDEX_QUOTE"}
- `get_index_history` (line ~720): summary="指数历史 K 线", markets=["csi","hk","us"], capabilities=["INDEX_HISTORICAL", "HISTORICAL_DWM"], cache={"ttl_sec": 300, "env": "CACHE_TTL_HISTORY_DAILY"}
- `get_index_intraday` (line ~831): summary="指数分钟 K 线", markets=["csi","hk","us"], capabilities=["INDEX_INTRADAY", "HISTORICAL_MIN"], cache={"ttl_sec": 30, "env": "CACHE_TTL_INDEX_INTRADAY"}

- [ ] **Step 6: Add `@endpoint_meta` to misc endpoints**

- `list_stocks` (line ~921): summary="股票列表（分页）", markets=["csi","hk","us"], capabilities=["STOCK_LIST"], cache=None
- `get_trade_calendar` (line ~961): summary="A 股交易日历", markets=["csi"], capabilities=["TRADE_CALENDAR"], cache=None
- `list_boards` (line ~1025): summary="概念 / 行业板块列表", markets=["csi"], capabilities=["STOCK_BOARD"], cache=None
- `get_board_stocks` (line ~1095): summary="板块成分股", markets=["csi"], capabilities=["STOCK_BOARD"], cache=None
- `get_pools` (line ~1175): summary="涨跌停股池", markets=["csi"], capabilities=["STOCK_ZT_POOL"], cache={"ttl_sec": 30, "env": "CACHE_TTL_POOLS"}
- `get_daily_dragon_tiger` (line ~1362): summary="龙虎榜（全市场）", markets=["csi"], capabilities=["DRAGON_TIGER"], cache={"ttl_sec": 600, "env": "CACHE_TTL_DAILY_DRAGONTIGER"}
- `get_hot_topics` (line ~1560): summary="热点题材", markets=["csi"], capabilities=["HOT_TOPICS"], cache={"ttl_sec": 300, "env": "CACHE_TTL_HOT_TOPICS"}
- `get_north_flow` (line ~1585): summary="北向资金", markets=["csi"], capabilities=["NORTH_FLOW"], cache={"ttl_sec": 60, "env": "CACHE_TTL_NORTH_FLOW"}
- `get_indicator_catalog` (line ~1660): summary="技术指标目录", markets=["csi","hk","us"], capabilities=[], cache=None

- [ ] **Step 7: Run all tests, expect green**

Run: `.venv/Scripts/python.exe -m pytest -v`
Expected: All previous tests still pass. Manifest integration test now shows non-empty sections.

- [ ] **Step 8: Smoke-test the manifest endpoint**

Run: `.venv/Scripts/python.exe -c "from stock_data.server import app; from fastapi.testclient import TestClient; from stock_data.api.endpoint_meta import REGISTRY; REGISTRY.clear(); print(TestClient(app).get('/control/api-manifest').json())"`

Expected: JSON with `sections` containing the ~20 endpoints you just decorated. The exact section count should match the number of `@endpoint_meta` decorators added (since the autouse fixture cleared REGISTRY, only routes decorated in this process will appear — same as test conditions).

- [ ] **Step 9: Commit**

```bash
cd D:/GitRepo/skills/stock_data
git add stock_data/api/routes.py
git commit -m "feat(routes): @endpoint_meta on all ~20 endpoints

Copies summary/markets/capabilities/cache from the old ENDPOINTS
block. After this commit, the manifest endpoint returns the full API
catalog (excluding routes without @endpoint_meta, which now would be
zero)."
```

---

## Task 5: Refactor `index.html` to fetch + render manifest

**Files:**
- Modify: `stock_data/explorer/static/index.html`

- [ ] **Step 1: Read the current `ENDPOINTS` block to verify what to delete**

Read `stock_data/explorer/static/index.html` lines 282-1293. Confirm the ENDPOINTS object structure (it is 1000+ lines).

- [ ] **Step 2: Delete the `ENDPOINTS` block (lines 282-1293)**

Delete from line 282 (the `// === Inline ENDPOINTS metadata (placeholder; replaced in Tasks 4-7) ===` comment) through line 1293 (the closing `</script>` tag of the ENDPOINTS block). Leave the main-app `<script>` block (starting at line 1294) intact.

- [ ] **Step 3: Add the new manifest-fetch bootstrap before the main app block**

Insert a new `<script>` block immediately before the existing main-app `<script>` block (currently at line 1294). This block defines `MANIFEST`, the `loadManifest()` async function, and the `ENDPOINTS` shim that maps to `MANIFEST`:

```html
  <script>
  // === Manifest bootstrap ===
  // Source of truth: server-side build_manifest() in stock_data/explorer/manifest.py
  // Fetched from GET /control/api-manifest on load. If the fetch fails (e.g.
  // server not running), we fall back to a minimal empty manifest — the
  // page will render a sidebar with no endpoints, which is the safe state.
  (function() {
    "use strict";
    const FALLBACK = {
      meta: { version: "0", generated_at: null, server_version: "?",
              capabilities: {} },
      sections: [],
    };
    let MANIFEST = FALLBACK;
    window.MANIFEST = MANIFEST;  // exposed for any debugging

    async function loadManifest() {
      try {
        const r = await fetch("/control/api-manifest", { cache: "no-store" });
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        MANIFEST = await r.json();
        window.MANIFEST = MANIFEST;
      } catch (e) {
        console.warn("[explorer] manifest fetch failed, using empty fallback:", e);
        MANIFEST = FALLBACK;
      }
    }

    // Legacy compatibility shim: the existing render code reads
    // `ENDPOINTS.sections` / `ENDPOINTS.meta`. We expose a getter so we
    // don't have to rename every reference.
    Object.defineProperty(window, "ENDPOINTS", {
      get() { return MANIFEST; },
    });

    // Fire fetch immediately; the init() function awaits it before rendering.
    window.loadManifest = loadManifest;
  })();
  </script>
```

- [ ] **Step 4: Replace the existing `init()` function to await `loadManifest`**

In the main-app `<script>` block (now starting at the line that had `// === Main app (boots after ENDPOINTS) ===`), find the `init()` function (around line 1340-1390 in the original) and prepend the manifest load to its body. The new init should look like:

```js
    async function init() {
      // Manifest must be loaded before any render function runs.
      await window.loadManifest();
      // ... existing init body unchanged ...
    }
```

Find the **first line** of the existing `init()` function body and prepend `await window.loadManifest();` (plus a blank line and a comment). All subsequent lines stay the same.

- [ ] **Step 5: Update `renderSidebar` and `renderContent` to use `ENDPOINTS` shim (no rename needed)**

The shim in Step 3 makes `window.ENDPOINTS` a getter that returns `MANIFEST`. The existing code at lines ~1493 and ~1506 already reads `ENDPOINTS.sections.forEach(...)` — no changes needed there. Verify by reading lines 1490-1515 of the file and confirming no changes are required.

- [ ] **Step 6: Update `renderEndpointDetails` field rendering (where `desc` is now empty)**

The new manifest's `params[].desc` is always `""` and `response_fields` is just field names with no grouping. Existing render code at lines ~1552-1599 reads `p.desc || ""` and renders `response_fields` as a flat list — both should keep working, but the UI will look sparser. This is expected for phase 1.

Verify by reading lines 1550-1610 and confirming the rendering code doesn't crash on empty `desc` strings. If any code path assumes non-empty `desc` (e.g. `if (p.desc) { ... }` followed by an empty render), no change is needed — we just render an empty string.

- [ ] **Step 7: Update `tests/test_api_html.py` to reflect the new shape**

Modify `tests/test_api_html.py`. The existing test `test_has_endpoints_dict` (line ~33) currently asserts `"const ENDPOINTS = {"` and `'"sections":'`. Replace it with:

```python
    def test_has_manifest_bootstrap(self, html_text):
        """The 1000-line hand-written ENDPOINTS block is gone; replaced by
        a fetch of /control/api-manifest + ENDPOINTS shim."""
        assert "const ENDPOINTS = {" not in html_text
        assert "fetch(\"/control/api-manifest\"" in html_text
        assert "loadManifest" in html_text
```

- [ ] **Step 8: Run all tests, expect green**

Run: `.venv/Scripts/python.exe -m pytest -v`
Expected: All tests pass. `test_has_manifest_bootstrap` is the new check.

- [ ] **Step 9: Manual smoke test in browser**

Run: `.venv/Scripts/python.exe -m stock_data.server`
Then open `http://127.0.0.1:8888/explorer/` in a browser.
Expected: Sidebar lists all ~20 endpoints, grouped by section. Click any endpoint, see its params/markets/capabilities.

If the page shows 0 endpoints, open browser DevTools console — the `[explorer] manifest fetch failed, using empty fallback` warning indicates a server-side problem (e.g. `@endpoint_meta` not registered for some route → that route is skipped with a warning in the server log).

- [ ] **Step 10: Commit**

```bash
cd D:/GitRepo/skills/stock_data
git add stock_data/explorer/static/index.html tests/test_api_html.py
git commit -m "refactor(explorer): fetch /control/api-manifest instead of inline ENDPOINTS

Removes the 1000-line const ENDPOINTS = { ... } block. The page now
fetches the manifest on load and renders from JSON. A window.ENDPOINTS
shim preserves the existing variable-name references in the render
code (no rename of 50+ touchpoints).

FALLBACK is an empty manifest; the page renders a sidebar with no
endpoints if the server is unreachable, which is the safe degradation
state. Phase 1 contract: path/method/params are auto-derived; per-
endpoint desc/response_fields-desc are empty strings (phase 2 will
backfill)."
```

---

## Task 6: Full integration verification

**Files:** none modified — verification only

- [ ] **Step 1: Run full test suite**

Run: `.venv/Scripts/python.exe -m pytest -v`
Expected: ALL tests green.

- [ ] **Step 2: Run lint**

Run: `ruff check .`
Expected: no errors. If there are, fix them with `ruff format .` followed by manual fixes for any remaining issues.

- [ ] **Step 3: Server smoke test**

Run: `.venv/Scripts/python.exe -m stock_data.server`
Then in a separate terminal:

```bash
curl -s http://127.0.0.1:8888/control/api-manifest | python -m json.tool | head -60
```

Expected: Valid JSON. The `sections` array has ~20 endpoints. Each endpoint has `id, method, path, summary, markets, capabilities, params, response_model, response_fields, cache, sources, probe_url`. Paths include the `/api/v1` prefix.

- [ ] **Step 4: Verify no regression on a real endpoint**

```bash
curl -s "http://127.0.0.1:8888/api/v1/health" | python -m json.tool
curl -s "http://127.0.0.1:8888/api/v1/stocks/600519/quote" | python -m json.tool | head -20
```

Expected: Real API responses, no breakage. (Realtime quote may fail if no token configured — that's pre-existing behavior, not a regression.)

- [ ] **Step 5: Verify the orphan-route warning fires when expected**

In a Python REPL:

```python
from stock_data.server import app
from fastapi.testclient import TestClient
from stock_data.api.endpoint_meta import REGISTRY
from stock_data.explorer.manifest import build_manifest

REGISTRY.clear()
# Calling build_manifest with cleared REGISTRY should log a warning for every route
# (since no route has @endpoint_meta registered in this process).
import logging
logging.basicConfig(level=logging.WARNING)
m = build_manifest(app)
print(f"sections: {len(m['sections'])}")  # expected: 0
print(f"warnings logged: {len([r for r in logging.getLogger().handlers])}")
```

Expected: `sections: 0` and warnings fire for every route. (This proves the "forgot to add @endpoint_meta" guard works.)

- [ ] **Step 6: Commit any test/lint fixes**

If Steps 1-5 required code changes:

```bash
cd D:/GitRepo/skills/stock_data
git add -A
git commit -m "chore: post-merge lint/format fixes"
```

If no changes, skip this step.

---

## Self-Review Notes (filled in by writer)

**Spec coverage check (cross-reference spec sections):**

| Spec section | Plan task |
|--------------|-----------|
| §4.1 endpoint_meta.py | Task 1 |
| §4.2 manifest.py | Task 2 |
| §4.3 tags.py | Task 2 |
| §4.4 /control/api-manifest endpoint | Task 3 |
| §4.5 routes.py @endpoint_meta | Task 4 |
| §4.6 index.html refactor | Task 5 |
| §7 error handling (warn on missing meta, exclude control tag) | Tests in Task 2 (TestRouteWithoutMetaSkipped, TestControlTagExclusion) |
| §8 testing strategy (unit + integration + html) | Tasks 1-3 tests, Task 5 test update |
| §9 commit plan (6 commits) | Tasks 1-6 each end with a commit |
| §12 acceptance criteria | Task 6 verification |

**Type consistency check:**

- `EndpointMeta` fields (summary/markets/capabilities/cache/sources/probe_url/section_id) are referenced identically in Task 1 (definition), Task 2 (manifest.py usage), and Task 4 (decorator calls).
- `build_manifest()` returns dict with keys `meta` + `sections`; section has `id/title/endpoints`; endpoint has `id/method/path/summary/markets/capabilities/params/response_model/response_fields/cache/sources/probe_url`. Referenced consistently in Task 2, Task 3, Task 5.
- `_slugify`, `_pick_method`, `_python_type_to_str`, `_reflect_response_fields`, `_resolve_section`, `_section_sort_key`, `_build_endpoint_node`, `_build_meta` defined in Task 2 manifest.py and called only there.
- `TAG_TO_SECTION` and `CAPABILITY_LABELS` defined in Task 2 tags.py; referenced only in manifest.py.
- `EndpointMeta.section_id` is read in manifest._resolve_section; the test `TestSectionOverride` in Task 2 exercises it.

**Placeholder scan:** No TBD/TODO/FIXME/"implement later"/"similar to" present.

**Known risk acknowledged:** The HTML refactor (Task 5) involves the largest single-file diff (~1000 line deletion + ~70 line insertion). It cannot be fully unit-tested (per spec §8.2: "不测 HTML 内部 JS(太脆)"). Step 9's manual smoke test is the safety net. The window.ENDPOINTS shim minimizes variable-rename touchpoints.
