"""
Akshare fetcher for A-share and HK stock data (Priority 2).

Support for both A-shares and Hong Kong stocks.
"""

import logging
import os
from typing import Any

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
    priority = int(os.getenv("AKSHARE_PRIORITY", "3"))
    supported_markets: set[str] = {"csi", "hk"}
    supported_data_types = (
        DataCapability.STOCK_KLINE
        | DataCapability.STOCK_REALTIME_QUOTE
        | DataCapability.STOCK_LIST
        | DataCapability.TRADE_CALENDAR
        | DataCapability.INDEX_REALTIME_QUOTE
        | DataCapability.INDEX_KLINE
        | DataCapability.STOCK_ZT_POOL
    )

    def is_available(self) -> bool:
        """True iff the ``akshare`` Python package is importable.

        Akshare is imported lazily inside each call (see ``import akshare
        as ak`` lines below), so a missing module would only surface at
        request time and bubble up as a 500. We probe via
        ``importlib.util.find_spec`` so the manager can skip this fetcher
        cleanly when akshare isn't installed, mirroring the pattern used
        by ``yfinance_fetcher.is_available``.
        """
        try:
            import importlib.util

            return importlib.util.find_spec("akshare") is not None
        except (ImportError, ValueError):
            return False

    def _map_adjust(self, adjust: str) -> str | None:
        """Map unified adjust to Akshare adjust value."""
        if not adjust:
            return ""  # 不复权
        mapping = {"qfq": "qfq", "hfq": "hfq"}
        return mapping.get(adjust, "")

    def supports_kline(self, period, adjust, market, asset):
        # 1m refuses adjust (upstream hard constraint; whole-fetcher-only 1m source).
        if period == "1" and adjust in ("qfq", "hfq"):
            return False
        return super().supports_kline(period, adjust, market, asset)

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
                        symbol=code,
                        period=frequency,
                        start_date=start_dt,
                        end_date=end_dt,
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
        """Normalize Akshare data to standard columns.

        Akshare upstream returns ``成交量`` in **手 (lots = 100 shares)**.
        Per spec §3.4 the canonical contract is **股 (shares)**, so we
        multiply by 100 to convert lots → shares.
        """
        out = self._normalize_dataframe(
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
        # 手 -> 股 (lots -> shares) per spec §3.4.
        # 1 手 = 100 股, so multiply by 100.
        if "volume" in out.columns:
            out["volume"] = out["volume"].apply(lambda v: int(v) * 100 if pd.notna(v) else 0)
        return out

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
                volume=safe_int(row.get("成交量"), 0) * 100,  # 手→股 per spec §3.4
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
                # 'cn' is the fetcher-internal tag for A-shares. The
                # public 'csi' tag is translated to 'cn' by
                # persistence/stock_list.py before reaching this call.
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
                            volume=safe_int(row.get("成交量"), 0) * 100,  # 手→股 per spec §3.4
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
                            volume=safe_int(row.get("成交量"), 0) * 100,  # 手→股 per spec §3.4
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
                    df = normalize_index_df(
                        df, code, _INDEX_SINA_MAP, numeric_cols=_INDEX_SINA_NUMERIC
                    )
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
                    df = normalize_index_df(df, code, _INDEX_TX_MAP, numeric_cols=_INDEX_TX_NUMERIC)
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
                    df = normalize_index_df(df, code, _INDEX_EM_MAP, numeric_cols=_INDEX_EM_NUMERIC)
                    return df
            except Exception as e:
                logger.debug(f"[AkshareFetcher] stock_zh_index_daily_em failed: {e}")

            return None

        except Exception as e:
            logger.warning(f"[AkshareFetcher] get_index_historical failed: {e}")
            return None

    def get_index_intraday(self, index_code: str, period: str = "5") -> pd.DataFrame | None:
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
        """Normalize Akshare ZT pool DataFrame to standard format.

        Field mapping (per upstream column docs at docs/akshare/stock/):
          ZT pool — code, name, 最新价, 涨跌幅, 成交额, 换手率, 连板数,
                    首次封板时间, 最后封板时间, 炸板次数, 涨停统计, 封板资金,
                    流通市值, 总市值
          DT pool — code, name, 最新价, 涨跌幅, 成交额, 换手率, 连续跌停,
                    最后封板时间, 开板次数, 封单资金, 流通市值, 总市值
                    (DT pool has no 首次封板时间 / 涨停统计 / 封板资金)
          ZBGC pool — code, name, 最新价, 涨跌幅, 成交额, 换手率, 涨速,
                    首次封板时间, 炸板次数, 涨停统计, 振幅, 流通市值, 总市值
                    (ZBGC pool has no 最后封板时间 / 封板资金 / 封单资金)

        Note: 首次封板时间 / 最后封板时间 are 6-digit integers in upstream
        (e.g. 141354, 150000), NOT the "HH:MM:SS" string format the akshare
        docs claim. We normalize them to HH:MM:SS via
        :meth:`_akshare_seal_time_to_hms`.
        """
        result = []
        for _, row in df.iterrows():
            code = str(row.get("代码", "")).strip()
            # Normalize to 6-digit format
            code = normalize_stock_code(code)

            def _col(name: str, _row=row):
                """Read a column from the row, returning None if absent."""
                return _row[name] if name in _row.index else None

            stock = {
                "code": code,
                "name": str(row.get("名称", "")).strip(),
                # All numeric fields go through safe_float / safe_int so the
                # returned types match ZhituFetcher / ZzshareFetcher
                # (cross-fetcher uniformity — see CLAUDE.md "Standardized Data
                # Schema"). Pre-fix these were raw numpy scalars (int64 /
                # float64) which serialize unreliably across json libs.
                "price": safe_float(_col("最新价")),
                "change_pct": safe_float(_col("涨跌幅")),
                "amount": safe_float(_col("成交额")),
                "turnover_rate": safe_float(_col("换手率")),
                "first_seal_time": self._akshare_seal_time_to_hms(_col("首次封板时间")),
                "last_seal_time": self._akshare_seal_time_to_hms(_col("最后封板时间")),
                "zt_count": str(_col("涨停统计")) if _col("涨停统计") is not None else None,
                "circ_mv": safe_float(_col("流通市值")),
                "total_mv": safe_float(_col("总市值")),
            }

            if pool_type == "dt":
                # DT pool: 连续跌停 (not 连续跌停次数), 开板次数 (not 炸板次数),
                # no 涨停统计, no 首次封板时间, 封单资金 (not 封板资金)
                stock["lb_count"] = safe_int(_col("连续跌停"))
                stock["seal_count"] = safe_int(_col("开板次数"))
                stock["seal_amount"] = safe_float(_col("封单资金"))
            else:
                # ZT and ZBGC pools use 炸板次数. ZBGC has 炸板次数 but no
                # 连板数 / 封板资金 columns upstream.
                stock["seal_count"] = safe_int(_col("炸板次数"))
                if pool_type == "zt":
                    stock["lb_count"] = safe_int(_col("连板数"))
                    stock["seal_amount"] = safe_float(_col("封板资金"))
                else:
                    # zbgc: no 连板数 / 封板资金 columns upstream
                    stock["lb_count"] = None
                    stock["seal_amount"] = None

            result.append(stock)

        return result

    @staticmethod
    def _akshare_seal_time_to_hms(raw: Any) -> str | None:
        """Normalize Akshare's seal time field to ``HH:MM:SS`` string format.

        The akshare docs (docs/akshare/stock/stock_zt_pool_*.md) describe
        ``首次封板时间`` / ``最后封板时间`` as ``object`` type with format
        ``09:25:00``, but the actual data is a 6-digit integer (e.g.
        ``141354`` for 14:13:54, ``150000`` for 15:00:00). The schema
        contract (``ZTPoolStock.first_seal_time`` /
        ``last_seal_time``) requires ``HH:MM:SS`` strings, so we coerce
        here.

        Accepts:
          - int/float (e.g. ``141354``) → ``"14:13:54"``
          - str of digits (e.g. ``"141354"``) → ``"14:13:54"``
          - str already in ``HH:MM:SS`` (e.g. ``"09:25:00"``) → unchanged
          - None / NaN / empty → ``None``
        """
        if raw is None:
            return None
        try:
            # pandas NaN check (without importing numpy at module level)
            if isinstance(raw, float) and raw != raw:  # NaN != NaN
                return None
        except Exception:
            pass

        # Numeric case (the common path: int 141354)
        try:
            n = int(raw)
            s = str(n).zfill(6)
            if len(s) == 6 and s.isdigit():
                return f"{s[:2]}:{s[2:4]}:{s[4:6]}"
        except (TypeError, ValueError):
            pass

        # String case
        s = str(raw).strip()
        if not s or s.lower() in ("nan", "none", "-", "--"):
            return None
        # Already HH:MM:SS or HH:MM — return as-is (defensive)
        if len(s) >= 5 and s[2] == ":":
            if len(s) == 8 and s[5] == ":":  # HH:MM:SS
                return s
            if len(s) == 5:  # HH:MM
                return s + ":00"
        return None
