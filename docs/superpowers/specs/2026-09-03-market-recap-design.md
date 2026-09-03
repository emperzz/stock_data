# `GET /api/v1/agent/market-recap` — Server-Side Aggregation of Market-Context + Market-Stats + Index Quotes

> Spec for a new aggregation endpoint that reuses the existing
> `market-context` and `market-stats` data builders and adds a 3-index
> quote block (上证 / 深成指 / 创业板). Designed for LLM agents that
> want a single round-trip recap with minimal token cost.

**Date**: 2026-09-03
**Status**: Draft (post-brainstorm)
**Scope**: 1 new route handler + 1 new Pydantic schema + 1 new MD
renderer + 1 cache key + tests. **No new fetcher, no new
`DataCapability` flag, no new manager method.** Reuses existing
`market-context` and `market-stats` logic by extracting their inner
data builders into module-level functions; handlers continue to call
the builders and remain behavior-identical.

---

## 1. Background

The agent `/api/v1/agent/*` family today offers two panorama
endpoints:

- `GET /agent/market-context` — Cls morning briefing + market recap +
  flash news
- `GET /agent/market-stats` — full-market stocks / boards distribution
  + zt/dt limit pools

LLM agents building an end-of-day recap narrative currently have to
make **both** calls, plus a third call to `/indices/{code}/quote` (or
`/agent/indices/batch-profile`) for **大盘方向 + 成长 vs 价值分裂**
context. That direction signal is the one piece of market-state
information the existing two endpoints do not cover.

`market-recap` is the minimal server-side aggregation that fills that
gap.

**Why not just call from the agent side**: every additional
round-trip is per-agent latency + N upstream fan-outs the server
could have collapsed into one. Reuse means the server-side cache
layers (`make_market_context_cache_key`,
`make_market_stats_cache_key`, plus a new key for the 3-index block)
absorb repeated calls within 60s.

**Why not just call `indices/batch-profile`**: that endpoint's
`BatchFeatures` block (trend MA/RSI/BOLL, pivots, z_anomalies) is
**~7× the token cost** of `IndexQuote` per index, and is **redundant
with the narrative already in `market-context.messages.market_recap`**
(ClsFetcher's recap is itself a synthesis of recent index action).
`batch-profile` describes the past 60 days; `market-recap` is asking
about today's session.

**Non-goals**:
- ❌ HK / US indices (csi only)
- ❌ `?include_trend=true` opt-in flag (deferred; user confirmed ship
  A only)
- ❌ configurable index list (3 indices are fixed at v1: 上证 /
  深成指 / 创业板)
- ❌ deep refactor of `market-context` / `market-stats` handlers
  (extract data builder only; decorator chain stays the same)

---

## 2. Public API

### 2.1 `GET /api/v1/agent/market-recap`

```jsonc
{
  "context":  { /* full MarketContextResponse (verbatim) */ },
  "stats":    { /* full MarketStatsResponse  (verbatim) */ },
  "indices": {
    "sh":                  { /* IndexQuote | null */ },   // 上证综指 000001
    "shenzhen_composite":  { /* IndexQuote | null */ },   // 深证成指 399001
    "chinext":             { /* IndexQuote | null */ }    // 创业板指 399006
  },
  "errors": [
    { "block": "context",           "error": "...", "message": "..." },
    { "block": "stats",             "error": "...", "message": "..." },
    { "block": "indices.sh",        "error": "...", "message": "..." },
    { "block": "indices.shenzhen_composite", "error": "...", "message": "..." },
    { "block": "indices.chinext",   "error": "...", "message": "..." }
  ],
  "summary": { "requested": 5, "ok": 5, "failed": 0, "elapsed_ms": 320 }
}
```

**Query params**:

| Field | Type | Default | Plumbed to |
|---|---|---|---|
| `flash_limit` | `int` (1-200) | 20 | `build_market_context_response` |
| `include_boards` | `bool` | True | `build_market_stats_response` |
| `include_pools` | `bool` | True | `build_market_stats_response` |
| `trade_date` | `str \| None` (YYYY-MM-DD) | server-defaulted to latest trade date on/before today | both builders |
| `format` | `Literal["json","md"]` | `"json"` | route-level JSON vs MD dispatch |

**`errors[].block` literals**: `"context"`, `"stats"`,
`"indices.sh"`, `"indices.shenzhen_composite"`, `"indices.chinext"`.
A failure inside `context` or `stats` does NOT recursively surface
their own `errors[]` — only the top-level recap-level entry. (Sub-block
errors stay nested in `context.errors` / `stats.errors` for
debuggability; the top-level `errors[]` is the *recap's* view.)

**Status codes**: 200 on partial success (per-block isolation).
400 on invalid `trade_date`. 422 on invalid `format`. 500 on
catastrophic (route handler itself raises).

### 2.2 What "verbatim" means for `context` / `stats`

The `context` block is the exact `MarketContextResponse` the
`/agent/market-context` route would return — same shape, same field
defaults, same `summary.requested/ok/failed/elapsed_ms`. The `stats`
block is the exact `MarketStatsResponse` `/agent/market-stats` would
return. We embed these models directly via Pydantic composition, not
via re-modeling them. **No field is renamed, dropped, or wrapped.**

This guarantees: an agent that already knows the context/stats
response shape does not have to learn a second shape for the recap
view.

---

## 3. Implementation

### 3.1 Reuse strategy — extract data builders

The existing `get_market_context` and `get_market_stats` handlers
have their data-building logic **inline in the handler body**
(`stock_data/api/routes/agent.py:805-836` and `:1269+`).
`market-recap` cannot call the handlers as plain functions because
they return `Response` (not the Pydantic model), so calling them
would force a JSON-parse round-trip.

Extraction: lift the body into two module-level functions with the
same signature shape as the `Query`-decorated params they currently
consume.

```python
# stock_data/api/routes/agent.py — new module-level helpers

def build_market_context_response(
    flash_limit: int,
    trade_date: str | None,
) -> MarketContextResponse:
    """Build the Pydantic model for /agent/market-context.
    Pure logic: cache lookup / store happens in the caller (handler
    or market-recap). Mirrors the post-2026-09-02 slim contract.
    """

def build_market_stats_response(
    include_boards: bool,
    include_pools: bool,
    trade_date: str | None,
) -> MarketStatsResponse:
    """Build the Pydantic model for /agent/market-stats.
    Pure logic: cache lookup / store happens in the caller.
    """
```

Both existing handlers are **refactored to call these helpers** —
same cache key, same `cached_lookup` / `cached_store` calls, same
render path. No behavior change for clients of those two endpoints.

**Why this is "reuse, not over-design"**: the handlers' bodies are
~30 lines each; the helpers are the same lines, just hoisted. No
new abstractions, no parameter objects, no new error wrappers.

### 3.2 New route handler

```python
@router.get(
    "/agent/market-recap",
    response_model=MarketRecapResponse,
    responses={400: {"model": ErrorResponse, ...}, 500: {"model": ErrorResponse, ...}},
    tags=["agent"],
)
@endpoint_meta(
    summary="市场全景聚合：context(messages) + stats(quantitative) + 3 指数 quote",
    markets=["csi"],
    capabilities=[],
    depends_on=[
        "/api/v1/agent/market-context",
        "/api/v1/agent/market-stats",
        "/api/v1/indices/{code}/quote",
    ],
)
@map_errors
def get_market_recap(
    flash_limit: int = Query(default=20, ge=1, le=200, ...),
    include_boards: bool = Query(default=True, ...),
    include_pools: bool = Query(default=True, ...),
    trade_date: str | None = Query(default=None, ...),
    format: str = Query(default="json", pattern="^(json|md)$", ...),
) -> Response:
    # 1. trade_date gate (same regex as context/stats → 400)
    # 2. resolve target_date via trade_calendar (same helper as context/stats)
    # 3. cache lookup
    # 4. on miss: parallel fan-out via asyncio.gather (handler is async def)
    #    - asyncio.to_thread(build_market_context_response, flash_limit, target_date)
    #    - asyncio.to_thread(build_market_stats_response, include_boards, include_pools, target_date)
    #    - asyncio.to_thread(_build_three_index_quotes_block)  # internally serial
    # 5. per-block error isolation → errors[]
    # 6. assemble MarketRecapResponse, cached_store, return _render_agent(...)
```

**Why `asyncio.to_thread`**: the two existing handlers are sync
(`def`, not `async def`) because they wrap blocking SDK calls
(ClsFetcher, persistence). Calling them directly from an async
handler would block the event loop. `to_thread` offloads to the
default executor, preserving FastAPI's request-concurrency model.

**Why 3 indices internally serial** (inside
`_build_three_index_quotes_block`): `manager.get_index_realtime_quote`
goes through `_with_failover`, which mutates per-fetcher circuit
breaker state. Concurrent calls on the singleton manager are not
re-entrant safe. Sequential adds ~50ms × 3 at worst; cache absorbs
repeat calls.
```

### 3.3 Index quote conversion

`manager.get_index_realtime_quote(code)` returns `UnifiedRealtimeQuote
| None`. To embed in `MarketRecapResponse.indices.{sh,shenzhen_composite,chinext}`
as `IndexQuote | None`, use a small field-by-field converter (similar
to `_build_minimal_quote_from_unified` at `agent.py:899`):

```python
def _index_quote_from_unified(code: str, q: UnifiedRealtimeQuote | None) -> IndexQuote | None:
    if q is None:
        return None
    return IndexQuote(
        code=code,
        name=getattr(q, "name", "") or "",
        source=getattr(q, "source", "") or "",
        current_price=float(getattr(q, "price", 0.0) or 0.0),
        change_amount=getattr(q, "change_amount", None),
        change_pct=getattr(q, "change_pct", None),
        open=getattr(q, "open", None),
        high=getattr(q, "high", None),
        low=getattr(q, "low", None),
        prev_close=getattr(q, "prev_close", None),
        volume=getattr(q, "volume", None),
        volume_unit="share",  # spec §3.4 — indices always "share"
        amount=getattr(q, "amount", None),
        update_time=getattr(q, "update_time", None),
    )
```

`getattr` with `None` defaults handles fetcher-side field variance
without raising. (Mirrors `_build_minimal_quote_from_unified`'s
defensive style.)

### 3.4 Cache

| Cache key | Builder | TTL |
|---|---|---|
| `agent_market_context:{flash_limit}:{date}` | existing `make_market_context_cache_key` | 60s on `get_quote_cache` |
| `agent_market_stats:{include_boards}:{include_pools}:{date}` | existing `make_market_stats_cache_key` | 60s on `get_quote_cache` |
| `agent_market_recap:{flash_limit}:{include_boards}:{include_pools}:{date}` | **new** `make_market_recap_cache_key` | 60s on `get_quote_cache` |

**Reuse, not bypass**: `market-recap` calls the existing
`cached_lookup` / `cached_store` against `make_market_context_cache_key`
and `make_market_stats_cache_key` for the inner builders. The
top-level key exists only so that a single recap request is cached as
a single response (avoids re-running all three fan-outs on repeat
hits).

### 3.5 MD rendering

```python
# new function in stock_data/api/routes/agent.py
def render_market_recap_as_md(p: MarketRecapResponse) -> str:
    """Reuse existing sub-block renderers; add a 3-line index table."""
    parts = [
        render_market_context_as_md(p.context),     # existing
        render_market_stats_as_md(p.stats),         # existing
    ]
    parts.append(_render_indices_table_md(p.indices))
    if p.errors:
        parts.append(_render_errors_md(p.errors))
    return "\n\n---\n\n".join(parts)
```

The 3-line index table is hand-written (one row per non-null index,
columns: code / name / change_pct / amount / volume). No
`feature`-level rendering needed — we deliberately don't pull
`batch-profile` data, so there's no `BatchFeatures` block to render.

**MD completeness contract** (CLAUDE.md → `?format=md`): every JSON
field appears in MD. The sub-block renderers already satisfy this
for `context` and `stats`. The index table covers all 13 `IndexQuote`
keys per row (or marks `null`). Errors are rendered as a bullet list.

### 3.6 Error isolation

```python
results: dict[str, object] = {"context": None, "stats": None, "indices": {}}
errors: list[MarketRecapErrorEntry] = []

# context
try:
    results["context"] = build_market_context_response(flash_limit, target_date)
except Exception as exc:
    logger.warning(...); errors.append(MarketRecapErrorEntry(block="context", ...))

# stats
try:
    results["stats"] = build_market_stats_response(include_boards, include_pools, target_date)
except Exception as exc:
    logger.warning(...); errors.append(MarketRecapErrorEntry(block="stats", ...))

# 3 indices (sequential, not parallel — they share the manager lock)
for label, code in (("sh", "000001"), ("shenzhen_composite", "399001"), ("chinext", "399006")):
    try:
        q = manager.get_index_realtime_quote(code)
        results["indices"][label] = _index_quote_from_unified(code, q)
    except Exception as exc:
        logger.warning(...); errors.append(MarketRecapErrorEntry(block=f"indices.{label}", ...))
        results["indices"][label] = None
```

Sequential index fetches are deliberate: each goes through
`manager.get_index_realtime_quote` → `_with_failover`, which is not
re-entrant safe under concurrent calls on the singleton manager.
This adds ~50-100ms total at worst (3 fetcher failovers in serial);
the cache absorbs repeat calls.

### 3.7 Schema

```python
# stock_data/api/schemas.py — new

class MarketRecapErrorEntry(BaseModel):
    block: Literal["context", "stats", "indices.sh", "indices.shenzhen_composite", "indices.chinext"]
    error: str
    message: str


class MarketRecapIndicesBlock(BaseModel):
    """3-index snapshot. Each value is IndexQuote on success, null on failure."""
    sh: IndexQuote | None = None
    shenzhen_composite: IndexQuote | None = None
    chinext: IndexQuote | None = None


class MarketRecapResponse(BaseModel):
    context: MarketContextResponse
    stats: MarketStatsResponse
    indices: MarketRecapIndicesBlock
    errors: list[MarketRecapErrorEntry] = Field(default_factory=list)
    summary: dict[str, int | float]  # mirrors MarketContextResponse.summary shape
```

`MarketRecapSummary` reuses the existing `_batch_summary(...)` helper
that produces `{"requested", "ok", "failed", "elapsed_ms"}`. The
schema field is typed as the same `dict[str, int | float]` shape
used by `MarketContextResponse.summary` and
`MarketStatsResponse.summary` (no new Pydantic model needed).

---

## 4. Files touched

| File | Change |
|---|---|
| `stock_data/api/routes/agent.py` | • Add `build_market_context_response()` and `build_market_stats_response()` module-level helpers (extract from existing handlers, no behavior change). • Refactor `get_market_context` and `get_market_stats` handlers to call the helpers (cache + render path stays). • Add `get_market_recap` handler + `@endpoint_meta`. • Add `_index_quote_from_unified`, `render_market_recap_as_md`, `_render_indices_table_md`, `_render_errors_md`. • Register `market-recap` in `_MD_TEMPLATES`. |
| `stock_data/api/schemas.py` | • Add `MarketRecapErrorEntry`, `MarketRecapIndicesBlock`, `MarketRecapResponse` models. |
| `stock_data/api/cache.py` | • Add `make_market_recap_cache_key(flash_limit, include_boards, include_pools, trade_date)`. |
| `tests/test_agent_market_recap.py` | • New test file. (See §6.) |

No changes to `manager.py`, no fetcher modifications, no
`data_provider/` layer changes.

---

## 5. Token economics

| Component | Keys (JSON) | Notes |
|---|---|---|
| `context` block | ~5 + 2 nested (`body_text` 1-3KB) | dominated by `body_text` of morning_briefing/market_recap articles |
| `stats` block | ~5 + 80-100 pool entries × 14 fields | dominated by zt/dt pool lists |
| `indices` block | 3 × 13 = **~40 keys flat** | the new addition; tiny |
| `errors` + `summary` | ~5 + 5 | meta |

Adding the `indices` block costs **~40 flat keys** to a payload
already dominated by `body_text` and pool lists. Net token delta:
**~5-8% on top of `context + stats`** — well below the 10× cost of
the `batch-profile d` alternative.

---

## 6. Tests

`tests/test_agent_market_recap.py` — six test cases:

1. **`test_market_recap_happy_path`** — mock all 3 sub-blocks OK; assert
   `context` / `stats` / `indices` all populated; `errors` empty;
   `summary.ok == 5`.
2. **`test_market_recap_context_block_fails_others_ok`** — context
   builder raises; stats + 3 indices OK; `errors` has
   `{block: "context"}`; response is 200; `context` field is `None`.
3. **`test_market_recap_index_failure_isolated`** — `get_index_realtime_quote`
   raises for `399001`; `indices.shenzhen_composite` is null; the
   other two indices populated; `errors` has
   `{block: "indices.shenzhen_composite"}`.
4. **`test_market_recap_cache_hit_skips_fanout`** — first call
   populates cache; second call within TTL does NOT call any of the 3
   builders (mock-call count = 1).
5. **`test_market_recap_md_format_no_field_drop`** — call with
   `format=md`; assert rendered output contains every JSON field
   name from a representative `MarketRecapResponse` (per CLAUDE.md
   `?format=md` contract).
6. **`test_market_recap_invalid_trade_date_returns_400`** — invalid
   `trade_date` regex; assert 400 with `error: "invalid_trade_date"`.

All 6 tests use the standard `mock_get_manager` /
`monkeypatch` fixtures already used in `tests/test_agent_endpoints.py`
— no new fixture machinery.

---

## 7. Migration / rollout

- New endpoint, additive change. Zero impact on existing routes.
- Cache key namespace (`agent_market_recap:*`) is new — no
  in-flight cache entries to orphan.
- Explorer manifest picks up the new endpoint automatically via
  `/control/api-manifest` rebuild on next request (CLAUDE.md →
  "manifest is rebuilt on every request"). Section partition
  (`depends_on` chain) surfaces the data-source contract to the
  explorer UI.
- No `STOCK_DB_INIT` / DB schema migration needed.

---

## 8. Open questions

None at draft time. Two deferred items, **explicitly out of scope**:

1. `?include_trend=true` opt-in flag → batch-profile d (deferred per
   user's "ship A only" guidance).
2. Configurable index list (`?indices=000001,399006`) → v2, only if
   users actually ask for HK / US / mid-cap indices.
