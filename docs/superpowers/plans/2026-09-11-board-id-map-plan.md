# board cid→platecode 映射基础设施 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 建立 THS `cid → platecode` 的本地映射（表 + seed CSV + 刷新工具），并让 `ThsFetcher` 用它在板块清单里解出侧栏板块的 platecode，消除 141 个 cid-only 板块导致的 422。

**Architecture:** 新增窄表 `ths_board_id_map` 作为"两套 id 关系"的唯一查询点；repo 内提交一份 `ths_board_id_map.csv` 作冷启动 seed；`tools/refresh_ths_board_id_map.py` 从 THS 自身（gn 首页 `gnSection` + 逐板详情页）刷新并对上一版做 diff。运行期只查表、不发额外请求。

**Tech Stack:** Python 3.13 / SQLite (`persistence` 层) / FastAPI（仅 `server.py` lifespan 复用既有 seed 通道）/ pytest / bs4（`ThsFetcher` 既有依赖）

## Global Constraints

- 本机**没有** `.venv/`，解释器用系统 `python`（miniconda 3.13.9）。`akshare` / `yfinance` / `gm` 不可用 —— 本计划不触碰 akshare 路由的端点。
- 测试命令一律 `python -m pytest <path> -v`；默认 addopts 已排除 `live_network`。
- 新代码遵守 spec §5 命名契约：board 路径**禁止裸 `code`**，必须写 `board_code` / `stock_code` / `ths_cid`。（`code` 作为既有行 key 的清理属 Plan 2，本计划不改。）
- `ths_board_id_map` 的写入必须过滤非 THS cid：`710xxx` / `803xxx` 是 zzshare code，**绝不可**入表（spec §3.1）。
- seed CSV 的优先级**必须低于** live 观测：表用 `INSERT OR REPLACE`（后写覆盖），工具先读 base 再叠加 live。
- 不新增第三方依赖。
- 所有 `*.py` 改动走 `feat/*` 分支；`docs/` 下的 markdown 直接提交 master。

## 范围与路线图

| 计划 | 覆盖 spec 阶段 | 交付物 | 公开 API 变化 |
|---|---|---|---|
| **Plan 1（本文档）** | 阶段 1 + 阶段 2 的侧栏解析半部分 | 映射表 + seed CSV + 刷新工具 + `ThsFetcher` 侧栏解析 | **无** |
| Plan 2 | 阶段 3-6 | id/命名契约、删 merge/fallback、路由放开 zzshare、include_quote 两层 | 有（6 项 breaking） |
| Plan 3 | 阶段 7-9 | 测试重写、4 份文档、`STOCK_DB_INIT` 重建与端到端验证 | 无 |

**为什么 3-6 不拆进本计划**：重命名行 key（`code`/`platecode` → `board_code`/`ths_cid`）会立刻打断 `persistence` 的读写，两者必须同一个 commit 落地；把它塞进本计划会让"映射基础设施"失去可独立交付性。

**一处相对 spec 的偏差（有意）**：spec §6 写"`map` miss 时走 gn detail 页单次解析并回写"发生在**运行期**。本计划把它移到**工具期**（`tools/refresh_ths_board_id_map.py`），运行期只查表。理由：`ths_fetcher.py:1784-1790` 的既有注释已论证"每次 refresh 多 88 个请求"是必须避免的成本；且实测 seed 已覆盖 138/141（98%），运行期 miss 不值得换 N 个请求。

---

## File Structure

| 文件 | 职责 |
|---|---|
| `stock_data/data_provider/persistence/board.py` (Modify) | 新表 DDL + `ths_board_id_map` 的 CRUD（唯一写入/查询点） |
| `stock_data/data_provider/persistence/board_csv.py` (Modify) | `ths_board_id_map.csv` 的 loader + 挂进 `seed_all_from_backup_dir`（顺序在 board 之前） |
| `stock_data/data_provider/persistence/__init__.py` (Modify) | 导出新 CRUD |
| `stock_data/data_provider/fetchers/ths_fetcher.py` (Modify) | `extract_platecode_from_detail` + `_merge_concept_sources` 查表解析侧栏 |
| `tools/refresh_ths_board_id_map.py` (Create) | 刷新 + diff 生成器（唯一触碰 gn 详情页的地方） |
| `stock_data/stock_data_backup/ths_board_id_map.csv` (Create) | 480 条 seed，repo 内提交 |
| `tests/test_persistence_ths_board_id_map.py` (Create) | 表 + CRUD 单测 |
| `tests/test_ths_board_id_map_csv_seed.py` (Create) | loader + seed 顺序 + 提交产物校验 |
| `tests/test_refresh_ths_board_id_map.py` (Create) | 生成器纯函数 + 注入 fake fetcher |
| `tests/test_ths_fetcher_sidebar_platecode.py` (Create) | 解析器 + 侧栏查表 |
| `tests/fixtures/ths_gn_index.html` (Create) | gn 首页 fixture（含真实 `gnSection` + `cate_items` 片段） |
| `tests/fixtures/ths_gn_detail_309121.html` (Create) | 详情页 fixture（仅含 886071 一个候选） |
| `docs/board-source-semantics.md` (Modify) | 增一节 `THS cid ↔ platecode` |

---

### Task 1: `ths_board_id_map` 表 + CRUD

**Files:**
- Modify: `stock_data/data_provider/persistence/board.py`（`init_schema` 的 `conn.commit()` 之前；新函数放在 `_is_valid_stock_code` 附近，约 line 2178）
- Modify: `stock_data/data_provider/persistence/__init__.py`
- Test: `tests/test_persistence_ths_board_id_map.py`

**Interfaces:**
- Produces: `_is_ths_cid(value: Any) -> bool`、`upsert_ths_board_id_map(rows: list[dict], conn: sqlite3.Connection | None = None) -> int`、`resolve_ths_platecode(ths_cid: str) -> str | None`、`get_ths_board_id_map_rows() -> list[dict[str, Any]]`
- Consumes: 无

- [ ] **Step 1: 写失败测试**

Create `tests/test_persistence_ths_board_id_map.py`:

```python
"""Tests for the ths_board_id_map table (THS cid → platecode)."""

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


class TestIsThsCid:
    def test_concept_cid_accepted(self):
        assert board_mod._is_ths_cid("300188") is True

    def test_industry_cid_accepted(self):
        assert board_mod._is_ths_cid("881121") is True

    def test_zzshare_code_rejected(self):
        """710xxx / 803xxx are zzshare plate codes, not THS cids (spec §3.1)."""
        assert board_mod._is_ths_cid("710002") is False
        assert board_mod._is_ths_cid("803003") is False

    def test_platecode_rejected(self):
        assert board_mod._is_ths_cid("885311") is False

    def test_non_string_and_bad_length_rejected(self):
        assert board_mod._is_ths_cid(None) is False
        assert board_mod._is_ths_cid(300188) is False
        assert board_mod._is_ths_cid("30018") is False
        assert board_mod._is_ths_cid("３００１８８") is False  # fullwidth digits


class TestUpsertAndResolve:
    def test_roundtrip(self, fresh_db):
        written = board_mod.upsert_ths_board_id_map(
            [
                {"cid": "309121", "platecode": "886071", "name": "AI PC", "board_type": "concept"},
                {"cid": "881121", "platecode": "881121", "name": "半导体", "board_type": "industry"},
            ]
        )
        assert written == 2
        assert board_mod.resolve_ths_platecode("309121") == "886071"
        # industry identity row keeps resolve() heuristic-free
        assert board_mod.resolve_ths_platecode("881121") == "881121"

    def test_resolve_unknown_returns_none(self, fresh_db):
        assert board_mod.resolve_ths_platecode("999999") is None

    def test_resolve_empty_returns_none(self, fresh_db):
        assert board_mod.resolve_ths_platecode("") is None

    def test_zzshare_cid_rejected_on_write(self, fresh_db):
        """A 710xxx 'cid' from the legacy CSV must never enter the map."""
        written = board_mod.upsert_ths_board_id_map(
            [{"cid": "710002", "platecode": "710002", "name": "DeFi", "board_type": "concept"}]
        )
        assert written == 0
        assert board_mod.resolve_ths_platecode("710002") is None

    def test_row_without_platecode_skipped(self, fresh_db):
        written = board_mod.upsert_ths_board_id_map([{"cid": "309121", "platecode": ""}])
        assert written == 0

    def test_later_write_wins(self, fresh_db):
        """The tool MUST be able to overwrite a stale seed value (spec §3.2)."""
        board_mod.upsert_ths_board_id_map(
            [{"cid": "309121", "platecode": "886071", "name": "AI PC", "board_type": "concept"}]
        )
        board_mod.upsert_ths_board_id_map(
            [{"cid": "309121", "platecode": "886999", "name": "AI PC", "board_type": "concept"}]
        )
        assert board_mod.resolve_ths_platecode("309121") == "886999"

    def test_rewrite_updates_name_without_duplicating(self, fresh_db):
        board_mod.upsert_ths_board_id_map(
            [{"cid": "309121", "platecode": "886071", "name": "AI PC", "board_type": "concept"}]
        )
        board_mod.upsert_ths_board_id_map(
            [{"cid": "309121", "platecode": "886071", "name": "AI PC 概念", "board_type": "concept"}]
        )
        rows = board_mod.get_ths_board_id_map_rows()
        assert len(rows) == 1
        assert rows[0]["name"] == "AI PC 概念"

    def test_empty_input_is_noop(self, fresh_db):
        assert board_mod.upsert_ths_board_id_map([]) == 0
        assert board_mod.get_ths_board_id_map_rows() == []

    def test_get_rows_sorted_by_cid(self, fresh_db):
        board_mod.upsert_ths_board_id_map(
            [
                {"cid": "309121", "platecode": "886071", "name": "AI PC", "board_type": "concept"},
                {"cid": "300188", "platecode": "885333", "name": "移动支付", "board_type": "concept"},
            ]
        )
        assert [r["cid"] for r in board_mod.get_ths_board_id_map_rows()] == ["300188", "309121"]
```

- [ ] **Step 2: 运行确认失败**

Run: `python -m pytest tests/test_persistence_ths_board_id_map.py -v`
Expected: FAIL — `AttributeError: module 'stock_data.data_provider.persistence.board' has no attribute '_is_ths_cid'`

- [ ] **Step 3: 加表 DDL**

在 `board.py` 的 `init_schema()` 里、`conn.commit()`（约 line 406，位于 membership 索引创建之后）之前插入：

```python
    # THS cid → platecode map. The single query point for "which of THS's
    # two board identifiers do I use here" — see docs/superpowers/specs/
    # 2026-09-11-board-source-split-design.md §3. `cid` is the stable key
    # (3xxxxx concept / 881xxx industry); `platecode` is the public one.
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS ths_board_id_map (
            cid        TEXT PRIMARY KEY,
            platecode  TEXT NOT NULL,
            name       TEXT,
            board_type TEXT,
            observed_at DATETIME
        )
    """)
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_ths_board_id_map_platecode
            ON ths_board_id_map(platecode)
    """)
```

（`reset_all()` 通过扫 `sqlite_master` 发现表，无需改动。）

- [ ] **Step 4: 加 CRUD**

在 `board.py` 的 `_is_valid_stock_code`（约 line 2178）之后追加：

```python
def _is_ths_cid(value: Any) -> bool:
    """True iff ``value`` is a THS board cid.

    A THS cid is either a concept cid (3xxxxx) or an industry cid
    (881xxx — identical to its platecode). Everything else is rejected,
    notably the zzshare plate codes (710xxx / 803xxx) that the legacy
    ``stock_board_ths.csv`` stores in its ``cid`` column: those are not
    mappings, and 118 such concept rows exist in that file (spec §3.1).
    """
    if not isinstance(value, str) or len(value) != 6:
        return False
    # isascii() guards against fullwidth digits, which str.isdigit() accepts.
    if not (value.isascii() and value.isdigit()):
        return False
    return value.startswith("3") or value.startswith("881")


def upsert_ths_board_id_map(
    rows: list[dict], conn: sqlite3.Connection | None = None
) -> int:
    """Upsert THS ``cid → platecode`` mappings. Returns the rows written.

    Rows whose ``cid`` fails :func:`_is_ths_cid`, or that carry no
    platecode, are skipped silently (the caller's row count is the
    diagnostic). Last write wins, so callers merge *live* observations
    after CSV seeds — the CSV is a snapshot, live data is authoritative
    (spec §3.2).
    """
    if not rows:
        return 0
    init_schema()
    if conn is None:
        conn = get_connection()
    payload = [
        (
            r["cid"],
            r["platecode"],
            r.get("name") or "",
            r.get("board_type") or "",
        )
        for r in rows
        if _is_ths_cid(r.get("cid")) and r.get("platecode")
    ]
    if not payload:
        return 0
    with conn:
        conn.cursor().executemany(
            """INSERT OR REPLACE INTO ths_board_id_map
               (cid, platecode, name, board_type, observed_at)
               VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)""",
            payload,
        )
    return len(payload)


def resolve_ths_platecode(ths_cid: str) -> str | None:
    """Return the THS platecode for a THS cid, or ``None`` when unmapped.

    Single SELECT. This helper is the only sanctioned cid → platecode
    lookup (spec §3.2) — callers must not rebuild the relation ad hoc
    (that is how the by-board-name join ended up conflating two code
    spaces).
    """
    if not ths_cid:
        return None
    init_schema()
    row = get_connection().execute(
        "SELECT platecode FROM ths_board_id_map WHERE cid = ?", (ths_cid,)
    ).fetchone()
    return row["platecode"] if row else None


def get_ths_board_id_map_rows() -> list[dict[str, Any]]:
    """All mappings ordered by cid (CSV export / tool / test use)."""
    init_schema()
    rows = get_connection().execute(
        "SELECT cid, platecode, name, board_type, observed_at "
        "FROM ths_board_id_map ORDER BY cid"
    ).fetchall()
    return [dict(r) for r in rows]
```

- [ ] **Step 5: 导出到 persistence 顶层 API**

在 `stock_data/data_provider/persistence/__init__.py` 的 `from .board import (...)` 列表中加入（保持字母序）：

```python
from .board import (
    get_board_list,
    get_board_stocks,
    get_ths_board_id_map_rows,
    resolve_ths_platecode,
    update_cached_board_stocks,
    update_cached_boards,
    upsert_ths_board_id_map,
)
```

并把 `"get_ths_board_id_map_rows"` / `"resolve_ths_platecode"` / `"upsert_ths_board_id_map"` 加进 `__all__` 的 board CRUD 段。

- [ ] **Step 6: 运行确认通过**

Run: `python -m pytest tests/test_persistence_ths_board_id_map.py -v`
Expected: PASS（16 passed）

- [ ] **Step 7: 提交**

```bash
git checkout -b feat/ths-board-id-map
git add stock_data/data_provider/persistence/board.py \
        stock_data/data_provider/persistence/__init__.py \
        tests/test_persistence_ths_board_id_map.py
git commit -m "feat(persistence): add ths_board_id_map table (cid → platecode)"
```

---

### Task 2: seed CSV + loader

**Files:**
- Create: `stock_data/stock_data_backup/ths_board_id_map.csv`（由一次性脚本生成）
- Modify: `stock_data/data_provider/persistence/board_csv.py`（loader + 挂进 `seed_all_from_backup_dir`，**顺序在 board 之前**）
- Test: `tests/test_ths_board_id_map_csv_seed.py`

**Interfaces:**
- Consumes: Task 1 的 `board_mod.upsert_ths_board_id_map(rows) -> int`
- Produces: `seed_ths_board_id_map_from_csv(csv_path: Path) -> int`

- [ ] **Step 1: 生成 seed CSV**

在 repo 根目录运行（一次性；本机 `python` 即可）：

```bash
python - <<'PY'
import csv

SRC = "stock_data/stock_data_backup/stock_board_ths.csv"
DST = "stock_data/stock_data_backup/ths_board_id_map.csv"


def is_ths_cid(v):
    return (
        isinstance(v, str)
        and len(v) == 6
        and v.isascii()
        and v.isdigit()
        and (v.startswith("3") or v.startswith("881"))
    )


seen = {}
for r in csv.DictReader(open(SRC, encoding="utf-8-sig")):
    if not is_ths_cid(r.get("cid")) or not r.get("code"):
        continue
    seen.setdefault(r["cid"], (r["cid"], r["code"], r["name"], r["board_type"]))

with open(DST, "w", encoding="utf-8", newline="") as f:
    w = csv.writer(f)
    w.writerow(["cid", "platecode", "name", "board_type"])
    for cid in sorted(seen):
        w.writerow(seen[cid])

print("wrote", len(seen))
PY
```

Expected: `wrote 480`

实测拆解（2026-09-11 验证）：输入 797 行 → 过滤 317 行 → 写入 480 条 distinct cid（376 concept + 104 industry identity）。被过滤的是：192 行 cid 为空、118 行 concept 的 cid 存的是 zzshare code（710xxx/803xxx）、以及少量空 code 行；另有 7 个 cid 在 383 个 genuine concept 行中重复出现，按 cid 折叠后为 376。cid 前缀全部落在 3xxxxx / 881xxx。

- [ ] **Step 2: 写失败测试**

Create `tests/test_ths_board_id_map_csv_seed.py`:

```python
"""Tests for the ths_board_id_map CSV seed path."""

from __future__ import annotations

import csv
from pathlib import Path

import pytest

from stock_data.data_provider.persistence import board as board_mod
from stock_data.data_provider.persistence import board_csv
from stock_data.data_provider.persistence import db as db_mod

REPO_CSV = (
    Path(__file__).resolve().parents[1]
    / "stock_data"
    / "stock_data_backup"
    / "ths_board_id_map.csv"
)


@pytest.fixture
def fresh_db(tmp_path, monkeypatch):
    monkeypatch.setattr(db_mod, "_db_path", None)
    monkeypatch.setattr(db_mod, "_conn", None)
    board_mod._schema_initialized_paths = set()
    monkeypatch.setenv("STOCK_CACHE_DB_PATH", str(tmp_path / "test.db"))
    board_mod.init_schema()
    yield


def _write_csv(path: Path, rows: list[tuple[str, str, str, str]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["cid", "platecode", "name", "board_type"])
        w.writerows(rows)


class TestCommittedArtifact:
    """Guards the repo-committed CSV itself, not just the loader."""

    def test_file_exists_and_has_required_columns(self):
        assert REPO_CSV.exists()
        with REPO_CSV.open(encoding="utf-8-sig") as f:
            header = next(csv.reader(f))
        assert set(header) >= {"cid", "platecode", "name", "board_type"}

    def test_no_zzshare_cid_leaked_in(self):
        with REPO_CSV.open(encoding="utf-8-sig") as f:
            bad = [
                r["cid"]
                for r in csv.DictReader(f)
                if not (r["cid"][:1] == "3" or r["cid"].startswith("881"))
            ]
        assert bad == [], f"non-THS cid rows leaked into the seed: {bad[:5]}"

    def test_contains_live_verified_pair(self):
        """Probed 2026-09-11: /gn/ gnSection entry 358 + /gn/detail/code/309121/."""
        with REPO_CSV.open(encoding="utf-8-sig") as f:
            m = {r["cid"]: r["platecode"] for r in csv.DictReader(f)}
        assert m.get("309121") == "886071"
        assert m.get("300188") == "885333"


class TestSeedLoader:
    def test_seeds_mappings(self, fresh_db, tmp_path):
        p = tmp_path / "m.csv"
        _write_csv(p, [("309121", "886071", "AI PC", "concept")])
        assert board_csv.seed_ths_board_id_map_from_csv(p) == 1
        assert board_mod.resolve_ths_platecode("309121") == "886071"

    def test_skips_zzshare_cid_rows(self, fresh_db, tmp_path):
        p = tmp_path / "m.csv"
        _write_csv(
            p,
            [
                ("710002", "710002", "DeFi", "concept"),
                ("309121", "886071", "AI PC", "concept"),
            ],
        )
        assert board_csv.seed_ths_board_id_map_from_csv(p) == 1
        assert board_mod.resolve_ths_platecode("710002") is None

    def test_missing_file_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            board_csv.seed_ths_board_id_map_from_csv(tmp_path / "nope.csv")

    def test_missing_column_raises(self, fresh_db, tmp_path):
        p = tmp_path / "bad.csv"
        p.write_text("cid,name\n309121,AI PC\n", encoding="utf-8")
        with pytest.raises(ValueError, match="missing required columns"):
            board_csv.seed_ths_board_id_map_from_csv(p)


class TestSeedAllOrdering:
    def test_id_map_seeded_before_board_csv(self, fresh_db, tmp_path, monkeypatch):
        """The map must be loaded first — sidebar resolution depends on it."""
        calls: list[str] = []
        monkeypatch.setattr(
            board_csv,
            "seed_ths_board_id_map_from_csv",
            lambda p: calls.append("id_map") or 1,
            raising=True,
        )
        monkeypatch.setattr(
            board_csv,
            "seed_stock_board_from_csv",
            lambda source, p: calls.append(f"board:{source}") or 1,
            raising=True,
        )
        monkeypatch.setattr(
            board_csv, "seed_membership_from_csv", lambda p: calls.append("membership") or 1
        )
        for name in (
            "ths_board_id_map.csv",
            "stock_board_ths.csv",
            "stock_board_eastmoney.csv",
            "stock_board_membership_ths.csv",
        ):
            (tmp_path / name).write_text("x", encoding="utf-8")

        results = board_csv.seed_all_from_backup_dir(tmp_path)

        assert calls[0] == "id_map", f"id_map must be first, got {calls}"
        assert results["ths_board_id_map"] == 1

    def test_missing_id_map_is_non_fatal(self, fresh_db, tmp_path, caplog):
        results = board_csv.seed_all_from_backup_dir(tmp_path)
        assert "ths_board_id_map" not in results
```

- [ ] **Step 3: 运行确认失败**

Run: `python -m pytest tests/test_ths_board_id_map_csv_seed.py -v`
Expected: FAIL — `AttributeError: module ... board_csv has no attribute 'seed_ths_board_id_map_from_csv'`

- [ ] **Step 4: 加 loader**

在 `board_csv.py` 的 `_MEMBERSHIP_COLS` 之后加常量：

```python
_THS_BOARD_ID_MAP_COLS = {"cid", "platecode"}
```

并在 `seed_membership_from_csv` 之后追加：

```python
def seed_ths_board_id_map_from_csv(csv_path: Path) -> int:
    """Seed ``ths_board_id_map`` from a ``cid,platecode,name,board_type`` CSV.

    Non-THS cid rows are skipped by ``board.upsert_ths_board_id_map``
    (spec §3.1: the legacy ``stock_board_ths.csv`` carries 118 concept
    rows whose ``cid`` column holds a zzshare code).

    Raises:
        FileNotFoundError: ``csv_path`` doesn't exist.
        ValueError: required columns missing.
    """
    if not csv_path.exists():
        raise FileNotFoundError(csv_path)
    board_mod.init_schema()
    _validate_csv_columns(csv_path, _THS_BOARD_ID_MAP_COLS)

    rows = [
        {
            "cid": r["cid"],
            "platecode": r["platecode"],
            "name": r.get("name") or "",
            "board_type": r.get("board_type") or "",
        }
        for r in _open_csv(csv_path)
    ]
    written = board_mod.upsert_ths_board_id_map(rows)
    logger.info(
        "[CSVSeed] %s: wrote %d cid→platecode mappings (of %d rows)",
        csv_path.name,
        written,
        len(rows),
    )
    return written
```

- [ ] **Step 5: 挂进 `seed_all_from_backup_dir`（必须最先）**

在 `seed_all_from_backup_dir` 的 `ths_board = backup_dir / "stock_board_ths.csv"` **之前**插入：

```python
    # Seeded FIRST: sidebar cid → platecode resolution depends on it.
    id_map_csv = backup_dir / "ths_board_id_map.csv"
    if id_map_csv.exists():
        try:
            results["ths_board_id_map"] = seed_ths_board_id_map_from_csv(id_map_csv)
        except _NON_FATAL_SEED_EXCEPTIONS as e:
            logger.error(
                "[CSVSeed] %s: %s: %s; skipping",
                id_map_csv.name,
                type(e).__name__,
                e,
            )
            failed_files.append(id_map_csv.name)
    else:
        logger.warning("[CSVSeed] %s not found; skipping id-map seed", id_map_csv)
        missing_files.append(id_map_csv.name)
```

同时更新 `seed_all_from_backup_dir` 的 docstring：Returns 段加 `'ths_board_id_map': N`，首行改为 "Seed ths_board_id_map + stock_board (THS+eastmoney) + stock_board_membership (THS)."

- [ ] **Step 6: 运行确认通过**

Run: `python -m pytest tests/test_ths_board_id_map_csv_seed.py -v`
Expected: PASS（8 passed）

- [ ] **Step 7: 提交**

```bash
git add stock_data/stock_data_backup/ths_board_id_map.csv \
        stock_data/data_provider/persistence/board_csv.py \
        tests/test_ths_board_id_map_csv_seed.py
git commit -m "feat(persistence): seed ths_board_id_map from repo CSV (487 mappings)"
```

---

### Task 3: 刷新工具 `tools/refresh_ths_board_id_map.py`

**Files:**
- Create: `tools/refresh_ths_board_id_map.py`
- Create: `tests/fixtures/ths_gn_index.html`
- Create: `tests/fixtures/ths_gn_detail_309121.html`
- Test: `tests/test_refresh_ths_board_id_map.py`

**Interfaces:**
- Consumes: `ThsFetcher._THS_CONCEPT_INDEX_URL`、`ThsFetcher._http_get_ths_board_index(url) -> str`、`ThsFetcher._parse_gn_section(html) -> list[dict]`、`ThsFetcher._parse_ths_gn_sidebar(html) -> list[dict]`、`ThsFetcher.extract_platecode_from_detail(html) -> str | None`（后者由 Task 4 提供 —— **本任务先按此签名调用，Task 4 落地该静态方法**）
- Produces: `read_map_csv(path) -> dict[str, dict]`、`write_map_csv(path, rows) -> None`、`snapshot_gn(fetcher) -> dict`、`resolve_unmapped(fetcher, snapshot, *, sleep_s, limit, log) -> tuple[dict, list[str]]`、`diff_maps(old, new) -> dict[str, list[str]]`

- [ ] **Step 1: 写 fixture**

Create `tests/fixtures/ths_gn_index.html`（`gnSection` 片段取自 2026-09-11 实测；`cate_items` 里放 3 个锚点，其中一个（309121）能对上，一个（309999）对不上）：

```html
<!DOCTYPE html>
<html><head><meta charset="gbk"><title>概念_同花顺</title></head>
<body>
<div class="cate_items">
  <a href="http://q.10jqka.com.cn/gn/detail/code/308614/" target="_blank">阿尔茨海默概念</a>
  <a href="http://q.10jqka.com.cn/gn/detail/code/309121/" target="_blank">AI PC</a>
  <a href="http://q.10jqka.com.cn/gn/detail/code/309999/" target="_blank">未收录概念</a>
</div>
<input type="hidden" id="baseUrl" value='gn/index'>
<input type="hidden" id="gnSection" value='{"358":{"platecode":"886071","platename":"AI PC","cid":"309121","199112":-0.84,"zjjlr":-26.33,"zfl":26},"361":{"platecode":"886074","platename":"AI语料","cid":"309126","199112":-1.41,"zjjlr":-13.26,"zfl":17},"355":{"platecode":"886056","platename":"阿尔茨海默概念","cid":"308614","199112":-1.17,"zjjlr":-23.13,"zfl":19}}'>
</body></html>
```

Create `tests/fixtures/ths_gn_detail_309121.html`（只含一个 885/886 候选）：

```html
<!DOCTYPE html>
<html><head><meta charset="gbk"><title>AI PC_同花顺</title></head>
<body>
<input type="hidden" id="clid" value="886071">
<div class="board_info">AI PC 概念板块</div>
</body></html>
```

- [ ] **Step 2: 写失败测试**

Create `tests/test_refresh_ths_board_id_map.py`:

```python
"""Tests for tools/refresh_ths_board_id_map.py (offline, fake fetcher)."""

from __future__ import annotations

import csv
from pathlib import Path

import pytest

from tools import refresh_ths_board_id_map as tool

FIXTURES = Path(__file__).parent / "fixtures"
GN_INDEX = (FIXTURES / "ths_gn_index.html").read_text(encoding="utf-8")
DETAIL_309121 = (FIXTURES / "ths_gn_detail_309121.html").read_text(encoding="utf-8")


class FakeFetcher:
    """Stands in for ThsFetcher: serves the gn index + detail pages."""

    def __init__(self, detail_pages: dict[str, str] | None = None):
        self.detail_pages = detail_pages or {"309999": "<html>待定</html>"}
        self.requested: list[str] = []

    def _http_get_ths_board_index(self, url: str) -> str:
        self.requested.append(url)
        if url.endswith("/gn/"):
            return GN_INDEX
        for cid, html in self.detail_pages.items():
            if f"/gn/detail/code/{cid}/" in url:
                return html
        raise AssertionError(f"unexpected url {url}")


class TestDiffMaps:
    def test_reports_added_changed_removed(self):
        old = {"300001": "885001", "300002": "885002", "300003": "885003"}
        new = {"300001": "885001", "300002": "885999", "300004": "885004"}
        d = tool.diff_maps(old, new)
        assert d["added"] == ["300004"]
        assert d["changed"] == ["300002"]
        assert d["removed"] == ["300003"]

    def test_identical_maps_produce_empty_diff(self):
        m = {"300001": "885001"}
        d = tool.diff_maps(m, m)
        assert d == {"added": [], "changed": [], "removed": []}


class TestSnapshotGn:
    def test_extracts_pairs_and_sidebar_cids(self):
        snap = tool.snapshot_gn(FakeFetcher())
        assert snap["mapped"]["309121"] == "886071"
        assert snap["mapped"]["308614"] == "886056"
        assert set(snap["sidebar_cids"]) == {"308614", "309121", "309999"}
        assert snap["names"]["309999"] == "未收录概念"


class TestResolveUnmapped:
    def test_resolves_via_detail_page(self):
        f = FakeFetcher({"309999": DETAIL_309121.replace("886071", "886123")})
        snap = tool.snapshot_gn(f)
        added, failed = tool.resolve_unmapped(f, snap, sleep_s=0.0, limit=None, log=lambda *_: None)
        assert added["309999"] == "886123"
        assert failed == []

    def test_unparsable_detail_page_is_reported_not_guessed(self):
        f = FakeFetcher({"309999": "<html>没有代码</html>"})
        snap = tool.snapshot_gn(f)
        added, failed = tool.resolve_unmapped(f, snap, sleep_s=0.0, limit=None, log=lambda *_: None)
        assert added == {}
        assert failed == ["309999"]

    def test_limit_caps_detail_requests(self):
        f = FakeFetcher({"309999": DETAIL_309121.replace("886071", "886123")})
        snap = tool.snapshot_gn(f)
        tool.resolve_unmapped(f, snap, sleep_s=0.0, limit=0, log=lambda *_: None)
        assert f.requested == [tool.ThsFetcher._THS_CONCEPT_INDEX_URL]


class TestCsvRoundtrip:
    def test_write_then_read(self, tmp_path):
        p = tmp_path / "m.csv"
        rows = [
            {"cid": "309121", "platecode": "886071", "name": "AI PC", "board_type": "concept"},
            {"cid": "881121", "platecode": "881121", "name": "半导体", "board_type": "industry"},
        ]
        tool.write_map_csv(p, rows)
        back = tool.read_map_csv(p)
        assert back["309121"]["platecode"] == "886071"
        assert back["881121"]["name"] == "半导体"

    def test_read_missing_file_returns_empty(self, tmp_path):
        assert tool.read_map_csv(tmp_path / "nope.csv") == {}

    def test_written_csv_has_stable_column_order(self, tmp_path):
        p = tmp_path / "m.csv"
        tool.write_map_csv(
            p, [{"cid": "309121", "platecode": "886071", "name": "AI PC", "board_type": "concept"}]
        )
        with p.open(encoding="utf-8") as f:
            assert next(csv.reader(f)) == ["cid", "platecode", "name", "board_type"]


class TestMainDryRun:
    def test_dry_run_writes_nothing(self, tmp_path, monkeypatch):
        target = tmp_path / "m.csv"
        tool.write_map_csv(
            target, [{"cid": "300001", "platecode": "885001", "name": "旧", "board_type": "concept"}]
        )
        before = target.read_text(encoding="utf-8")

        monkeypatch.setattr(tool, "ThsFetcher", lambda: FakeFetcher())
        rc = tool.main(["--out", str(target), "--dry-run", "--sleep", "0"])

        assert rc == 0
        assert target.read_text(encoding="utf-8") == before

    def test_apply_merges_live_over_base(self, tmp_path, monkeypatch):
        target = tmp_path / "m.csv"
        tool.write_map_csv(
            target, [{"cid": "309121", "platecode": "885000", "name": "AI PC", "board_type": "concept"}]
        )

        monkeypatch.setattr(tool, "ThsFetcher", lambda: FakeFetcher())
        rc = tool.main(["--out", str(target), "--apply", "--sleep", "0", "--no-detail"])

        assert rc == 0
        assert tool.read_map_csv(target)["309121"]["platecode"] == "886071"
```

- [ ] **Step 3: 运行确认失败**

Run: `python -m pytest tests/test_refresh_ths_board_id_map.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'tools.refresh_ths_board_id_map'`

- [ ] **Step 4: 实现工具**

Create `tools/refresh_ths_board_id_map.py`:

```python
"""Refresh ``stock_data/stock_data_backup/ths_board_id_map.csv``.

The map answers one question: given a THS board cid, what is its public
platecode? THS exposes the pair in two places, both THS-native:

1. ``GET /gn/`` → ``<input id="gnSection">`` carries ``platecode`` +
   ``cid`` together, but only for the day's "热门" subset (~292 of ~490).
2. ``GET /gn/detail/code/{cid}/`` → the detail page contains exactly one
   885/886 code (verified live 2026-09-11: cid 309121 → 886071).

This tool sweeps (1), then fills the remainder from (2), merges the result
over the CSV's existing contents, and reports a diff (added / changed /
removed). Live observations win over the file — the CSV is a snapshot,
never authoritative (spec §3.2).

Usage:
    python -m tools.refresh_ths_board_id_map --dry-run      # report only
    python -m tools.refresh_ths_board_id_map --apply        # write the CSV
    python -m tools.refresh_ths_board_id_map --apply --no-detail   # skip per-board fetches
"""

from __future__ import annotations

import argparse
import csv
import random
import sys
import time
from pathlib import Path

from stock_data.data_provider.fetchers.ths_fetcher import ThsFetcher

DEFAULT_OUT = (
    Path(__file__).resolve().parents[1]
    / "stock_data"
    / "stock_data_backup"
    / "ths_board_id_map.csv"
)
CSV_FIELDS = ("cid", "platecode", "name", "board_type")


def read_map_csv(path: Path) -> dict[str, dict]:
    """Read a mapping CSV into ``{cid: {platecode, name, board_type}}``.

    Missing file → ``{}`` (first run bootstraps from live data alone).
    """
    if not path.exists():
        return {}
    with path.open(encoding="utf-8-sig", newline="") as f:
        return {
            r["cid"]: {
                "cid": r["cid"],
                "platecode": r["platecode"],
                "name": r.get("name") or "",
                "board_type": r.get("board_type") or "",
            }
            for r in csv.DictReader(f)
            if r.get("cid") and r.get("platecode")
        }


def write_map_csv(path: Path, rows: list[dict]) -> None:
    """Write mappings sorted by cid, with a stable column order."""
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(CSV_FIELDS), extrasaction="ignore")
        w.writeheader()
        for r in sorted(rows, key=lambda r: r["cid"]):
            w.writerow(r)


def snapshot_gn(fetcher) -> dict:
    """Sweep ``GET /gn/`` once.

    Returns ``{"mapped": {cid: platecode}, "names": {cid: name},
    "sidebar_cids": [...]}``. ``mapped`` comes from gnSection (cid and
    platecode live in the same JSON object); ``sidebar_cids`` is the full
    sidebar, which includes boards gnSection misses.
    """
    html = fetcher._http_get_ths_board_index(ThsFetcher._THS_CONCEPT_INDEX_URL)
    mapped: dict[str, str] = {}
    names: dict[str, str] = {}
    for row in ThsFetcher._parse_gn_section(html):
        cid = row.get("code")
        platecode = row.get("platecode")
        if cid and platecode:
            mapped[cid] = platecode
            names[cid] = row.get("name") or ""
    sidebar = ThsFetcher._parse_ths_gn_sidebar(html)
    sidebar_cids = [r["code"] for r in sidebar if r.get("code")]
    for r in sidebar:
        names.setdefault(r["code"], r.get("name") or "")
    return {"mapped": mapped, "names": names, "sidebar_cids": sidebar_cids}


def resolve_unmapped(
    fetcher,
    snapshot: dict,
    *,
    sleep_s: float,
    limit: int | None,
    log,
) -> tuple[dict, list[str]]:
    """Fill platecodes for sidebar cids missing from ``snapshot['mapped']``.

    Fetches ``/gn/detail/code/{cid}/`` one board at a time with a jittered
    sleep. Returns ``(added, failed_cids)`` — a detail page that does not
    yield exactly one candidate is reported as failed, never guessed.
    """
    mapped = dict(snapshot["mapped"])
    names = snapshot["names"]
    added: dict[str, str] = {}
    failed: list[str] = []
    todo = [c for c in snapshot["sidebar_cids"] if c not in mapped]
    if limit is not None:
        todo = todo[:limit]
    for i, cid in enumerate(todo):
        url = f"https://q.10jqka.com.cn/gn/detail/code/{cid}/"
        try:
            platecode = ThsFetcher.extract_platecode_from_detail(
                fetcher._http_get_ths_board_index(url)
            )
        except Exception as e:  # network / non-2xx — report, keep going
            log(f"  {cid}: fetch failed ({type(e).__name__}: {e})")
            failed.append(cid)
            continue
        if platecode:
            added[cid] = platecode
        else:
            failed.append(cid)
        if sleep_s and i + 1 < len(todo):
            time.sleep(random.uniform(sleep_s, sleep_s * 2))
    for cid, platecode in added.items():
        names.setdefault(cid, "")
    return added, failed


def diff_maps(old: dict[str, str], new: dict[str, str]) -> dict[str, list[str]]:
    """Compare two ``{cid: platecode}`` maps.

    ``changed`` is the renumbering detector — the only place a THS
    platecode reassignment becomes visible.
    """
    return {
        "added": sorted(set(new) - set(old)),
        "changed": sorted(c for c in set(old) & set(new) if old[c] != new[c]),
        "removed": sorted(set(old) - set(new)),
    }


def build_argparser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--out", type=Path, default=DEFAULT_OUT)
    p.add_argument("--apply", action="store_true", help="write the CSV (default: report only)")
    p.add_argument("--dry-run", action="store_true", help="explicit report-only mode")
    p.add_argument("--no-detail", action="store_true", help="skip per-board detail-page fetches")
    p.add_argument("--limit", type=int, default=None, help="cap detail fetches (debug)")
    p.add_argument("--sleep", type=float, default=1.5, help="min jitter seconds between detail fetches")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_argparser().parse_args(argv)
    log = print

    base = read_map_csv(args.out)
    log(f"base: {len(base)} mappings from {args.out}")

    fetcher = ThsFetcher()
    snap = snapshot_gn(fetcher)
    log(f"gnSection: {len(snap['mapped'])} pairs; sidebar: {len(snap['sidebar_cids'])} cids")

    added: dict[str, str] = {}
    failed: list[str] = []
    if not args.no_detail:
        added, failed = resolve_unmapped(
            fetcher, snap, sleep_s=args.sleep, limit=args.limit, log=log
        )
        log(f"detail pages: resolved {len(added)}, failed {len(failed)}")
        if failed:
            log(f"  unresolved (rerun later): {failed[:20]}")

    live = {**snap["mapped"], **added}
    merged: dict[str, dict] = dict(base)
    for cid, platecode in live.items():
        prev = merged.get(cid)
        merged[cid] = {
            "cid": cid,
            "platecode": platecode,  # live wins over the file
            "name": snap["names"].get(cid) or (prev or {}).get("name") or "",
            "board_type": (prev or {}).get("board_type") or "concept",
        }

    d = diff_maps(
        {c: r["platecode"] for c, r in base.items()},
        {c: r["platecode"] for c, r in merged.items()},
    )
    log(f"diff: +{len(d['added'])} added, ~{len(d['changed'])} changed, -{len(d['removed'])} removed")
    for label in ("changed", "removed"):
        for cid in d[label][:10]:
            log(f"  {label}: {cid} {base.get(cid, {}).get('platecode')} → {merged.get(cid, {}).get('platecode')}")

    if not args.apply:
        log("report-only (pass --apply to write)")
        return 0
    write_map_csv(args.out, list(merged.values()))
    log(f"wrote {len(merged)} mappings to {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 5: 运行确认通过**

Run: `python -m pytest tests/test_refresh_ths_board_id_map.py -v`
Expected: 在 `extract_platecode_from_detail` 落地前，`TestResolveUnmapped` 两个用例 FAIL（`AttributeError`），其余 PASS。**先跑 Task 4 的 Step 1-4 再回到本步**，然后全部 PASS（11 passed）。

- [ ] **Step 6: 提交**

```bash
git add tools/refresh_ths_board_id_map.py tests/test_refresh_ths_board_id_map.py \
        tests/fixtures/ths_gn_index.html tests/fixtures/ths_gn_detail_309121.html
git commit -m "feat(tools): add ths_board_id_map refresher (gn sweep + detail pages + diff)"
```

---

### Task 4: `ThsFetcher` 侧栏 platecode 解析

**Files:**
- Modify: `stock_data/data_provider/fetchers/ths_fetcher.py`（新增 `extract_platecode_from_detail`；改写 `_merge_concept_sources`，约 line 1992-2016；更新 `get_all_boards` docstring 的 1784-1790 段）
- Test: `tests/test_ths_fetcher_sidebar_platecode.py`

**Interfaces:**
- Consumes: `persistence.board.resolve_ths_platecode(ths_cid) -> str | None`（Task 1）
- Produces: `ThsFetcher.extract_platecode_from_detail(html: str) -> str | None`（Task 3 Step 5 依赖）

- [ ] **Step 1: 写失败测试**

Create `tests/test_ths_fetcher_sidebar_platecode.py`:

```python
"""Sidebar-only concept rows must get their platecode from ths_board_id_map."""

from __future__ import annotations

from pathlib import Path

import pytest

from stock_data.data_provider.fetchers.ths_fetcher import ThsFetcher
from stock_data.data_provider.persistence import board as board_mod
from stock_data.data_provider.persistence import db as db_mod

FIXTURES = Path(__file__).parent / "fixtures"
DETAIL_309121 = (FIXTURES / "ths_gn_detail_309121.html").read_text(encoding="utf-8")


@pytest.fixture
def fresh_db(tmp_path, monkeypatch):
    monkeypatch.setattr(db_mod, "_db_path", None)
    monkeypatch.setattr(db_mod, "_conn", None)
    board_mod._schema_initialized_paths = set()
    monkeypatch.setenv("STOCK_CACHE_DB_PATH", str(tmp_path / "test.db"))
    board_mod.init_schema()
    yield


class TestExtractPlatecodeFromDetail:
    def test_single_candidate_returned(self):
        assert ThsFetcher.extract_platecode_from_detail(DETAIL_309121) == "886071"

    def test_no_candidate_returns_none(self):
        assert ThsFetcher.extract_platecode_from_detail("<html>没有代码</html>") is None

    def test_ambiguous_page_returns_none(self):
        """Two distinct candidates must not be guessed."""
        html = "<a>885001</a><a>886002</a>"
        assert ThsFetcher.extract_platecode_from_detail(html) is None

    def test_repeated_same_candidate_is_not_ambiguous(self):
        assert ThsFetcher.extract_platecode_from_detail(html="886071 ... 886071") == "886071"

    def test_empty_html_returns_none(self):
        assert ThsFetcher.extract_platecode_from_detail("") is None


class TestMergeConceptSources:
    def test_sidebar_only_row_resolved_from_map(self, fresh_db):
        board_mod.upsert_ths_board_id_map(
            [{"cid": "308614", "platecode": "886056", "name": "阿尔茨海默概念", "board_type": "concept"}]
        )
        gn = [{"code": "309121", "name": "AI PC", "platecode": "886071", "source": "ths"}]
        sidebar = [
            {"code": "309121", "name": "AI PC", "source": "ths"},
            {"code": "308614", "name": "阿尔茨海默概念", "source": "ths"},
        ]
        merged = ThsFetcher._merge_concept_sources(gn, sidebar)
        by_cid = {r["code"]: r for r in merged}
        assert by_cid["309121"]["platecode"] == "886071"  # gnSection wins
        assert by_cid["308614"]["platecode"] == "886056"  # resolved from the map

    def test_unmapped_sidebar_row_keeps_none(self, fresh_db):
        """No map entry and no name-match fallback — None, never a guess."""
        gn: list[dict] = []
        sidebar = [{"code": "309999", "name": "未收录概念", "source": "ths"}]
        merged = ThsFetcher._merge_concept_sources(gn, sidebar)
        assert merged[0]["platecode"] is None

    def test_gn_section_platecode_not_overwritten_by_map(self, fresh_db):
        board_mod.upsert_ths_board_id_map(
            [{"cid": "309121", "platecode": "886999", "name": "AI PC", "board_type": "concept"}]
        )
        gn = [{"code": "309121", "name": "AI PC", "platecode": "886071", "source": "ths"}]
        merged = ThsFetcher._merge_concept_sources(gn, [])
        assert merged[0]["platecode"] == "886071"

    def test_name_backfilled_from_sidebar(self, fresh_db):
        gn = [{"code": "309121", "name": "", "platecode": "886071", "source": "ths"}]
        sidebar = [{"code": "309121", "name": "AI PC", "source": "ths"}]
        merged = ThsFetcher._merge_concept_sources(gn, sidebar)
        assert merged[0]["name"] == "AI PC"

    def test_duplicate_cids_deduped(self, fresh_db):
        gn = [
            {"code": "309121", "name": "AI PC", "platecode": "886071", "source": "ths"},
            {"code": "309121", "name": "AI PC", "platecode": "886071", "source": "ths"},
        ]
        assert len(ThsFetcher._merge_concept_sources(gn, [])) == 1
```

- [ ] **Step 2: 运行确认失败**

Run: `python -m pytest tests/test_ths_fetcher_sidebar_platecode.py -v`
Expected: FAIL — `AttributeError: type object 'ThsFetcher' has no attribute 'extract_platecode_from_detail'`

- [ ] **Step 3: 加 `extract_platecode_from_detail`**

在 `ths_fetcher.py` 的 `_parse_ths_gn_sidebar` 之前加类常量（与 `_THS_CHANGECODE_RE` 同区）：

```python
    # A concept board's detail page carries exactly one 885/886 code — the
    # platecode. Verified live 2026-09-11: /gn/detail/code/309121/ → 886071.
    _THS_DETAIL_PLATECODE_RE = re.compile(r"\b(88[56]\d{3})\b")
```

并在 `_parse_ths_gn_sidebar` 之后加：

```python
    @staticmethod
    def extract_platecode_from_detail(html: str) -> str | None:
        """Return the platecode of a ``/gn/detail/code/{cid}/`` page.

        Returns ``None`` when the page carries zero or more than one
        distinct candidate — an ambiguous page must never be guessed at.
        The page is the last-resort resolver used by
        ``tools/refresh_ths_board_id_map.py``; the runtime board-list path
        only queries ``ths_board_id_map`` (no per-refresh fetches).
        """
        found = sorted(set(ThsFetcher._THS_DETAIL_PLATECODE_RE.findall(html or "")))
        return found[0] if len(found) == 1 else None
```

- [ ] **Step 4: 改写 `_merge_concept_sources`**

把整个函数体替换为：

```python
    @staticmethod
    def _merge_concept_sources(gn_section: list[dict], sidebar: list[dict]) -> list[dict]:
        """Merge gnSection (primary) + sidebar, resolving sidebar platecodes.

        gnSection rows carry ``platecode`` + real-time fields and always
        win. Sidebar-only rows carry only a cid; their platecode comes from
        ``ths_board_id_map`` — the single cid → platecode query point,
        seeded from the repo CSV and refreshed live by
        ``tools/refresh_ths_board_id_map.py``.

        Deliberately NOT resolved by matching board names against another
        source: that is what conflated THS's and zzshare's code spaces
        (docs/superpowers/specs/2026-09-11-board-source-split-design.md §1.2).
        A row that stays unresolved keeps ``platecode=None`` — callers must
        read that as "not known yet", never as another source's board.
        """
        from ..persistence.board import resolve_ths_platecode

        by_cid: dict[str, dict] = {}
        for r in gn_section:
            by_cid[r["code"]] = r
        for r in sidebar:
            cid = r["code"]
            if cid in by_cid:
                # gnSection should already carry the name; a malformed
                # upstream that left it empty benefits from the backfill.
                if not by_cid[cid].get("name") and r.get("name"):
                    by_cid[cid]["name"] = r["name"]
                continue
            by_cid[cid] = {**r, "platecode": resolve_ths_platecode(cid)}
        return list(by_cid.values())
```

- [ ] **Step 5: 更新 `get_all_boards` 的过时 docstring**

把 1784-1790 那段（"``platecode`` may be ``None`` for concept rows ... out of scope"）替换为：

```python
        - ``platecode`` is resolved for sidebar-only concept rows via
          ``ths_board_id_map`` (seeded from
          ``stock_data/stock_data_backup/ths_board_id_map.csv`` and
          refreshed by ``tools/refresh_ths_board_id_map.py``). It stays
          ``None`` only for boards THS has not yet exposed a platecode
          for — measured 3 of 141 on 2026-09-11.
```

- [ ] **Step 6: 运行确认通过**

Run: `python -m pytest tests/test_ths_fetcher_sidebar_platecode.py -v`
Expected: PASS（10 passed）

- [ ] **Step 7: 回归既有 THS 板块测试**

Run: `python -m pytest tests/test_ths_fetcher_get_all_boards_live.py tests/test_boards.py tests/test_persistence_board_merge.py -v`
Expected: 全部 PASS（`test_persistence_board_merge.py` 的 merge 用例与 `_merge_concept_sources` 无关，不受影响）

- [ ] **Step 8: 提交**

```bash
git add stock_data/data_provider/fetchers/ths_fetcher.py \
        tests/test_ths_fetcher_sidebar_platecode.py
git commit -m "feat(ths): resolve sidebar-only concept platecodes from ths_board_id_map"
```

---

### Task 5: 端到端验证 + 文档

**Files:**
- Modify: `docs/board-source-semantics.md`
- Test: `tests/test_ths_concept_platecode_coverage_live.py`（`live_network` 标记）

**Interfaces:**
- Consumes: Task 4 的 `ThsFetcher.get_all_boards(board_type="concept")` 输出（`platecode` 已解析）
- Produces: 无（终态验证）

- [ ] **Step 1: 写覆盖率测试（live）**

Create `tests/test_ths_concept_platecode_coverage_live.py`:

```python
"""Live: after the id-map seed, almost no concept row should lack a platecode.

Before this change, ~88 of ~383 rows per snapshot had ``platecode=None``
(the sidebar-only set) — see the old note at ths_fetcher.py:1784-1790.
Marked live_network; the suite xfails network-class failures automatically.
"""

from __future__ import annotations

import pytest

from stock_data.data_provider.fetchers.ths_fetcher import ThsFetcher

pytestmark = pytest.mark.live_network


def test_concept_platecode_coverage_is_high():
    rows = ThsFetcher().get_all_boards(board_type="concept")
    assert rows, "upstream returned no concept boards"
    unresolved = [r for r in rows if not r.get("platecode")]
    # Measured 3/141 unresolved on 2026-09-11. Allow headroom for boards
    # created after the seed snapshot.
    assert len(unresolved) <= max(5, len(rows) // 50), (
        f"{len(unresolved)}/{len(rows)} concept rows lack a platecode: "
        f"{[r.get('name') for r in unresolved[:10]]}"
    )
```

- [ ] **Step 2: 运行覆盖率测试**

Run: `python -m pytest tests/test_ths_concept_platecode_coverage_live.py -v -m live_network`
Expected: PASS（或网络类失败自动 xfail —— 见 `tests/_network_guard.py`）。若失败且原因是"未解析数远超阈值"，运行 `python -m tools.refresh_ths_board_id_map --apply` 刷新 CSV 后重跑。

- [ ] **Step 3: 验证 seed 通道真的会装载映射**

Run:

```bash
python - <<'PY'
import os, tempfile, pathlib
os.environ["STOCK_CACHE_DB_PATH"] = str(pathlib.Path(tempfile.mkdtemp()) / "t.db")
from stock_data.data_provider import persistence
from stock_data.data_provider.persistence import board as b
persistence.reset_all()
res = persistence.seed_all_from_backup_dir(
    pathlib.Path("stock_data/stock_data_backup")
)
print("seed results:", res)
print("map size:", len(b.get_ths_board_id_map_rows()))
print("309121 ->", b.resolve_ths_platecode("309121"))
print("710002 ->", b.resolve_ths_platecode("710002"))
PY
```

Expected:
```
seed results: {'ths_board_id_map': 480, 'stock_board_ths': 775, 'stock_board_membership_ths': 115081, 'stock_board_eastmoney': 992}
map size: 480
309121 -> 886071
710002 -> None
```

（`stock_board_ths` 为 775 而非 797：17 组重复 code 在 `UNIQUE(code, source)` 上折叠 —— 既有行为，非本次引入。）

- [ ] **Step 4: 文档**

在 `docs/board-source-semantics.md` 末尾追加一节：

```markdown
## THS cid ↔ platecode (2026-09-11)

THS gives every concept board two identifiers: a public `platecode`
(885xxx / 886xxx) and an internal `cid` (3xxxxx). They are NOT
interchangeable — the gn AJAX constituent endpoint takes the cid, the F10
page and board K-line take the platecode. Industry boards use one value
(881xxx) for both.

`ths_board_id_map` (SQLite) is the single cid → platecode lookup. It is
seeded at startup from `stock_data/stock_data_backup/ths_board_id_map.csv`
and refreshed by `python -m tools.refresh_ths_board_id_map --apply`, which
sweeps THS's own `GET /gn/` (gnSection pair) and falls back to one
`/gn/detail/code/{cid}/` request per unresolved board.

**The CSV is a snapshot, never authoritative.** It only contains pairs THS
has shown us at some point; live observations must always overwrite it, or
a THS renumbering would go unnoticed until a fetch 404s. The refresh tool
prints an added / changed / removed diff for exactly that reason.
```

- [ ] **Step 5: 全量回归**

Run: `python -m pytest tests/test_persistence_ths_board_id_map.py tests/test_ths_board_id_map_csv_seed.py tests/test_refresh_ths_board_id_map.py tests/test_ths_fetcher_sidebar_platecode.py tests/test_persistence_board.py tests/test_board_csv_seed.py tests/test_boards.py -v`
Expected: 全部 PASS

- [ ] **Step 6: 提交并合并**

```bash
git add docs/board-source-semantics.md tests/test_ths_concept_platecode_coverage_live.py
git commit -m "docs+test: document ths_board_id_map and pin concept platecode coverage"
git checkout master && git merge --no-ff feat/ths-board-id-map
```

---

## Self-Review

**Spec coverage（本计划覆盖的部分）**

| spec 节 | 覆盖于 |
|---|---|
| §3.1 探测结论（gnSection 同响应可解 / 详情页兜底） | Task 3 fixture + Task 4 实现 |
| §3.2 `ths_board_id_map` 表 + live 优先 | Task 1（表 + 后写覆盖）、Task 3（merge 顺序）、Task 5 Step 3（seed 验证） |
| §3.3 生成器 + diff | Task 3 |
| §10.1 CSV 拆三份中的 `ths_board_id_map.csv` | Task 2 |
| §10.3 seed 顺序在 board 之前 | Task 2 Step 5 + `TestSeedAllOrdering` |
| §11 新增"id 契约不变量测试"（映射侧） | Task 1 `TestIsThsCid` / `test_zzshare_cid_rejected_on_write` |
| §6 `get_all_boards` 侧栏解析 | Task 4 |
| §6 删除 zzshare 注释、`_merge_concept_sources` 中间态 | **Plan 2**（不在本计划；本计划只替换 `_merge_concept_sources` 的解析来源） |
| §4 id 契约硬规则、§5 命名契约第 1+2 层 | **Plan 2** |
| §7 删 merge/fallback、cache key 带 source | **Plan 2** |
| §8 include_quote 两层 | **Plan 2** |
| §9 路由放开 zzshare | **Plan 2** |
| §10.2/10.4-10.7 membership relabel、重建流程 | **Plan 3** |
| §11 测试重写、§12 文档、§13 breaking | **Plan 2 / Plan 3** |

**无 placeholder**：所有步骤含可直接执行的代码或命令；Task 3 Step 5 显式说明与 Task 4 的先后依赖，不留 TBD。

**类型一致性**：`upsert_ths_board_id_map(rows, conn=None) -> int` / `resolve_ths_platecode(str) -> str | None` / `get_ths_board_id_map_rows() -> list[dict]` / `seed_ths_board_id_map_from_csv(Path) -> int` / `extract_platecode_from_detail(str) -> str | None` / `snapshot_gn(fetcher) -> dict` / `resolve_unmapped(fetcher, snapshot, *, sleep_s, limit, log) -> tuple[dict, list[str]]` / `diff_maps(old, new) -> dict[str, list[str]]` —— Task 3 与 Task 4 共用 `extract_platecode_from_detail` 的同一签名，Task 1 与 Task 2/3/4 共用同一组 CRUD 名字。

**已知偏差（有意，已在"范围与路线图"声明）**：spec §6 的运行时详情页解析改为工具期解析。
</content>
