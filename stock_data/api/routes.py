"""
API routes for stock data server.
"""

import logging
from datetime import datetime

from fastapi import APIRouter, HTTPException, Path, Query

from ..data_provider import DataFetcherManager
from ..data_provider.cache import api_cache as stock_cache
from ..data_provider.fetchers.akshare_fetcher import AkshareFetcher
from ..data_provider.fetchers.baostock_fetcher import BaostockFetcher
from ..data_provider.fetchers.tushare_fetcher import TushareFetcher
from ..data_provider.fetchers.yfinance_fetcher import YfinanceFetcher
from ..data_provider.fetchers.zhitu_fetcher import ZhituFetcher
from ..data_provider.utils.normalize import is_hk_market, is_us_market, normalize_stock_code
from ..data_provider.index_symbols import get_all_indices
from .cache import (
    get_history_cache,
    get_quote_cache,
    is_cache_enabled,
    make_history_cache_key,
    make_quote_cache_key,
)
from .schemas import (
    ErrorResponse,
    HealthResponse,
    IndexInfo,
    IntradayData,
    IntradayResponse,
    KLineData,
    StockHistoryResponse,
    StockInfo,
    StockQuote,
    TradeCalendarResponse,
)

logger = logging.getLogger(__name__)

router = APIRouter()

# Global manager instance
_manager: DataFetcherManager | None = None


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

        zhitu = ZhituFetcher()
        if zhitu.is_available():
            _manager.add_fetcher(zhitu)
            logger.info("ZhituFetcher added")
        else:
            logger.info("ZhituFetcher skipped (ZHITU_TOKEN not configured)")

    return _manager


def reset_manager() -> None:
    """Reset the global manager, forcing re-initialization on next get_manager()."""
    global _manager
    _manager = None
    logger.info("Manager reset")


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
def get_quote(stock_code: str = Path(max_length=20, description="Stock code")) -> StockQuote:
    """
    Get realtime quote for a stock.

    Args:
        stock_code: Stock code (e.g., 600519, AAPL, HK00700)
    """
    try:
        # Cache check
        if is_cache_enabled():
            cache = get_quote_cache()
            key = make_quote_cache_key(stock_code)
            if key in cache:
                logger.info(f"[APICache] quote hit: {stock_code}")
                return cache[key]

        manager = get_manager()
        quote = manager.get_realtime_quote(stock_code)

        if quote is None:
            raise HTTPException(
                status_code=404,
                detail={"error": "not_found", "message": f"Quote not available for {stock_code}"},
            )

        result = StockQuote(
            code=quote.code,
            stock_name=quote.name or stock_cache.get_stock_name(stock_code, manager=manager),
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

        # Cache the result
        if is_cache_enabled():
            cache[key] = result

        return result

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Quote error: {e}", exc_info=True)
        raise HTTPException(
            status_code=500, detail={"error": "internal_error", "message": str(e)}
        ) from e


@router.get(
    "/stocks/{stock_code}/history",
    response_model=StockHistoryResponse,
    responses={
        500: {"model": ErrorResponse, "description": "Server error"},
    },
    tags=["stocks"],
)
def get_history(
    stock_code: str = Path(max_length=20, description="Stock code"),
    period: str = Query(
        default="daily", pattern="^(daily|weekly|monthly)$", description="K-line period"
    ),
    days: int = Query(default=30, ge=1, le=365, description="Number of days"),
    start_date: str | None = Query(
        default=None, description="Start date (YYYY-MM-DD), overrides days"
    ),
    end_date: str | None = Query(
        default=None, description="End date (YYYY-MM-DD), defaults to today"
    ),
    adjust: str = Query(
        default="",
        pattern="^(qfq|hfq)?$",
        description="Adjustment type: empty=不复权, qfq=前复权, hfq=后复权",
    ),
) -> StockHistoryResponse:
    """
    Get historical K-line data for a stock or index.

    Args:
        stock_code: Stock or index code
        period: K-line period (daily/weekly/monthly)
        days: Number of days when start_date not provided
        start_date: Start date (YYYY-MM-DD), overrides days parameter
        end_date: End date (YYYY-MM-DD), defaults to today
        adjust: Adjustment type - empty=不复权, qfq=前复权, hfq=后复权
    """
    try:
        period_map = {"daily": "d", "weekly": "w", "monthly": "m"}
        frequency = period_map.get(period, "d")

        # adjust is passed as-is to manager, which maps it per-provider
        adj_value = adjust or None

        # Cache key includes all params including adjust
        if is_cache_enabled():
            cache = get_history_cache(frequency)
            key = make_history_cache_key(
                stock_code, frequency, days, start_date, end_date, adj_value
            )
            if key in cache:
                logger.info(f"[APICache] history hit: {key}")
                return cache[key]

        manager = get_manager()

        df, source = manager.get_kline_data(
            stock_code,
            start_date=start_date,
            end_date=end_date,
            days=days,
            frequency=frequency,
            adjust=adj_value,
        )

        stock_name = stock_cache.get_stock_name(stock_code, manager=manager)

        # Convert to response model
        def format_date(val):
            if val is None:
                return ""
            if hasattr(val, "strftime"):
                return val.strftime("%Y-%m-%d")
            return str(val)

        records = df.to_dict("records")
        data = [
            KLineData(
                date=format_date(row.get("date")),
                open=float(row.get("open", 0)),
                high=float(row.get("high", 0)),
                low=float(row.get("low", 0)),
                close=float(row.get("close", 0)),
                volume=int(row.get("volume", 0)),
                amount=float(row.get("amount")) if row.get("amount") is not None else None,
                change_percent=float(row.get("pct_chg"))
                if row.get("pct_chg") is not None
                else None,
                ma5=float(row.get("ma5")) if row.get("ma5") is not None else None,
                ma10=float(row.get("ma10")) if row.get("ma10") is not None else None,
                ma20=float(row.get("ma20")) if row.get("ma20") is not None else None,
            )
            for row in records
        ]

        result = StockHistoryResponse(
            code=stock_code, stock_name=stock_name, period=period, data=data
        )

        # Cache the result
        if is_cache_enabled():
            cache[key] = result

        return result

    except Exception as e:
        logger.error(f"History error: {e}", exc_info=True)
        raise HTTPException(
            status_code=500, detail={"error": "internal_error", "message": str(e)}
        ) from e


@router.get(
    "/stocks/{stock_code}/intraday",
    response_model=IntradayResponse,
    responses={
        400: {"model": ErrorResponse, "description": "Invalid period or unsupported market"},
        500: {"model": ErrorResponse, "description": "Server error"},
    },
    tags=["stocks"],
)
def get_intraday(
    stock_code: str = Path(max_length=20, description="Stock code"),
    period: str = Query(
        default="5",
        pattern="^(1|5|15|30|60)$",
        description="Minute period: 1, 5, 15, 30, 60",
    ),
    adjust: str = Query(
        default="",
        pattern="^(qfq|hfq)?$",
        description="Adjustment type: empty=不复权, qfq=前复权, hfq=后复权",
    ),
) -> IntradayResponse:
    """
    Get intraday minute-level data for a stock.

    Args:
        stock_code: Stock code (e.g., 600519, 000001)
        period: Minute period - 1, 5, 15, 30, 60
        adjust: Adjustment type - empty=不复权, qfq=前复权, hfq=后复权

    Note:
        - period=1 is only supported by Akshare (Zhitu does not support 1-minute data)
        - Intraday data is only available for A-share stocks
    """
    try:
        # Only A-share supported for intraday
        code = normalize_stock_code(stock_code)
        if is_us_market(code) or is_hk_market(code):
            raise HTTPException(
                status_code=400,
                detail={
                    "error": "unsupported_market",
                    "message": "Intraday data is only available for A-share stocks",
                },
            )

        manager = get_manager()
        df, source = manager.get_intraday_data(stock_code, period=period, adjust=adjust)
        stock_name = stock_cache.get_stock_name(stock_code, manager=manager)

        # Determine trade date from data
        trade_date = ""
        if "time" in df.columns and len(df) > 0:
            first_time = str(df.iloc[0].get("time", ""))
            if len(first_time) >= 10:
                trade_date = first_time[:10]

        records = df.to_dict("records")
        data = [
            IntradayData(
                time=str(row.get("time", "")),
                open=float(row.get("open", 0)),
                high=float(row.get("high", 0)),
                low=float(row.get("low", 0)),
                close=float(row.get("close", 0)),
                volume=int(row.get("volume", 0)),
                amount=float(row.get("amount")) if row.get("amount") is not None else None,
            )
            for row in records
        ]

        period_label = f"{period}m"
        return IntradayResponse(
            code=stock_code,
            stock_name=stock_name,
            period=period_label,
            adjust=adjust,
            date=trade_date,
            data=data,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Intraday error: {e}", exc_info=True)
        raise HTTPException(
            status_code=500, detail={"error": "internal_error", "message": str(e)}
        ) from e


@router.get(
    "/indices",
    response_model=list[IndexInfo],
    tags=["indices"],
)
def list_indices() -> list[IndexInfo]:
    """
    List all available indices with code, name, and market type.

    Returns indices from CSI (A股), HK (港股), and US (美股) markets.
    """
    indices = get_all_indices()
    return [IndexInfo(code=i["code"], name=i["name"], market=i["market"]) for i in indices]


@router.get(
    "/stocks",
    response_model=list[StockInfo],
    responses={
        400: {"model": ErrorResponse, "description": "Invalid market parameter"},
    },
    tags=["stocks"],
)
def list_stocks(
    market: str = Query(..., pattern="^(csi|cn|hk|us)$", description="Market: csi/cn/hk/us"),
    refresh: bool = Query(False, description="Force fetch latest from upstream"),
    offset: int = Query(0, ge=0, description="Pagination offset"),
    limit: int = Query(100, ge=1, le=1000, description="Pagination limit"),
) -> list[StockInfo]:
    """
    List all available stocks for a specified market.

    Args:
        market: Market type - csi (A股), hk (港股), us (美股)
        refresh: If True, fetch latest from upstream and update cache.
        offset: Pagination offset (default 0).
        limit: Pagination limit (default 100, max 1000).

    Returns:
        List of stock codes and names for the specified market.
    """
    if market == "cn":
        market = "csi"  # Backward compat

    # Get stock list with automatic refresh (cache layer handles daily refresh logic)
    manager = get_manager()
    stocks = stock_cache.get_stock_list(market, refresh=refresh, manager=manager)
    logger.info(
        f"[list_stocks] Returned {len(stocks)} stocks for market={market}"
    )
    page = stocks[offset : offset + limit]
    return [StockInfo(code=s["code"], name=s["name"], market=market) for s in page]


@router.get(
    "/calendar",
    response_model=TradeCalendarResponse,
    responses={
        500: {"model": ErrorResponse, "description": "Server error"},
    },
    tags=["calendar"],
)
def get_trade_calendar(
    refresh: bool = Query(False, description="Force fetch latest from upstream"),
) -> TradeCalendarResponse:
    """
    Get A-share trade calendar.

    Returns all available trade dates sorted ascending. Data is cached in SQLite
    and refreshed from upstream when:
    - refresh=True is requested
    - Cache is empty
    - Cached latest date is before today (data may be stale)

    Uses akshare tool_trade_date_hist_sina API.
    """
    from ..data_provider.cache.api_cache import (
        get_cached_calendar,
        get_latest_cached_trade_date,
    )

    today = datetime.now().strftime("%Y-%m-%d")

    # Check if refresh is needed
    should_refresh = refresh
    if not should_refresh:
        cached_dates = get_cached_calendar()
        if not cached_dates:
            should_refresh = True
        else:
            latest_cached = get_latest_cached_trade_date()
            if latest_cached is None or latest_cached < today:
                should_refresh = True

    if should_refresh:
        logger.info(f"[calendar] Fetching fresh data from upstream, refresh={refresh}")
        try:
            manager = get_manager()
            dates = manager.get_trade_calendar()
            if dates:
                logger.info(f"[calendar] Updated {len(dates)} dates from manager")
        except Exception as e:
            logger.error(f"[calendar] Manager calendar failed: {e}")
            cached_dates = get_cached_calendar()
            if not cached_dates:
                raise HTTPException(
                    status_code=500,
                    detail={"error": "fetch_failed", "message": str(e)},
                ) from e
            # Fall through to use cached data

    # Get dates from cache
    dates = get_cached_calendar()
    latest = get_latest_cached_trade_date() if dates else None

    return TradeCalendarResponse(trade_dates=dates, latest_date=latest, total=len(dates))