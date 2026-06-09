"""
Myquant (掘金量化) fetcher for A-share stock data (Priority 1).

API: ``gm`` SDK (https://www.myquant.cn/) — free public version (体验版/专业版/机构版)
covers history / current_price / get_symbols / get_trading_dates_by_year / stk_get_*.

Token configured via MYQUANT_TOKEN environment variable.
Lazy ``gm.api.set_token`` on first data call.

This fetcher is a *backup* — placed right after Tushare, before Baostock on
the failover list (tie-broken by registration order in create_default_manager).
"""

# isort: off
import logging
import os
from datetime import datetime  # noqa: F401 — used in get_trade_calendar and get_index_intraday (Tasks 7, 9)

import pandas as pd

from ..base import BaseFetcher, DataCapability, DataFetchError, normalize_stock_code  # noqa: F401 — normalize_stock_code used in get_realtime_quote (Task 6)
from ..core.types import RealtimeSource, UnifiedRealtimeQuote, safe_float  # noqa: F401 — used in get_realtime_quote and get_all_stocks (Tasks 6, 8)
from ..utils.code_converter import to_myquant_format, to_myquant_index_format  # noqa: F401 — used in _map_adjust and _convert_code (Task 4)
# isort: on

logger = logging.getLogger(__name__)

# myquant adjust constants (see gm.api)
ADJUST_NONE = 0   # 不复权
ADJUST_PREV = 1   # 前复权
ADJUST_POST = 2   # 后复权

# Frequency mapping: server "d/5/15/30/60" → myquant "1d/300s/900s/1800s/3600s"
_FREQ_MAP: dict[str, str] = {
    "d": "1d",
    "5": "300s",
    "15": "900s",
    "30": "1800s",
    "60": "3600s",
}

# Index intraday mapping (same minute periods)
_INDEX_FREQ_MAP: dict[str, str] = {
    "5": "300s",
    "15": "900s",
    "30": "1800s",
    "60": "3600s",
}


class MyquantFetcher(BaseFetcher):
    """Myquant (掘金量化) SDK fetcher for A-share data."""

    name = "MyquantFetcher"
    priority = int(os.getenv("MYQUANT_PRIORITY", "1"))
    supported_markets: set[str] = {"csi"}
    supported_data_types = (
        DataCapability.HISTORICAL_DWM
        | DataCapability.HISTORICAL_MIN
        | DataCapability.REALTIME_QUOTE
        | DataCapability.STOCK_LIST
        | DataCapability.TRADE_CALENDAR
        | DataCapability.INDEX_HISTORICAL
        | DataCapability.INDEX_INTRADAY
    )

    def __init__(self):
        self._token = os.getenv("MYQUANT_TOKEN", "").strip()
        self._initialized = False

    def _ensure_initialized(self) -> None:
        """Lazily import gm.api and call set_token on first use."""
        if self._initialized:
            return
        self._initialized = True
        if not self._token:
            logger.warning("[MyquantFetcher] MYQUANT_TOKEN not set")
            return
        try:
            from gm.api import set_token  # type: ignore

            set_token(self._token)
            logger.info("[MyquantFetcher] Initialized (token configured)")
        except Exception as e:
            logger.warning(f"[MyquantFetcher] Failed to set token: {e}")

    def is_available(self) -> bool:
        """True iff MYQUANT_TOKEN is set."""
        return bool(self._token)

    # ---- unsupported base abstract methods ----

    def _fetch_raw_data(
        self,
        stock_code: str,
        start_date: str,
        end_date: str,
        frequency: str = "d",
        adjust: str | None = None,
    ) -> pd.DataFrame:
        raise DataFetchError("MyquantFetcher routes through get_kline_data override")

    def _normalize_data(self, df: pd.DataFrame, stock_code: str) -> pd.DataFrame:
        raise DataFetchError("MyquantFetcher routes through get_kline_data override")
