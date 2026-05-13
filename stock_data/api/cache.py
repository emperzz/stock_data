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
_ENABLE_CACHE = os.getenv("ENABLE_API_CACHE", "true").lower() == "true"

# Global per-frequency history cache instances
_history_cache_d: TTLCache = TTLCache(maxsize=512, ttl=_TTL_HISTORY_DAILY)
_history_cache_w: TTLCache = TTLCache(maxsize=512, ttl=_TTL_HISTORY_WEEKLY)
_history_cache_m: TTLCache = TTLCache(maxsize=512, ttl=_TTL_HISTORY_MONTHLY)

_quote_cache: TTLCache = TTLCache(maxsize=1024, ttl=_TTL_QUOTE)


def get_quote_cache() -> TTLCache:
    return _quote_cache


def get_history_cache(frequency: str) -> TTLCache:
    """Return the cache instance matching the given frequency (d/w/m)."""
    if frequency == "w":
        return _history_cache_w
    if frequency == "m":
        return _history_cache_m
    return _history_cache_d


def make_quote_cache_key(stock_code: str) -> str:
    return stock_code


def make_history_cache_key(
    stock_code: str, frequency: str, days: int, start_date: str | None = None, end_date: str | None = None
) -> str:
    if start_date or end_date:
        return f"{stock_code}:{frequency}:{days}:{start_date or ''}:{end_date or ''}"
    return f"{stock_code}:{frequency}:{days}"


def is_cache_enabled() -> bool:
    return _ENABLE_CACHE
