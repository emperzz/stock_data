# Board Relationships Bulk Endpoint Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `POST /api/v1/boards/relationships` — a bulk persistence-direct endpoint that returns the union of `(board_codes → stocks)` and `(stock_codes → boards)` membership rows for a single source.

**Architecture:** New persistence helper `read_memberships_by_codes` runs one SQL `WHERE source = ? AND (board_code IN (?, …) OR stock_code IN (?, …)) ORDER BY board_code, stock_code` against `stock_board_membership` (empty axes = no filter). New Pydantic models + new POST route that calls the helper and shapes a flat row list (6 fields per row). No fetcher calls, no caching, no streaming.

**Tech Stack:** FastAPI, Pydantic v2, SQLite (existing `stock_board_membership` table), pytest.

**Spec:** `docs/superpowers/specs/2026-09-18-board-relationships-bulk-design.md` (commit `f2474a7`).

## Global Constraints

These constraints apply to every task. Pulled verbatim from the spec.

- HTTP method = `POST`; path = `/api/v1/boards/relationships`; tag = `"boards"`
- `source` is REQUIRED and single-value: `Literal["ths", "zzshare", "eastmoney", "zhitu"]`
- `board_codes` and `stock_codes` are optional `list[str]`, each `max_length=100`
- Both lists empty → full snapshot for that source (no row ceiling)
- Either list non-empty → OR-filter on the two axes
- Response row shape (6 fields per row, NO `subtype` and NO per-row `source`):
  - `board_code`, `board_name`, `board_type`, `stock_code`, `stock_name`, `refreshed_at`
- Top-level response: `{source, count, rows}`
- Decorator order on route: `@router.post` → `@endpoint_meta` → `@map_errors` → `def`
- `endpoint_meta.deco` MUST return the original function (no wrapping). See `stock_data/api/endpoint_meta.py:75-80`.
- `@map_errors` MUST branch on `inspect.iscoroutinefunction` for sync vs async handlers. See `CLAUDE.md` Anti-Patterns.
- All response values must be JSON-serialisable: dates as ISO strings (the SQLite `CURRENT_TIMESTAMP` is UTC; preserve verbatim)
- Branch: Python code goes on `feat/board-relationships-bulk`; spec docs already committed to `master`
- Use `.venv/Scripts/python.exe` for all `pytest` / `python` commands (project venv). If `.venv/` is missing, fall back to system `python` and surface in commit message.
- No fetcher calls, no caching layer, no `StreamingResponse`, no pagination, no `format=md` renderer
- Per-task: TDD cycle (red → green → commit). Frequent commits. No code without a failing test first.

---

## Task 1: Persistence helper `read_memberships_by_codes`

**Files:**
- Modify: `stock_data/data_provider/persistence/board.py` (after existing `read_membership`)
- Test: `tests/test_persistence_board_relationships.py` (new file)

**Interfaces:**
- Produces:
  ```python
  def read_memberships_by_codes(
      board_codes: list[str] | None,
      stock_codes: list[str] | None,
      source: str,
  ) -> list[dict[str, Any]]:
      """Returns list of dicts with: board_code, stock_code, board_name,
      stock_name, board_type, refreshed_at. Sort: ORDER BY board_code, stock_code.
      Empty axes mean "no filter on that axis". Both empty means all rows for source.
      """
  ```

**Steps:**

- [ ] **Step 1: Create the failing test file**

Create `tests/test_persistence_board_relationships.py`:

```python
"""Unit tests for persistence.board.read_memberships_by_codes helper.

Bulk OR-query of stock_board_membership. Empty axes = no filter on that axis.
Both empty = all rows for the given source.
"""

from __future__ import annotations

import pytest

from stock_data.data_provider.persistence import board as board_mod
from stock_data.data_provider.persistence import db as db_mod


@pytest.fixture
def fresh_db(tmp_path, monkeypatch):
    """Per-test isolated SQLite + fresh schema."""
    monkeypatch.setattr(db_mod, "_db_path", None)
    board_mod._schema_initialized_paths = set()
    monkeypatch.setenv("STOCK_CACHE_DB_PATH", str(tmp_path / "test.db"))
    board_mod.init_schema()
    yield


def _seed(
    stock_code: str,
    source: str,
    board_code: str,
    board_type: str = "concept",
    board_name: str = "",
) -> None:
    board_mod.upsert_membership_bulk(
        source=source,
        stocks=[{"stock_code": stock_code, "stock_name": stock_code}],
        board_code=board_code,
        board_name=board_name or f"Board-{board_code}",
        board_type=board_type,
        subtype=None,
    )


class TestReadMembershipsByCodes:
    def test_board_codes_only_returns_matching_rows(self, fresh_db):
        """Forward direction: filter on board_code alone."""
        _seed("600519", "ths", "885595")
        _seed("000001", "ths", "885595")
        _seed("600036", "ths", "881270")  # different board, should NOT match

        rows = board_mod.read_memberships_by_codes(
            board_codes=["885595"], stock_codes=None, source="ths"
        )
        codes = sorted(r["stock_code"] for r in rows)
        assert codes == ["000001", "600519"]

    def test_stock_codes_only_returns_matching_rows(self, fresh_db):
        """Reverse direction: filter on stock_code alone."""
        _seed("600519", "ths", "885595")
        _seed("600519", "ths", "881270")  # 600519 belongs to two boards
        _seed("000001", "ths", "885595")  # 000001 also in 885595

        rows = board_mod.read_memberships_by_codes(
            board_codes=None, stock_codes=["600519"], source="ths"
        )
        boards = sorted(r["board_code"] for r in rows)
        assert boards == ["881270", "885595"]

    def test_both_codes_returns_union(self, fresh_db):
        """Forward ∪ reverse — rows for either set are returned, no duplicates."""
        _seed("600519", "ths", "885595")
        _seed("600519", "ths", "881270")
        _seed("000001", "ths", "885595")
        _seed("000002", "ths", "999999")  # unrelated row

        rows = board_mod.read_memberships_by_codes(
            board_codes=["885595"], stock_codes=["600519"], source="ths"
        )
        # Expect: 885595→600519, 885595→000001, 881270→600519 (3 rows; 999999→000002 excluded)
        keys = {(r["board_code"], r["stock_code"]) for r in rows}
        assert keys == {
            ("885595", "000001"),
            ("885595", "600519"),
            ("881270", "600519"),
        }

    def test_both_empty_returns_all_rows_for_source(self, fresh_db):
        """Both axes empty = full snapshot for the given source.

        Asserts source isolation by seeding rows under TWO different sources
        with overlapping stock codes. ``source='ths'`` must return exactly 2
        rows; ``source='zzshare'`` must return exactly 1. If the helper
        forgot to scope by `source`, both would return all 3 rows.
        """
        _seed("600519", "ths", "885595")
        _seed("000001", "ths", "885595")
        _seed("600519", "zzshare", "885540")  # different source, must not appear in ths

        ths_rows = board_mod.read_memberships_by_codes(
            board_codes=None, stock_codes=None, source="ths"
        )
        assert len(ths_rows) == 2
        assert {r["stock_code"] for r in ths_rows} == {"600519", "000001"}

        zzshare_rows = board_mod.read_memberships_by_codes(
            board_codes=None, stock_codes=None, source="zzshare"
        )
        assert len(zzshare_rows) == 1
        assert zzshare_rows[0]["board_code"] == "885540"

    def test_source_filter_isolates_rows(self, fresh_db):
        """source='zzshare' must not return rows from source='ths'."""
        _seed("600519", "ths", "885595")
        _seed("600519", "zzshare", "885540")

        rows = board_mod.read_memberships_by_codes(
            board_codes=None, stock_codes=["600519"], source="zzshare"
        )
        assert len(rows) == 1
        assert rows[0]["board_code"] == "885540"

    def test_result_shape_has_six_fields(self, fresh_db):
        """Each row dict has exactly the 6 documented keys; no subtype, no source."""
        _seed("600519", "ths", "885595", board_type="concept", board_name="煤炭概念")

        rows = board_mod.read_memberships_by_codes(
            board_codes=["885595"], stock_codes=None, source="ths"
        )
        assert len(rows) == 1
        row = rows[0]
        assert set(row.keys()) == {
            "board_code",
            "stock_code",
            "board_name",
            "stock_name",
            "board_type",
            "refreshed_at",
        }
        assert row["board_code"] == "885595"
        assert row["board_name"] == "煤炭概念"
        assert row["board_type"] == "concept"
        assert row["stock_code"] == "600519"
        assert row["stock_name"] == "600519"
        assert isinstance(row["refreshed_at"], str)
        assert len(row["refreshed_at"]) > 0

    def test_result_order_is_by_board_then_stock(self, fresh_db):
        """Stable sort: (board_code ASC, stock_code ASC) regardless of insertion order."""
        _seed("600003", "ths", "881270")
        _seed("600001", "ths", "885595")
        _seed("600002", "ths", "885595")
        _seed("600000", "ths", "881270")

        rows = board_mod.read_memberships_by_codes(
            board_codes=None, stock_codes=None, source="ths"
        )
        keys = [(r["board_code"], r["stock_code"]) for r in rows]
        assert keys == [
            ("881270", "600000"),
            ("881270", "600003"),
            ("885595", "600001"),
            ("885595", "600002"),
        ]

    def test_empty_db_returns_empty_list(self, fresh_db):
        """No rows for source → empty list, not None, no exception."""
        rows = board_mod.read_memberships_by_codes(
            board_codes=["885595"], stock_codes=None, source="ths"
        )
        assert rows == []

    def test_sql_injection_does_not_leak_other_sources(self, fresh_db):
        """Malicious ``board_code`` containing ``'`` or ``OR 1=1`` must NOT
        return rows from another source.

        The helper uses parameterised ``?`` placeholders (sqlite3 driver
        escapes them), so a malicious value is matched as a literal string
        and finds no rows. This test pins that contract end-to-end: if a
        future refactor switches to f-string interpolation, the test will
        fail (the malicious value would either raise or, worse, leak rows).
        """
        # Seed a row in a different source. If source scoping breaks,
        # the malicious value would surface this row.
        _seed("000001", "zzshare", "885540")
        # Malicious: classic SQLi probe (no row literally matches it).
        malicious = "', 'OR1=1", "x' UNION SELECT 1--"
        rows = board_mod.read_memberships_by_codes(
            board_codes=list(malicious), stock_codes=None, source="ths"
        )
        assert rows == []
        # Defence-in-depth: also assert that even querying both axes of
        # malicious codes against an unrelated source returns nothing.
        rows2 = board_mod.read_memberships_by_codes(
            board_codes=list(malicious),
            stock_codes=list(malicious),
            source="zzshare",
        )
        assert rows2 == []
```

- [ ] **Step 2: Run tests; expect ImportError / AttributeError**

Run (from repo root):
```bash
.venv/Scripts/python.exe -m pytest tests/test_persistence_board_relationships.py -v
```

Expected: collection error or `AttributeError: module 'stock_data.data_provider.persistence.board' has no attribute 'read_memberships_by_codes'`. Confirm tests run but fail for the missing symbol.

- [ ] **Step 3: Implement the helper**

Open `stock_data/data_provider/persistence/board.py`. Locate the existing `read_membership` function (around line 1111 in the post-2026-09-11 layout). Add the new function below it:

```python
def read_memberships_by_codes(
    board_codes: list[str] | None,
    stock_codes: list[str] | None,
    source: str,
) -> list[dict[str, Any]]:
    """Bulk OR-query of stock_board_membership for a single source.

    Returns rows matching ``(board_code IN board_codes) OR (stock_code IN stock_codes)``,
    filtered by ``source``. An empty (or ``None``) axis means "no filter on that axis".
    Both empty returns the full snapshot for the given source.

    Sort order: ``(board_code ASC, stock_code ASC)`` so pagination / streaming
    added later has a stable order. Each row dict carries the 6 fields
    ``board_code, stock_code, board_name, stock_name, board_type, refreshed_at``
    (no ``subtype``, no per-row ``source`` — see spec 2026-09-18 §4).

    Distinct from :func:`read_membership` (XOR, single-code, 8 columns):
    this helper supports OR semantics on lists of codes and returns the
    slim 6-column shape the bulk endpoint requires.

    Args:
        board_codes: optional list of board codes. ``None`` or ``[]`` skips
            the board_code filter.
        stock_codes: optional list of stock codes. ``None`` or ``[]`` skips
            the stock_code filter.
        source: the source slug to scope the query to. Required (the caller
            decides which source; this helper does not cross sources).

    Returns:
        List of membership row dicts (may be empty). Order: ascending by
        ``(board_code, stock_code)``.
    """
    init_schema()

    clauses: list[str] = ["source = ?"]
    params: list[Any] = [source]
    if board_codes:
        placeholders = ",".join("?" * len(board_codes))
        clauses.append(f"board_code IN ({placeholders})")
        params.extend(board_codes)
    if stock_codes:
        placeholders = ",".join("?" * len(stock_codes))
        clauses.append(f"stock_code IN ({placeholders})")
        params.extend(stock_codes)

    sql = (
        "SELECT board_code, stock_code, board_name, stock_name, "
        "       board_type, refreshed_at "
        "FROM stock_board_membership "
        f"WHERE {' AND '.join(clauses)} "
        "ORDER BY board_code, stock_code"
    )
    cursor = get_connection().execute(sql, params)
    return [dict(r) for r in cursor.fetchall()]
```

- [ ] **Step 4: Run tests; expect PASS**

```bash
.venv/Scripts/python.exe -m pytest tests/test_persistence_board_relationships.py -v
```

Expected: all 8 tests pass.

- [ ] **Step 5: Commit**

```bash
git add stock_data/data_provider/persistence/board.py tests/test_persistence_board_relationships.py
git commit -m "feat(persistence): add read_memberships_by_codes for bulk OR queries"
```

---

## Task 2: Pydantic schemas (request + response + row)

**Files:**
- Modify: `stock_data/api/schemas.py` (append at end of file)
- Test: `tests/test_board_relationships_schemas.py` (new file)

**Interfaces:**
- Produces three Pydantic models (verbatim from spec §4):
  ```python
  class BoardRelationshipRow(BaseModel):
      board_code: str
      board_name: str
      board_type: str
      stock_code: str
      stock_name: str
      refreshed_at: str

  class BoardRelationshipsRequest(BaseModel):
      source: Literal["ths", "zzshare", "eastmoney", "zhitu"]
      board_codes: list[str] = Field(default_factory=list, max_length=100)
      stock_codes: list[str] = Field(default_factory=list, max_length=100)

  class BoardRelationshipsResponse(BaseModel):
      source: str
      count: int
      rows: list[BoardRelationshipRow]
  ```

**Steps:**

- [ ] **Step 1: Create the failing test file**

Create `tests/test_board_relationships_schemas.py`:

```python
"""Unit tests for BoardRelationships* Pydantic schemas.

Pure schema tests — no DB, no fetcher. Pin field set + constraints.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from stock_data.api.schemas import (
    BoardRelationshipRow,
    BoardRelationshipsRequest,
    BoardRelationshipsResponse,
)


class TestBoardRelationshipRow:
    def test_six_required_fields(self):
        row = BoardRelationshipRow(
            board_code="885595",
            board_name="煤炭概念",
            board_type="concept",
            stock_code="600188",
            stock_name="兖矿能源",
            refreshed_at="2026-09-14 03:21:00",
        )
        assert row.board_code == "885595"
        assert row.stock_name == "兖矿能源"

    def test_missing_required_field_raises(self):
        with pytest.raises(ValidationError):
            BoardRelationshipRow(
                board_code="885595",
                # board_name omitted
                board_type="concept",
                stock_code="600188",
                stock_name="x",
                refreshed_at="2026-09-14",
            )


class TestBoardRelationshipsRequest:
    def test_minimal_payload(self):
        req = BoardRelationshipsRequest(source="ths")
        assert req.board_codes == []
        assert req.stock_codes == []

    def test_full_payload(self):
        req = BoardRelationshipsRequest(
            source="eastmoney",
            board_codes=["BK0438"],
            stock_codes=["600519", "000001"],
        )
        assert req.source == "eastmoney"
        assert req.board_codes == ["BK0438"]
        assert req.stock_codes == ["600519", "000001"]

    def test_invalid_source_rejected(self):
        with pytest.raises(ValidationError):
            BoardRelationshipsRequest(source="not-a-source")

    @pytest.mark.parametrize("size", [0, 100])
    def test_max_length_boundary_ok(self, size):
        codes = ["c"] * size
        # 0 = empty (valid), 100 = at the cap (valid)
        req = BoardRelationshipsRequest(source="ths", board_codes=codes)
        assert len(req.board_codes) == size

    def test_max_length_exceeded_rejected(self):
        codes = ["c"] * 101
        with pytest.raises(ValidationError):
            BoardRelationshipsRequest(source="ths", board_codes=codes)

    def test_max_length_exceeded_rejected_stock(self):
        codes = ["c"] * 101
        with pytest.raises(ValidationError):
            BoardRelationshipsRequest(source="ths", stock_codes=codes)


class TestBoardRelationshipsResponse:
    def test_default_serialisation(self):
        resp = BoardRelationshipsResponse(
            source="ths",
            count=0,
            rows=[],
        )
        assert resp.source == "ths"
        assert resp.count == 0
        assert resp.rows == []

    def test_row_serialised_as_dict(self):
        resp = BoardRelationshipsResponse(
            source="ths",
            count=1,
            rows=[
                BoardRelationshipRow(
                    board_code="885595",
                    board_name="煤炭概念",
                    board_type="concept",
                    stock_code="600188",
                    stock_name="兖矿能源",
                    refreshed_at="2026-09-14 03:21:00",
                )
            ],
        )
        d = resp.model_dump()
        assert d["source"] == "ths"
        assert d["count"] == 1
        assert len(d["rows"]) == 1
        # Pin the field set on the row level too — no subtype, no per-row source.
        assert set(d["rows"][0].keys()) == {
            "board_code",
            "board_name",
            "board_type",
            "stock_code",
            "stock_name",
            "refreshed_at",
        }
```

- [ ] **Step 2: Run tests; expect ImportError**

```bash
.venv/Scripts/python.exe -m pytest tests/test_board_relationships_schemas.py -v
```

Expected: `ImportError: cannot import name 'BoardRelationshipsRequest' from 'stock_data.api.schemas'`.

- [ ] **Step 3: Add the three models**

Open `stock_data/api/schemas.py`. Append at end of file:

```python
# ----------------------------------------------------------------------------
# Bulk board-stock relationships endpoint (2026-09-18 spec).
# Reads stock_board_membership directly; no fetcher calls.
# ----------------------------------------------------------------------------


class BoardRelationshipRow(BaseModel):
    """One row in /api/v1/boards/relationships response.

    Slim shape: 6 fields per row. Deliberately omits ``subtype`` and the
    per-row ``source`` (the top-level ``source`` echo is sufficient).
    """

    board_code: str = Field(description="板块 code")
    board_name: str = Field(description="板块名")
    board_type: str = Field(description="板块类型 concept/industry/index/special")
    stock_code: str = Field(description="股票 code")
    stock_name: str = Field(description="股票名")
    refreshed_at: str = Field(
        description=(
            "Membership row last-refresh timestamp from SQLite (UTC). "
            "Verbatim SQLite CURRENT_TIMESTAMP string; no timezone applied."
        )
    )


class BoardRelationshipsRequest(BaseModel):
    """POST body for /api/v1/boards/relationships.

    Both ``board_codes`` and ``stock_codes`` are optional; both empty
    returns the full snapshot for the chosen ``source``. FastAPI's
    Literal / max_length validators return 422 on violation; @map_errors
    does not catch that — clients see the FastAPI default 422 shape.
    """

    source: Literal["ths", "zzshare", "eastmoney", "zhitu"] = Field(
        ..., description="单 source (必填, Literal)"
    )
    board_codes: list[str] = Field(
        default_factory=list,
        max_length=100,
        description="板块 code 列表; 空 = 该轴不过滤; max_length=100",
    )
    stock_codes: list[str] = Field(
        default_factory=list,
        max_length=100,
        description="股票 列表; 空 = 该轴不过滤; max_length=100",
    )


class BoardRelationshipsResponse(BaseModel):
    """Response for /api/v1/boards/relationships.

    ``count`` always equals ``len(rows)`` — there is no ceiling, no
    truncation. The endpoint is a pure persistence read; callers can
    iterate ``rows`` directly or aggregate client-side.
    """

    source: str = Field(description="回显查询源")
    count: int = Field(ge=0, description="rows 行数 (= len(rows))")
    rows: list[BoardRelationshipRow] = Field(
        default_factory=list,
        description="flat row list, ORDER BY (board_code, stock_code)",
    )
```

- [ ] **Step 4: Run tests; expect PASS**

```bash
.venv/Scripts/python.exe -m pytest tests/test_board_relationships_schemas.py -v
```

Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add stock_data/api/schemas.py tests/test_board_relationships_schemas.py
git commit -m "feat(schemas): add BoardRelationship{Request,Response,Row} models"
```

---

## Task 3: Route handler `post_board_relationships`

**Files:**
- Modify: `stock_data/api/routes/boards.py` (append `post_board_relationships` near the bottom)
- Test: `tests/test_board_relationships_route.py` (new file)

**Interfaces:**
- Produces route handler signature:
  ```python
  @router.post("/boards/relationships", response_model=BoardRelationshipsResponse, tags=["boards"])
  @endpoint_meta(summary=..., markets=["csi"], capabilities=["STOCK_BOARD"])
  @map_errors
  def post_board_relationships(payload: BoardRelationshipsRequest) -> BoardRelationshipsResponse:
      rows = stock_board_cache.read_memberships_by_codes(
          board_codes=payload.board_codes or None,
          stock_codes=payload.stock_codes or None,
          source=payload.source,
      )
      return BoardRelationshipsResponse(
          source=payload.source,
          count=len(rows),
          rows=[BoardRelationshipRow(**r) for r in rows],
      )
  ```

**Steps:**

- [ ] **Step 1: Create the failing test file**

Create `tests/test_board_relationships_route.py`:

```python
"""Route-layer tests for POST /api/v1/boards/relationships.

Pure route integration: real FastAPI app + real Pydantic validation;
persistence layer is mocked so tests don't depend on DB fixtures or
backfill state. Pins the route's behaviour contract:
- response shape (top-level + per-row)
- board_codes / stock_codes passthrough semantics
- max_length / source validation (FastAPI native)
- source echoed at the top level

The route handler does not touch the DataFetcherManager singleton, so
no ``reset_manager`` autouse fixture is needed here.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest


_PERSISTENCE_PATCH = (
    "stock_data.data_provider.persistence.board.read_memberships_by_codes"
)


@pytest.fixture
def patched_persistence():
    """Patch the persistence call. Returns a context-manager helper so
    individual tests can override the return value."""
    with patch(_PERSISTENCE_PATCH) as mock_fn:
        mock_fn.return_value = []
        yield mock_fn


def _seed_rows():
    return [
        {
            "board_code": "885595",
            "board_name": "煤炭概念",
            "board_type": "concept",
            "stock_code": "600188",
            "stock_name": "兖矿能源",
            "refreshed_at": "2026-09-14 03:21:00",
        },
        {
            "board_code": "881270",
            "board_name": "煤炭开采",
            "board_type": "industry",
            "stock_code": "600188",
            "stock_name": "兖矿能源",
            "refreshed_at": "2026-09-14 03:21:00",
        },
    ]


class TestBoardRelationshipsRoute:
    def test_returns_rows_with_top_level_source(self, client, patched_persistence):
        patched_persistence.return_value = _seed_rows()
        resp = client.post(
            "/api/v1/boards/relationships",
            json={"source": "ths"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["source"] == "ths"
        assert body["count"] == 2
        assert len(body["rows"]) == 2
        # First row pinned
        first = body["rows"][0]
        assert first["board_code"] == "885595"
        assert first["stock_code"] == "600188"
        # Field-set pin: no subtype, no per-row source
        assert set(first.keys()) == {
            "board_code",
            "board_name",
            "board_type",
            "stock_code",
            "stock_name",
            "refreshed_at",
        }

    def test_passes_payload_codes_to_persistence(self, client, patched_persistence):
        patched_persistence.return_value = []
        client.post(
            "/api/v1/boards/relationships",
            json={
                "source": "eastmoney",
                "board_codes": ["BK0438"],
                "stock_codes": ["600519", "000001"],
            },
        )
        patched_persistence.assert_called_once_with(
            board_codes=["BK0438"],
            stock_codes=["600519", "000001"],
            source="eastmoney",
        )

    def test_empty_lists_pass_through_as_none(self, client, patched_persistence):
        """Route must convert [] → None before calling the helper (helper
        treats None and [] identically, but tests pin the call shape)."""
        patched_persistence.return_value = []
        client.post(
            "/api/v1/boards/relationships",
            json={"source": "ths", "board_codes": [], "stock_codes": []},
        )
        patched_persistence.assert_called_once_with(
            board_codes=None,
            stock_codes=None,
            source="ths",
        )

    def test_count_matches_len_rows(self, client, patched_persistence):
        patched_persistence.return_value = _seed_rows()
        resp = client.post(
            "/api/v1/boards/relationships", json={"source": "ths"}
        )
        body = resp.json()
        assert body["count"] == len(body["rows"])

    def test_empty_persistence_returns_count_zero(self, client, patched_persistence):
        patched_persistence.return_value = []
        resp = client.post(
            "/api/v1/boards/relationships", json={"source": "ths"}
        )
        body = resp.json()
        assert body["count"] == 0
        assert body["rows"] == []

    def test_invalid_source_returns_422(self, client):
        # FastAPI Literal validation — not our 400
        resp = client.post(
            "/api/v1/boards/relationships", json={"source": "not-a-source"}
        )
        assert resp.status_code == 422

    def test_max_length_exceeded_board_codes(self, client):
        resp = client.post(
            "/api/v1/boards/relationships",
            json={"source": "ths", "board_codes": ["c"] * 101},
        )
        assert resp.status_code == 422

    def test_max_length_exceeded_stock_codes(self, client):
        resp = client.post(
            "/api/v1/boards/relationships",
            json={"source": "ths", "stock_codes": ["c"] * 101},
        )
        assert resp.status_code == 422

    def test_missing_source_returns_422(self, client):
        # source is required
        resp = client.post(
            "/api/v1/boards/relationships",
            json={"board_codes": ["x"]},
        )
        assert resp.status_code == 422
```

- [ ] **Step 2: Run tests; expect collection error**

```bash
.venv/Scripts/python.exe -m pytest tests/test_board_relationships_route.py -v
```

Expected: 404 (route not registered) for every test, or `AssertionError: 404 != 200` on the positive tests.

- [ ] **Step 3: Add the route handler**

Open `stock_data/api/routes/boards.py`. Add the imports at the top of the file (next to the existing `from ..schemas import (...)` block around line 42):

```python
from ..schemas import (
    # ... existing ones ...
    BoardRelationshipRow,
    BoardRelationshipsRequest,
    BoardRelationshipsResponse,
)
```

Append the route at the end of the file (after the existing `get_reasons` function):

```python
@router.post(
    "/boards/relationships",
    response_model=BoardRelationshipsResponse,
    tags=["boards"],
)
@endpoint_meta(
    summary="板块-股票关系 bulk 查询 (persistence 直读; board_codes/stock_codes 任一可空; 若二者皆空返回该 source 全量)",
    markets=["csi"],
    capabilities=[],
)
@map_errors
def post_board_relationships(
    payload: BoardRelationshipsRequest,
) -> BoardRelationshipsResponse:
    """Bulk read of stock_board_membership.

    Reads directly from the SQLite persistence layer via
    ``read_memberships_by_codes`` — no fetcher calls, no caching layer.
    Both ``board_codes`` and ``stock_codes`` may be empty (full snapshot
    for the chosen source); both empty ``[]`` are normalised to ``None``
    before the helper call.

    Sort order comes from the SQL helper: ``ORDER BY board_code,
    stock_code`` (ASC, ASC) so the response is stable across calls.
    """
    rows = stock_board_cache.read_memberships_by_codes(
        board_codes=payload.board_codes or None,
        stock_codes=payload.stock_codes or None,
        source=payload.source,
    )
    return BoardRelationshipsResponse(
        source=payload.source,
        count=len(rows),
        rows=[BoardRelationshipRow(**r) for r in rows],
    )
```

- [ ] **Step 4: Run tests; expect PASS**

```bash
.venv/Scripts/python.exe -m pytest tests/test_board_relationships_route.py -v
```

Expected: all 9 tests pass.

- [ ] **Step 5: Commit**

```bash
git add stock_data/api/routes/boards.py tests/test_board_relationships_route.py
git commit -m "feat(boards): add POST /api/v1/boards/relationships bulk endpoint"
```

---

## Task 4: End-to-end smoke (real DB + server boot)

This task replaces mocked persistence with the real SQLite path. It catches integration issues the unit-level mocks in Task 3 would mask (e.g. SQLAlchemy-style column-name mismatches, type coercion in Pydantic).

**Files:**
- Test: `tests/test_board_relationships_e2e.py` (new file)

**Steps:**

- [ ] **Step 1: Write the integration test**

Create `tests/test_board_relationships_e2e.py`:

```python
"""End-to-end test for POST /api/v1/boards/relationships.

Uses the real persistence layer (per-test tmp_db fixture) and real
SQL — no mocks. Pins the round-trip: insert rows via
``upsert_membership_bulk``, hit the route, assert response rows match
the seeded data and respect the SQL sort order.
"""

from __future__ import annotations

import pytest

from stock_data.data_provider.persistence import board as board_mod


def _seed(stock_code: str, source: str, board_code: str,
          board_type: str = "concept") -> None:
    board_mod.upsert_membership_bulk(
        source=source,
        stocks=[{"stock_code": stock_code, "stock_name": f"Stock-{stock_code}"}],
        board_code=board_code,
        board_name=f"Board-{board_code}",
        board_type=board_type,
        subtype=None,
    )


class TestBoardRelationshipsE2E:
    def test_full_round_trip_with_real_sql(self, client, tmp_db):
        """Seed 4 rows → POST → assert response shape and order."""
        _seed("600519", "ths", "885595", "concept")
        _seed("000001", "ths", "885595", "concept")
        _seed("600519", "ths", "881270", "industry")
        # unrelated source — must not appear in ths response
        _seed("600519", "zzshare", "885540", "concept")

        resp = client.post(
            "/api/v1/boards/relationships",
            json={"source": "ths"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["source"] == "ths"
        assert body["count"] == 3
        keys = [(r["board_code"], r["stock_code"]) for r in body["rows"]]
        assert keys == [
            ("881270", "600519"),
            ("885595", "000001"),
            ("885595", "600519"),
        ]

    def test_board_codes_filter_e2e(self, client, tmp_db):
        _seed("600519", "ths", "885595")
        _seed("000001", "ths", "885595")
        _seed("600519", "ths", "881270")

        resp = client.post(
            "/api/v1/boards/relationships",
            json={"source": "ths", "board_codes": ["885595"]},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["count"] == 2
        assert {r["stock_code"] for r in body["rows"]} == {"000001", "600519"}

    def test_stock_codes_filter_e2e(self, client, tmp_db):
        _seed("600519", "ths", "885595")
        _seed("600519", "ths", "881270")
        _seed("000001", "ths", "885595")

        resp = client.post(
            "/api/v1/boards/relationships",
            json={"source": "ths", "stock_codes": ["600519"]},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["count"] == 2
        assert {r["board_code"] for r in body["rows"]} == {"881270", "885595"}

    def test_union_filter_e2e(self, client, tmp_db):
        """board_codes X ∪ stock_codes Y."""
        _seed("600519", "ths", "885595")  # in X
        _seed("000001", "ths", "885595")  # in X
        _seed("600519", "ths", "881270")  # 600519 stock → in Y
        _seed("000002", "ths", "999999")  # unrelated

        resp = client.post(
            "/api/v1/boards/relationships",
            json={
                "source": "ths",
                "board_codes": ["885595"],
                "stock_codes": ["600519"],
            },
        )
        assert resp.status_code == 200
        body = resp.json()
        keys = {(r["board_code"], r["stock_code"]) for r in body["rows"]}
        assert keys == {
            ("881270", "600519"),  # via stock_codes axis
            ("885595", "000001"),  # via board_codes axis
            ("885595", "600519"),  # via both axes
        }

    def test_empty_db_returns_count_zero(self, client, tmp_db):
        resp = client.post(
            "/api/v1/boards/relationships", json={"source": "ths"}
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body == {"source": "ths", "count": 0, "rows": []}
```

- [ ] **Step 2: Run e2e tests; expect PASS**

```bash
.venv/Scripts/python.exe -m pytest tests/test_board_relationships_e2e.py -v
```

Expected: all 5 tests pass. The `tmp_db` fixture (in `tests/conftest.py`) provides per-test isolation.

If any test fails:
- **count mismatch**: re-read `read_memberships_by_codes` body in Task 1 — did you wire `params.extend(...)` for both axes?
- **wrong source leaked**: did `WHERE source = ?` make it into the SQL? Did you skip the `params` append for source?

- [ ] **Step 3: Commit**

```bash
git add tests/test_board_relationships_e2e.py
git commit -m "test(boards): end-to-end test for /api/v1/boards/relationships"
```

---

## Task 5: Run the full task-related suite

Catches regressions in sibling code (e.g. endpoint_meta registry pollution).

**Steps:**

- [ ] **Step 1: Run the new test files**

```bash
.venv/Scripts/python.exe -m pytest \
    tests/test_persistence_board_relationships.py \
    tests/test_board_relationships_schemas.py \
    tests/test_board_relationships_route.py \
    tests/test_board_relationships_e2e.py \
    -v
```

Expected: all tests pass.

- [ ] **Step 2: Run the existing board + persistence test files**

```bash
.venv/Scripts/python.exe -m pytest \
    tests/test_boards.py \
    tests/test_persistence_board_memberships.py \
    tests/test_board_stale_fallback.py \
    tests/test_board_csv_seed.py \
    -v
```

Expected: all pre-existing tests still pass. If anything broke, the most likely culprit is:
- The decorator stack on `post_board_relationships` — order must be `@router.post` → `@endpoint_meta` → `@map_errors` → `def` (CLAUDE.md Anti-Patterns).
- An import side-effect from `schemas.py` — make sure the three new models are appended, not interleaved.

- [ ] **Step 3: Run explorer manifest sanity**

```bash
.venv/Scripts/python.exe -m pytest tests/test_explorer_manifest_endpoint.py -v
```

Expected: PASS. This verifies the new endpoint appears in the explorer manifest correctly (`@endpoint_meta` registration intact, no wrap-around the `func`).

- [ ] **Step 4: Final commit**

If any follow-up edits were needed:

```bash
git add <changed files>
git commit -m "fix(boards): <one-line description>"
```

---

## Task 6: Live server smoke

**Steps:**

- [ ] **Step 1: Start the server on a non-default port**

Per `do-not-kill-user-server` memory: never `taskkill` against an unknown PID on port 8888. Bind to a non-default port (18888) AND a per-run throwaway SQLite file via `mktemp -d` (works on Windows Git Bash; `/tmp/` does not exist on the project's Windows runtime per `windows-python-taskkill-gotcha` memory).

```bash
export SERVER_PORT=18888
SMOKE_DB_DIR="$(mktemp -d)"
SMOKE_DB_PATH="${SMOKE_DB_DIR}/smoke.db"
STOCK_DB_INIT=false STOCK_CACHE_DB_PATH="$SMOKE_DB_PATH" \
    .venv/Scripts/python.exe -m stock_data.server &
SERVER_PID=$!
sleep 3
```

- [ ] **Step 2: Smoke-test with curl**

```bash
curl -s -X POST http://localhost:${SERVER_PORT}/api/v1/boards/relationships \
    -H "Content-Type: application/json" \
    -d '{"source": "ths", "board_codes": ["885595"], "stock_codes": ["600519"]}' \
    | python -m json.tool | head -40
```

Expected: a 200 with the documented shape (`source`, `count`, `rows`). The `count` may be 0 if the smoke DB has no membership rows for these codes (acceptable — the contract is the shape, not the data).

- [ ] **Step 3: Negative smoke**

```bash
curl -s -o /dev/null -w "%{http_code}\n" \
    -X POST http://localhost:${SERVER_PORT}/api/v1/boards/relationships \
    -H "Content-Type: application/json" \
    -d '{"source": "ths", "board_codes": ["c","c","c","c","c","c","c","c","c","c","c","c","c","c","c","c","c","c","c","c","c","c","c","c","c","c","c","c","c","c","c","c","c","c","c","c","c","c","c","c","c","c","c","c","c","c","c","c","c","c","c","c","c","c","c","c","c","c","c","c","c","c","c","c","c","c","c","c","c","c","c","c","c","c","c","c","c","c","c","c","c","c","c","c","c","c","c","c","c","c","c","c","c","c","c","c","c","c","c","c","c","c","c","c","c","c","c"]}'
```

Expected: `422`.

- [ ] **Step 4: Tear down the server (kill the whole process group)**

A bare `kill $SERVER_PID` only signals the parent shell; uvicorn-spawned child workers may keep listening on the test port and leak across runs (per `windows-python-taskkill-gotcha` memory about orphaned servers). Kill the entire process group instead.

```bash
kill -- -$(ps -o pgid= $SERVER_PID | tr -d ' ')
rm -rf "$SMOKE_DB_DIR"
```

---

## Task 7: Branch push

**Steps:**

- [ ] **Step 1: Push the feature branch**

```bash
git push -u origin feat/board-relationships-bulk
```

- [ ] **Step 2: Stop. Hand off to the user for review / PR**

The plan's terminal action is the push — opening a PR is the user's call.