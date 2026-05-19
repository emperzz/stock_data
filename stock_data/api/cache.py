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
_TTL_BOARD_LIST = int(os.getenv("CACHE_TTL_BOARD_LIST", 300))
_TTL_BOARD_STOCKS = int(os.getenv("CACHE_TTL_BOARD_STOCKS", 300))
_TTL_INDEX_QUOTE = int(os.getenv("CACHE_TTL_INDEX_QUOTE", 60))
_TTL_INDEX_INTRADAY = int(os.getenv("CACHE_TTL_INDEX_INTRADAY", 30))
_TTL_STOCK_INTRADAY = int(os.getenv("CACHE_TTL_STOCK_INTRADAY", 30))
_ENABLE_CACHE = os.getenv("ENABLE_API_CACHE", "true").lower() == "true"

# Global per-frequency history cache instances
_history_cache_d: TTLCache = TTLCache(maxsize=512, ttl=_TTL_HISTORY_DAILY)
_history_cache_w: TTLCache = TTLCache(maxsize=512, ttl=_TTL_HISTORY_WEEKLY)
_history_cache_m: TTLCache = TTLCache(maxsize=512, ttl=_TTL_HISTORY_MONTHLY)

_quote_cache: TTLCache = TTLCache(maxsize=1024, ttl=_TTL_QUOTE)
_board_list_cache: TTLCache = TTLCache(maxsize=64, ttl=_TTL_BOARD_LIST)
_board_stocks_cache: TTLCache = TTLCache(maxsize=512, ttl=_TTL_BOARD_STOCKS)
_index_quote_cache: TTLCache = TTLCache(maxsize=512, ttl=_TTL_INDEX_QUOTE)
_index_intraday_cache: TTLCache = TTLCache(maxsize=512, ttl=_TTL_INDEX_INTRADAY)
_stock_intraday_cache: TTLCache = TTLCache(maxsize=512, ttl=_TTL_STOCK_INTRADAY)


def get_quote_cache() -> TTLCache:
    return _quote_cache


def get_board_list_cache() -> TTLCache:
    return _board_list_cache


def get_board_stocks_cache() -> TTLCache:
    return _board_stocks_cache


def get_index_quote_cache() -> TTLCache:
    return _index_quote_cache


def get_index_intraday_cache() -> TTLCache:
    return _index_intraday_cache


def get_stock_intraday_cache() -> TTLCache:
    return _stock_intraday_cache


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
    stock_code: str,
    frequency: str,
    days: int,
    start_date: str | None = None,
    end_date: str | None = None,
    adjust: str | None = None,
) -> str:
    parts = [stock_code, frequency, str(days)]
    if start_date or end_date:
        parts.extend([start_date or "", end_date or ""])
    if adjust:
        parts.append(adjust)
    return ":".join(parts)


def make_board_cache_key(board_type: str, source: str) -> str:
    """Make cache key for board list data."""
    return f"board:{board_type}:{source}"


def make_board_stocks_cache_key(
    board_code: str, source: str, include_quote: bool
) -> str:
    """Make cache key for board stocks data."""
    suffix = ":quote" if include_quote else ""
    return f"board_stocks:{board_code}:{source}{suffix}"


def make_index_quote_cache_key(index_code: str) -> str:
    return f"idx_quote:{index_code}"


def make_stock_intraday_cache_key(stock_code: str, period: str, adjust: str) -> str:
    suffix = f":{adjust}" if adjust else ""
    return f"stock_intraday:{stock_code}:{period}{suffix}"


def make_index_intraday_cache_key(index_code: str, period: str) -> str:
    return f"idx_intraday:{index_code}:{period}"


def make_index_history_cache_key(
    index_code: str,
    frequency: str,
    days: int,
    start_date: str | None = None,
    end_date: str | None = None,
) -> str:
    parts = [index_code, frequency, str(days)]
    if start_date or end_date:
        parts.extend([start_date or "", end_date or ""])
    return "idx_history:" + ":".join(parts)


def is_cache_enabled() -> bool:
    return _ENABLE_CACHE
