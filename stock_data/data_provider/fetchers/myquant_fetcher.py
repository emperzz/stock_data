"""
Myquant (掘金量化) fetcher for A-share stock data (default priority 9 — last-resort backup).

API: ``gm`` SDK (https://www.myquant.cn/) — free public version (体验版/专业版/机构版)
covers history / current_price / get_symbols / get_trading_dates_by_year / stk_get_*.

Token configured via MYQUANT_TOKEN environment variable.
``gm.api.set_token`` is called lazily on the first ``is_available()`` invocation
(matching the Baostock/Tushare convention) so the manager can register-or-skip
correctly at construction time.

This fetcher is a *last-resort backup* — its default priority (9) places it
after every richer source in the failover chain (Tushare → Zhitu/Tencent/
Akshare → Myquant). Realtime quote is price-only; intraday minute line is
supported only for the most recent trading day (myquant 18:00 wash rule).

Implementation notes (not in CLAUDE.md — these are fetcher-internal quirks):
- A-share only (SHSE/SZSE); no HK/US. Unsupported frequencies (weekly/monthly/
  1-min) raise ``DataFetchError`` for transparent degradation.
- ``current_price`` returns price only; all other fields stay ``None`` when
  we can't fill them from elsewhere.
- ``pct_chg`` is not provided by myquant; we derive it in ``_normalize_data``
  as ``close_t / close_{t-1} - 1`` after sorting by ``bob`` (matching the
  Baostock/Akshare/Tushare convention — not close/open).
- ``get_all_stocks`` runs ``is_a_share_stock_code`` defensively, so even if
  myquant widens ``sec_type1=1010`` we don't pollute the cache with
  non-A-share rows.
- gm 3.0.x declares ``pandas<2.0`` (Python ≤3.11) — that pin is over-conservative
  upstream; the fetcher is verified compatible with pandas 2.x. Install with
  ``pip install -e ".[dev]" --no-deps`` or pre-install pandas 2.x to silence
  the resolver warning.
"""

# isort: off
import logging
import os
from datetime import datetime  # used in get_trade_calendar, get_index_intraday, get_intraday_data

import pandas as pd

from ..base import BaseFetcher, DataCapability, DataFetchError, normalize_stock_code
from ..core.types import RealtimeSource, UnifiedRealtimeQuote, safe_float
from ..utils.code_converter import to_myquant_format, to_myquant_index_format
from ..utils.normalize import is_a_share_stock_code
# isort: on

logger = logging.getLogger(__name__)


def _decode_gm_name(raw: object) -> str:
    """Reverse-decode gm SDK's double-encoded ``sec_name`` field.

    gm 3.x's ``get_symbols(sec_type1=1010)`` returns ``sec_name`` that has
    been GBK-encoded and then decoded as latin-1, producing a string of
    high-ord characters. This helper reverses that: each char's codepoint
    is treated as a byte, then decoded as GBK to recover the original
    Chinese name (e.g. ``'浦发银行'``).

    Falls back to ``str(raw)`` if the input is empty, ``None``, or
    already-clean UTF-8 (e.g. a future gm SDK release that fixes the bug
    or returns names with codepoints > U+00FF).
    """
    if raw is None:
        return ""
    s = str(raw)
    if not s:
        return s
    try:
        return bytes(s, "latin-1").decode("gbk")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return s


def _ts_to_date(ts: object) -> str:
    """Convert pandas ``Timestamp`` to ``YYYY-MM-DD`` string.

    Returns ``""`` for ``None``, ``NaT``, or unconvertible input.
    """
    if ts is None:
        return ""
    try:
        if pd.isna(ts):
            return ""
    except (TypeError, ValueError):
        return ""
    try:
        return pd.Timestamp(ts).strftime("%Y-%m-%d")
    except Exception:
        return ""


# myquant adjust constants (see gm.api)
ADJUST_NONE = 0  # 不复权
ADJUST_PREV = 1  # 前复权
ADJUST_POST = 2  # 后复权

# Frequency mapping: server "d/5/15/30/60" → myquant "1d/300s/900s/1800s/3600s"
_FREQ_MAP: dict[str, str] = {
    "d": "1d",
    "5": "300s",
    "15": "900s",
    "30": "1800s",
    "60": "3600s",
}

# Intraday mapping (used by both get_index_intraday and get_intraday_data)
_INTRADAY_FREQ_MAP: dict[str, str] = {
    "5": "300s",
    "15": "900s",
    "30": "1800s",
    "60": "3600s",
}

# Trade calendar start year — env-var overridable for deep backfill needs.
_CALENDAR_START_YEAR = int(os.getenv("MYQUANT_CALENDAR_START_YEAR", "2010"))


class MyquantFetcher(BaseFetcher):
    """Myquant (掘金量化) SDK fetcher for A-share data."""

    name = "MyquantFetcher"
    priority = int(os.getenv("MYQUANT_PRIORITY", "9"))
    supported_markets: set[str] = {"csi"}
    supported_data_types = (
        DataCapability.HISTORICAL_DWM
        | DataCapability.HISTORICAL_MIN
        | DataCapability.REALTIME_QUOTE
        | DataCapability.STOCK_LIST
        | DataCapability.TRADE_CALENDAR
        | DataCapability.INDEX_HISTORICAL
        | DataCapability.INDEX_INTRADAY
        | DataCapability.STOCK_INFO
    )

    def __init__(self):
        self._token = os.getenv("MYQUANT_TOKEN", "").strip()
        self._initialized = False
        self._init_error: str | None = None  # captured reason if SDK init fails

    def _ensure_initialized(self) -> None:
        """Lazily import ``gm.api`` and call ``set_token``.

        Sets ``self._initialized = True`` only when ALL three preconditions
        hold: ``MYQUANT_TOKEN`` is set, the ``gm`` package is importable,
        AND ``set_token(token)`` runs without error. Mirrors the
        Baostock/Tushare convention: ``is_available()`` triggers this so
        the manager can register-or-skip correctly at construction time.
        """
        if self._initialized:
            return
        if not self._token:
            logger.warning("[MyquantFetcher] MYQUANT_TOKEN not set")
            return  # _initialized stays False → is_available() returns False
        # Optimistic: assume success. Roll back to False on ImportError /
        # set_token failure so a subsequent is_available() returns False.
        self._initialized = True
        try:
            from gm.api import set_token  # type: ignore

            set_token(self._token)
            logger.info("[MyquantFetcher] Initialized (token configured)")
            self._init_error = None
        except ImportError as e:
            logger.warning("[MyquantFetcher] gm package not installed")
            self._initialized = False
            self._init_error = "gm SDK not importable"
        except Exception as e:
            logger.warning(f"[MyquantFetcher] Failed to set token: {e}")
            self._initialized = False
            self._init_error = f"set_token failed: {e}"

    def is_available(self) -> bool:
        """True iff MYQUANT_TOKEN is set AND ``gm`` SDK initializes successfully.

        Triggers lazy ``_ensure_initialized`` on first call, so once this
        returns True every later ``gm.api`` call has a configured token.
        """
        self._ensure_initialized()
        return self._initialized

    def unavailable_reason(self) -> str | None:
        """Return a human-readable reason this fetcher is unavailable, or None.

        Derived from the same state ``is_available()`` inspects. Captures
        the specific failure mode (token missing vs. SDK missing vs.
        set_token rejection) into ``_init_error`` during init so this
        method can surface it without re-running init.
        """
        if self.is_available():
            return None
        if not self._token:
            return f"MYQUANT_TOKEN environment variable not set (required by {self.name})"
        # Token is set but init didn't complete. _init_error captures why.
        return f"{self.name} unavailable: {self._init_error or 'unknown initialization error'}"

    def _map_adjust(self, adjust: str) -> int:
        """Map unified adjust to myquant integer constant.

        "" / None → ADJUST_NONE (0)
        "qfq"      → ADJUST_PREV (1)
        "hfq"      → ADJUST_POST (2)
        """
        if not adjust:
            return ADJUST_NONE
        mapping = {"qfq": ADJUST_PREV, "hfq": ADJUST_POST}
        return mapping.get(adjust, ADJUST_NONE)

    def _convert_code(self, stock_code: str) -> str:
        """Convert to myquant ``SHSE/SZSE.{code}`` format. Raises DataFetchError on unsupported markets."""
        try:
            return to_myquant_format(stock_code)
        except ValueError as e:
            raise DataFetchError(f"Myquant does not support code {stock_code}: {e}") from e

    # ---- unsupported base abstract methods ----

    def _fetch_raw_data(
        self,
        stock_code: str,
        start_date: str,
        end_date: str,
        frequency: str = "d",
        adjust: str | None = None,
    ) -> pd.DataFrame:
        """Fetch K-line data from myquant (stocks only — indices use get_index_historical).

        Supported frequencies: d, 5, 15, 30, 60. Raises DataFetchError on others.
        """
        if not self.is_available():
            return None  # type: ignore[return-value]
        if frequency not in _FREQ_MAP:
            raise DataFetchError(
                f"MyquantFetcher does not support frequency={frequency!r} "
                f"(supported: {sorted(_FREQ_MAP.keys())})"
            )

        try:
            from gm.api import history  # type: ignore

            symbol = self._convert_code(stock_code)
            df = history(
                symbol=symbol,
                frequency=_FREQ_MAP[frequency],
                start_time=start_date,
                end_time=end_date,
                adjust=self._map_adjust(adjust or ""),
                df=True,
            )
            if df is None or df.empty:
                raise DataFetchError(f"Myquant returned empty for {stock_code}")
            return df
        except DataFetchError:
            raise
        except Exception as e:
            raise DataFetchError(f"Myquant fetch_raw_data failed for {stock_code}: {e}") from e

    def _normalize_data(self, df: pd.DataFrame, stock_code: str) -> pd.DataFrame:
        """Normalize myquant history output to STANDARD_COLUMNS.

        myquant returns: symbol, frequency, open, close, high, low, amount, volume, bob, eob.
        - 'bob' (begin of bar) is the time anchor → renamed to 'date'
        - 'pct_chg' is NOT provided by myquant → derived from previous row's close:
              pct_chg[t] = (close[t] / close[t-1] - 1) * 100
          matching the standard convention used by Baostock/Akshare/Tushare
          (close vs prev_close, not close vs open). The first row has no
          prior reference → pct_chg = None.
        - Other STANDARD_COLUMNS already match the source naming.
        """
        df = df.copy()
        if "bob" in df.columns:
            df = df.rename(columns={"bob": "date"})

        if "pct_chg" not in df.columns and "close" in df.columns:
            # Ensure deterministic row order before computing inter-bar deltas.
            if "date" in df.columns:
                df = df.sort_values("date", kind="mergesort").reset_index(drop=True)
            close_num = pd.to_numeric(df["close"], errors="coerce")
            prev_close = close_num.shift(1)
            pct = (close_num / prev_close) - 1.0
            # Guard against division-by-zero / inf → NaN; first row is already NaN.
            pct = pct.replace([float("inf"), float("-inf")], float("nan"))
            df["pct_chg"] = pct * 100.0
        return self._normalize_dataframe(df, stock_code, column_mapping={})

    def get_realtime_quote(self, stock_code: str) -> UnifiedRealtimeQuote | None:
        """Get realtime quote from myquant.

        Note: myquant's ``current_price`` only returns ``{symbol, price, created_at}`` —
        no volume/amount/change_pct/open/high/low. This fetcher is therefore
        positioned as a *last-resort* backup; richer quotes come from Tushare/
        Zhitu/Tencent/Akshare in the failover chain. Most other fields stay ``None``.
        """
        if not self.is_available():
            return None
        try:
            from gm.api import current_price  # type: ignore

            symbol = self._convert_code(stock_code)
            rows = current_price(symbols=symbol)
            if not rows:
                return None
            # Defensive: gm may return a list of dicts or a single dict — normalize.
            if not isinstance(rows, list):
                rows = [rows]
            row = rows[0]
            return UnifiedRealtimeQuote(
                code=normalize_stock_code(stock_code),
                source=RealtimeSource.MYQUANT,
                price=safe_float(row.get("price")),
            )
        except Exception:
            logger.warning(
                f"[MyquantFetcher] get_realtime_quote failed for {stock_code}",
                exc_info=True,
            )
            return None

    def get_trade_calendar(self) -> list[str] | None:
        """Get A-share trade calendar from myquant.

        Uses SHSE calendar (沪深共用). Returns ascending YYYY-MM-DD list.
        Returns None if unavailable or no data.
        """
        if not self.is_available():
            return None
        try:
            from gm.api import get_trading_dates_by_year  # type: ignore

            now = datetime.now()
            df = get_trading_dates_by_year(
                exchange="SHSE",
                start_year=_CALENDAR_START_YEAR,
                end_year=now.year,
            )
            if df is None or df.empty or "trade_date" not in df.columns:
                return None
            # myquant sets trade_date="" for non-trading days; filter those out
            dates = [
                d
                for d in df["trade_date"].astype(str).tolist()
                if d and d not in ("", "nan", "None")
            ]
            return sorted(dates)
        except Exception:
            logger.warning(
                "[MyquantFetcher] get_trade_calendar failed",
                exc_info=True,
            )
            return None

    def get_all_stocks(self, market: str = "csi") -> list:
        """Get A-share stock list from myquant.

        myquant's ``get_symbols(sec_type1=1010)`` returns additional fields
        beyond code/name: upper_limit / lower_limit / is_st / is_suspended /
        pre_close / turn_rate / adj_factor. We surface these as raw dict keys
        so the persistence layer can optionally consume them.

        Returns ``[]`` for non-CSI markets (myquant only covers A-share).
        Filters the upstream result with ``is_a_share_stock_code`` to
        defensively drop ETFs / funds / indices in case the upstream
        ``sec_type1`` semantics broaden. Matches the Baostock filter
        convention (utils/normalize.A_SHARE_STOCK_PREFIXES).
        """
        if market != "csi":
            return []
        if not self.is_available():
            return []
        try:
            from gm.api import get_symbols  # type: ignore

            df = get_symbols(sec_type1=1010, df=True)
            if df is None or df.empty:
                return []
            out: list = []
            for _, row in df.iterrows():
                full = str(row.get("symbol", ""))
                code = full.split(".", 1)[1] if "." in full else full
                # Defensive filter: drop non-A-share-stock codes (ETFs/funds/indices).
                if not is_a_share_stock_code(code):
                    continue
                out.append(
                    {
                        "code": code,
                        "name": _decode_gm_name(row.get("sec_name", "")),
                        "symbol_full": full,
                        "exchange": str(row.get("exchange", "")),
                        "is_st": bool(row.get("is_st", False)),
                        "is_suspended": bool(row.get("is_suspended", False)),
                        "upper_limit": safe_float(row.get("upper_limit")),
                        "lower_limit": safe_float(row.get("lower_limit")),
                        "turn_rate": safe_float(row.get("turn_rate")),
                        "adj_factor": safe_float(row.get("adj_factor")),
                        "pre_close": safe_float(row.get("pre_close")),
                    }
                )
            return out
        except Exception:
            logger.warning(
                "[MyquantFetcher] get_all_stocks failed",
                exc_info=True,
            )
            return []

    def get_intraday_data(
        self, stock_code: str, period: str = "5", adjust: str = ""
    ) -> pd.DataFrame | None:
        """Get intraday minute-level data for a CSI stock via myquant.

        Fetches the most recent trading day (myquant 18:00 wash rule applies
        for same-day data; for older dates the result is also fine).
        Supports 5/15/30/60; ``1min`` is intentionally rejected because
        myquant's public tier does not expose 1s-resolution.

        Args:
            stock_code: 6-digit A-share code (e.g., "600519", "000002")
            period: Minute period - "5", "15", "30", "60"
            adjust: Unified adjust ("", "qfq", "hfq") — mapped to myquant int

        Returns:
            DataFrame with columns: time, open, high, low, close, volume, amount
            or None if unavailable.
        """
        if not self.is_available():
            return None
        if period not in _INTRADAY_FREQ_MAP:
            raise DataFetchError(
                f"MyquantFetcher intraday does not support period={period!r} "
                f"(supported: {sorted(_INTRADAY_FREQ_MAP.keys())})"
            )
        try:
            from gm.api import history  # type: ignore

            symbol = self._convert_code(stock_code)
            today = datetime.now().strftime("%Y-%m-%d")
            df = history(
                symbol=symbol,
                frequency=_INTRADAY_FREQ_MAP[period],
                start_time=today,
                end_time=today,
                adjust=self._map_adjust(adjust or ""),
                df=True,
            )
            if df is None or df.empty:
                return None
            return self._normalize_intraday_df(df)
        except DataFetchError:
            raise
        except Exception:
            logger.warning(
                f"[MyquantFetcher] get_intraday_data failed for {stock_code}",
                exc_info=True,
            )
            return None

    def get_index_historical(
        self,
        index_code: str,
        start_date: str | None,
        end_date: str | None,
        frequency: str,
    ) -> pd.DataFrame | None:
        """Get historical K-line data for a CSI index via myquant.

        Only ``frequency="d"`` is supported. Weekly/monthly would need
        separate ``history`` calls aggregated client-side, which we don't
        implement here — the manager will fall through to other fetchers.
        """
        if not self.is_available():
            return None
        if frequency != "d":
            raise DataFetchError(
                f"MyquantFetcher index does not support frequency={frequency!r} "
                "(only 'd' is supported; use another fetcher for w/m)"
            )
        try:
            symbol = to_myquant_index_format(index_code)
        except ValueError as e:
            raise DataFetchError(f"Myquant does not support {index_code}: {e}") from e
        try:
            from gm.api import history  # type: ignore

            df = history(
                symbol=symbol,
                frequency="1d",
                start_time=start_date or "",
                end_time=end_date or "",
                df=True,
            )
            if df is None or df.empty:
                return None
            return self._normalize_index_df(df)
        except DataFetchError:
            raise
        except Exception:
            logger.warning(
                f"[MyquantFetcher] get_index_historical failed for {index_code}",
                exc_info=True,
            )
            return None

    def get_index_intraday(self, index_code: str, period: str = "5") -> pd.DataFrame | None:
        """Get intraday minute-level data for a CSI index via myquant.

        Fetches the most recent trading day (myquant 18:00 wash rule applies
        for same-day data; for older dates the result is also fine).
        """
        if not self.is_available():
            return None
        if period not in _INTRADAY_FREQ_MAP:
            raise DataFetchError(
                f"MyquantFetcher index intraday does not support period={period!r} "
                f"(supported: {sorted(_INTRADAY_FREQ_MAP.keys())})"
            )
        try:
            symbol = to_myquant_index_format(index_code)
        except ValueError as e:
            raise DataFetchError(f"Myquant does not support {index_code}: {e}") from e
        try:
            from gm.api import history  # type: ignore

            today = datetime.now().strftime("%Y-%m-%d")
            df = history(
                symbol=symbol,
                frequency=_INTRADAY_FREQ_MAP[period],
                start_time=today,
                end_time=today,
                df=True,
            )
            if df is None or df.empty:
                return None
            return self._normalize_intraday_df(df)
        except DataFetchError:
            raise
        except Exception:
            logger.warning(
                f"[MyquantFetcher] get_index_intraday failed for {index_code}",
                exc_info=True,
            )
            return None

    def _normalize_index_df(self, df: pd.DataFrame) -> pd.DataFrame:
        """Normalize myquant daily-index history to STANDARD_COLUMNS.

        Mirrors the inter-bar pct_chg convention used by
        :meth:`_normalize_data`: pct_chg[t] = (close[t] / close[t-1] - 1) * 100,
        first row NaN. ``pct_chg`` is not part of the standard
        ``IndexHistoryResponse`` schema today, but kept for parity with
        the stock K-line response and in case it lands in the index
        schema later.
        """
        df = df.copy()
        if "bob" in df.columns:
            df = df.rename(columns={"bob": "date"})
        if "pct_chg" not in df.columns and "close" in df.columns:
            if "date" in df.columns:
                df = df.sort_values("date", kind="mergesort").reset_index(drop=True)
            close_num = pd.to_numeric(df["close"], errors="coerce")
            prev_close = close_num.shift(1)
            pct = (close_num / prev_close) - 1.0
            pct = pct.replace([float("inf"), float("-inf")], float("nan"))
            df["pct_chg"] = pct * 100.0
        # No 'code' column needed for index history; strip symbol-related noise
        for col in ("symbol", "frequency"):
            if col in df.columns:
                df = df.drop(columns=[col])
        return df

    def _normalize_intraday_df(self, df: pd.DataFrame) -> pd.DataFrame:
        """Normalize myquant intraday (stock or index) to time/o/h/l/c/v/a schema.

        Used by both :meth:`get_intraday_data` (stocks) and
        :meth:`get_index_intraday` (indices) — the upstream ``gm.api.history``
        returns the same shape for both, so a single normalizer suffices.
        """
        df = df.copy()
        if "bob" in df.columns:
            df = df.rename(columns={"bob": "time"})
        elif "eob" in df.columns:
            df = df.rename(columns={"eob": "time"})
        # Coerce to HH:MM:SS strings iff the time column is datetime-typed.
        if "time" in df.columns and pd.api.types.is_datetime64_any_dtype(df["time"]):
            df["time"] = df["time"].dt.strftime("%H:%M:%S")
        for col in ("open", "high", "low", "close", "amount"):
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")
        if "volume" in df.columns:
            df["volume"] = pd.to_numeric(df["volume"], errors="coerce").astype("Int64")
        keep = [
            c
            for c in ("time", "open", "high", "low", "close", "volume", "amount")
            if c in df.columns
        ]
        return df[keep]

    def get_stock_info(self, stock_code: str) -> dict | None:
        """公司画像 (Myquant free tier) — 复用 get_symbols 加 symbols= 单只过滤.

        Free tier 仅提供 3 个有效字段: name/listed_date/delisted_date. 其他字段
        留空, 作为 Zhitu 失败的降级体验.
        """
        if not self.is_available():
            return None
        try:
            from gm.api import get_symbols  # type: ignore  # lazy import

            # is_available() above already triggered _ensure_initialized(); no
            # need to call it again here.
            symbol_full = self._convert_code(stock_code)  # "SHSE.600519" etc.
            df = get_symbols(sec_type1=1010, symbols=symbol_full, df=True)
            if df is None or df.empty:
                logger.warning("[MyquantFetcher] get_symbols empty for %s", stock_code)
                return None
            row = df.iloc[0]
            return {
                "code":              stock_code,
                "name":              _decode_gm_name(row.get("sec_name", "")),
                "ename":             "",
                "market":            "csi",
                "listed_date":       _ts_to_date(row.get("listed_date")),
                "delisted_date":     _ts_to_date(row.get("delisted_date")),
                "total_shares":      None,  # free tier 不提供
                "float_shares":      None,  # free tier 不提供
                "industry":          "",    # paid 接口 (GmError 2001)
                "concepts":          [],
                "registered_address": "",
                "registered_capital": "",
                "legal_representative": "",
                "business_scope":    "",
                "established_date":  "",
                "secretary":         "",
                "secretary_phone":   "",
                "secretary_email":   "",
            }
        except Exception as e:
            logger.warning("[MyquantFetcher] get_stock_info %s failed: %s", stock_code, e)
            return None
