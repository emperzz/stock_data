"""Build the explorer manifest by reflecting FastAPI routes + REGISTRY.

`build_manifest(app)` 在 `/control/api-manifest` 被请求时调用,反射
`app.routes` 拿到所有 APIRoute,合并每个 route 的 `endpoint_meta`
装饰器声明,产出 explorer 消费用的 JSON 树。

不缓存:manifest 体量约 27 endpoint × ~200 字节 ≈ 5 KB,序列化无压力;
缓存反而让"加 endpoint 不重启不生效"成为陷阱。
"""

from __future__ import annotations

import inspect
import logging
import types
from typing import Any, Union, get_args, get_origin

from fastapi import FastAPI
from fastapi.routing import APIRoute

from .. import __version__
from ..api.endpoint_meta import REGISTRY, EndpointMeta
from ..data_provider.base import CAPABILITY_TO_METHOD, BaseFetcher, DataCapability
from .tags import _INTERNAL_TAGS, CAPABILITY_LABELS, TAG_TO_TITLE

logger = logging.getLogger(__name__)


# Per-fetcher method overrides for capabilities where the capability-level
# default in `CAPABILITY_TO_METHOD` doesn't match what the specific fetcher
# actually implements. Currently the only such case is Zhitu's minute-level
# support: `CAPABILITY_TO_METHOD[STOCK_KLINE]` maps to ``get_kline_data``
# (correct for Baostock/Akshare/Yfinance/Myquant, which all expose minutes
# via ``get_kline_data``), but Zhitu's minutes live in ``get_intraday_data``
# and its inherited ``get_kline_data`` raises DataFetchError. The Test
# button uses this method name + signature verbatim, so getting it wrong
# produces confusing 500s.
_FETCHER_METHOD_OVERRIDES: dict[tuple[DataCapability, str], str] = {
    (DataCapability.STOCK_KLINE, "ZhituFetcher"): "get_intraday_data",
}


def _resolve_fetcher_method(cap: DataCapability, fetcher_name: str) -> str | None:
    """Pick the right method name for ``fetcher_name`` under capability ``cap``.

    Order: per-fetcher override → capability default → ``None`` (no mapping).
    """
    override = _FETCHER_METHOD_OVERRIDES.get((cap, fetcher_name))
    if override is not None:
        return override
    return CAPABILITY_TO_METHOD.get(cap)


# manifest schema version——schema 字段有 breaking 变化时递增
MANIFEST_VERSION = "1.1"


def _lookup_registry(endpoint: Any) -> EndpointMeta | None:
    """Find the :class:`EndpointMeta` registered for ``endpoint``.

    ``REGISTRY`` keys on the original function (the innermost function after
    ``@endpoint_meta``). With the routes-package refactor, layers like
    ``@cache_endpoint`` and ``@map_errors`` sit between ``@endpoint_meta``
    and ``@router.get``; ``functools.wraps`` sets ``__wrapped__`` so we can
    walk the chain to find the registered function.

    Returns ``None`` when nothing in the chain (or any cycle) resolves to a
    registry entry — callers treat that as "no @endpoint_meta, skip".
    """
    seen: set = set()
    func = endpoint
    while func is not None and func not in seen:
        if func in REGISTRY:
            return REGISTRY[func]
        seen.add(func)
        func = getattr(func, "__wrapped__", None)
    return None


def build_manifest(app: FastAPI) -> dict[str, Any]:
    """返回 {
        meta: { version, generated_at, server_version, capabilities: {...} },
        sections: [
          { id, title, endpoints: [
              { id, method, path, summary, markets, capabilities,
                params: [{name, in, required, type}],
                response_model,
                fetchers: [{name, method, priority, capabilities, signature}] }
          ]}
        ]
    }

    section id 直接用 route 的 primary tag(无业务含义,仅作 DOM
    锚点);title 从 TAG_TO_TITLE 查,查不到回退到 tag 名本身。

    `fetchers` 字段枚举该 endpoint 实际可调度的 fetcher(按 priority 升序);
    数据源是 `app.state.manager`(lifespan 启动时由 server.py 注入)。
    """
    manager = getattr(app.state, "manager", None)
    sections_map: dict[str, dict] = {}
    for route in app.routes:
        if not isinstance(route, APIRoute):
            continue
        if not route.tags or any(t in _INTERNAL_TAGS for t in route.tags):
            continue
        meta = _lookup_registry(route.endpoint)
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
        section["endpoints"].append(_build_endpoint_node(route, meta, manager))
    return {
        "meta": _build_meta(),
        "sections": sorted(sections_map.values(), key=_section_sort_key),
    }


def _build_endpoint_node(route: APIRoute, meta: EndpointMeta, manager) -> dict:
    params: list[dict] = []
    for p in route.dependant.path_params:
        params.append(
            {
                "name": p.name,
                "in": "path",
                "required": True,
                "type": _python_type_to_str(p.field_info.annotation),
            }
        )
    for p in route.dependant.query_params:
        params.append(
            {
                "name": p.name,
                "in": "query",
                "required": bool(p.field_info.is_required()),
                "type": _python_type_to_str(p.field_info.annotation),
            }
        )
    # 完整 URL: FastAPI 在 include_router(prefix=...) 时已把 prefix 合并到 route.path
    full_path = route.path
    # HTTP method: route.methods 是 frozenset, 例 {'GET'} 或 {'GET', 'HEAD'}
    method = _pick_method(route.methods)
    fetchers = _resolve_fetchers(meta, manager) if manager is not None else []
    return {
        "id": _slugify(f"{method}_{full_path}"),
        "method": method,
        "path": full_path,
        "summary": meta.summary,
        "markets": list(meta.markets),
        "capabilities": list(meta.capabilities),
        "params": params,
        "response_model": route.response_model.__name__ if route.response_model else None,
        "fetchers": fetchers,
    }


def _pick_method(methods: frozenset) -> str:
    """多 method 时优先 GET,否则第一个。FastAPI 不会构造空 methods。"""
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


def _reflect_signature(method) -> list[dict]:
    """Reflect a fetcher method into JSON-serializable param dicts.

    Skips `self`. Falls back to "string" for unannotated params and
    JSON-serializes defaults (unrepresentable defaults stringify via repr()).
    """
    out: list[dict] = []
    try:
        sig = inspect.signature(method)
    except (ValueError, TypeError):
        return out
    for name, param in sig.parameters.items():
        if name == "self":
            continue
        if param.kind in (inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD):
            continue  # *args / **kwargs not representable as discrete fields
        # Type rendering
        if param.annotation is inspect.Parameter.empty:
            type_str = "string"
        else:
            type_str = _python_type_to_str(param.annotation)
        # Default rendering
        if param.default is inspect.Parameter.empty:
            required = True
            default_val = None
        else:
            required = False
            default_val = _jsonify_default(param.default)
        out.append(
            {
                "name": name,
                "type": type_str,
                "required": required,
                "default": default_val,
            }
        )
    return out


def _jsonify_default(value):
    """Make a default value JSON-serializable, falling back to repr()."""
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return repr(value)


def _resolve_fetchers(meta, manager) -> list[dict]:
    """Enumerate fetchers eligible for an endpoint, deduped by (name, method).

    Returns a list of {name, method, priority, capabilities, signature,
    available, reason} dicts sorted by priority ascending (matches actual
    failover order).

    Walks **all** `BaseFetcher` subclasses that declare the capability for the
    endpoint's market — not just those currently registered with the manager.
    Unregistered fetchers (e.g. ZhituFetcher when ZHITU_TOKEN is unset) are
    surfaced with `available: false` and a `reason` string from the fetcher's
    own `unavailable_reason()` method (logic-driven, derived from real state
    rather than a hardcoded label). The Test button still works for them:
    /control/fetcher-test instantiates the class on demand and returns the
    same `FetcherUnavailable` error path it would have hit at registration.
    """
    if not meta.capabilities or not meta.markets:
        return []

    # Build two lookup maps from registered fetchers:
    # - by_name: instance.name → instance (production path — manager registers
    #   fetchers keyed by their own name attribute)
    # - by_class: id(cls) → instance (test path — when tests inject fake
    #   classes without going through manager.add_fetcher(), the only way to
    #   tell "this fetcher_cls has a registered instance" is by class identity)
    registered_by_name: dict[str, BaseFetcher] = {f.name: f for f in manager._fetchers}
    registered_by_class: dict[int, BaseFetcher] = {id(type(f)): f for f in manager._fetchers}

    # (fetcher_name, method_name) → entry dict (single source of dedup)
    entries: dict[tuple[str, str], dict] = {}

    for cap_name in meta.capabilities:
        # Resolve string → enum; skip unknown gracefully (warning lives in sanity check)
        try:
            cap = DataCapability[cap_name]
        except KeyError:
            continue

        # Determine method name: endpoint-level override > capability default.
        # Per-fetcher overrides (e.g. Zhitu's intraday method) are applied
        # *inside* the candidate-class loop below — see _resolve_fetcher_method.
        if meta.fetcher_method is not None:
            method_name = meta.fetcher_method
        else:
            method_name = CAPABILITY_TO_METHOD.get(cap)
            if method_name is None:
                continue  # capability has no mapped method

        # Walk all concrete subclasses that declare this capability — even
        # ones the manager didn't register (because is_available()==False).
        # This is the difference vs. the prior implementation, which only
        # iterated `manager._filter_by_capability(...)` (registered only).
        candidate_classes = _classes_declaring_capability(cap)
        # Endpoint-level override (e.g. `@endpoint_meta(fetcher_method=...)`)
        # wins for every fetcher on this endpoint — it's the strongest
        # signal. Only when it's NOT set do we look at per-fetcher
        # overrides (one-off cases like Zhitu's intraday, where one
        # outlier fetcher implements a capability via a different
        # method name than the rest of the failover chain).
        endpoint_method_override = meta.fetcher_method is not None
        for fetcher_cls in candidate_classes:
            fetcher_name = getattr(fetcher_cls, "name", fetcher_cls.__name__)

            if endpoint_method_override:
                # Endpoint-level override applies uniformly — skip the
                # per-fetcher resolver entirely.
                effective_method = method_name
            else:
                # Per-fetcher method override: when the capability's
                # default method name doesn't match what this particular
                # fetcher actually implements (e.g. Zhitu's minutes live
                # in `get_intraday_data`, not the default
                # `get_kline_data`), swap to the per-fetcher mapping.
                # Falls back to the loop-level `method_name` (which is
                # the capability default) when no override exists.
                # `method_name` stays the loop-level default;
                # `effective_method` is per-iteration so the override
                # doesn't leak to the next fetcher.
                effective_method = _resolve_fetcher_method(cap, fetcher_name)
                if effective_method is None:
                    # Capability has no default mapping and no per-fetcher
                    # override — leave the row off this endpoint (matches
                    # the pre-override behavior).
                    continue

            # Use the registered instance if available (already initialized);
            # otherwise instantiate a fresh one to query is_available() /
            # unsupported_markets / unsupported_reason() and reflect the
            # method signature. Construction is cheap — Zhitu/Tushare/
            # Myquant only read env vars; no network calls happen here.
            # Look up by `fetcher_name` first (production path); fall back
            # to class identity (test path: fakes registered without
            # matching name attribute).
            instance = registered_by_name.get(fetcher_name)
            if instance is None:
                instance = registered_by_class.get(id(fetcher_cls))
            if instance is None:
                try:
                    instance = fetcher_cls()
                except Exception:
                    # Cannot even construct — surface as unavailable with no reason.
                    entries[(fetcher_name, effective_method)] = {
                        "name": fetcher_name,
                        "method": effective_method,
                        "priority": getattr(fetcher_cls, "priority", 99),
                        "capabilities": [cap_name],
                        "signature": [],
                        "available": False,
                        "reason": f"{fetcher_name} could not be instantiated",
                    }
                    continue

            # Filter by market: skip if no overlap with the endpoint's markets.
            # Check instance (filled in by __init__) rather than class
            # (test fakes leave class-level default empty).
            instance_markets = getattr(instance, "supported_markets", set()) or set()
            if not instance_markets or not (instance_markets & set(meta.markets)):
                continue

            key = (fetcher_name, effective_method)
            if key in entries:
                if cap_name not in entries[key]["capabilities"]:
                    entries[key]["capabilities"].append(cap_name)
                continue

            # Skip if the (instance) doesn't actually expose this method.
            method = getattr(instance, effective_method, None)
            if method is None or not callable(method):
                continue

            available = bool(instance.is_available())
            reason = None if available else instance.unavailable_reason()

            entries[key] = {
                "name": fetcher_name,
                "method": effective_method,
                "priority": instance.priority,
                "capabilities": [cap_name],
                "signature": _reflect_signature(method),
                "available": available,
                "reason": reason,
            }

    return sorted(entries.values(), key=lambda e: e["priority"])


def _classes_declaring_capability(cap: DataCapability) -> list[type[BaseFetcher]]:
    """Walk `BaseFetcher.__subclasses__()` and return those whose
    `supported_data_types` includes `cap`.

    Mirrors `_collect_concrete_fetcher_classes()` in `explorer/__init__.py`
    but is scoped to a single capability and returns the raw classes (not
    instantiated). Importing the fetchers module is the caller's
    responsibility — we rely on the subclasses being importable by the time
    the manifest is built (the manager init at server startup imports them).
    """
    found: list[type[BaseFetcher]] = []
    stack: list[type] = list(BaseFetcher.__subclasses__())
    while stack:
        cls = stack.pop()
        found.append(cls)
        stack.extend(cls.__subclasses__())
    return [
        c
        for c in found
        if cap in (getattr(c, "supported_data_types", DataCapability(0)) or DataCapability(0))
    ]


def _build_meta() -> dict:
    return {
        "version": MANIFEST_VERSION,
        "generated_at": None,  # 服务端在响应时填 ISO 8601
        "server_version": __version__,
        "capabilities": CAPABILITY_LABELS,
    }


def _section_sort_key(sec: dict) -> str:
    """按 id 字符串排序 (id 是 tag 名)."""
    return sec["id"]


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
