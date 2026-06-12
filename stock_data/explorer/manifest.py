"""Build the explorer manifest by reflecting FastAPI routes + REGISTRY.

`build_manifest(app)` 在 server 启动时(或 `/control/api-manifest` 被请求时)
调用一次,反射 `app.routes` 拿到所有 APIRoute,合并每个 route 的
`endpoint_meta` 装饰器声明,产出 explorer 消费用的 JSON 树。

不缓存:manifest 体量约 20 endpoint × ~500 字节 ≈ 10 KB,序列化无压力;
缓存反而让"加 endpoint 不重启不生效"成为陷阱。
"""
from __future__ import annotations

import logging
import types
from typing import Any, Union, get_args, get_origin

from fastapi import FastAPI
from fastapi.routing import APIRoute

from ..api.endpoint_meta import REGISTRY, EndpointMeta
from .tags import CAPABILITY_LABELS, TAG_TO_SECTION

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
            "name": p.name, "in": "query", "required": bool(p.field_info.is_required()),
            "type": _python_type_to_str(p.field_info.annotation),
            "desc": "",
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
    """4.1, 4.2, ... 4.10 字典序正确(避免 '4.10' 排在 '4.2' 前)。"""
    parts = sec["id"].split(".")
    try:
        return tuple(int(p) for p in parts)
    except ValueError:
        return (999,)


def _slugify(s: str) -> str:
    """Stable, URL-safe slug for DOM id.

    `/`, `_`, `-` and path-param braces `{` `}` are all collapsed to a
    single `_`; consecutive separators become one. Example:
        "GET_/api/v1/stocks/{code}/quote" -> "get_api_v1_stocks_code_quote"
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
