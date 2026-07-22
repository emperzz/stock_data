"""
Yfinance fetcher for US stocks and indices (Priority 4).

Also supports A-share via .SS/.SZ suffixes and HK via .HK suffix.
Stooq is used as fallback for US stocks.
"""

import csv
import logging
import os
from io import StringIO
from urllib.request import Request, urlopen

import pandas as pd
from tenacity import (
    before_sleep_log,
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from ..base import (
    BaseFetcher,
    DataCapability,
    DataFetchError,
    is_us_market,
    normalize_stock_code,
)
from ..core.types import RealtimeSource, UnifiedRealtimeQuote
from ..utils.code_converter import to_yfinance_format
from ..utils.normalize import is_index_code

logger = logging.getLogger(__name__)


class YfinanceFetcher(BaseFetcher):
    """Yahoo Finance fetcher for US stocks and indices."""

    name = "YfinanceFetcher"
    priority = int(os.getenv("YFINANCE_PRIORITY", "4"))
    supported_markets: set[str] = {"csi", "hk", "us"}
    supported_data_types = (
        DataCapability.STOCK_KLINE
        | DataCapability.STOCK_REALTIME_QUOTE
        | DataCapability.INDEX_KLINE
        | DataCapability.INDEX_REALTIME_QUOTE
    )

    def _map_adjust(self, adjust: str) -> str | None:
        """Map unified adjust to yfinance auto_adjust flag."""
        if not adjust:
            return None  # 不复权 (auto_adjust=False)
        return "qfq"  # yfinance only has one adjustment flavor, map both to it

    def supports_kline(self, period, adjust, market, asset):
        # hfq silently downgrades to qfq (semantic loss) → treat as unsupported.
        if adjust == "hfq":
            return False
        # Yfinance upstream: no 1m interval (`interval` must be one of
        # 1d/5d/1wk/1mo/1h/30m/15m/5m/90m/60m — no "1m" exists).
        if period == "1":
            return False
        return super().supports_kline(period, adjust, market, asset)

    def _convert_code(self, stock_code: str) -> str:
        """Convert to yfinance ticker. Delegates to ``to_yfinance_format``."""
        return to_yfinance_format(stock_code)

    def is_available(self) -> bool:
        """Check if yfinance is available."""
        try:
            import importlib.util

            return importlib.util.find_spec("yfinance") is not None
        except ImportError:
            return False

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=30),
        retry=retry_if_exception_type((ConnectionError, TimeoutError)),
        before_sleep=before_sleep_log(logger, logging.WARNING),
    )
    def _fetch_raw_data(
        self,
        stock_code: str,
        start_date: str,
        end_date: str,
        frequency: str = "d",
        adjust: str | None = None,
    ) -> pd.DataFrame:
        """Fetch K-line data from yfinance (supports d/w/m/5/15/30/60).

        Args:
            stock_code: Stock code
            start_date: Start date (YYYY-MM-DD)
            end_date: End date (YYYY-MM-DD)
            frequency: K-line frequency - 'd'=日线, 'w'=周线, 'm'=月线, '5/15/30/60'=分钟线
            adjust: Adjustment type - None/True=调整后(前复权), False=未调整.
                   Defaults to True (前复权) if not specified.
        """
        try:
            import yfinance as yf

            code = self._convert_code(stock_code)
            logger.debug(f"[YfinanceFetcher] Fetching {code} ({frequency})")

            # yfinance interval mapping
            interval_map = {
                "d": "1d",
                "w": "1wk",
                "m": "1mo",
                "5": "5m",
                "15": "15m",
                "30": "30m",
                "60": "60m",
            }
            interval = interval_map.get(frequency, "1d")

            # adjust already mapped by _map_adjust: None=不复权, "qfq"=前复权
            auto_adjust = adjust is not None

            df = yf.download(
                tickers=code,
                start=start_date,
                end=end_date,
                progress=False,
                auto_adjust=auto_adjust,
                multi_level_index=True,
                interval=interval,
            )

            if df is None or df.empty:
                raise DataFetchError(f"Yfinance returned no data for {stock_code}")

            # Handle multi-level columns
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.get_level_values(0)

            return df

        except DataFetchError:
            raise
        except ImportError:
            raise DataFetchError("yfinance not installed") from None
        except Exception as e:
            raise DataFetchError(f"YfinanceFetcher fetch failed: {e}") from e

    def _normalize_data(self, df: pd.DataFrame, stock_code: str) -> pd.DataFrame:
        """Normalize yfinance data to standard columns."""
        df = df.copy().reset_index()

        # Use common normalization
        df = self._normalize_dataframe(
            df,
            stock_code,
            {
                "Date": "date",
                "Open": "open",
                "High": "high",
                "Low": "low",
                "Close": "close",
                "Volume": "volume",
            },
        )

        # Calculate pct_chg from close
        if "pct_chg" not in df.columns and "close" in df.columns:
            df["pct_chg"] = df["close"].pct_change() * 100
            df["pct_chg"] = df["pct_chg"].fillna(0).round(2)

        # Calculate amount from volume * close
        if "amount" not in df.columns and "close" in df.columns and "volume" in df.columns:
            df["amount"] = df["volume"] * df["close"]

        return df

    def get_realtime_quote(self, stock_code: str) -> UnifiedRealtimeQuote | None:
        """Get realtime quote from yfinance."""
        try:
            import yfinance as yf

            code = self._convert_code(stock_code)
            ticker = yf.Ticker(code)

            # Try fast_info first
            try:
                info = ticker.fast_info
                if info is None:
                    raise ValueError("fast_info is None")

                price = getattr(info, "lastPrice", None) or getattr(info, "last_price", None)
                prev_close = getattr(info, "previousClose", None) or getattr(
                    info, "previous_close", None
                )
                open_price = getattr(info, "open", None)
                high = getattr(info, "dayHigh", None) or getattr(info, "day_high", None)
                low = getattr(info, "dayLow", None) or getattr(info, "day_low", None)
                volume = getattr(info, "lastVolume", None) or getattr(info, "last_volume", None)
            except Exception:
                # Fallback to history
                hist = ticker.history(period="2d")
                if hist.empty:
                    # Try Stooq fallback for US stocks
                    if is_us_market(stock_code):
                        return self._get_from_stooq(stock_code)
                    return None

                today = hist.iloc[-1]
                prev = hist.iloc[-2] if len(hist) > 1 else today
                price = float(today["Close"])
                prev_close = float(prev["Close"])
                open_price = float(today["Open"])
                high = float(today["High"])
                low = float(today["Low"])
                volume = int(today["Volume"])

            # Calculate change
            change_amount = None
            change_pct = None
            if price is not None and prev_close is not None and prev_close > 0:
                change_amount = price - prev_close
                change_pct = (change_amount / prev_close) * 100

            # Amplitude
            amplitude = None
            if high is not None and low is not None and prev_close is not None and prev_close > 0:
                amplitude = ((high - low) / prev_close) * 100

            return UnifiedRealtimeQuote(
                code=normalize_stock_code(stock_code),
                name="",
                source=RealtimeSource.YFINANCE,
                price=price,
                change_pct=round(change_pct, 2) if change_pct is not None else None,
                change_amount=round(change_amount, 4) if change_amount is not None else None,
                volume=volume,
                open_price=open_price,
                high=high,
                low=low,
                pre_close=prev_close,
                amplitude=round(amplitude, 2) if amplitude is not None else None,
            )

        except Exception:
            logger.warning(
                f"[YfinanceFetcher] Realtime quote failed for {stock_code}", exc_info=True
            )
            if is_us_market(stock_code):
                return self._get_from_stooq(stock_code)
            return None

    def _get_from_stooq(self, stock_code: str) -> UnifiedRealtimeQuote | None:
        """Get US stock quote from Stooq as fallback."""
        symbol = stock_code.strip().upper()
        stooq_symbol = f"{symbol.lower()}.us"
        url = f"https://stooq.com/q/l/?s={stooq_symbol}"

        try:
            request = Request(
                url,
                headers={
                    "User-Agent": "Mozilla/5.0 (stock-data-server/1.0)",
                    "Accept": "text/plain,text/csv,*/*",
                },
            )

            with urlopen(request, timeout=15) as response:
                payload = response.read().decode("utf-8", "ignore").strip()

            if not payload or payload.upper().startswith("NO DATA"):
                return None

            reader = csv.reader(StringIO(payload))
            first_row = next(reader, None)
            if first_row is None:
                return None

            normalized = [cell.strip() for cell in first_row]
            header_tokens = {cell.lower() for cell in normalized if cell}
            has_header = "open" in header_tokens and "close" in header_tokens
            row = next(reader, None) if has_header else first_row
            if row is None:
                return None

            normalized_row = [cell.strip() for cell in row]
            while normalized_row and normalized_row[-1] == "":
                normalized_row.pop()

            if len(normalized_row) >= 8:
                open_idx, high_idx, low_idx, price_idx, vol_idx = 3, 4, 5, 6, 7
            elif len(normalized_row) >= 7:
                open_idx, high_idx, low_idx, price_idx, vol_idx = 2, 3, 4, 5, 6
            else:
                return None

            open_price = float(normalized_row[open_idx])
            high = float(normalized_row[high_idx])
            low = float(normalized_row[low_idx])
            price = float(normalized_row[price_idx])
            volume = int(float(normalized_row[vol_idx]))

            return UnifiedRealtimeQuote(
                code=symbol,
                name="",
                source=RealtimeSource.STOOQ,
                price=price,
                volume=volume,
                open_price=open_price,
                high=high,
                low=low,
            )

        except Exception as e:
            logger.warning(f"[YfinanceFetcher] Stooq fallback failed: {e}")
            return None

    def get_index_historical(
        self, index_code: str, start_date: str | None, end_date: str | None, frequency: str
    ) -> pd.DataFrame | None:
        """Get historical K-line data for an index (US/CSI/HK).

        Internally delegates to get_kline_data which handles index codes via
        _convert_code (US_INDEX_MAP, .SS, HK_INDEX_MAP). Supports d/w/m and
        minute frequencies.

        Args:
            index_code: Index code (e.g., SPX, 000300, HSI)
            start_date: Start date (YYYY-MM-DD)
            end_date: End date (YYYY-MM-DD)
            frequency: K-line period - 'd'=daily, 'w'=weekly, 'm'=monthly, '5/15/30/60'=minute

        Returns:
            DataFrame or None if not supported.
        """
        from datetime import datetime, timedelta

        code = normalize_stock_code(index_code)
        if not is_index_code(code):
            return None

        if not start_date:
            start_date = (datetime.now() - timedelta(days=365)).strftime("%Y-%m-%d")

        try:
            return self.get_kline_data(
                index_code, start_date, end_date, days=365, frequency=frequency
            )
        except DataFetchError:
            return None

    def get_index_realtime_quote(self, index_code: str) -> UnifiedRealtimeQuote | None:
        """Get realtime quote for an index (US/CSI/HK).

        Internally delegates to get_realtime_quote which handles index codes
        via _convert_code (US_INDEX_MAP, .SS, HK_INDEX_MAP).

        Args:
            index_code: Index code (e.g., SPX, 000300, HSI)

        Returns:
            UnifiedRealtimeQuote or None if not available.
        """
        code = normalize_stock_code(index_code)
        if not is_index_code(code):
            return None
        return self.get_realtime_quote(index_code)
