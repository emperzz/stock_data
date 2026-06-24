"""
Zhitu fetcher for A-share realtime quote (Priority 99).

API: https://api.zhituapi.com/hs/real/ssjy/{stock_code}?token={token}
Token configured via ZHITU_TOKEN environment variable.
"""

import logging
import os
from datetime import date

import pandas as pd
import requests

from ..base import BaseFetcher, DataCapability, DataFetchError, normalize_stock_code
from ..core.types import RealtimeSource, UnifiedRealtimeQuote, safe_float, safe_int
from ..utils.code_converter import to_zhitu_format, to_zhitu_market_suffix

logger = logging.getLogger(__name__)

# API base URL
ZHITU_API_BASE = "https://api.zhituapi.com"

# Zhitu /hs/index/tree type2 → (type, subtype) mapping
ZHITU_TYPE2_MAPPING: dict[int, tuple[str, str]] = {
    0: ("industry", "申万行业"),
    1: ("industry", "申万二级"),
    2: ("concept", "热门概念"),
    3: ("concept", "概念板块"),
    4: ("concept", "地域板块"),
    5: ("industry", "证监会行业"),
    6: ("index", "分类"),
    7: ("index", "指数成分"),
    8: ("special", "风险警示"),
    9: ("index", "大盘指数"),
    10: ("special", "次新股"),
    11: ("special", "沪港通"),
    12: ("special", "深港通"),
}

# type → 合法 subtype 集合（与 persistence/board.py 保持同步）
ZHITU_SUBTYPES_BY_TYPE: dict[str, set[str]] = {
    "industry": {"申万行业", "申万二级", "证监会行业"},
    "concept": {"热门概念", "概念板块", "地域板块"},
    "index": {"分类", "指数成分", "大盘指数"},
    "special": {"风险警示", "次新股", "沪港通", "深港通"},
}


def _split_concepts(raw: object) -> list[str]:
    """Split Zhitu's comma-separated ``idea`` string into a deduplicated list.

    Returns ``[]`` for empty/None input. Items are stripped; empty items dropped.
    """
    if not raw:
        return []
    parts = [p.strip() for p in str(raw).split(",")]
    seen: set[str] = set()
    out: list[str] = []
    for p in parts:
        if p and p not in seen:
            seen.add(p)
            out.append(p)
    return out


class ZhituFetcher(BaseFetcher):
    """Zhitu API fetcher for A-share realtime quotes (no historical data)."""

    name = "ZhituFetcher"
    priority = int(os.getenv("ZHITU_PRIORITY", "4"))
    supported_markets: set[str] = {"csi"}
    supported_data_types = (
        DataCapability.REALTIME_QUOTE
        | DataCapability.STOCK_ZT_POOL
        | DataCapability.STOCK_INFO
        | DataCapability.HISTORICAL_MIN
        | DataCapability.STOCK_LIST
        | DataCapability.STOCK_BOARD
    )

    def __init__(self):
        self._token = os.getenv("ZHITU_TOKEN", "").strip()

    def is_available(self) -> bool:
        """Check if Zhitu API token is configured."""
        return bool(self._token)

    def unavailable_reason(self) -> str | None:
        """Return a human-readable reason this fetcher is unavailable, or None.

        Mirrors the actual availability check so the explorer's docs can
        surface *why* the fetcher didn't register. Derived from real state
        (no hardcoded "token not set" literal that could drift from
        is_available()).
        """
        if not self._token:
            return f"ZHITU_TOKEN environment variable not set (required by {self.name})"
        return None

    def _convert_code(self, stock_code: str) -> str:
        """Convert to Zhitu format. Delegates to ``to_zhitu_format``."""
        return to_zhitu_format(stock_code)

    def _market_suffix(self, stock_code: str) -> str:
        """Zhitu market suffix. Delegates to ``to_zhitu_market_suffix``."""
        return to_zhitu_market_suffix(stock_code)

    def _fetch_raw_data(
        self,
        stock_code: str,
        start_date: str,
        end_date: str,
        frequency: str = "d",
        adjust: str | None = None,
    ) -> pd.DataFrame:
        """Zhitu does not support historical data, only realtime quotes."""
        raise DataFetchError(
            "ZhituFetcher does not support historical K-line data, only realtime quotes"
        )

    def _normalize_data(self, df: pd.DataFrame, stock_code: str) -> pd.DataFrame:
        """Zhitu does not support historical data normalization."""
        raise DataFetchError("ZhituFetcher does not support historical K-line data")

    def get_realtime_quote(self, stock_code: str) -> UnifiedRealtimeQuote | None:
        """Get realtime quote from Zhitu API.

        Args:
            stock_code: Stock code (e.g., 600519, 000001)

        Returns:
            UnifiedRealtimeQuote with realtime data, or None if unavailable.
        """
        if not self.is_available():
            logger.warning("[ZhituFetcher] ZHITU_TOKEN not configured")
            return None

        try:
            code = self._convert_code(stock_code)
            url = f"{ZHITU_API_BASE}/hs/real/ssjy/{code}"
            params = {"token": self._token}

            response = requests.get(url, params=params, timeout=10)
            response.raise_for_status()

            data = response.json()

            # Check for error response
            if isinstance(data, dict) and "detail" in data:
                error_msg = data.get("detail", "Unknown error")
                if "Licence证书" in str(error_msg) or "不存在" in str(error_msg):
                    logger.warning("[ZhituFetcher] Invalid token: token rejected by upstream")
                else:
                    logger.warning(f"[ZhituFetcher] API error: {error_msg[:50]}...")
                return None

            # Zhitu returns a dict directly (not a list)
            if not isinstance(data, dict):
                logger.warning(
                    f"[ZhituFetcher] Unexpected response type for {stock_code}: {type(data)}"
                )
                return None

            if not data:
                logger.warning(f"[ZhituFetcher] Empty response for {stock_code}")
                return None

            row = data

            return UnifiedRealtimeQuote(
                code=normalize_stock_code(stock_code),
                name=str(row.get("nm", "")),
                source=RealtimeSource.ZHITU,
                price=safe_float(row.get("p")),
                change_pct=safe_float(row.get("pc")),
                change_amount=safe_float(row.get("ud")),
                volume=safe_int(row.get("v")),
                amount=safe_float(row.get("cje")),
                open_price=safe_float(row.get("o")),
                high=safe_float(row.get("h")),
                low=safe_float(row.get("l")),
                pre_close=safe_float(row.get("yc")),
                amplitude=safe_float(row.get("zf")),
                volume_ratio=safe_float(row.get("lb")),
                turnover_rate=safe_float(row.get("hs")),
                pe_ratio=safe_float(row.get("pe")),
                pb_ratio=safe_float(row.get("sjl")),
                total_mv=safe_float(row.get("sz")),
                circ_mv=safe_float(row.get("lt")),
            )

        except requests.exceptions.Timeout:
            logger.warning(f"[ZhituFetcher] Timeout for {stock_code}")
            return None
        except requests.exceptions.RequestException:
            logger.warning(f"[ZhituFetcher] Request failed for {stock_code}", exc_info=True)
            return None
        except Exception:
            logger.warning(f"[ZhituFetcher] Error for {stock_code}", exc_info=True)
            return None

    def get_intraday_data(
        self, stock_code: str, period: str = "5", adjust: str = ""
    ) -> pd.DataFrame | None:
        """Get intraday minute-level data from Zhitu history API.

        API: https://api.zhituapi.com/hs/history/{code}.{market}/{period}/{adjust}?token={token}&st={date}&et={date}

        Args:
            stock_code: Stock code (e.g., 600519, 000001)
            period: Minute period - "5", "15", "30", "60" (NOT "1")
            adjust: Adjustment type - ""=不复权, "qfq"=前复权, "hfq"=后复权

        Returns:
            DataFrame with columns: time, open, high, low, close, volume, amount
            or None if not supported or period=1 (not supported by Zhitu).
        """
        if not self.is_available():
            logger.warning("[ZhituFetcher] ZHITU_TOKEN not configured")
            return None

        # Zhitu doesn't support period=1
        if period == "1":
            raise DataFetchError("ZhituFetcher does not support period=1")

        try:
            code = normalize_stock_code(stock_code)
            market = self._market_suffix(stock_code)
            symbol = f"{code}{market}"

            # Map adjust: API format
            adj_map = {"": "n", "qfq": "f", "hfq": "b"}
            adj_value = adj_map.get(adjust, "n")

            # Get latest trade date
            from ..persistence.trade_calendar import get_latest_cached_trade_date

            latest_date = get_latest_cached_trade_date()
            if not latest_date:
                latest_date = date.today().strftime("%Y%m%d")
            else:
                latest_date = latest_date.replace("-", "")

            url = f"{ZHITU_API_BASE}/hs/history/{symbol}/{period}/{adj_value}"
            params = {
                "token": self._token,
                "st": latest_date,
                "et": latest_date,
            }

            response = requests.get(url, params=params, timeout=10)
            response.raise_for_status()
            data = response.json()

            if isinstance(data, dict) and "detail" in data:
                logger.warning(f"[ZhituFetcher] API error: {data.get('detail')}")
                return None

            if not isinstance(data, list):
                logger.warning(f"[ZhituFetcher] Unexpected response type: {type(data)}")
                return None

            if not data:
                return None

            df = pd.DataFrame(data)
            return self._normalize_intraday_zhitu(df)

        except DataFetchError:
            raise
        except requests.exceptions.Timeout:
            logger.warning(f"[ZhituFetcher] Timeout for {stock_code}")
            return None
        except requests.exceptions.RequestException:
            logger.warning(f"[ZhituFetcher] Request failed for {stock_code}", exc_info=True)
            return None
        except Exception:
            logger.warning(f"[ZhituFetcher] Error for {stock_code}", exc_info=True)
            return None

    def get_zt_pool(self, pool_type: str, date: str) -> list[dict] | None:
        """
        Get ZT (涨跌停) pool data from Zhitu API.

        Args:
            pool_type: Pool type - "zt" (涨停), "dt" (跌停), "zbgc" (炸板)
            date: Pool date in YYYY-MM-DD format

        Returns:
            List of stock dicts with normalized fields, or None if unavailable.
        """
        if not self.is_available():
            logger.warning("[ZhituFetcher] ZHITU_TOKEN not configured")
            return None

        # Map pool_type to Zhitu API path
        path_map = {"zt": "ztgc", "dt": "dtgc", "zbgc": "zbgc"}
        api_path = path_map.get(pool_type)
        if not api_path:
            logger.warning(f"[ZhituFetcher] Unknown pool_type: {pool_type}")
            return None

        try:
            url = f"{ZHITU_API_BASE}/hs/pool/{api_path}/{date}"
            params = {"token": self._token}

            response = requests.get(url, params=params, timeout=10)
            response.raise_for_status()

            data = response.json()

            if isinstance(data, dict) and "detail" in data:
                logger.warning(f"[ZhituFetcher] API error: {data.get('detail')}")
                return None

            if not isinstance(data, list):
                logger.warning(f"[ZhituFetcher] Unexpected response type: {type(data)}")
                return None

            # Normalize and return
            return [self._normalize_zt_stock(row, pool_type) for row in data]

        except requests.exceptions.Timeout:
            logger.warning(f"[ZhituFetcher] Timeout for ZT pool {pool_type} {date}")
            return None
        except requests.exceptions.RequestException:
            logger.warning(f"[ZhituFetcher] Request failed for ZT pool {pool_type}", exc_info=True)
            return None
        except Exception:
            logger.warning(f"[ZhituFetcher] Error for ZT pool {pool_type}", exc_info=True)
            return None

    def _normalize_zt_stock(self, row: dict, pool_type: str) -> dict:
        """Normalize Zhitu ZT pool response to standard format."""
        code = row.get("dm", "")
        # Strip exchange prefix: "sz000657" -> "000657", "sh600519" -> "600519"
        if code.startswith(("sh", "sz", "SH", "SZ")):
            code = code[2:]

        return {
            "code": code,
            "name": row.get("mc", ""),
            "price": row.get("p"),
            "change_pct": row.get("zf"),
            "amount": row.get("cje"),
            "circ_mv": row.get("lt"),
            "total_mv": row.get("zsz"),
            "turnover_rate": row.get("hs"),
            "lb_count": row.get("lbc"),
            "first_seal_time": row.get("fbt"),
            "last_seal_time": row.get("lbt"),
            "seal_amount": row.get("zj"),
            "seal_count": row.get("zbc"),
            "zt_count": row.get("tj"),
        }

    def _normalize_intraday_zhitu(self, df: pd.DataFrame) -> pd.DataFrame:
        """Normalize Zhitu history API output."""
        df = df.copy()
        df = df.rename(
            columns={
                "t": "time",
                "o": "open",
                "h": "high",
                "l": "low",
                "c": "close",
                "v": "volume",
                "a": "amount",
            }
        )
        if "time" in df.columns:
            # Zhitu returns ISO format with T, extract HH:MM:SS
            df["time"] = df["time"].astype(str).str[-8:]
        numeric_cols = ["open", "high", "low", "close", "volume", "amount"]
        for col in numeric_cols:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")
        keep_cols = ["time", "open", "high", "low", "close", "volume", "amount"]
        df = df[[c for c in keep_cols if c in df.columns]]
        return df

    def get_all_stocks(self, market: str = "csi") -> list:
        """Get the full A-share stock list from Zhitu's ``/hs/list/all``.

        Zhitu only supports A-share (``csi``); HK/US return ``[]`` so the
        manager's failover keeps trying other fetchers. Each item is
        ``{"code": <dm>, "name": <mc>, "exchange": <jys>}`` — the
        ``exchange`` value is passed through raw (``"sh"``/``"sz"``);
        persistence normalizes via ``_normalize_exchange``.

        Returns:
            List of stock dicts, or ``[]`` on token absence / HTTP
            failure / parse error. Empty list (not raise) keeps the
            failover loop alive so the next fetcher can try.
        """
        if market != "csi":
            return []
        if not self.is_available():
            logger.warning("[ZhituFetcher] ZHITU_TOKEN not configured")
            return []

        try:
            url = f"{ZHITU_API_BASE}/hs/list/all"
            params = {"token": self._token}

            response = requests.get(url, params=params, timeout=10)
            response.raise_for_status()

            data = response.json()

            if isinstance(data, dict) and "detail" in data:
                logger.warning(
                    f"[ZhituFetcher] get_all_stocks API error: "
                    f"{data.get('detail', 'unknown')[:80]}"
                )
                return []

            if not isinstance(data, list):
                logger.warning(
                    f"[ZhituFetcher] get_all_stocks unexpected type: {type(data)}"
                )
                return []

            result: list = []
            for row in data:
                if not isinstance(row, dict):
                    continue
                code = str(row.get("dm", "")).strip()
                if not code:
                    continue
                result.append(
                    {
                        "code": code,
                        "name": str(row.get("mc", "")).strip(),
                        "exchange": str(row.get("jys", "")).strip().lower(),
                    }
                )
            return result

        except requests.exceptions.Timeout:
            logger.warning("[ZhituFetcher] get_all_stocks timeout")
            return []
        except requests.exceptions.RequestException:
            logger.warning(
                "[ZhituFetcher] get_all_stocks request failed", exc_info=True
            )
            return []
        except Exception:
            logger.warning(
                "[ZhituFetcher] get_all_stocks error", exc_info=True
            )
            return []

    def get_stock_info(self, stock_code: str) -> dict | None:
        """公司画像 — Zhitu gs/gsjj 端点 (https://api.zhituapi.com/hs/gs/gsjj/{code}).

        返回归一化的 18 user-data 字段 (source 由 manager 注入)。失败返 None 让 failover 工作。
        """
        if not self.is_available():
            return None
        url = f"{ZHITU_API_BASE}/hs/gs/gsjj/{stock_code}"
        params = {"token": self._token}
        try:
            response = requests.get(url, params=params, timeout=10)
            response.raise_for_status()
            data = response.json()
        except (requests.RequestException, ValueError) as e:
            logger.warning("[ZhituFetcher] get_stock_info %s failed: %s", stock_code, e)
            return None
        if not isinstance(data, dict) or "code" not in data:
            logger.warning("[ZhituFetcher] get_stock_info %s: malformed payload", stock_code)
            return None
        return {
            "code":              stock_code,
            "name":              data.get("name", "") or "",
            "ename":             data.get("ename", "") or "",
            "market":            "csi",
            "listed_date":       str(data.get("ldate", "") or ""),
            "delisted_date":     "",
            "total_shares":      safe_float(data.get("totalstock")),
            "float_shares":      safe_float(data.get("flowstock")),
            "industry":          "",
            "concepts":          _split_concepts(data.get("idea", "")),
            "registered_address": data.get("raddr", "") or "",
            "registered_capital": data.get("rcapital", "") or "",
            "legal_representative": data.get("rname", "") or "",
            "business_scope":    data.get("bscope", "") or "",
            "established_date":  str(data.get("rdate", "") or ""),
            "secretary":         data.get("bsname", "") or "",
            "secretary_phone":   data.get("bsphone", "") or "",
            "secretary_email":   data.get("bsemail", "") or "",
        }

    # ---------- board methods ----------

    def _fetch_board_tree(self) -> list[dict] | None:
        """Fetch raw /hs/index/tree response leaves. Returns list or None on failure."""
        if not self.is_available():
            return None
        try:
            url = f"{ZHITU_API_BASE}/hs/index/tree"
            params = {"token": self._token}
            response = requests.get(url, params=params, timeout=10)
            response.raise_for_status()
            data = response.json()

            if isinstance(data, dict) and "detail" in data:
                logger.warning(
                    f"[ZhituFetcher] _fetch_board_tree API error: "
                    f"{data.get('detail', '')[:80]}"
                )
                return None
            if not isinstance(data, list):
                return None
            return [r for r in data if isinstance(r, dict) and r.get("isleaf") == 1]
        except Exception:
            logger.warning("[ZhituFetcher] _fetch_board_tree failed", exc_info=True)
            return None

    def get_board_tree(
        self, board_type: str, subtype: str | None = None
    ) -> list[dict]:
        """Get boards filtered by type and optionally subtype.

        Returns list of ``{code, name, type, subtype}`` dicts.
        Returns ``[]`` on failure or no match.
        """
        leaves = self._fetch_board_tree()
        if leaves is None:
            return []

        out: list[dict] = []
        for row in leaves:
            type2 = row.get("type2")
            mapped = ZHITU_TYPE2_MAPPING.get(type2)
            if mapped is None:
                continue
            row_type, row_subtype = mapped
            if row_type != board_type:
                continue
            if subtype is not None and row_subtype != subtype:
                continue
            out.append({
                "code": str(row.get("code", "")),
                "name": str(row.get("name", "")),
                "type": row_type,
                "subtype": row_subtype,
            })
        return out

    def get_board_stocks(self, board_code: str) -> list[dict]:
        """Get stocks belonging to a Zhitu board via /hs/index/stock/{code}.

        Returns ``[{stock_code, stock_name, exchange}]`` or ``[]`` on failure.
        """
        if not self.is_available():
            return []
        try:
            url = f"{ZHITU_API_BASE}/hs/index/stock/{board_code}"
            params = {"token": self._token}
            response = requests.get(url, params=params, timeout=10)
            response.raise_for_status()
            data = response.json()

            if isinstance(data, dict) and "detail" in data:
                logger.warning(
                    f"[ZhituFetcher] get_board_stocks({board_code}) API error"
                )
                return []
            if not isinstance(data, list):
                return []
            return [
                {
                    "stock_code": str(r.get("dm", "")).strip(),
                    "stock_name": str(r.get("mc", "")).strip(),
                    "exchange": str(r.get("jys", "")).strip().lower(),
                }
                for r in data
                if isinstance(r, dict) and r.get("dm")
            ]
        except Exception:
            logger.warning(
                f"[ZhituFetcher] get_board_stocks({board_code}) failed",
                exc_info=True,
            )
            return []

    def get_stock_boards(self, stock_code: str) -> list[dict] | None:
        """Get boards a stock belongs to via /hs/index/index/{stock_code}.

        Returns ``[{code, name, type, subtype}]`` or ``None`` on failure.
        ``None`` (not ``[]``) so callers can distinguish "no data" from "no match".
        """
        if not self.is_available():
            return None
        try:
            url = f"{ZHITU_API_BASE}/hs/index/index/{stock_code}"
            params = {"token": self._token}
            response = requests.get(url, params=params, timeout=10)
            response.raise_for_status()
            data = response.json()

            if isinstance(data, dict) and "detail" in data:
                logger.warning(
                    f"[ZhituFetcher] get_stock_boards({stock_code}) API error"
                )
                return None
            if not isinstance(data, list):
                return None

            out: list[dict] = []
            for r in data:
                if not isinstance(r, dict):
                    continue
                code = str(r.get("code", "")).strip()
                name = str(r.get("name", "")).strip()
                if not code:
                    continue
                subtype = self._infer_subtype_from_name(name)
                row_type = self._infer_type_from_subtype(subtype)
                out.append({
                    "code": code,
                    "name": name,
                    "type": row_type,
                    "subtype": subtype,
                })
            return out
        except Exception:
            logger.warning(
                f"[ZhituFetcher] get_stock_boards({stock_code}) failed",
                exc_info=True,
            )
            return None

    @staticmethod
    def _infer_subtype_from_name(name: str) -> str:
        """Extract subtype from Zhitu's ``A股-{大类}-{细分}`` name format.

        Example: "A股-申万行业-银行" → "申万行业"
        """
        parts = name.split("-")
        if len(parts) >= 2 and parts[0] == "A股":
            return parts[1]
        return ""

    @staticmethod
    def _infer_type_from_subtype(subtype: str) -> str:
        """Map subtype back to type."""
        for board_type, subtypes in ZHITU_SUBTYPES_BY_TYPE.items():
            if subtype in subtypes:
                return board_type
        return ""

    def get_board_history(
        self, board_code: str, frequency: str = "d", days: int = 30
    ) -> list[dict]:
        """Get K-line for a Zhitu board.

        NOT IMPLEMENTED — Zhitu's /hs/history/ endpoints are stock-level only.
        """
        raise NotImplementedError(
            f"ZhituFetcher does not provide board-level K-line data "
            f"(board_code={board_code!r}, frequency={frequency!r}, days={days!r}). "
            f"No upstream Zhitu API exposes this."
        )
