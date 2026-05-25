"""
Tencent财经 HTTP API fetcher for enhanced realtime quotes.

API: https://qt.gtimg.cn/q={prefix_code}
Returns: GBK encoded, `~` delimited fields (88 fields total)

Key fields used:
- 39: PE(TTM), 43: 振幅%, 44: 总市值(亿), 45: 流通市值(亿)
- 46: PB, 49: 量比, 52: PE(静)
"""

import logging
import urllib.request
from typing import Optional

from ..base import BaseFetcher, DataCapability, DataFetchError
from ..core.types import RealtimeSource, UnifiedRealtimeQuote, safe_float
from ..utils.normalize import normalize_stock_code

logger = logging.getLogger(__name__)

# Tencent财经 API base URL
TENCENT_QUOTE_URL = "https://qt.gtimg.cn/q="


class TencentFetcher(BaseFetcher):
    """Tencent财经 HTTP API fetcher for enhanced realtime quotes."""

    name = "TencentFetcher"
    priority = 5  # After Tushare(0), Baostock(1), Akshare(2), Yfinance(3), Zhitu(4)
    supported_markets: set[str] = {"csi", "hk"}
    supported_data_types = DataCapability.REALTIME_QUOTE

    def is_available(self) -> bool:
        """Tencent API is always available (no auth required)."""
        return True

    def _tencent_prefix(self, stock_code: str) -> str:
        """Convert to Tencent API prefix format.

        Shanghai: sh600519, Shenzhen: sz000001, HK: hk00700, BJ: bj832000
        """
        code = normalize_stock_code(stock_code)

        if code.startswith(("5", "6", "7", "9")):
            return f"sh{code}"
        elif code.startswith(("0", "1", "2", "3", "4")):
            return f"sz{code}"
        elif code.upper().startswith("HK"):
            return f"hk{code[2:].zfill(5)}"
        elif code.startswith("8") or code.startswith("4"):
            return f"bj{code}"
        else:
            return f"sz{code}"

    def _fetch_raw_data(
        self,
        stock_code: str,
        start_date: str,
        end_date: str,
        frequency: str = "d",
        adjust: str | None = None,
    ) -> None:
        """Tencent API is realtime-only, not used for historical data."""
        raise DataFetchError(
            "TencentFetcher does not support historical K-line data, only realtime quotes"
        )

    def _normalize_data(self, df: None, stock_code: str) -> None:
        """Tencent API is realtime-only, not used for historical data."""
        raise DataFetchError("TencentFetcher does not support historical K-line data")

    def get_realtime_quote(self, stock_code: str) -> Optional[UnifiedRealtimeQuote]:
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

    def _parse_tencent_response(self, data: str, stock_code: str) -> Optional[UnifiedRealtimeQuote]:
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

            return UnifiedRealtimeQuote(
                code=normalize_stock_code(stock_code),
                name=values[1] if len(values) > 1 else "",
                source=RealtimeSource.TENCENT,
                price=safe_float(values[3]) if len(values) > 3 and values[3] else None,
                pre_close=safe_float(values[4]) if len(values) > 4 and values[4] else None,
                open_price=safe_float(values[5]) if len(values) > 5 and values[5] else None,
                volume=safe_float(values[36]) * 100 if len(values) > 36 and values[36] else None,  # 手 -> shares
                amount=safe_float(values[37]) * 10000 if len(values) > 37 and values[37] else None,  # 万元 -> 元
                change_amount=safe_float(values[31]) if len(values) > 31 and values[31] else None,
                change_pct=safe_float(values[32]) if len(values) > 32 and values[32] else None,
                high=safe_float(values[33]) if len(values) > 33 and values[33] else None,
                low=safe_float(values[34]) if len(values) > 34 and values[34] else None,
                turnover_rate=safe_float(values[38]) if len(values) > 38 and values[38] else None,
                pe_ratio=safe_float(values[39]) if len(values) > 39 and values[39] else None,
                amplitude=safe_float(values[43]) if len(values) > 43 and values[43] else None,
                total_mv=safe_float(values[44]) * 1e8 if len(values) > 44 and values[44] else None,  # 亿 -> 元
                circ_mv=safe_float(values[45]) * 1e8 if len(values) > 45 and values[45] else None,  # 亿 -> 元
                pb_ratio=safe_float(values[46]) if len(values) > 46 and values[46] else None,
                volume_ratio=safe_float(values[49]) if len(values) > 49 and values[49] else None,
            )
        except Exception as e:
            logger.warning(f"[TencentFetcher] Parse error for {stock_code}: {e}")
            return None