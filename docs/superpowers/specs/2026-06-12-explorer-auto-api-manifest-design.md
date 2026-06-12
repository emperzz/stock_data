# Explorer API 自动识别（第一期：路由 + 元数据 manifest）— 设计文档

> 日期: 2026-06-12
> 范围: 把 `stock_data/explorer/static/index.html` 中硬编码的 ~1000 行 `ENDPOINTS.sections` 替换为启动时由 server 聚合并下发的 manifest。第一期只到"路由 + 元数据 manifest"层。Per-fetcher 链路展示 + 单独测试 fetcher 留到第二期。
> 性质: **架构升级 + 单点真相**。`routes.py` 成为 API 清单的单一真相源，HTML 端不再手写 path/method/params。

---

## 1. 目标与动机

**目标**: 当前 `routes.py` 增加/修改/删除 endpoint 时，需要同步修改 `index.html:285-1293` 的硬编码 `ENDPOINTS.sections` 块（约 1000 行）。`docs/API.md` 还要再改一遍。两处人工同步极易遗漏，遗漏后表现是"HTML 显示一个不存在的 endpoint"或"新 endpoint 不会出现在 sidebar"，是**静默错误**。

本次要解决：让 `routes.py` 成为 API 清单的单一真相源；HTML 启动时拉 manifest 渲染，path/method/params 跟着 FastAPI 路由走，summary/markets/capabilities/cache/sources 由新加的 `endpoint_meta` 装饰器声明。

**非目标（第一期不做的）**:
- 不补全 `sources: [{ fetcher, method, upstream, notes }]`——这是第二期按 endpoint 逐个填
- 不加 `/control/fetcher/probe` 端点，不做 per-fetcher 单独测试
- 不动 `docs/API.md`（CLAUDE.md "do not edit API.md" 约定仍然成立；API.md 与 manifest 的关系将在第二期重新审视）
- 不重写 HTML 视觉层、CSS、主题、搜索、过滤逻辑——只换数据源，渲染逻辑尽量复用
- 不改 routes 的 URL、不改 response_model、不改任何 API 响应 schema
- 不动 explorer 的 `/control/*` 5 个端点（config / server/status / test-instance/*）

---

## 2. 当前状态

```
stock_data/
├── stock_data/
│   ├── api/
│   │   ├── routes.py              # 1712 行,~20 个 @router.get(...) 端点
│   │   ├── schemas.py             # Pydantic response model
│   │   └── cache.py
│   ├── explorer/
│   │   ├── __init__.py            # mount(app): 挂 /explorer 静态 + /control/* 路由
│   │   ├── routes.py              # build_control_router(): 5 个 /control/* 端点
│   │   ├── control.py             # Test Instance 子进程管理
│   │   └── static/
│   │       └── index.html         # 1649 行,其中 ENDPOINTS 块占 1000 行(285-1293)
│   └── server.py                  # 关闭 openapi_url=None / docs_url=None / redoc_url=None
└── docs/
    └── superpowers/specs/...
```

**ENDPOINTS 当前形态** (`index.html:285-1293`):
```js
const ENDPOINTS = {
  meta: {
    version: "1.0", generated: "2026-06-11",
    capabilities: { REALTIME_QUOTE: { label, icon }, ... },  // 18 项,纯 UI 装饰
    fetcher_meta: { Tushare: { priority, color }, ... },    // 9 项,纯 UI 装饰
  },
  sections: [
    { id: "4.1", title: "健康检查", endpoints: [ ... ] },
    { id: "4.2", title: "股票 / 个股 API", endpoints: [ ... ] },
    ...
  ]
};
```

每个 endpoint 节点当前含字段:
- `id, method, path, summary, markets, capabilities, params, response_fields, cache, sources`
- method/path/params 跟 routes.py 完全重复
- summary/markets/capabilities/cache/sources 是 OpenAPI 拿不到的"业务语义"

**引用 ENDPOINTS 的位置** (index.html):
- `1493` — `ENDPOINTS.sections.forEach(sec => ...)` 渲染 sidebar 导航
- `1506` — `ENDPOINTS.sections.forEach(sec => ...)` 渲染主区卡片
- `1531, 1533` — `ep.capabilities` 用于 capability 过滤
- `1510` — `ep.markets` 用于 market 过滤
- `1538-1539` — `ep.method`, `ep.path` 用于卡片头
- `1554-1558, 1572-1578, 1590-1599` — `ep.params` / `ep.response_fields` / `ep.cache` / `ep.sources` 用于详情区

---

## 3. 目标结构

```
stock_data/
├── stock_data/
│   ├── api/
│   │   ├── endpoint_meta.py       # 新增:EndpointMeta dataclass + @endpoint_meta 装饰器 + REGISTRY
│   │   ├── routes.py              # 改造:每个 @router.get 下挂 1 行 @endpoint_meta(...)
│   │   ├── schemas.py             # 不动
│   │   └── cache.py               # 不动
│   ├── explorer/
│   │   ├── manifest.py            # 新增:build_manifest(app) 反射 app.routes + 查 REGISTRY 合并
│   │   ├── routes.py              # 改造:加 @router.get("/api-manifest") 端点
│   │   ├── __init__.py            # 不动(mount() 调用点不变)
│   │   ├── control.py             # 不动
│   │   └── static/
│   │       └── index.html         # 改造:删 ENDPOINTS.sections 1000 行,替换为 ~250 行 fetch+render
└── docs/
    └── superpowers/specs/
        └── 2026-06-12-explorer-auto-api-manifest-design.md  # 本文档
```

**新模块依赖**:
- `endpoint_meta.py` 不依赖任何项目模块,纯标准库
- `manifest.py` 依赖 `fastapi.routing.APIRoute`(类型反射)、`endpoint_meta.REGISTRY`
- `index.html` 增加一次 `fetch("/control/api-manifest")`

---

## 4. 组件设计

### 4.1 `stock_data/api/endpoint_meta.py` (新增,~70 行)

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
from typing import Callable, Any

# Module-level registry: id(route_function) -> EndpointMeta
REGISTRY: dict[Callable, "EndpointMeta"] = {}


@dataclass(frozen=True)
class EndpointMeta:
    """OpenAPI 拿不到、但 explorer 需要展示的字段。

    path / method / params / response_model 不在此处——它们在 build_manifest()
    里从 FastAPI 路由对象反射出来(单一真相在 @router.get 装饰器)。
    """
    summary: str                                    # 中文一句话描述,显示在卡片头
    markets: list[str] = field(default_factory=list)  # ["csi","hk","us"] 之一或多个
    capabilities: list[str] = field(default_factory=list)  # DataCapability 字符串列表
    cache: dict | None = None                       # {ttl_sec, env} 或 None
    sources: list[dict] = field(default_factory=list)   # 第一期恒为空;第二期填
    probe_url: str | None = None                    # 第一期恒为 None;第二期填
    section_id: str | None = None                   # 第一期恒为 None;第二期用于自定义排序


def endpoint_meta(
    *,
    summary: str,
    markets: list[str] | None = None,
    capabilities: list[str] | None = None,
    cache: dict | None = None,
    sources: list[dict] | None = None,
    probe_url: str | None = None,
    section_id: str | None = None,
) -> Callable:
    """装饰器,把 EndpointMeta 存到 REGISTRY[func]。"""
    meta = EndpointMeta(
        summary=summary,
        markets=markets or [],
        capabilities=capabilities or [],
        cache=cache,
        sources=sources or [],
        probe_url=probe_url,
        section_id=section_id,
    )
    def deco(func: Callable) -> Callable:
        if func in REGISTRY:
            raise ValueError(f"@endpoint_meta already registered for {func}")
        REGISTRY[func] = meta
        return func
    return deco
```

**关键决定**:
- `path`/`method`/`params`/`response_model` **不**放在 `EndpointMeta` 里——FastAPI 已经持有
- 装饰器不复制 OpenAPI 能给的字段
- `REGISTRY` 用 `dict[Callable, EndpointMeta]` 而非 `dict[str, EndpointMeta]`(不用字符串 id),避免拼写错位
- 重复注册抛 `ValueError`,启动时就报错

### 4.2 `stock_data/explorer/manifest.py` (新增,~110 行)

```python
"""Build the explorer manifest by reflecting FastAPI routes + REGISTRY.

`build_manifest(app)` 在 server 启动时调用一次,反射 `app.routes` 拿到
所有 APIRoute,合并每个 route 的 `endpoint_meta` 装饰器声明,产出
explorer 消费用的 JSON 树。

不缓存:manifest 体量约 20 endpoint × ~500 字节 ≈ 10 KB,序列化无压力;
缓存反而让"加 endpoint 不重启不生效"成为陷阱。
"""
from __future__ import annotations
from typing import Any
from fastapi import FastAPI
from fastapi.routing import APIRoute

from ..api.endpoint_meta import REGISTRY
from .tags import TAG_TO_SECTION  # 见 4.3


# 这些 tag 不出现在 manifest(explorer 不展示)
_INTERNAL_TAGS = frozenset({"control"})


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

    `response_fields` 第一期填 "自动从 Pydantic response_model 反射出的
    字段名列表"——纯字段名,不含中文 desc。第二期手动补 desc 或留空。

    重要:`route.path` 在 FastAPI 里**不含** `app.include_router(prefix=...)`
    的 prefix。本项目 server.py 用 `include_router(router, prefix="/api/v1")`,
    所以 manifest 的 `path` 字段需要拼上 prefix 才是 HTML 端要展示的完整
    URL。`build_manifest` 通过 `APIRoute.path` + `APIRoute.prefix` 拿完整
    路径(在 _build_endpoint_node 里处理)。
    """
    sections_map: dict[str, dict] = {}  # section_id -> { id, title, endpoints: [] }
    for route in app.routes:
        if not isinstance(route, APIRoute):
            continue
        if not route.tags or any(t in _INTERNAL_TAGS for t in route.tags):
            continue
        # 反射:每个 route 的 func 可能在 REGISTRY 里
        meta = REGISTRY.get(route.endpoint)
        if meta is None:
            # 没挂 endpoint_meta 的 endpoint——跳过(explorer 不显示),
            # 但记日志,启动时就提醒开发者补
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

    例: tags=['stocks'], override=None -> ('4.2', '股票 / 个股 API')
        tags=['stocks'], override='4.10' -> ('4.10', ...)  # 第二期自定义
    """
    if override:
        title = TAG_TO_SECTION.get(override, override)
        return override, title
    tag = tags[0]
    sid = TAG_TO_SECTION.get(tag, {}).get("id", tag)
    title = TAG_TO_SECTION.get(tag, {}).get("title", tag)
    return sid, title


def _build_endpoint_node(route: APIRoute, meta: EndpointMeta) -> dict:
    # 反射 path params + query params
    params = []
    for p in route.dependant.path_params:
        params.append({"name": p.name, "in": "path", "required": True,
                       "type": _python_type_to_str(p.field_info.annotation),
                       "desc": ""})
    for p in route.dependant.query_params:
        params.append({"name": p.name, "in": "query", "required": p.required,
                       "type": _python_type_to_str(p.field_info.annotation),
                       "desc": ""})
    # 拼接完整 URL:FastAPI 的 route.path 不含 include_router(prefix=...)
    # 例 route.path='/stocks/{code}/quote', route.prefix='/api/v1' -> '/api/v1/stocks/{code}/quote'
    full_path = (route.prefix or "") + route.path
    return {
        "id": _slugify(f"{list(route.methods)[0]}_{full_path}"),
        "method": list(route.methods)[0],
        "path": full_path,
        "summary": meta.summary,
        "markets": meta.markets,
        "capabilities": meta.capabilities,
        "params": params,
        "response_model": route.response_model.__name__ if route.response_model else None,
        "response_fields": _reflect_response_fields(route.response_model),
        "cache": meta.cache,
        "sources": meta.sources,
        "probe_url": meta.probe_url,
    }


def _reflect_response_fields(model) -> list[str]:
    """从 Pydantic response_model 反射字段名(纯名字,无 desc)。"""
    if model is None:
        return []
    try:
        return list(model.model_fields.keys())
    except AttributeError:
        return []


def _python_type_to_str(annotation) -> str:
    """int / str / bool / float 映射;Optional 去掉 Optional 包装。"""
    if annotation is int: return "int"
    if annotation is str: return "string"
    if annotation is bool: return "bool"
    if annotation is float: return "float"
    return "string"  # 兜底


def _build_meta() -> dict:
    from .. import __version__
    return {
        "version": "1.1",
        "generated_at": None,  # 服务端在响应时填 ISO 8601
        "server_version": __version__,
        "capabilities": _CAPABILITY_LABELS,  # 18 项 label/icon 表,从 endpoint_meta 的 DataCapability 同步
    }


def _section_sort_key(sec):
    """4.1, 4.2, ... 4.10 字典序正确(避免 '4.10' 排在 '4.2' 前)。"""
    return tuple(int(x) for x in sec["id"].split("."))


# 同目录,manifest 暴露的"装饰性"标签表(从原 index.html 的 meta.capabilities 同步)
_CAPABILITY_LABELS = {
    "HISTORICAL_DWM":   {"label": "日/周/月 K线",     "icon": "📈"},
    # ... 与原 ENDPOINTS.meta.capabilities 完全一致
}
```

**关键决定**:
- `TAG_TO_SECTION` 在 `tags.py` 单独文件(见 4.3),跟 `endpoint_meta.py` 解耦
- 反射不出 `response_fields.desc`——第一期只给字段名,详情区显示"字段名 (无描述)";第二期手动补 desc 字段
- `desc: ""` 让 HTML 容错"字段名展示但 desc 留白"——比硬要写 desc 强
- 没挂 `@endpoint_meta` 的 route 跳过并 warn——不静默丢弃

### 4.3 `stock_data/explorer/tags.py` (新增,~40 行)

```python
"""Tag → section_id/title mapping for the explorer manifest.

FastAPI route 的 tags=["stocks"] 查这张表得到 sidebar 的 section_id 和
中文 title。这张表是 explorer 端的 UI 关注点,放在 explorer 子包而不是
api/ 路由层——业务路由不该知道"我的 tag 叫 stocks 会被 explorer 分到
4.2 节"这种 UI 决策。

第一期:硬编码。第二期:可改为允许每个 route 用 @endpoint_meta(section_id=...)
显式覆盖,用于"某个 endpoint 应该被分到'健康检查'节而不是'stocks'节"的
edge case(目前没有,但留口子)。
"""
TAG_TO_SECTION: dict[str, dict] = {
    # tag -> {id, title}
    "health":      {"id": "4.1",  "title": "健康检查"},
    "stocks":      {"id": "4.2",  "title": "股票 / 个股 API"},
    "indices":     {"id": "4.3",  "title": "指数 API"},
    "calendar":    {"id": "4.4",  "title": "股票 / 指数列表与日历"},
    "boards":      {"id": "4.5",  "title": "板块 (Boards)"},
    "pools":       {"id": "4.6",  "title": "涨跌停股池"},
    "dragon-tiger":{"id": "4.7",  "title": "龙虎榜"},
    "hot":         {"id": "4.8",  "title": "热点题材"},
    "north-flow":  {"id": "4.9",  "title": "北向资金"},
    "indicators":  {"id": "4.10", "title": "技术指标"},
    # 未来新 tag 在这里加一行
}
```

### 4.4 `stock_data/explorer/routes.py` (改造,+15 行)

在 `build_control_router()` 末尾追加一个端点:

```python
from fastapi import Request
from .manifest import build_manifest

@router.get("/api-manifest")
def control_api_manifest(request: Request) -> dict:
    """The /explorer/ HTML fetches this on load.

    返回 build_manifest(request.app) 的结果,加 generated_at 时间戳。
    不缓存(每次重新反射),保证"加 endpoint 后不重启也能看到"——重启
    server 才会触发新 route 注册,所以"不重启"本来也看不到新 endpoint,
    但 reload 配置或动态加 route 的场景下不缓存更安全。
    """
    manifest = build_manifest(request.app)
    from datetime import datetime, timezone
    manifest["meta"]["generated_at"] = datetime.now(timezone.utc).isoformat()
    return manifest
```

**关键决定**:
- 用 `request.app` 而不是 module-level `app`——避免 explorer 子包对 FastAPI 实例产生 import-time 依赖
- 端点放在 `/control/api-manifest` 而不是 `/api/v1/manifest`——与 explorer 同前缀、127.0.0.1 only、不污染业务路由

### 4.5 `stock_data/api/routes.py` (改造,~20 个 endpoint 各加 1 行)

每个 `@router.get(...)` 之下挂 `@endpoint_meta(...)`,例:

```python
@router.get(
    "/stocks/{stock_code}/quote",
    response_model=StockQuote,
    responses={...},
    tags=["stocks"],
)
@endpoint_meta(
    summary="实时行情",
    markets=["csi", "hk", "us"],
    capabilities=["REALTIME_QUOTE"],
    cache={"ttl_sec": 60, "env": "CACHE_TTL_QUOTE"},
)
def get_quote(...): ...
```

每个 endpoint 改造的 4 个字段从原 ENDPOINTS 复制:
- `summary`: 中文一句话
- `markets`: `["csi", "hk", "us"]` 之类
- `capabilities`: `["REALTIME_QUOTE"]` 之类
- `cache`: `{"ttl_sec": 60, "env": "CACHE_TTL_QUOTE"}` 之类

`params`/`response_fields`/`sources` **不复制**——`params` 从 FastAPI 反射,`response_fields` 字段名从 response_model 反射(`desc` 留空,第二期补),`sources` 第一期恒为空数组。

### 4.6 `stock_data/explorer/static/index.html` (改造)

**删**:第 282-1293 行(共约 1012 行,内嵌 ENDPOINTS 块)
**改**:1493-1599 区域(渲染逻辑)从 `ENDPOINTS.sections.forEach(...)` 改为 `manifest.sections.forEach(...)`,**结构完全相同,变量名替换 + 改 fetch 入口即可**
**加**:`<script>` 块在主 app 启动时执行 `fetch('/control/api-manifest')` → 缓存到全局 `manifest` → 调用 `renderSidebar()`/`renderContent()`

骨架:
```js
<script>
let MANIFEST = null;
const FALLBACK_ENDPOINTS = window.__FALLBACK_ENDPOINTS__;  // 拉取失败时用老 ENDPOINTS
async function loadManifest() {
  try {
    const r = await fetch("/control/api-manifest", { cache: "no-store" });
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    MANIFEST = await r.json();
  } catch (e) {
    console.warn("[explorer] manifest fetch failed, using fallback", e);
    MANIFEST = FALLBACK_ENDPOINTS;  // 兜底:老 ENDPOINTS
  }
}
function getEndpoints() { return MANIFEST; }  // 旧引用替换
</script>
```

`renderSidebar()`/`renderContent()`/`renderEndpoint()`/`renderEndpointDetails()` 的 `ENDPOINTS` 引用全部改为 `MANIFEST`。

`meta.capabilities`(label/icon)**移到 manifest 顶层**——capability 标签本质是 `DataCapability` flag 的可读名,跟 server 端定义强绑定(增/减/改名要跟 `data_provider/base.py` 同步),属于 server 元数据,由 manifest 携带;HTML 端只读不写。

`meta.fetcher_meta`(color 字段)继续手写在 `index.html`——color 是纯视觉装饰,跟 fetcher 业务无关;`priority` 字段第二期可从 `manager.fetchers` 反射填充,本期不动。

**容错**:如果 `fetch` 失败,使用一个**精简版**旧 ENDPOINTS(只 4-5 个 endpoint 的极简版)兜底——保证 HTML 永远不空白。但**实际失败只会发生在 server 完全没启动**,那种情况下 HTML 本来也连不上业务接口,所以兜底价值不大,先放最小化版本即可。

---

## 5. 数据流

```
server start
    ↓
    FastAPI 加载 routes.py
    ↓ @endpoint_meta 装饰器执行 → 写 REGISTRY[func] = EndpointMeta
    ↓
    explorer.mount(app) 调 build_control_router() 注册 /control/* + /control/api-manifest
    ↓
    client GET /explorer/ → StaticFiles 返回 index.html
    ↓
    HTML 解析 → 触发 fetch("/control/api-manifest")
    ↓
    control_api_manifest(request) → build_manifest(request.app)
        ├─ 遍历 app.routes,过滤 APIRoute 且 tags 不含 'control'
        ├─ 反射 route.path / route.methods / route.dependant.{path,query}_params
        ├─ 查 REGISTRY[route.endpoint] 拿 EndpointMeta
        └─ 合并成 JSON,加 generated_at 时间戳
    ↓
    JSON 返回 HTML → MANIFEST 赋值 → 渲染 sidebar + content
    ↓
    用户点 endpoint 卡片 → 用 MANIFEST 里的 path/method/params 调业务接口
```

**关键不变量**:
- `routes.py` 改了 endpoint → 启动 server 时 REGISTRY 重新填 → manifest 自动反映新 endpoint → HTML 刷新即可看到
- `routes.py` 加 endpoint 但忘了挂 `@endpoint_meta` → 启动 log warn → manifest 不含该 endpoint → HTML 漏显示 → **不静默**

---

## 6. API 设计 (manifest JSON 形态)

```json
{
  "meta": {
    "version": "1.1",
    "generated_at": "2026-06-12T10:30:00+00:00",
    "server_version": "0.5.2",
    "capabilities": {
      "REALTIME_QUOTE":  {"label": "实时行情",  "icon": "💹"},
      "HISTORICAL_DWM":  {"label": "日/周/月 K线", "icon": "📈"}
      // ...18 项,跟原 ENDPOINTS.meta.capabilities 一致
    }
  },
  "sections": [
    {
      "id": "4.2",
      "title": "股票 / 个股 API",
      "endpoints": [
        {
          "id": "get_stocks_stock_code_quote",
          "method": "GET",
          "path": "/stocks/{stock_code}/quote",
          "summary": "实时行情",
          "markets": ["csi", "hk", "us"],
          "capabilities": ["REALTIME_QUOTE"],
          "params": [
            {"name": "stock_code", "in": "path", "required": true, "type": "string", "desc": ""}
          ],
          "response_model": "StockQuote",
          "response_fields": ["code", "stock_name", "source", "current_price", ...],
          "cache": {"ttl_sec": 60, "env": "CACHE_TTL_QUOTE"},
          "sources": [],
          "probe_url": null
        }
      ]
    }
  ]
}
```

**字段约定**:
- `id`: 自动从 `method_path` slug 化,保证 DOM 元素 id 稳定
- `path`: 保留 FastAPI 路径参数 `{stock_code}` 格式,不转 `:stock_code` (HTML 已用 `{xxx}` 渲染)
- `desc` 在 `params` 和 `response_fields` 里**第一期全空**——HTML 端用字段名兜底显示
- `sources: []` / `probe_url: null`: 第一期显式空,schema 完整留给第二期填

---

## 7. 错误处理

| 失败点 | 行为 | 日志 |
|--------|------|------|
| `routes.py` 加 route 但没挂 `@endpoint_meta` | manifest 跳过 + log warn | `[manifest] route GET /xxx has no @endpoint_meta; skipping` |
| 同一函数挂两次 `@endpoint_meta` | 启动抛 `ValueError` | 启动失败(预期——开发期 bug) |
| `TAG_TO_SECTION` 漏配某 tag | 该 route 落到 tag 字面名为 section_id, title 也用 tag 字面名 | 无 log,UI 仍能渲染但不分组 |
| HTML `fetch('/control/api-manifest')` 失败 | 用 FALLBACK_ENDPOINTS 兜底 + console.warn | `[explorer] manifest fetch failed, using fallback` |
| Pydantic model 反射失败 | `response_fields: []` | 启动不报错,UI 显示无字段 |

**决定**: 反射失败全部**降级 + 继续**,不抛——manifest 是 UI 元数据,不能因为它导致 server 启动失败。

---

## 8. 测试策略

### 8.1 单元测试

**`tests/test_endpoint_meta.py`** (新增)
- `test_decorator_registers_in_REGISTRY`: 装饰器执行后 `REGISTRY[func]` 存在
- `test_duplicate_registration_raises`: 同一函数挂两次抛 `ValueError`
- `test_dataclass_is_frozen`: `EndpointMeta` 不可变

**`tests/test_manifest.py`** (新增)
- `test_manifest_includes_all_endpoints_with_meta`: 用 `FastAPI()` 临时 app,挂 3 个 route 各带 `@endpoint_meta`,调用 `build_manifest(app)` 断言 sections 含 3 个 endpoint
- `test_endpoint_without_meta_skipped_with_warning`: route 不带 `@endpoint_meta` → 不在 manifest
- `test_path_params_reflected`: `/stocks/{code}/quote` 反射出 `params[0] = {name: "code", in: "path", required: true, type: "string"}`
- `test_query_params_reflected_with_type_and_required`: `days: int = Query(30, ge=1)` 反射出 `{name: "days", in: "query", required: false, type: "int"}`
- `test_response_model_reflected_to_response_fields`: `response_model=StockQuote` 反射出字段名列表
- `test_sections_sorted_numerically`: `4.1, 4.2, ..., 4.10` 排序正确
- `test_control_tag_excluded`: `tags=["control"]` 的 `/control/*` 不在 manifest
- `test_capability_labels_preserved`: `meta.capabilities` 含原 18 项

### 8.2 集成测试

**`tests/test_explorer_manifest_endpoint.py`** (新增,扩展现有 `test_server_control_endpoints.py`)
- `test_get_api_manifest_returns_200_and_expected_shape`: `GET /control/api-manifest` → 200, JSON 含 `meta` + `sections`
- `test_manifest_sections_match_explorer_html_count`: manifest sections 数 == 原 index.html ENDPOINTS.sections 数(防止漏挂装饰器导致 endpoint 消失)
- `test_manifest_path_matches_router_path`: 每个 manifest endpoint.path == 对应 router 的 path 字符串

**`tests/test_explorer_manifest_html_render.py`** (新增,扩展现有 `test_api_html.py`)
- 不测 HTML 内部 JS(太脆);改为断言 `index.html` 不再含 `const ENDPOINTS = {` 字面量(防止 ENDPOINTS 块残留)
- 断言 `index.html` 含新引入的 `fetch("/control/api-manifest")`

### 8.3 回归测试

- 跑 `pytest` 全部用例,确保无破坏
- 手动启 server → 访问 `http://127.0.0.1:8888/explorer/` → 看到所有 endpoint 渲染出来
- 手动启 server → `curl /control/api-manifest` → 看到合理 JSON
- 手动在 routes.py 加一个临时 route(不挂 `@endpoint_meta`)→ 启动 log 看到 warn → manifest 跳过

---

## 9. 实施步骤 (建议 commit 拆分)

1. **commit 1**: 新增 `stock_data/api/endpoint_meta.py` + `tests/test_endpoint_meta.py`
2. **commit 2**: 新增 `stock_data/explorer/tags.py` + `stock_data/explorer/manifest.py` + `tests/test_manifest.py`
3. **commit 3**: `stock_data/explorer/routes.py` 加 `/control/api-manifest` 端点 + `tests/test_explorer_manifest_endpoint.py`
4. **commit 4**: `stock_data/api/routes.py` 给所有 endpoint 挂 `@endpoint_meta`(单 commit 大改动,理由:这些 endpoint 同步出现/消失,合在一起 review)
5. **commit 5**: `stock_data/explorer/static/index.html` 删 ENDPOINTS 块,改 fetch+render(单 commit 大改动,理由:同 4)
6. **commit 6**: 跑全套测试 + 手动验证

每个 commit 后 `pytest` 应全绿。

---

## 10. 不在范围 (Out of Scope)

第二期才做的(明确不在本次 commit 内):
- 补全 `sources: [{ fetcher, method, upstream, notes }]` 到每个 endpoint
- `manager.probe(fetcher, method, ...)` 方法
- `/control/fetcher/probe` 端点
- HTML fetcher 芯片 + "测试这个 fetcher" 按钮
- HTML `params.desc` / `response_fields` 中文 desc 自动/半自动补全
- `docs/API.md` 与 manifest 的关系重审(API.md 仍手工维护,但第二期可能停止维护,或加 docstring → API.md 的反向生成)

明确不做的(用户没要求,也不该做):
- 改路由 URL、response_model、API 响应 schema
- 重写 HTML 视觉/CSS/主题
- 改 explorer `/control/*` 5 个端点
- 重新打开 FastAPI `openapi_url`(那是方案 A,本次走方案 B)

---

## 11. 风险与缓解

| 风险 | 缓解 |
|------|------|
| 忘挂 `@endpoint_meta` 导致 endpoint 静默消失 | 启动 log warn;第二阶段可加 pre-commit hook 扫 routes.py |
| `response_fields` 缺 desc 让详情区难看 | 第一期允许,UI 端用字段名兜底;第二期补 desc |
| `dependant.path_params` 反射在某些 FastAPI 版本下行为不同 | `test_path_params_reflected` 锁定 0.115+ 行为;CI 跑 |
| `FALLBACK_ENDPOINTS` 体积大 | 删 ENDPOINTS 块时**保留一个极简版**(4-5 个 endpoint 字符串)作为兜底,体积 < 5KB |
| `tags.py` 与 `endpoint_meta.py` 循环引用 | tags.py 不依赖任何项目模块,manifest.py 引用 tags.py 即可 |
| `request.app` 类型是 `FastAPI`,反射 `app.routes` 拿不到所有 route | 已在 0.115 验证 `APIRoute` 在 `app.routes` 中;测试覆盖 |
| 大量 endpoint 一次性 commit 4 太大,review 困难 | routes.py 的 commit 4 改完后跑测试,review 时只看 diff 增量 |

---

## 12. 验收标准

- [ ] 所有 `routes.py` 现有 endpoint 都挂了 `@endpoint_meta`
- [ ] `pytest` 全绿(新增 ~10 个 test case)
- [ ] `index.html` 不再含字面量 `const ENDPOINTS = {`
- [ ] `curl /control/api-manifest` 返回 JSON,字段名跟本 spec 第 6 节一致
- [ ] 启动 server 后,`http://127.0.0.1:8888/explorer/` 渲染出所有 endpoint
- [ ] 在 `routes.py` 加一个临时 route(不挂 `@endpoint_meta`),启动 log 看到 warn,manifest 不含该 route
- [ ] 删掉 `index.html` 的 `const ENDPOINTS` 块后,HTML 仍能正常渲染(靠 fetch manifest + FALLBACK)
- [ ] `docs/superpowers/specs/2026-06-12-explorer-auto-api-manifest-design.md` 已 commit

---

## 13. 参考

- 现状 ENDPOINTS 形态: `stock_data/explorer/static/index.html:285-1293`
- 现状路由注册: `stock_data/api/routes.py:1-1712`
- 现状 explorer 挂载: `stock_data/explorer/__init__.py:21-52` + `stock_data/server.py:110-115`
- 现状 `/control/*` 端点风格: `stock_data/explorer/routes.py:39-88`
- 历史 spec 参考风格: `docs/superpowers/specs/2026-06-11-explorer-subpackage-move-design.md`
- CLAUDE.md "do not edit API.md" 约定: `CLAUDE.md:178` 附近
