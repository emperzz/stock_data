# API Reference

Full per-endpoint reference for the Stock Data Server. All paths are
versioned under `/api/v1/...` except `/healthz` (root-mounted). See the
main [README](README.md) for architecture, data-source routing, and
configuration. An interactive version is served at `/explorer/`.

## API Endpoints

All endpoints are versioned under `/api/v1/...` **except** `/healthz`,
which is mounted at the root (k8s/lb convention). The `/explorer/` UI
and `/control/*` management API are described under [API Explorer](README.md#api-explorer).

### Health Check

```bash
GET /healthz
```

Response (lightweight, default):
```json
{
  "status": "ok",
  "sources": null
}
```

Append `?details=true` to receive per-fetcher circuit-breaker state (a
list of `SourceHealth` objects). When all sources are unavailable the
status field is `"unhealthy"`; when at least one is open/half-open
it's `"degraded"`. The probe enumerates **all** `BaseFetcher` subclasses
(not just registered ones), so missing-config fetchers (Tushare/Zhitu
without their tokens) are surfaced with `available: false` and an
`unavailable_reason` — but only registered fetchers count toward
`ok/degraded/unhealthy`.

---

### Technical Indicators

The server ships with 14 pure-compute technical indicators. They are
attached to the K-line response via `?indicators=...` on
`/stocks/{code}/kline` and never hit the network — they transform the
K-line `DataFrame` in-process.

#### List available indicators

```bash
GET /api/v1/indicators
```

**Response:**
```json
{
  "indicators": [
    {
      "key": "ma",
      "input_shape": "closes",
      "default_options": {"periods": [5, 10, 20, 30, 60], "type": "sma"},
      "output_columns": ["ma5", "ma10", "ma20", "ma30", "ma60"],
      "default_lookback": 60
    },
    {
      "key": "macd",
      "input_shape": "closes",
      "default_options": {"short": 12, "long": 26, "signal": 9},
      "output_columns": ["macd_dif", "macd_dea", "macd_hist"],
      "default_lookback": 87
    },
    {
      "key": "kdj",
      "input_shape": "ohlcv",
      "default_options": {"period": 9, "kPeriod": 3, "dPeriod": 3},
      "output_columns": ["kdj_k", "kdj_d", "kdj_j"],
      "default_lookback": 18
    }
    /* ...11 more... */
  ]
}
```

Use the catalog for capability discovery — AI agents can introspect
what's available without reading source.

#### Attach indicators to K-line

```bash
# Stocks
GET /api/v1/stocks/600519/kline?days=120&indicators=ma,macd,kdj,boll,rsi
# Indices (same query param, same behavior)
GET /api/v1/indices/000300/kline?days=120&indicators=ma,macd,boll
```

**Supported indicators** (with their default `output_columns`):

| Key | Type | Inputs | Output columns | Lookback |
|-----|------|--------|----------------|----------|
| `ma` | SMA/EMA/WMA | closes | `ma5, ma10, ma20, ma30, ma60` | 60 |
| `macd` | 12/26/9 EMA diff | closes | `macd_dif, macd_dea, macd_hist` | 87 |
| `boll` | Bollinger Bands | closes | `boll_mid, boll_upper, boll_lower, boll_bandwidth` | 20 |
| `kdj` | Stochastic | ohlcv | `kdj_k, kdj_d, kdj_j` | 18 |
| `rsi` | Wilder's RSI | closes | `rsi_6, rsi_12, rsi_24` | 48 |
| `wr` | Williams %R | ohlcv | `wr_6, wr_10` | 10 |
| `bias` | 乖离率 | closes | `bias_6, bias_12, bias_24` | 24 |
| `cci` | Commodity Channel | ohlcv | `cci` | 14 |
| `atr` | Average True Range | ohlcv | `atr, tr` | 28 |
| `obv` | On-Balance Volume | ohlcv | `obv, obv_ma` | 1 |
| `roc` | Rate of Change | closes | `roc, roc_signal` | 12 |
| `dmi` | Directional Movement | ohlcv | `dmi_pdi, dmi_mdi, dmi_adx, dmi_adxr` | 56 |
| `sar` | Parabolic SAR | ohlcv | `sar, sar_trend, sar_ep, sar_af` | 5 |
| `kc` | Keltner Channel | ohlcv | `kc_mid, kc_upper, kc_lower, kc_width` | 60 |

**Per-bar `indicators` field** is `null` for any bar where the
indicator is not yet defined (insufficient lookback, NaN in input, or
range collapses to zero). For example, `macd_dif` first appears on
the 26th bar; `macd_dea` (signal line) only after 26+9 bars; `kdj_*`
only after 9 bars.

#### Auto lookback expansion

The server fetches extra K-line bars automatically so the indicators
have enough history to warm up, then truncates the response back to
the `days` you asked for. You don't need to pre-compute a larger
`days` value — just ask for what you want displayed.

**Example**: `?days=30&indicators=macd` triggers an internal fetch of
`max(30, 87) = 87` bars, runs MACD over all 87, then slices the last
30 rows for the response.

> **`days` is a calendar-day window** (no ×2 padding): a request without
> `?indicators=` returns whatever bars fall in the window (~0.7×`days` for
> daily, since weekends/holidays carry no bars). With `?indicators=`, the
> lookback expansion still gives enough bars to warm the indicator and the
> response is truncated back to the last `days` rows.

---

**Parameters:**
| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `period` | string | `daily` | K-line period: `daily`, `weekly`, `monthly` |
| `days` | int | 30 | Calendar-day window — number of days of history to fetch (1-365, ignored when `start_date` provided). Non-trading days are **not** padded: the response contains the bars that fall in the window (~0.7×`days` trading bars for daily). Ask for ~1.4× the bar count you want displayed. |
| `start_date` | string | null | Start date (YYYY-MM-DD), overrides `days` parameter |
| `end_date` | string | null | End date (YYYY-MM-DD), defaults to today |
| `adjust` | string | `` | Adjustment type: empty=不复权, `qfq`=前复权, `hfq`=后复权 |
| `indicators` | string | null | Comma-separated list of technical indicators to attach (see [Technical Indicators](#technical-indicators)) |

**Response (without `indicators`):**
```json
{
  "code": "600519",
  "name": "贵州茅台",
  "period": "daily",
  "data": [
    {
      "date": "2026-05-06",
      "open": 1680.0,
      "high": 1700.0,
      "low": 1670.0,
      "close": 1698.0,
      "volume": 1234567,
      "amount": 2087654321.0,
      "change_pct": 1.52
    }
  ]
}
```

> **Note:** the `indicators` field is **omitted from the response entirely**
> when `?indicators=` is not passed — instead of being present-but-null.
> To get per-bar indicator values, opt in with `?indicators=ma` (or any
> indicator set). `amount` and `change_pct` keep their original
> "null when missing" behavior.

**Response (with `?indicators=ma,macd,kdj,boll`):**
```json
{
  "code": "600519",
  "name": "贵州茅台",
  "period": "daily",
  "data": [
    {
      "date": "2026-05-26",
      "open": 1698.0,
      "high": 1712.0,
      "low": 1695.0,
      "close": 1708.0,
      "volume": 1234567,
      "amount": 2100000000.0,
      "change_pct": 0.59,
      "ma5": 1701.0,
      "ma10": 1695.0,
      "ma20": 1678.0,
      "indicators": {
        "ma5": 1701.0, "ma10": 1695.0, "ma20": 1678.0, "ma30": 1665.0, "ma60": 1640.0,
        "macd_dif": 5.32, "macd_dea": 4.18, "macd_hist": 2.28,
        "kdj_k": 72.5, "kdj_d": 65.1, "kdj_j": 87.3,
        "boll_mid": 1695.0, "boll_upper": 1720.5, "boll_lower": 1669.5, "boll_bandwidth": 3.01
      }
    }
  ]
}
```

The server automatically fetches extra lookback bars when the
indicators need it (e.g. MACD needs ~87 bars to warm up) and then
truncates the response to the `days` you asked for.

---

### Get Historical K-line Data

The `GET /api/v1/stocks/{code}/kline` endpoint is fully documented
under [Technical Indicators](#technical-indicators) above (parameters,
auto-lookback expansion, with- and without-`?indicators=` response
shapes). Omit `?indicators=` to receive the slim per-bar payload shown
in the **Response (without `indicators`)** block; pass
`?indicators=ma,macd,kdj,boll` to attach per-bar values via the
`indicators` dict. The same endpoint serves minute data via
`?period=1m|5m|15m|30m|60m` (the period param replaces the legacy
`/intraday` route, which was removed when the K-line API was unified).

---

### Get Realtime Quote

```bash
GET /api/v1/stocks/{code}/quote
```

**Response:**
```json
{
  "code": "600519",
  "name": "贵州茅台",
  "source": "AkshareFetcher",
  "current_price": 1698.0,
  "change_amount": 25.5,
  "change_pct": 1.52,
  "open": 1680.0,
  "high": 1700.0,
  "low": 1670.0,
  "prev_close": 1672.5,
  "volume": 1234567,
  "amount": 2087654321.0
}
```

**400 contract** (post-2026-07-23): the route raises 400 via
`_reject_invalid_stock_code` (`api/routes/helpers.py`) when
`stock_list.get_stock_name(code)` returns empty. The message branches on
`is_index_code(code)`:

- `True` (code in `CSI_INDEX_MAP`, e.g. `000001`, `000300`):
  `"Index {code} is not supported via this endpoint. Use /indices/{code}/quote instead."` —
  caller likely wanted `/indices/...`; follow the redirect hint.
- `False` (typo / delisted / unknown market tag):
  `"Stock code {code} was not found in the stock list."` —
  genuine not-found; no redirect.

The same contract applies to `/stocks/{code}/kline`. Pinned by
`tests/test_routes.py::TestKline::{test_kline_invalid_stock,test_kline_index_coded_input_redirects_message,test_kline_unknown_code_gets_not_found_message}` (the helper is shared between the two routes).

**Cold-cache note:** the first call after a fresh `stock_list` table (or
`STOCK_DB_INIT=true` reset) may add 1-3 s for a one-shot upstream
`manager.get_all_stocks` warm; subsequent hits use SQLite directly.

---

### Company Profile (公司画像)

```bash
GET /api/v1/stocks/{code}/info
```

A-share only. Fetches rich company profile (industry, listing date,
registered capital, executives, business scope, etc.) via
`STOCK_INFO` capability — Zhitu (P5) → Myquant (P9) failover.
Cached in-process for `CACHE_TTL_STOCK_INFO` (default 3600s).

**Response (excerpt):**
```json
{
  "code": "600519",
  "name": "贵州茅台",
  "exchange": "SH",
  "industry": "白酒",
  "listing_date": "2001-08-27",
  "total_share": 1256000000,
  "float_share": 1256000000,
  "reg_capital": 1256000000,
  "source": "ZhituFetcher"
}
```

`exchange` is `"SH"` / `"SZ"` / `"BJ"` when known (Zhitu / Myquant
populate it) and `null` otherwise (Baostock / Akshare do not).

---

### Get Stock Intraday Data

Minute-level (intraday) data is served via the unified K-line endpoint
with `period=1m|5m|15m|30m|60m`. There is no separate `/intraday` route.

```bash
GET /api/v1/stocks/600519/kline?period=5m
GET /api/v1/indices/000300/kline?period=15m
```

The `period` values `1m/5m/15m/30m/60m` select minute granularity; the
rest of the response shape matches the daily K-line response
(per-bar `time` replaces `date`). `adjust` is accepted but only Akshare
1m rejects it; Zzshare also rejects minute+adjust upstream. A-share
stocks and CSI indices support minute periods; US/HK stocks and US
indices do not.

---

### Per-Stock News Feed

```bash
GET /api/v1/stocks/{code}/news?limit=20
```

**Parameters:**
| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `limit` | int | 20 | Item count (1-100) |

Routed via `STOCK_NEWS` capability. **EastMoney** (P6) np-listapi is
primary (per-stock news feed rendered as "个股资讯" on the EastMoney
quote page); **THS** (P7, news.10jqka timeline API) is the failover.
Cached 60s. Distinct from `/news/search` (which needs a keyword or
中文 stock name); this endpoint takes a 6-digit code directly.

```json
{
  "code": "600519",
  "data": [
    {
      "title": "贵州茅台一季度业绩超预期",
      "url": "https://finance.eastmoney.com/news/...",
      "publish_time": "2026-05-20 09:31:00",
      "source_domain": "finance.eastmoney.com"
    }
  ],
  "total": 20,
  "limit": 20,
  "source": "EastMoneyFetcher"
}
```

---

### Trade Calendar

```bash
GET /api/v1/calendar
GET /api/v1/calendar?refresh=true
```

**Parameters:**
| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `refresh` | bool | `false` | Force fetch latest from upstream |

**Response:**
```json
{
  "trade_dates": ["2026-05-07", "2026-05-08", "2026-05-09", ...],
  "latest_date": "2026-05-09",
  "total": 245
}
```

**Note:** Returns A-share trade calendar. Data is cached in SQLite and refreshed when cache is stale.

---

### Index APIs

Index data is served via dedicated `/indices/` endpoints (separate from stocks).

#### Index Realtime Quote

```bash
GET /api/v1/indices/{index_code}/quote
```

**Response:**
```json
{
  "code": "000300",
  "name": "沪深300",
  "source": "akshare",
  "current_price": 4833.52,
  "change_amount": -26.07,
  "change_pct": -0.536,
  "open": 4836.33,
  "high": 4868.60,
  "low": 4806.15,
  "prev_close": 4859.59,
  "volume": 239077587,
  "amount": 733452822624.0
}
```

#### Index Historical K-line

```bash
GET /api/v1/indices/{index_code}/kline?period=daily&days=30
```

**Parameters:**
| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `period` | string | `daily` | K-line period: `daily`, `weekly`, `monthly` |
| `days` | int | 30 | Calendar-day window — number of days of history to fetch (1-365, ignored when `start_date` provided). Non-trading days are **not** padded (same semantics as `/stocks/{code}/kline`). |
| `start_date` | string | null | Start date (YYYY-MM-DD), overrides `days` |
| `end_date` | string | null | End date (YYYY-MM-DD), defaults to today |
| `indicators` | string | null | Comma-separated list of technical indicators to attach (see [Technical Indicators](#technical-indicators)). Same semantics as `/stocks/{code}/kline`. |

#### Index Intradaday (Minute-Level)

Minute-level data for CSI indices is served via the unified K-line
endpoint with `period=5m|15m|30m|60m` (1m is not supported for indices).

```bash
GET /api/v1/indices/000300/kline?period=5m
```

---

### List All Available Indices

```bash
GET /api/v1/indices
```

**Response:**
```json
[
  {"code": "000300", "name": "沪深300", "market": "csi"},
  {"code": "000001", "name": "上证指数", "market": "csi"},
  {"code": "399001", "name": "深证成指", "market": "csi"},
  {"code": "HSI", "name": "恒生指数", "market": "hk"},
  {"code": "HSCE", "name": "恒生中国企业指数", "market": "hk"},
  {"code": "SPX", "name": "S&P 500", "market": "us"},
  {"code": "DJI", "name": "Dow Jones Industrial Average", "market": "us"},
  {"code": "IXIC", "name": "Nasdaq Composite", "market": "us"}
]
```

**Market values:** `csi` (A股指数), `hk` (港股指数), `us` (美股指数)

---

### List All Stocks (with local cache)

```bash
GET /api/v1/stocks?market=csi
GET /api/v1/stocks?market=csi&refresh=true
GET /api/v1/stocks?market=csi&offset=0&limit=100
```

**Parameters:**
| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `market` | string | Required | Market: `csi` (A股), `hk` (港股), `us` (美股) |
| `refresh` | bool | `false` | If `true`, fetch latest from upstream and update cache |
| `offset` | int | 0 | Pagination offset |
| `limit` | int | 100 | Page size (1-1000) |

> **Note:** A-shares are exposed as `csi`. The legacy `cn` tag is an
> internal fetcher convention and is NOT a valid value here.

**Response:**
```json
[
  {"code": "000001", "name": "平安银行", "market": "csi", "exchange": "SZ"},
  {"code": "000002", "name": "万科A", "market": "csi", "exchange": "SZ"},
  {"code": "600519", "name": "贵州茅台", "market": "csi", "exchange": "SH"}
]
```

`exchange` is `"SH"` / `"SZ"` / `"BJ"` when known, else `null`.

**Caching behavior:**
- First call fetches from upstream (Zzshare primary → Akshare / Zhitu / Myquant fallback; Tushare has no STOCK_LIST capability)
- Subsequent calls return cached data (~50ms)
- Use `refresh=true` to force update from upstream

**Cached data location:** `stock_data/stock_cache.db` (SQLite). Override via `STOCK_CACHE_DB_PATH` environment variable. See [Persistence](README.md#persistence-on-disk-sqlite-store) in the README.

---

### Board Data (Concept / Industry / Index / Special)

Board endpoints are **source-routed** — the `source` query parameter is
**required** and selects the fetcher backend. Different sources use
incompatible board classification systems (EastMoney: concept/industry;
Zhitu: type × subtype), so failover between sources is intentionally
not supported.

**Available source labels (post 2026-07-08 unification):**
- `ths` — ThsFetcher (concept + industry; d/w/m/1m/5m/15m/30m/60m K-line; internally merges ZzshareFetcher for platecode backfill)
- `eastmoney` — EastMoneyFetcher (concept + industry only; no index/special classification upstream; d/w/m/5m/15m/30m/60m K-line, no 1m)
- `zhitu` — ZhituFetcher (concept / industry / index / special; no K-line)

**`zzshare` aliases:**
- `/boards` and `/boards/{code}/stocks` — `zzshare` is **not** a valid
  source label; it returns 422 (was unified under `ths` on 2026-07-08).
  The underlying ZzshareFetcher is still used internally for
  platecode backfill on `?source=ths` board-list and as primary
  `include_quote=false` fallback on `/boards/{code}/stocks`.
- `/stocks/{code}/boards` — `zzshare` is accepted as alias for `ths`
  (THS basic API is the shared upstream).
- `/boards/{code}/history` — `zzshare` is accepted and aliased to
  `ths` (ZzshareFetcher has no K-line implementation; upstream
  `plate_kline` only supports 883957 同花顺全A).

```bash
# Board list (concept / industry / index / special)
GET /api/v1/boards?type=concept&source=ths
GET /api/v1/boards?type=industry&source=eastmoney&include_quote=true
GET /api/v1/boards?type=industry&source=zhitu&subtype=申万行业
GET /api/v1/boards?type=concept&source=ths&subtype=同花顺概念

# Board stocks
GET /api/v1/boards/BK1048/stocks?source=eastmoney
GET /api/v1/boards/BK1048/stocks?source=ths&include_quote=true

# Stock → boards mapping (multi-source; default = all valid sources)
GET /api/v1/stocks/000001/boards?source=ths
GET /api/v1/stocks/000001/boards?source=zhitu&type=concept&subtype=热门概念
GET /api/v1/stocks/000001/boards?source=ths,eastmoney,zhitu   # multi-source aggregation

# Board K-line (THS: 8 frequencies, board_type required; EastMoney: 7 frequencies, no 1m)
GET /api/v1/boards/BK1048/history?source=eastmoney&frequency=d
GET /api/v1/boards/881270/history?source=ths&frequency=1m&board_type=industry
```

**Parameters for `GET /boards`:**
| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `type` | string | null (all) | Board type: `concept`, `industry`, `index`, `special`. Omit to query every type the source exposes (fan-out internally). Per-source coverage: `ths` supports `concept`+`industry` only (code prefix `885xxx`/`881xxx`); `eastmoney` supports `concept`+`industry` only (no index/special upstream); `zhitu` supports all 4 types. `?type=index`/`?type=special` returns 400 on `source=ths` or `source=eastmoney`. |
| `source` | string | Required | Data source: `ths`, `eastmoney`, or `zhitu` |
| `subtype` | string | null | Source-specific subtype (e.g. `申万行业` for zhitu). Validated per (source, type) pair. |
| `include_quote` | bool | `false` | Include realtime price/change/market data (EastMoney only; ThsFetcher + Zhitu ignore) |
| `sort_by` | string | null | Sort by: `change_pct`, `volume`, `amount`, `price` (requires `include_quote=true`) |
| `sort_order` | string | `desc` | Sort order: `asc` or `desc` |
| `limit` | int | null | Max items (1-500) |
| `refresh` | bool | `false` | Force fetch latest from upstream |

**Board type coverage by source:**

| Type | `ths` | `eastmoney` | `zhitu` |
|---|---|---|---|
| `concept` | ✅ `同花顺概念` / `同花顺题材` | ✅ `concept` | ✅ `热门概念` / `概念板块` / `地域板块` |
| `industry` | ✅ `同花顺行业` | ✅ `industry` | ✅ `申万行业` / `申万二级` / `证监会行业` |
| `index` | ❌ | ❌ | ✅ `分类` / `指数成分` / `大盘指数` |
| `special` | ❌ | ❌ | ✅ `风险警示` / `次新股` / `沪港通` / `深港通` |

**Response (with `include_quote=false`, default):**
```json
{
  "source": "ths",
  "data": [
    {"code": "301558", "name": "互联网服务", "type": "concept", "subtype": "同花顺概念"},
    {"code": "881270", "name": "白酒", "type": "industry", "subtype": "同花顺行业"}
  ]
}
```

`source` here is the **actual origin** (fetcher name on cache miss;
`"persistence"` on cache hit). It does not always equal the user-supplied
`source` query param — `source=ths` board-list internally merges THS
+ ZzshareFetcher platecode backfill but the public surface tags both
as `source="ths"`.

**Response (with `include_quote=true`):**
```json
{
  "source": "EastMoneyFetcher",
  "data": [
    {
      "code": "BK1048",
      "name": "互联网服务",
      "type": "concept",
      "price": 1850.5,
      "change_pct": 2.35,
      "change_amount": 42.3,
      "volume": 52000000,
      "amount": 95800000000.0,
      "turnover_pct": 3.58,
      "total_mv": 2345000000000.0,
      "up_count": 45,
      "down_count": 12,
      "leading_stock": "科大讯飞",
      "leading_stock_pct": 8.5
    }
  ]
}
```

**Parameters for `GET /boards/{board_code}/stocks`:**
| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `source` | string | Required | Data source: `ths`, `eastmoney`, or `zhitu`. `?source=zzshare` returns 422. |
| `include_quote` | bool | `false` | Include realtime quote fields (THS populates by default; EastMoney requires `true`; Zzshare/Zhitu emit no quote fields — affected fields are `null`, not omitted) |
| `refresh` | bool | `false` | Force fetch latest from upstream |

This endpoint returns three source fields:
- `query_source` — the user-supplied `?source=` value (canonicalized)
- `data_source` — the fetcher label on cache miss or `"persistence"` on cache hit
- `effective_source` — the fetcher that actually served the upstream call;
  on a persistence hit this is the unified cache-key label (currently `"ths"`)

**Parameters for `GET /stocks/{stock_code}/boards`:**
| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `source` | string | null (all) | Comma-separated sources (`ths,eastmoney,zhitu`). `zzshare` is accepted as alias for `ths`. Omit for all valid sources. |
| `type` | string | null | Filter by board type |
| `subtype` | string | null | Filter by source-specific subtype |

Multi-source aggregation: the response `source` field is `"merged"`
when more than one source is requested; the `cold_sources` array lists
sources with no cached data (the caller can decide whether to retry
against those sources — removed 2026-07-10; reverse lookup relies on
startup backfill or returns `cold_sources` on miss).

**Parameters for `GET /boards/{board_code}/history`:**
| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `source` | string | Required | Data source: `ths` (d/w/m/1m/5m/15m/30m/60m) or `eastmoney` (d/w/m/5m/15m/30m/60m; no 1m). `zzshare` is accepted and aliased to `ths`. |
| `frequency` | string | `d` | K-line frequency. Validated against the selected source: THS supports all 8 listed frequencies; EastMoney supports the same set except `1m`. |
| `start_date` | string | null | Start date (YYYY-MM-DD). Range width is capped at 800 days; exceeds → 400 `date_range_too_wide`. |
| `end_date` | string | null | End date (YYYY-MM-DD). Defaults to today. |
| `days` | int | 30 | Days (used when `start_date` is not given). 1-800. |
| `board_type` | string | null | **Required** when `source=ths` (`concept` or `industry` — ThsFetcher uses two incompatible code systems; 422 if missing). Ignored for `eastmoney`. |

**Source-specific subtype values:**

`ths`:
| Type | Valid subtypes |
|------|---------------|
| `concept` | `同花顺概念`, `同花顺题材` (zzshare plate=17 题材 folded into concept with subtype preserved) |
| `industry` | `同花顺行业` |

`eastmoney`:
| Type | Valid subtypes |
|------|---------------|
| `concept` | `concept` (mirror of type) |
| `industry` | `industry` (mirror of type) |
| `index` | **not supported** — returns 400 |
| `special` | **not supported** — returns 400 |

`zhitu`:
| Type | Valid subtypes |
|------|---------------|
| `industry` | `申万行业`, `申万二级`, `证监会行业` |
| `concept` | `热门概念`, `概念板块`, `地域板块` |
| `index` | `分类`, `指数成分`, `大盘指数` |
| `special` | `风险警示`, `次新股`, `沪港通`, `深港通` |

**Caching behavior for board endpoints:**
- Results are cached in `stock_data/stock_cache.db` (SQLite), keyed by
  `(board_type, source)` with optional `subtype`.
- `include_quote=true` fetches fresh data from upstream AND updates cache.
- `refresh=true` forces upstream fetch and updates cache.
- First call of each day triggers a refresh from upstream (cold path
  → upstream call → upsert; warm path → cache hit returns
  `source="persistence"`).

---

### Board Realtime Quote (板块实时行情)

```bash
GET /api/v1/boards/{board_code}/quote
```

THS only (`get_board_realtime`, q.10jqka concept page). No `?source=`
param — the only implementation is hard-coded. `board_type` is resolved
from the SQLite board cache; a cache miss returns `422 board_type_unresolved`
(run a board-list refresh first).

```json
{
  "code": "885595",
  "board_name": "互联网服务",
  "source": "ths",
  "price": 1850.5, "change_pct": 2.35, "change_amount": 42.3,
  "open": 1810.0, "high": 1860.0, "low": 1805.0, "prev_close": 1808.2,
  "volume": 52000000, "amount": 95800000000.0,
  "net_inflow": 1500000000.0, "up_count": 45, "down_count": 12, "rank": 3
}
```

---

### Board News (板块新闻)

```bash
GET /api/v1/boards/{board_code}/news?limit=20
```

Routed via `BOARD_NEWS` capability. **THS only** (v1) — news.10jqka
timeline API (`marketId=48`); `?source=` defaults to `ths`, any other
value → 422. Cursor-paginated (no 14-item cap), items carry a `summary`.

**Parameters:** `limit` (int, default 20, 1-50), `source` (`ths`, default).

```json
{
  "code": "885914",
  "source": "ths",
  "total": 20,
  "data": [
    {
      "title": "煤炭板块异动拉升",
      "url": "https://news.10jqka.com.cn/...",
      "publish_date": "2026-07-20",
      "publish_time": "09:41",
      "summary": "...",
      "source_domain": "news.10jqka.com.cn"
    }
  ]
}
```

---

### Board Surge Cycles (板块炒作周期)

```bash
GET /api/v1/boards/{board_code}/surges?limit=5
```

Routed via `BOARD_SURGES` capability. **THS only** (v1) — F10 `#period`
section (peak speculation cycles). `?source=` defaults to `ths`, any
other value → 422.

**Parameters:** `limit` (int, default 5, 1-12), `source` (`ths`, default).

```json
{
  "code": "885914",
  "source": "ths",
  "total": 5,
  "data": [
    {
      "date": "2026-07-18",
      "board_change_pct": 6.2,
      "sh_change_pct": 0.8,
      "limit_up_count": 4,
      "limit_up_stocks": ["601001", "600188"],
      "up_count": null,
      "down_count": null
    }
  ]
}
```

---

### 涨跌停股池 (ZT / DT / ZBGC Pool)

```bash
GET /api/v1/zt-pools?type=zt&date=2026-05-20
```

Routed via `STOCK_ZT_POOL` capability. Cached in SQLite (except the
current trading day, which is volatile and TTLCache-only).

**Parameters:**
| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `type` | string | required | `zt` (涨停) / `dt` (跌停) / `zbgc` (炸板) |
| `date` | string | null | `YYYY-MM-DD`; defaults to today (or latest trade date ≤ today) |
| `refresh` | bool | `false` | Force upstream refresh (write skipped for the current trading day) |

```json
{
  "date": "2026-05-20",
  "type": "zt",
  "total": 68,
  "stocks": [
    {
      "code": "601001", "name": "晋控煤业", "price": 12.5, "change_pct": 10.02,
      "amount": 850000000.0, "circ_mv": 21000000000.0, "total_mv": 21000000000.0,
      "turnover_pct": 4.1, "lb_count": 2, "first_seal_time": "09:41",
      "last_seal_time": "10:15", "seal_amount": 120000000.0,
      "seal_count": 3, "zt_count": 1
    }
  ],
  "source": "persistence"
}
```

---

### Quote Enhancement (PE/PB/Market Cap)

The `/quote` endpoint now returns enhanced valuation fields:

```json
{
  "code": "600519",
  "name": "贵州茅台",
  "current_price": 1698.0,
  "pe_ttm": 28.5,
  "pe_static": null,
  "pb": 8.2,
  "mcap_yi": 2350.0,
  "float_mcap_yi": 2340.0,
  "turnover_pct": 0.85,
  "amplitude_pct": 2.75,
  "limit_up": null,
  "limit_down": null,
  "volume_ratio": 1.2
}
```

> `limit_up` / `limit_down` 由 ZzshareFetcher (`rt_k` `high_limit` / `low_limit`) 和 TencentFetcher (qt.gtimg.cn 字段 47/48) 提供；Akshare / Zhitu / Yfinance / Tushare / Myquant 上游不暴露这两个字段，返回 `null`。详见 schema `StockQuote` (post 2026-07-30, commit b878841)。

---

### Margin Trading (融资融券)

```bash
GET /api/v1/stocks/{code}/margin?page_size=30
```

**Response:**
```json
{
  "code": "600519",
  "name": "贵州茅台",
  "records": [
    {
      "date": "2026-05-20",
      "rzye": 12000000000.0,
      "rzmre": 500000000.0,
      "rzche": 300000000.0,
      "rqye": 200000000.0,
      "rqmcl": 50000,
      "rqchl": 30000,
      "rzrqye": 12200000000.0
    }
  ],
  "source": "eastmoney"
}
```

---

### Block Trade (大宗交易)

```bash
GET /api/v1/stocks/{code}/block-trade?page_size=20
```

```json
{
  "code": "600519",
  "records": [
    {
      "date": "2026-05-20",
      "price": 100.0,
      "close": 98.0,
      "premium_pct": 2.04,
      "vol": 50000,
      "amount": 5000000,
      "buyer": "机构专用",
      "seller": "中信证券"
    }
  ],
  "source": "eastmoney"
}
```

---

### Shareholder Count (股东户数变化)

```bash
GET /api/v1/stocks/{code}/holder-num?page_size=10
```

```json
{
  "code": "600519",
  "records": [
    {
      "date": "2026-03-31",
      "holder_num": 150000,
      "change_num": -5000,
      "change_ratio": -3.2,
      "avg_shares": 8000.0
    }
  ],
  "source": "eastmoney"
}
```

---

### Dividend History (分红送转)

```bash
GET /api/v1/stocks/{code}/dividend?page_size=20
```

```json
{
  "code": "600519",
  "records": [
    {
      "date": "2025-06-19",
      "bonus_rmb": 21.91,
      "transfer_ratio": 0,
      "bonus_ratio": 0,
      "plan": "实施完成"
    }
  ],
  "source": "eastmoney"
}
```

---

### Dragon Tiger Board (龙虎榜)

**个股龙虎榜:**
```bash
GET /api/v1/stocks/{code}/dragon-tiger?trade_date=2026-05-20
```

```json
{
  "code": "002475",
  "name": "立讯精密",
  "records": [
    {"date": "2026-05-20", "reason": "日涨幅偏离值达7%", "net_buy_wan": 15230.5, "turnover_pct": 5.2}
  ],
  "seats": {
    "buy": [{"name": "机构专用", "buy_wan": 8900.0, "sell_wan": 1200.0, "net_wan": 7700.0}],
    "sell": [{"name": "中信证券", "buy_wan": 500.0, "sell_wan": 4500.0, "net_wan": -4000.0}]
  },
  "institution": {"buy_wan": 8900.0, "sell_wan": 600.0, "net_wan": 8300.0},
  "source": "eastmoney"
}
```

> 单日查询:`records` 最多包含一条对应 `trade_date` 的上榜记录;不传 `trade_date` 时默认查询最新一个交易日。

**全市场龙虎榜:**
```bash
GET /api/v1/dragon-tiger?trade_date=2026-05-20&min_net_buy=5000
```

---

### Fund Flow (资金流)

**分钟级实时:**
```bash
GET /api/v1/stocks/{code}/fund-flow
```

**120日历史:**
```bash
GET /api/v1/stocks/{code}/fund-flow/daily
```

```json
{
  "code": "600519",
  "type": "daily",
  "records": [
    {
      "date": "2026-05-20",
      "main_net": 5000000,
      "small_net": -1000000,
      "mid_net": 2000000,
      "large_net": 3000000,
      "super_net": -500000
    }
  ],
  "source": "eastmoney"
}
```

---

### Hot Topics (热点题材)

```bash
GET /api/v1/hot-topics?date=2026-05-20
```

```json
{
  "date": "2026-05-20",
  "total": 125,
  "topics": [
    {
      "code": "688017",
      "name": "绿的谐波",
      "reason": "人形机器人+减速器+特斯拉",
      "change_pct": 12.5,
      "turnover_pct": 8.3,
      "amount": 5000000000.0,
      "dde_net": 1500.0
    }
  ],
  "source": "ths"
}
```

---

### North-bound Flow (北向资金)

```bash
GET /api/v1/north-flow/realtime
```

```json
{
  "records": [
    {"time": "09:30", "hgt_yi": 0.5, "sgt_yi": 0.3},
    {"time": "09:31", "hgt_yi": 0.7, "sgt_yi": 0.4}
  ],
  "source": "ths"
}
```

---

### Research Reports (研报)

```bash
GET /api/v1/stocks/{code}/reports?max_pages=3
GET /api/v1/stocks/{code}/reports/{report_id}/pdf
```

```json
{
  "code": "688017",
  "name": "绿的谐波",
  "reports": [
    {
      "title": "绿的谐波深度报告",
      "publish_date": "2026-05-15",
      "org": "中信证券",
      "info_code": "ABC123",
      "rating": "买入",
      "predict_eps_this": 3.5,
      "predict_eps_next": 5.2,
      "predict_eps_next2": 7.1
    }
  ],
  "total": 45,
  "source": "eastmoney"
}
```

---

### Corporate Announcements (公告)

```bash
GET /api/v1/stocks/{code}/announcements?page_size=30
```

```json
{
  "code": "688017",
  "name": "绿的谐波",
  "announcements": [
    {
      "title": "2025年年度报告",
      "type": "年报",
      "date": "2026-03-31",
      "url": "https://www.cninfo.com.cn/new/disclosure/detail?annoId=..."
    }
  ],
  "total": 30,
  "source": "cninfo"
}
```

---

### News Search (关键词 / 股票代码 / 主题)

```bash
GET /api/v1/news/search?q=茅台&from=2026-05-01&to=2026-05-20&limit=20
```

**Parameters:**
| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `q` | string | required | Search query (1-200 chars, Chinese supported) |
| `from` | string | null | Start date `YYYY-MM-DD` |
| `to` | string | null | End date `YYYY-MM-DD` |
| `limit` | int | 20 | Result count (1-100) |

Routed via `NEWS_SEARCH` capability. **EastMoney** (P6) is primary;
**ThsFetcher** (P7) and **BaiduFetcher** (P7, requires `BAIDU_API_KEY`) are
the failovers. All three sources are restricted to canonical news
subdomains (`finance.eastmoney.com`, `www.cls.cn`, `news.10jqka.com.cn`);
Baidu also honors `BAIDU_NEWS_DOMAINS` overrides.

```json
{
  "data": [
    {
      "title": "贵州茅台一季度营收...",
      "url": "https://finance.eastmoney.com/news/...",
      "publish_date": "2026-05-15",
      "source_domain": "finance.eastmoney.com",
      "summary": "..."
    }
  ],
  "total": 20,
  "limit": 20,
  "query": "茅台",
  "source": "EastMoneyFetcher"
}
```

### Flash News (全球财经 7×24 实时推送)

```bash
GET /api/v1/news/flash?limit=50
```

**Parameters:**
| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `limit` | int | 50 | Item count (1-200) |

Routed via `NEWS_FLASH` capability. **EastMoney** (P6) is primary,
**THS** (P7) is the failover. Cached 60s. `code` in each item is the
**article ID**, not the stock code.

```json
{
  "data": [
    {
      "title": "央行宣布降准0.5个百分点",
      "publish_time": "2026-05-20 09:31:00",
      "url": "https://finance.eastmoney.com/news/...",
      "code": "202605200931000123",
      "source_domain": "finance.eastmoney.com"
    }
  ],
  "total": 50,
  "limit": 50,
  "source": "EastMoneyFetcher"
}
```

### News Content (URL → 正文)

```bash
GET /api/v1/news/content?url=https://finance.eastmoney.com/news/...
```

Given a news detail-page URL, fetches and extracts the article body.
Pure utility endpoint (no fetcher routing). URL is rejected when it
points at internal networks (`127.0.0.1`, `10.0.0.0/8`, etc.).

```json
{
  "url": "https://finance.eastmoney.com/news/...",
  "title": "贵州茅台一季度营收...",
  "body": "...",
  "publish_date": "2026-05-15T08:00:00",
  "author": "财经早知道",
  "source_domain": "finance.eastmoney.com",
  "extractor": "default",
  "byte_size": 4321,
  "content_status": "ok",
  "reason": null,
  "canonical_url": "https://finance.eastmoney.com/news/...",
  "http_status": 200
}
```

---

### 财联社早报 / 焦点复盘 (CLS Morning Briefing / Market Recap)

Two date-keyed full-text feeds scraped from 财联社 (CLS) via
`__NEXT_DATA__` JSON extraction (subject 1151 = 早报, subject 1135 = 焦点复盘).
Backed by `ClsFetcher` (P8) — not configurable with a `?source=` parameter
(no other fetcher exposes this content).

**Important — date window:** both endpoints accept dates within the past
**28 days only**. CLS list page returns ~20-28 most recent articles; older
dates return `404 No article published for this date`. The `date` param is
required and validated against Asia/Shanghai server time (so a UTC server
between 16:00–23:59 still accepts "today" for a BJT-located caller).

```bash
GET /api/v1/news/morning-briefing?date=2026-07-14
GET /api/v1/news/market-recap?date=2026-07-14
```

**Parameters:**
| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `date` | string | required | Article date `YYYY-MM-DD` (within last 28 days; not in the future). |

**Response (200):**
```json
{
  "subject": "morning_briefing",
  "subject_id": 1151,
  "date": "2026-07-14",
  "article": {
    "article_id": 1842356,
    "title": "财联社7月14日早报",
    "brief": "今日市场重点关注：...",
    "author": "财联社编辑部",
    "date": "2026-07-14",
    "ctime": 1752441600,
    "read_num": 25431,
    "comments_num": 0,
    "share_num": 87,
    "images": ["https://..."],
    "body_text": "【今日头条】\n...\n【行业动态】\n..."
  },
  "source": "cls"
}
```

- `body_text` is BS4-extracted plain text with paragraph breaks preserved
  (`get_text("\n", strip=True)` + 折叠连续 3+ 空行 → 2 个).
- `source` is the fetcher slug (`"cls"`); capability-routed failover means a
  future second provider (e.g. EastMoney) joining the chain will surface
  its slug here.
- Cached in-process for 3600s (`get_cls_feed_cache()`).

**Errors:**
- `400 Invalid date` — bad format / future date / older than 28 days.
- `404 No article published for this date` — date within window but CLS
  didn't publish that day.
- `503 All fetchers failed` — upstream 4xx/5xx or network failure.

Subject ids are imported from `stock_data.data_provider.fetchers.cls_fetcher`
(`CLS_SUBJECT_MORNING_BRIEFING = 1151`, `CLS_SUBJECT_MARKET_RECAP = 1135`,
probed 2026-07-14); if CLS rotates these the manifest will surface drift
via the `subject_id mismatch` warning before the article body.

---

## Agent Batch API

All routes in this section live under `/api/v1/agent/*`
(`stock_data/api/routes/agent.py`, plus `agent_correlation.py` for the
correlation matrix endpoint). They are server-side aggregations: the
typical AI-agent flow of "fetch N boards, pairwise compute intersection,
summarize" is folded into one request. Seven endpoints ship in v1:

| Endpoint | Method | Purpose |
|---|---|---|
| `/agent/boards/stock-overlap` | POST | Pairwise stock-set intersection + Jaccard across 2-10 boards |
| `/agent/stocks/board-overlap` | POST | Pairwise board-set intersection + Jaccard across 2-10 stocks |
| `/agent/boards/filter-stocks` | POST | Server-side numeric filter on a board's constituents |
| `/agent/indices/batch-profile` | GET | Per-index quote + 5m/d/w K-line (3 default CSI indices) |
| `/agent/market-context` | GET | Morning briefing + market recap + flash + zt/dt + dragon-tiger |
| `/agent/stocks/batch-profile` | POST | Per-stock fan-out across quote / kline / info / boards (1-5 codes) |
| `/agent/correlation/matrix` | POST | Pairwise Pearson + Spearman correlation matrix across 2-10 stocks/boards (A-share only) |

**Common contract:**

- **Per-item error isolation.** One upstream `DataFetchError` / `ValueError`
  on a single code is recorded in the response `errors[]` array; the
  remaining items still complete. The route never aborts the whole
  response on a single failure.
- **60s in-memory cache.** Cached under the existing `get_quote_cache`
  (reused as a generic 60s TTLCache slot for agent results). The
  `filter-stocks` cache key also includes `limit`, because `limit` is
  forwarded to upstream `get_board_stocks(..., top_n=limit)`. The
  `market-context` cache key also includes `session`
  (`pre-market` / `intraday` / `post-market` / `closed`) — without
  it, a 09:00 pre-market cache hit would mask a 16:00 post-market
  refresh.
- **No LLM judgment.** These endpoints emit only numeric / set-arithmetic
  facts. "Which stock is the leader" / "Which board is the better pick"
  remains the agent's job via `skills/market-principles.md`.
- **Capability-free.** Routes are decorated with
  `@endpoint_meta(capabilities=[])` — they don't map to a single
  `DataCapability` flag.

**`?format=json|md` projection:**

All 7 endpoints accept an optional `?format` query parameter:

| Value | Content-Type | Use case |
|---|---|---|
| `json` (default) | `application/json` | Programmatic clients, JSON pipelines |
| `md` | `text/markdown; charset=utf-8` | LLM agents (lower token cost; native in training data) |

The MD projection renders the Pydantic response to a stable markdown
layout (tables + headings + bullet lists). No data is dropped — every
JSON field appears in the MD output (e.g. the `matched_stocks` table
on `filter-stocks` carries all 16 fields; the `dragon_tiger.stocks`
list on `market-context` shows the full table alongside the top-10
summary). Pinned by
`tests/test_agent_endpoints.py::TestFormatMdDataCompleteness` (7 tests).

**Cache + format interaction:** the cache is **format-agnostic** — the
same Pydantic model serves both `?format=json` and `?format=md`. A
single body hashes to one cache entry; the dispatch happens at the
response layer.

**MD render failure → JSON fallback:** if a per-endpoint template
raises (e.g. an unexpected field shape), the helper returns the
original JSON payload as `application/json` plus an
`X-MD-Render-Error: <ExceptionClassName>: <message>` header. The
client always gets data, just not in their preferred format.

---

### POST /api/v1/agent/boards/stock-overlap

Pairwise intersection + Jaccard of the stock sets belonging to 2-10
boards. Use case: "given 2-10 candidate boards, which stocks appear in
more than one?".

```bash
POST /api/v1/agent/boards/stock-overlap
Content-Type: application/json
```

**Request body:**

| Field | Type | Required | Description |
|---|---|---|---|
| `codes` | string[] | yes | 2-10 board codes (THS platecode — `885xxx` concept, `881xxx` industry). |

**Response (200):**

```json
{
  "sets": [
    {"code": "885595", "count": 87, "source": "ths"},
    {"code": "881270", "count": 12, "source": "ths"}
  ],
  "pairs": [
    {
      "a": "881270",
      "b": "885595",
      "intersection": ["000568", "600519"],
      "intersection_count": 2,
      "jaccard": 0.0206
    }
  ],
  "errors": []
}
```

| Field | Type | Description |
|---|---|---|
| `sets[].code` | string | The board code. |
| `sets[].count` | int | Number of stocks in the board's set (post-dedupe). |
| `sets[].source` | string | `effective_source` (the fetcher that actually served the upstream call). On a persistence hit this is the cache-key label (`"ths"`). |
| `pairs[].a` / `pairs[].b` | string | The two board codes (alphabetical, `a < b`). |
| `pairs[].intersection` | string[] | Stock codes appearing in both sets, sorted ascending. |
| `pairs[].intersection_count` | int | `len(intersection)`. |
| `pairs[].jaccard` | float | `|A ∩ B| / |A ∪ B|`. `0.0` when union is empty. |
| `errors[]` | object[] | Per-code failure records. Empty on success. |

**Error record shape:** `{"code": "<board_code>", "error": "<ExceptionClassName>", "message": "<str>"}`.

**Errors:**

- `400 invalid_request` — empty `codes` / > 10 codes / non-string items.
- `503 board_unavailable` — every board in `codes` failed (no successful
  set to compare); partial failures are still in `errors[]` with HTTP 200.
- `422 cid_unresolved` — returned by the shared `get_board_stocks`
  helper when the THS platecode→cid index is cold; the route propagates
  this as 422, not a misleading 200 with empty `matched_stocks`.

**Cache:** `make_boards_overlap_cache_key(sorted(codes))` →
`agent_boards_stock_overlap:<sorted_codes>`. Same key across `?include_quote=`
variants (always fetches with `include_quote=False`).

---

### POST /api/v1/agent/stocks/board-overlap

Pairwise intersection + Jaccard of the board sets each of 2-10 stocks
belongs to. Use case: "given 2-10 candidate stocks, do they share
sector/board affinity?".

```bash
POST /api/v1/agent/stocks/board-overlap
Content-Type: application/json
```

**Request body:**

| Field | Type | Required | Description |
|---|---|---|---|
| `codes` | string[] | yes | 2-10 stock codes (bare 6-digit A-share). |

**Response (200):**

```json
{
  "sets": [
    {
      "code": "600519",
      "boards": [
        {"code": "885595", "name": "白酒", "type": "industry", "subtype": "同花顺行业", "source": "ths"}
      ]
    }
  ],
  "pairs": [
    {
      "a": "000858",
      "b": "600519",
      "common_boards": [
        {"code": "881270", "name": "白酒", "type": "industry", "subtype": "同花顺行业", "source": "ths"}
      ],
      "intersection_count": 1,
      "jaccard": 0.5
    }
  ],
  "errors": []
}
```

| Field | Type | Description |
|---|---|---|
| `sets[].code` | string | The stock code. |
| `sets[].boards[]` | object[] | `{code, name, type, subtype, source}` — the stock's full board membership as returned by the persistence layer. |
| `pairs[].a` / `pairs[].b` | string | The two stock codes (alphabetical). |
| `pairs[].common_boards` | object[] | Boards that both stocks belong to (deduped by `(code, name)`, sorted by code). |
| `pairs[].intersection_count` | int | `len(common_boards)`. |
| `pairs[].jaccard` | float | `|A ∩ B| / |A ∪ B|`. |
| `errors[]` | object[] | Per-stock failure records. |

**Cache:** `make_stocks_board_overlap_cache_key(sorted(codes))` →
`agent_stocks_board_overlap:<sorted_codes>`. Internal `get_stock_memberships`
call hard-codes `sources=['ths']` (the documented default for agent
inference per spec §3.2.5).

---

### POST /api/v1/agent/boards/filter-stocks

Server-side numeric filter on a board's constituent stocks. Use case:
"given board X, return members passing turnover / change / amount /
mcap / max-gain thresholds" — the server runs the filter, so the agent
doesn't have to fetch and re-parse the full list itself.

```bash
POST /api/v1/agent/boards/filter-stocks
Content-Type: application/json
```

**Request body:**

| Field | Type | Required | Description |
|---|---|---|---|
| `board_code` | string | yes | THS platecode (`885xxx` / `881xxx`). |
| `source` | string | yes | Data source: `ths` (recommended), `eastmoney`, or `zhitu`. `zzshare` returns 422. |
| `filters.turnover_pct` | `{min?, max?}` | no | Range filter on turnover rate (%). |
| `filters.change_pct` | `{min?, max?}` | no | Range filter on change percent (%). |
| `filters.amount_yi` | `{min?, max?}` | no | Range filter on traded amount in **亿元**. |
| `filters.mcap_yi` | `{min?, max?}` | no | Range filter on total market cap in **亿元**. |
| `filters.max_gain_pct` | `{min?, max?}` | no | Range filter on `(high - open) / open * 100`. |
| `limit` | int | no | Max rows to return (also forwarded as upstream `top_n`; default 50, THS upstream hard cap). |

**Range semantics:**

- `min` / `max` are both optional; `{min: 5.0}` is a one-sided lower bound.
- A constituent row with `value=None` is **excluded** when the corresponding
  range is set, **included** when the range is absent. (Pinned by
  `tests/test_agent_endpoints.py::TestFilterStocks::test_filter_excludes_row_when_value_is_none`.)
- An empty `filters` object returns all constituents (subject to `limit`).

**Response (200):**

```json
{
  "code": "885595",
  "board_name": "白酒",
  "filters_applied": {"turnover_pct": {"min": 5.0, "max": 20.0}, "change_pct": {"min": 0.0}},
  "matched_stocks": [
    {
      "code": "000568",
      "name": "泸州老窖",
      "price": 178.5,
      "change_pct": 1.23,
      "max_gain_pct": 2.11,
      "turnover_pct": 7.4,
      "amount_yi": 12.3,
      "mcap_yi": 2610.0,
      "change_amount": 2.16,
      "volume": 1234567,
      "volume_ratio": 1.4,
      "pe_ratio": 25.8,
      "open": 176.0,
      "high": 179.2,
      "low": 175.5,
      "prev_close": 176.3,
      "amplitude_pct": 2.1
    }
  ],
  "summary": {
    "total_in_board": 87,
    "matched": 1,
    "limit_applied": true
  }
}
```

> v2 union fillup (post 2026-07-30, commit 4e6a570) 在 THS top-50 行上也补齐 `open`/`high`/`prev_close`/`volume`，所以 `max_gain_pct` 过滤会对**全部**行生效（之前仅对 suffix 行生效——top-50 行的 None 值会被 `_passes_range` 剔除）。`change_amount` / `volume_ratio` / `pe_ratio` / `amplitude_pct` 为新增可读字段；`total_mv` 仍是 THS-only（suffix 行 `mcap_yi=None` 仍会触发任何 `mcap_yi` 过滤剔除）。

| Field | Type | Description |
|---|---|---|
| `board_code` / `board_name` | string | The board; `board_name` is best-effort (cache miss ⇒ fallback to the code). |
| `filters_applied` | object | Echo of the request `filters`. |
| `matched_stocks[]` | object[] | Sorted by `max_gain_pct desc, turnover_pct desc`; truncated to `limit` if set. |
| `summary.total_in_board` | int | The board's total membership (best-effort; equals `len(stocks)` when the THS 50-row heuristic didn't fire). |
| `summary.matched` | int | `len(matched_stocks)`. |
| `summary.limit_applied` | bool | `true` if `limit` was set; otherwise `false` (the cache hit does not retroactively re-truncate). |

**Sort order:** `(max_gain_pct desc, turnover_pct desc)`. `None` values
sort to the bottom (treated as `-inf` for both keys).

**Errors:**

- `400 invalid_request` — missing `board_code` / `source` / `filters`,
  or `limit` outside [1, 500].
- `503 board_unavailable` — upstream `get_board_stocks` raised
  `DataFetchError` or `ValueError` (e.g. THS 50-row login wall, network
  failure, source-routed fetcher outage). `board_unavailable` is **not**
  silently swallowed as "0 matches".
- `422 cid_unresolved` — THS platecode→cid index is cold; the
  persistence helper cannot dispatch. Run a board-list refresh
  (`GET /boards?source=ths`) before retrying. (Pinned by
  `test_cid_unresolved_returns_422`.)

**Caching — important:** `make_filter_stocks_cache_key(board_code, source, filters, limit)`
hashes `{filters, limit}` together. Two requests with identical
board/source/filters but **different `limit`** use **different cache
entries** and trigger **separate upstream `top_n` fetches**. The cached
value stores the upstream-bounded (un-truncated) result; the response
path applies `limit` on the way out. This is required for correctness
when `limit` is forwarded as upstream `top_n` — do not collapse
`filter-stocks` and `boards/stock-overlap` into a single cache key
namespace.

---

### GET /api/v1/agent/indices/batch-profile

Per-index fan-out: realtime quote + 5m / d / w K-line. Use case: "give
me a one-call snapshot of the major CSI indices for the market-recap
'指数全景' step".

```bash
GET /api/v1/agent/indices/batch-profile
GET /api/v1/agent/indices/batch-profile?codes=000001,000300
```

**Parameters:**

| Parameter | Type | Default | Description |
|---|---|---|---|
| `codes` | string | `000001,399001,399006` | Comma-separated CSI index codes. Empty = the 3 core indices (上证 / 深证 / 创业板). |
| `format` | string | `json` | `json` (default) or `md` — see [`?format=json|md` projection](#agent-batch-api). |

**Response (200):**

```json
{
  "indices": [
    {
      "code": "000001",
      "name": "上证指数",
      "quote": {
        "code": "000001", "name": "上证指数", "source": "akshare",
        "current_price": 3200.0, "change_amount": 5.5, "change_pct": 0.17,
        "open": 3195.0, "high": 3210.0, "low": 3190.0, "prev_close": 3194.5,
        "volume": 123456789, "amount": 234567890123.0
      },
      "klines": {
        "5m": {"data": [...96 bars...], "error": null},
        "d":  {"data": [...30 bars...],  "error": null},
        "w":  {"data": [...48 bars...],  "error": null}
      },
      "errors": {"quote": null}
    }
  ],
  "summary": {"requested": 3, "ok": 3, "failed": 0, "elapsed_ms": 1234}
}
```

| Field | Type | Description |
|---|---|---|
| `indices[].code` | string | The index code (canonical 6-digit). |
| `indices[].name` | string | The index name (from `index_symbols` map or upstream). |
| `indices[].quote` | object \| null | The realtime `IndexQuote` dict, or `null` when no fetcher could serve. |
| `indices[].klines` | object | Per-frequency K-line block (`5m` / `d` / `w`). Each block: `{data: KLineData[], error: string\|null}`. `error` is set when that specific frequency's upstream call failed. |
| `indices[].errors` | object | `{quote: string\|null}` — per-frequency K-line errors live in `klines[f].error` instead (mirrors the per-aspect shape used by the stocks variant). |
| `summary.requested` | int | `len(codes)`. |
| `summary.ok` | int | Number of entries with both quote AND all 3 K-line frequencies served. |
| `summary.failed` | int | `requested - ok`. |
| `summary.elapsed_ms` | int | Wall-clock for the fan-out (per request, not per fetcher). |

**Bar counts are pinned server-side** to keep the response shape
stable: 5m = 2 trading days (~96 bars), d = 30 bars, w = 48 bars
(~1 year). Clients that want different bar counts still go through
`/indices/{code}/kline?frequency=...&days=...`.

**K-line fan-out is sequential per index** (3 frequencies × N codes).
For the default 3 codes that's 9 fetches; the route is not parallelized
(individual fetcher calls are already I/O-bound under their own
circuit breakers).

**Errors:**

- No upstream `DataFetchError` propagates out of the route — per-frequency
  failures populate `klines[f].error` and the entry is marked failed
  in the summary. The route returns 200 even when all 3 frequencies
  of an index failed (the failure is in the body, not the status).

**Cache:** `make_indices_batch_profile_cache_key(sorted(codes))` →
`agent_indices_batch_profile:<sorted_codes>`. Codes are sorted for
order-perturbation immunity; the response list is reordered to the
caller's input order on cache hit.

---

### GET /api/v1/agent/market-context

Daily market snapshot: morning briefing + market recap + flash news +
zt/dt pools + dragon-tiger. Use case: "give me everything I need for
one market-recap pass in a single call".

```bash
GET /api/v1/agent/market-context
GET /api/v1/agent/market-context?flash_limit=50&trade_date=2026-07-14
```

**Parameters:**

| Parameter | Type | Default | Description |
|---|---|---|---|
| `flash_limit` | int | 20 | Flash news item count (1-200, matches `fetch_flash_news`'s `pageSize` hard cap). |
| `trade_date` | string | latest trade date ≤ today | `YYYY-MM-DD`; affects morning-briefing / market-recap / dragon-tiger. zt and dt pools and flash news are not date-keyed (zt/dt default to today, flash is real-time). Malformed values → 400 `invalid_trade_date`. |
| `format` | string | `json` | `json` (default) or `md` — see [`?format=json|md` projection](#agent-batch-api). |

**Response (200):**

```json
{
  "trade_date": "2026-07-14",
  "is_trade_day": true,
  "market_session": "post-market",
  "messages": {
    "morning_briefing": {"article_id": 1842356, "title": "财联社7月14日早报", "date": "2026-07-14", "body_text": "..."},
    "market_recap":    {"article_id": 1842400, "title": "财联社7月14日复盘", "date": "2026-07-14", "body_text": "..."},
    "flash_news": [{"title": "...", "publish_time": "2026-07-14 09:31:00", "url": "..."}]
  },
  "limit_pools": {
    "zt": [{"code": "601001", "name": "晋控煤业", "change_pct": 10.02, "first_seal_time": "09:41", "lb_count": 2, "industry": "煤炭"}],
    "dt": null
  },
  "dragon_tiger": {
    "stocks": [{"code": "002475", "name": "立讯精密", "net_buy_wan": 15230.5, "buy_wan": 18000.0, "sell_wan": 2769.5, "total_amount_wan": 95000.0, "pct_chg": 10.0, "pct_chg_after": 10.5}],
    "summary": {
      "total_net_buy_wan": 12345.0,
      "top_by_net_buy": [{"code": "002475", "name": "立讯精密", "net_buy_wan": 15230.5}],
      "top_by_net_sell": [{"code": "300750", "name": "宁德时代", "net_buy_wan": -8500.0}]
    }
  },
  "summary": {"requested": 6, "ok": 6, "failed": 0, "elapsed_ms": 567}
}
```

| Field | Type | Description |
|---|---|---|
| `trade_date` | string | The trade date this snapshot represents (`YYYY-MM-DD`). |
| `is_trade_day` | bool | Whether today (server local CST) is a trade day. |
| `market_session` | enum | `pre-market` / `intraday` / `post-market` / `closed`. Anchored to Asia/Shanghai 09:15 / 15:00 per spec §3.2.3. |
| `messages.morning_briefing` | object \| null | CLS morning briefing article dict; `null` when no article published / fetch failed. |
| `messages.market_recap` | object \| null | CLS market recap article dict; same null semantics. |
| `messages.flash_news` | object[] | Global flash news list (default 20 items, configurable via `flash_limit`). Empty list on upstream failure. |
| `limit_pools.zt` / `dt` | object[] \| null | ZT / DT pool lists. `null` in pre-market (池子未成形) OR when the upstream call failed entirely. Empty list `[]` is distinct from `null` (means "fetch succeeded, 0 stocks"). |
| `dragon_tiger.stocks` | object[] | Full daily 龙虎榜 list (not truncated to top 10). |
| `dragon_tiger.summary` | object | Server-computed rollup: `total_net_buy_wan` (signed), `top_by_net_buy` (top 10 by net_buy DESC), `top_by_net_sell` (top 10 by net_buy ASC among rows with `net_buy_wan < 0` only — surfacing positive rows as "top sell" would be misleading on all-positive days). |
| `summary` | object | `{requested, ok, failed, elapsed_ms}` — `requested` is the number of attempts made; in pre-market the zt + dt attempts are skipped, so `requested` drops to 4 (briefing + recap + flash + dtiger). |

**Per-block isolation:** each upstream call is wrapped in its own
try/except, so a failure in one block (e.g. CLS HTML parser crash on
the briefing) does not abort the others. The failed block's value is
its `null` (or `[]` for flash) and the failed count is incremented.

**Cache:** `make_market_context_cache_key(flash_limit, trade_date, session)` →
`agent_market_context:<flash_limit>:<trade_date>:<session>`. The
`session` dimension is required because pre/intra/post-market produce
materially different responses (pre-market forces zt/dt to null).

**`trade_date` validation:** the route enforces a `^\d{4}-\d{2}-\d{2}$`
regex. Non-date strings (e.g. `yesterday`) → 400 `invalid_trade_date`,
not a silent 200 with empty results.

---

### POST /api/v1/agent/stocks/batch-profile

Per-stock fan-out across 5 server-side aspects: `quote` (realtime),
`kline` (daily, 60 bars), `kline_5m` (5-minute, 2 days), `info` (company
profile), `boards` (THS-membership reverse lookup). Use case: "give
me everything I need to evaluate 1-5 candidate stocks in a single call".

```bash
POST /api/v1/agent/stocks/batch-profile
Content-Type: application/json

{"codes": ["600519", "000858"], "aspects": ["quote", "kline", "info", "boards"]}
```

**Request body:**

| Field | Type | Required | Description |
|---|---|---|---|
| `codes` | string[] | yes | 1-5 stock codes (bare 6-digit A-share). The 5-code cap matches the stock-picking funnel. |
| `aspects` | enum[] | no (default = all 5) | Subset of `["quote", "kline", "kline_5m", "info", "boards"]`. `fund_flow` is NOT supported (use `/stocks/{code}/fund-flow` directly). |

**Response (200):**

```json
{
  "results": [
    {
      "code": "600519",
      "ok": true,
      "data": {
        "quote":     {"code": "600519", "name": "贵州茅台", "current_price": 1698.0, "change_pct": 1.52, "...": "..."},
        "kline":     {"source": "akshare", "data": [{"date": "2026-07-14", "open": 1680.0, "high": 1700.0, "low": 1670.0, "close": 1698.0, "volume": 1234567, "amount": 2087654321.0, "change_pct": 1.52}]},
        "kline_5m":  {"source": "akshare", "data": [...]},
        "info":      {"source": "zhitu", "data": {"code": "600519", "name": "贵州茅台", "industry": "白酒"}},
        "boards":    {"source": "persistence", "data": [{"code": "885595", "name": "白酒", "type": "industry", "subtype": "同花顺行业", "source": "ths"}]}
      },
      "errors": []
    }
  ],
  "summary": {"requested": 2, "ok": 2, "failed": 0, "elapsed_ms": 890}
}
```

| Field | Type | Description |
|---|---|---|
| `results[].code` | string | Stock code (echoes the request). |
| `results[].ok` | bool | `false` only when **all** aspects raised (entry-level failure); partial aspect failures keep `ok=true` and surface in `errors[]`. |
| `results[].data` | object | Per-aspect payload (key = aspect name). Each value's shape matches the corresponding non-agent endpoint: `quote` is the flat `StockQuote` dict (NOT wrapped in `{source, data}`); `kline` / `kline_5m` / `info` / `boards` are `{source, data}` envelopes. |
| `results[].errors[]` | object[] | Per-aspect failure: `{"aspect": "<name>", "error": "<ExceptionClassName>", "message": "<str>"}`. |
| `summary` | object | `{requested, ok, failed, elapsed_ms}`. |

**Per-aspect error isolation:** each aspect is wrapped in its own
try/except. The `boards` aspect routes through the persistence layer
(`stock_board_cache.get_stock_memberships`), NOT `manager.get_stock_boards`,
to inherit the ZZSHARE↔THS fallback chain and `effective_source` plumbing.

**`kline` aspect pinning:** always passes `asset="stock"` to the
manager so that codes like `000001` (which is also a CSI index) route
to `STOCK_KLINE`, not `INDEX_KLINE`. Pinned by
`test_stocks_batch_profile_kline_passes_asset_stock`.

**Cache:** `make_stocks_batch_profile_cache_key(sorted(codes), sorted(aspects))` →
`agent_stocks_batch_profile:<sorted_codes>|<sorted_aspects>`. Both
axes are sorted so the same (set, set) pair collapses to one entry;
the response is reordered to the caller's input order on hit.

**Errors:**

- `422 invalid_request` (Pydantic) — `codes` empty / > 5 / `aspects`
  empty / unknown aspect name.

---

### POST /api/v1/agent/correlation/matrix

Cross-asset (stocks + boards, A-share only) pairwise correlation
matrix. Returns symmetric NxN Pearson + Spearman matrices (N = 2..10,
2 ≤ N ≤ 10) on the same inner-joined date alignment. Use case: "which
boards track the same as my watchlist" or "how tightly does `885595`
track `600519` over 90 d".

```bash
POST /api/v1/agent/correlation/matrix
Content-Type: application/json
```

**Request body:**

| Field | Type | Required | Default | Description |
|---|---|---|---|---|
| `stocks` | string[] | no | `[]` | 0-10 stock codes (bare 6-digit A-share; pre-normalized via `normalize_stock_code`). |
| `boards` | array | no | `[]` | 0-10 entries; each is either a bare code string (`"885595"` → source defaults to `"ths"`) or `{"code": "885595", "source": "ths" \| "eastmoney"}`. |
| `frequency` | enum | no | `"d"` | One of `d` / `w` / `m` / `1m` / `5m` / `15m` / `30m` / `60m`. |
| `days` | int | no | `90` | Calendar-day window for the alignment; range is frequency-dependent (table below). The route fetches `days + 1` (a +1 buffer for `pct_change`) and reports the actual overlapping bar count in `alignment.common_bars` — for d/w/m that is ~0.7×`days` (non-trading days carry no bars), so request ~1.4× the sample size you want. |
| `methods` | enum[] | no | `["pearson", "spearman"]` | One or both of `"pearson"` and `"spearman"`. De-duped, order preserved. |
| `format` | query | no | `"json"` | `json` (default) or `md` — see [`?format=json\|md` projection](#agent-batch-api). |

**Cross-field:** `len(stocks) + len(boards)` must be in `[2, 10]`. Each
list independently capped at 10.

**`frequency` × `days` validation table** (out-of-range → 422
`bad_request`):

| `frequency` | `days` range | Boards `ths` | Boards `eastmoney` |
|---|---|---|---|
| `d` | 2..365 | yes | yes |
| `w` | 14..1095 | yes | yes |
| `m` | 60..1825 | yes | yes |
| `1m` | 2..3 | yes | **no** → 422 if any board has `source="eastmoney"` |
| `5m` | 2..3 | yes | yes |
| `15m` | 2..5 | yes | yes |
| `30m` | 2..10 | yes | yes |
| `60m` | 2..20 | yes | yes |

The board-source/frequency table is **server-validated in advance** —
the route refuses early with `422` rather than letting
`manager.get_board_history(..., frequency="1m", source="eastmoney")`
explode downstream. Ranges are calendar days; the lower bound guarantees
≥ 2 return observations (minute `days=1` would be trimmed to a single
return → 422). Low d/w/m values can still 422 on holiday/weekend
alignment. THS upstream caps 1m at ~800 most-recent bars, so the `1m`
upper bound is `days ≤ 3` (~3.3 trading sessions).

**Response (200):**

```json
{
  "labels": [
    {"type": "stock", "code": "600519", "name": "贵州茅台", "source": null},
    {"type": "stock", "code": "000858", "name": "五粮液",  "source": null},
    {"type": "board", "code": "881270", "name": "白酒",    "source": "ths"}
  ],
  "frequency": "d",
  "days": 90,
  "alignment": {
    "requested_days": 90,
    "common_bars": 63,
    "missing_after_join": 1
  },
  "matrices": {
    "pearson":  [[1.0, 0.87, 0.41], [0.87, 1.0, 0.39], [0.41, 0.39, 1.0]],
    "spearman": [[1.0, 0.79, 0.32], [0.79, 1.0, 0.34], [0.32, 0.34, 1.0]]
  },
  "errors": []
}
```

| Field | Type | Description |
|---|---|---|
| `labels[i]` | object | `{type, code, name, source}`. Order = request order (stocks block first, then boards block). `labels[i]` corresponds to `matrices.<m>[i][:]`. For stock labels `source` is always `null`; for board labels `source` is the *requested* source (`"ths"` / `"eastmoney"`), **not** the actually-serving fetcher (no per-asset `effective_source` on this composite endpoint). |
| `frequency` / `days` | enum / int | Echoed back so an agent can confirm what the matrix was computed over. |
| `alignment.requested_days` | int | The `days` you asked for. |
| `alignment.common_bars` | int | Number of rows in the inner-joined DataFrame — the actual sample size used to compute the matrix. For d/w/m this is typically **less than `days`** (~0.7× for daily): `days` is a calendar-day window and non-trading days carry no bars, so the trailing trim (ceiling `days+1`) is a no-op there. Minute frequencies return dense bars, so `common_bars` ≈ `days+1`. |
| `alignment.missing_after_join` | int | Dates dropped by the inner-join itself (longest source minus joined length, computed **before** the trailing-window trim so it reflects real date gaps, not calendar padding). |
| `matrices.<method>` | `list[list[float]] \| null` | Symmetric NxN matrix, diagonal=1.0, NaN→0, rounded to 4 dp. `null` when the method wasn't requested. Key always exists for shape checks. |
| `errors[]` | object[] | Per-asset failures. Each: `{type, code, source, reason}` where `reason ∈ {"data_unavailable", "empty", "too_short"}`. Empty on success. |

**Errors:**

- `400 bad_request` — malformed JSON or invalid stock code in `stocks`
  (e.g. `normalize_stock_code` rejected the input).
- `422 bad_request` — `frequency` not in enum, `days` outside
  frequency-dependent range, `methods` empty / unknown, `len(stocks) +
  len(boards)` outside `[2, 10]`, board `source` not in `{"ths",
  "eastmoney"}`, or `frequency × source` pair not allowed (e.g.
  `1m` + `eastmoney`).
- `422 insufficient_assets` — fewer than 2 assets survived after per-item
  failures (no matrix computable). The response body is omitted on this
  hard 422.
- **No 5xx.** Per-item `DataFetchError` is always reported in `errors[]`;
  blanket upstream outages manifest as `len(errors) == N` plus a 422.

**`?format=md` projection:** renders one section per requested method
(`pearson` / `spearman`), each with a header summary, a top-pairs
table sorted by `|ρ|` descending, and the full NxN matrix below:

```markdown
## 相关性矩阵 — pearson (d × 90d)

> 资产数: 3 · 对齐 63/90 个日历日 · 缺失 1 个数据点

### 所有 pair (按 |ρ| 降序)
| # | Pair                                | ρ     |
|---|-------------------------------------|-------|
| 1 | 600519 ↔ 000858                   | 0.87  |
| 2 | 000858 ↔ 881270 (ths)             | 0.39  |
| 3 | 600519 ↔ 881270 (ths)             | 0.41  |

### 完整矩阵 (pearson)
|          | 600519 | 000858 | 881270 (ths) |
|----------|--------|--------|--------------|
| 600519   | —      | 0.87   | 0.41         |
| 000858   | 0.87   | —      | 0.39         |
| 881270   | 0.41   | 0.39   | —            |
```

When `errors[]` is non-empty, an extra `### 数据缺失` subsection
appends one bullet per failed asset. Unlike the other 6 agent
endpoints, this projection is rendered directly via `PlainTextResponse`
inside the route — there is **no JSON-fallback / `X-MD-Render-Error`
header contract**: a template failure surfaces as a 500. The MD body
contains the same fields as the JSON response, no data is dropped.

**No agent-level composite cache (deliberate deviation).** Unlike the
other 6 endpoints, this one does **not** use the 60s `get_quote_cache`
slot. Reasoning: each `manager.get_kline_data` / `manager.get_board_history`
call is independently memoized by the fetcher-level TTLCache (60+ s for
K-line per `CACHE_TTL_STOCK_KLINE`), and a 2-10 asset fan-out is sub-1 s
on the warm path. Adding a composite cache would re-do work the inner
TTLs already paid. If cold-path latency becomes a complaint, add
`make_correlation_matrix_cache_key` to `api/cache.py` and wrap the
handler with `cached_lookup` / `cached_store` — a 4-line patch with a
60 s TTL choice.

**Per-item error isolation:** each fetch is wrapped in
`try/except (DataFetchError, ValueError, KeyError, AttributeError,
TypeError)`. Failure → `errors[]` entry, asset dropped from analysis,
remaining continue. The route never aborts the whole response on a
single failure (unless fewer than 2 survive, which becomes the
`insufficient_assets` 422 above).

**Alignment internals** (for debugging): the route normalizes each
series index (drop time-of-day, sort, dedupe duplicate dates — some
upstream bar series can carry two rows on one date, e.g. suspend/resume
or a merged today bar; `pd.concat` would otherwise raise on the
re-index). Inner-join keeps only dates present in **every** series, then
`pct_change(fill_method=None)` per column drops the first row. The
final matrix uses `len(returns)` rows; `common_bars` reports the
pre-pct-change size. `np.corrcoef` handles zero-variance columns (NaN
→ 0 via `_finalize_matrix`'s `np.where(np.isnan, 0.0)` fallback).
