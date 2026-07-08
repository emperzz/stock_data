# THS / Zzshare Boards 服务端统一 实施 Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 `/boards` 与 `/boards/{code}/stocks` 端点对外的 `source` 收窄到 `ths` 单一值;DB 写单一 source='ths';内部把 zzshare 改造成 platecode 补全源 + stocks 备选源。

**Architecture:** 路由层 Literal 收窄 + 持久层 4 个新 helper(`fetch_boards_with_zzshare_backfill` / `_merge_ths_zzshare_by_name` / `_resolve_ths_cid_from_platecode` / `fetch_board_stocks_with_zzshare_fallback`)+ `get_board_list` / `get_board_stocks` 签名 drop `source`。零 fetcher 实现侵入,零 DB schema 变更,零 capability flag 改动。

**Tech Stack:** Python 3.11+, FastAPI, Pydantic, SQLite, pytest, ruff

**Working directory:** Always use `.venv/Scripts/python.exe` (per CLAUDE.md). Venv `akshare`/`yfinance`/`gm`/`zzshare` packages — running system Python will hit `ModuleNotFoundError`.

**Spec:** `docs/superpowers/specs/2026-07-08-ths-zzshare-boards-unification-design.md`

---

## File Structure

**Files modified:**

| File | Responsibility |
|---|---|
| `stock_data/data_provider/persistence/board.py` | 新增 4 helper;改 `VALID_SOURCES` / `_BOARD_STOCKS_VALID_SOURCES`;改 `get_board_list` / `get_board_stocks` 签名 |
| `stock_data/api/routes/boards.py` | `source` Literal 收窄;删 dead code `_parse_source_csv`;`get_board_list` / `get_board_stocks` 调用适配;endpoint_meta summary 更新 |
| `tests/test_boards.py` | 删 `TestThsSourceAliasMatrix`;新增 `TestThsOnly` class |
| `tests/test_boards_api.py` | 改写/删除 6 个旧测试(source=zzshare 相关) |
| `tests/test_persistence_board_merge.py` | **新建**:测试 `_merge_ths_zzshare_by_name` / `_resolve_ths_cid_from_platecode` |

**Files unchanged:**
- `stock_data/data_provider/fetchers/ths_fetcher.py` — 不动
- `stock_data/data_provider/fetchers/zzshare_fetcher.py` — 不动
- `stock_data/data_provider/manager.py` — 不动
- `stock_data/data_provider/persistence/_refresh.py` / `db.py` / `__init__.py` — 不动
- `stock_data/api/routes/_router.py` / `helpers.py` / `errors.py` — 不动
- `tests/test_boards_history_route.py` / `test_stock_boards_reverse_route.py` / `test_zzshare_fetcher.py` / `test_eastmoney_fetcher_board.py` / `test_zhitu_fetcher_board.py` — 不动

---

## Task 1: 持久层 `VALID_SOURCES` 与 `_BOARD_STOCKS_VALID_SOURCES` 收窄

**Files:**
- Modify: `stock_data/data_provider/persistence/board.py:74-94`

- [ ] **Step 1: 写失败的占位测试(确认改前现状)**

在 `tests/test_boards_api.py` 末尾追加:

```python
def test_boards_valid_sources_excludes_zzshare():
    """After unification, VALID_SOURCES must not include 'zzshare'."""
    from stock_data.data_provider.persistence import board as board_mod
    assert "zzshare" not in board_mod.VALID_SOURCES
    assert "ths" in board_mod.VALID_SOURCES
    assert "eastmoney" in board_mod.VALID_SOURCES
    assert "zhitu" in board_mod.VALID_SOURCES


def test_boards_stocks_valid_sources_excludes_zzshare():
    """_BOARD_STOCKS_VALID_SOURCES must not include 'zzshare' either."""
    from stock_data.data_provider.persistence import board as board_mod
    assert "zzshare" not in board_mod._BOARD_STOCKS_VALID_SOURCES
    assert "ths" in board_mod._BOARD_STOCKS_VALID_SOURCES
```

- [ ] **Step 2: 运行测试确认失败**

Run: `.venv/Scripts/python.exe -m pytest tests/test_boards_api.py::test_boards_valid_sources_excludes_zzshare tests/test_boards_api.py::test_boards_stocks_valid_sources_excludes_zzshare -v`

Expected: FAIL — 当前 `VALID_SOURCES` 含 `zzshare`(line 74)。

- [ ] **Step 3: 改 `VALID_SOURCES`**

在 `stock_data/data_provider/persistence/board.py:74` 改:

```python
# 改前
VALID_SOURCES: tuple[str, ...] = ("eastmoney", "zhitu", "zzshare", "ths")
# 改后
VALID_SOURCES: tuple[str, ...] = ("ths", "eastmoney", "zhitu")
```

- [ ] **Step 4: 改 `_BOARD_STOCKS_VALID_SOURCES`**

在 `stock_data/data_provider/persistence/board.py:92-94` 改:

```python
# 改前
_BOARD_STOCKS_VALID_SOURCES: tuple[str, ...] = (
    "eastmoney", "zhitu", "zzshare", "ths"
)
# 改后
_BOARD_STOCKS_VALID_SOURCES: tuple[str, ...] = (
    "ths", "eastmoney", "zhitu"
)
```

- [ ] **Step 5: 运行测试确认通过**

Run: `.venv/Scripts/python.exe -m pytest tests/test_boards_api.py::test_boards_valid_sources_excludes_zzshare tests/test_boards_api.py::test_boards_stocks_valid_sources_excludes_zzshare -v`

Expected: PASS

- [ ] **Step 6: 运行持久层测试套件确认无回归**

Run: `.venv/Scripts/python.exe -m pytest tests/test_persistence_board.py tests/test_board_persistence_subtype.py -v`

Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add stock_data/data_provider/persistence/board.py tests/test_boards_api.py
git commit -m "refactor(boards): drop 'zzshare' from VALID_SOURCES + _BOARD_STOCKS_VALID_SOURCES

Public boards API surface no longer accepts source=zzshare (that role
is now internal: ZZshareFetcher stays in _slug_index for the
fetch_boards_with_zzshare_backfill helper to call directly).

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 2: 新增 helper `_resolve_ths_cid_from_platecode()`

**Files:**
- Modify: `stock_data/data_provider/persistence/board.py`(在 `get_board_stocks` 前新增)
- Test: `tests/test_persistence_board_merge.py`(新建)

- [ ] **Step 1: 写失败的测试文件**

创建 `tests/test_persistence_board_merge.py`:

```python
"""Unit tests for THS / ZZSHARE merge helpers in persistence/board.py."""

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


def _seed_board(code: str, platecode: str | None, name: str,
                board_type: str = "concept", source: str = "ths") -> None:
    """Insert a row into stock_board directly via the public upsert helper."""
    from datetime import datetime
    conn = board_mod.get_connection()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with conn:
        conn.execute(
            """INSERT OR REPLACE INTO stock_board
               (code, name, board_type, subtype, source, platecode, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (code, name, board_type, "同花顺概念" if board_type == "concept" else "同花顺行业",
             source, platecode, now),
        )


class TestResolveThsCidFromPlatecode:
    def test_concept_returns_different_cid(self, fresh_db):
        """Concept: platecode=885642 → cid=301558 (different value)."""
        _seed_board(code="301558", platecode="885642", name="跨境电商",
                    board_type="concept", source="ths")
        assert board_mod._resolve_ths_cid_from_platecode("885642") == "301558"

    def test_industry_returns_same_as_platecode(self, fresh_db):
        """Industry: platecode=881270 → code=881270 (industry has no separate cid)."""
        _seed_board(code="881270", platecode="881270", name="半导体",
                    board_type="industry", source="ths")
        assert board_mod._resolve_ths_cid_from_platecode("881270") == "881270"

    def test_unknown_returns_none(self, fresh_db):
        """Unknown platecode → None (caller falls back to zzshare-only)."""
        assert board_mod._resolve_ths_cid_from_platecode("999999") is None

    def test_only_matches_ths_source(self, fresh_db):
        """Platecode row under source='zzshare' must NOT match (we want ths only)."""
        _seed_board(code="300000", platecode="885000", name="x",
                    board_type="concept", source="zzshare")
        assert board_mod._resolve_ths_cid_from_platecode("885000") is None
```

- [ ] **Step 2: 运行测试确认失败**

Run: `.venv/Scripts/python.exe -m pytest tests/test_persistence_board_merge.py -v`

Expected: FAIL — `AttributeError: module ... has no attribute '_resolve_ths_cid_from_platecode'`

- [ ] **Step 3: 实现 helper**

在 `stock_data/data_provider/persistence/board.py` 的 `get_board_stocks`(line 584 附近)之前插入:

```python
def _resolve_ths_cid_from_platecode(platecode: str) -> str | None:
    """Resolve THS code (cid) for a platecode via the stock_board cache.

    Single SELECT against stock_board. The same query handles both
    concept boards (cid ≠ platecode: 300xxx vs 885xxx) and industry
    boards (cid == platecode: 881xxx) — for industry the row's
    ``code`` column stores 881xxx, so the lookup returns the same
    value back. No special-casing by length or prefix; the data
    layer is the single source of truth.

    Args:
        platecode: THS platecode (e.g. '885642' for concept,
            '881270' for industry).

    Returns:
        The THS code (cid for concept, == platecode for industry),
        or None if no row matches. Callers treat None as
        "no cid available — skip ThsFetcher path, rely on zzshare".
    """
    init_schema()
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT code FROM stock_board "
        "WHERE platecode = ? AND source = 'ths' LIMIT 1",
        (platecode,),
    )
    row = cursor.fetchone()
    return row["code"] if row else None
```

- [ ] **Step 4: 运行测试确认通过**

Run: `.venv/Scripts/python.exe -m pytest tests/test_persistence_board_merge.py -v`

Expected: 4 PASS

- [ ] **Step 5: Commit**

```bash
git add stock_data/data_provider/persistence/board.py tests/test_persistence_board_merge.py
git commit -m "feat(boards): _resolve_ths_cid_from_platecode helper

Translate THS platecode (885xxx/881xxx) to cid via the stock_board
cache. Concept boards: cid ≠ platecode (300xxx vs 885xxx). Industry
boards: cid == platecode (881xxx). The same SELECT handles both —
no special-casing by length or prefix; the data layer is the single
source of truth.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 3: 新增 helper `_merge_ths_zzshare_by_name()`

**Files:**
- Modify: `stock_data/data_provider/persistence/board.py`(紧跟 Task 2 之后)
- Test: `tests/test_persistence_board_merge.py`(追加)

- [ ] **Step 1: 追加失败的测试**

在 `tests/test_persistence_board_merge.py` 末尾追加:

```python
class TestMergeThsZzshareByName:
    def test_ths_wins_by_default(self):
        """Same name in both: ths row kept, platecode from ths."""
        ths = [{"code": "301558", "name": "跨境电商", "platecode": "885642",
                "type": "concept", "subtype": "同花顺概念", "source": "ths"}]
        zz = [{"code": "885642", "name": "跨境电商", "platecode": "885642",
               "type": "concept", "subtype": "同花顺概念", "source": "zzshare"}]
        out = board_mod._merge_ths_zzshare_by_name(ths, zz)
        assert len(out) == 1
        assert out[0]["code"] == "301558"  # ths's cid, not zzshare's plate_code
        assert out[0]["platecode"] == "885642"  # ths's platecode
        assert out[0]["source"] == "ths"

    def test_zzshare_backfills_missing_platecode(self):
        """THS row platecode=None, zzshare has same name → platecode backfilled."""
        ths = [{"code": "301558", "name": "跨境电商", "platecode": None,
                "type": "concept", "subtype": "同花顺概念", "source": "ths"}]
        zz = [{"code": "885642", "name": "跨境电商", "platecode": "885642",
               "type": "concept", "subtype": "同花顺概念", "source": "zzshare"}]
        out = board_mod._merge_ths_zzshare_by_name(ths, zz)
        assert len(out) == 1
        assert out[0]["code"] == "301558"
        assert out[0]["platecode"] == "885642"  # ← backfilled

    def test_zzshare_only_rows_appended(self):
        """zzshare has a board ths doesn't → appended at end."""
        ths = [{"code": "301558", "name": "跨境电商", "platecode": "885642",
                "type": "concept", "subtype": "同花顺概念", "source": "ths"}]
        zz = [{"code": "885999", "name": "独此一家", "platecode": "885999",
               "type": "concept", "subtype": "同花顺概念", "source": "zzshare"}]
        out = board_mod._merge_ths_zzshare_by_name(ths, zz)
        codes = [r["code"] for r in out]
        assert "301558" in codes
        assert "885999" in codes  # zzshare-only appended
        assert out[1]["source"] == "ths"  # tagged as ths after merge

    def test_dedup_by_code_and_name(self):
        """Same (code, name) emitted twice → one row."""
        ths = [{"code": "301558", "name": "跨境电商", "platecode": "885642",
                "type": "concept", "subtype": "同花顺概念", "source": "ths"}]
        zz = [{"code": "301558", "name": "跨境电商", "platecode": "885642",
               "type": "concept", "subtype": "同花顺概念", "source": "zzshare"}]
        out = board_mod._merge_ths_zzshare_by_name(ths, zz)
        assert len(out) == 1

    def test_empty_inputs(self):
        assert board_mod._merge_ths_zzshare_by_name([], []) == []
        assert board_mod._merge_ths_zzshare_by_name(
            [], [{"code": "885999", "name": "x", "platecode": "885999",
                  "type": "concept", "subtype": "同花顺概念", "source": "zzshare"}]
        ) == [{"code": "885999", "name": "x", "platecode": "885999",
               "type": "concept", "subtype": "同花顺概念", "source": "ths"}]
        assert board_mod._merge_ths_zzshare_by_name(
            [{"code": "301558", "name": "x", "platecode": "885642",
              "type": "concept", "subtype": "同花顺概念", "source": "ths"}], []
        ) == [{"code": "301558", "name": "x", "platecode": "885642",
               "type": "concept", "subtype": "同花顺概念", "source": "ths"}]
```

- [ ] **Step 2: 运行测试确认失败**

Run: `.venv/Scripts/python.exe -m pytest tests/test_persistence_board_merge.py::TestMergeThsZzshareByName -v`

Expected: FAIL — `AttributeError: ... has no attribute '_merge_ths_zzshare_by_name'`

- [ ] **Step 3: 实现 helper**

在 `stock_data/data_provider/persistence/board.py` 紧跟 `_resolve_ths_cid_from_platecode` 之后插入:

```python
def _merge_ths_zzshare_by_name(
    ths_rows: list[dict],
    zzshare_rows: list[dict],
) -> list[dict]:
    """Merge THS(primary) + ZZSHARE(platecode backfill) by board name.

    Rules (verified 2026-07-08):
    - Index zzshare rows by name → platecode (in-memory dict).
    - For each ths row:
        * If ths_row['platecode'] is None and zzshare has same name
          → copy platecode from zzshare into ths row (in-place dict update).
        * Otherwise keep ths row as-is (it already has platecode, or
          zzshare doesn't have a matching name — the row is THS-only).
    - For each zzshare row not matched by any ths row (by name) →
      append as-is. The row carries its own plate_code as 'code'
      (no cid available; clients see this as a platecode-only row).
    - Final dedup by (code, name) within the merged list to guard
      against upstream double-emit (rare; seen once in THS gnSection
      duplicates per 2026-07-08 notes).
    - All output rows are tagged with source='ths' regardless of origin
      (the public surface unifies them; DB writes follow).

    Empty input edge cases:
    - ths_rows empty + zzshare_rows empty → []
    - ths_rows empty + zzshare_rows non-empty → all zzshare rows appended
    - ths_rows non-empty + zzshare_rows empty → ths rows returned as-is

    Note on dedup: ThsFetcher's own internal `_merge_concept_sources`
    (ths_fetcher.py:1300) dedups by `cid` (concept's `code` field). The
    (code, name) dedup here is a SECOND-LAYER safety net in case the
    ThsFetcher's internal merge missed a duplicate after zzshare rows
    were appended. Both layers are independent; this one is
    implementation-detail of the new helper, not a replacement of
    ThsFetcher's existing dedup logic.
    """
    by_name: dict[str, str] = {}
    for r in zzshare_rows:
        name = r.get("name", "")
        if name and r.get("platecode"):
            by_name[name] = r["platecode"]

    out: list[dict] = []
    seen: set[tuple[str, str]] = set()
    for r in ths_rows:
        # Backfill platecode from zzshare when THS row lacks one
        if not r.get("platecode") and r.get("name") in by_name:
            r["platecode"] = by_name[r["name"]]
        key = (r.get("code", ""), r.get("name", ""))
        if key in seen:
            continue
        seen.add(key)
        r["source"] = "ths"  # tag as ths regardless of origin
        out.append(r)
    for r in zzshare_rows:
        key = (r.get("code", ""), r.get("name", ""))
        if key in seen:
            continue
        seen.add(key)
        r["source"] = "ths"
        out.append(r)
    return out
```

- [ ] **Step 4: 运行测试确认通过**

Run: `.venv/Scripts/python.exe -m pytest tests/test_persistence_board_merge.py -v`

Expected: 9 PASS(Task 2 的 4 + Task 3 的 5)

- [ ] **Step 5: Commit**

```bash
git add stock_data/data_provider/persistence/board.py tests/test_persistence_board_merge.py
git commit -m "feat(boards): _merge_ths_zzshare_by_name helper

Merge two board lists with THS as primary (carries cid + real-time
fields) and ZZSHARE as platecode backfill source. Joins on board
name (Chinese). Backfills missing platecode for THS sidebar-only
rows. Appends ZZSHARE-only rows. Dedups by (code, name) as a
second-layer safety net.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 4: 新增 helper `fetch_boards_with_zzshare_backfill()`

**Files:**
- Modify: `stock_data/data_provider/persistence/board.py`(紧跟 Task 3 之后)

- [ ] **Step 1: 写失败的测试**

在 `tests/test_persistence_board_merge.py` 末尾追加:

```python
class TestFetchBoardsWithZzshareBackfill:
    def test_returns_ths_rows_with_zzshare_backfill(self, monkeypatch):
        """THS primary + ZZSHARE backfill; merged, write goes to cache."""
        from unittest.mock import MagicMock
        ths_rows = [
            {"code": "301558", "name": "跨境电商", "platecode": "885642",
             "type": "concept", "subtype": "同花顺概念", "source": "ths"},
            {"code": "301999", "name": "无名板块", "platecode": None,  # sidebar-only
             "type": "concept", "subtype": "同花顺概念", "source": "ths"},
        ]
        zz_rows = [
            {"code": "885642", "name": "跨境电商", "platecode": "885642",
             "type": "concept", "subtype": "同花顺概念", "source": "zzshare"},
            {"code": "885777", "name": "无名板块", "platecode": "885777",  # backfill
             "type": "concept", "subtype": "同花顺概念", "source": "zzshare"},
            {"code": "885888", "name": "独此一家", "platecode": "885888",  # zzshare-only
             "type": "concept", "subtype": "同花顺概念", "source": "zzshare"},
        ]
        mgr = MagicMock()
        mgr.get_all_boards.side_effect = [ths_rows, zz_rows]

        out = board_mod.fetch_boards_with_zzshare_backfill(
            board_type="concept", refresh=True, include_quote=False,
            subtype=None, manager=mgr,
        )

        # 1. THS called first
        assert mgr.get_all_boards.call_args_list[0].kwargs["source"] == "ths"
        # 2. ZZSHARE called second
        assert mgr.get_all_boards.call_args_list[1].kwargs["source"] == "zzshare"
        # 3. "无名板块" platecode backfilled from None → "885777"
        by_code = {r["code"]: r for r in out}
        assert by_code["301999"]["platecode"] == "885777"
        # 4. zzshare-only "独此一家" appended
        assert "885888" in by_code
        # 5. All rows tagged source='ths'
        assert all(r["source"] == "ths" for r in out)

    def test_zzshare_failure_does_not_break(self, monkeypatch):
        """ZZSHARE upstream fails → still return THS rows + WARNING log."""
        from unittest.mock import MagicMock
        ths_rows = [{"code": "301558", "name": "x", "platecode": "885642",
                     "type": "concept", "subtype": "同花顺概念", "source": "ths"}]
        mgr = MagicMock()
        # First call (ths) returns data; second call (zzshare) raises
        mgr.get_all_boards.side_effect = [ths_rows, Exception("upstream 503")]

        out = board_mod.fetch_boards_with_zzshare_backfill(
            board_type="concept", refresh=True, include_quote=False,
            subtype=None, manager=mgr,
        )
        assert len(out) == 1
        assert out[0]["code"] == "301558"
```

- [ ] **Step 2: 运行测试确认失败**

Run: `.venv/Scripts/python.exe -m pytest tests/test_persistence_board_merge.py::TestFetchBoardsWithZzshareBackfill -v`

Expected: FAIL — `AttributeError: ... has no attribute 'fetch_boards_with_zzshare_backfill'`

- [ ] **Step 3: 实现 helper**

在 `stock_data/data_provider/persistence/board.py` 紧跟 `_merge_ths_zzshare_by_name` 之后插入:

```python
def fetch_boards_with_zzshare_backfill(
    board_type: str | None,
    refresh: bool,
    include_quote: bool,
    subtype: str | None,
    manager,
) -> list[dict]:
    """Return unified board list with ths as primary, zzshare as platecode backfill.

    Behavior:
    - Always writes source='ths' to the cache (single source).
    - Always calls both ThsFetcher and ZzshareFetcher; merge by name.
    - When board_type is None, iterates every type VALID_SUBTYPES_BY_SOURCE['ths']
      supports (currently concept + industry; index/special are NOT exposed by
      ths — they fall through to persistence for eastmoney/zhitu callers).
    - When subtype is given, applies after merge (post-filter in memory).
    - When include_quote=True, the include_quote flag is forwarded to both
      ThsFetcher and ZzshareFetcher; zzshare's quote fields are sparse
      (only change_pct/amount/total_mv) so post-merge rows may have None
      for fields THS doesn't supply either.

    Returns:
        list of {code, name, type, subtype, source, platecode, ...quote}
        where source='ths' on every row (zzshare rows are tagged with the
        same label after merge; the distinction is internal).

    Raises:
        DataFetchError: ThsFetcher's call failed. ZzshareFetcher failures
        are logged at WARNING and treated as empty list (best-effort
        backfill; primary path is THS).
    """
    types_to_fetch: list[str]
    if board_type is None:
        # Iterate every type ths supports (concept + industry currently).
        # Falls back to "concept" if the metadata table is somehow empty.
        ths_table = VALID_SUBTYPES_BY_SOURCE.get("ths", {})
        types_to_fetch = list(ths_table.keys()) or ["concept", "industry"]
    elif board_type in ("concept", "industry"):
        types_to_fetch = [board_type]
    else:
        # index / special are not exposed by ths; return empty
        return []

    out: list[dict] = []
    for bt in types_to_fetch:
        ths_rows: list[dict] = []
        try:
            ths_rows, _ = manager.get_all_boards(
                source="ths", board_type=bt, subtype=None, include_quote=include_quote,
            )
        except DataFetchError as e:
            logger.warning(
                f"[BoardCache] fetch_boards_with_zzshare_backfill: "
                f"ths({bt}) failed: {e}"
            )
            # ThsFetcher failure is fatal for this bt — skip it.
            continue

        zz_rows: list[dict] = []
        try:
            zz_rows, _ = manager.get_all_boards(
                source="zzshare", board_type=bt, subtype=None, include_quote=include_quote,
            )
        except Exception as e:
            logger.warning(
                f"[BoardCache] fetch_boards_with_zzshare_backfill: "
                f"zzshare({bt}) failed (best-effort): {e}"
            )
            zz_rows = []

        merged = _merge_ths_zzshare_by_name(ths_rows, zz_rows)
        # Subtype filter is applied per-type post-merge (in-memory).
        if subtype is not None:
            merged = [r for r in merged if r.get("subtype") == subtype]
        out.extend(merged)
    return out
```

- [ ] **Step 4: 运行测试确认通过**

Run: `.venv/Scripts/python.exe -m pytest tests/test_persistence_board_merge.py -v`

Expected: 11 PASS

- [ ] **Step 5: Commit**

```bash
git add stock_data/data_provider/persistence/board.py tests/test_persistence_board_merge.py
git commit -m "feat(boards): fetch_boards_with_zzshare_backfill helper

Orchestrate the merge: call ths first (primary), then zzshare
(best-effort backfill), merge by name. Per-type iteration when
board_type is None. Subtype filter post-merge.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 5: 改写 `get_board_list()` — 删 `source` 形参

**Files:**
- Modify: `stock_data/data_provider/persistence/board.py:378-477`

- [ ] **Step 1: 写失败的占位测试**

在 `tests/test_boards_api.py` 末尾追加:

```python
def test_get_board_list_signature_no_source_arg():
    """get_board_list must drop 'source' param after unification."""
    import inspect
    sig = inspect.signature(board_mod.get_board_list)
    assert "source" not in sig.parameters, (
        f"get_board_list still has 'source' param: {list(sig.parameters)}"
    )
```

- [ ] **Step 2: 运行测试确认失败**

Run: `.venv/Scripts/python.exe -m pytest tests/test_boards_api.py::test_get_board_list_signature_no_source_arg -v`

Expected: FAIL — current `get_board_list` has `source` param

- [ ] **Step 3: 改 `get_board_list` 签名 + body**

在 `stock_data/data_provider/persistence/board.py:378-477`,整段 `get_board_list` 替换为:

```python
def get_board_list(
    board_type: str | None,
    refresh: bool = False,
    include_quote: bool = False,
    subtype: str | None = None,
    manager=None,
) -> tuple[list, str]:
    """Get board list with automatic refresh.

    - No local cache -> fetch from upstream (THS primary + ZZSHARE backfill)
      and cache as source='ths'.
    - First call of the day -> force refresh.
    - refresh=True -> force refresh.
    - include_quote=True -> always fetch fresh data from upstream.
    - Otherwise -> return cached data.

    The ``source`` parameter has been removed (2026-07-08): all writes go
    to ``source='ths'``. The response's ``data_source`` field reflects the
    primary fetcher served (always 'ths' now; older callers expecting
    'zzshare' should migrate).

    Args:
        board_type: one of "concept" / "industry" / "index" / "special", or
            ``None`` to query every type the ths fetcher exposes
            (currently concept + industry).
        refresh: If True, force refresh from upstream.
        include_quote: If True, include realtime price/change/market data and skip cache.
        subtype: optional source-specific subtype filter.
        manager: DataFetcherManager instance. Required when fetching from upstream.

    Returns:
        Tuple of (boards, origin) where origin is:
          - "persistence" when data was read from the SQLite cache
          - "ths" when data was freshly fetched (always, post-unification)
        List of board dicts: [{"code", "name", "type", "subtype", "source", "platecode", ...quote}, ...]
    """
    init_schema()

    if board_type is None:
        return _get_all_board_types(
            refresh=refresh,
            include_quote=include_quote,
            subtype=subtype,
            manager=manager,
        )

    needs_refresh = (
        refresh or include_quote or _refresh_tracker.is_first_call(f"{board_type}:ths")
    )

    if not needs_refresh:
        cached = _read_boards_from_db(board_type, "ths", subtype)
        if cached:
            return cached, "persistence"

    if manager is None:
        raise ValueError("manager is required when refresh=True or cache miss")

    boards = fetch_boards_with_zzshare_backfill(
        board_type=board_type, refresh=refresh,
        include_quote=include_quote, subtype=None, manager=manager,
    )

    if boards:
        update_cached_boards(board_type, "ths", boards)
        logger.info(f"[BoardCache] Refreshed {len(boards)} boards for {board_type}/ths")

    if subtype is not None:
        boards = [b for b in boards if b.get("subtype") == subtype]

    return boards, "ths"
```

- [ ] **Step 4: 改 `_get_all_board_types` 签名 + body**

在 `stock_data/data_provider/persistence/board.py:480-581`,把 `_get_all_board_types` 替换为:

```python
def _get_all_board_types(
    refresh: bool,
    include_quote: bool,
    subtype: str | None,
    manager,
) -> tuple[list[dict], str]:
    """All-types variant of :func:`get_board_list` (post-unification).

    Iterates over every board_type the ths fetcher exposes (derived
    from ``VALID_SUBTYPES_BY_SOURCE['ths']``; currently concept + industry).
    EastMoney/Zhitu callers fall through to the per-source path; this
    helper is THS-only because the unification collapsed the boards
    surface to source='ths'.

    Returns:
        ``(combined_boards, origin)`` where ``origin`` is:
          - ``"persistence"`` when every per-type call was a cache hit
          - ``"ths"`` when every per-type call hit the network
          - ``"mixed"`` otherwise (some types fresh, some cached)
    """
    init_schema()

    if subtype is not None:
        raise ValueError(
            "subtype filter requires a specific board_type; "
            "cross-type subtype filtering is not supported."
        )

    if manager is None:
        raise ValueError(
            "manager is required when querying all board types "
            "(cache may be partially cold and an upstream call may be needed)"
        )

    supported_types = list(VALID_SUBTYPES_BY_SOURCE.get("ths", {}).keys())
    if not supported_types:
        return [], "persistence"

    combined: list[dict] = []
    seen_codes: set[str] = set()
    origins: set[str] = set()
    for bt in supported_types:
        boards, origin = get_board_list(
            board_type=bt,
            refresh=refresh,
            include_quote=include_quote,
            subtype=None,
            manager=manager,
        )
        origins.add(origin)
        if not boards and origin != "persistence":
            logger.warning(
                f"[BoardCache] all-types query for board_type='{bt}' "
                f"returned 0 rows from upstream ({origin}); "
                f"partial result may be incomplete."
            )
        for b in boards:
            code = b.get("code")
            if not code or code in seen_codes:
                if code in seen_codes:
                    logger.debug(
                        f"[BoardCache] dropping duplicate code '{code}' "
                        f"(kept first occurrence)"
                    )
                continue
            seen_codes.add(code)
            combined.append(b)

    if origins == {"persistence"}:
        summary = "persistence"
    elif "persistence" in origins:
        summary = "mixed"
    else:
        summary = next(iter(origins))  # "ths"

    return combined, summary
```

- [ ] **Step 5: 运行测试确认通过**

Run: `.venv/Scripts/python.exe -m pytest tests/test_boards_api.py::test_get_board_list_signature_no_source_arg -v`

Expected: PASS

- [ ] **Step 6: 运行持久层套件确认无回归**

Run: `.venv/Scripts/python.exe -m pytest tests/test_persistence_board.py tests/test_board_persistence_subtype.py tests/test_board_membership_readwrite.py tests/test_persistence_board_merge.py -v`

Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add stock_data/data_provider/persistence/board.py tests/test_boards_api.py
git commit -m "refactor(boards): drop source arg from get_board_list

After unification, boards list is THS-only at the persistence layer.
ZZSHAREFetcher still exists but is invoked internally by
fetch_boards_with_zzshare_backfill for platecode backfill. Cache
writes go to source='ths'.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 6: 新增 helper `fetch_board_stocks_with_zzshare_fallback()`

**Files:**
- Modify: `stock_data/data_provider/persistence/board.py`(紧跟 Task 4 之后)

- [ ] **Step 1: 写失败的测试**

在 `tests/test_persistence_board_merge.py` 末尾追加:

```python
class TestFetchBoardStocksWithZzshareFallback:
    def _mgr(self, ths_return, zz_return, ths_raise=False, zz_raise=False):
        from unittest.mock import MagicMock
        mgr = MagicMock()
        def ths_call(*a, **kw):
            if ths_raise:
                raise Exception("ths 503")
            return ths_return
        def zz_call(*a, **kw):
            if zz_raise:
                raise Exception("zz 503")
            return zz_return
        # The helper calls ths first when include_quote=True, zz first when False.
        # We just record which was called first via call_args_list after the test runs.
        mgr.get_board_stocks.side_effect = lambda *a, **kw: (
            ths_call(*a, **kw) if kw.get("source") == "ths" else zz_call(*a, **kw)
        )
        return mgr

    def test_include_quote_true_prefers_ths(self):
        """include_quote=True: ths first; cid translation is internal."""
        ths_return = ([{"stock_code": "300740", "stock_name": "x"}], "ths")
        zz_return = ([{"stock_code": "300740", "stock_name": "x"}], "zzshare")
        mgr = self._mgr(ths_return, zz_return)
        # cid lookup needs stock_board; mock returns cid for platecode 885642
        with monkeypatch_db({("885642",): "301558"}):
            stocks, origin = board_mod.fetch_board_stocks_with_zzshare_fallback(
                board_code="885642", include_quote=True, manager=mgr,
            )
        assert stocks == [{"stock_code": "300740", "stock_name": "x"}]
        assert origin == "ths"
        # ths was called with the cid, not the platecode
        ths_call = [c for c in mgr.get_board_stocks.call_args_list
                    if c.kwargs.get("source") == "ths"][0]
        assert ths_call.kwargs["board_code"] == "301558"

    def test_include_quote_false_prefers_zzshare(self):
        """include_quote=False: zzshare first (no cid translation)."""
        ths_return = ([{"stock_code": "300740", "stock_name": "x"}], "ths")
        zz_return = ([{"stock_code": "300740", "stock_name": "x"}], "zzshare")
        mgr = self._mgr(ths_return, zz_return)
        stocks, origin = board_mod.fetch_board_stocks_with_zzshare_fallback(
            board_code="885642", include_quote=False, manager=mgr,
        )
        assert stocks == [{"stock_code": "300740", "stock_name": "x"}]
        assert origin == "zzshare"
        # zz was called first with platecode (no translation)
        zz_call = mgr.get_board_stocks.call_args_list[0]
        assert zz_call.kwargs["board_code"] == "885642"
        assert zz_call.kwargs["source"] == "zzshare"

    def test_ths_fallback_when_zzshare_empty(self):
        """include_quote=False, zzshare empty → ths fallback."""
        ths_return = ([{"stock_code": "300740", "stock_name": "x"}], "ths")
        zz_return = ([], "zzshare")
        mgr = self._mgr(ths_return, zz_return)
        with monkeypatch_db({("885642",): "301558"}):
            stocks, origin = board_mod.fetch_board_stocks_with_zzshare_fallback(
                board_code="885642", include_quote=False, manager=mgr,
            )
        assert origin == "ths"
        assert stocks == [{"stock_code": "300740", "stock_name": "x"}]

    def test_zzshare_fallback_when_ths_fails(self):
        """include_quote=True, ths raises → zzshare fallback."""
        ths_return = ([], "ths")
        zz_return = ([{"stock_code": "300740", "stock_name": "x"}], "zzshare")
        mgr = self._mgr(ths_return, zz_return, ths_raise=True)
        with monkeypatch_db({("885642",): "301558"}):
            stocks, origin = board_mod.fetch_board_stocks_with_zzshare_fallback(
                board_code="885642", include_quote=True, manager=mgr,
            )
        assert origin == "zzshare"
        assert stocks == [{"stock_code": "300740", "stock_name": "x"}]

    def test_both_empty_returns_empty_origin_empty(self):
        """Both paths return [] → ([], "")."""
        mgr = self._mgr(([], "ths"), ([], "zzshare"))
        with monkeypatch_db({("999999",): None}):
            stocks, origin = board_mod.fetch_board_stocks_with_zzshare_fallback(
                board_code="999999", include_quote=False, manager=mgr,
            )
        assert stocks == []
        assert origin == ""


@pytest.fixture
def monkeypatch_db(monkeypatch):
    """Patch _resolve_ths_cid_from_platecode to return mapped values.
    Usage: with monkeypatch_db({("885642",): "301558", ("999999",): None}): ...
    """
    from contextlib import contextmanager
    @contextmanager
    def _ctx(mapping):
        def fake(platecode):
            return mapping.get((platecode,))
        monkeypatch.setattr(board_mod, "_resolve_ths_cid_from_platecode", fake)
        yield
    return _ctx
```

- [ ] **Step 2: 运行测试确认失败**

Run: `.venv/Scripts/python.exe -m pytest tests/test_persistence_board_merge.py::TestFetchBoardStocksWithZzshareFallback -v`

Expected: FAIL — `AttributeError: ... has no attribute 'fetch_board_stocks_with_zzshare_fallback'`

- [ ] **Step 3: 实现 helper**

在 `stock_data/data_provider/persistence/board.py` 紧跟 `fetch_boards_with_zzshare_backfill` 之后插入:

```python
def fetch_board_stocks_with_zzshare_fallback(
    board_code: str,
    include_quote: bool,
    manager,
) -> tuple[list[dict], str]:
    """Get stocks for a board with source-aware primary/fallback order.

    Strategy:
    - include_quote=False (default): ZzshareFetcher.plates_stocks first
      (anonymous SDK call, fast, no v-token required). On empty/error,
      fallback to ThsFetcher.
    - include_quote=True: ThsFetcher first (THS AJAX returns quote
      fields natively). On empty/error, fallback to ZzshareFetcher.
    - When ThsFetcher is invoked, look up the cid via
      _resolve_ths_cid_from_platecode; if not found, skip THS path
      and return zzshare's result (or empty).
    - ThsFetcher's input is the cid; ZzshareFetcher's input is the
      platecode (which is what the public API hands us).

    Caveat — ZzshareFetcher.get_board_stocks (zzshare_fetcher.py:625)
    accepts `**kwargs` but does NOT consume `include_quote`. The choice
    of THS-vs-zzshare by `include_quote` is therefore based purely on
    the upstream's quote-field availability (THS has them, ZzshareFetcher
    doesn't), not on ZzshareFetcher's handling of the flag.

    Returns:
        (stocks, source) — source is the fetcher name that served
        the response (always 'ths' or 'zzshare'; caller exposes it
        as-is, but writes to stock_board_membership with source='ths').
        When both paths fail or return empty, returns ([], "") — the
        empty-list signal flows through to the route layer's 404 path.

    Raises:
        DataFetchError: only when both fetcher paths raise a Hard error
        (network / 5xx). Empty results are returned as-is (treated as
        "no stocks in this board" → caller → 404).
    """
    def _try_zzshare() -> list[dict]:
        rows, _ = manager.get_board_stocks(
            board_code=board_code, source="zzshare", include_quote=include_quote,
        )
        return rows

    def _try_ths() -> list[dict]:
        cid = _resolve_ths_cid_from_platecode(board_code)
        if not cid:
            return []
        rows, _ = manager.get_board_stocks(
            board_code=cid, source="ths", include_quote=include_quote,
        )
        return rows

    if include_quote:
        # ThsFetcher first
        try:
            rows = _try_ths()
            if rows:
                return rows, "ths"
        except Exception as e:
            logger.warning(
                f"[BoardCache] fetch_board_stocks_with_zzshare_fallback: "
                f"ths failed (will fallback to zzshare): {e}"
            )
        try:
            rows = _try_zzshare()
            if rows:
                return rows, "zzshare"
        except Exception as e:
            logger.warning(
                f"[BoardCache] fetch_board_stocks_with_zzshare_fallback: "
                f"zzshare failed: {e}"
            )
        return [], ""
    else:
        # ZzshareFetcher first
        try:
            rows = _try_zzshare()
            if rows:
                return rows, "zzshare"
        except Exception as e:
            logger.warning(
                f"[BoardCache] fetch_board_stocks_with_zzshare_fallback: "
                f"zzshare failed (will fallback to ths): {e}"
            )
        try:
            rows = _try_ths()
            if rows:
                return rows, "ths"
        except Exception as e:
            logger.warning(
                f"[BoardCache] fetch_board_stocks_with_zzshare_fallback: "
                f"ths failed: {e}"
            )
        return [], ""
```

- [ ] **Step 4: 运行测试确认通过**

Run: `.venv/Scripts/python.exe -m pytest tests/test_persistence_board_merge.py -v`

Expected: 16 PASS(Task 2/3/4 + Task 6 的 5)

- [ ] **Step 5: Commit**

```bash
git add stock_data/data_provider/persistence/board.py tests/test_persistence_board_merge.py
git commit -m "feat(boards): fetch_board_stocks_with_zzshare_fallback helper

include_quote=False → ZZSHARE primary, THS fallback.
include_quote=True  → THS primary, ZZSHARE fallback.
Translates public platecode to THS cid via _resolve_ths_cid_from_platecode
only when invoking ThsFetcher; ZZSHARE accepts platecode directly.
Returns (stocks, origin) where origin reflects the fetcher that served.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 7: 改写 `get_board_stocks()` — 删 `source` 形参

**Files:**
- Modify: `stock_data/data_provider/persistence/board.py:584-651`

- [ ] **Step 1: 写失败的占位测试**

在 `tests/test_boards_api.py` 末尾追加:

```python
def test_get_board_stocks_signature_no_source_arg():
    """get_board_stocks must drop 'source' param after unification."""
    import inspect
    sig = inspect.signature(board_mod.get_board_stocks)
    assert "source" not in sig.parameters, (
        f"get_board_stocks still has 'source' param: {list(sig.parameters)}"
    )
```

- [ ] **Step 2: 运行测试确认失败**

Run: `.venv/Scripts/python.exe -m pytest tests/test_boards_api.py::test_get_board_stocks_signature_no_source_arg -v`

Expected: FAIL — current `get_board_stocks` has `source` param

- [ ] **Step 3: 改 `get_board_stocks` 签名 + body**

整段 `get_board_stocks`(line 584-651)替换为:

```python
def get_board_stocks(
    board_code: str,
    refresh: bool = False,
    include_quote: bool = False,
    manager=None,
) -> tuple[list, str]:
    """Get stocks belonging to a board with automatic refresh.

    Cache is keyed on source='ths' (post-unification). Cache hits return
    origin="persistence". Cache misses call
    fetch_board_stocks_with_zzshare_fallback (THS + ZZSHARE orchestration)
    and write back to source='ths'.

    Args:
        board_code: THS platecode (885xxx concept / 881xxx industry).
        refresh: If True, force refresh from upstream.
        include_quote: If True, always fetch fresh realtime data from upstream.
        manager: DataFetcherManager instance. Required when fetching from upstream.

    Returns:
        Tuple of (stocks, origin) where origin is:
          - "persistence" when data was read from the SQLite cache
          - "ths" when ThsFetcher served the response
          - "zzshare" when ZzshareFetcher served the response (fallback)
          - "" when both paths returned empty
        List of stock dicts: [{"stock_code", "stock_name", ...quote}, ...]
    """
    init_schema()

    needs_refresh = (
        include_quote or refresh or _refresh_tracker.is_first_call(f"{board_code}:ths")
    )

    if not needs_refresh:
        cached = _read_board_stocks_from_db(board_code, "ths")
        if cached:
            return cached, "persistence"

    if manager is None:
        raise ValueError("manager is required when refresh=True or cache miss")

    stocks, origin = fetch_board_stocks_with_zzshare_fallback(
        board_code=board_code, include_quote=include_quote, manager=manager,
    )

    if stocks:
        update_cached_board_stocks(board_code, "ths", stocks)
        logger.info(
            f"[BoardCache] Refreshed {len(stocks)} stocks for board "
            f"{board_code}/ths (origin={origin})"
        )

    return stocks, origin
```

- [ ] **Step 4: 运行测试确认通过**

Run: `.venv/Scripts/python.exe -m pytest tests/test_boards_api.py::test_get_board_stocks_signature_no_source_arg -v`

Expected: PASS

- [ ] **Step 5: 运行持久层套件确认无回归**

Run: `.venv/Scripts/python.exe -m pytest tests/test_persistence_board.py tests/test_board_persistence_subtype.py tests/test_board_membership_readwrite.py tests/test_persistence_board_merge.py -v`

Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add stock_data/data_provider/persistence/board.py tests/test_boards_api.py
git commit -m "refactor(boards): drop source arg from get_board_stocks

DB writes go to source='ths' regardless of which fetcher served.
origin field reflects the actual served fetcher (ths/zzshare/persistence/'').

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 8: 路由层 — `/boards` 端点 `source` Literal 收窄 + 调用适配

**Files:**
- Modify: `stock_data/api/routes/boards.py:300-432`(`list_boards` 路由)

- [ ] **Step 1: 改 `list_boards` 路由的 `source` Literal**

在 `stock_data/api/routes/boards.py:314`,把 `source` Literal 改:

```python
# 改前
source: Literal["eastmoney", "zhitu", "zzshare", "ths"] = Query(
    ..., description="Data source (REQUIRED). All four sources are independent."
),
# 改后
source: Literal["ths", "eastmoney", "zhitu"] = Query(
    ..., description="Data source (REQUIRED). 'zzshare' was unified under 'ths' on 2026-07-08."
),
```

- [ ] **Step 2: 删 `list_boards` 内 `get_board_list` 调用的 `source` 形参**

在 `stock_data/api/routes/boards.py:383-390`,改:

```python
# 改前
boards, origin = stock_board_cache.get_board_list(
    board_type=type,
    source=source,
    refresh=refresh,
    include_quote=include_quote,
    subtype=subtype,
    manager=manager,
)
# 改后
boards, origin = stock_board_cache.get_board_list(
    board_type=type,
    refresh=refresh,
    include_quote=include_quote,
    subtype=subtype,
    manager=manager,
)
```

- [ ] **Step 3: 运行 boards 测试确认无回归**

Run: `.venv/Scripts/python.exe -m pytest tests/test_boards.py -v`

Expected: 部分可能 FAIL(测试代码还在传 source),记录失败列表,等 Task 11 改完测试再过

- [ ] **Step 4: Commit(仅路由改动)**

```bash
git add stock_data/api/routes/boards.py
git commit -m "refactor(routes): tighten /boards source Literal to drop 'zzshare'

Aligns with persistence layer's get_board_list dropping the source
parameter. zzshare→ths internal merge now lives entirely in
persistence/board.py:fetch_boards_with_zzshare_backfill.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 9: 路由层 — `/boards/{code}/stocks` 端点 `source` Literal 收窄 + 调用适配

**Files:**
- Modify: `stock_data/api/routes/boards.py:435-536`(`get_board_stocks` 路由)

- [ ] **Step 1: 改 `get_board_stocks` 路由的 `source` Literal**

在 `stock_data/api/routes/boards.py:454-462`,把 `source` Literal 改:

```python
# 改前
source: Literal["ths", "eastmoney", "zhitu", "zzshare"] = Query(
    ...,
    description=(
        "Data source (REQUIRED). All four sources are independently "
        "valid: `ths` (ThsFetcher via q.10jqka.com.cn AJAX), "
        "`eastmoney` (push2his), `zhitu`, "
        "`zzshare` (plates_stocks — upstream IS 同花顺 data)."
    ),
),
# 改后
source: Literal["ths", "eastmoney", "zhitu"] = Query(
    ...,
    description=(
        "Data source (REQUIRED). 'zzshare' was unified under 'ths' "
        "on 2026-07-08. include_quote=false → ZZSHARE primary, THS "
        "fallback. include_quote=true → THS primary, ZZSHARE fallback."
    ),
),
```

- [ ] **Step 2: 删 `get_board_stocks` 内 `get_board_stocks` 调用的 `source` 形参**

在 `stock_data/api/routes/boards.py:485-494`,改:

```python
# 改前
stocks, origin = stock_board_cache.get_board_stocks(
    board_code,
    source=source,
    refresh=refresh,
    include_quote=include_quote,
    manager=manager,
)
# 改后
stocks, origin = stock_board_cache.get_board_stocks(
    board_code,
    refresh=refresh,
    include_quote=include_quote,
    manager=manager,
)
```

- [ ] **Step 3: Commit**

```bash
git add stock_data/api/routes/boards.py
git commit -m "refactor(routes): tighten /boards/{code}/stocks source Literal

Drop 'zzshare' from public API surface. DB writes go to source='ths'
via the refactored persistence helper.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 10: 路由层 — 删 dead code `_parse_source_csv()`

**Files:**
- Modify: `stock_data/api/routes/boards.py:207-238`

- [ ] **Step 1: 确认 dead code**

Run: `grep -rn "_parse_source_csv" stock_data/ tests/`

Expected: 仅 `boards.py:207` 定义 + 几个 docstring 引用。无 caller。

- [ ] **Step 2: 整段删除 `_parse_source_csv` 函数**

在 `stock_data/api/routes/boards.py:207-238`,整段删除 `_parse_source_csv` 函数(共 32 行)。

- [ ] **Step 3: 清理 docstring 引用**

在 `stock_data/api/routes/boards.py:248` 附近(`normalize_board_stocks_source` docstring 提到 "Unlike ``normalize_stock_board_source``"),无需修改。

在 `stock_data/data_provider/persistence/board.py:135` 附近(之前 docstring 引用 `_parse_source_csv`),如果还在引用,删掉那一行注释引用。检查:

```python
# 改前 (board.py 旧 docstring)
``boards.py:_parse_source_csv``.
# 改后
(无引用,或改为 "see boards.py route layer" 等通用描述)
```

- [ ] **Step 4: 启动 server smoke test 确认无 500**

Run: `.venv/Scripts/python.exe -c "from stock_data.api.routes import boards; print('ok')"`

Expected: `ok`

- [ ] **Step 5: Commit**

```bash
git add stock_data/api/routes/boards.py stock_data/data_provider/persistence/board.py
git commit -m "refactor(routes): remove dead code _parse_source_csv

Function was defined but never called; the boards-list endpoint
never used CSV sources. Stale docstring references cleaned up.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 11: 测试清理 — `tests/test_boards.py` 删 `TestThsSourceAliasMatrix`

**Files:**
- Modify: `tests/test_boards.py:321-366`

- [ ] **Step 1: 删整 class**

在 `tests/test_boards.py:321-366`,删除整个 `TestThsSourceAliasMatrix` class(含 `test_board_list_ths_aliases_to_zzshare` 和 `test_board_stocks_ths_does_not_alias` 两个测试)。

- [ ] **Step 2: 运行测试确认无 syntax 错误**

Run: `.venv/Scripts/python.exe -m pytest tests/test_boards.py --collect-only 2>&1 | head -20`

Expected: collect 通过,无 ImportError / SyntaxError

- [ ] **Step 3: Commit**

```bash
git add tests/test_boards.py
git commit -m "test(boards): remove TestThsSourceAliasMatrix (alias behavior retired)

The ths→zzshare alias on /boards and /boards/{code}/stocks no longer
exists (post-unification). History and reverse-lookup endpoints still
have their own alias maps (covered by tests in
test_boards_history_route.py and test_stock_boards_reverse_route.py).

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 12: 测试清理 — `tests/test_boards.py` 新增 `TestThsOnly` class

**Files:**
- Modify: `tests/test_boards.py`(在 `TestThsSourceAliasMatrix` 删后位置追加)

- [ ] **Step 1: 追加 `TestThsOnly` class**

在 `tests/test_boards.py`(刚删完 class 的位置附近)追加:

```python
class TestThsOnly:
    """Post-unification: boards endpoints accept only ths/eastmoney/zhitu."""

    def test_boards_list_source_zzshare_returns_422(self, client):
        """/api/v1/boards?source=zzshare returns 422 (FastAPI Literal rejects)."""
        response = client.get("/api/v1/boards?type=concept&source=zzshare")
        assert response.status_code == 422

    def test_boards_list_source_ths_passes_through(self, client):
        """/api/v1/boards?source=ths reaches persistence; source hardcoded to 'ths'."""
        from stock_data.data_provider.persistence import board as board_mod
        from unittest.mock import patch, MagicMock
        with patch.object(board_mod, "fetch_boards_with_zzshare_backfill",
                          return_value=[]):
            response = client.get("/api/v1/boards?type=concept&source=ths")
        assert response.status_code == 200
        # The persistence helper is called without a 'source' arg (post-unification)
        for call in board_mod.fetch_boards_with_zzshare_backfill.call_args_list:
            assert "source" not in call.kwargs

    def test_board_stocks_source_zzshare_returns_422(self, client):
        """/api/v1/boards/885642/stocks?source=zzshare returns 422."""
        response = client.get("/api/v1/boards/885642/stocks?source=zzshare")
        assert response.status_code == 422

    def test_board_stocks_include_quote_false_prefers_zzshare(self, client):
        """/boards/{code}/stocks?include_quote=false → ZZSHARE primary, THS fallback."""
        from unittest.mock import patch, MagicMock
        mgr = MagicMock()
        mgr.get_board_stocks.return_value = (
            [{"stock_code": "300740", "stock_name": "x"}], "zzshare",
        )
        with patch("stock_data.api.routes.boards.get_manager", return_value=mgr):
            response = client.get(
                "/api/v1/boards/885642/stocks?source=ths&include_quote=false"
            )
        assert response.status_code == 200
        first_call = mgr.get_board_stocks.call_args_list[0]
        assert first_call.kwargs["source"] == "zzshare"
        assert first_call.kwargs["board_code"] == "885642"  # platecode, not cid

    def test_board_stocks_include_quote_true_prefers_ths(self, client):
        """/boards/{code}/stocks?include_quote=true → THS primary, ZZSHARE fallback."""
        from unittest.mock import patch, MagicMock
        from stock_data.data_provider.persistence import board as board_mod
        mgr = MagicMock()
        mgr.get_board_stocks.return_value = (
            [{"stock_code": "300740", "stock_name": "x"}], "ths",
        )
        # Mock the cid resolution to return a known cid
        with patch.object(board_mod, "_resolve_ths_cid_from_platecode",
                          return_value="301558"), \
             patch("stock_data.api.routes.boards.get_manager", return_value=mgr):
            response = client.get(
                "/api/v1/boards/885642/stocks?source=ths&include_quote=true"
            )
        assert response.status_code == 200
        first_call = mgr.get_board_stocks.call_args_list[0]
        assert first_call.kwargs["source"] == "ths"
        assert first_call.kwargs["board_code"] == "301558"  # translated cid

    def test_board_stocks_ths_fallback_when_zzshare_empty(self, client):
        """include_quote=false, zzshare empty → THS fallback (origin='ths')."""
        from unittest.mock import patch, MagicMock
        from stock_data.data_provider.persistence import board as board_mod
        mgr = MagicMock()
        mgr.get_board_stocks.side_effect = [
            ([], "zzshare"),  # primary empty
            ([{"stock_code": "300740", "stock_name": "x"}], "ths"),  # fallback hits
        ]
        with patch.object(board_mod, "_resolve_ths_cid_from_platecode",
                          return_value="301558"), \
             patch("stock_data.api.routes.boards.get_manager", return_value=mgr):
            response = client.get(
                "/api/v1/boards/885642/stocks?source=ths&include_quote=false"
            )
        assert response.status_code == 200
        body = response.json()
        assert body["data_source"] == "ths"  # origin reflects fallback fetcher

    def test_board_stocks_zzshare_fallback_when_ths_fails(self, client):
        """include_quote=true, THS raises → ZZSHARE fallback (origin='zzshare')."""
        from unittest.mock import patch, MagicMock
        from stock_data.data_provider.persistence import board as board_mod
        mgr = MagicMock()
        mgr.get_board_stocks.side_effect = [
            Exception("ths 503"),  # primary raises
            ([{"stock_code": "300740", "stock_name": "x"}], "zzshare"),
        ]
        with patch.object(board_mod, "_resolve_ths_cid_from_platecode",
                          return_value="301558"), \
             patch("stock_data.api.routes.boards.get_manager", return_value=mgr):
            response = client.get(
                "/api/v1/boards/885642/stocks?source=ths&include_quote=true"
            )
        assert response.status_code == 200
        body = response.json()
        assert body["data_source"] == "zzshare"
```

- [ ] **Step 2: 运行 `TestThsOnly` 确认通过**

Run: `.venv/Scripts/python.exe -m pytest tests/test_boards.py::TestThsOnly -v`

Expected: 7 PASS

- [ ] **Step 3: Commit**

```bash
git add tests/test_boards.py
git commit -m "test(boards): add TestThsOnly covering post-unification behavior

- source=zzshare → 422 (FastAPI Literal)
- include_quote=false → ZZSHARE primary, platecode passed directly
- include_quote=true → THS primary, platecode→cid translation
- Both fallback paths: zzshare-empty→ths-fallback, ths-raises→zzshare-fallback

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 13: 测试清理 — `tests/test_boards_api.py` 改写旧测试

**Files:**
- Modify: `tests/test_boards_api.py`

- [ ] **Step 1: 改写 `test_list_boards_source_zzshare_still_works`(line 82)**

把 `test_list_boards_source_zzshare_still_works` 函数体替换为:

```python
def test_list_boards_source_zzshare_returns_422(client):
    """?source=zzshare on /boards returns 422 (FastAPI Literal validation)."""
    r = client.get("/api/v1/boards?type=concept&source=zzshare")
    assert r.status_code == 422
```

- [ ] **Step 2: 删除 `test_list_boards_zzshare_no_type_returns_all_supported_types`(line 267)**

整函数删除。

- [ ] **Step 3: 改写 `test_list_boards_zzshare_type_special_returns_400`(line 245)**

把函数体替换为(现在 source 校验提前,不再走到 type 校验):

```python
def test_list_boards_source_zzshare_type_special_returns_422(client):
    """?source=zzshare&type=special returns 422 (Literal check fires before type check)."""
    r = client.get("/api/v1/boards?type=special&source=zzshare")
    assert r.status_code == 422
```

- [ ] **Step 4: 改写 `test_get_board_stocks_zzshare_still_works`(line 427)**

把函数体替换为:

```python
def test_get_board_stocks_source_zzshare_returns_422(client):
    """?source=zzshare on /boards/{code}/stocks returns 422."""
    r = client.get("/api/v1/boards/308709/stocks?source=zzshare")
    assert r.status_code == 422
```

- [ ] **Step 5: 改写 `test_list_boards_source_ths_passes_ths_to_persistence`(line 50)**

把 `assert kwargs.get("source") == "ths"` 改为断言不传 source 形参(`get_board_list` signature 已 drop source):

```python
def test_list_boards_source_ths_passes_ths_to_persistence(client):
    """?source=ths reaches persistence; source hardcoded to 'ths' inside helper."""
    from unittest.mock import patch
    from stock_data.data_provider.persistence import board as board_mod
    with patch.object(board_mod, "fetch_boards_with_zzshare_backfill",
                      return_value=[]) as mock_fetch:
        r = client.get("/api/v1/boards?type=concept&source=ths")
    assert r.status_code == 200
    # After unification, get_board_list doesn't take 'source' kwarg
    for call in mock_fetch.call_args_list:
        assert "source" not in call.kwargs
```

- [ ] **Step 6: 改写 `test_get_board_stocks_ths_passes_ths_to_persistence`(line 400)**

把内部 mock 从 `get_board_stocks` 改为 `fetch_board_stocks_with_zzshare_fallback`,断言不传 source 形参:

```python
def test_get_board_stocks_source_ths_passes_ths_to_persistence(client):
    """?source=ths reaches persistence; fetch helper called without source arg."""
    from unittest.mock import patch
    from stock_data.data_provider.persistence import board as board_mod
    with patch.object(board_mod, "fetch_board_stocks_with_zzshare_fallback",
                      return_value=([], "")) as mock_fetch:
        r = client.get("/api/v1/boards/885642/stocks?source=ths")
    assert r.status_code in (200, 404)  # empty may 404
    for call in mock_fetch.call_args_list:
        assert "source" not in call.kwargs
```

- [ ] **Step 7: 运行 `test_boards_api.py` 确认通过**

Run: `.venv/Scripts/python.exe -m pytest tests/test_boards_api.py -v`

Expected: 全部 PASS(改写的 6 个 + 未触碰的其他)

- [ ] **Step 8: Commit**

```bash
git add tests/test_boards_api.py
git commit -m "test(boards): rewrite source=zzshare tests for post-unification 422

Six tests touched:
- test_list_boards_source_zzshare_still_works → returns_422
- test_list_boards_zzshare_no_type_returns_all_supported_types → deleted
- test_list_boards_zzshare_type_special_returns_400 → returns_422
- test_get_board_stocks_zzshare_still_works → returns_422
- test_list_boards_source_ths_passes_ths_to_persistence → no source kwarg
- test_get_board_stocks_ths_passes_ths_to_persistence → no source kwarg

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 14: endpoint_meta summary 更新

**Files:**
- Modify: `stock_data/api/routes/boards.py:300-304` 与 `445-450`

- [ ] **Step 1: 改 `/boards` summary**

在 `stock_data/api/routes/boards.py:300-304`:

```python
# 改前
@endpoint_meta(
    summary="板块清单（支持实时报价、排序、截断）",
    markets=["csi"],
    capabilities=["STOCK_BOARD"],
)
# 改后
@endpoint_meta(
    summary="板块清单 (ths; 内部合并 zzshare 补 platecode) — ?source=zzshare 已下线",
    markets=["csi"],
    capabilities=["STOCK_BOARD"],
)
```

- [ ] **Step 2: 改 `/boards/{code}/stocks` summary**

在 `stock_data/api/routes/boards.py:445-450`:

```python
# 改前
@endpoint_meta(
    summary="板块成分股 (ths/eastmoney/zhitu/zzshare — no alias)",
    markets=["csi"],
    capabilities=["STOCK_BOARD"],
    fetcher_method="get_board_stocks",
)
# 改后
@endpoint_meta(
    summary="板块成分股 (ths/eastmoney/zhitu; ?source=zzshare 已下线; "
            "include_quote=false 走 zzshare 优先, 失败 fallback 到 ths)",
    markets=["csi"],
    capabilities=["STOCK_BOARD"],
    fetcher_method="get_board_stocks",
)
```

- [ ] **Step 3: Commit**

```bash
git add stock_data/api/routes/boards.py
git commit -m "docs(routes): update endpoint_meta summary for boards endpoints

Reflect post-unification behavior in the explorer manifest.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 15: 最终集成 smoke test + 全套件回归

**Files:**
- 无代码改动,纯验证

- [ ] **Step 1: 启动 server 跑 smoke test**

```bash
# 从项目根目录
.venv/Scripts/python.exe -m stock_data.server &
sleep 3

# /boards?source=zzshare 应该 422
curl -s -o /dev/null -w "%{http_code}" "http://localhost:8888/api/v1/boards?type=concept&source=zzshare"
# 期望:422

# /boards?source=ths 应该 200(可能数据是空的,看 live_network 是否开)
curl -s "http://localhost:8888/api/v1/boards?type=concept&source=ths" | head -c 200
# 期望:JSON 响应,可能 source="persistence" 或 "ths"
```

- [ ] **Step 2: 检查 explorer manifest 反映新 summary**

```bash
curl -s "http://localhost:8888/control/api-manifest" | python -c "
import json, sys
m = json.load(sys.stdin)
for sec in m.get('sections', []):
    for ep in sec.get('endpoints', []):
        if '/boards' in ep.get('path', '') or 'board' in ep.get('path', '').lower():
            print(ep.get('path'), '->', ep.get('summary', ''))
"
```

Expected: 看到新 summary,含 "已下线" 字样

- [ ] **Step 3: 跑完整测试套件(默认 skip live_network)**

Run: `.venv/Scripts/python.exe -m pytest`

Expected: 全部 PASS

- [ ] **Step 4: 跑完整测试套件(含 live_network,需 token)**

Run: `.venv/Scripts/python.exe -m pytest -m ""

Expected: 大部分 PASS,live_network 类可能 xfail(ths/zzshare 依赖上游,可能挂)

- [ ] **Step 5: 关闭 server**

```bash
# 找占用 8888 的 PID(注意不要 kill 用户自己的 server,见 memory)
netstat -ano | grep :8888
# 如果是本进程启动的,kill 它
# 假设 PID 是 XXXXX
# taskkill //F //PID XXXXX
```

- [ ] **Step 6: 如有修复,单独 commit;否则标记完成**

如有发现,按类型 commit:
```bash
git add <files>
git commit -m "fix(boards): <description>

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Self-Review Checklist

对照 spec 验证 plan 覆盖度:

- [x] **§1.1 公共 API 收窄** → Task 8 / Task 9(改 Literal)+ Task 13(测试改 422)
- [x] **§1.2 / §1.3 内部 merge + stocks 主备** → Task 2 / Task 3 / Task 4 / Task 6(4 个 helper)+ Task 5 / Task 7(改 get_board_list / get_board_stocks 签名)
- [x] **§1.4 platecode 公开** → Task 6(`fetch_board_stocks_with_zzshare_fallback` 用 platecode)+ Task 12 测试覆盖
- [x] **§2 目标 1-6** → 全部覆盖
- [x] **§3.1 路由 Literal** → Task 8 / Task 9
- [x] **§3.2 VALID_SOURCES 收窄** → Task 1
- [x] **§3.3 fetch_boards_with_zzshare_backfill** → Task 4
- [x] **§3.4 _merge_ths_zzshare_by_name** → Task 3
- [x] **§3.5 改 get_board_list** → Task 5
- [x] **§3.6 _resolve_ths_cid_from_platecode** → Task 2
- [x] **§3.7 fetch_board_stocks_with_zzshare_fallback** → Task 6
- [x] **§3.8 改 get_board_stocks** → Task 7
- [x] **§3.9 路由调用适配** → Task 8 / Task 9
- [x] **§3.10 endpoint_meta summary** → Task 14
- [x] **§4 端点行为矩阵** → 全部覆盖(改后行为在 Task 8 / 9 / 12 / 13)
- [x] **§5 数据流图** → Task 12 测试覆盖 5.2 / 5.3 / 5.5;5.1 / 5.4 由 Task 5 / 7 行为自然覆盖
- [x] **§6 错误处理** → Task 12 测试 422;5.4 由 Task 6 helper 返回 `([], "")`
- [x] **§7.1 新增测试** → Task 12(`TestThsOnly` 7 个) + Task 2-6 单元测试
- [x] **§7.2 删除/改写旧测试** → Task 11(删 class)+ Task 13(改 6 个)+ 已存在的 history / reverse 测试不删(spec 确认)
- [x] **§8 兼容性 / 迁移** → 无 DB schema 改动(已确认);API breaking 写在 endpoint_meta summary
- [x] **§9 风险** → 接受现状(无 task);name 冲突 + 冷启动延迟都有 mitigation(merge helper + try/except)
- [x] **§10 决策记录** → 已反映在 plan 任务选择中
