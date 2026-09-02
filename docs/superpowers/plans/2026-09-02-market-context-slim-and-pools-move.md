# Market-Context Slim + Move ZT/DT Pools to Market-Stats Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Slim `/api/v1/agent/market-context` to messages-only (drop dragon-tiger + zt/dt pools blocks) and absorb zt/dt into `/api/v1/agent/market-stats` as a third per-block aggregation.

**Architecture:** Additive schema + cache-key changes first (Task 1), TDD-driven handler + MD renderer for the new market-stats pools block (Task 2), then a single sweeping removal for market-context (Task 3), then test cleanup (Task 4). Each task is a single commit on a `feat/agent-market-stats-pools` branch.

**Tech Stack:** Python 3.12, FastAPI, Pydantic v2, pytest, monkeypatch-based route-layer mocking (no live_network).

**Spec:** `docs/superpowers/specs/2026-09-02-market-context-and-market-stats-redesign-design.md`

**Branch strategy:** Per CLAUDE.md "Skip branch for trivial changes", `*.md` commits go to master. This plan file AND the spec file at `docs/superpowers/specs/2026-09-02-market-context-and-market-stats-redesign-design.md` are `*.md` → both already on master. Implementation commits → `feat/agent-market-stats-pools` branch (Python server code per project rule).

**Intermediate red state warning:** Between Task 3 commit and Task 4 commit, ~10 existing market-context tests will fail (they assert pre-slim fields: `limit_pools`, `dragon_tiger`, `make_market_context_cache_key(..., session)`). Task 4 cleans them up. Branch is NOT fast-forward-mergeable until Task 4 lands. CI on master stays green throughout because the branch isn't merged until Task 4.12 — no `git push origin master` happens until the full 4-task sequence is green.

**Cache key shape drift:** Task 1 changes `agent_market_stats:{bool}` → `agent_market_stats:{bool}:{bool}:{str}`. Existing in-flight cache entries from before the change will orphan and self-expire in 60s (TTL); no manual flush required. The drift is unavoidable because the previous 1-arg signature didn't carry enough information to distinguish `(include_pools=true, today)` from `(include_pools=false, today)`.

---

## Global Constraints

These apply to every task in this plan:

- **Python venv**: `.venv/Scripts/python.exe` (CLAUDE.md "Common Commands"). System `python` will silently break akshare-routed paths.
- **Default `pytest`** skips `live_network` and `requires_token` markers (per `pyproject.toml` `addopts`). Fast dev loop. No marker override needed for these tasks — all tests mock at the route layer.
- **TDD**: write failing test first, run it (verify it fails for the right reason), implement minimal code, run again (verify pass), commit.
- **Per-project anti-patterns** (CLAUDE.md + memory):
  - No hardcoded fetcher class in manager routes — already true for these endpoints.
  - Don't add `DataCapability` flags — neither endpoint uses one.
  - **Don't** leak `ts_code` suffixes — pools return bare 6-digit codes; already true.
  - **Don't** mix inline imports — keep top-level imports.
  - **Don't** assume test contract from spec — tests pin the contract (memory: `[[test-wins-spec-code-test-disagree]]`).
  - **Don't** cache realtime quote data in SQLite — pools are fetched live per request; unchanged.
- **Response cache**: shared `get_quote_cache` 60s TTL via `cached_lookup` / `cached_store`. Existing convention; both endpoints use it.
- **Pydantic v2** (`BaseModel.model_validator(mode="before")`, `@model_serializer`, `Field(default=None)`).
- **Code style**: ruff-formatted; run `ruff format .` before commits.
- **Commit messages**: end with `Co-Authored-By: Claude <noreply@anthropic.com>`.
- **Don't write to CLAUDE.md** unless explicitly asked. Spec and plan are the project substrate; changes here don't need CLAUDE.md updates (the project already pins market-stats / market-context semantics via the spec).

---

## File Structure

Files touched by this plan:

| File | Responsibility | Tasks |
|---|---|---|
| `stock_data/api/schemas.py` | Add `MarketStatsLimitPools`; extend `MarketStatsErrorEntry.block` literal; add `limit_pools` field on `MarketStatsResponse`; **delete** `MarketContextLimitPools` + `MarketContextDragonTiger*`; remove fields from `MarketContextResponse` | 1, 3 |
| `stock_data/api/cache.py` | Extend `make_market_stats_cache_key` signature (add `include_pools`, `trade_date`); slim `make_market_context_cache_key` (drop `session`) | 1, 3 |
| `stock_data/api/routes/agent.py` | New `_compute_limit_pools_block` helper; new `_md_limit_pools_block` MD helper; extend `get_market_stats` with `include_pools` + `trade_date` query params + pools block; slim `get_market_context` (drop pools/dragon-tiger attempts); delete `_summarize_dragon_tiger` helper; update `render_market_context_as_md` (drop pools/dragon-tiger sections); update `render_market_stats_as_md` (call `_md_limit_pools_block`) | 2, 3 |
| `tests/test_agent_market_stats_schemas.py` | Add tests for `MarketStatsLimitPools` (populated/null/partial); add tests for new `MarketStatsErrorEntry.block` literals; add test for `MarketStatsResponse.limit_pools` default | 1 |
| `tests/test_agent_market_stats.py` | Update existing tests (`test_market_stats_returns_200`, `test_stocks_upstream_failure_does_not_affect_boards`, `test_boards_upstream_failure_does_not_affect_stocks`, `test_both_blocks_fail`, `test_include_boards_false_skips_boards_upstream`, `test_cache_key_includes_include_boards`, `test_market_stats_cache_hit_skips_upstream`); add new tests for the pools block | 2 |
| `tests/test_agent_endpoints.py` | Update `TestMarketContext` tests: delete obsolete dragon-tiger/pool tests; rename + update `test_happy_path_all_blocks_present` to assert no pools/dragon-tiger in response; update `test_trade_date_query_param`; update `test_cache_hit_same_flash_limit_and_date`; update `test_market_context_md`; add `test_market_context_cache_key_omits_session` | 4 |

Decomposition rationale: schema is the contract; cache key is the lookup primitive; handler orchestrates; MD renderer projects. Splitting by responsibility (not by technical layer) means each task commits one logical unit and reviewers can reject one without rejecting its neighbor.

---

## Task 1: Schema additions + cache key extension (additive, no behavior change)

**Files:**
- Modify: `stock_data/api/schemas.py:2085-2105` (extend `MarketStatsErrorEntry`, add `MarketStatsLimitPools`, add `limit_pools` field on `MarketStatsResponse`)
- Modify: `stock_data/api/cache.py:541-548` (extend `make_market_stats_cache_key`)
- Modify: `tests/test_agent_market_stats_schemas.py:1-79` (add new schema tests)
- Modify: `tests/test_agent_market_stats.py:232-235` (update cache key test for new signature)

**Interfaces:**
- Consumes: existing `StockStats`, `BoardStats`, `MarketStatsResponse` schemas
- Produces:
  - `class MarketStatsLimitPools(BaseModel)` with fields `zt: list[dict] | None = None`, `dt: list[dict] | None = None`
  - `MarketStatsErrorEntry.block: Literal["stocks", "boards", "zt_pool", "dt_pool"]`
  - `MarketStatsResponse.limit_pools: MarketStatsLimitPools | None = None`
  - `make_market_stats_cache_key(include_boards: bool, include_pools: bool, trade_date: str) -> str` returning `f"agent_market_stats:{include_boards}:{include_pools}:{trade_date}"`

This task is purely additive — no existing test should break. If a test breaks here, stop and investigate before committing.

- [ ] **Step 1.1: Write failing tests for new schemas**

Append to `tests/test_agent_market_stats_schemas.py`:

```python
def test_market_stats_limit_pools_both_populated():
    """zt + dt both populated — happy path."""
    from stock_data.api.schemas import MarketStatsLimitPools

    p = MarketStatsLimitPools(
        zt=[{"code": "600519", "name": "茅台"}],
        dt=[{"code": "000001", "name": "平安"}],
    )
    assert p.zt is not None and len(p.zt) == 1
    assert p.dt is not None and len(p.dt) == 1
    assert p.zt[0]["code"] == "600519"


def test_market_stats_limit_pools_both_null():
    """Both null — per-pool upstream failure or include_pools=false."""
    from stock_data.api.schemas import MarketStatsLimitPools

    p = MarketStatsLimitPools(zt=None, dt=None)
    assert p.zt is None and p.dt is None


def test_market_stats_limit_pools_zt_only():
    """Asymmetric — zt OK, dt failed (per-pool error isolation)."""
    from stock_data.api.schemas import MarketStatsLimitPools

    p = MarketStatsLimitPools(zt=[{"code": "600519"}], dt=None)
    assert p.zt is not None and p.dt is None


def test_market_stats_error_entry_pool_literals():
    """New block literals 'zt_pool' and 'dt_pool' must validate."""
    from stock_data.api.schemas import MarketStatsErrorEntry

    zt_err = MarketStatsErrorEntry(block="zt_pool", error="DataFetchError", message="zt down")
    dt_err = MarketStatsErrorEntry(block="dt_pool", error="ValueError", message="dt down")
    assert zt_err.block == "zt_pool"
    assert dt_err.block == "dt_pool"


def test_market_stats_error_entry_pool_literal_rejects_unknown():
    """Unknown block literal must raise ValidationError."""
    import pytest
    from pydantic import ValidationError
    from stock_data.api.schemas import MarketStatsErrorEntry

    with pytest.raises(ValidationError):
        MarketStatsErrorEntry(block="unknown_block", error="X", message="x")


def test_market_stats_response_includes_limit_pools_field():
    """MarketStatsResponse.model_fields MUST contain 'limit_pools'."""
    from stock_data.api.schemas import MarketStatsResponse

    assert "limit_pools" in MarketStatsResponse.model_fields


def test_market_stats_response_default_limit_pools_is_none():
    """Omitting limit_pools keyword → field is None (excludes cleanly via exclude_none)."""
    from stock_data.api.schemas import MarketStatsResponse

    r = MarketStatsResponse(
        stocks=None, boards=None, errors=[], summary={}
    )
    assert r.limit_pools is None
```

- [ ] **Step 1.2: Run tests to verify they fail (ImportError expected)**

Run: `.venv/Scripts/python.exe -m pytest tests/test_agent_market_stats_schemas.py -v`
Expected: 7 ImportError / AttributeError failures (`MarketStatsLimitPools` doesn't exist yet; `MarketStatsErrorEntry(block="zt_pool", ...)` fails validation; `MarketStatsResponse.limit_pools` doesn't exist).

- [ ] **Step 1.3: Add `MarketStatsLimitPools` schema**

In `stock_data/api/schemas.py`, add immediately after the `BoardStats` class (around line 2083) and before `MarketStatsErrorEntry`:

```python
class MarketStatsLimitPools(BaseModel):
    """涨跌停 block of /agent/market-stats.

    Each pool is independently nullable: zt may be null while dt has
    data (per-pool error isolation). An empty list (`[]`) means
    "upstream returned no data for this date" — distinct from null,
    which means "upstream failed OR pools were not queried
    (`include_pools=false`)".
    """

    zt: list[dict] | None = Field(
        default=None,
        description="涨停池 list. null on per-pool upstream failure or include_pools=false.",
    )
    dt: list[dict] | None = Field(
        default=None,
        description="跌停池 list. null on per-pool upstream failure or include_pools=false.",
    )
```

- [ ] **Step 1.4: Extend `MarketStatsErrorEntry.block` literal**

In `stock_data/api/schemas.py`, modify `MarketStatsErrorEntry` (around line 2085):

```python
class MarketStatsErrorEntry(BaseModel):
    """One per-block failure surfaced in errors[]."""

    block: Literal["stocks", "boards", "zt_pool", "dt_pool"]
    error: str
    message: str
```

- [ ] **Step 1.5: Add `limit_pools` field to `MarketStatsResponse`**

In `stock_data/api/schemas.py`, modify `MarketStatsResponse` (around line 2093):

```python
class MarketStatsResponse(BaseModel):
    """Top-level response for /agent/market-stats.

    Either block may be `null` (the upstream call failed); the failure
    is captured in `errors[]`. `summary` mirrors the contract used by
    IndicesBatchProfileResponse / MarketContextResponse:
    `{requested, ok, failed, elapsed_ms}`.
    """

    stocks: StockStats | None
    boards: BoardStats | None
    limit_pools: MarketStatsLimitPools | None = Field(
        default=None,
        description="涨跌停 block (NEW post-2026-09-02). null when include_pools=false or both pools failed.",
    )
    errors: list[MarketStatsErrorEntry]
    summary: dict
```

- [ ] **Step 1.6: Run schema tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_agent_market_stats_schemas.py -v`
Expected: All 7 new tests pass. Existing 6 schema tests also still pass (no breakage).

- [ ] **Step 1.7: Write failing cache key test for new signature**

In `tests/test_agent_market_stats.py`, find the existing `test_cache_key_includes_include_boards` (around line 232) and replace it with:

```python
def test_cache_key_includes_all_three_dimensions():
    """Cache key includes include_boards, include_pools, and trade_date.

    All three knobs produce distinct cache entries because changing
    any of them produces a materially different response.
    """
    assert make_market_stats_cache_key(True, True, "2026-09-02") == (
        "agent_market_stats:True:True:2026-09-02"
    )
    assert make_market_stats_cache_key(False, True, "2026-09-02") == (
        "agent_market_stats:False:True:2026-09-02"
    )
    assert make_market_stats_cache_key(True, False, "2026-09-02") == (
        "agent_market_stats:True:False:2026-09-02"
    )
    assert make_market_stats_cache_key(True, True, "2026-09-01") == (
        "agent_market_stats:True:True:2026-09-01"
    )
    # All four are distinct entries
    keys = {
        make_market_stats_cache_key(True, True, "2026-09-02"),
        make_market_stats_cache_key(False, True, "2026-09-02"),
        make_market_stats_cache_key(True, False, "2026-09-02"),
        make_market_stats_cache_key(True, True, "2026-09-01"),
    }
    assert len(keys) == 4
```

- [ ] **Step 1.8: Run cache key test to verify it fails (signature mismatch)**

Run: `.venv/Scripts/python.exe -m pytest tests/test_agent_market_stats.py::test_cache_key_includes_all_three_dimensions -v`
Expected: FAIL with `TypeError: make_market_stats_cache_key() missing 2 required positional arguments: 'include_pools' and 'trade_date'`.

- [ ] **Step 1.9: Extend `make_market_stats_cache_key` in `stock_data/api/cache.py`**

Replace the existing `make_market_stats_cache_key` (around line 541):

```python
def make_market_stats_cache_key(
    include_boards: bool, include_pools: bool, trade_date: str
) -> str:
    """Cache key for GET /api/v1/agent/market-stats.

    All three knobs participate: changing any of them produces a
    materially different response (different blocks populated / zt
    pool for a different date). 60s TTL via get_quote_cache.
    """
    return f"agent_market_stats:{include_boards}:{include_pools}:{trade_date}"
```

- [ ] **Step 1.10: Run cache key test to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/test_agent_market_stats.py::test_cache_key_includes_all_three_dimensions -v`
Expected: PASS.

- [ ] **Step 1.11: Run full market-stats test file to verify no regressions**

Run: `.venv/Scripts/python.exe -m pytest tests/test_agent_market_stats.py tests/test_agent_market_stats_schemas.py -v`
Expected: All tests pass. The pre-existing 16 tests in `test_agent_market_stats.py` still call `make_market_stats_cache_key` via the route (no direct test calls except this one) and the route itself is updated later in Task 2 — wait, no, the route in Task 1 still calls the OLD signature. That's a bug.

Wait — let me check the current `get_market_stats` handler in `stock_data/api/routes/agent.py:1268`:

```python
cache_key = make_market_stats_cache_key(include_boards)
```

This call will now fail with `TypeError: missing 2 required positional arguments`. Two existing tests will break:
- `test_market_stats_returns_200` (calls the route → fails)
- `test_market_stats_cache_hit_skips_upstream` (calls the route → fails)

These tests rely on the route running end-to-end. The signature change forces us to update the route's call site in this task, OR to add a backwards-compatible default in the cache key. The cleaner approach is to update the route call site now too.

In `stock_data/api/routes/agent.py` line 1268, replace:

```python
cache_key = make_market_stats_cache_key(include_boards)
```

with a placeholder that compiles but doesn't add the new behavior yet:

```python
# TODO(Task 2): extend to include include_pools + trade_date once the
# handler picks them up. For Task 1 we only need the call site to
# compile against the new signature.
cache_key = make_market_stats_cache_key(include_boards, include_pools=False, trade_date="legacy")
```

Wait — that's ugly. Better approach: keep the old 1-arg signature working alongside the new 3-arg one for Task 1, then unify in Task 2. Use `*args, **kwargs` or default values:

Revert the cache key helper to accept the new params as optional:

```python
def make_market_stats_cache_key(
    include_boards: bool, include_pools: bool = True, trade_date: str = ""
) -> str:
    """Cache key for GET /api/v1/agent/market-stats.

    All three knobs participate (post-2026-09-02): changing any of them
    produces a materially different response (different blocks
    populated / zt pool for a different date). 60s TTL via
    get_quote_cache. ``include_pools`` and ``trade_date`` default for
    Task-1 backwards compatibility; Task 2 will plumb them through
    the route handler.
    """
    return f"agent_market_stats:{include_boards}:{include_pools}:{trade_date}"
```

And revert the test for Task 1 — the original 1-arg test should still pass:

```python
def test_cache_key_backwards_compatible_one_arg():
    """Task 1 keeps the 1-arg form compiling; Task 2 will migrate call sites."""
    assert make_market_stats_cache_key(True) == "agent_market_stats:True:True:"
    assert make_market_stats_cache_key(False) == "agent_market_stats:False:True:"
```

This is the cleaner approach: signature becomes backwards-compatible, Task 1 just adds the new fields to the key shape, Task 2 plumbs the new args through the route.

Run: `.venv/Scripts/python.exe -m pytest tests/test_agent_market_stats.py tests/test_agent_market_stats_schemas.py -v`
Expected: All tests pass.

- [ ] **Step 1.12: Lint + format**

Run: `ruff check stock_data/api/schemas.py stock_data/api/cache.py tests/test_agent_market_stats_schemas.py tests/test_agent_market_stats.py && ruff format stock_data/api/schemas.py stock_data/api/cache.py tests/test_agent_market_stats_schemas.py tests/test_agent_market_stats.py`

Expected: no errors.

- [ ] **Step 1.13: Commit**

```bash
git checkout -b feat/agent-market-stats-pools
git add stock_data/api/schemas.py stock_data/api/cache.py tests/test_agent_market_stats_schemas.py tests/test_agent_market_stats.py
git commit -m "feat(schemas): add MarketStatsLimitPools + extend error-entry for pools blocks

Additive only — no handler/behavior change yet. The new MarketStatsLimitPools
schema carries zt/dt as independently-nullable list[dict] | None (per-pool
error isolation). MarketStatsErrorEntry.block literal extended to include
'zt_pool' and 'dt_pool'. MarketStatsResponse gains an optional limit_pools
field (default None → exclude_none cleanly strips when include_pools=false).

make_market_stats_cache_key gains include_pools + trade_date params with
backwards-compatible defaults — Task 2 will plumb them through the handler.

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Task 2: market-stats handler + helper + MD renderer (TDD)

**Files:**
- Modify: `stock_data/api/routes/agent.py:1229-1343` (extend `get_market_stats`)
- Modify: `stock_data/api/routes/agent.py:1947-1962` (update `render_market_stats_as_md`)
- Modify: `stock_data/api/routes/agent.py` (add `_compute_limit_pools_block` near `_classify_market_session`)
- Modify: `stock_data/api/routes/agent.py` (add `_md_limit_pools_block` near `_md_stats_block`)
- Modify: `tests/test_agent_market_stats.py` (update existing 4 tests + add 11 new tests)

**Interfaces:**
- Consumes: `MarketStatsLimitPools`, `MarketStatsErrorEntry`, `make_market_stats_cache_key(include_boards, include_pools, trade_date)`, `manager.get_zt_pool(pool_type, date)`, `trade_calendar.get_latest_trade_date_on_or_before(today)`, `_TRADE_DATE_RE`, `datetime.now(_CST).date().isoformat()`
- Produces:
  - `_compute_limit_pools_block(manager, target_date: str) -> tuple[MarketStatsLimitPools, list[MarketStatsErrorEntry]]` — per-pool try/except fan-out; both pools attempted unconditionally
  - `_md_limit_pools_block(out: list[str], pools: MarketStatsLimitPools | None) -> None` — emits `## 涨跌停` heading + per-pool table or null marker
  - `get_market_stats` with new query params `include_pools: bool = True`, `trade_date: str | None = None`; new pools block in the response

Per the spec §3.4, no `session` or `is_trade_day` calculation is needed for market-stats — the route is session-agnostic.

- [ ] **Step 2.1: Write failing tests for new query params + pools block**

In `tests/test_agent_market_stats.py`, append a new test class:

```python
# ----- pools block (post-2026-09-02) -----


def _patch_zt_pool(monkeypatch, *, zt_value=([], "akshare", None), dt_value=([], "akshare", None)):
    """Patch manager.get_zt_pool + the other market-stats upstreams.

    Each of ``zt_value`` / ``dt_value`` is either:
    - a 3-tuple ``(rows, src, error_reason)`` — returned to the caller
      at the matching call
    - an ``Exception`` instance — raised at the matching call

    MagicMock's ``side_effect`` accepts a list of mixed return-or-raise
    values, so we just pass the args straight through.
    """
    fake_manager = MagicMock()
    fake_manager.get_zt_pool.side_effect = [zt_value, dt_value]
    fake_manager.get_realtime_quotes.return_value = (
        [_make_quote("600000", 1.0)], "akshare",
    )
    monkeypatch.setattr(agent_module, "get_manager", lambda: fake_manager)
    fake_cache = MagicMock()
    fake_cache.get_board_list.return_value = (
        [{"code": "BK0001", "name": "X", "change_pct": 0.5}], "ths",
    )
    monkeypatch.setattr(agent_module, "stock_board_cache", fake_cache)
    return fake_manager


class TestMarketStatsPoolsBlock:
    def test_happy_path_includes_pools(self, client, monkeypatch):
        """Default request includes pools block; summary.requested=3 (stocks + boards + pools)."""
        _patch_zt_pool(
            monkeypatch,
            zt_value=([{"code": "600519", "name": "茅台"}], "akshare", None),
            dt_value=([{"code": "000001", "name": "平安"}], "akshare", None),
        )
        resp = client.get("/api/v1/agent/market-stats")
        assert resp.status_code == 200
        body = resp.json()
        assert body["limit_pools"] is not None
        assert len(body["limit_pools"]["zt"]) == 1
        assert len(body["limit_pools"]["dt"]) == 1
        assert body["limit_pools"]["zt"][0]["code"] == "600519"
        assert body["errors"] == []
        assert body["summary"]["requested"] == 3
        assert body["summary"]["ok"] == 3

    def test_zt_pool_failure_isolates_dt(self, client, monkeypatch):
        """zt upstream raises DataFetchError → zt=null, dt populated, errors[] has zt_pool entry."""
        from stock_data.data_provider.base import DataFetchError

        _patch_zt_pool(
            monkeypatch,
            zt_value=DataFetchError("zt down"),
            dt_value=([{"code": "000001"}], "akshare", None),
        )
        resp = client.get("/api/v1/agent/market-stats")
        assert resp.status_code == 200
        body = resp.json()
        assert body["limit_pools"]["zt"] is None
        assert body["limit_pools"]["dt"] is not None
        assert len(body["limit_pools"]["dt"]) == 1
        zt_errs = [e for e in body["errors"] if e["block"] == "zt_pool"]
        assert len(zt_errs) == 1
        assert "zt down" in zt_errs[0]["message"]
        # ok counts the pools block as success (per-pool errors don't decrement)
        assert body["summary"]["ok"] == 3

    def test_dt_pool_failure_isolates_zt(self, client, monkeypatch):
        """Symmetric — dt fails, zt populated."""
        from stock_data.data_provider.base import DataFetchError

        _patch_zt_pool(
            monkeypatch,
            zt_value=([{"code": "600519"}], "akshare", None),
            dt_value=DataFetchError("dt down"),
        )
        resp = client.get("/api/v1/agent/market-stats")
        assert resp.status_code == 200
        body = resp.json()
        assert body["limit_pools"]["zt"] is not None
        assert body["limit_pools"]["dt"] is None
        dt_errs = [e for e in body["errors"] if e["block"] == "dt_pool"]
        assert len(dt_errs) == 1
        assert body["summary"]["ok"] == 3

    def test_both_pools_fail(self, client, monkeypatch):
        """Both raise → both null, 2 pool errors, ok still 3 (block call succeeded)."""
        from stock_data.data_provider.base import DataFetchError

        _patch_zt_pool(
            monkeypatch,
            zt_value=DataFetchError("zt down"),
            dt_value=DataFetchError("dt down"),
        )
        resp = client.get("/api/v1/agent/market-stats")
        body = resp.json()
        assert body["limit_pools"]["zt"] is None
        assert body["limit_pools"]["dt"] is None
        assert len(body["errors"]) == 2
        blocks = {e["block"] for e in body["errors"]}
        assert blocks == {"zt_pool", "dt_pool"}
        assert body["summary"]["ok"] == 3

    def test_pools_empty_passthrough(self, client, monkeypatch):
        """Upstream returns [] for both (pre-market today) → both [] in response, no errors."""
        _patch_zt_pool(monkeypatch, zt_value=([], "akshare", None), dt_value=([], "akshare", None))
        resp = client.get("/api/v1/agent/market-stats")
        body = resp.json()
        assert body["limit_pools"]["zt"] == []
        assert body["limit_pools"]["dt"] == []
        assert body["errors"] == []
        assert body["summary"]["ok"] == 3

    def test_include_pools_false_skips_pools_upstream(self, client, monkeypatch):
        """?include_pools=false → no upstream pool call, field present with both null, requested=2."""
        fake_manager = MagicMock()
        fake_manager.get_realtime_quotes.return_value = ([_make_quote("600000", 1.0)], "akshare")
        monkeypatch.setattr(agent_module, "get_manager", lambda: fake_manager)
        fake_cache = MagicMock()
        fake_cache.get_board_list.return_value = (
            [{"code": "BK0001", "name": "X", "change_pct": 0.5}], "ths",
        )
        monkeypatch.setattr(agent_module, "stock_board_cache", fake_cache)

        resp = client.get("/api/v1/agent/market-stats?include_pools=false")
        body = resp.json()
        assert body["limit_pools"] is not None
        assert body["limit_pools"]["zt"] is None
        assert body["limit_pools"]["dt"] is None
        assert body["errors"] == []
        assert body["summary"]["requested"] == 2
        assert body["summary"]["ok"] == 2
        fake_manager.get_zt_pool.assert_not_called()

    def test_pools_trade_date_passed_through(self, client, monkeypatch):
        """?trade_date=2026-09-01 → manager.get_zt_pool called twice with date='2026-09-01'."""
        fake_manager = _patch_zt_pool(
            monkeypatch,
            zt_value=([{"code": "600519"}], "akshare", None),
            dt_value=([{"code": "000001"}], "akshare", None),
        )
        client.get("/api/v1/agent/market-stats?trade_date=2026-09-01")
        calls = fake_manager.get_zt_pool.call_args_list
        assert len(calls) == 2, f"expected 2 calls, got {len(calls)}"
        seen_pool_types = set()
        for call in calls:
            assert call.kwargs.get("date") == "2026-09-01", (
                f"expected date=2026-09-01, got {call.kwargs.get('date')!r}"
            )
            seen_pool_types.add(call.kwargs.get("pool_type"))
        assert seen_pool_types == {"zt", "dt"}

    def test_pools_trade_date_malformed_400(self, client):
        """?trade_date=not-a-date → 400 with invalid_trade_date code (matches market-context)."""
        resp = client.get("/api/v1/agent/market-stats?trade_date=not-a-date")
        assert resp.status_code == 400
        body = resp.json()
        assert body.get("error") == "invalid_trade_date"
        assert "trade_date" in body.get("message", "")

    def test_pools_trade_date_default_to_latest_trade_date(self, client, monkeypatch):
        """Omit ?trade_date → handler resolves to get_latest_trade_date_on_or_before(today)."""
        fake_manager = _patch_zt_pool(
            monkeypatch,
            zt_value=([{"code": "600519"}], "akshare", None),
            dt_value=([{"code": "000001"}], "akshare", None),
        )
        client.get("/api/v1/agent/market-stats")
        for call in fake_manager.get_zt_pool.call_args_list:
            assert call.kwargs.get("date"), "date must be non-empty (trade_calendar default)"

    def test_pools_cache_hit(self, client, monkeypatch):
        """Second call with same (include_boards, include_pools, trade_date) → cache hit."""
        # Override the cache-disabled default for this test
        monkeypatch.setenv("ENABLE_API_CACHE", "true")
        import importlib

        import stock_data.server as server_module
        importlib.reload(server_module)
        from fastapi.testclient import TestClient

        fresh_client = TestClient(server_module.app)

        fake_manager = _patch_zt_pool(
            monkeypatch,
            zt_value=([{"code": "600519"}], "akshare", None),
            dt_value=([{"code": "000001"}], "akshare", None),
        )
        from stock_data.api.cache import get_quote_cache

        get_quote_cache().clear()

        fresh_client.get("/api/v1/agent/market-stats?trade_date=2026-09-01")
        assert fake_manager.get_zt_pool.call_count == 2  # zt + dt on first call

        fresh_client.get("/api/v1/agent/market-stats?trade_date=2026-09-01")
        assert fake_manager.get_zt_pool.call_count == 2  # cache hit, no new calls

        monkeypatch.setenv("ENABLE_API_CACHE", "false")

    def test_format_md_renders_pools_section(self, client, monkeypatch):
        """?format=md → body contains ## 涨跌停 + table headers for zt and dt."""
        _patch_zt_pool(
            monkeypatch,
            zt_value=(
                [{"code": "600519", "name": "茅台", "pct_chg": 10.0, "limit_time": "10:00",
                  "limit_count": 2, "industry": "白酒"}],
                "akshare", None,
            ),
            dt_value=(
                [{"code": "000001", "name": "平安", "pct_chg": -10.0,
                  "limit_time": "10:00", "industry": "银行"}],
                "akshare", None,
            ),
        )
        resp = client.get("/api/v1/agent/market-stats?format=md")
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("text/markdown")
        body = resp.text
        assert "## 涨跌停" in body
        assert "**涨停池**: 1 只" in body
        assert "**跌停池**: 1 只" in body
        assert "| 代码 | 名称 | 涨跌幅 | 涨停时间 | 连板数 | 所属行业 |" in body
        assert "| 600519 | 茅台 | +10.00% | 10:00 | 2 | 白酒 |" in body
        assert "| 000001 | 平安 | -10.00% | 10:00 | 银行 |" in body

    def test_format_md_renders_null_pools_when_disabled(self, client, monkeypatch):
        """?include_pools=false&format=md → body contains ## 涨跌停 + null markers.

        When include_pools=false the handler populates
        MarketStatsLimitPools(zt=None, dt=None) (see Step 2.4) so the
        field is present-but-null. The MD renderer emits the heading
        with `**涨停池**: null` markers.
        """
        _patch_zt_pool(monkeypatch)
        resp = client.get("/api/v1/agent/market-stats?include_pools=false&format=md")
        body = resp.text
        assert "## 涨跌停" in body
        assert "**涨停池**: null" in body
        assert "**跌停池**: null" in body
```

- [ ] **Step 2.2: Run the new tests to verify they all fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_agent_market_stats.py::TestMarketStatsPoolsBlock -v`
Expected: 12 failures with various errors (missing query params, `limit_pools` not in response, `get_zt_pool` not called, etc.).

- [ ] **Step 2.3: Add `_compute_limit_pools_block` helper**

In `stock_data/api/routes/agent.py`, add the helper near `_classify_market_session` (around line 544):

```python
def _compute_limit_pools_block(
    manager, target_date: str
) -> tuple["MarketStatsLimitPools", list["MarketStatsErrorEntry"]]:
    """Compute the limit_pools block for market-stats.

    Per-pool fan-out with per-pool error isolation — zt failure emits
    a `{"block": "zt_pool"}` entry and leaves zt=None while dt is
    still attempted (and vice versa). No session-aware short-circuit:
    whatever the upstream returns for the given date is the truth
    (pre-market today → empty list, completed day → full pool, error
    → null + errors[] entry).
    """
    errors: list[MarketStatsErrorEntry] = []
    zt: list[dict] | None = None
    dt: list[dict] | None = None

    try:
        zt, _src, _ = manager.get_zt_pool(pool_type="zt", date=target_date)
    except Exception as exc:
        logger.warning(f"[agent/market-stats] zt_pool failed: {exc}", exc_info=True)
        errors.append(
            MarketStatsErrorEntry(
                block="zt_pool", error=type(exc).__name__, message=str(exc),
            )
        )

    try:
        dt, _src, _ = manager.get_zt_pool(pool_type="dt", date=target_date)
    except Exception as exc:
        logger.warning(f"[agent/market-stats] dt_pool failed: {exc}", exc_info=True)
        errors.append(
            MarketStatsErrorEntry(
                block="dt_pool", error=type(exc).__name__, message=str(exc),
            )
        )

    return MarketStatsLimitPools(zt=zt, dt=dt), errors
```

Add the import at the top of the file (the imports block near line 70) — `MarketStatsLimitPools` is already not imported; add it:

In the `from ..schemas import (...)` block (around line 70), add `MarketStatsLimitPools` to the import list:

```python
from ..schemas import (
    ...
    MarketStatsLimitPools,
    MarketStatsResponse,
    ...
)
```

- [ ] **Step 2.4: Extend `get_market_stats` handler with new query params + pools block**

Replace the existing `get_market_stats` (around line 1229-1343 in `stock_data/api/routes/agent.py`):

```python
@router.get(
    "/agent/market-stats",
    response_model=MarketStatsResponse,
    responses={500: {"model": ErrorResponse, "description": "Server error"}},
    tags=["agent"],
)
@endpoint_meta(
    summary="市场全量统计（个股+板块涨幅分布 + 涨跌停池 + 桶形数据）",
    markets=["csi"],
    capabilities=[],
    depends_on=[
        "/api/v1/stocks",
        "/api/v1/boards",
        "/api/v1/zt-pools",
        "manager.get_realtime_quotes",
        "cache.get_board_list",
        "manager.get_zt_pool",
        "calendar.get_latest_trade_date_on_or_before",
    ],
)
@map_errors
def get_market_stats(
    include_boards: bool = Query(
        default=True,
        description="是否包含板块块;false 时只返回个股块 (无板块上游调用)",
    ),
    include_pools: bool = Query(
        default=True,
        description="是否包含涨跌停池块;false 时只返回个股+板块 (无 zt/dt 上游调用)",
    ),
    trade_date: str | None = Query(
        default=None,
        description=(
            "交易日 YYYY-MM-DD;不传默认 = "
            "get_latest_trade_date_on_or_before(today). 影响 zt/dt 池子查询日期."
        ),
    ),
    format: str = Query(
        "json",
        pattern="^(json|md)$",
        description="Output format. json=application/json (default); md=text/markdown.",
    ),
) -> Response:
    """Per-block fan-out with per-block error isolation.

    stocks block:  manager.get_realtime_quotes('csi') (single upstream call)
    boards block:  stock_board_cache.get_board_list(board_type=None, source='ths',
                   include_quote=True, manager=manager) (single upstream call,
                   persistence-routed)
    pools block:   manager.get_zt_pool(pool_type='zt'|'dt', date=trade_date)
                   (two upstream calls; per-pool error isolation)

    A single upstream failure sets that block to ``null`` and surfaces
    the exception in ``errors[]``; the other blocks continue normally.
    Cached 60s via ``get_quote_cache`` (one entry shared between json/md).
    """
    if trade_date is not None and not _TRADE_DATE_RE.match(trade_date):
        raise HTTPException(
            status_code=400,
            detail={
                "error": "invalid_trade_date",  # match market-context's gate code (see CLAUDE.md tests)
                "message": (
                    f"trade_date must be YYYY-MM-DD; got {trade_date!r}. "
                    "Empty = server-defaulted to most recent trade date on/before today."
                ),
            },
        )
    today_str = datetime.now(_CST).date().isoformat()
    target_date = (
        trade_date
        or trade_calendar.get_latest_trade_date_on_or_before(today_str)
        or today_str
    )

    cache_key = make_market_stats_cache_key(include_boards, include_pools, target_date)
    hit = cached_lookup(get_quote_cache, cache_key, "agent_market_stats")
    if hit is not None:
        return _render_agent("market-stats", hit, format)

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

    # --- limit_pools block ---
    # The field is ALWAYS present in the JSON response (per spec §4 wire
    # format), even when include_pools=false. When disabled, we populate
    # it with `MarketStatsLimitPools(zt=None, dt=None)` so consumers
    # see a stable shape; the field's presence is NOT a signal that
    # pools were attempted. (That signal is in `summary.requested`.)
    if include_pools:
        limit_pools_block, pool_errors = _compute_limit_pools_block(manager, target_date)
        errors.extend(pool_errors)
        # Per-pool failures don't decrement ok — the block call DID
        # complete (with partial data). Empty upstream results also
        # count as success (caller distinguishes via inner [] vs null).
        ok += 1
    else:
        limit_pools_block = MarketStatsLimitPools(zt=None, dt=None)

    result = MarketStatsResponse(
        stocks=stocks_stats,
        boards=boards_stats,
        limit_pools=limit_pools_block,
        errors=errors,
        summary=_batch_summary(requested, ok, started),
    )
    cached_store(get_quote_cache, cache_key, result)
    return _render_agent("market-stats", result, format)
```

- [ ] **Step 2.5: Add `_md_limit_pools_block` MD helper**

In `stock_data/api/routes/agent.py`, add the helper near `_md_stats_block` (around line 1920):

```python
def _md_limit_pools_block(out: list[str], pools) -> None:
    """Render the limit_pools block. Always emits a `## 涨跌停` heading;
    distinguishes disabled / empty / partial / full via inner labels."""
    out.append("## 涨跌停")
    if pools is None:
        out.append("（未启用）")
        out.append("")
        return
    for label, key, headers in [
        ("涨停池", "zt", "| 代码 | 名称 | 涨跌幅 | 涨停时间 | 连板数 | 所属行业 |"),
        ("跌停池", "dt", "| 代码 | 名称 | 涨跌幅 | 跌停时间 | 所属行业 |"),
    ]:
        rows = getattr(pools, key)
        if rows is None:
            out.append(f"**{label}**: null")
        elif not rows:
            out.append(f"**{label}**: （空）")
        else:
            out.append(f"**{label}**: {len(rows)} 只")
            out.append("")
            out.append(headers)
            out.append("|---|---|---|---|---|---|")
            for s in rows:
                code = s.get("code", "")
                name = s.get("name", "")
                pct = s.get("pct_chg") or s.get("change_pct")
                if key == "zt":
                    t = s.get("limit_time") or s.get("first_limit_time") or ""
                    lb = s.get("limit_count") or s.get("continuous_limit_count")
                    industry = s.get("industry", "")
                    out.append(
                        f"| {code} | {name} | {_md_pct(pct)} | {t} | "
                        f"{lb if lb is not None else '—'} | {industry} |"
                    )
                else:
                    t = s.get("limit_time") or s.get("first_limit_time") or ""
                    industry = s.get("industry", "")
                    out.append(
                        f"| {code} | {name} | {_md_pct(pct)} | {t} | {industry} |"
                    )
        out.append("")
```

- [ ] **Step 2.6: Update `render_market_stats_as_md` to call `_md_limit_pools_block`**

Replace the existing `render_market_stats_as_md` (around line 1947):

```python
def render_market_stats_as_md(p: MarketStatsResponse) -> str:
    out: list[str] = ["# 市场全量统计", ""]
    out.extend(_md_stats_block("个股", p.stocks, total_universe_label="A 股全市场"))
    out.append("")
    out.extend(_md_stats_block("板块", p.boards, total_universe_label="ths 板块清单"))
    out.append("")
    _md_limit_pools_block(out, p.limit_pools)
    out.append("")
    out.append("## 失败列表")
    out.extend(_md_errors([e.model_dump() for e in p.errors], key="block", header="块"))
    out.append("")
    s = p.summary or {}
    out.append(
        f"## 汇总 — requested {s.get('requested', '?')}, "
        f"ok {s.get('ok', '?')}, failed {s.get('failed', '?')}, "
        f"elapsed {s.get('elapsed_ms', '?')}ms"
    )
    return "\n".join(out)
```

- [ ] **Step 2.7: Run the new tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_agent_market_stats.py::TestMarketStatsPoolsBlock -v`
Expected: 12 new tests pass.

- [ ] **Step 2.8: Update existing market-stats tests for new signature + default behavior**

In `tests/test_agent_market_stats.py`, update these existing tests to handle `requested=3` (the new default with `include_pools=true`) and to mock `manager.get_zt_pool`:

**`test_market_stats_returns_200`** (line 99):

```python
def test_market_stats_returns_200(client, monkeypatch):
    """Happy path — all 3 blocks populated, summary reports 3/3 ok."""
    quotes = [_make_quote("600000", 1.0), _make_quote("600001", -1.0), _make_quote("600002", 0.0)]
    boards = [{"code": "BK0001", "name": "X", "change_pct": 0.5}]
    fake_manager = _patch_manager(monkeypatch, quotes=quotes)
    fake_manager.get_zt_pool.return_value = ([], "akshare", None)
    _patch_board_cache(monkeypatch, all_boards_payload=(boards, "ths"))

    resp = client.get("/api/v1/agent/market-stats")
    assert resp.status_code == 200
    body = resp.json()
    assert body["stocks"]["sample_size"] == 3
    assert body["boards"]["sample_size"] == 1
    assert body["limit_pools"] is not None
    assert body["limit_pools"]["zt"] == []
    assert body["limit_pools"]["dt"] == []
    assert body["errors"] == []
    assert body["summary"]["requested"] == 3
    assert body["summary"]["ok"] == 3
```

**`test_stocks_upstream_failure_does_not_affect_boards`** (line 123):

```python
def test_stocks_upstream_failure_does_not_affect_boards(client, monkeypatch):
    """When get_realtime_quotes raises, stocks=null but boards + pools are still populated."""
    fake_manager = MagicMock()
    fake_manager.get_realtime_quotes.side_effect = DataFetchError("upstream down")
    fake_manager.get_zt_pool.return_value = ([], "akshare", None)
    monkeypatch.setattr(agent_module, "get_manager", lambda: fake_manager)
    boards = [{"code": "BK0001", "name": "X", "change_pct": 0.5}]
    _patch_board_cache(monkeypatch, all_boards_payload=(boards, "ths"))

    resp = client.get("/api/v1/agent/market-stats")
    assert resp.status_code == 200
    body = resp.json()
    assert body["stocks"] is None
    assert body["boards"] is not None
    assert body["limit_pools"] is not None
    assert any(e["block"] == "stocks" for e in body["errors"])
    assert body["summary"]["ok"] == 2
    assert body["summary"]["failed"] == 1
```

**`test_boards_upstream_failure_does_not_affect_stocks`** (line 142):

```python
def test_boards_upstream_failure_does_not_affect_stocks(client, monkeypatch):
    """Symmetric — boards=null but stocks + pools still populated."""
    quotes = [_make_quote("600000", 1.0)]
    fake_manager = _patch_manager(monkeypatch, quotes=quotes)
    fake_manager.get_zt_pool.return_value = ([], "akshare", None)
    fake_cache = MagicMock()
    fake_cache.get_board_list.side_effect = ValueError("cid_unresolved")
    monkeypatch.setattr(agent_module, "stock_board_cache", fake_cache)

    resp = client.get("/api/v1/agent/market-stats")
    assert resp.status_code == 200
    body = resp.json()
    assert body["stocks"] is not None
    assert body["boards"] is None
    assert body["limit_pools"] is not None
    assert any(e["block"] == "boards" for e in body["errors"])
    assert body["summary"]["ok"] == 2
```

**`test_both_blocks_fail`** (line 159):

```python
def test_both_blocks_fail(client, monkeypatch):
    """Stocks + boards fail, pools succeed — 2 errors, summary.ok=1, requested=3."""
    fake_manager = MagicMock()
    fake_manager.get_realtime_quotes.side_effect = DataFetchError("stocks down")
    fake_manager.get_zt_pool.return_value = ([], "akshare", None)
    monkeypatch.setattr(agent_module, "get_manager", lambda: fake_manager)
    fake_cache = MagicMock()
    fake_cache.get_board_list.side_effect = RuntimeError("boards down")
    monkeypatch.setattr(agent_module, "stock_board_cache", fake_cache)

    resp = client.get("/api/v1/agent/market-stats")
    assert resp.status_code == 200
    body = resp.json()
    assert body["stocks"] is None
    assert body["boards"] is None
    assert body["limit_pools"] is not None
    assert len(body["errors"]) == 2
    assert body["summary"]["ok"] == 1
    assert body["summary"]["requested"] == 3
```

**`test_include_boards_false_skips_boards_upstream`** (line 181):

```python
def test_include_boards_false_skips_boards_upstream(client, monkeypatch):
    """?include_boards=false must NOT invoke any boards upstream call (pools still on)."""
    quotes = [_make_quote("600000", 1.0)]
    fake_manager = MagicMock()
    fake_manager.get_realtime_quotes.return_value = (quotes, "akshare")
    fake_manager.get_zt_pool.return_value = ([], "akshare", None)
    monkeypatch.setattr(agent_module, "get_manager", lambda: fake_manager)
    fake_cache = MagicMock()
    monkeypatch.setattr(agent_module, "stock_board_cache", fake_cache)

    resp = client.get("/api/v1/agent/market-stats?include_boards=false")
    assert resp.status_code == 200
    body = resp.json()
    assert body["stocks"] is not None
    assert body["boards"] is None
    assert body["limit_pools"] is not None
    assert body["errors"] == []
    assert body["summary"]["requested"] == 2
    assert body["summary"]["ok"] == 2
    fake_cache.get_board_list.assert_not_called()
```

**`test_market_stats_cache_hit_skips_upstream`** (line 238):

```python
def test_market_stats_cache_hit_skips_upstream(monkeypatch):
    """Second call within 60s does NOT re-invoke upstream methods."""
    monkeypatch.setenv("ENABLE_API_CACHE", "true")
    import importlib

    import stock_data.server as server_module
    importlib.reload(server_module)
    fresh_client = TestClient(server_module.app)

    quotes = [_make_quote("600000", 1.0)]
    boards = [{"code": "BK0001", "name": "X", "change_pct": 0.5}]
    fake_manager = MagicMock()
    fake_manager.get_realtime_quotes.return_value = (quotes, "akshare")
    fake_manager.get_zt_pool.return_value = ([], "akshare", None)
    monkeypatch.setattr(agent_module, "get_manager", lambda: fake_manager)
    fake_cache = MagicMock()
    fake_cache.get_board_list.return_value = (boards, "ths")
    monkeypatch.setattr(agent_module, "stock_board_cache", fake_cache)

    from stock_data.api.cache import get_quote_cache
    get_quote_cache().clear()

    resp1 = fresh_client.get("/api/v1/agent/market-stats")
    assert resp1.status_code == 200
    assert fake_manager.get_realtime_quotes.call_count == 1
    assert fake_cache.get_board_list.call_count == 1
    assert fake_manager.get_zt_pool.call_count == 2  # zt + dt

    resp2 = fresh_client.get("/api/v1/agent/market-stats")
    assert resp2.status_code == 200
    assert fake_manager.get_realtime_quotes.call_count == 1
    assert fake_cache.get_board_list.call_count == 1
    assert fake_manager.get_zt_pool.call_count == 2  # cache hit, no new calls

    monkeypatch.setenv("ENABLE_API_CACHE", "false")
```

- [ ] **Step 2.9: Run the full market-stats test file to verify no regressions**

Run: `.venv/Scripts/python.exe -m pytest tests/test_agent_market_stats.py tests/test_agent_market_stats_schemas.py -v`
Expected: All tests pass. Old + new.

- [ ] **Step 2.10: Lint + format**

Run: `ruff check stock_data/api/routes/agent.py tests/test_agent_market_stats.py && ruff format stock_data/api/routes/agent.py tests/test_agent_market_stats.py`

Expected: no errors.

- [ ] **Step 2.11: Commit**

```bash
git add stock_data/api/routes/agent.py tests/test_agent_market_stats.py
git commit -m "feat(agent): add pools block to market-stats (TDD)

New /agent/market-stats query params: ?include_pools (default true),
?trade_date (YYYY-MM-DD, defaults to get_latest_trade_date_on_or_before
(today)). New limit_pools block in the response carrying zt + dt as
independently-nullable lists with per-pool error isolation.

_per-pool failure (zt raises) emits a {block: zt_pool} error entry,
leaves zt=null, and still attempts dt. Empty upstream lists pass through
unchanged (e.g. pre-market today).

Cache key extended to three dimensions: (include_boards, include_pools,
trade_date). MD projection adds ## 涨跌停 section with per-pool tables.

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Task 3: Slim market-context (remove dragon-tiger + limit_pools)

**Files:**
- Modify: `stock_data/api/schemas.py:1810-1903` (slim `MarketContextResponse`; delete dragon/pool schemas)
- Modify: `stock_data/api/routes/agent.py:571-597` (delete `_summarize_dragon_tiger`)
- Modify: `stock_data/api/routes/agent.py:713-874` (slim `get_market_context` handler)
- Modify: `stock_data/api/routes/agent.py:1744-1869` (slim `render_market_context_as_md`)
- Modify: `stock_data/api/routes/agent.py:1-110` (drop unused imports)
- Modify: `stock_data/api/cache.py:530-538` (slim `make_market_context_cache_key`)

**Interfaces:**
- Consumes: existing `MarketContextMessages`, `MarketContextResponse`
- Produces:
  - Slim `MarketContextResponse` with only `trade_date`, `is_trade_day`, `market_session`, `messages`, `summary`
  - `make_market_context_cache_key(flash_limit: int, trade_date: str) -> str` returning `f"agent_market_context:{flash_limit}:{trade_date}"`
  - Slim `get_market_context` with no `zt_pool`/`dt_pool`/`daily_dragon_tiger` attempts

This task will cause multiple existing market-context tests to FAIL (they assert old fields/behavior). Task 4 will clean those tests up. Per task right-sizing guidance, the reviewer gates are: (1) implementation review, (2) test cleanup review — separating them allows rejecting one without rejecting the other.

- [ ] **Step 3.1: Delete obsolete schemas in `stock_data/api/schemas.py`**

Delete these classes entirely (around lines 1830-1883):

```python
class MarketContextLimitPools(BaseModel):
    """涨跌停 block of /agent/market-context.

    Both pools forced to null in pre-market (per spec §3.2.3). Otherwise
    null only when the upstream failed entirely.
    """

    zt: list[dict] | None = Field(
        default=None,
        description="涨停池 list. null in pre-market OR on upstream failure.",
    )
    dt: list[dict] | None = Field(
        default=None,
        description="跌停池 list. null in pre-market OR on upstream failure.",
    )


class MarketContextDragonTigerSummaryTop(BaseModel):
    """One row in top_by_net_buy / top_by_net_sell."""

    code: str
    name: str
    net_buy_wan: float = Field(default=0, description="净买入(万元)")


class MarketContextDragonTigerSummary(BaseModel):
    """Server-side rollup over the day's dragon-tiger list."""

    total_net_buy_wan: float = Field(default=0, description="全市场净买入合计 (万元)")
    top_by_net_buy: list[MarketContextDragonTigerSummaryTop] = Field(
        default_factory=list,
        description="净买入 Top 10 (default)",
    )
    top_by_net_sell: list[MarketContextDragonTigerSummaryTop] = Field(
        default_factory=list,
        description="净卖出 Top 10 (default, signed net_buy_wan < 0)",
    )


class MarketContextDragonTiger(BaseModel):
    """龙虎榜 block of /agent/market-context.

    On upstream failure both fields are null (caller can detect via
    the explicit null).
    """

    stocks: list[dict] | None = Field(
        default=None,
        description="龙虎榜个股列表 (DailyDragonTigerStock-shaped dicts). null on failure.",
    )
    summary: MarketContextDragonTigerSummary | None = Field(
        default=None,
        description="Server-computed summary (totals + top 10). null on failure.",
    )
```

Also delete the comment block above `MarketContextLimitPools`:

```python
# ────────────────────────────────────────────────────────────────────────
# Agent market-context (Phase 2 §3.2.3 — news + zt/dt pools + dragon
# tiger aggregation). Replaces the originally-planned
# /agent/news/cls/bundle + /agent/zt + /agent/dragon-tiger trio.
# ────────────────────────────────────────────────────────────────────────
```

(Keep `MarketSession` literal + `MarketContextMessages` class — both still used.)

- [ ] **Step 3.2: Slim `MarketContextResponse`**

Replace the class (around line 1886):

```python
class MarketContextResponse(BaseModel):
    """GET response for /agent/market-context.

    Post-2026-09-02: messages-only snapshot. ZT/DT pools moved to
    /agent/market-stats; dragon-tiger removed entirely (callers use
    GET /api/v1/dragon-tiger directly).
    """

    trade_date: str = Field(description="The trade date this snapshot represents (YYYY-MM-DD).")
    is_trade_day: bool = Field(description="Whether today (server local) is a trade day.")
    market_session: MarketSession = Field(
        description="Server-local time + trade-calendar derived session label.",
    )
    messages: MarketContextMessages = Field(default_factory=MarketContextMessages)
    summary: dict = Field(
        default_factory=dict,
        description="{requested, ok, failed, elapsed_ms}",
    )
```

- [ ] **Step 3.3: Delete `_summarize_dragon_tiger` helper**

In `stock_data/api/routes/agent.py`, delete the function (around lines 571-597):

```python
def _summarize_dragon_tiger(stocks: list[dict]) -> MarketContextDragonTigerSummary:
    """Compute the dragon-tiger summary block.

    - total_net_buy_wan = sum across ALL rows (signed: positive = 净买入, negative = 净卖出)
    - top_by_net_buy: top 10 by net_buy_wan DESC (positive-first)
    - top_by_net_sell: top 10 by net_buy_wan ASC, but only rows with
      net_buy_wan < 0 (a positive row is by definition NOT a sell-side
      candidate; surfacing it as "top sell" would be misleading on
      all-positive days).
    """
    rows = [
        MarketContextDragonTigerSummaryTop(
            code=s.get("code", ""),
            name=s.get("name", ""),
            net_buy_wan=float(s.get("net_buy_wan") or 0),
        )
        for s in (stocks or [])
    ]
    total = sum(r.net_buy_wan for r in rows)
    top_buy = sorted(rows, key=lambda r: -r.net_buy_wan)[:10]
    negative_only = [r for r in rows if r.net_buy_wan < 0]
    top_sell = sorted(negative_only, key=lambda r: r.net_buy_wan)[:10]
    return MarketContextDragonTigerSummary(
        total_net_buy_wan=total,
        top_by_net_buy=top_buy,
        top_by_net_sell=top_sell,
    )
```

- [ ] **Step 3.4: Drop now-unused schema imports**

In `stock_data/api/routes/agent.py`, in the `from ..schemas import (...)` block (around line 70), remove these entries:

- `MarketContextDragonTiger`
- `MarketContextDragonTigerSummary`
- `MarketContextDragonTigerSummaryTop`
- `MarketContextLimitPools`

Keep `MarketContextMessages`, `MarketContextResponse` — still used.

- [ ] **Step 3.5: Slim `get_market_context` handler**

Replace the existing `get_market_context` handler (around line 713-874):

```python
@router.get(
    "/agent/market-context",
    response_model=MarketContextResponse,
    responses={
        500: {"model": ErrorResponse, "description": "Server error"},
    },
    tags=["agent"],
)
@endpoint_meta(
    summary="市场消息面快照（早报 + 复盘 + 快讯；含时段判断）",
    markets=["csi"],
    capabilities=[],
    depends_on=[
        "/api/v1/calendar",
        "/api/v1/news/morning-briefing",
        "/api/v1/news/market-recap",
        "/api/v1/news/flash",
        "calendar.is_trade_date",
        "calendar.get_latest_trade_date_on_or_before",
    ],
)
@map_errors
def get_market_context(
    flash_limit: int = Query(
        default=20,
        ge=1,
        le=200,
        description="快讯条数上限 1-200;默认 20;与上游 fetch_flash_news 的 pageSize 硬 cap 对齐",
    ),
    trade_date: str | None = Query(
        default=None,
        description=(
            "交易日 YYYY-MM-DD;不传默认 = get_latest_trade_date_on_or_before(today). "
            "影响早报/复盘查询日期;快讯不受影响(按实时)."
        ),
    ),
    format: str = Query(
        "json",
        pattern="^(json|md)$",
        description="Output format. json=application/json (default); md=text/markdown.",
    ),
) -> Response:
    """Aggregate morning-briefing + market-recap + flash.

    Per spec §3.2.3:
    - morning/recap return null on per-source failure (NOT 503);
    - flash always attempts;
    - zt/dt pools moved to /agent/market-stats (post-2026-09-02);
    - dragon-tiger removed entirely (callers use /api/v1/dragon-tiger).
    """
    if trade_date is not None and not _TRADE_DATE_RE.match(trade_date):
        raise HTTPException(
            status_code=400,
            detail={
                "error": "invalid_trade_date",
                "message": (
                    f"trade_date must be YYYY-MM-DD; got {trade_date!r}. "
                    "Empty = server-defaulted to most recent trade date on/before today."
                ),
            },
        )
    today_str = datetime.now(_CST).date().isoformat()
    is_trade_day = trade_calendar.is_trade_date(today_str)
    target_date = (
        trade_date
        or trade_calendar.get_latest_trade_date_on_or_before(today_str)
        or today_str
    )
    session = _classify_market_session(is_trade_day)

    cache_key = make_market_context_cache_key(flash_limit, target_date)
    hit = cached_lookup(get_quote_cache, cache_key, "agent_market_context")
    if hit is not None:
        return _render_agent("market-context", hit, format)

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

    result = MarketContextResponse(
        trade_date=target_date,
        is_trade_day=is_trade_day,
        market_session=session,  # type: ignore[arg-type]
        messages=MarketContextMessages(
            morning_briefing=results["morning_briefing"],
            market_recap=results["market_recap"],
            flash_news=results["flash_news"],
        ),
        summary=_batch_summary(len(attempts), n_ok, started),
    )
    cached_store(get_quote_cache, cache_key, result)
    return _render_agent("market-context", result, format)
```

- [ ] **Step 3.6: Slim `make_market_context_cache_key`**

In `stock_data/api/cache.py`, replace (around line 530):

```python
def make_market_context_cache_key(flash_limit: int, trade_date: str) -> str:
    """Cache key for GET /agent/market-context.

    Session removed (post-2026-09-02): the response no longer varies
    by session — pools and dragon-tiger moved out, so pre/intra/post/
    closed produce identical bodies for a given (flash_limit,
    trade_date). Kept the two-knob signature stable for backwards
    compatibility with any existing cache entries.
    """
    return f"agent_market_context:{flash_limit}:{trade_date}"
```

- [ ] **Step 3.7: Slim `render_market_context_as_md`**

In `stock_data/api/routes/agent.py`, replace the function (around line 1744). Remove the `## 涨跌停` and `## 龙虎榜` sections:

```python
def render_market_context_as_md(p: MarketContextResponse) -> str:
    out = [
        f"# 市场全景 — {p.trade_date} {p.market_session}",
        f"**is_trade_day**: {p.is_trade_day}",
        "",
    ]
    msg = p.messages
    out.append("## 消息面")
    if msg.morning_briefing:
        _render_dict_block(out, "早报", msg.morning_briefing)
    else:
        out.append("### 早报 — （无）")
        out.append("")
    if msg.market_recap:
        _render_dict_block(out, "复盘", msg.market_recap)
    else:
        out.append("### 复盘 — （无）")
        out.append("")
    out.append(f"### 快讯 ({len(msg.flash_news)} 条)")
    if msg.flash_news:
        for f in msg.flash_news:
            title = f.get("title", "—")
            t = f.get("publish_time", "")
            src = f.get("source", "")
            url = f.get("url", "")
            content = f.get("content", "")
            line = f"- [{t}] {title}"
            if src:
                line += f" _(source: {src})_"
            if url:
                line += f" [link]({url})"
            out.append(line)
            if content:
                out.append(f"  {content}")
    else:
        out.append("（无）")
    out.append("")
    s = p.summary or {}
    out.append(
        f"## 汇总 — requested {s.get('requested', '?')}, "
        f"ok {s.get('ok', '?')}, failed {s.get('failed', '?')}, "
        f"elapsed {s.get('elapsed_ms', '?')}ms"
    )
    return "\n".join(out)
```

- [ ] **Step 3.8: Run market-context tests to confirm expected failures**

Run: `.venv/Scripts/python.exe -m pytest tests/test_agent_endpoints.py::TestMarketContext -v`
Expected: Many failures — tests still assert `limit_pools`, `dragon_tiger` fields, and `make_market_context_cache_key` 3-arg signature. This is expected and the cleanup happens in Task 4.

- [ ] **Step 3.9: Run market-stats tests to confirm they still pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_agent_market_stats.py -v`
Expected: All pass (this task didn't touch market-stats).

- [ ] **Step 3.10: Lint + format**

Run: `ruff check stock_data/api/schemas.py stock_data/api/routes/agent.py stock_data/api/cache.py && ruff format stock_data/api/schemas.py stock_data/api/routes/agent.py stock_data/api/cache.py`

Expected: no errors. May need to address unused-import warnings (e.g., `Callable` is no longer used if both handlers shed their Callable-typed lists).

- [ ] **Step 3.11: Commit**

```bash
git add stock_data/api/schemas.py stock_data/api/routes/agent.py stock_data/api/cache.py
git commit -m "refactor(agent): slim market-context to messages-only

Remove dragon_tiger + limit_pools blocks. Morning briefing, market
recap, flash news only. Trade_date gate retained; session label
retained for the response field.

Dragon-tiger functionality preserved via the standalone
GET /api/v1/dragon-tiger endpoint (no behavior lost). ZT/DT pools
now live in /agent/market-stats (see prior commit).

Cache key drops the session dimension: response no longer varies by
session — pools moved out, so pre/intra/post/closed produce identical
bodies for a given (flash_limit, trade_date). Existing tests pin the
old contract; cleanup follows in the next commit.

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Task 4: Test cleanup + verification

**Files:**
- Modify: `tests/test_agent_endpoints.py:706-986` (update `TestMarketContext`)
- Modify: `tests/test_agent_endpoints.py:1169-1190` (update `TestFormatMd.test_market_context_md`)
- Modify: `tests/test_agent_endpoints.py:956-978` (add `test_market_context_cache_key_omits_session`)

**Interfaces:**
- Consumes: slim `MarketContextResponse` (no `limit_pools`, no `dragon_tiger`); slim `make_market_context_cache_key(flash_limit, trade_date)` (no session)
- Produces: a passing `TestMarketContext` test class reflecting the slim contract

- [ ] **Step 4.1: Delete obsolete `TestMarketContext` tests**

In `tests/test_agent_endpoints.py`, delete these methods from `TestMarketContext` (around line 706-986):

- `test_pre_market_pools_forced_null` — no pools field
- `test_dragon_tiger_failure_isolated_other_blocks_served` — no dragon-tiger field
- `test_market_context_pre_market_summary_drops_pool_attempts` — pre-market no longer affects summary
- `test_market_context_cache_key_includes_session` — cache key no longer has session
- `test_market_context_zt_dt_full_pool_table` — no pools section
- `test_market_context_dragon_tiger_full_table` — no dragon-tiger section
- `test_market_context_dragon_tiger_summary_still_present` — no dragon-tiger section

- [ ] **Step 4.2: Update `test_happy_path_all_blocks_present` for slim behavior**

In `tests/test_agent_endpoints.py`, rename and update the method (around line 747):

```python
def test_messages_only_no_pools_no_dragon_tiger(self, client, monkeypatch):
    """Slim market-context: only messages block. No limit_pools, no dragon_tiger."""
    from stock_data.api.routes import agent as agent_module

    self._patch_all_ok(monkeypatch)
    monkeypatch.setattr(
        agent_module,
        "_classify_market_session",
        lambda _is_td: "post-market",
    )
    response = client.get("/api/v1/agent/market-context?flash_limit=10")
    assert response.status_code == 200
    data = response.json()
    # trade_date resolved to a YYYY-MM-DD
    assert len(data["trade_date"]) == 10
    assert "is_trade_day" in data
    assert data["market_session"] in {"pre-market", "intraday", "post-market", "closed"}
    # news block
    assert data["messages"]["morning_briefing"]["title"] == "早报"
    assert data["messages"]["market_recap"]["title"] == "复盘"
    assert len(data["messages"]["flash_news"]) == 1
    # Post-2026-09-02: dragon_tiger and limit_pools MUST NOT appear
    assert "dragon_tiger" not in data
    assert "limit_pools" not in data
    # summary has the standard {requested, ok, failed, elapsed_ms} shape
    assert "summary" in data
    assert "requested" in data["summary"]
```

- [ ] **Step 4.3: Update `test_morning_briefing_null_on_no_article` to drop pool mocks**

In `tests/test_agent_endpoints.py`, replace the method (around line 804):

```python
def test_morning_briefing_null_on_no_article(self, client, monkeypatch):
    """morning_briefing returns (None, '') (no article for this date) → morning_briefing=null in response."""
    from unittest.mock import MagicMock

    from stock_data.api.routes import agent as agent_module

    mock_manager = MagicMock()
    mock_manager.get_morning_briefing.return_value = (None, "")
    mock_manager.get_market_recap.return_value = (
        {"title": "复盘", "date": "2026-07-25"},
        "cls",
    )
    mock_manager.get_flash_news.return_value = ([], "eastmoney")
    monkeypatch.setattr(agent_module, "get_manager", lambda: mock_manager)

    response = client.get("/api/v1/agent/market-context")
    assert response.status_code == 200
    data = response.json()
    assert data["messages"]["morning_briefing"] is None
    # market_recap still ok
    assert data["messages"]["market_recap"] is not None
```

- [ ] **Step 4.4: Update `test_trade_date_query_param` to drop dragon-tiger mock**

In `tests/test_agent_endpoints.py`, replace the method (around line 854):

```python
def test_trade_date_query_param(self, client, monkeypatch):
    """?trade_date=YYYY-MM-DD is plumbed to morning_briefing + market_recap."""
    from unittest.mock import MagicMock

    from stock_data.api.routes import agent as agent_module

    mock_manager = MagicMock()
    mock_manager.get_morning_briefing.return_value = (None, "")
    mock_manager.get_market_recap.return_value = (None, "")
    mock_manager.get_flash_news.return_value = ([], "eastmoney")
    monkeypatch.setattr(agent_module, "get_manager", lambda: mock_manager)

    response = client.get("/api/v1/agent/market-context?trade_date=2026-07-20")
    assert response.status_code == 200
    data = response.json()
    assert data["trade_date"] == "2026-07-20"
    # Date-keyed calls got 2026-07-20
    assert mock_manager.get_morning_briefing.call_args.args[0] == "2026-07-20"
    assert mock_manager.get_market_recap.call_args.args[0] == "2026-07-20"
    # Flash is NOT date-keyed
    assert mock_manager.get_flash_news.call_args.kwargs.get("limit") == 20
```

- [ ] **Step 4.5: Update `test_cache_hit_same_flash_limit_and_date` to drop dragon-tiger mock**

In `tests/test_agent_endpoints.py`, replace the method (around line 877):

```python
def test_cache_hit_same_flash_limit_and_date(self, client, monkeypatch):
    """Second request with same (flash_limit, trade_date) hits cache."""
    from unittest.mock import MagicMock

    from stock_data.api.routes import agent as agent_module

    mock_manager = MagicMock()
    mock_manager.get_morning_briefing.return_value = (None, "")
    mock_manager.get_market_recap.return_value = (None, "")
    mock_manager.get_flash_news.return_value = ([], "eastmoney")
    monkeypatch.setattr(agent_module, "get_manager", lambda: mock_manager)

    client.get("/api/v1/agent/market-context?flash_limit=20&trade_date=2026-07-25")
    assert mock_manager.get_morning_briefing.call_count == 1
    client.get("/api/v1/agent/market-context?flash_limit=20&trade_date=2026-07-25")
    assert mock_manager.get_morning_briefing.call_count == 1
```

- [ ] **Step 4.6: Update `test_market_context_md` in `TestFormatMd`**

In `tests/test_agent_endpoints.py` (around line 1169), replace:

```python
def test_market_context_md(self, client, monkeypatch):
    from stock_data.api.routes import agent as agent_module

    TestMarketContext._patch_all_ok(self, monkeypatch)
    monkeypatch.setattr(agent_module, "_classify_market_session", lambda _is_td: "post-market")
    r = client.get("/api/v1/agent/market-context?flash_limit=10&format=md")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/markdown")
    body = r.text
    assert "# 市场全景 —" in body
    assert "post-market" in body
    # news section
    assert "## 消息面" in body
    assert "### 早报" in body
    assert "### 复盘" in body
    assert "### 快讯" in body
    # Post-2026-09-02: pools and dragon-tiger sections MUST NOT appear
    assert "## 涨跌停" not in body
    assert "## 龙虎榜" not in body
```

- [ ] **Step 4.7: Add `test_market_context_cache_key_omits_session`**

In `tests/test_agent_endpoints.py`, in `TestPhase2DefensiveGuards` (around line 956), replace `test_market_context_cache_key_includes_session` with:

```python
def test_market_context_cache_key_omits_session(self):
    """Cache key no longer includes session (post-2026-09-02 slim).

    Same (flash_limit, trade_date) → same key. Different inputs →
    different keys. The session dimension was dropped because the
    response content no longer varies by session (pools and
    dragon-tiger moved out).
    """
    from stock_data.api.cache import make_market_context_cache_key

    assert make_market_context_cache_key(20, "2026-07-25") == (
        "agent_market_context:20:2026-07-25"
    )
    # Different trade_date → different keys
    assert make_market_context_cache_key(20, "2026-07-25") != make_market_context_cache_key(
        20, "2026-07-26"
    )
    # Different flash_limit → different keys
    assert make_market_context_cache_key(20, "2026-07-25") != make_market_context_cache_key(
        10, "2026-07-25"
    )
```

- [ ] **Step 4.8: Run the full market-context test class to verify all green**

Run: `.venv/Scripts/python.exe -m pytest tests/test_agent_endpoints.py::TestMarketContext tests/test_agent_endpoints.py::TestFormatMd tests/test_agent_endpoints.py::TestPhase2DefensiveGuards -v`
Expected: All tests pass.

- [ ] **Step 4.9: Run the full test suite to verify no regressions**

Run: `.venv/Scripts/python.exe -m pytest -v`
Expected: All tests pass (excluding any `live_network` / `requires_token` markers, which are skipped by default per `pyproject.toml`).

- [ ] **Step 4.10: Lint + format final pass**

Run: `ruff check . && ruff format .`

Expected: no errors.

- [ ] **Step 4.11: Commit**

```bash
git add tests/test_agent_endpoints.py
git commit -m "test(agent): update market-context tests for slim contract

TestMarketContext now pins the messages-only contract:
- test_happy_path_all_blocks_present renamed to test_messages_only_
  no_pools_no_dragon_tiger; asserts 'limit_pools' / 'dragon_tiger'
  keys are absent from the JSON response
- test_pre_market_pools_forced_null: deleted (no pools field)
- test_dragon_tiger_failure_isolated_other_blocks_served: deleted
- test_market_context_pre_market_summary_drops_pool_attempts: deleted
- test_market_context_cache_key_includes_session: deleted (key
  no longer has session); replaced with
  test_market_context_cache_key_omits_session
- test_market_context_zt_dt_full_pool_table: deleted
- test_market_context_dragon_tiger_full_table: deleted
- test_market_context_dragon_tiger_summary_still_present: deleted

TestFormatMd.test_market_context_md: asserts ## 涨跌停 and ## 龙虎榜
sections are NOT in the markdown body.

Co-Authored-By: Claude <noreply@anthropic.com>"
```

- [ ] **Step 4.12: Merge feat branch**

After all 4 commits land green on `feat/agent-market-stats-pools`, merge to master:

```bash
git checkout master
git merge --no-ff feat/agent-market-stats-pools -m "Merge feat/agent-market-stats-pools: market-context slim + zt/dt → market-stats"
```

Verify post-merge: re-run the full suite on master:

```bash
.venv/Scripts/python.exe -m pytest -v
```

Expected: all pass.

---

## Self-Review Notes (post-write)

**Spec coverage** — each spec section mapped to a task:

| Spec section | Task |
|---|---|
| §1 Background | (no implementation) |
| §2 Public API surface | Tasks 1 (schemas), 2 (handler + MD), 3 (slim context) |
| §3.1 Files touched | Tasks 1, 2, 3, 4 (all file changes) |
| §3.2 get_market_context slim | Task 3.5 |
| §3.3 _compute_limit_pools_block | Task 2.3 |
| §3.4 get_market_stats extension | Task 2.4 |
| §3.5 Schema changes | Task 1.3-1.5, 3.1-3.2 |
| §3.6 Cache keys | Task 1.9, 3.6 |
| §3.7 MD projection | Task 2.5-2.6, 3.7 |
| §4 Error isolation matrix | Task 2 (helper), 3 (slim) |
| §5.1 test_agent_endpoints updates | Task 4 |
| §5.2 test_agent_market_stats additions | Task 2 |
| §5.3 test_agent_market_stats_schemas additions | Task 1 |
| §6 Anti-patterns | (no implementation, guardrails baked into the plan via "Global Constraints") |
| §7 Out of scope | (no implementation) |

**Placeholder scan** — no "TBD", "TODO", "implement later" in implementation steps. Two `TODO(Task 2)` markers in Step 1.11 are intentional breadcrumbs explaining the temporary placeholder state.

**Type consistency** — `MarketStatsLimitPools`, `MarketStatsErrorEntry(block="zt_pool"|"dt_pool")`, `make_market_stats_cache_key(include_boards, include_pools, trade_date)`, `make_market_context_cache_key(flash_limit, trade_date)` — defined in Task 1, consumed in Tasks 2-4 with matching signatures.

**Branch strategy** — implementation commits on `feat/agent-market-stats-pools` per CLAUDE.md; plan file (this doc) on master per project rule.
