"""Build the explorer manifest by reflecting FastAPI routes + REGISTRY.

`build_manifest(app)` 在 `/control/api-manifest` 被请求时调用,反射
`app.routes` 拿到所有 APIRoute,合并每个 route 的 `endpoint_meta`
装饰器声明,产出 explorer 消费用的 JSON 树。

不缓存:manifest 体量约 27 endpoint × ~200 字节 ≈ 5 KB,序列化无压力;
缓存反而让"加 endpoint 不重启不生效"成为陷阱。
"""
from __future__ import annotations

import logging
import types
from typing import Any, Union, get_args, get_origin

from fastapi import FastAPI
from fastapi.routing import APIRoute

from ..api.endpoint_meta import REGISTRY, EndpointMeta
from .tags import CAPABILITY_LABELS, TAG_TO_TITLE

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
                params: [{name, in, required, type}],
                response_model }
          ]}
        ]
    }

    section id 直接用 route 的 primary tag(无业务含义,仅作 DOM
    锚点);title 从 TAG_TO_TITLE 查,查不到回退到 tag 名本身。
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
        tag = route.tags[0]
        section = sections_map.setdefault(
            tag, {"id": tag, "title": TAG_TO_TITLE.get(tag, tag), "endpoints": []}
        )
        section["endpoints"].append(_build_endpoint_node(route, meta))
    return {
        "meta": _build_meta(),
        "sections": sorted(sections_map.values(), key=_section_sort_key),
    }


def _build_endpoint_node(route: APIRoute, meta: EndpointMeta) -> dict:
    params: list[dict] = []
    for p in route.dependant.path_params:
        params.append({
            "name": p.name, "in": "path", "required": True,
            "type": _python_type_to_str(p.field_info.annotation),
        })
    for p in route.dependant.query_params:
        params.append({
            "name": p.name, "in": "query", "required": bool(p.field_info.is_required()),
            "type": _python_type_to_str(p.field_info.annotation),
        })
    # 完整 URL: FastAPI 在 include_router(prefix=...) 时已把 prefix 合并到 route.path
    full_path = route.path
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
    }


def _pick_method(methods: frozenset) -> str:
    """多 method 时优先 GET,否则第一个。FastAPI 不会构造空 methods。"""
    if "GET" in methods:
        return "GET"
    if not methods:
        return "GET"  # 防御性兜底,实际不会触发
    return next(iter(methods))


def _python_type_to_str(annotation) -> str:
    """int / str / bool / float 映射;Optional 去掉 Optional 包装。"""
    # Handle Optional[X] / Union[X, None] (typing.Union AND PEP 604 types.UnionType)
    origin = get_origin(annotation)
    if origin is Union or origin is types.UnionType:
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
    """按 id 排序:目前 id 是 tag 名,字符串序即可。

    保留 (int, ...) 元组 fallback 以兼容未来若 id 重新引入"段号.小节"
    格式(避免 '4.10' 排在 '4.2' 前)。
    """
    parts = sec["id"].split(".")
    try:
        return tuple(int(p) for p in parts)
    except ValueError:
        return (sec["id"],)


def _slugify(s: str) -> str:
    """Stable, URL-safe slug for DOM id.

    `/`, `_`, `-` and path-param braces `{` `}` are all collapsed to a
    single `_`; consecutive separators become one. Example:
        "GET_/api/v1/stocks/{stock_code}/quote" -> "get_api_v1_stocks_stock_code_quote"
    """
    out: list[str] = []
    prev_sep = False
    for ch in s.lower():
        if ch.isalnum():
            out.append(ch)
            prev_sep = False
        elif ch in "/_{}-":
            if not prev_sep and out:
                out.append("_")
            prev_sep = True
    return "".join(out)
