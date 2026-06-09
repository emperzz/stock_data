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

from ..base import BaseFetcher, DataCapability, DataFetchError, normalize_stock_code
from ..core.types import RealtimeSource, UnifiedRealtimeQuote, safe_float
from ..utils.code_converter import to_myquant_format, to_myquant_index_format  # noqa: F401 — to_myquant_index_format used in get_index_intraday (Task 9)
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

    def _map_adjust(self, adjust: str) -> int:
        """Map unified adjust to myquant integer constant.

        "" / None → ADJUST_NONE (0)
        "qfq"      → ADJUST_PREV (1)
        "hfq"      → ADJUST_POST (2)
        """
        if not adjust:
            return ADJUST_NONE
        mapping = {"qfq": ADJUST_PREV, "hfq": ADJUST_POST}
        return mapping.get(adjust, ADJUST_NONE)

    def _convert_code(self, stock_code: str) -> str:
        """Convert to myquant ``SHSE/SZSE.{code}`` format. Raises DataFetchError on unsupported markets."""
        try:
            return to_myquant_format(stock_code)
        except ValueError as e:
            raise DataFetchError(f"Myquant does not support code {stock_code}: {e}") from e

    # ---- unsupported base abstract methods ----

    def _fetch_raw_data(
        self,
        stock_code: str,
        start_date: str,
        end_date: str,
        frequency: str = "d",
        adjust: str | None = None,
    ) -> pd.DataFrame:
        """Fetch K-line data from myquant (stocks only — indices use get_index_historical).

        Supported frequencies: d, 5, 15, 30, 60. Raises DataFetchError on others.
        """
        if not self.is_available():
            return None  # type: ignore[return-value]
        if frequency not in _FREQ_MAP:
            raise DataFetchError(
                f"MyquantFetcher does not support frequency={frequency!r} "
                f"(supported: {sorted(_FREQ_MAP.keys())})"
            )

        try:
            from gm.api import history  # type: ignore

            symbol = self._convert_code(stock_code)
            df = history(
                symbol=symbol,
                frequency=_FREQ_MAP[frequency],
                start_time=start_date,
                end_time=end_date,
                adjust=self._map_adjust(adjust or ""),
                df=True,
            )
            if df is None or df.empty:
                raise DataFetchError(f"Myquant returned empty for {stock_code}")
            return df
        except DataFetchError:
            raise
        except Exception as e:
            raise DataFetchError(f"Myquant fetch_raw_data failed for {stock_code}: {e}") from e

    def _normalize_data(self, df: pd.DataFrame, stock_code: str) -> pd.DataFrame:
        """Normalize myquant history output to STANDARD_COLUMNS.

        myquant returns: symbol, frequency, open, close, high, low, amount, volume, bob, eob.
        - 'bob' (begin of bar) is the time anchor → renamed to 'date'
        - 'pct_chg' is NOT provided by myquant → computed from close/open (×100)
        - Other STANDARD_COLUMNS already match the source naming.
        """
        df = df.copy()
        if "bob" in df.columns:
            df = df.rename(columns={"bob": "date"})
        # myquant doesn't return pct_chg; derive it from close vs open (consistent with the
        # rest of the codebase, which uses open as the reference for "intraday change").
        if "pct_chg" not in df.columns and "open" in df.columns and "close" in df.columns:
            open_num = pd.to_numeric(df["open"], errors="coerce")
            close_num = pd.to_numeric(df["close"], errors="coerce")
            df["pct_chg"] = ((close_num / open_num) - 1.0) * 100.0
        return self._normalize_dataframe(df, stock_code, column_mapping={})

    def get_realtime_quote(self, stock_code: str) -> UnifiedRealtimeQuote | None:
        """Get realtime quote from myquant.

        Note: myquant's ``current_price`` only returns ``{symbol, price, created_at}`` —
        no volume/amount/change_pct/open/high/low. This fetcher is therefore
        positioned as a *last-resort* backup; richer quotes come from Tushare/
        Tencent/Zhitu in the failover chain. Most other fields stay ``None``.
        """
        if not self.is_available():
            return None
        try:
            from gm.api import current_price  # type: ignore

            symbol = self._convert_code(stock_code)
            rows = current_price(symbols=symbol)
            if not rows:
                return None
            row = rows[0] if isinstance(rows, list) else rows
            return UnifiedRealtimeQuote(
                code=normalize_stock_code(stock_code),
                source=RealtimeSource.MYQUANT,
                price=safe_float(row.get("price")),
            )
        except Exception as e:
            logger.warning(f"[MyquantFetcher] get_realtime_quote failed for {stock_code}: {e}")
            return None
