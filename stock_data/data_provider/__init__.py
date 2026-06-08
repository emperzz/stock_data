# Data Provider Package
# Stock data fetchers with unified interface

from .base import (
    STANDARD_COLUMNS,
    BaseFetcher,
    DataCapability,
    DataFetcherManager,
    DataFetchError,
    RateLimitError,
)

# Re-export cache module for backward compatibility
from .cache import api_cache as stock_cache

# Re-export from cache for backward compatibility
from .cache.api_cache import (
    get_cache_info,
    get_cached_calendar,
    get_cached_stocks,
    get_latest_cached_trade_date,
    get_stock_list,
    get_stock_name,
    has_cached_data,
    init_calendar_db,
    init_db,
    update_cached_calendar,
    update_cached_stocks,
)
from .core.types import CircuitBreaker, RealtimeSource, UnifiedRealtimeQuote

# Re-export fetcher classes for backward compatibility
from .fetchers.akshare_fetcher import AkshareFetcher
from .fetchers.baostock_fetcher import BaostockFetcher
from .fetchers.tushare_fetcher import TushareFetcher
from .fetchers.yfinance_fetcher import YfinanceFetcher
from .fetchers.zhitu_fetcher import ZhituFetcher

__all__ = [
    "BaseFetcher",
    "DataCapability",
    "DataFetcherManager",
    "DataFetchError",
    "RateLimitError",
    "STANDARD_COLUMNS",
    "UnifiedRealtimeQuote",
    "CircuitBreaker",
    "RealtimeSource",
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
    # Cache module for backward compatibility
    "stock_cache",
    # Fetcher classes for backward compatibility
    "AkshareFetcher",
    "BaostockFetcher",
    "TushareFetcher",
    "YfinanceFetcher",
    "ZhituFetcher",
]
