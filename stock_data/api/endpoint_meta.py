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
