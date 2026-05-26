# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

A Python-based local stock data aggregation server that:
- Integrates 9 upstream stock data APIs (Tushare, Baostock, Akshare, Yfinance, Zhitu, Tencent, EastMoney, THS, Cninfo)
- Normalizes data into a unified format across 7 data layers (行情/研报/信号/资金面/新闻/基础数据/公告)
- Provides a stable REST API for consumption by AI agents like OpenClaw

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│                    API Layer (FastAPI)                   │
│   GET /stocks/{code}/quote   GET /stocks/{code}/history  │
│   GET /stocks/{code}/intraday GET /stocks/{code}/dragon-tiger │
│   GET /stocks/{code}/margin   GET /stocks/{code}/block-trade │
│   GET /stocks/{code}/fund-flow GET /stocks/{code}/reports   │
│   GET /dragon-tiger/daily     GET /hot/topics              │
│   GET /north-flow/realtime    GET /indices/{code}/quote     │
├─────────────────────────────────────────────────────────┤
│                    StockService                          │
│         Unified interface for data access                 │
├─────────────────────────────────────────────────────────┤
│                 DataFetcherManager                        │
│    Priority-based failover, circuit breaker, caching       │
├─────────────────────────────────────────────────────────┤
│                   Source Adapters                         │
│  TushareFetcher  BaostockFetcher  AkshareFetcher  YfinanceFetcher ...    │
│  TencentFetcher  EastMoneyFetcher  ThsFetcher  CninfoFetcher              │
├─────────────────────────────────────────────────────────┤
│              Upstream Stock Data APIs                    │
```

## Directory Structure

```
stock_data/
├── __init__.py
├── server.py
├── api/
│   ├── __init__.py
│   ├── routes.py
│   ├── schemas.py
│   └── cache.py
└── data_provider/
    ├── __init__.py                  # Public API re-exports
    ├── base.py                      # BaseFetcher, DataFetcherManager, DataCapability
    ├── core/
    │   ├── __init__.py
    │   └── types.py                # UnifiedRealtimeQuote, CircuitBreaker, safe_float/int
    ├── fetchers/
    │   ├── __init__.py
    │   ├── index_symbols.py        # Index mappings (CSI/HK/US)
    │   ├── akshare_fetcher.py
    │   ├── baostock_fetcher.py
    │   ├── tushare_fetcher.py
    │   ├── yfinance_fetcher.py
    │   └── zhitu_fetcher.py
    ├── cache/
    │   ├── __init__.py
    │   ├── api_cache.py            # Compatibility re-export module
    │   ├── stock_list_cache.py
    │   └── trade_calendar_cache.py
    └── utils/
        ├── __init__.py
        └── normalize.py            # normalize_stock_code, market_tag, etc.
```

## Core Components

### `data_provider/base.py`
- `BaseFetcher`: Abstract base defining `_fetch_raw_data()`, `_normalize_data()`, `get_daily_data()`, `get_realtime_quote()`
- `DataFetcherManager`: Orchestrates fetchers with priority-based failover, circuit breakers, and capability-based routing
- `DataCapability`: Flag enum for fetcher capability declarations (see below)

### `data_provider/fetchers/`
- Each source has its own fetcher: `baostock_fetcher.py`, `akshare_fetcher.py`, `yfinance_fetcher.py`, `tushare_fetcher.py`, `zhitu_fetcher.py`, `tencent_fetcher.py`, `eastmoney_fetcher.py`, `ths_fetcher.py`, `cninfo_fetcher.py`
- Each fetcher handles:
  - Source-specific API calls
  - Rate limiting (random jitter, User-Agent rotation)
  - Data normalization to standard format
  - Retry with exponential backoff (using `tenacity`)

### `data_provider/core/types.py`
- `UnifiedRealtimeQuote`: Dataclass for normalized realtime quotes
- `CircuitBreaker`: Thread-safe circuit breaker implementation
- `safe_float()`, `safe_int()`: Type-safe conversion utilities

### `data_provider/utils/normalize.py`
- `normalize_stock_code()`: Handles various input formats (SH600519 → 600519, etc.)
- `market_tag()`: Returns market tag (csi/us/hk)
- `is_us_market()`, `is_hk_market()`: Market detection utilities

## Standardized Data Schema

**Historical K-line columns** (`STANDARD_COLUMNS`):
```
date, open, high, low, close, volume, amount, pct_chg
```

**Realtime quote fields**:
```
code, name, source, price, change_pct, change_amount,
volume, amount, volume_ratio, turnover_rate, amplitude,
open_price, high, low, pre_close, pe_ratio, pb_ratio, total_mv, circ_mv
```

## Provider API Documentation

### BaostockFetcher (Priority 1, A股 only, Free)

**API**: `bs.query_history_k_data_plus(code, fields, start_date, end_date, frequency, adjustflag)`

**Frequency**: `d`=日线, `w`=周线, `m`=月线, `5/15/30/60`=分钟线（不适用指数）

**Fields (日线)**:
```
date, open, high, low, close, preclose, volume, amount, adjustflag, turn, tradestatus, pctChg, isST
```

**Note**: Baostock has **NO realtime quotes API** - only historical data.

**Links**: https://baostock.com/mainContent?file=stockKData.md

---

### AkshareFetcher (Priority 2, A股+HK, Free)

**A-share API**: `ak.stock_zh_a_hist(symbol, period, start_date, end_date, adjust)`
- `period`: `'daily'`, `'weekly'`, `'monthly'`
- `adjust`: `''`=不复权, `'qfq'`=前复权, `'hfq'`=后复权

**HK API**: `ak.stock_hk_hist(symbol, period, start_date, end_date, adjust)`
- Same parameters as A-share

**Output columns (中文)**:
```
日期, 股票代码, 开盘, 收盘, 最高, 最低, 成交量, 成交额, 振幅, 涨跌幅, 涨跌额, 换手率
```

**Links**: https://akshare.akfamily.xyz/data/stock/stock.html

---

### TushareFetcher (Priority 0, A股, Requires Token)

**APIs**: `api.query('daily', ...)`, `api.query('weekly', ...)`, `api.query('monthly', ...)`

**Output columns** (same for daily/weekly/monthly):
```
ts_code, trade_date, open, high, low, close, pre_close, change, pct_chg, vol, amount
```

**Units**:
- `vol`: 手 (1手=100股) → convert to shares
- `amount`: 千元 → convert to yuan

**Note**: All three interfaces return **未复权行情**. For 复权数据, use the 复权因子接口 separately.

**Links**: https://tushare.pro/document/2?doc_id=27 (daily), doc_id=144 (weekly), doc_id=145 (monthly)

---

### YfinanceFetcher (Priority 3, US+A股+HK, Free)

**API**: `yf.download(tickers, start, end, auto_adjust=True)`

**Supports**: US stocks, US indices (via `US_INDEX_MAP`), A-share (.SS/.SZ), HK (.HK)

**Frequency**: Only daily (intervals via `interval` param: `'1d'`, `'1wk'`, `'1mo'`, `'5m'`, etc.)

---

### ZhituFetcher (Priority 4, A股 realtime only, Requires Token)

**API**: `https://api.zhituapi.com/hs/real/ssjy/{stock_code}?token={token}`

**Supports**: A股 realtime quotes only (no historical K-line data)

**Token**: Set via `ZHITU_TOKEN` environment variable

**Output fields**:
```
p (price), pc (change_pct), ud (change_amount), v (volume),
cje (amount), o (open), h (high), l (low), yc (pre_close),
zf (amplitude), lb (volume_ratio), hs (turnover_rate), pe (pe_ratio),
sjl (pb_ratio), sz (total_mv), lt (circ_mv)
```

**Note**: Zhitu API returns rich realtime data but **does not support historical K-line data**.
It is used as a fallback for realtime quotes only.

**Links**: https://www.zhituapi.com/hsstockapi.html

---

### TencentFetcher (Priority 5, A股+HK, Free)

**API**: `https://qt.gtimg.cn/q={prefix_code}` (HTTP GET, GBK encoding)

**Supports**: A-share + HK realtime quotes with enhanced valuation fields

**Key enhanced fields** (88-field `~` delimited response):
- Index 39: PE(TTM), Index 46: PB, Index 44/45: 总市值/流通市值(亿)
- Index 47/48: 涨停价/跌停价, Index 49: 量比, Index 52: PE(静)

**Note**: Tencent财经 provides enhanced valuation data not available from other providers. Uses `urllib` for GBK response handling.

---

### EastMoneyFetcher (Priority 6, A股, Free)

**Datacenter domain** (datacenter-web.eastmoney.com):
- 龙虎榜: `RPT_DAILYBILLBOARD_DETAILSNEW`, 席位: `RPT_BILLBOARD_DAILYDETAILSBUY/SELL`
- 融资融券: `RPTA_WEB_RZRQ_GGMX`
- 大宗交易: `RPT_DATA_BLOCKTRADE`
- 股东户数: `RPT_HOLDERNUMLATEST`
- 分红送转: `RPT_SHAREBONUS_DET`

**push2 domain** (push2.eastmoney.com / push2his.eastmoney.com):
- 资金流分钟级: `/api/qt/stock/fflow/kline/get?klt=1`
- 资金流120日: `/api/qt/stock/fflow/daykline/get?lmt=120`

**ReportAPI domain** (reportapi.eastmoney.com):
- 研报列表: `/report/list`, PDF: `https://pdf.dfcfw.com/pdf/H3_{info_code}_1.pdf`

**Note**: All domains share a unified `_datacenter_query()` helper. No authentication required.

---

### ThsFetcher (Priority 7, A股, Free)

**热点题材**: `http://zx.10jqka.com.cn/event/api/getharden/`
- Returns daily hot stocks with reason tags (题材归因), zero-auth, ~73ms

**北向资金**: `https://data.hexin.cn/market/hsgtApi/method/dayChart/`
- Minute-level 沪股通/深股通 cumulative net buy data (262 time points per day)

**Note**: No API key required. Simple HTTP GET with User-Agent header.

---

### CninfoFetcher (Priority 8, A股, Free)

**API**: `https://www.cninfo.com.cn/new/hisAnnouncement/query` (HTTP POST)

**Supports**: Full-text announcement search and retrieval for A-share stocks

**orgId format**: `gssh0{code}` (Shanghai), `gssz0{code}` (Shenzhen), `gsbj0{code}` (Beijing)

**Note**: Returns announcement title, type, date, and detail page URL. PDF download not yet implemented.

---

## Provider Frequency Support

| Provider | d | w | m | 5m | 15m | 30m | 60m |
|----------|---|---|---|----|----|-----|-----|
| BaostockFetcher | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| AkshareFetcher | ✅ | ✅ | ✅ | ❌ | ❌ | ❌ | ❌ |
| TushareFetcher | ✅ | ✅ | ✅ | ❌ | ❌ | ❌ | ❌ |
| YfinanceFetcher | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |

**Fallback**: Server queries providers in priority order. If provider doesn't support the requested frequency, it raises `DataFetchError` and the next provider is tried.

## Capability-Based Routing

Every fetcher declares its capabilities via `supported_data_types: DataCapability`, a `Flag` enum in `base.py`:

```python
class DataCapability(Flag):
    HISTORICAL_DWM   # 日/周/月 K线 (d/w/m)
    HISTORICAL_MIN   # 分钟 K线 (1/5/15/30/60m)
    REALTIME_QUOTE   # 实时报价
    STOCK_LIST       # 股票列表 (get_all_stocks)
    STOCK_NAME       # 股票名称 (get_stock_name)
    TRADE_CALENDAR   # 交易日历
    STOCK_BOARD      # 板块数据（概念/行业板块列表）
    INDEX_QUOTE      # 指数实时行情
    INDEX_HISTORICAL # 指数历史K线 (d/w/m)
    INDEX_INTRADAY   # 指数日内分时 (1/5/15/30/60m)
    STOCK_ZT_POOL    # 涨跌停股池
    DRAGON_TIGER     # 龙虎榜（个股+全市场）
    MARGIN_TRADING   # 融资融券
    BLOCK_TRADE      # 大宗交易
    HOLDER_NUM       # 股东户数变化
    DIVIDEND         # 分红送转
    FUND_FLOW        # 资金流（个股资金流分钟级+120日）
    HOT_TOPICS       # 热点题材（同花顺当日强势股+题材归因）
    NORTH_FLOW       # 北向资金（沪股通/深股通分钟流向）
    RESEARCH_REPORT  # 研报
    ANNOUNCEMENT     # 公告
```

**Hard rule**: EVERY data access method in `DataFetcherManager` MUST route through
`_filter_by_capability(market, capability)`. Never hardcode a specific fetcher class
(e.g. `AkshareFetcher()`) — that bypasses priority-based failover and is forbidden.
If a new data type needs routing, add a capability flag and declare it on the
fetchers that support it.

`DataFetcherManager._filter_by_capability(market, capability)` filters fetchers by market AND capability flag. Each data method routes through this filter:

| API Method | Capability Used |
|------------|----------------|
| `get_kline_data` (d/w/m) | `HISTORICAL_DWM` |
| `get_kline_data` (5/15/30/60) | `HISTORICAL_MIN` |
| `get_realtime_quote` | `REALTIME_QUOTE` |
| `get_intraday_data` | `HISTORICAL_MIN` |
| `get_stock_name` | `STOCK_NAME` |
| `list_stocks` (via `_filter_by_capability`) | `STOCK_LIST` |
| `get_trade_calendar` | `TRADE_CALENDAR` |
| `get_all_concept_boards` / `get_all_industry_boards` | `STOCK_BOARD` |
| `get_concept_board_stocks` / `get_industry_board_stocks` | `STOCK_BOARD` |
| `get_index_realtime_quote` | `INDEX_QUOTE` |
| `get_index_historical` | `INDEX_HISTORICAL` |
| `get_index_intraday` | `INDEX_INTRADAY` |
| `get_zt_pool` | `STOCK_ZT_POOL` |
| `get_dragon_tiger` | `DRAGON_TIGER` |
| `get_margin_trading` | `MARGIN_TRADING` |
| `get_block_trade` | `BLOCK_TRADE` |
| `get_holder_num_change` | `HOLDER_NUM` |
| `get_dividend` | `DIVIDEND` |
| `get_fund_flow_minute` / `get_fund_flow_120d` | `FUND_FLOW` |
| `get_hot_topics` | `HOT_TOPICS` |
| `get_north_flow` | `NORTH_FLOW` |
| `get_reports` | `RESEARCH_REPORT` |
| `get_announcements` | `ANNOUNCEMENT` |

**Fetcher capability declarations:**

| Fetcher | Capabilities |
|---------|-------------|
| BaostockFetcher | `HISTORICAL_DWM \| HISTORICAL_MIN \| TRADE_CALENDAR \| INDEX_HISTORICAL` |
| AkshareFetcher | `HISTORICAL_DWM \| REALTIME_QUOTE \| STOCK_LIST \| STOCK_NAME \| TRADE_CALENDAR \| STOCK_BOARD \| INDEX_QUOTE \| INDEX_HISTORICAL \| INDEX_INTRADAY` |
| TushareFetcher | `HISTORICAL_DWM \| REALTIME_QUOTE \| STOCK_LIST \| STOCK_NAME \| INDEX_HISTORICAL` |
| YfinanceFetcher | `HISTORICAL_DWM \| HISTORICAL_MIN \| REALTIME_QUOTE \| INDEX_HISTORICAL \| INDEX_QUOTE` |
| ZhituFetcher | `REALTIME_QUOTE \| STOCK_ZT_POOL` |
| TencentFetcher | `REALTIME_QUOTE` (增强字段: PE/PB/市值/涨跌停价) |
| EastMoneyFetcher | `DRAGON_TIGER \| MARGIN_TRADING \| BLOCK_TRADE \| HOLDER_NUM \| DIVIDEND \| FUND_FLOW \| RESEARCH_REPORT` |
| ThsFetcher | `HOT_TOPICS \| NORTH_FLOW` |
| CninfoFetcher | `ANNOUNCEMENT` |

**Index routing design**: Each fetcher that declares an INDEX_* capability must implement the corresponding public method (`get_index_realtime_quote`, `get_index_historical`, `get_index_intraday`). The Manager calls these methods directly — no `hasattr` checks, no fallback to stock methods. Internally, a fetcher may delegate to shared data processing logic (e.g. `get_index_historical` → `get_kline_data`), but the public interface is always the dedicated index method.

**Anti-pattern**: Do NOT use `supports_historical` or `supports_realtime` — these are deprecated. Use `supported_data_types` with `DataCapability` flags.

## Symbol Conventions

| Market | Format | Examples |
|--------|--------|----------|
| A-share (Shanghai) | 6 digits + `.SS` | `600519.SS`, `000001.SZ` |
| A-share (Shenzhen) | 6 digits + `.SZ` | `000001.SZ` |
| HK stocks | `HK` + 5 digits | `HK00700`, `HK01810` |
| US stocks | 1-5 letters | `AAPL`, `TSLA` |
| US indices | Mapped to yfinance | `SPX` → `^GSPC` |

## Key Design Patterns

### Circuit Breaker
Per-source circuit breakers prevent cascading failures:
- CLOSED (normal) → OPEN (after N failures) → HALF_OPEN (probe) → CLOSED (recover)
- Configurable failure threshold and cooldown

### Rate Limiting / Anti-Banning
- Random jitter between requests (1.5-3.0s default)
- Random User-Agent rotation from pool
- Exponential backoff retry on failure

### Market-Aware Routing
Manager routes requests based on stock code and capability:
- US stocks → YfinanceFetcher (primary), Stooq fallback
- A-shares → BaostockFetcher (primary), AkshareFetcher (fallback)
- Each fetcher declares supported markets via `supported_markets` and capabilities via `supported_data_types: DataCapability`

### Code Normalization
`normalize_stock_code()` handles various input formats:
- `SH600519` → `600519`, `sz000001` → `000001`, `HK00700` → `HK00700`

## Common Commands

```bash
# Install dependencies
pip install -e ".[dev]"

# Run the server
python -m stock_data.server

# Run tests
pytest

# Run a single test
pytest tests/test_adapter.py -v

# Lint
ruff check .

# Format
ruff format .
```

## Configuration

Environment variables (see `.env.example`):
- `TUSHARE_TOKEN` - Tushare Pro API token
- `BAOSTOCK_PRIORITY` - Override Baostock fetcher priority (default: 1)
- `AKSHARE_PRIORITY` - Override Akshare fetcher priority (default: 2)
- `YFINANCE_PRIORITY` - Override Yfinance fetcher priority (default: 3)
- `ZHITU_TOKEN` - Zhitu API token for realtime quotes
- `ZHITU_PRIORITY` - Override Zhitu fetcher priority (default: 4)
- `ENABLE_API_CACHE` - Enable/disable API response caching (default: true)
- `TENCENT_PRIORITY` - Override Tencent fetcher priority (default: 5)
- `EASTMONEY_PRIORITY` - Override EastMoney fetcher priority (default: 6)
- `THS_PRIORITY` - Override ThsFetcher priority (default: 7)
- `CNINFO_PRIORITY` - Override Cninfo fetcher priority (default: 8)
- `CACHE_TTL_STOCK_INTRADAY` - Stock intraday cache TTL in seconds (default: 30)
- `CACHE_TTL_INDEX_INTRADAY` - Index intraday cache TTL in seconds (default: 30)

## Anti-Patterns to Avoid

- **Don't** put all code in one file — split fetchers into separate modules
- **Don't** use verbose Hungarian notation like `_stock_name_cache_lock` — use `_lock` on the cache dict itself
- **Don't** mix inline imports and top-level imports inconsistently
- **Don't** add features not needed for core data fetching (defer fundamental data, sentiment, etc.)
- **Don't** create deeply nested manager hierarchies — one `DataFetcherManager` is sufficient
- **Don't** hardcode a specific fetcher class (e.g. `AkshareFetcher()`) in `DataFetcherManager` methods — ALL data access must route through `_filter_by_capability(market, capability)`. This applies to existing methods AND any new capability added in the future. If your new feature needs a data type that doesn't fit existing capabilities, add a new `DataCapability` flag, declare it on the fetchers that support it, and route through `_filter_by_capability`.
- **Don't** cache realtime quote data in SQLite — the `stock_board` and `stock_board_stock` tables store metadata only (code, name, type, timestamps). Quote/price data is always fetched live from the API.