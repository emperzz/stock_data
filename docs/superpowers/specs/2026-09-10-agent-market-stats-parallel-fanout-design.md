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
    unchanged. Cached 60s via ``get_quote_cache`` (one entry shared
    between json/md). [docstring note preserved verbatim from the
    pre-refactor sync version.]"""
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
            # NOTE: this branch is dead code in practice — _build_limit_pools_block
            # catches all exceptions internally per-pool (its try/excepts are
            # bare `except Exception`), so the only ways this catch can fire are
            # (a) a non-Exception BaseException (e.g. asyncio.CancelledError)
            # or (b) a Pydantic construct failure on `MarketStatsLimitPools(...)`.
            # We use `block="zt_pool"` (closest semantic match in the
            # MarketStatsErrorEntry Literal) rather than `"pools"`, which
            # would violate the schema and trigger a 500 if ever fired.
            # Preserved from the existing build_market_stats_response but
            # with the literal corrected.
            logger.warning(f"[agent/market-stats] pools failed: {exc}", exc_info=True)
            return None, [
                MarketStatsErrorEntry(block="zt_pool", error=type(exc).__name__, message=str(exc))
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
| `summary.elapsed_ms` | int(time.monotonic() - started)*1000 | **measurement-point shifts** from `build_market_stats_response` (existing, measures inside the wrapper) to the new `async def get_market_stats` (measures at route handler entry, before `manager = get_manager()` and `asyncio.gather`). Sub-ms difference (cache lookup + manager import); no test asserts `elapsed_ms` values, so no functional change. The wall time itself **decreases** under cold-path as the headline goal. |
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
  through `_with_failover` with **no circuit breaker** at all. Verified
  at `manager.py:888-894`: `get_zt_pool_raw` calls
  `self._with_failover(...)` without a `circuit_breaker=` argument,
  and `_with_failover`'s signature defaults `circuit_breaker=None`
  with all CB interactions guarded by `if circuit_breaker is not None`
  (`manager.py:318, 371-404`). The pools block is therefore CB-less:
  a stocks-block failure cannot trip it, and a pools-block failure
  cannot affect any other breaker. The cross-block contamination
  conclusion in the lead paragraph holds *a fortiori*.

None of the three blocks share a circuit-breaker instance. Cross-block
CB-state contamination is therefore impossible.

### 4.1 `_refresh_tracker` (persistence/board.py) shared state

`stock_board_cache.get_board_list` internally calls
`_refresh_tracker.is_first_call(f"{board_type}:{source}")`. The
review (2026-09-10) verified that **the race the original brainstorm
   flagged does not exist**:

- `DailyRefreshTracker.__init__` (in
  `stock_data/data_provider/persistence/_refresh.py:26`) constructs
  `self._lock = threading.Lock()`.
- `is_first_call` wraps its read-modify-write of `self._dates[key]`
  inside `with self._lock:` (`_refresh.py:33`).

Concurrent threads calling `is_first_call(key)` for the same key are
serialized by `_lock`: the first thread records `today`, subsequent
threads see `today` already set and return False. The "duplicate
fetch on first concurrent cold-path request of the day" scenario is
**structurally impossible**.

**Implication**: no mitigation needed. The original brainstorm's
"accept the risk" paragraph is preserved here as a record of the
reasoning trail but the conclusion is that this entry should be
removed from any future risk register.

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
   `_build_limit_pools_block`) to sleep for **250ms** each. Hit the
   endpoint with `include_boards=true, include_pools=true`. Assert the
   total wall time is `< 700ms` (serial baseline = 750ms; 50ms
   headroom against asyncio dispatch + GC pauses + executor scheduling
   under CI load). Assert each builder was called exactly once. The
   250ms mock duration was chosen over the original 100ms because the
   100ms / 250ms threshold combination leaves insufficient headroom
   for slow CI machines (only 50ms over a 300ms serial baseline).

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

(Note: a 4th test for `test_market_recap_stats_subpath_still_works`
was considered but **deleted** during spec review — the existing
  `tests/test_agent_market_recap.py::test_market_recap_happy_path`
  already covers market-recap's call into `build_market_stats_response`
  end-to-end via stubbing. Adding a near-duplicate test would only
  catch a NameError/ImportError from a broken rename, which the test
  suite's collection phase catches earlier and more reliably.)

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

Single PR with the following checklist:

- [ ] Add `_build_stocks_block(manager)` helper in `agent.py` (extracted
  from current `build_market_stats_response`'s stocks try/except).
- [ ] Add `_build_boards_block(manager)` helper in `agent.py` (extracted
  from current `build_market_stats_response`'s boards try/except).
- [ ] Rename `_compute_limit_pools_block` → `_build_limit_pools_block`
  in `agent.py` (touch only the definition at agent.py:668 + the single
  in-file call site at agent.py:1639). Also fix the stale line-number
  reference at agent.py:1548 (currently says "defined at agent.py:568"
  but the definition is at agent.py:668) — bundled with the rename.
- [ ] Refactor `build_market_stats_response` to call the 3 helpers in
  sequence (preserves the existing sync behavior; called by market-recap).
- [ ] Convert `get_market_stats` to `async def`, add `asyncio.gather`
  + `asyncio.to_thread` per §2.2. Preserve the existing 60s
  `get_quote_cache` note verbatim in the updated docstring.
- [ ] Add `TestParallelFanout` class to `tests/test_agent_market_stats.py`
  (3 tests per §5.2).
- [ ] Update `CLAUDE.md` agent-batch table — `/agent/market-stats` row
  gains one sentence noting "stocks/boards/pools blocks fan out via
  asyncio.gather on cold-path; 60s composite cache unchanged."
- [ ] Run full test suite (`pytest -m ""`); confirm 0 regressions.

- No feature flag, no canary: the change is bounded to a single route
  handler; the cache + response shape are unchanged; the worst-case
  regression is "blocks run serially again" (the old behavior) which
  is caught by the §5.2.1 wall-time assertion.
- Expected user-visible change: cold-path p50 latency drops from
  ~6-10s to ~3-5s; p95 from ~15-20s to ~5-10s. Hot-path (within 60s
  cache window) unchanged at sub-ms.

---

## 8. Risk register

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| `_refresh_tracker` duplicate fetch on cold-path concurrent first-call | **none** (verified thread-safe — see §4.1) | n/a | No mitigation needed; the original concern was based on a false premise. The 2026-09-10 review verified `DailyRefreshTracker._lock` serializes `is_first_call` for the same key. |
| asyncio.to_thread default executor saturation under heavy load | low (1 extra concurrent sync helper per request) | added queue latency | Out of scope; default executor is sized for the rest of the server's sync helpers; re-evaluate if logs show saturation |
| market-recap's stats sub-call regression | low | market-recap stats block reverts to slower path | Covered by existing `tests/test_agent_market_recap.py::test_market_recap_happy_path` which stubs `build_market_stats_response` and asserts the recap response carries the stats block. The new TestParallelFanout deliberately omits a duplicate test per §5.2.4 note. |
| Future refactor of `build_market_stats_response` accidentally calls the helpers AND the wrapper | low | double-fetch in market-recap path | The 3 helpers are private (underscore prefix); wrapper is the only public surface |
| `_build_limit_pools_block` outer catch fires (dead code path) | extremely low (only via BaseException or Pydantic construct failure) | would have constructed `MarketStatsErrorEntry(block="zt_pool", ...)` which is now schema-valid per the §2.2 fix | Outer catch constructs `block="zt_pool"` (closest semantic match in the Literal); mirrors existing behavior with a corrected literal |

---

## 9. Spec metadata

- **Spec author**: brainstorm session 2026-09-10
- **Spec review**: subagent verification 2026-09-10; 11 findings, all applied
  inline (2 HIGH factual corrections to §4 + §4.1, 4 MEDIUM including a
  latent dead-code bug fix, 4 LOW verification-positive findings).
- **Implementation plan**: derived directly from §7 Roll-out checklist
  (no separate `superpowers:writing-plans` document — change is single-route
  bounded and the checklist is the actionable plan).
- **Related specs**:
  - `docs/superpowers/specs/2026-09-03-market-recap-design.md` — pattern source for `asyncio.gather` + `asyncio.to_thread` fan-out
  - `docs/superpowers/specs/2026-09-02-market-context-and-market-stats-redesign-design.md` — defines the current 3-block shape
  - `docs/superpowers/specs/2026-09-09-agent-market-stats-board-movers-design.md` — adds the `top_gainers` / `top_losers` board fields that this spec preserves
- **Anti-patterns audited** (CLAUDE.md):
  - "Don't reorder decorators on a route" — verified against existing market-recap decorator stack (agent.py:2664-2684); preserved.
  - "Don't add a `DataCapability` flag without declaring intent" — N/A, no new flag.
  - "Don't call `manager.get_board_stocks(...)` directly from agent code" — verified; the new `_build_boards_block` goes through `stock_board_cache.get_board_list(...)` (Persistence-Only Routing rule).
  - "Don't hardcode `adjust="qfq"` in `/agent/stocks/batch-profile` for minute frequencies" — N/A, this spec touches only `/agent/market-stats`.