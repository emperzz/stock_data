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

---

**Parameters:**
| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `period` | string | `daily` | K-line period: `daily`, `weekly`, `monthly` |
| `days` | int | 30 | Number of days to retrieve (1-365, ignored when `start_date` provided) |
| `start_date` | string | null | Start date (YYYY-MM-DD), overrides `days` parameter |
| `end_date` | string | null | End date (YYYY-MM-DD), defaults to today |
| `adjust` | string | `` | Adjustment type: empty=不复权, `qfq`=前复权, `hfq`=后复权 |
| `indicators` | string | null | Comma-separated list of technical indicators to attach (see [Technical Indicators](#technical-indicators)) |

**Response (without `indicators`):**
```json
{
  "code": "600519",
  "stock_name": "贵州茅台",
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
      "change_percent": 1.52
    }
  ]
}
```

> **Note:** the `indicators` field is **omitted from the response entirely**
> when `?indicators=` is not passed — instead of being present-but-null.
> To get per-bar indicator values, opt in with `?indicators=ma` (or any
> indicator set). `amount` and `change_percent` keep their original
> "null when missing" behavior.

**Response (with `?indicators=ma,macd,kdj,boll`):**
```json
{
  "code": "600519",
  "stock_name": "贵州茅台",
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
      "change_percent": 0.59,
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
  "stock_name": "贵州茅台",
  "source": "AkshareFetcher",
  "current_price": 1698.0,
  "change": 25.5,
  "change_percent": 1.52,
  "open": 1680.0,
  "high": 1700.0,
  "low": 1670.0,
  "prev_close": 1672.5,
  "volume": 1234567,
  "amount": 2087654321.0
}
```

**Note:** Index codes are not supported via `/stocks/{code}/quote`. Use `/indices/{code}/quote` instead.

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
  "change": -26.07,
  "change_percent": -0.536,
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
| `days` | int | 30 | Number of days (1-365, ignored when `start_date` provided) |
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
- First call fetches from upstream (Tushare for A-share if token, otherwise Akshare)
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
- `ths` — ThsFetcher (concept + industry, d-only K-line; internally
  merges ZzshareFetcher for platecode backfill)
- `eastmoney` — EastMoneyFetcher (concept + industry only; no
  index/special classification upstream; d/w/m + 5/15/30/60m K-line)
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

# Board K-line (THS: d-only, board_type required; EastMoney: multi-frequency)
GET /api/v1/boards/BK1048/history?source=eastmoney&frequency=d
GET /api/v1/boards/881270/history?source=ths&frequency=d&board_type=industry
```

**Parameters for `GET /boards`:**
| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `type` | string | null (all) | Board type: `concept`, `industry`, `index`, `special`. Omit to return every type the source exposes. `eastmoney` only supports `concept` + `industry`; `?type=index` / `?type=special` returns 400 on `source=eastmoney`. |
| `source` | string | Required | Data source: `ths`, `eastmoney`, or `zhitu` |
| `subtype` | string | null | Source-specific subtype (e.g. `申万行业` for zhitu). Validated per (source, type) pair. |
| `include_quote` | bool | `false` | Include realtime price/change/market data (EastMoney only; ThsFetcher + Zhitu ignore) |
| `sort_by` | string | null | Sort by: `change_pct`, `volume`, `amount`, `price` (requires `include_quote=true`) |
| `sort_order` | string | `desc` | Sort order: `asc` or `desc` |
| `limit` | int | null | Max items (1-500) |
| `refresh` | bool | `false` | Force fetch latest from upstream |

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
      "turnover_rate": 3.58,
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

This endpoint returns two source fields:
- `query_source` — the user-supplied `?source=` value (canonicalized)
- `data_source` — the actual origin (`fetcher name` on cache miss;
  `"persistence"` on cache hit)

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
| `source` | string | Required | Data source: `ths` (d-only) or `eastmoney` (d/w/m + 5/15/30/60m). `zzshare` is accepted and aliased to `ths`. |
| `frequency` | string | `d` | K-line frequency. `eastmoney` supports `d / w / m / 5m / 15m / 30m / 60m`; `ths` is `d`-only (other frequencies raise 4xx). |
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
  "board_code": "885595",
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
  "board_code": "885914",
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
  "board_code": "885914",
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
      "turnover_rate": 4.1, "lb_count": 2, "first_seal_time": "09:41",
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
  "stock_name": "贵州茅台",
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
  "vol_ratio": 1.2
}
```

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
  "institution": {"buy_amt": 8900.0, "sell_amt": 600.0, "net_amt": 8300.0},
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
      "turnover_rate": 8.3,
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
**BaiduFetcher** (P7, requires `BAIDU_API_KEY`) is the failover. Both
sources are restricted to canonical news subdomains (`finance.eastmoney.com`,
`www.cls.cn`, `news.10jqka.com.cn`); Baidu also honors `BAIDU_NEWS_DOMAINS`
overrides.

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
  "byte_size": 4321
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
