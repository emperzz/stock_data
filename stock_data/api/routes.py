# -*- coding: utf-8 -*-
"""
API routes for stock data server.
"""

import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, Query

from .schemas import (
    ErrorResponse,
    HealthResponse,
    KLineData,
    StockHistoryResponse,
    StockQuote,
)
from ..data_provider import DataFetcherManager
from ..data_provider.tushare_fetcher import TushareFetcher
from ..data_provider.baostock_fetcher import BaostockFetcher
from ..data_provider.akshare_fetcher import AkshareFetcher
from ..data_provider.yfinance_fetcher import YfinanceFetcher

logger = logging.getLogger(__name__)

router = APIRouter()

# Global manager instance
_manager: Optional[DataFetcherManager] = None


def get_manager() -> DataFetcherManager:
    """Get or create the global DataFetcherManager."""
    global _manager
    if _manager is None:
        _manager = DataFetcherManager()
        # Add fetchers in priority order
        tushare = TushareFetcher()
        if tushare.is_available():
            _manager.add_fetcher(tushare)
            logger.info("TushareFetcher added")
        else:
            logger.info("TushareFetcher skipped (not configured)")

        baostock = BaostockFetcher()
        if baostock.is_available():
            _manager.add_fetcher(baostock)
            logger.info("BaostockFetcher added")
        else:
            logger.info("BaostockFetcher skipped (not configured)")

        akshare = AkshareFetcher()
        _manager.add_fetcher(akshare)
        logger.info("AkshareFetcher added")

        yfinance = YfinanceFetcher()
        if yfinance.is_available():
            _manager.add_fetcher(yfinance)
            logger.info("YfinanceFetcher added")
        else:
            logger.info("YfinanceFetcher skipped (yfinance not installed)")

    return _manager


@router.get(
    "/health",
    response_model=HealthResponse,
    tags=["health"],
)
def health_check() -> HealthResponse:
    """Health check endpoint."""
    manager = get_manager()
    return HealthResponse(status="ok", available_sources=manager.available_fetchers)


@router.get(
    "/stocks/{stock_code}/quote",
    response_model=StockQuote,
    responses={
        404: {"model": ErrorResponse, "description": "Stock not found"},
        500: {"model": ErrorResponse, "description": "Server error"},
    },
    tags=["stocks"],
)
def get_quote(stock_code: str) -> StockQuote:
    """
    Get realtime quote for a stock.

    Args:
        stock_code: Stock code (e.g., 600519, AAPL, HK00700)
    """
    try:
        manager = get_manager()
        quote = manager.get_realtime_quote(stock_code)

        if quote is None:
            raise HTTPException(
                status_code=404,
                detail={"error": "not_found", "message": f"Quote not available for {stock_code}"},
            )

        return StockQuote(
            stock_code=quote.code,
            stock_name=quote.name,
            source=quote.source.value,
            current_price=quote.price or 0.0,
            change=quote.change_amount,
            change_percent=quote.change_pct,
            open=quote.open_price,
            high=quote.high,
            low=quote.low,
            prev_close=quote.pre_close,
            volume=quote.volume,
            amount=quote.amount,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Quote error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail={"error": "internal_error", "message": str(e)})


@router.get(
    "/stocks/{stock_code}/history",
    response_model=StockHistoryResponse,
    responses={
        500: {"model": ErrorResponse, "description": "Server error"},
    },
    tags=["stocks"],
)
def get_history(
    stock_code: str,
    period: str = Query(
        default="daily", pattern="^(daily|weekly|monthly)$", description="K-line period"
    ),
    days: int = Query(default=30, ge=1, le=365, description="Number of days"),
) -> StockHistoryResponse:
    """
    Get historical K-line data for a stock.

    Args:
        stock_code: Stock code
        period: K-line period (daily/weekly/monthly)
        days: Number of days to retrieve
    """
    try:
        manager = get_manager()

        # Map period to frequency
        period_map = {"daily": "d", "weekly": "w", "monthly": "m"}
        frequency = period_map.get(period, "d")

        df, source = manager.get_daily_data(stock_code, days=days, frequency=frequency)

        # Get stock name if available
        stock_name = ""
        for fetcher in manager._fetchers:
            if hasattr(fetcher, "get_stock_name"):
                try:
                    name = fetcher.get_stock_name(stock_code)
                    if name:
                        stock_name = name
                        break
                except Exception:
                    pass

        # Convert to response model
        data = []
        for _, row in df.iterrows():
            kline = KLineData(
                date=row.get("date", "").strftime("%Y-%m-%d")
                if hasattr(row.get("date"), "strftime")
                else str(row.get("date", "")),
                open=float(row.get("open", 0)),
                high=float(row.get("high", 0)),
                low=float(row.get("low", 0)),
                close=float(row.get("close", 0)),
                volume=int(row.get("volume", 0)),
                amount=float(row.get("amount", 0)) if row.get("amount") is not None else None,
                change_percent=float(row.get("pct_chg", 0))
                if row.get("pct_chg") is not None
                else None,
                ma5=float(row.get("ma5")) if row.get("ma5") is not None else None,
                ma10=float(row.get("ma10")) if row.get("ma10") is not None else None,
                ma20=float(row.get("ma20")) if row.get("ma20") is not None else None,
            )
            data.append(kline)

        return StockHistoryResponse(
            stock_code=stock_code, stock_name=stock_name, period=period, data=data
        )

    except Exception as e:
        logger.error(f"History error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail={"error": "internal_error", "message": str(e)})
