"""Per-endpoint metadata registration for the API Explorer manifest.

`@endpoint_meta(...)` 装饰器挂载在每个 route 函数上,声明 OpenAPI 拿不到的
"业务语义"字段(markets, capabilities)。manifest 聚合器在请求时反射
`app.routes` 拿到 path / method / params,跟 REGISTRY 里这个函数的
metadata 合并。

Why a decorator instead of a parallel dict: 装饰器让 metadata 跟 route
函数物理上挨在一起,改 endpoint 时不会忘记同步(单点真相)。反射
`app.routes` 时按 `route.endpoint == 函数引用` 查 REGISTRY,O(1) 命中。

**Contract**: `endpoint_meta.deco` MUST return the same `func` object it
receives (not a wrapper). FastAPI captures `route.endpoint` at @router.get
time as the function reference AFTER the inner @endpoint_meta has run; if
this decorator ever wraps/replaces, `REGISTRY.get(route.endpoint)` will
miss and the route silently disappears from the explorer manifest.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

# Module-level registry: id(route_function) -> EndpointMeta
# Mutable on purpose: only the @endpoint_meta decorator writes to it.
REGISTRY: dict[Callable, EndpointMeta] = {}


@dataclass(frozen=True)
class EndpointMeta:
    """OpenAPI 拿不到、但 explorer 需要展示的字段。

    path / method / params / response_model 不在此处——它们在 build_manifest()
    里从 FastAPI 路由对象反射出来(单一真相在 @router.get 装饰器)。

    `fetcher_method` (optional): overrides the default method derived from
    CAPABILITY_TO_METHOD. Use when the endpoint's capability is shared by
    multiple endpoints calling different fetcher methods (e.g.
    /api/v1/dragon-tiger declares DRAGON_TIGER but calls
    get_daily_dragon_tiger, not the default get_dragon_tiger).
    """
    summary: str
    markets: list[str] = field(default_factory=list)
    capabilities: list[str] = field(default_factory=list)
    fetcher_method: str | None = None


def endpoint_meta(
    *,
    summary: str,
    markets: list[str] | None = None,
    capabilities: list[str] | None = None,
    fetcher_method: str | None = None,
) -> Callable:
    """装饰器,把 EndpointMeta 存到 REGISTRY[func]。"""
    meta = EndpointMeta(
        summary=summary,
        markets=list(markets) if markets else [],
        capabilities=list(capabilities) if capabilities else [],
        fetcher_method=fetcher_method,
    )

    def deco(func: Callable) -> Callable:
        if func in REGISTRY:
            raise ValueError(
                f"@endpoint_meta already registered for {func.__qualname__}"
            )
        REGISTRY[func] = meta
        return func

    return deco
