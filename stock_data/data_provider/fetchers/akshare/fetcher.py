"""
Akshare fetcher for A-share and HK stock data (Priority 2).

Support for both A-shares and Hong Kong stocks.
"""

import logging
import os

import pandas as pd

from ...base import (
    BaseFetcher,
    DataCapability,
    DataFetchError,
    is_hk_market,
    normalize_stock_code,
)
from ...core.types import RealtimeSource, UnifiedRealtimeQuote, safe_float, safe_int
from ...utils.code_converter import to_akshare_format
from ...utils.normalize import get_index_type, is_index_code
from .board import fetch_board_list, fetch_board_stocks
from .index_norm import (
    _INDEX_EM_MAP,
    _INDEX_EM_NUMERIC,
    _INDEX_SINA_MAP,
    _INDEX_SINA_NUMERIC,
    _INDEX_TX_MAP,
    _INDEX_TX_NUMERIC,
    filter_by_date,
    normalize_index_df,
    normalize_intraday_df,
)

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

    def is_available(self) -> bool:
        """Akshare is always available when installed (no auth required)."""
        return True

    def _map_adjust(self, adjust: str) -> str | None:
        """Map unified adjust to Akshare adjust value."""
        if not adjust:
            return ""  # 不复权
        mapping = {"qfq": "qfq", "hfq": "hfq"}
        return mapping.get(adjust, "")

    def _convert_code(self, stock_code: str) -> str:
        """Convert to akshare query format. Delegates to ``to_akshare_format``."""
        return to_akshare_format(stock_code)

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

        Thin wrapper over ``index_norm.normalize_intraday_df`` — kept as
        an instance method so the call site in ``_fetch_raw_data`` reads
        the same as the ``get_intraday_data`` path.
        """
        return normalize_intraday_df(df)

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

            if market in ("cn", "csi"):
                # A-share stocks via stock_info_a_code_name
                # Accept both "cn" (legacy) and "csi" (normalized by
                # persistence/stock_list.py) so the upstream call
                # actually fires for csi market.
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
            return normalize_intraday_df(df)
        except Exception as e:
            logger.debug(f"[AkshareFetcher] EM intraday failed: {e}")
            return None

    def _fetch_intraday_sina(self, code: str, period: str, adjust: str) -> pd.DataFrame | None:
        """Fetch via stock_zh_a_minute. Sina uses ``"day"`` as the time column."""
        try:
            import akshare as ak

            # Sina format: sh600519 or sz000001
            symbol = f"sh{code}" if code.startswith(("6", "5")) else f"sz{code}"
            df = ak.stock_zh_a_minute(symbol=symbol, period=period, adjust=adjust)
            if df is None or df.empty:
                return None
            return normalize_intraday_df(df, time_col="day")
        except Exception as e:
            logger.debug(f"[AkshareFetcher] Sina intraday failed: {e}")
            return None

    def get_all_concept_boards(
        self, source: str = "eastmoney", include_quote: bool = False
    ) -> list[dict]:
        """Get all concept boards. Delegates to the shared board helper."""
        import akshare as ak
        return fetch_board_list(
            ak.stock_board_concept_name_em,
            include_quote=include_quote,
            fetcher_label=self.name,
        )

    def get_concept_board_stocks(
        self, board_code: str, source: str = "eastmoney", include_quote: bool = False
    ) -> list[dict]:
        """Get stocks within a concept board. Delegates to the shared board helper."""
        import akshare as ak
        return fetch_board_stocks(
            ak.stock_board_concept_cons_em,
            board_code,
            include_quote=include_quote,
            fallback_enricher=self._enrich_stock_from_realtime,
            fetcher_label=self.name,
        )

    def get_all_industry_boards(
        self, source: str = "eastmoney", include_quote: bool = False
    ) -> list[dict]:
        """Get all industry boards. Delegates to the shared board helper."""
        import akshare as ak
        return fetch_board_list(
            ak.stock_board_industry_name_em,
            include_quote=include_quote,
            fetcher_label=self.name,
        )

    def get_industry_board_stocks(
        self, board_code: str, source: str = "eastmoney", include_quote: bool = False
    ) -> list[dict]:
        """Get stocks within an industry board. Delegates to the shared board helper."""
        import akshare as ak
        return fetch_board_stocks(
            ak.stock_board_industry_cons_em,
            board_code,
            include_quote=include_quote,
            fallback_enricher=self._enrich_stock_from_realtime,
            fetcher_label=self.name,
        )

    def _enrich_stock_from_realtime(self, stock_code: str) -> dict | None:
        """Enrich a single stock dict with realtime quote fields.

        Used as ``fallback_enricher`` by ``fetch_board_stocks`` when the
        direct API quote enrichment fails.
        """
        quote = self.get_realtime_quote(stock_code)
        if quote is None:
            return None
        return {
            "price": quote.price,
            "change_pct": quote.change_pct,
            "change_amount": quote.change_amount,
            "volume": quote.volume,
            "amount": quote.amount,
            "turnover_rate": quote.turnover_rate,
            "pe_ratio": quote.pe_ratio,
            "pb_ratio": quote.pb_ratio,
            "high": quote.high,
            "low": quote.low,
            "open": quote.open_price,
            "pre_close": quote.pre_close,
        }

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

            # Determine Sina/Tencent prefix
            prefix = "sh" if code.startswith(("6", "5", "0")) else "sz"
            sina_symbol = f"{prefix}{code}"

            # Try stock_zh_index_daily (Sina)
            try:
                df = ak.stock_zh_index_daily(symbol=sina_symbol)
                if df is not None and not df.empty:
                    df = normalize_index_df(df, code, _INDEX_SINA_MAP,
                                            numeric_cols=_INDEX_SINA_NUMERIC)
                    if start_date or end_date:
                        df = filter_by_date(df, start_date, end_date)
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
                    df = normalize_index_df(df, code, _INDEX_TX_MAP,
                                            numeric_cols=_INDEX_TX_NUMERIC)
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
                    df = normalize_index_df(df, code, _INDEX_EM_MAP,
                                            numeric_cols=_INDEX_EM_NUMERIC)
                    return df
            except Exception as e:
                logger.debug(f"[AkshareFetcher] stock_zh_index_daily_em failed: {e}")

            return None

        except Exception as e:
            logger.warning(f"[AkshareFetcher] get_index_historical failed: {e}")
            return None

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
            from datetime import date, datetime

            import akshare as ak

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

            return normalize_intraday_df(df)

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
