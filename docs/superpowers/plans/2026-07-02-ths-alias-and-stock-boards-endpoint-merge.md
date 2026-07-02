# ths alias + Stock-Boards Endpoint Merge Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `?source=ths` as an API alias for `zzshare` (THS-classified boards) and merge `/stocks/{code}/boards` + `/stocks/{code}/board-memberships` into a single unified endpoint with optional CSV source, opt-in cold_fill, per-entry source, always-on cold_sources reporting.

**Architecture:** Pure routing + persistence-layer refactor. Zero fetcher changes, zero DB schema changes, zero new capabilities. The alias is a one-line remap in each affected endpoint. The merge is implemented via a shared helper `get_stock_memberships()` in `persistence/board.py` that both the new unified endpoint and the deprecated wrapper call. The wrapper's response schema is preserved unchanged for backwards compatibility.

**Tech Stack:** Python 3.11, FastAPI, Pydantic, SQLite (existing). No new dependencies.

**Spec:** `docs/superpowers/specs/2026-07-02-ths-alias-and-stock-boards-endpoint-merge-design.md`

---

## File Structure

### Files to modify

| File | Responsibility |
|---|---|
| `stock_data/api/routes/boards.py` | Route handlers for `/boards*` endpoints. Adds alias remap, CSV parser, refactors `/stocks/{code}/boards`, converts `/board-memberships` to wrapper, updates `@endpoint_meta` summaries. |
| `stock_data/api/schemas.py` | Pydantic response models. Extends `StockBoardInfo` with `source` field; extends `StockBoardsResponse` with `cold_sources` field. |
| `stock_data/data_provider/persistence/board.py` | Persistence layer for board data. Adds `get_stock_memberships()` helper that supports multi-source lookup + optional cold-fill. |

### Files to create

None — all changes are modifications to existing files.

### Test files

| File | Existing/New | What it tests |
|---|---|---|
| `tests/test_boards.py` | existing | Add: alias `?source=ths` cases for `/boards`, `/boards/{code}/stocks`, `/boards/{code}/history`. |
| `tests/test_stock_boards_reverse_route.py` | existing | Update for new CSV source + cold_fill behavior; verify response schema additions. |
| `tests/test_stock_board_memberships_view.py` | existing | Verify wrapper still returns `BoardMembershipsResponse` schema unchanged. |
| `tests/test_boards_schemas.py` | existing | Add tests for new `StockBoardInfo.source` and `StockBoardsResponse.cold_sources` fields. |
| `tests/test_persistence_board_memberships.py` | NEW | Unit tests for `get_stock_memberships()` helper. |

---

## Task 1: `?source=ths` alias on the 3 single-source list endpoints

**Files:**
- Modify: `stock_data/api/routes/boards.py:98, 205, 437` (Literal types)
- Modify: `stock_data/api/routes/boards.py:115, 212, 449` (route body — add remap)
- Test: `tests/test_boards.py` (extend)

Routes covered: `/boards`, `/boards/{code}/stocks`, `/boards/{code}/history`. The 4th (`/stocks/{code}/boards`) is handled separately in Task 4 because it accepts CSV source after merge.

### Step 1: Write failing tests

In `tests/test_boards.py`, add a parametrized test class after `TestBoardAPIRoutes`:

```python
class TestThsAlias:
    """?source=ths must behave identically to ?source=zzshare on all list endpoints."""

    @pytest.mark.parametrize("endpoint,extra_params", [
        # (url path with stock_code/board_code, additional query params)
        ("/api/v1/boards?type=concept&source=ths", {}),
        ("/api/v1/boards/BK1048/stocks?source=ths", {}),
        ("/api/v1/boards/BK1048/history?source=ths", {"frequency": "d"}),
    ])
    def test_ths_alias_remaps_to_zzshare(self, client, endpoint, extra_params):
        """source=ths → routes to zzshare fetcher; DB writes use source='zzshare'."""
        from stock_data.data_provider.persistence import board as board_mod
        from stock_data.data_provider.persistence import db as db_mod
        # Reset schema tracking so each test gets a clean DB
        db_mod._db_path = None
        db_mod._conn = None
        board_mod._schema_initialized_paths = set()

        url = endpoint + "".join(f"&{k}={v}" for k, v in extra_params.items())
        with patch(_PERSISTENCE_PATCH) as mock_get:
            mock_get.return_value = ([], "zzshare")
            response = client.get(url)
            assert response.status_code == 200
            # The persistence layer must have been called with source='zzshare',
            # not source='ths'. This proves the alias remap happened upstream
            # of the persistence boundary.
            called_kwargs = mock_get.call_args.kwargs
            assert called_kwargs["source"] == "zzshare"
```

### Step 2: Run test to verify it fails

Run: `.venv/Scripts/python.exe -m pytest tests/test_boards.py::TestThsAlias -v`

Expected: FAIL — `boards.py:98` declares `Literal["eastmoney", "zhitu", "zzshare"]`, so FastAPI returns 422 for `?source=ths` before our remap can run. The test assertion `called_kwargs["source"] == "zzshare"` also fails because `_resolve_source("ths")` raises 400.

### Step 3: Update Literal types in `boards.py`

In `stock_data/api/routes/boards.py`, change three `Literal` declarations:

**Line 98** (`list_boards`):
```python
source: Literal["eastmoney", "zhitu", "zzshare", "ths"] = Query(
    ..., description="Data source (REQUIRED). 'ths' is an alias for 'zzshare' (THS-classified boards)."
),
```

**Line 205** (`get_board_stocks`):
```python
source: Literal["eastmoney", "zhitu", "zzshare", "ths"] = Query(
    ..., description="Data source (REQUIRED). 'ths' is an alias for 'zzshare'."
),
```

**Line 437** (`get_board_history`):
```python
source: Literal["eastmoney", "zhitu", "zzshare", "ths"] = Query(
    ..., description="Data source (REQUIRED). 'ths' is an alias for 'zzshare'."
),
```

### Step 4: Add remap statements in route bodies

In `stock_data/api/routes/boards.py`, **before** each call to `_resolve_source(source)`:

**Line ~115** (after the existing `sort_by` check, before `_resolve_source(source)`):
```python
# ths alias: zzshare's plates_list 上游就是同花顺数据,客户端用 ths/zzshare 等价。
if source == "ths":
    source = "zzshare"
```

**Line ~212** (top of `get_board_stocks` body, before `_resolve_source(source)`):
```python
if source == "ths":
    source = "zzshare"
```

**Line ~449** (top of `get_board_history` body, before `_resolve_source(source)`):
```python
if source == "ths":
    source = "zzshare"
```

Note: The remap must happen **before** `_resolve_source()` so the validation in `_resolve_source` sees the normalized value.

### Step 5: Run test to verify it passes

Run: `.venv/Scripts/python.exe -m pytest tests/test_boards.py::TestThsAlias -v`

Expected: PASS — 3 cases (one per endpoint).

### Step 6: Run full board test suite to verify no regression

Run: `.venv/Scripts/python.exe -m pytest tests/test_boards.py tests/test_board_source_routing.py -v`

Expected: PASS — all existing tests still pass.

### Step 7: Commit

```bash
git add stock_data/api/routes/boards.py tests/test_boards.py
git commit -m "feat(boards): ?source=ths alias for zzshare (THS-classified boards)

zzshare SDK's plates_list upstream is 同花顺 data, but the API source
name 'zzshare' obscures that fact. Accept 'ths' as a route-layer alias
that remaps to 'zzshare' before persistence, so DB source column stays
'zzshare' (no migration).

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 2: Schema extensions — per-entry `source` + response `cold_sources`

**Files:**
- Modify: `stock_data/api/schemas.py:330-355` (`StockBoardInfo`, `StockBoardsResponse`)

### Step 1: Write failing tests

Append to `tests/test_boards_schemas.py`:

```python
class TestStockBoardInfoSchema:
    """StockBoardInfo must carry per-entry source after merge."""

    def test_stock_board_info_has_source_field(self):
        from stock_data.api.schemas import StockBoardInfo
        info = StockBoardInfo(
            code="BK1048", name="互联网服务", type="concept",
            subtype="concept", source="eastmoney",
        )
        assert info.source == "eastmoney"

    def test_stock_board_info_source_required_after_merge(self):
        from stock_data.api.schemas import StockBoardInfo
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            StockBoardInfo(code="BK1048", name="x", type="concept", subtype="concept")
        # No source → ValidationError (we made it required post-merge)


class TestStockBoardsResponseSchema:
    """StockBoardsResponse must have cold_sources field after merge."""

    def test_response_has_cold_sources_default_empty(self):
        from stock_data.api.schemas import StockBoardsResponse
        r = StockBoardsResponse(stock_code="600519", source="eastmoney", data=[])
        assert r.cold_sources == []

    def test_response_cold_sources_populated(self):
        from stock_data.api.schemas import StockBoardsResponse
        r = StockBoardsResponse(
            stock_code="600519", source="merged", data=[], cold_sources=["zhitu", "zzshare"]
        )
        assert r.cold_sources == ["zhitu", "zzshare"]
```

### Step 2: Run test to verify it fails

Run: `.venv/Scripts/python.exe -m pytest tests/test_boards_schemas.py::TestStockBoardInfoSchema tests/test_boards_schemas.py::TestStockBoardsResponseSchema -v`

Expected: FAIL — `StockBoardInfo` has no `source` field (ValidationError on test 1, but actually `test_stock_board_info_has_source_field` would fail with `unexpected keyword argument 'source'`). `StockBoardsResponse` has no `cold_sources` field.

### Step 3: Extend `StockBoardInfo`

In `stock_data/api/schemas.py:330-340`:

```python
class StockBoardInfo(BaseModel):
    """A board that a stock belongs to."""

    code: str = Field(description="Board code (source-specific, e.g. 'sw_yx' for Zhitu)")
    name: str = Field(description="Board full name (e.g. 'A股-申万行业-银行')")
    type: str = Field(description="Board type: concept / industry / index / special")
    subtype: str = Field(
        default="",
        description="Source-specific subtype (e.g. '申万行业' for Zhitu, "
        "'concept' for EastMoney)",
    )
    source: str = Field(
        description="eastmoney / zhitu / zzshare — which source provided this entry. "
        "Always present after endpoint merge (was implicit before).",
    )
```

### Step 4: Extend `StockBoardsResponse`

In `stock_data/api/schemas.py:343-354`:

```python
class StockBoardsResponse(BaseModel):
    """Unified response for /stocks/{stock_code}/boards endpoint."""

    stock_code: str = Field(description="Stock code queried")
    source: str = Field(
        default="",
        description="数据来源 fetcher 名 (e.g. 'zhitu'), 'persistence' on cache hit, "
        "'merged' when multiple sources were aggregated.",
    )
    data: list[StockBoardInfo] = Field(
        default_factory=list,
        description="Boards the stock belongs to. Each entry carries its source.",
    )
    cold_sources: list[str] = Field(
        default_factory=list,
        description="Sources with no membership data for this stock. "
        "Always present (empty list = all requested sources returned data).",
    )
```

### Step 5: Run test to verify it passes

Run: `.venv/Scripts/python.exe -m pytest tests/test_boards_schemas.py::TestStockBoardInfoSchema tests/test_boards_schemas.py::TestStockBoardsResponseSchema -v`

Expected: PASS — 4 cases.

### Step 6: Run full schema test suite

Run: `.venv/Scripts/python.exe -m pytest tests/test_boards_schemas.py -v`

Expected: PASS — existing tests still pass (new fields are additions, not breaking changes).

### Step 7: Commit

```bash
git add stock_data/api/schemas.py tests/test_boards_schemas.py
git commit -m "feat(schemas): StockBoardInfo.source + StockBoardsResponse.cold_sources

Schema extension to support unified /stocks/{code}/boards endpoint:
- Per-entry source (was implicit before merge; now explicit on each row)
- Top-level cold_sources (replaces 404 + cold_source flag pattern)

Non-breaking: old callers ignoring new fields continue to work.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 3: Helper `get_stock_memberships()` in persistence layer

**Files:**
- Modify: `stock_data/data_provider/persistence/board.py` (add helper after `get_stock_boards_with_lazy_fill`, ~line 550)
- Create: `tests/test_persistence_board_memberships.py`

This is the data-access primitive that both the new unified endpoint (Task 4) and the deprecated wrapper (Task 5) will call.

### Step 1: Write the test file

Create `tests/test_persistence_board_memberships.py`:

```python
"""Unit tests for persistence.board.get_stock_memberships helper."""

from __future__ import annotations

import pytest

from stock_data.data_provider.persistence import board as board_mod
from stock_data.data_provider.persistence import db as db_mod


@pytest.fixture
def fresh_db(tmp_path, monkeypatch):
    monkeypatch.setattr(db_mod, "_db_path", None)
    monkeypatch.setattr(db_mod, "_conn", None)
    board_mod._schema_initialized_paths = set()
    monkeypatch.setenv("STOCK_CACHE_DB_PATH", str(tmp_path / "test.db"))
    board_mod.init_schema()
    yield


def _seed_membership(stock_code: str, source: str, board_code: str,
                     board_type: str = "concept", subtype: str = "concept") -> None:
    """Helper: insert one membership row."""
    board_mod.upsert_membership_bulk(
        source=source,
        stocks=[{"stock_code": stock_code, "stock_name": "x"}],
        board_code=board_code,
        board_name=f"Board-{board_code}",
        board_type=board_type,
        subtype=subtype,
    )


class TestGetStockMemberships:
    """Helper semantics: returns entries, cold_sources, origin_summary."""

    def test_single_source_with_data(self, fresh_db):
        """Single source, all data in cache → entries=[...], cold=[], origin='persistence'."""
        _seed_membership("600519", "zhitu", "sw_yx")
        entries, cold, origin = board_mod.get_stock_memberships(
            stock_code="600519", sources=["zhitu"]
        )
        assert len(entries) == 1
        assert entries[0]["source"] == "zhitu"
        assert entries[0]["code"] == "sw_yx"
        assert cold == []
        assert origin == "persistence"

    def test_single_source_cold_no_fill(self, fresh_db):
        """Single source, no data, cold_fill=False → cold=[source], origin='persistence'."""
        entries, cold, origin = board_mod.get_stock_memberships(
            stock_code="600519", sources=["zhitu"], cold_fill=False
        )
        assert entries == []
        assert cold == ["zhitu"]
        assert origin == "persistence"

    def test_multi_source_partial_cold(self, fresh_db):
        """Multi source, only zhitu has data → cold=[others], origin='mixed'."""
        _seed_membership("600519", "zhitu", "sw_yx")
        entries, cold, origin = board_mod.get_stock_memberships(
            stock_code="600519", sources=["eastmoney", "zhitu", "zzshare"]
        )
        assert {e["source"] for e in entries} == {"zhitu"}
        assert set(cold) == {"eastmoney", "zzshare"}
        assert origin == "mixed"

    def test_filter_by_type(self, fresh_db):
        """type filter applied per-entry, in-memory after fetch."""
        _seed_membership("600519", "zhitu", "sw_yx", board_type="industry")
        _seed_membership("600519", "zhitu", "chgn_700532", board_type="concept")
        entries, cold, origin = board_mod.get_stock_memberships(
            stock_code="600519", sources=["zhitu"], type="concept"
        )
        assert len(entries) == 1
        assert entries[0]["code"] == "chgn_700532"

    def test_filter_by_subtype(self, fresh_db):
        """subtype filter applied per-entry."""
        _seed_membership("600519", "zhitu", "sw_yx", subtype="申万行业")
        _seed_membership("600519", "zhitu", "chgn_700532", subtype="热门概念")
        entries, cold, _ = board_mod.get_stock_memberships(
            stock_code="600519", sources=["zhitu"], subtype="申万行业"
        )
        assert len(entries) == 1
        assert entries[0]["code"] == "sw_yx"

    def test_no_sources_returns_empty(self, fresh_db):
        """Empty sources list → empty entries, empty cold."""
        entries, cold, origin = board_mod.get_stock_memberships(
            stock_code="600519", sources=[]
        )
        assert entries == []
        assert cold == []
        assert origin == ""

    def test_stock_not_in_any_source(self, fresh_db):
        """Stock has no membership rows → all sources cold, empty entries."""
        entries, cold, origin = board_mod.get_stock_memberships(
            stock_code="600519", sources=["eastmoney", "zhitu", "zzshare"]
        )
        assert entries == []
        assert set(cold) == {"eastmoney", "zhitu", "zzshare"}
        assert origin == "persistence"  # all cold, no fetcher called
```

### Step 2: Run test to verify it fails

Run: `.venv/Scripts/python.exe -m pytest tests/test_persistence_board_memberships.py -v`

Expected: FAIL — `get_stock_memberships` is not defined.

### Step 3: Implement the helper

Add to `stock_data/data_provider/persistence/board.py` after `get_stock_boards_with_lazy_fill` (around line 550, before `get_board_name`):

```python
def get_stock_memberships(
    stock_code: str,
    sources: list[str],
    type: str | None = None,
    subtype: str | None = None,
    cold_fill: bool = False,
    manager=None,
) -> tuple[list[dict], list[str], str]:
    """Single source of truth for stock→boards reverse lookup.

    Reads stock_board_membership for each requested source, applies
    type/subtype filters, and (optionally) triggers zhitu cold-fill for
    sources with no data when cold_fill=True.

    Args:
        stock_code: 6-digit stock code (e.g. '600519').
        sources: list of normalized source names (no 'ths' alias; caller
                 must remap 'ths' → 'zzshare' before calling). May be empty.
        type: optional board type filter (concept/industry/index/special).
        subtype: optional source-specific subtype filter.
        cold_fill: if True and source='zhitu' has no data, call the zhitu
                   fetcher to populate membership (same lazy-fill as
                   get_stock_boards_with_lazy_fill). Other sources never
                   trigger cold-fill (no upstream API).
        manager: DataFetcherManager instance. Required when cold_fill=True.

    Returns:
        (entries, cold_sources, origin_summary)
        - entries: list of {code, name, type, subtype, source}, one dict per row.
        - cold_sources: subset of `sources` with no data after cold_fill attempt.
        - origin_summary:
            - "persistence" — all entries came from SQLite cache (no fetcher calls)
            - "<fetcher>"   — single source with cold-fill triggered
            - "mixed"       — multi-source case (entries span multiple sources)
            - ""            — no entries

    Caller decides how to expose origin_summary in the top-level response
    source field (single-source: pass-through; multi-source: override with 'merged').
    """
    init_schema()

    if not sources:
        return [], [], ""

    conn = get_connection()
    cursor = conn.cursor()

    # Read all rows for this stock from the requested sources in one query.
    placeholders = ",".join("?" * len(sources))
    cursor.execute(
        f"""SELECT board_code, stock_code, source, board_name, stock_name,
                   board_type, subtype
           FROM stock_board_membership
           WHERE stock_code = ? AND source IN ({placeholders})
           ORDER BY source, board_code""",
        (stock_code, *sources),
    )
    raw_rows = cursor.fetchall()

    # Group by source to compute present set
    present_sources: set[str] = set()
    entries: list[dict] = []
    for row in raw_rows:
        present_sources.add(row["source"])
        entries.append({
            "code": row["board_code"],
            "name": row["board_name"],
            "type": row["board_type"],
            "subtype": row["subtype"] or "",
            "source": row["source"],
        })

    # Cold-fill: only zhitu has upstream reverse API; only when cold_fill=True.
    cold_fill_triggered = False
    if cold_fill and manager is not None and "zhitu" in sources and "zhitu" not in present_sources:
        from .stock_list import get_stock_name as _get_stock_name

        boards, _ = manager.get_stock_boards(stock_code, source="zhitu")
        if boards:
            stock_name = _get_stock_name(stock_code) or ""
            upsert_membership_for_stock_boards(
                stock_code=stock_code,
                stock_name=stock_name,
                boards=boards,
                source="zhitu",
            )
            cold_fill_triggered = True
            # Re-query to include newly-written rows
            cursor.execute(
                f"""SELECT board_code, stock_code, source, board_name, stock_name,
                           board_type, subtype
                   FROM stock_board_membership
                   WHERE stock_code = ? AND source IN ({placeholders})
                   ORDER BY source, board_code""",
                (stock_code, *sources),
            )
            raw_rows = cursor.fetchall()
            entries = [
                {
                    "code": row["board_code"],
                    "name": row["board_name"],
                    "type": row["board_type"],
                    "subtype": row["subtype"] or "",
                    "source": row["source"],
                }
                for row in raw_rows
            ]
            present_sources = {row["source"] for row in raw_rows}

    # Apply type/subtype filters (post-query, in-memory)
    if type is not None:
        entries = [e for e in entries if e["type"] == type]
    if subtype is not None:
        entries = [e for e in entries if e["subtype"] == subtype]

    # Cold sources = requested but not present
    cold_sources = [s for s in sources if s not in present_sources]

    # Origin summary
    if not entries:
        origin_summary = ""
    elif cold_fill_triggered:
        origin_summary = "zhitu"  # cold-fill happened (zhitu is the only source that can)
    elif len(sources) > 1:
        origin_summary = "mixed"
    else:
        origin_summary = "persistence"

    return entries, cold_sources, origin_summary
```

### Step 4: Run test to verify it passes

Run: `.venv/Scripts/python.exe -m pytest tests/test_persistence_board_memberships.py -v`

Expected: PASS — 7 cases.

### Step 5: Run full board persistence suite to verify no regression

Run: `.venv/Scripts/python.exe -m pytest tests/test_board_membership_readwrite.py tests/test_board_persistence_subtype.py tests/test_persistence_board.py 2>&1 | tail -30`

Expected: PASS — existing tests still pass.

### Step 6: Commit

```bash
git add stock_data/data_provider/persistence/board.py tests/test_persistence_board_memberships.py
git commit -m "feat(persistence): get_stock_memberships() helper for unified lookup

Single source of truth for stock→boards reverse lookup. Supports:
- Multi-source queries (single SQL query with IN clause)
- Optional zhitu cold-fill (opt-in via cold_fill=True)
- Type/subtype filtering (in-memory post-query)
- Origin summary computation (persistence / <fetcher> / mixed / '')

Both the new unified /stocks/{code}/boards endpoint and the deprecated
/stocks/{code}/board-memberships wrapper will call this helper.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 4: Route refactor — unified `/stocks/{code}/boards` with CSV source + cold_fill

**Files:**
- Modify: `stock_data/api/routes/boards.py:275-354` (entire `get_stock_boards` route)
- Modify: `stock_data/api/routes/boards.py` (add `_parse_source_csv` helper near top)
- Modify: `tests/test_stock_boards_reverse_route.py` (rewrite for new behavior)

### Step 1: Write failing tests for new behavior

Replace the body of `tests/test_stock_boards_reverse_route.py` with the following. (Keep the `fresh_db` fixture unchanged.)

```python
"""Tests for unified /stocks/{code}/boards endpoint with CSV source + cold_fill."""


def test_single_source_returns_per_entry_source_field(fresh_db):
    """Per-entry source field must appear on each returned board."""
    board_mod.upsert_membership_bulk(
        source="zhitu",
        stocks=[{"stock_code": "600519", "stock_name": "贵州茅台"}],
        board_code="sw_yx_baijiu", board_name="白酒",
        board_type="industry", subtype="申万行业",
    )
    with TestClient(_app_for_test) as client:
        r = client.get("/api/v1/stocks/600519/boards?source=zhitu")
    assert r.status_code == 200
    body = r.json()
    assert body["source"] == "persistence"  # cache hit
    assert body["cold_sources"] == []
    assert len(body["data"]) == 1
    assert body["data"][0]["source"] == "zhitu"  # per-entry source
    assert body["data"][0]["code"] == "sw_yx_baijiu"


def test_csv_source_aggregates_multiple_sources(fresh_db):
    """?source=zhitu,eastmoney aggregates entries; per-entry source distinguishable."""
    board_mod.upsert_membership_bulk(
        source="zhitu",
        stocks=[{"stock_code": "600519", "stock_name": "x"}],
        board_code="sw_yx", board_name="SW", board_type="industry", subtype="申万行业",
    )
    board_mod.upsert_membership_bulk(
        source="eastmoney",
        stocks=[{"stock_code": "600519", "stock_name": "x"}],
        board_code="BK1048", board_name="EM", board_type="concept", subtype="concept",
    )
    with TestClient(_app_for_test) as client:
        r = client.get("/api/v1/stocks/600519/boards?source=zhitu,eastmoney")
    assert r.status_code == 200
    body = r.json()
    assert body["source"] == "merged"
    assert body["cold_sources"] == ["zzshare"]  # third source missing
    by_src = {e["source"] for e in body["data"]}
    assert by_src == {"zhitu", "eastmoney"}


def test_ths_alias_accepted_in_csv(fresh_db):
    """?source=ths,zhitu → ths remaps to zzshare internally."""
    with patch("stock_data.data_provider.persistence.board.get_stock_memberships") as mock:
        mock.return_value = ([], ["zzshare", "zhitu"], "")
        with TestClient(_app_for_test) as client:
            r = client.get("/api/v1/stocks/600519/boards?source=ths,zhitu")
        assert r.status_code == 200
        # Helper must be called with normalized sources (no 'ths')
        called = mock.call_args.kwargs["sources"]
        assert "ths" not in called
        assert "zzshare" in called
        assert "zhitu" in called


def test_no_source_aggregates_all(fresh_db):
    """Omitting ?source= aggregates all 3 sources."""
    with patch("stock_data.data_provider.persistence.board.get_stock_memberships") as mock:
        mock.return_value = ([{"code": "x", "name": "x", "type": "concept", "subtype": "", "source": "zhitu"}], [], "mixed")
        with TestClient(_app_for_test) as client:
            r = client.get("/api/v1/stocks/600519/boards")
        assert r.status_code == 200
        called = mock.call_args.kwargs["sources"]
        assert set(called) == {"eastmoney", "zhitu", "zzshare"}


def test_cold_fill_true_triggers_lazy_fill(fresh_db):
    """?cold_fill=true + cold zhitu data → fetcher called via lazy-fill path."""
    # Seed no zhitu data → lazy fill should trigger
    mock_manager = MagicMock()
    mock_manager.get_stock_boards.return_value = (
        [{"code": "sw_yx", "name": "x", "type": "industry", "subtype": "申万行业"}],
        "zhitu",
    )
    with TestClient(_app_for_test) as client:
        with patch.object(_app_for_test, "dependency_overrides", {}), \
             patch("stock_data.api.routes.boards.get_manager", return_value=mock_manager):
            r = client.get("/api/v1/stocks/600519/boards?source=zhitu&cold_fill=true")
    # Lazy fill must have called the manager
    assert mock_manager.get_stock_boards.called


def test_cold_fill_false_does_not_trigger_lazy_fill(fresh_db):
    """?cold_fill=false (default) → cold source appears in cold_sources, no fetcher call."""
    mock_manager = MagicMock()
    with TestClient(_app_for_test) as client:
        with patch("stock_data.api.routes.boards.get_manager", return_value=mock_manager):
            r = client.get("/api/v1/stocks/600519/boards?source=zhitu")
    assert r.status_code == 200
    body = r.json()
    assert body["cold_sources"] == ["zhitu"]
    assert body["data"] == []
    mock_manager.get_stock_boards.assert_not_called()


def test_invalid_source_in_csv_returns_400(fresh_db):
    """Unknown source in CSV → 400 with error detail."""
    with TestClient(_app_for_test) as client:
        r = client.get("/api/v1/stocks/600519/boards?source=zhitu,bogus")
    assert r.status_code == 400
    assert r.json()["detail"]["error"] == "invalid_source"


def test_legacy_source_param_still_required_for_ths_when_not_csv(fresh_db):
    """Existing test (kept for backwards compat): single ths source → alias works."""
    with patch("stock_data.data_provider.persistence.board.get_stock_memberships") as mock:
        mock.return_value = ([], ["zzshare"], "")
        with TestClient(_app_for_test) as client:
            r = client.get("/api/v1/stocks/600519/boards?source=ths")
        assert r.status_code == 200
```

### Step 2: Run test to verify it fails

Run: `.venv/Scripts/python.exe -m pytest tests/test_stock_boards_reverse_route.py -v`

Expected: FAIL — old `?source=zhitu` path goes through `get_stock_boards_with_lazy_fill` not `get_stock_memberships`; CSV parsing doesn't exist; per-entry source field doesn't exist; response schema doesn't have `cold_sources`.

### Step 3: Add `_parse_source_csv` helper in `boards.py`

Insert near the top of `stock_data/api/routes/boards.py` (after `_resolve_type`, ~line 78):

```python
def _parse_source_csv(raw: str | None) -> list[str]:
    """Parse ?source=ths,zhitu,eastmoney -> ['zzshare', 'zhitu', 'eastmoney'] (normalized).

    - None / empty → all valid sources
    - Splits on comma, strips whitespace
    - Remaps 'ths' → 'zzshare' (route-layer alias)
    - Dedupes (preserves first occurrence order)
    - Raises 400 on unknown source name
    """
    from .helpers import stock_board_cache  # local import to avoid circular at module load

    if not raw:
        return list(stock_board_cache.VALID_SOURCES)
    out: list[str] = []
    for s in raw.split(","):
        s = s.strip()
        if not s:
            continue
        if s == "ths":
            s = "zzshare"
        if s not in stock_board_cache.VALID_SOURCES:
            raise HTTPException(
                status_code=400,
                detail={
                    "error": "invalid_source",
                    "message": (
                        f"Unknown source '{s}' in CSV. "
                        f"Valid sources: {sorted(stock_board_cache.VALID_SOURCES)}"
                    ),
                },
            )
        if s not in out:
            out.append(s)
    return out
```

### Step 4: Replace `get_stock_boards` route body

Replace the entire body of `get_stock_boards` (from `def get_stock_boards(...)` through the closing `raise HTTPException(...)`) with:

```python
@map_errors
def get_stock_boards(
    stock_code: str = Path(max_length=20, description="Stock code (e.g. 000001)"),
    source: str | None = Query(
        None,
        description="Comma-separated sources (e.g. 'eastmoney,zhitu,zzshare,ths'). "
        "Omit for all sources. 'ths' aliases 'zzshare'.",
    ),
    type: Literal["concept", "industry", "index", "special"] | None = Query(
        None, description="Filter by board type"
    ),
    subtype: str | None = Query(None, description="Filter by source-specific subtype"),
    cold_fill: bool = Query(
        False, description="Opt-in zhitu lazy-fill on cold data. "
        "Default false (cold data surfaces in cold_sources instead).",
    ),
) -> StockBoardsResponse:
    """Get boards a stock belongs to.

    Unified endpoint: single source or multi-source aggregation in one call.
    Reads from stock_board_membership; opt-in zhitu cold-fill via cold_fill=true.
    """
    normalized_sources = _parse_source_csv(source)

    # Per-source subtype validation (only when type is provided)
    if type is not None and subtype is not None:
        for src in normalized_sources:
            stock_board_cache._validate_subtype(src, type, subtype)

    # Single shared helper — same code path for both single and multi source.
    entries, cold_sources, origin = stock_board_cache.get_stock_memberships(
        stock_code=stock_code,
        sources=normalized_sources,
        type=type,
        subtype=subtype,
        cold_fill=cold_fill,
        manager=get_manager(),
    )

    # Top-level source field:
    # - multi-source → "merged"
    # - single source → origin from helper (persistence / <fetcher> / "")
    top_source = "merged" if len(normalized_sources) > 1 else origin

    return StockBoardsResponse(
        stock_code=stock_code,
        source=top_source,
        data=[
            StockBoardInfo(
                code=e["code"],
                name=e["name"],
                type=e.get("type", ""),
                subtype=e.get("subtype", ""),
                source=e["source"],
            )
            for e in entries
        ],
        cold_sources=cold_sources,
    )
```

Also update the `@endpoint_meta` summary on the route:

```python
@endpoint_meta(
    summary="股票所属板块（统一端点：单源/多源聚合；cold_fill 显式 opt-in）",
    markets=["csi"],
    capabilities=["STOCK_BOARD"],
    fetcher_method="get_stock_boards",
)
```

### Step 5: Run new tests to verify they pass

Run: `.venv/Scripts/python.exe -m pytest tests/test_stock_boards_reverse_route.py -v`

Expected: PASS — all 8 cases.

### Step 6: Run full board test suite to verify no regression

Run: `.venv/Scripts/python.exe -m pytest tests/test_boards.py tests/test_board_source_routing.py tests/test_stock_boards_reverse_route.py tests/test_boards_schemas.py -v`

Expected: PASS — old tests + new tests all pass.

### Step 7: Commit

```bash
git add stock_data/api/routes/boards.py tests/test_stock_boards_reverse_route.py
git commit -m "refactor(boards): unified /stocks/{code}/boards with CSV source + cold_fill

- ?source= now optional, comma-separated (e.g. 'eastmoney,zhitu,zzshare,ths')
- ?cold_fill=true opt-in for zhitu lazy-fill (was implicit before)
- Response always carries cold_sources (was 404 + cold_source flag)
- Per-entry source field (was implicit before merge)
- Top-level source: 'merged' for multi-source, helper origin for single-source

Helper get_stock_memberships is the single source of truth for lookup.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 5: Wrapper conversion — `/stocks/{code}/board-memberships`

**Files:**
- Modify: `stock_data/api/routes/boards.py:357-417` (replace route body)
- Modify: `tests/test_stock_board_memberships_view.py` (verify schema unchanged)

### Step 1: Verify current wrapper behavior with existing tests

Run: `.venv/Scripts/python.exe -m pytest tests/test_stock_board_memberships_view.py -v`

Expected: PASS — baseline before refactor.

### Step 2: Replace the route body

In `stock_data/api/routes/boards.py`, replace the entire body of `get_stock_board_memberships` (from `@map_errors` through the `return BoardMembershipsResponse(...)`):

```python
@map_errors
def get_stock_board_memberships(
    stock_code: str = Path(max_length=20, description="Stock code (e.g. 000001)"),
    type: Literal["concept", "industry", "index", "special"] | None = Query(
        None, description="Filter by board type"
    ),
    subtype: str | None = Query(None, description="Filter by source-specific subtype"),
) -> BoardMembershipsResponse:
    """Cross-source view of all known boards a stock belongs to.

    **DEPRECATED**: This endpoint is preserved for backwards compatibility.
    New code should use ``/stocks/{code}/boards?source=...`` instead, which
    returns a unified flat-list response with per-entry source.

    Behavior preserved:
    - Reads stock_board_membership directly (no fetcher calls; never lazy-fills)
    - Groups entries by source in `memberships` dict
    - Lists sources with no data in `cold_sources`

    Schema unchanged.
    """
    if type is not None:
        _resolve_type(type)

    # All sources, no lazy-fill (legacy behavior). Same helper as the unified
    # endpoint — only the response shaping differs.
    entries, cold_sources, _ = stock_board_cache.get_stock_memberships(
        stock_code=stock_code,
        sources=list(stock_board_cache.VALID_SOURCES),
        type=type,
        subtype=subtype,
        cold_fill=False,
        manager=get_manager(),
    )

    by_source: dict[str, list[BoardMembershipEntry]] = {}
    for e in entries:
        by_source.setdefault(e["source"], []).append(
            BoardMembershipEntry(
                board_code=e["code"],
                board_name=e["name"],
                board_type=e.get("type", ""),
                subtype=e.get("subtype", ""),
            )
        )

    return BoardMembershipsResponse(
        stock_code=stock_code,
        memberships=by_source,
        cold_sources=cold_sources,
    )
```

Update the `@endpoint_meta` summary and add `deprecated=True`:

```python
@endpoint_meta(
    summary="股票所属板块（跨源视图，已弃用，请改用 /stocks/{code}/boards）",
    markets=["csi"],
    capabilities=["STOCK_BOARD"],
    # No fetcher_method: this endpoint is pure DB aggregation, never calls a fetcher.
    deprecated=True,
)
```

Note: `endpoint_meta.deprecated` is a new field; if FastAPI's existing decorator doesn't pass it through, set the OpenAPI metadata separately (the wrapper's deprecation is communicated via the summary text, which is already shown in the explorer).

### Step 3: Run wrapper tests to verify schema unchanged

Run: `.venv/Scripts/python.exe -m pytest tests/test_stock_board_memberships_view.py -v`

Expected: PASS — all existing tests still pass (schema is identical).

### Step 4: Add a test that wrapper response matches new endpoint's reshaped form

Append to `tests/test_stock_board_memberships_view.py`:

```python
def test_wrapper_response_matches_helper_reshape(fresh_db):
    """Sanity: wrapper's {memberships: {src: [...]}} is the helper's
    flat list reshaped by source. Verify a multi-source seed round-trips."""
    board_mod.upsert_membership_bulk(
        source="zhitu",
        stocks=[{"stock_code": "600519", "stock_name": "x"}],
        board_code="sw_yx", board_name="SW", board_type="industry", subtype="申万行业",
    )
    board_mod.upsert_membership_bulk(
        source="eastmoney",
        stocks=[{"stock_code": "600519", "stock_name": "x"}],
        board_code="BK1048", board_name="EM", board_type="concept", subtype="concept",
    )
    with TestClient(_app_for_test) as client:
        r = client.get("/api/v1/stocks/600519/board-memberships")
    assert r.status_code == 200
    body = r.json()
    assert set(body["memberships"].keys()) == {"zhitu", "eastmoney"}
    assert "zzshare" in body["cold_sources"]
    assert body["memberships"]["zhitu"][0]["board_code"] == "sw_yx"
    assert body["memberships"]["eastmoney"][0]["board_code"] == "BK1048"
```

### Step 5: Run all board tests

Run: `.venv/Scripts/python.exe -m pytest tests/test_boards.py tests/test_board_source_routing.py tests/test_stock_boards_reverse_route.py tests/test_stock_board_memberships_view.py tests/test_boards_schemas.py -v`

Expected: PASS — full suite green.

### Step 6: Commit

```bash
git add stock_data/api/routes/boards.py tests/test_stock_board_memberships_view.py
git commit -m "refactor(boards): /board-memberships as thin wrapper, schema unchanged

- Reuses get_stock_memberships() helper (single source of truth for lookup)
- Reshapes flat list → {memberships: {src: [...]}, cold_sources: [...]} for compat
- @endpoint_meta summary marks it deprecated; recommends /stocks/{code}/boards
- cold_fill=False preserves legacy behavior (no fetcher calls)
- Schema unchanged: existing clients keep working

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 6: Final integration smoke test + manual verification

**Files:** No code changes. Verification only.

### Step 1: Start the server and verify alias

```bash
# From project root
.venv/Scripts/python.exe -m stock_data.server &
sleep 3

# /boards with ?source=ths should work
curl -s "http://localhost:8888/api/v1/boards?type=concept&source=ths" | python -m json.tool | head -20
```

Expected: HTTP 200, JSON response with boards.

### Step 2: Verify alias persistence behavior

```bash
# Make a call with ths alias, then inspect SQLite to confirm source='zzshare'
curl -s "http://localhost:8888/api/v1/stocks/600519/boards?source=ths" > /tmp/resp.json
sqlite3 stock_data/stock_cache.db "SELECT DISTINCT source FROM stock_board_membership WHERE stock_code='600519'"
```

Expected: `zzshare` (NOT `ths`).

### Step 3: Verify unified endpoint aggregates

```bash
curl -s "http://localhost:8888/api/v1/stocks/600519/boards?source=eastmoney,zzshare,ths" | python -m json.tool
```

Expected: 200 with `"source": "merged"`, per-entry source field, `cold_sources` list.

### Step 4: Verify wrapper still works with original schema

```bash
curl -s "http://localhost:8888/api/v1/stocks/600519/board-memberships" | python -m json.tool
```

Expected: 200 with `{"stock_code": ..., "memberships": {...}, "cold_sources": [...]}` (original schema, no `data` flat list).

### Step 5: Run the full test suite (excluding live_network)

Run: `.venv/Scripts/python.exe -m pytest`

Expected: PASS — all tests green (default skips live_network per `pyproject.toml` `addopts`).

### Step 6: Kill server and commit any incidental fixes

```bash
# Find and kill the server
lsof -i :8888 | tail -1 | awk '{print $2}' | xargs -r kill -9 2>/dev/null
# On Windows: netstat -ano | grep 8888 | awk '{print $5}' | head -1
```

If anything was fixed during verification, commit it:

```bash
git status
# If clean:
echo "Smoke test passed; no further commits needed"
# If dirty:
git add <files>
git commit -m "fix(<area>): <description of manual verification fix>

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Self-Review Checklist

After completing all tasks, verify the plan against the spec:

- [ ] **Spec §3.1 (ths alias)**: Tasks 1 cover `/boards`, `/boards/{code}/stocks`, `/boards/{code}/history`; Task 4 step 3-4 cover `/stocks/{code}/boards`. ✓
- [ ] **Spec §3.2.1 (new response schema)**: Task 2 extends `StockBoardInfo.source` + `StockBoardsResponse.cold_sources`. ✓
- [ ] **Spec §3.2.3 (helper)**: Task 3 implements `get_stock_memberships()` with exact signature `(entries, cold_sources, origin_summary)`. ✓
- [ ] **Spec §3.2.4 (cold_sources computation)**: Task 3 step 3 implements `cold_sources = sources - present_sources`. ✓
- [ ] **Spec §3.3 (wrapper conversion)**: Task 5 converts the wrapper, preserves schema. ✓
- [ ] **Spec §4 (no DB schema changes)**: No migration in any task. ✓
- [ ] **Spec §5 (file changes)**: All listed files are modified in the tasks above. ✓
- [ ] **Spec §6 (testing)**: Tests added in tasks 1-5; Task 6 is manual smoke test. ✓
- [ ] **Spec §8 (backwards compat)**: Task 4 step 4 preserves single-source behavior; Task 5 preserves wrapper schema. ✓
- [ ] **Spec §9 (review checkboxes)**: All 5 decisions covered by the plan. ✓