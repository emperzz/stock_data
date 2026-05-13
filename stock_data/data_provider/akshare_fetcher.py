"""
Akshare fetcher for A-share and HK stock data (Priority 2).

Support for both A-shares and Hong Kong stocks.
"""

import logging
import os
from typing import Optional

import pandas as pd

from .base import (
    STANDARD_COLUMNS,
    BaseFetcher,
    DataFetchError,
    get_index_type,
    is_hk_market,
    is_index_code,
    normalize_stock_code,
)
from .index_symbols import US_INDEX_AKSHARE_MAP
from .realtime_types import RealtimeSource, UnifiedRealtimeQuote, safe_float, safe_int

logger = logging.getLogger(__name__)


class AkshareFetcher(BaseFetcher):
    """Akshare library fetcher for A-share and HK stock data."""

    name = "AkshareFetcher"
    priority = int(os.getenv("AKSHARE_PRIORITY", "2"))

    def _convert_to_akshare_code(self, stock_code: str) -> str:
        """
        Convert stock code to akshare format.

        A-share:
            600519 -> 600519
            000001 -> 000001
        HK:
            HK00700 -> 00700.hk
            00700 -> 00700.hk
        CSI index:
            000300 -> 000300
        US index:
            SPX -> .INX (Sina format via index_us_stock_sina)
        """
        code = normalize_stock_code(stock_code)

        # Check if it's an index
        if is_index_code(code):
            index_type = get_index_type(code)
            if index_type == "us":
                return US_INDEX_AKSHARE_MAP.get(code, code)
            elif index_type == "hk":
                return code  # HK indices need special EM handling in _fetch_raw_data
            # CSI indices use same 6-digit format as A-share stocks
            return code

        if is_hk_market(code):
            if code.startswith("HK"):
                code = code[2:]
            return f"{code.lstrip('0')}.hk"

        return code

    def _fetch_raw_data(
        self, stock_code: str, start_date: str, end_date: str, frequency: str = "d", adjust: Optional[str] = None
    ) -> pd.DataFrame:
        """Fetch daily K-line data from Akshare (supports d/w/m for stocks and indices).

        Args:
            stock_code: Stock code
            start_date: Start date (YYYY-MM-DD)
            end_date: End date (YYYY-MM-DD)
            frequency: K-line frequency - 'd'=日线, 'w'=周线, 'm'=月线
            adjust: Adjustment type - None/''=不复权, 'qfq'=前复权, 'hfq'=后复权.
        """
        try:
            import akshare as ak

            code = self._convert_to_akshare_code(stock_code)
            is_hk = is_hk_market(stock_code)
            is_index = is_index_code(stock_code)
            index_type = get_index_type(stock_code) if is_index else None

            logger.debug(f"[AkshareFetcher] Fetching {code} ({frequency})")

            # Akshare period mapping
            period_map = {"d": "daily", "w": "weekly", "m": "monthly"}
            period = period_map.get(frequency, "daily")

            # Minute frequencies not supported
            if frequency in ("5", "15", "30", "60"):
                raise DataFetchError("Akshare does not support minute frequency for indices")

            # Map adjust parameter to akshare adjust value
            # None or empty string means no adjustment (use '' for不复权)
            # 'qfq' for forward-adjusted, 'hfq' for backward-adjusted
            if adjust in ("qfq", "2"):
                adj_value = "qfq"  # Forward-adjusted
            elif adjust in ("hfq", "1"):
                adj_value = "hfq"  # Backward-adjusted
            else:
                adj_value = ""  # No adjustment (不复权)

            if is_index and index_type == "us":
                # US indices via index_us_stock_sina (.IXIC, .INX, .DJI, etc.)
                df = ak.index_us_stock_sina(symbol=code)
            elif is_index and index_type == "hk":
                # HK indices require EM-format symbols that need runtime lookup
                # Not easily predictable, let failover handle
                raise DataFetchError(
                    f"Akshare does not support HK index {code} (EM symbol lookup needed)"
                )
            elif is_hk:
                df = ak.stock_hk_hist(
                    symbol=code.replace(".hk", ""),
                    period=period,
                    start_date=start_date.replace("-", ""),
                    end_date=end_date.replace("-", ""),
                    adjust=adj_value,
                )
            elif is_index and index_type == "csi":
                # CSI indices use index_zh_a_hist (no adjustment support)
                df = ak.index_zh_a_hist(
                    symbol=code,
                    period=period,
                    start_date=start_date.replace("-", ""),
                    end_date=end_date.replace("-", ""),
                )
            else:
                df = ak.stock_zh_a_hist(
                    symbol=code,
                    period=period,
                    start_date=start_date,
                    end_date=end_date,
                    adjust=adj_value,
                )

            if df is None or df.empty:
                raise DataFetchError(f"Akshare returned no data for {stock_code}")

            return df

        except DataFetchError:
            raise
        except ImportError:
            raise DataFetchError("akshare not installed") from None
        except Exception as e:
            raise DataFetchError(f"AkshareFetcher fetch failed: {e}") from e

    def _normalize_data(self, df: pd.DataFrame, stock_code: str) -> pd.DataFrame:
        """Normalize Akshare data to standard columns."""
        df = df.copy()

        column_mapping = {
            "日期": "date",
            "开盘": "open",
            "收盘": "close",
            "最高": "high",
            "最低": "low",
            "成交量": "volume",
            "成交额": "amount",
            "涨跌幅": "pct_chg",
            "股票代码": "code",
        }

        df = df.rename(columns=column_mapping)

        if "date" in df.columns:
            df["date"] = pd.to_datetime(df["date"])

        numeric_cols = ["open", "high", "low", "close", "volume", "amount", "pct_chg"]
        for col in numeric_cols:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")

        if "code" not in df.columns:
            df["code"] = normalize_stock_code(stock_code)

        keep_cols = ["code"] + [c for c in STANDARD_COLUMNS if c in df.columns]
        df = df[[c for c in keep_cols if c in df.columns]]

        return df

    def get_realtime_quote(self, stock_code: str) -> UnifiedRealtimeQuote | None:
        """Get realtime quote from Akshare."""
        try:
            import akshare as ak

            code = self._convert_to_akshare_code(stock_code)
            is_hk = is_hk_market(stock_code)
            is_index = is_index_code(stock_code)

            if is_hk:
                df = ak.stock_hk_spot_em()
                symbol = code.replace(".hk", "").lstrip("0")
                row = df[df["代码"] == symbol]
                if row.empty:
                    return None
                row = row.iloc[0]
            elif is_index:
                # CSI/HK indices - use index_zh_a_spot_em for CSI, skip HK (EM symbols unpredictable)
                index_type = get_index_type(stock_code)
                if index_type == "csi":
                    df = ak.index_zh_a_spot_em(symbol=code)
                    row = df[df["代码"] == code]
                    if row.empty:
                        return None
                    row = row.iloc[0]
                else:
                    # HK indices need EM-format symbols that require runtime lookup
                    logger.warning(
                        f"[AkshareFetcher] HK index {stock_code} realtime quote not supported (EM symbol lookup needed)"
                    )
                    return None
            else:
                df = ak.stock_zh_a_spot_em()
                row = df[df["代码"] == code]
                if row.empty:
                    return None
                row = row.iloc[0]

            return UnifiedRealtimeQuote(
                code=normalize_stock_code(stock_code),
                name=str(row.get("名称", "")),
                source=RealtimeSource.AKSHARE,
                price=safe_float(row.get("最新价")),
                change_pct=safe_float(row.get("涨跌幅")),
                change_amount=safe_float(row.get("涨跌额")),
                volume=safe_int(row.get("成交量")),
                amount=safe_float(row.get("成交额")),
                open_price=safe_float(row.get("今开")),
                high=safe_float(row.get("最高")),
                low=safe_float(row.get("最低")),
                pre_close=safe_float(row.get("昨收")),
                amplitude=safe_float(row.get("振幅")),
                turnover_rate=safe_float(row.get("换手率")),
                volume_ratio=safe_float(row.get("量比")),
                pe_ratio=safe_float(row.get("市盈率")),
                pb_ratio=safe_float(row.get("市净率")),
            )

        except Exception as e:
            logger.warning(f"[AkshareFetcher] Realtime quote failed: {e}")
            return None

    def get_all_stocks(self, market: str = "cn") -> list:
        """
        Get all available stocks for a market.

        Args:
            market: Market type - cn (A-share), hk, us

        Returns:
            List of dicts: [{"code": "600519", "name": "贵州茅台"}, ...]
        """
        try:
            import akshare as ak

            result = []

            if market == "cn":
                # A-share stocks via stock_info_a_code_name
                df = ak.stock_info_a_code_name()
                if df is not None and not df.empty:
                    for _, row in df.iterrows():
                        code = str(row.get("code", "")).strip()
                        name = str(row.get("name", "")).strip()
                        if code:
                            result.append({"code": code, "name": name})

            elif market == "hk":
                # HK stocks via stock_hk_spot_em
                df = ak.stock_hk_spot_em()
                if df is not None and not df.empty:
                    for _, row in df.iterrows():
                        code = str(row.get("代码", "")).strip()
                        name = str(row.get("名称", "")).strip()
                        if code:
                            # Normalize to HK prefix: 00700 -> HK00700
                            code = f"HK{int(code):05d}" if code.isdigit() else code
                            result.append({"code": code, "name": name})

            elif market == "us":
                # US stocks via major indices components (simplified)
                # Get S&P 500 components as a representative sample
                try:
                    df = ak.index_cons_sina(symbol="SPX")
                    if df is not None and not df.empty:
                        for _, row in df.iterrows():
                            code = str(row.get("symbol", "")).strip()
                            name = str(row.get("name", "")).strip()
                            if code:
                                result.append({"code": code, "name": name})
                except Exception as e:
                    logger.warning(f"[AkshareFetcher] US stocks fetch failed: {e}")

            return result

        except Exception as e:
            logger.warning(f"[AkshareFetcher] get_all_stocks failed: {e}")
            return []
