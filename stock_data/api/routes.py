"""
API routes for stock data server.
"""

import logging
from datetime import datetime

from fastapi import APIRouter, HTTPException, Path, Query

from ..data_provider import (
    AkshareFetcher,
    BaostockFetcher,
    CninfoFetcher,
    DataFetcherManager,
    DataFetchError,
    EastMoneyFetcher,
    TencentFetcher,
    ThsFetcher,
    TushareFetcher,
    YfinanceFetcher,
    ZhituFetcher,
)
from ..data_provider.cache import api_cache as stock_cache
from ..data_provider.cache import stock_board_cache
from ..data_provider.fetchers.index_symbols import get_all_indices
from ..data_provider.utils.normalize import (
    is_hk_market,
    is_index_code,
    is_us_market,
    normalize_stock_code,
)
from .cache import (
    get_announcements_cache,
    get_block_trade_cache,
    get_board_list_cache,
    get_board_stocks_cache,
    get_dividend_cache,
    get_dragontiger_cache,
    get_fund_flow_cache,
    get_history_cache,
    get_holder_num_cache,
    get_hot_topics_cache,
    get_index_intraday_cache,
    get_index_quote_cache,
    get_margin_cache,
    get_north_flow_cache,
    get_pools_cache,
    get_quote_cache,
    get_reports_cache,
    get_stock_intraday_cache,
    is_cache_enabled,
    make_announcements_cache_key,
    make_block_trade_cache_key,
    make_board_cache_key,
    make_board_stocks_cache_key,
    make_daily_dragon_tiger_cache_key,
    make_dividend_cache_key,
    make_dragon_tiger_cache_key,
    make_fund_flow_cache_key,
    make_fund_flow_daily_cache_key,
    make_history_cache_key,
    make_holder_num_cache_key,
    make_hot_topics_cache_key,
    make_index_history_cache_key,
    make_index_intraday_cache_key,
    make_index_quote_cache_key,
    make_margin_cache_key,
    make_north_flow_cache_key,
    make_pools_cache_key,
    make_quote_cache_key,
    make_reports_cache_key,
    make_stock_intraday_cache_key,
)
from .schemas import (
    AnnouncementRecord,
    AnnouncementResponse,
    BlockTradeRecord,
    BlockTradeResponse,
    BoardInfo,
    BoardListResponse,
    BoardStockInfo,
    BoardStocksResponse,
    DailyDragonTigerResponse,
    DailyDragonTigerStock,
    DividendRecord,
    DividendResponse,
    DragonTigerInstitution,
    DragonTigerRecord,
    DragonTigerResponse,
    DragonTigerSeat,
    ErrorResponse,
    FundFlowDailyRecord,
    FundFlowMinuteRecord,
    FundFlowResponse,
    HealthResponse,
    HolderNumRecord,
    HolderNumResponse,
    HotTopicRecord,
    HotTopicResponse,
    IndexHistoryResponse,
    IndexInfo,
    IndexIntradayResponse,
    IndexQuote,
    IntradayData,
    IntradayResponse,
    KLineData,
    MarginTradingRecord,
    MarginTradingResponse,
    NorthFlowRecord,
    NorthFlowResponse,
    ReportPDFResponse,
    ReportRecord,
    ReportResponse,
    StockHistoryResponse,
    StockInfo,
    StockQuote,
    TradeCalendarResponse,
    ZTPoolResponse,
    ZTPoolStock,
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

        tencent = TencentFetcher()
        if tencent.is_available():
            _manager.add_fetcher(tencent)
            logger.info("TencentFetcher added")
        else:
            logger.info("TencentFetcher skipped")

        eastmoney = EastMoneyFetcher()
        if eastmoney.is_available():
            _manager.add_fetcher(eastmoney)
            logger.info("EastMoneyFetcher added")
        else:
            logger.info("EastMoneyFetcher skipped")

        ths = ThsFetcher()
        if ths.is_available():
            _manager.add_fetcher(ths)
            logger.info("ThsFetcher added")
        else:
            logger.info("ThsFetcher skipped")

        cninfo = CninfoFetcher()
        if cninfo.is_available():
            _manager.add_fetcher(cninfo)
            logger.info("CninfoFetcher added")
        else:
            logger.info("CninfoFetcher skipped")

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

    Note:
        Index codes are not supported. Use /indices/{index_code}/quote instead.
    """
    try:
        # Reject index codes
        if is_index_code(stock_code):
            raise HTTPException(
                status_code=400,
                detail={
                    "error": "invalid_request",
                    "message": f"Index {stock_code} is not supported via this endpoint. Use /indices/{stock_code}/quote instead.",
                },
            )

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
            # Enhanced fields from Tencent财经
            pe_ttm=quote.pe_ratio,
            pe_static=None,  # Tencent API doesn't expose this in current parsing
            pb=quote.pb_ratio,
            mcap_yi=quote.total_mv / 1e8 if quote.total_mv else None,
            float_mcap_yi=quote.circ_mv / 1e8 if quote.circ_mv else None,
            turnover_pct=quote.turnover_rate,
            amplitude_pct=quote.amplitude,
            limit_up=None,  # Not yet parsed from Tencent response
            limit_down=None,  # Not yet parsed from Tencent response
            vol_ratio=quote.volume_ratio,
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
    Get historical K-line data for a stock.

    Args:
        stock_code: Stock code
        period: K-line period (daily/weekly/monthly)
        days: Number of days when start_date not provided
        start_date: Start date (YYYY-MM-DD), overrides days parameter
        end_date: End date (YYYY-MM-DD), defaults to today
        adjust: Adjustment type - empty=不复权, qfq=前复权, hfq=后复权

    Note:
        Index codes are not supported. Use /indices/{index_code}/history instead.
    """
    try:
        if is_index_code(stock_code):
            raise HTTPException(
                status_code=400,
                detail={
                    "error": "invalid_request",
                    "message": f"Index {stock_code} is not supported via this endpoint. Use /indices/{stock_code}/history instead.",
                },
            )

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

    except DataFetchError as e:
        logger.warning(f"History data unavailable: {e}")
        raise HTTPException(
            status_code=503,
            detail={
                "error": "data_unavailable",
                "message": f"History data not currently available: {e}",
            },
        ) from e
    except HTTPException:
        raise
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
        # Only A-share stocks supported for intraday (indices not allowed)
        code = normalize_stock_code(stock_code)
        if is_us_market(code) or is_hk_market(code) or is_index_code(code):
            raise HTTPException(
                status_code=400,
                detail={
                    "error": "unsupported_market",
                    "message": "Intraday data is only available for A-share stocks. Use /indices/{index_code}/intraday for indices.",
                },
            )

        if is_cache_enabled():
            cache = get_stock_intraday_cache()
            key = make_stock_intraday_cache_key(stock_code, period, adjust)
            if key in cache:
                logger.info(f"[APICache] stock_intraday hit: {key}")
                return cache[key]

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
        result = IntradayResponse(
            code=stock_code,
            stock_name=stock_name,
            period=period_label,
            adjust=adjust,
            date=trade_date,
            data=data,
        )

        if is_cache_enabled():
            cache[key] = result

        return result

    except DataFetchError as e:
        logger.warning(f"Intraday data unavailable: {e}")
        raise HTTPException(
            status_code=503,
            detail={
                "error": "data_unavailable",
                "message": f"Intraday data not currently available: {e}",
            },
        ) from e
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
    "/indices/{index_code}/quote",
    response_model=IndexQuote,
    responses={
        400: {"model": ErrorResponse, "description": "Invalid index code"},
        404: {"model": ErrorResponse, "description": "Index not found"},
        500: {"model": ErrorResponse, "description": "Server error"},
    },
    tags=["indices"],
)
def get_index_quote(index_code: str = Path(max_length=20, description="Index code")) -> IndexQuote:
    """
    Get realtime quote for an index.

    Args:
        index_code: Index code (e.g., 000300, 399006, HSI, SPX)
    """
    try:
        if is_cache_enabled():
            cache = get_index_quote_cache()
            key = make_index_quote_cache_key(index_code)
            if key in cache:
                logger.info(f"[APICache] index_quote hit: {index_code}")
                return cache[key]

        manager = get_manager()
        quote = manager.get_index_realtime_quote(index_code)

        if quote is None:
            raise HTTPException(
                status_code=404,
                detail={"error": "not_found", "message": f"Quote not available for {index_code}"},
            )

        result = IndexQuote(
            code=quote.code,
            name=quote.name or "",
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

        if is_cache_enabled():
            cache[key] = result

        return result

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Index quote error: {e}", exc_info=True)
        raise HTTPException(
            status_code=500, detail={"error": "internal_error", "message": str(e)}
        ) from e


@router.get(
    "/indices/{index_code}/history",
    response_model=IndexHistoryResponse,
    responses={
        400: {"model": ErrorResponse, "description": "Invalid index code"},
        500: {"model": ErrorResponse, "description": "Server error"},
    },
    tags=["indices"],
)
def get_index_history(
    index_code: str = Path(max_length=20, description="Index code"),
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
) -> IndexHistoryResponse:
    """
    Get historical K-line data for an index.

    Args:
        index_code: Index code (e.g., 000300, 399006)
        period: K-line period (daily/weekly/monthly)
        days: Number of days when start_date not provided
        start_date: Start date (YYYY-MM-DD), overrides days parameter
        end_date: End date (YYYY-MM-DD), defaults to today
    """
    try:
        period_map = {"daily": "d", "weekly": "w", "monthly": "m"}
        frequency = period_map.get(period, "d")

        if is_cache_enabled():
            cache = get_history_cache(frequency)
            key = make_index_history_cache_key(index_code, frequency, days, start_date, end_date)
            if key in cache:
                logger.info(f"[APICache] index_history hit: {key}")
                return cache[key]

        manager = get_manager()
        df, source = manager.get_index_historical(
            index_code,
            start_date=start_date,
            end_date=end_date,
            days=days,
            frequency=frequency,
        )

        # Get index name from index list
        all_indices = get_all_indices()
        index_name = next((i["name"] for i in all_indices if i["code"] == index_code), index_code)

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

        result = IndexHistoryResponse(code=index_code, name=index_name, period=period, data=data)

        if is_cache_enabled():
            cache[key] = result

        return result

    except DataFetchError as e:
        logger.warning(f"Index history data unavailable: {e}")
        raise HTTPException(
            status_code=503,
            detail={
                "error": "data_unavailable",
                "message": f"Index history data not currently available: {e}",
            },
        ) from e
    except Exception as e:
        logger.error(f"Index history error: {e}", exc_info=True)
        raise HTTPException(
            status_code=500, detail={"error": "internal_error", "message": str(e)}
        ) from e


@router.get(
    "/indices/{index_code}/intraday",
    response_model=IndexIntradayResponse,
    responses={
        400: {"model": ErrorResponse, "description": "Invalid period or unsupported"},
        500: {"model": ErrorResponse, "description": "Server error"},
    },
    tags=["indices"],
)
def get_index_intraday(
    index_code: str = Path(max_length=20, description="Index code"),
    period: str = Query(
        default="5",
        pattern="^(1|5|15|30|60)$",
        description="Minute period: 1, 5, 15, 30, 60",
    ),
) -> IndexIntradayResponse:
    """
    Get intraday minute-level data for an index.

    Args:
        index_code: Index code (e.g., 000300, 399006)
        period: Minute period - 1, 5, 15, 30, 60
    """
    try:
        if is_cache_enabled():
            cache = get_index_intraday_cache()
            key = make_index_intraday_cache_key(index_code, period)
            if key in cache:
                logger.info(f"[APICache] index_intraday hit: {key}")
                return cache[key]

        manager = get_manager()
        df, source = manager.get_index_intraday(index_code, period=period)

        # Get index name
        all_indices = get_all_indices()
        index_name = next((i["name"] for i in all_indices if i["code"] == index_code), index_code)

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
        result = IndexIntradayResponse(
            code=index_code,
            name=index_name,
            period=period_label,
            date=trade_date,
            data=data,
        )

        if is_cache_enabled():
            cache[key] = result

        return result

    except DataFetchError as e:
        logger.warning(f"Index intraday data unavailable: {e}")
        raise HTTPException(
            status_code=503,
            detail={
                "error": "data_unavailable",
                "message": f"Intraday data not currently available for {index_code}: {e}",
            },
        ) from e
    except Exception as e:
        logger.error(f"Index intraday error: {e}", exc_info=True)
        raise HTTPException(
            status_code=500, detail={"error": "internal_error", "message": str(e)}
        ) from e


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
    logger.info(f"[list_stocks] Returned {len(stocks)} stocks for market={market}")
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


@router.get(
    "/boards",
    response_model=BoardListResponse,
    responses={
        400: {"model": ErrorResponse, "description": "Invalid board type"},
        500: {"model": ErrorResponse, "description": "Server error"},
    },
    tags=["boards"],
)
def list_boards(
    type: str = Query(
        ...,
        pattern="^(concept|industry)$",
        description="Board type: concept or industry",
    ),
    source: str = Query(default="eastmoney", description="Data source"),
    include_quote: bool = Query(False, description="Include realtime quote data"),
    refresh: bool = Query(False, description="Force fetch latest from upstream"),
) -> BoardListResponse:
    """
    Get list of concept or industry boards.

    Args:
        type: Board type - "concept" (概念板块) or "industry" (行业板块)
        source: Data source (default: "eastmoney")
        include_quote: If True, include realtime price/change/market data for each board
        refresh: If True, force refresh from upstream and update cache

    Returns:
        Board list with code and name, optionally with realtime data
    """
    try:
        if is_cache_enabled():
            cache = get_board_list_cache()
            key = make_board_cache_key(type, source)
            if not refresh and not include_quote and key in cache:
                logger.info(f"[APICache] board list hit: {key}")
                return cache[key]

        manager = get_manager()
        boards = stock_board_cache.get_board_list(
            type, source, refresh=refresh, include_quote=include_quote, manager=manager
        )

        result = BoardListResponse(
            data=[
                BoardInfo(
                    code=b["code"],
                    name=b["name"],
                    price=b.get("price"),
                    change_pct=b.get("change_pct"),
                    change_amount=b.get("change_amount"),
                    volume=b.get("volume"),
                    amount=b.get("amount"),
                    turnover_rate=b.get("turnover_rate"),
                    total_mv=b.get("total_mv"),
                    up_count=b.get("up_count"),
                    down_count=b.get("down_count"),
                    leading_stock=b.get("leading_stock"),
                    leading_stock_pct=b.get("leading_stock_pct"),
                )
                for b in boards
            ]
        )

        if is_cache_enabled():
            cache[key] = result

        return result

    except Exception as e:
        logger.error(f"Boards error: {e}", exc_info=True)
        raise HTTPException(
            status_code=500, detail={"error": "internal_error", "message": str(e)}
        ) from e


@router.get(
    "/boards/{board_code}/stocks",
    response_model=BoardStocksResponse,
    responses={
        404: {"model": ErrorResponse, "description": "Board not found"},
        500: {"model": ErrorResponse, "description": "Server error"},
    },
    tags=["boards"],
)
def get_board_stocks(
    board_code: str = Path(max_length=20, description="Board code (e.g., BK1048)"),
    source: str = Query(default="eastmoney", description="Data source"),
    include_quote: bool = Query(False, description="Include realtime quote data"),
    refresh: bool = Query(False, description="Force fetch latest from upstream"),
) -> BoardStocksResponse:
    """
    Get stocks belonging to a board.

    Args:
        board_code: Board code (e.g., BK1048)
        source: Data source (default: "eastmoney")
        include_quote: If True, include realtime price/change data for each stock
        refresh: If True, force refresh from upstream and update cache

    Returns:
        Board info and list of stocks, optionally with quote data
    """
    try:
        if is_cache_enabled():
            cache = get_board_stocks_cache()
            key = make_board_stocks_cache_key(board_code, source, include_quote)
            if not refresh and not include_quote and key in cache:
                logger.info(f"[APICache] board stocks hit: {key}")
                return cache[key]

        manager = get_manager()
        stocks = stock_board_cache.get_board_stocks(
            board_code, source, refresh=refresh, include_quote=include_quote, manager=manager
        )

        if not stocks:
            raise HTTPException(
                status_code=404,
                detail={"error": "not_found", "message": f"No stocks found for board {board_code}"},
            )

        # Get board name — try both types since "BK" prefix is shared
        board_name = board_code
        for bt in ("concept", "industry"):
            boards = stock_board_cache.get_board_list(bt, source, refresh=False, manager=manager)
            match = next((b["name"] for b in boards if b["code"] == board_code), None)
            if match:
                board_name = match
                break

        # Build stock list
        stock_list = [
            BoardStockInfo(
                code=s.get("stock_code", ""),
                name=s.get("stock_name", ""),
                price=s.get("price"),
                change_pct=s.get("change_pct"),
                volume=s.get("volume"),
            )
            for s in stocks
        ]

        result = BoardStocksResponse(
            board=BoardInfo(code=board_code, name=board_name),
            stocks=stock_list,
            source=source,
        )

        if is_cache_enabled():
            cache[key] = result

        return result

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Board stocks error: {e}", exc_info=True)
        raise HTTPException(
            status_code=500, detail={"error": "internal_error", "message": str(e)}
        ) from e


@router.get(
    "/pools",
    response_model=ZTPoolResponse,
    responses={
        400: {"model": ErrorResponse, "description": "Invalid pool type"},
        404: {"model": ErrorResponse, "description": "No data found for date"},
        500: {"model": ErrorResponse, "description": "Server error"},
    },
    tags=["pools"],
)
def get_pools(
    type: str = Query(
        ...,
        pattern="^(zt|dt|zbgc)$",
        description="Pool type: zt (涨停) / dt (跌停) / zbgc (炸板)",
    ),
    date: str | None = Query(
        None, description="Pool date (YYYY-MM-DD), defaults to latest cached or today"
    ),
    refresh: bool = Query(False, description="Force refresh from upstream"),
) -> ZTPoolResponse:
    """
    Get ZT (涨跌停) pool data for a specific type and date.

    Args:
        type: Pool type - zt (涨停), dt (跌停), zbgc (炸板)
        date: Pool date in YYYY-MM-DD format. If not provided, uses the latest
              cached date or today's date.
        refresh: If True, force refresh from upstream and update cache.

    Returns:
        ZTPoolResponse with list of stocks in the pool.
    """
    try:
        if is_cache_enabled():
            cache = get_pools_cache()
            key = make_pools_cache_key(type, date)
            if key in cache:
                logger.info(f"[APICache] pools hit: {key}")
                return cache[key]

        manager = get_manager()
        stocks = manager.get_zt_pool(pool_type=type, date=date, refresh=refresh)

        if not stocks:
            raise HTTPException(
                status_code=404,
                detail={"error": "not_found", "message": f"No {type} pool data found"},
            )

        # Derive actual date from query param or first stock record
        actual_date = date or stocks[0].get("pool_date", "")

        pool_stocks = [
            ZTPoolStock(
                code=s.get("code", ""),
                name=s.get("name", ""),
                price=s.get("price"),
                change_pct=s.get("change_pct"),
                amount=s.get("amount"),
                circ_mv=s.get("circ_mv"),
                total_mv=s.get("total_mv"),
                turnover_rate=s.get("turnover_rate"),
                lb_count=s.get("lb_count"),
                first_seal_time=s.get("first_seal_time"),
                last_seal_time=s.get("last_seal_time"),
                seal_amount=s.get("seal_amount"),
                seal_count=s.get("seal_count"),
                zt_count=s.get("zt_count"),
            )
            for s in stocks
        ]

        result = ZTPoolResponse(
            date=actual_date,
            type=type,
            total=len(pool_stocks),
            stocks=pool_stocks,
        )

        if is_cache_enabled():
            cache[key] = result

        return result

    except DataFetchError as e:
        logger.warning(f"ZT pool unavailable: {e}")
        raise HTTPException(
            status_code=503,
            detail={"error": "data_unavailable", "message": f"ZT pool data not available: {e}"},
        ) from e
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"ZT pool error: {e}", exc_info=True)
        raise HTTPException(
            status_code=500, detail={"error": "internal_error", "message": str(e)}
        ) from e


@router.get(
    "/stocks/{stock_code}/dragon-tiger",
    response_model=DragonTigerResponse,
    responses={
        503: {"model": ErrorResponse, "description": "Data unavailable"},
        500: {"model": ErrorResponse, "description": "Server error"},
    },
    tags=["stocks"],
)
def get_dragon_tiger(
    stock_code: str = Path(max_length=20),
    trade_date: str = Query(default="", description="Trade date (YYYY-MM-DD)"),
    look_back: int = Query(default=30, ge=1, le=365),
) -> DragonTigerResponse:
    try:
        if is_cache_enabled():
            cache = get_dragontiger_cache()
            key = make_dragon_tiger_cache_key(stock_code, trade_date, look_back)
            if key in cache:
                logger.info(f"[APICache] dragontiger hit: {key}")
                return cache[key]

        manager = get_manager()
        data = manager.get_dragon_tiger(stock_code, trade_date, look_back)
        stock_name = stock_cache.get_stock_name(stock_code, manager=manager)
        records = [DragonTigerRecord(**r) for r in data.get("records", [])]
        seats_data = data.get("seats", {})
        seats = {
            "buy": [DragonTigerSeat(**s) for s in seats_data.get("buy", [])],
            "sell": [DragonTigerSeat(**s) for s in seats_data.get("sell", [])],
        }
        result = DragonTigerResponse(
            code=stock_code,
            name=stock_name or "",
            records=records,
            seats=seats,
            institution=DragonTigerInstitution(**data.get("institution", {})),
        )
        if is_cache_enabled():
            cache[key] = result
        return result
    except DataFetchError as e:
        logger.warning(f"Dragon tiger data unavailable: {e}")
        raise HTTPException(
            status_code=503, detail={"error": "data_unavailable", "message": str(e)}
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500, detail={"error": "internal_error", "message": str(e)}
        ) from e


@router.get(
    "/dragon-tiger/daily",
    response_model=DailyDragonTigerResponse,
    responses={
        503: {"model": ErrorResponse, "description": "Data unavailable"},
        500: {"model": ErrorResponse, "description": "Server error"},
    },
    tags=["dragon-tiger"],
)
def get_daily_dragon_tiger(
    trade_date: str = Query(default="", description="Trade date (YYYY-MM-DD)"),
    min_net_buy: float | None = Query(default=None, description="Min net buy (万元)"),
) -> DailyDragonTigerResponse:
    try:
        if is_cache_enabled():
            cache = get_dragontiger_cache()
            key = make_daily_dragon_tiger_cache_key(trade_date, min_net_buy)
            if key in cache:
                logger.info(f"[APICache] daily_dragon_tiger hit: {key}")
                return cache[key]

        manager = get_manager()
        data = manager.get_daily_dragon_tiger(trade_date, min_net_buy)
        stocks = [DailyDragonTigerStock(**s) for s in data["stocks"]]
        result = DailyDragonTigerResponse(date=data["date"], total=data["total"], stocks=stocks)
        if is_cache_enabled():
            cache[key] = result
        return result
    except DataFetchError as e:
        logger.warning(f"Daily dragon tiger unavailable: {e}")
        raise HTTPException(
            status_code=503, detail={"error": "data_unavailable", "message": str(e)}
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500, detail={"error": "internal_error", "message": str(e)}
        ) from e


@router.get(
    "/stocks/{stock_code}/margin",
    response_model=MarginTradingResponse,
    responses={
        503: {"model": ErrorResponse, "description": "Data unavailable"},
        500: {"model": ErrorResponse, "description": "Server error"},
    },
    tags=["stocks"],
)
def get_margin(
    stock_code: str = Path(max_length=20),
    page_size: int = Query(default=30, ge=1, le=100),
) -> MarginTradingResponse:
    try:
        if is_cache_enabled():
            cache = get_margin_cache()
            key = make_margin_cache_key(stock_code, page_size)
            if key in cache:
                logger.info(f"[APICache] margin hit: {key}")
                return cache[key]

        manager = get_manager()
        data = manager.get_margin_trading(stock_code, page_size)
        stock_name = stock_cache.get_stock_name(stock_code, manager=manager)
        records = [MarginTradingRecord(**r) for r in data]
        result = MarginTradingResponse(code=stock_code, name=stock_name or "", records=records)
        if is_cache_enabled():
            cache[key] = result
        return result
    except DataFetchError as e:
        logger.warning(f"Margin trading unavailable: {e}")
        raise HTTPException(
            status_code=503, detail={"error": "data_unavailable", "message": str(e)}
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500, detail={"error": "internal_error", "message": str(e)}
        ) from e


@router.get(
    "/stocks/{stock_code}/block-trade",
    response_model=BlockTradeResponse,
    responses={
        503: {"model": ErrorResponse, "description": "Data unavailable"},
        500: {"model": ErrorResponse, "description": "Server error"},
    },
    tags=["stocks"],
)
def get_block_trade(
    stock_code: str = Path(max_length=20),
    page_size: int = Query(default=20, ge=1, le=100),
) -> BlockTradeResponse:
    try:
        if is_cache_enabled():
            cache = get_block_trade_cache()
            key = make_block_trade_cache_key(stock_code, page_size)
            if key in cache:
                logger.info(f"[APICache] block_trade hit: {key}")
                return cache[key]

        manager = get_manager()
        data = manager.get_block_trade(stock_code, page_size)
        stock_name = stock_cache.get_stock_name(stock_code, manager=manager)
        records = [BlockTradeRecord(**r) for r in data]
        result = BlockTradeResponse(
            code=stock_code, name=stock_name or "", records=records, total=len(records)
        )
        if is_cache_enabled():
            cache[key] = result
        return result
    except DataFetchError as e:
        logger.warning(f"Block trade unavailable: {e}")
        raise HTTPException(
            status_code=503, detail={"error": "data_unavailable", "message": str(e)}
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500, detail={"error": "internal_error", "message": str(e)}
        ) from e


@router.get(
    "/stocks/{stock_code}/holder-num",
    response_model=HolderNumResponse,
    responses={
        503: {"model": ErrorResponse, "description": "Data unavailable"},
        500: {"model": ErrorResponse, "description": "Server error"},
    },
    tags=["stocks"],
)
def get_holder_num(
    stock_code: str = Path(max_length=20),
    page_size: int = Query(default=10, ge=1, le=50),
) -> HolderNumResponse:
    try:
        if is_cache_enabled():
            cache = get_holder_num_cache()
            key = make_holder_num_cache_key(stock_code, page_size)
            if key in cache:
                logger.info(f"[APICache] holder_num hit: {key}")
                return cache[key]

        manager = get_manager()
        data = manager.get_holder_num_change(stock_code, page_size)
        stock_name = stock_cache.get_stock_name(stock_code, manager=manager)
        records = [HolderNumRecord(**r) for r in data]
        result = HolderNumResponse(code=stock_code, name=stock_name or "", records=records)
        if is_cache_enabled():
            cache[key] = result
        return result
    except DataFetchError as e:
        logger.warning(f"Holder num unavailable: {e}")
        raise HTTPException(
            status_code=503, detail={"error": "data_unavailable", "message": str(e)}
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500, detail={"error": "internal_error", "message": str(e)}
        ) from e


@router.get(
    "/stocks/{stock_code}/dividend",
    response_model=DividendResponse,
    responses={
        503: {"model": ErrorResponse, "description": "Data unavailable"},
        500: {"model": ErrorResponse, "description": "Server error"},
    },
    tags=["stocks"],
)
def get_dividend(
    stock_code: str = Path(max_length=20),
    page_size: int = Query(default=20, ge=1, le=100),
) -> DividendResponse:
    try:
        if is_cache_enabled():
            cache = get_dividend_cache()
            key = make_dividend_cache_key(stock_code, page_size)
            if key in cache:
                logger.info(f"[APICache] dividend hit: {key}")
                return cache[key]

        manager = get_manager()
        data = manager.get_dividend(stock_code, page_size)
        stock_name = stock_cache.get_stock_name(stock_code, manager=manager)
        records = [DividendRecord(**r) for r in data]
        result = DividendResponse(code=stock_code, name=stock_name or "", records=records)
        if is_cache_enabled():
            cache[key] = result
        return result
    except DataFetchError as e:
        logger.warning(f"Dividend unavailable: {e}")
        raise HTTPException(
            status_code=503, detail={"error": "data_unavailable", "message": str(e)}
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500, detail={"error": "internal_error", "message": str(e)}
        ) from e


@router.get(
    "/stocks/{stock_code}/fund-flow",
    response_model=FundFlowResponse,
    responses={
        503: {"model": ErrorResponse, "description": "Data unavailable"},
        500: {"model": ErrorResponse, "description": "Server error"},
    },
    tags=["stocks"],
)
def get_fund_flow(stock_code: str = Path(max_length=20)) -> FundFlowResponse:
    """Get minute-level capital flow for a stock."""
    try:
        if is_cache_enabled():
            cache = get_fund_flow_cache()
            key = make_fund_flow_cache_key(stock_code)
            if key in cache:
                logger.info(f"[APICache] fund_flow hit: {key}")
                return cache[key]

        manager = get_manager()
        data = manager.get_fund_flow_minute(stock_code)
        stock_name = stock_cache.get_stock_name(stock_code, manager=manager)
        records = [FundFlowMinuteRecord(**r) for r in data]
        result = FundFlowResponse(
            code=stock_code, name=stock_name or "", type="minute", records=records
        )
        if is_cache_enabled():
            cache[key] = result
        return result
    except DataFetchError as e:
        logger.warning(f"Fund flow unavailable: {e}")
        raise HTTPException(
            status_code=503, detail={"error": "data_unavailable", "message": str(e)}
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500, detail={"error": "internal_error", "message": str(e)}
        ) from e


@router.get(
    "/stocks/{stock_code}/fund-flow/daily",
    response_model=FundFlowResponse,
    responses={
        503: {"model": ErrorResponse, "description": "Data unavailable"},
        500: {"model": ErrorResponse, "description": "Server error"},
    },
    tags=["stocks"],
)
def get_fund_flow_daily(stock_code: str = Path(max_length=20)) -> FundFlowResponse:
    """Get 120-day capital flow history for a stock."""
    try:
        if is_cache_enabled():
            cache = get_fund_flow_cache()
            key = make_fund_flow_daily_cache_key(stock_code)
            if key in cache:
                logger.info(f"[APICache] fund_flow_daily hit: {key}")
                return cache[key]

        manager = get_manager()
        data = manager.get_fund_flow_120d(stock_code)
        stock_name = stock_cache.get_stock_name(stock_code, manager=manager)
        records = [FundFlowDailyRecord(**r) for r in data]
        result = FundFlowResponse(
            code=stock_code, name=stock_name or "", type="daily", records=records
        )
        if is_cache_enabled():
            cache[key] = result
        return result
    except DataFetchError as e:
        logger.warning(f"Fund flow daily unavailable: {e}")
        raise HTTPException(
            status_code=503, detail={"error": "data_unavailable", "message": str(e)}
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500, detail={"error": "internal_error", "message": str(e)}
        ) from e


@router.get(
    "/hot/topics",
    response_model=HotTopicResponse,
    responses={
        503: {"model": ErrorResponse, "description": "Data unavailable"},
        500: {"model": ErrorResponse, "description": "Server error"},
    },
    tags=["hot"],
)
def get_hot_topics(
    date: str = Query(default="", description="Date (YYYY-MM-DD), empty=today"),
) -> HotTopicResponse:
    """Get daily hot stocks with reason tags."""
    try:
        if is_cache_enabled():
            cache = get_hot_topics_cache()
            key = make_hot_topics_cache_key(date)
            if key in cache:
                logger.info(f"[APICache] hot_topics hit: {key}")
                return cache[key]

        from datetime import datetime

        manager = get_manager()
        data = manager.get_hot_topics(date)
        topics = [HotTopicRecord(**r) for r in data]
        actual_date = date or datetime.now().strftime("%Y-%m-%d")
        result = HotTopicResponse(date=actual_date, total=len(topics), topics=topics)
        if is_cache_enabled():
            cache[key] = result
        return result
    except DataFetchError as e:
        logger.warning(f"Hot topics unavailable: {e}")
        raise HTTPException(
            status_code=503, detail={"error": "data_unavailable", "message": str(e)}
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500, detail={"error": "internal_error", "message": str(e)}
        ) from e


@router.get(
    "/north-flow/realtime",
    response_model=NorthFlowResponse,
    responses={
        503: {"model": ErrorResponse, "description": "Data unavailable"},
        500: {"model": ErrorResponse, "description": "Server error"},
    },
    tags=["north-flow"],
)
def get_north_flow() -> NorthFlowResponse:
    """Get north-bound capital flow (minute-level)."""
    try:
        if is_cache_enabled():
            cache = get_north_flow_cache()
            key = make_north_flow_cache_key()
            if key in cache:
                logger.info(f"[APICache] north_flow hit: {key}")
                return cache[key]

        manager = get_manager()
        data = manager.get_north_flow()
        records = [NorthFlowRecord(**r) for r in data]
        result = NorthFlowResponse(records=records)
        if is_cache_enabled():
            cache[key] = result
        return result
    except DataFetchError as e:
        logger.warning(f"North flow unavailable: {e}")
        raise HTTPException(
            status_code=503, detail={"error": "data_unavailable", "message": str(e)}
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500, detail={"error": "internal_error", "message": str(e)}
        ) from e


@router.get(
    "/stocks/{stock_code}/reports",
    response_model=ReportResponse,
    responses={
        503: {"model": ErrorResponse, "description": "Data unavailable"},
        500: {"model": ErrorResponse, "description": "Server error"},
    },
    tags=["stocks"],
)
def get_reports(
    stock_code: str = Path(max_length=20),
    max_pages: int = Query(default=3, ge=1, le=10, description="Max pages"),
) -> ReportResponse:
    """Get research reports for a stock."""
    try:
        if is_cache_enabled():
            cache = get_reports_cache()
            key = make_reports_cache_key(stock_code, max_pages)
            if key in cache:
                logger.info(f"[APICache] reports hit: {key}")
                return cache[key]

        manager = get_manager()
        data = manager.get_reports(stock_code, max_pages)
        stock_name = stock_cache.get_stock_name(stock_code, manager=manager)
        reports = [ReportRecord(**r) for r in data]
        result = ReportResponse(
            code=stock_code, name=stock_name or "", reports=reports, total=len(reports)
        )
        if is_cache_enabled():
            cache[key] = result
        return result
    except DataFetchError as e:
        logger.warning(f"Reports unavailable: {e}")
        raise HTTPException(
            status_code=503, detail={"error": "data_unavailable", "message": str(e)}
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500, detail={"error": "internal_error", "message": str(e)}
        ) from e


@router.get(
    "/stocks/{stock_code}/reports/{report_id}/pdf",
    response_model=ReportPDFResponse,
    responses={
        503: {"model": ErrorResponse, "description": "Data unavailable"},
        500: {"model": ErrorResponse, "description": "Server error"},
    },
    tags=["stocks"],
)
def get_report_pdf(
    stock_code: str = Path(max_length=20),
    report_id: str = Path(description="info_code"),
) -> ReportPDFResponse:
    """Download a research report PDF. Returns local file path."""
    try:
        manager = get_manager()
        fetcher = manager.get_fetcher("EastMoneyFetcher")
        if not fetcher:
            raise HTTPException(status_code=503, detail={"error": "unavailable"})
        url = fetcher.get_report_pdf_url(report_id)
        path = fetcher.download_report_pdf(report_id)
        return ReportPDFResponse(report_id=report_id, download_path=path, url=url)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500, detail={"error": "internal_error", "message": str(e)}
        ) from e


@router.get(
    "/stocks/{stock_code}/announcements",
    response_model=AnnouncementResponse,
    responses={
        503: {"model": ErrorResponse, "description": "Data unavailable"},
        500: {"model": ErrorResponse, "description": "Server error"},
    },
    tags=["stocks"],
)
def get_announcements(
    stock_code: str = Path(max_length=20),
    page_size: int = Query(default=30, ge=1, le=100, description="Page size"),
) -> AnnouncementResponse:
    """Get corporate announcements for a stock."""
    try:
        if is_cache_enabled():
            cache = get_announcements_cache()
            key = make_announcements_cache_key(stock_code, page_size)
            if key in cache:
                logger.info(f"[APICache] announcements hit: {key}")
                return cache[key]

        manager = get_manager()
        data = manager.get_announcements(stock_code, page_size)
        stock_name = stock_cache.get_stock_name(stock_code, manager=manager)
        announcements = [AnnouncementRecord(**r) for r in data]
        result = AnnouncementResponse(
            code=stock_code,
            name=stock_name or "",
            announcements=announcements,
            total=len(announcements),
        )
        if is_cache_enabled():
            cache[key] = result
        return result
    except DataFetchError as e:
        logger.warning(f"Announcements unavailable: {e}")
        raise HTTPException(
            status_code=503, detail={"error": "data_unavailable", "message": str(e)}
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500, detail={"error": "internal_error", "message": str(e)}
        ) from e
