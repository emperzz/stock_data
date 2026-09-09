# Agent Market-Stats Board Movers (Top-3 Gainers/Losers) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `boards.top_gainers` and `boards.top_losers` (each a list of up to 3 `BoardMoverEntry` with `MinimalQuote`) to `/api/v1/agent/market-stats` response, derived from the existing single THS board-list upstream call.

**Architecture:** Pure-function helpers (`_build_minimal_quote_from_list_row_dict`, `_select_top_board_movers`) compute the movers in-memory from the ~383 rows already returned by `stock_board_cache.get_board_list(..., include_quote=True)`. No new fetcher, no new query param, no new cache key. The boards block of `build_market_stats_response` calls the helper and assigns the result onto the existing `BoardStats` instance. MD renderer gains a `_md_top_movers` helper.

**Tech Stack:** Python 3.12, FastAPI, Pydantic v2, pytest, ruff format, monkeypatch-based route-layer mocking (no live_network).

**Spec:** `docs/superpowers/specs/2026-09-09-agent-market-stats-board-movers-design.md`

**Branch strategy:** Per CLAUDE.md "Skip branch for trivial changes", `*.md` commits go to master. This plan file AND the spec file at `docs/superpowers/specs/2026-09-09-agent-market-stats-board-movers-design.md` are `*.md` → both already on master. Implementation commits → `feat/agent-market-stats-board-movers` branch (Python server code per project rule).

---

## Global Constraints

These apply to every task in this plan:

- **Python venv**: `.venv/Scripts/python.exe` (CLAUDE.md "Common Commands"). System `python` will silently break akshare-routed paths.
- **Default `pytest`** skips `live_network` and `requires_token` markers (per `pyproject.toml` `addopts`). Fast dev loop. No marker override needed for these tasks — all tests mock at the route layer.
- **TDD**: write failing test first, run it (verify it fails for the right reason), implement minimal code, run again (verify pass), commit.
- **Per-project anti-patterns** (CLAUDE.md + memory):
  - No hardcoded fetcher class in manager routes — already true for this endpoint; the new helper is pure logic and does NOT call any fetcher.
  - Don't add `DataCapability` flags — none needed.
  - **Don't** leak `ts_code` suffixes — board codes flow through verbatim from upstream; already canonical per `fetch_boards_with_zzshare_backfill`.
  - **Don't** mix inline imports — keep top-level imports.
  - **Don't** assume test contract from spec — tests pin the contract (memory: `[[test-wins-spec-code-test-disagree]]`).
  - **Don't** cache realtime quote data in SQLite — the boards upstream call is unchanged (still `include_quote=True` → always-fresh per request).
- **Response cache**: shared `get_quote_cache` 60s TTL via `cached_lookup` / `cached_store`. Existing convention; unchanged.
- **Pydantic v2** (`BaseModel`, `Field(default_factory=list)`).
- **Code style**: ruff-formatted; run `ruff format .` before commits.
- **Commit messages**: end with `Co-Authored-By: Claude <noreply@anthropic.com>`.
- **Don't write to CLAUDE.md** unless explicitly asked. Spec and plan are the project substrate; changes here don't need CLAUDE.md updates (the project already pins market-stats semantics via the spec).

---

## File Structure

Files touched by this plan:

| File | Responsibility | Tasks |
|---|---|---|
| `stock_data/api/schemas.py` | Add `BoardMoverEntry`; extend `BoardStats` with `top_gainers` / `top_losers` list fields | 1 |
| `stock_data/api/routes/agent.py` | Add `_build_minimal_quote_from_list_row_dict` + `_select_top_board_movers` helpers; wire into `build_market_stats_response`; add `_md_top_movers` MD helper; extend `_md_stats_block` | 2, 3, 4 |
| `tests/test_agent_market_stats_schemas.py` | Add tests for new `BoardStats` fields + `BoardMoverEntry` shape | 1 |
| `tests/test_agent_market_stats.py` | Add tests for top-movers behavior, failure modes, empty-upstream, MD rendering | 3, 4 |

Decomposition rationale: schema is the contract; pure helpers are independently testable without route plumbing; handler integration is a single wiring step; MD renderer is its own commit so the JSON-shape review and the MD-shape review don't block each other.

---

## Task 1: Schema additions

**Files:**
- Modify: `stock_data/api/schemas.py:2123-2136` (extend `BoardStats` with `top_gainers` / `top_losers`)
- Modify: `stock_data/api/schemas.py` (add `BoardMoverEntry` near other batch-profile schemas; suggested insertion: just before `BoardStats` at line 2123)
- Test: `tests/test_agent_market_stats_schemas.py` (append new tests)

**Interfaces:**
- Consumes: existing `MinimalQuote` schema (`schemas.py:1694`)
- Produces:
  - `class BoardMoverEntry(BaseModel)` with fields `code: str`, `name: str`, `type: str`, `subtype: str`, `source: str`, `quote: MinimalQuote | None = None`
  - `BoardStats.top_gainers: list[BoardMoverEntry]` (default `[]`)
  - `BoardStats.top_losers: list[BoardMoverEntry]` (default `[]`)

This task is purely additive — no existing test should break. If a test breaks here, stop and investigate before committing.

- [ ] **Step 1.1: Write failing tests for new schema**

Append to `tests/test_agent_market_stats_schemas.py`:

```python
from stock_data.api.schemas import BoardMoverEntry, BoardStats, MinimalQuote


def test_board_stats_top_movers_default_empty_list():
    """BoardStats without explicit top_movers defaults to empty lists."""
    bs = BoardStats(
        sample_size=383,
        mean_pct=0.52,
        median_pct=0.31,
        max_pct=5.82,
        min_pct=-3.15,
        up_count=187,
        down_count=162,
        flat_count=34,
        buckets=[],
    )
    assert bs.top_gainers == []
    assert bs.top_losers == []


def test_board_stats_top_movers_can_be_populated():
    """BoardStats accepts explicit top_gainers / top_losers lists."""
    entry = BoardMoverEntry(
        code="881154",
        name="半导体",
        type="industry",
        subtype="881",
        source="ths",
        quote=MinimalQuote(change_pct=5.82),
    )
    bs = BoardStats(
        sample_size=383,
        mean_pct=0.52,
        median_pct=0.31,
        max_pct=5.82,
        min_pct=-3.15,
        up_count=187,
        down_count=162,
        flat_count=34,
        buckets=[],
        top_gainers=[entry],
        top_losers=[entry],
    )
    assert len(bs.top_gainers) == 1
    assert bs.top_gainers[0].code == "881154"
    assert bs.top_gainers[0].quote.change_pct == 5.82


def test_board_mover_entry_quote_none_default():
    """BoardMoverEntry.quote defaults to None (not required)."""
    entry = BoardMoverEntry(
        code="881154",
        name="半导体",
        type="industry",
        subtype="881",
        source="ths",
    )
    assert entry.quote is None


def test_board_mover_entry_sparse_minimal_quote():
    """A quote built from a sparse get_board_list row has most fields None."""
    # Mimic what the upstream returns in practice — only 6 fields populated
    sparse_quote = MinimalQuote(
        change_pct=5.82,
        volume=2345678,
        volume_unit="wan_shou",
        amount=1.2e9,
        up_count=23,
        down_count=5,
        net_inflow=4.5,        # pass-through (亿元), NOT ×1e8
    )
    entry = BoardMoverEntry(
        code="881154",
        name="半导体",
        type="industry",
        subtype="881",
        source="ths",
        platecode="881154",
        quote=sparse_quote,
    )
    # populated fields
    assert entry.quote.change_pct == 5.82
    assert entry.quote.volume == 2345678
    assert entry.quote.amount == 1.2e9
    assert entry.quote.up_count == 23
    assert entry.quote.down_count == 5
    assert entry.quote.net_inflow == 4.5            # pass-through (亿元)
    # platecode round-trips
    assert entry.platecode == "881154"
    # sparse fields
    assert entry.quote.price is None
    assert entry.quote.open is None
    assert entry.quote.rank is None
    assert entry.quote.pe_ratio is None  # stock-only


def test_board_mover_entry_platecode_optional():
    """platecode defaults to None (some upstream rows may not carry it)."""
    entry = BoardMoverEntry(
        code="881154", name="半导体", type="industry", subtype="881", source="ths",
    )
    assert entry.platecode is None
```

- [ ] **Step 1.2: Run tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_agent_market_stats_schemas.py -v`
Expected: FAIL — `ImportError: cannot import name 'BoardMoverEntry' from 'stock_data.api.schemas'` (or `AttributeError: type object 'BoardStats' has no attribute 'top_gainers'`).

- [ ] **Step 1.3: Add `BoardMoverEntry` schema**

In `stock_data/api/schemas.py`, add immediately above the existing `BoardStats` class (line 2123):

```python
class BoardMoverEntry(BaseModel):
    """One board in /agent/market-stats top_gainers / top_losers.

    Added 2026-09-09 alongside the spec amendment that adds top-3
    gainers / top-3 losers to the boards block. `quote` reuses the
    shared MinimalQuote schema (defined above) — same one across stock
    / index / board batch-profile endpoints. Sparse fields stay None
    when upstream doesn't populate them (matches the precedent set by
    /agent/boards/batch-profile).

    `platecode` is preserved as Optional[str] because the upstream row
    dict carries it (per fetch_boards_with_zzshare_backfill at
    persistence/board.py:911) and downstream consumers already expect
    to find it on board-shaped entries (matches the
    /api/v1/boards/{board_code}/stocks precedent). Concept boards may
    have None (sidebar-only rows — see ths_fetcher.py:1784-1788).
    """

    code: str
    name: str
    type: str
    subtype: str
    source: str
    platecode: str | None = None
    quote: MinimalQuote | None = None
```

- [ ] **Step 1.4: Extend `BoardStats` with two new fields**

In `stock_data/api/schemas.py`, modify the existing `BoardStats` class (line 2123) — add the two lines after `buckets: list[DistributionBucket]`:

```python
class BoardStats(BaseModel):
    """Full-market board statistics (THS source)."""

    sample_size: int = Field(ge=0)
    mean_pct: float | None
    median_pct: float | None
    max_pct: float | None
    min_pct: float | None
    up_count: int = Field(ge=0)
    down_count: int = Field(ge=0)
    flat_count: int = Field(ge=0)
    bin_width: float = 1.0
    source: str = ""
    buckets: list[DistributionBucket]
    # Added 2026-09-09: top movers for client dashboards. Always list
    # (never None) so consumers can iterate without null checks; list
    # may be empty when upstream returned 0 rows with non-None change_pct.
    top_gainers: list[BoardMoverEntry] = Field(default_factory=list)
    top_losers: list[BoardMoverEntry] = Field(default_factory=list)
```

- [ ] **Step 1.5: Run tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_agent_market_stats_schemas.py -v`
Expected: PASS (5 new tests + all existing tests).

- [ ] **Step 1.6: Commit**

```bash
git add stock_data/api/schemas.py tests/test_agent_market_stats_schemas.py
git commit -m "feat(schemas): add BoardMoverEntry + top_gainers/top_losers on BoardStats" -m "Adds the BoardMoverEntry shape (incl. platecode Optional, matching persistence/board.py:911 precedent) and two new nested list fields on BoardStats. Purely additive; existing MarketStatsResponse consumers see extra JSON keys (Pydantic default is permissive)." -m "Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Task 2: Pure helpers (`_build_minimal_quote_from_list_row_dict` + `_select_top_board_movers`)

**Files:**
- Modify: `stock_data/api/routes/agent.py` (add two new helpers near `_build_minimal_quote_from_board_dict` at line 1312)
- Test: `tests/test_agent_market_stats.py` (append new tests)

**Interfaces:**
- Produces:
  - `_build_minimal_quote_from_list_row_dict(row: dict) -> MinimalQuote` — maps a `stock_board_cache.get_board_list` row to `MinimalQuote`. 6 fields populated (`change_pct` / `volume` / `volume_unit="wan_shou"` / `amount` (×1e8) / `up_count` / `down_count` / `net_inflow`); the other 16 MinimalQuote fields stay None.
  - `_select_top_board_movers(rows: list[dict] | None, *, top_n: int = 3) -> tuple[list[BoardMoverEntry], list[BoardMoverEntry]]` — pure sort+filter; no upstream calls.

Both helpers are pure (no `manager`, no fetcher calls, no async, no cache). Easy to TDD.

- [ ] **Step 2.1: Write failing tests for both helpers**

Append to `tests/test_agent_market_stats.py`:

```python
def test_build_minimal_quote_from_list_row_dict_populates_six_fields():
    """Only the 6 board-relevant fields present in upstream are filled."""
    from stock_data.api.routes.agent import _build_minimal_quote_from_list_row_dict

    row = {
        "code": "881154",
        "name": "半导体",
        "change_pct": 5.82,
        "volume": 2345678,
        "amount": 12.0,           # THS upstream in 亿元
        "net_inflow": 4.5,        # upstream in 亿元
        "up_count": 23,
        "down_count": 5,
    }
    quote = _build_minimal_quote_from_list_row_dict(row)
    assert quote.change_pct == 5.82
    assert quote.volume == 2345678
    assert quote.volume_unit == "wan_shou"
    assert quote.amount == 12.0 * 1e8            # ×1e8 conversion
    assert quote.up_count == 23
    assert quote.down_count == 5
    assert quote.net_inflow == 4.5               # pass-through (NOT ×1e8)
    # sparse fields stay None
    assert quote.price is None
    assert quote.open is None
    assert quote.high is None
    assert quote.low is None
    assert quote.prev_close is None
    assert quote.change_amount is None
    assert quote.rank is None


def test_build_minimal_quote_handles_missing_fields():
    """All-None quote when row has no quote fields at all."""
    from stock_data.api.routes.agent import _build_minimal_quote_from_list_row_dict

    row = {"code": "BK0001", "name": "X"}  # no quote fields
    quote = _build_minimal_quote_from_list_row_dict(row)
    assert quote.change_pct is None
    assert quote.amount is None
    assert quote.up_count is None
    assert quote.volume_unit == "wan_shou"  # always set


def test_select_top_board_movers_sorts_correctly():
    """Top 3 by change_pct DESC, bottom 3 by ASC.

    Per spec §3.1 — BOTH lists mirror the same eligible set. With 6
    eligible rows and top_n=3, both lists have length 3 (NOT a sign
    filter that would yield 3 gainers + 3 losers from a pos/neg split).
    This test pins that invariant.
    """
    from stock_data.api.routes.agent import _select_top_board_movers

    rows = [
        {"code": "BK0001", "name": "A", "type": "industry", "subtype": "881", "source": "ths", "change_pct": 1.0},
        {"code": "BK0002", "name": "B", "type": "industry", "subtype": "881", "source": "ths", "change_pct": 5.0},
        {"code": "BK0003", "name": "C", "type": "industry", "subtype": "881", "source": "ths", "change_pct": -2.0},
        {"code": "BK0004", "name": "D", "type": "industry", "subtype": "881", "source": "ths", "change_pct": 3.0},
        {"code": "BK0005", "name": "E", "type": "industry", "subtype": "881", "source": "ths", "change_pct": -5.0},
        {"code": "BK0006", "name": "F", "type": "industry", "subtype": "881", "source": "ths", "change_pct": 2.0},
    ]
    gainers, losers = _select_top_board_movers(rows, top_n=3)
    assert len(gainers) == 3
    assert len(losers) == 3
    # gainers sorted DESC: BK0002 (5.0), BK0004 (3.0), BK0006 (2.0)
    assert [g.code for g in gainers] == ["BK0002", "BK0004", "BK0006"]
    # losers sorted ASC: BK0005 (-5.0), BK0003 (-2.0), BK0001 (1.0)
    assert [l.code for l in losers] == ["BK0005", "BK0003", "BK0001"]


def test_select_top_board_movers_excludes_none_change_pct():
    """Rows with None / non-numeric change_pct are skipped."""
    from stock_data.api.routes.agent import _select_top_board_movers

    rows = [
        {"code": "BK0001", "change_pct": 2.0},
        {"code": "BK0002", "change_pct": None},
        {"code": "BK0003", "change_pct": "—"},        # upstream sentinel
        {"code": "BK0004", "change_pct": 1.0},
        {"code": "BK0005"},                          # missing key
    ]
    gainers, losers = _select_top_board_movers(rows, top_n=3)
    codes = {g.code for g in gainers}
    assert codes == {"BK0001", "BK0004"}            # only 2 valid rows
    assert all(l.code in {"BK0001", "BK0004"} for l in losers)


def test_select_top_board_movers_tie_break_code_asc():
    """Identical change_pct → sorted by code ASC (deterministic)."""
    from stock_data.api.routes.agent import _select_top_board_movers

    rows = [
        {"code": "BK0009", "change_pct": 2.0},
        {"code": "BK0001", "change_pct": 2.0},
        {"code": "BK0005", "change_pct": 2.0},
        {"code": "BK0003", "change_pct": 2.0},
    ]
    gainers, _ = _select_top_board_movers(rows, top_n=3)
    assert [g.code for g in gainers] == ["BK0001", "BK0003", "BK0005"]


def test_select_top_board_movers_fewer_than_three():
    """When fewer than 3 rows qualify, both lists mirror the available rows.

    Per spec §3.1 — there is NO sign filter. With 2 eligible rows and
    top_n=3, both lists have length 2 (NOT 1 gainer + 1 loser); the 2
    rows appear in both lists at different ranks. This test pins that
    invariant.
    """
    from stock_data.api.routes.agent import _select_top_board_movers

    rows = [
        {"code": "BK0001", "change_pct": 2.0},
        {"code": "BK0002", "change_pct": -1.0},
    ]
    gainers, losers = _select_top_board_movers(rows, top_n=3)
    assert len(gainers) == 2
    assert len(losers) == 2
    # gainers sorted DESC: BK0001 (+2.0), BK0002 (-1.0)
    assert [g.code for g in gainers] == ["BK0001", "BK0002"]
    # losers sorted ASC: BK0002 (-1.0), BK0001 (+2.0) — same set, reversed order
    assert [l.code for l in losers] == ["BK0002", "BK0001"]


def test_select_top_board_movers_empty_input():
    """Empty / None input → two empty lists (no exception)."""
    from stock_data.api.routes.agent import _select_top_board_movers

    assert _select_top_board_movers([], top_n=3) == ([], [])
    assert _select_top_board_movers(None, top_n=3) == ([], [])


def test_select_top_board_movers_entry_carries_minimal_quote():
    """Each BoardMoverEntry.quote is built via the quote helper."""
    from stock_data.api.routes.agent import _select_top_board_movers

    rows = [{"code": "BK0001", "name": "半导体", "type": "industry", "subtype": "881",
             "source": "ths", "change_pct": 5.82, "volume": 2345678, "amount": 12.0,
             "up_count": 23, "down_count": 5, "net_inflow": 4.5}]
    gainers, _ = _select_top_board_movers(rows, top_n=3)
    assert gainers[0].code == "BK0001"
    assert gainers[0].name == "半导体"
    assert gainers[0].type == "industry"
    assert gainers[0].source == "ths"
    assert gainers[0].quote is not None
    assert gainers[0].quote.change_pct == 5.82
    assert gainers[0].quote.amount == 12.0 * 1e8
```

- [ ] **Step 2.2: Run tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_agent_market_stats.py -v -k "build_minimal_quote_from_list_row_dict or select_top_board_movers"`
Expected: FAIL — `ImportError: cannot import name '_build_minimal_quote_from_list_row_dict' from 'stock_data.api.routes.agent'`.

- [ ] **Step 2.3: Add the two pure helpers**

In `stock_data/api/routes/agent.py`, add immediately after `_build_minimal_quote_from_board_dict` (which ends at line 1339). Also add the `BoardMoverEntry` import to the schema import block at line 72-108.

Add to imports (line 72-108 area, alphabetical placement — find where `BatchFeatures, BoardProfile, BoardsBatchProfileRequest,` block starts; insert `BoardMoverEntry,` **before** `BoardProfile` (alphabetical: M < P)):

```python
    BoardMoverEntry,
    BoardProfile,
```

Then add helpers after `_build_minimal_quote_from_board_dict`:

```python
def _build_minimal_quote_from_list_row_dict(row: dict) -> MinimalQuote:
    """Map a ``stock_board_cache.get_board_list`` row to ``MinimalQuote``.

    The ``get_board_list`` row shape (with ``include_quote=True``) is
    sparser than ``get_board_realtime``'s — only 6 of the board-relevant
    ``MinimalQuote`` fields have upstream values: ``change_pct`` /
    ``volume`` / ``amount`` / ``net_inflow`` / ``up_count`` /
    ``down_count``. The other 7 board-relevant fields (``price`` /
    ``change_amount`` / ``OHLC`` / ``prev_close`` / ``rank``) and the 8
    stock-only fields stay ``None``. This matches the
    ``/agent/boards/batch-profile`` precedent where "field present in
    schema, ``None`` upstream" is the documented contract.

    ``amount`` is multiplied by ``1e8`` to convert THS upstream 亿元 →
    元, matching the conversion already applied at
    ``routes/boards.py:857`` and inside ``_build_minimal_quote_from_board_dict``
    for the realtime path. ``net_inflow`` stays as-is (board upstream
    is already 亿元; consumers divide by ``1e8`` if they want 元).
    Spec: docs/superpowers/specs/2026-09-09-agent-market-stats-board-movers-design.md §3.2
    """
    raw_amount = row.get("amount")
    return MinimalQuote(
        change_pct=row.get("change_pct"),
        volume=row.get("volume"),
        volume_unit="wan_shou",
        amount=(raw_amount * 1e8) if raw_amount is not None else None,
        up_count=row.get("up_count"),
        down_count=row.get("down_count"),
        net_inflow=row.get("net_inflow"),
    )


def _select_top_board_movers(
    rows: list[dict] | None, *, top_n: int = 3
) -> tuple[list[BoardMoverEntry], list[BoardMoverEntry]]:
    """Pick top-N gainers and losers from the ``get_board_list`` rows.

    Filters out rows with non-finite ``change_pct`` (``None`` / ``bool``
    / non-numeric — same predicate the aggregate stats use at
    ``agent.py:1547``). Tie-breaker = ``code`` ASC for determinism.
    Returns two independent lists — both may contain the same row if
    its ``change_pct == 0.0`` and a tie emerges at the boundary.

    Pure function: no upstream calls, no side effects.
    Spec: docs/superpowers/specs/2026-09-09-agent-market-stats-board-movers-design.md §3.1
    """
    def _pct(r):
        v = r.get("change_pct")
        return v if isinstance(v, (int, float)) and not isinstance(v, bool) else None

    eligible = [(r, _pct(r)) for r in (rows or [])]
    eligible = [(r, p) for r, p in eligible if p is not None]

    def _code(r):
        return r.get("code") or ""

    gainers_sorted = sorted(eligible, key=lambda rp: (-rp[1], _code(rp[0])))[:top_n]
    losers_sorted = sorted(eligible, key=lambda rp: (rp[1], _code(rp[0])))[:top_n]

    def _to_entry(rp):
        r, _ = rp
        return BoardMoverEntry(
            code=r.get("code") or "",
            name=r.get("name") or "",
            type=r.get("type") or "",
            subtype=r.get("subtype") or "",
            source=r.get("source") or "ths",
            platecode=r.get("platecode"),  # None for sidebar-only concept rows
            quote=_build_minimal_quote_from_list_row_dict(r),
        )

    return [_to_entry(rp) for rp in gainers_sorted], [_to_entry(rp) for rp in losers_sorted]
```

- [ ] **Step 2.4: Run tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_agent_market_stats.py -v -k "build_minimal_quote_from_list_row_dict or select_top_board_movers"`
Expected: PASS (8 new tests).

Also run the full schema test file to ensure imports didn't break anything:
Run: `.venv/Scripts/python.exe -m pytest tests/test_agent_market_stats_schemas.py -v`
Expected: PASS (5 new + existing — added platecode optional test in Task 1).

- [ ] **Step 2.5: Commit**

```bash
git add stock_data/api/routes/agent.py tests/test_agent_market_stats.py
git commit -m "feat(agent): add pure helpers for board top movers" -m "Adds _build_minimal_quote_from_list_row_dict (quote-shape adapter for get_board_list rows) and _select_top_board_movers (pure sort + filter for top-N gainers / losers). No upstream calls, no cache impact — Task 3 wires into the boards block." -m "Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Task 3: Handler integration (`build_market_stats_response` boards block)

**Files:**
- Modify: `stock_data/api/routes/agent.py:1535-1565` (boards block of `build_market_stats_response`)
- Test: `tests/test_agent_market_stats.py` (append new tests)

**Interfaces:**
- Consumes: `_select_top_board_movers` from Task 2 (returns `tuple[list[BoardMoverEntry], list[BoardMoverEntry]]`)
- Produces: `boards_stats.top_gainers` and `boards_stats.top_losers` populated when boards upstream succeeds; `[]` when upstream returns empty list; absent when boards upstream raises (boards block itself is `None`).

- [ ] **Step 3.1: Write failing tests for boards block integration**

**Before writing tests**, update the `_patch_manager` helper in
`tests/test_agent_market_stats.py` (around line 69) to ALSO stub
`get_zt_pool`, otherwise the `include_pools=True` (default) code path
will hit an unstubbed MagicMock and the test will spuriously fail /
inject a `zt_pool` errors[] entry that the new assertions don't check
for. Existing tests rely on the route's try/except absorbing the
failure (verified in `agent.py:683-705`); making the helper complete
removes that brittleness for both old and new tests.

Replace `_patch_manager`:

```python
def _patch_manager(monkeypatch, *, quotes):
    """Patch the manager method the route uses.

    NOTE: the route calls ``manager.get_realtime_quotes`` (stocks
    block) AND ``manager.get_zt_pool`` (limit_pools block, when
    ``include_pools=True`` — the default). The boards block goes
    through ``stock_board_cache.get_board_list`` (see
    ``_patch_board_cache``), so no ``get_all_boards`` stub is needed.
    """
    fake_manager = MagicMock()
    fake_manager.get_realtime_quotes.return_value = (quotes, "akshare")
    # zt/dt pools: default to empty pool (route treats this as success).
    # Tuple shape matches manager.get_zt_pool: (pool, source, warning).
    fake_manager.get_zt_pool.return_value = ([], "akshare", None)
    monkeypatch.setattr(agent_module, "get_manager", lambda: fake_manager)
    return fake_manager
```

**Verify all existing tests still pass** after this change:

Run: `.venv/Scripts/python.exe -m pytest tests/test_agent_market_stats.py -v`
Expected: PASS (no regression — the new `return_value` simply makes
the helper more thorough).

**Commit this helper update as its own commit** (so the new behavior is
attributable, not lost in a feature commit):

```bash
git add tests/test_agent_market_stats.py
git commit -m "test(agent): make _patch_manager stub get_zt_pool (default empty pool)

The route's include_pools=True (default) calls manager.get_zt_pool.
Previously the helper only stubbed get_realtime_quotes, so the zt/dt
calls hit unstubbed MagicMock — the route's try/except in
_compute_limit_pools_block (agent.py:683-705) absorbed the failure,
which masked the brittleness. Stubbing the default makes every
existing + future test more robust without changing observable
behavior." -m "Co-Authored-By: Claude <noreply@anthropic.com>"
```

Then append the new tests:

```python
def test_boards_top_gainers_top_losers_in_response(client, monkeypatch):
    """Happy path: top_gainers and top_losers appear on the boards block.

    Per spec §3.1 — both lists mirror the same eligible set. With 3
    eligible rows + top_n=3, BOTH lists have length 3 (NOT a sign
    filter that would yield 3 gainers + 1 loser). This test pins that
    invariant.
    """
    boards_payload = (
        [
            {"code": "BK0001", "name": "A", "type": "industry", "subtype": "881",
             "source": "ths", "change_pct": 5.82, "volume": 100, "amount": 1.0,
             "up_count": 10, "down_count": 2, "net_inflow": 0.5},
            {"code": "BK0002", "name": "B", "type": "industry", "subtype": "881",
             "source": "ths", "change_pct": -3.0, "volume": 50, "amount": 0.5,
             "up_count": 2, "down_count": 8, "net_inflow": -0.3},
            {"code": "BK0003", "name": "C", "type": "industry", "subtype": "881",
             "source": "ths", "change_pct": 2.0, "volume": 80, "amount": 0.8,
             "up_count": 8, "down_count": 4, "net_inflow": 0.2},
        ],
        "ths",
    )
    _patch_manager(monkeypatch, quotes=[_make_quote("600519", 1.0)])
    _patch_board_cache(monkeypatch, all_boards_payload=boards_payload)

    resp = client.get("/api/v1/agent/market-stats")
    assert resp.status_code == 200
    data = resp.json()
    assert data["boards"] is not None
    assert len(data["boards"]["top_gainers"]) == 3       # mirrors all 3 eligible rows
    assert len(data["boards"]["top_losers"]) == 3
    # gainers sorted DESC: BK0001 (5.82), BK0003 (2.0), BK0002 (-3.0)
    assert [g["code"] for g in data["boards"]["top_gainers"]] == ["BK0001", "BK0003", "BK0002"]
    # losers sorted ASC: BK0002 (-3.0), BK0003 (2.0), BK0001 (5.82)
    assert [l["code"] for l in data["boards"]["top_losers"]] == ["BK0002", "BK0003", "BK0001"]
    # quote fields populated correctly
    top1 = data["boards"]["top_gainers"][0]
    assert top1["code"] == "BK0001"
    assert top1["quote"]["change_pct"] == 5.82
    assert top1["quote"]["amount"] == 1.0 * 1e8
    assert top1["quote"]["net_inflow"] == 0.5           # ×1e8 conversion only applies to `amount`


def test_boards_top_movers_absent_when_upstream_raises(client, monkeypatch):
    """Boards block fails → boards=None → top_gainers field absent in JSON."""
    _patch_manager(monkeypatch, quotes=[_make_quote("600519", 1.0)])
    fake_cache = MagicMock()
    fake_cache.get_board_list.side_effect = DataFetchError("ths down")
    monkeypatch.setattr(agent_module, "stock_board_cache", fake_cache)

    resp = client.get("/api/v1/agent/market-stats")
    assert resp.status_code == 200
    body_text = resp.text
    assert '"boards": null' in body_text or '"boards":null' in body_text
    assert "top_gainers" not in body_text               # field absent because parent is absent
    assert any(e["block"] == "boards" for e in resp.json()["errors"])


def test_boards_top_movers_empty_when_upstream_returns_empty(client, monkeypatch):
    """Boards upstream returns [] → boards block present but top_* empty."""
    _patch_manager(monkeypatch, quotes=[_make_quote("600519", 1.0)])
    _patch_board_cache(monkeypatch, all_boards_payload=([], "ths"))

    resp = client.get("/api/v1/agent/market-stats")
    assert resp.status_code == 200
    data = resp.json()
    assert data["boards"] is not None
    assert data["boards"]["top_gainers"] == []
    assert data["boards"]["top_losers"] == []
    assert data["boards"]["sample_size"] == 0           # existing aggregate still works
    assert not any(e["block"] == "boards" for e in data["errors"])  # empty != error


def test_boards_top_movers_skipped_when_include_boards_false(client, monkeypatch):
    """include_boards=False → no boards block, no top_movers, no upstream call."""
    _patch_manager(monkeypatch, quotes=[_make_quote("600519", 1.0)])
    fake_cache = MagicMock()
    fake_cache.get_board_list.return_value = ([], "ths")
    monkeypatch.setattr(agent_module, "stock_board_cache", fake_cache)

    resp = client.get("/api/v1/agent/market-stats?include_boards=false")
    assert resp.status_code == 200
    body_text = resp.text
    assert "top_gainers" not in body_text
    assert "top_losers" not in body_text
    fake_cache.get_board_list.assert_not_called()       # upstream must be skipped
```

- [ ] **Step 3.2: Run tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_agent_market_stats.py -v -k "boards_top_gainers_top_losers_in_response or boards_top_movers_absent or boards_top_movers_empty or boards_top_movers_skipped"`
Expected: FAIL — `KeyError: 'top_gainers'` (or `assert len(data["boards"]["top_gainers"]) == 2` fails with `TypeError: list indices must be integers or slices, not str`).

- [ ] **Step 3.3: Wire helpers into `build_market_stats_response`**

In `stock_data/api/routes/agent.py`, modify the boards block inside `build_market_stats_response` (lines 1535-1565). Find this block:

```python
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
```

Replace with:

```python
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
            # NEW (2026-09-09): top-3 gainers + top-3 losers derived from
            # the same upstream rows. Pure in-memory sort; no extra
            # upstream call, no cache-key change. Defaults to [] when
            # upstream returns 0 rows with non-None change_pct.
            # Spec: docs/superpowers/specs/2026-09-09-agent-market-stats-board-movers-design.md §3.1
            top_gainers, top_losers = _select_top_board_movers(boards, top_n=3)
            boards_stats.top_gainers = top_gainers
            boards_stats.top_losers = top_losers
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
```

- [ ] **Step 3.4: Run tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_agent_market_stats.py -v -k "boards_top_gainers_top_losers_in_response or boards_top_movers_absent or boards_top_movers_empty or boards_top_movers_skipped"`
Expected: PASS (4 new tests).

Also run the full test_agent_market_stats.py file to ensure no regressions:
Run: `.venv/Scripts/python.exe -m pytest tests/test_agent_market_stats.py -v`
Expected: PASS (all tests, existing + new).

- [ ] **Step 3.5: Commit**

```bash
git add stock_data/api/routes/agent.py tests/test_agent_market_stats.py
git commit -m "feat(agent): wire top movers into market-stats boards block" -m "Wires _select_top_board_movers into the boards block of build_market_stats_response. Populates BoardStats.top_gainers / .top_losers when upstream succeeds (with [] for empty upstream); boards upstream failure keeps boards=None and the new fields absent (same failure-mode contract as the rest of the block)." -m "Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Task 4: MD renderer (`_md_top_movers` + extend `_md_stats_block`)

**Files:**
- Modify: `stock_data/api/routes/agent.py:2183-2207` (extend `_md_stats_block`)
- Modify: `stock_data/api/routes/agent.py` (add `_md_top_movers` helper near `_md_feature_block` / `_render_dict_block`)
- Test: `tests/test_agent_market_stats.py` (append new tests)

**Interfaces:**
- Produces:
  - `_md_top_movers(out: list[str], title: str, entries: list[BoardMoverEntry])` — appends to `out` (list of MD lines) one heading + a single MD table OR a single `（无数据）` marker when the list is empty.
  - `_md_stats_block` extended to call `_md_top_movers` after the buckets table when the stats object is a `BoardStats` (not a `StockStats`).

The MD table projects 7 fields: code / name / change_pct / amount_yi / volume / up_count / down_count / net_inflow_yi (8 columns). Per spec §5.2.

- [ ] **Step 4.1: Write failing tests for MD rendering**

Append to `tests/test_agent_market_stats.py`:

```python
def test_market_stats_md_includes_top_movers_sections(client, monkeypatch):
    """MD output contains ### 涨幅前三 + ### 跌幅前三 with data rows.

    Pins the 8-column table contract per spec §5.2 — a regression that
    emits 7 or 9 columns would silently pass the loose substring
    checks, so we pin the exact header row + separator row.
    """
    from stock_data.api.schemas import BoardMoverEntry, MinimalQuote
    boards_payload = (
        [
            {"code": "BK0001", "name": "半导体", "type": "industry", "subtype": "881",
             "source": "ths", "change_pct": 5.82, "volume": 2345678, "amount": 12.0,
             "up_count": 23, "down_count": 5, "net_inflow": 4.5},
            {"code": "BK0002", "name": "煤炭", "type": "industry", "subtype": "881",
             "source": "ths", "change_pct": -3.15, "volume": 1000000, "amount": 5.0,
             "up_count": 2, "down_count": 18, "net_inflow": -2.1},
        ],
        "ths",
    )
    _patch_manager(monkeypatch, quotes=[_make_quote("600519", 1.0)])
    _patch_board_cache(monkeypatch, all_boards_payload=boards_payload)

    resp = client.get("/api/v1/agent/market-stats?format=md")
    assert resp.status_code == 200
    md = resp.text
    assert "### 涨幅前三" in md
    assert "### 跌幅前三" in md
    assert "BK0001" in md
    assert "半导体" in md
    assert "+5.82%" in md                                  # signed pct
    assert "BK0002" in md
    assert "煤炭" in md
    assert "-3.15%" in md
    # 8-column contract pin: exact header + separator row.
    # CLAUDE.md no-data-dropped invariant is enforced via the literal
    # header string match (not just `"| 代码 |" in md` which would also
    # match 7- or 9-column variants).
    expected_header = "| 代码 | 名称 | 涨跌幅 | 成交额(亿) | 成交量(万手) | 上涨 | 下跌 | 资金净流入(亿) |"
    expected_sep = "|---|---|---|---|---|---|---|---|"
    assert expected_header in md
    assert expected_sep in md
    # net_inflow unit clarification: pass-through 亿元 (NOT ×1e8 to 元)
    assert "4.50" in md                                     # upstream 4.5 → "4.50" via _md_num(2)
    assert "-2.10" in md


def test_market_stats_md_empty_movers_emits_explicit_marker(client, monkeypatch):
    """MD output emits ### 涨幅前三 + （无数据）, NOT a bare empty table skeleton."""
    _patch_manager(monkeypatch, quotes=[_make_quote("600519", 1.0)])
    _patch_board_cache(monkeypatch, all_boards_payload=([], "ths"))

    resp = client.get("/api/v1/agent/market-stats?format=md")
    assert resp.status_code == 200
    md = resp.text
    assert "### 涨幅前三" in md
    assert "### 跌幅前三" in md
    # Two explicit empty markers (one per heading) — NOT a bare "| 代码 |..." header
    # followed by zero data rows.
    assert md.count("（无数据）") >= 2


def test_market_stats_md_no_top_movers_when_include_boards_false(client, monkeypatch):
    """include_boards=false → no boards MD section, no top_movers headings."""
    _patch_manager(monkeypatch, quotes=[_make_quote("600519", 1.0)])
    fake_cache = MagicMock()
    fake_cache.get_board_list.return_value = ([], "ths")
    monkeypatch.setattr(agent_module, "stock_board_cache", fake_cache)

    resp = client.get("/api/v1/agent/market-stats?include_boards=false&format=md")
    assert resp.status_code == 200
    md = resp.text
    assert "### 涨幅前三" not in md
    assert "### 跌幅前三" not in md
```

- [ ] **Step 4.2: Run tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_agent_market_stats.py -v -k "market_stats_md_includes_top_movers or market_stats_md_empty_movers or market_stats_md_no_top_movers"`
Expected: FAIL — `assert "### 涨幅前三" in md` fails (current MD output has no such heading).

- [ ] **Step 4.3: Add `_md_top_movers` helper**

In `stock_data/api/routes/agent.py`, add the helper immediately after `_render_dict_block` (which ends at line 2082). The helper sits in the MD-projection section:

```python
def _md_top_movers(out: list[str], title: str, entries: list[BoardMoverEntry]) -> None:
    """Render one BoardMoverEntry list as an MD table (or empty marker).

    Same empty-table rule as ``_render_dict_block``: a bare heading +
    separator + zero rows reads as "computed, but blank", which is the
    opposite of the truth when upstream returned 0 rows. Emit an
    explicit ``（无数据）`` marker instead.

    Projects 8 columns per spec §5.2:
        代码 / 名称 / 涨跌幅 / 成交额(亿) / 成交量(万手) / 上涨 / 下跌 / 资金净流入(亿)
    The full 23-field MinimalQuote is unchanged in JSON — agents that
    need it read JSON, not MD. This is an intentional projection, not a
    data drop. The 8-column header is pinned by
    ``test_market_stats_md_includes_top_movers_sections`` to prevent
    silent regressions where a column is added/removed.

    `amount_yi` divides the 元 value by 1e8 to surface 亿元 (matches the
    units THS upstream reports natively, easier to scan in a recap).
    `net_inflow_yi` is pass-through (THS upstream 亿元; the helper does
    NOT multiply by 1e8 — see spec §3.2 unit convention note; the
    `(亿)` column header makes the unit explicit). `volume` is already
    万手 in the THS upstream `get_board_list` payload — pass-through,
    just formatted with thousands separator.
    """
    out.append(f"### {title}")
    if not entries:
        out.append("（无数据）")
        out.append("")
        return
    out.append("| 代码 | 名称 | 涨跌幅 | 成交额(亿) | 成交量(万手) | 上涨 | 下跌 | 资金净流入(亿) |")
    out.append("|---|---|---|---|---|---|---|---|")
    for entry in entries:
        q = entry.quote
        amount_yi = (q.amount / 1e8) if (q is not None and q.amount is not None) else None
        net_inflow_yi = (q.net_inflow) if (q is not None and q.net_inflow is not None) else None
        # net_inflow is already 亿元 from THS upstream; _md_num formats it.
        volume_str = (
            _md_num(q.volume, 0) if (q is not None and q.volume is not None) else "—"
        )
        up_str = (
            _md_num(q.up_count, 0) if (q is not None and q.up_count is not None) else "—"
        )
        down_str = (
            _md_num(q.down_count, 0) if (q is not None and q.down_count is not None) else "—"
        )
        out.append(
            f"| {entry.code} | {entry.name or ''} | "
            f"{_md_pct(q.change_pct if q is not None else None)} | "
            f"{_md_num(amount_yi, 2)} | {volume_str} | {up_str} | {down_str} | "
            f"{_md_num(net_inflow_yi, 2)} |"
        )
    out.append("")
```

- [ ] **Step 4.4: Extend `_md_stats_block` to call the helper for boards**

In `stock_data/api/routes/agent.py`, modify `_md_stats_block` (lines 2183-2207). Find this block:

```python
def _md_stats_block(title: str, stats, *, total_universe_label: str) -> list[str]:
    """Render one stats block (个股 or 板块) to MD table rows."""
    out: list[str] = [f"## {title}"]
    if stats is None:
        out.append("（失败 — 详见 errors）")
        return out
    out.append(
        f"样本数: **{stats.sample_size}** ({total_universe_label}); "
        f"均值 {_md_pct(stats.mean_pct)}, 中位 {_md_pct(stats.median_pct)}, "
        f"最高 {_md_pct(stats.max_pct)}, 最低 {_md_pct(stats.min_pct)}"
    )
    out.append(
        f"上涨: **{stats.up_count}** / 下跌: **{stats.down_count}** / 平盘: **{stats.flat_count}**"
    )
    out.append("")
    out.append("| 区间 | 计数 | 占比 |")
    out.append("|---|---|---|")
    if stats.sample_size:
        for b in stats.buckets:
            pct = b.count / stats.sample_size * 100
            out.append(f"| {b.label} | {b.count} | {_md_num(pct, 2)}% |")
    else:
        for b in stats.buckets:
            out.append(f"| {b.label} | 0 | — |")
    return out
```

Replace with:

```python
def _md_stats_block(title: str, stats, *, total_universe_label: str) -> list[str]:
    """Render one stats block (个股 or 板块) to MD table rows.

    When ``stats`` is a ``BoardStats`` instance, also render the
    top-3 gainers / top-3 losers after the buckets table (added
    2026-09-09; spec §5.2). ``StockStats`` has no equivalent field —
    those calls pass through unchanged.
    """
    out: list[str] = [f"## {title}"]
    if stats is None:
        out.append("（失败 — 详见 errors）")
        return out
    out.append(
        f"样本数: **{stats.sample_size}** ({total_universe_label}); "
        f"均值 {_md_pct(stats.mean_pct)}, 中位 {_md_pct(stats.median_pct)}, "
        f"最高 {_md_pct(stats.max_pct)}, 最低 {_md_pct(stats.min_pct)}"
    )
    out.append(
        f"上涨: **{stats.up_count}** / 下跌: **{stats.down_count}** / 平盘: **{stats.flat_count}**"
    )
    out.append("")
    out.append("| 区间 | 计数 | 占比 |")
    out.append("|---|---|---|")
    if stats.sample_size:
        for b in stats.buckets:
            pct = b.count / stats.sample_size * 100
            out.append(f"| {b.label} | {b.count} | {_md_num(pct, 2)}% |")
    else:
        for b in stats.buckets:
            out.append(f"| {b.label} | 0 | — |")
    # NEW (2026-09-09): boards block exposes top-3 movers (StockStats
    # doesn't have these fields — guard with hasattr so the helper stays
    # usable for both endpoints).
    if hasattr(stats, "top_gainers"):
        _md_top_movers(out, "涨幅前三", stats.top_gainers)
        _md_top_movers(out, "跌幅前三", stats.top_losers)
    return out
```

- [ ] **Step 4.5: Run tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_agent_market_stats.py -v -k "market_stats_md_includes_top_movers or market_stats_md_empty_movers or market_stats_md_no_top_movers"`
Expected: PASS (3 new tests).

- [ ] **Step 4.6: Commit**

```bash
git add stock_data/api/routes/agent.py tests/test_agent_market_stats.py
git commit -m "feat(agent): MD render top movers in market-stats" -m "Adds _md_top_movers helper (renders BoardMoverEntry list as a 7-column table or empty marker). Extends _md_stats_block to call it after the buckets table when stats has top_gainers/top_losers fields (BoardStats only; StockStats has no equivalent)." -m "Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Task 5: Final regression + lint

**Files:**
- Modify: nothing (verification + lint only)

This task runs the broader test surface to catch any unintended regressions and applies ruff. Per project memory `[[subagent-test-scope]]`, only run task-related tests during dev loop; here we run the wider agent suite because the change touches a shared schema.

- [ ] **Step 5.1: Run the full agent test suite**

Run: `.venv/Scripts/python.exe -m pytest tests/test_agent_market_stats.py tests/test_agent_market_stats_schemas.py tests/test_agent_market_recap.py tests/test_agent_market_recap_schemas.py tests/test_agent_endpoints.py tests/test_agent_batch_features.py -v`
Expected: PASS (all tests). The recap tests cover the verbatim market-stats sub-block inside the market-recap aggregation; the agent_endpoints tests cover the format-md round trip for the slim market-context which also consumes the cache key.

- [ ] **Step 5.2: Run the wider api/ persistence smoke**

Run: `.venv/Scripts/python.exe -m pytest tests/test_api_cache.py tests/test_persistence_board_topn.py tests/test_manager_get_board_stocks_kwargs.py -v`
Expected: PASS.

- [ ] **Step 5.3: Run ruff format + check**

Run: `.venv/Scripts/python.exe -m ruff format stock_data/api/routes/agent.py stock_data/api/schemas.py tests/test_agent_market_stats.py tests/test_agent_market_stats_schemas.py`
Expected: no changes (already formatted) OR a small reformat if Step 3/4 introduced trailing whitespace / line-length issues. If format changes, re-run Step 5.1.

Run: `.venv/Scripts/python.exe -m ruff check stock_data/api/routes/agent.py stock_data/api/schemas.py tests/test_agent_market_stats.py tests/test_agent_market_stats_schemas.py`
Expected: 0 errors.

- [ ] **Step 5.4: Commit (if ruff reformatted anything)**

```bash
git diff --stat                       # confirm only the formatted files changed
git add stock_data/api/routes/agent.py stock_data/api/schemas.py tests/test_agent_market_stats.py tests/test_agent_market_stats_schemas.py
git commit -m "style: ruff format agent.py + market-stats tests" -m "Co-Authored-By: Claude <noreply@anthropic.com>"
```

Only commit if `git diff --stat` shows changes. Otherwise skip.

- [ ] **Step 5.5: Verify branch + final state**

Run: `git status && git log --oneline feat/agent-market-stats-board-movers ^master`
Expected:
- `On branch feat/agent-market-stats-board-movers`
- `nothing to commit, working tree clean`
- 5 new commits on the branch (Tasks 1-5), plus the spec commit on master.

- [ ] **Step 5.6: Hand off to merge / PR**

Per project convention, implementation lands on `feat/agent-market-stats-board-movers` branch. Don't merge to master or open a PR without explicit user direction (memory `[[do-not-kill-user-server]]` / CLAUDE.md "Commit or push only when the user asks").

Report back to the user: tests passed, ruff clean, branch ready for review. Wait for user direction on merge / PR.

---

## Self-Review (post-write)

**1. Spec coverage** — checking each spec section against plan tasks:

| Spec section | Plan task |
|---|---|
| §2.1 JSON shape (top_gainers/top_losers under BoardStats) | Task 1 (schema) + Task 3 (handler wire-up) |
| §2.2 BoardMoverEntry schema | Task 1 |
| §3.1 Sort + tie-break (code ASC, None excluded) | Task 2 (`_select_top_board_movers` tests + impl) |
| §3.2 Quote fill (6 fields ×1e8 conversion) | Task 2 (`_build_minimal_quote_from_list_row_dict` tests + impl) |
| §3.3 Failure modes (None / empty / include_boards=False) | Task 3 (3 dedicated tests) |
| §3.4 Cache impact (no change) | Implicit — Task 3 explicitly does NOT touch cache code |
| §3.5 ok/requested accounting (no new increment) | Implicit — Task 3 only adds the `_select_top_board_movers` call + assignment, no `ok += 1` change |
| §4.1 Schema additions | Task 1 |
| §4.2 Cache key (no change) | Implicit — no Task touches `make_market_stats_cache_key` |
| §5.1 Handler helper signatures | Task 2 |
| §5.2 MD renderer | Task 4 |
| §5.3 CLAUDE.md (no change) | Implicit — no Task touches CLAUDE.md |
| §6.1 Schema tests | Task 1 |
| §6.2 Handler integration tests | Task 3 |
| §6.3 MD tests | Task 4 |
| §6.4 Regression coverage | Task 5 |
| §7 Migration (forward-compatible) | Implicit — default factory + Field(default_factory=list) in Task 1 |

All sections covered.

**2. Placeholder scan** — searched plan for: `TBD`, `TODO`, `implement later`, `fill in details`, `Add appropriate error handling`, `Write tests for the above`. **None found.** Every code block shows the actual code; every test block shows the actual test code; every command shows the actual command with expected output.

**3. Type consistency** — checked function/class names across tasks:
- `BoardMoverEntry` — used consistently in Task 1, 2, 4
- `_build_minimal_quote_from_list_row_dict` — used consistently in Task 2 (defined) and Task 4 (called via `_select_top_board_movers` which is itself called from Task 3)
- `_select_top_board_movers` — defined Task 2 with `rows: list[dict] | None, *, top_n: int = 3`, called Task 3 with `boards, top_n=3` where `boards` is the upstream list (None-able via `boards or []` upstream semantics). Consistent.
- `top_gainers` / `top_losers` — used consistently across Task 1 (schema), 3 (assignment), 4 (MD access via `stats.top_gainers`)
- `_md_top_movers(out, title, entries)` — defined Task 4 with that exact signature, called in Task 4 same shape. ✓

**4. Assertion tracing** (added after subagent review surfaced B1/B2):
For each test in the plan, explicitly trace the assertion against the
spec algorithm in §3.1 (no sign filter; mirror full eligible set):

| Test | Assertion | Spec trace |
|---|---|---|
| `test_select_top_board_movers_sorts_correctly` | `len(gainers)==3, len(losers)==3` | 6 eligible rows × top_n=3 → both lists 3 entries (not sign-split). ✓ |
| `test_select_top_board_movers_fewer_than_three` | `len(gainers)==2, len(losers)==2` | 2 eligible rows × top_n=3 → both lists 2 entries (the 2 rows appear in BOTH at different ranks). ✓ |
| `test_select_top_board_movers_excludes_none_change_pct` | `{g.code for g in gainers} == {"BK0001", "BK0004"}` | 2 eligible rows → both lists contain {BK0001, BK0004}. ✓ |
| `test_select_top_board_movers_tie_break_code_asc` | gainers codes == ["BK0001", "BK0003", "BK0005"] | tie on 2.0 → sort by code ASC. ✓ |
| `test_select_top_board_movers_empty_input` | `([], [])` for `[]` and `None` | pure function; no exception. ✓ |
| `test_select_top_board_movers_entry_carries_minimal_quote` | entry.quote is non-None, amount × 1e8 | pure conversion from row dict. ✓ |
| `test_boards_top_gainers_top_losers_in_response` | `len(gainers)==3, len(losers)==3`, exact code order | 3 eligible rows × top_n=3 → both lists 3 entries at expected ranks. ✓ |
| `test_boards_top_movers_absent_when_upstream_raises` | boards=None, no top_gainers key | boards failure path leaves boards None; field absent. ✓ |
| `test_boards_top_movers_empty_when_upstream_returns_empty` | `top_gainers==[], top_losers==[]` | 0 eligible rows → both lists empty. ✓ |
| `test_boards_top_movers_skipped_when_include_boards_false` | upstream not called | include_boards=False skips the whole block. ✓ |
| `test_market_stats_md_includes_top_movers_sections` | exact 8-column header + separator pinned | spec §5.2 layout; CLAUDE.md no-data-dropped invariant. ✓ |
| `test_market_stats_md_empty_movers_emits_explicit_marker` | `（无数据）` marker, NOT bare table skeleton | empty-list rule from `_render_dict_block` precedent. ✓ |
| `test_market_stats_md_no_top_movers_when_include_boards_false` | no `### 涨幅前三` heading | include_boards=False skips. ✓ |
| `test_board_stats_top_movers_default_empty_list` | `top_gainers==[]`, `top_losers==[]` | `default_factory=list` (Task 1 schema). ✓ |
| `test_board_stats_top_movers_can_be_populated` | explicit lists accepted | schema field accepts `list[BoardMoverEntry]`. ✓ |
| `test_board_mover_entry_quote_none_default` | `quote is None` | default `None` (Task 1). ✓ |
| `test_board_mover_entry_sparse_minimal_quote` | 6 fields populated, 17 None | helper fills 6, rest None (spec §3.2). ✓ |
| `test_board_mover_entry_platecode_optional` | `platecode is None` by default | Optional[str] = None (Task 1). ✓ |
| `test_build_minimal_quote_from_list_row_dict_populates_six_fields` | amount × 1e8, net_inflow pass-through | helper field mapping (Task 2 / spec §3.2). ✓ |
| `test_build_minimal_quote_handles_missing_fields` | all-None quote when row has no quote | helper handles missing keys. ✓ |

All 20 tests traced. No future B1/B2-style drift.

**Self-review result**: plan is internally consistent, spec-complete,
and every test assertion is traced to its spec source. Proceeding.