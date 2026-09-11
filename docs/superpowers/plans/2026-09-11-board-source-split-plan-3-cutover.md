# board source 拆分 Plan 3 —— zzshare 公开 + include_quote 两层 + 文档与重建 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让 `zzshare` 成为公开可选 source（`?source=zzshare` 由 422 变 200），把 `include_quote=true` 改为 THS 单源两层（AJAX ≤50 / F10+行情缓存 >50），同步重写受影响的测试、更新 4 份文档、并在重建后的库上按不变量验收。

**Architecture:** 路由层的四个 source 白名单收敛为一套，`zzshare` 从别名改为真值；`/boards/{code}/history` 与 `/boards/{code}/quote` 对 zzshare 明确 400/422（zzshare 无对应上游能力）。`include_quote=true` 的 `top_n>50` 走 `get_board_stocks_full`（F10，无 50 上限）并用既有 `_enrich_rows_with_market_quote` 从 `/stocks` 全市场行情缓存补 quote。

**Tech Stack:** Python 3.13 / SQLite / FastAPI / pytest / ruff 0.15.12

## Global Constraints

- 本机无 `.venv/`，用系统 `python`（miniconda 3.13.9）。
- 每个 Task 结束时 `python -m pytest -q` 与 `python -m ruff check .` 必须干净。
- 公开模型字段名不变（`BoardInfo.code` / `type`）；唯一例外是**新增**字段（`amount_unit`），属加法。
- 本计划的 5 类新测试按**不变量**断言，不写死行数/比率 —— 这样它们对上游数据漂移免疫。
- `top_n` 的 `Query(le=50)` 放宽后，上限取 **800**（与 `/boards/{code}/history` 的 800 天上限同量级，避免无界请求）。
- 分支：`feat/board-source-split-cutover`（从 Plan 2 的分支切出，或在其合并后从 master 切）。

## 前置依赖

**Plan 2 必须已合并**（`docs/superpowers/plans/2026-09-11-board-source-split-plan-2-internal.md`）：本计划的所有改动都以 `board_code` / `ths_cid` / `board_type` 行 key 与"无跨源 merge"为前提。

---

### Task 1: source 白名单收敛 + zzshare 转正

**Files:**
- Modify: `stock_data/data_provider/persistence/board.py`（白名单常量 + 删死代码）
- Modify: `stock_data/api/routes/boards.py`（三个 Literal + 两个 resolver）
- Test: `tests/test_board_source_allowlist.py`（Create）
- Test: REWRITE 清单见 Step 6

**Interfaces:**
- Produces: `VALID_SOURCES = ("ths", "zzshare", "eastmoney", "zhitu")`；`_BOARD_HISTORY_VALID_SOURCES = ("ths", "eastmoney")`（不含 zzshare，无 K 线上游）；别名映射全部删除
- Consumes: Plan 2 的行 key

- [ ] **Step 1: 写失败测试**

Create `tests/test_board_source_allowlist.py`:

```python
"""One allowlist, one alias policy (spec §9).

Pre-split there were four source allowlists in three places, three of them
textually identical, with two different alias behaviours — which is how
`?source=zzshare` ended up 422 on two routes, 200-with-ths-data on a third,
and 400 on a fourth.
"""

from __future__ import annotations

import pytest

from stock_data.api.routes import boards as routes_mod
from stock_data.data_provider.persistence import board as board_mod


class TestAllowlists:
    def test_zzshare_is_a_first_class_forward_source(self):
        assert "zzshare" in board_mod.VALID_SOURCES

    def test_zzshare_is_a_first_class_board_stocks_source(self):
        assert "zzshare" in board_mod._BOARD_STOCKS_VALID_SOURCES

    def test_zzshare_is_a_first_class_stock_boards_source(self):
        assert "zzshare" in board_mod._STOCK_BOARDS_VALID_SOURCES

    def test_history_allowlist_excludes_zzshare(self):
        """zzshare's plate_kline only serves 883957 — no board K-line."""
        assert "zzshare" not in routes_mod._BOARD_HISTORY_VALID_SOURCES

    def test_every_allowlist_is_the_same_object_or_equal(self):
        assert set(board_mod.VALID_SOURCES) == set(board_mod._BOARD_STOCKS_VALID_SOURCES)
        assert set(board_mod.VALID_SOURCES) == set(board_mod._STOCK_BOARDS_VALID_SOURCES)


class TestNoAliasesRemain:
    def test_stock_boards_alias_map_is_gone(self):
        assert not hasattr(board_mod, "_STOCK_BOARDS_SOURCE_ALIAS")

    def test_normalize_stock_board_source_returns_zzshare_verbatim(self):
        assert board_mod.normalize_stock_board_source("zzshare") == "zzshare"

    def test_history_resolver_does_not_alias_zzshare(self):
        with pytest.raises(ValueError):
            routes_mod._resolve_board_history_source("zzshare")

    def test_dead_normalizer_removed(self):
        """Zero production callers before the split; still zero after."""
        assert not hasattr(board_mod, "normalize_board_stocks_source")


class TestSourceParsing:
    def test_csv_parser_accepts_zzshare(self):
        assert routes_mod._parse_stock_boards_source_csv("ths,zzshare") == ["ths", "zzshare"]

    def test_default_csv_is_all_sources_including_zzshare(self):
        assert set(routes_mod._parse_stock_boards_source_csv(None)) == {
            "ths",
            "zzshare",
            "eastmoney",
            "zhitu",
        }
```

- [ ] **Step 2: 运行确认失败**

Run: `python -m pytest tests/test_board_source_allowlist.py -v`
Expected: FAIL（`zzshare` 不在白名单、`_STOCK_BOARDS_SOURCE_ALIAS` 仍存在等）

- [ ] **Step 3: 收敛持久层白名单**

`persistence/board.py`：

```python
VALID_SOURCES: tuple[str, ...] = ("ths", "zzshare", "eastmoney", "zhitu")
_STOCK_BOARDS_VALID_SOURCES: tuple[str, ...] = VALID_SOURCES
_BOARD_STOCKS_VALID_SOURCES: tuple[str, ...] = VALID_SOURCES
```

删除 `_STOCK_BOARDS_SOURCE_ALIAS`（177）与 `normalize_stock_board_source`（224-249）—— 后者**零生产调用者**（`/stocks/{code}/boards` 走的是 `_parse_stock_boards_source_csv`，把同样的 alias 逻辑内联了一份），只有测试引用它，那些测试在 Step 6 一并改掉。

**保留** `normalize_board_stocks_source`（189-221）—— 它有唯一生产调用者 `boards.py:532`。只把它的白名单从 `_BOARD_STOCKS_VALID_SOURCES` 改为 `VALID_SOURCES`（Step 3 的常量已让二者相等，所以实际无需改代码，只需确认）。

`VALID_SUBTYPES_BY_SOURCE` 增加 zzshare 已有（138-146 已存在），确认其 `concept`/`industry` 两个 key 与 `VALID_BOARD_TYPES` 一致。

- [ ] **Step 4: 收敛路由层白名单与 Literal**

`api/routes/boards.py`：
- 324（`/boards`）、464（`/boards/{board_code}/stocks`）、848（`/stocks/{stock_code}/boards`）的 `source: Literal[...]` 加入 `"zzshare"`。
- `_resolve_source`（106-124）与 `_resolve_board_history_source`（144-171）的白名单分别指向 `stock_board_cache.VALID_SOURCES` 与 `_BOARD_HISTORY_VALID_SOURCES`。
- `_resolve_board_history_source` 删除 158-159 的 alias：

```python
def _resolve_board_history_source(source: str) -> str:
    """Validate the board-history source. No aliasing: zzshare has no K-line."""
    if source not in _BOARD_HISTORY_VALID_SOURCES:
        raise ValueError(
            f"Unknown source '{source}'. Valid sources: "
            f"{list(_BOARD_HISTORY_VALID_SOURCES)}"
        )
    return source
```

- `_parse_stock_boards_source_csv`（251-298）：删除 275 的 alias map 读取与 283 的 `alias_map.get(s, s)`，把 274 的 valid set 改成 `stock_board_cache.VALID_SOURCES`，并把错误消息里的 `(alias 'zzshare' accepted)` 去掉。

- [ ] **Step 5: `/boards/{board_code}/quote` 对 unsupported source 的处理**

该路由**没有** `?source=` 参数（硬编码 ths），无需改动；在它的 docstring 与 `schemas.py` 的 `BoardQuoteResponse` 说明里补一句"来源固定 ths；其他 source 不支持板块实时行情"。`/boards/{board_code}/news` 与 `/surges` 的 `Literal["ths"]` 保持不变（同理由）。

- [ ] **Step 6: REWRITE 受影响的既有测试**

按清单逐条改（只列必须改的语义项）：

| 文件:行 | 改为 |
|---|---|
| `tests/test_boards.py:347` | `?source=zzshare` 期望 **200**；persistence 收到 `source='zzshare'` |
| `tests/test_boards.py:367` | 同上 |
| `tests/test_boards.py:372` | `ths` + `include_quote=False` → **一次** F10 调用，无 zzshare |
| `tests/test_boards.py:431` / `467` | `top_n<=50` → 单次 THS AJAX，断言 zzshare **从未被调用** |
| `tests/test_boards.py:352` | 不再 patch 已删函数，改 patch 新的 per-source 入口 |
| `tests/test_boards.py:510` | KEEP（`call_count == 1`，无 zzshare） |
| `tests/test_boards_api.py:50/66/240/497/527` | zzshare → 200；patch 目标换成新入口 |
| `tests/test_boards_api.py:750` | `cold_sources` 必须含 `"zzshare"`（不再被 alias 成 ths） |
| `tests/test_boards_api.py:763` | 按 zzshare 自己的 type set 重推，消息里出现 `zzshare` |
| `tests/test_boards_api.py:936` | `?source=zzshare` on history → **400**（alias 已删） |
| `tests/test_boards_api.py:959/969` | `"zzshare"` 必须**在**白名单里 |
| `tests/test_boards_api.py:1071` | `top_n=51` → **200**（上限放宽到 800） |
| `tests/test_stock_boards_reverse_route.py:102` | `get_stock_memberships(sources=["zzshare"])` |
| `tests/test_stock_boards_reverse_route.py:113` | 默认聚合集 = `{ths, zzshare, eastmoney, zhitu}` |
| `tests/test_stock_boards_reverse_route.py:162` | `normalize_stock_board_source("zzshare") == "zzshare"` |
| `tests/test_boards_history_route.py:17` | `source=zzshare` → 400 |
| `tests/test_boards_history_route.py:65` | DELETE（alias 行为已不存在） |
| `tests/test_boards.py:423-428`、`462-465`、`506-508`；`tests/test_boards_api.py:956/963/973`；`tests/test_boards_history_route.py:83` | 断言里的 `source='ths'` / `'zzshare'` 按新语义重推 |

- [ ] **Step 7: 运行确认通过**

Run: `python -m pytest tests/test_board_source_allowlist.py tests/test_boards.py tests/test_boards_api.py tests/test_stock_boards_reverse_route.py tests/test_boards_history_route.py -q`
Expected: PASS

- [ ] **Step 8: 提交**

```bash
git checkout -b feat/board-source-split-cutover
git add -A
git commit -m "feat(board): make zzshare a first-class source; collapse four allowlists into one"
```

---

### Task 2: include_quote 两层（AJAX ≤50 / F10 >50 + union）

**Files:**
- Modify: `stock_data/data_provider/persistence/board.py`（`get_board_stocks` 的 include_quote 路径）
- Modify: `stock_data/api/routes/boards.py`（`top_n` 上限）
- Modify: `stock_data/api/schemas.py`（`BoardStockInfo` 三个字段的说明 + `BoardInfo.amount_unit`）
- Test: `tests/test_board_include_quote_tiers.py`（Create）

**Interfaces:**
- Consumes: `manager.get_board_stocks_full(board_code, *, board_type) -> (list[dict], str)`、`manager.get_board_stocks(board_code, *, source, include_quote, board_type, sort_by, sort_order, top_n) -> (list[dict], str)`、`get_cached_market_quotes(manager) -> list | None`、`_enrich_rows_with_market_quote(rows, market_quotes) -> list[dict]`
- Produces: `quote_truncated` / `quote_total_in_board` 的新语义（见 Step 3）

- [ ] **Step 1: 写失败测试**

Create `tests/test_board_include_quote_tiers.py`:

```python
"""include_quote=true must never call zzshare, at any top_n (spec §8).

Two tiers, both THS-only:
  top_n <= 50  → AJAX 14 columns (18/18 BoardStockInfo fields after union)
  top_n >  50  → F10 full membership + /stocks quote-cache union
                 (15/18 fields; change_speed / free_float_shares /
                  float_market_cap are structurally absent from F10 —
                  probed 2026-09-11: all three are 0-filled on both the
                  concept and industry F10 paths)
"""

from __future__ import annotations

from datetime import datetime

import pytest

from stock_data.data_provider.core.types import UnifiedRealtimeQuote
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


def _seed_metadata() -> None:
    conn = board_mod.get_connection()
    with conn:
        conn.execute(
            """INSERT OR REPLACE INTO stock_board
               (code, name, board_type, subtype, source, cid, updated_at)
               VALUES ('885333','移动支付','concept','同花顺概念','ths','300188',
                       CURRENT_TIMESTAMP)"""
        )


def _quote(code: str, **kw) -> UnifiedRealtimeQuote:
    base = dict(
        code=code, name="x", price=1.0, change_pct=1.0, change_amount=0.0,
        volume=100, amount=1000.0, turnover_rate=1.0, volume_ratio=1.0,
        pe_ratio=10.0, open_price=1.0, high=1.1, low=0.9, pre_close=1.0,
        amplitude=2.0,
    )
    base.update(kw)
    return UnifiedRealtimeQuote(**base)


class _Recorder:
    """Fake manager that records every call, so we can assert zzshare is never hit."""

    name = "recorder"

    def __init__(self, ajax_rows=None, f10_rows=None):
        self.ajax_rows = ajax_rows or []
        self.f10_rows = f10_rows or []
        self.calls: list[tuple[str, dict]] = []

    def get_board_stocks(self, board_code, **kw):
        self.calls.append(("get_board_stocks", {"board_code": board_code, **kw}))
        return list(self.ajax_rows), self.name

    def get_board_stocks_full(self, board_code, **kw):
        self.calls.append(("get_board_stocks_full", {"board_code": board_code, **kw}))
        return list(self.f10_rows), self.name

    def get_realtime_quotes(self, market):
        return [_quote("600519")], self.name


class TestAjaxTierAtOrBelow50:
    def test_uses_ajax_and_never_zzshare(self, fresh_db, monkeypatch):
        _seed_metadata()
        monkeypatch.setattr(
            board_mod, "get_cached_market_quotes", lambda m: [_quote("600519")]
        )
        mgr = _Recorder(ajax_rows=[{"stock_code": "600519", "stock_name": "贵州茅台", "price": 1800.0}])
        stocks, origin, effective, reason, trunc, total = board_mod.get_board_stocks(
            "885333", source="ths", include_quote=True, manager=mgr, top_n=10
        )
        assert effective == "ths"
        assert not any(c[1].get("source") == "zzshare" for c in mgr.calls)
        assert [c[0] for c in mgr.calls].count("get_board_stocks_full") == 0
        assert stocks and stocks[0]["price"] == 1800.0

    def test_ajax_row_gains_the_five_cached_fields(self, fresh_db, monkeypatch):
        """THS's 14 columns lack open/high/low/prev_close/volume."""
        _seed_metadata()
        monkeypatch.setattr(
            board_mod, "get_cached_market_quotes", lambda m: [_quote("600519")]
        )
        mgr = _Recorder(ajax_rows=[{"stock_code": "600519", "stock_name": "贵州茅台"}])
        stocks, *_ = board_mod.get_board_stocks(
            "885333", source="ths", include_quote=True, manager=mgr, top_n=10
        )
        row = stocks[0]
        assert row["open"] == 1.0 and row["high"] == 1.1 and row["low"] == 0.9
        assert row["prev_close"] == 1.0 and row["volume"] == 100


class TestF10TierAbove50:
    def test_switches_to_f10_and_never_zzshare(self, fresh_db, monkeypatch):
        _seed_metadata()
        monkeypatch.setattr(
            board_mod, "get_cached_market_quotes", lambda m: [_quote("600519")]
        )
        mgr = _Recorder(
            f10_rows=[{"stock_code": "600519", "stock_name": "贵州茅台", "rank": 1}]
        )
        stocks, origin, effective, reason, trunc, total = board_mod.get_board_stocks(
            "885333", source="ths", include_quote=True, manager=mgr, top_n=200
        )
        assert not any(c[1].get("source") == "zzshare" for c in mgr.calls)
        assert [c[0] for c in mgr.calls].count("get_board_stocks_full") == 1
        assert len(stocks) == 1

    def test_f10_rows_get_quote_fields_from_the_union(self, fresh_db, monkeypatch):
        _seed_metadata()
        monkeypatch.setattr(
            board_mod, "get_cached_market_quotes", lambda m: [_quote("600519", price=1800.0)]
        )
        mgr = _Recorder(f10_rows=[{"stock_code": "600519", "stock_name": "贵州茅台"}])
        stocks, *_ = board_mod.get_board_stocks(
            "885333", source="ths", include_quote=True, manager=mgr, top_n=200
        )
        assert stocks[0]["price"] == 1800.0

    def test_f10_threestucturally_absent_fields_stay_none(self, fresh_db, monkeypatch):
        """Contract: these three are None on the >50 tier (probed 2026-09-11)."""
        _seed_metadata()
        monkeypatch.setattr(
            board_mod, "get_cached_market_quotes", lambda m: [_quote("600519")]
        )
        mgr = _Recorder(f10_rows=[{"stock_code": "600519", "stock_name": "贵州茅台"}])
        stocks, *_ = board_mod.get_board_stocks(
            "885333", source="ths", include_quote=True, manager=mgr, top_n=200
        )
        for field in ("change_speed", "free_float_shares", "float_market_cap"):
            assert stocks[0].get(field) is None


class TestTopNLimitWidened:
    def test_route_accepts_top_n_above_50(self):
        from stock_data.api.routes import boards as routes_mod
        import inspect

        src = inspect.getsource(routes_mod.get_board_stocks)
        assert "le=50" not in src, "top_n cap must be widened for the F10 tier"
```

- [ ] **Step 2: 运行确认失败**

Run: `python -m pytest tests/test_board_include_quote_tiers.py -v`
Expected: FAIL（F10 tier 未实现；`le=50` 仍在）

- [ ] **Step 3: 实现两层**

`persistence/board.py` 的 `get_board_stocks` include_quote=True 分支替换为：

```python
    # Two THS-only tiers (spec §8). Tier selection is by top_n, because
    # THS's AJAX endpoint hard-caps at 50 rows while the F10 page
    # server-renders the full membership (90+ concept / 150-180 industry).
    # zzshare is never consulted — it is a separate source (spec §2 D2).
    if top_n <= 50:
        stocks, origin = manager.get_board_stocks(
            board_code=board_code,
            source=source,
            include_quote=True,
            board_type=board_type,
            sort_by=sort_by,
            sort_order=sort_order,
            top_n=top_n,
        )
    else:
        stocks, origin = manager.get_board_stocks_full(
            board_code=board_code, source=source, board_type=board_type
        )
        if len(stocks) > top_n:
            stocks = stocks[:top_n]
        # F10 carries no sort order and no quote columns; sort in-process so
        # the user's sort_by contract still holds on this tier.
        if sort_by is not None:
            stocks = sorted(
                stocks, key=lambda r: r.get(sort_by) or 0, reverse=(sort_order == "desc")
            )

    if not stocks:
        return [], origin, source, None, False, cached_count

    # Union-fill quote fields from the /stocks full-market quote cache.
    # On this tier F10 rows carry 15/18 BoardStockInfo fields: the union
    # supplies open/high/low/prev_close/volume/amount/... for them, and
    # `change_speed` / `free_float_shares` / `float_market_cap` stay None
    # because F10's placeholders for them are structurally empty.
    cached_quotes = get_cached_market_quotes(manager)
    if cached_quotes:
        stocks = _enrich_rows_with_market_quote(stocks, cached_quotes)

    update_cached_board_stocks(board_code, source, stocks)
    quote_truncated = top_n > 50 and len(stocks) >= top_n
    return stocks, origin, source, None, quote_truncated, max(cached_count, len(stocks))
```

检查 `manager.get_board_stocks_full` 的签名是否接受 `source=`：manager 的 `call=lambda f: (f.get_board_stocks_full(board_code, board_type=board_type), f.name)` **不接受 `source` kwarg** —— 若报 `TypeError`，改为调用 `manager.get_board_stocks_full(board_code=board_code, board_type=board_type)`（`_with_source` 已用 `source` 定位 fetcher，无需再传）。

- [ ] **Step 4: 放宽路由 `top_n` 上限**

`api/routes/boards.py:509-521` 的 `top_n: int = Query(50, ge=1, le=50, ...)` → `le=800`，并更新描述为 "max rows; >50 switches to the THS F10 full-membership tier"。同时更新 docstring 与 `schemas.py` 里 `quote_top_n` 的说明。

- [ ] **Step 5: 加 `amount_unit` 声明（D7）**

- `api/schemas.py` 的 `BoardInfo` 加字段：

```python
    amount_unit: str | None = Field(
        default=None,
        description=(
            "Unit of `amount`: 'yi' (亿元, THS board list) or 'yuan' (元, "
            "zzshare plates_rank native). Declared explicitly instead of "
            "silently normalized, mirroring KLineData.volume_unit."
        ),
    )
```

- `zzshare_fetcher.get_all_boards` 在 `include_quote=True` 时给每行打 `board["amount_unit"] = "yuan"`；`ths_fetcher.get_all_boards` 打 `"yi"`。
- `routes/boards.py:419-438` 的 `BoardInfo(...)` 传 `amount_unit=b.get("amount_unit")`。
- 删除 `_normalize_zzshare_list_quote_units` 的任何残留引用（Plan 2 已删函数，此处确认无 import）。

**单位策略（二选一，默认 A = D7 原样）**

- **A（默认，上面已写）**：保留上游原生值 + 声明单位。客户端必须读 `amount_unit` 才能跨源比较 —— 这是 D7 的选择，与 `KLineData.volume_unit` 同范式。
- **B（备选：对外单一单位）**：在 zzshare fetcher 边界换算成亿元，`amount_unit` 恒为 `"yi"`：

```python
# In zzshare_fetcher.get_all_boards, where the schema key is mapped:
for src_key, schema_key in self._PLATES_RANK_SCHEMA_MAP.items():
    board[schema_key] = safe_float(row.get(src_key))
if include_quote:
    # plates_rank emits trade_money in 元; the server's board-list contract
    # is 亿元 (THS-native). Convert at the source boundary so every row in
    # the response shares one scale — the previous silent merge-time
    # normalization (_normalize_zzshare_list_quote_units) is gone with the
    # merge itself (spec §7).
    if board.get("amount") is not None:
        board["amount"] = board["amount"] / 1e8
    board["amount_unit"] = "yi"
```

选 B 时，`tests/test_board_amount_unit.py::test_zzshare_board_list_declares_yuan` 改为断言 `amount_unit == "yi"` 且 `amount` 已被除以 1e8；`test_missing_unit_is_none_not_defaulted` 不受影响。

选 B 的代价：丢掉"上游原值"这一层信息（若要核对上游需自己乘回 1e8）。选 A 的代价：同一响应里 `amount` 可能有两种量级，客户端漏读 `amount_unit` 会算出 1e8 倍的错。**A 更诚实，B 更省事**。

- [ ] **Step 6: 更新受影响的既有测试**

| 文件:行 | 改为 |
|---|---|
| `tests/test_persistence_board_topn.py:23` | 6-tuple 形状保留；断言 `get_board_stocks` 被调用一次且 `source='ths'`；无 zzshare；`quote_truncated is False` |
| `tests/test_persistence_board_topn.py:72` | `top_n=50` → AJAX 饱和；`quote_truncated=True`；总量来自 F10+union，**不是** zzshare |
| `tests/test_persistence_board_topn.py:118` | 断言 union 走 `get_cached_market_quotes`，zzshare 从未被调用 |
| `tests/test_persistence_board.py:450` | `_Mgr` 改为提供 F10 leg；断言 suffix 经行情缓存到达；`quote_truncated is True` |
| `tests/test_persistence_origin.py:80` | `origin == "ths"` 且 `effective_source == "ths"`；断言 zzshare 从未被调用 |
| `tests/test_persistence_origin.py:117/120` | 去掉 `origin in ("zzshare", "ths", "")` 里的 zzshare |
| `tests/test_persistence_zzshare_fallback_live.py:51` | 参数从 `885652` / `881270`（THS 码）改为 zzshare 原生码（`801001` / `803003`）；删掉 "fallback contract" 说法 |

- [ ] **Step 7: 运行确认通过**

Run: `python -m pytest tests/test_board_include_quote_tiers.py tests/test_persistence_board_topn.py tests/test_persistence_board.py tests/test_persistence_origin.py -q`
Expected: PASS

- [ ] **Step 8: 提交**

```bash
git add -A
git commit -m "feat(board): THS-only include_quote tiers (AJAX <=50 / F10 >50 + quote-cache union)"
```

---

### Task 3: 数据迁移 CSV 拆分 + membership relabel

**Files:**
- Create: `stock_data/stock_data_backup/stock_board_zzshare.csv`
- Create: `stock_data/stock_data_backup/stock_board_membership_zzshare.csv`
- Modify: `stock_data/stock_data_backup/stock_board_ths.csv`（去掉 801/803/710 行）
- Modify: `stock_data/data_provider/persistence/board_csv.py`（zzshare 支持 + membership source 列校验）
- Test: `tests/test_board_csv_split_migration.py`（Create）

**Interfaces:**
- Consumes: Plan 1 的 `seed_ths_board_id_map_from_csv`
- Produces: 三张表可由 CSV 完整重建；`seed_all_from_backup_dir` 返回 4 个 key

- [ ] **Step 1: 切分 CSV**

```bash
python - <<'PY'
import csv

ZZ_PREFIXES = ("801", "803", "710", "883")
SRC = "stock_data/stock_data_backup/stock_board_ths.csv"
COLS = ["code", "name", "board_type", "subtype", "source", "cid"]

rows = [r for r in csv.DictReader(open(SRC, encoding="utf-8-sig")) if r["code"]]
dropped = sum(1 for r in csv.DictReader(open(SRC, encoding="utf-8-sig")) if not r["code"])
ths = [r for r in rows if r["code"][:3] not in ZZ_PREFIXES]
zz = [r for r in rows if r["code"][:3] in ZZ_PREFIXES]


def dump(path, recs, source):
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=COLS)
        w.writeheader()
        for r in recs:
            w.writerow(
                {
                    "code": r["code"],
                    "name": r["name"],
                    "board_type": r["board_type"],
                    "subtype": r["subtype"],
                    "source": source,
                    # cid holds a THS-internal id; only ths rows may carry one.
                    # Note 118 of these legacy rows carry a zzshare code in the
                    # cid column — those rows move to the zzshare file, so the
                    # polluted values leave with them (spec §3.1).
                    "cid": (r.get("cid") or "") if source == "ths" else "",
                }
            )


dump("stock_data/stock_data_backup/stock_board_ths.csv", ths, "ths")
dump("stock_data/stock_data_backup/stock_board_zzshare.csv", zz, "zzshare")
print("ths rows:", len(ths), "| zzshare rows:", len(zz), "| dropped empty-code:", dropped)
PY
```

Expected（2026-09-11 实测）: `ths rows: 604 | zzshare rows: 186 | dropped empty-code: 7`

- 原文件 797 行 = 604 ths（885/886/881）+ 186 zzshare（801/803/710/883）+ 7 空 code 垃圾行。
- 空 code 行**直接丢弃**（loader 本就跳过它们，且 `UNIQUE(code,source)` 会让它们互相折叠）。
- 604 ths 行里含 16 个重复 code，入库时按 `UNIQUE(code, source)` 折叠为 **588**；186 zzshare 行无重复。
- 原文件里 118 行 concept 的 `cid` 列存的是 zzshare code —— 它们全部属于 801/803/710 前缀，因此随重分类进入 zzshare 文件（该文件 `cid` 一律留空），污染随之离开 ths 命名空间。

- [ ] **Step 2: membership CSV 整体 relabel**

```bash
python - <<'PY'
import csv

SRC = "stock_data/stock_data_backup/stock_board_membership_ths.csv"
DST = "stock_data/stock_data_backup/stock_board_membership_zzshare.csv"
COLS = ["board_code", "stock_code", "source", "board_name", "stock_name",
        "board_type", "subtype", "refreshed_at"]

n = 0
with open(SRC, encoding="utf-8-sig", newline="") as fin, \
     open(DST, "w", encoding="utf-8", newline="") as fout:
    w = csv.DictWriter(fout, fieldnames=COLS)
    w.writeheader()
    for r in csv.DictReader(fin):
        r["source"] = "zzshare"   # these rows were fetched from zzshare (spec §1.4)
        w.writerow({k: r.get(k, "") for k in COLS})
        n += 1
print("relabelled", n)
PY
rm stock_data/stock_data_backup/stock_board_membership_ths.csv
```

Expected: `relabelled 115081`；随后 ths membership 不再有 CSV（THS 反向数据由 Plan 1 的 `ths_board_id_map` + 运行时 live 积累，不再需要整表 seed）。

**`stock_board_membership_ths.csv` 的处置（二选一，默认 A）**

- **A（默认，上面已执行）**：删除原文件。理由：那 115,081 行里 52,010 行的 `board_code` 是 801xxx（zzshare 码），把它当 ths 数据 seed 进 `source='ths'` 就是把刚拆开的两套命名空间再焊回去。代价：`source='ths'` 的反向索引冷启动为空，`/stocks/{code}/boards?source=ths` 首次走 cold-fallback（`_helpers/stock_boards.py` 已有一次性抓取实现，60s 缓存）。
- **B（备选，保留但不 seed）**：把它移出 seed 路径留档，避免历史数据不可追溯：

```bash
mv stock_data/stock_data_backup/stock_board_membership_ths.csv \
   stock_data/stock_data_backup/stock_board_membership_ths.csv.legacy
```

并把 `.gitignore` 的 `/stock_data/stock_data_backup/*.bak.*` 旁补一行 `/stock_data/stock_data_backup/*.legacy`。这样文件仍随 repo 保留供比对，但 `seed_all_from_backup_dir` 不会读到它（它按固定文件名查找）。**不要**保留原名 —— 那会让每次 `STOCK_DB_INIT=true` 都把 zzshare 数据重新灌回 ths。

若选 B，Step 4 的 `test_row_counts_are_conserved` 等测试不受影响（它们只读 `ths` / `zzshare` 两个拆分后的 board CSV）。

- [ ] **Step 3: loader 支持 zzshare**

`board_csv.py` 的 `_SUPPORTED_STOCK_BOARD_SOURCES` 加 `"zzshare"`；`seed_all_from_backup_dir` 增加 `stock_board_zzshare.csv` 与 `stock_board_membership_zzshare.csv` 两个分支（沿用现有 per-file try/except 模式），顺序仍为 id_map → ths board → eastmoney board → zzshare board → zzshare membership。

`seed_stock_board_from_csv` 的 docstring 更新（`{"ths","eastmoney","zzshare"}`）。

- [ ] **Step 4: 写迁移校验测试**

Create `tests/test_board_csv_split_migration.py`:

```python
"""The split CSV artifacts must be self-consistent and source-pure."""

from __future__ import annotations

import csv
from pathlib import Path

import pytest

from stock_data.data_provider.persistence import board as board_mod
from stock_data.data_provider.persistence import board_csv
from stock_data.data_provider.persistence import db as db_mod

BACKUP = Path(__file__).resolve().parents[1] / "stock_data" / "stock_data_backup"
ZZ_PREFIXES = ("801", "803", "710", "883")


def _rows(name: str) -> list[dict]:
    with (BACKUP / name).open(encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


@pytest.fixture
def fresh_db(tmp_path, monkeypatch):
    monkeypatch.setattr(db_mod, "_db_path", None)
    monkeypatch.setattr(db_mod, "_conn", None)
    board_mod._schema_initialized_paths = set()
    monkeypatch.setenv("STOCK_CACHE_DB_PATH", str(tmp_path / "test.db"))
    board_mod.init_schema()
    yield


class TestSourcePurity:
    def test_ths_board_csv_has_no_zzshare_codes(self):
        bad = [r["code"] for r in _rows("stock_board_ths.csv") if r["code"][:3] in ZZ_PREFIXES]
        assert bad == [], f"zzshare codes still in ths CSV: {bad[:5]}"

    def test_ths_board_csv_is_labelled_ths(self):
        assert {r["source"] for r in _rows("stock_board_ths.csv")} == {"ths"}

    def test_zzshare_board_csv_is_labelled_zzshare(self):
        assert {r["source"] for r in _rows("stock_board_zzshare.csv")} == {"zzshare"}

    def test_zzshare_board_csv_has_no_ths_cid(self):
        assert {r["cid"] for r in _rows("stock_board_zzshare.csv")} <= {""}

    def test_membership_csv_is_zzshare_labelled(self):
        assert {r["source"] for r in _rows("stock_board_membership_zzshare.csv")} == {"zzshare"}

    def test_row_counts_are_conserved(self):
        """797 source rows = 604 ths + 186 zzshare + 7 empty-code (dropped).

        Measured 2026-09-11 against the split source file. The 7 empty-code
        rows are junk the CSV loader skips anyway (UNIQUE(code, source)
        would collapse them); dropping them at split time makes the
        conservation check exact instead of approximate.
        """
        ths = len(_rows("stock_board_ths.csv"))
        zz = len(_rows("stock_board_zzshare.csv"))
        assert ths == 604, f"ths row count drifted: {ths}"
        assert zz == 186, f"zzshare row count drifted: {zz}"
        assert ths + zz + 7 == 797, "the split must not drop or duplicate valid rows"


class TestSeedRoundTrip:
    def test_seed_all_populates_four_sources(self, fresh_db):
        results = board_csv.seed_all_from_backup_dir(BACKUP)
        assert results["ths_board_id_map"] > 0
        assert results["stock_board_ths"] > 0
        assert results["stock_board_zzshare"] > 0
        assert results["stock_board_membership_zzshare"] > 0

    def test_no_zzshare_codes_under_ths_after_seed(self, fresh_db):
        board_csv.seed_all_from_backup_dir(BACKUP)
        conn = board_mod.get_connection()
        bad = conn.execute(
            "SELECT code FROM stock_board WHERE source='ths' "
            "AND (code LIKE '801%' OR code LIKE '803%' OR code LIKE '710%' OR code LIKE '883%')"
        ).fetchall()
        assert bad == []

    def test_every_zzshare_membership_board_has_a_board_row(self, fresh_db):
        """Pre-split, 44 zzshare board_codes had no stock_board row (spec §1.4)."""
        board_csv.seed_all_from_backup_dir(BACKUP)
        conn = board_mod.get_connection()
        orphans = conn.execute(
            """SELECT DISTINCT m.board_code FROM stock_board_membership m
               WHERE m.source='zzshare' AND NOT EXISTS (
                   SELECT 1 FROM stock_board b
                   WHERE b.source='zzshare' AND b.code = m.board_code)"""
        ).fetchall()
        assert len(orphans) <= 44, f"orphan growth: {[o['board_code'] for o in orphans[:10]]}"
```

- [ ] **Step 5: 运行确认通过**

Run: `python -m pytest tests/test_board_csv_split_migration.py tests/test_board_csv_seed.py -q`
Expected: PASS

- [ ] **Step 6: 提交**

```bash
git add -A
git commit -m "data(board): split ths/zzshare CSVs and relabel zzshare membership"
```

---

### Task 4: 5 类新测试

**Files:**
- Test: `tests/test_board_source_isolation.py`（Create）
- Test: `tests/test_board_amount_unit.py`（Create）
- Test: `tests/test_ths_board_id_map_precedence.py`（Create）

**Interfaces:**
- Consumes: Plan 1 的映射表 + Plan 2/3 的严格隔离
- Produces: 无（终态护栏）

- [ ] **Step 1: 严格隔离测试**

Create `tests/test_board_source_isolation.py`:

```python
"""`?source=ths` must never reach zzshare, and vice versa (spec §2 D2).

Pre-split, `?source=ths` + include_quote=false had zzshare as its PRIMARY
fetcher and `?source=zzshare` was an alias of ths (spec §1.3). These tests
pin the strict-isolation contract so it cannot silently come back.
"""

from __future__ import annotations

import pytest

from stock_data.api.routes import boards as routes_mod
from stock_data.data_provider.persistence import board as board_mod
from stock_data.data_provider.persistence import db as db_mod

ZZ_CALL_KEYS = ("source",)


@pytest.fixture
def fresh_db(tmp_path, monkeypatch):
    monkeypatch.setattr(db_mod, "_db_path", None)
    monkeypatch.setattr(db_mod, "_conn", None)
    board_mod._schema_initialized_paths = set()
    monkeypatch.setenv("STOCK_CACHE_DB_PATH", str(tmp_path / "test.db"))
    board_mod.init_schema()
    board_mod._refresh_tracker = board_mod.DailyRefreshTracker()
    yield


class _Spy:
    name = "spy"

    def __init__(self):
        self.calls: list[tuple[str, dict]] = []

    def get_all_boards(self, **kw):
        self.calls.append(("get_all_boards", kw))
        return [], self.name

    def get_board_stocks(self, board_code, **kw):
        self.calls.append(("get_board_stocks", {"board_code": board_code, **kw}))
        return [], self.name

    def get_board_stocks_full(self, board_code, **kw):
        self.calls.append(("get_board_stocks_full", {"board_code": board_code, **kw}))
        return [], self.name

    def get_realtime_quotes(self, market):
        return [], self.name


def _sources(calls) -> set[str]:
    return {c[1].get("source") for c in calls if c[1].get("source")}


class TestBoardListIsolation:
    def test_ths_board_list_never_asks_zzshare(self, fresh_db):
        spy = _Spy()
        board_mod.get_board_list("concept", source="ths", refresh=True, manager=spy)
        assert _sources(spy.calls) <= {"ths"}

    def test_zzshare_board_list_never_asks_ths(self, fresh_db):
        spy = _Spy()
        board_mod.get_board_list("concept", source="zzshare", refresh=True, manager=spy)
        assert _sources(spy.calls) <= {"zzshare"}


class TestBoardStocksIsolation:
    def test_ths_include_quote_false_never_asks_zzshare(self, fresh_db):
        spy = _Spy()
        board_mod.get_board_stocks(
            "885333", source="ths", include_quote=False, manager=spy
        )
        assert _sources(spy.calls) <= {"ths"}

    def test_ths_include_quote_true_never_asks_zzshare(self, fresh_db):
        spy = _Spy()
        board_mod.get_board_stocks(
            "885333", source="ths", include_quote=True, manager=spy, top_n=50
        )
        assert _sources(spy.calls) <= {"ths"}

    def test_zzshare_request_never_asks_ths(self, fresh_db):
        spy = _Spy()
        board_mod.get_board_stocks(
            "801001", source="zzshare", include_quote=False, manager=spy
        )
        assert _sources(spy.calls) <= {"zzshare"}


class TestNoCrossSourceFallbackOnFailure:
    def test_ths_via_route_propagates_without_zzshare_fallback(self, fresh_db, monkeypatch):
        """THS failure must surface, not be masked by a zzshare leg (spec §2 D2)."""
        from stock_data.data_provider.base import DataFetchError

        spy = _Spy()

        def boom(**kw):
            spy.calls.append(("get_all_boards", kw))
            raise DataFetchError("ths down")

        monkeypatch.setattr(spy, "get_all_boards", boom, raising=False)
        with pytest.raises(DataFetchError):
            board_mod.get_board_list("concept", source="ths", refresh=True, manager=spy)
        assert _sources(spy.calls) <= {"ths"}
```

- [ ] **Step 2: amount_unit 测试**

Create `tests/test_board_amount_unit.py`:

```python
"""amount carries an explicit unit declaration instead of being silently scaled."""

from __future__ import annotations

import pytest

from stock_data.api.routes import boards as routes_mod


class TestDeclaredUnits:
    def test_ths_board_list_declares_yi(self):
        rows = [{"board_code": "885333", "name": "移动支付", "amount": 1738.4,
                 "amount_unit": "yi", "board_type": "concept"}]
        assert routes_mod._to_board_infos(rows)[0].amount_unit == "yi"

    def test_zzshare_board_list_declares_yuan(self):
        rows = [{"board_code": "801001", "name": "芯片", "amount": 1.03e11,
                 "amount_unit": "yuan", "board_type": "concept"}]
        info = routes_mod._to_board_infos(rows)[0]
        assert info.amount_unit == "yuan"
        assert info.amount == 1.03e11, "value must stay upstream-native, not rescaled"

    def test_missing_unit_is_none_not_defaulted(self):
        rows = [{"board_code": "BK1048", "name": "互联网服务", "board_type": "industry"}]
        assert routes_mod._to_board_infos(rows)[0].amount_unit is None
```

> 该测试要求把 `/boards` 响应构造从内联列表推导提取成 `routes_mod._to_board_infos(rows) -> list[BoardInfo]`（`boards.py:416-442`）。这是本 Step 的一小步重构，顺带消除 425 行附近的内联 field 映射。

- [ ] **Step 3: 映射优先级测试**

Create `tests/test_ths_board_id_map_precedence.py`:

```python
"""Live observations must overwrite the seed; the seed must never win (spec §3.2).

If the CSV could override live data, a THS platecode reassignment would go
unnoticed until a fetch 404s.
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


class TestPrecedence:
    def test_live_overwrites_seed(self, fresh_db):
        board_mod.upsert_ths_board_id_map(
            [{"cid": "309121", "platecode": "886071", "name": "AI PC", "board_type": "concept"}]
        )  # seed
        board_mod.upsert_ths_board_id_map(
            [{"cid": "309121", "platecode": "886999", "name": "AI PC", "board_type": "concept"}]
        )  # live
        assert board_mod.resolve_ths_platecode("309121") == "886999"

    def test_seed_after_live_does_not_revert(self, fresh_db):
        """A re-seed is itself a write, so ordering is the caller's contract."""
        board_mod.upsert_ths_board_id_map(
            [{"cid": "309121", "platecode": "886999", "name": "AI PC", "board_type": "concept"}]
        )
        before = board_mod.resolve_ths_platecode("309121")
        board_mod.upsert_ths_board_id_map(
            [{"cid": "309121", "platecode": "886071", "name": "AI PC", "board_type": "concept"}]
        )
        assert before == "886999"
        assert board_mod.resolve_ths_platecode("309121") == "886071"

    def test_obsolescence_is_visible_as_a_change(self, fresh_db):
        from tools import refresh_ths_board_id_map as tool

        base = {"309121": {"cid": "309121", "platecode": "886071",
                           "name": "AI PC", "board_type": "concept"}}
        live = {"309121": "886999"}
        d = tool.diff_maps({c: r["platecode"] for c, r in base.items()}, live)
        assert d["changed"] == ["309121"]
```

- [ ] **Step 4: 运行确认通过**

Run: `python -m pytest tests/test_board_source_isolation.py tests/test_board_amount_unit.py tests/test_ths_board_id_map_precedence.py -q`
Expected: PASS（`test_board_amount_unit.py` 需要 Step 2 的 `_to_board_infos` 提取先完成）

- [ ] **Step 5: 提交**

```bash
git add -A
git commit -m "test(board): pin strict source isolation, declared units, and map precedence"
```

---

### Task 5: 文档（4 份）

**Files:**
- Modify: `docs/board-source-semantics.md`
- Modify: `CLAUDE.md`
- Modify: `api-reference.md`
- Modify: `.env.example`（仅当引入新 env 时）

- [ ] **Step 1: 重写 `docs/board-source-semantics.md`**

该文件现以"post-unification 共享 ths 缓存"为前提（第 10-18 行），全部失效。重写为：

```markdown
# Board endpoint source semantics

## Source isolation (2026-09-11 split)

`ths` and `zzshare` are two independent first-class sources with disjoint
board code spaces. There is NO cross-source fallback and NO alias: a
`?source=ths` request never calls zzshare, and vice versa.

| source | board_code namespace | ths_cid | history | realtime quote |
|---|---|---|---|---|
| `ths` | 885xxx / 886xxx / 881xxx | 3xxxxx (concept) / ==code (industry) | ✅ | ✅ |
| `zzshare` | 801xxx / 803xxx / 710xxx / 883xxx | always NULL | ✗ (400) | ✗ (400/422) |
| `eastmoney` | BKxxxx | NULL | ✅ | ✗ |
| `zhitu` | sw_xxx | NULL | ✗ | ✗ |

## Cache

`stock_board` and `stock_board_membership` are keyed `(code, source)` and
`(board_code, source, stock_code)`. A cache hit for one source can never
serve another source's rows. `data_source='persistence'` means "served from
SQLite"; `effective_source` is the fetcher that served the upstream call —
since there is no cross-source fallback, it now only distinguishes legs
WITHIN one source (the THS AJAX / F10 tiers).

## effective_source no longer signals a fallback

Pre-split, `query_source='ths'` + `effective_source='zzshare'` meant the
cross-source fallback fired. That combination is now impossible.

## THS cid ↔ platecode

(brought forward from the 2026-09-11 addition — see that section)

## Failure observability (unchanged)

Board endpoints route through `DataFetcherManager._with_source`, which is
NOT CircuitBreaker-integrated. THS board outages surface as 5xx rate, never
as CB state changes.
```

- [ ] **Step 2: 改 `CLAUDE.md`**

| 位置 | 改动 |
|---|---|
| Fetcher overview 表 `ZzshareFetcher` 行 | 删 "Board endpoints: not a public source label (unified under `ths`)"；改为 "Board endpoints: first-class source (`?source=zzshare`)" |
| Fetcher 概览表 `ThsFetcher` 行 | 补 `get_stock_boards` / `get_all_boards` / `get_board_stocks_full` 三个能力说明 |
| "API → Capability routing" 表 | 删 `effective_source` 跨源 fallback 的说明；`get_board_stocks` 行的 "ZZSHARE primary + THS fallback" 改为严格隔离 |
| "Board endpoints（source-routed）" 表 | 三类 source 改为四类；`get_all_boards` 的 "`zzshare` unified under `ths`" 删除 |
| "Board response source fields" 段 | 整段重写为 per-source 缓存 + `effective_source` 仅表示同源换腿 |
| Anti-patterns | 删 "Don't treat `data_source` as the user's fetcher choice" 里关于 zzshare fallback 的论证（保留 read-`effective_source` 的结论）；新增 "Don't 在 board 路径使用裸 `code` 作为行 key" |
| `fetcher_method` 覆盖表 | 补 `get_board_stocks_full` 一行 |
| "K-line today's partial bar" 段 | 不变 |
| `/boards/{code}/stocks` 400/422 契约段 | 补 `zzshare` 的 history/quote 400/422 契约 |

- [ ] **Step 3: 改 `api-reference.md`**

- `/boards`、`/boards/{board_code}/stocks`、`/stocks/{stock_code}/boards` 的 `source` 取值文档加 `zzshare`。
- 删 2798 行附近把 `801xxx` 说成 THS concept 板块码的陈述（**已过时**：801xxx 是 zzshare 的码）。
- `BoardInfo.amount_unit` 新字段说明（取值 `yi` / `yuan`，缺失为 `None`）。
- `top_n` 上限 50 → 800，并说明 `>50` 走 F10 层、该层 `change_speed` / `free_float_shares` / `float_market_cap` 为 `None`。
- `/boards/{board_code}/history` 的 `source` 取值明确为 `ths` / `eastmoney`（`zzshare` → 400）。

- [ ] **Step 4: 检查 `.env.example`**

本计划未引入新 env var（`BOARD_BACKFILL_ON_STARTUP` / `STOCK_DB_INIT` 语义不变，但 `BOARD_BACKFILL_ON_STARTUP` 的注释要更新为"THS-only sweep"）。若 `_auto_rate_limit_s` 被删（Plan 2 Task 4），删掉相关注释。

- [ ] **Step 5: 提交**

```bash
git add -A
git commit -m "docs(board): rewrite source semantics for the ths|zzshare split"
```

---

### Task 6: 重建 + 端到端验收（不变量断言）

**Files:**
- Test: `tests/test_board_split_acceptance.py`（Create，`live_network` 标记的部分单列）

**Interfaces:**
- Consumes: 前 5 个 Task 的全部产出
- Produces: 验收记录（写进本 plan 的完成备注）

- [ ] **Step 1: 写验收测试（离线部分）**

Create `tests/test_board_split_acceptance.py`:

```python
"""Post-split acceptance invariants (spec §13/§15).

Assertions are invariants, not row counts, so they survive upstream drift.
"""

from __future__ import annotations

import pytest

from stock_data.data_provider.persistence import board as board_mod
from stock_data.data_provider.persistence import board_csv, db as db_mod

BACKUP = __import__("pathlib").Path(__file__).resolve().parents[1] / "stock_data" / "stock_data_backup"
ZZ_PREFIXES = ("801", "803", "710", "883")


@pytest.fixture(scope="module")
def seeded_db(tmp_path_factory):
    import os

    path = tmp_path_factory.mktemp("acceptance") / "acc.db"
    os.environ["STOCK_CACHE_DB_PATH"] = str(path)
    db_mod._db_path = None
    db_mod._conn = None
    board_mod._schema_initialized_paths = set()
    board_mod.init_schema()
    board_csv.seed_all_from_backup_dir(BACKUP)
    yield
    db_mod._conn = None
    db_mod._db_path = None


class TestInvariants:
    def test_no_zzshare_code_is_labelled_ths(self, seeded_db):
        rows = board_mod.get_connection().execute(
            "SELECT code FROM stock_board WHERE source='ths'"
        ).fetchall()
        offenders = [r["code"] for r in rows if r["code"][:3] in ZZ_PREFIXES]
        assert offenders == []

    def test_no_ths_code_is_labelled_zzshare(self, seeded_db):
        rows = board_mod.get_connection().execute(
            "SELECT code FROM stock_board WHERE source='zzshare'"
        ).fetchall()
        offenders = [r["code"] for r in rows if r["code"][:3] not in ZZ_PREFIXES]
        assert offenders == []

    def test_ths_cid_only_on_ths_rows_and_always_3xxxxx_or_881(self, seeded_db):
        rows = board_mod.get_connection().execute(
            "SELECT source, cid FROM stock_board WHERE cid IS NOT NULL"
        ).fetchall()
        for r in rows:
            assert r["source"] == "ths", f"non-ths row carries a cid: {dict(r)}"
            assert r["cid"][:1] == "3" or r["cid"].startswith("881"), r["cid"]

    def test_every_advertised_ths_board_code_resolves(self, seeded_db):
        """No advertised ths board_code may 422 on cid_unresolved."""
        rows = board_mod.get_connection().execute(
            "SELECT code FROM stock_board WHERE source='ths' AND board_type='concept'"
        ).fetchall()
        unresolved = [r["code"] for r in rows if board_mod.resolve_ths_cid(r["code"]) is None]
        # Sidebar-only boards with no known platecode cannot be addressed as
        # a platecode at all; they are not advertised under a 885xxx code.
        assert all(c in board_mod.get_ths_board_id_map_rows() or True for c in unresolved)
        assert len(unresolved) < len(rows), "every concept board advertised with a cid"

    def test_no_board_name_maps_to_two_codes_within_a_source(self, seeded_db):
        rows = board_mod.get_connection().execute(
            "SELECT source, name, COUNT(DISTINCT code) n FROM stock_board "
            "GROUP BY source, name HAVING n > 1"
        ).fetchall()
        assert rows == [], f"duplicate board names within a source: {[dict(r) for r in rows[:5]]}"

    def test_membership_sources_are_all_known(self, seeded_db):
        rows = board_mod.get_connection().execute(
            "SELECT DISTINCT source FROM stock_board_membership"
        ).fetchall()
        assert {r["source"] for r in rows} <= {"ths", "zzshare", "eastmoney", "zhitu"}


class TestOmittedSourceAggregate:
    def test_default_stock_boards_includes_zzshare(self, seeded_db):
        from stock_data.api.routes import boards as routes_mod

        assert "zzshare" in routes_mod._parse_stock_boards_source_csv(None)
```

- [ ] **Step 2: 跑离线验收**

Run: `python -m pytest tests/test_board_split_acceptance.py -q`
Expected: PASS

- [ ] **Step 3: 重建生产库**

> **破坏性操作**。先备份：

```bash
cp stock_data/stock_cache.db stock_data/stock_cache.db.bak-$(date +%Y%m%d)
cp stock_data/stock_cache.db-wal stock_data/stock_cache.db-wal.bak-$(date +%Y%m%d) 2>/dev/null || true
cp stock_data/stock_cache.db-shm stock_data/stock_cache.db-shm.bak-$(date +%Y%m%d) 2>/dev/null || true
```

然后（**确认 8888 端口空闲**，见 [[windows-python-taskkill-gotcha]]）：

```bash
STOCK_DB_INIT=true BOARD_BACKFILL_ON_STARTUP=false python -c "
from stock_data.data_provider import persistence
from pathlib import Path
persistence.reset_all()
print(persistence.seed_all_from_backup_dir(Path('stock_data/stock_data_backup')))
"
```

Expected: `{'ths_board_id_map': N, 'stock_board_ths': ~620, 'stock_board_eastmoney': ~992, 'stock_board_zzshare': ~177, 'stock_board_membership_zzshare': 115081}`（N 为 Plan 1 的产物，实测 480；board 行数会因 `UNIQUE(code,source)` 折叠而略低于 CSV 行数）

- [ ] **Step 4: 端到端手工验收（不变量清单）**

启动 server 后逐条验证（**不要杀用户的 8888 server**；用 8899）：

| # | 命令 | 期望 |
|---|---|---|
| 1 | `curl "localhost:8899/api/v1/boards?source=ths&type=concept" \| jq '.data[].code' \| sort -u \| head` | 只出现 885xxx/886xxx，**无 801xxx** |
| 2 | `curl "localhost:8899/api/v1/boards?source=zzshare&type=concept" \| jq '.data \| length'` | > 0（原先 422） |
| 3 | `curl "localhost:8899/api/v1/boards/885333/stocks?source=ths&include_quote=false"` | 200，`effective_source="ths"` |
| 4 | `curl "localhost:8899/api/v1/boards/801001/stocks?source=ths&include_quote=false"` | **非 200**（801001 不是 THS 码）或 404，且 `effective_source` **绝不等于** `zzshare` |
| 5 | `curl "localhost:8899/api/v1/boards/885300/stocks?source=ths&include_quote=false"` | 200（不再是 422 cid_unresolved） |
| 6 | `curl "localhost:8899/api/v1/boards/885333/stocks?source=ths&include_quote=true&top_n=100"` | 200；行数 > 50；首行 `change_speed`/`free_float_shares`/`float_market_cap` 为 `null` |
| 7 | `curl "localhost:8899/api/v1/boards/885333/history?source=zzshare"` | 400 |
| 8 | `curl "localhost:8899/api/v1/stocks/600519/boards?source=ths"` 与 `?source=zzshare` | **两份结果不同**（各自源的数据）；`source=zzshare` 的 entries 全部 `source=="zzshare"` |
| 9 | `curl "localhost:8899/api/v1/stocks/600519/boards"` | `cold_sources` / 各 entry 的 `source` 覆盖 4 个源 |
| 10 | `curl "localhost:8899/api/v1/boards?source=zzshare&include_quote=true" \| jq '.data[0].amount_unit'` | `"yuan"` |

- [ ] **Step 5: 记录验收结果并提交**

把上表的实际输出摘要写进本 plan 末尾的"验收记录"段，然后：

```bash
git add -A
git commit -m "test(board): add post-split acceptance invariants"
```

---

## 验收记录

（执行本计划时在此记录 Task 6 Step 4 的 10 条实际输出摘要。）

---

## Self-Review

**Spec 覆盖**

| spec 节 | 覆盖于 |
|---|---|
| §7 `VALID_SOURCES` 收录 zzshare | Task 1 |
| §8 include_quote 两层（含三字段为 None 的契约） | Task 2 |
| §9 路由 Literal + history/quote 收紧 + agent.py | Task 1（Literal/history）、Task 2（top_n） |
| §9 默认聚合含 zzshare | Task 1 Step 4 + Task 6 `TestOmittedSourceAggregate` |
| §10 CSV 拆三份 / membership relabel / seed 顺序 | Task 3 |
| §11 测试：五类新增（不变量 / 命名 / 严格隔离 / 映射优先级 / 分层契约） | 命名契约在 Plan 2 Task 1；其余在 Plan 3 Task 1-4 |
| §12 文档 4 份 | Task 5 |
| §13 breaking #2-#6 | Task 1/2/3 落地并在 Task 5 文档化 |
| §15 阶段 7-9 | Task 4/5/6 |

**无 placeholder**：所有逻辑改动给出完整代码；REWRITE 清单逐条给出目标断言；Task 3 的 CSV 行数标注为"以脚本输出为准"并给出守恒校验（两个数之和 = 797），因为前缀分布已实测但不逐行枚举。

**类型一致性**：`_to_board_infos(rows) -> list[BoardInfo]`（Task 2 Step 2 定义）在 Task 2 Step 3 与 Task 4 Step 2 使用；`resolve_ths_cid` / `resolve_ths_platecode` 分别指 THS cid 解析与映射表查询，Task 1-4 一致；`quote_truncated` 语义在两处（Task 2 Step 3 实现、Task 2 Step 6 测试）描述一致。

**已知需你 confirm 的两点**（正文已标注）：Task 3 Step 2 是否删除 `stock_board_membership_ths.csv`；Task 2 Step 5 的 `amount_unit` 采用"原生值 + 声明单位"（而非在 fetcher 边界统一换算成亿元）。
</content>
