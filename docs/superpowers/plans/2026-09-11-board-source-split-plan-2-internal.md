# board source 拆分 Plan 2 —— 内部 id/命名契约 + 删除跨源 merge Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 `ths` / `zzshare` 的跨源 merge 与兜底从持久层删除，并把 board 路径的内部行 key 统一为 `board_code` / `ths_cid` / `board_type`，使 id 契约由构造保证。

**Architecture:** 行 key 重命名是一次性原子改动（fetcher 输出 → 持久层读写 → 路由内部变量），公开 API 字段名（`BoardInfo.code` / `type`）**不变**，只在响应边界做一次显式映射。`get_board_list(source=X)` 直连 `manager.get_all_boards(source=X)`，无 merge 分支；缓存 key 全部带上 `source`；`update_cached_boards` 改为 `(board_type, source)` 快照替换。

**Tech Stack:** Python 3.13 / SQLite / FastAPI / pytest / ruff 0.15.12

## Global Constraints

- 本机无 `.venv/`，用系统 `python`（miniconda 3.13.9）。
- 测试命令 `python -m pytest <path> -v`；lint 用 `python -m ruff check .`。
- **回归基准**：本计划开工前 `python -m pytest tests/test_persistence_board.py tests/test_boards.py -q` = `40 passed`。每个 Task 结束时该命令必须仍全绿（数量会因删/改测试而变化，但不得有 fail/error）。
- **重命名硬规则**（spec §5.1）：board 路径禁止裸 `code`；`code` 只能作为公开 API 字段名出现在 `api/schemas.py` 与响应构造处。
- 本计划**不改**公开 API 参数面：`?source=` 的 Literal 仍是 `("ths","eastmoney","zhitu")`，`?source=zzshare` 仍 422。这是 Plan 3 的事。
- 本计划**不改**：`turnover_rate`/`turnover_pct`、`amplitude`/`amplitude_pct`、`pre_close`/`prev_close`、quote 对象的 `code`/`stock_code`（spec §5.3 明确排除）。
- `stock_board` / `stock_board_membership` 的 **SQL 列名不改**（`code` / `cid` / `board_type` 列保持原样）—— 本次只改内存中的行 dict key。迁移成本因此为零。
- 分支：`feat/board-source-split-internal`。

## 前置依赖

Plan 1（`docs/superpowers/plans/2026-09-11-board-id-map-plan.md`）必须先落地：本计划 Task 3 的 `_resolve_ths_cid_from_code` 收紧依赖 `ths_board_id_map` 已存在且有数据，否则侧栏板块会全部解析失败。

---

## 命名契约（本计划的核心映射表）

| 旧行 key | 新行 key | 适用行类型 |
|---|---|---|
| `code` | `board_code` | fetcher 板块行、`_read_boards_from_db` 行、membership entry |
| `platecode` | `board_code`（与 `code` 合并） | THS fetcher 板块行 |
| `code`（THS fetcher 里装的是 cid） | `ths_cid` | THS fetcher 板块行 |
| `cid` | `ths_cid` | `_read_boards_from_db` 行、`get_board_metadata` 输出 |
| `type` | `board_type` | 所有板块行 / membership entry |
| `code`（quote 对象） | **不改**（spec §5.3） | `UnifiedRealtimeQuote` |
| `stock_code` | **不改** | board-stocks / membership 行 |

**公开 API 字段名不变**：`BoardInfo.code` / `BoardInfo.type` / `StockBoardInfo.code` / `StockBoardInfo.type` / `BoardQuoteResponse.code`。响应构造处是唯一允许出现 `code=` / `type=` 的地方。

## 完整改动点清单（按文件）

重命名是 1:1 机械映射，因此下表即执行指令，不再逐行复制代码。

### `persistence/board.py`
| 行 | 现状 | 改为 |
|---|---|---|
| 742 | `code = b.get("code")`（`_get_all_board_types` 去重键） | `board_code = b.get("board_code")` |
| 801 | `return row["cid"] if row["cid"] is not None else row["code"] if row["code"] else None` | 见 Task 3（去掉 `code` 回退） |
| 1662 | `row["code"]: {"type": row["board_type"], "subtype": row["subtype"]}` | `row["code"]: {"board_type": ..., "subtype": ...}` |
| 1843 | `"code": r["board_code"]`（`_read_membership_entries` 输出） | `"board_code": r["board_code"]` |
| 1847 | `"type": (...)` | `"board_type": (...)` |
| 1908 | `e["type"] == type` | `e["board_type"] == type` |
| 2011/2013/2014 | `get_board_metadata` 输出的 `"type"` / `"code"` / `"cid"` | `"board_type"` / `"board_code"` / `"ths_cid"` |
| 2069 | `board_code in (b.get("code"), b.get("platecode"))` | `board_code == b.get("board_code")` |
| 2118/2120/2130 | `_read_boards_from_db` 输出的 `"code"` / `"type"` / `"cid"` + 别名 `"board_type"` | `"board_code"` / `"board_type"` / `"ths_cid"`；**删除 `"type"` 与 `"board_type"` 双返回** |
| 2227/2245 | `update_cached_boards` 的 `b.get("platecode") or b["code"]` / `b["code"] if ...` | `b["board_code"]` / `b["ths_cid"] if source == "ths" else None` |

### 删除（Task 2）
`fetch_boards_with_zzshare_backfill`（913-1003）、`fetch_board_stocks_with_zzshare_fallback`（1006-1252）、`_merge_ths_zzshare_by_name`（811-883）、`_normalize_zzshare_list_quote_units`（886-910）、`_resolve_ths_cid_from_platecode` 别名（808）。

### `persistence/backfill.py`
| 行 | 现状 | 改为 |
|---|---|---|
| 24-25 | import 两个被删函数 | 删除 import |
| 100-106 | 调 `fetch_boards_with_zzshare_backfill` | 改为按 type 直调 `manager.get_all_boards(source="ths", board_type=bt)`（Task 4） |
| 128 / 131 / 171 / 175 / 222-224 | `b.get("type")` / `b.get("code")` / `board.get("platecode")` | `board_type` / `board_code` / `board["board_code"]` |

### `api/routes/boards.py`
| 行 | 现状 | 改为 |
|---|---|---|
| 408 | `b.get(sort_by)` | 不变（`sort_by` 是 quote 字段名，不是 id） |
| 420-421 | `BoardInfo(code=b["code"], name=b["name"])` | `code=b["board_code"]`（**响应边界，保留 `code=`**） |
| 425 | `BoardInfo(type=b.get("type"))` | `type=b.get("board_type")` |
| 679-680 / 706 | `cached_metadata.get("type")` / `["type"]` | `.get("board_type")` / `["board_type"]` |
| 783 | `metadata.get("type")` | `.get("board_type")` |
| 932 | `e["source"] == "ths"` | 不变（`source` 是源标签，不是 id） |
| 966-970 | membership entry 的 `e["code"]` / `e.get("type")` | `e["board_code"]` / `e.get("board_type")` |
| 972-973 | `e["code"] in enrichment_by_code` / `enrichment_by_code[e["code"]]` | `e["board_code"]` |
| 983-986 | fetcher 行的 `r.get("code")` / `r.get("type")` | `r.get("board_code")` / `r.get("board_type")` |
| 1009-1013 | `e["code"]` / `e.get("type")` | `e["board_code"]` / `e.get("board_type")` |
| 402 / 593 | `{"error": str(e)}`（缺 `message`） | **顺手补齐为 `{"error": ..., "message": str(e)}`**，与 `ErrorResponse` 模型一致 |

### `api/routes/agent.py`
| 行 | 现状 | 改为 |
|---|---|---|
| 431 | `"code": e["code"]` | `"code": e["board_code"]`（响应边界） |
| 432-435 | `e.get("type")` | `e.get("board_type")` |
| 439 | `{(b["code"], b["name"]) for b in boards}` | `b["board_code"]` |
| 447 | `{"code": k, ...}` | 响应边界，键名不变；`k` 来自上面 |
| 1488 / 1502-1504 | `r.get("code") or ""` / `r.get("type")` | `board_code` / `board_type` |
| 2015-2016 | `b.get("type")` / `b.get("subtype")` | `b.get("board_type")` |
| 2381-2383 | `b.get("code","?")` / `b.get("type")` | `board_code` / `board_type` |

### `api/_helpers/stock_boards.py` / `api/_helpers/agent_stock_profile.py`
| 文件:行 | 现状 | 改为 |
|---|---|---|
| `stock_boards.py:107` | `code = entry.get("code")` | `board_code = entry.get("board_code")`（连同 110/113 的局部变量名） |
| `agent_stock_profile.py:186` | `{k: e.get(k) for k in ("code","name","type","subtype","source")}` | `("board_code","name","board_type","subtype","source")` |
| `agent_stock_profile.py:187` | `enrichment_by_code.get(e["code"], {})` | `e["board_code"]` |

### `data_provider/fetchers/`（4 个 fetcher 的板块行输出）
| 文件 | 现状 | 改为 |
|---|---|---|
| `ths_fetcher.py` `_parse_gn_section` / `_parse_ths_gn_sidebar` / `_merge_concept_sources` / `get_all_boards` | `{"code": cid, "platecode": platecode, "type": bt}` | `{"ths_cid": cid, "board_code": platecode, "board_type": bt}`；侧栏未解析时 `board_code=None` |
| `ths_fetcher.py` `get_stock_boards` | 输出 `code` / `type` | `board_code` / `board_type` |
| `zzshare_fetcher.py` `get_all_boards` | `board["code"]` / `board["type"]` | `board["board_code"]` / `board["board_type"]`；**`ths_cid` 恒为 None** |
| `eastmoney/_boards_mixin.py` `get_all_boards` / `get_stock_boards` | `code` / `type` | `board_code` / `board_type` |
| `zhitu_fetcher.py` `get_all_boards` / `get_stock_boards` | `code` / `type` | `board_code` / `board_type` |

> 注意 `get_all_boards` 的 `subtype` 过滤（`get_board_list:678-679`、`_get_all_board_types`）与 `_REALTIME_BOARD_FIELDS` 的 `setdefault` 循环不涉及 id，无需改。

---

### Task 1: 行 key 重命名 + 不变量测试

**Files:**
- Modify: 上表"完整改动点清单"里的全部文件
- Test: `tests/test_board_naming_contract.py`（Create）
- Test: 上表涉及 mock 行 dict 的既有测试（30+ 处，见 Task 5 清单）

**Interfaces:**
- Produces: 所有 board 路径的行 dict 使用 `board_code` / `ths_cid` / `board_type`；`BoardStockInfo` / `BoardInfo` 等公开模型字段名不变
- Consumes: 无

- [ ] **Step 1: 写不变量测试**

Create `tests/test_board_naming_contract.py`:

```python
"""Naming contract for the board path (spec §5.1).

Board row dicts must use `board_code` / `ths_cid` / `board_type`.
A bare `code` key is the bug this contract exists to prevent: the same key
meant `cid` in ThsFetcher and `platecode` in update_cached_boards, which is
how the two code spaces got conflated (spec §1.2).
"""

from __future__ import annotations

import pytest

from stock_data.data_provider.persistence import board as board_mod
from stock_data.data_provider.persistence import db as db_mod

FORBIDDEN_BARE_CODE = "code"


@pytest.fixture
def fresh_db(tmp_path, monkeypatch):
    monkeypatch.setattr(db_mod, "_db_path", None)
    monkeypatch.setattr(db_mod, "_conn", None)
    board_mod._schema_initialized_paths = set()
    monkeypatch.setenv("STOCK_CACHE_DB_PATH", str(tmp_path / "test.db"))
    board_mod.init_schema()
    yield


def _seed_board(board_code: str, ths_cid: str | None, board_type: str = "concept") -> None:
    conn = board_mod.get_connection()
    with conn:
        conn.execute(
            """INSERT OR REPLACE INTO stock_board
               (code, name, board_type, subtype, source, cid, updated_at)
               VALUES (?,?,?,?,?,?,CURRENT_TIMESTAMP)""",
            (board_code, "测试板块", board_type, "同花顺概念", "ths", ths_cid),
        )


class TestReadRowsUseCanonicalKeys:
    def test_read_boards_from_db_keys(self, fresh_db):
        _seed_board("885333", "300188")
        rows = board_mod._read_boards_from_db("concept", "ths")
        assert rows
        row = rows[0]
        assert row["board_code"] == "885333"
        assert row["ths_cid"] == "300188"
        assert row["board_type"] == "concept"
        assert FORBIDDEN_BARE_CODE not in row, "bare 'code' key must not exist"
        assert "type" not in row, "dual type/board_type return must be gone"
        assert "cid" not in row

    def test_get_board_metadata_keys(self, fresh_db):
        _seed_board("885333", "300188")
        md = board_mod.get_board_metadata("885333", "ths")
        assert md is not None
        assert md["board_code"] == "885333"
        assert md["ths_cid"] == "300188"
        assert md["board_type"] == "concept"
        assert FORBIDDEN_BARE_CODE not in md and "type" not in md and "cid" not in md


class TestMembershipEntriesUseCanonicalKeys:
    def test_entry_keys(self, fresh_db):
        _seed_board("885333", "300188")
        board_mod.upsert_membership_bulk(
            source="ths",
            stocks=[{"stock_code": "600519", "stock_name": "贵州茅台"}],
            board_code="885333",
            board_name="测试板块",
            board_type="concept",
            subtype="同花顺概念",
        )
        entries, _cold, _origin = board_mod.get_stock_memberships("600519", ["ths"])
        assert entries
        entry = entries[0]
        assert entry["board_code"] == "885333"
        assert entry["board_type"] == "concept"
        assert FORBIDDEN_BARE_CODE not in entry and "type" not in entry


class TestFetcherRowsUseCanonicalKeys:
    def test_ths_get_all_boards_row_keys(self, monkeypatch):
        """ThsFetcher concept rows: board_code=platecode, ths_cid=cid, board_type."""
        from stock_data.data_provider.fetchers.ths_fetcher import ThsFetcher

        parsed = ThsFetcher._parse_gn_section(
            '<input id="gnSection" value=\'{"1":{"platecode":"886071",'
            '"platename":"AI PC","cid":"309121","199112":-0.84}}\'>'
        )
        assert parsed
        row = parsed[0]
        assert row["board_code"] == "886071"
        assert row["ths_cid"] == "309121"
        assert FORBIDDEN_BARE_CODE not in row
        assert "platecode" not in row

    def test_zzshare_get_all_boards_ths_cid_always_none(self, monkeypatch):
        """spec §4 hard rule 3: zzshare rows must never carry a THS cid."""
        from stock_data.data_provider.fetchers.zzshare_fetcher import ZzshareFetcher

        f = ZzshareFetcher()
        monkeypatch.setattr(
            ZzshareFetcher,
            "_api",
            type(
                "A",
                (),
                {
                    "plates_rank": lambda self, **kw: [
                        {"plate_code": "801001", "plate_name": "芯片", "rate": 1.0}
                    ]
                },
            )(),
        )
        monkeypatch.setattr(f, "_ensure_api", lambda: None)
        rows = f.get_all_boards(board_type="concept")
        assert rows
        assert rows[0]["board_code"] == "801001"
        assert rows[0]["ths_cid"] is None
        assert FORBIDDEN_BARE_CODE not in rows[0]
```

- [ ] **Step 2: 运行确认失败**

Run: `python -m pytest tests/test_board_naming_contract.py -v`
Expected: FAIL（`KeyError: 'board_code'` / `assert 'code' not in row` 失败）

- [ ] **Step 3: 执行重命名**

按上文"完整改动点清单"逐文件改。顺序建议（每改完一组跑一次 `python -m pytest tests/test_board_naming_contract.py -v`）：

1. `data_provider/fetchers/`（4 个 fetcher）—— 先让产生方统一
2. `persistence/board.py` 的读写函数（`_read_boards_from_db` / `_read_membership_entries` / `get_board_metadata` / `update_cached_boards` / `_get_all_board_types` / `get_board_name_with_fallback` / `resolve_board_types`）
3. `persistence/backfill.py`
4. `api/routes/boards.py` / `agent.py` / `_helpers/*`（只改内部变量与入参，**响应构造处保留 `code=` / `type=`**）

关键点（易错）：
- `_read_boards_from_db` 必须**删掉** `"type"` 与 `"board_type"` 的双返回，只留 `"board_type"`。
- `get_board_name_with_fallback` 的 `board_code in (b.get("code"), b.get("platecode"))` 必须退化成 `board_code == b.get("board_code")`，两个 key 的探测是本次要消灭的模式。
- `update_cached_boards` 的 `b["code"]` 是硬下标（KeyError 风险），改为 `b["board_code"]` 时保持硬下标（契约要求必备字段）。
- fetcher 与持久层之间的 `platecode` 键**彻底消失**；`stock_board.platecode` SQL 列早已不存在，无需处理。

- [ ] **Step 4: 同步既有测试的 mock 行 key**

按 Task 5 的 REWRITE 清单改（本步只改 mock dict 的 key，不改断言语义）：
`tests/test_persistence_origin.py`（178-719 的 12 处）、`tests/test_boards.py`（29/56/95/136/172/227/267/311）、`tests/test_boards_api.py`（72/123/140/164/192/205/215/252/273/341）、`tests/test_board_csv_seed.py`（28/52/233）、`tests/test_board_backfill.py`（14 处）、`tests/test_boards_backfill_integration.py`（30 的 helper）、`tests/test_persistence_board_name_fallback.py`（35/58/101/112/134/145）、`tests/test_persistence_board.py`（450）。

- [ ] **Step 5: 运行确认通过**

Run: `python -m pytest tests/test_board_naming_contract.py tests/test_persistence_board.py tests/test_boards.py -q`
Expected: PASS（不变量测试全绿；既有测试的 mock key 已同步）

- [ ] **Step 6: 提交**

```bash
git checkout -b feat/board-source-split-internal
git add -A
git commit -m "refactor(board): unify internal row keys to board_code/ths_cid/board_type"
```

---

### Task 2: 删除跨源 merge 与兜底

**Files:**
- Modify: `stock_data/data_provider/persistence/board.py`
- Modify: `stock_data/data_provider/persistence/backfill.py`
- Delete: `tests/test_persistence_board_merge.py`（16 个用例）、`tests/test_persistence_board_f10_fallback.py`（整文件）

**Interfaces:**
- Consumes: Task 1 的 `board_code` / `ths_cid` 行 key
- Produces: `get_board_list` 的 ths 分支直连 `manager.get_all_boards(source="ths", ...)`；`get_board_stocks` 无跨源分支

- [ ] **Step 1: 删除四个函数与别名**

在 `persistence/board.py` 删除：
- `_merge_ths_zzshare_by_name`（811-883）
- `_normalize_zzshare_list_quote_units`（886-910）
- `fetch_boards_with_zzshare_backfill`（913-1003）
- `fetch_board_stocks_with_zzshare_fallback`（1006-1252）
- `_resolve_ths_cid_from_platecode = _resolve_ths_cid_from_code` 别名行（808）

- [ ] **Step 2: `get_board_list` 去掉 merge 分支**

`get_board_list` 的 658-672 替换为：

```python
    boards, _ = manager.get_all_boards(
        source=source,
        board_type=board_type,
        subtype=None,
        include_quote=include_quote,
    )
```

（`subtype` 仍由 678-679 的 in-memory 过滤处理；ths 不再有第二条过滤路径，因为 merge 分支已删。）

- [ ] **Step 3: `get_board_stocks` 去掉跨源分支**

把 1469-1625 的 include_quote 两段替换为按 source 直调（本 Task 只做"去掉跨源"，两层分流是 Plan 3）：

```python
    if not include_quote:
        # include_quote=False: THS F10 full membership (no 50-cap) is the
        # only leg; zzshare is a separate source and is never called here
        # (spec §2 D2: strict isolation, no cross-source fallback).
        try:
            stocks, origin = manager.get_board_stocks_full(
                board_code=board_code, source=source, board_type=board_type
            )
        except DataFetchError as e:
            if cached_full:
                logger.warning(
                    f"[BoardCache] Upstream failed for {board_code} "
                    f"(include_quote=False), serving {len(cached_full)} stale "
                    f"stocks: {e}"
                )
                return (
                    cached_full, "persistence", source,
                    "stale_after_upstream_failure", False, cached_count,
                )
            raise
        if stocks:
            update_cached_board_stocks(board_code, source, stocks)
        return stocks, origin, source, None, False, cached_count
```

include_quote=True 分支的 zzshare suffix 段（1534-1551）**删除**，`quote_truncated` / `quote_total_in_board` 暂按"仅 THS 结果"计算，并在 Plan 3 换成 F10+union 的真实实现：

```python
    # Plan 3 replaces this with the F10 + /stocks quote-cache union tier;
    # for now the response is honesty-first: THS top_n only, and
    # quote_truncated reflects "we cannot see beyond what THS returned".
    cached_quotes = get_cached_market_quotes(manager)
    if cached_quotes:
        stocks = _enrich_rows_with_market_quote(stocks, cached_quotes)
    update_cached_board_stocks(board_code, source, stocks)
    quote_truncated = len(stocks) >= top_n
    return stocks, origin, source, None, quote_truncated, max(cached_count, len(stocks))
```

- [ ] **Step 4: 删除既有测试**

```bash
git rm tests/test_persistence_board_merge.py tests/test_persistence_board_f10_fallback.py
```

并从 `tests/test_board_backfill.py` 删除 `test_zzshare_empty_falls_back_to_ths`（606）与 `test_zzshare_raises_falls_back_to_ths`（656）这两个 pin 住跨源兜底的用例。`TestResolveThsCidFromPlatecode`（原 merge 文件 56-97 的 5 个用例）**保留**，迁到 `tests/test_persistence_board.py` 或 `tests/test_board_naming_contract.py`（它们只断言 SQL 列语义，不受影响）。

- [ ] **Step 5: 运行确认**

Run: `python -m pytest tests/test_board_backfill.py tests/test_persistence_board.py -q`
Expected: PASS。**同时确认没有任何地方再 import 被删的函数**：

```bash
python -m ruff check . && grep -rn "fetch_boards_with_zzshare_backfill\|fetch_board_stocks_with_zzshare_fallback\|_merge_ths_zzshare_by_name\|_normalize_zzshare_list_quote_units" stock_data/ tools/ | grep -v "\.pyc"
```
Expected: ruff 无错误；grep 无输出（docstring 引用一并在 Step 6 清理）

- [ ] **Step 6: 清理 docstring / 注释引用**

删除或改写这些已失效的说明（不删代码，只改文字）：
`api/routes/boards.py:577`、`api/routes/boards.py:311/613/617`、`api/routes/agent.py:1497`、`api/schemas.py:2136`、`manager.py:1278-1281`、`persistence/backfill.py:46-54/70/82-90`、`docs/board-source-semantics.md` 的 `effective_source` 段（跨源 fallback 语义已不存在）。

- [ ] **Step 7: 提交**

```bash
git add -A
git commit -m "refactor(board): delete cross-source merge/fallback (strict ths|zzshare isolation)"
```

---

### Task 3: cache key 带 source + `_resolve_ths_cid_from_code` 收紧

**Files:**
- Modify: `stock_data/data_provider/persistence/board.py`
- Test: `tests/test_board_cache_key_per_source.py`（Create）

**Interfaces:**
- Consumes: Plan 1 的 `resolve_ths_platecode(ths_cid) -> str | None`、`ths_board_id_map` 表
- Produces: `get_board_stocks` 的缓存读写与 refresh tracker 全部带 `source`

- [ ] **Step 1: 写失败测试**

Create `tests/test_board_cache_key_per_source.py`:

```python
"""Cache rows and the refresh tracker must be keyed per source.

Pre-split, everything was hardcoded to source='ths' — a zzshare request
could read THS rows and vice versa (spec §7). After the split a cache hit
for `source=zzshare` must NOT be able to see `source=ths` rows.
"""

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
    board_mod._refresh_tracker = board_mod.DailyRefreshTracker()
    yield


class TestMembershipCacheIsolatedPerSource:
    def test_zzshare_rows_invisible_to_ths(self, fresh_db):
        board_mod.update_cached_board_stocks(
            "801001", "zzshare", [{"stock_code": "600519", "stock_name": "贵州茅台"}]
        )
        assert board_mod._read_board_stocks_from_db("801001", "ths") == []
        assert len(board_mod._read_board_stocks_from_db("801001", "zzshare")) == 1

    def test_ths_rows_invisible_to_zzshare(self, fresh_db):
        board_mod.update_cached_board_stocks(
            "885333", "ths", [{"stock_code": "600519", "stock_name": "贵州茅台"}]
        )
        assert board_mod._read_board_stocks_from_db("885333", "zzshare") == []


class TestRefreshTrackerKeyIncludesSource:
    def test_two_sources_do_not_share_a_tracker_key(self, fresh_db, monkeypatch):
        calls: list[tuple[str, str]] = []
        real = board_mod._refresh_tracker.is_first_call

        def spy(key):
            calls.append(key)
            return real(key)

        monkeypatch.setattr(board_mod._refresh_tracker, "is_first_call", spy)
        monkeypatch.setattr(
            board_mod, "get_cached_market_quotes", lambda manager: None
        )

        class _Mgr:
            name = "fake"

            def get_board_stocks_full(self, **kw):
                return [], self.name

            def get_board_stocks(self, **kw):
                return [], self.name

        board_mod.get_board_stocks("885333", source="ths", manager=_Mgr())
        board_mod.get_board_stocks("801001", source="zzshare", manager=_Mgr())
        assert "885333:ths" in calls
        assert "801001:zzshare" in calls


class TestResolveThsCidNoLongerFallsBackToCode:
    def test_zzshare_code_row_yields_none(self, fresh_db):
        """A row whose cid column is NULL must NOT resolve to its own code.

        Pre-fix, `_resolve_ths_cid_from_code('801001')` returned '801001'
        (the code-column fallback), which was then handed to ThsFetcher as
        a THS cid — the entry point of the observed
        `?source=ths → effective_source='zzshare'` leak (spec §1.3).
        """
        conn = board_mod.get_connection()
        with conn:
            conn.execute(
                """INSERT OR REPLACE INTO stock_board
                   (code, name, board_type, subtype, source, cid, updated_at)
                   VALUES ('801001','芯片','concept','同花顺题材','ths',NULL,
                           CURRENT_TIMESTAMP)"""
            )
        assert board_mod.resolve_ths_cid("801001") is None

    def test_concept_row_resolves_its_cid(self, fresh_db):
        conn = board_mod.get_connection()
        with conn:
            conn.execute(
                """INSERT OR REPLACE INTO stock_board
                   (code, name, board_type, subtype, source, cid, updated_at)
                   VALUES ('885333','移动支付','concept','同花顺概念','ths','300188',
                           CURRENT_TIMESTAMP)"""
            )
        assert board_mod.resolve_ths_cid("885333") == "300188"

    def test_industry_row_identity(self, fresh_db):
        """Industry rows store cid == code on purpose (881xxx)."""
        conn = board_mod.get_connection()
        with conn:
            conn.execute(
                """INSERT OR REPLACE INTO stock_board
                   (code, name, board_type, subtype, source, cid, updated_at)
                   VALUES ('881121','半导体','industry','同花顺行业','ths','881121',
                           CURRENT_TIMESTAMP)"""
            )
        assert board_mod.resolve_ths_cid("881121") == "881121"

    def test_unknown_code_returns_none(self, fresh_db):
        assert board_mod.resolve_ths_cid("999999") is None
```

- [ ] **Step 2: 运行确认失败**

Run: `python -m pytest tests/test_board_cache_key_per_source.py -v`
Expected: FAIL（`AttributeError: module ... has no attribute 'resolve_ths_cid'`；per-source 隔离断言失败）

- [ ] **Step 3: 改 cache key**

在 `persistence/board.py`：

1. `_resolve_ths_cid_from_code` 重命名为 `resolve_ths_cid`，去掉 `code` 回退：

```python
def resolve_ths_cid(board_code: str) -> str | None:
    """Resolve the THS internal cid for a THS public board_code.

    Returns ``None`` when no THS row exists, or when the row's ``cid``
    column is NULL. **There is deliberately no fallback to ``code``**: that
    fallback is what let a zzshare plate code (801xxx) be handed to
    ThsFetcher as if it were a cid (spec §1.3). Industry rows keep
    ``cid == code`` (881xxx) by construction, so they resolve normally.
    """
    init_schema()
    row = get_connection().execute(
        "SELECT cid FROM stock_board WHERE code = ? AND source = 'ths' LIMIT 1",
        (board_code,),
    ).fetchone()
    return row["cid"] if row and row["cid"] else None
```

2. `get_board_stocks` 的 1454/1456/1503/1617 把硬编码 `"ths"` 换成 `source`：

```python
    needs_refresh = (
        include_quote or refresh or _refresh_tracker.is_first_call(f"{board_code}:{source}")
    )
    cached_full = _read_board_stocks_from_db(board_code, source)
```

（两处 `update_cached_board_stocks(board_code, "ths", ...)` → `(board_code, source, ...)`。）

3. 更新 `ths_fetcher.py` / `persistence/board.py` 里对 `_resolve_ths_cid_from_platecode` 的引用（ths_fetcher.py:1444）为 `resolve_ths_cid`。

- [ ] **Step 4: 运行确认通过**

Run: `python -m pytest tests/test_board_cache_key_per_source.py -q`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add -A
git commit -m "refactor(board): key board-stock cache and refresh tracker per source"
```

---

### Task 4: `backfill.py` 改为 ths-only

**Files:**
- Modify: `stock_data/data_provider/persistence/backfill.py`
- Test: `tests/test_board_backfill.py`

**Interfaces:**
- Consumes: Task 2 删除后的 `manager.get_all_boards` / `manager.get_board_stocks_full`
- Produces: `run_ths_board_backfill` 两阶段均为 THS 单源

- [ ] **Step 1: 改 Phase 1（按 type 直调）**

把 `backfill.py:100-106` 替换为：

```python
        # THS-only sweep. Pre-split this called
        # fetch_boards_with_zzshare_backfill, which merged zzshare rows in
        # and stamped them source='ths' (spec §1.4).
        merged_by_type: dict[str, list[dict]] = {}
        for bt in ("concept", "industry"):
            rows_b, _origin = manager.get_all_boards(
                source="ths",
                board_type=bt,
                subtype=None,
                include_quote=include_quote,
            )
            merged_by_type[bt] = rows_b or []
        boards_merged = [r for rows_b in merged_by_type.values() for r in rows_b]
```

后续 114-118 的 `report.phase1_boards_emitted` 与 124-133 的 groupby 改用 `b.get("board_type")`（原 `b.get("type")`）。因为已经按 type 分组，124-133 的 groupby 可直接删除，改为：

```python
        for bt, bucket in merged_by_type.items():
            if bucket:
                report.phase1.success += update_cached_boards(bt, "ths", bucket)
```

- [ ] **Step 2: 改 Phase 2（用 board_code 而非 platecode）**

`backfill.py:171-177` 替换为：

```python
            board_code = board.get("board_code")
            if not board_code:
                logger.debug(
                    f"[Backfill] skipping board with no board_code: {board.get('name')!r}"
                )
                continue
```

`backfill.py:184-191` 替换为：

```python
            try:
                rows, _source_label = manager.get_board_stocks_full(
                    board_code=board_code,
                    source="ths",
                    board_type=board.get("board_type"),
                )
            except DataFetchError as e:
                rows = []
                _err = e
```

**限速处置（二选一，默认 A）**

`_auto_rate_limit_s`（46-54）的取值依据是 zzshare `plates_stocks` 的限流（有 token 时 1.2s，否则 3.0s）。phase 2 的 zzshare 腿已删，该依据失效。

- **A（默认）**：删除 `_auto_rate_limit_s` 与 `inter_call_sleep_s` 参数，sleep 固定 `0.0`。理由：F10 是单次 GET，且 `get_board_f10_page` 自带 45s HTML 缓存；THS 的板块页没有 zzshare 那样的限流证据。在 `run_ths_board_backfill` 的 docstring 里写明"no inter-call sleep: F10 is a single GET with a 45s HTML cache"。
- **B（备选：保守限速）**：保留限速但改为 THS 依据：

```python
# THS q.10jqka.com.cn appears in the project's UA/rate-limit audit as the
# weakest link under single-IP high-frequency use (CLAUDE.md, Key Design
# Patterns). The backfill is a one-off sweep, so a conservative jitter
# costs minutes, not hours.
THS_BOARD_FETCH_JITTER_S = (1.5, 3.0)
```

并把 `_auto_rate_limit_s` 替换为：

```python
def _auto_rate_limit_s() -> float:
    """Lower bound of the THS board-page jitter, in seconds."""
    return THS_BOARD_FETCH_JITTER_S[0]
```

选 B 时，`tests/test_board_backfill.py:19/27` 的两个 `_auto_rate_limit_s` 用例**保留但改断言值**（1.2 / 3.0 → 1.5 / 1.5），不要删。

Phase 2 的 `204-213`（连续错误计数）逻辑在两版下都不变。

`backfill.py:218-226` 的 `upsert_membership_bulk(source="ths", ...)` 保持 `"ths"`，`board.get("board_type","")` 取新 key。

- [ ] **Step 3: 改测试**

`tests/test_board_backfill.py`：
- 删除 `test_zzshare_empty_falls_back_to_ths`（606）、`test_zzshare_raises_falls_back_to_ths`（656）
- 删除 `test_auto_rate_limit_s_with_token_returns_1_2`（19）、`test_auto_rate_limit_s_without_token_returns_3_0`（27）—— 被删函数
- 其余 14 处按 REWRITE：mock 行 key 改 `board_code`/`board_type`；`test_full_sweep_writes_membership`（110）的 `assert source == "zzshare"`（148）改为 `assert source == "ths"`；`get_board_stocks.return_value = ([], "zzshare")` 全部改为 `get_board_stocks_full` 的 stub
- `_make_phase1_only_manager`（47）返回 `{"board_code","board_type"}` 形状

- [ ] **Step 4: 运行确认通过**

Run: `python -m pytest tests/test_board_backfill.py tests/test_boards_backfill_integration.py -q`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add -A
git commit -m "refactor(backfill): make startup board backfill ths-only"
```

---

### Task 5: `update_cached_boards` 快照替换 + 回归

**Files:**
- Modify: `stock_data/data_provider/persistence/board.py`
- Test: `tests/test_board_prune_stale_boards.py`（Create）

**Interfaces:**
- Consumes: Task 1 的 `b["board_code"]`
- Produces: `update_cached_boards(board_type, source, boards)` 先按 `(board_type, source)` 删除再插入

- [ ] **Step 1: 写失败测试**

Create `tests/test_board_prune_stale_boards.py`:

```python
"""update_cached_boards must be a snapshot replace, not an append.

Pre-fix there was no DELETE, so a board that disappeared upstream stayed in
`stock_board` forever, and a board observed first as a cid-keyed row and
later as a platecode-keyed row ended up stored twice (spec §1.3, mechanism 3).
`update_cached_board_stocks` already purges per (board_code, source) — this
brings the board-list table to the same contract.
"""

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


def _codes(source: str = "ths") -> set[str]:
    rows = board_mod.get_connection().execute(
        "SELECT code FROM stock_board WHERE source = ?", (source,)
    ).fetchall()
    return {r["code"] for r in rows}


class TestSnapshotReplace:
    def test_board_gone_upstream_is_removed(self, fresh_db):
        board_mod.update_cached_boards(
            "concept", "ths", [{"board_code": "885333", "name": "移动支付"}]
        )
        assert _codes() == {"885333"}
        board_mod.update_cached_boards(
            "concept", "ths", [{"board_code": "886071", "name": "AI PC"}]
        )
        assert _codes() == {"886071"}, "stale 885333 must be purged"

    def test_other_source_rows_survive(self, fresh_db):
        board_mod.update_cached_boards(
            "concept", "ths", [{"board_code": "885333", "name": "移动支付"}]
        )
        board_mod.update_cached_boards(
            "concept", "zzshare", [{"board_code": "801001", "name": "芯片"}]
        )
        assert _codes("ths") == {"885333"}
        assert _codes("zzshare") == {"801001"}

    def test_other_board_type_rows_survive(self, fresh_db):
        board_mod.update_cached_boards(
            "concept", "ths", [{"board_code": "885333", "name": "移动支付"}]
        )
        board_mod.update_cached_boards(
            "industry", "ths", [{"board_code": "881121", "name": "半导体"}]
        )
        assert _codes() == {"885333", "881121"}

    def test_ths_cid_written_only_for_ths_rows(self, fresh_db):
        board_mod.update_cached_boards(
            "concept",
            "ths",
            [{"board_code": "885333", "name": "移动支付", "ths_cid": "300188"}],
        )
        board_mod.update_cached_boards(
            "concept",
            "zzshare",
            [{"board_code": "801001", "name": "芯片", "ths_cid": None}],
        )
        conn = board_mod.get_connection()
        assert conn.execute(
            "SELECT cid FROM stock_board WHERE code='885333'"
        ).fetchone()["cid"] == "300188"
        assert conn.execute(
            "SELECT cid FROM stock_board WHERE code='801001'"
        ).fetchone()["cid"] is None

    def test_purge_scoped_to_source_does_not_touch_other_sources_membership(self, fresh_db):
        board_mod.update_cached_board_stocks(
            "801001", "zzshare", [{"stock_code": "600519", "stock_name": "贵州茅台"}]
        )
        board_mod.update_cached_boards(
            "concept", "ths", [{"board_code": "885333", "name": "移动支付"}]
        )
        assert len(board_mod._read_board_stocks_from_db("801001", "zzshare")) == 1
```

- [ ] **Step 2: 运行确认失败**

Run: `python -m pytest tests/test_board_prune_stale_boards.py -v`
Expected: FAIL（`test_board_gone_upstream_is_removed` 断言失败，885333 仍在）

- [ ] **Step 3: 实现 purge**

在 `update_cached_boards` 的 `cursor.executemany` **之前**插入：

```python
            # Snapshot replace, scoped to (board_type, source): boards that
            # left upstream must not linger, and a board previously written
            # under a different code key must not survive as a duplicate
            # (spec §1.3, mechanism 3). Mirrors update_cached_board_stocks'
            # DELETE-then-INSERT contract.
            cursor.execute(
                "DELETE FROM stock_board WHERE board_type = ? AND source = ?",
                (board_type, source),
            )
```

并更新函数 docstring：加一句 "Snapshot replace: rows for this `(board_type, source)` pair are deleted before insert."

- [ ] **Step 4: 运行确认通过**

Run: `python -m pytest tests/test_board_prune_stale_boards.py -q`
Expected: PASS

- [ ] **Step 5: 全量回归**

Run:

```bash
python -m pytest -q
python -m ruff check .
```

Expected: 无 fail / error；ruff 干净。**若出现 `test_boards.py` / `test_boards_api.py` 中与 `?source=zzshare` 422 相关的失败，那是预期的** —— 它们属于 Plan 3 的 REWRITE 清单（本计划不改公开参数面，因此这些用例应仍绿；若变红说明重命名漏了某处，回头修）。

- [ ] **Step 6: 提交**

```bash
git add -A
git commit -m "fix(board): make update_cached_boards a (board_type, source) snapshot replace"
```

---

## Self-Review

**Spec 覆盖**

| spec 节 | 覆盖于 |
|---|---|
| §4 id 契约硬规则 1/2/3/4 | Task 1（命名 + `ths_cid` 只对 ths 行写）、Task 3（去掉 cid 回退） |
| §4 硬规则 5（`update_cached_boards` purge） | Task 5 |
| §5.1 第 1 层命名收敛 | Task 1 |
| §5.2 第 2 层（删别名 + 去双返回） | Task 1（双返回）、Task 2（别名） |
| §5.3 第 3 层排除 | Global Constraints 显式声明不碰 |
| §6 ThsFetcher 输出归一 | Task 1 |
| §7 删除四个函数 + cache key per-source | Task 2、Task 3 |
| §7 `VALID_SOURCES` 收录 zzshare | **Plan 3**（与 Literal 一起改，避免中间态 400） |
| §8 include_quote 两层 | Task 2 只摘掉 zzshare leg；真实两层在 **Plan 3** |
| §9 路由放开 zzshare / history·quote 收紧 | **Plan 3** |
| §10 数据迁移 CSV 拆分 / membership relabel | **Plan 3** |
| §11 测试重写 | Task 1-5 内联（每个 Task 含自己打破的测试） |
| §12 文档 | Task 2 Step 6（清理失效引用）+ **Plan 3**（4 份文档） |
| §13 breaking #1（`?source=ths` 结果集变小） | 本计划落地 |
| §13 breaking #2-#6 | **Plan 3** |

**无 placeholder**：所有逻辑改动给出完整代码；机械重命名给出 1:1 映射表 + 逐文件行号清单（不复制每一行为代码，因映射唯一且无歧义）。

**类型一致性**：`resolve_ths_cid(board_code) -> str | None`（Task 3）取代 `_resolve_ths_cid_from_code`；行 key `board_code` / `ths_cid` / `board_type` 在 Task 1 定义后，Task 2/3/4/5 一致使用；`update_cached_boards(board_type, source, boards)` 签名不变。

**已知需你确认的两点**（已在正文标注）：
1. Task 4 Step 2 的 `_auto_rate_limit_s` 删除 → 是否保留 THS 限速（默认删，改为 `0.0`）。
2. Task 1 Step 3 的 fetcher 重命名会**同时改变 4 个 fetcher 的输出 key**（eastmoney / zhitu 也受影响），`/control/fetcher-test` 的 Stage 2 原始返回也会随之变化 —— 该端点是调试用、无契约承诺，但 explorer 页面的展示会变。
</content>
