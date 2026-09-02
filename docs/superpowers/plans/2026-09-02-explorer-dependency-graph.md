# Explorer 依赖关系节点图 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 `/explorer/` 增加一个可交互的依赖关系节点图视图，展示 `endpoint → fetcher`（served-by）与 `agent → endpoint`（composed-of）两类边，点击节点展示入参/body/response schema 等详情。

**Architecture:** 后端扩展 manifest（新增 `depends_on` + `response_schema` 字段，`MANIFEST_VERSION`→1.2），`@endpoint_meta` 新增 `depends_on` 声明参数。前端在现有纯 vanilla JS 单 HTML 里新增 `GraphView`（vis-network via CDN，lazy-load + graceful degradation）与 `NodeDetailPanel` 两个 IIFE 模块，复用 `JSONView`/`ResultPanel`/`el()`/theme/事件委托，topbar 加视图切换。

**Tech Stack:** Python 3.13 + FastAPI + Pydantic v2（后端）；vanilla JS + vis-network 9.x UMD via CDN（前端，无 npm/构建）。

## Global Constraints

- **Python 解释器**：`.venv/Scripts/python.exe`（项目约定；akshare/yfinance/gm 只在 venv）。无 venv 时退化为系统 `python`。
- **测试命令**：`.venv/Scripts/python.exe -m pytest <path> -v`（默认跳过 `live_network`/`requires_token`）。
- **Lint/Format**：`ruff check .` / `ruff format .`，每个后端 task 完成后跑。
- **装饰器契约**：`endpoint_meta.deco` 必须返回原 `func`（`endpoint_meta.py:12-16`），新增 `depends_on` 仅作 dataclass 字段，`deco` 不动。
- **装饰器顺序**：`@router.get → @endpoint_meta → @map_errors → @cache_endpoint → def`（CLAUDE.md Anti-Patterns）。新增 `depends_on` 是 `@endpoint_meta` 的 kwarg，不改顺序。
- **manifest 不缓存**：`build_manifest` 每次请求反射 `app.routes`（`manifest.py:64-105`），新增字段随请求即时生效。
- **manifest 后向兼容**：新字段缺失时前端走 `||` 兜底；`MANIFEST_VERSION` 升级不断现有字段。
- **分支策略**：本项目 `*.md`（spec/plan/docs）直接 commit master；**Python 服务端代码走 `feat/*` 分支**（memory: skip-branch-for-trivial-changes）。Task 1–3（后端 .py）在 `feat/explorer-dependency-graph` 分支；Task 4–6（前端 .html）也走该分支（虽是单文件但属功能代码）。最终合 master。
- **前端无自动测试**：现有 explorer 前端无测试框架。前端 task 靠后端 manifest shape 测试 pin + 手动 smoke（启动 server + 操作验证）。不引入前端测试框架（YAGNI）。
- **vis-network CDN**：`https://cdn.jsdelivr.net/npm/vis-network@9/standalone/umd/vis-network.min.js`，lazy-load（图视图首次激活时加载），失败 graceful degradation 提示。

## File Structure

| 文件 | 责任 | 动作 |
|---|---|---|
| `stock_data/api/endpoint_meta.py` | `EndpointMeta` dataclass + `@endpoint_meta` 装饰器 | Modify：加 `depends_on` 字段 |
| `stock_data/explorer/manifest.py` | `build_manifest` 反射器 | Modify：加 `response_schema` + `depends_on` 解析；`MANIFEST_VERSION`→1.2 |
| `stock_data/api/routes/agent.py` | 8 个 agent route | Modify：每个 `@endpoint_meta` 加 `depends_on=[...]` |
| `stock_data/api/routes/agent_correlation.py` | 1 个 agent route（correlation/matrix） | Modify：`@endpoint_meta` 加 `depends_on=[...]` |
| `stock_data/explorer/static/index.html` | 单 HTML 前端 | Modify：加 `GraphView`/`NodeDetailPanel` IIFE + topbar view switch + boot lazy-load + 集成 |
| `tests/test_manifest.py` | manifest 单元测试 | Modify：version 断言→1.2；加 `response_schema`/`depends_on` 测试 |
| `tests/test_manifest_depends_on.py` | agent depends_on 漂移检测 | Create |

---

### Task 1: 后端 — `response_schema` 字段 + `MANIFEST_VERSION` 1.2

最小独立可测：给每个 endpoint 的 manifest 节点加 `response_schema`（Pydantic `model_json_schema()`，mirror 现有 `body.schema` 逻辑），版本升 1.2。

**Files:**
- Modify: `stock_data/explorer/manifest.py:39`（`MANIFEST_VERSION`）、`manifest.py:108-164`（`_build_endpoint_node`）
- Modify: `tests/test_manifest.py:54-59`（version 断言）、`test_manifest.py:127-150`（`TestResponseModelReflection`）
- Test: `tests/test_manifest.py`

**Interfaces:**
- Consumes: `route.response_model`（FastAPI `APIRoute` 属性，Pydantic class or None）
- Produces: manifest endpoint 节点新增 `response_schema: dict | None`（完整 JSON Schema，无 `response_model` 时为 None）；`meta.version == "1.2"`

- [ ] **Step 1: Write the failing test**

追加到 `tests/test_manifest.py` 的 `TestResponseModelReflection` 类（`test_manifest.py:127` 之后，`test_no_response_model` 之前）：

```python
    def test_response_schema_reflected_when_response_model_set(self):
        app = FastAPI()

        @app.get("/q", response_model=QuoteResp, tags=["stocks"])
        @endpoint_meta(summary="x", capabilities=["STOCK_REALTIME_QUOTE"])
        def q():
            return None

        m = build_manifest(app)
        ep = m["sections"][0]["endpoints"][0]
        assert ep["response_model"] == "QuoteResp"
        # response_schema is the full Pydantic JSON Schema (mirror of body.schema)
        assert isinstance(ep["response_schema"], dict)
        assert ep["response_schema"]["type"] == "object"
        # the three QuoteResp fields appear as properties
        assert set(ep["response_schema"]["properties"].keys()) == {"code", "price", "name"}
        # code is required (no default); name is optional (default None)
        assert "code" in ep["response_schema"].get("required", [])
        assert "name" not in ep["response_schema"].get("required", [])

    def test_response_schema_none_when_no_response_model(self):
        app = FastAPI()

        @app.get("/h", tags=["health"])
        @endpoint_meta(summary="x", capabilities=[])
        def h():
            return None

        m = build_manifest(app)
        ep = m["sections"][0]["endpoints"][0]
        assert ep["response_model"] is None
        assert ep["response_schema"] is None
```

同时把 `test_meta_has_version_and_capabilities`（`test_manifest.py:54-59`）的版本断言从 `"1.1"` 改为 `"1.2"`：

```python
    def test_meta_has_version_and_capabilities(self):
        m = build_manifest(self._build_app())
        assert m["meta"]["version"] == "1.2"
        assert "server_version" in m["meta"]
        assert "STOCK_REALTIME_QUOTE" in m["meta"]["capabilities"]
        assert m["meta"]["capabilities"]["STOCK_REALTIME_QUOTE"]["icon"] == "💹"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_manifest.py::TestResponseModelReflection::test_response_schema_reflected_when_response_model_set tests/test_manifest.py::TestBuildManifestIncludesDecoratedRoutes::test_meta_has_version_and_capabilities -v`

Expected: FAIL — `KeyError: 'response_schema'`（字段未实现）+ `AssertionError: assert "1.1" == "1.2"`（version 未升）。

- [ ] **Step 3: Write minimal implementation**

`stock_data/explorer/manifest.py:39`：

```python
MANIFEST_VERSION = "1.2"
```

`stock_data/explorer/manifest.py`，在 `_build_endpoint_node`（`:108-164`）里，紧跟现有 `body` 反射块（`:133-147`）之后、`return`（`:153`）之前，新增 `response_schema` 反射 + 把字段加进返回 dict：

```python
    # Response body schema: mirror the body.schema reflection above, but for
    # the response_model. route.response_model is the Pydantic class (or None);
    # .model_json_schema() returns the standard JSON Schema (properties /
    # required / $defs / nested). Used by the node-graph detail panel to show
    # the response field inventory. NOTE: this is the STATIC schema —
    # @model_serializer conditional serialization (e.g. KLineData.indicators
    # omit-when-empty) is NOT reflected; see spec §5.3.
    response_schema: dict | None = None
    if route.response_model is not None and hasattr(route.response_model, "model_json_schema"):
        try:
            response_schema = route.response_model.model_json_schema()
        except Exception as e:  # pragma: no cover — defensive
            logger.warning(
                f"[manifest] response schema reflection failed for {route.path}: {e}"
            )
            response_schema = None
```

然后在 `return { ... }`（`:153-164`）的 dict 里，在 `"response_model"` 行（`:162`）之后加：

```python
        "response_schema": response_schema,
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/test_manifest.py -v`

Expected: PASS（全部，含新测试 + 升级后的 version 断言）。

- [ ] **Step 5: Run full manifest-related suite to confirm no regression**

Run: `.venv/Scripts/python.exe -m pytest tests/test_manifest.py tests/test_explorer_manifest_endpoint.py -v`

Expected: PASS（`response_schema` 是新增字段，不破坏现有 `fetchers`/`params`/`body` 断言）。

- [ ] **Step 6: Lint + commit**

```bash
ruff check stock_data/explorer/manifest.py tests/test_manifest.py
ruff format stock_data/explorer/manifest.py tests/test_manifest.py
git add stock_data/explorer/manifest.py tests/test_manifest.py
git commit -m "feat(manifest): add response_schema field + bump MANIFEST_VERSION to 1.2

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 2: 后端 — `depends_on` 字段 + `_resolve_depends_on` 解析

`EndpointMeta` 加 `depends_on: list[str] | None`；`build_manifest` 解析每条依赖为 `{target_path, kind, label}`（`kind` ∈ `"endpoint"`/`"internal"`），path 项归一化匹配（`{code}` 与 `{stock_code}` 等价）。

**Files:**
- Modify: `stock_data/api/endpoint_meta.py:29-70`（`EndpointMeta` + `endpoint_meta` 签名）
- Modify: `stock_data/explorer/manifest.py:64-164`（`build_manifest` 传 app → `_build_endpoint_node`；新增 `_resolve_depends_on` + `_normalize_path`）
- Test: `tests/test_manifest.py`

**Interfaces:**
- Consumes: `EndpointMeta.depends_on`（list[str] | None）；`app.routes`（path 存在性校验）
- Produces: manifest endpoint 节点新增 `depends_on: list[{target_path: str|None, kind: "endpoint"|"internal", label: str}]`（`depends_on` 为 None 时是 `[]`）

- [ ] **Step 1: Write the failing test**

追加到 `tests/test_manifest.py`（文件末尾，新 class）：

```python
class TestDependsOnResolution:
    """depends_on: list[str] where each item is either an endpoint path
    (starts with '/') → kind:"endpoint", or an internal-call label
    ("manager.xxx"/"cache.xxx"/...) → kind:"internal". Path-param names
    are normalized: {code} and {stock_code} both match /stocks/{stock_code}/q.
    """

    def _build_app_with_dep(self):
        app = FastAPI()

        @app.get("/stocks/{stock_code}/quote", tags=["stocks"])
        @endpoint_meta(summary="q", capabilities=["STOCK_REALTIME_QUOTE"])
        def quote(stock_code: str):
            return None

        @app.get("/agent/x", tags=["agent"])
        @endpoint_meta(
            summary="agg",
            capabilities=[],
            depends_on=[
                "/stocks/{code}/quote",  # normalized match against {stock_code}
                "manager.get_realtime_quote",  # internal
                "cache.get_board_list",  # internal
            ],
        )
        def agg():
            return None

        return app

    def test_depends_on_resolves_endpoint_and_internal(self):
        m = build_manifest(self._build_app_with_dep())
        agg = next(
            ep for sec in m["sections"] for ep in sec["endpoints"]
            if ep["path"] == "/agent/x"
        )
        deps = agg["depends_on"]
        assert len(deps) == 3
        # endpoint ref: target_path is the REAL route path ({stock_code}),
        # even though depends_on wrote {code} — normalization matched it.
        assert deps[0] == {
            "target_path": "/stocks/{stock_code}/quote",
            "kind": "endpoint",
            "label": "/stocks/{stock_code}/quote",
        }
        assert deps[1]["kind"] == "internal"
        assert deps[1]["label"] == "manager.get_realtime_quote"
        assert deps[1]["target_path"] is None
        assert deps[2]["kind"] == "internal"
        assert deps[2]["label"] == "cache.get_board_list"

    def test_depends_on_defaults_empty_list_when_unset(self):
        app = FastAPI()

        @app.get("/q", tags=["stocks"])
        @endpoint_meta(summary="q", capabilities=["STOCK_REALTIME_QUOTE"])
        def q():
            return None

        m = build_manifest(app)
        assert m["sections"][0]["endpoints"][0]["depends_on"] == []

    def test_depends_on_path_not_in_routes_falls_back_to_internal(self):
        app = FastAPI()

        @app.get("/agent/x", tags=["agent"])
        @endpoint_meta(
            summary="agg", capabilities=[], depends_on=["/no/such/endpoint"]
        )
        def agg():
            return None

        m = build_manifest(app)
        deps = next(
            ep for sec in m["sections"] for ep in sec["endpoints"]
            if ep["path"] == "/agent/x"
        )["depends_on"]
        # path that matches no route → kind:"internal" (no crash, no edge drawn)
        assert deps == [{"target_path": "/no/such/endpoint", "kind": "internal", "label": "/no/such/endpoint"}]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_manifest.py::TestDependsOnResolution -v`

Expected: FAIL — `TypeError: endpoint_meta() got an unexpected keyword argument 'depends_on'`（字段未加）。

- [ ] **Step 3: Write minimal implementation**

`stock_data/api/endpoint_meta.py`，`EndpointMeta`（`:29-46`）加字段：

```python
@dataclass(frozen=True)
class EndpointMeta:
    """OpenAPI 拿不到、但 explorer 需要展示的字段。

    path / method / params / response_model / response_schema / body 不在此处——
    它们在 build_manifest() 里从 FastAPI 路由对象反射出来(单一真相在
    @router.get 装饰器)。

    `fetcher_method` (optional): overrides the default method derived from
    CAPABILITY_TO_METHOD. Use when the endpoint's capability is shared by
    multiple endpoints calling different fetcher methods (e.g.
    /api/v1/dragon-tiger declares DRAGON_TIGER but calls
    get_daily_dragon_tiger, not the default get_dragon_tiger).

    `depends_on` (optional): for composite (agent) endpoints, declares which
    other endpoints / internal calls this one composes. Each item is either an
    endpoint path (starts with "/") — drawn as a composed-of graph edge — or
    an internal-call label string ("manager.xxx"/"cache.xxx"/"calendar.xxx"/
    "features.xxx") shown only in the detail panel. Path-param names are
    normalized at manifest-build time, so "/stocks/{code}/quote" matches a
    route registered as "/stocks/{stock_code}/quote".
    """

    summary: str
    markets: list[str] = field(default_factory=list)
    capabilities: list[str] = field(default_factory=list)
    fetcher_method: str | None = None
    depends_on: list[str] | None = None
```

`endpoint_meta`（`:49-70`）签名 + dataclass 构造加 `depends_on`：

```python
def endpoint_meta(
    *,
    summary: str,
    markets: list[str] | None = None,
    capabilities: list[str] | None = None,
    fetcher_method: str | None = None,
    depends_on: list[str] | None = None,
) -> Callable:
    """装饰器,把 EndpointMeta 存到 REGISTRY[func]。"""
    meta = EndpointMeta(
        summary=summary,
        markets=list(markets) if markets else [],
        capabilities=list(capabilities) if capabilities else [],
        fetcher_method=fetcher_method,
        depends_on=list(depends_on) if depends_on else None,
    )

    def deco(func: Callable) -> Callable:
        if func in REGISTRY:
            raise ValueError(f"@endpoint_meta already registered for {func.__qualname__}")
        REGISTRY[func] = meta
        return func

    return deco
```

`stock_data/explorer/manifest.py`：

顶部 import 加 `re`（`:13-16` 附近，和 `inspect`/`logging` 同组）：

```python
import re
```

`build_manifest`（`:64-105`）把 `app` 传给 `_build_endpoint_node`（`:101`）：

```python
        section["endpoints"].append(_build_endpoint_node(route, meta, manager, app))
```

`_build_endpoint_node`（`:108-164`）签名加 `app`，并在返回 dict 里加 `depends_on`：

```python
def _build_endpoint_node(route: APIRoute, meta: EndpointMeta, manager, app) -> dict:
```

在函数内（`fetchers = ...` 行 `:152` 之后、`return` `:153` 之前）加：

```python
    depends_on = _resolve_depends_on(meta.depends_on, app) if meta.depends_on else []
```

`return` dict（`:153-164`）加字段（在 `"fetchers": fetchers,` 之后）：

```python
        "depends_on": depends_on,
```

文件末尾新增两个 helper（`_slugify` 之后，`:426-443` 之后）：

```python
def _normalize_path(path: str) -> str:
    """Collapse path-param names so {code} and {stock_code} match the same route.

    depends_on refs may use a different param name than the target route's
    registration (e.g. agent code says {code} but /stocks/{stock_code}/quote
    registered {stock_code}). Normalizing both to {} before comparing makes
    the ref resilient to param-name drift.
    """
    return re.sub(r"\{[^}]+\}", "{}", path)


def _resolve_depends_on(deps: list[str] | None, app: FastAPI) -> list[dict]:
    """Resolve @endpoint_meta(depends_on=[...]) into graph-edge-ready dicts.

    Each item becomes {target_path, kind, label}:
      - starts with "/" and matches a real route (exact OR normalized) →
        kind:"endpoint", target_path = the REAL route path (param name from
        the route, not the ref), label = same. Frontend draws a composed-of
        edge to the endpoint node with this path.
      - otherwise → kind:"internal", target_path=None, label = the item as-is.
        Frontend shows it as text in the detail panel, no graph edge.
    """
    if not deps:
        return []
    # Index real route paths: exact + normalized, so a ref can hit either.
    exact_paths: set[str] = set()
    norm_to_real: dict[str, str] = {}
    for route in app.routes:
        if isinstance(route, APIRoute):
            exact_paths.add(route.path)
            norm_to_real[_normalize_path(route.path)] = route.path
    out: list[dict] = []
    for dep in deps:
        if dep.startswith("/"):
            if dep in exact_paths:
                out.append({"target_path": dep, "kind": "endpoint", "label": dep})
            else:
                real = norm_to_real.get(_normalize_path(dep))
                if real is not None:
                    out.append({"target_path": real, "kind": "endpoint", "label": real})
                else:
                    out.append({"target_path": dep, "kind": "internal", "label": dep})
        else:
            out.append({"target_path": None, "kind": "internal", "label": dep})
    return out
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/test_manifest.py::TestDependsOnResolution -v`

Expected: PASS。

- [ ] **Step 5: Run full manifest suite for regression**

Run: `.venv/Scripts/python.exe -m pytest tests/test_manifest.py tests/test_explorer_manifest_endpoint.py tests/test_endpoint_meta.py -v`

Expected: PASS。

- [ ] **Step 6: Lint + commit**

```bash
ruff check stock_data/api/endpoint_meta.py stock_data/explorer/manifest.py tests/test_manifest.py
ruff format stock_data/api/endpoint_meta.py stock_data/explorer/manifest.py tests/test_manifest.py
git add stock_data/api/endpoint_meta.py stock_data/explorer/manifest.py tests/test_manifest.py
git commit -m "feat(manifest): add depends_on field + _resolve_depends_on path normalization

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 3: 后端 — 9 个 agent route 声明 `depends_on`

给每个 agent route 的 `@endpoint_meta(...)` 加 `depends_on=[...]`，值来自 endpoint↔manager method 映射。新增 `tests/test_manifest_depends_on.py` 检测漂移。

**Files:**
- Modify: `stock_data/api/routes/agent.py`（8 个 route 的 `@endpoint_meta`）
- Modify: `stock_data/api/routes/agent_correlation.py`（1 个 route 的 `@endpoint_meta`）
- Test: `tests/test_manifest_depends_on.py`（Create）

**Interfaces:**
- Consumes: Task 2 的 `depends_on` kwarg + `_resolve_depends_on`
- Produces: 9 个 agent endpoint 的 manifest `depends_on` 非空，每条 path 项能在 manifest 找到匹配 endpoint（漂移检测）

**depends_on 值表**（path 项必须与目标 route 的注册 path 字面匹配参数名归一化后等价；internal 项是自由 label）：

| Agent route | 文件:行 | depends_on |
|---|---|---|
| `POST /agent/boards/stock-overlap` | `agent.py:194`（装饰器 `:202`） | `["/api/v1/boards/{board_code}/stocks", "cache.get_board_stocks"]` |
| `POST /agent/stocks/board-overlap` | `agent.py:279`（`:287`） | `["/api/v1/stocks/{stock_code}/boards", "cache.get_stock_memberships"]` |
| `POST /agent/boards/filter-stocks` | `agent.py:416`（`:424`） | `["/api/v1/boards/{board_code}/stocks", "cache.get_board_stocks", "cache.get_board_name_with_fallback"]` |
| `GET /agent/indices/batch-profile` | `agent.py:594`（`:602`） | `["/api/v1/indices/{index_code}/quote", "/api/v1/indices/{index_code}/kline", "features.build_features"]` |
| `GET /agent/market-context` | `agent.py:702`（`:709`） | `["/api/v1/calendar", "/api/v1/news/morning-briefing", "/api/v1/news/market-recap", "/api/v1/news/flash", "/api/v1/zt-pools", "/api/v1/dragon-tiger", "calendar.is_trade_date", "calendar.get_latest_trade_date_on_or_before"]` |
| `POST /agent/stocks/batch-profile` | `agent.py:856`（`:865`） | `["/api/v1/stocks/{stock_code}/quote", "/api/v1/stocks/{code}/kline", "/api/v1/stocks/{code}/info", "/api/v1/stocks/{stock_code}/boards", "features.build_features", "cache.get_stock_memberships"]` |
| `POST /agent/boards/batch-profile` | `agent.py:1062`（`:1070`） | `["/api/v1/boards/{board_code}/quote", "/api/v1/boards/{board_code}/history", "features.build_features", "cache.get_board_name_with_fallback"]` |
| `GET /agent/market-stats` | `agent.py:1194`（`:1199`） | `["/api/v1/stocks", "/api/v1/boards", "manager.get_realtime_quotes", "cache.get_board_list"]` |
| `POST /agent/correlation/matrix` | `agent_correlation.py:425`（`:430`） | `["/api/v1/stocks/{code}/kline", "/api/v1/boards/{board_code}/history", "manager.get_kline_data", "manager.get_board_history"]` |

> 注意 path 参数名：`/stocks/{code}/kline` 与 `/stocks/{code}/info` 用 `{code}`（`stocks.py:448`/`:355`），`/stocks/{stock_code}/quote` 与 `/stocks/{stock_code}/boards` 用 `{stock_code}`（`stocks.py:396`/`boards.py:866`）。Task 2 的归一化使二者可互换，但上表已按目标 route 的真实参数名书写，exact-match 命中。

- [ ] **Step 1: Write the failing test**

Create `tests/test_manifest_depends_on.py`：

```python
"""Drift detection for @endpoint_meta(depends_on=...) on agent routes.

depends_on is hand-declared (mirrors fetcher_method's manual-override model).
These tests pin:
  - every agent route declares a non-empty depends_on
  - every endpoint-path ref (kind:"endpoint") resolves to a real route in the
    manifest (catches: deleted/renamed endpoint, typo in the path, param-name
    drift the normalizer can't paper over)
  - at least one endpoint ref per agent (so the graph draws a composed-of edge)
"""

import pytest
from fastapi.testclient import TestClient

from stock_data.api.endpoint_meta import REGISTRY
from stock_data.server import app

_REGISTRY_SNAPSHOT: dict = dict(REGISTRY)


# 9 agent routes (8 in agent.py + 1 in agent_correlation.py). method+path
# exactly as registered (router prefix /api/v1 already merged).
AGENT_ROUTES = [
    ("POST", "/api/v1/agent/boards/stock-overlap"),
    ("POST", "/api/v1/agent/stocks/board-overlap"),
    ("POST", "/api/v1/agent/boards/filter-stocks"),
    ("GET", "/api/v1/agent/indices/batch-profile"),
    ("GET", "/api/v1/agent/market-context"),
    ("POST", "/api/v1/agent/stocks/batch-profile"),
    ("POST", "/api/v1/agent/boards/batch-profile"),
    ("GET", "/api/v1/agent/market-stats"),
    ("POST", "/api/v1/agent/correlation/matrix"),
]


@pytest.fixture(autouse=True)
def _restore_registry():
    REGISTRY.clear()
    REGISTRY.update(_REGISTRY_SNAPSHOT)
    yield


def _manifest():
    with TestClient(app) as client:
        client.get("/control/server/status")  # trigger lifespan
        resp = client.get("/control/api-manifest")
        resp.raise_for_status()
        return resp.json()


def _agent_endpoint(manifest: dict, method: str, path: str) -> dict:
    for sec in manifest["sections"]:
        for ep in sec["endpoints"]:
            if ep["method"] == method and ep["path"] == path:
                return ep
    pytest.fail(f"agent endpoint not found: {method} {path}")


def _all_endpoint_paths(manifest: dict) -> set[str]:
    return {
        ep["path"] for sec in manifest["sections"] for ep in sec["endpoints"]
    }


@pytest.mark.parametrize("method,path", AGENT_ROUTES)
def test_every_agent_route_declares_depends_on(method, path):
    m = _manifest()
    ep = _agent_endpoint(m, method, path)
    assert ep["depends_on"], f"{method} {path} has empty depends_on"


@pytest.mark.parametrize("method,path", AGENT_ROUTES)
def test_agent_depends_on_endpoint_refs_resolve(method, path):
    m = _manifest()
    ep = _agent_endpoint(m, method, path)
    all_paths = _all_endpoint_paths(m)
    endpoint_refs = [d for d in ep["depends_on"] if d["kind"] == "endpoint"]
    assert endpoint_refs, f"{method} {path} has no endpoint-kind depends_on (no composed-of edge)"
    for d in endpoint_refs:
        assert d["target_path"] in all_paths, (
            f"{method} {path} depends_on ref {d['label']!r} resolves to "
            f"{d['target_path']!r} which is not in the manifest — "
            f"target endpoint was deleted/renamed, or param-name drift."
        )
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_manifest_depends_on.py -v`

Expected: FAIL — 每个 agent route 的 `depends_on` 为 `[]`（未声明），`assert ep["depends_on"]` 失败。

- [ ] **Step 3: Declare depends_on on the 9 agent routes**

对每个 `@endpoint_meta(...)`，加 `depends_on=[...]` kwarg（值见上表）。示例——`agent.py:1199` 的 market-stats：

```python
@endpoint_meta(
    summary="市场全量统计（个股+板块涨幅分布 + 桶形数据）",
    markets=["csi"],
    capabilities=[],  # agent aggregation, no single capability
    depends_on=[
        "/api/v1/stocks",
        "/api/v1/boards",
        "manager.get_realtime_quotes",
        "cache.get_board_list",
    ],
)
```

对其余 8 个 route 按上表同样加 `depends_on=[...]`。`agent_correlation.py:430` 的 correlation/matrix：

```python
@endpoint_meta(
    summary="...",  # 保持原 summary 不变
    markets=["csi"],  # 保持原值不变
    capabilities=[],  # 保持原值不变
    depends_on=[
        "/api/v1/stocks/{code}/kline",
        "/api/v1/boards/{board_code}/history",
        "manager.get_kline_data",
        "manager.get_board_history",
    ],
)
```

> 实现者须保持每个 `@endpoint_meta` 的 `summary`/`markets`/`capabilities`/`fetcher_method` 等已有 kwarg **原样不变**，仅追加 `depends_on`。读每个 route 的现有装饰器（按上表行号）确认其余 kwarg 后追加。

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/test_manifest_depends_on.py -v`

Expected: PASS（9 个 route 全部声明 depends_on，endpoint ref 全部解析成功）。

- [ ] **Step 5: Run full explorer + manifest suite for regression**

Run: `.venv/Scripts/python.exe -m pytest tests/test_manifest.py tests/test_explorer_manifest_endpoint.py tests/test_manifest_depends_on.py tests/test_endpoint_meta.py tests/test_capability_method_map.py -v`

Expected: PASS。

- [ ] **Step 6: Lint + commit**

```bash
ruff check stock_data/api/routes/agent.py stock_data/api/routes/agent_correlation.py tests/test_manifest_depends_on.py
ruff format stock_data/api/routes/agent.py stock_data/api/routes/agent_correlation.py tests/test_manifest_depends_on.py
git add stock_data/api/routes/agent.py stock_data/api/routes/agent_correlation.py tests/test_manifest_depends_on.py
git commit -m "feat(agent): declare depends_on on 9 agent routes for dependency graph

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 4: 前端 — `GraphView` 模块 + CDN lazy-load + 节点/边渲染

新增 `GraphView` IIFE：从 `MANIFEST` 构建 nodes（endpoint + fetcher）与 edges（served-by + composed-of），lazy-load vis-network CDN，渲染 force-directed 图，click 触发 `onNodeClick` 回调。graceful degradation：CDN 失败显示提示。

**Files:**
- Modify: `stock_data/explorer/static/index.html`（在 `ResultPanel` IIFE 之后、主 app IIFE 之前插入 `GraphView` IIFE；主 app `boot()` 加 lazy-load 触发点）

**Interfaces:**
- Consumes: `window.MANIFEST`（Task 1–3 的 `response_schema` + `depends_on` 字段）；全局 `vis`（CDN lazy-load）；CSS 变量（`getComputedStyle` 读 `--accent`/`--accent-post`/`--text`/`--text-muted`/`--border`）
- Produces: `GraphView.render(container, manifest, onNodeClick)` → 渲染图；`GraphView.applyFilter(state)` → 按 market/fetcher 过滤；`GraphView.applySearch(q)` → fuzzy 高亮；`GraphView.destroy()` → 清理

- [ ] **Step 1: Add the GraphView IIFE module**

在 `index.html` 的 `ResultPanel` IIFE 结束（`</script>` at `:753`）之后、主 app `<script>`（`:754`）之前，插入新 `<script>` 块：

```html
  <script>
  // ========================================================================
  // Module: GraphView
  // Purpose: render the dependency node-graph (endpoint <-> fetcher served-by
  //          edges + agent -> endpoint composed-of edges) using vis-network.
  //          Lazy-loads vis-network from CDN on first render; degrades to a
  //          message if the CDN is unreachable. Public API:
  //   GraphView.load()            - async; resolve when vis is loaded (or failed)
  //   GraphView.render(container, manifest, {onNodeClick, css}) - draw graph
  //   GraphView.applyFilter(state) - hide endpoints not matching market/fetcher filter
  //   GraphView.applySearch(q)    - dim non-matching nodes
  //   GraphView.destroy()         - tear down the network instance
  // Reuses: window.MANIFEST shape (fetchers[], depends_on[]), fuzzyMatch().
  // ========================================================================
  const GraphView = (() => {
    const VIS_CDN = "https://cdn.jsdelivr.net/npm/vis-network@9/standalone/umd/vis-network.min.js";
    let network = null;          // vis.Network instance
    let dataSet = null;          // { nodes: vis.DataSet, edges: vis.DataSet }
    let lastManifest = null;
    let lastCallbacks = null;
    let visLoadPromise = null;

    function load() {
      if (visLoadPromise) return visLoadPromise;
      if (window.vis && window.vis.Network) return Promise.resolve();
      visLoadPromise = new Promise((resolve) => {
        const s = document.createElement("script");
        s.src = VIS_CDN;
        s.onload = () => resolve();
        s.onerror = () => resolve();  // resolve anyway; render() checks vis
        document.head.appendChild(s);
      });
      return visLoadPromise;
    }

    // Read a CSS variable from :root, fall back to a hex.
    function cssVar(name, fallback) {
      try {
        const v = getComputedStyle(document.documentElement)
          .getPropertyValue(name).trim();
        return v || fallback;
      } catch { return fallback; }
    }

    // Build {nodes, edges} from the manifest.
    //  - Endpoint nodes: one per endpoint. shape = dot (ordinary) / diamond
    //    (agent composite, capabilities=[] AND tag starts with "agent") /
    //    dot small grey (no fetchers & no capabilities, e.g. /indicators).
    //    color by HTTP method.
    //  - Fetcher nodes: one per distinct fetcher name across all endpoints'
    //    fetchers[]. box shape, priority badge in label.
    //  - served-by edges: endpoint -> fetcher (one per fetchers[] entry).
    //  - composed-of edges: agent endpoint -> target endpoint (depends_on
    //    kind:"endpoint" items).
    function buildGraph(manifest) {
      const nodes = [];
      const edges = [];
      const fetcherNames = new Set();
      const epByPath = {};
      const accent = cssVar("--accent", "#0071e3");
      const accentPost = cssVar("--accent-post", "#34c759");
      const textMuted = cssVar("--text-muted", "#6e6e73");
      const border = cssVar("--border", "#e5e5ea");
      const warn = cssVar("--accent-warn", "#ff9500");

      // First pass: collect fetcher names + index endpoints by path.
      for (const sec of manifest.sections) {
        for (const ep of sec.endpoints) {
          epByPath[ep.path] = ep;
          for (const f of (ep.fetchers || [])) fetcherNames.add(f.name);
        }
      }

      // Endpoint nodes.
      for (const sec of manifest.sections) {
        for (const ep of sec.endpoints) {
          const isAgent = (!ep.capabilities || ep.capabilities.length === 0)
            && sec.id === "agent";
          const isPure = (!ep.fetchers || ep.fetchers.length === 0)
            && (!ep.capabilities || ep.capabilities.length === 0)
            && !isAgent;
          let shape, color, size;
          if (isAgent) { shape = "diamond"; color = { border: "#af52de", background: "#f3e8ff", highlight: { border: "#af52de", background: "#e9d5ff" } }; size = 18; }
          else if (isPure) { shape = "dot"; color = { background: textMuted, border: textMuted }; size = 8; }
          else { shape = "dot"; const c = ep.method === "POST" ? accentPost : accent; color = { background: c, border: c }; size = 14; }
          const label = `${ep.method} ${ep.path.length > 28 ? ep.path.slice(0, 25) + "…" : ep.path}`;
          nodes.push({
            id: "ep:" + ep.path,
            label,
            shape,
            color,
            size,
            title: `${ep.method} ${ep.path}\n${ep.summary || ""}`,
            group: "endpoint",
            _ep: ep,
          });
        }
      }

      // Fetcher nodes.
      for (const name of [...fetcherNames].sort()) {
        nodes.push({
          id: "fx:" + name,
          label: name.replace(/Fetcher$/, ""),
          shape: "box",
          color: { background: "#f5f5f7", border: border, highlight: { background: "#e5e5ea", border: textMuted } },
          font: { color: textMuted, size: 12 },
          margin: 6,
          title: name,
          group: "fetcher",
          _name: name,
        });
      }

      // served-by edges (endpoint -> fetcher).
      let edgeId = 0;
      for (const sec of manifest.sections) {
        for (const ep of sec.endpoints) {
          for (const f of (ep.fetchers || [])) {
            edges.push({
              id: "e" + (edgeId++),
              from: "ep:" + ep.path,
              to: "fx:" + f.name,
              // lower priority = thicker/darker. P0 -> 2px, P9 -> 0.5px.
              width: Math.max(0.5, 2.5 - 0.2 * (f.priority ?? 5)),
              color: { color: f.available === false ? border : textMuted, opacity: f.available === false ? 0.4 : 0.6 },
              dashes: f.available === false,
              title: `.${f.method}()  P${f.priority}`,
              _kind: "served-by",
            });
          }
        }
      }

      // composed-of edges (agent endpoint -> target endpoint).
      for (const sec of manifest.sections) {
        for (const ep of sec.endpoints) {
          for (const d of (ep.depends_on || [])) {
            if (d.kind === "endpoint" && epByPath[d.target_path]) {
              edges.push({
                id: "e" + (edgeId++),
                from: "ep:" + ep.path,
                to: "ep:" + d.target_path,
                width: 1.5,
                color: { color: "#af52de", opacity: 0.7 },
                arrows: "to",
                dashes: false,
                title: "composed-of",
                _kind: "composed-of",
              });
            }
          }
        }
      }
      return { nodes, edges };
    }

    function render(container, manifest, callbacks) {
      lastManifest = manifest;
      lastCallbacks = callbacks || {};
      if (!window.vis || !window.vis.Network) {
        container.innerHTML =
          '<div class="result-empty"><span class="arrow">⚠</span>' +
          '图库 (vis-network) 加载失败 — 请检查网络，或把库 vendor 到 ' +
          '<code>explorer/static/vendor/</code> 并改 GraphView 的 VIS_CDN。</div>';
        return;
      }
      const { nodes, edges } = buildGraph(manifest);
      dataSet = {
        nodes: new window.vis.DataSet(nodes),
        edges: new window.vis.DataSet(edges),
      };
      const options = {
        nodes: { font: { color: cssVar("--text", "#1d1d1f"), size: 13 } },
        edges: { smooth: { type: "continuous", roundness: 0.5 } },
        physics: {
          stabilization: { iterations: 120, fit: true },
          barnesHut: { gravitationalConstant: -8000, springLength: 140, springConstant: 0.04 },
        },
        interaction: { hover: true, tooltipDelay: 120, navigationButtons: false, zoomView: true, dragView: true },
      };
      network = new window.vis.Network(container, dataSet, options);
      network.on("click", (params) => {
        if (params.nodes.length && lastCallbacks.onNodeClick) {
          const node = dataSet.nodes.get(params.nodes[0]);
          lastCallbacks.onNodeClick(node);
        }
      });
    }

    // Dim nodes whose endpoint doesn't match the market/fetcher filter.
    // Fetcher nodes stay visible iff at least one served-by neighbor stays.
    function applyFilter(state) {
      if (!network || !dataSet) return;
      const visibleEp = new Set();
      for (const sec of lastManifest.sections) {
        for (const ep of sec.endpoints) {
          const marketOk = (ep.markets || []).some(m => (state.marketFilter || []).includes(m));
          const fetcherOk = !state.fetcherFilter
            || (ep.fetchers || []).some(f => f.name === state.fetcherFilter)
            || (!ep.fetchers || ep.fetchers.length === 0);
          if (marketOk && fetcherOk) visibleEp.add("ep:" + ep.path);
        }
      }
      // fetchers visible iff a visible endpoint serves them
      const visibleFx = new Set();
      for (const e of dataSet.edges.get()) {
        if (e._kind === "served-by" && visibleEp.has(e.from)) visibleFx.add(e.to);
      }
      const updates = dataSet.nodes.get().map(n => ({
        id: n.id,
        hidden: !(n.group === "endpoint" ? visibleEp.has(n.id) : visibleFx.has(n.id)),
      }));
      dataSet.nodes.update(updates);
      network.redraw();
    }

    // Dim (not hide) nodes whose label doesn't fuzzy-match q.
    function applySearch(q) {
      if (!network || !dataSet) return;
      const query = (q || "").trim();
      const updates = dataSet.nodes.get().map(n => {
        const match = !query || fuzzyMatchGlobal(query, n.label);
        return { id: n.id, opacity: match ? 1.0 : 0.15 };
      });
      dataSet.nodes.update(updates);
    }
    // local copy of fuzzyMatch (main app's is inside its own IIFE)
    function fuzzyMatchGlobal(query, text) {
      if (!query) return true;
      const q = query.toLowerCase(), t = (text || "").toLowerCase();
      let i = 0;
      for (const c of t) { if (c === q[i]) i++; if (i === q.length) return true; }
      return false;
    }

    function destroy() {
      if (network) { network.destroy(); network = null; }
      dataSet = null;
    }

    return { load, render, applyFilter, applySearch, destroy };
  })();
  </script>
```

- [ ] **Step 2: Smoke test — graph renders**

启动 server：`.venv/Scripts/python.exe -m stock_data.server`（新端口 8888；若已占用见 memory `windows-python-taskkill-gotcha`/`do-not-kill-user-server`，用 `SERVER_PORT=8889`）。

浏览器开 `http://localhost:8888/explorer/`，打开 DevTools console。

临时验证 GraphView（此步在 Task 6 正式接入 view switch；这里先在 console 手测模块可用）：

```js
// in browser console
await GraphView.load();
const c = document.querySelector('.main');
c.innerHTML = '<div id="graphProbe" style="height:80vh"></div>';
GraphView.render(document.getElementById('graphProbe'), window.MANIFEST, { onNodeClick: n => console.log('click', n.group, n._ep?.path || n._name) });
```

Expected：图渲染出 ~30 endpoint 节点（GET 蓝 / POST 绿 / agent 紫 diamond / 纯计算灰小点）+ 13 fetcher box 节点 + served-by 边（priority 越低越粗）+ agent→endpoint 紫色箭头边。点击节点 console 打印节点信息。物理布局稳定后停止。

- [ ] **Step 3: Lint (HTML 无 ruff；跳过) + commit**

```bash
git add stock_data/explorer/static/index.html
git commit -m "feat(explorer): add GraphView module (vis-network CDN, node/edge render)

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 5: 前端 — `NodeDetailPanel` 模块 + 节点点击详情

新增 `NodeDetailPanel` IIFE：复用右侧 `#resultPanel` 容器，点击 endpoint/fetcher 节点渲染详情（endpoint：meta+params+body schema+response schema+fetcher 链+depends_on；fetcher：name+priority+capabilities+serves 列表）。复用 `JSONView.render` 渲染 schema，复用 `renderFetcherRow` 逻辑。

**Files:**
- Modify: `stock_data/explorer/static/index.html`（`GraphView` IIFE 之后插入 `NodeDetailPanel` IIFE）

**Interfaces:**
- Consumes: `JSONView.render`（渲染 schema）；`CAPABILITY_LABELS`（manifest.meta.capabilities）；endpoint 节点的 `_ep`、fetcher 节点的 `_name`；manifest 全量（反查 fetcher 的 serves 列表）
- Produces: `NodeDetailPanel.init()`、`NodeDetailPanel.showEndpoint(ep, manifest)`、`NodeDetailPanel.showFetcher(name, manifest)`、`NodeDetailPanel.clear()`

- [ ] **Step 1: Add the NodeDetailPanel IIFE module**

在 `GraphView` IIFE 的 `</script>` 之后、主 app `<script>`（`:754`）之前，插入：

```html
  <script>
  // ========================================================================
  // Module: NodeDetailPanel
  // Purpose: render node detail in the right-side #resultPanel container
  //          (shared with ResultPanel — they swap by current view). Reuses
  //          JSONView for schema rendering. Public API:
  //   NodeDetailPanel.init()                          - bind refs (shared with ResultPanel)
  //   NodeDetailPanel.showEndpoint(ep, manifest)       - endpoint node detail
  //   NodeDetailPanel.showFetcher(name, manifest)      - fetcher node detail
  //   NodeDetailPanel.clear()                          - reset to empty
  // ========================================================================
  const NodeDetailPanel = (() => {
    let bodyEl;

    function init() {
      bodyEl = document.getElementById("resultBody");
    }

    function clear() {
      bodyEl.innerHTML = "";
      const empty = document.createElement("div");
      empty.className = "result-empty";
      empty.innerHTML = '<span class="arrow">◐</span>点击图节点查看依赖详情。';
      bodyEl.appendChild(empty);
    }

    function esc(s) {
      if (s == null) return "";
      return String(s).replace(/[&<>"']/g, c => ({
        "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
      }[c]));
    }

    function chip(label, icon) {
      const s = document.createElement("span");
      s.className = "chip cap-chip";
      s.textContent = (icon ? icon + " " : "") + label;
      return s;
    }

    function sectionTitle(text) {
      const t = document.createElement("div");
      t.className = "result-section-title";
      t.textContent = text;
      return t;
    }

    function schemaBlock(title, schema, note) {
      const wrap = document.createElement("div");
      wrap.appendChild(sectionTitle(title));
      if (note) {
        const n = document.createElement("div");
        n.style.cssText = "font-size:11px;color:var(--text-muted);margin-bottom:4px;";
        n.textContent = note;
        wrap.appendChild(n);
      }
      if (schema) {
        wrap.appendChild(JSONView.render(schema));
      } else {
        const e = document.createElement("div");
        e.style.cssText = "font-size:12px;color:var(--text-muted);";
        e.textContent = "（无）";
        wrap.appendChild(e);
      }
      return wrap;
    }

    function paramsBlock(ep) {
      if (!ep.params || !ep.params.length) return null;
      const wrap = document.createElement("div");
      wrap.appendChild(sectionTitle("Parameters"));
      const pre = document.createElement("pre");
      pre.className = "result-raw";
      pre.style.maxHeight = "30vh";
      ep.params.forEach(p => {
        pre.appendChild(document.createTextNode(
          `${p.in}.${p.name}${p.required ? " (required)" : ""}: ${p.type}\n`
        ));
      });
      wrap.appendChild(pre);
      return wrap;
    }

    function fetcherRowMini(f) {
      // Compact version of renderFetcherRow for the detail panel.
      const row = document.createElement("div");
      row.style.cssText = "display:grid;grid-template-columns:40px 1fr;gap:8px;padding:6px 0;border-bottom:1px solid var(--border);";
      const p = document.createElement("span");
      p.className = "fetcher-priority";
      p.textContent = "P" + f.priority;
      if (f.available === false) { p.style.opacity = "0.5"; }
      row.appendChild(p);
      const body = document.createElement("div");
      const name = document.createElement("div");
      name.style.fontWeight = "600";
      name.style.fontSize = "13px";
      name.textContent = f.name + (f.available === false ? "  ⚠" : "");
      body.appendChild(name);
      const sig = document.createElement("div");
      sig.style.cssText = "font-family:monospace;font-size:11px;color:var(--text-muted);";
      sig.textContent = `.${f.method}(${(f.signature || []).map(s => s.name).join(", ")})`;
      body.appendChild(sig);
      row.appendChild(body);
      return row;
    }

    function showEndpoint(ep, manifest) {
      bodyEl.innerHTML = "";
      // meta header
      const meta = document.createElement("div");
      meta.className = "result-meta";
      const caps = (ep.capabilities || []).map(c => {
        const lbl = (manifest.meta.capabilities || {})[c] || {};
        return chip(lbl.label || c, lbl.icon);
      });
      const line1 = document.createElement("div");
      line1.className = "row";
      line1.innerHTML = `<span class="label">Endpoint:</span> <span class="value">${esc(ep.method)} ${esc(ep.path)}</span>`;
      meta.appendChild(line1);
      const line2 = document.createElement("div");
      line2.className = "row";
      line2.innerHTML = `<span class="label">Summary:</span> <span class="value">${esc(ep.summary || "")}</span>`;
      meta.appendChild(line2);
      const line3 = document.createElement("div");
      line3.className = "row";
      line3.appendChild(document.createTextNode("Markets/Caps: "));
      (ep.markets || []).forEach(m => meta.appendChild(chip(m)));
      caps.forEach(c => meta.appendChild(c));
      meta.appendChild(line3);
      bodyEl.appendChild(meta);

      const params = paramsBlock(ep);
      if (params) bodyEl.appendChild(params);

      bodyEl.appendChild(schemaBlock("Request body schema", ep.body && ep.body.schema));
      bodyEl.appendChild(schemaBlock(
        "Response schema",
        ep.response_schema,
        "静态字段清单；@model_serializer 条件序列化（如 KLineData.indicators 空值 omit）不反映，以 CLAUDE.md Standardized Data Schema 为准。"
      ));

      // Fetcher backends (served-by chain)
      if (ep.fetchers && ep.fetchers.length) {
        bodyEl.appendChild(sectionTitle(`Fetcher backends (${ep.fetchers.length})`));
        ep.fetchers.forEach(f => bodyEl.appendChild(fetcherRowMini(f)));
      }

      // Dependencies (agent composed-of)
      if (ep.depends_on && ep.depends_on.length) {
        bodyEl.appendChild(sectionTitle("Dependencies"));
        const ul = document.createElement("div");
        ep.depends_on.forEach(d => {
          const row = document.createElement("div");
          row.style.cssText = "padding:4px 0;border-bottom:1px solid var(--border);font-size:12px;";
          if (d.kind === "endpoint") {
            row.innerHTML = `<span class="chip" style="background:#f3e8ff;color:#af52de;">edge</span> → ${esc(d.label)}`;
          } else {
            row.innerHTML = `<span class="chip">internal</span> ${esc(d.label)}`;
          }
          ul.appendChild(row);
        });
        bodyEl.appendChild(ul);
      }
    }

    function showFetcher(name, manifest) {
      bodyEl.innerHTML = "";
      // Reverse index: all endpoints whose fetchers[] include this name.
      const served = [];
      for (const sec of manifest.sections) {
        for (const ep of sec.endpoints) {
          for (const f of (ep.fetchers || [])) {
            if (f.name === name) {
              served.push({ ep, method: f.method, priority: f.priority, signature: f.signature, available: f.available, caps: f.capabilities });
            }
          }
        }
      }
      const meta = document.createElement("div");
      meta.className = "result-meta";
      const l1 = document.createElement("div");
      l1.className = "row";
      l1.innerHTML = `<span class="label">Fetcher:</span> <span class="value">${esc(name)}</span>`;
      meta.appendChild(l1);
      if (served.length) {
        const p = served[0].priority;
        const l2 = document.createElement("div");
        l2.className = "row";
        l2.innerHTML = `<span class="label">Priority:</span> <span class="value">P${p}</span>`;
        meta.appendChild(l2);
        const l3 = document.createElement("div");
        l3.className = "row";
        l3.appendChild(document.createTextNode("Capabilities: "));
        served[0].caps.forEach(c => meta.appendChild(chip(c)));
        meta.appendChild(l3);
        if (served[0].available === false) {
          const l4 = document.createElement("div");
          l4.className = "row";
          l4.style.color = "var(--accent-warn)";
          l4.textContent = "⚠ unavailable (见 endpoint 详情的 reason)";
          meta.appendChild(l4);
        }
      }
      bodyEl.appendChild(meta);

      bodyEl.appendChild(sectionTitle(`Serves ${served.length} endpoint(s)`));
      const ul = document.createElement("div");
      served.forEach(({ ep, method, signature }) => {
        const row = document.createElement("div");
        row.style.cssText = "padding:6px 0;border-bottom:1px solid var(--border);font-size:12px;";
        row.innerHTML = `${esc(ep.method)} <code>${esc(ep.path)}</code><br><span style="font-family:monospace;color:var(--text-muted);">.${esc(method)}(${(signature || []).map(s => s.name).join(", ")})</span>`;
        ul.appendChild(row);
      });
      bodyEl.appendChild(ul);
    }

    return { init, showEndpoint, showFetcher, clear };
  })();
  </script>
```

- [ ] **Step 2: Smoke test — detail panel renders on click**

启动 server，浏览器 console（接 Task 4 的 probe）：

```js
NodeDetailPanel.init();
// re-render graph with a click handler that routes to the panel:
const c = document.querySelector('.main');
c.innerHTML = '<div id="graphProbe" style="height:80vh"></div>';
GraphView.render(document.getElementById('graphProbe'), window.MANIFEST, {
  onNodeClick: (n) => {
    if (n.group === "endpoint") NodeDetailPanel.showEndpoint(n._ep, window.MANIFEST);
    else if (n.group === "fetcher") NodeDetailPanel.showFetcher(n._name, window.MANIFEST);
  }
});
// click an endpoint node → right panel shows params + body schema + response schema + fetchers
// click a fetcher node → right panel shows priority + capabilities + serves list
```

Expected：点击 endpoint 节点（如 `/api/v1/stocks/{code}/kline`）→ 右侧显示 Parameters、Request body schema（无则"（无）"）、Response schema（KLineData 字段树，可折叠）、Fetcher backends 链、（agent 节点）Dependencies。点击 fetcher 节点 → priority + capabilities + serves N endpoints 列表。

- [ ] **Step 3: Commit**

```bash
git add stock_data/explorer/static/index.html
git commit -m "feat(explorer): add NodeDetailPanel module (endpoint/fetcher detail)

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 6: 前端 — view switch + boot 集成 + filter/search/theme + graceful degradation + 物理预设

topbar 加 `Endpoints / Dependency Graph` segmented control；`boot()` 激活图视图时 lazy-load vis + render；market/fetcher filter + search 复用于图；theme 切换同步重渲染图；CDN 失败提示已在 Task 4 的 `render()` 内。

**Files:**
- Modify: `stock_data/explorer/static/index.html`（topbar DOM、主 app IIFE 的 `state`/`bindUI`/`boot`/`renderContent`）

**Interfaces:**
- Consumes: `GraphView`（Task 4）、`NodeDetailPanel`（Task 5）、`ResultPanel`（现有）、`state`（marketFilter/fetcherFilter/theme）
- Produces: `state.view`（`"endpoints" | "graph"`，localStorage 持久）；topbar view switch；图视图下右侧面板 = NodeDetailPanel，list 视图 = ResultPanel

- [ ] **Step 1: Add topbar view switch DOM**

`index.html` topbar（`:327-335`），在 `<h1>` 之后、`#search` 之前插入 segmented control：

```html
    <div class="segmented" id="viewSwitch" role="group" aria-label="View">
      <button type="button" data-view="endpoints" class="seg active">Endpoints</button>
      <button type="button" data-view="graph" class="seg">Dependency Graph</button>
    </div>
```

在 `<style>`（`:12-324`）的 `.topbar` 区块附近加：

```css
    .segmented { display: inline-flex; border: 1px solid var(--border); border-radius: 8px; overflow: hidden; }
    .segmented .seg { font: inherit; font-size: 13px; padding: 6px 14px; border: 0; background: var(--bg-card); color: var(--text-muted); cursor: pointer; border-right: 1px solid var(--border); }
    .segmented .seg:last-child { border-right: 0; }
    .segmented .seg.active { background: var(--accent); color: #fff; }
```

- [ ] **Step 2: Wire view switch into the main app IIFE**

主 app IIFE（`:756` 起）。

`state`（`:779-793`）加 `view`：

```javascript
    let state = {
      baseUrl: safeGetItem("baseUrl", ""),
      theme: safeGetItem("theme", "light"),
      view: safeGetItem("view", "endpoints"),
      marketFilter: JSON.parse(safeGetItem("marketFilter", '["csi","hk","us"]')),
      fetcherFilter: (() => {
        const raw = safeGetItem("fetcherFilter", null);
        if (raw === null) return null;
        const parsed = JSON.parse(raw);
        if (Array.isArray(parsed)) return null;
        return typeof parsed === "string" ? parsed : null;
      })(),
      fetcherListRestrict: safeGetItem("fetcherListRestrict", "false") === "true",
    };
```

`boot()`（`:847-885`）末尾（`renderContent()` 之后）加 NodeDetailPanel init + view 应用：

```javascript
      NodeDetailPanel.init();
      applyView();
```

新增 `applyView()` / `renderGraph()` / `renderMain()`（在 `renderContent` `:997` 之前）：

```javascript
    function applyView() {
      const segs = $$("#viewSwitch .seg");
      segs.forEach(b => b.classList.toggle("active", b.dataset.view === state.view));
      const isGraph = state.view === "graph";
      // main area: graph or endpoint list
      const content = $("#content");
      if (isGraph) {
        content.innerHTML = "";
        const g = el("div", { id: "graphCanvas", style: "width:100%;height:calc(100vh - 120px);min-height:400px;" });
        content.appendChild(g);
        NodeDetailPanel.clear();
        renderGraph(g);
      } else {
        renderContent();
      }
      // result panel title hint
      $(".result-panel-header span").textContent = isGraph ? "Node Detail" : "Response";
    }

    async function renderGraph(container) {
      await GraphView.load();
      GraphView.render(container, MANIFEST, {
        onNodeClick: (n) => {
          if (n.group === "endpoint") NodeDetailPanel.showEndpoint(n._ep, MANIFEST);
          else if (n.group === "fetcher") NodeDetailPanel.showFetcher(n._name, MANIFEST);
        },
      });
      GraphView.applyFilter(state);
    }

    function setView(v) {
      if (state.view === v) return;
      // tear down previous graph if leaving
      if (state.view === "graph") GraphView.destroy();
      state.view = v;
      safeSetItem("view", v);
      applyView();
    }
```

`bindUI()`（`:891-970`）加 view switch + filter/search 联动图：

```javascript
      $("#viewSwitch").onclick = (e) => {
        const btn = e.target.closest(".seg");
        if (btn) setView(btn.dataset.view);
      };
```

并把现有 `$("#marketFilter").onchange`（`:939-944`）、`$("#fetcherFilter").onchange`（`:945-951`）、`#search` `oninput`（`:903`）各自末尾追加图联动：

`marketFilter` onchange 末尾加：
```javascript
        if (state.view === "graph") GraphView.applyFilter(state);
```

`fetcherFilter` onchange 末尾加：
```javascript
        if (state.view === "graph") GraphView.applyFilter(state);
```

`fetcherListRestrict` onchange（`:965-969`）在图视图下也应触发 filter（它只影响 endpoint list 的 fetcher 行显示，对图无意义——保持原 `refreshFetcherLists()` 不动，图不受影响，无需加）。

`search` `oninput`（`:903`）改为：
```javascript
      $("#search").oninput = () => {
        applySearchAndFilter();
        if (state.view === "graph") GraphView.applySearch($("#search").value);
      };
```

theme 切换（`:892-896`）末尾加重渲染图（让节点重新读 CSS 变量）：
```javascript
      $("#themeToggle").onclick = () => {
        state.theme = state.theme === "light" ? "dark" : "light";
        safeSetItem("theme", state.theme);
        applyTheme();
        if (state.view === "graph") {
          const g = $("#graphCanvas");
          if (g) { GraphView.destroy(); applyView(); }  // rebuild picks up new CSS vars
        }
      };
```

- [ ] **Step 3: Smoke test — full integration**

启动 server，浏览器开 `/explorer/`：

1. 默认 Endpoints 视图，endpoint list 正常渲染（回归未破）。
2. 点 `Dependency Graph` → 图渲染（endpoint + fetcher 节点 + 两类边）；URL 不变，刷新后保留（localStorage `view=graph`）。
3. 点 endpoint 节点 → 右侧 NodeDetailPanel 显示 params/body schema/response schema/fetchers/depends_on。
4. 点 fetcher 节点 → 右侧显示 priority/capabilities/serves 列表。
5. 在 search 框输入 `kline` → 非匹配节点暗化。
6. 勾掉 sidebar 的 `hk` market → 图中非 csi/us 的 endpoint 节点隐藏（A 股 endpoint 多，hk/us 节点消失）。
7. 选 sidebar 某个 fetcher radio → 图中只保留该 fetcher + 其服务的 endpoint。
8. 点 🌗 切 dark theme → 图节点配色随之变（重建图）。
9. DevTools 断网（offline）后刷新切图视图 → 显示"图库加载失败"提示，不影响 Endpoints 视图。
10. 双击 `Endpoints` 切回 → endpoint list 正常。

Expected：1–10 全部符合。

- [ ] **Step 4: Lint (HTML 无 ruff) + commit**

```bash
git add stock_data/explorer/static/index.html
git commit -m "feat(explorer): integrate dependency graph view (switch/filter/search/theme)

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Self-Review (run after writing)

已完成自审：
1. **Spec coverage**：§4.1 节点模型→Task 4 `buildGraph`；§4.2 边模型→Task 4 served-by+composed-of；§4.3 入口→Task 6 view switch；§4.4 交互→Task 6（click/hover/filter/search/drag-zoom-pan 内置）；§4.5 详情→Task 5；§4.6 美观→Task 4 CSS 变量配色 + Task 6 theme；§5.1 depends_on→Task 2+3；§5.2 build_manifest→Task 1+2；§5.3 response schema 限制→Task 5 schemaBlock note；§6 前端模块→Task 4+5+6；§7 测试→Task 1–3。全覆盖。
2. **Placeholder scan**：无 TBD/TODO；所有代码块完整；depends_on 值表给出全部 9 条真实值。
3. **Type consistency**：`GraphView.render(container, manifest, {onNodeClick})` 在 Task 4 定义、Task 5/6 调用一致；`NodeDetailPanel.showEndpoint(ep, manifest)` / `showFetcher(name, manifest)` 定义与调用一致；`node.group` (`"endpoint"`/`"fetcher"`)、`node._ep`/`node._name` 在 buildGraph 设定、onNodeClick 读取一致；manifest 字段名 `depends_on`/`response_schema`/`fetchers`/`params`/`body.schema` 全程一致。

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-09-02-explorer-dependency-graph.md`. Two execution options:

**1. Subagent-Driven (recommended)** — I dispatch a fresh subagent per task, review between tasks, fast iteration.

**2. Inline Execution** — Execute tasks in this session using executing-plans, batch execution with checkpoints.

Which approach?
