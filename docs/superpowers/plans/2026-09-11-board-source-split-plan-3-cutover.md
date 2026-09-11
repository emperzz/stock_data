# board source 拆分 Plan 3 —— zzshare 公开 + include_quote 两层 + 文档与重建 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让 `zzshare` 成为公开可选 source（`?source=zzshare` 由 422 变 200），把 `include_quote=true` 改为 THS 单源两层（AJAX ≤50 / F10+行情缓存 >50），同步重写受影响的测试、更新 4 份文档、并在重建后的库上按不变量验收。

**Architecture:** 路由层的四个 source 白名单收敛为一套，`zzshare` 从别名改为真值；`/boards/{code}/history` 与 `/boards/{code}/quote` 对 zzshare 明确 400/422（zzshare 无对应上游能力）。`include_quote=true` 的 `top_n>50` 走 `get_board_stocks_full`（F10，无 50 上限）并用既有 `_enrich_rows_with_market_quote` 从 `/stocks` 全市场行情缓存补 quote。

**Tech Stack:** Python 3.10.11（`.venv/Scripts/python.exe`）/ SQLite / FastAPI / pytest / ruff

## Global Constraints

- 解释器一律用 **`.venv/Scripts/python.exe`**（CPython 3.10.11，含 `curl_cffi` / `akshare`）。**不要用系统 `python`**：`tests/conftest.py:131` 会在 `import curl_cffi` 处抛 `ModuleNotFoundError`，整套测试无法采集。CLAUDE.md 的 Common Commands 对此有硬性要求。
- 每个 Task 结束时 `python -m pytest -q` 与 `.venv/Scripts/python.exe -m ruff check .` 必须干净。
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

Run: `.venv/Scripts/python.exe -m pytest tests/test_board_source_allowlist.py -v`
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
- 只有**两处**是 `source: Literal[...]`，各加 `"zzshare"`：`boards.py:324`（`/boards`）与 `boards.py:464`（`/boards/{board_code}/stocks`）。
- **`/stocks/{stock_code}/boards` 不是 Literal**（早前版本说"848 的 `source: Literal[...]`"，那是 `type:` 那一行；该路由的 `source` 在 840-847，类型是 `str | None`，逗号分隔，别名逻辑在 `_parse_stock_boards_source_csv` 里）。它**不需要改类型**，只需 Step 4 后半段的解析器改动；`?source=zzshare` 由 422 变 200 靠的就是删掉别名映射。
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

- [ ] **Step 5: `/boards/{board_code}/quote` —— 它没有 `?source=` 参数，且 `?source=` 会被静默忽略**

**实测**：该路由（`boards.py:745-798`）只声明了 `board_code: str = Path(...)`，**没有 `source` 参数**，实现里硬编码 `source="ths"`（798 行）。因此 `curl ".../quote?source=zzshare"` **返回 200 的 THS 数据**，参数被 FastAPI 静默丢弃 —— 不是 400/422。（spec §9 早前写的"→ 400/422"是错的，已修正。）它的 docstring（764-775）与 `schemas.py::BoardQuoteResponse.source` 的说明**已经**写明"该路由不接受 `?source=`"，所以本次无需改代码，只做两件事：

1. 在 `api-reference.md` 的该端点参数表里显式写一句"**无 `source` 参数**；该端点固定 ths，其他 source 不支持板块实时行情"。
2. **加一条测试钉住"传了 `?source=` 也不改变行为"**（避免以后有人误以为它生效）：

```python
def test_board_quote_ignores_source_param(client, monkeypatch):
    """The quote route has no ?source= param — passing one must not 422
    and must not change the served source (spec §9, reviewed 2026-09-11)."""
    called: list[str] = []
    monkeypatch.setattr(
        "stock_data.data_provider.manager.DataFetcherManager.get_board_realtime",
        lambda self, board_code, source, **kw: (called.append(source) or {"code": board_code}, source),
    )
    r = client.get("/api/v1/boards/885333/quote?source=zzshare")
    assert r.status_code == 200, r.text
    assert called == ["ths"]
```

（放进 `tests/test_boards_api.py` 或 Plan 3 Task 4 的 `test_board_source_isolation.py` 均可。）

`/boards/{board_code}/news`（`boards.py:1209`）与 `/surges`（`:1251`）的 `source: Literal["ths"]` **保持不变** —— 它们是**真** 422，与 quote 不同，别一起改。

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

Run: `.venv/Scripts/python.exe -m pytest tests/test_board_source_allowlist.py tests/test_boards.py tests/test_boards_api.py tests/test_stock_boards_reverse_route.py tests/test_boards_history_route.py -q`
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
                  probed 2026-09-11: the F10 row template simply has no
                  such keys, and _enrich_rows_with_market_quote never
                  sets them either, so they stay None on this tier)
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

    def test_f10_structurally_absent_fields_stay_none(self, fresh_db, monkeypatch):
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
    def test_route_accepts_top_n_above_50(self, client):
        """Assert on the OpenAPI schema, not on source text.

        The earlier draft did `assert "le=50" not in
        inspect.getsource(routes_mod.get_board_stocks)`. That is a
        false-green: `@map_errors` / `@cache_endpoint` replace the module
        attribute with a WRAPPER (see CLAUDE.md's decorator-order rule), and
        `inspect.getsource` reports the wrapper's source — in errors.py — so
        the assertion passes no matter what the route body says.
        """
        schema = client.get("/openapi.json").json()
        params = schema["paths"]["/api/v1/boards/{board_code}/stocks"]["get"]["parameters"]
        top_n = next(p for p in params if p["name"] == "top_n")
        assert top_n["schema"]["maximum"] == 800, top_n
        assert top_n["schema"]["default"] == 50, top_n
```

- [ ] **Step 2: 运行确认失败**

Run: `.venv/Scripts/python.exe -m pytest tests/test_board_include_quote_tiers.py -v`
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
    quote_truncated = len(stocks) >= top_n
    return stocks, origin, source, None, quote_truncated, max(cached_count, len(stocks))
```

**`quote_truncated` 必须是 `len(stocks) >= top_n`，不能写 `top_n > 50 and …`**：AJAX 层（`top_n ≤ 50`）的上游硬上限就是 50，所以 `top_n=50` 且拿到 50 行时**就是被截断了**，标志必须为 `True`。（早前版本的 `top_n > 50 and …` 会让该分支恒为 `False`，而同一份计划的 `test_persistence_board_topn.py:72` 又断言 `quote_truncated is True` —— 自相矛盾。已修正为统一语义。）

**关于 `manager.get_board_stocks_full` 的 `source=`**：早前版本的担心是错的。公开方法是 `get_board_stocks_full(self, board_code: str, source: str, *, board_type=None) -> tuple[list[dict], str]`（`manager.py:1265-1271`）—— **`source` 是必需参数**；`manager.py:1288` 那个不含 `source` 的 `call=lambda f: (…)` 是包装器**内部**的 lambda，不是调用方约束。现有生产代码也是这么调的（`persistence/board.py:1149-1153`）。所以 `source=source` 照传；**千万别按早前版本的建议去掉它**，那会 `TypeError: missing 1 required positional argument: 'source'`。`ThsFetcher.get_board_stocks_full`（`ths_fetcher.py:2426`）签名末尾有 `**kwargs`，会静默吸收它。

**6-tuple 第 3 位是 `effective_source`**（`(stocks, origin, effective_source, reason, quote_truncated, quote_total_in_board)`）。严格隔离后新鲜路径上 `effective_source == origin == source`，写 `source` 是等价的；但**别把它和第 2 位的 `origin` 搞混** —— 缓存命中时 `origin` 是字面量 `"persistence"`。缓存命中早退分支的硬编码 `"ths"` 已在 Plan 2 Task 3 Step 3 改为 `source`。

- [ ] **Step 4: 放宽路由 `top_n` 上限**

`api/routes/boards.py:509-521` 的 `top_n: int = Query(50, ge=1, le=50, ...)` → `le=800`，并更新描述为 "max rows; >50 switches to the THS F10 full-membership tier"。同时更新 docstring 与 `schemas.py` 里 `quote_top_n` 的说明。

- [ ] **Step 5: `amount` 单位统一到亿元 + 新增 `amount_unit` 声明（**已选定 B**）**

**决策（2026-09-11 复核，选 B）**：换算**前移到 zzshare fetcher 边界**，对外 `amount` 只有一个量级（亿元），`amount_unit` 恒为 `"yi"`。原先 `_normalize_zzshare_list_quote_units`（`board.py:886-910`，由 Plan 2 删除）做的是 merge 期隐式换算——换算位置与"谁是权威"都藏在合并逻辑里。前移到 fetcher 之后，每个 source 自己声明自己的单位，merge 不存在了也就不需要换算层。

代价（明确写下）：丢掉"上游原值"这一层信息，若要核对上游需自己乘回 `1e8`。收益：客户端不必读 `amount_unit` 也能跨源比较；同一条响应不会出现两种量级。

1. `zzshare_fetcher.get_all_boards`（`zzshare_fetcher.py:729-731`）：映射之后把 `amount` 换算成亿元并声明单位：

```python
                if include_quote:
                    for src_key, schema_key in self._PLATES_RANK_SCHEMA_MAP.items():
                        board[schema_key] = safe_float(row.get(src_key))
                    # plates_rank emits trade_money in 元; the server's
                    # board-list contract is 亿元 (THS-native). Convert at
                    # the SOURCE boundary so every row of a response shares
                    # one scale — the old silent merge-time normalization
                    # (_normalize_zzshare_list_quote_units) is gone with the
                    # merge itself (spec §7, D7).
                    if board.get("amount") is not None:
                        board["amount"] = board["amount"] / 1e8
                    board["amount_unit"] = "yi"
```

2. `ths_fetcher.get_all_boards`：`include_quote=True` 时给每行打 `r["amount_unit"] = "yi"`（THS 板块清单的 `amount` 本来就是亿元，**不改数值**）。`include_quote=False` 两条路径都**不打** `amount_unit` —— 没有 `amount` 就没有单位声明，`None` 比默认值诚实。

3. `api/schemas.py` 的 `BoardInfo` 加字段（放在 `amount` 之后）：

```python
    amount_unit: str | None = Field(
        default=None,
        description=(
            "Unit of `amount`. Always 'yi' (亿元) on the board-list path — "
            "zzshare's native 元 is converted at its fetcher boundary. "
            "`None` means the row carries no `amount` at all "
            "(include_quote=false). Mirrors KLineData.volume_unit."
        ),
    )
```

4. `routes/boards.py` 的 `BoardInfo(...)` 构造传 `amount_unit=b.get("amount_unit")`（见 Step 2 一起抽出的 `_to_board_infos`）。

5. **清掉 `_normalize_zzshare_list_quote_units` 的全部残留引用**（函数本身由 Plan 2 Task 2 删；这些是文字引用）：`api/schemas.py:2136`（`BoardMoverEntry` docstring，Plan 2 Task 2 Step 6 已列）、`api/routes/agent.py:1497`（Plan 2 已列）、**`api-reference.md:587` 与 `:2802`（Plan 3 Task 5 Step 3 处理）**。核对命令：

```bash
grep -rn "_normalize_zzshare_list_quote_units" stock_data/ docs/ api-reference.md CLAUDE.md
```

6. `tests/test_board_amount_unit.py` 按 B 写（见 Task 4 Step 2）：`test_zzshare_board_list_declares_yi` 断言 `amount_unit == "yi"`；再加一条钉住 fetcher 边界换算的用例：

```python
    def test_zzshare_fetcher_converts_trade_money_to_yi(self, monkeypatch):
        """plates_rank emits 元; the fetcher must emit 亿元 (D7/B)."""
        from stock_data.data_provider.fetchers.zzshare_fetcher import ZzshareFetcher

        f = ZzshareFetcher()
        monkeypatch.setattr(f, "_ensure_api", lambda: None)
        monkeypatch.setattr(
            ZzshareFetcher,
            "_api",
            type("A", (), {"plates_rank": lambda self, **kw: [
                {"plate_code": "801001", "plate_name": "芯片",
                 "trade_money": 1.03e11, "rate": 1.0, "market_cap_cir": 5.0e12}
            ]})(),
        )
        rows = f.get_all_boards(board_type="concept", include_quote=True)
        assert rows
        assert rows[0]["amount"] == pytest.approx(1030.0)  # 1.03e11 元 → 亿元
        assert rows[0]["amount_unit"] == "yi"
```

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

Run: `.venv/Scripts/python.exe -m pytest tests/test_board_include_quote_tiers.py tests/test_persistence_board_topn.py tests/test_persistence_board.py tests/test_persistence_origin.py -q`
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
ths_raw = [r for r in rows if r["code"][:3] not in ZZ_PREFIXES]
zz = [r for r in rows if r["code"][:3] in ZZ_PREFIXES]


def is_ths_cid(v):
    """Same guard as persistence.board._is_ths_cid (spec §4 rule 6)."""
    return (
        isinstance(v, str)
        and len(v) == 6
        and v.isascii()
        and v.isdigit()
        and (v.startswith("3") or v.startswith("881"))
    )


def collapse(recs):
    """One row per `code`, deterministically.

    16 ths codes appear twice in the source file. `seed_stock_board_from_csv`
    uses INSERT OR REPLACE on UNIQUE(code, source), so the LAST row in the
    file wins — and for 885940 ("WiFi 6") the last row carries the polluted
    `cid=885940` while the FIRST carries the real `cid=308791`. Letting the
    loader decide would silently lose that cid (and with it the AJAX leg for
    that board). Collapsing here with an explicit preference makes the CSV
    self-consistent and the loader's collapse a no-op.
    """
    out: dict[str, dict] = {}
    for r in recs:
        prev = out.get(r["code"])
        if prev is None:
            out[r["code"]] = r
            continue
        # Prefer a real THS cid, then any non-empty cid, then the earlier row.
        if not is_ths_cid(prev.get("cid")) and is_ths_cid(r.get("cid")):
            out[r["code"]] = r
        elif not (prev.get("cid") or "") and (r.get("cid") or ""):
            out[r["code"]] = r
    return list(out.values())


ths = collapse(ths_raw)


nulled = 0


def dump(path, recs, source):
    global nulled
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=COLS)
        w.writeheader()
        for r in recs:
            cid = r.get("cid") or ""
            if source == "ths":
                # 110 legacy concept rows have cid == code == 885xxx/886xxx
                # (the pre-2026-07-20 layout wrote a platecode into the cid
                # column). Keeping them would put a platecode into
                # stock_board.cid, violating spec §4 rule 6 and feeding a
                # platecode to the AJAX leg as if it were a cid.
                if cid and not is_ths_cid(cid):
                    nulled += 1
                    cid = ""
            else:
                cid = ""  # spec §4 rule 3: zzshare rows carry no THS cid
            w.writerow(
                {
                    "code": r["code"],
                    "name": r["name"],
                    "board_type": r["board_type"],
                    "subtype": r["subtype"],
                    "source": source,
                    "cid": cid,
                }
            )


dump("stock_data/stock_data_backup/stock_board_ths.csv", ths, "ths")
dump("stock_data/stock_data_backup/stock_board_zzshare.csv", zz, "zzshare")
print("ths raw:", len(ths_raw), "-> collapsed:", len(ths),
      "| zzshare rows:", len(zz),
      "| dropped empty-code:", dropped, "| collapsed dups:", len(ths_raw) - len(ths),
      "| cid nulled:", nulled)
PY
```

Expected（2026-09-11 实测）: `ths raw: 604 -> collapsed: 588 | zzshare rows: 186 | dropped empty-code: 7 | collapsed dups: 16 | cid nulled: 109`

- 原文件 797 行 = 604 ths（885=397 / 886=103 / 881=104）+ 186 zzshare（801=177 / 803=7 / 710=1 / 883=1）+ 7 空 code 行。
- 空 code 行**直接丢弃**（loader 本就跳过它们）。
- **16 个 ths code 在源文件里出现两次**，由 `collapse()` 在拆分期确定性折叠（见该函数 docstring：loader 的 last-wins 会丢掉 `885940` 的真实 cid `308791`）。**输出 CSV 无重复 code**，LOADER 的 `UNIQUE(code, source)` 折叠因此成为 no-op —— 这条守恒链是可断言的，而不是"加载时才知道"。
- `cid` 置空：**109 行**。其中 110 行是 `cid == code == 885/886` 的旧布局污染，但 16 个重复 code 折叠掉 16 行，被折叠掉的那 16 行里恰好有 1 行是污染行（`885940`，保留了带真实 cid 的那行），所以净置空 = 110 − 1 = **109**。
- 另有 15 行 `cid` 本就为空。
- **早前版本说"118 行 cid 里的污染随 zzshare 行一起离开 ths 命名空间"是错的**：那 118 行里只有 8 行的 `code` 属于 801/803/710/883 前缀（因而进 zzshare 文件）；剩下 **110 行的 `code` 是 885/886，会留在 ths 文件里**，必须显式置空 `cid`。这正是 Task 6 的不变量 `test_ths_cid_only_on_ths_rows_and_always_3xxxxx_or_881` 要钉的东西——不置空它直接红。
- 置空 + 折叠后 ths 文件的 `cid` 分布：**479 行合法 cid + 109 行空 = 588** ✓
- 守恒核对：797 = 588（ths 输出）+ 186（zzshare 输出）+ 16（折叠的重复 code）+ 7（空 code 丢弃）

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

**`stock_board_membership_ths.csv` 的处置（**已选定 A：删除原文件**）**

理由：那 115,081 行里 **52,010 行**的 `board_code` 是 801xxx（zzshare 码），把它当 ths 数据 seed 进 `source='ths'` 就是把刚拆开的两套命名空间再焊回去。代价：`source='ths'` 的反向索引冷启动为空，`/stocks/{code}/boards?source=ths` 首次走 cold-fallback（`_helpers/stock_boards.py` 已有一次性抓取实现，60s 缓存）。

**唯一不能做的是"保留原名"** —— 那会让每次 `STOCK_DB_INIT=true` 都把 zzshare 数据重新灌回 `source='ths'`。若日后要留档，用 `mv … .legacy` + 在 `.gitignore` 的 `/stock_data/stock_data_backup/*.bak.*` 旁补 `/stock_data/stock_data_backup/*.legacy`（`seed_all_from_backup_dir` 按固定文件名查找，`.legacy` 不会被读到）；本轮选择直接删，历史仍在 git 里。

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

    def test_ths_board_csv_cid_column_is_only_real_cids(self):
        """spec §4 rule 6 + the 110-row legacy pollution (§3.1).

        These 110 rows stay in the ths file (their `code` is 885/886), so
        if the split forgets to null their `cid`, this is where it shows.
        """
        def _is_cid(v: str) -> bool:
            return len(v) == 6 and v.isascii() and v.isdigit() and (
                v.startswith("3") or v.startswith("881")
            )

        bad = [r["cid"] for r in _rows("stock_board_ths.csv") if r["cid"] and not _is_cid(r["cid"])]
        assert bad == [], f"platecode-shaped cid survived the split: {bad[:5]}"

    def test_ths_board_csv_cid_nulled_count(self):
        """479 real cids + 109 blank == 588 (measured 2026-09-11).

        Blank = 15 rows that were already blank + 110 polluted rows nulled
        − 1 polluted row that disappeared in the 16-code de-duplication.
        """
        rows = _rows("stock_board_ths.csv")
        blank = sum(1 for r in rows if not r["cid"])
        real = sum(1 for r in rows if r["cid"])
        assert (real, blank) == (479, 109), f"got real={real} blank={blank}"

    def test_no_duplicate_board_codes_in_either_file(self):
        """The split must de-duplicate: the loader's INSERT OR REPLACE is
        last-wins, and for 885940 the last source row carries the polluted
        cid — letting the loader decide would silently lose cid 308791."""
        for name in ("stock_board_ths.csv", "stock_board_zzshare.csv"):
            codes = [r["code"] for r in _rows(name)]
            dups = sorted({c for c in codes if codes.count(c) > 1})
            assert dups == [], f"{name} still has duplicate codes: {dups[:5]}"

    def test_885940_keeps_its_real_cid(self):
        """The one code whose de-duplication choice is load-bearing."""
        by_code = {r["code"]: r for r in _rows("stock_board_ths.csv")}
        assert by_code["885940"]["cid"] == "308791"

    def test_membership_csv_is_zzshare_labelled(self):
        assert {r["source"] for r in _rows("stock_board_membership_zzshare.csv")} == {"zzshare"}

    def test_row_counts_are_conserved(self):
        """797 source rows = 588 ths + 186 zzshare + 16 collapsed dup + 7 empty-code.

        Measured 2026-09-11 against the split source file. The 7 empty-code
        rows are junk the loader skips anyway; the 16 duplicate ths codes
        are collapsed BY THE SPLIT (deterministically, preferring a real
        cid) rather than by the loader's last-wins INSERT OR REPLACE.
        """
        ths = len(_rows("stock_board_ths.csv"))
        zz = len(_rows("stock_board_zzshare.csv"))
        assert ths == 588, f"ths row count drifted: {ths}"
        assert zz == 186, f"zzshare row count drifted: {zz}"
        assert ths + zz + 16 + 7 == 797, "the split must not drop or duplicate valid rows"


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

Run: `.venv/Scripts/python.exe -m pytest tests/test_board_csv_split_migration.py tests/test_board_csv_seed.py -q`
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

    def test_zzshare_board_list_declares_yi(self):
        """D7/B: the 元→亿元 conversion happens in the fetcher, so the route
        layer sees 亿元 + `"yi"` for every source."""
        rows = [{"board_code": "801001", "name": "芯片", "amount": 1030.0,
                 "amount_unit": "yi", "board_type": "concept"}]
        info = routes_mod._to_board_infos(rows)[0]
        assert info.amount == 1030.0
        assert info.amount_unit == "yi"

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

Run: `.venv/Scripts/python.exe -m pytest tests/test_board_source_isolation.py tests/test_board_amount_unit.py tests/test_ths_board_id_map_precedence.py -q`
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

该文件现以"post-unification 共享 ths 缓存"为前提（第 10-18 行 = `## Board Cache Source-Normalization`），第 20-45 行是 `effective_source` 段，**两段都失效**。

**但不要整文件替换** —— 早前版本给的替换稿把两个**仍然有效**的小节丢掉了：

- `## Board endpoint failure observability`（现第 47-57 行）
- `## Persistence ↔ manager bidirectional coupling (audit §M3)`（现第 59-68 行）

那两节的结论本次没有推翻（`_with_source` 仍不与 CircuitBreaker 集成；persistence↔manager 的耦合站点只是变少，没有消失）。改法是**只替换 10-45 行**，保留 47 行之后，并把 Plan 1 Task 5 Step 4 追加的 `## THS cid ↔ platecode` 一节与下面的新内容合并（不要出现"brought forward — see that section"这种占位句）。

替换稿（10-45 行 → 以下内容）：

```markdown
## Source isolation (2026-09-11 split)

`ths` and `zzshare` are two independent first-class sources with disjoint
board code spaces. There is NO cross-source fallback and NO alias: a
`?source=ths` request never calls zzshare, and vice versa.

| source | board_code namespace | ths_cid | history | realtime quote |
|---|---|---|---|---|
| `ths` | 885xxx / 886xxx / 881xxx | 3xxxxx (concept) / ==code (industry) / NULL | ✅ | ✅ |
| `zzshare` | 801xxx / 803xxx / 710xxx / 883xxx | always NULL | ✗ (400) | ✗ |
| `eastmoney` | BKxxxx | NULL | ✅ | ✗ |
| `zhitu` | sw_xxx | NULL | ✗ | ✗ |

`/boards/{code}/quote` takes **no `?source=` parameter at all** — it is
hardcoded to ths, and an unexpected `?source=` is silently ignored (not
422). `/boards/{code}/news` and `/surges` DO declare `Literal["ths"]` and
therefore really do 422 on any other value.

## Cache

`stock_board` and `stock_board_membership` are keyed `(code, source)` and
`(board_code, source, stock_code)`. A cache hit for one source can never
serve another source's rows. `data_source='persistence'` means "served from
SQLite"; `effective_source` is the fetcher that served — since there is no
cross-source fallback, it only ever distinguishes legs WITHIN one source
(the THS AJAX ≤50 / F10 >50 tiers).

## effective_source no longer signals a fallback

Pre-split, `query_source='ths'` + `effective_source='zzshare'` meant the
cross-source fallback fired. That combination is now impossible. The
cache-hit early return used to hardcode `effective_source='ths'`; it now
reports the row's own `source` (2026-09-11).

## THS cid ↔ platecode

THS gives every concept board two identifiers: a public `platecode`
(885xxx / 886xxx) and an internal `cid` (3xxxxx). They are NOT
interchangeable — the gn AJAX constituent endpoint takes the cid, the F10
page and board K-line take the platecode. Industry boards use one value
(881xxx) for both.

`ths_board_id_map` (SQLite) is the single cid → platecode lookup. It is
seeded at startup from `stock_data/stock_data_backup/ths_board_id_map.csv`
and refreshed by `.venv/Scripts/python.exe -m
stock_data.tools.refresh_ths_board_id_map --apply`, which sweeps THS's own
`GET /gn/` (gnSection pair) and falls back to one
`/gn/detail/code/{cid}/` request per unresolved board. The runtime board
path additionally resolves an individual miss on demand and writes the
result back, so each board costs at most one detail-page request ever.

**The CSV is a snapshot, never authoritative.** It only contains pairs THS
has shown us at some point; live observations must always overwrite it, or
a THS renumbering would go unnoticed until a fetch 404s. The refresh tool
prints an added / changed / removed diff for exactly that reason.

A `ths_cid` value is always a real cid or NULL — never a platecode. The
110 legacy rows that had `cid == code == 885xxx/886xxx` had their `cid`
cleared during the 2026-09-11 CSV split.
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
| `fetcher_method` 覆盖表（`CLAUDE.md:122-134`） | **不能补 `get_board_stocks_full` 一行** —— `EndpointMeta.fetcher_method` 是**单个标量**（`api/endpoint_meta.py:55`），`/boards/{board_code}/stocks` 已经声明了 `get_board_stocks`。F10 只是该端点的**内部层**（`top_n>50`），不是独立端点，无法用现有 schema 表达。改为在 `get_board_stocks` 那一行补一句"（`top_n>50` 时内部换 `get_board_stocks_full`）" |
| "K-line today's partial bar" 段 | 不变 |
| `/boards/{code}/stocks` 400/422 契约段 | 补 `zzshare` 的 history 400 契约；补 quote 端点"无 `?source=` 参数、传了被忽略"（**不是** 400/422，见 Task 1 Step 5） |
| 环境变量段（`fetcher_method` 表附近 / Configuration 段） | **`THS_ENABLED=false` 与 `ZZSHARE_ENABLED=false` 的 blast-radius 说明已失效**（CLAUDE.md 与 `.env.example:110-120` 都写着"board cache 恒 keyed source='ths'，且 `?source=zzshare` 被 alias 成 ths"）。改为：`THS_ENABLED=false` 仍会打断 ths 侧全部 board 端点，但 **zzshare 侧的 `/boards?source=zzshare` 依然可用**（不再互相依赖）；`ZZSHARE_ENABLED=false` 只影响 zzshare 侧端点与 zzshare membership 的 lazy fill，**不再有"调用方没点名的内部链路"** |
| Persistence ↔ manager coupling 段 | 站点减少（merge/fallback 两个函数被删），但方向性结论不变；`docs/board-source-semantics.md` 的小节保留 |

- [ ] **Step 3: 改 `api-reference.md`**

逐条给出**实际存在的**位置（早前版本只点了 2798，其余是"凭印象"的）：

| 位置 | 改动 |
|---|---|
| `506-509` | source 标签总表：`zzshare` 由"alias"改为独立 source；补四源列表 |
| `511-521` | **alias 行为矩阵整段作废**（现在写着 `/boards` + `/boards/{code}/stocks` 对 zzshare → 422、`/stocks/{code}/boards` → alias、`/boards/{code}/history` → alias）。重写为：前两者 → 200（真源）；`/stocks/{code}/boards` → 200（真源，默认聚合含 zzshare）；`/boards/{code}/history` → 400 |
| `548` | `/boards` 的 `source` 取值：`ths`,`eastmoney`,`zhitu` → 加 `zzshare` |
| `621` | `/boards/{board_code}/stocks` 的 "`?source=zzshare` returns 422" → 改为 200 |
| `618-623` | **该端点的参数表没有 `top_n`**（只有 `source`/`include_quote`/`refresh`），所以"把 `top_n` 上限 50 改成 800"**不是改文字，是新增**：补 `top_n` / `sort_by` / `sort_order` 三行，并写明"`top_n>50` 切换到 THS F10 整表层（无 50 上限，上限 800），该层 `change_speed` / `free_float_shares` / `float_market_cap` 恒为 `None`" |
| `634` | `/stocks/{stock_code}/boards` 的 "`zzshare` is accepted as alias for `ths`" → 删除，改为独立 source |
| `670` | `/boards/{board_code}/history` 的 "`zzshare` is accepted and aliased to `ths`" → 改为 "`zzshare` → 400（zzshare 无板块 K 线上游）" |
| `746-798` 对应的文档段 | 补一句"该端点**没有 `source` 参数**，固定 ths；传入 `?source=` 会被忽略（不报错）" |
| `1604` | `POST /agent/boards/filter-stocks` 的 "`zzshare` returns 422" → 200 |
| `2476` / `2534` | agent 端点的 `boards` 标签 source → 加 `zzshare` |
| `2798` | 删/改 "Board code (THS platecode; e.g. `881154` industry, `885642` / `801xxx` concept)" —— `801xxx` **不是** THS 码 |
| `587` 与 `2802` | 两处引用 `_normalize_zzshare_list_quote_units`（Plan 2 已删该函数）→ 改写为"zzshare 的 `amount` 在 fetcher 边界换算成亿元" |
| `BoardInfo` 字段表 | 新增 `amount_unit` 行（恒 `"yi"`；`None` 表示该行无 `amount`） |

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
    """Seed a throwaway DB once for the module, then put globals back.

    Module scope is deliberate (115k membership rows are slow to re-seed),
    which means ``monkeypatch`` is unavailable. So the env var, the
    memoised ``db._db_path``/``db._conn``, and
    ``board_mod._schema_initialized_paths`` must be saved and restored BY
    HAND — otherwise every later test in the session re-resolves
    ``get_db_path()`` to this temp file (it stays set after teardown) and
    the suite order starts mattering.
    """
    import os

    path = tmp_path_factory.mktemp("acceptance") / "acc.db"
    saved_env = os.environ.get("STOCK_CACHE_DB_PATH")
    saved_db_path = db_mod._db_path
    saved_conn = db_mod._conn
    saved_schema = board_mod._schema_initialized_paths

    os.environ["STOCK_CACHE_DB_PATH"] = str(path)
    db_mod._db_path = None
    db_mod._conn = None
    board_mod._schema_initialized_paths = set()
    try:
        board_mod.init_schema()
        board_csv.seed_all_from_backup_dir(BACKUP)
        yield
    finally:
        temp_conn = db_mod._conn
        if temp_conn is not None and temp_conn is not saved_conn:
            temp_conn.close()
        db_mod._conn = saved_conn
        db_mod._db_path = saved_db_path
        board_mod._schema_initialized_paths = saved_schema
        if saved_env is None:
            os.environ.pop("STOCK_CACHE_DB_PATH", None)
        else:
            os.environ["STOCK_CACHE_DB_PATH"] = saved_env


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

    def test_advertised_cids_agree_with_the_id_map(self, seeded_db):
        """Every ths row that carries a cid must agree with ths_board_id_map.

        This is the real cross-artifact invariant: it ties the board table
        (seeded from stock_board_ths.csv) to the map table (seeded from
        ths_board_id_map.csv) — both come from the same source file, so a
        disagreement means one of the two loaders or the split is wrong.

        Verified on the split artifacts 2026-09-11: all 479 ths rows with a
        non-NULL cid satisfy `resolve_ths_platecode(cid) == code`, and all
        104 industry rows are identity (`cid == code == 881xxx`).

        NOTE: the earlier draft of this test ended in
        `assert all(… or True for c in unresolved)` — a tautology that
        asserts nothing. Do not reintroduce that shape.
        """
        rows = board_mod.get_connection().execute(
            "SELECT code, cid, board_type FROM stock_board "
            "WHERE source='ths' AND cid IS NOT NULL"
        ).fetchall()
        assert rows, "seeded ths rows must carry cids"
        mismatched = [
            (r["code"], r["cid"], board_mod.resolve_ths_platecode(r["cid"]))
            for r in rows
            if board_mod.resolve_ths_platecode(r["cid"]) != r["code"]
        ]
        assert mismatched == [], f"cid/board_code disagree with the map: {mismatched[:5]}"

    def test_no_ths_board_code_is_a_bare_cid(self, seeded_db):
        """spec §4 rule 2: a cid must never be written into board_code.

        (881xxx industry codes are exempt — there cid == code by design.)
        """
        rows = board_mod.get_connection().execute(
            "SELECT code FROM stock_board WHERE source='ths'"
        ).fetchall()
        offenders = [
            r["code"] for r in rows
            if r["code"].startswith("3") and not r["code"].startswith("881")
        ]
        assert offenders == [], f"bare cids leaked into board_code: {offenders}"

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

Run: `.venv/Scripts/python.exe -m pytest tests/test_board_split_acceptance.py -q`
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

Expected（2026-09-11 实测口径）:

```
{'ths_board_id_map': 480, 'stock_board_ths': 588, 'stock_board_eastmoney': 992,
 'stock_board_zzshare': 186, 'stock_board_membership_zzshare': 115081}
```

- `stock_board_ths` 是 **588**，与拆分后的 CSV 行数**一致**（Task 3 的 `collapse()` 已经去重，loader 不再折叠任何东西）。
- `stock_board_zzshare` 是 **186**（早前写的 `~177` 是 801 前缀的行数，漏算了 803/710/883 共 9 行）。
- `stock_board_eastmoney` 992（该文件 992 行，无重复 code）。

- [ ] **Step 4: 端到端手工验收（不变量清单）**

启动 server 后逐条验证（**不要杀用户的 8888 server**；用 8899）：

| # | 命令 | 期望 |
|---|---|---|
| 1 | `curl "localhost:8899/api/v1/boards?source=ths&type=concept" \| jq '.data[].code' \| sort -u \| head` | 只出现 885xxx/886xxx，**无 801xxx** |
| 2 | `curl "localhost:8899/api/v1/boards?source=zzshare&type=concept" \| jq '.data \| length'` | > 0（原先 422） |
| 3 | `curl "localhost:8899/api/v1/boards/885333/stocks?source=ths&include_quote=false"` | 200，`effective_source="ths"` |
| 4 | `curl "localhost:8899/api/v1/boards/801001/stocks?source=ths&include_quote=false"` | **非 200**：THS 拿一个 zzshare 码去查，F10 页无此板块 → 空结果 → 路由把空映射为 **404**（若上游直接报错则 503）。`effective_source` **绝不等于** `zzshare`（这一条就是 D2 的反例检测） |
| 5 | `curl "localhost:8899/api/v1/boards/885300/stocks?source=ths&include_quote=false"` | 200（不再是 422 cid_unresolved） |
| 6 | `curl "localhost:8899/api/v1/boards/885333/stocks?source=ths&include_quote=true&top_n=100"` | 200；行数 > 50；首行 `change_speed`/`free_float_shares`/`float_market_cap` 为 `null` |
| 7 | `curl "localhost:8899/api/v1/boards/885333/history?source=zzshare"` | 400 |
| 8 | `curl "localhost:8899/api/v1/stocks/600519/boards?source=ths"` 与 `?source=zzshare` | **两份结果不同**（各自源的数据）；`source=zzshare` 的 entries 全部 `source=="zzshare"` |
| 9 | `curl "localhost:8899/api/v1/stocks/600519/boards"` | `cold_sources` / 各 entry 的 `source` 覆盖 4 个源 |
| 10 | `curl "localhost:8899/api/v1/boards?source=zzshare&include_quote=true" \| jq '.data[0].amount_unit'` | `"yi"`（D7/B：zzshare 在 fetcher 边界已换算成亿元） |
| 11 | `curl "localhost:8899/api/v1/boards/885333/quote?source=zzshare"` | **200**，且返回 THS 数据 —— 该端点没有 `source` 参数，`?source=` 被静默忽略（**不是** 400/422，见 Task 1 Step 5） |
| 12 | `curl "localhost:8899/api/v1/boards/885333/stocks?source=ths&include_quote=true&top_n=50"` | `quote_truncated` 在拿到 50 行时为 `true`（`len(stocks) >= top_n`，**不是** `top_n > 50 and …`） |

- [ ] **Step 5: 记录验收结果并提交**

把上表的实际输出摘要写进本 plan 末尾的"验收记录"段，然后：

```bash
git add -A
git commit -m "test(board): add post-split acceptance invariants"
```

---

## 验收记录（2026-09-11，inline）

Plan 3 已落地（commit `bb71b05` → `fbf9465` → `649563f` → `c1a5296` → `9e5a071`）。全量 `.venv/Scripts/python.exe -m pytest -q` = **2767 passed, 2 skipped, 0 failed**。

### 重建结果（实测）

`STOCK_DB_INIT=true` + `reset_all()` + `seed_all_from_backup_dir`：

```
{'ths_board_id_map': 479, 'stock_board_ths': 588, 'stock_board_eastmoney': 992,
 'stock_board_zzshare': 186, 'stock_board_membership_zzshare': 115081}
```

（`ths_board_id_map` 是 479 而非 480 —— 见下面的缺陷 #1。）

### 端到端验收（真实 server + 真实上游）

| # | 命令 | 实测 |
|---|---|---|
| 1 | `/boards?source=ths&type=concept` | 484 行，前缀只有 885/886 |
| 2 | `/boards?source=zzshare&type=concept` | 186 行（缓存），前缀 801/803/710/883 |
| 3 | `/boards/885333/stocks?source=ths&include_quote=false` | 78 只，`effective_source="ths"` |
| 6 | `...&include_quote=true&top_n=100` | 78 行；`change_speed`/`free_float_shares`/`float_market_cap` 均 `null`；`quote_truncated=false` |
| 12 | `...&include_quote=true&top_n=50` | 50 行；`quote_truncated=true`；首行 `open/high/low` 有值（AJAX 50 行上限 = 真截断） |
| 7 | `/boards/885333/history?source=zzshare` | **400** |
| 8 | `/stocks/600519/boards?source=ths` vs `?source=zzshare` | 8 条 vs 10 条，条目 source 各自纯净（改前逐字节相同） |
| 9 | `/stocks/600519/boards`（省略 source） | 18 条 = 10 zzshare + 8 ths |
| 10 | `/boards?source=zzshare&include_quote=true` | `amount_unit="yi"`，`amount=51.5105`（亿元） |
| 11 | `/boards/885333/quote?source=zzshare` | **200**（该端点无 `source` 参数，参数被忽略） |

**第 5 项与预期不符，但 404 是对的**：`/boards/885300/stocks?source=ths` 返回 404 而非计划期望的 200。实测 885300 的 F10 页是 **2,138 字节的空壳**（无成分股），而活的 885333 是 108,505 字节 —— 885300 是已下线的 THS 代码。改前的 422 是 `cid_unresolved`（无 DB 行），改后是空结果 404，两者都是"没有数据"，404 更准确。

### 验收清单抓到的四个缺陷（3 个是本轮引入的）

| # | 缺陷 | 处置 |
|---|---|---|
| 1 | **`ths_board_id_map` 收进了 zzshare 码**：CSV 里 `cid='300066'`（真 THS cid）+ `code='803014'`（zzshare 码）。只守 cid 半边就放行，随后运行期把 803014 当作 ths 板块吐出并落库 | 新增 `_is_ths_platecode`（885/886/881），写入路径 + seed 生成双重把关；seed 480 → 479 |
| 2 | **plan 原文的"整表 relabel 为 zzshare"是对的，我的中间版本按前缀拆错了**（见下） | 回退为单个 115,081 行 `stock_board_membership_zzshare.csv` |
| 3 | **`/stocks/{code}/boards` 在 ths 冷缓存时丢弃所有非 THS 条目**：cold-branch 用 live THS 结果**替换**了整个 data 列表，而不是与之合并。因为没有 ths membership seed，这条分支对每个股票都会命中 —— 600519 返回 8 条 ths、静默丢掉 10 条 zzshare | 改为合并；回归测试已验证"去掉修复就失败" |
| 4 | spec §1.2 的 code space 表只列了 zzshare plate_type 17，"没有任何一个 code 共用"的结论由此而来 | §1.2/§1.4/§1.5 + `board-source-semantics.md` + `CLAUDE.md` + `.env.example` 全部订正 |

### 缺陷 #2 的细节（一次被推翻的结论）

Plan 3 Task 3 Step 2 原文是"membership 整体 relabel 为 zzshare"。执行中我按 `board_code` 前缀把它拆成 zzshare 55,301 行 + THS 59,780 行，理由是"code space 不相交 + subtype 词汇各说各话"。**这个理由是错的**，两条都不成立：

- zzshare 的 `plates_rank` 跨三个 plate_type：**15(概念) → 885/886**、**14(行业) → 881**、17(题材) → 801/803/710/883。所以它和 THS 的公开码**大面积重叠**。我所谓的"不相交"只成立于该文件自己的两个分组之间，不成立于两个**来源的能力范围**之间。
- `同花顺概念`/`同花顺行业` 是**板块清单**带下来的 label（生成器抄进 membership 行），而 zzshare 的 plate_type 14/15 正好对应行业/概念，所以这两个 subtype 根本无法区分来源。唯一只属于 zzshare 的词汇是 `同花顺题材`(pt=17)，它只能证明 801xxx 那一组。

推翻它的证据是活库对照：zzshare 对 `885333` 返回 75 只 / CSV 74 只（交集 74，Jaccard 0.99）、`885431` 1010/1002（0.97）、`881121` 181/176（0.97）。差异来自 CSV 是 2026-07-12 的快照。

**教益**：`board_code` 的前缀不是来源标记 —— 两个 source 的取值域重叠。判断来源要靠 `source` 字段本身或上游对照，不能靠 code 形状。

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

**两个原先待确认项，已定档（正文已按此改写）**：

1. **Task 3 Step 2 → 删除 `stock_board_membership_ths.csv`**（选 A）。
2. **Task 2 Step 5 → 在 zzshare fetcher 边界换算成亿元**，`amount_unit` 恒 `"yi"`（选 B）。

**本次 review 修正的问题（全部已写进正文）**：

| # | 问题 | 修正位置 |
|---|---|---|
| 1 | Global Constraints 说"本机无 `.venv/`、用系统 python（miniconda 3.13.9）"—— 实际 `.venv/Scripts/python.exe`（3.10.11）存在，系统 python 连 conftest 都采不到 | Global Constraints |
| 2 | `/stocks/{stock_code}/boards` 的 `source` **不是** Literal（848 是 `type:`），早前版本的改法指向了错误的行 | Task 1 Step 4 |
| 3 | `/boards/{code}/quote?source=zzshare` 不会 400/422 —— 该端点没有 `source` 参数，参数被静默忽略 | Task 1 Step 5 + Task 6 验收 #11 |
| 4 | `quote_truncated = top_n > 50 and …` 与本计划自己的 `test_persistence_board_topn.py:72` 断言自相矛盾 | Task 2 Step 3 |
| 5 | `manager.get_board_stocks_full` **确实**接受 `source=`（必需参数），早前版本的"去掉 source"建议会导致 `TypeError` | Task 2 Step 3 |
| 6 | CSV 拆分把 118 行 `cid == code` 全说成"zzshare code 污染"——实际只有 8 行是 zzshare 码，**110 行是 885/886 platecode，会留在 ths 文件里且必须置空** | Task 3 Step 1 + Step 4 |
| 7 | 16 个 ths 重复 code 交给 loader 的 last-wins `INSERT OR REPLACE` 会静默丢掉 `885940` 的真实 cid `308791` | Task 3 Step 1 新增 `collapse()` |
| 8 | Task 6 的 `test_every_advertised_ths_board_code_resolves` 里 `all(… or True …)` 是恒真断言，什么都没钉住 | Task 6 Step 1 |
| 9 | Task 6 的 module-scoped fixture 直接改 `os.environ` / `db._db_path` 且不还原，会污染同 session 的后续测试 | Task 6 Step 1 |
| 10 | `fetcher_method` 是**单标量**，`get_board_stocks_full` 加不进那个表（它是端点内部层） | Task 5 Step 2 |
| 11 | Task 5 Step 1 的替换稿会**删掉两个仍然有效的小节**（failure observability / persistence↔manager coupling） | Task 5 Step 1 |
| 12 | 任务 5 Step 3 说"改 `top_n` 上限 50 → 800"，但 `api-reference.md` **根本没写 `top_n`** —— 是新增不是修改 | Task 5 Step 3 |
| 13 | `stock_board_zzshare` 的期望行数 `~177` 只是 801 前缀的数量，漏了 803/710/883 共 9 行 | Task 6 Step 3 |
| 14 | `_normalize_zzshare_list_quote_units` 的引用还有 `api-reference.md:587` / `:2802` 未在早前版本列出 | Task 5 Step 3 |
| 15 | Task 2 Step 1 的 `assert "le=50" not in inspect.getsource(routes_mod.get_board_stocks)` 是**假绿**：`@map_errors` / `@cache_endpoint` 已把模块属性换成 wrapper，`getsource` 拿到的是 `errors.py` 里的包装函数 | Task 2 Step 1（改为断言 OpenAPI schema） |
</content>
