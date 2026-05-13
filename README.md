# Stock Data Server

A local stock data aggregation server that integrates multiple upstream APIs into a unified REST API for AI agents.

## Features

- **Multi-source aggregation**: Tushare, Baostock, Akshare, Yahoo Finance
- **Automatic failover**: Priority-based source selection with fallback
- **Circuit breaker**: Prevents cascading failures from unavailable sources
- **Unified data format**: Consistent schema across all sources
- **Market support**: A-shares, Hong Kong stocks, US stocks and indices

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

## API Endpoints

### Health Check

```bash
GET /api/v1/health
```

Response:
```json
{
  "status": "ok",
  "available_sources": ["TushareFetcher", "BaostockFetcher", "AkshareFetcher", "YfinanceFetcher"]
}
```

---

### Get Historical K-line Data

```bash
GET /api/v1/stocks/{code}/history?period=daily&days=30
```

**Parameters:**
| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `period` | string | `daily` | K-line period: `daily`, `weekly`, `monthly` |
| `days` | int | 30 | Number of days to retrieve (1-365) |

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
      "ma5": 1690.0,
      "ma10": 1685.0,
      "ma20": 1678.0
    }
  ]
}
```

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
- First call fetches from upstream (Baostock for A-share, ~10-20 seconds)
- Subsequent calls return cached data (~50ms)
- Use `refresh=true` to force update from upstream

**Cached data location:** `stock_data/stock_cache.db` (SQLite)

---

## API Response Caching

The `/quote` and `/history` endpoints are cached using an in-memory TTLCache to avoid repeated upstream API calls when multiple users request the same data within a short window.

| Endpoint | Cache Key | Default TTL |
|----------|-----------|-------------|
| `GET /stocks/{code}/quote` | `stock_code` | 60s |
| `GET /stocks/{code}/history` (daily) | `code:d:days` | 300s |
| `GET /stocks/{code}/history` (weekly) | `code:w:days` | 3600s |
| `GET /stocks/{code}/history` (monthly) | `code:m:days` | 7200s |

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

**Examples:**
```bash
GET /api/v1/stocks/000300/history     # 沪深300 日线
GET /api/v1/stocks/000300/history?period=weekly   # 沪深300 周线
GET /api/v1/stocks/399001/history     # 深证成指
GET /api/v1/stocks/000001/history?period=monthly  # 上证指数 月线
```

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
| 0 | Yfinance | Primary source |
| 1 | Stooq | Fallback |

### US Indices

| Priority | Source | Note |
|----------|--------|------|
| 0 | Akshare | Uses `index_us_stock_sina(.INX)` |
| 1 | Yfinance | Uses `^GSPC`, `^DJI` etc. |

### HK Stocks

| Priority | Source | Note |
|----------|--------|------|
| 0 | Akshare | Uses `stock_hk_hist` API |

### HK Indices

| Priority | Source | Note |
|----------|--------|------|
| 0 | Yfinance | Uses `^HSI`, `^HSCE` format |

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
| `YFINANCE_PRIORITY` | Override Yfinance priority | 4 |
| `SERVER_PORT` | Server port | 8888 |
| `SERVER_HOST` | Server host | 0.0.0.0 |

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
