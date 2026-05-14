"""
Compatibility re-export module for stock cache.

Stock listing and trade calendar caching have been split into separate modules:
- stock_list_cache: Stock listing CRUD (get_cached_stocks, update_cached_stocks, etc.)
- trade_calendar_cache: Trade calendar CRUD (get_cached_calendar, update_cached_calendar, etc.)

This module re-exports all public functions for backward compatibility.
"""

from .stock_list_cache import (
    get_cache_info,
    get_cached_stocks,
    has_cached_data,
    init_db,
    update_cached_stocks,
)
from .trade_calendar_cache import (
    get_cached_calendar,
    get_latest_cached_trade_date,
    init_calendar_db,
    update_cached_calendar,
)

__all__ = [
    "get_cache_info",
    "get_cached_calendar",
    "get_cached_stocks",
    "get_latest_cached_trade_date",
    "has_cached_data",
    "init_calendar_db",
    "init_db",
    "update_cached_calendar",
    "update_cached_stocks",
]
