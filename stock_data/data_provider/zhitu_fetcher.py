"""
Zhitu fetcher for A-share realtime quote (Priority 99).

API: https://api.zhituapi.com/hs/real/ssjy/{stock_code}?token={token}
Token configured via ZHITU_TOKEN environment variable.
"""

import logging
import os

import pandas as pd
import requests

from .base import BaseFetcher, DataFetchError, normalize_stock_code
from .realtime_types import RealtimeSource, UnifiedRealtimeQuote, safe_float, safe_int

logger = logging.getLogger(__name__)

# API base URL
ZHITU_API_BASE = "https://api.zhituapi.com"


class ZhituFetcher(BaseFetcher):
    """Zhitu API fetcher for A-share realtime quotes."""

    name = "ZhituFetcher"
    priority = int(os.getenv("ZHITU_PRIORITY", "4"))  # After YfinanceFetcher

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
        self, stock_code: str, start_date: str, end_date: str, frequency: str = "d", adjust: str | None = None
    ) -> pd.DataFrame:
        """Zhitu does not support historical data, only realtime quotes."""
        raise DataFetchError("ZhituFetcher does not support historical K-line data, only realtime quotes")

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
                logger.warning(f"[ZhituFetcher] Unexpected response type for {stock_code}: {type(data)}")
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
        except requests.exceptions.RequestException as e:
            logger.warning(f"[ZhituFetcher] Request failed: {e}")
            return None
        except Exception as e:
            logger.warning(f"[ZhituFetcher] Error: {e}")
            return None
