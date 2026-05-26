# Health Check Enhancement Design

**Date:** 2026/05/26
**Topic:** Enhanced /health endpoint with lightweight and detailed modes

## Motivation

The current `/health` endpoint is incomplete:
- `status` always returns "ok" regardless of actual fetcher health
- `available_fetchers` only lists registered fetcher names, no health status
- No visibility into CircuitBreaker state or data freshness

## Design

### Two Modes

| Mode | Endpoint | Purpose | API Calls |
|------|----------|---------|-----------|
| Lightweight | `GET /health` | K8s/lb probe | None |
| Detailed | `GET /health?details=true` | AI agent display | None |

### Response Schema

**Lightweight mode** (`GET /health`):
```json
{
  "status": "ok",              // "ok" | "degraded" | "unhealthy"
  "version": "0.1.0"
}
```

**Detailed mode** (`GET /health?details=true`):
```json
{
  "status": "ok",
  "version": "0.1.0",
  "sources": [
    {
      "name": "BaostockFetcher",
      "state": "closed",       // "closed" | "open" | "half_open"
      "available": true,
      "last_success_time": 1748256000.123,
      "last_failure_time": null,
      "failure_count": 0
    }
  ]
}
```

### Status Logic

- **"ok"**: All available fetchers have CLOSED circuit breakers
- **"degraded"**: Some fetchers have OPEN/HALF_OPEN CBs (partial availability)
- **"unhealthy"**: All fetchers have OPEN circuit breakers

### Changes Required

1. **CircuitBreaker (core/types.py)**
   - Add `last_success_time` field to state dict
   - Modify `record_success()` to set `last_success_time = time.time()`

2. **HealthResponse (api/schemas.py)**
   - Add `sources: list[SourceHealth] | None = None` field (populated only when `details=true`)
   - Add `SourceHealth` model with fields: `name`, `state`, `available`, `last_success_time`, `last_failure_time`, `failure_count`

3. **health_check endpoint (api/routes.py)**
   - Read `details: bool = False` query param
   - Compute `status` from CB states (not hardcoded "ok")
   - Populate `sources` only when `details=true`

### Constraints

- No actual API calls to upstream data sources
- CircuitBreaker state is purely in-memory; restart resets all timestamps
- `last_success_time` is `None` if no successful call has ever been recorded