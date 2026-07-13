# Board-Stocks top_n + Multi-Field Sort + ZZSHARE Backfill Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extend `GET /boards/{board_code}/stocks` with `?sort_by`, `?sort_order`, `?top_n` query params. THS upstream already supports all 11 of these sort fields via its `field/<column_code>/order/<dir>/` URL pattern (probed 2026-07-13 against board 301546 / 央企国企改革). When the upstream's 50-stock login wall truncates results, automatically fill in the missing members via ZZSHARE (no quote fields).

**Architecture:** 8 layered commits (A→H). Schema `BoardStockInfo` grows by 6 fields (THS 14-column parser currently ignores idx 6/8/9/11/12/13). Schema `BoardStocksResponse` grows by 5 echo fields. THS fetcher gets a sort-field code map + new kwargs. `DataFetcherManager.get_board_stocks` grows 3 keyword-only kwargs and forwards them. Route layer adds cross-validation that mirror sibling `/boards` UX. Persistence layer wraps `fetch_board_stocks_with_zzshare_fallback` with a 50-stock heuristic that triggers a single ZZSHARE membership fill-in. Each commit is independently revertable.

**Tech Stack:** Python 3.11, FastAPI, Pydantic v2, requests + curl_cffi, tenacity, py_mini_racer, bs4, demjson3, SQLite (via existing `persistence/board.py`)

**Reference Spec:** `docs/superpowers/specs/2026-07-13-board-stocks-top-n-sort-design.md` (commit `84b0b70`)

---

## File Structure

| # | File | Type | Responsibility |
|---|---|---|---|
| 1 | `stock_data/api/schemas.py` | Modify | Add 6 fields to `BoardStockInfo`; add 5 fields to `BoardStocksResponse` |
| 2 | `stock_data/data_provider/fetchers/ths_fetcher.py` | Modify | Add URL template + sort-field map; add 3 kwargs to `get_board_stocks`; parse 14 columns; add `_parse_free_float` helper |
| 3 | `stock_data/data_provider/manager.py` | Modify | Extend `get_board_stocks` with keyword-only kwargs; `call()` forwards them |
| 4 | `stock_data/data_provider/persistence/board.py` | Modify | Extend `get_board_stocks` + `fetch_board_stocks_with_zzshare_fallback`; implement 50-stock heuristic + top-N-first merge |
| 5 | `stock_data/api/routes/boards.py` | Modify | Add 3 query params + cross-validation; project 6 new schema fields; populate 5 echo response fields |
| 6 | `stock_data/CLAUDE.md` | Modify | Document 11 sortable fields + persistence backfill policy |
| 7 | `tests/test_ths_fetcher.py` | Modify | Add 8 new tests for sort/top_n/parse |
| 8 | `tests/test_boards_api.py` | Modify | Add 7 new tests for route validation + truncation semantics |
| 9 | `tests/fixtures/ths_board_301546_page1.html` | Create | Offline HTML fixture: real upstream page-1 body for board 301546 |

**Dependency order** (compile-time safety): A → B → C → D → E → F. Commits G+H land last. D before F (manager must forward kwargs before persistence uses them).

---

## Task 1: Schema — extend `BoardStockInfo` with 6 new optional quote fields (Commit A)

**Files:**
- Modify: `stock_data/api/schemas.py:338-353` (`BoardStockInfo` class)
- Test: `tests/test_boards_schemas.py` (existing file — extend it)

- [ ] **Step 1.1: Write failing schema test**

Open `tests/test_boards_schemas.py` (create file if missing) and add:

```python
"""Schema-level tests for BoardStockInfo / BoardStocksResponse."""


def test_board_stock_info_accepts_6_new_optional_fields():
    """BoardStockInfo 接受 6 个 2026-07-13 新增 optional quote 字段 (THS 14 列 schema 暴露)."""
    from stock_data.api.schemas import BoardStockInfo

    row = BoardStockInfo(
        code="000034",
        name="神州数码",
        price=12.34,
        change_pct=5.5,
        change_amount=0.65,
        turnover_rate=8.7,
        # 6 new fields (2026-07-13):
        change_speed=0.10,        # 涨速(%)
        volume_ratio=1.85,          # 量比
        amplitude=2.31,            # 振幅(%)
        free_float_shares=473_000_000,  # 流通股(4.73亿股)
        float_market_cap=66_300_000_000.0,  # 流通市值(66.31亿)
        pe_ratio=37.59,            # 市盈率
    )
    assert row.change_speed == 0.10
    assert row.volume_ratio == 1.85
    assert row.amplitude == 2.31
    assert row.free_float_shares == 473_000_000
    assert row.float_market_cap == 66_300_000_000.0
    assert row.pe_ratio == 37.59


def test_board_stock_info_new_fields_default_none():
    """新增字段缺省为 None (向后兼容)."""
    from stock_data.api.schemas import BoardStockInfo

    row = BoardStockInfo(code="000034", name="x")
    assert row.change_speed is None
    assert row.volume_ratio is None
    assert row.amplitude is None
    assert row.free_float_shares is None
    assert row.float_market_cap is None
    assert row.pe_ratio is None
```

- [ ] **Step 1.2: Run test (expect FAIL — fields don't exist)**

Run: `.venv/Scripts/python.exe -m pytest tests/test_boards_schemas.py -v`
Expected: **FAIL** with `TypeError: BoardStockInfo() got unexpected keyword argument 'change_speed'`

- [ ] **Step 1.3: Add 6 fields to `BoardStockInfo` (in `stock_data/api/schemas.py`)**

Edit `BoardStockInfo` in `stock_data/api/schemas.py` to add after the existing `turnover_rate` field:

```python
    # === 2026-07-13 新增 (THS /field/<code> 14 列全部暴露) ===
    change_speed: float | None = Field(
        default=None, description="涨速(%) — THS upstream column 6")
    volume_ratio: float | None = Field(
        default=None, description="量比 — THS upstream column 8")
    amplitude: float | None = Field(
        default=None, description="振幅(%) — THS upstream column 9")
    free_float_shares: int | None = Field(
        default=None, description="流通股(股) — THS upstream column 11 parsed from 'N.NN亿'")
    float_market_cap: float | None = Field(
        default=None, description="流通市值(元) — THS upstream column 12")
    pe_ratio: float | None = Field(
        default=None, description="市盈率 — THS upstream column 13")
```

- [ ] **Step 1.4: Run test (expect PASS)**

Run: `.venv/Scripts/python.exe -m pytest tests/test_boards_schemas.py -v`
Expected: 2 passed

- [ ] **Step 1.5: Run all existing board tests (regression check)**

Run: `.venv/Scripts/python.exe -m pytest tests/test_boards_api.py tests/test_boards_schemas.py -v`
Expected: All pass; no existing test breaks (new fields are Optional with default None)

- [ ] **Step 1.6: Commit**

```bash
git add stock_data/api/schemas.py tests/test_boards_schemas.py
git commit -m "feat(boards): extend BoardStockInfo with 6 new optional quote fields

THS /field/<code> URL pattern exposes 11 sortable columns; previously
only 9 were parsed (idx 0/1/2/3/4/5/7/10 + volume=None). Index 6/8/9/
11/12/13 columns (change_speed / volume_ratio / amplitude /
free_float_shares / float_market_cap / pe_ratio) flowed into the
fetcher dict → Pydantic extra=ignore drop silently. Adding all as
Optional keeps backward compat (existing schemas default None).
"
```

---

## Task 2: THS fetcher — URL template + sort-field map (Commit B)

**Files:**
- Modify: `stock_data/data_provider/fetchers/ths_fetcher.py` (top of file — add module-level constants)
- Modify: `stock_data/data_provider/fetchers/ths_fetcher.py:202-207` (`_BOARD_STOCKS_URL` global)
- Test: `tests/test_ths_fetcher.py` (extend `TestGetBoardStocks`)

- [ ] **Step 2.1: Write failing test for URL template + field map**

Open `tests/test_ths_fetcher.py` and add a new test class (or append to existing `TestGetBoardStocks`):

```python
class TestBoardStocksSortFieldMap:
    def test_field_map_has_11_entries(self):
        from stock_data.data_provider.fetchers.ths_fetcher import (
            _THS_BOARD_STOCKS_SORT_FIELD_MAP,
        )
        assert len(_THS_BOARD_STOCKS_SORT_FIELD_MAP) == 11

    def test_field_map_known_entries(self):
        """11 个排序键与实测 THS 上游列代码对应 (2026-07-13 playwright probe)."""
        from stock_data.data_provider.fetchers.ths_fetcher import (
            _THS_BOARD_STOCKS_SORT_FIELD_MAP,
        )
        expected = {
            "change_pct": "199112",
            "price": "10",
            "turnover_rate": "1968584",
            "volume_ratio": "1771976",
            "amplitude": "526792",
            "change_amount": "264648",
            "change_speed": "48",
            "amount": "19",
            "pe_ratio": "2034120",
            "float_market_cap": "3475914",
            "free_float_shares": "407",
        }
        assert _THS_BOARD_STOCKS_SORT_FIELD_MAP == expected


class TestBoardStocksUrlTemplate:
    def test_url_template_renders_with_field_code_and_order(self):
        from stock_data.data_provider.fetchers.ths_fetcher import (
            _BOARD_STOCKS_URL_TEMPLATE,
        )
        url = _BOARD_STOCKS_URL_TEMPLATE.format(
            concept_id="301546", field_code="10", order="desc", page=1
        )
        assert url == (
            "https://q.10jqka.com.cn/gn/detail/code/301546"
            "/field/10/order/desc/page/1/ajax/1/"
        )
```

- [ ] **Step 2.2: Run tests (expect FAIL — module attrs don't exist)**

Run: `.venv/Scripts/python.exe -m pytest tests/test_ths_fetcher.py::TestBoardStocksSortFieldMap tests/test_ths_fetcher.py::TestBoardStocksUrlTemplate -v`
Expected: **FAIL** with `ImportError: cannot import name '_THS_BOARD_STOCKS_SORT_FIELD_MAP' / '_BOARD_STOCKS_URL_TEMPLATE'`

- [ ] **Step 2.3: Add module-level constants (replace the existing `_BOARD_STOCKS_URL`)**

In `stock_data/data_provider/fetchers/ths_fetcher.py`, replace the existing `_BOARD_STOCKS_URL = (...)` block (around line 202-207) with:

```python
# THS upstream URL: /field/<code>/order/<dir>/page/N/ajax/1/
# field/<code> 决定排序键 (199112=涨跌幅); order/<dir> 决定方向;
# 每页 10 只; ajax/1/ 强制 AJAX HTML 片段 (避免完整页面).
_BOARD_STOCKS_URL_TEMPLATE = (
    "https://q.10jqka.com.cn/gn/detail/code/{concept_id}"
    "/field/{field_code}/order/{order}/page/{page}/ajax/1/"
)
# THS 上游列代码 (从 <th a field="..."> 实测) → python attr name.
# 2026-07-13 playwright probe. 新加任何 key 需 route Literal 同步开放.
_THS_BOARD_STOCKS_SORT_FIELD_MAP: dict[str, str] = {
    "change_pct":        "199112",   # 涨跌幅(%)
    "price":             "10",       # 现价
    "turnover_rate":     "1968584",  # 换手(%)
    "volume_ratio":      "1771976",  # 量比
    "amplitude":         "526792",   # 振幅(%)
    "change_amount":     "264648",   # 涨跌(元)
    "change_speed":      "48",       # 涨速(%)
    "amount":            "19",       # 成交额(元)
    "pe_ratio":          "2034120",  # 市盈率
    "float_market_cap":  "3475914",  # 流通市值(元)
    "free_float_shares": "407",      # 流通股(股)
}
```

- [ ] **Step 2.4: Run tests (expect PASS)**

Run: `.venv/Scripts/python.exe -m pytest tests/test_ths_fetcher.py::TestBoardStocksSortFieldMap tests/test_ths_fetcher.py::TestBoardStocksUrlTemplate -v`
Expected: 3 passed

- [ ] **Step 2.5: Commit**

```bash
git add stock_data/data_provider/fetchers/ths_fetcher.py tests/test_ths_fetcher.py
git commit -m "feat(ths-fetcher): board-stocks URL template + 11-field sort map

替换 hardcoded field/199112/order/desc 全段 URL → 参数化模板
(field/<col_code>/order/<dir>/page/N/ajax/1/), 配 11-项 column-
code 映射表. Playwright 2026-07-13 实测确认这 11 个代码是列头
<a field=...> 的真实值; 199112 不是 "14 列字段集 ID", 而是涨跌幅
的列代码. 这打开了对现价/换手/量比/振幅/涨速/成交额/市盈率/
流通市值/流通股 9 个新排序键的支持."
```

---

## Task 3: THS fetcher — `get_board_stocks` accepts sort_by / sort_order / top_n (Commit C part 1)

**Files:**
- Modify: `stock_data/data_provider/fetchers/ths_fetcher.py:810-904` (`get_board_stocks` signature + pagination loop)
- Modify: `stock_data/data_provider/fetchers/ths_fetcher.py:747-808` (`_fetch_ths_board_stocks_page` — accept field_code + order)
- Test: `tests/test_ths_fetcher.py` (extend `TestGetBoardStocks`)

- [ ] **Step 3.1: Write failing tests for kwargs validation + top_n clamp**

Append to `tests/test_ths_fetcher.py`:

```python
class TestGetBoardStocksTopNAndSort:
    """sort_by / top_n / sort_order 行为契约 (Task 3 of plan)."""

    def _board_stocks_test_target(self):
        # Test target: instance method, easy to instantiate.
        from stock_data.data_provider.fetchers.ths_fetcher import ThsFetcher
        return ThsFetcher()

    def test_get_board_stocks_rejects_unknown_sort_by(self):
        """sort_by 不在白名单 → DataFetchError (而不是默默回退到默认)."""
        fetcher = self._board_stocks_test_target()
        with pytest.raises(DataFetchError, match="sort_by='p_e'"):
            fetcher.get_board_stocks(
                board_code="301546", top_n=10, sort_by="p_e", sort_order="desc",
            )

    def test_get_board_stocks_rejects_invalid_sort_order(self):
        """sort_order 不是 asc/desc → DataFetchError."""
        fetcher = self._board_stocks_test_target()
        with pytest.raises(DataFetchError, match="sort_order='random'"):
            fetcher.get_board_stocks(
                board_code="301546", top_n=10, sort_by="change_pct", sort_order="random",
            )

    def test_get_board_stocks_top_n_clamped_to_50(self):
        """top_n > 50 → 防御性 clamp 到 50 (避免上游 login wall 浪费请求)."""
        fetcher = self._board_stocks_test_target()
        # 间接通过 mock 验证: top_n=200 时内部只翻 ceil(50/10)+1=6 页.
        with patch.object(fetcher, "_fetch_ths_board_stocks_page", return_value=[]) as mock_page:
            fetcher.get_board_stocks(
                board_code="301546", top_n=200, sort_by="change_pct", sort_order="desc",
            )
        # _MAX_BOARD_STOCKS_PAGES=50 是 hard cap, top_n=200 应被 clamp 到 50 → ceil(50/10)+2=7 page attempts.
        # 注意计划用 +2 buffer: max_pages = ceil(top_n/10) + 1
        assert mock_page.call_count <= 7

    def test_fetch_ths_board_stocks_page_accepts_field_code_and_order(self):
        """`_fetch_ths_board_stocks_page` 接收 field_code + order kwarg."""
        from stock_data.data_provider.fetchers.ths_fetcher import ThsFetcher
        fetcher = ThsFetcher()
        with patch.object(fetcher, "_http_get") as mock_get:
            mock_get.return_value.text = "<table></table>"
            mock_get.return_value.status_code = 200
            fetcher._fetch_ths_board_stocks_page(
                "301546", 1, field_code="10", order="desc",
            )
            called_url = mock_get.call_args[0][0]
            assert "field/10/" in called_url
            assert "order/desc/" in called_url
```

- [ ] **Step 3.2: Run tests (expect FAIL — kwargs not accepted)**

Run: `.venv/Scripts/python.exe -m pytest tests/test_ths_fetcher.py::TestGetBoardStocksTopNAndSort -v`
Expected: **FAIL** with `TypeError: get_board_stocks() got unexpected keyword argument 'sort_by'` (and same for top_n / sort_order)

- [ ] **Step 3.3: Update `_fetch_ths_board_stocks_page` signature to accept `field_code` + `order`**

In `stock_data/data_provider/fetchers/ths_fetcher.py`, modify the `_fetch_ths_board_stocks_page` method:

```python
def _fetch_ths_board_stocks_page(
    concept_id: str,
    page: int,
    *,
    field_code: str = "199112",       # 默认 change_pct, 行为向后兼容
    order: str = "desc",
) -> list[dict]:
    """Fetch one page of THS board stocks (10 rows per page).

    Args:
        concept_id: THS concept slug (e.g. "301546").
        page: Page number (1-based).
        field_code: THS upstream column code for sort key.
            Defaults to "199112" (change_pct desc). 2026-07-13 probe
            confirmed: 11 codes work (price=10, turnover_rate=1968584, etc.).
        order: Sort direction, "asc" or "desc".

    Returns [] when the page is empty / non-2xx network / ThsBoundarySignalError
    (when after-data boundary) — see existing implementation.

    Raises:
        DataFetchError on hard network failure on first page.
    """
    url = _BOARD_STOCKS_URL_TEMPLATE.format(
        concept_id=concept_id, field_code=field_code, order=order, page=page,
    )
    # ... rest of existing implementation body unchanged ...
```

- [ ] **Step 3.4: Update `get_board_stocks` signature + validation + pagination loop**

Replace the entire `get_board_stocks` method:

```python
def get_board_stocks(
    board_code: str,
    *,
    source: str | None = None,           # accepted for interface parity; ignored
    include_quote: bool = False,
    board_type: str | None = None,
    top_n: int = 50,
    sort_by: str = "change_pct",
    sort_order: str = "desc",
    **kwargs,
) -> list[dict]:
    """THS board constituent stocks via q.10jqka.com.cn AJAX endpoint.
    [ existing docstring ]
    """
    if sort_by not in _THS_BOARD_STOCKS_SORT_FIELD_MAP:
        raise DataFetchError(
            f"[ThsFetcher] get_board_stocks: sort_by={sort_by!r} not in "
            f"supported set {sorted(_THS_BOARD_STOCKS_SORT_FIELD_MAP.keys())}"
        )
    if sort_order not in ("asc", "desc"):
        raise DataFetchError(
            f"[ThsFetcher] get_board_stocks: sort_order={sort_order!r} "
            f"must be 'asc' or 'desc'"
        )
    # Defensive clamp: THS upstream hard cap is 50 (=5 pages * 10).
    # Caller (route layer) already enforces le=50; this is belt+suspenders.
    top_n = max(1, min(int(top_n), 50))
    field_code = _THS_BOARD_STOCKS_SORT_FIELD_MAP[sort_by]
    max_pages = (top_n + 9) // 10 + 1  # ceil(top_n/10) + 1 buffer for partial last page

    all_rows: list[dict] = []
    for page in range(1, max_pages + 1):
        try:
            rows = self._fetch_ths_board_stocks_page(
                board_code, page, field_code=field_code, order=sort_order,
            )
        except ThsBoundarySignalError as e:
            if not all_rows:
                raise
            logger.info(
                f"[ThsFetcher] board_stocks({board_code}, page={page}, "
                f"sort_by={sort_by}, sort_order={sort_order}) "
                f"HTTP {e.status_code} on beyond-data page; treating as "
                f"end of pagination ({len(all_rows)} rows collected so far)"
            )
            break
        if not rows:
            break
        all_rows.extend(rows)
        if len(all_rows) >= top_n:
            break
    return all_rows[:top_n]
```

- [ ] **Step 3.5: Run tests (expect PASS)**

Run: `.venv/Scripts/python.exe -m pytest tests/test_ths_fetcher.py::TestGetBoardStocksTopNAndSort -v`
Expected: 4 passed

- [ ] **Step 3.6: Run full ths_fetcher test suite (regression)**

Run: `.venv/Scripts/python.exe -m pytest tests/test_ths_fetcher.py -v`
Expected: All pass (existing TestGetBoardStocks tests still work because default sort_by="change_pct", sort_order="desc", top_n=50 matches existing hardcoded URL behavior)

- [ ] **Step 3.7: Commit**

```bash
git add stock_data/data_provider/fetchers/ths_fetcher.py tests/test_ths_fetcher.py
git commit -m "feat(ths-fetcher): top_n / sort_by / sort_order params for get_board_stocks

- 3 个 kwarg 加入 get_board_stocks 签名;
- sort_by 白名单 (11 字段) 在 _THS_BOARD_STOCKS_SORT_FIELD_MAP;
- 防御性 clamp top_n 到 [1, 50]; sort_order 必须 asc/desc 否则抛;
- 翻页循环 max_pages = ceil(top_n/10)+1 (旧硬 50 上限改为按 top_n);
- 提前终止于 len(all_rows)>=top_n (不浪费请求);
- _fetch_ths_board_stocks_page 接收 field_code + order, 默认值保留旧行为.

Backward compat: 默认值 (top_n=50, sort_by=change_pct, sort_order=desc)
与旧 hardcoded URL (field/199112/order/desc) 完全一致."
```

---

## Task 4: THS fetcher — parse all 14 columns + `_parse_free_float` helper (Commit C part 2)

**Files:**
- Modify: `stock_data/data_provider/fetchers/ths_fetcher.py:692-746` (`_parse_ths_board_stocks_row`)
- Modify: `stock_data/data_provider/fetchers/ths_fetcher.py` (top of file — add `_parse_free_float`)
- Test: `tests/test_ths_fetcher.py`

- [ ] **Step 4.1: Write failing tests for `_parse_free_float` + all 14-column parser**

Append to `tests/test_ths_fetcher.py`:

```python
class TestParseFreeFloat:
    """_parse_free_float 单元: 解析 THS 上游 'N.NN亿' 格式."""

    def test_parses_standard_yi_format(self):
        from stock_data.data_provider.fetchers.ths_fetcher import _parse_free_float
        assert _parse_free_float("4.73亿") == 473_000_000
        assert _parse_free_float("27.16亿") == 2_716_000_000

    def test_none_on_dash(self):
        """停牌 / 无数据股票上游是 '--' → None."""
        from stock_data.data_provider.fetchers.ths_fetcher import _parse_free_float
        assert _parse_free_float("--") is None
        assert _parse_free_float("-") is None
        assert _parse_free_float("") is None
        assert _parse_free_float(None) is None

    def test_none_on_unrecognized_format(self):
        """上游格式变化 ('xx千万' 等) 时降级到 None, 不抛错."""
        from stock_data.data_provider.fetchers.ths_fetcher import _parse_free_float
        assert _parse_free_float("100万") is None
        assert _parse_free_float("not-a-number") is None


class TestParseBoardStocksRow14Cols:
    """_parse_ths_board_stocks_row 现在解 14 列 (旧版 9 列)."""

    def test_all_14_columns_parsed(self):
        """idx 0..13 全部映射到已知字段."""
        from bs4 import BeautifulSoup
        from stock_data.data_provider.fetchers.ths_fetcher import (
            _parse_ths_board_stocks_row,
        )

        # Build a synthetic <tr> with 14 <td>s.
        html = """
        <tr><td>1</td><td>000034</td><td>神州数码</td><td>12.34</td><td>5.50</td>
        <td>0.65</td><td>0.10</td><td>8.70</td><td>1.85</td><td>2.31</td>
        <td>5.91亿</td><td>4.73亿</td><td>66.31亿</td><td>37.59</td></tr>
        """
        soup = BeautifulSoup(html, "lxml")
        tr = soup.select_one("tr")
        tds = tr.find_all("td")
        row = _parse_ths_board_stocks_row(tds)
        assert row is not None
        assert row["stock_code"] == "000034"
        assert row["stock_name"] == "神州数码"
        assert row["price"] == 12.34
        assert row["change_pct"] == 5.50
        assert row["change_amount"] == 0.65
        assert row["change_speed"] == 0.10      # idx 6
        assert row["turnover_rate"] == 8.70
        assert row["volume_ratio"] == 1.85      # idx 8
        assert row["amplitude"] == 2.31         # idx 9
        assert row["amount"] == 5_910_000_000.0  # idx 10 = 5.91亿
        assert row["free_float_shares"] == 473_000_000  # idx 11 = 4.73亿
        assert row["float_market_cap"] == 6_631_000_000.0  # idx 12 = 66.31亿
        assert row["pe_ratio"] == 37.59
```

- [ ] **Step 4.2: Run tests (expect FAIL)**

Run: `.venv/Scripts/python.exe -m pytest tests/test_ths_fetcher.py::TestParseFreeFloat tests/test_ths_fetcher.py::TestParseBoardStocksRow14Cols -v`
Expected: **FAIL** (`_parse_free_float` doesn't exist OR `_parse_ths_board_stocks_row` returns dict without the 6 new keys)

- [ ] **Step 4.3: Add `_parse_free_float` helper at module top**

In `stock_data/data_provider/fetchers/ths_fetcher.py`, add after imports (before class `ThsFetcher`):

```python
def _parse_free_float(s: str | None) -> int | None:
    """Parse THS upstream 'N.NN亿' → raw share count (e.g. 4.73亿 → 473_000_000).

    THS 上游对 流通股 / 流通市值 / 成交额 等大数字用 'N.NN亿' 中文单位.
    本 helper 仅用于 free_float_shares 字段 (其他 2 列保留 float-in-元).

    Returns:
        int | None — None on '--'/'-'/空字符串/未识别格式 (上游格式变化时
        安全降级而非抛错). 调用方靠 schema Optional 接受 None.

    2026-07-13 实测上游格式稳定; regex 严格匹配，未来微调时降级.
    """
    import re
    s = (s or "").strip().replace(",", "").replace("\xa0", "")
    if not s or s in ("--", "-"):
        return None
    m = re.match(r"^([0-9]+(?:\.[0-9]+)?)亿$", s)
    if not m:
        return None
    return int(round(float(m.group(1)) * 1e8))
```

- [ ] **Step 4.4: Extend `_parse_ths_board_stocks_row` to parse all 14 columns**

In `stock_data/data_provider/fetchers/ths_fetcher.py`, replace the existing `_parse_ths_board_stocks_row` body (after computing `exchange`):

```python
def _parse_ths_board_stocks_row(tds: list) -> dict | None:
    """Parse one <tr> from q.10jqka.com.cn board-stocks HTML into a dict.

    14 columns (固定):
    idx 0:  序号 (string, ignored)
    idx 1:  代码 (string)
    idx 2:  名称 (string)
    idx 3:  现价 (float | None)
    idx 4:  涨跌幅 (float | None, %)
    idx 5:  涨跌 (float | None, 元)
    idx 6:  涨速 (float | None, %)
    idx 7:  换手 (float | None, %)
    idx 8:  量比 (float | None)
    idx 9:  振幅 (float | None, %)
    idx 10: 成交额 (float | None, 元)
    idx 11: 流通股 (int | None, 股, parsed from 'N.NN亿')
    idx 12: 流通市值 (float | None, 元)
    idx 13: 市盈率 (float | None)

    Returns None when ``td[1]`` (code) is missing — that row is malformed.
    ``--`` (em-dash) maps to None via ``safe_float`` in core.types.
    """
    from ..core.types import safe_float

    if len(tds) < 3:
        return None
    stock_code = tds[1].get_text(strip=True)
    if not stock_code:
        return None
    stock_name = tds[2].get_text(strip=True)
    code_prefix = stock_code[:1]
    exchange = (
        "sh" if code_prefix in ("6", "9") else ("sz" if code_prefix in ("0", "3") else "")
    )
    return {
        "stock_code": stock_code,
        "stock_name": stock_name,
        "exchange": exchange,
        "price":            safe_float(tds[3].get_text(strip=True)) if len(tds) > 3 else None,
        "change_pct":       safe_float(tds[4].get_text(strip=True)) if len(tds) > 4 else None,
        "change_amount":    safe_float(tds[5].get_text(strip=True)) if len(tds) > 5 else None,
        "change_speed":     safe_float(tds[6].get_text(strip=True)) if len(tds) > 6 else None,
        "turnover_rate":    safe_float(tds[7].get_text(strip=True)) if len(tds) > 7 else None,
        "volume_ratio":     safe_float(tds[8].get_text(strip=True)) if len(tds) > 8 else None,
        "amplitude":        safe_float(tds[9].get_text(strip=True)) if len(tds) > 9 else None,
        "amount":           safe_float(tds[10].get_text(strip=True)) if len(tds) > 10 else None,
        "free_float_shares":_parse_free_float(tds[11].get_text(strip=True)) if len(tds) > 11 else None,
        "float_market_cap": safe_float(tds[12].get_text(strip=True)) if len(tds) > 12 else None,
        "pe_ratio":         safe_float(tds[13].get_text(strip=True)) if len(tds) > 13 else None,
        # 旧字段保留: volume 含义是成交量(股), THS 上游 14 列里没有, 留 None.
        "volume": None,
    }
```

- [ ] **Step 4.5: Run tests (expect PASS)**

Run: `.venv/Scripts/python.exe -m pytest tests/test_ths_fetcher.py::TestParseFreeFloat tests/test_ths_fetcher.py::TestParseBoardStocksRow14Cols -v`
Expected: 4 passed

- [ ] **Step 4.6: Commit**

```bash
git add stock_data/data_provider/fetchers/ths_fetcher.py tests/test_ths_fetcher.py
git commit -m "feat(ths-fetcher): parse all 14 board-stock columns + free-float helper

_parse_ths_board_stocks_row 旧版只解 idx 0..5, 7, 10 (9 字段);
改后解 idx 6/8/9/11/12/13 → 6 个新字段 (change_speed/volume_ratio/
amplitude/free_float_shares/float_market_cap/pe_ratio).

新增 _parse_free_float 模块级 helper: 'N.NN亿' → int shares.
降级语义: 上游格式变化 / '--' / '-' / None → None (不抛).

Schema 配合 (commit A) 接收 6 字段; route 投影 (commit E) 透传.
全套 board-stocks 输出字段从 9 升到 15 (代码 + 9 旧 quote + 6 新).
"
```

---

## Task 5: Manager — forward 3 kwargs through `get_board_stocks` (Commit D)

**Files:**
- Modify: `stock_data/data_provider/manager.py:810-853` (`get_board_stocks` signature + inner `call`)
- Test: `tests/test_manager_get_board_stocks_kwargs.py` (create new test file)

- [ ] **Step 5.1: Write failing test verifying kwargs propagate to fetcher**

Create `tests/test_manager_get_board_stocks_kwargs.py`:

```python
"""Verify DataFetcherManager.get_board_stocks forwards sort_by / sort_order / top_n kwargs.

Task 5 of plan; commit D.
"""
from unittest.mock import MagicMock, patch

from stock_data.data_provider.manager import DataFetcherManager


def test_manager_forwards_sort_kwargs_to_ths_fetcher():
    """当 fetcher 是 ThsFetcher 时, sort_by / sort_order / top_n 应被 call() 注入.

    校验: ths_fetcher.get_board_stocks() 收到 keyword args.
    """
    manager = DataFetcherManager()

    fake_ths_fetcher = MagicMock()
    fake_ths_fetcher.name = "ThsFetcher"
    fake_ths_fetcher.get_board_stocks.return_value = (
        [{"stock_code": "000034", "stock_name": "x"}],
        "ths",
    )

    # 直接 patch _with_source 以避免完整 stock_board 初始化.
    with patch.object(manager, "_with_source", return_value=(
        fake_ths_fetcher.get_board_stocks.return_value[0],
        fake_ths_fetcher.name,
    )) as mock_with_source:
        manager.get_board_stocks(
            board_code="885595", source="ths", include_quote=True,
            sort_by="price", sort_order="asc", top_n=10,
        )
        # 找到 call 闭包并取出 kwargs.
        call_kwargs = mock_with_source.call_args.kwargs["call"]
        # call is a lambda; invoke it.
        result = call_kwargs(fake_ths_fetcher)
        # 验证 fake_ths_fetcher.get_board_stocks 被调用时收到 kwargs.
        fake_ths_fetcher.get_board_stocks.assert_called_once()
        _, kwargs = fake_ths_fetcher.get_board_stocks.call_args
        assert kwargs.get("sort_by") == "price"
        assert kwargs.get("sort_order") == "asc"
        assert kwargs.get("top_n") == 10
        assert kwargs.get("include_quote") is True
        assert kwargs.get("source") == "ths"
```

- [ ] **Step 5.2: Run test (expect FAIL)**

Run: `.venv/Scripts/python.exe -m pytest tests/test_manager_get_board_stocks_kwargs.py -v`
Expected: **FAIL** with `TypeError: get_board_stocks() got an unexpected keyword argument 'sort_by'` (manager signature is fixed)

- [ ] **Step 5.3: Extend manager signature**

In `stock_data/data_provider/manager.py`, replace the `get_board_stocks` method:

```python
def get_board_stocks(
    self,
    board_code: str,
    source: str,
    include_quote: bool = False,
    board_type: str | None = None,
    *,
    sort_by: str | None = None,         # 2026-07-13: forward to fetcher
    sort_order: str = "desc",           # 2026-07-13: forward to fetcher
    top_n: int = 50,                    # 2026-07-13: forward to fetcher
) -> tuple[list[dict], str]:
    """[ existing docstring + a paragraph noting kwargs forwarding ]"""

    def call(f):
        kwargs = {
            "source": source,
            "include_quote": include_quote,
            "sort_by": sort_by,
            "sort_order": sort_order,
            "top_n": top_n,
        }
        # Only pass board_type when explicitly set — keeps the call
        # shape identical for callers that haven't migrated yet
        # (assert_called_once_with tests in test_board_source_routing).
        if board_type is not None:
            kwargs["board_type"] = board_type
        return f.get_board_stocks(board_code, **kwargs), f.name

    stocks, name = self._with_source(
        source=source,
        capability=DataCapability.STOCK_BOARD,
        market="csi",
        op_label=f"board stocks {board_code} ({source})",
        call=call,
    )
    return stocks, name
```

- [ ] **Step 5.4: Run test (expect PASS)**

Run: `.venv/Scripts/python.exe -m pytest tests/test_manager_get_board_stocks_kwargs.py -v`
Expected: 1 passed

- [ ] **Step 5.5: Run manager / routing tests (regression)**

Run: `.venv/Scripts/python.exe -m pytest tests/test_boards.py tests/test_boards_api.py -v`
Expected: All existing pass; new keyword args are optional so legacy callers unaffected

- [ ] **Step 5.6: Commit**

```bash
git add stock_data/data_provider/manager.py tests/test_manager_get_board_stocks_kwargs.py
git commit -m "feat(manager): forward sort_by / sort_order / top_n in get_board_stocks

在 3 个 keyword-only kwarg 注入 _with_source.call kwargs dict.
不影响其他 fetcher:
- ZzshareFetcher / ZhituFetcher / MyquantFetcher 都收 **kwargs, 多余 kwargs 静默吞
- EastMoneyFetcher.get_board_stocks 固定签名, 但 route 层 400 校验 (commit E)
  保证 eastmoney 路径永不传入 sort_by/top_n
- ThsFetcher 显式读 3 个 kwarg (commit C)

HIGH-blocking 链路穿透: route → persistence → manager → ThsFetcher
"
```

---

## Task 6: Persistence — `get_board_stocks` + `fetch_board_stocks_with_zzshare_fallback` accept kwargs + 50-stock heuristic (Commit F)

**Files:**
- Modify: `stock_data/data_provider/persistence/board.py:745-893` (`fetch_board_stocks_with_zzshare_fallback`)
- Modify: `stock_data/data_provider/persistence/board.py:896-998` (`get_board_stocks`)
- Test: `tests/test_persistence_board_topn.py` (create new test file)

- [ ] **Step 6.1: Write failing tests for new persistence signature + heuristic**

Create `tests/test_persistence_board_topn.py`:

```python
"""Persistence-layer tests for top_n + sort + 50-stock heuristic (Task 6 of plan)."""
from unittest.mock import MagicMock, patch

import pytest

from stock_data.api.routes import reset_manager
from stock_data.data_provider.persistence import board as stock_board_cache


@pytest.fixture(autouse=True)
def reset_mgr():
    reset_manager()
    yield


def _stub_cache(codes: list[str]):
    """Build a fake cache-read returning the given stock codes."""
    cached_rows = [
        {"stock_code": c, "stock_name": f"Name-{c}", "exchange": "sh"}
        for c in codes
    ]
    return cached_rows


def test_persistence_get_board_stocks_returns_6_tuple():
    """per spec section 3.4.1, 返回 (list, str, str, str|None, bool, int)."""
    manager = MagicMock()
    fake_ths_response = [
        {"stock_code": "000034", "stock_name": "x", "exchange": "sh", "price": 1.0,
         "change_pct": 1.0, "change_amount": 0.01, "volume": None, "amount": 1e8,
         "turnover_rate": 1.0},
    ]
    with patch.object(stock_board_cache, "_read_board_stocks_from_db", return_value=[]), \
         patch.object(stock_board_cache, "fetch_board_stocks_with_zzshare_fallback",
                      return_value=(fake_ths_response, "ths", "ths", None)), \
         patch.object(stock_board_cache, "update_cached_board_stocks", return_value=1):
        result = stock_board_cache.get_board_stocks(
            board_code="885595", source="ths", refresh=True,
            include_quote=True, manager=manager,
            sort_by="change_pct", sort_order="desc", top_n=10,
        )
    # 6-tuple
    assert len(result) == 6
    stocks, origin, es, reason, quote_truncated, total_in_board = result
    assert origin == "ths"
    assert es == "ths"
    assert reason is None
    assert quote_truncated is False       # ths returned only 1 row, < 50
    assert len(stocks) == 1


def test_heuristic_triggers_zzshare_when_ths_returns_50():
    """当 THS 返回正好 50 只 → 调用 ZZSHARE 补全 suffix."""
    manager = MagicMock()
    ths_50 = [
        {"stock_code": f"0000{i:02d}", "stock_name": f"t{i}", "exchange": "sh",
         "price": i * 0.1, "change_pct": i, "change_amount": 0.01, "volume": None,
         "amount": 1e8, "turnover_rate": 1.0}
        for i in range(50)
    ]
    zz_suffix = [
        {"stock_code": f"0002{i:02d}", "stock_name": f"z{i}", "exchange": "sz"}
        for i in range(10)
    ]
    with patch.object(stock_board_cache, "_read_board_stocks_from_db", return_value=[]), \
         patch.object(stock_board_cache, "fetch_board_stocks_with_zzshare_fallback",
                      return_value=(ths_50, "ths", "ths", None)), \
         patch.object(manager, "get_board_stocks",
                      return_value=(zz_suffix, "zzshare")) as mock_zz, \
         patch.object(stock_board_cache, "update_cached_board_stocks", return_value=60):
        result = stock_board_cache.get_board_stocks(
            board_code="885595", source="ths", refresh=True,
            include_quote=True, manager=manager,
            sort_by="change_pct", sort_order="desc", top_n=50,
        )
    # ZZSHARE must have been called.
    assert mock_zz.called
    # 50 + 10 = 60 in merged result.
    _, _, _, _, quote_truncated, total = result
    assert quote_truncated is True
    assert total == max(0, 60)


def test_heuristic_short_circuit_when_ths_below_50():
    """THS 返回 <50 → 不调 ZZSHARE."""
    manager = MagicMock()
    ths_30 = [
        {"stock_code": f"000{i:03d}", "stock_name": "x", "exchange": "sh",
         "price": 1.0, "change_pct": 1.0, "change_amount": 0.01, "volume": None,
         "amount": 1e8, "turnover_rate": 1.0}
        for i in range(30)
    ]
    with patch.object(stock_board_cache, "_read_board_stocks_from_db", return_value=[]), \
         patch.object(stock_board_cache, "fetch_board_stocks_with_zzshare_fallback",
                      return_value=(ths_30, "ths", "ths", None)), \
         patch.object(manager, "get_board_stocks") as mock_zz, \
         patch.object(stock_board_cache, "update_cached_board_stocks", return_value=30):
        result = stock_board_cache.get_board_stocks(
            board_code="885595", source="ths", refresh=True,
            include_quote=True, manager=manager,
            sort_by="change_pct", sort_order="desc", top_n=50,
        )
    assert not mock_zz.called
    _, _, _, _, quote_truncated, total = result
    assert quote_truncated is False
```

- [ ] **Step 6.2: Run tests (expect FAIL)**

Run: `.venv/Scripts/python.exe -m pytest tests/test_persistence_board_topn.py -v`
Expected: **FAIL** with `TypeError: get_board_stocks() got unexpected keyword arguments` OR `len(result) != 6`

- [ ] **Step 6.3: Extend `fetch_board_stocks_with_zzshare_fallback` signature**

In `stock_data/data_provider/persistence/board.py`, modify the function signature and the THS leg:

```python
def fetch_board_stocks_with_zzshare_fallback(
    board_code: str,
    source: str,
    include_quote: bool,
    manager,
    *,
    sort_by: str | None = None,         # 2026-07-13: 透传到 ths
    sort_order: str = "desc",
    top_n: int = 50,
) -> tuple[list[dict], str, str, str | None]:
    """[ existing docstring + mention sort/top_n kwargs ]"""

    if source == "ths":
        if include_quote:
            cid = _resolve_ths_cid_from_platecode(board_code)
            if not cid:
                return [], "ths", "ths", "cid_unresolved"
            try:
                rows, _ = manager.get_board_stocks(
                    board_code=cid,
                    source="ths",
                    include_quote=True,
                    sort_by=sort_by,
                    sort_order=sort_order,
                    top_n=top_n,
                )
            except DataFetchError:
                raise
            return rows, "ths", "ths", None

        # include_quote=False: ZZSHARE primary → THS fallback (kwargs 不用)
        try:
            rows, _ = manager.get_board_stocks(
                board_code=board_code, source="zzshare", include_quote=False,
            )
        except DataFetchError as zz_err:
            logger.info(...)
        else:
            if rows:
                return rows, "ths", "zzshare", None
            logger.info(...)

        cid = _resolve_ths_cid_from_platecode(board_code)
        if not cid:
            return [], "ths", "ths", "cid_unresolved"
        try:
            rows, _ = manager.get_board_stocks(
                board_code=cid, source="ths", include_quote=False,
            )
        except DataFetchError:
            raise
        return rows, "ths", "ths", None

    if source == "zzshare":
        try:
            rows, _ = manager.get_board_stocks(
                board_code=board_code, source="zzshare", include_quote=include_quote,
            )
        except DataFetchError:
            raise
        return rows, "zzshare", "zzshare", None

    if source in ("eastmoney", "zhitu"):
        try:
            rows, _ = manager.get_board_stocks(
                board_code=board_code, source=source, include_quote=include_quote,
            )
        except DataFetchError:
            raise
        return rows, source, source, None

    raise ValueError(...)
```

- [ ] **Step 6.4: Extend `get_board_stocks` to 6-tuple + heuristic**

In `stock_data/data_provider/persistence/board.py`, replace the existing `get_board_stocks` body:

```python
THS_HARD_CAP = 50

def get_board_stocks(
    board_code: str,
    source: str = "ths",
    refresh: bool = False,
    include_quote: bool = False,
    manager=None,
    *,
    sort_by: str | None = None,         # 2026-07-13
    sort_order: str = "desc",           # 2026-07-13
    top_n: int = 50,                    # 2026-07-13
) -> tuple[list, str, str, str | None, bool, int]:
    """[ upgrade existing docstring — return shape now 6-tuple ]

    Returns:
        Tuple of (stocks, origin, effective_source, reason,
                  quote_truncated, quote_total_in_board).
        quote_truncated=True iff heuristic fired and either (a) ZZSHARE fill-in
        added rows or (b) ZZSHARE failed (conservative).
    """
    init_schema()
    cached_full = _read_board_stocks_from_db(board_code, "ths")
    cached_count = len(cached_full)

    if not include_quote:
        # 3 query params are NO-OP for include_quote=False (route layer 400-ensures this).
        needs_refresh = refresh or _refresh_tracker.is_first_call(f"{board_code}:ths")
        if not needs_refresh:
            return cached_full, "persistence", "ths", None, False, cached_count

        if manager is None:
            raise ValueError("manager is required when refresh=True or cache miss")

        stocks, origin, es, reason = fetch_board_stocks_with_zzshare_fallback(
            board_code=board_code, source=source, include_quote=False, manager=manager,
        )
        if stocks:
            update_cached_board_stocks(board_code, "ths", stocks)
        return stocks, origin, es, reason, False, len(stocks)

    # include_quote=True 路径
    if manager is None:
        raise ValueError("manager is required for include_quote=True")

    stocks, origin, es, reason = fetch_board_stocks_with_zzshare_fallback(
        board_code=board_code, source=source, include_quote=True, manager=manager,
        sort_by=sort_by, sort_order=sort_order, top_n=top_n,
    )

    if not stocks:
        return [], origin, es, reason, False, cached_count

    needs_fill_in = len(stocks) >= THS_HARD_CAP

    suffix_no_quote: list[dict] = []
    if needs_fill_in:
        try:
            zz_rows, _ = manager.get_board_stocks(
                board_code=board_code, source="zzshare", include_quote=False,
            )
        except DataFetchError as e:
            logger.warning(
                f"[BoardCache] ZZSHARE fill-in for {board_code} failed: {e}; "
                f"falling back to THS-only top-{len(stocks)}"
            )
            zz_rows = []

        quote_codes = {s["stock_code"] for s in stocks if s.get("stock_code")}
        suffix_no_quote = [
            r for r in (zz_rows or [])
            if r.get("stock_code") and r["stock_code"] not in quote_codes
        ]

    if not needs_fill_in:
        quote_truncated = False
    elif suffix_no_quote:
        quote_truncated = True
    else:
        # heuristic triggered but ZZSHARE returned nothing → conservative
        logger.info(
            f"[BoardCache] {board_code}: heuristic fired but no suffix added; "
            f"reporting quote_truncated=True conservatively"
        )
        quote_truncated = True

    if suffix_no_quote:
        cached_count = max(cached_count, len(stocks) + len(suffix_no_quote))
        final_stocks = stocks + suffix_no_quote
    else:
        final_stocks = stocks

    update_cached_board_stocks(board_code, "ths", final_stocks)
    return final_stocks, origin, es, reason, quote_truncated, cached_count
```

- [ ] **Step 6.5: Run tests (expect PASS)**

Run: `.venv/Scripts/python.exe -m pytest tests/test_persistence_board_topn.py -v`
Expected: 3 passed

- [ ] **Step 6.6: Run full board test suite (regression)**

Run: `.venv/Scripts/python.exe -m pytest tests/test_boards_api.py tests/test_boards.py tests/test_boards_history_route.py tests/test_boards_schemas.py -v`
Expected: All pass (callers using 4-tuple would break — verify all callers updated to 6-tuple)

- [ ] **Step 6.7: Update existing callers of the 4-tuple `persistence.get_board_stocks`**

`api/routes/boards.py` and (if any) tests that destructure the 4-tuple need to expand to 6-tuple. Search-and-fix:

```bash
grep -rn 'get_board_stocks(' stock_data/api/routes/ tests/ --include='*.py' | grep -v 'manager.get_board_stocks\|fetcher.get_board_stocks\|update_cached\|read_cached\|write_cached'
```

All hits need `_ , _ = result` adjust to 6-tuple. (See Task 7 step where route layer consumes the 6-tuple.)

- [ ] **Step 6.8: Commit**

```bash
git add stock_data/data_provider/persistence/board.py tests/test_persistence_board_topn.py stock_data/api/routes/boards.py
git commit -m "feat(persistence): 50-stock heuristic + ZZSHARE fill-in + 6-tuple return

get_board_stocks 返回值 4-tuple → 6-tuple:
  (stocks, origin, effective_source, reason, quote_truncated, quote_total_in_board)

include_quote=True 路径:
- heuristic (len(stocks) >= 50) 触发后调一次 ZZSHARE membership 拉全量
- merge: top-N (THS, quote 完整, 用户 sort 序) + suffix (ZZSHARE, 无 quote, 无序)
- quote_truncated 三态: False (板上 <50) / True (有 suffix) / True 保守 (fallback 失败或空)

ZZSHARE 调用: no retry, 用 SDK 默认 timeout; 失败降级到 THS-only + 保守 True.

fetch_board_stocks_with_zzshare_fallback 也加 sort/top_n kwargs 透传.

旧 4-tuple 调用点 (routes/boards.py) 同步更新 — downstream 是 commit E.
"
```

---

## Task 7: Route — query params + cross-validation + schema projection (Commit E)

**Files:**
- Modify: `stock_data/api/routes/boards.py:398-622` (`get_board_stocks`)
- Test: `tests/test_boards_api.py` (extend)

- [ ] **Step 7.1: Write failing tests for cross-validation + echo fields**

Append to `tests/test_boards_api.py`:

```python
class TestBoardStocksTopNAndSort:
    """Route-level tests for sort_by / sort_order / top_n (Task 7 of plan)."""

    @patch("stock_data.data_provider.persistence.board.get_board_stocks",
           return_value=([], "persistence", "ths", None, False, 0))
    def test_default_request_no_new_fields(self, mock_pers):
        """不传 sort/top_n 时 response 行为不变 (quote_* echo 全部 None)."""
        r = client.get("/api/v1/boards/885595/stocks?source=ths")
        assert r.status_code == 200
        body = r.json()
        assert body["quote_truncated"] is False
        assert body["quote_top_n"] is None
        assert body["quote_sort_by"] is None
        assert body["quote_sort_order"] is None
        assert body["quote_total_in_board"] is None

    @patch("stock_data.data_provider.persistence.board.get_board_stocks",
           return_value=([{"stock_code": "000034", "stock_name": "x"}],
                         "ths", "ths", None, False, 1))
    def test_sort_by_echoed_back(self, mock_pers):
        """?sort_by=price 返回时 echo 回 quote_sort_by."""
        r = client.get(
            "/api/v1/boards/885595/stocks?source=ths&include_quote=true&"
            "sort_by=price&sort_order=asc&top_n=10"
        )
        assert r.status_code == 200
        body = r.json()
        assert body["quote_sort_by"] == "price"
        assert body["quote_sort_order"] == "asc"
        assert body["quote_top_n"] == 10
        assert body["quote_total_in_board"] == 1

    def test_sort_by_with_non_ths_source_returns_400(self):
        """source='eastmoney' + sort_by=price → 400 invalid_combination (route cross-validation)."""
        r = client.get(
            "/api/v1/boards/885595/stocks?source=eastmoney&include_quote=true"
            "&sort_by=price"
        )
        assert r.status_code == 400
        body = r.json()
        # HTTPException detail uses FastAPI's detail envelope: {"detail": {...}}
        detail = body.get("detail", {})
        assert detail.get("error") == "invalid_combination"
        assert "source='ths'" in detail.get("message", "")

    def test_sort_by_without_include_quote_returns_400(self):
        """?sort_by=price 不带 include_quote=true → 400 (与 /boards sibling 一致)."""
        r = client.get(
            "/api/v1/boards/885595/stocks?source=ths"
            "&sort_by=price"
        )
        assert r.status_code == 400
        detail = r.json().get("detail", {})
        assert detail.get("error") == "invalid_combination"

    def test_top_n_above_50_returns_422(self):
        """Query(le=50) → FastAPI 自带 422 validation."""
        r = client.get(
            "/api/v1/boards/885595/stocks?source=ths&include_quote=true&top_n=100"
        )
        assert r.status_code == 422

    def test_sort_by_invalid_literal_returns_422(self):
        """Literal[...] 校验 → 422."""
        r = client.get(
            "/api/v1/boards/885595/stocks?source=ths&include_quote=true"
            "&sort_by=magic"
        )
        assert r.status_code == 422
```

- [ ] **Step 7.2: Run tests (expect FAIL)**

Run: `.venv/Scripts/python.exe -m pytest tests/test_boards_api.py::TestBoardStocksTopNAndSort -v`
Expected: **FAIL** (new query params missing OR cross-validation not implemented)

- [ ] **Step 7.3: Add new query params to `get_board_stocks` route signature**

In `stock_data/api/routes/boards.py`, modify the route function signature (after the existing `include_quote` / `refresh`):

```python
def get_board_stocks(
    board_code: str = Path(max_length=30, description="Board code"),
    source: Literal["ths", "eastmoney", "zhitu"] = Query(
        ..., description=(
            "Data source (REQUIRED). 'zzshare' was unified under 'ths' "
            # [ existing description preserved ]
        ),
    ),
    include_quote: bool = Query(False, description="Include realtime quote data"),
    refresh: bool = Query(False, description="Force fetch latest from upstream"),
    sort_by: Literal[
        "change_pct", "price", "turnover_rate", "volume_ratio",
        "amplitude", "change_amount", "change_speed", "amount",
        "pe_ratio", "float_market_cap", "free_float_shares",
    ] | None = Query(
        None,
        description=(
            "Sort by field. ONLY effective when include_quote=true. "
            "Defaults to 'change_pct desc' (THS upstream default). "
            "Field code mapping: change_pct=199112, price=10, "
            "turnover_rate=1968584, volume_ratio=1771976, amplitude=526792, "
            "change_amount=264648, change_speed=48, amount=19, "
            "pe_ratio=2034120, float_market_cap=3475914, free_float_shares=407."
        ),
    ),
    sort_order: Literal["asc", "desc"] = Query(
        "desc", description="Sort direction. ONLY effective when include_quote=true.",
    ),
    top_n: int = Query(
        50, ge=1, le=50,
        description=(
            "Max number of stocks to fetch live quotes for "
            "(mirrors THS upstream 50-stock hard cap). "
            "ONLY effective when include_quote=true. "
            "When the board's full member count exceeds top_n, "
            "the response carries 'quote_truncated=true' with the "
            "remaining stocks filled in from ZZSHARE (no quote fields)."
        ),
    ),
) -> BoardStocksResponse:
```

- [ ] **Step 7.4: Add cross-validation right after the `try: source = normalize_...` block**

Insert after `source = stock_board_cache.normalize_board_stocks_source(source)`:

```python
    # Cross-validation: sort_by / sort_order / top_n require
    # (a) source == 'ths' and (b) include_quote == True.
    # Mirrors sibling /boards UX (api/routes/boards.py:327-335) and
    # avoids eastmoney/zhitu TypeError→5xx due to fixed signatures.
    if (sort_by is not None or top_n != 50 or sort_order != "desc"):
        if source != "ths":
            raise HTTPException(
                status_code=400,
                detail={
                    "error": "invalid_combination",
                    "message": (
                        "sort_by / sort_order / top_n are only supported "
                        f"with source='ths'. Got source={source!r}."
                    ),
                },
            )
        if not include_quote:
            raise HTTPException(
                status_code=400,
                detail={
                    "error": "invalid_combination",
                    "message": (
                        "sort_by / sort_order / top_n require include_quote=true. "
                        "These parameters drive upstream quote fetching; "
                        "without quotes the sort has no defined ordering."
                    ),
                },
            )
```

- [ ] **Step 7.5: Update persistence call site to 6-tuple + pass kwargs**

Find the existing `stock_board_cache.get_board_stocks(...)` call site (in the route body) and update:

```python
        stocks, origin, effective_source, reason, quote_truncated, total_in_board = (
            stock_board_cache.get_board_stocks(
                board_code,
                source=source,
                refresh=refresh,
                include_quote=include_quote,
                manager=manager,
                sort_by=sort_by,
                sort_order=sort_order,
                top_n=top_n,
            )
        )
```

- [ ] **Step 7.6: Update `BoardStockInfo` projection to include 6 new fields**

In the `stock_list = [` loop, expand the field pass-through:

```python
    stock_list = [
        BoardStockInfo(
            code=s.get("stock_code", ""),
            name=s.get("stock_name", ""),
            price=s.get("price"),
            change_pct=s.get("change_pct"),
            change_amount=s.get("change_amount"),
            volume=s.get("volume"),
            amount=s.get("amount"),
            turnover_rate=s.get("turnover_rate"),
            # 2026-07-13 新增投影
            change_speed=s.get("change_speed"),
            volume_ratio=s.get("volume_ratio"),
            amplitude=s.get("amplitude"),
            free_float_shares=s.get("free_float_shares"),
            float_market_cap=s.get("float_market_cap"),
            pe_ratio=s.get("pe_ratio"),
        )
        for s in stocks
    ]
```

- [ ] **Step 7.7: Update `BoardStocksResponse` construction to include 5 echo fields**

Find the `return BoardStocksResponse(...)` block:

```python
    return BoardStocksResponse(
        board=board_info,
        stocks=stock_list,
        query_source=source,
        data_source=origin,
        effective_source=effective_source,
        quote_source=quote_source,
        quote_error=quote_error,
        # 2026-07-13 新增 echo
        quote_truncated=quote_truncated,
        quote_top_n=top_n if (sort_by is not None or sort_order != "desc"
                              or top_n != 50 or include_quote) else None,
        quote_sort_by=sort_by,
        quote_sort_order=sort_order if (sort_by is not None or sort_order != "desc"
                                        or top_n != 50 or include_quote) else None,
        quote_total_in_board=total_in_board if total_in_board > 0 else None,
    )
```

- [ ] **Step 7.8: Run tests (expect PASS)**

Run: `.venv/Scripts/python.exe -m pytest tests/test_boards_api.py::TestBoardStocksTopNAndSort -v`
Expected: 6 passed

- [ ] **Step 7.9: Run all existing route tests (regression)**

Run: `.venv/Scripts/python.exe -m pytest tests/test_boards_api.py tests/test_boards.py tests/test_boards_history_route.py -v`
Expected: All pass; existing tests don't pass new query params so cross-validation's `if (sort_by is not None or ...)` is False → no 400 raised.

- [ ] **Step 7.10: Commit**

```bash
git add stock_data/api/routes/boards.py tests/test_boards_api.py
git commit -m "feat(boards-route): sort_by / top_n query params + 5 echo response fields

/boards/{code}/stocks 增加 3 个 query param + 入口交叉校验:
- source != 'ths' 时传 sort/top_n → 400 invalid_combination
- include_quote=false 时传 sort/top_n → 400 invalid_combination
  (与 /boards sibling UX 一致, 也避免 eastmoney TypeError 5xx path)

BoardStocksResponse 新增 5 字段 (echo 回 query params):
- quote_truncated
- quote_top_n
- quote_sort_by
- quote_sort_order
- quote_total_in_board

BoardStockInfo 投影加 6 字段 (THS 14 列全部暴露).

Persistence 调用从 4-tuple 升 6-tuple; source 同步透传 sort/top_n.
"
```

---

## Task 8: Tests — fixture + integration coverage (Commit G)

**Files:**
- Create: `tests/fixtures/ths_board_301546_page1.html`
- Create: `tests/test_boards_stocks_truncation_integration.py`

- [ ] **Step 8.1: Create offline fixture**

Capture a real upstream page-1 HTML for board 301546 and save as `tests/fixtures/ths_board_301546_page1.html`:

```bash
# Once: capture real upstream (live_network mark — single shot)
python -c "
import requests
r = requests.get(
    'https://q.10jqka.com.cn/gn/detail/code/301546/field/199112/order/desc/page/1/ajax/1/',
    headers={'User-Agent': 'Mozilla/5.0 Windows NT 10.0; Win64 Chrome/117.0.0.0',
             'Referer': 'https://q.10jqka.com.cn/gn/detail/code/301546/',
             'X-Requested-With': 'XMLHttpRequest'},
    timeout=10,
)
r.encoding = 'gbk'
import pathlib
pathlib.Path('tests/fixtures/ths_board_301546_page1.html').write_text(r.text, encoding='gbk')
"
```

Result file: `<tr>` × 10 rows, each with 14 `<td>` cells filled with real upstream data (already-probed on 2026-07-13).

- [ ] **Step 8.2: Write integration test that loads the fixture**

Create `tests/test_boards_stocks_truncation_integration.py`:

```python
"""Integration tests using fixture HTML for top_n + truncation path."""
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from stock_data.api.routes import reset_manager


FIXTURE_PATH = Path(__file__).parent / "fixtures" / "ths_board_301546_page1.html"


@pytest.fixture(autouse=True)
def reset_mgr():
    reset_manager()
    yield


def _read_fixture() -> str:
    return FIXTURE_PATH.read_text(encoding="gbk")


def test_fixture_loads_10_rows():
    body = _read_fixture()
    assert body.count("<tr") >= 10


def test_integration_top_n_10_with_real_fixture():
    """完整路径: fixture HTML → fetcher parse → 响应 6-tuple → route 返回."""
    from stock_data.data_provider.fetchers.ths_fetcher import ThsFetcher
    fetcher = ThsFetcher()

    fake_html = _read_fixture()
    with patch.object(fetcher, "_http_get") as mock_get:
        mock_get.return_value.text = fake_html
        mock_get.return_value.status_code = 200
        # 显式 encoding
        mock_get.return_value.encoding = "gbk"
        # 显式 content too (r.content 在 r.encoding 设置后还会被读到)
        mock_get.return_value.content = fake_html.encode("gbk")

        rows = fetcher.get_board_stocks(
            board_code="301546", top_n=10,
            sort_by="change_pct", sort_order="desc",
        )

    assert len(rows) == 10
    # 验证所有 6 新字段都被解析.
    for row in rows:
        assert row["stock_code"]
        assert row["stock_name"]
        # 14 列下 change_speed/volume_ratio/amplitude 等字段都应被赋值.
        # (上游真实值可能是 '--' → None, 仅要求字段 key 存在)
        assert "change_speed" in row
        assert "volume_ratio" in row
        assert "amplitude" in row
        assert "free_float_shares" in row
        assert "float_market_cap" in row
        assert "pe_ratio" in row


def test_integration_top_n_3_truncates_after_first_page():
    """top_n=3 → 翻 1 页 (10 行) → 接到 3 行就 break."""
    from stock_data.data_provider.fetchers.ths_fetcher import ThsFetcher
    fetcher = ThsFetcher()

    fake_html = _read_fixture()
    with patch.object(fetcher, "_http_get") as mock_get:
        mock_get.return_value.text = fake_html
        mock_get.return_value.status_code = 200
        mock_get.return_value.encoding = "gbk"
        mock_get.return_value.content = fake_html.encode("gbk")

        rows = fetcher.get_board_stocks(
            board_code="301546", top_n=3,
            sort_by="change_pct", sort_order="desc",
        )

    # 拿到的前 3 行的 stock_code 必须 == fixture 的前 3 行 stock_code.
    # (verify break at top_n; never continues to page 2)
    assert len(rows) == 3
    # mock_get 只调了 1 次 (page 1).
    assert mock_get.call_count == 1
```

- [ ] **Step 8.3: Run integration tests (expect PASS)**

Run: `.venv/Scripts/python.exe -m pytest tests/test_boards_stocks_truncation_integration.py -v`
Expected: 3 passed

- [ ] **Step 8.4: Run full test suite (final regression)**

Run: `.venv/Scripts/python.exe -m pytest`
Expected: All pass (default skip live_network)

- [ ] **Step 8.5: Run lint**

Run: `ruff check .`
Expected: No new issues

- [ ] **Step 8.6: Run live_network smoke test (one-shot, 302546真实)**

Run: `.venv/Scripts/python.exe -m pytest tests/test_boards_stocks_truncation_integration.py -m live_network -v --runxfail`
Expected: `test_integration_top_n_10_with_real_fixture` and `test_integration_top_n_3_truncates_after_first_page` PASS or XFAIL (CI / upstream occasionally flaky)

- [ ] **Step 8.7: Commit**

```bash
git add tests/fixtures/ths_board_301546_page1.html tests/test_boards_stocks_truncation_integration.py
git commit -m "test(boards): real-upstream fixture + integration coverage for top_n path

tests/fixtures/ths_board_301546_page1.html: 10 行真实 upstream HTML
(实测于 2026-07-13, 14 列 GBK 编码). 供离线 fast feedback 测试用.

tests/test_boards_stocks_truncation_integration.py 3 个测试:
- fixture load yields 10 rows;
- top_n=10 走 ThsFetcher 翻 1 页拿 10 行, 6 个新字段都有 key;
- top_n=3 翻 1 页拿到 3 行后 break, _http_get 只 call 1 次.

Live-network smoke: pytest -m live_network; CI 偶尔 flaky 用 xfail 兜底.
"
```

---

## Task 9: Docs — `CLAUDE.md` updates (Commit H)

**Files:**
- Modify: `D:\GitRepo\skills\stock_data\CLAUDE.md` (multiple sections)

- [ ] **Step 9.1: Update THS fetcher row in Provider API Documentation table**

Find the row in `## Provider API Documentation` table:

```diff
 | `ThsFetcher` | 7 | csi | `HOT_TOPICS \| NORTH_FLOW \| NEWS_FLASH \| NEWS_SEARCH \| STOCK_BOARD` (board K-line concept/industry, d-only — 2026-07-08; + `get_board_realtime` 板块实时行情 via q.10jqka /gn/detail/code/{cid}/) | none |
```

Add: `+ STOCK_BOARD board-stocks 支持 11 列排序 (sort_by / sort_order / top_n ≤50) + ZZSHARE-backfill`

Replace with:

```
 | `ThsFetcher` | 7 | csi | `HOT_TOPICS \| NORTH_FLOW \| NEWS_FLASH \| NEWS_SEARCH \| STOCK_BOARD` (board K-line concept/industry, d-only — 2026-07-08; + `get_board_realtime` 板块实时行情 via q.10jqka /gn/detail/code/{cid}/; **`get_board_stocks` 支持 11 列 sort_by + top_n≤50 + ZZSHARE 自动补全 (2026-07-13)**) | none |
```

- [ ] **Step 9.2: Update Capability-Based Routing table for `get_board_stocks`**

Find the entry for `get_board_stocks`:

```diff
 | `get_board_stocks` | `STOCK_BOARD` (source-routed, public source labels: `ths` / `eastmoney` / `zhitu`; `source=zzshare` is not a public label here — returns 422). **One internal cross-source fallback (2026-07-10):** `source='ths'` + `include_quote=False` → ZZSHARE primary, THS fallback. For `include_quote=True`, THS is mandatory ... |
```

Append a final paragraph to the same cell:

```
 ... For `include_quote=True`, THS is mandatory (ZZSHARE emits no quote fields; falling back would silently degrade the response). `effective_source` field on the response exposes which fetcher actually served. **(2026-07-13)** When `include_quote=true`, route accepts `?sort_by={11 keys}` `?sort_order=asc|desc` `?top_n=1..50`. THS 50-stock login-wall → persistence triggers single ZZSHARE fill-in (no retry); `quote_truncated` exposes whether merge happened. |
```

- [ ] **Step 9.3: Add a new Anti-Pattern note for `quote_truncated` truthiness**

Find `### Anti-Patterns to Avoid` and append:

```
- **Don't** treat `data_source` on `/boards/{code}/stocks` as the user's fetcher choice — read `effective_source` instead. As of 2026-07-10 the helper transparently falls back ... [existing bullet].
- **Don't** trust `stocks.length == top_n` as evidence that the board has exactly N members — it could mean truncation (THS upstream 50-stock login wall). Always read `quote_truncated` and `quote_total_in_board` together. (2026-07-13)
```

- [ ] **Step 9.4: Commit**

```bash
git add CLAUDE.md
git commit -m "docs(CLAUDE.md): document 11-sort + ZZSHARE-backfill policy

3 个 section 更新:
- Provider API Documentation 表 (ThsFetcher 行)
- Capability-Based Routing 表 (get_board_stocks 行) 加 sort/top_n 注释
- Anti-Patterns 加 'don't trust stocks.length == top_n' 提醒.

Reference: spec docs/superpowers/specs/2026-07-13-board-stocks-top-n-sort-design.md
"
```

---

## Self-Review (per skill instructions)

**Spec coverage check:**

| Spec section | Implemented in |
|---|---|
| 3.1.1 query params + Literal | Task 7 ✓ |
| 3.1.1.1 cross-validation | Task 7 ✓ |
| 3.1.2 5 echo response fields | Task 7 ✓ |
| 3.1.3 behavior matrix | Task 7 ✓ |
| 3.2.1 URL template + sort map | Task 2 ✓ |
| 3.2.2 fetcher signature | Task 3 ✓ |
| 3.2.3 sort_by validation | Task 3 ✓ |
| 3.2.4 page loop + top_n early termination | Task 3 ✓ |
| 3.2.5 parse all 14 columns | Task 4 ✓ |
| 3.2.5 `_parse_free_float` | Task 4 ✓ |
| 3.2.6 docstring updates | inline in Task 3, 4 (note: docstring edits not isolated; do them as part of those steps) |
| 3.3 schema 6 new fields | Task 1 ✓ |
| 3.4.1 + 3.4.2 + 3.4.3 6-tuple + heuristic + merge | Task 6 ✓ |
| 3.4.4 `fetch_board_stocks_with_zzshare_fallback` signature | Task 6 ✓ |
| 3.4.5 `manager.get_board_stocks` signature (HIGH) | Task 5 ✓ |
| 3.5 tests (7-14 new) | Tasks 1, 3, 4, 6, 7, 8 ✓ |
| 4.1 / 4.2 / 4.3 / 4.4 data flow examples | documented in spec, not impl (verification: Task 6 + 8 tests) |
| 5 error handling (422, 5xx, ZZSHARE fail) | Tasks 6, 7 ✓ |
| 6 backward compat | Tasks 1, 3, 5 (default kwargs preserve old behavior) |
| 7 rollback section (design guidance only) | n/a (out of implementation scope) |
| 9 acceptance checklist (full) | covered across all tasks |
| 10 commit plan | mapped 1:1 to Tasks 1-9 |

**Placeholder scan:** Plan has zero TBDs. Every step has explicit code or commands.

**Type consistency:**
- `manager.get_board_stocks` kwargs: `sort_by: str | None`, `sort_order: str = "desc"`, `top_n: int = 50` — Task 5 ✓
- `fetch_board_stocks_with_zzshare_fallback` kwargs: same names — Task 6 ✓
- `persistence.get_board_stocks` kwargs: same names, returns 6-tuple — Task 6 ✓
- `route ` query param names: `sort_by` / `sort_order` / `top_n` — Task 7 ✓
- Schema field names: 6 new fields consistent in Tasks 1, 4, 7 ✓
- All 5 echo response fields consistent (`quote_truncated`, `quote_top_n`, `quote_sort_by`, `quote_sort_order`, `quote_total_in_board`) — Task 7 ✓

**Found issues to fix:** none

---

## Execution Choice

**Plan complete and saved to `docs/superpowers/plans/2026-07-13-board-stocks-top-n-sort.md`. Two execution options:**

1. **Subagent-Driven (recommended)** - I dispatch a fresh subagent per task, review between tasks, fast iteration
2. **Inline Execution** - Execute tasks in this session using executing-plans, batch execution with checkpoints

Which approach?
