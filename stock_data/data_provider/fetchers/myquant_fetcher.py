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
from datetime import datetime  # used in get_trade_calendar (Task 7) and get_index_intraday (Task 9)

import pandas as pd

from ..base import BaseFetcher, DataCapability, DataFetchError, normalize_stock_code
from ..core.types import RealtimeSource, UnifiedRealtimeQuote, safe_float
from ..utils.code_converter import to_myquant_format, to_myquant_index_format
# isort: on

logger = logging.getLogger(__name__)

# myquant adjust constants (see gm.api)
ADJUST_NONE = 0  # 不复权
ADJUST_PREV = 1  # 前复权
ADJUST_POST = 2  # 后复权

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

    def get_trade_calendar(self) -> list[str] | None:
        """Get A-share trade calendar from myquant.

        Uses SHSE calendar (沪深共用). Returns ascending YYYY-MM-DD list.
        Returns None if unavailable or no data.
        """
        if not self.is_available():
            return None
        try:
            from gm.api import get_trading_dates_by_year  # type: ignore

            now = datetime.now()
            df = get_trading_dates_by_year(
                exchange="SHSE",
                start_year=2010,
                end_year=now.year,
            )
            if df is None or df.empty or "trade_date" not in df.columns:
                return None
            # myquant sets trade_date="" for non-trading days; filter those out
            dates = [
                d
                for d in df["trade_date"].astype(str).tolist()
                if d and d not in ("", "nan", "None")
            ]
            return sorted(dates)
        except Exception as e:
            logger.warning(f"[MyquantFetcher] get_trade_calendar failed: {e}")
            return None

    def get_all_stocks(self, market: str = "csi") -> list:
        """Get A-share stock list from myquant.

        myquant's ``get_symbols(sec_type1=1010)`` returns additional fields
        beyond code/name: upper_limit / lower_limit / is_st / is_suspended /
        pre_close / turn_rate / adj_factor. We surface these as raw dict keys
        so the persistence layer can optionally consume them.

        Returns ``[]`` for non-CSI markets (myquant only covers A-share).
        """
        if market != "csi":
            return []
        if not self.is_available():
            return []
        try:
            from gm.api import get_symbols  # type: ignore

            df = get_symbols(sec_type1=1010, df=True)
            if df is None or df.empty:
                return []
            out: list = []
            for _, row in df.iterrows():
                full = str(row.get("symbol", ""))
                code = full.split(".", 1)[1] if "." in full else full
                out.append(
                    {
                        "code": code,
                        "name": str(row.get("sec_name", "")),
                        "symbol_full": full,
                        "exchange": str(row.get("exchange", "")),
                        "is_st": bool(row.get("is_st", False)),
                        "is_suspended": bool(row.get("is_suspended", False)),
                        "upper_limit": safe_float(row.get("upper_limit")),
                        "lower_limit": safe_float(row.get("lower_limit")),
                        "turn_rate": safe_float(row.get("turn_rate")),
                        "adj_factor": safe_float(row.get("adj_factor")),
                        "pre_close": safe_float(row.get("pre_close")),
                    }
                )
            return out
        except Exception as e:
            logger.warning(f"[MyquantFetcher] get_all_stocks failed: {e}")
            return []

    def get_index_historical(
        self,
        index_code: str,
        start_date: str | None,
        end_date: str | None,
        frequency: str,
    ) -> pd.DataFrame | None:
        """Get historical K-line data for a CSI index via myquant.

        Only ``frequency="d"`` is supported. Weekly/monthly would need
        separate ``history`` calls aggregated client-side, which we don't
        implement here — the manager will fall through to other fetchers.
        """
        if not self.is_available():
            return None
        if frequency != "d":
            raise DataFetchError(
                f"MyquantFetcher index does not support frequency={frequency!r} "
                "(only 'd' is supported; use another fetcher for w/m)"
            )
        try:
            symbol = to_myquant_index_format(index_code)
        except ValueError as e:
            raise DataFetchError(f"Myquant does not support {index_code}: {e}") from e
        try:
            from gm.api import history  # type: ignore

            df = history(
                symbol=symbol,
                frequency="1d",
                start_time=start_date or "",
                end_time=end_date or "",
                df=True,
            )
            if df is None or df.empty:
                return None
            return self._normalize_index_df(df)
        except DataFetchError:
            raise
        except Exception as e:
            logger.warning(f"[MyquantFetcher] get_index_historical failed for {index_code}: {e}")
            return None

    def get_index_intraday(self, index_code: str, period: str = "5") -> pd.DataFrame | None:
        """Get intraday minute-level data for a CSI index via myquant.

        Fetches the most recent trading day (myquant 18:00 wash rule applies
        for same-day data; for older dates the result is also fine).
        """
        if not self.is_available():
            return None
        if period not in _INDEX_FREQ_MAP:
            raise DataFetchError(
                f"MyquantFetcher index intraday does not support period={period!r} "
                f"(supported: {sorted(_INDEX_FREQ_MAP.keys())})"
            )
        try:
            symbol = to_myquant_index_format(index_code)
        except ValueError as e:
            raise DataFetchError(f"Myquant does not support {index_code}: {e}") from e
        try:
            from gm.api import history  # type: ignore

            today = datetime.now().strftime("%Y-%m-%d")
            df = history(
                symbol=symbol,
                frequency=_INDEX_FREQ_MAP[period],
                start_time=today,
                end_time=today,
                df=True,
            )
            if df is None or df.empty:
                return None
            return self._normalize_index_intraday_df(df, period)
        except DataFetchError:
            raise
        except Exception as e:
            logger.warning(f"[MyquantFetcher] get_index_intraday failed for {index_code}: {e}")
            return None

    def _normalize_index_df(self, df: pd.DataFrame) -> pd.DataFrame:
        """Normalize myquant daily-index history to STANDARD_COLUMNS + 'code'."""
        df = df.copy()
        if "bob" in df.columns:
            df = df.rename(columns={"bob": "date"})
        if "pct_chg" not in df.columns and "open" in df.columns and "close" in df.columns:
            open_num = pd.to_numeric(df["open"], errors="coerce")
            close_num = pd.to_numeric(df["close"], errors="coerce")
            df["pct_chg"] = ((close_num / open_num) - 1.0) * 100.0
        # No 'code' column needed for index history; strip symbol-related noise
        for col in ("symbol", "frequency"):
            if col in df.columns:
                df = df.drop(columns=[col])
        return df

    def _normalize_index_intraday_df(self, df: pd.DataFrame, period: str) -> pd.DataFrame:
        """Normalize myquant index intraday to time/o/h/l/c/v/a schema."""
        df = df.copy()
        if "bob" in df.columns:
            df = df.rename(columns={"bob": "time"})
        elif "eob" in df.columns:
            df = df.rename(columns={"eob": "time"})
        # Coerce to HH:MM:SS strings if datetime
        if "time" in df.columns and hasattr(df["time"].iloc[0] if len(df) else None, "strftime"):
            df["time"] = df["time"].dt.strftime("%H:%M:%S")
        for col in ("open", "high", "low", "close", "amount"):
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")
        if "volume" in df.columns:
            df["volume"] = pd.to_numeric(df["volume"], errors="coerce").astype("Int64")
        keep = [
            c
            for c in ("time", "open", "high", "low", "close", "volume", "amount")
            if c in df.columns
        ]
        return df[keep]
