"""
Board (concept/industry) helpers for AkshareFetcher.

Internal implementation detail — not part of the public fetcher API.
Extracts the duplicated pattern across get_all_concept_boards,
get_all_industry_boards, get_concept_board_stocks, and
get_industry_board_stocks into parameterised functions.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

logger = logging.getLogger(__name__)

# Column-name mappings for akshare EM board APIs.
# Both concept and industry boards use identical column names in the
# akshare EM responses; the only difference is which API function is
# called (stock_board_concept_name_em vs stock_board_industry_name_em).

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
    fetcher_label: str = "AkshareFetcher",
) -> list[dict[str, Any]]:
    """Fetch a board list from akshare.

    Args:
        ak_func: Zero-arg akshare callable (e.g.
            ``ak.stock_board_concept_name_em`` or
            ``ak.stock_board_industry_name_em``).
        include_quote: If True, attach realtime price/change/volume fields.
        fetcher_label: Tag for log messages.

    Returns:
        List of board dicts: ``[{code, name, ...quote_fields}]``.
    """
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
    fetcher_label: str = "AkshareFetcher",
) -> list[dict[str, Any]]:
    """Fetch stocks belonging to a concept or industry board.

    Args:
        ak_func: Callable accepting ``symbol=board_code`` (e.g.
            ``ak.stock_board_concept_cons_em`` or
            ``ak.stock_board_industry_cons_em``).
        board_code: Board code like ``"BK1048"``.
        include_quote: If True, attach realtime fields from the API row.
            When the direct API call fails and ``include_quote`` is True,
            falls back to fetching without quote data and enriching each
            stock via ``fallback_enricher(code)``.
        fallback_enricher: Called per-stock when the direct quote fetch
            fails and ``include_quote=True``. Receives the stock code,
            returns a dict of fields to merge (or None).
        fetcher_label: Tag for log messages.

    Returns:
        List of stock dicts: ``[{stock_code, stock_name, ...}]``.
    """
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

        # Fallback: fetch without quote, then enrich per-stock
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
