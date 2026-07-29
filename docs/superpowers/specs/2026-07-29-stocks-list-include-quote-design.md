# `/api/v1/stocks` — Include Realtime Quote + Sort Support

> Spec for adding `include_quote`, `sort_by`, `sort_order` to the existing
> stock-list endpoint, with a new `DataFetcherManager.get_realtime_quotes` +
> `BaseFetcher.get_realtime_quotes(market)` ABC method for all-market realtime
> snapshots. No new `DataCapability` flag.

**Date**: 2026-07-29
**Status**: Draft
**Scope**: API surface (route), schema, manager, two fetchers, cache, tests

---

## 1. Background

`GET /api/v1/stocks?market=csi|hk|us` (in `stock_data/api/routes/calendar.py`)
currently returns `list[StockInfo]` (4 fields: code/name/market/exchange) — a
metadata-only list with pagination via `offset`/`limit`, no realtime quote, no
sort.

`UnifiedRealtimeQuote` and `StockQuote` (24-field realtime model) exist and
serve `/stocks/{code}/quote`. The single-stock path is per-code via
`BaseFetcher.get_realtime_quote(stock_code)`. No fetcher currently exposes a
single-call all-market variant.

**Goal**: extend `/api/v1/stocks` so callers can ask for the full A-share
market with realtime quote, sorted by quote fields, in one HTTP call. HK/US
remain metadata-only (no all-market source).

---

## 2. Public API

### 2.1 Endpoint contract

```
GET /api/v1/stocks
```

| Param | Type | Default | Constraints |
|---|---|---|---|
| `market` | Literal["csi","hk","us"] | required | Public market tag |
| `include_quote` | bool | `false` | `true` only valid for `market=csi` |
| `sort_by` | Literal["change_pct","amount","turnover_rate","price","total_mv","volume"] \| None | `None` | Requires `include_quote=true` |
| `sort_order` | Literal["asc","desc"] | `"desc"` | |
| `offset` | int ≥ 0 | `0` | Pagination offset |
| `limit` | int 1..10000 | `100` | Pagination limit (raised from current 1000 to cover full market) |

### 2.2 Response

```jsonc
// include_quote=false
[{
  "code": "600519", "name": "贵州茅台", "market": "csi",
  "exchange": "SH",
  "quote": null,
  "source": "persistence"  // or "akshare" / "zzshare"
}]

// include_quote=true (csi only)
[{
  "code": "600519", "name": "贵州茅台", "market": "csi",
  "exchange": "SH",
  "quote": {
    "code": "600519", "name": "贵州茅台",
    "current_price": 1680.5, "change_pct": 1.23,
    "open": 1680.0, "high": 1685.0, "low": 1678.0, "prev_close": 1675.0,
    "volume": 1234567, "volume_unit": "share", "amount": 1.2e8,
    "pe_ttm": 28.5, "pb": 9.1, "mcap_yi": 21000.0, "float_mcap_yi": 21000.0,
    "turnover_pct": 0.5, "amplitude_pct": 0.4,
    "limit_up": null, "limit_down": null, "volume_ratio": 1.2,
    "update_time": null, "pe_static": null,
    "source": "akshare"
  },
  "source": "akshare"
}]
```

`StockInfo` (in `stock_data/api/schemas.py`) gains two fields:
- `quote: StockQuote | None` — populated only on `include_quote=true`
- `source: str` — fetcher name or `"persistence"`

`StockQuote` schema is unchanged (existing 24 fields).

### 2.3 Breaking changes

**`refresh` query param is removed.** Previously `?refresh=true` forced an
upstream fetch. With `include_quote=true` available, the manual override is
no longer needed (`stock_list.get_stock_list()` already auto-refreshes on
first call of day; `include_quote=true` always goes to upstream for quote).
Any existing client passing `?refresh=true` will receive `422` from FastAPI's
unknown-query-param validator.

### 2.4 Error contract

| Condition | HTTP | error code | message |
|---|---|---|---|
| `market ∉ {csi,hk,us}` | 422 | (FastAPI Literal) | `Invalid market value` |
| `include_quote=true` + `market ∈ {hk,us}` | **422** | `include_quote_unsupported` | `include_quote=true only supports market=csi; hk/us have no all-market realtime source.` |
| `sort_by` not in whitelist | 422 | (FastAPI Literal) | `Invalid sort_by value` |
| `sort_by` set without `include_quote=true` | **400** | `sort_requires_quote` | `sort_by requires include_quote=true (sortable fields are quote-only).` |
| `limit > 10000` | 422 | (FastAPI `le=10000`) | `limit must be ≤ 10000` |
| `offset >= total` | 200 | — | returns `[]` (Python slice semantics) |
| All realtime fetchers fail | **503** | `quote_unavailable` | `All realtime fetchers failed for market=csi` |
| All realtime fetchers return empty | **503** | `quote_empty` | `All realtime fetchers returned empty for market=csi` |
| `stock_list` upstream fails (path B metadata) | 503 | `stock_list_unavailable` | `Failed to fetch stock list for market=csi` |

`@map_errors` already maps `DataFetchError → 503` and other
`Exception → 500`; new `HTTPException(400/422, ...)` passes through.

---

## 3. Data flow

Three execution paths:

### 3.1 Path A — `include_quote=false` and `sort_by is None`

```
manager.get_all_stocks()  ←  stock_list.get_stock_list(market)
   ├─ DB hit (non-stale)         → origin="persistence"
   └─ upstream refresh (first-of-day or refresh trigger)
                              → origin="akshare" | "zzshare"
↓
[StockInfo(code, name, market, exchange, quote=None, source=origin)]
   for s in page[offset : offset+limit]
↓
@cache_endpoint (300s, key=market:offset:limit)
```

### 3.2 Path B — `include_quote=true` or `sort_by is set`

```
manager.get_realtime_quotes("csi")
   _filter_by_capability("csi", STOCK_REALTIME_QUOTE) → candidates
   _with_failover(STOCK_REALTIME_QUOTE, "csi",
                  "realtime_quotes csi",
                  lambda f: f.get_realtime_quotes("csi"),
                  circuit_breaker=REALTIME_CIRCUIT_BREAKER,
                  return_source=True, allow_none=True)
   Per-candidate lambda:
     - try f.get_realtime_quotes(market)
     - except DataFetchError → return None  (skip fetcher that doesn't support)
↓
list[UnifiedRealtimeQuote], quote_source
↓
(NO stock_list.get_stock_list() call — derive market/exchange from quote data)
   for q in quotes:
       code = q.code
       name = q.name  (already carried)
       market = "csi"  (constant in this path)
       exchange = code_to_exchange(code)  (existing helper, derives SH/SZ/BJ from prefix)
       quote_obj = StockQuote.from_unified_quote(q)  (existing helper)
       StockInfo(code=code, name=name, market=market, exchange=exchange,
                 quote=quote_obj, source=quote_source)
↓
apply sort_by/sort_order (None or quote field)
   Note: this path B list never has quote=null entries
   (every row came from quote data), so sort is straightforward.
↓
slice [offset : offset+limit]
↓
@in-memory cache (60s, single key per market)
   Cache stores list[StockInfo-with-quote] (already sorted by stable order
   upstream: ts_code ascending).
   Different limit/sort_by/sort_order requests within the 60s window share
   the cached list and re-sort/slice in-memory.
```

### 3.3 Path C — `include_quote=true` + `market ∈ {hk,us}`

```
HTTPException(422, detail={
  "error": "include_quote_unsupported",
  "message": "include_quote=true only supports market=csi; ..."
})
```

### 3.4 Key non-obvious decision: path B does NOT call `stock_list.get_stock_list()`

The previous design had path B join `manager.get_realtime_quotes()` with
`stock_list.get_stock_list()`. That's two upstream calls on cold cache
(worse: 2x upstream traffic) plus join code + sort-stability logic.

Reality check:
- `UnifiedRealtimeQuote` already carries `code` and `name`.
- `market` is hardcoded to `"csi"` in this path (we already reject hk/us).
- `exchange` is derivable from code prefix via `code_to_exchange(code)`
  (existing helper used by `get_stock_info` at `stocks.py:119`).

So the join is unnecessary. Path B becomes a single fetcher call, no join,
no edge case for "DB has code but quote doesn't".

---

## 4. Implementation

### 4.1 `data_provider/base.py` — ABC method

```python
class BaseFetcher:
    ...

    def get_realtime_quotes(self, market: str) -> list[UnifiedRealtimeQuote] | None:
        """Single-call all-market realtime snapshot.

        Default raises; only fetchers whose upstream exposes the full
        market in one call override. Manager routes via STOCK_REALTIME_QUOTE
        capability + failover; fetchers that raise are skipped.
        """
        raise DataFetchError(
            f"{type(self).__name__} does not support all-market realtime quote"
        )
```

**No changes** to `DataCapability` enum or `CAPABILITY_TO_METHOD`. The
existing `STOCK_REALTIME_QUOTE → get_realtime_quote` mapping stays for the
Stage 2 manifest. The new `get_realtime_quotes` method is not enumerated
in the manifest (admin debugger would not test all-market via single fetcher).

### 4.2 `data_provider/fetchers/akshare/fetcher.py`

```python
def _normalize_spot_row(self, row, code: str) -> UnifiedRealtimeQuote:
    """Convert one ak.stock_zh_a_spot_em() row → UnifiedRealtimeQuote.
    Shared by get_realtime_quote (single-stock filter) and
    get_realtime_quotes (all-market iter)."""
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
    """Refactored: same upstream call (stock_zh_a_spot_em + filter),
    now delegates row mapping to _normalize_spot_row."""
    # ... HK / index branches unchanged (out of scope) ...
    # A-share branch:
    df = ak.stock_zh_a_spot_em()
    row_df = df[df["代码"] == self._convert_code(stock_code)]
    if row_df.empty:
        return None
    return self._normalize_spot_row(row_df.iloc[0], stock_code)

def get_realtime_quotes(self, market: str = "csi") -> list[UnifiedRealtimeQuote] | None:
    """A-share all-market via ak.stock_zh_a_spot_em(). Single upstream call."""
    if market not in ("csi", "cn"):
        return None
    import akshare as ak
    try:
        df = ak.stock_zh_a_spot_em()
    except Exception as e:
        logger.warning(f"[AkshareFetcher] stock_zh_a_spot_em failed: {e}")
        return None
    if df is None or df.empty:
        return None
    out = []
    for _, row in df.iterrows():
        code = str(row.get("代码", "")).strip()
        if not code:
            continue
        out.append(self._normalize_spot_row(row, code))
    return out
```

### 4.3 `data_provider/fetchers/zzshare_fetcher.py`

```python
_RT_K_ALL_MARKET_TS_CODE = "60*.SH,68*.SH,0*.SZ,3*.SZ,9*.BJ"

def _normalize_rt_k_row(self, row, code: str) -> UnifiedRealtimeQuote:
    """Convert one api.rt_k() row → UnifiedRealtimeQuote. Shared by
    get_realtime_quote (single code) and get_realtime_quotes (wildcard)."""
    pre_close = safe_float(row.get("pre_close"))
    close = safe_float(row.get("close"))
    return UnifiedRealtimeQuote(
        code=normalize_stock_code(code),
        name=str(row.get("name", "")),
        source=RealtimeSource.ZZSHARE,
        price=close,
        change_pct=safe_float(row.get("quote_rate")),
        change_amount=(close - pre_close)
            if (close is not None and pre_close is not None) else None,
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
    """Unchanged upstream: rt_k(ts_code='600519.SH', fields='all').
    Only row-mapping delegated to _normalize_rt_k_row."""
    # (existing call, just `df.iloc[0]` row passed through helper)

def get_realtime_quotes(self, market: str = "csi") -> list[UnifiedRealtimeQuote] | None:
    """A-share all-market via rt_k wildcard + fields='all'."""
    self._ensure_api()
    api = self.__class__._api
    if api is None or market not in ("csi", "cn"):
        return None
    try:
        df = api.rt_k(ts_code=_RT_K_ALL_MARKET_TS_CODE, fields="all")
    except Exception as e:
        logger.warning(f"[ZzshareFetcher] rt_k all-market failed: {e}")
        return None
    if df is None or df.empty:
        return None
    out = []
    for _, row in df.iterrows():
        ts_code = str(row.get("ts_code", ""))
        if not ts_code:
            continue
        code = ts_code.split(".")[0]  # "600519.SH" → "600519"
        out.append(self._normalize_rt_k_row(row, code))
    return out
```

**Important**: `get_realtime_quote` does NOT route through `get_realtime_quotes`
+ filter. `rt_k` natively supports single code; calling the wildcard variant
for one stock would pull ~5400 rows unnecessarily.

### 4.4 `data_provider/manager.py`

```python
def get_realtime_quotes(
    self, market: str
) -> tuple[list[UnifiedRealtimeQuote] | None, str]:
    """All-market realtime quote with failover + circuit breaker.

    Filter by STOCK_REALTIME_QUOTE (existing capability — no new flag),
    iterate candidates in priority order, call get_realtime_quotes(market)
    on each. Per-fetcher DataFetchError → skip (treated as "not supported").
    Returns (list_or_None, fetcher_name_or_empty).
    """
    candidates = self._filter_by_capability(market, DataCapability.STOCK_REALTIME_QUOTE)
    if not candidates:
        raise DataFetchError(f"No fetcher supports quote market={market}")

    def _call(f):
        try:
            return f.get_realtime_quotes(market)
        except DataFetchError as e:
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

### 4.5 `api/cache.py` — two new TTLCache instances

```python
_stock_list_cache: TTLCache = TTLCache(maxsize=64, ttl=300)        # path A
_stock_list_quote_cache: TTLCache = TTLCache(maxsize=8, ttl=60)    # path B

def get_stock_list_cache() -> TTLCache:
    return _stock_list_cache

def get_stock_list_quote_cache() -> TTLCache:
    return _stock_list_quote_cache

def make_stock_list_cache_key(market: str, offset: int, limit: int) -> str:
    return f"stock_list:{market}:{offset}:{limit}"

def make_stock_list_quote_cache_key(market: str) -> str:
    return f"stock_list_quote:{market}"
```

TTL rationale:
- `_stock_list_cache` 300s — metadata rarely changes, DB-backed anyway; TTL
  just dedupes dashboard refreshes.
- `_stock_list_quote_cache` 60s — matches `_quote_cache` TTL; one entry per
  market is enough.

**Why not reuse `_quote_cache`** — `maxsize=1024` is sized for per-stock entries
(~80B each). A single all-market response is ~5400 × ~300B = ~1.6 MB; one entry
in `_quote_cache` is fine, but mixing scales in the same instance is a
maintenance hazard. Separate cache keeps the two domains isolated.

### 4.6 `api/schemas.py` — `StockInfo` extension

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

### 4.7 `api/routes/calendar.py` and `api/routes/stocks.py` — relocation

`list_stocks` moves from `stock_data/api/routes/calendar.py:15-53` to
`stock_data/api/routes/stocks.py` (alongside the per-stock routes). Update
the module-level docstring in `stocks.py` that currently states
"the stock-list endpoint lives in calendar" to remove that clause.

After relocation, `calendar.py` only hosts `GET /calendar`. The
`stock_list` import (currently in `calendar.py:7`) moves to `stocks.py`,
along with any helper imports the relocated route needs.

### 4.8 Route implementation sketch

```python
# in stocks.py (after relocation)
@router.get(
    "/stocks",
    response_model=list[StockInfo],
    responses={
        422: {"model": ErrorResponse, "description": "Invalid request"},
        400: {"model": ErrorResponse, "description": "sort_by without include_quote"},
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
    market: str = Query(..., pattern="^(csi|hk|us)$"),
    include_quote: bool = Query(False),
    sort_by: Literal["change_pct","amount","turnover_rate","price","total_mv","volume"] | None = Query(None),
    sort_order: Literal["asc","desc"] = Query("desc"),
    offset: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=10000),
) -> list[StockInfo]:
    """..."""
    manager = get_manager()

    # Validate include_quote vs market
    if include_quote and market != "csi":
        raise HTTPException(422, detail={
            "error": "include_quote_unsupported",
            "message": "include_quote=true only supports market=csi; hk/us have no all-market realtime source.",
        })

    # Validate sort_by requires include_quote
    if sort_by is not None and not include_quote:
        raise HTTPException(400, detail={
            "error": "sort_requires_quote",
            "message": "sort_by requires include_quote=true (sortable fields are quote-only).",
        })

    use_quote = include_quote or sort_by is not None

    if use_quote:
        return _list_stocks_with_quote(market, manager, offset, limit, sort_by, sort_order)
    else:
        return _list_stocks_metadata_only(market, manager, offset, limit)
```

`_list_stocks_metadata_only` and `_list_stocks_with_quote` are private helpers
in the same file; the former wraps `@cache_endpoint` style behavior via
`cached_lookup`/`cached_store` around `stock_list.get_stock_list()`.

---

## 5. Cache strategy (recap)

| Cache | TTL | maxsize | Key | Value |
|---|---|---|---|---|
| `_stock_list_cache` | 300s | 64 | `stock_list:{market}:{offset}:{limit}` | `list[StockInfo]` (quote=null, source=persistence-or-fetcher) |
| `_stock_list_quote_cache` | 60s | 8 | `stock_list_quote:{market}` | `list[StockInfo]` (with quote populated, source=quote-fetcher) |

Path B caches the full-market response as a single key per market. After
cache hit, sort_by/sort_order and offset/limit are applied **in-memory** in
the route layer. Multiple sort_by/limit combinations within the 60s window
share the cached upstream fetch.

`ENABLE_API_CACHE=false` (existing toggle) disables both via
`cached_lookup` / `cached_store` no-op semantics.

---

## 6. Tests

31 new test cases distributed across 5 files. TDD order: write tests, watch
them fail, implement, watch them pass.

### 6.1 `tests/test_routes.py` (extend `TestListStocks`, line 154-176)

1. `test_list_stocks_csi_no_quote_no_sort` — backward compat, all `quote=None`
2. `test_list_stocks_persistence_hit` — DB hit → `source="persistence"`
3. `test_list_stocks_upstream_refresh` — DB miss → fetcher → `source="akshare"`
4. `test_list_stocks_include_quote_csi_cache_miss` — first request, fetch
5. `test_list_stocks_include_quote_csi_cache_hit` — second request within 60s
   uses cache (mock fetch count == 0)
6. `test_list_stocks_include_quote_respects_limit` — limit=100 on 5400 quotes
7. `test_list_stocks_sort_by_change_pct_desc` — sort applied
8. `test_list_stocks_sort_by_change_pct_asc`
9. `test_list_stocks_sort_by_amount`
10. `test_list_stocks_include_quote_hk_returns_422`
11. `test_list_stocks_include_quote_us_returns_422`
12. `test_list_stocks_sort_without_quote_returns_400`
13. `test_list_stocks_invalid_sort_by_returns_422`
14. `test_list_stocks_limit_exceeds_max_returns_422`
15. `test_list_stocks_include_quote_all_fetchers_fail_returns_503`
16. `test_list_stocks_offset_out_of_range_returns_empty`
17. `test_list_stocks_refresh_param_removed` — BREAKING: `?refresh=true` → 422

### 6.2 `tests/test_zzshare_fetcher.py` (extend `TestRealtimeQuote`)

18. `test_realtime_quotes_uses_wildcard` — pin `ts_code='60*.SH,68*.SH,...'` + `fields='all'`
19. `test_realtime_quote_uses_single_code_not_wildcard` — single-stock path
    MUST NOT degenerate to wildcard (regression guard)
20. `test_realtime_quotes_empty_df_returns_empty_list`
21. `test_realtime_quotes_sdk_unavailable_returns_none`
22. `test_normalize_rt_k_row_consistent` — helper output stable
23. `test_realtime_quotes_returns_all_rows` — 5400-row df → 5400 quotes

### 6.3 `tests/test_providers.py` (extend akshare block at 150-233)

24. `test_get_realtime_quotes_csi_calls_spot_em` — mock ak.stock_zh_a_spot_em
25. `test_normalize_spot_row_consistent` — helper stable

### 6.4 `tests/test_manager.py` (or new file)

26. `test_manager_realtime_quotes_akshare_failover_to_zzshare`
27. `test_manager_realtime_quotes_all_fail_returns_none`
28. `test_manager_realtime_quotes_skips_unsupported_fetchers` — TencentFetcher
    inherits ABC raise, manager skips
29. `test_manager_realtime_quotes_respects_circuit_breaker`

### 6.5 `tests/test_cache_keys.py` (or new file)

30. `test_stock_list_cache_key_different_pages`
31. `test_stock_list_quote_cache_key_per_market`

---

## 7. Anti-patterns explicitly avoided

- ❌ No new `DataCapability` flag (reuses `STOCK_REALTIME_QUOTE`)
- ❌ No per-stock loop fallback in path B (yak-shaving when fetchers fail)
- ❌ No persistence of realtime quote data (CLAUDE.md:556 hard rule)
- ❌ No new `StockQuote`-like schema model (reuse `StockQuote` via `quote: StockQuote | None`)
- ❌ No `@cache_endpoint` decorator on `list_stocks` (mixes path A/B; manual
  `cached_lookup`/`cached_store` inside the function gives cleaner control
  of cache miss/hit per branch and the `refresh` removal)
- ❌ No `manager.get_realtime_quote` change (single-stock path unchanged)
- ❌ No `refresh` parameter preservation (YAGNI; daily-first-call auto-refresh
  + `include_quote=true` covers the same use cases)
- ❌ No nested/flat schema duplication — `quote: StockQuote | None` nested
  via existing `StockQuote.from_unified_quote()` helper

---

## 8. CLAUDE.md sync

Two updates needed (post-implementation):

1. **Source Tracking section** — replace "`/stocks` 当前响应不暴露 source 字段"
   with "`/stocks` exposes `source` on each list entry: quote fetcher name for
   `include_quote=true`, metadata origin (`persistence`/fetcher) otherwise."

2. **Fetcher overview table** — annotate `AkshareFetcher` and `ZzshareFetcher`
   rows with `get_realtime_quotes(market)` capability (all-market single-call).
   No priority change.

3. **Indicator Computation / Standardized Data Schema sections** — no change.

---

## 9. Migration / rollout

No DB migration. No environment variable changes. Single deploy:

1. Land fetcher ABC + Akshare/Zzshare impl + manager wrapper
2. Land schema + cache + route
3. Run test suite (`pytest -m ""`)
4. Deploy

If any production client is passing `?refresh=true`, they get 422 immediately.
Acceptable per breaking-change note in §2.3.

---

## 10. Out of scope

- HK/US all-market realtime (no upstream source available; would require a
  new fetcher that doesn't exist today)
- WebSocket / SSE push of quote updates
- Snapshot persistence (CLAUDE.md:556 forbids)
- Pagination cursor (offset/limit stays simple; deep-pagination is rare for
  5400-row lists)