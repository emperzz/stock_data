"""
Data Provider Package
Stock data fetchers with unified interface
"""

# Core classes - main entry point
from .base import (
    BaseFetcher,
    DataCapability,
    DataFetcherManager,
    DataFetchError,
    RateLimitError,
    STANDARD_COLUMNS,
)

# Types
from .core.types import (
    CircuitBreaker,
    RealtimeSource,
    UnifiedRealtimeQuote,
    safe_float,
    safe_int,
    get_realtime_circuit_breaker,
)

# Cache functions - use `from data_provider import stock_cache` for the module
from .cache.api_cache import (
    get_cached_calendar,
    get_cached_stocks,
    get_cache_info,
    get_latest_cached_trade_date,
    get_stock_list,
    get_stock_name,
    has_cached_data,
    init_calendar_db,
    init_db,
    update_cached_calendar,
    update_cached_stocks,
)

# Backward compatibility: re-export cache module
from . import cache as stock_cache

# Fetcher classes
from .fetchers.akshare_fetcher import AkshareFetcher
from .fetchers.baostock_fetcher import BaostockFetcher
from .fetchers.tushare_fetcher import TushareFetcher
from .fetchers.yfinance_fetcher import YfinanceFetcher
from .fetchers.zhitu_fetcher import ZhituFetcher

__all__ = [
    # Core
    "BaseFetcher",
    "DataCapability",
    "DataFetcherManager",
    "DataFetchError",
    "RateLimitError",
    "STANDARD_COLUMNS",
    # Types
    "CircuitBreaker",
    "RealtimeSource",
    "UnifiedRealtimeQuote",
    "safe_float",
    "safe_int",
    "get_realtime_circuit_breaker",
    # Cache functions
    "get_cached_calendar",
    "get_cached_stocks",
    "get_cache_info",
    "get_latest_cached_trade_date",
    "get_stock_list",
    "get_stock_name",
    "has_cached_data",
    "init_calendar_db",
    "init_db",
    "update_cached_calendar",
    "update_cached_stocks",
    # Cache module
    "stock_cache",
    # Fetchers
    "AkshareFetcher",
    "BaostockFetcher",
    "TushareFetcher",
    "YfinanceFetcher",
    "ZhituFetcher",
]