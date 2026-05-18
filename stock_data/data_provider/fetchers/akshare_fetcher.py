"""
Akshare fetcher for A-share and HK stock data (Priority 2).

Support for both A-shares and Hong Kong stocks.
"""

import logging
import os

import pandas as pd

from ..base import (
    BaseFetcher,
    DataCapability,
    DataFetchError,
    is_hk_market,
    normalize_stock_code,
)
from ..core.types import RealtimeSource, UnifiedRealtimeQuote, safe_float, safe_int
from ..utils.normalize import get_index_type, is_index_code
from .index_symbols import US_INDEX_AKSHARE_MAP

logger = logging.getLogger(__name__)


class AkshareFetcher(BaseFetcher):
    """Akshare library fetcher for A-share and HK stock data."""

    name = "AkshareFetcher"
    priority = int(os.getenv("AKSHARE_PRIORITY", "2"))
    supported_markets: set[str] = {"csi", "hk"}
    supported_data_types = (
        DataCapability.HISTORICAL_DWM
        | DataCapability.REALTIME_QUOTE
        | DataCapability.STOCK_LIST
        | DataCapability.STOCK_NAME
        | DataCapability.TRADE_CALENDAR
        | DataCapability.STOCK_BOARD
    )

    def _map_adjust(self, adjust: str) -> str | None:
        """Map unified adjust to Akshare adjust value."""
        if not adjust:
            return ""  # 不复权
        mapping = {"qfq": "qfq", "hfq": "hfq"}
        return mapping.get(adjust, "")

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
                entry = US_INDEX_AKSHARE_MAP.get(code)
                return entry[0] if entry is not None else code
            elif index_type == "hk":
                return code  # HK indices need special EM handling in _fetch_raw_data
            # CSI indices use same 6-digit format as A-share stocks
            return code

        if is_hk_market(code):
            if code.startswith("HK"):
                code = code[2:]
            # Keep leading zeros: normalize_stock_code ensures HK codes are zero-padded to 5 digits
            return f"{code}.hk"

        return code

    def _fetch_raw_data(
        self,
        stock_code: str,
        start_date: str,
        end_date: str,
        frequency: str = "d",
        adjust: str | None = None,
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

            # adjust is already mapped by _map_adjust
            adj_value = adjust or ""

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
        return self._normalize_dataframe(
            df,
            stock_code,
            {
                "日期": "date",
                "开盘": "open",
                "收盘": "close",
                "最高": "high",
                "最低": "low",
                "成交量": "volume",
                "成交额": "amount",
                "涨跌幅": "pct_chg",
                "股票代码": "code",
            },
        )

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
                    df = ak.stock_zh_index_spot_em(symbol=code)
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

        except Exception:
            logger.warning(
                f"[AkshareFetcher] Realtime quote failed for {stock_code}", exc_info=True
            )
            return None

    def get_stock_name(self, stock_code: str) -> str | None:
        """Get stock name from Akshare stock info."""
        try:
            import akshare as ak

            code = normalize_stock_code(stock_code)

            # A-share: use stock_info_a_code_name
            if code.startswith(("6", "5", "0", "3")):
                df = ak.stock_info_a_code_name()
                if df is not None and not df.empty:
                    match = df[df["code"] == code]
                    if not match.empty:
                        return str(match.iloc[0].get("name", "")).strip()

            # HK: use stock_hk_spot_em
            if is_hk_market(stock_code):
                df = ak.stock_hk_spot_em()
                if df is not None and not df.empty:
                    symbol = code.replace("HK", "").lstrip("0")
                    match = df[df["代码"] == symbol]
                    if not match.empty:
                        return str(match.iloc[0].get("名称", "")).strip()

        except Exception as e:
            logger.warning(f"[AkshareFetcher] get_stock_name failed: {e}")

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

    def get_trade_calendar(self) -> list[str] | None:
        """Get A-share trade calendar from Akshare."""
        try:
            import akshare as ak

            df = ak.tool_trade_date_hist_sina()
            dates = df["trade_date"].astype(str).tolist()
            if dates:
                return sorted(dates)
        except Exception as e:
            logger.warning(f"[AkshareFetcher] get_trade_calendar failed: {e}")
        return None

    def get_intraday_data(
        self, stock_code: str, period: str = "5", adjust: str = ""
    ) -> pd.DataFrame | None:
        """Get intraday minute-level data.

        Strategy:
        1. Try stock_zh_a_hist_min_em (Eastmoney, supports period+adjust+date range)
        2. Fallback to stock_zh_a_minute (Sina, supports period+adjust)

        Args:
            stock_code: Stock code (e.g., 600519, 000001)
            period: Minute period - "1", "5", "15", "30", "60"
            adjust: Adjustment type - ""=不复权, "qfq"=前复权, "hfq"=后复权

        Returns:
            DataFrame with columns: time, open, high, low, close, volume, amount
            or None if not supported.
        """
        try:
            # Convert code: 600519 -> 600519 (A-share), normalize for index
            code = normalize_stock_code(stock_code)
            is_index = is_index_code(stock_code)
            if is_index:
                index_type = get_index_type(stock_code)
                if index_type != "csi":
                    return None  # Only CSI indices supported for intraday

            # Map adjust: API format
            adj_map = {"": "", "qfq": "qfq", "hfq": "hfq"}
            adj_value = adj_map.get(adjust, "")

            # Try EM first (stock_zh_a_hist_min_em)
            df = self._fetch_intraday_em(code, period, adj_value)
            if df is not None and not df.empty:
                return df

            # Fallback to Sina (stock_zh_a_minute)
            df = self._fetch_intraday_sina(code, period, adj_value)
            return df

        except Exception as e:
            logger.warning(f"[AkshareFetcher] get_intraday_data failed: {e}")
            return None

    def _fetch_intraday_em(self, code: str, period: str, adjust: str) -> pd.DataFrame | None:
        """Fetch via stock_zh_a_hist_min_em."""
        try:
            from datetime import date

            import akshare as ak

            today = date.today().strftime("%Y-%m-%d")
            start = f"{today} 09:30:00"
            end = f"{today} 15:00:00"

            df = ak.stock_zh_a_hist_min_em(
                symbol=code, start_date=start, end_date=end, period=period, adjust=adjust
            )
            if df is None or df.empty:
                return None
            return self._normalize_intraday(df, time_col="时间")
        except Exception as e:
            logger.debug(f"[AkshareFetcher] EM intraday failed: {e}")
            return None

    def _fetch_intraday_sina(self, code: str, period: str, adjust: str) -> pd.DataFrame | None:
        """Fetch via stock_zh_a_minute."""
        try:
            import akshare as ak

            # Sina format: sh600519 or sz000001
            symbol = f"sh{code}" if code.startswith(("6", "5")) else f"sz{code}"
            df = ak.stock_zh_a_minute(symbol=symbol, period=period, adjust=adjust)
            if df is None or df.empty:
                return None
            return self._normalize_intraday(df, time_col="day")
        except Exception as e:
            logger.debug(f"[AkshareFetcher] Sina intraday failed: {e}")
            return None

    def _normalize_intraday(self, df: pd.DataFrame, time_col: str = "时间") -> pd.DataFrame:
        """Normalize intraday data from EM or Sina source."""
        df = df.copy()
        column_mapping = {
            time_col: "time",
            "开盘": "open",
            "收盘": "close",
            "最高": "high",
            "最低": "low",
            "成交量": "volume",
            "成交额": "amount",
        }
        df = df.rename(columns={k: v for k, v in column_mapping.items() if k in df.columns})
        if "time" in df.columns:
            df["time"] = df["time"].astype(str).str[-8:]  # Extract HH:MM:SS
        numeric_cols = ["open", "high", "low", "close", "volume", "amount"]
        for col in numeric_cols:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")
        keep_cols = ["time", "open", "high", "low", "close", "volume", "amount"]
        df = df[[c for c in keep_cols if c in df.columns]]
        return df

    def get_all_concept_boards(self, source: str = "eastmoney") -> list[dict]:
        """Get all concept boards from Akshare.

        Args:
            source: Data source - "eastmoney" (default)

        Returns:
            List of dicts: [{"code": "BK1048", "name": "互联网服务"}, ...]
        """
        try:
            import akshare as ak

            df = ak.stock_board_concept_name_em()
            result = []
            if df is not None and not df.empty:
                for _, row in df.iterrows():
                    code = str(row.get("板块代码", "")).strip()
                    name = str(row.get("板块名称", "")).strip()
                    if code:
                        result.append({"code": code, "name": name})
            return result
        except Exception as e:
            logger.warning(f"[AkshareFetcher] get_all_concept_boards failed: {e}")
            return []

    def get_concept_board_stocks(self, board_code: str, source: str = "eastmoney") -> list[dict]:
        """Get stocks within a concept board.

        Args:
            board_code: Board code like "BK1048"
            source: Data source - "eastmoney" (default)

        Returns:
            List of dicts: [{"code": "600519", "name": "贵州茅台"}, ...]
        """
        try:
            import akshare as ak

            df = ak.stock_board_concept_cons_em(symbol=board_code)
            result = []
            if df is not None and not df.empty:
                for _, row in df.iterrows():
                    code = str(row.get("代码", "")).strip()
                    name = str(row.get("名称", "")).strip()
                    if code:
                        result.append({"code": code, "name": name})
            return result
        except Exception as e:
            logger.warning(f"[AkshareFetcher] get_concept_board_stocks({board_code}) failed: {e}")
            return []

    def get_all_industry_boards(self, source: str = "eastmoney") -> list[dict]:
        """Get all industry boards from Akshare.

        Args:
            source: Data source - "eastmoney" (default)

        Returns:
            List of dicts: [{"code": "BK0418", "name": "银行"}, ...]
        """
        try:
            import akshare as ak

            df = ak.stock_board_industry_name_em()
            result = []
            if df is not None and not df.empty:
                for _, row in df.iterrows():
                    code = str(row.get("板块代码", "")).strip()
                    name = str(row.get("板块名称", "")).strip()
                    if code:
                        result.append({"code": code, "name": name})
            return result
        except Exception as e:
            logger.warning(f"[AkshareFetcher] get_all_industry_boards failed: {e}")
            return []

    def get_industry_board_stocks(self, board_code: str, source: str = "eastmoney") -> list[dict]:
        """Get stocks within an industry board.

        Args:
            board_code: Board code like "BK0418"
            source: Data source - "eastmoney" (default)

        Returns:
            List of dicts: [{"code": "600519", "name": "贵州茅台"}, ...]
        """
        try:
            import akshare as ak

            df = ak.stock_board_industry_cons_em(symbol=board_code)
            result = []
            if df is not None and not df.empty:
                for _, row in df.iterrows():
                    code = str(row.get("代码", "")).strip()
                    name = str(row.get("名称", "")).strip()
                    if code:
                        result.append({"code": code, "name": name})
            return result
        except Exception as e:
            logger.warning(f"[AkshareFetcher] get_industry_board_stocks({board_code}) failed: {e}")
            return []