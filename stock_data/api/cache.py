"""
In-memory TTLCache for API response caching.

Avoids repeated upstream API calls for identical requests within a short window.
"""

import logging
import os

from cachetools import TTLCache

logger = logging.getLogger(__name__)

_TTL_QUOTE = int(os.getenv("CACHE_TTL_QUOTE", 60))
_TTL_HISTORY_DAILY = int(os.getenv("CACHE_TTL_HISTORY_DAILY", 300))
_TTL_HISTORY_WEEKLY = int(os.getenv("CACHE_TTL_HISTORY_WEEKLY", 3600))
_TTL_HISTORY_MONTHLY = int(os.getenv("CACHE_TTL_HISTORY_MONTHLY", 7200))
_TTL_INDEX_QUOTE = int(os.getenv("CACHE_TTL_INDEX_QUOTE", 60))
_TTL_STOCK_INTRADAY = int(os.getenv("CACHE_TTL_STOCK_INTRADAY", 30))
_ENABLE_CACHE = os.getenv("ENABLE_API_CACHE", "true").lower() == "true"

# Global per-frequency history cache instances
_history_cache_d: TTLCache = TTLCache(maxsize=512, ttl=_TTL_HISTORY_DAILY)
_history_cache_w: TTLCache = TTLCache(maxsize=512, ttl=_TTL_HISTORY_WEEKLY)
_history_cache_m: TTLCache = TTLCache(maxsize=512, ttl=_TTL_HISTORY_MONTHLY)

_quote_cache: TTLCache = TTLCache(maxsize=1024, ttl=_TTL_QUOTE)
_index_quote_cache: TTLCache = TTLCache(maxsize=512, ttl=_TTL_INDEX_QUOTE)
_stock_intraday_cache: TTLCache = TTLCache(maxsize=512, ttl=_TTL_STOCK_INTRADAY)

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
_TTL_STOCK_INFO = int(os.getenv("CACHE_TTL_STOCK_INFO", "3600"))  # 公司画像 (1h)
_TTL_NEWS_SEARCH = int(os.getenv("CACHE_TTL_NEWS_SEARCH", "300"))
_TTL_NEWS_CONTENT = int(os.getenv("CACHE_TTL_NEWS_CONTENT", "3600"))
_TTL_NEWS_FLASH = int(os.getenv("CACHE_TTL_NEWS_FLASH", "60"))  # 7x24 快讯 (60s)

# Cache instances
_dragontiger_cache: TTLCache = TTLCache(maxsize=512, ttl=_TTL_DRAGON_TIGER)
_margin_cache: TTLCache = TTLCache(maxsize=512, ttl=_TTL_MARGIN)
_block_trade_cache: TTLCache = TTLCache(maxsize=512, ttl=_TTL_BLOCK_TRADE)
_holder_num_cache: TTLCache = TTLCache(maxsize=512, ttl=_TTL_HOLDER_NUM)
_dividend_cache: TTLCache = TTLCache(maxsize=512, ttl=_TTL_DIVIDEND)
_fund_flow_minute_cache: TTLCache = TTLCache(maxsize=512, ttl=_TTL_FUND_FLOW)
_fund_flow_daily_cache: TTLCache = TTLCache(maxsize=256, ttl=_TTL_FUND_FLOW)
_hot_topics_cache: TTLCache = TTLCache(maxsize=128, ttl=_TTL_HOT_TOPICS)
_north_flow_cache: TTLCache = TTLCache(maxsize=64, ttl=_TTL_NORTH_FLOW)
_reports_cache: TTLCache = TTLCache(maxsize=512, ttl=_TTL_REPORTS)
_announcements_cache: TTLCache = TTLCache(maxsize=512, ttl=_TTL_ANNOUNCEMENTS)
_pools_cache: TTLCache = TTLCache(maxsize=128, ttl=_TTL_POOLS)
_stock_info_cache: TTLCache = TTLCache(maxsize=512, ttl=_TTL_STOCK_INFO)
_news_search_cache: TTLCache = TTLCache(maxsize=256, ttl=_TTL_NEWS_SEARCH)
_news_content_cache: TTLCache = TTLCache(maxsize=256, ttl=_TTL_NEWS_CONTENT)
_news_flash_cache: TTLCache = TTLCache(maxsize=64, ttl=_TTL_NEWS_FLASH)


def get_quote_cache() -> TTLCache:
    return _quote_cache


def get_index_quote_cache() -> TTLCache:
    return _index_quote_cache


def get_stock_intraday_cache() -> TTLCache:
    return _stock_intraday_cache


def get_history_cache(frequency: str) -> TTLCache:
    """Return the cache instance matching the given frequency (d/w/m)."""
    if frequency == "w":
        return _history_cache_w
    if frequency == "m":
        return _history_cache_m
    return _history_cache_d


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
    """Cache for minute-level fund flow (one entry per stock_code)."""
    return _fund_flow_minute_cache


def get_fund_flow_daily_cache() -> TTLCache:
    """Cache for 120-day daily fund flow (one entry per stock_code)."""
    return _fund_flow_daily_cache


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


def get_stock_info_cache() -> TTLCache:
    return _stock_info_cache


def get_news_search_cache() -> TTLCache:
    return _news_search_cache


def get_news_content_cache() -> TTLCache:
    return _news_content_cache


def get_news_flash_cache() -> TTLCache:
    return _news_flash_cache


def make_news_stock_cache_key(stock_code: str, limit: int) -> str:
    from stock_data.data_provider.utils.normalize import normalize_stock_code

    return f"news_stock:{normalize_stock_code(stock_code)}:{limit}"


def make_news_flash_cache_key(limit: int) -> tuple:
    """Cache key for /api/v1/news/flash?limit=N. Single-param, opaque tuple."""
    return ("news_flash", limit)


def make_quote_cache_key(stock_code: str) -> str:
    return stock_code


def make_index_quote_cache_key(index_code: str) -> str:
    return f"idx_quote:{index_code}"


def make_dragon_tiger_cache_key(stock_code: str, trade_date: str) -> str:
    return f"dt:{stock_code}:{trade_date}"


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


def make_stock_info_cache_key(stock_code: str) -> str:
    return f"stock_info:{stock_code}"


def make_news_search_cache_key(
    q: str, from_date: str | None, to_date: str | None, limit: int
) -> str:
    return f"news:search:{q}:{from_date or ''}:{to_date or ''}:{limit}"


def make_news_content_cache_key(url: str) -> str:
    import hashlib

    return f"news:content:{hashlib.sha256(url.encode('utf-8')).hexdigest()[:16]}"


def make_kline_cache_key(
    code: str,
    frequency: str,
    days: int | None,
    start_date: str | None,
    end_date: str | None,
    adjust: str | None,
    indicators: list[str],
) -> str:
    """Stable cache key for /kline responses per spec §5.4."""
    return (
        f"kline:{code}:{frequency}:{days or ''}:{start_date or ''}:"
        f"{end_date or ''}:{adjust or ''}:{','.join(sorted(indicators))}"
    )


def get_kline_cache(frequency: str) -> TTLCache:
    """TTL split per spec §5.4. Minute -> 30s intraday TTL; daily+ -> history TTL."""
    if frequency in ("1", "5", "15", "30", "60"):
        return get_stock_intraday_cache()
    return get_history_cache(frequency)


def is_cache_enabled() -> bool:
    return _ENABLE_CACHE


def cached_lookup(cache_fn, key: str, hit_label: str) -> object | None:
    """Read-side helper: return cached value if present, else None.

    Centralises the is_cache_enabled + cache-in + logger pattern that the route
    handlers used to inline 13+ times. Use with ``cached_store()`` at write
    time to keep cache writes explicit and visible at the call site.
    """
    if not _ENABLE_CACHE:
        return None
    cache = cache_fn()
    if key in cache:
        logger.info(f"[APICache] {hit_label} hit: {key}")
        return cache[key]
    return None


def cached_store(cache_fn, key: str, value: object) -> None:
    """Write-side helper: store ``value`` at ``key`` in the cache returned by
    ``cache_fn``. No-op when caching is disabled, so callers don't have to
    wrap the call in ``is_cache_enabled()``.
    """
    if not _ENABLE_CACHE:
        return
    cache = cache_fn()
    cache[key] = value


def cache_endpoint(
    cache_fn,
    key_builder,
    hit_label: str,
):
    """Cache-only wrapper for routes where the cache key derives from raw args.

    Composes with :func:`stock_data.api.routes.errors.map_errors` for the
    uniform ``DataFetchError→503 / HTTPException passthrough / Exception→500``
    error contract. Without that decorator, exceptions raised by the wrapped
    function propagate unchanged.

    Args:
        cache_fn: ``(*args, **kwargs) -> TTLCache``. Both fixed-cache
            endpoints (``cache_fn=lambda *a, **kw: get_quote_cache()``) and
            per-frequency endpoints
            (``cache_fn=lambda code, period, **kw: get_history_cache(_freq(period))``)
            share the same signature.
        key_builder: ``(*args, **kwargs) -> str``. The same args are forwarded.
            May raise :class:`fastapi.HTTPException` for invalid input (e.g.
            a 400 for an unknown indicator name) — the exception propagates
            through ``@map_errors``.
        hit_label: short label used in the ``[APICache] <label> hit: <key>``
            log line on cache hits.

    Usage:
        @router.get('/path')
        @map_errors
        @cache_endpoint(get_x_cache, make_x_key, 'label')
        @endpoint_meta(...)
        def handler(...): ...
    """
    from functools import wraps

    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            cache = cache_fn(*args, **kwargs)
            cache_key = key_builder(*args, **kwargs)
            if cache_key in cache:
                logger.info(f"[APICache] {hit_label} hit: {cache_key}")
                return cache[cache_key]
            result = func(*args, **kwargs)
            cache[cache_key] = result
            return result

        return wrapper

    return decorator
