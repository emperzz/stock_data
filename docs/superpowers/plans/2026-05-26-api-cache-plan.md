# API TTL Cache Enhancement Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add TTLCache to 13 uncached API endpoints in routes.py, by extending cache.py with 11 new cache instances.

**Architecture:** Extend `stock_data/api/cache.py` with new cache instances and key functions, then update `routes.py` to check/write these caches in each endpoint.

**Tech Stack:** Python, cachetools.TTLCache, FastAPI routes

---

## File Map

| File | Responsibility |
|------|---------------|
| `stock_data/api/cache.py` | TTLCache instances + accessor functions + key builders |
| `stock_data/api/routes.py` | 13 endpoints that need cache check/write logic |

---

## Task 1: Extend cache.py

**Files:**
- Modify: `stock_data/api/cache.py:132` (after existing cache functions)

- [ ] **Step 1: Add new TTL constants and cache instances**

After line 35 (`_stock_intraday_cache` definition), add:

```python
# TTL constants for uncached APIs
_TTL_DRAGON_TIGER = int(os.getenv("CACHE_TTL_DRAGON_TIGER", "300"))
_TTL_MARGIN = int(os.getenv("CACHE_TTL_MARGIN", "300"))
_TTL_BLOCK_TRADE = int(os.getenv("CACHE_TTL_BLOCK_TRADE", "300"))
_TTL_HOLDER_NUM = int(os.getenv("CACHE_TTL_HOLDER_NUM", "300"))
_TTL_DIVIDEND = int(os.getenv("CACHE_TTL_DIVIDEND", "300"))
_TTL_FUND_FLOW = int(os.getenv("CACHE_TTL_FUND_FLOW", "60"))
_TTL_HOT_TOPICS = int(os.getenv("CACHE_TTL_HOT_TOPICS", "60"))
_TTL_NORTH_FLOW = int(os.getenv("CACHE_TTL_NORTH_FLOW", "60"))
_TTL_REPORTS = int(os.getenv("CACHE_TTL_REPORTS", "1800"))
_TTL_ANNOUNCEMENTS = int(os.getenv("CACHE_TTL_ANNOUNCEMENTS", "1800"))
_TTL_POOLS = int(os.getenv("CACHE_TTL_POOLS", "60"))

# Cache instances
_dragontiger_cache: TTLCache = TTLCache(maxsize=512, ttl=_TTL_DRAGON_TIGER)
_margin_cache: TTLCache = TTLCache(maxsize=512, ttl=_TTL_MARGIN)
_block_trade_cache: TTLCache = TTLCache(maxsize=512, ttl=_TTL_BLOCK_TRADE)
_holder_num_cache: TTLCache = TTLCache(maxsize=512, ttl=_TTL_HOLDER_NUM)
_dividend_cache: TTLCache = TTLCache(maxsize=512, ttl=_TTL_DIVIDEND)
_fund_flow_cache: TTLCache = TTLCache(maxsize=512, ttl=_TTL_FUND_FLOW)
_hot_topics_cache: TTLCache = TTLCache(maxsize=128, ttl=_TTL_HOT_TOPICS)
_north_flow_cache: TTLCache = TTLCache(maxsize=64, ttl=_TTL_NORTH_FLOW)
_reports_cache: TTLCache = TTLCache(maxsize=512, ttl=_TTL_REPORTS)
_announcements_cache: TTLCache = TTLCache(maxsize=512, ttl=_TTL_ANNOUNCEMENTS)
_pools_cache: TTLCache = TTLCache(maxsize=128, ttl=_TTL_POOLS)
```

- [ ] **Step 2: Add getter functions for all new caches**

After line 69 (`get_history_cache`), add:

```python
def get_dragontiger_cache() -> TTLCache:
    return _dragontiger_cache

def get_margin_cache() -> TTLCache:
    return _margin_cache

def get_block_trade_cache() -> TTLCache:
    return _block_trade_cache

def get_holder_num_cache() -> TTLCache:
    return _holder_num_cache

def get_dividend_cache() -> TTLCache:
    return _dividend_cache

def get_fund_flow_cache() -> TTLCache:
    return _fund_flow_cache

def get_hot_topics_cache() -> TTLCache:
    return _hot_topics_cache

def get_north_flow_cache() -> TTLCache:
    return _north_flow_cache

def get_reports_cache() -> TTLCache:
    return _reports_cache

def get_announcements_cache() -> TTLCache:
    return _announcements_cache

def get_pools_cache() -> TTLCache:
    return _pools_cache
```

- [ ] **Step 3: Add make_xxx_cache_key functions**

After line 128 (`make_index_history_cache_key`), add:

```python
def make_dragon_tiger_cache_key(stock_code: str, trade_date: str, look_back: int) -> str:
    return f"dt:{stock_code}:{trade_date}:{look_back}"

def make_daily_dragon_tiger_cache_key(trade_date: str, min_net_buy: float | None) -> str:
    mb = str(min_net_buy) if min_net_buy is not None else ""
    return f"dtdaily:{trade_date}:{mb}"

def make_margin_cache_key(stock_code: str, page_size: int) -> str:
    return f"margin:{stock_code}:{page_size}"

def make_block_trade_cache_key(stock_code: str, page_size: int) -> str:
    return f"block:{stock_code}:{page_size}"

def make_holder_num_cache_key(stock_code: str, page_size: int) -> str:
    return f"holder:{stock_code}:{page_size}"

def make_dividend_cache_key(stock_code: str, page_size: int) -> str:
    return f"div:{stock_code}:{page_size}"

def make_fund_flow_cache_key(stock_code: str) -> str:
    return f"ff:{stock_code}"

def make_fund_flow_daily_cache_key(stock_code: str) -> str:
    return f"ffd:{stock_code}"

def make_hot_topics_cache_key(date: str) -> str:
    return f"hot:{date}"

def make_north_flow_cache_key() -> str:
    return "north:realtime"

def make_reports_cache_key(stock_code: str, max_pages: int) -> str:
    return f"rpt:{stock_code}:{max_pages}"

def make_announcements_cache_key(stock_code: str, page_size: int) -> str:
    return f"ann:{stock_code}:{page_size}"

def make_pools_cache_key(pool_type: str, date: str | None) -> str:
    d = date or ""
    return f"pool:{pool_type}:{d}"
```

- [ ] **Step 4: Commit cache.py changes**

```bash
git add stock_data/api/cache.py
git commit -m "feat: add TTLCache for 11 uncached API endpoints"
```

---

## Task 2: Add cache logic to routes.py endpoints

**Files:**
- Modify: `stock_data/api/routes.py`

For each endpoint, the pattern is:
```python
if is_cache_enabled():
    cache = get_xxx_cache()
    key = make_xxx_cache_key(...)
    if key in cache:
        logger.info(f"[APICache] {cache_name} hit: {key}")
        return cached_result

# ... normal processing ...

if is_cache_enabled():
    cache[key] = result
return result
```

Apply this pattern to:

- [ ] **Step 1: Add cache logic to `get_dragon_tiger` (line ~1141)**

After `try:` block start, before manager call:
```python
if is_cache_enabled():
    cache = get_dragontiger_cache()
    key = make_dragon_tiger_cache_key(stock_code, trade_date, look_back)
    if key in cache:
        logger.info(f"[APICache] dragontiger hit: {key}")
        return cache[key]
```

At end before `return DragonTigerResponse(...)`:
```python
if is_cache_enabled():
    cache[key] = result
return result
```

- [ ] **Step 2: Add cache logic to `get_daily_dragon_tiger` (line ~1179)**

Cache key: `make_daily_dragon_tiger_cache_key(trade_date, min_net_buy)`
Cache getter: `get_dragontiger_cache()`

- [ ] **Step 3: Add cache logic to `get_margin` (line ~1206)**

Cache key: `make_margin_cache_key(stock_code, page_size)`
Cache getter: `get_margin_cache()`

- [ ] **Step 4: Add cache logic to `get_block_trade` (line ~1234)**

Cache key: `make_block_trade_cache_key(stock_code, page_size)`
Cache getter: `get_block_trade_cache()`

- [ ] **Step 5: Add cache logic to `get_holder_num` (line ~1262)**

Cache key: `make_holder_num_cache_key(stock_code, page_size)`
Cache getter: `get_holder_num_cache()`

- [ ] **Step 6: Add cache logic to `get_dividend` (line ~1290)**

Cache key: `make_dividend_cache_key(stock_code, page_size)`
Cache getter: `get_dividend_cache()`

- [ ] **Step 7: Add cache logic to `get_fund_flow` (line ~1318)**

Cache key: `make_fund_flow_cache_key(stock_code)`
Cache getter: `get_fund_flow_cache()`

- [ ] **Step 8: Add cache logic to `get_fund_flow_daily` (line ~1344)**

Cache key: `make_fund_flow_daily_cache_key(stock_code)`
Cache getter: `get_fund_flow_cache()`

- [ ] **Step 9: Add cache logic to `get_hot_topics` (line ~1370)**

Cache key: `make_hot_topics_cache_key(date)`
Cache getter: `get_hot_topics_cache()`

- [ ] **Step 10: Add cache logic to `get_north_flow` (line ~1399)**

Cache key: `make_north_flow_cache_key()`
Cache getter: `get_north_flow_cache()`

- [ ] **Step 11: Add cache logic to `get_reports` (line ~1424)**

Cache key: `make_reports_cache_key(stock_code, max_pages)`
Cache getter: `get_reports_cache()`

- [ ] **Step 12: Add cache logic to `get_announcements` (line ~1481)**

Cache key: `make_announcements_cache_key(stock_code, page_size)`
Cache getter: `get_announcements_cache()`

- [ ] **Step 13: Add cache logic to `get_pools` (line ~1056)**

Cache key: `make_pools_cache_key(type, date)`
Cache getter: `get_pools_cache()`

**Import updates needed in routes.py:**
```python
from .cache import (
    ...
    get_dragontiger_cache,
    get_margin_cache,
    get_block_trade_cache,
    get_holder_num_cache,
    get_dividend_cache,
    get_fund_flow_cache,
    get_hot_topics_cache,
    get_north_flow_cache,
    get_reports_cache,
    get_announcements_cache,
    get_pools_cache,
    make_dragon_tiger_cache_key,
    make_daily_dragon_tiger_cache_key,
    make_margin_cache_key,
    make_block_trade_cache_key,
    make_holder_num_cache_key,
    make_dividend_cache_key,
    make_fund_flow_cache_key,
    make_fund_flow_daily_cache_key,
    make_hot_topics_cache_key,
    make_north_flow_cache_key,
    make_reports_cache_key,
    make_announcements_cache_key,
    make_pools_cache_key,
)
```

- [ ] **Step 14: Commit routes.py changes**

```bash
git add stock_data/api/routes.py
git commit -m "feat: add TTL cache to 13 uncached API endpoints"
```

---

## Verification

- [ ] **Run linter:** `ruff check stock_data/api/cache.py stock_data/api/routes.py`
- [ ] **Run tests:** `pytest -x -q`
- [ ] **Smoke test** (optional): Start server and hit a few cached endpoints to verify no errors