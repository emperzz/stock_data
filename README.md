# Stock Data Server

A local stock data aggregation server that integrates 13 upstream stock data APIs into a unified REST API for AI agents.

**Four layers in one server:**

- **API Layer (FastAPI)** — declarative routes; metadata-driven via `@endpoint_meta`.
- **Indicator compute layer (module functions)** — `MA · MACD · BOLL · KDJ · RSI · WR · BIAS · CCI · ATR · OBV · ROC · DMI · SAR · KC` (14 built-in). Sits on top of the manager; no fetcher involvement.
- **DataFetcherManager** — capability-routed, priority-based failover + circuit breaker + TTLCache.
- **Source Adapters** — `Tushare · Baostock · Akshare · Yfinance · Zhitu · Zzshare · Tencent · EastMoney · THS · Cninfo · Cls · Myquant · Baidu` (13 fetchers).

Persistence (on-disk SQLite for stock lists / board metadata / trade calendar / ZT pools) is owned by `data_provider/persistence/` and seeded transparently by the manager. Board persistence supports all types (concept/industry/index/special), keyed by (board_type, source). An interactive API Explorer is served at `/explorer/`.

## Features

- **Multi-source aggregation** (13 fetchers): Tushare, Baostock, Akshare, Yfinance, Zhitu, Zzshare, Tencent, EastMoney, THS, Cninfo, Cls, Myquant, Baidu
- **Board data** (concept / industry / index / special): source-routed across `ths` (concept + industry, d-only K-line), `eastmoney` (concept + industry, d/w/m + minutes K-line), `zhitu` (all 4 types, no K-line); `zzshare` unified under `ths` since 2026-07-08. THS also serves board realtime quote / news (news.10jqka) / 炒作周期 (F10).
- **Automatic failover**: priority-based source selection with capability-routed fallback
- **Circuit breaker**: prevents cascading failures from unavailable sources
- **Persistent metadata cache**: SQLite for stock lists, board metadata, trade calendar, ZT/DT/ZBGC pools (separate from in-process TTLCache)
- **Unified data format**: consistent schema across all sources
- **Market support**: A-shares, Hong Kong stocks, US stocks and indices (CSI / HK / US)
- **Enhanced quotes**: PE/PB/市值/换手率/振幅 via Tencent财经
- **Signal layer**: 龙虎榜/融资融券/大宗交易/股东户数/分红/资金流/热点题材/北向资金
- **News**: 关键词搜索 (EastMoney → Baidu 备份) / 7×24 快讯 (EastMoney → THS 备份) / 个股新闻 (EastMoney → THS 备份) / **财联社早报 + 焦点复盘** (按日取全文本, CLS subject 1151/1135, 20-28 天窗口) / 正文提取
- **Fundamentals**: 公司画像 (Zhitu → Myquant) / 研报检索+PDF下载 / 公告检索
- **Technical indicators** (pure compute, 14 built-in): MA · MACD · BOLL · KDJ · RSI · WR · BIAS · CCI · ATR · OBV · ROC · DMI · SAR · KC — attach to K-line via `?indicators=ma,macd,kdj`
- **API Explorer** (`/explorer/`): interactive docs, search, market/fetcher filters, Stage 2 fetcher drill-down

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
curl 'http://localhost:8888/api/v1/stocks/600519/kline?days=120&indicators=macd,kdj,boll'

# What indicators are available?
curl 'http://localhost:8888/api/v1/indicators'

# Health check (root-mounted, k8s/lb convention)
curl 'http://localhost:8888/healthz?details=true'

# 财联社 早报 (today, Asia/Shanghai)
curl 'http://localhost:8888/api/v1/news/morning-briefing?date=2026-07-14'

# 财联社 焦点复盘
curl 'http://localhost:8888/api/v1/news/market-recap?date=2026-07-14'
```

## API Endpoints

Full per-endpoint reference (request params, response shapes, JSON
examples) lives in **[api-reference.md](api-reference.md)**,
or browse it interactively at `/explorer/` once the server is running.

Quick index: health · technical indicators · K-line · realtime quote ·
company profile · per-stock news · trade calendar · indices · stock list ·
boards (list / stocks / quote / news / surges / history) · 涨跌停股池 ·
margin · block trade · holder count · dividend · dragon-tiger · fund flow ·
hot topics · north-bound flow · research reports · announcements ·
news search / flash / content · 财联社早报 / 焦点复盘.

## API Response Caching

The `/quote` and `/kline` endpoints are cached using an in-memory TTLCache to avoid repeated upstream API calls when multiple users request the same data within a short window.

| Endpoint | Cache Key | Default TTL |
|----------|-----------|-------------|
| `GET /stocks/{code}/quote` | `stock_code` | 60s |
| `GET /stocks/{code}/kline` (daily) | `code:d:days` | 300s |
| `GET /stocks/{code}/kline` (weekly) | `code:w:days` | 3600s |
| `GET /stocks/{code}/kline` (monthly) | `code:m:days` | 7200s |
| `GET /indices/{code}/quote` | `idx_quote:{code}` | 60s |
| `GET /indices/{code}/kline` | `{code}:{freq}:{days}` | 300/3600/7200s (daily/weekly/monthly); 30s for 1m/5m/15m/30m/60m |

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

**Board endpoints**: the `source` field in the response echoes the actual
data origin (fetcher name on cache miss; `"persistence"` on cache hit).
Board data is source-routed — different sources use incompatible
classification systems, so the source in the response generally matches
the `source` query parameter, with two exceptions:
- `source=ths` on `/boards` internally merges `ThsFetcher` +
  `ZzshareFetcher` (platecode backfill); the public surface tags both
  as `source="ths"`.
- `/boards/{code}/stocks` returns **two** source fields:
  `query_source` (user-supplied `?source=`, canonicalized) and
  `data_source` (actual origin: fetcher name or `"persistence"`).

`/stocks` and `/calendar` currently do NOT expose `source` (their response models have no such field) — the persistence origin is still computed and discarded. This is a YAGNI choice; if needed later, add `source: str` to those response models and the route layer is already wired to pass it through.

---

## API Explorer

An interactive docs UI is mounted at `/explorer/` (after `python -m stock_data.server`, open `http://localhost:8888/explorer/`). It is generated server-side from `app.routes` + the `@endpoint_meta` decorator on each route — the page fetches `GET /control/api-manifest` on load and renders a sidebar with search, market filter, fetcher filter, and a right-side response panel.

**Features:**

- **Search** — filter by endpoint path / summary
- **Market filter** — `csi` / `hk` / `us`
- **Fetcher filter** — `BaostockFetcher` / `AkshareFetcher` / `YfinanceFetcher` / etc.
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
GET /api/v1/stocks/600519/kline       # 贵州茅台
GET /api/v1/stocks/000001/kline       # 平安银行
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
GET /api/v1/indices/000300/kline       # 沪深300 日线
GET /api/v1/indices/000300/kline?period=weekly    # 沪深300 周线
GET /api/v1/indices/399001/kline       # 深证成指
GET /api/v1/indices/000001/kline?period=monthly   # 上证指数 月线
```

**Index intraday (minute-level):**
```bash
GET /api/v1/indices/399006/kline?period=5m  # 创业板指 5-minute
GET /api/v1/indices/000300/kline?period=15m # 沪深300 15-minute
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
GET /api/v1/stocks/HK00700/kline      # 腾讯控股
GET /api/v1/stocks/HK01810/kline     # 小米集团
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
GET /api/v1/indices/SPX/kline        # S&P 500 日线
GET /api/v1/indices/SPX/kline?period=weekly     # S&P 500 周线
GET /api/v1/indices/DJI/kline        # 道琼斯工业平均
GET /api/v1/indices/IXIC/kline       # 纳斯达克综合
```

---

## Data Source Routing

The server automatically routes requests to the appropriate data source based on the stock/index code and the capability required. Default priorities are overridable via `*_PRIORITY` env vars (see [Configuration](#configuration)).

### A-share Stocks

| Priority | Source | Note |
|----------|--------|------|
| 0 | Tushare | Requires `TUSHARE_TOKEN` |
| 1 | Baostock | Free, no token |
| 2 | Zzshare | A-share multi-capability (d/5/15/30/60/股票列表/交易日历/板块/龙虎榜/热点题材/公司画像); anonymous-capable, `ZZSHARE_TOKEN` optional (only `stock_info` + `uplimit_stocks` need it). **Board endpoints: not a public source label** since 2026-07-08 unification; still used internally for platecode backfill on `?source=ths` board-list and as primary `include_quote=false` fallback on `/boards/{code}/stocks`. |
| 3 | Akshare | Fallback (also serves 1m, no adjust) |
| 4 | Yfinance | Fallback |
| 5 | Zhitu | Realtime quotes + 公司画像 + 板块 (含 stock→boards), minute fallback (5/15/30/60), requires `ZHITU_TOKEN` |
| 5 | Tencent | Enhanced quotes (PE/PB/市值/涨跌停价), HTTP only |
| 6 | EastMoney | 龙虎榜/融资融券/大宗/股东户数/分红/资金流/研报/快讯/新闻/板块 (concept+industry only) /个股资讯/公告 |
| 7 | THS | 热点题材/北向资金/快讯 (backup) / 板块 K 线 (d-only, concept+industry) / 板块实时行情 / 板块新闻 (news.10jqka) / 板块炒作周期 (F10) / 个股新闻 + 个股公告 P7 备份 |
| 7 | Baidu | 新闻搜索 (backup for EastMoney), requires `BAIDU_API_KEY` |
| 8 | Cninfo | 公告检索 |
| 8 | **CLS** | **财联社 早报 (subject 1151) + 焦点复盘 (subject 1135)**；按日取全文本, 20-28 天窗口 (无上游分页) |
| 9 | Myquant | Last-resort backup (d/w/m/minute/quote/index-d), requires `MYQUANT_TOKEN` |

### A-share Indices (CSI)

| Priority | Source | Note |
|----------|--------|------|
| 0 | Tushare | Requires API token, uses `index_daily` API; d/w/m only (no minutes) |
| 1 | Baostock | Uses `sh.XXXXXX` / `sz.XXXXXX` format; d/w/m only (no minutes) |
| 3 | Akshare | Uses `index_zh_a_hist` API; full d/w/m + 5/15/30/60m; 1m via `index_zh_a_hist_min_em` (single-day window) |
| 4 | Yfinance | Uses `.SS` / `.SZ` suffix; d/w/m + 5/15/30/60m; no 1m; no hfq |
| 5 | Zhitu | `/hz/history/fsjy/<code>.<mkt>/<level>` — added 2026-07-06; d/w/m + 5/15/30/60m; csi only; no adjust (指数无复权) |
| 9 | Myquant | Last-resort backup; **d only** for indices (no minutes) |

### US Stocks

| Priority | Source | Note |
|----------|--------|------|
| 4 | Yfinance | Primary source, falls back to Stooq |

### US Indices

| Priority | Source | Note |
|----------|--------|------|
| 4 | Yfinance | Uses `^GSPC`, `^DJI` etc. |

### HK Stocks

| Priority | Source | Note |
|----------|--------|------|
| 3 | Akshare | Primary, uses `stock_hk_hist` API |
| 4 | Yfinance | Fallback, uses `.HK` suffix |
| 9 | Myquant | Last-resort backup |

### HK Indices

| Priority | Source | Note |
|----------|--------|------|
| 4 | Yfinance | Primary, uses `^HSI`, `^HSCE` format |
| 3 | Akshare | Fallback |

---

## Frequency Support

**Stocks (csi):**

| Provider | d | w | m | 1m | 5m | 15m | 30m | 60m |
|----------|---|---|---|----|----|-----|-----|-----|
| Baostock | ✅ | ✅ | ✅ | ❌ | ✅ | ✅ | ✅ | ✅ |
| Akshare | ✅ | ✅ | ✅ | ✅¹ | ✅ | ✅ | ✅ | ✅ |
| Tushare | ✅ | ✅ | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ |
| Yfinance | ✅ | ✅ | ✅ | ❌ | ✅ | ✅ | ✅ | ✅² |
| Zhitu | ❌ | ❌ | ❌ | ❌ | ✅³ | ✅³ | ✅³ | ✅³ |
| Zzshare | ✅ | ❌ | ❌ | ✅ | ✅ | ✅ | ✅ | ✅ |
| Myquant | ✅ | ✅ | ✅ | ❌ | ✅ | ✅ | ✅ | ✅ |

¹ Akshare 1m 走 `stock_zh_a_hist_min_em`,需单日窗口(start_date=end_date),1m 拒绝 adjust。
² Yfinance 拒绝 hfq(Stage 2 即剔除);HK/US 股票同 5m-60m。
³ Zhitu 股票 K 线强制 5/15/30/60 minute,无 d/w/m(分钟回退);无 qfq/hfq。

**Indices (csi, no adjust 适用 — 指数无复权):**

| Provider | d | w | m | 1m | 5m | 15m | 30m | 60m |
|----------|---|---|---|----|----|-----|-----|-----|
| Baostock | ✅ | ✅ | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ |
| Tushare | ✅ | ✅ | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ |
| Akshare | ✅ | ✅ | ✅ | ✅⁴ | ✅ | ✅ | ✅ | ✅ |
| Yfinance | ✅ | ✅ | ✅ | ❌ | ✅ | ✅ | ✅ | ✅² |
| Zhitu | ✅ | ✅ | ✅ | ❌ | ✅ | ✅ | ✅ | ✅ |
| Myquant | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ |

⁴ Akshare 指数 1m 走 `index_zh_a_hist_min_em`,需单日窗口(start_date=end_date)。

**Notes:**
- 1-minute stock data: Akshare + Zzshare; Zhitu / Yfinance / Myquant / Baostock / Tushare do not support 1m.
- 1-minute index data: only Akshare (csi, single-day window). Zhitu has no 1m endpoint; Myquant index is d-only.
- Minute-line K-line is only available for A-share stocks and CSI indices (not US/HK stocks or US indices). Use `period=5m` etc. on `/stocks/{code}/kline` or `/indices/{code}/kline` — there is no separate `/intraday` route.

---

## Configuration

### Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `TUSHARE_TOKEN` | Tushare Pro API token | - |
| `TUSHARE_PRIORITY` | Override Tushare priority | 0 |
| `BAOSTOCK_PRIORITY` | Override Baostock priority | 1 |
| `ZZSHARE_TOKEN` | Zzshare API token (optional — only `stock_info` + `uplimit_stocks` need it; everything else is anonymous-capable) | - |
| `ZZSHARE_PRIORITY` | Override Zzshare priority | 2 |
| `AKSHARE_PRIORITY` | Override Akshare priority | 3 |
| `YFINANCE_PRIORITY` | Override Yfinance priority | 4 |
| `ZHITU_TOKEN` | Zhitu API token (realtime + 公司画像) | - |
| `ZHITU_PRIORITY` | Override Zhitu priority | 5 |
| `TENCENT_PRIORITY` | Override Tencent priority | 5 |
| `EASTMONEY_PRIORITY` | Override EastMoney priority | 6 |
| `THS_PRIORITY` | Override THS priority | 7 |
| `BAIDU_API_KEY` | Baidu Qianfan API key (NEWS_SEARCH backup for EastMoney) | - |
| `BAIDU_PRIORITY` | Override Baidu priority | 7 |
| `CNINFO_PRIORITY` | Override Cninfo priority | 8 |
| `CLS_PRIORITY` | Override CLS (财联社) priority | 8 |
| `MYQUANT_TOKEN` | Myquant (掘金) API token | - |
| `MYQUANT_PRIORITY` | Override Myquant priority (default is 9, last-resort) | 9 |
| `BAIDU_NEWS_DOMAINS` | Comma-separated host whitelist for Baidu news search | canonical news subdomains |
| `SERVER_PORT` | Server port | 8888 |
| `SERVER_HOST` | Server host (default changed to loopback; control API must not be public) | 127.0.0.1 |

### Trade Calendar

| Variable | Description | Default |
|----------|-------------|---------|
| `TRADE_CALENDAR_START_YEAR` | Start year for `get_trade_calendar` (zzshare + myquant; akshare is upstream-driven) | 1990 |
| `TRADE_CALENDAR_END_YEAR` | End year for `get_trade_calendar` (zzshare + myquant; akshare is upstream-driven) | current year |
| `MYQUANT_CALENDAR_START_YEAR` | Legacy alias for `TRADE_CALENDAR_START_YEAR` (still honored for backward compat) | — |

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
