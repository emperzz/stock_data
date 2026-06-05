# Stock Data Server

A local stock data aggregation server that integrates multiple upstream APIs into a unified REST API for AI agents.

**Two layers in one server:**

- **Data layer** — aggregates 9 upstream APIs (Tushare / Baostock / Akshare / Yfinance / Zhitu / Tencent / EastMoney / THS / Cninfo) with priority-based failover, circuit breaker, and persistent cache.
- **Compute layer** — 14 technical indicators (MA / MACD / BOLL / KDJ / RSI / WR / BIAS / CCI / ATR / OBV / ROC / DMI / SAR / KC) attached to K-line via `?indicators=...`. Pure-compute, no upstream calls.

## Features

- **Multi-source aggregation**: Tushare, Baostock, Akshare, Yfinance, Zhitu, Tencent, EastMoney, THS, Cninfo
- **Automatic failover**: Priority-based source selection with fallback
- **Circuit breaker**: Prevents cascading failures from unavailable sources
- **Unified data format**: Consistent schema across all sources
- **Market support**: A-shares, Hong Kong stocks, US stocks and indices
- **Enhanced quotes**: PE/PB/市值/涨跌停价 via Tencent财经
- **Signal layer**: 龙虎榜/融资融券/大宗交易/股东户数/分红/资金流/热点题材/北向资金
- **Fundamentals**: 研报检索+PDF下载 / 公告检索
- **Technical indicators** (pure compute, 14 built-in): MA · MACD · BOLL · KDJ · RSI · WR · BIAS · CCI · ATR · OBV · ROC · DMI · SAR · KC — attach to K-line via `?indicators=ma,macd,kdj`

## Quick Start

```bash
# Install dependencies
pip install -e ".[dev]"

# Configure (copy and edit .env)
cp .env.example .env
# Edit .env and add your TUSHARE_TOKEN if available

# Run the server
python -m stock_data.server

# Or with uvicorn directly
uvicorn stock_data.server:app --host 0.0.0.0 --port 8888
```

**One-liner with technical indicators:**

```bash
# K-line + MACD + KDJ + BOLL
curl 'http://localhost:8888/api/v1/stocks/600519/history?days=120&indicators=macd,kdj,boll'

# What indicators are available?
curl 'http://localhost:8888/api/v1/indicators/catalog'
```

## API Endpoints

### Health Check

```bash
GET /api/v1/health
```

Response:
```json
{
  "status": "ok",
  "available_sources": ["TushareFetcher", "BaostockFetcher", "AkshareFetcher", "YfinanceFetcher", "ZhituFetcher"]
}
```

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
GET /api/v1/stocks/600519/history?days=120&indicators=ma,macd,kdj,boll,rsi
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
      "change_percent": 1.52,
      "ma5": null,
      "ma10": null,
      "ma20": null,
      "indicators": {}
    }
  ]
}
```

> **Note:** `ma5`/`ma10`/`ma20` are always `null` unless you opt in by
> adding `?indicators=ma` (or any indicator that produces them). The
> legacy "always-on" inline MA computation was removed in favour of
> the explicit `?indicators=` pattern.

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

### Get Historical K-line Data (without indicators)

```bash
GET /api/v1/stocks/{code}/history?period=daily&days=30
```

**Parameters:**
| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `period` | string | `daily` | K-line period: `daily`, `weekly`, `monthly` |
| `days` | int | 30 | Number of days to retrieve (1-365, ignored when `start_date` provided) |
| `start_date` | string | null | Start date (YYYY-MM-DD), overrides `days` parameter |
| `end_date` | string | null | End date (YYYY-MM-DD), defaults to today |
| `adjust` | string | `` | Adjustment type: empty=不复权, `qfq`=前复权, `hfq`=后复权 |
| `indicators` | string | null | Comma-separated list of technical indicators to attach (see [Technical Indicators](#technical-indicators)) |

**Response:**
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
      "change_percent": 1.52,
      "ma5": null,
      "ma10": null,
      "ma20": null,
      "indicators": {}
    }
  ]
}
```

> **Note:** `ma5`/`ma10`/`ma20` are always `null` unless you opt in by
> adding `?indicators=ma` (or any indicator that produces them). The
> legacy "always-on" inline MA computation was removed in favour of
> the explicit `?indicators=` pattern.
>
> For a fully-loaded example response (with indicators), see the
> [Technical Indicators](#technical-indicators) section above.

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
GET /api/v1/stocks?market=cn
GET /api/v1/stocks?market=cn&refresh=true
```

**Parameters:**
| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `market` | string | Required | Market: `cn` (A股), `hk` (港股), `us` (美股) |
| `refresh` | bool | `false` | If `true`, fetch latest from upstream and update cache |

**Response:**
```json
[
  {"code": "000001", "name": "平安银行", "market": "cn"},
  {"code": "000002", "name": "万科A", "market": "cn"},
  {"code": "600519", "name": "贵州茅台", "market": "cn"}
]
```

**Caching behavior:**
- First call fetches from upstream (Tushare for A-share if token, otherwise Akshare)
- Subsequent calls return cached data (~50ms)
- Use `refresh=true` to force update from upstream

**Cached data location:** `stock_data/stock_cache.db` (SQLite). Override via `STOCK_CACHE_DB_PATH` environment variable.

---

### Board Data (Concept / Industry)

```bash
GET /api/v1/boards?type=concept
GET /api/v1/boards?type=industry&include_quote=true
GET /api/v1/boards/BK1048/stocks
GET /api/v1/boards/BK1048/stocks?include_quote=true
```

**Parameters for `GET /boards`:**
| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `type` | string | Required | Board type: `concept` (概念板块) or `industry` (行业板块) |
| `include_quote` | bool | `false` | If `true`, include realtime price/change/market data |
| `source` | string | `eastmoney` | Data source |
| `refresh` | bool | `false` | Force fetch latest from upstream |

**Response (with `include_quote=false`, default):**
```json
{
  "data": [
    {"code": "BK1048", "name": "互联网服务"},
    {"code": "BK0891", "name": "云计算"}
  ]
}
```

**Response (with `include_quote=true`):**
```json
{
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
| `include_quote` | bool | `false` | If `true`, include realtime price/change/volume data for each stock |
| `source` | string | `eastmoney` | Data source |
| `refresh` | bool | `false` | Force fetch latest from upstream |

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
GET /api/v1/stocks/{code}/reports/{info_code}/pdf
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
| `CACHE_TTL_INDEX_INTRADAY` | TTL for index intraday (seconds) | `30` |
| `CACHE_TTL_STOCK_INTRADAY` | TTL for stock intraday (seconds) | `30` |
| `CACHE_TTL_BOARD_LIST` | TTL for board list (seconds) | `300` |
| `CACHE_TTL_BOARD_STOCKS` | TTL for board stocks (seconds) | `300` |

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

### Hong Kong Indices

| Index | Code | Full Name |
|-------|------|----------|
| 恒生指数 | `HSI` | Hang Seng Index |
| 国企指数 | `HSCE` | HSCEI |

**Examples:**
```bash
GET /api/v1/stocks/HSI/history       # 恒生指数
GET /api/v1/stocks/HSCE/history       # 国企指数
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

The server automatically routes requests to the appropriate data source based on the stock/index code:

### A-share Stocks

| Priority | Source | Note |
|----------|--------|------|
| 0 | Tushare | Requires API token |
| 1 | Baostock | Free, no token |
| 2 | Akshare | Fallback |
| 3 | Yfinance | Fallback |
| 4 | Zhitu | Realtime only, requires token |
| 5 | Tencent | Enhanced quotes (PE/PB/市值/涨跌停价), HTTP only |
| 6 | EastMoney | 龙虎榜/融资融券/大宗/股东户数/分红/资金流/研报 |
| 7 | THS | 热点题材/北向资金 |
| 8 | Cninfo | 公告检索 |

### A-share Indices (CSI)

| Priority | Source | Note |
|----------|--------|------|
| 0 | Tushare | Requires API token, uses `index_daily` API |
| 1 | Baostock | Uses `sh.XXXXXX` / `sz.XXXXXX` format |
| 2 | Akshare | Uses `index_zh_a_hist` API |
| 3 | Yfinance | Uses `.SS` / `.SZ` suffix |

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

### HK Indices

| Priority | Source | Note |
|----------|--------|------|
| 0 | Yfinance | Uses `^HSI`, `^HSCE` format |
| 1 | Akshare | Fallback |

---

## Frequency Support

| Provider | Daily (d) | Weekly (w) | Monthly (m) | Minute (5/15/30/60) |
|----------|-----------|------------|-------------|---------------------|
| Baostock | ✅ | ✅ | ✅ | ✅ (stocks only, NOT indices) |
| Tushare | ✅ | ✅ | ✅ | ❌ |
| Akshare | ✅ | ✅ | ✅ | ❌ |
| Yfinance | ✅ | ✅ | ✅ | ✅ |

**Note:** Baostock does NOT support minute frequency for indices (only for stocks).

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
| `ZHITU_TOKEN` | Zhitu API token (for realtime quotes) | - |
| `ZHITU_PRIORITY` | Override Zhitu priority | 4 |
| `TENCENT_PRIORITY` | Override Tencent priority | 5 |
| `EASTMONEY_PRIORITY` | Override EastMoney priority | 6 |
| `THS_PRIORITY` | Override THS priority | 7 |
| `CNINFO_PRIORITY` | Override Cninfo priority | 8 |
| `SERVER_PORT` | Server port | 8888 |
| `SERVER_HOST` | Server host | 0.0.0.0 |

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
