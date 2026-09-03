# Market-Recap Aggregation Endpoint Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `GET /api/v1/agent/market-recap` that server-side aggregates `market-context` + `market-stats` + 3 CSI index quotes (上证 / 深成指 / 创业板) into a single response, reusing existing data builders and cache layers.

**Architecture:** Extract the data-building bodies of `get_market_context` and `get_market_stats` into module-level helpers; have the existing handlers call them. Add a new `async def` route that calls all three builders (context + stats + 3 index quotes) via `asyncio.gather` + `asyncio.to_thread`, embeds the three sub-results in a new `MarketRecapResponse` Pydantic model, and reuses existing MD renderers. No fetcher / manager / DataCapability changes.

**Tech Stack:** FastAPI, Pydantic v2, asyncio, TTLCache (`get_quote_cache`), `re`, `datetime`. Tests use pytest with the existing `monkeypatch` / mock fixtures from `tests/conftest.py`.

**Spec:** [`docs/superpowers/specs/2026-09-03-market-recap-design.md`](../specs/2026-09-03-market-recap-design.md) (commit `c6cb82e`).

## Global Constraints

These apply to every task:

- Python ≥ 3.11, repo uses `.venv/Scripts/python.exe` (CLAUDE.md → "Common Commands").
- Test runner: `.venv/Scripts/python.exe -m pytest`. Default `addopts` skips `live_network` — leave that alone.
- All commits use `Co-Authored-By: Claude <noreply@anthropic.com>` suffix.
- Spec doc / plan files: commit directly to `master` (memory `[[skip-branch-for-trivial-changes]]`). Server code: this is **not** a doc-only change — see Task 6 for branch guidance.
- Endpoint route prefix: `agent.py` is mounted under `/api/v1` (verified by existing routes in this file); new path is `/agent/market-recap`.
- Pydantic field names use snake_case. JSON field names mirror Python via Pydantic defaults.
- Per CLAUDE.md `?format=md` contract: every JSON field name must appear in the MD output. The plan's MD renderer step enforces this for the new endpoint.

---

## File Map

| File | Responsibility | Created/Modified |
|---|---|---|
| `stock_data/api/schemas.py` | Add `MarketRecapErrorEntry`, `MarketRecapIndicesBlock`, `MarketRecapResponse` Pydantic models | Modified |
| `stock_data/api/cache.py` | Add `make_market_recap_cache_key` | Modified |
| `stock_data/api/routes/agent.py` | • Extract `build_market_context_response()` and `build_market_stats_response()` helpers (refactor). • Add `_index_quote_from_unified()`, `_build_three_index_quotes_block()`. • Add `render_market_recap_as_md()` + helpers. • Add `get_market_recap()` route. • Register in `_MD_TEMPLATES`. | Modified |
| `tests/test_agent_market_recap.py` | 6 endpoint tests from spec §6 | Created |

No fetcher / `data_provider/` / manager changes.

---

## Task 1: Add `MarketRecapResponse` Schema Models

**Files:**
- Modify: `stock_data/api/schemas.py` (add 3 new classes at the end of the agent section)

**Interfaces:**
- Consumes: existing `IndexQuote`, `MarketContextResponse`, `MarketStatsResponse` from same file.
- Produces: `MarketRecapErrorEntry`, `MarketRecapIndicesBlock`, `MarketRecapResponse` (re-exported in `__all__` if that list exists).

**Background:** Pydantic models are pure data — TDD at the schema level means a tiny `pytest` test that constructs the model and asserts the shape. Existing `MarketContextResponse` and `MarketStatsResponse` already live in this file (around lines 1830 / 2057 per spec explore), so we just append below them.

- [ ] **Step 1: Write the failing test**

Create `tests/test_agent_market_recap_schemas.py`:

```python
"""Schema smoke tests for the new MarketRecap response models."""

from stock_data.api.schemas import (
    IndexQuote,
    MarketContextResponse,
    MarketRecapErrorEntry,
    MarketRecapIndicesBlock,
    MarketRecapResponse,
    MarketStatsResponse,
)


def test_market_recap_indices_block_accepts_three_quotes():
    block = MarketRecapIndicesBlock(
        sh=IndexQuote(code="000001", change_pct=1.2),
        shenzhen_composite=IndexQuote(code="399001", change_pct=0.5),
        chinext=IndexQuote(code="399006", change_pct=-0.3),
    )
    assert block.sh.code == "000001"
    assert block.shenzhen_composite.code == "399001"
    assert block.chinext.code == "399006"


def test_market_recap_indices_block_defaults_to_all_none():
    block = MarketRecapIndicesBlock()
    assert block.sh is None
    assert block.shenzhen_composite is None
    assert block.chinext is None


def test_market_recap_error_entry_accepts_all_block_literals():
    for block_literal in (
        "context",
        "stats",
        "indices.sh",
        "indices.shenzhen_composite",
        "indices.chinext",
    ):
        entry = MarketRecapErrorEntry(block=block_literal, error="X", message="Y")  # type: ignore[arg-type]
        assert entry.block == block_literal


def test_market_recap_response_constructs_with_minimum_required_fields():
    # Stub the inner models with empty bodies — the test only checks shape composition.
    ctx = MarketContextResponse.model_construct(
        trade_date="2026-09-03",
        is_trade_day=True,
        market_session="intraday",
        messages=None,
        summary={"requested": 1, "ok": 1, "failed": 0, "elapsed_ms": 10},
    )
    stats = MarketStatsResponse.model_construct(
        stocks=None,
        boards=None,
        limit_pools=None,
        errors=[],
        summary={"requested": 1, "ok": 1, "failed": 0, "elapsed_ms": 10},
    )
    resp = MarketRecapResponse(
        context=ctx,
        stats=stats,
        indices=MarketRecapIndicesBlock(),
        summary={"requested": 5, "ok": 5, "failed": 0, "elapsed_ms": 100},
    )
    assert resp.errors == []
    assert resp.indices.sh is None
    assert resp.summary["ok"] == 5
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_agent_market_recap_schemas.py -v`
Expected: `ImportError` / `ModuleNotFoundError` — `MarketRecapErrorEntry` etc. don't exist yet.

- [ ] **Step 3: Add the three Pydantic models**

Append to `stock_data/api/schemas.py` (find the end of the agent-related section near the existing `MarketStatsResponse`; if there is no clear anchor, append just before the final re-export block):

```python
class MarketRecapErrorEntry(BaseModel):
    """Per-block error for the market-recap aggregation endpoint."""

    block: Literal[
        "context",
        "stats",
        "indices.sh",
        "indices.shenzhen_composite",
        "indices.chinext",
    ] = Field(description="Which recap sub-block failed")
    error: str = Field(description="Exception class name")
    message: str = Field(description="Human-readable failure detail")


class MarketRecapIndicesBlock(BaseModel):
    """3-index snapshot for the market-recap endpoint.

    Each field is IndexQuote on success, None on per-index failure.
    Indices are fixed at v1: 上证 (000001) / 深成指 (399001) / 创业板 (399006).
    """

    sh: IndexQuote | None = Field(default=None, description="上证综指 quote")
    shenzhen_composite: IndexQuote | None = Field(
        default=None, description="深证成指 quote"
    )
    chinext: IndexQuote | None = Field(default=None, description="创业板指 quote")


class MarketRecapResponse(BaseModel):
    """Aggregated recap: messages + quantitative + 3-index snapshot."""

    context: MarketContextResponse = Field(
        description="Verbatim /agent/market-context response"
    )
    stats: MarketStatsResponse = Field(
        description="Verbatim /agent/market-stats response"
    )
    indices: MarketRecapIndicesBlock = Field(
        description="3-index quote block (上证 / 深成指 / 创业板)"
    )
    errors: list[MarketRecapErrorEntry] = Field(
        default_factory=list,
        description="Per-block failures across the recap aggregation",
    )
    summary: dict[str, int | float] = Field(
        description="requested / ok / failed / elapsed_ms — mirrors context/stats"
    )
```

(If `schemas.py` has an `__all__` list with explicit exports, append the three new class names there too. If it doesn't, Pydantic classes are auto-discoverable and no edit is needed.)

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/test_agent_market_recap_schemas.py -v`
Expected: 4 tests pass.

- [ ] **Step 5: Commit**

```bash
git add stock_data/api/schemas.py tests/test_agent_market_recap_schemas.py
git commit -m "feat(schemas): add MarketRecap response models"
```

---

## Task 2: Add `make_market_recap_cache_key`

**Files:**
- Modify: `stock_data/api/cache.py` (append after `make_market_stats_cache_key` at line 556)

**Interfaces:**
- Consumes: nothing new.
- Produces: `make_market_recap_cache_key(flash_limit: int, include_boards: bool, include_pools: bool, trade_date: str) -> str`

**Background:** Cache key format mirrors `make_market_stats_cache_key` (4-segment colon-joined). Lives on `get_quote_cache` with the same 60s TTL used by the existing context/stats keys.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_agent_market_recap_schemas.py` (or create `tests/test_agent_market_recap_cache_key.py` if preferred — keep it in the same test file for cohesion):

```python
from stock_data.api.cache import make_market_recap_cache_key


def test_make_market_recap_cache_key_format():
    key = make_market_recap_cache_key(20, True, True)
    assert key == "agent_market_recap:20:True:True"


def test_make_market_recap_cache_key_changes_with_each_param():
    base = make_market_recap_cache_key(20, True, True)
    assert make_market_recap_cache_key(40, True, True) != base
    assert make_market_recap_cache_key(20, False, True) != base
    assert make_market_recap_cache_key(20, True, False) != base
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_agent_market_recap_schemas.py -v`
Expected: `ImportError: cannot import name 'make_market_recap_cache_key' from 'stock_data.api.cache'`.

- [ ] **Step 3: Add the cache key builder**

Append to `stock_data/api/cache.py`:

```python
def make_market_recap_cache_key(
    flash_limit: int,
    include_boards: bool,
    include_pools: bool,
) -> str:
    """Cache key for GET /api/v1/agent/market-recap.

    3-segment colon-joined shape (no `trade_date` segment — recap
    always targets the server-resolved latest trade date; there is
    no user-facing date param). All three knobs participate:
    changing any produces a materially different response
    (different context flash count, different stats blocks,
    different pools). 60s TTL via get_quote_cache.
    """
    return f"agent_market_recap:{flash_limit}:{include_boards}:{include_pools}"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/test_agent_market_recap_schemas.py -v`
Expected: all 6 tests pass (4 from Task 1 + 2 from this task).

- [ ] **Step 5: Commit**

```bash
git add stock_data/api/cache.py tests/test_agent_market_recap_schemas.py
git commit -m "feat(cache): add make_market_recap_cache_key"
```

---

## Task 3: Extract `build_market_context_response` Helper (Refactor)

**Files:**
- Modify: `stock_data/api/routes/agent.py:805-836` (the body of `get_market_context` between `cached_lookup` and `cached_store`)

**Interfaces:**
- Consumes: `flash_limit: int`, `target_date: str` (already-resolved date, not raw query param).
- Produces: `MarketContextResponse` (no cache, no render — pure data).

**Background:** Pure refactor. The handler body between lines 805 and 836 builds the `MarketContextResponse` inline. Lift that body into a module-level function. The handler calls `cached_lookup` → if hit return → else call helper → `cached_store` → return. Behavior is identical for clients of `GET /agent/market-context`.

- [ ] **Step 1: Run existing market-context tests to establish a green baseline**

Run: `.venv/Scripts/python.exe -m pytest tests/test_agent_market_stats.py tests/test_agent_endpoints.py -v -k "market_context or context"`
Expected: all existing context-related tests pass (this is the regression bar).

If no tests match the filter, broaden to:
Run: `.venv/Scripts/python.exe -m pytest tests/test_agent_endpoints.py -v`
Expected: all pass.

- [ ] **Step 2: Add a focused test for the extracted helper**

Append to `tests/test_agent_market_recap_schemas.py`:

```python
from stock_data.api.routes.agent import build_market_context_response


def test_build_market_context_response_returns_model(monkeypatch):
    """Smoke test: the helper returns a MarketContextResponse for valid inputs."""
    from stock_data.api.schemas import MarketContextResponse

    # manager is fetched lazily inside the helper — monkeypatch it so the
    # test doesn't hit real upstream APIs.
    from stock_data.api.routes import agent as agent_mod

    class _FakeManager:
        def get_morning_briefing(self, _date):
            return (None, "ths")

        def get_market_recap(self, _date):
            return (None, "ths")

        def get_flash_news(self, *, limit):
            return ([], "ths")

    monkeypatch.setattr(agent_mod, "get_manager", lambda: _FakeManager())

    result = build_market_context_response(
        flash_limit=20, target_date="2026-09-03", today_str="2026-09-03"
    )
    assert isinstance(result, MarketContextResponse)
    assert result.trade_date == "2026-09-03"
    assert result.is_trade_day is True  # 2026-09-03 is a Thursday (and a trade day)
    assert result.market_session in {"pre-market", "intraday", "post-market", "closed"}
    assert result.messages.morning_briefing is None
    assert result.messages.market_recap is None
    assert result.messages.flash_news == []
    assert result.summary["requested"] == 3
```

(The `manager` instance access path matches the existing handler body — `get_manager()` is imported at module top of `agent.py`.)

- [ ] **Step 3: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_agent_market_recap_schemas.py::test_build_market_context_response_returns_model -v`
Expected: `ImportError: cannot import name 'build_market_context_response'`.

- [ ] **Step 4: Extract the helper and refactor the handler**

In `stock_data/api/routes/agent.py`, **before** `def get_market_context(...)` (i.e. around line 745), add:

```python
def build_market_context_response(
    flash_limit: int,
    target_date: str,
    today_str: str,
) -> MarketContextResponse:
    """Build the Pydantic model for /agent/market-context.

    Pure logic — cache lookup/store lives in the caller (route handler
    or market-recap). Returns the slim post-2026-09-02 shape:
    morning_briefing + market_recap + flash_news only (no pools,
    no dragon-tiger).

    `target_date` populates `trade_date` (may be historical if the
    caller passed `?trade_date=...`). `today_str` is the server's
    local date and is used ONLY to compute `is_trade_day` and
    `market_session` — those fields describe the present moment,
    not the queried date (see `MarketContextResponse.is_trade_day`
    docstring at `schemas.py:1839`). The original handler at
    `agent.py:788-794` already separates these two concepts; the
    helper preserves that semantics.
    """
    started = time.monotonic()
    manager = get_manager()
    attempts: list[tuple[str, Callable, object]] = [
        ("morning_briefing", lambda: manager.get_morning_briefing(target_date)[0], None),
        ("market_recap", lambda: manager.get_market_recap(target_date)[0], None),
        ("flash_news", lambda: manager.get_flash_news(limit=flash_limit)[0], []),
    ]

    results: dict[str, object] = {}
    n_ok = 0
    for name, fn, default in attempts:
        try:
            results[name] = fn()
            n_ok += 1
        except Exception as exc:
            logger.warning(f"[agent/market-context] {name} failed: {exc}", exc_info=True)
            results[name] = default

    is_today_trade_day = trade_calendar.is_trade_date(today_str)
    return MarketContextResponse(
        trade_date=target_date,
        is_trade_day=is_today_trade_day,
        market_session=_classify_market_session(is_today_trade_day),  # type: ignore[arg-type]
        messages=MarketContextMessages(
            morning_briefing=results["morning_briefing"],
            market_recap=results["market_recap"],
            flash_news=results["flash_news"],
        ),
        summary=_batch_summary(len(attempts), n_ok, started),
    )
```

**Note:** `is_trade_day` and `market_session` are computed from `today_str`, NOT from `target_date`. The original handler at `agent.py:788-794` uses `today_str = datetime.now(_CST).date().isoformat()` for these two fields, and `target_date` only for the data queries. The helper preserves this exact split.

Then **in** `get_market_context(...)` body, replace the inline build (lines 805-836 of the original file) with:

```python
    result = build_market_context_response(
        flash_limit=flash_limit,
        target_date=target_date,
        today_str=today_str,
    )
    cached_store(get_quote_cache, cache_key, result)
    return _render_agent("market-context", result, format)
```

The `started = time.monotonic()` line that the original handler had is no longer needed — remove it (the helper measures its own `started`).

- [ ] **Step 5: Re-run existing market-context tests + new helper test**

Run: `.venv/Scripts/python.exe -m pytest tests/test_agent_market_recap_schemas.py tests/test_agent_endpoints.py tests/test_agent_market_stats.py -v`
Expected: all pass (regression preserved + new helper test passes).

- [ ] **Step 6: Commit**

```bash
git add stock_data/api/routes/agent.py tests/test_agent_market_recap_schemas.py
git commit -m "refactor(agent): extract build_market_context_response helper"
```

---

## Task 4: Extract `build_market_stats_response` Helper (Refactor)

**Files:**
- Modify: `stock_data/api/routes/agent.py:1269-1357` (the data-building portion of `get_market_stats`)

**Interfaces:**
- Consumes: `include_boards: bool`, `include_pools: bool`, `target_date: str`.
- Produces: `MarketStatsResponse` (no cache, no render — pure data).

**Background:** Same pattern as Task 3. Lift the body of `get_market_stats` (between `cached_lookup` and `cached_store` at lines 1269-1357) into a module-level helper. The handler keeps cache_lookup/store/render.

- [ ] **Step 1: Run existing market-stats tests to establish a green baseline**

Run: `.venv/Scripts/python.exe -m pytest tests/test_agent_market_stats.py tests/test_agent_market_stats_schemas.py -v`
Expected: all pass.

- [ ] **Step 2: Add a focused test for the extracted helper**

Append to `tests/test_agent_market_recap_schemas.py`:

```python
from stock_data.api.routes.agent import build_market_stats_response


def test_build_market_stats_response_returns_model(monkeypatch):
    """Smoke test: the helper returns a MarketStatsResponse for valid inputs."""
    from stock_data.api.schemas import MarketStatsResponse
    from stock_data.api.routes import agent as agent_mod

    class _FakeManager:
        def get_realtime_quotes(self, market):
            return ([], "akshare")

    monkeypatch.setattr(agent_mod, "get_manager", lambda: _FakeManager())
    monkeypatch.setattr(
        "stock_data.data_provider.persistence.board.stock_board_cache.get_board_list",
        lambda **kwargs: ([], "ths"),
    )

    result = build_market_stats_response(
        include_boards=True, include_pools=False, target_date="2026-09-03"
    )
    assert isinstance(result, MarketStatsResponse)
    assert result.summary["requested"] == 2  # stocks + boards (no pools)
    assert result.limit_pools.zt is None
    assert result.limit_pools.dt is None
```

(`stock_board_cache.get_board_list` is imported in `agent.py` via `from ...persistence.board import stock_board_cache` — monkeypatch the symbol on its module path.)

- [ ] **Step 3: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_agent_market_recap_schemas.py::test_build_market_stats_response_returns_model -v`
Expected: `ImportError: cannot import name 'build_market_stats_response'`.

- [ ] **Step 4: Extract the helper and refactor the handler**

In `stock_data/api/routes/agent.py`, **before** `def get_market_stats(...)` (around line 1213), add:

```python
def build_market_stats_response(
    include_boards: bool,
    include_pools: bool,
    target_date: str,
) -> MarketStatsResponse:
    """Build the Pydantic model for /agent/market-stats.

    Pure logic — cache lookup/store lives in the caller. Per-block
    fan-out with per-block error isolation:
    - stocks block: manager.get_realtime_quotes('csi') (one upstream call)
    - boards block: stock_board_cache.get_board_list(...) (one upstream call)
    - pools block: manager.get_zt_pool('zt'|'dt', date=target_date) (two calls)
    A single upstream failure sets that block to null and appends to errors[];
    the rest continue.
    """
    started = time.monotonic()
    manager = get_manager()
    errors: list[MarketStatsErrorEntry] = []
    stocks_stats: StockStats | None = None
    boards_stats: BoardStats | None = None
    limit_pools_block: MarketStatsLimitPools | None = None

    requested = 1 + (1 if include_boards else 0) + (1 if include_pools else 0)
    ok = 0

    # --- stocks block (always attempted) ---
    try:
        quotes, _src = manager.get_realtime_quotes("csi")
        values = [
            q.change_pct for q in (quotes or []) if getattr(q, "change_pct", None) is not None
        ]
        agg = compute_aggregate(
            values,
            bin_width=STOCK_BUCKET_BIN_WIDTH,
            buckets_template=build_stock_buckets(),
        )
        stocks_stats = _stock_stats_from_aggregate(agg)
        ok += 1
    except Exception as exc:
        logger.warning(f"[agent/market-stats] stocks failed: {exc}", exc_info=True)
        errors.append(
            MarketStatsErrorEntry(
                block="stocks",
                error=type(exc).__name__,
                message=str(exc),
            )
        )

    # --- boards block (skipped when include_boards=false) ---
    if include_boards:
        try:
            boards, src = stock_board_cache.get_board_list(
                board_type=None,
                source="ths",
                include_quote=True,
                manager=manager,
            )
            values = [
                b.get("change_pct")
                for b in (boards or [])
                if isinstance(b.get("change_pct"), (int, float))
                and not isinstance(b.get("change_pct"), bool)
            ]
            agg = compute_aggregate(
                values,
                bin_width=BOARD_BUCKET_BIN_WIDTH,
                buckets_template=build_board_buckets(),
            )
            boards_stats = _board_stats_from_aggregate(agg, src or "ths")
            ok += 1
        except Exception as exc:
            logger.warning(f"[agent/market-stats] boards failed: {exc}", exc_info=True)
            errors.append(
                MarketStatsErrorEntry(
                    block="boards",
                    error=type(exc).__name__,
                    message=str(exc),
                )
            )

    # --- pools block (delegated to the existing helper — do NOT re-implement
    #     the per-pool fan-out here; `_compute_limit_pools_block` is the
    #     canonical implementation at agent.py:568 and unpacks the 3-tuple
    #     from `manager.get_zt_pool` correctly.) ---
    if include_pools:
        try:
            limit_pools_block, pool_errors = _compute_limit_pools_block(manager, target_date)
            errors.extend(pool_errors)
            ok += 1   # ONE block-level increment, matching the original handler
        except Exception as exc:
            logger.warning(f"[agent/market-stats] pools failed: {exc}", exc_info=True)
            errors.append(
                MarketStatsErrorEntry(
                    block="pools",
                    error=type(exc).__name__,
                    message=str(exc),
                )
            )

    return MarketStatsResponse(
        stocks=stocks_stats,
        boards=boards_stats,
        limit_pools=limit_pools_block or MarketStatsLimitPools(zt=None, dt=None),
        errors=errors,
        summary=_batch_summary(requested, ok, started),
    )
```

**Note:** This helper preserves the original handler's exact behavior including the `requested`/`ok` counters and `MarketStatsLimitPools(zt=None, dt=None)` fallback when both pools are skipped. The pools block delegates to the existing `_compute_limit_pools_block` so the 3-tuple unpack (`zt_pool`, `dt_pool`, `_src`, `_warn`) and the per-pool error entries (`zt_pool` / `dt_pool` literals) live in one place. `ok += 1` is incremented **once** for the entire pools block (not per-pool), matching `agent.py:1346` in the original handler — otherwise `_batch_summary`'s `failed = requested - ok` would go negative on the default `include_pools=True` path.

Then **in** `get_market_stats(...)` body, replace lines 1269-1357 with:

```python
    result = build_market_stats_response(
        include_boards=include_boards,
        include_pools=include_pools,
        target_date=target_date,
    )
    cached_store(get_quote_cache, cache_key, result)
    return _render_agent("market-stats", result, format)
```

(If `started` was tracked separately for any logging that referenced it, keep an `started = time.monotonic()` call before the helper — but the helper now owns its own timing for the summary block, so the outer one is dead.)

- [ ] **Step 5: Re-run existing market-stats tests + new helper test**

Run: `.venv/Scripts/python.exe -m pytest tests/test_agent_market_recap_schemas.py tests/test_agent_market_stats.py tests/test_agent_market_stats_schemas.py tests/test_agent_endpoints.py -v`
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add stock_data/api/routes/agent.py tests/test_agent_market_recap_schemas.py
git commit -m "refactor(agent): extract build_market_stats_response helper"
```

---

## Task 5: Add Index Quote Converter + Three-Index Helper

**Files:**
- Modify: `stock_data/api/routes/agent.py` (new helpers, near the existing `_build_minimal_quote_from_unified` at line 983)

**Interfaces:**
- Consumes: `UnifiedRealtimeQuote | None`, the bare 6-digit code.
- Produces: `IndexQuote | None`.

**Background:** `manager.get_index_realtime_quote(code)` returns `UnifiedRealtimeQuote | None`. We need a small field-by-field converter to `IndexQuote` (the 13-key schema). Mirrors the defensive `getattr(..., None)` style of `_build_minimal_quote_from_unified` at `agent.py:983`. **Important**: `UnifiedRealtimeQuote` (defined at `stock_data/data_provider/core/types.py:56`) uses different field names than `IndexQuote`: `open_price` (not `open`), `pre_close` (not `prev_close`), and **has no `update_time` field at all** — so the converter maps those three explicitly.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_agent_market_recap_schemas.py`:

```python
from stock_data.api.routes.agent import _index_quote_from_unified
from stock_data.data_provider.core.types import RealtimeSource, UnifiedRealtimeQuote
from stock_data.api.schemas import IndexQuote


def test_index_quote_from_unified_none_input():
    assert _index_quote_from_unified("000001", None) is None


def test_index_quote_from_unified_populates_all_fields():
    # UnifiedRealtimeQuote field names differ from IndexQuote — see
    # `stock_data/data_provider/core/types.py:56-100`. Notably:
    #   open_price (not open), pre_close (not prev_close),
    #   source is RealtimeSource enum, no update_time field.
    q = UnifiedRealtimeQuote(
        code="000001",
        name="上证综指",
        source=RealtimeSource.AKSHARE,
        price=3245.67,
        change_amount=12.34,
        change_pct=0.38,
        open_price=3230.0,
        high=3255.0,
        low=3228.0,
        pre_close=3233.33,
        volume=350_000_000,
        amount=4.5e10,
    )
    out = _index_quote_from_unified("000001", q)
    assert isinstance(out, IndexQuote)
    assert out.code == "000001"
    assert out.name == "上证综指"
    assert out.source == "akshare"  # .value of RealtimeSource.AKSHARE
    assert out.current_price == 3245.67
    assert out.change_pct == 0.38
    assert out.open == 3230.0
    assert out.prev_close == 3233.33
    assert out.volume == 350_000_000
    assert out.volume_unit == "share"
    assert out.amount == 4.5e10
    assert out.update_time is None  # always None on recap path


def test_index_quote_from_unified_handles_missing_fields():
    """All optional fields default to None / empty / 0.0 — no raises."""
    q = UnifiedRealtimeQuote(code="000001")  # only required field
    out = _index_quote_from_unified("000001", q)
    assert isinstance(out, IndexQuote)
    assert out.name == ""
    assert out.source == ""
    assert out.current_price == 0.0
    assert out.change_pct is None
    assert out.volume is None
    assert out.volume_unit == "share"
    assert out.update_time is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_agent_market_recap_schemas.py -v -k "index_quote_from_unified"`
Expected: `ImportError: cannot import name '_index_quote_from_unified'`.

- [ ] **Step 3: Add the converter and three-index helper**

In `stock_data/api/routes/agent.py`, after `_build_minimal_quote_from_unified` (line 983), add:

```python
def _index_quote_from_unified(code: str, q: UnifiedRealtimeQuote | None) -> IndexQuote | None:
    """Convert a UnifiedRealtimeQuote (or None) to an IndexQuote schema.

    Defensive: uses getattr with None defaults so fetcher-side field
    variance doesn't raise. Always sets volume_unit="share" per spec §3.4
    (indices are always quoted in shares, never wan_shou).

    Field-name mapping (UnifiedRealtimeQuote → IndexQuote):
      open_price   → open
      pre_close    → prev_close
      source.value → source  (RealtimeSource enum → str)
      update_time  → None    (UnifiedRealtimeQuote has no update_time)
    """
    if q is None:
        return None
    src = getattr(q, "source", None)
    src_str = src.value if hasattr(src, "value") else (src or "")
    return IndexQuote(
        code=code,
        name=getattr(q, "name", "") or "",
        source=src_str,
        current_price=float(getattr(q, "price", 0.0) or 0.0),
        change_amount=getattr(q, "change_amount", None),
        change_pct=getattr(q, "change_pct", None),
        open=getattr(q, "open_price", None),
        high=getattr(q, "high", None),
        low=getattr(q, "low", None),
        prev_close=getattr(q, "pre_close", None),
        volume=getattr(q, "volume", None),
        volume_unit="share",
        amount=getattr(q, "amount", None),
        update_time=None,
    )


# Fixed CSI index codes for the market-recap aggregation. v1 is hard-coded
# (上证 / 深成指 / 创业板); see spec §2.1 / §7 for the deferred
# configurable-list path.
_RECAP_INDICES: tuple[tuple[str, str], ...] = (
    ("sh", "000001"),
    ("shenzhen_composite", "399001"),
    ("chinext", "399006"),
)


def _build_three_index_quotes_block(
    manager,
) -> tuple[MarketRecapIndicesBlock, list[MarketRecapErrorEntry]]:
    """Fetch the 3 fixed index quotes, with per-index error isolation.

    Returns (block, errors). Each missing index is null in the block;
    its failure is appended to errors. Sequential (not concurrent)
    because manager.get_index_realtime_quote → _with_failover mutates
    per-fetcher circuit-breaker state and is not re-entrant safe.
    """
    block_dict: dict[str, IndexQuote | None] = {}
    errors: list[MarketRecapErrorEntry] = []
    for label, code in _RECAP_INDICES:
        try:
            q = manager.get_index_realtime_quote(code)
            block_dict[label] = _index_quote_from_unified(code, q)
        except Exception as exc:
            logger.warning(
                f"[agent/market-recap] indices.{label} ({code}) failed: {exc}",
                exc_info=True,
            )
            errors.append(
                MarketRecapErrorEntry(
                    block=f"indices.{label}",  # type: ignore[arg-type]
                    error=type(exc).__name__,
                    message=str(exc),
                )
            )
            block_dict[label] = None
    return MarketRecapIndicesBlock(**block_dict), errors
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/test_agent_market_recap_schemas.py -v`
Expected: all pass (3 converter tests + all prior tests).

- [ ] **Step 5: Commit**

```bash
git add stock_data/api/routes/agent.py tests/test_agent_market_recap_schemas.py
git commit -m "feat(agent): add index quote converter for market-recap"
```

---

## Task 6: Add `render_market_recap_as_md` MD Renderer

**Files:**
- Modify: `stock_data/api/routes/agent.py` (new renderer + helpers, near `render_market_stats_as_md` at line 1959)

**Interfaces:**
- Consumes: `MarketRecapResponse`.
- Produces: `str` (Markdown).

**Background:** Reuses `render_market_context_as_md` and `render_market_stats_as_md` (already exist in this file). Adds a hand-written 3-row index table. Per CLAUDE.md `?format=md` contract: every JSON field appears in the MD output.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_agent_market_recap_schemas.py`:

```python
from stock_data.api.routes.agent import render_market_recap_as_md
from stock_data.api.schemas import (
    MarketContextMessages,
    MarketRecapErrorEntry,
    MarketRecapIndicesBlock,
    MarketRecapResponse,
)


def _stub_response() -> MarketRecapResponse:
    # Use a real MarketContextMessages (NOT None) so render_market_context_as_md
    # exercises the full path — a `None` falls through to the JSON-fallback in
    # _render_markdown and silently passes the assertions below.
    ctx = MarketContextResponse.model_construct(
        trade_date="2026-09-03",
        is_trade_day=True,
        market_session="intraday",
        messages=MarketContextMessages(
            morning_briefing={"article_id": 1, "title": "早报"},
            market_recap=None,
            flash_news=[],
        ),
        summary={"requested": 3, "ok": 2, "failed": 1, "elapsed_ms": 10},
    )
    stats = MarketStatsResponse.model_construct(
        stocks=None,
        boards=None,
        limit_pools=None,
        errors=[],
        summary={"requested": 1, "ok": 1, "failed": 0, "elapsed_ms": 10},
    )
    indices = MarketRecapIndicesBlock(
        sh=IndexQuote(code="000001", name="上证综指", change_pct=0.5, amount=1.0),
        shenzhen_composite=IndexQuote(code="399001", name="深证成指", change_pct=1.2, amount=2.0),
        chinext=None,
    )
    return MarketRecapResponse(
        context=ctx,
        stats=stats,
        indices=indices,
        errors=[MarketRecapErrorEntry(block="indices.chinext", error="X", message="boom")],
        summary={"requested": 5, "ok": 4, "failed": 1, "elapsed_ms": 100},
    )


def test_render_market_recap_as_md_contains_all_sub_blocks():
    md = render_market_recap_as_md(_stub_response())
    # Reuses context renderer (real messages, not None — exercises the markdown path)
    assert "trade_date" in md
    assert "is_trade_day" in md
    assert "早报" in md  # from MarketContextMessages.morning_briefing
    # Reuses stats renderer
    assert "stocks" in md or "boards" in md
    # Index block — codes + names appear for non-null rows
    assert "000001" in md
    assert "399001" in md
    assert "上证综指" in md
    assert "深证成指" in md
    # Error block surfaced
    assert "indices.chinext" in md
    assert "boom" in md


def test_render_market_recap_as_md_includes_all_13_indexquote_columns():
    """Spec §3.5: the index table must include all 13 IndexQuote columns per row
    to satisfy the CLAUDE.md `?format=md` 'no field dropped' contract."""
    md = render_market_recap_as_md(_stub_response())
    expected_cols = [
        "code", "name", "source", "current_price", "change_amount",
        "change_pct", "open", "high", "low", "prev_close",
        "volume", "volume_unit", "amount", "update_time",
    ]
    missing = [c for c in expected_cols if c not in md]
    assert not missing, f"IndexQuote columns missing from MD: {missing}"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_agent_market_recap_schemas.py -v -k "render_market_recap_as_md"`
Expected: `ImportError: cannot import name 'render_market_recap_as_md'`.

- [ ] **Step 3: Add the renderer + sub-renderers**

In `stock_data/api/routes/agent.py`, after `render_market_stats_as_md` (line 1959), add:

```python
def _render_recap_indices_table_md(indices: MarketRecapIndicesBlock) -> str:
    """Render the 3-index block as a markdown table with ALL 13 IndexQuote
    columns (per spec §3.5 + CLAUDE.md `?format=md` "no field dropped"
    contract). Null rows are rendered with explicit `—` markers.

    Note: this table is wider than a human-friendly recap table, but the
    recap endpoint targets LLM agents that prefer machine-readability.
    The CLAUDE.md contract is satisfied by listing every IndexQuote field
    by name, regardless of value.
    """
    lines: list[str] = ["## 指数快讯", ""]
    cols = [
        "code", "name", "source", "current_price", "change_amount",
        "change_pct", "open", "high", "low", "prev_close",
        "volume", "volume_unit", "amount", "update_time",
    ]
    lines.append("| " + " | ".join(cols) + " |")
    lines.append("| " + " | ".join("---" for _ in cols) + " |")
    for label, code, label_cn in (
        ("sh", "000001", "上证综指"),
        ("shenzhen_composite", "399001", "深证成指"),
        ("chinext", "399006", "创业板指"),
    ):
        q = getattr(indices, label)
        if q is None:
            lines.append("| " + " | ".join(["—"] * len(cols)) + " |")
            continue
        # Helper: format a numeric field with `—` for None
        def _num(v, fmt: str) -> str:
            if v is None:
                return "—"
            if isinstance(v, float):
                return format(v, fmt)
            return str(v)

        cells = [
            q.code or code,
            q.name or label_cn,
            q.source or "—",
            _num(q.current_price, ".2f"),
            _num(q.change_amount, ".2f"),
            (
                f"{q.change_pct:+.2f}%"
                if isinstance(q.change_pct, (int, float))
                else "—"
            ),
            _num(q.open, ".2f"),
            _num(q.high, ".2f"),
            _num(q.low, ".2f"),
            _num(q.prev_close, ".2f"),
            _num(q.volume, ",d"),
            q.volume_unit or "share",
            _num(q.amount, ".0f"),
            q.update_time or "—",
        ]
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines)


def _render_recap_errors_md(errors: list[MarketRecapErrorEntry]) -> str:
    """Render the top-level errors block as a bullet list."""
    if not errors:
        return ""
    lines = ["## 错误", ""]
    for e in errors:
        lines.append(f"- `{e.block}`: {e.error} — {e.message}")
    return "\n".join(lines)


def render_market_recap_as_md(p: MarketRecapResponse) -> str:
    """Render the market-recap aggregation as Markdown.

    Reuses render_market_context_as_md and render_market_stats_as_md
    for the verbatim sub-blocks (preserves their MD-completeness
    contracts). Adds a 3-row index table and a top-level error block.
    Sections are joined with `\\n\\n---\\n\\n` so each is visually
    distinct in markdown renderers.
    """
    parts = [
        render_market_context_as_md(p.context),
        render_market_stats_as_md(p.stats),
        _render_recap_indices_table_md(p.indices),
    ]
    err_md = _render_recap_errors_md(p.errors)
    if err_md:
        parts.append(err_md)
    return "\n\n---\n\n".join(parts)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/test_agent_market_recap_schemas.py -v`
Expected: all pass.

- [ ] **Step 5: Register the renderer in `_MD_TEMPLATES`**

Find `_MD_TEMPLATES` (around line 1980 in `agent.py`) and add a new entry:

```python
_MD_TEMPLATES: dict[str, Callable] = {
    ...
    "market-stats": render_market_stats_as_md,
    "market-recap": render_market_recap_as_md,   # <-- add this line
    "boards/batch-profile": render_boards_batch_profile_as_md,
}
```

- [ ] **Step 6: Run all tests to confirm no regressions**

Run: `.venv/Scripts/python.exe -m pytest tests/test_agent_market_recap_schemas.py tests/test_agent_market_stats.py tests/test_agent_market_stats_schemas.py tests/test_agent_endpoints.py -v`
Expected: all pass.

- [ ] **Step 7: Commit**

```bash
git add stock_data/api/routes/agent.py tests/test_agent_market_recap_schemas.py
git commit -m "feat(agent): add render_market_recap_as_md"
```

---

## Task 7: Add `get_market_recap` Route Handler + Endpoint Tests

**Files:**
- Modify: `stock_data/api/routes/agent.py` (new handler at the end of the file, after `get_market_stats`)
- Modify: `tests/test_agent_market_recap.py` (create, with 6 endpoint tests from spec §6)

**Interfaces:**
- Consumes: query params `flash_limit`, `include_boards`, `include_pools`, `trade_date`, `format`. Internal: `_batch_summary`, `asyncio.gather`, `asyncio.to_thread`, `cached_lookup`/`cached_store` on `get_quote_cache`, `make_market_recap_cache_key`, `_render_agent`.
- Produces: `Response` (JSON or MD, dispatched by `_render_agent("market-recap", payload, format)`).

**Background:** TDD per the 6 spec §6 tests. Each sub-task is one cycle: write test → fail → implement/extend handler → pass → commit. The handler is built up across all 6 cycles.

- [ ] **Step 1: Write test 1 — happy path (TDD cycle 1)**

Create `tests/test_agent_market_recap.py`:

```python
"""Endpoint tests for GET /api/v1/agent/market-recap."""

from fastapi.testclient import TestClient

from stock_data.api.routes import agent as agent_mod
from stock_data.api.schemas import (
    IndexQuote,
    MarketContextMessages,
    MarketContextResponse,
    MarketRecapIndicesBlock,
    MarketStatsResponse,
)


def _ctx_stub():
    # Use a real MarketContextMessages (NOT None) so the response carries
    # the messages sub-object end-to-end. A `None` here makes
    # render_market_context_as_md raise and silently fall through to the
    # JSON-fallback in `_render_markdown`, which would mask regressions.
    return MarketContextResponse.model_construct(
        trade_date="2026-09-03",
        is_trade_day=True,
        market_session="intraday",
        messages=MarketContextMessages(
            morning_briefing=None, market_recap=None, flash_news=[]
        ),
        summary={"requested": 3, "ok": 3, "failed": 0, "elapsed_ms": 10},
    )


def _stats_stub():
    return MarketStatsResponse.model_construct(
        stocks=None,
        boards=None,
        limit_pools=None,
        errors=[],
        summary={"requested": 1, "ok": 1, "failed": 0, "elapsed_ms": 10},
    )


def test_market_recap_happy_path(monkeypatch):
    """All 5 sub-blocks OK → 200, all populated, errors empty, summary.ok == 5."""
    from stock_data.server import app

    # Stub the two extracted builders + the index helper
    monkeypatch.setattr(agent_mod, "build_market_context_response", lambda **_: _ctx_stub())
    monkeypatch.setattr(agent_mod, "build_market_stats_response", lambda **_: _stats_stub())
    monkeypatch.setattr(
        agent_mod,
        "_build_three_index_quotes_block",
        lambda mgr: (
            MarketRecapIndicesBlock(
                sh=IndexQuote(code="000001", change_pct=0.5),
                shenzhen_composite=IndexQuote(code="399001", change_pct=1.2),
                chinext=IndexQuote(code="399006", change_pct=-0.3),
            ),
            [],
        ),
    )

    client = TestClient(app)
    resp = client.get("/api/v1/agent/market-recap")
    assert resp.status_code == 200
    body = resp.json()
    assert body["errors"] == []
    assert body["summary"]["ok"] == 5
    assert body["indices"]["sh"]["code"] == "000001"
    assert body["indices"]["shenzhen_composite"]["code"] == "399001"
    assert body["indices"]["chinext"]["code"] == "399006"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_agent_market_recap.py::test_market_recap_happy_path -v`
Expected: `404` (route not registered) or `AssertionError` (handler exists but returns wrong shape).

- [ ] **Step 3: Add minimal `get_market_recap` handler (passes happy path only)**

First, **add the new Pydantic symbols to the existing import block** in `stock_data/api/routes/agent.py`. Find the `from ..schemas import (...)` block (around lines 70-101) and extend it:

```python
    MarketRecapErrorEntry,
    MarketRecapIndicesBlock,
    MarketRecapResponse,
```

(If `asyncio` is not yet imported at the top of `agent.py`, also add `import asyncio` near the existing top-level imports. Check first.)

Then append the new handler **after** the existing `get_market_stats` handler (around line 1747 of the current file):

```python
@router.get(
    "/agent/market-recap",
    response_model=MarketRecapResponse,
    responses={
        400: {"model": ErrorResponse, "description": "Invalid trade_date"},
        422: {"model": ErrorResponse, "description": "format not in (json, md)"},
        500: {"model": ErrorResponse, "description": "Server error"},
    },
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
async def get_market_recap(
    flash_limit: int = Query(
        default=20,
        ge=1,
        le=200,
        description="快讯条数上限 1-200;默认 20;透传给 market-context.",
    ),
    include_boards: bool = Query(default=True, description="是否包含板块块;透传给 market-stats."),
    include_pools: bool = Query(default=True, description="是否包含涨跌停池块;透传给 market-stats."),
    # NOTE: no `trade_date` query param — recap always targets the server-resolved
    # latest trade date. See spec §2.1 for the rationale.
    format: str = Query(
        default="json",
        pattern="^(json|md)$",
        description="Output format. json=application/json (default); md=text/markdown.",
    ),
) -> Response:
    """Server-side aggregation of market-context + market-stats + 3 index quotes.

    Per spec §3.6:
    - per-block error isolation (5 blocks: context, stats, 3 indices);
    - context/stats builders are reused from /agent/market-context and
      /agent/market-stats (same cache keys, same Pydantic shapes);
    - 3 indices fetched sequentially (manager singleton not re-entrant safe
      for concurrent _with_failover).
    - top-level cache via make_market_recap_cache_key (60s TTL).
    - always targets the latest trade date on or before today (no user
      date input — see spec §2.1).
    """
    # 1. resolve target_date via trade_calendar (no user input — always latest)
    today_str = datetime.now(_CST).date().isoformat()
    target_date = (
        trade_calendar.get_latest_trade_date_on_or_before(today_str) or today_str
    )

    # 2. top-level cache lookup
    cache_key = make_market_recap_cache_key(flash_limit, include_boards, include_pools)
    hit = cached_lookup(get_quote_cache, cache_key, "agent_market_recap")
    if hit is not None:
        return _render_agent("market-recap", hit, format)

    # 3. parallel fan-out via asyncio.gather (handler is async; sync helpers
    #    wrapped in asyncio.to_thread to avoid blocking the event loop)
    started = time.monotonic()
    manager = get_manager()
    errors: list[MarketRecapErrorEntry] = []
    requested = 5

    async def _gather_context() -> MarketContextResponse | None:
        try:
            return await asyncio.to_thread(
                build_market_context_response,
                flash_limit=flash_limit,
                target_date=target_date,
                today_str=today_str,
            )
        except Exception as exc:
            logger.warning(f"[agent/market-recap] context failed: {exc}", exc_info=True)
            errors.append(
                MarketRecapErrorEntry(block="context", error=type(exc).__name__, message=str(exc))
            )
            return None

    async def _gather_stats() -> MarketStatsResponse | None:
        try:
            return await asyncio.to_thread(
                build_market_stats_response,
                include_boards=include_boards,
                include_pools=include_pools,
                target_date=target_date,
            )
        except Exception as exc:
            logger.warning(f"[agent/market-recap] stats failed: {exc}", exc_info=True)
            errors.append(
                MarketRecapErrorEntry(block="stats", error=type(exc).__name__, message=str(exc))
            )
            return None

    async def _gather_indices() -> MarketRecapIndicesBlock:
        block, idx_errors = await asyncio.to_thread(_build_three_index_quotes_block, manager)
        errors.extend(idx_errors)
        return block

    context_resp, stats_resp, indices_block = await asyncio.gather(
        _gather_context(), _gather_stats(), _gather_indices()
    )

    # 4. assemble response; fail-soft: any None sub-block is rendered as null
    if context_resp is None:
        context_resp = _ctx_stub_null()
    if stats_resp is None:
        stats_resp = _stats_stub_null()

    # requested / ok counters
    ok = (
        (1 if context_resp is not None and not _is_placeholder_stub(context_resp) else 0)
        + (1 if stats_resp is not None and not _is_placeholder_stub(stats_resp) else 0)
        + (1 if indices_block.sh is not None else 0)
        + (1 if indices_block.shenzhen_composite is not None else 0)
        + (1 if indices_block.chinext is not None else 0)
    )

    result = MarketRecapResponse(
        context=context_resp,
        stats=stats_resp,
        indices=indices_block,
        errors=errors,
        summary=_batch_summary(requested, ok, started),
    )
    cached_store(get_quote_cache, cache_key, result)
    return _render_agent("market-recap", result, format)
```

The handler references two small helpers (`_ctx_stub_null`, `_stats_stub_null`, `_is_placeholder_stub`) and the module-level imports `asyncio`, `MarketRecapErrorEntry`. **Add these helpers** above the handler:

```python
import asyncio


def _ctx_stub_null() -> MarketContextResponse:
    """All-null placeholder used when the context builder raises."""
    return MarketContextResponse.model_construct(
        trade_date="",
        is_trade_day=False,
        market_session="closed",  # type: ignore[arg-type]
        messages=None,
        summary={"requested": 0, "ok": 0, "failed": 0, "elapsed_ms": 0},
    )


def _stats_stub_null() -> MarketStatsResponse:
    """All-null placeholder used when the stats builder raises."""
    return MarketStatsResponse.model_construct(
        stocks=None,
        boards=None,
        limit_pools=None,
        errors=[],
        summary={"requested": 0, "ok": 0, "failed": 0, "elapsed_ms": 0},
    )


def _is_placeholder_stub(m: MarketContextResponse | MarketStatsResponse) -> bool:
    """The null-placeholders all have requested == 0; real builders always > 0."""
    return bool(m.summary) and m.summary.get("requested", 0) == 0
```

(If `asyncio` is already imported at the top of `agent.py`, the `import asyncio` line is redundant — check before adding.)

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/test_agent_market_recap.py::test_market_recap_happy_path -v`
Expected: PASS.

- [ ] **Step 5: Write test 2 — context block fails, others OK**

Append to `tests/test_agent_market_recap.py`:

```python
def test_market_recap_context_block_fails_others_ok(monkeypatch):
    """context builder raises → response still 200, context field is the null stub,
    errors[] has {block: 'context'}, other blocks still populated."""
    from stock_data.server import app

    def _raise(**_):
        raise RuntimeError("context boom")

    monkeypatch.setattr(agent_mod, "build_market_context_response", _raise)
    monkeypatch.setattr(agent_mod, "build_market_stats_response", lambda **_: _stats_stub())
    monkeypatch.setattr(
        agent_mod,
        "_build_three_index_quotes_block",
        lambda mgr: (
            MarketRecapIndicesBlock(
                sh=IndexQuote(code="000001"),
                shenzhen_composite=IndexQuote(code="399001"),
                chinext=IndexQuote(code="399006"),
            ),
            [],
        ),
    )

    client = TestClient(app)
    resp = client.get("/api/v1/agent/market-recap")
    assert resp.status_code == 200
    body = resp.json()
    assert any(e["block"] == "context" for e in body["errors"])
    assert body["summary"]["failed"] == 1
    # context is the null stub (requested==0), stats + indices are real
    assert body["context"]["summary"]["requested"] == 0
    assert body["stats"]["summary"]["requested"] == 1
    assert body["indices"]["sh"]["code"] == "000001"
```

- [ ] **Step 6: Run test to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/test_agent_market_recap.py::test_market_recap_context_block_fails_others_ok -v`
Expected: PASS (the handler already implements this — Step 3 covered it).

- [ ] **Step 7: Write test 3 — index failure isolated**

Append to `tests/test_agent_market_recap.py`:

```python
def test_market_recap_index_failure_isolated(monkeypatch):
    """_build_three_index_quotes_block returns (block, errors) with one error;
    that index is null, others populated, response is 200."""
    from stock_data.server import app

    monkeypatch.setattr(agent_mod, "build_market_context_response", lambda **_: _ctx_stub())
    monkeypatch.setattr(agent_mod, "build_market_stats_response", lambda **_: _stats_stub())

    def _fake_block(_mgr):
        return (
            MarketRecapIndicesBlock(
                sh=IndexQuote(code="000001"),
                shenzhen_composite=None,  # <-- the failed one
                chinext=IndexQuote(code="399006"),
            ),
            [
                agent_mod.MarketRecapErrorEntry(
                    block="indices.shenzhen_composite",
                    error="DataFetchError",
                    message="upstream timeout",
                )
            ],
        )

    monkeypatch.setattr(agent_mod, "_build_three_index_quotes_block", _fake_block)

    client = TestClient(app)
    resp = client.get("/api/v1/agent/market-recap")
    assert resp.status_code == 200
    body = resp.json()
    assert body["indices"]["sh"]["code"] == "000001"
    assert body["indices"]["shenzhen_composite"] is None
    assert body["indices"]["chinext"]["code"] == "399006"
    assert any(
        e["block"] == "indices.shenzhen_composite" for e in body["errors"]
    )
```

- [ ] **Step 8: Run test to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/test_agent_market_recap.py::test_market_recap_index_failure_isolated -v`
Expected: PASS (handler's `_gather_indices` already extends the errors list with the helper's output).

- [ ] **Step 9: Write test 4 — cache hit skips fan-out**

Append to `tests/test_agent_market_recap.py`:

```python
def test_market_recap_cache_hit_skips_fanout(monkeypatch):
    """Second call within TTL reuses the cached response; the underlying builders
    are NOT invoked a second time."""
    from stock_data.api.cache import get_quote_cache, make_market_recap_cache_key
    from stock_data.server import app

    # Clear any stale entry from prior tests.
    cache_key = make_market_recap_cache_key(20, True, True)
    get_quote_cache.pop(cache_key, None)

    call_counts = {"context": 0, "stats": 0, "indices": 0}

    def _counted_ctx(**_):
        call_counts["context"] += 1
        return _ctx_stub()

    def _counted_stats(**_):
        call_counts["stats"] += 1
        return _stats_stub()

    def _counted_indices(_mgr):
        call_counts["indices"] += 1
        return (
            MarketRecapIndicesBlock(
                sh=IndexQuote(code="000001"),
                shenzhen_composite=IndexQuote(code="399001"),
                chinext=IndexQuote(code="399006"),
            ),
            [],
        )

    monkeypatch.setattr(agent_mod, "build_market_context_response", _counted_ctx)
    monkeypatch.setattr(agent_mod, "build_market_stats_response", _counted_stats)
    monkeypatch.setattr(agent_mod, "_build_three_index_quotes_block", _counted_indices)

    # Two consecutive calls — first misses + populates the cache, second hits.
    # The 3-segment cache key (no trade_date) makes the hit deterministic.
    client = TestClient(app)
    r1 = client.get("/api/v1/agent/market-recap")
    r2 = client.get("/api/v1/agent/market-recap")
    assert r1.status_code == 200
    assert r2.status_code == 200
    assert call_counts["context"] == 1
    assert call_counts["stats"] == 1
    assert call_counts["indices"] == 1
```

- [ ] **Step 10: Run test to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/test_agent_market_recap.py::test_market_recap_cache_hit_skips_fanout -v`
Expected: PASS (the handler already does `cached_lookup` at the top — first call misses and populates, second hits).

- [ ] **Step 11: Write test 5 — `?format=md` no field drop**

Append to `tests/test_agent_market_recap.py`:

```python
def test_market_recap_md_format_no_field_drop(monkeypatch):
    """`?format=md` must include every JSON field name from the response."""
    from stock_data.server import app

    monkeypatch.setattr(agent_mod, "build_market_context_response", lambda **_: _ctx_stub())
    monkeypatch.setattr(agent_mod, "build_market_stats_response", lambda **_: _stats_stub())
    monkeypatch.setattr(
        agent_mod,
        "_build_three_index_quotes_block",
        lambda mgr: (
            MarketRecapIndicesBlock(
                sh=IndexQuote(code="000001", name="上证综指", change_pct=0.5, amount=1.0),
                shenzhen_composite=IndexQuote(code="399001", name="深证成指", change_pct=1.2, amount=2.0),
                chinext=IndexQuote(code="399006", name="创业板指", change_pct=-0.3, amount=3.0),
            ),
            [],
        ),
    )

    client = TestClient(app)
    resp = client.get("/api/v1/agent/market-recap?format=md")
    assert resp.status_code == 200
    md = resp.text

    # Every JSON field name from MarketRecapResponse / IndexQuote / errors
    # must appear in the rendered markdown. The list is the union of:
    # - MarketRecapResponse top-level: context, stats, indices, errors, summary
    # - MarketRecapIndicesBlock: sh, shenzhen_composite, chinext
    # - IndexQuote keys
    # - MarketRecapErrorEntry: block, error, message
    required = [
        "context", "stats", "indices", "errors", "summary",
        "sh", "shenzhen_composite", "chinext",
        "code", "name", "change_pct", "amount", "volume",
        "block", "error", "message",
        "000001", "399001", "399006",
        "上证综指", "深证成指", "创业板指",
    ]
    missing = [k for k in required if k not in md]
    assert not missing, f"MD output missing fields: {missing}"
```

- [ ] **Step 12: Run test to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/test_agent_market_recap.py::test_market_recap_md_format_no_field_drop -v`
Expected: PASS (renderer already produces table columns + error list + reuses context/stats MD renderers).

(There is no test 6 for `?trade_date=` 400 validation — recap has no
`trade_date` query param after the scope-reduction, so the only 400
that could fire would be a 422 from `format` validation, which
FastAPI handles via the `pattern` regex. Pinned indirectly by the
MD test which passes `format=md`.)

- [ ] **Step 13: Run the full agent test suite + explorer manifest**

Run: `.venv/Scripts/python.exe -m pytest tests/test_agent_market_recap.py tests/test_agent_market_recap_schemas.py tests/test_agent_market_stats.py tests/test_agent_market_stats_schemas.py tests/test_agent_endpoints.py tests/test_explorer_manifest_endpoint.py -v`
Expected: all pass.

(If `test_explorer_manifest_endpoint.py` fails because the new endpoint isn't in the manifest, the manifest is rebuilt on every request — no cache invalidation needed. But verify the test asserts presence of routes decorated with `@endpoint_meta`, which the new route is.)

- [ ] **Step 14: Commit**

```bash
git add stock_data/api/routes/agent.py tests/test_agent_market_recap.py
git commit -m "feat(agent): add GET /agent/market-recap aggregation endpoint"
```

---

## Task 8: Final Verification + Server Smoke Test

**Files:** none modified.

**Background:** Run the wider test suite to confirm no regressions, then boot the server briefly to confirm the new endpoint is reachable from the live app.

- [ ] **Step 1: Run the full default test suite**

Run: `.venv/Scripts/python.exe -m pytest`
Expected: all pass except any pre-existing xfail markers (live_network / requires_token are skipped by default per CLAUDE.md).

- [ ] **Step 2: Boot the server and curl the new endpoint**

In one terminal:
```bash
.venv/Scripts/python.exe -m stock_data.server
```

Wait for `Uvicorn running on http://0.0.0.0:8888`.

In another terminal:
```bash
curl -s "http://localhost:8888/api/v1/agent/market-recap?format=md" | head -50
```

Expected: 200 response with markdown containing the 3-row index table.

(If `live_network` upstream is unreachable in the dev environment, the 5 builders may all return null blocks and the response will be partial — that's fine, the smoke test only confirms routing works.)

- [ ] **Step 3: Confirm the manifest picks up the new endpoint**

In the same browser/curl session:
```bash
curl -s "http://localhost:8888/control/api-manifest" | python -c "import json,sys; m=json.load(sys.stdin); print([r['path'] for r in m['routes'] if 'market-recap' in r['path']])"
```

Expected: `['/api/v1/agent/market-recap']`.

- [ ] **Step 4: Stop the server**

In the terminal running `python -m stock_data.server`, press `Ctrl-C`.

- [ ] **Step 5: Commit (no source changes; this is a verification-only task)**

No commit needed if Steps 1-4 all pass cleanly. If any step required a code fix, that fix goes in its own commit.

---

## Self-Review

**Spec coverage:**

| Spec § | Requirement | Task |
|---|---|---|
| §2.1 | `MarketRecapResponse` shape (context / stats / indices / errors / summary) | Task 1, Task 7 |
| §2.1 | 3 fixed indices (上证 / 深成指 / 创业板) | Task 5 (`_RECAP_INDICES`) |
| §2.1 | Query params (flash_limit, include_boards, include_pools, format; **no trade_date**) | Task 7 |
| §2.1 | `errors[].block` literals | Task 1, Task 5 |
| §2.1 | Server-resolved target_date via trade_calendar | Task 7 (handler body) |
| §2.2 | Verbatim context/stats shape (Pydantic composition, not re-modeling) | Task 1 |
| §3.1 | Extract `build_market_context_response` + `build_market_stats_response` helpers | Tasks 3, 4 |
| §3.2 | `get_market_recap` async handler with `asyncio.gather` + `to_thread` | Task 7 |
| §3.3 | `IndexQuote` conversion from `UnifiedRealtimeQuote` (open_price / pre_close / no update_time) | Task 5 |
| §3.4 | Cache: `make_market_recap_cache_key` (3-segment, no trade_date) + reuse of context/stats key builders | Task 2, Task 3, Task 4, Task 7 |
| §3.5 | MD renderer reusing existing renderers + 14-column index table (all IndexQuote fields + `update_time`) | Task 6 |
| §3.6 | Per-block error isolation | Task 5 (`_build_three_index_quotes_block`), Task 7 (handler try/except) |
| §3.7 | Schema models | Task 1 |
| §4 | Files touched | Tasks 1-7 each enumerate their file edits |
| §5 | Token economics discussion | (Spec-only, no code) |
| §6 | 5 test cases (happy path, context fail, index fail, cache hit, MD completeness) — invalid_trade_date removed since param dropped | Task 7 (one per cycle), Task 6 (renderer-level MD completeness subtest) |
| §7 | Migration / rollout (no DB change, no breaking change) | Verified by Task 8 regression run |

**Type / name consistency check (across tasks):**

- `_RECAP_INDICES` defined in Task 5, consumed in Task 5 only (single use). ✓
- `build_market_context_response(flash_limit, target_date, today_str)` defined in Task 3, called from Task 7 with kwargs matching. ✓
- `build_market_stats_response(include_boards, include_pools, target_date)` defined in Task 4, called from Task 7 with kwargs matching. ✓
- `_build_three_index_quotes_block(manager)` defined in Task 5, called from Task 7 with positional arg. ✓
- `_index_quote_from_unified(code, q)` defined in Task 5, called from Task 5 only. ✓
- `render_market_recap_as_md(p)` defined in Task 6, registered in `_MD_TEMPLATES["market-recap"]` (Task 6 Step 5), dispatched from Task 7 handler via `_render_agent("market-recap", result, format)`. ✓
- `MarketRecapErrorEntry` defined in Task 1, used in Tasks 5, 7. ✓
- `MarketRecapIndicesBlock` defined in Task 1, used in Tasks 5, 7. ✓
- `MarketRecapResponse` defined in Task 1, used in Tasks 6, 7. ✓
- `make_market_recap_cache_key(flash_limit, include_boards, include_pools)` defined in Task 2, called from Task 7. ✓

**Placeholder scan:**

No `TBD` / `TODO` / "implement later" / "similar to Task N" markers in the plan body. Every code block is concrete and runnable as written.

**Scope check:**

The plan is one feature (one new endpoint + supporting helpers + tests). No decomposition needed.

---

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-09-03-market-recap.md`. Two execution options:

1. **Subagent-Driven (recommended)** — I dispatch a fresh subagent per task, review between tasks, fast iteration.
2. **Inline Execution** — Execute tasks in this session using `executing-plans`, batch execution with checkpoints.

Which approach?
