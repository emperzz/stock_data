# `/api/v1/agent/market-stats` — Parallel Fan-out of 3 Independent Blocks

> Convert the three serial per-block aggregations (stocks / boards / pools)
> into a single `asyncio.gather` fan-out. Cold-path wall time goes from
> `sum(blocks)` to `max(blocks)`. No public-contract change, no new
> fetcher, no new cache key, no new `DataCapability`.

**Date**: 2026-09-10
**Status**: Draft (post-brainstorm)
**Scope**: `stock_data/api/routes/agent.py::get_market_stats` +
`build_market_stats_response` + 1 new test. **No response shape change;
no cache key change; no schema change; no fetcher change.**

---

## 1. Background

`GET /api/v1/agent/market-stats` is the agent-side "全市场涨幅分布" endpoint.
Per `build_market_stats_response` (`stock_data/api/routes/agent.py:1536-1661`)
the handler runs three independent upstream aggregations **sequentially**:

| Block | Source call | Cold-path latency |
|---|---|---|
| `stocks` | `manager.get_realtime_quotes("csi")` (Zzshare `rt_k` primary, AkShare fallback) | 1-3s (Zzshare), 3-10s (AkShare fallback) |
| `boards` | `stock_board_cache.get_board_list(None, "ths", include_quote=True, manager=...)` (THS gnSection + 2×industry ranks + ZZSHARE plates_list) | 3-5s |
| `pools`  | `manager.get_zt_pool("zt", date)` + `manager.get_zt_pool("dt", date)` | 2-5s |

Cold-path wall time is `stocks + boards + pools` ≈ **6-20s**. The
60-second `get_quote_cache` composite cache hit path is already
sub-ms, so the optimization target is the cold-path scenario:
cache miss / first call of the day / first call after `CACHE_TTL_QUOTE`
expires.

The exact same pattern (3+ independent aggregations → `asyncio.gather`
+ `asyncio.to_thread`) was already shipped for
`/api/v1/agent/market-recap` on 2026-09-03
(`docs/superpowers/specs/2026-09-03-market-recap-design.md`). That
endpoint uses the pattern for its 5-block fan-out (context, stats, 3
indices) and currently runs cleanly in production. Market-stats is the
obvious next candidate because:

1. Its blocks are **strictly more independent** than market-recap's
   (market-recap keeps the 3 indices sequential because the manager
   singleton is not re-entrant-safe for concurrent `_with_failover`;
   market-stats' blocks touch **separate** circuit breakers — see §4).
2. It's the slowest endpoint the user complains about; market-recap
   was the previous pain point and was solved this way.

**Non-goals**:

- No new fetcher, no new `DataCapability` flag, no new manager method.
- No response shape change; no Pydantic schema change; no MD template
  change.
- No cache key change (top-level `agent_market_stats:{include_boards}:{include_pools}:{date}`
  on `get_quote_cache` stays as-is).
- No `DataFetcherManager` change.
- No sub-block caching — that's a planned follow-up
  (方案 B from the brainstorming session; see §6).

---

## 2. Design

### 2.1 Refactor `build_market_stats_response` into 3 sync block builders + 1 sync wrapper

Split the existing monolithic function into three block-scoped
synchronous builders + a thin orchestrator:

```python
# New sync helpers (all live in agent.py near the existing handler)

def _build_stocks_block(manager) -> tuple[StockStats | None, list[MarketStatsErrorEntry]]:
    """stocks block. One upstream call: manager.get_realtime_quotes('csi').
    Returns (block_or_None, errors)."""

def _build_boards_block(manager) -> tuple[BoardStats | None, list[MarketStatsErrorEntry]]:
    """boards block. One upstream call: stock_board_cache.get_board_list(
    board_type=None, source='ths', include_quote=True, manager=manager)."""

def _build_limit_pools_block(
    manager, target_date: str
) -> tuple[MarketStatsLimitPools | None, list[MarketStatsErrorEntry]]:
    """pools block. Wraps existing `_compute_limit_pools_block(
    manager, target_date)` (currently at `agent.py:668`) by renaming
    it for symmetry with `_build_stocks_block` /
    `_build_boards_block`. The body is unchanged: per-pool try/except
    fan-out over `manager.get_zt_pool("zt" / "dt", target_date)` with
    errors collected per-pool. The rename touches the single in-file
    call site at `agent.py:1639`; no external callers.

    Implementation note: the plan renames the function in-place
    (rather than adding a wrapper layer), so the existing tests that
    reference `_compute_limit_pools_block` directly (none today —
    grepped the test suite) continue to work; if any test references
    the old name, the rename ships with a test-name update in the
    same change."""

def build_market_stats_response(
    include_boards: bool,
    include_pools: bool,
    target_date: str,
) -> MarketStatsResponse:
    """Sync orchestrator. Sequential (unchanged behavior). Called from
    /agent/market-recap's _gather_stats; preserves the existing
    single-threaded contract for callers that don't want async fan-out."""
    # ... existing implementation, but uses the 3 helpers above ...
```

The 3 helpers are **pure** in the sense that they do their own
try/except and return `(payload | None, [errors])`. They have **no
shared state** — the boards helper reads `stock_board_cache` (SQLite +
its internal `_refresh_tracker`); the stocks helper reads
`manager.get_realtime_quotes`; the pools helper reads
`manager.get_zt_pool`. None of them mutate shared module-level state.

### 2.2 Convert `get_market_stats` route handler to async

```python
@router.get(...)
@endpoint_meta(summary=..., markets=["csi"], capabilities=[], depends_on=[...])
@map_errors
async def get_market_stats(  # was: def get_market_stats
    include_boards: bool = Query(...),
    include_pools: bool = Query(...),
    trade_date: str | None = Query(...),
    format: str = Query(...),
) -> Response:
    """Per-block fan-out with per-block error isolation.
    Cold-path runs stocks / boards / pools blocks concurrently via
    asyncio.gather (see spec §2.2). Hot-path returns cached entry
    unchanged."""
    # 1. resolve target_date (unchanged)
    if trade_date is not None and not _TRADE_DATE_RE.match(trade_date):
        raise HTTPException(...)
    today_str = datetime.now(_CST).date().isoformat()
    target_date = (
        trade_date or trade_calendar.get_latest_trade_date_on_or_before(today_str) or today_str
    )

    # 2. top-level cache lookup (unchanged)
    cache_key = make_market_stats_cache_key(include_boards, include_pools, target_date)
    hit = cached_lookup(get_quote_cache, cache_key, "agent_market_stats")
    if hit is not None:
        return _render_agent("market-stats", hit, format)

    # 3. parallel fan-out — each block in its own asyncio.to_thread so
    #    the sync upstream calls don't block the event loop.
    started = time.monotonic()
    manager = get_manager()
    requested = 1 + (1 if include_boards else 0) + (1 if include_pools else 0)

    async def _gather_stocks():
        try:
            block, errs = await asyncio.to_thread(_build_stocks_block, manager)
            return block, errs, True  # (block, errors, ok)
        except Exception as exc:
            logger.warning(f"[agent/market-stats] stocks failed: {exc}", exc_info=True)
            return None, [
                MarketStatsErrorEntry(block="stocks", error=type(exc).__name__, message=str(exc))
            ], False

    async def _gather_boards():
        if not include_boards:
            return None, [], False  # not attempted; ok=False to keep requested counting honest
        try:
            block, errs = await asyncio.to_thread(_build_boards_block, manager)
            return block, errs, True
        except Exception as exc:
            logger.warning(f"[agent/market-stats] boards failed: {exc}", exc_info=True)
            return None, [
                MarketStatsErrorEntry(block="boards", error=type(exc).__name__, message=str(exc))
            ], False

    async def _gather_pools():
        if not include_pools:
            return None, [], False
        try:
            block, errs = await asyncio.to_thread(
                _build_limit_pools_block, manager, target_date
            )
            return block, errs, True
        except Exception as exc:
            logger.warning(f"[agent/market-stats] pools failed: {exc}", exc_info=True)
            return None, [
                MarketStatsErrorEntry(block="pools", error=type(exc).__name__, message=str(exc))
            ], False

    (stocks_block, stocks_errs, stocks_ok), (boards_block, boards_errs, boards_ok), (
        pools_block, pools_errs, pools_ok
    ) = await asyncio.gather(_gather_stocks(), _gather_boards(), _gather_pools())

    # 4. assemble (unchanged assembly logic)
    ok = int(stocks_ok) + int(boards_ok) + int(pools_ok)
    errors: list[MarketStatsErrorEntry] = stocks_errs + boards_errs + pools_errs
    result = MarketStatsResponse(
        stocks=stocks_block,
        boards=boards_block,
        limit_pools=pools_block or MarketStatsLimitPools(zt=None, dt=None),
        errors=errors,
        summary=_batch_summary(requested, ok, started),
    )

    # 5. cache + return (unchanged)
    cached_store(get_quote_cache, cache_key, result)
    return _render_agent("market-stats", result, format)
```

### 2.3 Sync wrapper preserved for `/agent/market-recap` reuse

`/agent/market-recap` (`agent.py:2747-2760`) currently calls
`build_market_stats_response(include_boards, include_pools, target_date)`
from inside its own `asyncio.to_thread(...)`. That call site **stays
the same** — `build_market_stats_response` continues to exist as a
sync orchestrator that the new `async get_market_stats` does **not**
call (the new handler uses `_build_*_block` helpers directly + its own
`asyncio.gather`).

This means market-recap continues to do its stats sub-fanout via the
serial path. That's intentional — market-recap already parallelizes
context + stats + indices, and the stats sub-blocks (stocks / boards /
pools) run **inside the stats `asyncio.to_thread` boundary**, so they
remain serial within that thread (same as today). No regression.

If market-recap later wants to also fan out the stats sub-blocks
internally, it can switch to calling the new helpers — but that's a
separate change, not part of this spec.

---

## 3. Public contract preserved

| Field | Before | After |
|---|---|---|
| URL | `GET /api/v1/agent/market-stats` | unchanged |
| Query params | `include_boards`, `include_pools`, `trade_date`, `format` | unchanged |
| Response schema | `MarketStatsResponse` | unchanged |
| `summary.requested` | `1 + (include_boards?1:0) + (include_pools?1:0)` | unchanged |
| `summary.ok` | count of blocks that succeeded | unchanged |
| `summary.elapsed_ms` | int(time.monotonic() - started)*1000 | unchanged (wall time still measured at route entry; **decreases** under cold-path) |
| `errors[]` shape | `{block, error, message}` | unchanged |
| `stocks/boards/limit_pools` field semantics | null on per-block failure | unchanged |
| MD output | `render_market_stats_as_md` | unchanged (called from `_render_agent`) |
| Top-level cache key | `agent_market_stats:{include_boards}:{include_pools}:{date}` on `get_quote_cache` (60s TTL) | unchanged |
| `build_market_stats_response` signature | sync, called from market-recap | unchanged (sync orchestrator kept for market-recap reuse) |

---

## 4. Concurrency & circuit-breaker safety

The pre-existing market-recap implementation
(`docs/superpowers/specs/2026-09-03-market-recap-design.md` §3.6) notes:
*"manager singleton + circuit breaker concurrent safety — 3 indices
fetched sequentially (manager singleton not re-entrant safe for
concurrent `_with_failover`)."*

For market-stats the situation is **structurally cleaner** than
market-recap, because the 3 blocks touch **separate circuit breakers**:

- **`stocks` block** uses `manager.get_realtime_quotes("csi")`, which
  goes through `_with_failover(..., circuit_breaker=QUOTE_LIST_CIRCUIT_BREAKER, ...)`
  (`stock_data/data_provider/manager.py:806`). `QUOTE_LIST_CIRCUIT_BREAKER`
  is a **dedicated breaker** (separate from the singleton
  `REALTIME_CIRCUIT_BREAKER` used by single-stock paths), introduced
  specifically to keep the list path from poisoning the single-stock
  path's breaker state. Verified at `manager.py:767-774`.
- **`boards` block** uses `stock_board_cache.get_board_list(...)`,
  which internally calls `manager.get_all_boards(source="ths", ...)` and
  `manager.get_all_boards(source="zzshare", ...)`. These go through
  `_with_source(...)` (`manager.py`), which is **not** circuit-breaker
  integrated per CLAUDE.md
  ("Board endpoints route through `_with_source`, which is **not**
  CircuitBreaker-integrated").
- **`pools` block** uses `manager.get_zt_pool(...)`, which routes
  through `_with_failover` with the default singleton `CIRCUIT_BREAKER`
  (Akshare primary → Zhitu fallback). This breaker is **not the same
  instance** as `QUOTE_LIST_CIRCUIT_BREAKER` (used by the stocks block)
  nor as `REALTIME_CIRCUIT_BREAKER` (used by single-stock paths), so a
  stocks-block failure cannot trip the pools breaker.

None of the three blocks share a circuit-breaker instance. Cross-block
CB-state contamination is therefore impossible.

### 4.1 `_refresh_tracker` (persistence/board.py) shared state

`stock_board_cache.get_board_list` internally calls
`_refresh_tracker.is_first_call(f"{board_type}:{source}")`. This is
module-level state in `stock_data/data_provider/persistence/board.py`.
Concurrent threads reading `is_first_call` for the same key would each
see "first call" and trigger a parallel upstream fetch — a *duplicate*
fetch (not a correctness bug, just wasted bandwidth).

**Mitigation chosen (post-brainstorm)**: **no code change**. Rationale:

   - The race only fires when 3+ threads happen to call
     `get_board_list` for the same `(board_type, source)` **on the
     same calendar day, before the cache is populated**. In production
     the `stocks_list_cache` and the persistence board cache get
     populated by other endpoints (`/stocks?include_quote=true`,
     `/boards/{code}/stocks`, `/agent/stocks/batch-profile`) long
     before `/agent/market-stats` is hit; the practical concurrency
     window is microseconds at the first agent request of the day.
   - Even in the worst case, the second thread's redundant fetch
     produces a fresh `update_cached_boards(...)` write — idempotent on
     the (board_code, source) UNIQUE constraint; no data corruption,
     just one wasted upstream call.
   - Adding a `threading.Lock` to `_refresh_tracker` would add
     coupling from the persistence layer to the route layer's threading
     model, which `CLAUDE.md` "Anti-Patterns" discourages.
   - Market-recap's 5-block fan-out already accepts this same kind of
     shared-state micro-race for its single-threaded stats inner call;
     extending the same philosophy is consistent.

   **Risk log entry**: document in the spec that
   `persistence.board._refresh_tracker` is *technically* not
   thread-safe for `is_first_call` under the new concurrent
   `get_board_list` invocation, and that the practical impact is at
   most one duplicate upstream fetch on the first concurrent
   cold-path request of the day.

### 4.2 `asyncio.to_thread` and the default executor

`asyncio.to_thread` defaults to the loop's executor (a
`ThreadPoolExecutor` with `min(32, os.cpu_count() + 4)` workers on
Python 3.8+). The 3 block calls share that pool with the rest of the
server's sync helpers — but `/agent/market-stats` is unlikely to
saturate it. If a real saturation event surfaces (visible as queue
wait time in `asyncio` logs), the response is documented to escalate
to a dedicated executor; out of scope here.

---

## 5. Tests

### 5.1 Tests that stay unchanged

`tests/test_agent_market_stats.py` (16 tests, asserting response
shape, error semantics, summary accounting) — **no change needed**.
The response shape, cache key, error envelope, and `summary.*`
semantics are all preserved verbatim.

`tests/test_api_cache.py::test_make_market_stats_cache_key_*` — **no
change needed**. The cache key signature is unchanged.

### 5.2 New test

`tests/test_agent_market_stats.py::TestParallelFanout` (new class):

1. `test_three_blocks_fan_out_concurrently`
   Mock the 3 sync builders (`_build_stocks_block`, `_build_boards_block`,
   `_build_limit_pools_block`) to sleep for 100ms each. Hit the
   endpoint with `include_boards=true, include_pools=true`. Assert the
   total wall time is `< 250ms` (would be ~300ms+ serially). Assert
   each builder was called exactly once.

2. `test_skipped_block_does_not_block_fan_out`
   Hit with `include_boards=false, include_pools=false`. Mock the
   boards + pools builders to raise (so we'd see them in errors[] if
   they were called). Assert only `_build_stocks_block` was called
   and that boards + pools errors are absent.

3. `test_one_block_failure_does_not_break_others`
   Mock `_build_stocks_block` to raise; mock the other two to return
   normal payloads. Assert response is 200, `stocks=null`, `boards`
   and `pools` are populated, `errors[]` has exactly one
   `{block: "stocks", ...}` entry.

4. `test_market_recap_stats_subpath_still_works`
   Regression: market-recap calls `build_market_stats_response`
   (sync) — assert it still works after the refactor (it should, the
   signature is unchanged; the body is just split into helpers).

### 5.3 Out-of-scope tests

- No latency benchmark — too flaky for CI. The functional verification
  in §5.2 catches the regression ("blocks became serial again") via
  wall-time assertion on the 100ms-each mock.
- No thread-safety test for `_refresh_tracker` — the chosen mitigation
  is "accept the duplicate fetch on first concurrent cold-path request";
  pinning a thread-safety contract on `_refresh_tracker` is a separate
  concern with a separate scope (would belong in
  `persistence/board.py`'s test suite).

---

## 6. Follow-up (separate spec, not part of this change)

**方案 B from the brainstorming session** — sub-block caching with
session-adaptive TTL. Decompose the top-level
`agent_market_stats:{include_boards}:{include_pools}:{date}` key into
3 sub-block keys (`stocks:{date}:session`, `boards:{date}:session`,
`pools:{date}`) with `session` derived from
`_classify_market_session()` (already implemented at `agent.py:641`).
Set 60s TTL during `intraday` session, 1800s during `post-market` and
`closed` (since `change_pct` is frozen post-close). The composite
60s key remains for fast hot-path; sub-block caches serve the
post-close case where today the user pays a full cold-path fetch every
60 seconds.

This is a clean follow-up because:

- It's an additive cache layer (sub-block + composite coexist).
- It uses an existing helper (`_classify_market_session`).
- It addresses the **post-close** pain point, which this spec does
  **not** address (this spec only addresses cold-path latency during
  any session).

Track as a separate change once this one ships.

---

## 7. Roll-out

- Single PR: refactor `build_market_stats_response` → 3 helpers + sync
  wrapper; convert `get_market_stats` to async + add `asyncio.gather`;
  add `TestParallelFanout` (4 tests); update `CLAUDE.md` agent-batch
  section to note the parallelism (one-paragraph addition to the
  `/agent/market-stats` row in the routes table).
- No feature flag, no canary: the change is bounded to a single route
  handler; the cache + response shape are unchanged; the worst-case
  regression is "blocks run serially again" (the old behavior) which
  is caught by the §5.2 wall-time assertion.
- Expected user-visible change: cold-path p50 latency drops from
  ~6-10s to ~3-5s; p95 from ~15-20s to ~5-10s. Hot-path (within 60s
  cache window) unchanged at sub-ms.

---

## 8. Risk register

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| `_refresh_tracker` duplicate fetch on cold-path concurrent first-call | very low (microsecond window, once per day) | 1 wasted upstream call, no data corruption | Accept; document in §4.1 |
| asyncio.to_thread default executor saturation under heavy load | low (1 extra concurrent sync helper per request) | added queue latency | Out of scope; default executor is sized for the rest of the server's sync helpers; re-evaluate if logs show saturation |
| market-recap's stats sub-call regression | low | market-recap stats block reverts to slower path | §5.2.4 regression test |
| Future refactor of `build_market_stats_response` accidentally calls the helpers AND the wrapper | low | double-fetch in market-recap path | The 3 helpers are private (underscore prefix); wrapper is the only public surface |
| `_build_limit_pools_block` raises an exception type the wrapper doesn't catch | very low | 500 instead of structured `errors[]` entry | Both wrappers catch `Exception` (broadest base); mirrors existing behavior |

---

## 9. Spec metadata

- **Spec author**: brainstorm session 2026-09-10
- **Implementation plan**: to be generated via `superpowers:writing-plans`
  after spec approval.
- **Related specs**:
  - `docs/superpowers/specs/2026-09-03-market-recap-design.md` — pattern source for `asyncio.gather` + `asyncio.to_thread` fan-out
  - `docs/superpowers/specs/2026-09-02-market-context-and-market-stats-redesign-design.md` — defines the current 3-block shape
  - `docs/superpowers/specs/2026-09-09-agent-market-stats-board-movers-design.md` — adds the `top_gainers` / `top_losers` board fields that this spec preserves
- **Anti-patterns audited** (CLAUDE.md):
  - "Don't reorder decorators on a route" — checked; `@router.get` outermost, `@endpoint_meta` next, `@map_errors` innermost, `async def`. No change vs current order.
  - "Don't add a `DataCapability` flag without declaring intent" — N/A, no new flag.
  - "Don't call `manager.get_board_stocks(...)` directly from agent code" — N/A, boards block goes through `stock_board_cache`.