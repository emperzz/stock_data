# THS `get_stock_boards` Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `ThsFetcher.get_stock_boards` to populate `/stocks/{code}/boards` for the THS source (via basic.10jqka.com.cn), remove the `ZzshareFetcher.get_stock_boards` stub, and wire THS through persistence + route layer with cold-fill support.

**Architecture:** Source-routed board methods (per CLAUDE.md) — `manager.get_stock_boards(source="ths")` already routes via `DataCapability.STOCK_BOARD` filter. ThsFetcher (already declares STOCK_BOARD for board K-line) gains `get_stock_boards`. Route layer reverses the alias direction for the stock-boards endpoint only (`zzshare → ths`, because zzshare's plates_list IS THS upstream). Persistence layer adds `"ths"` to `VALID_SUBTYPES_BY_SOURCE` and enables cold-fill.

**Tech Stack:** Python 3.11+, FastAPI, SQLite (persistence), requests/json_get (HTTP), pytest

**Spec:** `docs/superpowers/specs/2026-07-04-ths-stock-boards-design.md`

**Working directory:** Always use `.venv/Scripts/python.exe` (per CLAUDE.md). Venv `akshare`/`yfinance`/`gm` packages — running system Python will hit `ModuleNotFoundError`.

---

## File Structure

**Files modified:**

| File | Responsibility |
|---|---|
| `stock_data/data_provider/fetchers/ths_fetcher.py` | Add `get_stock_boards` + constants + import |
| `stock_data/data_provider/fetchers/zzshare_fetcher.py` | Remove `get_stock_boards` stub |
| `stock_data/data_provider/persistence/board.py` | Add `ths` to `VALID_SUBTYPES_BY_SOURCE`; add `normalize_stock_board_source`; enable cold-fill for `ths` |
| `stock_data/api/routes/boards.py` | Add `_parse_stock_boards_source_csv`; update `get_stock_boards` route |
| `tests/test_stock_boards_reverse_route.py` | Update 2 tests + add 2 new tests |
| `tests/test_zzshare_fetcher.py` | Remove obsolete test |
| `tests/test_ths_fetcher.py` | Add 3 unit tests for `get_stock_boards` |

**No new files created** (tests are added to existing test files per codebase convention).

---

## Task 1: ThsFetcher.get_stock_boards — TDD

**Files:**
- Modify: `stock_data/data_provider/fetchers/ths_fetcher.py` (imports + new constants + new method)
- Modify: `tests/test_ths_fetcher.py` (append 3 unit tests)

### Step 1.1: Locate existing test file and inspect current structure

```bash
grep -n "^def test_\|^class Test" tests/test_ths_fetcher.py | head -10
```

Expected: A list of existing test functions (e.g. `test_ths_get_hot_topics_*`, `test_ths_get_board_history_*`). Note the file's import style — copy that for new tests.

### Step 1.2: Write 3 failing unit tests for `ThsFetcher.get_stock_boards`

Open `tests/test_ths_fetcher.py` and append (do NOT delete existing tests):

```python
# --- get_stock_boards ---------------------------------------------------

def test_get_stock_boards_returns_normalized_dicts(monkeypatch):
    """Verify HTTP call shape + response normalization for known market."""
    from stock_data.data_provider.fetchers.ths_fetcher import ThsFetcher

    fetcher = ThsFetcher()
    fake_payload = {
        "status_code": 0,
        "data": [
            {"quote_code": "885642", "name": "跨境电商"},
            {"quote_code": "885910", "name": "拼多多概念"},
        ],
    }

    with patch(
        "stock_data.data_provider.fetchers.ths_fetcher.json_get",
        return_value=fake_payload,
    ) as mock_get:
        result = fetcher.get_stock_boards("300740")

    # HTTP called with right URL + params + headers
    args, kwargs = mock_get.call_args
    assert "basic.10jqka.com.cn" in args[0]
    assert args[0].endswith("/stock_concept_list")
    assert kwargs["params"]["code"] == "300740"
    assert kwargs["params"]["market_id"] == "33"  # 深市 (3xx prefix)
    assert kwargs["params"]["simple"] == 1
    assert "Referer" in kwargs["headers"]

    # Response normalized
    assert len(result) == 2
    assert result[0] == {
        "code": "885642",
        "name": "跨境电商",
        "type": "concept",
        "subtype": "同花顺概念",
    }
    assert result[1]["code"] == "885910"


def test_get_stock_boards_market_id_mapping(monkeypatch):
    """沪市代码 → market_id=17; 深市 → 33."""
    from stock_data.data_provider.fetchers.ths_fetcher import ThsFetcher

    fetcher = ThsFetcher()
    fake_payload = {"status_code": 0, "data": []}

    with patch(
        "stock_data.data_provider.fetchers.ths_fetcher.json_get",
        return_value=fake_payload,
    ) as mock_get:
        # 沪市主板 (600xxx)
        fetcher.get_stock_boards("600519")
        assert mock_get.call_args.kwargs["params"]["market_id"] == "17"

        # 沪市 B 股 (900xxx)
        fetcher.get_stock_boards("900901")
        assert mock_get.call_args.kwargs["params"]["market_id"] == "17"

        # 深市主板 (000xxx)
        fetcher.get_stock_boards("000001")
        assert mock_get.call_args.kwargs["params"]["market_id"] == "33"

        # 深市创业板 (300xxx)
        fetcher.get_stock_boards("300750")
        assert mock_get.call_args.kwargs["params"]["market_id"] == "33"


def test_get_stock_boards_empty_on_unknown_prefix(monkeypatch):
    """北交所代码 (4/8 prefix) 无 mapping → 空列表 + 不调上游."""
    from stock_data.data_provider.fetchers.ths_fetcher import ThsFetcher

    fetcher = ThsFetcher()
    with patch(
        "stock_data.data_provider.fetchers.ths_fetcher.json_get",
    ) as mock_get:
        result = fetcher.get_stock_boards("830799")  # 北交所

    assert result == []
    mock_get.assert_not_called()


def test_get_stock_boards_raises_data_fetch_error_on_http_failure(monkeypatch):
    """json_get 抛异常 → 包装为 DataFetchError."""
    from stock_data.data_provider.fetchers.ths_fetcher import ThsFetcher
    from stock_data.data_provider.base import DataFetchError

    fetcher = ThsFetcher()
    with patch(
        "stock_data.data_provider.fetchers.ths_fetcher.json_get",
        side_effect=RuntimeError("network unreachable"),
    ):
        with pytest.raises(DataFetchError, match="stock_concept_list"):
            fetcher.get_stock_boards("300740")
```

Also ensure the imports at the top of the test file include what's needed. Add if missing:

```python
from unittest.mock import patch
import pytest
```

(If `pytest` and `patch` are already imported, do not duplicate.)

### Step 1.3: Run tests to verify they fail

```bash
.venv/Scripts/python.exe -m pytest tests/test_ths_fetcher.py -k "get_stock_boards" -v
```

Expected: 4 failures with `AttributeError` (ThsFetcher.get_stock_boards doesn't exist yet) or `NameError` (constants don't exist).

### Step 1.4: Add import to ths_fetcher.py

Edit `stock_data/data_provider/fetchers/ths_fetcher.py` imports section (around line 38-40):

Find this existing block:

```python
from ..base import BaseFetcher, DataCapability, DataFetchError
from ..utils.http import json_get, json_post
from ..utils.text import strip_em_tags
```

Add one line after `from ..utils.http`:

```python
from ..base import BaseFetcher, DataCapability, DataFetchError
from ..utils.http import json_get, json_post
from ..utils.normalize import normalize_stock_code
from ..utils.text import strip_em_tags
```

### Step 1.5: Add constants near other THS URL constants

Find the block:

```python
_CONCEPT_DETAIL_URL = "https://q.10jqka.com.cn/gn/detail/code/{slug}/"

_THS_BOARD_KLINE_URL = "https://d.10jqka.com.cn/v4/line/bk_{inner}/01/{year}.js"
```

Add right after `_CONCEPT_DETAIL_URL`:

```python
_CONCEPT_DETAIL_URL = "https://q.10jqka.com.cn/gn/detail/code/{slug}/"

_STOCK_CONCEPT_LIST_URL = (
    "https://basic.10jqka.com.cn/fuyao/f10_stock_index/concept/v1/stock_concept_list"
)
# THS market_id: 17=沪市, 33=深市. BJ (4/8 prefix) 暂不映射 (上游 stock_concept_list
# 端点可能不支持北交所; 留待后续任务). 注意代码首位即可区分:
#   6/9 → 沪市;  0/3 → 深市;  4/8 → 北交所 (未映射)
_THS_MARKET_ID_MAP: dict[str, str] = {
    "6": "17",  # 沪市主板 + 科创板
    "9": "17",  # 沪市 B 股
    "0": "33",  # 深市主板 + 中小板
    "3": "33",  # 深市创业板
}
```

### Step 1.6: Implement `ThsFetcher.get_stock_boards`

Find the existing `get_hot_topics` method (search for `def get_hot_topics`) and insert `get_stock_boards` BEFORE it (so it sits with the other "stock membership" methods, after `get_board_history`):

Locate the line `# ---- 热点题材 (Hot Topics) ----` (search for that comment in ths_fetcher.py). Insert just above it:

```python
    # ------------------------------------------------------------------
    # 股票所属概念 (stock_concept_list — basic.10jqka.com.cn)
    # ------------------------------------------------------------------

    def get_stock_boards(self, stock_code: str, **kwargs) -> list[dict]:
        """THS concept membership via basic.10jqka.com.cn stock_concept_list.

        Returns list[{code, name, type, subtype}] or [] on upstream empty /
        no market_id mapping (北交所暂不支持).

        - code = quote_code (885xxx) — matches zzshare board-list code
          system, so forward board-list cache and reverse cold-fill rows
          join cleanly via (board_code, source).
        - type = 'concept' (硬编码 — endpoint is stock_concept_list).
        - subtype = '同花顺概念' — matches
          VALID_SUBTYPES_BY_SOURCE["zzshare"]["concept"] convention.

        Raises:
            DataFetchError: HTTP fetch failed.
        """
        code = normalize_stock_code(stock_code)
        market_id = _THS_MARKET_ID_MAP.get(code[:1])
        if not market_id:
            logger.warning(
                f"[ThsFetcher] get_stock_boards: no market_id mapping "
                f"for code={code!r} (北交所暂不支持)"
            )
            return []
        try:
            payload = json_get(
                _STOCK_CONCEPT_LIST_URL,
                params={"code": code, "market_id": market_id, "simple": 1},
                headers={
                    "Referer": "https://basic.10jqka.com.cn/astockpc/astockmain/index.html",
                    "User-Agent": THS_UA,
                },
                timeout=10,
            )
        except Exception as e:
            raise DataFetchError(
                f"[ThsFetcher] stock_concept_list({code}) failed: {e}"
            ) from e
        rows = payload.get("data") or []
        return [
            {
                "code": str(r.get("quote_code", "")).strip(),
                "name": str(r.get("name", "")).strip(),
                "type": "concept",
                "subtype": "同花顺概念",
            }
            for r in rows
            if r.get("quote_code")
        ]
```

### Step 1.7: Run tests to verify they pass

```bash
.venv/Scripts/python.exe -m pytest tests/test_ths_fetcher.py -k "get_stock_boards" -v
```

Expected: 4 PASS.

### Step 1.8: Commit

```bash
git add stock_data/data_provider/fetchers/ths_fetcher.py tests/test_ths_fetcher.py
git commit -m "feat(ths): get_stock_boards via basic.10jqka.com.cn

- Calls /fuyao/f10_stock_index/concept/v1/stock_concept_list with
  code + market_id (17=沪, 33=深) + simple=1
- Normalizes to (code=quote_code, name, type=concept, subtype=同花顺概念)
- BJ stocks (4/8 prefix) return [] (TODO: BJ THS endpoint)
- Raises DataFetchError on HTTP failure"
```

---

## Task 2: Remove `ZzshareFetcher.get_stock_boards` stub

**Files:**
- Modify: `stock_data/data_provider/fetchers/zzshare_fetcher.py:641-647` (delete method)
- Modify: `tests/test_zzshare_fetcher.py` (delete related test if present)

### Step 2.1: Locate the stub

```bash
grep -n "def get_stock_boards\|zzshare SDK does not provide" stock_data/data_provider/fetchers/zzshare_fetcher.py
```

Expected: Match at line 641 (or wherever). Confirm method body:

```python
    def get_stock_boards(self, stock_code: str, **kwargs) -> list[dict] | None:
        """Reverse lookup: boards a stock belongs to.

        zzshare SDK does not provide a direct stock->boards endpoint. Return
        None so the route layer can 404 (matches EastMoney behavior).
        """
        return None
```

### Step 2.2: Delete the method (lines 641-647 inclusive)

Open `stock_data/data_provider/fetchers/zzshare_fetcher.py`, find the method block, delete it entirely (including the trailing blank line so we don't double-up spacing).

The block to delete is exactly:

```python
    def get_stock_boards(self, stock_code: str, **kwargs) -> list[dict] | None:
        """Reverse lookup: boards a stock belongs to.

        zzshare SDK does not provide a direct stock->boards endpoint. Return
        None so the route layer can 404 (matches EastMoney behavior).
        """
        return None

```

(Note: include the trailing blank line for clean separation.)

### Step 2.3: Locate the test that exercises this stub

```bash
grep -n "get_stock_boards\|test_zzshare.*boards" tests/test_zzshare_fetcher.py
```

Expected: A test like `test_zzshare_get_stock_boards_returns_none` that explicitly asserts the stub returns None.

### Step 2.4: Delete the obsolete test

Delete the entire test function (and any helper/setup specific to it). Do NOT delete tests for OTHER ZzshareFetcher methods (e.g. minute K-line, daily dragon tiger).

### Step 2.5: Run zzshare tests to verify the rest still pass

```bash
.venv/Scripts/python.exe -m pytest tests/test_zzshare_fetcher.py -v
```

Expected: All remaining tests pass (no more `get_stock_boards`-related failures). If some test failures appear unrelated to the removed test, investigate; do NOT proceed with broken tests.

### Step 2.6: Commit

```bash
git add stock_data/data_provider/fetchers/zzshare_fetcher.py tests/test_zzshare_fetcher.py
git commit -m "refactor(zzshare): remove get_stock_boards stub

- THS (basic.10jqka.com.cn) is now the canonical THS upstream for
  stock→boards reverse lookup (via ThsFetcher)
- ZzshareFetcher.get_stock_boards was always None; calls now route
  through source=zzshare → alias → source=ths → ThsFetcher"
```

---

## Task 3: Persistence — add `ths` to `VALID_SUBTYPES_BY_SOURCE`

**Files:**
- Modify: `stock_data/data_provider/persistence/board.py` (line 23-42 area)

### Step 3.1: Locate VALID_SUBTYPES_BY_SOURCE

```bash
grep -n "VALID_SUBTYPES_BY_SOURCE\|zzshare.*NEW\|同花顺概念" stock_data/data_provider/persistence/board.py
```

Expected: Match around line 23.

### Step 3.2: Add `ths` entry

Find the dictionary (currently ends with `"zzshare": {...}`). Add a new entry AFTER `"zzshare"`:

```python
    "zzshare": {  # NEW
        "industry": {"同花顺行业"},
        "concept": {"同花顺概念"},
        "special": {"同花顺题材"},
        # "index" — zzshare 不暴露大盘指数板块
    },
    "ths": {  # NEW — stock-boards 专用 (THS basic API 仅返回 concept)
        "concept": {"同花顺概念"},
        # industry / special / index 暂不支持 (THS stock_concept_list 端点特性)
    },
```

### Step 3.3: Run persistence-related tests

```bash
.venv/Scripts/python.exe -m pytest tests/test_stock_boards_reverse_route.py tests/test_stock_boards_eastmoney_source.py -v
```

Expected: All existing tests still pass. Adding a key to `VALID_SUBTYPES_BY_SOURCE` should not affect existing flow because `VALID_SOURCES` is derived (sort-deduplicated), and existing routes filter sources explicitly.

### Step 3.4: Verify VALID_SOURCES derived set

```bash
.venv/Scripts/python.exe -c "from stock_data.data_provider.persistence.board import VALID_SOURCES; print(sorted(VALID_SOURCES))"
```

Expected: `['eastmoney', 'ths', 'zhitu', 'zzshare']` (4 entries, alphabetical).

### Step 3.5: Commit

```bash
git add stock_data/data_provider/persistence/board.py
git commit -m "feat(persistence): add 'ths' to VALID_SUBTYPES_BY_SOURCE

- New source key for stock-boards (THS basic API)
- concept-only for now (stock_concept_list endpoint nature)
- zzshare entry unchanged (board-list endpoint still uses it)"
```

---

## Task 4: Persistence — `normalize_stock_board_source` helper (TDD)

**Files:**
- Modify: `stock_data/data_provider/persistence/board.py` (add helper + constants after VALID_SOURCES)

### Step 4.1: Write failing tests for the helper

Append to `tests/test_stock_boards_reverse_route.py` (or new file if preferred, but codebase convention is to consolidate route-layer tests):

```python
# --- normalize_stock_board_source -----------------------------------

def test_normalize_stock_board_source_canonical():
    """ths / eastmoney / zhitu pass through unchanged."""
    from stock_data.data_provider.persistence.board import normalize_stock_board_source
    assert normalize_stock_board_source("ths") == "ths"
    assert normalize_stock_board_source("eastmoney") == "eastmoney"
    assert normalize_stock_board_source("zhitu") == "zhitu"


def test_normalize_stock_board_source_zzshare_alias():
    """zzshare aliases to ths (data is THS upstream)."""
    from stock_data.data_provider.persistence.board import normalize_stock_board_source
    assert normalize_stock_board_source("zzshare") == "ths"


def test_normalize_stock_board_source_invalid_raises():
    """Unknown source raises ValueError."""
    from stock_data.data_provider.persistence.board import normalize_stock_board_source
    with pytest.raises(ValueError, match="Unknown stock-boards source"):
        normalize_stock_board_source("bogus")
    with pytest.raises(ValueError, match="Unknown stock-boards source"):
        normalize_stock_board_source("")


def test_normalize_stock_board_source_does_not_alias_other_directions():
    """ths is canonical (does NOT alias to zzshare)."""
    from stock_data.data_provider.persistence.board import normalize_stock_board_source
    assert normalize_stock_board_source("ths") != "zzshare"
```

### Step 4.2: Run tests to verify they fail

```bash
.venv/Scripts/python.exe -m pytest tests/test_stock_boards_reverse_route.py -k "normalize_stock_board_source" -v
```

Expected: `ImportError` (helper doesn't exist yet) or `AttributeError`.

### Step 4.3: Add helper to persistence/board.py

Find the line `VALID_SOURCES: tuple[str, ...] = tuple(sorted(VALID_SUBTYPES_BY_SOURCE.keys()))` (around line 48). Add constants and helper right AFTER that line:

```python
VALID_BOARD_TYPES: tuple[str, ...] = ("concept", "industry", "index", "special")
VALID_SOURCES: tuple[str, ...] = tuple(sorted(VALID_SUBTYPES_BY_SOURCE.keys()))


# Stock-boards 专用 source 集合 + alias (仿照 _BOARD_HISTORY_VALID_SOURCES 模式).
# board-list 端点继续用 ths→zzshare alias (zzshare 的 plates_list 上游 = THS);
# stock-boards 端点反转为 zzshare→ths alias (THS basic API 是真正的 stock→boards 上游).
_STOCK_BOARDS_VALID_SOURCES: tuple[str, ...] = ("ths", "eastmoney", "zhitu")
_STOCK_BOARDS_SOURCE_ALIAS: dict[str, str] = {"zzshare": "ths"}


def normalize_stock_board_source(source: str) -> str:
    """Alias + validate a source name for the stock-boards endpoint.

    Applies the stock-boards alias map (zzshare → ths) and validates
    against _STOCK_BOARDS_VALID_SOURCES. The board-list endpoint uses
    the opposite alias direction (ths → zzshare); see boards.py:_resolve_source.

    Args:
        source: User-supplied source name (e.g. ``"ths"``, ``"zzshare"``).

    Returns:
        Canonical source name accepted by the persistence layer.

    Raises:
        ValueError: ``source`` is not in the valid set after aliasing.
            Caller (route layer) maps this to ``HTTPException(400)``.
    """
    s = _STOCK_BOARDS_SOURCE_ALIAS.get(source, source)
    if s not in _STOCK_BOARDS_VALID_SOURCES:
        raise ValueError(
            f"Unknown stock-boards source {source!r}. "
            f"Valid sources: {list(_STOCK_BOARDS_VALID_SOURCES)} "
            f"(alias 'zzshare' accepted)"
        )
    return s
```

### Step 4.4: Run tests to verify they pass

```bash
.venv/Scripts/python.exe -m pytest tests/test_stock_boards_reverse_route.py -k "normalize_stock_board_source" -v
```

Expected: 4 PASS.

### Step 4.5: Commit

```bash
git add stock_data/data_provider/persistence/board.py tests/test_stock_boards_reverse_route.py
git commit -m "feat(persistence): normalize_stock_board_source helper

- _STOCK_BOARDS_VALID_SOURCES = (ths, eastmoney, zhitu)
- _STOCK_BOARDS_SOURCE_ALIAS = {zzshare: ths}
- Raises ValueError on unknown source (caller maps to HTTP 400)
- Independent of board-list helper (alias direction reversed)"
```

---

## Task 5: Persistence — cold-fill for `ths`

**Files:**
- Modify: `stock_data/data_provider/persistence/board.py:get_stock_memberships`

### Step 5.1: Locate cold-fill loop

```bash
grep -n "for cold_src in\|cold_src = " stock_data/data_provider/persistence/board.py | head -5
```

Expected: Match around line 743 (`for cold_src in ("zhitu", "eastmoney"):`).

### Step 5.2: Add `"ths"` to the loop

Find:

```python
        for cold_src in ("zhitu", "eastmoney"):
            if cold_src not in sources or cold_src in present_sources:
                continue
            boards, _ = manager.get_stock_boards(stock_code, source=cold_src)
```

Replace with:

```python
        for cold_src in ("ths", "zhitu", "eastmoney"):  # ths 加首位 (新实现)
            if cold_src not in sources or cold_src in present_sources:
                continue
            boards, _ = manager.get_stock_boards(stock_code, source=cold_src)
```

Also find the `coldfill_sources` set computation:

```python
        coldfill_sources = {"zhitu", "eastmoney"} & {e["source"] for e in entries}
```

Replace with:

```python
        coldfill_sources = {"ths", "zhitu", "eastmoney"} & {e["source"] for e in entries}
```

### Step 5.3: Run existing persistence tests to verify no regression

```bash
.venv/Scripts/python.exe -m pytest tests/test_stock_boards_reverse_route.py -v
```

Expected: Existing tests still pass (the loop change doesn't affect existing test paths because they don't exercise cold-fill for ths specifically).

### Step 5.4: Add test for cold-fill ths

Append to `tests/test_stock_boards_reverse_route.py`:

```python
def test_cold_fill_ths_triggers_ths_fetcher(fresh_db):
    """?cold_fill=true&source=ths → fetcher called with source='ths'."""
    mock_manager = MagicMock()
    # First read returns empty (cache miss); second read after cold-fill returns data
    mock_manager.get_stock_boards.return_value = (
        [
            {"code": "885642", "name": "跨境电商",
             "type": "concept", "subtype": "同花顺概念"},
        ],
        "ths",  # fetcher name
    )
    with (
        TestClient(_app_for_test) as client,
        patch("stock_data.api.routes.boards.get_manager", return_value=mock_manager),
    ):
        r = client.get("/api/v1/stocks/600519/boards?source=ths&cold_fill=true")
    assert r.status_code == 200
    # fetcher was called with source='ths'
    mock_manager.get_stock_boards.assert_called_once()
    call_kwargs = mock_manager.get_stock_boards.call_args.kwargs
    assert call_kwargs["source"] == "ths"
```

### Step 5.5: Run new test

```bash
.venv/Scripts/python.exe -m pytest tests/test_stock_boards_reverse_route.py -k "cold_fill_ths" -v
```

Expected: PASS.

### Step 5.6: Commit

```bash
git add stock_data/data_provider/persistence/board.py tests/test_stock_boards_reverse_route.py
git commit -m "feat(persistence): enable cold-fill for source='ths'

- get_stock_memberships cold-fill loop now includes 'ths'
- coldfill_sources summary set updated to track ths entries
- Tests cover cold-fill triggers ThsFetcher with source='ths'"
```

---

## Task 6: Route layer — `_parse_stock_boards_source_csv` helper

**Files:**
- Modify: `stock_data/api/routes/boards.py` (add helper after `_parse_source_csv`)

### Step 6.1: Locate `_parse_source_csv` to copy style

```bash
grep -n "_parse_source_csv\|def _resolve_source" stock_data/api/routes/boards.py
```

Expected: `_parse_source_csv` around line 186, `_resolve_source` around line 54.

### Step 6.2: Add `_parse_stock_boards_source_csv` helper

Insert after the existing `_parse_source_csv` function (around line 217, after the closing `return out` of `_parse_source_csv`):

```python
def _parse_stock_boards_source_csv(raw: str | None) -> list[str]:
    """Parse ?source= for /stocks/{code}/boards — alias zzshare → ths.

    与 _parse_source_csv (board-list 用, alias 方向是 ths→zzshare) 相反:
    THS basic API 是 stock→boards 反查的真正上游; zzshare SDK 没有这个端点
    (返回 stub None), 所以这里让 zzshare alias 到 ths (数据本来同源)。

    核心 CSV 解析逻辑 (split/strip/dedup) 与 _parse_source_csv 重复 5 行 —
    不抽公共 helper, 因为两端点的 alias 方向 / valid set / 默认集合都不同,
    强行复用 = 配置化函数, 可读性下降。两个端点各自一个聚焦 helper
    (rule of three 之后再考虑抽公共)。

    Args:
        raw: User-supplied ?source= value (may be None or comma-separated).

    Returns:
        List of normalized source names in user-requested order, deduplicated.

    Raises:
        HTTPException(400): any source (after aliasing) is not in the valid set.
            Error detail lists valid sources + accepted alias.
    """
    valid_set = stock_board_cache._STOCK_BOARDS_VALID_SOURCES
    alias_map = stock_board_cache._STOCK_BOARDS_SOURCE_ALIAS
    if not raw:
        return list(valid_set)
    out: list[str] = []
    for s in raw.split(","):
        s = s.strip()
        if not s:
            continue
        s = alias_map.get(s, s)
        if s not in valid_set:
            raise HTTPException(
                status_code=400,
                detail={
                    "error": "invalid_source",
                    "message": (
                        f"Unknown stock-boards source {s!r}. "
                        f"Valid sources: {list(valid_set)} "
                        f"(alias 'zzshare' accepted)"
                    ),
                },
            )
        if s not in out:
            out.append(s)
    return out
```

### Step 6.3: Update `get_stock_boards` route to use new helper

Find the `get_stock_boards` route function (around line 463 in boards.py). Replace:

```python
    normalized_sources = _parse_source_csv(source)
```

With:

```python
    normalized_sources = _parse_stock_boards_source_csv(source)
```

Also update the route's `source` parameter description. Find:

```python
    source: str | None = Query(
        None,
        description="Comma-separated sources (e.g. 'eastmoney,zhitu,zzshare,ths'). "
        "Omit for all sources. 'ths' aliases 'zzshare'.",
    ),
```

Replace with:

```python
    source: str | None = Query(
        None,
        description=(
            "Comma-separated sources (e.g. 'ths,eastmoney,zhitu'). "
            "'zzshare' is accepted as alias for 'ths' (THS upstream is shared). "
            "Omit for all valid sources."
        ),
    ),
```

Also update the `@endpoint_meta` summary line. Find:

```python
@endpoint_meta(
    summary="股票所属板块（统一端点：单源/多源聚合；cold_fill 显式 opt-in）",
    ...
)
```

Replace with:

```python
@endpoint_meta(
    summary="股票所属板块 (ths/eastmoney/zhitu; source=zzshare alias → ths)",
    ...
)
```

### Step 6.4: Run route-layer tests to verify the helper compiles

```bash
.venv/Scripts/python.exe -m pytest tests/test_stock_boards_reverse_route.py -v
```

Expected: The new helper import works; existing tests may still pass with stale expectations — we'll fix those next.

### Step 6.5: Commit (route helper, before test updates)

```bash
git add stock_data/api/routes/boards.py
git commit -m "feat(routes): stock-boards specific CSV parser (alias zzshare→ths)

- New _parse_stock_boards_source_csv mirrors _parse_source_csv
  but with reversed alias direction (data is THS upstream)
- Default source set is (ths, eastmoney, zhitu) — no zzshare
  (zzshare is fully aliased to ths for this endpoint)
- Updates route description + endpoint_meta summary"
```

---

## Task 7: Update existing route-layer tests for new behavior

**Files:**
- Modify: `tests/test_stock_boards_reverse_route.py`

### Step 7.1: Update `test_ths_alias_accepted_in_csv`

Find:

```python
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
```

Replace with:

```python
def test_ths_canonical_in_csv(fresh_db):
    """?source=ths,zhitu → ths stays as ths (no longer aliases to zzshare)."""
    with patch("stock_data.data_provider.persistence.board.get_stock_memberships") as mock:
        mock.return_value = ([], ["ths", "zhitu"], "")
        with TestClient(_app_for_test) as client:
            r = client.get("/api/v1/stocks/600519/boards?source=ths,zhitu")
        assert r.status_code == 200
        called = mock.call_args.kwargs["sources"]
        assert "ths" in called
        assert "zzshare" not in called
        assert "zhitu" in called
```

### Step 7.2: Update `test_no_source_aggregates_all`

Find:

```python
def test_no_source_aggregates_all(fresh_db):
    """Omitting ?source= aggregates all 3 sources."""
    with patch("stock_data.data_provider.persistence.board.get_stock_memberships") as mock:
        mock.return_value = (
            [{"code": "x", "name": "x", "type": "concept", "subtype": "", "source": "zhitu"}],
            [],
            "mixed",
        )
        with TestClient(_app_for_test) as client:
            r = client.get("/api/v1/stocks/600519/boards")
        assert r.status_code == 200
        called = mock.call_args.kwargs["sources"]
        assert set(called) == {"eastmoney", "zhitu", "zzshare"}
```

Replace with:

```python
def test_no_source_aggregates_all(fresh_db):
    """Omitting ?source= aggregates (ths, eastmoney, zhitu) — no zzshare."""
    with patch("stock_data.data_provider.persistence.board.get_stock_memberships") as mock:
        mock.return_value = (
            [{"code": "x", "name": "x", "type": "concept", "subtype": "", "source": "zhitu"}],
            [],
            "mixed",
        )
        with TestClient(_app_for_test) as client:
            r = client.get("/api/v1/stocks/600519/boards")
        assert r.status_code == 200
        called = mock.call_args.kwargs["sources"]
        assert set(called) == {"ths", "eastmoney", "zhitu"}
```

### Step 7.3: Delete obsolete `test_ths_alias_single_source`

Find:

```python
def test_ths_alias_single_source(fresh_db):
    """Existing test pattern (kept for backwards compat): single ths source → alias works."""
    with patch("stock_data.data_provider.persistence.board.get_stock_memberships") as mock:
        mock.return_value = ([], ["zzshare"], "")
        with TestClient(_app_for_test) as client:
            r = client.get("/api/v1/stocks/600519/boards?source=ths")
        assert r.status_code == 200
        called = mock.call_args.kwargs["sources"]
        assert called == ["zzshare"]
```

Delete this test function entirely (it's no longer accurate — `source=ths` is now canonical, not an alias).

### Step 7.4: Add new test `test_zzshare_aliases_to_ths`

Append after `test_ths_canonical_in_csv`:

```python
def test_zzshare_aliases_to_ths(fresh_db):
    """?source=zzshare now aliases to ths (data is THS upstream)."""
    with patch("stock_data.data_provider.persistence.board.get_stock_memberships") as mock:
        mock.return_value = ([], ["ths"], "")
        with TestClient(_app_for_test) as client:
            r = client.get("/api/v1/stocks/600519/boards?source=zzshare")
        assert r.status_code == 200
        called = mock.call_args.kwargs["sources"]
        assert called == ["ths"]
```

### Step 7.5: Add new test `test_ths_industry_filter_returns_400`

Append:

```python
def test_ths_industry_filter_returns_400(fresh_db):
    """ths only supports concept; ?source=ths&type=industry → 400 (bad_request).

    Note: error code is ``bad_request`` (not ``invalid_subtype``) because the
    route delegates to ``stock_board_cache._validate_subtype`` which raises
    ValueError, and ``@map_errors`` uniformly maps ValueError → bad_request.
    Same convention as the existing ``/boards/{board_code}/stocks`` endpoint.
    """
    with TestClient(_app_for_test) as client:
        r = client.get("/api/v1/stocks/600519/boards?source=ths&type=industry&subtype=申万行业")
    assert r.status_code == 400
    assert r.json()["detail"]["error"] == "bad_request"
```

### Step 7.6: Run updated tests

```bash
.venv/Scripts/python.exe -m pytest tests/test_stock_boards_reverse_route.py -v
```

Expected: All 8 tests pass:
- test_single_source_returns_per_entry_source_field ✓
- test_csv_source_aggregates_multiple_sources ✓
- test_ths_canonical_in_csv ✓ (updated)
- test_no_source_aggregates_all ✓ (updated)
- test_cold_fill_false_does_not_trigger_lazy_fill ✓
- test_invalid_source_in_csv_returns_400 ✓
- test_zzshare_aliases_to_ths ✓ (new)
- test_ths_industry_filter_returns_400 ✓ (new)
- test_cold_fill_ths_triggers_ths_fetcher ✓ (from Task 5)
- test_normalize_stock_board_source_* (4 tests from Task 4)

### Step 7.7: Commit

```bash
git add tests/test_stock_boards_reverse_route.py
git commit -m "test(routes): align reverse-lookup tests with new THS alias

- test_ths_canonical_in_csv: ths is canonical, no longer aliases
- test_no_source_aggregates_all: 3 sources = (ths, eastmoney, zhitu)
- Remove test_ths_alias_single_source (alias no longer exists)
- Add test_zzshare_aliases_to_ths (back-compat alias direction)
- Add test_ths_industry_filter_returns_400 (concept-only constraint)"
```

---

## Task 8: Full integration verification

### Step 8.1: Run all test suites that touch the modified code

```bash
.venv/Scripts/python.exe -m pytest \
    tests/test_ths_fetcher.py \
    tests/test_zzshare_fetcher.py \
    tests/test_stock_boards_reverse_route.py \
    tests/test_stock_boards_eastmoney_source.py \
    tests/test_eastmoney_stock_boards.py \
    -v
```

Expected: All pass. If any fail, investigate; do NOT proceed with broken tests.

### Step 8.2: Run full default test suite

```bash
.venv/Scripts/python.exe -m pytest
```

Expected: No regressions. This catches any cross-test interactions (e.g. capability map tests, manifest sanity checks).

### Step 8.3: Run lint

```bash
ruff check stock_data/data_provider/fetchers/ths_fetcher.py \
        stock_data/data_provider/fetchers/zzshare_fetcher.py \
        stock_data/data_provider/persistence/board.py \
        stock_data/api/routes/boards.py \
        tests/test_ths_fetcher.py \
        tests/test_stock_boards_reverse_route.py
```

Expected: No errors. Fix any reported issues.

### Step 8.4: Manual smoke test (optional but recommended)

Start the server:

```bash
.venv/Scripts/python.exe -m stock_data.server
```

In another shell:

```bash
# 1. source=ths canonical
curl -s "http://localhost:8888/api/v1/stocks/300740/boards?source=ths" | jq '.source, .data | length'

# 2. source=zzshare aliases to ths
curl -s "http://localhost:8888/api/v1/stocks/300740/boards?source=zzshare" | jq '.source'

# 3. Cold-fill ths
curl -s "http://localhost:8888/api/v1/stocks/300740/boards?source=ths&cold_fill=true" | jq '.data | length'

# 4. Default aggregates (ths, eastmoney, zhitu)
curl -s "http://localhost:8888/api/v1/stocks/300740/boards" | jq '.cold_sources'

# 5. Invalid: ths with industry filter
curl -s -w "\n%{http_code}" "http://localhost:8888/api/v1/stocks/300740/boards?source=ths&type=industry"
```

Expected:
1. Source = `ths` or `persistence`, data length > 0
2. Source = `ths` (after alias)
3. data length > 0 (cold-fill triggered)
4. cold_sources may include `eastmoney` and `zhitu` (cache miss; `ths` may be persistence or ths after cold-fill)
5. HTTP 400 with `invalid_subtype` error

Stop the server with Ctrl+C.

### Step 8.5: Final commit (if smoke test surfaced any small fixes)

```bash
git add -A
git commit -m "fix: integration smoke-test adjustments" --allow-empty
```

(Only commit if there were fixes; if clean, skip this step.)

---

## Self-Review Checklist

**Spec coverage:**
- [x] §1 ThsFetcher.get_stock_boards — Task 1
- [x] §2 Persistence VALID_SUBTYPES + helper + cold-fill — Tasks 3, 4, 5
- [x] §3 Route layer new helper — Task 6
- [x] §4 Manager (no changes) — confirmed in plan
- [x] §5.1 test_stock_boards_reverse_route.py updates — Tasks 4, 5, 7
- [x] §5.2 test_zzshare_fetcher.py cleanup — Task 2
- [x] §5.3 test_ths_fetcher.py unit tests — Task 1
- [x] Compatibility matrix — covered by tests in Tasks 5, 7
- [x] Risk mitigations — addressed by tests + DataFetchError wrapping

**Placeholder scan:** No "TBD"/"TODO"/"implement later" in any task.

**Type consistency:** Method signatures, function names, parameter names consistent across tasks.

**File paths:** All paths absolute (under `E:\GitRepo\stock_data\`) or relative to repo root; test paths match real locations.

**Commands:** All use `.venv/Scripts/python.exe` per CLAUDE.md.

---

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-07-04-ths-stock-boards.md`.

Two execution options:
1. **Subagent-Driven** (recommended) — fresh subagent per task, two-stage review between tasks
2. **Inline Execution** — execute tasks in this session using executing-plans, batch with checkpoints

Which approach?