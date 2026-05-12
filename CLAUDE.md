# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

A Python-based local stock data aggregation server that:
- Integrates multiple upstream stock data APIs (Yahoo Finance, Alpha Vantage, East Money, etc.)
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
│  EfinanceFetcher  AkshareFetcher  YfinanceFetcher ...    │
├─────────────────────────────────────────────────────────┤
│              Upstream Stock Data APIs                    │
```

## Core Components

### `data_provider/base.py`
- `BaseFetcher`: Abstract base defining `_fetch_raw_data()`, `_normalize_data()`, `get_daily_data()`, `get_realtime_quote()`
- `DataFetcherManager`: Orchestrates fetchers with priority-based failover, circuit breakers, and market-aware routing

### `data_provider/{source}_fetcher.py`
- Each source has its own fetcher: `efinance_fetcher.py`, `akshare_fetcher.py`, `yfinance_fetcher.py`
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
- US/HK stocks → specialized fetchers (YfinanceFetcher, LongbridgeFetcher)
- A-shares → EfinanceFetcher (primary), AkshareFetcher (fallback)
- Each fetcher declares supported markets via `_DAILY_MARKET_FETCHER_SUPPORT`

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
- `LONGBRIDGE_APP_KEY/SECRET/TOKEN` - Longbridge credentials
- `EFINANCE_PRIORITY` - Override efinance fetcher priority (default: 0)
- `YFINANCE_PRIORITY` - Override yfinance fetcher priority (default: 4)
- `ENABLE_REALTIME_QUOTE` - Toggle realtime quote feature
- `REALTIME_SOURCE_PRIORITY` - Comma-separated source priority for realtime

## Anti-Patterns to Avoid

- **Don't** put all code in one file — split fetchers into separate modules
- **Don't** use verbose Hungarian notation like `_stock_name_cache_lock` — use `_lock` on the cache dict itself
- **Don't** mix inline imports and top-level imports inconsistently
- **Don't** add features not needed for core data fetching (defer fundamental data, sentiment, etc.)
- **Don't** create deeply nested manager hierarchies — one `DataFetcherManager` is sufficient
