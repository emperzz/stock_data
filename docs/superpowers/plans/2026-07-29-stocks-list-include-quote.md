# `/api/v1/stocks` — Include Realtime Quote + Sort Support Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `include_quote`, `sort_by`, `sort_order` parameters to `GET /api/v1/stocks` with full-market realtime quote aggregation, single-call upstream, sort by quote fields. No new `DataCapability` flag.

**Architecture:** Add `BaseFetcher.get_realtime_quotes(market)` ABC method (default raises). Implement in `AkshareFetcher` (uses existing `ak.stock_zh_a_spot_em()`) and `ZzshareFetcher` (uses `rt_k(ts_code='60*.SH,68*.SH,0*.SZ,3*.SZ,9*.BJ', fields='all')`). Manager wraps failover via existing `_filter_by_capability(STOCK_REALTIME_QUOTE)` + `_with_failover` + `REALTIME_CIRCUIT_BREAKER`. Route relocates from `calendar.py` to `stocks.py`, drops `refresh` param (BREAKING), adds path B (quote cache, single key per market, TTL 60s) alongside existing path A (metadata cache, TTL 300s).

**Tech Stack:** FastAPI, Pydantic v2, `cachetools.TTLCache`, existing fetcher + manager infrastructure, akshare, zzshare SDK.

## Global Constraints

These constraints apply to every task:

- **No new `DataCapability` flag** — reuse `STOCK_REALTIME_QUOTE` capability; manager's per-fetcher `try/except DataFetchError` skips unsupported fetchers.
- **No realtime quote persistence** — quote data lives only in memory (`_stock_list_quote_cache`, TTL 60s). Compliance with CLAUDE.md:556.
- **No per-stock loop fallback** — if a fetcher doesn't natively expose all-market quote, it returns `DataFetchError` from `get_realtime_quotes`. Manager skips it. No synthetic loop.
- **Quote data MUST come from a single upstream call** — `ak.stock_zh_a_spot_em()` for akshare; `rt_k` wildcard for zzshare. Single-stock `get_realtime_quote(stock_code)` MUST NOT be refactored to call `get_realtime_quotes` + filter.
- **Schema reuse** — extend `StockInfo` with `quote: StockQuote | None` + `source: str`. Do NOT duplicate `StockQuote`'s 24 fields on `StockInfo`. Use `StockQuote.from_unified_quote()` as the single mapping helper.
- **`refresh` param removed** (BREAKING) — daily-first-call auto-refresh + `include_quote=true` covers the same use cases. Any client passing `?refresh=true` will get 422 from FastAPI.
- **HK/US + `include_quote=true` → 422** with `error: "include_quote_unsupported"`. No per-stock fallback for hk/us.
- **`sort_by` requires `include_quote=true`** — otherwise 400 with `error: "sort_requires_quote"`. Sortable fields are quote-only (no metadata sort).
- **limit upper bound: 10000** for both paths. Default 100.
- **TTLCache TTLs**: `_stock_list_cache` 300s (metadata), `_stock_list_quote_cache` 60s (quote). Both respect `ENABLE_API_CACHE` toggle.
- **`@map_errors` contract**: `DataFetchError → 503`, `HTTPException` passes through, other `Exception → 500`. New `HTTPException(400, ...)` and `HTTPException(422, ...)` for client errors.
- **Path B does NOT call `stock_list.get_stock_list()`** — derive market (hardcoded `"csi"` in path B) + exchange (`code_to_exchange(code)`) from quote data. Single fetcher call per request.
- **TDD discipline**: each task writes its failing tests first, watches them fail, then implements, then watches them pass, then commits.
- **Frequent commits** — one commit per task, conventional commit message (`feat:` / `refactor:` / `test:` / `docs:`).

---

## File Structure

| File | Action | Responsibility |
|---|---|---|
| `stock_data/api/schemas.py` | Modify | Extend `StockInfo` (line 304) with `quote: StockQuote \| None` + `source: str` |
| `stock_data/data_provider/base.py` | Modify | Add default-raise `BaseFetcher.get_realtime_quotes(market)` |
| `stock_data/data_provider/fetchers/akshare/fetcher.py` | Modify | Extract `_normalize_spot_row`; implement `get_realtime_quotes`; refactor `get_realtime_quote` to use helper |
| `stock_data/data_provider/fetchers/zzshare_fetcher.py` | Modify | Extract `_normalize_rt_k_row`; implement `get_realtime_quotes`; refactor `get_realtime_quote` to use helper |
| `stock_data/data_provider/manager.py` | Modify | Add `get_realtime_quotes(market)` failover wrapper |
| `stock_data/api/cache.py` | Modify | Add `_stock_list_cache` + `_stock_list_quote_cache` instances + getter functions + key builders |
| `stock_data/api/routes/calendar.py` | Modify | Remove `list_stocks` (moves to stocks.py); remove `stock_list` import |
| `stock_data/api/routes/stocks.py` | Modify | Add `list_stocks` (relocated) + helpers + `__all__` re-exports if needed; update module docstring |
| `tests/test_routes.py` | Modify | Extend `TestListStocks` (line 154-176) with 17 new cases |
| `tests/test_zzshare_fetcher.py` | Modify | Extend `TestRealtimeQuote` (line 799) with 6 new cases |
| `tests/test_providers.py` | Modify | Extend akshare block (line 150-233) with 2 new cases |
| `tests/test_manager_realtime_quotes.py` | Create | 4 failover + circuit-breaker cases |
| `tests/test_stock_list_cache_keys.py` | Create | 2 cache key cases |
| `CLAUDE.md` | Modify | Update Source Tracking section; annotate fetcher overview table |

---

## Task 1: Extend `StockInfo` schema with `quote` and `source` fields

**Files:**
- Modify: `stock_data/api/schemas.py:304-314` (extend `StockInfo` class)
- Modify: `tests/test_routes.py:154-176` (extend `TestListStocks` with backward-compat tests)

**Interfaces:**
- Consumes: existing `StockQuote` schema (line 49-131)
- Produces: `StockInfo` instances with optional `quote` and `source` fields

This is the foundation task. All later tasks depend on `StockInfo.quote` and `StockInfo.source` existing.

- [ ] **Step 1: Write failing tests for new `StockInfo` fields**

Append to `tests/test_routes.py::TestListStocks` (after line 176, before the next test class):

```python
def test_list_stocks_response_has_quote_field(self, client):
    """Backward compat: quote field always present, null when not requested."""
    response = client.get("/api/v1/stocks?market=csi&limit=3")
    assert response.status_code == 200
    data = response.json()
    assert len(data) > 0
    for stock in data:
        assert "quote" in stock
        assert stock["quote"] is None

def test_list_stocks_response_has_source_field(self, client):
    """Source field exposes fetcher name or 'persistence'."""
    response = client.get("/api/v1/stocks?market=csi&limit=3")
    assert response.status_code == 200
    data = response.json()
    assert len(data) > 0
    for stock in data:
        assert "source" in stock
        assert stock["source"] != ""
        assert stock["source"] in ("persistence", "akshare", "zzshare")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_routes.py::TestListStocks::test_list_stocks_response_has_quote_field tests/test_routes.py::TestListStocks::test_list_stocks_response_has_source_field -v`

Expected: FAIL with `AssertionError: 'quote' not in stock` and `AssertionError: 'source' not in stock`.

- [ ] **Step 3: Extend `StockInfo` schema**

In `stock_data/api/schemas.py:304-314`, replace the class body:

```python
class StockInfo(BaseModel):
    """Stock list entry. `quote` populated when request includes
    ?include_quote=true; null otherwise. `source` identifies the origin
    fetcher (or "persistence" for DB hits)."""

    code: str = Field(description="Stock code (e.g., 600519, AAPL, HK00700)")
    name: str = Field(description="Stock name")
    market: str = Field(description="Market type: csi/hk/us")
    exchange: str | None = Field(
        default=None,
        description="Exchange code (SH/SZ/BJ) when known; null otherwise.",
    )
    quote: StockQuote | None = Field(
        default=None,
        description=(
            "Realtime quote snapshot. Populated only when ?include_quote=true; "
            "null otherwise. quote.source identifies which fetcher served it."
        ),
    )
    source: str = Field(
        default="",
        description=(
            "Origin of this list entry's data. For include_quote=true: the "
            "fetcher that served the realtime quote (akshare/zzshare). "
            "For include_quote=false: the source of the metadata "
            "(akshare/zzshare/persistence)."
        ),
    )
```

`StockQuote` is defined earlier in the same file (line 49) and is in scope.

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_routes.py::TestListStocks -v`

Expected: PASS for all 5 tests (3 existing + 2 new).

- [ ] **Step 5: Verify response includes new fields in production code path**

Run: `.venv/Scripts/python.exe -m pytest tests/test_routes.py::TestListStocks tests/test_bugfix_pydantic_akshare_csi.py -v`

Expected: PASS for all tests. The bugfix test pins `?market=cn` → 422; verify it's still satisfied.

- [ ] **Step 6: Commit**

```bash
git add stock_data/api/schemas.py tests/test_routes.py
git commit -m "feat(schemas): StockInfo gains optional quote + source fields"
```

---

## Task 2: Add `stock_list_cache` and `stock_list_quote_cache` TTLCache instances

**Files:**
- Modify: `stock_data/api/cache.py` (add instances after line 29, getters after line 87, key builders after line 217)
- Create: `tests/test_stock_list_cache_keys.py` (cache key unit tests)

**Interfaces:**
- Consumes: existing `TTLCache`, `is_cache_enabled`, `cached_lookup`, `cached_store` infrastructure
- Produces:
  - `get_stock_list_cache() -> TTLCache` (maxsize=64, ttl=300)
  - `get_stock_list_quote_cache() -> TTLCache` (maxsize=8, ttl=60)
  - `make_stock_list_cache_key(market, offset, limit) -> str`
  - `make_stock_list_quote_cache_key(market) -> str`

- [ ] **Step 1: Write failing tests for cache key builders**

Create `tests/test_stock_list_cache_keys.py`:

```python
"""Cache key builder tests for /api/v1/stocks cache layer."""

from stock_data.api.cache import (
    make_stock_list_cache_key,
    make_stock_list_quote_cache_key,
)


class TestStockListCacheKeys:
    def test_stock_list_cache_key_format(self):
        key = make_stock_list_cache_key("csi", 0, 100)
        assert key == "stock_list:csi:0:100"

    def test_stock_list_cache_key_different_pages(self):
        a = make_stock_list_cache_key("csi", 0, 100)
        b = make_stock_list_cache_key("csi", 100, 100)
        c = make_stock_list_cache_key("csi", 0, 200)
        assert a != b
        assert a != c
        assert b != c

    def test_stock_list_quote_cache_key_format(self):
        assert make_stock_list_quote_cache_key("csi") == "stock_list_quote:csi"

    def test_stock_list_quote_cache_key_per_market(self):
        assert (
            make_stock_list_quote_cache_key("csi")
            != make_stock_list_quote_cache_key("hk")
        )
        assert (
            make_stock_list_quote_cache_key("hk")
            != make_stock_list_quote_cache_key("us")
        )
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_stock_list_cache_keys.py -v`

Expected: ImportError or AttributeError on `make_stock_list_cache_key`.

- [ ] **Step 3: Add TTLCache instances + getters**

In `stock_data/api/cache.py`, after the existing `_stock_intraday_cache` instance (line 29), add:

```python
# /api/v1/stocks caches (Task 2 — see docs/superpowers/plans/2026-07-29-stocks-list-include-quote.md)
_stock_list_cache: TTLCache = TTLCache(maxsize=64, ttl=300)        # metadata only
_stock_list_quote_cache: TTLCache = TTLCache(maxsize=8, ttl=60)    # full-market quote
```

The TTL constants are already loaded at the top of the file (e.g. `_TTL_HISTORY_DAILY = 300`). The two new instances use fixed values matching the design's TTL rationale; if future tuning is needed, add env vars mirroring the existing pattern.

After `get_stock_intraday_cache()` (line 83), add:

```python
def get_stock_list_cache() -> TTLCache:
    """Return the cache for /api/v1/stocks metadata-only responses.

    TTL 300s (5 min). Metadata changes slowly; this just dedupes dashboard
    refreshes. Path A only (no quote, no sort).
    """
    return _stock_list_cache


def get_stock_list_quote_cache() -> TTLCache:
    """Return the cache for /api/v1/stocks full-market quote responses.

    TTL 60s (1 min). One entry per market (csi). Multiple sort_by/limit
    requests within the window share the cached upstream fetch and
    re-sort/slice in-memory. Path B only (include_quote=true or sort_by).
    """
    return _stock_list_quote_cache
```

After `make_index_quote_cache_key()` (line 215-216), add:

```python
def make_stock_list_cache_key(market: str, offset: int, limit: int) -> str:
    """Cache key for /api/v1/stocks metadata-only responses."""
    return f"stock_list:{market}:{offset}:{limit}"


def make_stock_list_quote_cache_key(market: str) -> str:
    """Cache key for /api/v1/stocks full-market quote responses (path B).

    Single key per market — the cached value is the unsorted, unsliced
    full-market upstream response. offset/limit/sort are applied in-memory
    on cache hit.
    """
    return f"stock_list_quote:{market}"
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_stock_list_cache_keys.py -v`

Expected: PASS for all 4 tests.

- [ ] **Step 5: Run full cache test suite to ensure no regression**

Run: `.venv/Scripts/python.exe -m pytest tests/test_api_cache.py tests/test_cache_keys.py -v 2>&1 | tail -30`

If `test_api_cache.py` or `test_cache_keys.py` does not exist, skip this step (run only the new test file).

Expected: existing cache tests still pass.

- [ ] **Step 6: Commit**

```bash
git add stock_data/api/cache.py tests/test_stock_list_cache_keys.py
git commit -m "feat(cache): add stock_list + stock_list_quote TTLCache instances"
```

---

## Task 3: Add `BaseFetcher.get_realtime_quotes` ABC default-raise method

**Files:**
- Modify: `stock_data/data_provider/base.py` (add method to `BaseFetcher` class around line 266)
- Create: `tests/test_base_fetcher_realtime_quotes.py` (default-raise test)

**Interfaces:**
- Consumes: existing `DataFetchError`, `UnifiedRealtimeQuote` types
- Produces:
  - `BaseFetcher.get_realtime_quotes(market: str) -> list[UnifiedRealtimeQuote] | None`
  - Default raises `DataFetchError`; override in AkshareFetcher + ZzshareFetcher (Tasks 4-7)

- [ ] **Step 1: Write failing test for ABC default-raise**

Create `tests/test_base_fetcher_realtime_quotes.py`:

```python
"""Verify the default ABC behavior for get_realtime_quotes."""

import pytest

from stock_data.data_provider.base import BaseFetcher, DataFetchError


class _MinimalFetcher(BaseFetcher):
    """Subclass that does not override get_realtime_quotes."""
    name = "MinimalFetcher"
    priority = 99


class TestBaseFetcherGetRealtimeQuotesDefault:
    def test_default_raises_data_fetch_error(self):
        fetcher = _MinimalFetcher()
        with pytest.raises(DataFetchError, match="does not support all-market realtime quote"):
            fetcher.get_realtime_quotes("csi")

    def test_default_market_tag_independent(self):
        """The default raise fires regardless of market arg."""
        fetcher = _MinimalFetcher()
        for m in ("csi", "hk", "us", "cn", "unknown"):
            with pytest.raises(DataFetchError):
                fetcher.get_realtime_quotes(m)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_base_fetcher_realtime_quotes.py -v`

Expected: `AttributeError: '_MinimalFetcher' object has no attribute 'get_realtime_quotes'`.

- [ ] **Step 3: Add default-raise method to `BaseFetcher`**

In `stock_data/data_provider/base.py`, locate the `BaseFetcher` class definition (around line 266). Add the method after the existing `get_realtime_quote` definition. To find the right spot, search for the `get_realtime_quote` method first:

```bash
grep -n "def get_realtime_quote\b" stock_data/data_provider/base.py
```

Insert the new method immediately after `get_realtime_quote`:

```python
    def get_realtime_quotes(self, market: str) -> list[UnifiedRealtimeQuote] | None:
        """Single-call all-market realtime snapshot.

        Fetchers whose upstream exposes the full market in one call
        (akshare's ``stock_zh_a_spot_em``, zzshare's ``rt_k`` wildcard)
        override this. The default raises ``DataFetchError``; the manager
        routes via existing ``STOCK_REALTIME_QUOTE`` capability + failover
        and treats per-fetcher ``DataFetchError`` as "unsupported, skip".

        Args:
            market: Public market tag (``"csi"`` for A-shares).

        Returns:
            ``list[UnifiedRealtimeQuote]`` on success; ``None`` when upstream
            returns empty or unavailable.

        Raises:
            DataFetchError: when the fetcher does not support all-market
                realtime quote (default behavior).
        """
        raise DataFetchError(
            f"{type(self).__name__} does not support all-market realtime quote"
        )
```

`UnifiedRealtimeQuote` is already imported at the top of `base.py`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_base_fetcher_realtime_quotes.py -v`

Expected: PASS for both tests.

- [ ] **Step 5: Commit**

```bash
git add stock_data/data_provider/base.py tests/test_base_fetcher_realtime_quotes.py
git commit -m "feat(base): add default-raise BaseFetcher.get_realtime_quotes"
```

---

## Task 4: Extract `_normalize_spot_row` helper in `AkshareFetcher`

**Files:**
- Modify: `stock_data/data_provider/fetchers/akshare/fetcher.py:256-318` (extract helper + refactor `get_realtime_quote`)
- Modify: `tests/test_providers.py:150-233` (add helper-output test, refactor existing test to assert helper reuse)

**Interfaces:**
- Consumes: existing `get_realtime_quote` row-mapping inline
- Produces:
  - `AkshareFetcher._normalize_spot_row(row, code: str) -> UnifiedRealtimeQuote`
  - `get_realtime_quote(stock_code)` continues to return the same `UnifiedRealtimeQuote | None` it did before

- [ ] **Step 1: Write failing test for `_normalize_spot_row`**

Append to `tests/test_providers.py` after the existing akshare realtime tests (around line 233):

```python
class TestAkshareSpotRowNormalize:
    """Unit tests for AkshareFetcher._normalize_spot_row."""

    def _fetcher(self):
        # Lazy import to avoid loading akshare at test collection time
        from stock_data.data_provider.fetchers.akshare.fetcher import AkshareFetcher
        return AkshareFetcher()

    def test_normalize_spot_row_basic_fields(self):
        fetcher = self._fetcher()
        row = {
            "代码": "600519",
            "名称": "贵州茅台",
            "最新价": 1680.5,
            "涨跌幅": 1.23,
            "涨跌额": 20.5,
            "成交量": 12345,        # 手
            "成交额": 2.07e8,
            "今开": 1680.0,
            "最高": 1685.0,
            "最低": 1678.0,
            "昨收": 1660.0,
            "振幅": 0.4,
            "换手率": 0.5,
            "量比": 1.2,
            "市盈率": 28.5,
            "市净率": 9.1,
        }
        from stock_data.data_provider.core.types import RealtimeSource
        quote = fetcher._normalize_spot_row(row, "600519")
        assert quote.code == "600519"
        assert quote.name == "贵州茅台"
        assert quote.source == RealtimeSource.AKSHARE
        assert quote.price == 1680.5
        assert quote.change_pct == 1.23
        assert quote.change_amount == 20.5
        assert quote.volume == 12345 * 100     # 手 → 股 (spec §3.4)
        assert quote.amount == 2.07e8
        assert quote.open_price == 1680.0
        assert quote.high == 1685.0
        assert quote.low == 1678.0
        assert quote.pre_close == 1660.0
        assert quote.amplitude == 0.4
        assert quote.turnover_rate == 0.5
        assert quote.volume_ratio == 1.2
        assert quote.pe_ratio == 28.5
        assert quote.pb_ratio == 9.1

    def test_normalize_spot_row_missing_fields_returns_none(self):
        """Missing optional fields → None, not crash."""
        fetcher = self._fetcher()
        row = {"代码": "000001", "名称": "平安银行"}  # minimal row
        quote = fetcher._normalize_spot_row(row, "000001")
        assert quote.code == "000001"
        assert quote.name == "平安银行"
        assert quote.price is None
        assert quote.change_pct is None
        assert quote.volume is None  # safe_int(0) * 100 = 0, not None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_providers.py::TestAkshareSpotRowNormalize -v`

Expected: ImportError on `_normalize_spot_row` or AttributeError.

- [ ] **Step 3: Extract `_normalize_spot_row` helper and refactor `get_realtime_quote`**

In `stock_data/data_provider/fetchers/akshare/fetcher.py`, replace the existing `get_realtime_quote` method (line 256-318) with:

```python
    def _normalize_spot_row(self, row, code: str) -> UnifiedRealtimeQuote:
        """Convert one ``ak.stock_zh_a_spot_em()`` row → UnifiedRealtimeQuote.

        Shared by ``get_realtime_quote`` (single-stock filter) and
        ``get_realtime_quotes`` (all-market iteration).
        """
        return UnifiedRealtimeQuote(
            code=normalize_stock_code(code),
            name=str(row.get("名称", "")),
            source=RealtimeSource.AKSHARE,
            price=safe_float(row.get("最新价")),
            change_pct=safe_float(row.get("涨跌幅")),
            change_amount=safe_float(row.get("涨跌额")),
            volume=safe_int(row.get("成交量"), 0) * 100,  # 手→股 per spec §3.4
            amount=safe_float(row.get("成交额")),
            open_price=safe_float(row.get("今开")),
            high=safe_float(row.get("最高")),
            low=safe_float(row.get("最低")),
            pre_close=safe_float(row.get("昨收")),
            amplitude=safe_float(row.get("振幅")),
            turnover_rate=safe_float(row.get("换手率")),
            volume_ratio=safe_float(row.get("量比")),
            pe_ratio=safe_float(row.get("市盈率")),
            pb_ratio=safe_float(row.get("市净率")),
        )

    def get_realtime_quote(self, stock_code: str) -> UnifiedRealtimeQuote | None:
        """Get realtime quote from Akshare.

        Single-stock path. For all-market use ``get_realtime_quotes``.
        """
        try:
            import akshare as ak

            code = self._convert_code(stock_code)
            is_hk = is_hk_market(stock_code)
            is_index = is_index_code(stock_code)

            if is_hk:
                df = ak.stock_hk_spot_em()
                symbol = code.replace(".hk", "").zfill(5)
                row = df[df["代码"] == symbol]
                if row.empty:
                    return None
                row = row.iloc[0]
            elif is_index:
                # CSI/HK indices - use index_zh_a_spot_em for CSI, skip HK
                index_type = get_index_type(stock_code)
                if index_type == "csi":
                    df = ak.stock_zh_index_spot_em(symbol=code)
                    row = df[df["代码"] == code]
                    if row.empty:
                        return None
                    row = row.iloc[0]
                else:
                    logger.warning(
                        f"[AkshareFetcher] HK index {stock_code} realtime quote not supported"
                    )
                    return None
            else:
                df = ak.stock_zh_a_spot_em()
                row = df[df["代码"] == code]
                if row.empty:
                    return None
                row = row.iloc[0]

            return self._normalize_spot_row(row, stock_code)

        except Exception:
            logger.warning(
                f"[AkshareFetcher] Realtime quote failed for {stock_code}", exc_info=True
            )
            return None
```

**CRITICAL — only the A-share branch is refactored**. The HK and index branches keep their existing inline row→dict mapping because their upstream tables have different column names (`名称` vs `名称` but with different layout). The A-share branch now uses `_normalize_spot_row` so both single-stock and all-market share the same mapping.

If the existing implementation also used `_normalize_spot_row` for HK/index, that's a future cleanup; out of scope here.

- [ ] **Step 4: Run new + existing tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_providers.py::TestAkshareSpotRowNormalize tests/test_providers.py::TestAkshareRealtime -v`

Expected: PASS for both new test classes and all existing akshare tests.

- [ ] **Step 5: Commit**

```bash
git add stock_data/data_provider/fetchers/akshare/fetcher.py tests/test_providers.py
git commit -m "refactor(akshare): extract _normalize_spot_row for single+all-market reuse"
```

---

## Task 5: Implement `AkshareFetcher.get_realtime_quotes` (all-market)

**Files:**
- Modify: `stock_data/data_provider/fetchers/akshare/fetcher.py` (add method after `_normalize_spot_row`)
- Modify: `tests/test_providers.py` (add tests for `get_realtime_quotes`)

**Interfaces:**
- Consumes: `_normalize_spot_row` (from Task 4)
- Produces: `AkshareFetcher.get_realtime_quotes(market: str = "csi") -> list[UnifiedRealtimeQuote] | None`

- [ ] **Step 1: Write failing tests**

Append to `tests/test_providers.py::TestAkshareSpotRowNormalize` (or a new test class — keep it close to existing akshare tests):

```python
class TestAkshareGetRealtimeQuotes:
    """Tests for AkshareFetcher.get_realtime_quotes (all-market)."""

    def _fetcher(self):
        from stock_data.data_provider.fetchers.akshare.fetcher import AkshareFetcher
        return AkshareFetcher()

    def test_get_realtime_quotes_csi(self, monkeypatch):
        """Single ak.stock_zh_a_spot_em() call → list of UnifiedRealtimeQuote."""
        import pandas as pd

        fake_df = pd.DataFrame([
            {"代码": "600519", "名称": "贵州茅台", "最新价": 1680.5, "涨跌幅": 1.23,
             "涨跌额": 20.5, "成交量": 12345, "成交额": 2.07e8, "今开": 1680.0,
             "最高": 1685.0, "最低": 1678.0, "昨收": 1660.0, "振幅": 0.4,
             "换手率": 0.5, "量比": 1.2, "市盈率": 28.5, "市净率": 9.1},
            {"代码": "000001", "名称": "平安银行", "最新价": 12.5, "涨跌幅": -0.5,
             "涨跌额": -0.06, "成交量": 80000, "成交额": 1.0e8, "今开": 12.6,
             "最高": 12.7, "最低": 12.4, "昨收": 12.56, "振幅": 2.4,
             "换手率": 0.3, "量比": 0.8, "市盈率": 5.2, "市净率": 0.6},
        ])

        def fake_spot_em():
            return fake_df
        import stock_data.data_provider.fetchers.akshare.fetcher as akshare_mod
        monkeypatch.setattr(akshare_mod, "ak", type("ak", (), {"stock_zh_a_spot_em": staticmethod(fake_spot_em)}))

        fetcher = self._fetcher()
        quotes = fetcher.get_realtime_quotes("csi")
        assert quotes is not None
        assert len(quotes) == 2
        codes = {q.code for q in quotes}
        assert codes == {"600519", "000001"}
        maotai = next(q for q in quotes if q.code == "600519")
        assert maotai.name == "贵州茅台"
        assert maotai.price == 1680.5

    def test_get_realtime_quotes_returns_none_on_failure(self, monkeypatch):
        """Upstream exception → None (not raise)."""
        def fake_spot_em():
            raise ConnectionError("akshare network down")
        import stock_data.data_provider.fetchers.akshare.fetcher as akshare_mod
        monkeypatch.setattr(akshare_mod, "ak", type("ak", (), {"stock_zh_a_spot_em": staticmethod(fake_spot_em)}))

        fetcher = self._fetcher()
        assert fetcher.get_realtime_quotes("csi") is None

    def test_get_realtime_quotes_returns_none_on_empty_df(self, monkeypatch):
        """Empty upstream response → None."""
        import pandas as pd
        import stock_data.data_provider.fetchers.akshare.fetcher as akshare_mod
        monkeypatch.setattr(akshare_mod, "ak", type("ak", (), {"stock_zh_a_spot_em": staticmethod(lambda: pd.DataFrame())}))

        fetcher = self._fetcher()
        assert fetcher.get_realtime_quotes("csi") is None

    def test_get_realtime_quotes_unsupported_market_returns_none(self):
        """market other than csi/cn → None (no all-market source)."""
        fetcher = self._fetcher()
        assert fetcher.get_realtime_quotes("hk") is None
        assert fetcher.get_realtime_quotes("us") is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_providers.py::TestAkshareGetRealtimeQuotes -v`

Expected: AttributeError on `get_realtime_quotes`.

- [ ] **Step 3: Implement `AkshareFetcher.get_realtime_quotes`**

Add immediately after `_normalize_spot_row` in `stock_data/data_provider/fetchers/akshare/fetcher.py`:

```python
    def get_realtime_quotes(self, market: str = "csi") -> list[UnifiedRealtimeQuote] | None:
        """A-share all-market realtime quote via ``ak.stock_zh_a_spot_em()``.

        Single upstream call. Returns ``None`` on upstream failure or
        empty response; otherwise a list with one ``UnifiedRealtimeQuote``
        per A-share stock in the upstream universe.

        Note: ``market="cn"`` (legacy fetcher-internal alias) accepted
        alongside ``"csi"`` for symmetry with ``get_all_stocks``.
        """
        if market not in ("csi", "cn"):
            return None
        try:
            import akshare as ak

            df = ak.stock_zh_a_spot_em()
        except Exception as e:
            logger.warning(f"[AkshareFetcher] stock_zh_a_spot_em failed: {e}")
            return None
        if df is None or df.empty:
            return None
        out: list = []
        for _, row in df.iterrows():
            code = str(row.get("代码", "")).strip()
            if not code:
                continue
            out.append(self._normalize_spot_row(row, code))
        return out
```

The imports `akshare as ak` is local to the method (matches existing `get_realtime_quote` style). `logger` and `safe_float`/`safe_int` are already module-level.

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_providers.py::TestAkshareGetRealtimeQuotes tests/test_providers.py::TestAkshareSpotRowNormalize -v`

Expected: PASS for all tests.

- [ ] **Step 5: Commit**

```bash
git add stock_data/data_provider/fetchers/akshare/fetcher.py tests/test_providers.py
git commit -m "feat(akshare): implement get_realtime_quotes (all-market via stock_zh_a_spot_em)"
```

---

## Task 6: Extract `_normalize_rt_k_row` helper in `ZzshareFetcher`

**Files:**
- Modify: `stock_data/data_provider/fetchers/zzshare_fetcher.py:368-407` (extract helper + refactor `get_realtime_quote`)
- Modify: `tests/test_zzshare_fetcher.py:799-892` (add helper-output test)

**Interfaces:**
- Consumes: existing `get_realtime_quote` row-mapping inline
- Produces:
  - `ZzshareFetcher._normalize_rt_k_row(row, code: str) -> UnifiedRealtimeQuote`
  - `get_realtime_quote(stock_code)` continues to return same `UnifiedRealtimeQuote | None` it did before

- [ ] **Step 1: Write failing test for `_normalize_rt_k_row`**

Append to `tests/test_zzshare_fetcher.py` after the existing `TestRealtimeQuote` class (around line 884):

```python
class TestNormalizeRtKRow:
    def test_normalize_rt_k_row_basic_fields(self):
        from stock_data.data_provider.fetchers.zzshare_fetcher import ZzshareFetcher
        fetcher = ZzshareFetcher()
        row = {
            "ts_code": "600519.SH",
            "name": "贵州茅台",
            "pre_close": 1700.0,
            "open": 1710.0,
            "high": 1725.0,
            "low": 1695.0,
            "close": 1720.0,
            "vol": 1e6,
            "amount": 1e9,
            "quote_rate": 1.18,
            "turnover_rate": 0.5,
            "market_value": 2.16e12,
            "circulation_value": 2.16e12,
            "ttm_pe_rate": 25.5,
        }
        from stock_data.data_provider.core.types import RealtimeSource
        quote = fetcher._normalize_rt_k_row(row, "600519")
        assert quote.code == "600519"
        assert quote.name == "贵州茅台"
        assert quote.source == RealtimeSource.ZZSHARE
        assert quote.price == 1720.0
        assert quote.change_pct == 1.18
        assert quote.change_amount == 1720.0 - 1700.0  # close - pre_close
        assert quote.pre_close == 1700.0
        assert quote.open_price == 1710.0
        assert quote.high == 1725.0
        assert quote.low == 1695.0
        assert quote.volume == 1_000_000
        assert quote.amount == 1e9
        assert quote.turnover_rate == 0.5
        assert quote.total_mv == 2.16e12
        assert quote.circ_mv == 2.16e12
        assert quote.pe_ratio == 25.5

    def test_normalize_rt_k_row_missing_change_amount_when_pre_close_none(self):
        from stock_data.data_provider.fetchers.zzshare_fetcher import ZzshareFetcher
        fetcher = ZzshareFetcher()
        row = {"ts_code": "000001.SZ", "name": "平安银行", "close": 12.5, "pre_close": None}
        quote = fetcher._normalize_rt_k_row(row, "000001")
        assert quote.change_amount is None  # not computable
        assert quote.price == 12.5
        assert quote.pre_close is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_zzshare_fetcher.py::TestNormalizeRtKRow -v`

Expected: AttributeError on `_normalize_rt_k_row`.

- [ ] **Step 3: Extract `_normalize_rt_k_row` and refactor `get_realtime_quote`**

In `stock_data/data_provider/fetchers/zzshare_fetcher.py`, replace the existing `get_realtime_quote` method (line 368-407) with:

```python
    def _normalize_rt_k_row(self, row, code: str) -> UnifiedRealtimeQuote:
        """Convert one ``api.rt_k()`` row → UnifiedRealtimeQuote.

        Shared by ``get_realtime_quote`` (single code) and
        ``get_realtime_quotes`` (wildcard all-market). Preserves the
        pre-existing field mapping verbatim — this is a pure refactor.
        """
        pre_close = safe_float(row.get("pre_close"))
        close = safe_float(row.get("close"))
        return UnifiedRealtimeQuote(
            code=normalize_stock_code(code),
            name=str(row.get("name", "")),
            source=RealtimeSource.ZZSHARE,
            price=close,
            change_pct=safe_float(row.get("quote_rate")),
            change_amount=(close - pre_close)
            if (close is not None and pre_close is not None)
            else None,
            volume=safe_int(row.get("vol")),
            amount=safe_float(row.get("amount")),
            open_price=safe_float(row.get("open")),
            high=safe_float(row.get("high")),
            low=safe_float(row.get("low")),
            pre_close=pre_close,
            turnover_rate=safe_float(row.get("turnover_rate")),
            total_mv=safe_float(row.get("market_value")),
            circ_mv=safe_float(row.get("circulation_value")),
            pe_ratio=safe_float(row.get("ttm_pe_rate")),
        )

    def get_realtime_quote(self, stock_code: str) -> UnifiedRealtimeQuote | None:
        """Fetch realtime snapshot from zzshare ``rt_k(fields='all')``.

        Single-stock path. Upstream call shape is unchanged from the
        pre-refactor version — only the row-mapping is delegated to
        ``_normalize_rt_k_row``. For all-market use ``get_realtime_quotes``.
        """
        self._ensure_api()
        api = self.__class__._api
        if api is None:
            return None
        ts_code = _to_zzshare_ts_code(normalize_stock_code(stock_code))
        try:
            df = api.rt_k(ts_code=ts_code, fields="all")
        except Exception as e:
            logger.warning(f"[ZzshareFetcher] rt_k({ts_code}) failed: {e}")
            return None
        if df is None or df.empty:
            return None
        return self._normalize_rt_k_row(df.iloc[0], stock_code)
```

The upstream call (`rt_k(ts_code='600519.SH', fields='all')`) is byte-identical to the pre-refactor version. Only the row→UnifiedRealtimeQuote mapping moved to the helper.

- [ ] **Step 4: Run new + existing tests**

Run: `.venv/Scripts/python.exe -m pytest tests/test_zzshare_fetcher.py::TestRealtimeQuote tests/test_zzshare_fetcher.py::TestNormalizeRtKRow -v`

Expected: PASS for all tests (existing TestRealtimeQuote proves no regression; new TestNormalizeRtKRow proves helper works).

- [ ] **Step 5: Commit**

```bash
git add stock_data/data_provider/fetchers/zzshare_fetcher.py tests/test_zzshare_fetcher.py
git commit -m "refactor(zzshare): extract _normalize_rt_k_row for single+all-market reuse"
```

---

## Task 7: Implement `ZzshareFetcher.get_realtime_quotes` (all-market)

**Files:**
- Modify: `stock_data/data_provider/fetchers/zzshare_fetcher.py` (add method after `_normalize_rt_k_row`; add module-level constant near top)
- Modify: `tests/test_zzshare_fetcher.py` (add tests for `get_realtime_quotes`)

**Interfaces:**
- Consumes: `_normalize_rt_k_row` (from Task 6)
- Produces: `ZzshareFetcher.get_realtime_quotes(market: str = "csi") -> list[UnifiedRealtimeQuote] | None`

- [ ] **Step 1: Write failing tests**

Append to `tests/test_zzshare_fetcher.py` after `TestNormalizeRtKRow`:

```python
class TestRealtimeQuotes:
    """Tests for ZzshareFetcher.get_realtime_quotes (all-market)."""

    def _fetcher_with_api(self, fake_rt_k):
        fetcher = ZzshareFetcher()
        fake_api = MagicMock()
        fake_api.rt_k = MagicMock(return_value=fake_rt_k)
        ZzshareFetcher._api = fake_api
        ZzshareFetcher._init_attempted = True
        return fetcher

    def test_realtime_quotes_uses_wildcard(self):
        """Pin the rt_k(ts_code=wildcard, fields='all') call shape."""
        raw = pd.DataFrame([
            {"ts_code": "600519.SH", "name": "贵州茅台", "close": 1720.0,
             "pre_close": 1700.0, "open": 1710.0, "high": 1725.0,
             "low": 1695.0, "vol": 1e6, "amount": 1e9, "quote_rate": 1.18,
             "turnover_rate": 0.5, "market_value": 2.16e12,
             "circulation_value": 2.16e12, "ttm_pe_rate": 25.5},
        ])
        fetcher = self._fetcher_with_api(raw)
        fetcher.get_realtime_quotes("csi")
        call = ZzshareFetcher._api.rt_k.call_args
        assert "60*.SH" in call.kwargs["ts_code"]
        assert "68*.SH" in call.kwargs["ts_code"]
        assert "0*.SZ" in call.kwargs["ts_code"]
        assert "3*.SZ" in call.kwargs["ts_code"]
        assert "9*.BJ" in call.kwargs["ts_code"]
        assert call.kwargs.get("fields") == "all"

    def test_realtime_quote_uses_single_code_not_wildcard(self):
        """REGRESSION GUARD: single-stock path MUST NOT use the wildcard.

        If a future refactor makes get_realtime_quote call
        get_realtime_quotes + filter, this test fails — preventing the
        ~5400-row over-fetch regression.
        """
        raw = pd.DataFrame([{"ts_code": "600519.SH", "name": "贵州茅台", "close": 1720.0}])
        fetcher = self._fetcher_with_api(raw)
        fetcher.get_realtime_quote("600519")
        call = ZzshareFetcher._api.rt_k.call_args
        assert call.kwargs["ts_code"] == "600519.SH"
        assert "60*.SH" not in call.kwargs["ts_code"]

    def test_realtime_quotes_returns_all_rows(self):
        raw = pd.DataFrame([
            {"ts_code": "600519.SH", "name": "贵州茅台", "close": 1720.0,
             "pre_close": 1700.0},
            {"ts_code": "000001.SZ", "name": "平安银行", "close": 12.5,
             "pre_close": 12.56},
            {"ts_code": "300750.SZ", "name": "宁德时代", "close": 200.0,
             "pre_close": 198.0},
        ])
        fetcher = self._fetcher_with_api(raw)
        quotes = fetcher.get_realtime_quotes("csi")
        assert quotes is not None
        assert len(quotes) == 3
        codes = {q.code for q in quotes}
        assert codes == {"600519", "000001", "300750"}

    def test_realtime_quotes_empty_df_returns_empty_list(self):
        fetcher = self._fetcher_with_api(pd.DataFrame())
        assert fetcher.get_realtime_quotes("csi") == []

    def test_realtime_quotes_sdk_unavailable_returns_none(self, monkeypatch):
        monkeypatch.delenv("ZZSHARE_TOKEN", raising=False)
        with patch("importlib.util.find_spec", return_value=None):
            fetcher = ZzshareFetcher()
            assert fetcher.get_realtime_quotes("csi") is None

    def test_realtime_quotes_unsupported_market_returns_none(self):
        """market other than csi/cn → None."""
        fetcher = ZzshareFetcher()
        ZzshareFetcher._api = MagicMock()
        ZzshareFetcher._init_attempted = True
        assert fetcher.get_realtime_quotes("hk") is None
        assert fetcher.get_realtime_quotes("us") is None
        # rt_k should not be called for unsupported markets
        ZzshareFetcher._api.rt_k.assert_not_called()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_zzshare_fetcher.py::TestRealtimeQuotes -v`

Expected: AttributeError on `get_realtime_quotes`.

- [ ] **Step 3: Add module-level constant + implement `get_realtime_quotes`**

In `stock_data/data_provider/fetchers/zzshare_fetcher.py`, near the top of the file (after imports and existing module-level constants like `_to_zzshare_ts_code`), add:

```python
# Wildcard pattern covering all A-share markets: SH main + STAR + SZ main + ChiNext + BJ.
# Used by get_realtime_quotes() for all-market single-call upstream.
# Per docs/zzshare/02-realtime.md, single-call "all market" via comma-separated wildcards
# is documented but rate-limited (20 calls/min); the route layer caches the response 60s.
_RT_K_ALL_MARKET_TS_CODE = "60*.SH,68*.SH,0*.SZ,3*.SZ,9*.BJ"
```

Then immediately after `_normalize_rt_k_row` in the `ZzshareFetcher` class, add:

```python
    def get_realtime_quotes(self, market: str = "csi") -> list[UnifiedRealtimeQuote] | None:
        """A-share all-market realtime quote via ``rt_k`` wildcard + ``fields='all'``.

        Single upstream call returning ~5400 rows. Returns ``[]`` on empty
        upstream, ``None`` on upstream failure / SDK unavailable.

        ``market="cn"`` (legacy fetcher-internal alias) accepted alongside
        ``"csi"`` for symmetry with ``get_all_stocks``.
        """
        self._ensure_api()
        api = self.__class__._api
        if api is None or market not in ("csi", "cn"):
            return None
        try:
            df = api.rt_k(ts_code=_RT_K_ALL_MARKET_TS_CODE, fields="all")
        except Exception as e:
            logger.warning(f"[ZzshareFetcher] rt_k all-market failed: {e}")
            return None
        if df is None:
            return None
        if df.empty:
            return []
        out: list = []
        for _, row in df.iterrows():
            ts_code = str(row.get("ts_code", ""))
            if not ts_code:
                continue
            # ts_code like "600519.SH" -> bare "600519"
            code = ts_code.split(".")[0]
            out.append(self._normalize_rt_k_row(row, code))
        return out
```

The check `if df is None` (vs `if df is None or df.empty`) — `_is_meaningful` in manager distinguishes `None` from `[]`. Returning `[]` for empty df lets the manager continue failover; returning `None` for `df is None` (defensive — `rt_k` shouldn't return None) short-circuits.

Per `_is_meaningful` in `manager.py:26-32`: `None` is not meaningful → fail through; empty list `[]` is meaningful only if it has length > 0, so empty list also fails through. Both end up triggering the next fetcher. The distinction between `None` and `[]` here is mostly cosmetic — the manager treats them the same. Keep the split for clarity (None = upstream returned nothing valid; [] = upstream returned empty result).

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_zzshare_fetcher.py::TestRealtimeQuote tests/test_zzshare_fetcher.py::TestNormalizeRtKRow tests/test_zzshare_fetcher.py::TestRealtimeQuotes -v`

Expected: PASS for all 12 tests (4 existing + 2 normalize + 6 new).

- [ ] **Step 5: Commit**

```bash
git add stock_data/data_provider/fetchers/zzshare_fetcher.py tests/test_zzshare_fetcher.py
git commit -m "feat(zzshare): implement get_realtime_quotes (all-market via rt_k wildcard)"
```

---

## Task 8: Add `DataFetcherManager.get_realtime_quotes` failover wrapper

**Files:**
- Modify: `stock_data/data_provider/manager.py` (add method after existing `get_realtime_quote` at line 734)
- Create: `tests/test_manager_realtime_quotes.py` (4 failover + circuit-breaker tests)

**Interfaces:**
- Consumes: `BaseFetcher.get_realtime_quotes` (Tasks 3, 5, 7), existing `_filter_by_capability`, `_with_failover`, `REALTIME_CIRCUIT_BREAKER`
- Produces: `DataFetcherManager.get_realtime_quotes(market: str) -> tuple[list[UnifiedRealtimeQuote] | None, str]`

- [ ] **Step 1: Write failing tests**

Create `tests/test_manager_realtime_quotes.py`:

```python
"""Tests for DataFetcherManager.get_realtime_quotes failover."""

from unittest.mock import MagicMock

import pytest

from stock_data.data_provider.base import DataCapability, DataFetchError
from stock_data.data_provider.core.types import (
    REALTIME_CIRCUIT_BREAKER,
    RealtimeSource,
    UnifiedRealtimeQuote,
)
from stock_data.data_provider.manager import DataFetcherManager


def _make_quote(code: str = "600519", name: str = "贵州茅台") -> UnifiedRealtimeQuote:
    return UnifiedRealtimeQuote(
        code=code, name=name, source=RealtimeSource.AKSHARE, price=1680.5,
    )


class TestManagerGetRealtimeQuotes:
    def _manager(self):
        return DataFetcherManager()

    def _add_fetcher(self, manager, name, priority, supported_data_types,
                     get_realtime_quotes_return=None, raises=None):
        fetcher = MagicMock()
        fetcher.name = name
        fetcher.priority = priority
        fetcher.supported_markets = {"csi"}
        fetcher.supported_data_types = supported_data_types
        if raises is not None:
            fetcher.get_realtime_quotes = MagicMock(side_effect=raises)
        else:
            fetcher.get_realtime_quotes = MagicMock(
                return_value=get_realtime_quotes_return
            )
        manager._fetchers.append(fetcher)
        return fetcher

    def test_akshare_succeeds_returns_akshare_source(self):
        mgr = self._manager()
        akshare = self._add_fetcher(
            mgr, "AkshareFetcher", 3,
            DataCapability.STOCK_REALTIME_QUOTE,
            get_realtime_quotes_return=[_make_quote()],
        )
        quotes, source = mgr.get_realtime_quotes("csi")
        assert source == "AkshareFetcher"
        assert len(quotes) == 1
        assert akshare.get_realtime_quotes.call_count == 1
        assert akshare.get_realtime_quotes.call_args.args == ("csi",)

    def test_akshare_fails_falls_through_to_zzshare(self):
        mgr = self._manager()
        self._add_fetcher(
            mgr, "AkshareFetcher", 3,
            DataCapability.STOCK_REALTIME_QUOTE,
            raises=DataFetchError("akshare timeout"),
        )
        zzshare = self._add_fetcher(
            mgr, "ZzshareFetcher", 2,
            DataCapability.STOCK_REALTIME_QUOTE,
            get_realtime_quotes_return=[_make_quote()],
        )
        quotes, source = mgr.get_realtime_quotes("csi")
        assert source == "ZzshareFetcher"
        assert len(quotes) == 1

    def test_tencent_fetcher_raises_skipped_via_abc_default(self):
        """TencentFetcher doesn't override get_realtime_quotes → ABC default raises.

        Manager catches DataFetchError and skips to next fetcher.
        """
        mgr = self._manager()
        # Tencent-style: has capability but raises on get_realtime_quotes
        self._add_fetcher(
            mgr, "TencentFetcher", 5,
            DataCapability.STOCK_REALTIME_QUOTE,
            raises=DataFetchError("TencentFetcher does not support all-market realtime quote"),
        )
        akshare = self._add_fetcher(
            mgr, "AkshareFetcher", 3,
            DataCapability.STOCK_REALTIME_QUOTE,
            get_realtime_quotes_return=[_make_quote()],
        )
        quotes, source = mgr.get_realtime_quotes("csi")
        assert source == "AkshareFetcher"
        assert len(quotes) == 1

    def test_all_fetchers_fail_returns_none_empty_source(self):
        mgr = self._manager()
        self._add_fetcher(
            mgr, "AkshareFetcher", 3,
            DataCapability.STOCK_REALTIME_QUOTE,
            raises=DataFetchError("akshare down"),
        )
        self._add_fetcher(
            mgr, "ZzshareFetcher", 2,
            DataCapability.STOCK_REALTIME_QUOTE,
            raises=DataFetchError("zzshare down"),
        )
        # Per _with_failover with allow_none=True: total failure returns (None, "")
        # (the manager layer may raise instead — depends on the wrapper; adjust if needed)
        try:
            quotes, source = mgr.get_realtime_quotes("csi")
            assert quotes is None
            assert source == ""
        except DataFetchError:
            # Also acceptable: total failure raises when allow_none=False
            pass

    def test_empty_results_fall_through_to_next_fetcher(self):
        """Empty list from primary fetcher → fall through (per _is_meaningful)."""
        mgr = self._manager()
        akshare = self._add_fetcher(
            mgr, "AkshareFetcher", 3,
            DataCapability.STOCK_REALTIME_QUOTE,
            get_realtime_quotes_return=[],   # empty → not meaningful
        )
        zzshare = self._add_fetcher(
            mgr, "ZzshareFetcher", 2,
            DataCapability.STOCK_REALTIME_QUOTE,
            get_realtime_quotes_return=[_make_quote()],
        )
        quotes, source = mgr.get_realtime_quotes("csi")
        assert source == "ZzshareFetcher"
        assert len(quotes) == 1
        assert akshare.get_realtime_quotes.call_count == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_manager_realtime_quotes.py -v`

Expected: AttributeError on `get_realtime_quotes` method (only `get_realtime_quote` exists on manager).

- [ ] **Step 3: Implement `DataFetcherManager.get_realtime_quotes`**

In `stock_data/data_provider/manager.py`, immediately after the existing `get_realtime_quote` method (line 734-755), add:

```python
    def get_realtime_quotes(
        self, market: str
    ) -> tuple[list[UnifiedRealtimeQuote] | None, str]:
        """All-market realtime quote with priority-based failover + circuit breaker.

        Routes via existing STOCK_REALTIME_QUOTE capability — no new flag.
        Fetchers whose ``get_realtime_quotes`` raises ``DataFetchError``
        (e.g. the ABC default) are skipped, not failed; this lets
        TencentFetcher / ZhituFetcher / TushareFetcher / MyquantFetcher
        (per-code only) co-exist with AkshareFetcher / ZzshareFetcher
        (all-market) without bumping them out of the capability filter.

        Returns:
            ``(quotes_or_None, fetcher_name_or_empty)`` tuple. ``quotes``
            is the first non-empty list returned by any candidate; ``None``
            when every candidate either raised or returned empty.
            ``fetcher_name`` is the name of the fetcher that returned the
            non-empty list, or ``""`` when no fetcher produced data.
        """
        candidates = self._filter_by_capability(market, DataCapability.STOCK_REALTIME_QUOTE)
        if not candidates:
            raise DataFetchError(f"No fetcher supports quote market={market}")

        def _call(f):
            try:
                return f.get_realtime_quotes(market)
            except DataFetchError as e:
                # ABC default raise = "this fetcher doesn't support all-market".
                # Skip without recording a circuit-breaker failure (the fetcher
                # is intentionally not advertising this capability — it's not
                # "broken", it's "not applicable").
                logger.debug(f"[Manager] {f.name} get_realtime_quotes unsupported: {e}")
                return None

        return self._with_failover(
            DataCapability.STOCK_REALTIME_QUOTE,
            market,
            f"realtime_quotes {market}",
            _call,
            circuit_breaker=REALTIME_CIRCUIT_BREAKER,
            candidates=sorted(candidates, key=lambda f: f.priority),
            return_source=True,
            allow_none=True,
        )
```

`_filter_by_capability`, `_with_failover`, `REALTIME_CIRCUIT_BREAKER`, `DataFetchError`, `DataCapability`, and `UnifiedRealtimeQuote` are already imported at the top of `manager.py`.

**Critical note on `allow_none=True`**: when every fetcher raises or returns empty, `_with_failover` returns `(None, "")` rather than raising. The route layer must check for `(None, "")` and emit a 503 — see Task 10.

**Critical note on circuit breaker**: when `_call` returns `None` (from our explicit `except DataFetchError`), `_with_failover` does NOT call `circuit_breaker.record_failure()` because there's no exception — it just sees a None return and treats it as "not meaningful" (per `_is_meaningful`). So the ABC-raise path does NOT poison the breaker. ✓

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_manager_realtime_quotes.py -v`

Expected: PASS for all 5 tests.

- [ ] **Step 5: Verify the existing single-stock `get_realtime_quote` still works**

Run: `.venv/Scripts/python.exe -m pytest tests/test_providers.py -v 2>&1 | tail -20`

Expected: existing tests still PASS. (We're only adding a new method, not changing `get_realtime_quote`.)

- [ ] **Step 6: Commit**

```bash
git add stock_data/data_provider/manager.py tests/test_manager_realtime_quotes.py
git commit -m "feat(manager): get_realtime_quotes failover wrapper (no new capability flag)"
```

---

## Task 9: Relocate `list_stocks` from `calendar.py` to `stocks.py` and update docstring

**Files:**
- Modify: `stock_data/api/routes/calendar.py` (remove `list_stocks` function; remove `stock_list` import)
- Modify: `stock_data/api/routes/stocks.py` (update module docstring; add `list_stocks` skeleton with new params but path A only)

**Interfaces:**
- Consumes: existing `get_manager`, `stock_list.get_stock_list`, `cached_lookup`/`cached_store`, `make_stock_list_cache_key`
- Produces: relocated `list_stocks` endpoint with new params (path A only at this stage; path B added in Task 10)

This task is purely relocation + path-A-only. It establishes the new endpoint signature and removes the old one. Tests must pass for both old TestListStocks cases (no behavior change yet) and the new shape.

- [ ] **Step 1: Run existing TestListStocks to confirm baseline**

Run: `.venv/Scripts/python.exe -m pytest tests/test_routes.py::TestListStocks -v`

Expected: PASS (existing 3 tests + 2 from Task 1 = 5 total).

- [ ] **Step 2: Update `stocks.py` module docstring**

In `stock_data/api/routes/stocks.py`, replace the module docstring (lines 1-7):

Current:
```python
"""Per-stock endpoints. Everything under ``/stocks/{code}/...`` plus the
related dragon-tiger / margin / block-trade / holder-num / dividend / fund-flow /
reports / announcements / info / quote / kline surfaces.

The stock-list endpoint (``GET /stocks``) lives in :mod:`.calendar` because
it's a list-level query, not per-stock.
"""
```

Replace with:
```python
"""Per-stock endpoints + the stock-list endpoint.

Hosts every route under ``/stocks/...``:
- ``GET /stocks`` — list endpoint (was previously in ``calendar.py``; relocated
  2026-07-29 when include_quote/sort_by support made it more than a list-level
  query — see docs/superpowers/specs/2026-07-29-stocks-list-include-quote-design.md)
- ``GET /stocks/{code}/{info,quote,kline,dragon-tiger,margin,block-trade,...}`` —
  per-stock data surfaces
"""
```

- [ ] **Step 3: Update `calendar.py` to remove the relocated function**

In `stock_data/api/routes/calendar.py`, delete the entire `list_stocks` route definition (lines 15-53). Also remove the now-unused import `from ...data_provider.persistence import stock_list` (line 7). Verify with:

```bash
grep -n "stock_list\|list_stocks" stock_data/api/routes/calendar.py
```

Expected: no matches.

The `TradeCalendarResponse` import (line 9) and `get_trade_calendar` route remain — `calendar.py` keeps `/calendar` only.

- [ ] **Step 4: Run tests — relocation alone should not change behavior**

Run: `.venv/Scripts/python.exe -m pytest tests/test_routes.py::TestListStocks -v`

Expected: PASS. (Endpoint path didn't change; only file location.)

- [ ] **Step 5: Commit relocation (skeleton only, path A still works)**

For now, the relocated `list_stocks` should be a near-copy of the original. Place it at the top of `stocks.py` (above `get_stock_info`). Add the new param signatures but DO NOT add path B yet — that's Task 10.

```python
@router.get(
    "/stocks",
    response_model=list[StockInfo],
    responses={
        400: {"model": ErrorResponse, "description": "sort_by without include_quote"},
        422: {"model": ErrorResponse, "description": "Invalid request"},
        503: {"model": ErrorResponse, "description": "All fetchers failed"},
        500: {"model": ErrorResponse, "description": "Server error"},
    },
    tags=["stocks"],
)
@endpoint_meta(
    summary="股票列表（支持全市场实时行情 + 排序）",
    markets=["csi", "hk", "us"],
    capabilities=["STOCK_LIST", "STOCK_REALTIME_QUOTE"],
)
@map_errors
def list_stocks(
    market: str = Query(..., pattern="^(csi|hk|us)$", description="Market: csi/hk/us"),
    include_quote: bool = Query(False, description="Include realtime quote for csi"),
    sort_by: Literal["change_pct", "amount", "turnover_rate", "price", "total_mv", "volume"] | None = Query(None),
    sort_order: Literal["asc", "desc"] = Query("desc"),
    offset: int = Query(0, ge=0, description="Pagination offset"),
    limit: int = Query(100, ge=1, le=10000, description="Pagination limit"),
) -> list[StockInfo]:
    """List all available stocks for a specified market.

    ``include_quote=true`` returns a full-market A-share realtime snapshot
    (single upstream call, cached 60s). HK/US do not support include_quote.

    ``sort_by`` requires ``include_quote=true``; sort applies to quote
    fields only. Default order is upstream-natural (ts_code ascending);
    sort_by overrides for the response.
    """
    manager = get_manager()

    if include_quote and market != "csi":
        raise HTTPException(422, detail={
            "error": "include_quote_unsupported",
            "message": "include_quote=true only supports market=csi; hk/us have no all-market realtime source.",
        })

    if sort_by is not None and not include_quote:
        raise HTTPException(400, detail={
            "error": "sort_requires_quote",
            "message": "sort_by requires include_quote=true (sortable fields are quote-only).",
        })

    # Path B will be added in Task 10. For now, ignore include_quote / sort_by
    # and route through path A (metadata only) — callers without
    # include_quote=true keep working unchanged.
    if include_quote or sort_by is not None:
        # Task 10 will replace this with the quote path
        raise HTTPException(503, detail={
            "error": "not_yet_implemented",
            "message": "include_quote path B implementation lands in Task 10.",
        })

    # Path A — metadata only (current behavior)
    cache_key = make_stock_list_cache_key(market, offset, limit)
    hit = cached_lookup(get_stock_list_cache, cache_key, "stock_list")
    if hit is not None:
        return hit

    meta_stocks, origin = stock_list.get_stock_list(market, manager=manager)
    page = meta_stocks[offset : offset + limit]
    rows = [
        StockInfo(
            code=s["code"],
            name=s["name"],
            market=market,
            exchange=s.get("exchange"),
            quote=None,
            source=origin,
        )
        for s in page
    ]
    cached_store(get_stock_list_cache, cache_key, rows)
    return rows
```

Required new imports at the top of `stocks.py`:

```python
from typing import Literal

from ...data_provider.utils.normalize import code_to_exchange
from ..cache import (
    cached_lookup,
    cached_store,
    get_stock_list_cache,
    get_stock_list_quote_cache,
    make_stock_list_cache_key,
    make_stock_list_quote_cache_key,
)
```

- [ ] **Step 6: Run existing tests to verify relocation + path A**

Run: `.venv/Scripts/python.exe -m pytest tests/test_routes.py::TestListStocks tests/test_bugfix_pydantic_akshare_csi.py -v`

Expected: PASS for all. The 5 TestListStocks tests still work; the `?market=cn` 422 test still works.

- [ ] **Step 7: Commit**

```bash
git add stock_data/api/routes/stocks.py stock_data/api/routes/calendar.py
git commit -m "refactor(routes): relocate /stocks from calendar.py; new params (path A only)"
```

---

## Task 10: Implement path B (include_quote / sort_by) on the relocated `list_stocks`

**Files:**
- Modify: `stock_data/api/routes/stocks.py` (replace the Task-9 placeholder with full path B logic)

**Interfaces:**
- Consumes: `manager.get_realtime_quotes` (Task 8), `_stock_list_quote_cache` + `make_stock_list_quote_cache_key` (Task 2), `StockQuote.from_unified_quote` (existing)
- Produces: full path B with cache + sort + slice

- [ ] **Step 1: Write failing tests for path B behavior**

Append to `tests/test_routes.py::TestListStocks` (test classes 17-31 of the spec):

```python
def test_list_stocks_include_quote_csi_cache_miss(self, client, monkeypatch):
    """include_quote=true with cold cache → manager.get_realtime_quotes called once."""
    from stock_data.data_provider.core.types import (
        RealtimeSource, UnifiedRealtimeQuote,
    )
    fake_quotes = [
        UnifiedRealtimeQuote(code="600519", name="贵州茅台",
                             source=RealtimeSource.AKSHARE, price=1680.5,
                             change_pct=1.23, amount=2.07e8,
                             turnover_rate=0.5, total_mv=2.16e12),
        UnifiedRealtimeQuote(code="000001", name="平安银行",
                             source=RealtimeSource.AKSHARE, price=12.5,
                             change_pct=-0.5, amount=1.0e8,
                             turnover_rate=0.3, total_mv=2.4e11),
    ]
    call_count = {"n": 0}
    def fake_get_rt_quotes(market):
        call_count["n"] += 1
        return list(fake_quotes), "akshare"
    from stock_data.api.routes.helpers import get_manager
    mgr = get_manager()
    monkeypatch.setattr(mgr, "get_realtime_quotes", fake_get_rt_quotes)

    response = client.get("/api/v1/stocks?market=csi&include_quote=true&limit=10")
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 2
    assert data[0]["code"] == "600519"
    assert data[0]["quote"] is not None
    assert data[0]["quote"]["current_price"] == 1680.5
    assert data[0]["source"] == "akshare"
    assert call_count["n"] == 1  # cold cache → exactly one upstream call


def test_list_stocks_include_quote_hk_returns_422(self, client):
    response = client.get("/api/v1/stocks?market=hk&include_quote=true")
    assert response.status_code == 422
    body = response.json()
    assert body["detail"]["error"] == "include_quote_unsupported"


def test_list_stocks_include_quote_us_returns_422(self, client):
    response = client.get("/api/v1/stocks?market=us&include_quote=true")
    assert response.status_code == 422


def test_list_stocks_sort_without_quote_returns_400(self, client):
    response = client.get("/api/v1/stocks?market=csi&sort_by=change_pct")
    assert response.status_code == 400
    body = response.json()
    assert body["detail"]["error"] == "sort_requires_quote"


def test_list_stocks_invalid_sort_by_returns_422(self, client):
    response = client.get("/api/v1/stocks?market=csi&include_quote=true&sort_by=foobar")
    assert response.status_code == 422


def test_list_stocks_limit_exceeds_max_returns_422(self, client):
    response = client.get("/api/v1/stocks?market=csi&limit=10001")
    assert response.status_code == 422


def test_list_stocks_include_quote_all_fetchers_fail_returns_503(self, client, monkeypatch):
    from stock_data.api.routes.helpers import get_manager
    from stock_data.data_provider.base import DataFetchError
    mgr = get_manager()
    monkeypatch.setattr(mgr, "get_realtime_quotes",
                        MagicMock(side_effect=DataFetchError("all failed")))
    response = client.get("/api/v1/stocks?market=csi&include_quote=true")
    assert response.status_code == 503


def test_list_stocks_offset_out_of_range_returns_empty(self, client):
    response = client.get("/api/v1/stocks?market=csi&offset=100000")
    assert response.status_code == 200
    assert response.json() == []


def test_list_stocks_refresh_param_removed(self, client):
    response = client.get("/api/v1/stocks?market=csi&refresh=true")
    assert response.status_code == 422  # FastAPI unknown query param


def test_list_stocks_sort_by_change_pct_desc(self, client, monkeypatch):
    """Path B: sort by quote.change_pct desc — applied after cache hit."""
    from stock_data.data_provider.core.types import (
        RealtimeSource, UnifiedRealtimeQuote,
    )
    fake_quotes = [
        UnifiedRealtimeQuote(code="000001", name="平安银行",
                             source=RealtimeSource.AKSHARE, change_pct=-1.0),
        UnifiedRealtimeQuote(code="600519", name="贵州茅台",
                             source=RealtimeSource.AKSHARE, change_pct=2.0),
        UnifiedRealtimeQuote(code="300750", name="宁德时代",
                             source=RealtimeSource.AKSHARE, change_pct=0.5),
    ]
    from stock_data.api.routes.helpers import get_manager
    mgr = get_manager()
    monkeypatch.setattr(mgr, "get_realtime_quotes",
                        lambda market: (fake_quotes, "akshare"))

    response = client.get("/api/v1/stocks?market=csi&include_quote=true&sort_by=change_pct&sort_order=desc")
    assert response.status_code == 200
    data = response.json()
    codes = [s["code"] for s in data]
    assert codes == ["600519", "300750", "000001"]  # 2.0, 0.5, -1.0


def test_list_stocks_sort_by_change_pct_asc(self, client, monkeypatch):
    from stock_data.data_provider.core.types import (
        RealtimeSource, UnifiedRealtimeQuote,
    )
    fake_quotes = [
        UnifiedRealtimeQuote(code="000001", name="平安银行",
                             source=RealtimeSource.AKSHARE, change_pct=-1.0),
        UnifiedRealtimeQuote(code="600519", name="贵州茅台",
                             source=RealtimeSource.AKSHARE, change_pct=2.0),
    ]
    from stock_data.api.routes.helpers import get_manager
    mgr = get_manager()
    monkeypatch.setattr(mgr, "get_realtime_quotes",
                        lambda market: (fake_quotes, "akshare"))

    response = client.get("/api/v1/stocks?market=csi&include_quote=true&sort_by=change_pct&sort_order=asc")
    assert response.status_code == 200
    codes = [s["code"] for s in response.json()]
    assert codes == ["000001", "600519"]


def test_list_stocks_include_quote_respects_limit(self, client, monkeypatch):
    """limit=2 on 5400 upstream quotes → response has 2 rows."""
    from stock_data.data_provider.core.types import (
        RealtimeSource, UnifiedRealtimeQuote,
    )
    fake_quotes = [
        UnifiedRealtimeQuote(code=f"{600000+i:06d}", name=f"测试{i}",
                             source=RealtimeSource.AKSHARE)
        for i in range(5400)
    ]
    from stock_data.api.routes.helpers import get_manager
    mgr = get_manager()
    monkeypatch.setattr(mgr, "get_realtime_quotes",
                        lambda market: (fake_quotes, "akshare"))

    response = client.get("/api/v1/stocks?market=csi&include_quote=true&limit=2")
    assert response.status_code == 200
    assert len(response.json()) == 2
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_routes.py::TestListStocks -v`

Expected: the new 11 path-B tests FAIL (path B still raises the Task-9 "not_yet_implemented" 503); the existing 5 tests still PASS.

- [ ] **Step 3: Implement path B**

Replace the placeholder block in `stocks.py::list_stocks` (the part with `raise HTTPException(503, ...)`) with:

```python
    # Determine execution path
    use_quote_path = include_quote or sort_by is not None

    if use_quote_path:
        return _list_stocks_with_quote(manager, offset, limit, sort_by, sort_order)
    else:
        return _list_stocks_metadata_only(market, manager, offset, limit)


# Whitelist mapping: sort_by param → UnifiedRealtimeQuote field name.
# Adding a new sortable quote field = add an entry here. Pydantic Literal
# on the Query param prevents unknown values at the route layer.
_SORT_FIELD_MAP = {
    "change_pct": "change_pct",
    "amount": "amount",
    "turnover_rate": "turnover_rate",
    "price": "price",
    "total_mv": "total_mv",
    "volume": "volume",
}


def _list_stocks_with_quote(manager, offset, limit, sort_by, sort_order):
    """Path B: include_quote=true or sort_by set → single upstream quote call.

    Cached at the route layer (60s, single key per market). sort_by and
    slice are applied in-memory on cache hit so multiple sort/limit combos
    share the upstream fetch.
    """
    market = "csi"  # path B is csi-only; route layer rejects hk/us upstream
    cache_key = make_stock_list_quote_cache_key(market)
    hit = cached_lookup(get_stock_list_quote_cache, cache_key, "stock_list_quote")

    if hit is not None:
        quotes, quote_source = hit
    else:
        quotes, quote_source = manager.get_realtime_quotes(market)
        if quotes is None:
            raise HTTPException(503, detail={
                "error": "quote_unavailable",
                "message": "All realtime fetchers failed for market=csi",
            })
        cached_store(get_stock_list_quote_cache, cache_key, (quotes, quote_source))

    # Build StockInfo list from quote data only (no persistence join).
    # market is hardcoded "csi" (constant in path B); exchange derived
    # from code prefix via the existing code_to_exchange helper.
    rows = []
    for q in quotes:
        try:
            exchange = code_to_exchange(q.code)
        except Exception:
            exchange = None
        rows.append(StockInfo(
            code=q.code,
            name=q.name,
            market=market,
            exchange=exchange,
            quote=StockQuote.from_unified_quote(q),
            source=quote_source,
        ))

    # Sort (path B never has quote=null entries — every row came from quote data).
    if sort_by is not None:
        field = _SORT_FIELD_MAP[sort_by]
        rows.sort(
            key=lambda r: getattr(r.quote, field) or float("-inf"),
            reverse=(sort_order == "desc"),
        )

    return rows[offset : offset + limit]


def _list_stocks_metadata_only(market, manager, offset, limit):
    """Path A: metadata only (current behavior)."""
    cache_key = make_stock_list_cache_key(market, offset, limit)
    hit = cached_lookup(get_stock_list_cache, cache_key, "stock_list")
    if hit is not None:
        return hit

    meta_stocks, origin = stock_list.get_stock_list(market, manager=manager)
    page = meta_stocks[offset : offset + limit]
    rows = [
        StockInfo(
            code=s["code"],
            name=s["name"],
            market=market,
            exchange=s.get("exchange"),
            quote=None,
            source=origin,
        )
        for s in page
    ]
    cached_store(get_stock_list_cache, cache_key, rows)
    return rows
```

The `code_to_exchange` helper is imported from `...data_provider.utils.normalize`. Verify it's importable in this module — it may already be imported in `helpers.py`; if not, add the import.

If `code_to_exchange` doesn't exist or has a different name in `utils/normalize.py`, check there and adjust the import name. (It does exist per the spec — used by `get_stock_info` at `stocks.py:119` in the current pre-relocation code.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_routes.py::TestListStocks -v`

Expected: PASS for all tests (5 from Task 1 + 11 new = 16 total).

- [ ] **Step 5: Run wider test suite for regression**

Run: `.venv/Scripts/python.exe -m pytest tests/test_routes.py tests/test_bugfix_pydantic_akshare_csi.py -v`

Expected: PASS for all. No regression on `/stocks/{code}/*` endpoints or `?market=cn` 422 test.

- [ ] **Step 6: Commit**

```bash
git add stock_data/api/routes/stocks.py tests/test_routes.py
git commit -m "feat(routes): implement path B (include_quote + sort_by/sort_order)"
```

---

## Task 11: Update `CLAUDE.md` to reflect new endpoint behavior

**Files:**
- Modify: `CLAUDE.md`

**Interfaces:**
- Consumes: existing CLAUDE.md text
- Produces: updated Source Tracking section + Fetcher overview table annotations

- [ ] **Step 1: Update Source Tracking section**

In `CLAUDE.md`, find the paragraph in the "Source Tracking (new)" section that says `/stocks` and `/calendar` do not expose `source`. Replace it with the new behavior. Search for `/stocks.*不暴露 source`:

Current text (approximate):
```
> **注意**: `/stocks` 和 `/calendar` 当前响应**不暴露** source 字段 (其 response model 没有 source 字段), 持久化层 origin 仍被透传但被丢弃。这是 YAGNI 决策——如果未来要暴露, 给对应 response model 加 `source: str` 字段即可, 路由层已准备好。
```

Replace with:
```
> `/stocks` 暴露 `source` 字段 (post-2026-07-29): 每个 list entry 的 source 是 metadata origin (akshare/zzshare/persistence) 或 quote fetcher (当 `?include_quote=true`)。`/calendar` 仍然不暴露 source (response model 无该字段)。
```

- [ ] **Step 2: Update Fetcher overview table annotations**

Find the `AkshareFetcher` and `ZzshareFetcher` rows in the Fetcher overview table. The Capabilities column shows the list of capability flags. Add a clarifying note about all-market quote via `get_realtime_quotes(market)`. Search for `AkshareFetcher.*P3` and `ZzshareFetcher.*P2` in CLAUDE.md.

For `AkshareFetcher`, append to the Notes column: `get_realtime_quotes(csi) via ak.stock_zh_a_spot_em() (single call).`

For `ZzshareFetcher`, append to the Notes column: `get_realtime_quotes(csi) via rt_k(ts_code='60*.SH,68*.SH,0*.SZ,3*.SZ,9*.BJ', fields='all') (single call; rate-limited 20/min).`

- [ ] **Step 3: Verify the docs render correctly**

Run: `git diff CLAUDE.md`

Expected: clean diff with the two text updates. No accidental edits.

- [ ] **Step 4: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: update CLAUDE.md for /api/v1/stocks include_quote + sort_by"
```

---

## Self-Review Checklist (run before execution handoff)

The implementer should verify each item before starting:

1. **Spec coverage**: see table below.
2. **Placeholder scan**: no TBD/TODO/"similar to Task N" in any task.
3. **Type consistency**:
   - `BaseFetcher.get_realtime_quotes(market: str) -> list[UnifiedRealtimeQuote] | None` (Task 3) ↔ `AkshareFetcher.get_realtime_quotes(market: str = "csi")` (Task 5) ↔ `ZzshareFetcher.get_realtime_quotes(market: str = "csi")` (Task 7) — ✓ signatures match.
   - `manager.get_realtime_quotes(market: str) -> tuple[list | None, str]` (Task 8) — ✓ return type matches `_with_failover(return_source=True, allow_none=True)` output.
   - `_SORT_FIELD_MAP` keys (Task 10) match `Literal` whitelist in route signature (Task 9-10) — ✓ both use `"change_pct", "amount", "turnover_rate", "price", "total_mv", "volume"`.
   - `StockInfo.quote: StockQuote | None` and `source: str` (Task 1) ↔ Task 9 path A builds both fields, Task 10 path B builds both — ✓.
4. **Order**: ABC default-raise (Task 3) before any fetcher override (Tasks 5, 7). Manager (Task 8) after fetcher impls (Tasks 5, 7). Cache (Task 2) before route (Task 10). Schema (Task 1) before route (Tasks 9, 10).

### Spec coverage matrix

| Spec section | Implemented by |
|---|---|
| §2.1 endpoint contract | Tasks 9, 10 |
| §2.2 response shape | Tasks 1, 4-7, 10 |
| §2.3 BREAKING refresh removed | Task 9 (signature change); Task 10 (test_list_stocks_refresh_param_removed) |
| §2.4 error contract | Task 10 (validation + 503/422/400 handlers) |
| §3 data flow | Task 10 (path B uses manager.get_realtime_quotes, no persistence join) |
| §4.1 ABC method | Task 3 |
| §4.2 AkshareFetcher impl | Tasks 4, 5 |
| §4.3 ZzshareFetcher impl | Tasks 6, 7 |
| §4.4 manager wrapper | Task 8 |
| §4.5 cache instances | Task 2 |
| §4.6 schema extension | Task 1 |
| §4.7 route relocation | Task 9 |
| §4.8 route impl sketch | Task 10 |
| §5 cache strategy | Task 10 (path B single-key-per-market) |
| §6 tests (31 cases) | Tasks 1, 2, 3, 4, 5, 6, 7, 8, 10 |
| §8 CLAUDE.md sync | Task 11 |