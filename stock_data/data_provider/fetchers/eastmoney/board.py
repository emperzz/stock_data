"""Board (concept/industry) helpers for EastMoneyFetcher.

Migrated from ``stock_data.data_provider.fetchers.akshare.board``.

The akshare EM APIs (e.g. ``ak.stock_board_concept_name_em``) are the
canonical EastMoney board endpoints — they're exposed through akshare
but originate from EastMoney's public board pages.
"""
from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

logger = logging.getLogger(__name__)

# Module-level reference to akshare; populated lazily by ``get_ak``.
# Tests monkey-patch this attribute directly to avoid real akshare I/O.
_AKSHARE: Any = None


def get_ak() -> Any:
    """Return the akshare module, importing it on first call.

    Lazy import keeps akshare optional for tests and for code paths
    that don't touch board data. The returned module is also exposed
    as the module-level ``_AKSHARE`` attribute so tests can
    ``@patch`` it before the import is triggered.
    """
    global _AKSHARE
    if _AKSHARE is None:
        import akshare as ak
        _AKSHARE = ak
    return _AKSHARE


_BOARD_LIST_QUOTE_COLS: dict[str, str] = {
    "price": "最新价",
    "change_pct": "涨跌幅",
    "change_amount": "涨跌额",
    "volume": "成交量",
    "amount": "成交额",
    "turnover_rate": "换手率",
    "total_mv": "总市值",
    "up_count": "上涨家数",
    "down_count": "下跌家数",
    "leading_stock": "领涨股票",
    "leading_stock_pct": "领涨股票-涨跌幅",
}

_BOARD_STOCK_QUOTE_COLS: dict[str, str] = {
    "price": "最新价",
    "change_pct": "涨跌幅",
    "change_amount": "涨跌额",
    "volume": "成交量",
    "amount": "成交额",
    "turnover_rate": "换手率",
    "pe_ratio": "市盈率-动态",
    "pb_ratio": "市净率",
    "high": "最高",
    "low": "最低",
    "open": "今开",
    "pre_close": "昨收",
}


def fetch_board_list(
    ak_func: Callable[..., Any],
    include_quote: bool = False,
    *,
    fetcher_label: str = "EastMoneyFetcher",
) -> list[dict[str, Any]]:
    """Fetch a board list from akshare (EastMoney backend)."""
    try:
        df = ak_func()
        result: list[dict[str, Any]] = []
        if df is None or df.empty:
            return result

        for _, row in df.iterrows():
            code = str(row.get("板块代码", "")).strip()
            name = str(row.get("板块名称", "")).strip()
            if not code:
                continue
            board: dict[str, Any] = {"code": code, "name": name}
            if include_quote:
                for out_key, src_col in _BOARD_LIST_QUOTE_COLS.items():
                    board[out_key] = row.get(src_col)
            result.append(board)
        return result

    except Exception:
        logger.warning(
            f"[{fetcher_label}] fetch_board_list failed", exc_info=True
        )
        return []


def fetch_board_stocks(
    ak_func: Callable[..., Any],
    board_code: str,
    include_quote: bool = False,
    *,
    fallback_enricher: Callable[[str], dict[str, Any] | None] | None = None,
    fetcher_label: str = "EastMoneyFetcher",
) -> list[dict[str, Any]]:
    """Fetch stocks belonging to a concept or industry board (EastMoney)."""
    try:
        df = ak_func(symbol=board_code)
        result: list[dict[str, Any]] = []
        if df is None or df.empty:
            return result

        for _, row in df.iterrows():
            code = str(row.get("代码", "")).strip()
            name = str(row.get("名称", "")).strip()
            if not code:
                continue
            stock: dict[str, Any] = {"stock_code": code, "stock_name": name}
            if include_quote:
                for out_key, src_col in _BOARD_STOCK_QUOTE_COLS.items():
                    stock[out_key] = row.get(src_col)
            result.append(stock)
        return result

    except Exception:
        logger.warning(
            f"[{fetcher_label}] fetch_board_stocks({board_code}) failed",
            exc_info=True,
        )
        if not include_quote or fallback_enricher is None:
            return []

        try:
            stocks = fetch_board_stocks(
                ak_func,
                board_code,
                include_quote=False,
                fetcher_label=fetcher_label,
            )
        except Exception:
            return []

        for stock in stocks:
            enriched = fallback_enricher(stock["stock_code"])
            if enriched:
                stock.update(enriched)
        return stocks