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
  "version": "0.1.0",
  "available_sources": ["TushareFetcher", "AkshareFetcher", "YfinanceFetcher"]
}
```

### Get Realtime Quote

```bash
GET /api/v1/stocks/{code}/quote
```

Examples:
- A-share: `GET /api/v1/stocks/600519/quote`
- US stock: `GET /api/v1/stocks/AAPL/quote`
- HK stock: `GET /api/v1/stocks/HK00700/quote`

### Get Historical Data

```bash
GET /api/v1/stocks/{code}/history?days=30
```

## Configuration

| Variable | Description | Default |
|----------|-------------|---------|
| `TUSHARE_TOKEN` | Tushare Pro API token | - |
| `SERVER_PORT` | Server port | 8888 |
| `SERVER_HOST` | Server host | 0.0.0.0 |

## Data Sources

Priority order for A-shares:
1. **Tushare** (Priority 0) - Requires API token
2. **Baostock** (Priority 1) - Free, no token
3. **Akshare** (Priority 2) - Fallback

US stocks: Yahoo Finance (Stooq as fallback)

## License

MIT
