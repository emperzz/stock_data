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

# Persistence functions (on-disk SQLite store). The legacy data_provider.cache/
# module was removed; this package is now the single home for SQLite-backed
# metadata. For in-memory caching of recent API responses, use api.cache
# (cachetools.TTLCache) — see routes.py `from .cache import`.
from .persistence import (
    get_cached_calendar,
    get_cached_stocks,
    get_latest_cached_trade_date,
    get_latest_trade_date_on_or_before,
    get_stock_list,
    get_stock_list_cache_info,
    get_stock_name,
    has_cached_data,
    init_stock_list_schema,
    init_trade_calendar_schema,
    is_trade_date,
    update_cached_calendar,
    update_cached_stocks,
)

# Backward compatibility: `stock_cache` is the on-disk persistence layer.
# Kept as a public alias because external consumers (OpenClaw) and many
# call sites in routes.py use `from data_provider import stock_cache`.
from . import persistence as stock_cache

# Fetcher classes
from .fetchers.akshare_fetcher import AkshareFetcher
from .fetchers.baostock_fetcher import BaostockFetcher
from .fetchers.cninfo_fetcher import CninfoFetcher
from .fetchers.eastmoney_fetcher import EastMoneyFetcher
from .fetchers.tencent_fetcher import TencentFetcher
from .fetchers.ths_fetcher import ThsFetcher
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
    # Persistence functions (on-disk SQLite store)
    "get_cached_calendar",
    "get_cached_stocks",
    "get_latest_cached_trade_date",
    "get_latest_trade_date_on_or_before",
    "get_stock_list",
    "get_stock_list_cache_info",
    "get_stock_name",
    "has_cached_data",
    "init_stock_list_schema",
    "init_trade_calendar_schema",
    "is_trade_date",
    "update_cached_calendar",
    "update_cached_stocks",
    # Persistence module alias (legacy name preserved for back-compat)
    "stock_cache",
    # Fetchers
    "AkshareFetcher",
    "BaostockFetcher",
    "CninfoFetcher",
    "EastMoneyFetcher",
    "TencentFetcher",
    "ThsFetcher",
    "TushareFetcher",
    "YfinanceFetcher",
    "ZhituFetcher",
]