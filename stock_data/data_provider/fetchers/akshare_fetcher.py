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
from ..persistence.pool_daily import init_schema as init_zt_cache_schema
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
        | DataCapability.HISTORICAL_MIN
        | DataCapability.REALTIME_QUOTE
        | DataCapability.STOCK_LIST
        | DataCapability.TRADE_CALENDAR
        | DataCapability.STOCK_BOARD
        | DataCapability.INDEX_QUOTE
        | DataCapability.INDEX_HISTORICAL
        | DataCapability.INDEX_INTRADAY
        | DataCapability.STOCK_ZT_POOL
    )

    def _map_adjust(self, adjust: str) -> str | None:
        """Map unified adjust to Akshare adjust value."""
        if not adjust:
            return ""  # 不复权
        mapping = {"qfq": "qfq", "hfq": "hfq"}
        return mapping.get(adjust, "")

    def _convert_code(self, stock_code: str) -> str:
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
        """Fetch K-line data from Akshare.

        Supports:
        - Daily/weekly/monthly for A-share stocks, A-share (CSI) indices, HK stocks
        - Minute (1/5/15/30/60) for A-share stocks via ``stock_zh_a_hist_min_em``
        - Minute (1/5/15/30/60) for CSI indices via ``index_zh_a_hist_min_em``

        Args:
            stock_code: Stock code
            start_date: Start date (YYYY-MM-DD); for minute freq, this is also the date
            end_date: End date (YYYY-MM-DD)
            frequency: K-line frequency - 'd'=日线, 'w'=周线, 'm'=月线,
                       '1'/'5'/'15'/'30'/'60'=分钟线 (A-share stocks & CSI indices only)
            adjust: Adjustment type - None/''=不复权, 'qfq'=前复权, 'hfq'=后复权.
        """
        try:
            import akshare as ak

            code = self._convert_code(stock_code)
            is_hk = is_hk_market(stock_code)
            is_index = is_index_code(stock_code)
            index_type = get_index_type(stock_code) if is_index else None

            logger.debug(f"[AkshareFetcher] Fetching {code} ({frequency})")

            # Akshare period mapping (d/w/m only)
            period_map = {"d": "daily", "w": "weekly", "m": "monthly"}
            period = period_map.get(frequency, "daily")
            adj_value = adjust or ""

            # ----- Minute-frequency branch -----
            if frequency in ("1", "5", "15", "30", "60"):
                if is_hk:
                    raise DataFetchError(
                        f"Akshare does not support minute frequency for HK {stock_code}"
                    )
                if is_index and index_type != "csi":
                    raise DataFetchError(
                        f"Akshare does not support minute frequency for {index_type} index {stock_code}"
                    )
                # For minute data, start_date/end_date refer to a single trading day
                # (the EM endpoints can't return long history). Use start_date as the
                # trading day and the full trading session 09:30-15:00.
                trade_day = start_date
                start_dt = f"{trade_day} 09:30:00"
                end_dt = f"{trade_day} 15:00:00"
                if is_index:
                    df = ak.index_zh_a_hist_min_em(
                        symbol=code, period=frequency, start_date=start_dt, end_date=end_dt
                    )
                else:
                    df = ak.stock_zh_a_hist_min_em(
                        symbol=code, period=frequency, start_date=start_dt, end_date=end_dt,
                        adjust=adj_value,
                    )
                if df is None or df.empty:
                    raise DataFetchError(f"Akshare returned no minute data for {stock_code}")
                return self._normalize_intraday_minute(df, stock_code)

            # ----- Daily/weekly/monthly branch -----
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

    def _normalize_intraday_minute(self, df: pd.DataFrame, stock_code: str) -> pd.DataFrame:
        """Normalize raw minute DataFrame (from stock_zh_a_hist_min_em /
        index_zh_a_hist_min_em) to the standard intraday columns.

        Raw columns (中文): 时间, 开盘, 收盘, 最高, 最低, 成交量, 成交额, 均价
        Standard columns: time, open, high, low, close, volume, amount
        """
        rename = {
            "时间": "time",
            "开盘": "open",
            "最高": "high",
            "最低": "low",
            "收盘": "close",
            "成交量": "volume",
            "成交额": "amount",
        }
        out = df.rename(columns=rename)
        for col in ("time", "open", "high", "low", "close", "volume", "amount"):
            if col not in out.columns:
                out[col] = None
        return out[["time", "open", "high", "low", "close", "volume", "amount"]]

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

            code = self._convert_code(stock_code)
            is_hk = is_hk_market(stock_code)
            is_index = is_index_code(stock_code)

            if is_hk:
                df = ak.stock_hk_spot_em()
                symbol = code.replace(".hk", "").zfill(5)
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
                    symbol = code.replace("HK", "").zfill(5)
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

    def get_all_concept_boards(
        self, source: str = "eastmoney", include_quote: bool = False
    ) -> list[dict]:
        """Get all concept boards from Akshare.

        Args:
            source: Data source - "eastmoney" (default)
            include_quote: If True, include realtime price/change/market data

        Returns:
            List of dicts: [{"code": "BK1048", "name": "互联网服务"}, ...]
            When include_quote=True, also includes: price, change_pct, change_amount,
            volume, amount, turnover_rate, total_mv, up_count, down_count,
            leading_stock, leading_stock_pct
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
                        board = {"code": code, "name": name}
                        if include_quote:
                            board.update({
                                "price": row.get("最新价"),
                                "change_pct": row.get("涨跌幅"),
                                "change_amount": row.get("涨跌额"),
                                "volume": row.get("成交量"),
                                "amount": row.get("成交额"),
                                "turnover_rate": row.get("换手率"),
                                "total_mv": row.get("总市值"),
                                "up_count": row.get("上涨家数"),
                                "down_count": row.get("下跌家数"),
                                "leading_stock": row.get("领涨股票"),
                                "leading_stock_pct": row.get("领涨股票-涨跌幅"),
                            })
                        result.append(board)
            return result
        except Exception as e:
            logger.warning(f"[AkshareFetcher] get_all_concept_boards failed: {e}")
            return []

    def get_concept_board_stocks(
        self, board_code: str, source: str = "eastmoney", include_quote: bool = False
    ) -> list[dict]:
        """Get stocks within a concept board.

        Args:
            board_code: Board code like "BK1048"
            source: Data source - "eastmoney" (default)
            include_quote: If True, fetch realtime quote for each stock

        Returns:
            List of dicts: [{"stock_code": "600519", "stock_name": "贵州茅台"}, ...]
            When include_quote=True, also includes: price, change_pct, change_amount,
            volume, amount, turnover_rate, pe_ratio, pb_ratio, high, low, open, pre_close
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
                        stock = {"stock_code": code, "stock_name": name}
                        if include_quote:
                            stock.update({
                                "price": row.get("最新价"),
                                "change_pct": row.get("涨跌幅"),
                                "change_amount": row.get("涨跌额"),
                                "volume": row.get("成交量"),
                                "amount": row.get("成交额"),
                                "turnover_rate": row.get("换手率"),
                                "pe_ratio": row.get("市盈率-动态"),
                                "pb_ratio": row.get("市净率"),
                                "high": row.get("最高"),
                                "low": row.get("最低"),
                                "open": row.get("今开"),
                                "pre_close": row.get("昨收"),
                            })
                        result.append(stock)
            return result
        except Exception as e:
            logger.warning(f"[AkshareFetcher] get_concept_board_stocks({board_code}) failed: {e}")
            if include_quote:
                return self._get_board_stocks_with_fallback(board_code, source, "concept")
            return []

    def get_all_industry_boards(
        self, source: str = "eastmoney", include_quote: bool = False
    ) -> list[dict]:
        """Get all industry boards from Akshare.

        Args:
            source: Data source - "eastmoney" (default)
            include_quote: If True, include realtime price/change/market data

        Returns:
            List of dicts: [{"code": "BK0418", "name": "银行"}, ...]
            When include_quote=True, also includes: price, change_pct, change_amount,
            volume, amount, turnover_rate, total_mv, up_count, down_count,
            leading_stock, leading_stock_pct
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
                        board = {"code": code, "name": name}
                        if include_quote:
                            board.update({
                                "price": row.get("最新价"),
                                "change_pct": row.get("涨跌幅"),
                                "change_amount": row.get("涨跌额"),
                                "volume": row.get("成交量"),
                                "amount": row.get("成交额"),
                                "turnover_rate": row.get("换手率"),
                                "total_mv": row.get("总市值"),
                                "up_count": row.get("上涨家数"),
                                "down_count": row.get("下跌家数"),
                                "leading_stock": row.get("领涨股票"),
                                "leading_stock_pct": row.get("领涨股票-涨跌幅"),
                            })
                        result.append(board)
            return result
        except Exception as e:
            logger.warning(f"[AkshareFetcher] get_all_industry_boards failed: {e}")
            return []

    def get_industry_board_stocks(
        self, board_code: str, source: str = "eastmoney", include_quote: bool = False
    ) -> list[dict]:
        """Get stocks within an industry board.

        Args:
            board_code: Board code like "BK0418"
            source: Data source - "eastmoney" (default)
            include_quote: If True, fetch realtime quote for each stock

        Returns:
            List of dicts: [{"stock_code": "600519", "stock_name": "贵州茅台"}, ...]
            When include_quote=True, also includes: price, change_pct, change_amount,
            volume, amount, turnover_rate, pe_ratio, pb_ratio, high, low, open, pre_close
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
                        stock = {"stock_code": code, "stock_name": name}
                        if include_quote:
                            stock.update({
                                "price": row.get("最新价"),
                                "change_pct": row.get("涨跌幅"),
                                "change_amount": row.get("涨跌额"),
                                "volume": row.get("成交量"),
                                "amount": row.get("成交额"),
                                "turnover_rate": row.get("换手率"),
                                "pe_ratio": row.get("市盈率-动态"),
                                "pb_ratio": row.get("市净率"),
                                "high": row.get("最高"),
                                "low": row.get("最低"),
                                "open": row.get("今开"),
                                "pre_close": row.get("昨收"),
                            })
                        result.append(stock)
            return result
        except Exception as e:
            logger.warning(f"[AkshareFetcher] get_industry_board_stocks({board_code}) failed: {e}")
            if include_quote:
                return self._get_board_stocks_with_fallback(board_code, source, "industry")
            return []

    def _get_board_stocks_with_fallback(
        self, board_code: str, source: str, board_type: str
    ) -> list[dict]:
        """Fallback: get board stocks without realtime data, then enrich with get_realtime_quote."""
        if board_type == "concept":
            stocks = self.get_concept_board_stocks(board_code, source=source, include_quote=False)
        else:
            stocks = self.get_industry_board_stocks(board_code, source=source, include_quote=False)

        if not stocks:
            return []

        # Fallback to get_realtime_quote for each stock
        for stock in stocks:
            quote = self.get_realtime_quote(stock["stock_code"])
            if quote:
                stock["price"] = quote.price
                stock["change_pct"] = quote.change_pct
                stock["change_amount"] = quote.change_amount
                stock["volume"] = quote.volume
                stock["amount"] = quote.amount
                stock["turnover_rate"] = quote.turnover_rate
                stock["pe_ratio"] = quote.pe_ratio
                stock["pb_ratio"] = quote.pb_ratio
                stock["high"] = quote.high
                stock["low"] = quote.low
                stock["open"] = quote.open_price
                stock["pre_close"] = quote.pre_close
        return stocks

    def get_index_realtime_quote(self, index_code: str) -> UnifiedRealtimeQuote | None:
        """Get realtime quote for a CSI index.

        Args:
            index_code: Index code (e.g., 000300, 399006)

        Returns:
            UnifiedRealtimeQuote or None if not available.
        """
        try:
            import akshare as ak

            code = normalize_stock_code(index_code)

            # Try EM first (stock_zh_index_spot_em)
            try:
                df = ak.stock_zh_index_spot_em(symbol="上证系列指数")
                if df is not None and not df.empty:
                    row = df[df["代码"] == code]
                    if row.empty:
                        # Try other index series
                        for symbol in ["沪深重要指数", "深证系列指数", "中证系列指数"]:
                            df = ak.stock_zh_index_spot_em(symbol=symbol)
                            if df is not None and not df.empty:
                                row = df[df["代码"] == code]
                                if not row.empty:
                                    break
                    if not row.empty:
                        row = row.iloc[0]
                        return UnifiedRealtimeQuote(
                            code=code,
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
                        )
            except Exception as e:
                logger.debug(f"[AkshareFetcher] stock_zh_index_spot_em failed: {e}")

            # Fallback to Sina (stock_zh_index_spot_sina)
            try:
                df = ak.stock_zh_index_spot_sina()
                if df is not None and not df.empty:
                    # Sina returns codes like "sh000001", "sz399006"
                    prefix = "sh" if code.startswith(("6", "5", "0")) else "sz"
                    sina_code = f"{prefix}{code}"
                    row = df[df["代码"] == sina_code]
                    if row.empty:
                        # Try without prefix
                        row = df[df["代码"].str.contains(code, na=False)]
                    if not row.empty:
                        row = row.iloc[0]
                        return UnifiedRealtimeQuote(
                            code=code,
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
                        )
            except Exception as e:
                logger.debug(f"[AkshareFetcher] stock_zh_index_spot_sina failed: {e}")

            return None

        except Exception:
            logger.warning(
                f"[AkshareFetcher] get_index_realtime_quote failed for {index_code}",
                exc_info=True,
            )
            return None

    def get_index_historical(
        self,
        index_code: str,
        start_date: str | None = None,
        end_date: str | None = None,
        period: str = "d",
    ) -> pd.DataFrame | None:
        """Get historical K-line data for a CSI index.

        Tries in order: stock_zh_index_daily (Sina) -> stock_zh_index_daily_tx (Tencent) ->
        stock_zh_index_daily_em (EM).

        Args:
            index_code: Index code (e.g., 000300, 399006)
            start_date: Start date (YYYY-MM-DD)
            end_date: End date (YYYY-MM-DD)
            period: K-line period - 'd'=daily, 'w'=weekly, 'm'=monthly

        Returns:
            DataFrame with columns: date, open, high, low, close, volume, amount, pct_chg
            or None if not available.
        """
        try:
            import akshare as ak

            code = normalize_stock_code(index_code)
            period_map = {"d": "daily", "w": "weekly", "m": "monthly"}
            period_value = period_map.get(period, "daily")

            # Determine Sina/Tencent prefix
            prefix = "sh" if code.startswith(("6", "5", "0")) else "sz"
            sina_symbol = f"{prefix}{code}"

            # Try stock_zh_index_daily (Sina)
            try:
                df = ak.stock_zh_index_daily(symbol=sina_symbol)
                if df is not None and not df.empty:
                    df = self._normalize_index_daily(df, code)
                    if start_date or end_date:
                        df = self._filter_by_date(df, start_date, end_date)
                    return df
            except Exception as e:
                logger.debug(f"[AkshareFetcher] stock_zh_index_daily failed: {e}")

            # Try stock_zh_index_daily_tx (Tencent)
            try:
                df = ak.stock_zh_index_daily_tx(
                    symbol=sina_symbol,
                    start_date=(start_date or "").replace("-", ""),
                    end_date=(end_date or "").replace("-", ""),
                )
                if df is not None and not df.empty:
                    df = self._normalize_index_daily_tx(df, code)
                    return df
            except Exception as e:
                logger.debug(f"[AkshareFetcher] stock_zh_index_daily_tx failed: {e}")

            # Try stock_zh_index_daily_em (EM)
            try:
                df = ak.stock_zh_index_daily_em(
                    symbol=code,
                    start_date=start_date.replace("-", "") if start_date else "19900101",
                    end_date=end_date.replace("-", "") if end_date else "20500101",
                )
                if df is not None and not df.empty:
                    df = self._normalize_index_daily_em(df, code)
                    return df
            except Exception as e:
                logger.debug(f"[AkshareFetcher] stock_zh_index_daily_em failed: {e}")

            return None

        except Exception as e:
            logger.warning(f"[AkshareFetcher] get_index_historical failed: {e}")
            return None

    def _normalize_index_daily(self, df: pd.DataFrame, code: str) -> pd.DataFrame:
        """Normalize stock_zh_index_daily (Sina) DataFrame."""
        column_mapping = {
            "date": "date",
            "open": "open",
            "high": "high",
            "low": "low",
            "close": "close",
            "volume": "volume",
        }
        df = df.rename(columns={k: v for k, v in column_mapping.items() if k in df.columns})
        if "date" in df.columns:
            df["date"] = pd.to_datetime(df["date"], errors="coerce")
        numeric_cols = ["open", "high", "low", "close", "volume"]
        for col in numeric_cols:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")
        if "code" not in df.columns:
            df["code"] = code
        keep_cols = ["code", "date", "open", "high", "low", "close", "volume"]
        df = df[[c for c in keep_cols if c in df.columns]]
        return df

    def _normalize_index_daily_tx(self, df: pd.DataFrame, code: str) -> pd.DataFrame:
        """Normalize stock_zh_index_daily_tx (Tencent) DataFrame."""
        column_mapping = {
            "date": "date",
            "open": "open",
            "close": "close",
            "high": "high",
            "low": "low",
            "amount": "volume",
        }
        df = df.rename(columns={k: v for k, v in column_mapping.items() if k in df.columns})
        if "date" in df.columns:
            df["date"] = pd.to_datetime(df["date"], errors="coerce")
        numeric_cols = ["open", "high", "low", "close", "volume"]
        for col in numeric_cols:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")
        if "code" not in df.columns:
            df["code"] = code
        keep_cols = ["code", "date", "open", "high", "low", "close", "volume"]
        df = df[[c for c in keep_cols if c in df.columns]]
        return df

    def _normalize_index_daily_em(self, df: pd.DataFrame, code: str) -> pd.DataFrame:
        """Normalize stock_zh_index_daily_em (EM) DataFrame."""
        column_mapping = {
            "date": "date",
            "open": "open",
            "close": "close",
            "high": "high",
            "low": "low",
            "volume": "volume",
            "amount": "amount",
        }
        df = df.rename(columns={k: v for k, v in column_mapping.items() if k in df.columns})
        if "date" in df.columns:
            df["date"] = pd.to_datetime(df["date"], errors="coerce")
        numeric_cols = ["open", "high", "low", "close", "volume", "amount"]
        for col in numeric_cols:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")
        if "code" not in df.columns:
            df["code"] = code
        keep_cols = ["code", "date", "open", "high", "low", "close", "volume", "amount"]
        df = df[[c for c in keep_cols if c in df.columns]]
        return df

    def _filter_by_date(
        self, df: pd.DataFrame, start_date: str | None, end_date: str | None
    ) -> pd.DataFrame:
        """Filter DataFrame by date range."""
        if "date" not in df.columns:
            return df
        if start_date:
            df = df[df["date"] >= pd.to_datetime(start_date, errors="coerce")]
        if end_date:
            df = df[df["date"] <= pd.to_datetime(end_date, errors="coerce")]
        return df

    def get_index_intraday(
        self, index_code: str, period: str = "5"
    ) -> pd.DataFrame | None:
        """Get intraday minute-level data for a CSI index.

        Args:
            index_code: Index code (e.g., 000300, 399006)
            period: Minute period - "1", "5", "15", "30", "60"

        Returns:
            DataFrame with columns: time, open, high, low, close, volume, amount
            or None if not available.
        """
        try:
            import akshare as ak
            from datetime import date, datetime, timedelta

            code = normalize_stock_code(index_code)

            today = date.today()
            start_dt = datetime.combine(today, datetime.min.time().replace(hour=9, minute=30))
            end_dt = datetime.combine(today, datetime.min.time().replace(hour=15, minute=0))

            start_str = start_dt.strftime("%Y-%m-%d %H:%M:%S")
            end_str = end_dt.strftime("%Y-%m-%d %H:%M:%S")

            df = ak.index_zh_a_hist_min_em(
                symbol=code,
                period=period,
                start_date=start_str,
                end_date=end_str,
            )
            if df is None or df.empty:
                return None

            df = df.rename(
                columns={
                    "时间": "time",
                    "开盘": "open",
                    "收盘": "close",
                    "最高": "high",
                    "最低": "low",
                    "成交量": "volume",
                    "成交额": "amount",
                }
            )
            if "time" in df.columns:
                df["time"] = df["time"].astype(str).str[-8:]
            numeric_cols = ["open", "high", "low", "close", "volume", "amount"]
            for col in numeric_cols:
                if col in df.columns:
                    df[col] = pd.to_numeric(df[col], errors="coerce")
            keep_cols = ["time", "open", "high", "low", "close", "volume", "amount"]
            df = df[[c for c in keep_cols if c in df.columns]]
            return df

        except Exception as e:
            logger.warning(f"[AkshareFetcher] get_index_intraday failed: {e}")
            return None

    def get_zt_pool(self, pool_type: str, date: str) -> list[dict] | None:
        """
        Get ZT (涨跌停) pool data from Akshare.

        Args:
            pool_type: Pool type - "zt" (涨停), "dt" (跌停), "zbgc" (炸板)
            date: Pool date in YYYY-MM-DD format (converted to YYYYMMDD internally
                to match Akshare's expected format)

        Returns:
            List of stock dicts with normalized fields, or None if unavailable.
        """
        try:
            import akshare as ak

            init_zt_cache_schema()

            # Map pool_type to Akshare function
            func_map = {
                "zt": ak.stock_zt_pool_em,
                "zbgc": ak.stock_zt_pool_zbgc_em,
                "dt": ak.stock_zt_pool_dtgc_em,
            }
            func = func_map.get(pool_type)
            if not func:
                logger.warning(f"[AkshareFetcher] Unknown pool_type: {pool_type}")
                return None

            # Akshare's pool APIs expect YYYYMMDD; the manager hands us YYYY-MM-DD
            akshare_date = date.replace("-", "") if date else date
            df = func(date=akshare_date)
            if df is None or df.empty:
                return None

            return self._normalize_zt_pool(df, pool_type)

        except Exception as e:
            logger.warning(f"[AkshareFetcher] get_zt_pool({pool_type}, {date}) failed: {e}")
            return None

    def _normalize_zt_pool(self, df: pd.DataFrame, pool_type: str) -> list[dict]:
        """Normalize Akshare ZT pool DataFrame to standard format."""
        result = []
        for _, row in df.iterrows():
            code = str(row.get("代码", "")).strip()
            # Normalize to 6-digit format
            code = normalize_stock_code(code)

            stock = {
                "code": code,
                "name": str(row.get("名称", "")).strip(),
                "price": row.get("最新价") if "最新价" in row.index else None,
                "change_pct": row.get("涨跌幅") if "涨跌幅" in row.index else None,
                "amount": row.get("成交额") if "成交额" in row.index else None,
                "turnover_rate": row.get("换手率") if "换手率" in row.index else None,
                "lb_count": row.get("连板数") if "连板数" in row.index else None,
                "first_seal_time": row.get("首次封板时间") if "首次封板时间" in row.index else None,
                "last_seal_time": row.get("最后封板时间") if "最后封板时间" in row.index else None,
                "seal_count": row.get("炸板次数") if "炸板次数" in row.index else None,
                "zt_count": row.get("涨停统计") if "涨停统计" in row.index else None,
            }

            # dt_pool has different fields (连续跌停次数, no 炸板次数, no 涨停统计)
            if pool_type == "dt":
                stock["lb_count"] = row.get("连续跌停次数") if "连续跌停次数" in row.index else None
                stock["seal_amount"] = None
            else:
                stock["seal_amount"] = None

            # circ_mv and total_mv are not in akshare ZT pool data
            stock["circ_mv"] = None
            stock["total_mv"] = None

            result.append(stock)

        return result