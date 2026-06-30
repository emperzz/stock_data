# Stock Data Server

A local stock data aggregation server that integrates 12 upstream stock data APIs into a unified REST API for AI agents.

**Four layers in one server:**

- **API Layer (FastAPI)** — declarative routes; metadata-driven via `@endpoint_meta`.
- **IndicatorService (pure compute)** — `MA · MACD · BOLL · KDJ · RSI · WR · BIAS · CCI · ATR · OBV · ROC · DMI · SAR · KC` (14 built-in). Sits on top of the manager; no fetcher involvement.
- **DataFetcherManager** — capability-routed, priority-based failover + circuit breaker + TTLCache.
- **Source Adapters** — `Tushare · Baostock · Akshare · Yfinance · Zhitu · Zzshare · Tencent · EastMoney · THS · Cninfo · Myquant · Baidu` (12 fetchers).

Persistence (on-disk SQLite for stock lists / board metadata / trade calendar / ZT pools) is owned by `data_provider/persistence/` and seeded transparently by the manager. Board persistence supports all types (concept/industry/index/special), keyed by (board_type, source). An interactive API Explorer is served at `/explorer/`.

## Features

- **Multi-source aggregation** (12 fetchers): Tushare, Baostock, Akshare, Yfinance, Zhitu, Zzshare, Tencent, EastMoney, THS, Cninfo, Myquant, Baidu
- **Automatic failover**: priority-based source selection with capability-routed fallback
- **Circuit breaker**: prevents cascading failures from unavailable sources
- **Persistent metadata cache**: SQLite for stock lists, board metadata, trade calendar, ZT/DT/ZBGC pools (separate from in-process TTLCache)
- **Unified data format**: consistent schema across all sources
- **Market support**: A-shares, Hong Kong stocks, US stocks and indices (CSI / HK / US)
- **Enhanced quotes**: PE/PB/市值/换手率/振幅 via Tencent财经
- **Signal layer**: 龙虎榜/融资融券/大宗交易/股东户数/分红/资金流/热点题材/北向资金
- **News**: 关键词搜索 (EastMoney → Baidu 备份) / 7×24 快讯 (EastMoney → THS 备份) / 正文提取
- **Fundamentals**: 公司画像 (Zhitu → Myquant) / 研报检索+PDF下载 / 公告检索
- **Technical indicators** (pure compute, 14 built-in): MA · MACD · BOLL · KDJ · RSI · WR · BIAS · CCI · ATR · OBV · ROC · DMI · SAR · KC — attach to K-line via `?indicators=ma,macd,kdj`
- **API Explorer** (`/explorer/`): interactive docs, search, market/capability filters, Stage 2 fetcher drill-down

## Quick Start

> **Always use the project venv.** `akshare` / `yfinance` / `gm` are
> installed in `.venv/`, not the system Python. Running the bare
> `python` binary will hit `ModuleNotFoundError` and break every
> endpoint that routes through those packages. Use
> `.venv/Scripts/python.exe` (Windows) / `.venv/bin/python` (Linux/macOS)
> directly, or `source .venv/Scripts/activate` first.

```bash
# Install dependencies (into the venv)
.venv/Scripts/python.exe -m pip install -e ".[dev]"

# Configure (copy and edit .env)
cp .env.example .env
# Edit .env and add your TUSHARE_TOKEN (and optionally ZHITU_TOKEN /
# ZZSHARE_TOKEN / MYQUANT_TOKEN / BAIDU_API_KEY)

# Run the server
.venv/Scripts/python.exe -m stock_data.server

# Or with uvicorn directly
.venv/Scripts/python.exe -m uvicorn stock_data.server:app --host 127.0.0.1 --port 8888
```

After startup, open `http://localhost:8888/explorer/` for the interactive API explorer.

**One-liner with technical indicators:**

```bash
# K-line + MACD + KDJ + BOLL
curl 'http://localhost:8888/api/v1/stocks/600519/history?days=120&indicators=macd,kdj,boll'

# What indicators are available?
curl 'http://localhost:8888/api/v1/indicators/catalog'

# Health check (root-mounted, k8s/lb convention)
curl 'http://localhost:8888/healthz?details=true'
```

## API Endpoints

All endpoints are versioned under `/api/v1/...` **except** `/healthz`,
which is mounted at the root (k8s/lb convention). The `/explorer/` UI
and `/control/*` management API are described under [API Explorer](#api-explorer).

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
`/stocks/{code}/history` and never hit the network — they transform the
K-line `DataFrame` in-process.

#### List available indicators

```bash
GET /api/v1/indicators/catalog
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
GET /api/v1/stocks/600519/history?days=120&indicators=ma,macd,kdj,boll,rsi
# Indices (same query param, same behavior)
GET /api/v1/indices/000300/history?days=120&indicators=ma,macd,boll
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
| `cci` | Commodity Channel | ohlcv | `cci` | 28 |
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
  "stock_code": "600519",
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
  "stock_code": "600519",
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

The `GET /api/v1/stocks/{code}/history` endpoint is fully documented
under [Technical Indicators](#technical-indicators) above (parameters,
auto-lookback expansion, with- and without-`?indicators=` response
shapes). Omit `?indicators=` to receive the slim per-bar payload shown
in the **Response (without `indicators`)** block; pass
`?indicators=ma,macd,kdj,boll` to attach per-bar values via the
`indicators` dict.

---

### Get Realtime Quote

```bash
GET /api/v1/stocks/{code}/quote
```

**Response:**
```json
{
  "stock_code": "600519",
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
`STOCK_INFO` capability — Zhitu (P4) → Myquant (P9) failover.
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

```bash
GET /api/v1/stocks/{code}/intraday?period=5
```

**Parameters:**
| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `period` | string | `5` | Minute period: `1`, `5`, `15`, `30`, `60` |
| `adjust` | string | `` | Adjustment type: empty=不复权, `qfq`=前复权, `hfq`=后复权 |

**Response:**
```json
{
  "code": "600519",
  "stock_name": "贵州茅台",
  "period": "5m",
  "date": "2026-05-19",
  "data": [
    {
      "time": "09:30:00",
      "open": 1698.0,
      "high": 1700.0,
      "low": 1695.0,
      "close": 1699.0,
      "volume": 12345,
      "amount": 20987654.0
    }
  ]
}
```

**Note:** Intraday data is only available for A-share stocks (not US/HK stocks or indices).

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
GET /api/v1/indices/{index_code}/history?period=daily&days=30
```

**Parameters:**
| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `period` | string | `daily` | K-line period: `daily`, `weekly`, `monthly` |
| `days` | int | 30 | Number of days (1-365, ignored when `start_date` provided) |
| `start_date` | string | null | Start date (YYYY-MM-DD), overrides `days` |
| `end_date` | string | null | End date (YYYY-MM-DD), defaults to today |
| `indicators` | string | null | Comma-separated list of technical indicators to attach (see [Technical Indicators](#technical-indicators)). Same semantics as `/stocks/{code}/history`. |

#### Index Intradaday (Minute-Level)

```bash
GET /api/v1/indices/{index_code}/intraday?period=5
```

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `period` | string | `5` | Minute period: `1`, `5`, `15`, `30`, `60` |

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

**Cached data location:** `stock_data/stock_cache.db` (SQLite). Override via `STOCK_CACHE_DB_PATH` environment variable. See [Persistence](#persistence-on-disk-sqlite-store) below.

---

### Board Data (Concept / Industry / Index / Special)

Board endpoints are **source-routed** — the `source` query parameter is
**required** and selects the fetcher backend. Different sources use
incompatible board classification systems (EastMoney: concept/industry;
Zhitu: type × subtype), so failover between sources is intentionally
not supported.

Available sources: `eastmoney`, `zhitu`.

```bash
# Board list (concept / industry / index / special)
GET /api/v1/boards?type=concept&source=eastmoney
GET /api/v1/boards?type=industry&source=eastmoney&include_quote=true
GET /api/v1/boards?type=industry&source=zhitu&subtype=申万行业

# Board stocks
GET /api/v1/boards/BK1048/stocks?source=eastmoney
GET /api/v1/boards/BK1048/stocks?source=eastmoney&include_quote=true

# Stock → boards mapping (Zhitu only)
GET /api/v1/stocks/000001/boards?source=zhitu
GET /api/v1/stocks/000001/boards?source=zhitu&type=concept&subtype=热门概念

# Board K-line (stub — 501 Not Implemented)
GET /api/v1/boards/BK1048/history?source=eastmoney
```

**Parameters for `GET /boards`:**
| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `type` | string | Required | Board type: `concept`, `industry`, `index`, `special` |
| `source` | string | Required | Data source: `eastmoney` or `zhitu` |
| `subtype` | string | null | Source-specific subtype (e.g. `申万行业` for zhitu). Validated per (source, type) pair. |
| `include_quote` | bool | `false` | Include realtime price/change/market data (EastMoney only; Zhitu ignores) |
| `sort_by` | string | null | Sort by: `change_pct`, `volume`, `amount`, `price` (requires `include_quote=true`) |
| `sort_order` | string | `desc` | Sort order: `asc` or `desc` |
| `limit` | int | null | Max items (1-500) |
| `refresh` | bool | `false` | Force fetch latest from upstream |

**Response (with `include_quote=false`, default):**
```json
{
  "source": "EastMoneyFetcher",
  "data": [
    {"code": "BK1048", "name": "互联网服务"},
    {"code": "BK0891", "name": "云计算"}
  ]
}
```

**Response (with `include_quote=true`):**
```json
{
  "source": "EastMoneyFetcher",
  "data": [
    {
      "code": "BK1048",
      "name": "互联网服务",
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
| `source` | string | Required | Data source: `eastmoney` or `zhitu` |
| `include_quote` | bool | `false` | Include realtime price/change/volume data for each stock |
| `refresh` | bool | `false` | Force fetch latest from upstream |

**Parameters for `GET /stocks/{stock_code}/boards`:**
| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `source` | string | Required | Data source (currently only `zhitu` supported; `eastmoney` returns 501) |
| `type` | string | null | Filter by board type |
| `subtype` | string | null | Filter by source-specific subtype |

**Source-specific subtype values (zhitu):**
| Type | Valid subtypes |
|------|---------------|
| `industry` | `申万行业`, `申万二级`, `证监会行业` |
| `concept` | `热门概念`, `概念板块`, `地域板块` |
| `index` | `分类`, `指数成分`, `大盘指数` |
| `special` | `风险警示`, `次新股`, `沪港通`, `深港通` |

**EastMoney** subtype is a mirror of type (`concept`, `industry`, `index`, `special`).

**Caching behavior for board endpoints:**
- Results are cached in `stock_data/stock_cache.db` (SQLite)
- `include_quote=true` fetches fresh data from upstream AND updates cache
- `refresh=true` forces upstream fetch and updates cache
- First call of each day triggers a refresh from upstream

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
GET /api/v1/stocks/{code}/dragon-tiger?trade_date=2026-05-20&look_back=30
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

**全市场龙虎榜:**
```bash
GET /api/v1/dragon-tiger/daily?trade_date=2026-05-20&min_net_buy=5000
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
GET /api/v1/hot/topics?date=2026-05-20
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

## API Response Caching

The `/quote` and `/history` endpoints are cached using an in-memory TTLCache to avoid repeated upstream API calls when multiple users request the same data within a short window.

| Endpoint | Cache Key | Default TTL |
|----------|-----------|-------------|
| `GET /stocks/{code}/quote` | `stock_code` | 60s |
| `GET /stocks/{code}/history` (daily) | `code:d:days` | 300s |
| `GET /stocks/{code}/history` (weekly) | `code:w:days` | 3600s |
| `GET /stocks/{code}/history` (monthly) | `code:m:days` | 7200s |
| `GET /indices/{code}/quote` | `idx_quote:{code}` | 60s |
| `GET /indices/{code}/history` | `{code}:{freq}:{days}` | 300/3600/7200s |
| `GET /indices/{code}/intraday` | `idx_intraday:{code}:{period}` | 30s |

**Cache behavior:**
- First request fetches from upstream (subject to rate limiting)
- Subsequent identical requests within TTL return cached data instantly
- Cache is per-process (not shared across workers)

**Configuration (environment variables):**
| Variable | Description | Default |
|----------|-------------|---------|
| `ENABLE_API_CACHE` | Enable/disable API response cache | `true` |
| `CACHE_TTL_QUOTE` | TTL for realtime quotes (seconds) | `60` |
| `CACHE_TTL_HISTORY_DAILY` | TTL for daily K-line (seconds) | `300` |
| `CACHE_TTL_HISTORY_WEEKLY` | TTL for weekly K-line (seconds) | `3600` |
| `CACHE_TTL_HISTORY_MONTHLY` | TTL for monthly K-line (seconds) | `7200` |
| `CACHE_TTL_INDEX_QUOTE` | TTL for index realtime quotes (seconds) | `60` |
| `CACHE_TTL_STOCK_INTRADAY` | TTL for stock intraday (seconds) | `30` |
| `CACHE_TTL_STOCK_INFO` | TTL for 公司画像 (`StockInfoResponse`, seconds) | `3600` |

### Persistence (on-disk SQLite store)

The persistence layer caches stock lists, board metadata, trade calendar, and ZT/DT/ZBGC pool history across processes. It lives in `stock_data/data_provider/persistence/` and is separate from the in-process TTLCache above.

**Board persistence**: boards are cached per `(board_type, source)` pair.
The persistence layer calls the fetcher via `manager.get_all_boards()` for
all types (concept/industry/index/special); fetchers return `[]` for types
they don't support (e.g. EastMoney returns `[]` for `index`/`special`).
Board metadata (code, name, type, source, timestamp) is stored in SQLite;
realtime quote data is always fetched live and never persisted.

| Variable | Description | Default |
|----------|-------------|---------|
| `STOCK_CACHE_DB_PATH` | Path to the SQLite file used by the persistence layer | `<repo>/stock_data/stock_cache.db` |
| `STOCK_DB_INIT` | `true` → DROP + recreate all persistence tables on boot; `false` → idempotent CREATE IF NOT EXISTS only. **WARNING: `true` wipes all cached stock lists, board metadata, trade calendar, and ZT/DT/ZBGC pool history.** | `false` |

### Source Tracking (new)

All responses carrying fetched data include a `source: str` field with one of these values:

- **fetcher name** (e.g. `tushare`, `akshare`, `eastmoney`): live fetch from upstream, OR API TTLCache hit (the cache stores the original fetcher name, so cache hits report the same source as the original call).
- **`"persistence"`**: served from the SQLite persistence layer (historical K-line / board lists / trade calendar / etc.).

`source` is optional in the schema and defaults to `""`. Older clients may ignore it.

**Board endpoints**: the `source` field in the response echoes the fetcher
name (e.g. `"EastMoneyFetcher"`, `"ZhituFetcher"`). Board data is
source-routed — different sources use incompatible classification
systems, so the source in the response always matches the `source`
query parameter.

`/stocks` and `/calendar` currently do NOT expose `source` (their response models have no such field) — the persistence origin is still computed and discarded. This is a YAGNI choice; if needed later, add `source: str` to those response models and the route layer is already wired to pass it through.

---

## API Explorer

An interactive docs UI is mounted at `/explorer/` (after `python -m stock_data.server`, open `http://localhost:8888/explorer/`). It is generated server-side from `app.routes` + the `@endpoint_meta` decorator on each route — the page fetches `GET /control/api-manifest` on load and renders a sidebar with search, market filter, capability filter, and a right-side response panel.

**Features:**

- **Search** — filter by endpoint path / summary
- **Market filter** — `csi` / `hk` / `us`
- **Capability filter** — `REALTIME_QUOTE` / `HISTORICAL_DWM` / `NEWS_FLASH` / etc.
- **Fetcher drill-down** (Stage 2) — collapsible section under each endpoint showing every fetcher that can serve it, with method signature + a `Test` button that posts to `POST /control/fetcher-test` to invoke the fetcher directly (bypassing the manager's circuit breaker / capability filter)

**Management endpoints (`/control/*`):**

| Endpoint | Purpose |
|----------|---------|
| `GET /control/config` | Current server config |
| `GET /control/server/status` | Runtime status |
| `GET /control/api-manifest` | JSON manifest consumed by the explorer UI |
| `POST /control/fetcher-test` | Stage 2 fetcher drill-down (always 127.0.0.1) |

> `/control/*` is bound to `127.0.0.1` only (the new `SERVER_HOST` default). To enable remote access, set `SERVER_HOST=0.0.0.0` explicitly. Stage 2 results bypass the manager's circuit breaker and are not production-equivalent.

---

## Symbol Conventions

### A-share Stocks (China)

| Market | Format | Examples |
|--------|--------|----------|
| Shanghai | 6 digits + `.SS` | `600519.SS`, `000001.SS` |
| Shenzhen | 6 digits + `.SZ` | `000001.SZ`, `399006.SZ` |
| Beijing | 6 digits + `.BJ` | `430001.BJ` |

**Input examples (all normalized to 6-digit code):**
```bash
GET /api/v1/stocks/600519/history     # 贵州茅台
GET /api/v1/stocks/000001/history     # 平安银行
GET /api/v1/stocks/SH600519/quote     # prefix stripped
GET /api/v1/stocks/SZ000001/quote     # prefix stripped
```

### A-share Indices (CSI)

| Index | Code | Full Name |
|-------|------|----------|
| 沪深300 | `000300` | CSI 300 |
| 上证指数 | `000001` | Shanghai Composite |
| 深证成指 | `399001` | Shenzhen Component |
| 创业板指 | `399006` | ChiNext |
| 中证500 | `000905` | CSI 500 |
| 科创50 | `000688` | STAR 50 |

**Index realtime quote:**
```bash
GET /api/v1/indices/000300/quote      # 沪深300 realtime
GET /api/v1/indices/399006/quote      # 创业板指 realtime
```

**Index historical K-line:**
```bash
GET /api/v1/indices/000300/history     # 沪深300 日线
GET /api/v1/indices/000300/history?period=weekly   # 沪深300 周线
GET /api/v1/indices/399001/history     # 深证成指
GET /api/v1/indices/000001/history?period=monthly  # 上证指数 月线
```

**Index intraday (minute-level):**
```bash
GET /api/v1/indices/399006/intraday?period=5   # 创业板指 5-minute
GET /api/v1/indices/000300/intraday?period=15  # 沪深300 15-minute
```

### Hong Kong Indices

| Index | Code | Full Name |
|-------|------|----------|
| 恒生指数 | `HSI` | Hang Seng Index |
| 国企指数 | `HSCE` | HSCEI |

**Note:** HK index intraday is not yet supported.

### Hong Kong Stocks

| Format | Example |
|--------|---------|
| `HK` + 5 digits | `HK00700`, `HK01810` |
| Suffix form | `00700.HK` |

**Examples:**
```bash
GET /api/v1/stocks/HK00700/history    # 腾讯控股
GET /api/v1/stocks/HK01810/history   # 小米集团
```

### US Stocks

| Format | Example |
|--------|---------|
| 1-5 letters | `AAPL`, `TSLA`, `GOOGL` |

**Examples:**
```bash
GET /api/v1/stocks/AAPL/quote        # Apple
GET /api/v1/stocks/TSLA/quote        # Tesla
```

### US Indices

| Index | Code | Yahoo Finance Symbol |
|-------|------|---------------------|
| S&P 500 | `SPX`, `SPY` | `^GSPC` |
| Dow Jones | `DJI` | `^DJI` |
| Nasdaq | `IXIC`, `NASDAQ` | `^IXIC` |
| VIX | `VIX` | `^VIX` |

**Examples:**
```bash
GET /api/v1/stocks/SPX/history       # S&P 500 日线
GET /api/v1/stocks/SPX/history?period=weekly    # S&P 500 周线
GET /api/v1/stocks/DJI/history        # 道琼斯工业平均
GET /api/v1/stocks/IXIC/history       # 纳斯达克综合
```

---

## Data Source Routing

The server automatically routes requests to the appropriate data source based on the stock/index code and the capability required. Default priorities are overridable via `*_PRIORITY` env vars (see [Configuration](#configuration)).

### A-share Stocks

| Priority | Source | Note |
|----------|--------|------|
| 0 | Tushare | Requires `TUSHARE_TOKEN` |
| 1 | Baostock | Free, no token |
| 2 | Akshare | Fallback |
| 3 | Yfinance | Fallback |
| 4 | Zhitu | Realtime quotes + 公司画像 + 板块 (含 stock→boards), requires `ZHITU_TOKEN` |
| 5 | Zzshare | A-share multi-capability (d/5/15/30/60/股票列表/交易日历/板块/龙虎榜/热点题材/公司画像); anonymous-capable, `ZZSHARE_TOKEN` optional (only `stock_info` + `uplimit_stocks` need it) |
| 6 | Tencent | Enhanced quotes (PE/PB/市值/涨跌停价), HTTP only |
| 6 | EastMoney | 龙虎榜/融资融券/大宗/股东户数/分红/资金流/研报/快讯/新闻/板块 |
| 7 | THS | 热点题材/北向资金/快讯 (backup) |
| 7 | Baidu | 新闻搜索 (backup for EastMoney), requires `BAIDU_API_KEY` |
| 8 | Cninfo | 公告检索 |
| 9 | Myquant | Last-resort backup (d/w/m/minute/quote/index), requires `MYQUANT_TOKEN` |

### A-share Indices (CSI)

| Priority | Source | Note |
|----------|--------|------|
| 0 | Tushare | Requires API token, uses `index_daily` API |
| 1 | Baostock | Uses `sh.XXXXXX` / `sz.XXXXXX` format |
| 2 | Akshare | Uses `index_zh_a_hist` API |
| 3 | Yfinance | Uses `.SS` / `.SZ` suffix |
| 9 | Myquant | Last-resort backup |

### US Stocks

| Priority | Source | Note |
|----------|--------|------|
| 0 | Yfinance | Primary source, falls back to Stooq |

### US Indices

| Priority | Source | Note |
|----------|--------|------|
| 0 | Yfinance | Uses `^GSPC`, `^DJI` etc. |

### HK Stocks

| Priority | Source | Note |
|----------|--------|------|
| 0 | Akshare | Primary, uses `stock_hk_hist` API |
| 1 | Yfinance | Fallback, uses `.HK` suffix |
| 9 | Myquant | Last-resort backup |

### HK Indices

| Priority | Source | Note |
|----------|--------|------|
| 0 | Yfinance | Uses `^HSI`, `^HSCE` format |
| 1 | Akshare | Fallback |

---

## Frequency Support

| Provider | Daily (d) | Weekly (w) | Monthly (m) | Minute (1/5/15/30/60) |
|----------|-----------|------------|-------------|------------------------|
| Baostock | ✅ | ✅ | ✅ | ✅ (5/15/30/60, stocks only) |
| Tushare | ✅ | ✅ | ✅ | ❌ |
| Akshare | ✅ | ✅ | ✅ | ❌ |
| Yfinance | ✅ | ✅ | ✅ | ✅ |
| Zhitu | ❌ | ❌ | ❌ | ✅ (5/15/30/60; no 1-min) |
| Zzshare | ✅ | ❌ | ❌ | ✅ (5/15/30/60; no 1-min) |
| Myquant | ✅ | ✅ | ✅ | ✅ |

**Notes:**
- Baostock does NOT support minute frequency for indices (only for stocks).
- `period=1` (1-minute) is only served by Akshare; Zhitu / Zzshare do not support 1-minute data.
- Minute-line K-line is only available for A-share stocks (not US/HK stocks or indices — use `/indices/{code}/intraday` for indices).

---

## Configuration

### Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `TUSHARE_TOKEN` | Tushare Pro API token | - |
| `TUSHARE_PRIORITY` | Override Tushare priority | 0 |
| `BAOSTOCK_PRIORITY` | Override Baostock priority | 1 |
| `AKSHARE_PRIORITY` | Override Akshare priority | 2 |
| `YFINANCE_PRIORITY` | Override Yfinance priority | 3 |
| `ZHITU_TOKEN` | Zhitu API token (realtime + 公司画像) | - |
| `ZHITU_PRIORITY` | Override Zhitu priority | 4 |
| `ZZSHARE_TOKEN` | Zzshare API token (optional — only `stock_info` + `uplimit_stocks` need it; everything else is anonymous-capable) | - |
| `ZZSHARE_PRIORITY` | Override Zzshare priority | 5 |
| `TENCENT_PRIORITY` | Override Tencent priority | 6 |
| `EASTMONEY_PRIORITY` | Override EastMoney priority | 6 |
| `THS_PRIORITY` | Override THS priority | 7 |
| `CNINFO_PRIORITY` | Override Cninfo priority | 8 |
| `MYQUANT_TOKEN` | Myquant (掘金) API token | - |
| `MYQUANT_PRIORITY` | Override Myquant priority (default is 9, last-resort) | 9 |
| `BAIDU_API_KEY` | Baidu Qianfan API key (NEWS_SEARCH backup for EastMoney) | - |
| `BAIDU_PRIORITY` | Override Baidu priority | 7 |
| `BAIDU_NEWS_DOMAINS` | Comma-separated host whitelist for Baidu news search | canonical news subdomains |
| `SERVER_PORT` | Server port | 8888 |
| `SERVER_HOST` | Server host (default changed to loopback; control API must not be public) | 127.0.0.1 |

### Trade Calendar

| Variable | Description | Default |
|----------|-------------|---------|
| `MYQUANT_CALENDAR_START_YEAR` | Start year for `get_trade_calendar` | 2010 |

### Circuit Breaker Configuration (Advanced)

| Variable | Description | Default |
|----------|-------------|---------|
| `CB_FAILURE_THRESHOLD` | Failures before opening circuit | 3 |
| `CB_COOLDOWN_SECONDS` | Time before probing after open (s) | 300 |
| `CB_HALF_OPEN_MAX_CALLS` | Max calls in half-open state | 1 |

---

## Linux Production Deployment

### 1. Create Virtual Environment

```bash
python3 -m venv venv
source venv/bin/activate
pip install -e ".[dev]"
```

### 2. Create Systemd Service

Create `/etc/systemd/system/stock-data.service`:

```ini
[Unit]
Description=Stock Data API Server
After=network.target

[Service]
WorkingDirectory=/path/to/stock_data
Environment="PATH=/path/to/stock_data/venv/bin"
EnvironmentFile=/path/to/stock_data/.env
ExecStart=/path/to/stock_data/venv/bin/python -m stock_data.server
Restart=always
User=your_username

[Install]
WantedBy=multi-user.target
```

### 3. Enable and Start

```bash
sudo systemctl daemon-reload
sudo systemctl enable stock-data
sudo systemctl start stock-data
sudo systemctl status stock-data
```

### 4. View Logs

```bash
sudo journalctl -u stock-data -f
```

### Alternative: nohup (Simple Background Run)

```bash
# Create virtual environment and install
python3 -m venv venv
source venv/bin/activate
pip install -e ".[dev]"

# Run in background
nohup python -m stock_data.server > server.log 2>&1 &

# Check process
ps aux | grep stock_data

# Stop server
pkill -f "python -m stock_data.server"
```

### Alternative: Gunicorn (Higher Performance)

```bash
pip install gunicorn
gunicorn stock_data.server:app --workers 2 --bind 0.0.0.0:8888 --daemon
```

---

## License

MIT
