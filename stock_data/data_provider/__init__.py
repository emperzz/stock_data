"""
Data Provider Package
Stock data fetchers with unified interface
"""

# Load .env BEFORE importing any fetcher class. Each fetcher's class body
# reads ``priority = int(os.getenv("<SLUG>_PRIORITY", "<default>"))`` at
# module import time — if ``load_dotenv()`` runs after that, the priority
# always comes from the hardcoded default and the operator's .env override
# is silently ignored.
#
# This used to live in ``server.py``, but ``server.py`` imports
# ``routes/__init__.py`` (which transitively pulls in *this* file) before
# calling ``load_dotenv()``, so the bug was structural — any entry point
# that touched ``stock_data.data_provider`` without first calling
# ``load_dotenv()`` itself inherited the same silent override.
#
# Centralizing the load here makes it a side effect of importing the
# package, so the priority is always read from the operator's .env
# regardless of entry point (server / tests / tools / future MCP server).
# ``server.py`` keeps its own ``load_dotenv()`` call as redundant
# documentation at the entry point — ``load_dotenv()`` is idempotent
# (``override=False`` default, so existing env vars are never overwritten).
import os

from dotenv import load_dotenv

load_dotenv()

# Core classes - main entry point
from .base import (
    STANDARD_COLUMNS,
    BaseFetcher,
    DataCapability,
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
from .fetchers.cls_fetcher import ClsFetcher
from .fetchers.cninfo_fetcher import CninfoFetcher
from .fetchers.eastmoney_fetcher import EastMoneyFetcher
from .fetchers.tencent_fetcher import TencentFetcher
from .fetchers.ths_fetcher import ThsFetcher
from .fetchers.tushare_fetcher import TushareFetcher
from .fetchers.yfinance_fetcher import YfinanceFetcher
from .fetchers.zhitu_fetcher import ZhituFetcher
from .fetchers.zzshare_fetcher import ZzshareFetcher

# Manager factory
from .manager import DataFetcherManager, create_default_manager

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
    # Manager factory
    "create_default_manager",
    # Fetchers
    "AkshareFetcher",
    "BaiduFetcher",
    "BaostockFetcher",
    "ClsFetcher",
    "CninfoFetcher",
    "EastMoneyFetcher",
    "TencentFetcher",
    "ThsFetcher",
    "TushareFetcher",
    "YfinanceFetcher",
    "ZhituFetcher",
    "ZzshareFetcher",
]
