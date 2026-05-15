"""
Zhitu fetcher for A-share realtime quote (Priority 99).

API: https://api.zhituapi.com/hs/real/ssjy/{stock_code}?token={token}
Token configured via ZHITU_TOKEN environment variable.
"""

import logging
import os
from datetime import date

import pandas as pd
import requests

from .base import BaseFetcher, DataCapability, DataFetchError, normalize_stock_code
from .realtime_types import RealtimeSource, UnifiedRealtimeQuote, safe_float, safe_int

logger = logging.getLogger(__name__)

# API base URL
ZHITU_API_BASE = "https://api.zhituapi.com"


class ZhituFetcher(BaseFetcher):
    """Zhitu API fetcher for A-share realtime quotes (no historical data)."""

    name = "ZhituFetcher"
    priority = int(os.getenv("ZHITU_PRIORITY", "4"))
    supported_markets: set[str] = {"csi"}
    supported_data_types = DataCapability.REALTIME_QUOTE

    def __init__(self):
        self._token = os.getenv("ZHITU_TOKEN", "").strip()

    def is_available(self) -> bool:
        """Check if Zhitu API token is configured."""
        return bool(self._token)

    def _convert_code(self, stock_code: str) -> str:
        """
        Convert stock code to Zhitu format.

        Zhitu expects 6-digit code without exchange suffix.
        Examples:
            600519 -> 600519
            000001 -> 000001
        """
        code = normalize_stock_code(stock_code)
        return code

    def _fetch_raw_data(
        self,
        stock_code: str,
        start_date: str,
        end_date: str,
        frequency: str = "d",
        adjust: str | None = None,
    ) -> pd.DataFrame:
        """Zhitu does not support historical data, only realtime quotes."""
        raise DataFetchError(
            "ZhituFetcher does not support historical K-line data, only realtime quotes"
        )

    def _normalize_data(self, df: pd.DataFrame, stock_code: str) -> pd.DataFrame:
        """Zhitu does not support historical data normalization."""
        raise DataFetchError("ZhituFetcher does not support historical K-line data")

    def get_realtime_quote(self, stock_code: str) -> UnifiedRealtimeQuote | None:
        """Get realtime quote from Zhitu API.

        Args:
            stock_code: Stock code (e.g., 600519, 000001)

        Returns:
            UnifiedRealtimeQuote with realtime data, or None if unavailable.
        """
        if not self.is_available():
            logger.warning("[ZhituFetcher] ZHITU_TOKEN not configured")
            return None

        try:
            code = self._convert_code(stock_code)
            url = f"{ZHITU_API_BASE}/hs/real/ssjy/{code}"
            params = {"token": self._token}

            response = requests.get(url, params=params, timeout=10)
            response.raise_for_status()

            data = response.json()

            # Check for error response
            if isinstance(data, dict) and "detail" in data:
                error_msg = data.get("detail", "Unknown error")
                if "Licence证书" in str(error_msg) or "不存在" in str(error_msg):
                    logger.warning(f"[ZhituFetcher] Invalid token: {error_msg}")
                else:
                    logger.warning(f"[ZhituFetcher] API error: {error_msg}")
                return None

            # Zhitu returns a dict directly (not a list)
            if not isinstance(data, dict):
                logger.warning(
                    f"[ZhituFetcher] Unexpected response type for {stock_code}: {type(data)}"
                )
                return None

            if not data:
                logger.warning(f"[ZhituFetcher] Empty response for {stock_code}")
                return None

            row = data

            return UnifiedRealtimeQuote(
                code=normalize_stock_code(stock_code),
                name=str(row.get("nm", "")),
                source=RealtimeSource.ZHITU,
                price=safe_float(row.get("p")),
                change_pct=safe_float(row.get("pc")),
                change_amount=safe_float(row.get("ud")),
                volume=safe_int(row.get("v")),
                amount=safe_float(row.get("cje")),
                open_price=safe_float(row.get("o")),
                high=safe_float(row.get("h")),
                low=safe_float(row.get("l")),
                pre_close=safe_float(row.get("yc")),
                amplitude=safe_float(row.get("zf")),
                volume_ratio=safe_float(row.get("lb")),
                turnover_rate=safe_float(row.get("hs")),
                pe_ratio=safe_float(row.get("pe")),
                pb_ratio=safe_float(row.get("sjl")),
                total_mv=safe_float(row.get("sz")),
                circ_mv=safe_float(row.get("lt")),
            )

        except requests.exceptions.Timeout:
            logger.warning(f"[ZhituFetcher] Timeout for {stock_code}")
            return None
        except requests.exceptions.RequestException:
            logger.warning(f"[ZhituFetcher] Request failed for {stock_code}", exc_info=True)
            return None
        except Exception:
            logger.warning(f"[ZhituFetcher] Error for {stock_code}", exc_info=True)
            return None

    def _market_suffix(self, stock_code: str) -> str:
        """Return .SZ or .SH for Zhitu API."""
        code = normalize_stock_code(stock_code)
        # Beijing Stock Exchange
        if len(code) == 6 and code.startswith(("83", "87", "43", "82", "88", "92", "81")):
            return ".BJ"
        # Shanghai
        if code.startswith(("6", "5")):
            return ".SH"
        # Shenzhen
        return ".SZ"

    def get_intraday_data(
        self, stock_code: str, period: str = "5", adjust: str = ""
    ) -> pd.DataFrame | None:
        """Get intraday minute-level data from Zhitu history API.

        API: https://api.zhituapi.com/hs/history/{code}.{market}/{period}/{adjust}?token={token}&st={date}&et={date}

        Args:
            stock_code: Stock code (e.g., 600519, 000001)
            period: Minute period - "5", "15", "30", "60" (NOT "1")
            adjust: Adjustment type - ""=不复权, "qfq"=前复权, "hfq"=后复权

        Returns:
            DataFrame with columns: time, open, high, low, close, volume, amount
            or None if not supported or period=1 (not supported by Zhitu).
        """
        if not self.is_available():
            logger.warning("[ZhituFetcher] ZHITU_TOKEN not configured")
            return None

        # Zhitu doesn't support period=1
        if period == "1":
            raise DataFetchError("ZhituFetcher does not support period=1")

        try:
            code = normalize_stock_code(stock_code)
            market = self._market_suffix(stock_code)
            symbol = f"{code}{market}"

            # Map adjust: API format
            adj_map = {"": "n", "qfq": "f", "hfq": "b"}
            adj_value = adj_map.get(adjust, "n")

            # Get latest trade date
            from .stock_cache import get_latest_cached_trade_date

            latest_date = get_latest_cached_trade_date()
            if not latest_date:
                latest_date = date.today().strftime("%Y%m%d")
            else:
                latest_date = latest_date.replace("-", "")

            url = f"{ZHITU_API_BASE}/hs/history/{symbol}/{period}/{adj_value}"
            params = {
                "token": self._token,
                "st": latest_date,
                "et": latest_date,
            }

            response = requests.get(url, params=params, timeout=10)
            response.raise_for_status()
            data = response.json()

            if isinstance(data, dict) and "detail" in data:
                logger.warning(f"[ZhituFetcher] API error: {data.get('detail')}")
                return None

            if not isinstance(data, list):
                logger.warning(f"[ZhituFetcher] Unexpected response type: {type(data)}")
                return None

            if not data:
                return None

            df = pd.DataFrame(data)
            return self._normalize_intraday_zhitu(df)

        except DataFetchError:
            raise
        except requests.exceptions.Timeout:
            logger.warning(f"[ZhituFetcher] Timeout for {stock_code}")
            return None
        except requests.exceptions.RequestException:
            logger.warning(f"[ZhituFetcher] Request failed for {stock_code}", exc_info=True)
            return None
        except Exception:
            logger.warning(f"[ZhituFetcher] Error for {stock_code}", exc_info=True)
            return None

    def _normalize_intraday_zhitu(self, df: pd.DataFrame) -> pd.DataFrame:
        """Normalize Zhitu history API output."""
        df = df.copy()
        df = df.rename(
            columns={
                "t": "time",
                "o": "open",
                "h": "high",
                "l": "low",
                "c": "close",
                "v": "volume",
                "a": "amount",
            }
        )
        if "time" in df.columns:
            # Zhitu returns ISO format with T, extract HH:MM:SS
            df["time"] = df["time"].astype(str).str[-8:]
        numeric_cols = ["open", "high", "low", "close", "volume", "amount"]
        for col in numeric_cols:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")
        keep_cols = ["time", "open", "high", "low", "close", "volume", "amount"]
        df = df[[c for c in keep_cols if c in df.columns]]
        return df
