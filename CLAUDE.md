# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

A Python-based local stock data aggregation server that:
- Integrates multiple upstream stock data APIs (Tushare, Baostock, Akshare, Yfinance, Zhitu)
- Normalizes data into a unified format
- Provides a stable REST API for consumption by AI agents like OpenClaw

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│                    API Layer (FastAPI)                   │
│   GET /stocks/{code}/quote   GET /stocks/{code}/history  │
├─────────────────────────────────────────────────────────┤
│                    StockService                          │
│         Unified interface for data access                 │
├─────────────────────────────────────────────────────────┤
│                 DataFetcherManager                        │
│    Priority-based failover, circuit breaker, caching       │
├─────────────────────────────────────────────────────────┤
│                   Source Adapters                         │
│  TushareFetcher  BaostockFetcher  AkshareFetcher  YfinanceFetcher ...    │
├─────────────────────────────────────────────────────────┤
│              Upstream Stock Data APIs                    │
```

## Core Components

### `data_provider/base.py`
- `BaseFetcher`: Abstract base defining `_fetch_raw_data()`, `_normalize_data()`, `get_daily_data()`, `get_realtime_quote()`
- `DataFetcherManager`: Orchestrates fetchers with priority-based failover, circuit breakers, and market-aware routing

### `data_provider/{source}_fetcher.py`
- Each source has its own fetcher: `baostock_fetcher.py`, `akshare_fetcher.py`, `yfinance_fetcher.py`
- Each fetcher handles:
  - Source-specific API calls
  - Rate limiting (random jitter, User-Agent rotation)
  - Data normalization to standard format
  - Retry with exponential backoff (using `tenacity`)

### `data_provider/realtime_types.py`
- `UnifiedRealtimeQuote`: Dataclass for normalized realtime quotes
- `CircuitBreaker`: Thread-safe circuit breaker implementation
- `safe_float()`, `safe_int()`: Type-safe conversion utilities

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

## Provider Frequency Support

| Provider | d | w | m | 5m | 15m | 30m | 60m |
|----------|---|---|---|----|----|-----|-----|
| BaostockFetcher | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| AkshareFetcher | ✅ | ✅ | ✅ | ❌ | ❌ | ❌ | ❌ |
| TushareFetcher | ✅ | ✅ | ✅ | ❌ | ❌ | ❌ | ❌ |
| YfinanceFetcher | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |

**Fallback**: Server queries providers in priority order. If provider doesn't support the requested frequency, it raises `DataFetchError` and the next provider is tried.

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
Manager routes requests based on stock code:
- US stocks → YfinanceFetcher (primary), Stooq fallback
- A-shares → BaostockFetcher (primary), AkshareFetcher (fallback)
- Each fetcher declares supported markets via `_MARKET_SUPPORT` dict

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

## Anti-Patterns to Avoid

- **Don't** put all code in one file — split fetchers into separate modules
- **Don't** use verbose Hungarian notation like `_stock_name_cache_lock` — use `_lock` on the cache dict itself
- **Don't** mix inline imports and top-level imports inconsistently
- **Don't** add features not needed for core data fetching (defer fundamental data, sentiment, etc.)
- **Don't** create deeply nested manager hierarchies — one `DataFetcherManager` is sufficient
