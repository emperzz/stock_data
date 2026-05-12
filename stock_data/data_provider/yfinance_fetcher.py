# -*- coding: utf-8 -*-
"""
Yfinance fetcher for US stocks and indices (Priority 3).

Also supports A-share via .SS/.SZ suffixes and HK via .HK suffix.
Stooq is used as fallback for US stocks.
"""

import csv
import logging
import os
from datetime import datetime
from io import StringIO
from typing import Any, Optional
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import pandas as pd
from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type,
    before_sleep_log,
)

from .base import BaseFetcher, DataFetchError, is_us_market, normalize_stock_code, is_index_code, get_index_type
from .realtime_types import UnifiedRealtimeQuote, RealtimeSource, safe_float, safe_int
from .index_symbols import US_INDEX_MAP, CSI_INDEX_MAP, HK_INDEX_MAP

logger = logging.getLogger(__name__)


class YfinanceFetcher(BaseFetcher):
    """Yahoo Finance fetcher for US stocks and indices."""

    name = "YfinanceFetcher"
    priority = int(os.getenv("YFINANCE_PRIORITY", "3"))

    def _convert_code(self, stock_code: str) -> str:
        """
        Convert stock code to yfinance format.

        A-share:
            600519 -> 600519.SS
            000001 -> 000001.SZ
        HK:
            HK00700 -> 0700.HK
        US:
            AAPL -> AAPL (unchanged)
        Indices:
            SPX -> ^GSPC
            000300 -> 000300.SS (CSI 300)
            HSI -> ^HSI (Hang Seng)
        """
        code = stock_code.strip().upper()

        # Check if it's an index code
        if is_index_code(code):
            index_type = get_index_type(code)
            if index_type == "us" and code in US_INDEX_MAP:
                return US_INDEX_MAP[code]
            elif index_type == "csi":
                # CSI index: 000300 -> 000300.SS
                return f"{code}.SS"
            elif index_type == "hk" and code in HK_INDEX_MAP:
                return HK_INDEX_MAP[code]

        # Already in yfinance format
        if code.endswith((".SS", ".SZ", ".HK", ".BJ")):
            return code

        # US stock (1-5 letters)
        if is_us_market(code):
            return code

        # HK stock
        if code.startswith("HK"):
            digits = code[2:].lstrip("0") or "0"
            return f"{digits.zfill(4)}.HK"

        # A-share Shanghai
        if code.startswith(("6", "5", "7")):
            return f"{code}.SS"

        # A-share Shenzhen
        if code.startswith(("0", "1", "2", "3")):
            return f"{code}.SZ"

        # Default to Shenzhen
        return f"{code}.SZ"

    def is_available(self) -> bool:
        """Check if yfinance is available."""
        try:
            import yfinance as yf
            return True
        except ImportError:
            return False

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=30),
        retry=retry_if_exception_type((ConnectionError, TimeoutError)),
        before_sleep=before_sleep_log(logger, logging.WARNING),
    )
    def _fetch_raw_data(
        self, stock_code: str, start_date: str, end_date: str, frequency: str = "d"
    ) -> pd.DataFrame:
        """Fetch K-line data from yfinance (supports d/w/m/5/15/30/60)."""
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

            df = yf.download(
                tickers=code,
                start=start_date,
                end=end_date,
                progress=False,
                auto_adjust=True,
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
            raise DataFetchError("yfinance not installed")
        except Exception as e:
            raise DataFetchError(f"YfinanceFetcher fetch failed: {e}") from e

    def _normalize_data(self, df: pd.DataFrame, stock_code: str) -> pd.DataFrame:
        """Normalize yfinance data to standard columns."""
        df = df.copy()

        # Reset index to get date as column
        df = df.reset_index()

        # yfinance columns: Date, Open, High, Low, Close, Volume
        column_mapping = {
            "Date": "date",
            "Open": "open",
            "High": "high",
            "Low": "low",
            "Close": "close",
            "Volume": "volume",
        }

        df = df.rename(columns=column_mapping)

        # Convert date
        if "date" in df.columns:
            df["date"] = pd.to_datetime(df["date"])

        # Calculate pct_chg if not present
        if "pct_chg" not in df.columns and "close" in df.columns:
            df["pct_chg"] = df["close"].pct_change() * 100
            df["pct_chg"] = df["pct_chg"].fillna(0).round(2)

        # Calculate amount if not present
        if "amount" not in df.columns and "close" in df.columns and "volume" in df.columns:
            df["amount"] = df["volume"] * df["close"]

        # Add code
        if "code" not in df.columns:
            df["code"] = normalize_stock_code(stock_code)

        keep_cols = ["code"] + [c for c in STANDARD_COLUMNS if c in df.columns]
        df = df[[c for c in keep_cols if c in df.columns]]

        return df

    def get_realtime_quote(self, stock_code: str) -> Optional[UnifiedRealtimeQuote]:
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

        except Exception as e:
            logger.warning(f"[YfinanceFetcher] Realtime quote failed: {e}")
            # Try Stooq fallback for US stocks
            if is_us_market(stock_code):
                return self._get_from_stooq(stock_code)
            return None

    def _get_from_stooq(self, stock_code: str) -> Optional[UnifiedRealtimeQuote]:
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


# Import STANDARD_COLUMNS at module level
from .base import STANDARD_COLUMNS
