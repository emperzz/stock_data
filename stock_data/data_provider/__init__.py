"""
Data Provider Package
Stock data fetchers with unified interface
"""

# Core classes - main entry point
# Backward compatibility: `stock_cache` is the on-disk persistence layer.
# Kept as a public alias because external consumers (OpenClaw) and many
# call sites in routes.py use `from data_provider import stock_cache`.
from . import persistence as stock_cache
from .base import (
    STANDARD_COLUMNS,
    BaseFetcher,
    DataCapability,
    DataFetcherManager,
    DataFetchError,
)

# Types
from .core.types import (
    REALTIME_CIRCUIT_BREAKER,
    CircuitBreaker,
    RealtimeSource,
    UnifiedRealtimeQuote,
    safe_float,
    safe_int,
)

# Fetcher classes
from .fetchers.akshare import AkshareFetcher
from .fetchers.baidu_fetcher import BaiduFetcher
from .fetchers.baostock_fetcher import BaostockFetcher
from .fetchers.cninfo_fetcher import CninfoFetcher
from .fetchers.eastmoney_fetcher import EastMoneyFetcher
from .fetchers.tencent_fetcher import TencentFetcher
from .fetchers.ths_fetcher import ThsFetcher
from .fetchers.tushare_fetcher import TushareFetcher
from .fetchers.yfinance_fetcher import YfinanceFetcher
from .fetchers.zhitu_fetcher import ZhituFetcher
from .fetchers.zzshare_fetcher import ZzshareFetcher

# Manager factory
from .manager import create_default_manager

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
    get_stock_name,
    is_trade_date,
    update_cached_calendar,
    update_cached_stocks,
)

__all__ = [
    # Core
    "BaseFetcher",
    "DataCapability",
    "DataFetcherManager",
    "DataFetchError",
    "STANDARD_COLUMNS",
    # Types
    "CircuitBreaker",
    "RealtimeSource",
    "UnifiedRealtimeQuote",
    "safe_float",
    "safe_int",
    "REALTIME_CIRCUIT_BREAKER",
    # Persistence functions (on-disk SQLite store)
    "get_cached_calendar",
    "get_cached_stocks",
    "get_latest_cached_trade_date",
    "get_latest_trade_date_on_or_before",
    "get_stock_list",
    "get_stock_name",
    "is_trade_date",
    "update_cached_calendar",
    "update_cached_stocks",
    # Persistence module alias (legacy name preserved for back-compat)
    "stock_cache",
    # Manager factory
    "create_default_manager",
    # Fetchers
    "AkshareFetcher",
    "BaiduFetcher",
    "BaostockFetcher",
    "CninfoFetcher",
    "EastMoneyFetcher",
    "TencentFetcher",
    "ThsFetcher",
    "TushareFetcher",
    "YfinanceFetcher",
    "ZhituFetcher",
    "ZzshareFetcher",
]
