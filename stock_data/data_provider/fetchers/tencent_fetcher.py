"""
Tencent财经 HTTP API fetcher for enhanced realtime quotes.

API: https://qt.gtimg.cn/q={prefix_code}
Returns: GBK encoded, `~` delimited fields (88 fields total)

Key fields used:
- 39: PE(TTM), 43: 振幅%, 44: 总市值(亿), 45: 流通市值(亿)
- 46: PB, 49: 量比, 52: PE(静)
"""

import logging
import os
import urllib.request

import pandas as pd

from ..base import BaseFetcher, DataCapability, DataFetchError
from ..core.types import RealtimeSource, UnifiedRealtimeQuote, safe_float
from ..utils.code_converter import to_tencent_prefix
from ..utils.normalize import normalize_stock_code

logger = logging.getLogger(__name__)

# Tencent财经 API base URL
TENCENT_QUOTE_URL = "https://qt.gtimg.cn/q="


class TencentFetcher(BaseFetcher):
    """Tencent财经 HTTP API fetcher for enhanced realtime quotes."""

    name = "TencentFetcher"
    priority = int(os.getenv("TENCENT_PRIORITY", "5"))
    supported_markets: set[str] = {"csi", "hk"}
    supported_data_types = DataCapability.REALTIME_QUOTE

    def is_available(self) -> bool:
        """Tencent API is always available (no auth required)."""
        return True

    def _tencent_prefix(self, stock_code: str) -> str:
        """Convert to Tencent API prefix. Delegates to ``to_tencent_prefix``."""
        return to_tencent_prefix(stock_code)

    def _fetch_raw_data(
        self,
        stock_code: str,
        start_date: str,
        end_date: str,
        frequency: str = "d",
        adjust: str | None = None,
    ) -> pd.DataFrame:
        """Tencent API is realtime-only, not used for historical data."""
        raise DataFetchError(
            "TencentFetcher does not support historical K-line data, only realtime quotes"
        )

    def _normalize_data(self, df: pd.DataFrame, stock_code: str) -> pd.DataFrame:
        """Tencent API is realtime-only, not used for historical data."""
        raise DataFetchError("TencentFetcher does not support historical K-line data")

    def get_realtime_quote(self, stock_code: str) -> UnifiedRealtimeQuote | None:
        """Get realtime quote from Tencent财经 API.

        Returns enhanced fields including PE/PB/市值/涨跌停价.

        Args:
            stock_code: Stock code (e.g., 600519, 000001, HK00700, 00700)

        Returns:
            UnifiedRealtimeQuote with enhanced fields, or None if unavailable.
        """
        try:
            prefix = self._tencent_prefix(stock_code)
            url = f"{TENCENT_QUOTE_URL}{prefix}"

            req = urllib.request.Request(url)
            req.add_header("User-Agent", "Mozilla/5.0")
            resp = urllib.request.urlopen(req, timeout=10)
            data = resp.read().decode("gbk")

            return self._parse_tencent_response(data, stock_code)

        except Exception as e:
            logger.warning(f"[TencentFetcher] Error for {stock_code}: {e}")
            return None

    def _parse_tencent_response(self, data: str, stock_code: str) -> UnifiedRealtimeQuote | None:
        """Parse Tencent财经 response.

        Response format: v_pv_title="data~field1~field2~...";
        Field index reference (0-based):
            0:  stock code with prefix (e.g., sh600519)
            1:  stock name
            3:  current price
            4:  yesterday close
            5:  open price
            31: change amount
            32: change percent
            33: high
            34: low
            37: amount (万元)
            38: turnover rate (%)
            39: PE(TTM)
            43: amplitude (%)
            44: total market cap (亿)
            45: float market cap (亿)
            46: PB
            47: limit up price
            48: limit down price
            49: volume ratio
            52: PE(static)
        """
        if not data or "=" not in data:
            return None

        try:
            line = data.strip()
            if line.endswith(";"):
                line = line[:-1]
            if "=" not in line:
                return None

            if '"' not in line:
                return None

            values = line.split('"')[1].split("~")
            if len(values) < 53:
                logger.warning(f"[TencentFetcher] Insufficient fields for {stock_code}: {len(values)}")
                return None

            def v(idx: int, scale: float = 1.0) -> float | None:
                """Parse a single `~`-delimited field, applying a unit scale.

                Centralises the (bounds-check, empty-check, float-coerce, scale)
                sequence that was previously open-coded 13 times in this constructor.
                Returns None on any failure rather than letting ``None * scale``
                raise ``TypeError``.
                """
                if idx >= len(values) or not values[idx]:
                    return None
                f = safe_float(values[idx])
                return f * scale if f is not None else None

            return UnifiedRealtimeQuote(
                code=normalize_stock_code(stock_code),
                name=values[1] if len(values) > 1 else "",
                source=RealtimeSource.TENCENT,
                price=v(3),
                pre_close=v(4),
                open_price=v(5),
                volume=v(36, 100),  # 手 -> shares
                amount=v(37, 10000),  # 万元 -> 元
                change_amount=v(31),
                change_pct=v(32),
                high=v(33),
                low=v(34),
                turnover_rate=v(38),
                pe_ratio=v(39),
                amplitude=v(43),
                total_mv=v(44, 1e8),  # 亿 -> 元
                circ_mv=v(45, 1e8),  # 亿 -> 元
                pb_ratio=v(46),
                volume_ratio=v(49),
            )
        except Exception as e:
            logger.warning(f"[TencentFetcher] Parse error for {stock_code}: {e}")
            return None
