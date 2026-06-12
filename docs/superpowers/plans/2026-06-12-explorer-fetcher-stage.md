# Explorer Fetcher Drill-down Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a two-stage UI under each server API in `/explorer/`: Stage 1 lists the fetchers that can serve the endpoint plus their internal method signatures; Stage 2 lets the user invoke any single fetcher method (bypassing manager failover) for diagnostics.

**Architecture:** Add a `CAPABILITY_TO_METHOD` lookup table next to `DataCapability`. Extend `EndpointMeta` with an optional `fetcher_method` override for capabilities used by multiple endpoints. Manifest builder reflects the manager (passed via `app.state.manager`) to enumerate eligible fetchers per endpoint and `inspect.signature` to expose method signatures. A new `POST /control/fetcher-test` endpoint accepts `{fetcher, method, kwargs}` and always returns HTTP 200 (success/failure in body). HTML adds a collapsible `<details>` section per endpoint card with per-fetcher Test buttons that open inline mini-forms.

**Tech Stack:** Python 3.11+, FastAPI route introspection (`APIRoute`, `route.dependant`, `app.state`), `inspect.signature`, Pydantic, vanilla JS + native `<details>` element in `index.html`, pytest + FastAPI `TestClient` + `unittest.mock`.

**Spec:** `docs/superpowers/specs/2026-06-12-explorer-fetcher-stage-design.md`

---

## File Structure

| File | Action | Purpose |
|------|--------|---------|
| `stock_data/data_provider/base.py` | Modify | Add `CAPABILITY_TO_METHOD: dict[DataCapability, str]` + `_NO_FETCHER_METHOD: frozenset[DataCapability]` |
| `stock_data/api/endpoint_meta.py` | Modify | Add `EndpointMeta.fetcher_method: str \| None` field; decorator accepts new kwarg |
| `stock_data/api/routes.py` | Modify | Add `fetcher_method=...` to 3 endpoints (`/boards/{board_code}/stocks`, `/dragon-tiger/daily`, `/stocks/{stock_code}/fund-flow/daily`) |
| `stock_data/server.py` | Modify | Wire `app.state.manager = get_manager()` in lifespan |
| `stock_data/explorer/manifest.py` | Modify | Add `_reflect_signature(method)` + `_resolve_fetchers(meta, manager)` helpers; integrate `fetchers` field into `_build_endpoint_node` |
| `stock_data/explorer/routes.py` | Modify | Add `POST /control/fetcher-test` (Pydantic request model + error classification) |
| `stock_data/explorer/__init__.py` | Modify | Extend `_validate_manifest_invariants` (map completeness + override sanity + cache fetcher-method whitelist on app.state) |
| `stock_data/explorer/static/index.html` | Modify | Stage 1 collapsible Fetcher backends section + Stage 2 mini-form + Run flow |
| `tests/test_capability_method_map.py` | Create | Parametrized completeness tests for `CAPABILITY_TO_METHOD` + override sanity |
| `tests/test_endpoint_meta.py` | Modify | Test new `fetcher_method` field on `EndpointMeta` + decorator |
| `tests/test_explorer_manifest_endpoint.py` | Modify | Assert `fetchers[]` field on manifest nodes; verify override endpoints |
| `tests/test_fetcher_test_endpoint.py` | Create | Cover all error classes; assert HTTP always 200 + elapsed_ms field |
| `CLAUDE.md` | Modify | Add "Stage 1/2 Fetcher Drill-down" section + manifest schema update + `fetcher_method` override table |

---

## Task 1: `CAPABILITY_TO_METHOD` lookup table + sanity tests

**Files:**
- Modify: `stock_data/data_provider/base.py`
- Create: `tests/test_capability_method_map.py`

This task introduces the central mapping from `DataCapability` to fetcher method name, with an explicit "no method" sentinel set to force every new capability to declare intent.

- [ ] **Step 1: Write the failing test**

Create `tests/test_capability_method_map.py`:

```python
"""Tests for CAPABILITY_TO_METHOD lookup table in data_provider/base.py.

This table is the single source of truth used by the explorer manifest to
decide which fetcher method corresponds to which DataCapability.
Every DataCapability flag MUST be either:
  - in CAPABILITY_TO_METHOD (maps to a fetcher method name), OR
  - in _NO_FETCHER_METHOD (explicit "this capability has no method").
This forces every new capability author to declare intent.
"""
import pytest

from stock_data.data_provider.base import (
    BaseFetcher,
    DataCapability,
    CAPABILITY_TO_METHOD,
    _NO_FETCHER_METHOD,
)


@pytest.mark.parametrize("cap", list(DataCapability))
def test_every_capability_has_intent_declared(cap):
    """Every DataCapability MUST be either mapped to a method or explicitly excluded."""
    in_map = cap in CAPABILITY_TO_METHOD
    in_no_method = cap in _NO_FETCHER_METHOD
    assert in_map ^ in_no_method, (
        f"DataCapability.{cap.name} must be in CAPABILITY_TO_METHOD "
        f"OR _NO_FETCHER_METHOD (not both, not neither). "
        f"Currently: in_map={in_map}, in_no_method={in_no_method}"
    )


@pytest.mark.parametrize("cap,method_name", list(CAPABILITY_TO_METHOD.items()))
def test_mapped_method_exists_on_base_fetcher(cap, method_name):
    """Every method name in the map must exist on BaseFetcher (catch typos)."""
    assert hasattr(BaseFetcher, method_name), (
        f"DataCapability.{cap.name} maps to method '{method_name}', "
        f"but BaseFetcher has no such attribute. Did you typo the method name?"
    )


def test_known_mappings():
    """Spot-check a few well-known mappings to catch refactor regressions."""
    assert CAPABILITY_TO_METHOD[DataCapability.HISTORICAL_DWM] == "get_kline_data"
    assert CAPABILITY_TO_METHOD[DataCapability.HISTORICAL_MIN] == "get_kline_data"
    assert CAPABILITY_TO_METHOD[DataCapability.REALTIME_QUOTE] == "get_realtime_quote"
    assert CAPABILITY_TO_METHOD[DataCapability.STOCK_BOARD] == "get_all_concept_boards"
    assert CAPABILITY_TO_METHOD[DataCapability.DRAGON_TIGER] == "get_dragon_tiger"
    assert CAPABILITY_TO_METHOD[DataCapability.FUND_FLOW] == "get_fund_flow_minute"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_capability_method_map.py -v`
Expected: FAIL with `ImportError: cannot import name 'CAPABILITY_TO_METHOD' from 'stock_data.data_provider.base'`

- [ ] **Step 3: Add `CAPABILITY_TO_METHOD` and `_NO_FETCHER_METHOD` to base.py**

Edit `stock_data/data_provider/base.py`. Just below the `DataCapability(Flag)` class definition (currently ending at line ~56), insert:

```python
# ────────────────────────────────────────────────────────────────────────
# Capability → fetcher method name lookup
# ────────────────────────────────────────────────────────────────────────
#
# Single source of truth used by the explorer manifest (`build_manifest`)
# to enumerate "which fetcher method corresponds to this capability".
# Manager.py does NOT consume this table — its routing methods already
# hardcode the method call (e.g. `manager.get_kline_data` calls
# `fetcher.get_kline_data` directly). This table is reflection-only.
#
# Rule (enforced by tests/test_capability_method_map.py):
#   Every DataCapability flag MUST be in CAPABILITY_TO_METHOD or
#   _NO_FETCHER_METHOD. Adding a new capability without declaring
#   intent breaks the test suite.
#
# When a single capability is used by multiple endpoints that call
# different fetcher methods (STOCK_BOARD, DRAGON_TIGER, FUND_FLOW),
# the value here is the DEFAULT. Endpoints that need a different
# method override via `@endpoint_meta(fetcher_method="...")`.
CAPABILITY_TO_METHOD: dict[DataCapability, str] = {
    DataCapability.HISTORICAL_DWM: "get_kline_data",
    DataCapability.HISTORICAL_MIN: "get_kline_data",
    DataCapability.REALTIME_QUOTE: "get_realtime_quote",
    DataCapability.STOCK_LIST: "get_all_stocks",
    DataCapability.TRADE_CALENDAR: "get_trade_calendar",
    DataCapability.STOCK_BOARD: "get_all_concept_boards",   # default; industry/.stocks variants override
    DataCapability.INDEX_QUOTE: "get_index_realtime_quote",
    DataCapability.INDEX_HISTORICAL: "get_index_historical",
    DataCapability.INDEX_INTRADAY: "get_index_intraday",
    DataCapability.STOCK_ZT_POOL: "get_zt_pool",
    DataCapability.DRAGON_TIGER: "get_dragon_tiger",         # default; /daily variant overrides
    DataCapability.MARGIN_TRADING: "get_margin_trading",
    DataCapability.BLOCK_TRADE: "get_block_trade",
    DataCapability.HOLDER_NUM: "get_holder_num_change",
    DataCapability.DIVIDEND: "get_dividend",
    DataCapability.FUND_FLOW: "get_fund_flow_minute",        # default; /daily variant overrides
    DataCapability.HOT_TOPICS: "get_hot_topics",
    DataCapability.NORTH_FLOW: "get_north_flow",
    DataCapability.RESEARCH_REPORT: "get_reports",
    DataCapability.ANNOUNCEMENT: "get_announcements",
}

# Explicit "this capability legitimately has no fetcher method" set.
# Empty today — placeholder for future pure-compute capabilities.
_NO_FETCHER_METHOD: frozenset[DataCapability] = frozenset()
```

Also update the `__all__` re-exports:

```python
__all__ = [
    "BaseFetcher",
    "DataCapability",
    "DataFetchError",
    "RateLimitError",
    "STANDARD_COLUMNS",
    "CAPABILITY_TO_METHOD",
    "_NO_FETCHER_METHOD",
]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/test_capability_method_map.py -v`
Expected: PASS (3 named tests + parametrized expansions ≈ 40+ test cases all green)

- [ ] **Step 5: Commit**

```bash
git add stock_data/data_provider/base.py tests/test_capability_method_map.py
git commit -m "feat(base): add CAPABILITY_TO_METHOD lookup for explorer manifest

Single source of truth mapping DataCapability flags to fetcher method
names. Used by the explorer manifest builder to enumerate eligible
fetchers per endpoint. Manager.py is unchanged — this table is
reflection-only.

Includes parametrized tests enforcing that every DataCapability is
either in the map or in the explicit _NO_FETCHER_METHOD set,
preventing silent drift when new capabilities are added.

Refs: docs/superpowers/specs/2026-06-12-explorer-fetcher-stage-design.md

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 2: `EndpointMeta.fetcher_method` field

**Files:**
- Modify: `stock_data/api/endpoint_meta.py`
- Modify: `tests/test_endpoint_meta.py`

This task adds the optional `fetcher_method` override field so multi-method capabilities (STOCK_BOARD, DRAGON_TIGER, FUND_FLOW) can pin a specific method per endpoint.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_endpoint_meta.py` (after the existing `TestEndpointMetaDecorator` class):

```python
class TestFetcherMethodOverride:
    def teardown_method(self):
        REGISTRY.clear()

    def test_default_is_none(self):
        m = EndpointMeta(summary="x")
        assert m.fetcher_method is None

    def test_explicit_value_stored(self):
        m = EndpointMeta(summary="x", fetcher_method="get_dragon_tiger")
        assert m.fetcher_method == "get_dragon_tiger"

    def test_decorator_accepts_fetcher_method(self):
        @endpoint_meta(
            summary="龙虎榜每日",
            capabilities=["DRAGON_TIGER"],
            fetcher_method="get_daily_dragon_tiger",
        )
        def my_route():
            return None
        meta = REGISTRY[my_route]
        assert meta.fetcher_method == "get_daily_dragon_tiger"
        assert meta.capabilities == ["DRAGON_TIGER"]

    def test_decorator_default_fetcher_method_is_none(self):
        @endpoint_meta(summary="x", capabilities=["REALTIME_QUOTE"])
        def my_route():
            return None
        assert REGISTRY[my_route].fetcher_method is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_endpoint_meta.py::TestFetcherMethodOverride -v`
Expected: FAIL with `TypeError: __init__() got an unexpected keyword argument 'fetcher_method'`

- [ ] **Step 3: Add `fetcher_method` field to dataclass and decorator**

Edit `stock_data/api/endpoint_meta.py`. Modify the `EndpointMeta` dataclass (around line 28-37) to add the new field:

```python
@dataclass(frozen=True)
class EndpointMeta:
    """OpenAPI 拿不到、但 explorer 需要展示的字段。

    path / method / params / response_model 不在此处——它们在 build_manifest()
    里从 FastAPI 路由对象反射出来(单一真相在 @router.get 装饰器)。

    `fetcher_method` (optional): overrides the default method derived from
    CAPABILITY_TO_METHOD. Use when the endpoint's capability is shared by
    multiple endpoints calling different fetcher methods (e.g.
    /dragon-tiger/daily declares DRAGON_TIGER but calls
    get_daily_dragon_tiger, not the default get_dragon_tiger).
    """
    summary: str
    markets: list[str] = field(default_factory=list)
    capabilities: list[str] = field(default_factory=list)
    fetcher_method: str | None = None
```

Modify the `endpoint_meta` decorator signature (around line 40-61):

```python
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/test_endpoint_meta.py -v`
Expected: PASS (existing tests + 4 new tests in `TestFetcherMethodOverride`)

- [ ] **Step 5: Commit**

```bash
git add stock_data/api/endpoint_meta.py tests/test_endpoint_meta.py
git commit -m "feat(endpoint_meta): add optional fetcher_method override

Endpoints whose declared capability is used by multiple endpoints
(STOCK_BOARD, DRAGON_TIGER, FUND_FLOW) can now pin the specific
fetcher method via @endpoint_meta(fetcher_method=\"...\"). When
unset, manifest builder falls back to CAPABILITY_TO_METHOD default.

Refs: docs/superpowers/specs/2026-06-12-explorer-fetcher-stage-design.md

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 3: Add `fetcher_method` overrides to 3 endpoints in routes.py

**Files:**
- Modify: `stock_data/api/routes.py`

Three endpoints declare a capability whose default method is wrong for them. Add explicit overrides.

- [ ] **Step 1: Locate and patch `/boards/{board_code}/stocks` (~line 1163)**

Find the `@endpoint_meta(...)` block right after `@router.get("/boards/{board_code}/stocks", ...)`. The current block is:

```python
@endpoint_meta(
    summary="板块成分股",
    markets=["csi"],
    capabilities=["STOCK_BOARD"],
)
```

Replace with:

```python
@endpoint_meta(
    summary="板块成分股",
    markets=["csi"],
    capabilities=["STOCK_BOARD"],
    fetcher_method="get_concept_board_stocks",  # default get_all_concept_boards is wrong for /stocks variant
)
```

- [ ] **Step 2: Locate and patch `/dragon-tiger/daily` (~line 1448)**

Find the `@endpoint_meta(...)` block right after `@router.get("/dragon-tiger/daily", ...)`. The current block:

```python
@endpoint_meta(
    summary="龙虎榜（全市场）",
    markets=["csi"],
    capabilities=["DRAGON_TIGER"],
)
```

Replace with:

```python
@endpoint_meta(
    summary="龙虎榜（全市场）",
    markets=["csi"],
    capabilities=["DRAGON_TIGER"],
    fetcher_method="get_daily_dragon_tiger",  # default get_dragon_tiger is per-stock variant
)
```

- [ ] **Step 3: Locate and patch `/stocks/{stock_code}/fund-flow/daily` (~line 1655)**

Find the `@endpoint_meta(...)` block right after `@router.get("/stocks/{stock_code}/fund-flow/daily", ...)`. The current block:

```python
@endpoint_meta(
    summary="资金流（120 日）",
    markets=["csi"],
    capabilities=["FUND_FLOW"],
)
```

Replace with:

```python
@endpoint_meta(
    summary="资金流（120 日）",
    markets=["csi"],
    capabilities=["FUND_FLOW"],
    fetcher_method="get_fund_flow_120d",  # default get_fund_flow_minute is the minute-level variant
)
```

- [ ] **Step 4: Run existing tests to verify nothing breaks**

Run: `.venv/Scripts/python.exe -m pytest tests/test_endpoint_meta.py tests/test_explorer_manifest_endpoint.py -v`
Expected: PASS (no behavior change for existing tests; the new field is optional)

- [ ] **Step 5: Commit**

```bash
git add stock_data/api/routes.py
git commit -m "feat(routes): add fetcher_method override on 3 multi-method endpoints

/boards/{board_code}/stocks       → get_concept_board_stocks
/dragon-tiger/daily               → get_daily_dragon_tiger
/stocks/{stock_code}/fund-flow/daily → get_fund_flow_120d

Without these, the explorer Fetcher backends panel would show the
default method for the capability (e.g. get_dragon_tiger for both
/dragon-tiger/{code} and /dragon-tiger/daily), misleading the user
about what Stage 2 testing actually calls.

Refs: docs/superpowers/specs/2026-06-12-explorer-fetcher-stage-design.md

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 4: Wire `app.state.manager` in server lifespan

**Files:**
- Modify: `stock_data/server.py`

Manifest builder needs the manager instance to enumerate fetchers. Expose it via `app.state.manager` so tests can inject mocks.

- [ ] **Step 1: Write the failing test**

Create or extend `tests/test_explorer_manifest_endpoint.py` (we'll fill it out more in Task 7; for now just add this one test). If file exists, append. If not, create with:

```python
"""Integration tests for GET /control/api-manifest with fetchers field."""
from fastapi.testclient import TestClient

from stock_data.server import app


def test_app_state_has_manager_after_startup():
    """app.state.manager must be wired during lifespan startup."""
    with TestClient(app) as client:
        # Trigger lifespan
        client.get("/control/server/status")
        assert hasattr(app.state, "manager"), (
            "app.state.manager not set — manifest builder will fail to "
            "enumerate fetchers"
        )
        from stock_data.data_provider.manager import DataFetcherManager
        assert isinstance(app.state.manager, DataFetcherManager)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_explorer_manifest_endpoint.py::test_app_state_has_manager_after_startup -v`
Expected: FAIL with `AssertionError: app.state.manager not set` (or `AttributeError`)

- [ ] **Step 3: Wire manager in lifespan startup**

Edit `stock_data/server.py`. In the `lifespan` function (currently lines 39-80), after the trade-calendar warm-up block (line 77), before `yield`, add:

```python
    # ----- Expose manager via app.state for the explorer manifest builder -----
    # The manifest needs to enumerate fetchers per (market, capability).
    # Using app.state avoids importing the global get_manager() into manifest.py,
    # which would make manifest.py harder to unit-test (couldn't inject a mock).
    from .api.routes import get_manager
    app.state.manager = get_manager()
    logger.info("[Startup] app.state.manager wired for explorer manifest")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/test_explorer_manifest_endpoint.py::test_app_state_has_manager_after_startup -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add stock_data/server.py tests/test_explorer_manifest_endpoint.py
git commit -m "feat(server): expose manager via app.state for explorer manifest

The /control/api-manifest endpoint needs to enumerate fetchers per
(market, capability) to populate the new fetchers[] field on each
endpoint node. Wiring via app.state.manager (instead of importing
get_manager into manifest.py) keeps manifest.py testable via mock
injection.

Refs: docs/superpowers/specs/2026-06-12-explorer-fetcher-stage-design.md

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 5: `_reflect_signature` helper in manifest.py

**Files:**
- Modify: `stock_data/explorer/manifest.py`
- Create: `tests/test_manifest_signature.py`

Helper that reflects a fetcher method's signature into a JSON-serializable list of param dicts. Pure function — easy to unit-test in isolation before integrating.

- [ ] **Step 1: Write the failing test**

Create `tests/test_manifest_signature.py`:

```python
"""Unit tests for _reflect_signature in explorer/manifest.py."""
import pytest

from stock_data.explorer.manifest import _reflect_signature


class _DummyFetcher:
    """A stand-in fetcher whose methods exercise the reflector's edge cases."""

    def simple(self, code: str, period: str = "d") -> str:
        return ""

    def with_optional(self, code: str, start: str | None = None) -> str:
        return ""

    def with_int_and_bool(self, code: str, limit: int = 30, force: bool = False) -> str:
        return ""

    def no_annotations(self, code, period="d"):
        return ""


def test_self_is_stripped():
    sig = _reflect_signature(_DummyFetcher().simple)
    assert all(p["name"] != "self" for p in sig)


def test_required_param_has_default_null():
    sig = _reflect_signature(_DummyFetcher().simple)
    code = next(p for p in sig if p["name"] == "code")
    assert code["required"] is True
    assert code["default"] is None
    assert code["type"] == "string"


def test_optional_param_keeps_default():
    sig = _reflect_signature(_DummyFetcher().simple)
    period = next(p for p in sig if p["name"] == "period")
    assert period["required"] is False
    assert period["default"] == "d"


def test_str_or_none_is_treated_as_string():
    sig = _reflect_signature(_DummyFetcher().with_optional)
    start = next(p for p in sig if p["name"] == "start")
    assert start["type"] == "string"
    assert start["required"] is False
    assert start["default"] is None


def test_int_and_bool_types_render():
    sig = _reflect_signature(_DummyFetcher().with_int_and_bool)
    limit = next(p for p in sig if p["name"] == "limit")
    force = next(p for p in sig if p["name"] == "force")
    assert limit["type"] == "int"
    assert limit["default"] == 30
    assert force["type"] == "bool"
    assert force["default"] is False


def test_unannotated_falls_back_to_string():
    sig = _reflect_signature(_DummyFetcher().no_annotations)
    code = next(p for p in sig if p["name"] == "code")
    # Annotation is Parameter.empty → falls back to "string"
    assert code["type"] == "string"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_manifest_signature.py -v`
Expected: FAIL with `ImportError: cannot import name '_reflect_signature' from 'stock_data.explorer.manifest'`

- [ ] **Step 3: Implement `_reflect_signature` in manifest.py**

Edit `stock_data/explorer/manifest.py`. Add a new import at the top:

```python
import inspect
```

Add the helper after the existing `_python_type_to_str` function (around line 120, before `_build_meta`):

```python
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
        out.append({
            "name": name,
            "type": type_str,
            "required": required,
            "default": default_val,
        })
    return out


def _jsonify_default(value):
    """Make a default value JSON-serializable, falling back to repr()."""
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return repr(value)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/test_manifest_signature.py -v`
Expected: PASS (6 tests)

- [ ] **Step 5: Commit**

```bash
git add stock_data/explorer/manifest.py tests/test_manifest_signature.py
git commit -m "feat(manifest): add _reflect_signature helper

Reflects fetcher method signatures into JSON-serializable list of
param dicts ({name, type, required, default}). Skips self and
*args/**kwargs. Falls back to 'string' for unannotated params and
JSON-encodes defaults (or repr() for non-JSON values).

Refs: docs/superpowers/specs/2026-06-12-explorer-fetcher-stage-design.md

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 6: `_resolve_fetchers` helper in manifest.py

**Files:**
- Modify: `stock_data/explorer/manifest.py`
- Create: `tests/test_manifest_resolve_fetchers.py`

Helper that takes an `EndpointMeta` + manager instance and returns a deduped list of fetcher entries (Approach A: merge by `(fetcher.name, method_name)`).

- [ ] **Step 1: Write the failing test**

Create `tests/test_manifest_resolve_fetchers.py`:

```python
"""Unit tests for _resolve_fetchers in explorer/manifest.py."""
from unittest.mock import MagicMock

import pytest

from stock_data.api.endpoint_meta import EndpointMeta
from stock_data.data_provider.base import BaseFetcher, DataCapability
from stock_data.explorer.manifest import _resolve_fetchers


class _FakeFetcher(BaseFetcher):
    """Minimal concrete BaseFetcher subclass for tests."""

    def __init__(self, name: str, priority: int, markets: set[str], caps: DataCapability):
        self.name = name
        self.priority = priority
        self.supported_markets = markets
        self.supported_data_types = caps

    def _fetch_raw_data(self, *a, **k):
        return None

    def _normalize_data(self, *a, **k):
        return None


def _mock_manager(fetchers):
    """Build a mock manager whose _filter_by_capability returns the right subset."""
    m = MagicMock()
    def _filter(market, cap):
        return sorted(
            [f for f in fetchers if market in f.supported_markets and cap in f.supported_data_types],
            key=lambda f: f.priority,
        )
    m._filter_by_capability.side_effect = _filter
    return m


def test_empty_capabilities_returns_empty_list():
    manager = _mock_manager([])
    meta = EndpointMeta(summary="x", markets=["csi"], capabilities=[])
    assert _resolve_fetchers(meta, manager) == []


def test_single_capability_returns_sorted_fetchers():
    fa = _FakeFetcher("alpha", priority=1, markets={"csi"}, caps=DataCapability.REALTIME_QUOTE)
    fb = _FakeFetcher("beta", priority=0, markets={"csi"}, caps=DataCapability.REALTIME_QUOTE)
    manager = _mock_manager([fa, fb])
    meta = EndpointMeta(summary="x", markets=["csi"], capabilities=["REALTIME_QUOTE"])
    result = _resolve_fetchers(meta, manager)
    assert [r["name"] for r in result] == ["beta", "alpha"]  # priority 0 first
    assert all(r["method"] == "get_realtime_quote" for r in result)


def test_multi_capability_same_method_merges_to_one_row():
    """Approach A: baostock supports DWM+MIN, both map to get_kline_data; result is ONE row."""
    f = _FakeFetcher(
        "baostock", priority=1, markets={"csi"},
        caps=DataCapability.HISTORICAL_DWM | DataCapability.HISTORICAL_MIN,
    )
    manager = _mock_manager([f])
    meta = EndpointMeta(
        summary="K线", markets=["csi"],
        capabilities=["HISTORICAL_DWM", "HISTORICAL_MIN"],
    )
    result = _resolve_fetchers(meta, manager)
    assert len(result) == 1
    assert result[0]["name"] == "baostock"
    assert result[0]["method"] == "get_kline_data"
    assert set(result[0]["capabilities"]) == {"HISTORICAL_DWM", "HISTORICAL_MIN"}


def test_fetcher_method_override_wins_over_capability_default():
    f = _FakeFetcher("eastmoney", priority=0, markets={"csi"}, caps=DataCapability.DRAGON_TIGER)
    manager = _mock_manager([f])
    meta = EndpointMeta(
        summary="龙虎榜每日", markets=["csi"],
        capabilities=["DRAGON_TIGER"],
        fetcher_method="get_daily_dragon_tiger",
    )
    result = _resolve_fetchers(meta, manager)
    assert len(result) == 1
    assert result[0]["method"] == "get_daily_dragon_tiger"  # override, not default


def test_unknown_capability_string_is_skipped():
    """Capability name that doesn't match any DataCapability enum member is silently ignored."""
    manager = _mock_manager([])
    meta = EndpointMeta(summary="x", markets=["csi"], capabilities=["NONEXISTENT_CAP"])
    assert _resolve_fetchers(meta, manager) == []


def test_signature_field_is_populated():
    """The returned entries include a signature field reflecting the method."""
    f = _FakeFetcher("alpha", priority=0, markets={"csi"}, caps=DataCapability.REALTIME_QUOTE)
    manager = _mock_manager([f])
    meta = EndpointMeta(summary="x", markets=["csi"], capabilities=["REALTIME_QUOTE"])
    result = _resolve_fetchers(meta, manager)
    sig = result[0]["signature"]
    assert isinstance(sig, list)
    # BaseFetcher.get_realtime_quote(self, stock_code) → 1 param after self
    assert any(p["name"] == "stock_code" for p in sig)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_manifest_resolve_fetchers.py -v`
Expected: FAIL with `ImportError: cannot import name '_resolve_fetchers'`

- [ ] **Step 3: Implement `_resolve_fetchers` in manifest.py**

Edit `stock_data/explorer/manifest.py`. Add this import at the top:

```python
from ..data_provider.base import CAPABILITY_TO_METHOD, DataCapability
```

Add the helper after `_reflect_signature` from Task 5:

```python
def _resolve_fetchers(meta, manager) -> list[dict]:
    """Enumerate fetchers eligible for an endpoint, deduped by (name, method).

    Returns a list of {name, method, priority, capabilities, signature} dicts
    sorted by priority ascending (matches actual failover order).
    See spec Section 4 for the full resolution rules.
    """
    if not meta.capabilities or not meta.markets:
        return []

    # (fetcher_name, method_name) → entry dict (single source of dedup)
    entries: dict[tuple[str, str], dict] = {}

    for cap_name in meta.capabilities:
        # Resolve string → enum; skip unknown gracefully (warning lives in sanity check)
        try:
            cap = DataCapability[cap_name]
        except KeyError:
            continue

        # Determine method name: override > capability default
        if meta.fetcher_method is not None:
            method_name = meta.fetcher_method
        else:
            method_name = CAPABILITY_TO_METHOD.get(cap)
            if method_name is None:
                continue  # capability has no mapped method (or is in _NO_FETCHER_METHOD)

        for market in meta.markets:
            for fetcher in manager._filter_by_capability(market, cap):
                key = (fetcher.name, method_name)
                if key in entries:
                    # Merge capability into existing entry
                    if cap_name not in entries[key]["capabilities"]:
                        entries[key]["capabilities"].append(cap_name)
                    continue
                method = getattr(fetcher, method_name, None)
                if method is None:
                    continue  # fetcher doesn't actually expose this method
                entries[key] = {
                    "name": fetcher.name,
                    "method": method_name,
                    "priority": fetcher.priority,
                    "capabilities": [cap_name],
                    "signature": _reflect_signature(method),
                }

    return sorted(entries.values(), key=lambda e: e["priority"])
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/test_manifest_resolve_fetchers.py -v`
Expected: PASS (6 tests)

- [ ] **Step 5: Commit**

```bash
git add stock_data/explorer/manifest.py tests/test_manifest_resolve_fetchers.py
git commit -m "feat(manifest): add _resolve_fetchers helper

Takes an EndpointMeta + manager and returns the deduped fetcher list
for an endpoint's (markets, capabilities). Implements Approach A
(merge by fetcher.name, method_name) and override priority
(meta.fetcher_method > CAPABILITY_TO_METHOD default).

Refs: docs/superpowers/specs/2026-06-12-explorer-fetcher-stage-design.md

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 7: Wire `fetchers` field into the manifest builder

**Files:**
- Modify: `stock_data/explorer/manifest.py`
- Modify: `tests/test_explorer_manifest_endpoint.py`

Integration step: `_build_endpoint_node` now includes a `fetchers: []` field via `_resolve_fetchers`. Verify against real routes through `TestClient`.

- [ ] **Step 1: Write the failing integration test**

Append to `tests/test_explorer_manifest_endpoint.py`:

```python
class TestManifestFetchersField:
    """Verify the new fetchers[] field on each endpoint node."""

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
        # Priority order: tushare(0), baostock(1), akshare(2), ... — at least these 3 must appear
        for name in ("tushare", "baostock", "akshare"):
            assert name in names, f"{name} missing from /stocks/.../history fetchers"

    def test_kline_baostock_merged_dwm_and_min(self):
        """Approach A: baostock supports DWM+MIN, both map to get_kline_data → ONE row with merged caps."""
        m = self._manifest()
        ep = self._endpoint(m, "GET", "/stocks/{stock_code}/history")
        baostock = next((f for f in ep["fetchers"] if f["name"] == "baostock"), None)
        assert baostock is not None
        assert set(baostock["capabilities"]) == {"HISTORICAL_DWM", "HISTORICAL_MIN"}
        assert baostock["method"] == "get_kline_data"

    def test_indicators_catalog_has_no_fetchers(self):
        m = self._manifest()
        ep = self._endpoint(m, "GET", "/indicators/catalog")
        assert ep["fetchers"] == []

    def test_dragon_tiger_daily_overrides_method(self):
        m = self._manifest()
        ep = self._endpoint(m, "GET", "/dragon-tiger/daily")
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
        assert methods == {"get_concept_board_stocks"}

    def test_signature_has_code_field_for_kline(self):
        m = self._manifest()
        ep = self._endpoint(m, "GET", "/stocks/{stock_code}/history")
        baostock = next(f for f in ep["fetchers"] if f["name"] == "baostock")
        sig = baostock["signature"]
        code_param = next((p for p in sig if p["name"] in ("code", "stock_code")), None)
        assert code_param is not None
        assert code_param["required"] is True
        assert code_param["type"] == "string"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_explorer_manifest_endpoint.py::TestManifestFetchersField -v`
Expected: FAIL — `KeyError: 'fetchers'` on the first test

- [ ] **Step 3: Integrate `fetchers` field into `_build_endpoint_node`**

Edit `stock_data/explorer/manifest.py`. Modify `build_manifest(app)` so it has access to the manager (currently it's just `(app)` and pulls from `app.routes`). Replace the function and `_build_endpoint_node` block to look like:

```python
def build_manifest(app: FastAPI) -> dict[str, Any]:
    """Return the full manifest JSON. See module docstring for shape."""
    manager = getattr(app.state, "manager", None)
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
        section["endpoints"].append(_build_endpoint_node(route, meta, manager))
    return {
        "meta": _build_meta(),
        "sections": sorted(sections_map.values(), key=_section_sort_key),
    }
```

Then update `_build_endpoint_node` to accept `manager` and include the new field:

```python
def _build_endpoint_node(route: APIRoute, meta: EndpointMeta, manager) -> dict:
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
    full_path = route.path
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_explorer_manifest_endpoint.py -v`
Expected: PASS (the new TestManifestFetchersField class + any pre-existing tests). If a pre-existing test breaks because it doesn't expect the new `fetchers` field, update it to accept the extra key.

- [ ] **Step 5: Commit**

```bash
git add stock_data/explorer/manifest.py tests/test_explorer_manifest_endpoint.py
git commit -m "feat(manifest): emit fetchers[] field on every endpoint node

build_manifest now reads app.state.manager and calls _resolve_fetchers
per endpoint to populate the new fetchers[] field. Verified against
the live FastAPI app: /stocks/.../history shows tushare+baostock+akshare,
/indicators/catalog shows [], and the 3 override endpoints
(/dragon-tiger/daily, /stocks/.../fund-flow/daily,
/boards/{board_code}/stocks) report the correct method names.

Refs: docs/superpowers/specs/2026-06-12-explorer-fetcher-stage-design.md

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 8: `POST /control/fetcher-test` endpoint

**Files:**
- Modify: `stock_data/explorer/routes.py`
- Create: `tests/test_fetcher_test_endpoint.py`

Stage 2 server-side: accept `{fetcher, method, kwargs}`, invoke directly on the fetcher (bypassing manager failover), always return HTTP 200.

- [ ] **Step 1: Write the failing test**

Create `tests/test_fetcher_test_endpoint.py`:

```python
"""Tests for POST /control/fetcher-test endpoint."""
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from stock_data.server import app


@pytest.fixture
def client():
    with TestClient(app) as c:
        c.get("/control/server/status")  # trigger lifespan
        yield c


def _post(client, body: dict):
    return client.post("/control/fetcher-test", json=body)


def test_happy_path_returns_ok_true(client):
    fake = MagicMock()
    fake.is_available.return_value = True
    fake.get_realtime_quote.return_value = {"price": 100.0}
    with patch.object(app.state.manager, "get_fetcher", return_value=fake):
        r = _post(client, {"fetcher": "baostock", "method": "get_realtime_quote",
                           "kwargs": {"stock_code": "600519"}})
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["fetcher"] == "baostock"
    assert body["method"] == "get_realtime_quote"
    assert body["result"] == {"price": 100.0}
    assert body["error"] is None
    assert isinstance(body["elapsed_ms"], int)
    assert body["elapsed_ms"] >= 0


def test_unknown_fetcher_returns_ok_false_http_200(client):
    with patch.object(app.state.manager, "get_fetcher", return_value=None):
        r = _post(client, {"fetcher": "ghost", "method": "get_realtime_quote",
                           "kwargs": {"stock_code": "600519"}})
    assert r.status_code == 200  # always 200
    body = r.json()
    assert body["ok"] is False
    assert body["error"]["type"] == "UnknownFetcher"
    assert "ghost" in body["error"]["message"]


def test_unknown_method_returns_ok_false_http_200(client):
    fake = MagicMock()
    with patch.object(app.state.manager, "get_fetcher", return_value=fake):
        r = _post(client, {"fetcher": "baostock", "method": "__init__",
                           "kwargs": {}})
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is False
    assert body["error"]["type"] == "UnknownMethod"


def test_fetcher_unavailable_returns_ok_false(client):
    fake = MagicMock()
    fake.is_available.return_value = False
    with patch.object(app.state.manager, "get_fetcher", return_value=fake):
        r = _post(client, {"fetcher": "baostock", "method": "get_realtime_quote",
                           "kwargs": {"stock_code": "600519"}})
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is False
    assert body["error"]["type"] == "FetcherUnavailable"


def test_missing_kwarg_returns_type_error(client):
    fake = MagicMock()
    fake.is_available.return_value = True
    fake.get_realtime_quote.side_effect = TypeError(
        "get_realtime_quote() missing 1 required positional argument: 'stock_code'"
    )
    with patch.object(app.state.manager, "get_fetcher", return_value=fake):
        r = _post(client, {"fetcher": "baostock", "method": "get_realtime_quote", "kwargs": {}})
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is False
    assert body["error"]["type"] == "TypeError"


def test_fetcher_exception_returns_class_name_with_traceback(client):
    fake = MagicMock()
    fake.is_available.return_value = True
    from stock_data.data_provider.base import DataFetchError
    fake.get_realtime_quote.side_effect = DataFetchError("BaoStock login failed")
    with patch.object(app.state.manager, "get_fetcher", return_value=fake):
        r = _post(client, {"fetcher": "baostock", "method": "get_realtime_quote",
                           "kwargs": {"stock_code": "600519"}})
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is False
    assert body["error"]["type"] == "DataFetchError"
    assert "BaoStock login failed" in body["error"]["message"]
    assert body["error"]["traceback"]  # non-empty


def test_missing_body_field_returns_422(client):
    """Pydantic validation kicks in for missing required body fields."""
    r = _post(client, {"fetcher": "baostock"})  # missing method, kwargs
    assert r.status_code == 422
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_fetcher_test_endpoint.py -v`
Expected: FAIL with `404 Not Found` (endpoint doesn't exist yet) for all happy/error tests

- [ ] **Step 3: Implement `POST /control/fetcher-test` in explorer/routes.py**

Edit `stock_data/explorer/routes.py`. Add these imports near the top:

```python
import time
import traceback as _traceback
from pydantic import BaseModel, Field

from ..data_provider.base import CAPABILITY_TO_METHOD
```

Inside `build_control_router()`, add a Pydantic request model and the endpoint (after the `/api-manifest` endpoint, before `return router`):

```python
    class _FetcherTestRequest(BaseModel):
        fetcher: str = Field(..., description="Fetcher name (e.g. 'baostock')")
        method: str = Field(..., description="Method name on the fetcher")
        kwargs: dict = Field(default_factory=dict, description="kwargs unpacked into the method call")

    @router.post("/fetcher-test")
    def control_fetcher_test(req: _FetcherTestRequest, request: Request) -> dict:
        """Invoke a single fetcher method directly, bypassing manager failover.

        Always returns HTTP 200; success/failure is encoded in the body's
        `ok` field. See spec Section 5 for the error classification.
        """
        manager = request.app.state.manager
        # Whitelist comes from CAPABILITY_TO_METHOD values PLUS any
        # endpoint-declared override. Build once per request from manifest.
        # (We re-import here to avoid a circular import at module load.)
        from .manifest import build_manifest
        manifest = build_manifest(request.app)
        allowed_methods = {
            f["method"]
            for sec in manifest["sections"]
            for ep in sec["endpoints"]
            for f in ep["fetchers"]
        }

        def _err(type_: str, message: str, *, with_tb: bool = False) -> dict:
            return {
                "ok": False,
                "fetcher": req.fetcher,
                "method": req.method,
                "elapsed_ms": 0,
                "result": None,
                "error": {
                    "type": type_,
                    "message": message,
                    "traceback": _traceback.format_exc() if with_tb else "",
                },
            }

        # 1. Unknown fetcher
        fetcher = manager.get_fetcher(req.fetcher)
        if fetcher is None:
            loaded = sorted(f.name for f in manager._fetchers)
            return _err(
                "UnknownFetcher",
                f"no fetcher named '{req.fetcher}'; loaded: {loaded}",
            )

        # 2. Unknown method (not in whitelist)
        if req.method not in allowed_methods:
            return _err(
                "UnknownMethod",
                f"method '{req.method}' not allowed; allowed: {sorted(allowed_methods)}",
            )

        # 3. Fetcher unavailable
        if hasattr(fetcher, "is_available") and not fetcher.is_available():
            return _err(
                "FetcherUnavailable",
                f"{req.fetcher}.is_available() returned False (check token / SDK install)",
            )

        # 4. Invoke the method, classify exceptions
        method = getattr(fetcher, req.method, None)
        if method is None:
            return _err(
                "UnknownMethod",
                f"fetcher {req.fetcher} has no attribute '{req.method}'",
            )
        start = time.monotonic()
        try:
            result = method(**req.kwargs)
        except TypeError as e:
            elapsed_ms = int((time.monotonic() - start) * 1000)
            return {
                "ok": False, "fetcher": req.fetcher, "method": req.method,
                "elapsed_ms": elapsed_ms, "result": None,
                "error": {"type": "TypeError", "message": str(e),
                          "traceback": _traceback.format_exc()},
            }
        except Exception as e:
            elapsed_ms = int((time.monotonic() - start) * 1000)
            return {
                "ok": False, "fetcher": req.fetcher, "method": req.method,
                "elapsed_ms": elapsed_ms, "result": None,
                "error": {"type": type(e).__name__, "message": str(e),
                          "traceback": _traceback.format_exc()},
            }
        elapsed_ms = int((time.monotonic() - start) * 1000)
        return {
            "ok": True,
            "fetcher": req.fetcher,
            "method": req.method,
            "elapsed_ms": elapsed_ms,
            "result": _json_safe(result),
            "error": None,
        }


def _json_safe(value):
    """Best-effort JSON-safe coercion for fetcher return values."""
    import pandas as pd
    if isinstance(value, pd.DataFrame):
        return value.to_dict(orient="records")
    if hasattr(value, "to_dict"):
        try:
            return value.to_dict()
        except Exception:
            pass
    if isinstance(value, (list, tuple)):
        return [_json_safe(v) for v in value]
    if isinstance(value, dict):
        return {k: _json_safe(v) for k, v in value.items()}
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return repr(value)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_fetcher_test_endpoint.py -v`
Expected: PASS (7 tests)

- [ ] **Step 5: Commit**

```bash
git add stock_data/explorer/routes.py tests/test_fetcher_test_endpoint.py
git commit -m "feat(control): add POST /control/fetcher-test for Stage 2 single-fetcher tests

Accepts {fetcher, method, kwargs} and invokes the named method directly
on the fetcher instance, bypassing manager failover. Always returns
HTTP 200; success/failure encoded in body's 'ok' field. Errors are
classified into UnknownFetcher / UnknownMethod / FetcherUnavailable /
TypeError / <ExceptionClassName>, each with optional traceback for
debugging (127.0.0.1-only endpoint, no leak risk).

Method whitelist derives from the manifest (CAPABILITY_TO_METHOD
values + endpoint-declared overrides) — adding a new capability or
override automatically extends the whitelist.

Refs: docs/superpowers/specs/2026-06-12-explorer-fetcher-stage-design.md

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 9: Extend startup sanity check in `explorer/__init__.py`

**Files:**
- Modify: `stock_data/explorer/__init__.py`

Add warnings for: methods declared in `CAPABILITY_TO_METHOD` that don't exist on `BaseFetcher`; `DataCapability` flags that are neither in the map nor in `_NO_FETCHER_METHOD`; `@endpoint_meta(fetcher_method=...)` referring to a method that doesn't exist.

- [ ] **Step 1: Read current sanity check code**

Run: `cat E:/GitRepo/stock_data/stock_data/explorer/__init__.py`

Locate `_validate_manifest_invariants()`. We'll add new warnings to that function.

- [ ] **Step 2: Add new warnings**

Edit `stock_data/explorer/__init__.py`. Add these imports at the top (if not already present):

```python
from ..data_provider.base import (
    BaseFetcher,
    CAPABILITY_TO_METHOD,
    DataCapability,
    _NO_FETCHER_METHOD,
)
from ..api.endpoint_meta import REGISTRY
```

Inside `_validate_manifest_invariants` (or create the function if it doesn't exist yet), append:

```python
    # ----- CAPABILITY_TO_METHOD invariants -----
    for cap, method_name in CAPABILITY_TO_METHOD.items():
        if not hasattr(BaseFetcher, method_name):
            logger.warning(
                f"[explorer/sanity] CAPABILITY_TO_METHOD[{cap.name}] = "
                f"{method_name!r} but BaseFetcher has no such attribute. "
                f"Manifest will silently skip this capability."
            )

    for cap in DataCapability:
        if cap not in CAPABILITY_TO_METHOD and cap not in _NO_FETCHER_METHOD:
            logger.warning(
                f"[explorer/sanity] DataCapability.{cap.name} is neither in "
                f"CAPABILITY_TO_METHOD nor in _NO_FETCHER_METHOD. Add it to one "
                f"of them to declare intent."
            )

    # ----- @endpoint_meta(fetcher_method=...) sanity -----
    for func, meta in REGISTRY.items():
        if meta.fetcher_method is not None and not hasattr(BaseFetcher, meta.fetcher_method):
            logger.warning(
                f"[explorer/sanity] {func.__qualname__} declares "
                f"fetcher_method={meta.fetcher_method!r}, but BaseFetcher has "
                f"no such attribute. Stage 2 testing for this endpoint will fail."
            )
```

- [ ] **Step 3: Run server to verify no spurious warnings**

Run: `.venv/Scripts/python.exe -m stock_data.server`

Watch the startup logs. Expected: no new `[explorer/sanity]` warnings (since Tasks 1–3 have already kept the invariants satisfied). If warnings appear, fix whatever the warning describes before proceeding.

Then `Ctrl+C` to stop.

- [ ] **Step 4: Smoke-check with a deliberately-broken state**

Temporarily edit `stock_data/data_provider/base.py` and change one entry in `CAPABILITY_TO_METHOD` to a typo (e.g. `DataCapability.HISTORICAL_DWM: "get_kline_dataXXX"`). Restart the server.

Expected: a `[explorer/sanity]` warning line appears in startup logs naming the typo.

Revert the typo before committing.

- [ ] **Step 5: Commit**

```bash
git add stock_data/explorer/__init__.py
git commit -m "feat(explorer): extend startup sanity checks for fetcher map

Warns at server startup if:
- CAPABILITY_TO_METHOD references a method missing from BaseFetcher
- A DataCapability flag is in neither CAPABILITY_TO_METHOD nor
  _NO_FETCHER_METHOD (intent not declared)
- An endpoint's @endpoint_meta(fetcher_method=...) references a
  method missing from BaseFetcher

These are warnings (not errors) so a broken capability doesn't
prevent the server from booting — but the misconfiguration is loud.

Refs: docs/superpowers/specs/2026-06-12-explorer-fetcher-stage-design.md

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 10: HTML Stage 1 — Fetcher backends collapsible section

**Files:**
- Modify: `stock_data/explorer/static/index.html`

Pure UI: render a `<details>` block under each endpoint card listing the fetchers from manifest, with priority badges and capability chips. No Stage 2 interactivity yet — that's Task 11.

- [ ] **Step 1: Read the existing endpoint card render function**

Run: `grep -n "renderEndpoint\|endpoint-card" E:/GitRepo/stock_data/stock_data/explorer/static/index.html | head -20`

Find the function that renders one endpoint card (likely `renderEndpoint(ep)`). Read the section around it (~50 lines context) to understand the existing markup pattern, chip classes, and where to insert.

- [ ] **Step 2: Add CSS for fetcher backends section**

Edit `stock_data/explorer/static/index.html`. In the `<style>` block, append after the existing chip / card / form rules:

```css
    /* === Fetcher backends section (Stage 1) === */
    .fetcher-backends { margin-top: 16px; }
    .fetcher-backends > summary {
      cursor: pointer; user-select: none;
      padding: 6px 10px; font-size: 13px; font-weight: 500;
      color: var(--text-muted); border-radius: 6px;
      list-style: none;
    }
    .fetcher-backends > summary::-webkit-details-marker { display: none; }
    .fetcher-backends > summary:hover { background: var(--bg-sidebar); }
    .fetcher-backends > summary::before {
      content: "▶"; display: inline-block;
      width: 14px; transition: transform 0.15s;
    }
    .fetcher-backends[open] > summary::before { transform: rotate(90deg); }
    .fetcher-list {
      margin-top: 8px; border: 1px solid var(--border);
      border-radius: 8px; overflow: hidden;
    }
    .fetcher-row {
      display: grid;
      grid-template-columns: 50px 1fr auto;
      gap: 12px; align-items: start;
      padding: 10px 14px; border-bottom: 1px solid var(--border);
    }
    .fetcher-row:last-child { border-bottom: 0; }
    .fetcher-priority {
      display: inline-block; padding: 2px 8px;
      background: #888; color: #fff;
      border-radius: 4px; font: 11px monospace; font-weight: 600;
    }
    .fetcher-body { min-width: 0; }
    .fetcher-name { font-weight: 600; font-size: 14px; }
    .fetcher-method {
      font-family: monospace; font-size: 12px;
      color: var(--text-muted); margin-top: 2px; word-break: break-all;
    }
    .fetcher-caps { margin-top: 6px; display: flex; gap: 4px; flex-wrap: wrap; }
    .fetcher-test-btn {
      font: 12px inherit; padding: 4px 10px;
      border: 1px solid var(--border); border-radius: 6px;
      background: var(--bg); color: var(--text); cursor: pointer;
    }
    .fetcher-test-btn:hover { background: var(--accent); color: #fff; border-color: var(--accent); }
```

- [ ] **Step 3: Add render helper for one fetcher row**

In the `<script>` block, add a new helper near other render helpers:

```js
    function renderFetcherRow(f) {
      const sigArgs = f.signature.map(p => p.name).join(", ");
      const capChips = f.capabilities
        .map(c => `<span class="chip cap-chip">${escapeHTML(c)}</span>`)
        .join("");
      return `
        <div class="fetcher-row" data-fetcher="${escapeHTML(f.name)}"
             data-method="${escapeHTML(f.method)}"
             title="${escapeHTML(f.method)}(${escapeHTML(sigArgs)})">
          <span class="fetcher-priority">P${f.priority}</span>
          <div class="fetcher-body">
            <div class="fetcher-name">${escapeHTML(f.name)}</div>
            <div class="fetcher-method">.${escapeHTML(f.method)}(${escapeHTML(sigArgs)})</div>
            <div class="fetcher-caps">${capChips}</div>
          </div>
          <button class="fetcher-test-btn" type="button">Test</button>
        </div>
      `;
    }

    function renderFetcherBackends(ep) {
      if (!ep.fetchers || ep.fetchers.length === 0) return "";
      const rows = ep.fetchers.map(renderFetcherRow).join("");
      return `
        <details class="fetcher-backends">
          <summary>Fetcher backends (${ep.fetchers.length})</summary>
          <div class="fetcher-list">${rows}</div>
        </details>
      `;
    }
```

If `escapeHTML` doesn't exist yet, add it next to other utility functions:

```js
    function escapeHTML(s) {
      if (s == null) return "";
      return String(s).replace(/[&<>"']/g, c => ({
        "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
      }[c]));
    }
```

- [ ] **Step 4: Wire the helper into `renderEndpoint`**

Find the function that renders an endpoint card. Inside it, where it composes the inner HTML, append `${renderFetcherBackends(ep)}` to the bottom of the card content (after the Try-it section).

For example, if the current render is:

```js
    function renderEndpoint(ep) {
      return `
        <div class="endpoint" id="${ep.id}">
          ... existing header / params / try-it ...
        </div>
      `;
    }
```

Modify to:

```js
    function renderEndpoint(ep) {
      return `
        <div class="endpoint" id="${ep.id}">
          ... existing header / params / try-it ...
          ${renderFetcherBackends(ep)}
        </div>
      `;
    }
```

- [ ] **Step 5: Manual smoke test**

Start server: `.venv/Scripts/python.exe -m stock_data.server`

Open `http://localhost:8888/explorer/`. Verify:
- Each endpoint card now has a `▶ Fetcher backends (N)` collapse below the Try-it button (where N > 0)
- `/indicators/catalog` does NOT have this collapse (because `fetchers: []`)
- Clicking the collapse expands a list of fetcher rows showing `[P0] tushare .get_kline_data(code, period, ...)` etc.
- The Test button doesn't do anything yet (Task 11 wires it)

Ctrl+C to stop.

- [ ] **Step 6: Commit**

```bash
git add stock_data/explorer/static/index.html
git commit -m "feat(explorer/ui): Stage 1 Fetcher backends collapsible section

Each endpoint card now has a <details>-based collapsible section
listing the fetchers that serve it, with priority badge, method
signature, and capability chips. Endpoints with no eligible fetcher
(e.g. /indicators/catalog) skip the section entirely.

Test buttons are present but inert; Stage 2 wires them in the next
commit.

Refs: docs/superpowers/specs/2026-06-12-explorer-fetcher-stage-design.md

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 11: HTML Stage 2 — Test button mini-form + Run flow

**Files:**
- Modify: `stock_data/explorer/static/index.html`

Click Test → reveal inline form pre-filled from manifest signature and (best-effort) from the endpoint's Try-it form; click Run → POST `/control/fetcher-test`; render result in the existing result panel.

- [ ] **Step 1: Add CSS for the mini-form**

Add to the `<style>` block (after the Fetcher backends rules from Task 10):

```css
    /* === Fetcher mini-form (Stage 2) === */
    .fetcher-miniform {
      grid-column: 1 / -1;
      margin-top: 8px; padding: 12px;
      background: var(--bg-sidebar); border-radius: 6px;
    }
    .fetcher-miniform[hidden] { display: none; }
    .fetcher-miniform h4 {
      margin: 0 0 8px; font-size: 13px;
      font-family: monospace; color: var(--text);
    }
    .fetcher-miniform .field {
      display: grid; grid-template-columns: 100px 1fr;
      gap: 8px; align-items: center; margin-bottom: 6px;
    }
    .fetcher-miniform label { font-size: 12px; color: var(--text-muted); }
    .fetcher-miniform input {
      font: inherit; padding: 4px 8px;
      border: 1px solid var(--border); border-radius: 4px;
      background: var(--bg); color: var(--text);
    }
    .fetcher-miniform .actions {
      margin-top: 8px; display: flex; gap: 8px;
    }
    .fetcher-miniform .actions button {
      font: inherit; padding: 4px 12px; cursor: pointer;
      border: 1px solid var(--border); border-radius: 6px;
      background: var(--bg); color: var(--text);
    }
    .fetcher-miniform .actions button.primary {
      background: var(--accent); color: #fff; border-color: var(--accent);
    }
```

- [ ] **Step 2: Render the mini-form (hidden) inside each fetcher-row**

In `renderFetcherRow(f)`, just after the existing `.fetcher-row` div but inside it (or as a sibling immediately following), add the hidden mini-form. Update the helper to:

```js
    function renderFetcherRow(f) {
      const sigArgs = f.signature.map(p => p.name).join(", ");
      const capChips = f.capabilities
        .map(c => `<span class="chip cap-chip">${escapeHTML(c)}</span>`)
        .join("");
      const fields = f.signature.map(p => `
        <div class="field">
          <label>${escapeHTML(p.name)}${p.required ? " *" : ""}:</label>
          <input type="text" data-param="${escapeHTML(p.name)}"
                 value="${escapeHTML(p.default ?? '')}"
                 placeholder="${p.required ? 'required' : 'optional'}">
        </div>
      `).join("");
      return `
        <div class="fetcher-row" data-fetcher="${escapeHTML(f.name)}"
             data-method="${escapeHTML(f.method)}"
             title="${escapeHTML(f.method)}(${escapeHTML(sigArgs)})">
          <span class="fetcher-priority">P${f.priority}</span>
          <div class="fetcher-body">
            <div class="fetcher-name">${escapeHTML(f.name)}</div>
            <div class="fetcher-method">.${escapeHTML(f.method)}(${escapeHTML(sigArgs)})</div>
            <div class="fetcher-caps">${capChips}</div>
          </div>
          <button class="fetcher-test-btn" type="button">Test</button>
          <div class="fetcher-miniform" hidden>
            <h4>Direct call: ${escapeHTML(f.name)}.${escapeHTML(f.method)}</h4>
            ${fields}
            <div class="actions">
              <button type="button" class="primary fetcher-run-btn">Run</button>
              <button type="button" class="fetcher-cancel-btn">Cancel</button>
            </div>
          </div>
        </div>
      `;
    }
```

- [ ] **Step 3: Add event wiring (Test / Run / Cancel)**

In the script block, add (after `renderFetcherBackends` or at the top of an existing global init function):

```js
    // Stage 2 event delegation: handle Test/Run/Cancel inside any endpoint card.
    document.addEventListener("click", (ev) => {
      const target = ev.target;

      // Test button → reveal mini-form + prefill from endpoint Try-it inputs
      if (target.classList.contains("fetcher-test-btn")) {
        const row = target.closest(".fetcher-row");
        const mini = row.querySelector(".fetcher-miniform");
        if (mini.hidden) {
          prefillMiniFormFromTryIt(row, mini);
          mini.hidden = false;
        } else {
          mini.hidden = true;
        }
        return;
      }

      // Cancel button → hide mini-form
      if (target.classList.contains("fetcher-cancel-btn")) {
        const mini = target.closest(".fetcher-miniform");
        mini.hidden = true;
        return;
      }

      // Run button → POST /control/fetcher-test
      if (target.classList.contains("fetcher-run-btn")) {
        const mini = target.closest(".fetcher-miniform");
        const row = mini.closest(".fetcher-row");
        runFetcherTest(row, mini);
        return;
      }
    });

    function prefillMiniFormFromTryIt(row, mini) {
      // Find the endpoint card containing this row; scrape its Try-it inputs.
      const card = row.closest(".endpoint");
      if (!card) return;
      const tryitInputs = card.querySelectorAll(".tryit-form input[name], .tryit-form input[data-param]");
      const lookup = {};
      tryitInputs.forEach(inp => {
        const k = inp.name || inp.dataset.param;
        if (k && inp.value) lookup[k] = inp.value;
      });
      mini.querySelectorAll("input[data-param]").forEach(inp => {
        const k = inp.dataset.param;
        if (lookup[k] != null && !inp.value) inp.value = lookup[k];
      });
    }

    async function runFetcherTest(row, mini) {
      const fetcherName = row.dataset.fetcher;
      const method = row.dataset.method;
      const kwargs = {};
      mini.querySelectorAll("input[data-param]").forEach(inp => {
        if (inp.value !== "") kwargs[inp.dataset.param] = inp.value;
      });
      // Render "loading" into the result panel using existing helper.
      renderResultLoading(`Direct fetcher · ${fetcherName}.${method}`);
      try {
        const resp = await fetch("/control/fetcher-test", {
          method: "POST",
          headers: {"Content-Type": "application/json"},
          body: JSON.stringify({fetcher: fetcherName, method, kwargs}),
        });
        const body = await resp.json();
        if (resp.status !== 200) {
          renderResultError(`HTTP ${resp.status}`, JSON.stringify(body, null, 2));
          return;
        }
        if (!body.ok) {
          renderResultError(
            `${body.error.type}: ${body.error.message}`,
            body.error.traceback || ""
          );
          return;
        }
        renderResultSuccess(
          `Direct fetcher · ${fetcherName}.${method} · ${body.elapsed_ms}ms`,
          JSON.stringify(body.result, null, 2)
        );
      } catch (e) {
        renderResultError("Network error", String(e));
      }
    }
```

If `renderResultLoading`/`renderResultError`/`renderResultSuccess` do not already exist with these exact names, find the existing helpers used by the Try-it flow (search for `result-panel-body`) and either reuse their names directly or add thin wrappers that produce the same output. **Do not invent new DOM structure for the result panel** — it must reuse the existing one.

- [ ] **Step 4: Manual smoke test**

Start server: `.venv/Scripts/python.exe -m stock_data.server`

Open `http://localhost:8888/explorer/`. Verify:
1. Expand Fetcher backends on `/stocks/{stock_code}/quote`
2. Click Test on any fetcher row → mini-form appears with the method's params
3. Code field is pre-filled if you already filled the Try-it form's `stock_code`
4. Click Run with a valid kwarg (e.g. `stock_code=600519`) → result appears in the right panel labeled `Direct fetcher · baostock.get_realtime_quote · NNNms`
5. Click Test on a different fetcher in the same row, change `stock_code` to empty, click Run → result panel shows error type + traceback (e.g. `TypeError: missing required argument`)
6. Click Cancel on an expanded mini-form → it collapses
7. Try `/indicators/catalog` — confirm no Fetcher backends section at all

Ctrl+C to stop.

- [ ] **Step 5: Commit**

```bash
git add stock_data/explorer/static/index.html
git commit -m "feat(explorer/ui): Stage 2 Test button → mini-form → /control/fetcher-test

Clicking Test reveals an inline mini-form whose fields come from the
manifest signature for that fetcher method. Path/query values from
the endpoint's Try-it form prefill same-named fields (best-effort).
Run posts to /control/fetcher-test and renders result/error into the
existing right-side result panel with a 'Direct fetcher · ...' label.

Reuses the existing renderResult helpers — no new DOM panel.

Refs: docs/superpowers/specs/2026-06-12-explorer-fetcher-stage-design.md

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 12: Update CLAUDE.md

**Files:**
- Modify: `CLAUDE.md`

Document the new manifest field, the `fetcher_method` override mechanism, the 3 override endpoints, and the new `/control/fetcher-test` endpoint.

- [ ] **Step 1: Add a new section after the existing "Source Tracking" section**

Edit `CLAUDE.md`. Find the "## Source Tracking" section. Insert a new top-level section right after it:

```markdown
## Stage 1/2 Fetcher Drill-down (Explorer)

The `/explorer/` UI shows, under each endpoint card, a collapsible
"Fetcher backends" section listing every fetcher that can serve the
endpoint along with its internal method signature. Each row has a
`Test` button that opens an inline form posting to `POST /control/fetcher-test`
to invoke the fetcher method directly (bypassing manager failover).

### Data flow

1. `GET /control/api-manifest` returns endpoints with a new `fetchers[]`
   field. Each entry is `{name, method, priority, capabilities, signature}`.
2. The manifest builder uses `data_provider.base.CAPABILITY_TO_METHOD`
   (and `EndpointMeta.fetcher_method` override) to figure out the right
   method per fetcher.
3. HTML renders the rows under a `<details>`-based collapse.
4. Clicking Test → POST `/control/fetcher-test` body
   `{fetcher, method, kwargs}` → **always HTTP 200**; success/failure in
   the body's `ok` field. Errors classified as
   `UnknownFetcher / UnknownMethod / FetcherUnavailable / TypeError / <ExceptionName>`,
   each with optional traceback.

### `fetcher_method` overrides (3 known)

`@endpoint_meta(fetcher_method=...)` pins the method when the capability's
default isn't right:

| Endpoint | Capability | Override method |
|----------|------------|-----------------|
| `/boards/{board_code}/stocks` | `STOCK_BOARD` | `get_concept_board_stocks` |
| `/dragon-tiger/daily` | `DRAGON_TIGER` | `get_daily_dragon_tiger` |
| `/stocks/{stock_code}/fund-flow/daily` | `FUND_FLOW` | `get_fund_flow_120d` |

**`/boards` (single endpoint, `?type=concept|industry` dispatch) Stage 2
tests the concept variant by default**; industry variant is not exposed
in the UI (the user can change the method name in the mini-form manually).

### Anti-patterns

- **Don't** add a `DataCapability` without putting it in either
  `CAPABILITY_TO_METHOD` or `_NO_FETCHER_METHOD`. Both startup sanity
  checks and `tests/test_capability_method_map.py` will refuse silently.
- **Don't** assume Stage 2 result is "production-equivalent" — it bypasses
  the manager's circuit breaker and the capability filter.
- **Don't** rely on `/control/fetcher-test` from external networks — it's
  127.0.0.1-only via the control router.
```

- [ ] **Step 2: Update the manifest schema reference**

Find the section that documents the manifest endpoint shape (search for `api-manifest` or `EndpointMeta`). Update the JSON example to include the new `fetchers[]` field, mirroring spec Section 4.

- [ ] **Step 3: Commit**

```bash
git add CLAUDE.md
git commit -m "docs(CLAUDE): document Stage 1/2 Fetcher Drill-down

Adds a top-level section explaining the new fetchers[] manifest field,
the @endpoint_meta(fetcher_method=...) override mechanism with the
3 known overrides, and the POST /control/fetcher-test endpoint
contract. Updates the manifest schema example to show fetchers[].

Refs: docs/superpowers/specs/2026-06-12-explorer-fetcher-stage-design.md

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Final Verification Checklist

- [ ] Run all tests: `.venv/Scripts/python.exe -m pytest -v`
      Expected: all PASS, no skipped due to import errors.

- [ ] Run lint: `ruff check .`
      Expected: no new warnings/errors.

- [ ] Boot the server: `.venv/Scripts/python.exe -m stock_data.server`
      Expected: no new `[explorer/sanity]` warnings in startup logs.

- [ ] Open `http://localhost:8888/explorer/` and run the **manual smoke checklist** from spec Section 7.5:
    1. Sidebar loads normally.
    2. Click 3 different endpoints, expand Fetcher backends each — see fetcher list.
    3. Click `/indicators/catalog` — verify NO Fetcher backends button.
    4. Click Test on a fetcher row of `/stocks/{stock_code}/quote` → mini-form opens → Run → result in right panel.
    5. Fill `stock_code` as empty (or omit), Run → see red error.type + traceback.

- [ ] Final commit of any stray fixes from the smoke test, then stop.
