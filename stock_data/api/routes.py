"""
API routes for stock data server.
"""

import logging
from datetime import datetime
from typing import TYPE_CHECKING

from fastapi import APIRouter, HTTPException, Path, Query

if TYPE_CHECKING:
    import pandas as pd

from stock_data.data_provider.core.types import (
    REALTIME_CIRCUIT_BREAKER,
    safe_float,
    safe_int,
)

from ..data_provider import DataFetcherManager, DataFetchError
from ..data_provider.fetchers.index_symbols import get_all_indices
from ..data_provider.indicators import available_catalog, compute, compute_lookback
from ..data_provider.indicators.types import IndicatorKey
from ..data_provider.manager import create_default_manager
from ..data_provider.persistence import board as stock_board_cache
from ..data_provider.persistence import stock_list as stock_cache
from ..data_provider.utils.normalize import (
    is_hk_market,
    is_index_code,
    is_us_market,
    normalize_stock_code,
)
from .cache import (
    cached_endpoint,
    cached_lookup,
    cached_store,
    get_announcements_cache,
    get_block_trade_cache,
    get_dividend_cache,
    get_dragontiger_cache,
    get_fund_flow_cache,
    get_fund_flow_daily_cache,
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
from .endpoint_meta import endpoint_meta
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
    IndicatorCatalogEntry,
    IndicatorCatalogResponse,
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
    SourceHealth,
    StockHistoryResponse,
    StockInfo,
    StockQuote,
    TradeCalendarResponse,
    ZTPoolResponse,
    ZTPoolStock,
)

logger = logging.getLogger(__name__)

router = APIRouter()


# ---------- shared helpers for the two history endpoints ----------


def _parse_indicators_param(indicators: str | None) -> list[str]:
    """Parse the `?indicators=a,b,c` query param.

    Each name is validated against `IndicatorKey`. Empty / None returns
    an empty list. Duplicates are deduplicated (preserves order of first
    occurrence). Raises 400 on an unknown indicator name.

    Used by both /stocks/{code}/history and /indices/{code}/history.
    """
    if not indicators:
        return []
    out: list[str] = []
    for raw in indicators.split(","):
        key = raw.strip()
        if not key or key in out:
            continue
        try:
            IndicatorKey(key)
        except ValueError:
            raise HTTPException(
                status_code=400,
                detail={
                    "error": "invalid_indicator",
                    "message": (
                        f"Unknown indicator: {key!r}. "
                        "See /indicators/catalog for the list of supported indicators."
                    ),
                },
            ) from None
        out.append(key)
    return out


def _apply_indicators(
    df: "pd.DataFrame",
    requested_indicators: list[str],
    days: int,
    actual_days: int,
) -> "pd.DataFrame":
    """Run the indicator orchestrator on `df` if requested, then truncate
    back to the user-requested bar count.

    Args:
        df: K-line DataFrame already fetched with `actual_days` rows.
        requested_indicators: empty list → no-op (returns df unchanged).
        days: the user-requested bar count.
        actual_days: how many rows were actually fetched (>= days when
            lookback expansion was needed).

    Returns:
        A DataFrame with the `indicators` column populated and at most
        `days` rows (the most recent ones).
    """
    if not requested_indicators:
        return df
    df = compute(df, requested_indicators)
    if actual_days > days and len(df) > days:
        df = df.tail(days).reset_index(drop=True)
    return df


def _build_kline_data(row: dict, format_date) -> KLineData:
    """Build a KLineData from a DataFrame row dict.

    Centralizes the back-compat fill for `ma5`/`ma10`/`ma20` from the
    `indicators` dict (the legacy `KLineData` field surface). When
    `indicators` wasn't computed, those fields are left as None — the
    model's `@model_serializer` will then drop them from the JSON
    response entirely. When `indicators` was computed, `ma5/10/20` are
    populated from the dict (mirrors the pre-refactor shape) AND the
    full `indicators` dict is preserved.

    Used by both /stocks/{code}/history and /indices/{code}/history.
    """
    ind = row.get("indicators") or {}
    return KLineData(
        date=format_date(row.get("date")),
        # Required OHLCV fields — _clean_data already drops rows with NaN
        # in these columns; safe_float/safe_int are defense-in-depth.
        open=safe_float(row.get("open"), 0.0) or 0.0,
        high=safe_float(row.get("high"), 0.0) or 0.0,
        low=safe_float(row.get("low"), 0.0) or 0.0,
        close=safe_float(row.get("close"), 0.0) or 0.0,
        volume=safe_int(row.get("volume"), 0) or 0,
        # Optional fields — NaN → None → JSON null (semantically correct).
        amount=safe_float(row.get("amount")),
        change_percent=safe_float(row.get("pct_chg")),
        # Back-compat: surface ma5/ma10/ma20 from the indicators dict if computed.
        # None when not requested — model_serializer drops the key.
        ma5=safe_float(ind.get("ma5")),
        ma10=safe_float(ind.get("ma10")),
        ma20=safe_float(ind.get("ma20")),
        # Pass the full dict when computed, None when empty — serializer drops it.
        indicators=ind or None,
    )


def _format_date(val) -> str:
    """Format a K-line / intraday `date` cell to a YYYY-MM-DD string.

    Used by both the stock and index history routes. Module-level
    (instead of inlined in each route) because it's pure and stable.
    """
    if val is None:
        return ""
    if hasattr(val, "strftime"):
        return val.strftime("%Y-%m-%d")
    return str(val)


# Global manager instance
_manager: DataFetcherManager | None = None


def get_manager() -> DataFetcherManager:
    """Get or create the global DataFetcherManager."""
    global _manager
    if _manager is None:
        _manager = create_default_manager()
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
@endpoint_meta(
    summary="健康检查 + fetcher 断路器状态",
    markets=["csi", "hk", "us"],
    capabilities=[],
)
def health_check(details: bool = False) -> HealthResponse:
    """Health check endpoint.

    Lightweight mode (default): returns overall status for k8s/lb probes.
    Detailed mode (?details=true): returns per-source circuit breaker state for AI agents.

    Both modes are READ-ONLY — they use ``CircuitBreaker.snapshot_state()`` which does
    not transition states or consume half-open probe budgets, so frequent probes
    cannot starve real fetches.
    """
    manager = get_manager()
    source_states: list[SourceHealth] = []
    any_available = False

    for fetcher in manager.fetchers:
        snap = REALTIME_CIRCUIT_BREAKER.snapshot_state(fetcher.name)
        if snap["available"]:
            any_available = True
        last_success = snap["last_success_time"] if snap["last_success_time"] > 0 else None
        last_failure = snap["last_failure_time"] if snap["last_failure_time"] > 0 else None
        source_states.append(SourceHealth(
            name=fetcher.name,
            state=snap["state"],
            available=snap["available"],
            last_success_time=last_success,
            last_failure_time=last_failure,
            failure_count=snap["failures"],
        ))

    if any_available:
        open_count = sum(1 for s in source_states if s.state in ("open", "half_open"))
        status = "degraded" if open_count > 0 else "ok"
    else:
        status = "unhealthy"

    return HealthResponse(
        status=status,
        sources=source_states if details else None,
    )


@router.get(
    "/stocks/{stock_code}/quote",
    response_model=StockQuote,
    responses={
        404: {"model": ErrorResponse, "description": "Stock not found"},
        500: {"model": ErrorResponse, "description": "Server error"},
    },
    tags=["stocks"],
)
@endpoint_meta(
    summary="实时行情",
    markets=["csi", "hk", "us"],
    capabilities=["REALTIME_QUOTE"],
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
@endpoint_meta(
    summary="历史 K 线（含可选指标）",
    markets=["csi", "hk", "us"],
    capabilities=["HISTORICAL_DWM", "HISTORICAL_MIN"],
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
    indicators: str | None = Query(
        default=None,
        description=(
            "Comma-separated list of technical indicators to compute on the K-line. "
            "Supported: ma, macd, boll, kdj, rsi, wr, bias, cci, atr, obv, "
            "roc, dmi, sar, kc. The 'ma' indicator always returns ma5/10/20/30/60 "
            "with default options. Use /indicators/catalog for details."
        ),
    ),
) -> StockHistoryResponse:
    """
    Get historical K-line data for a stock, optionally with technical indicators.

    Args:
        stock_code: Stock code
        period: K-line period (daily/weekly/monthly)
        days: Number of days when start_date not provided
        start_date: Start date (YYYY-MM-DD), overrides days parameter
        end_date: End date (YYYY-MM-DD), defaults to today
        adjust: Adjustment type - empty=不复权, qfq=前复权, hfq=后复权
        indicators: Comma-separated indicator names, e.g. "ma,macd,kdj"

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

        # Parse indicators param
        requested_indicators = _parse_indicators_param(indicators)

        # Cache key includes all params including adjust + indicators
        if is_cache_enabled():
            cache = get_history_cache(frequency)
            key = make_history_cache_key(
                stock_code, frequency, days, start_date, end_date, adj_value, requested_indicators
            )
            if key in cache:
                logger.info(f"[APICache] history hit: {key}")
                return cache[key]

        manager = get_manager()

        # If indicators are requested, fetch enough history to warm them up
        actual_days = days
        if requested_indicators:
            extra_lookback = compute_lookback(requested_indicators)
            if extra_lookback > 0:
                actual_days = max(days, extra_lookback)

        df, source = manager.get_kline_data(
            stock_code,
            start_date=start_date,
            end_date=end_date,
            days=actual_days,
            frequency=frequency,
            adjust=adj_value,
        )

        # Compute indicators (if any) and merge into the DataFrame
        df = _apply_indicators(df, requested_indicators, days=days, actual_days=actual_days)

        stock_name = stock_cache.get_stock_name(stock_code, manager=manager)

        # Convert to response model
        records = df.to_dict("records")
        data = [_build_kline_data(row, _format_date) for row in records]

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
@endpoint_meta(
    summary="分钟 K 线",
    markets=["csi"],
    capabilities=["HISTORICAL_MIN"],
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
@endpoint_meta(
    summary="指数列表（A 股 + 港股 + 美股）",
    markets=["csi", "hk", "us"],
    capabilities=[],
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
@endpoint_meta(
    summary="指数实时行情",
    markets=["csi", "hk", "us"],
    capabilities=["INDEX_QUOTE"],
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
@endpoint_meta(
    summary="指数历史 K 线",
    markets=["csi", "hk", "us"],
    capabilities=["INDEX_HISTORICAL", "HISTORICAL_DWM"],
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
    indicators: str | None = Query(
        default=None,
        description=(
            "Comma-separated list of technical indicators to compute on the K-line. "
            "Supported: ma, macd, boll, kdj, rsi, wr, bias, cci, atr, obv, "
            "roc, dmi, sar, kc. The 'ma' indicator always returns ma5/10/20/30/60 "
            "with default options. Use /indicators/catalog for details."
        ),
    ),
) -> IndexHistoryResponse:
    """
    Get historical K-line data for an index, optionally with technical indicators.

    Args:
        index_code: Index code (e.g., 000300, 399006)
        period: K-line period (daily/weekly/monthly)
        days: Number of days when start_date not provided
        start_date: Start date (YYYY-MM-DD), overrides days parameter
        end_date: End date (YYYY-MM-DD), defaults to today
        indicators: Comma-separated indicator names, e.g. "ma,macd,kdj"
    """
    try:
        period_map = {"daily": "d", "weekly": "w", "monthly": "m"}
        frequency = period_map.get(period, "d")

        # Parse indicators param (same semantics as /stocks/{code}/history)
        requested_indicators = _parse_indicators_param(indicators)

        # If indicators are requested, fetch enough history to warm them up.
        # (Akshare's index branch doesn't go through BaseFetcher's auto-*2
        # expansion, so the route must do the lookback itself.)
        actual_days = days
        if requested_indicators:
            extra_lookback = compute_lookback(requested_indicators)
            if extra_lookback > 0:
                actual_days = max(days, extra_lookback)

        if is_cache_enabled():
            cache = get_history_cache(frequency)
            key = make_index_history_cache_key(
                index_code, frequency, days, start_date, end_date, requested_indicators
            )
            if key in cache:
                logger.info(f"[APICache] index_history hit: {key}")
                return cache[key]

        manager = get_manager()
        df, source = manager.get_index_historical(
            index_code,
            start_date=start_date,
            end_date=end_date,
            days=actual_days,
            frequency=frequency,
        )

        # Compute indicators (if any) and merge into the DataFrame
        df = _apply_indicators(df, requested_indicators, days=days, actual_days=actual_days)

        # Get index name from index list
        all_indices = get_all_indices()
        index_name = next((i["name"] for i in all_indices if i["code"] == index_code), index_code)

        records = df.to_dict("records")
        data = [_build_kline_data(row, _format_date) for row in records]

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
    except HTTPException:
        raise
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
@endpoint_meta(
    summary="指数分钟 K 线",
    markets=["csi", "hk", "us"],
    capabilities=["INDEX_INTRADAY", "HISTORICAL_MIN"],
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
@endpoint_meta(
    summary="股票列表（分页）",
    markets=["csi", "hk", "us"],
    capabilities=["STOCK_LIST"],
)
def list_stocks(
    market: str = Query(..., pattern="^(csi|hk|us)$", description="Market: csi/hk/us"),
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

    Note:
        A-shares are exposed as ``csi`` (中证). The legacy ``cn`` tag is
        an internal fetcher convention and is NOT a valid value here —
        ``csi`` is the single public-facing A-share tag.
    """

    # Get stock list with automatic refresh (cache layer handles daily refresh logic)
    manager = get_manager()
    stocks, _origin = stock_cache.get_stock_list(market, refresh=refresh, manager=manager)
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
@endpoint_meta(
    summary="A 股交易日历",
    markets=["csi"],
    capabilities=["TRADE_CALENDAR"],
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
    from ..data_provider.persistence.trade_calendar import (
        get_cached_calendar,
        get_latest_cached_trade_date,
    )

    today = datetime.now().strftime("%Y-%m-%d")

    # Check if refresh is needed
    should_refresh = refresh
    if not should_refresh:
        cached_dates, _ = get_cached_calendar()
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
            cached_dates, _ = get_cached_calendar()
            if not cached_dates:
                raise HTTPException(
                    status_code=500,
                    detail={"error": "fetch_failed", "message": str(e)},
                ) from e
            # Fall through to use cached data

    # Get dates from cache
    dates, _ = get_cached_calendar()
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
@endpoint_meta(
    summary="概念 / 行业板块列表",
    markets=["csi"],
    capabilities=["STOCK_BOARD"],
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
        # Board list metadata is persisted in SQLite; the persistence layer
        # handles daily-refresh logic. No TTLCache needed — SQLite lookups
        # on indexed columns are sub-millisecond.
        manager = get_manager()
        boards, _ = stock_board_cache.get_board_list(
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
@endpoint_meta(
    summary="板块成分股",
    markets=["csi"],
    capabilities=["STOCK_BOARD"],
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
        # Board-stock mapping is persisted in SQLite; the persistence layer
        # handles refresh logic. No TTLCache needed — SQLite queries on
        # indexed columns are sub-millisecond.
        manager = get_manager()
        stocks, _ = stock_board_cache.get_board_stocks(
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
            boards, _ = stock_board_cache.get_board_list(bt, source, refresh=False, manager=manager)
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
@endpoint_meta(
    summary="涨跌停股池",
    markets=["csi"],
    capabilities=["STOCK_ZT_POOL"],
)
def get_pools(
    type: str = Query(
        ...,
        pattern="^(zt|dt|zbgc)$",
        description="Pool type: zt (涨停) / dt (跌停) / zbgc (炸板)",
    ),
    date: str | None = Query(
        None,
        description=(
            "Pool date (YYYY-MM-DD). If not provided, the server picks the most recent "
            "trade date relative to today: today itself when today is a trade day, "
            "otherwise the latest cached trade date <= today."
        ),
    ),
    refresh: bool = Query(
        False,
        description=(
            "Force refresh from upstream. Bypasses the persistence read, but the "
            "persistence write is still skipped when the resolved date is the "
            "'current trading day' (today AND today is a trade day), to avoid "
            "persisting a partially-formed pool."
        ),
    ),
) -> ZTPoolResponse:
    """
    Get ZT (涨跌停) pool data for a specific type and date.

    Args:
        type: Pool type - zt (涨停), dt (跌停), zbgc (炸板)
        date: Pool date in YYYY-MM-DD format. If not provided, the server resolves
              it as: today (if today is a trade day) or the latest trade date <= today.
        refresh: If True, force refresh from upstream and (for non-current-day) update cache.

    Returns:
        ZTPoolResponse with list of stocks in the pool.
    """
    try:
        # ----- Resolve query_date -----
        from datetime import date as date_cls

        from ..data_provider.persistence import trade_calendar

        today_str = date_cls.today().strftime("%Y-%m-%d")

        if date:
            query_date = date
        else:
            # User did not pass a date: today if it's a trade day, otherwise
            # the latest persisted trade date <= today.
            if trade_calendar.is_trade_date(today_str):
                query_date = today_str
            else:
                resolved = trade_calendar.get_latest_trade_date_on_or_before(today_str)
                # Extreme edge case: trade_calendar table is empty. Fall back to
                # today so the caller gets a clear upstream error rather than a
                # silent 404.
                query_date = resolved or today_str

        # `is_current_day` is now a ROUTE-LAYER concern only — it drives
        # the in-process TTLCache (which is per-process and short-lived).
        # The persistence layer (pool_daily.get_pool) computes the same
        # decision internally to control SQLite read/write/fallback.
        is_current_day = (query_date == today_str) and trade_calendar.is_trade_date(today_str)

        # TTLCache is only used for the current trading day (volatile data
        # that must NOT hit SQLite). Historical queries go through the
        # persistence layer directly — SQLite handles date-keyed lookups.
        cache_key = make_pools_cache_key(type, query_date)
        if is_current_day and is_cache_enabled():
            hit = cached_lookup(get_pools_cache, cache_key, "pools")
            if hit is not None:
                return hit

        manager = get_manager()
        # The persistence layer now owns the volatile/historical policy
        # via pool_daily.is_volatile_date(); no need to pass is_current_day
        # down anymore.
        stocks = manager.get_zt_pool(
            pool_type=type,
            date=query_date,
            refresh=refresh,
        )

        if not stocks:
            raise HTTPException(
                status_code=404,
                detail={"error": "not_found", "message": f"No {type} pool data found"},
            )

        # Derive actual date from query param or first stock record
        actual_date = query_date or stocks[0].get("pool_date", "")

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

        # Only cache current-day results in TTLCache (historical goes to SQLite).
        if is_current_day:
            cached_store(get_pools_cache, cache_key, result)
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
@endpoint_meta(
    summary="龙虎榜（个股）",
    markets=["csi"],
    capabilities=["DRAGON_TIGER"],
)
def get_dragon_tiger(
    stock_code: str = Path(max_length=20),
    trade_date: str = Query(default="", description="Trade date (YYYY-MM-DD)"),
    look_back: int = Query(default=30, ge=1, le=365),
) -> DragonTigerResponse:
    manager = get_manager()
    data = manager.get_dragon_tiger(stock_code, trade_date, look_back)
    stock_name = stock_cache.get_stock_name(stock_code, manager=manager)
    seats_data = data.get("seats", {})
    return DragonTigerResponse(
        code=stock_code,
        name=stock_name or "",
        records=[DragonTigerRecord(**r) for r in data.get("records", [])],
        seats={
            "buy": [DragonTigerSeat(**s) for s in seats_data.get("buy", [])],
            "sell": [DragonTigerSeat(**s) for s in seats_data.get("sell", [])],
        },
        institution=DragonTigerInstitution(**data.get("institution", {})),
    )


get_dragon_tiger = cached_endpoint(
    get_dragontiger_cache,
    make_dragon_tiger_cache_key,
    "dragontiger",
    "Dragon tiger",
)(get_dragon_tiger)


@router.get(
    "/dragon-tiger/daily",
    response_model=DailyDragonTigerResponse,
    responses={
        503: {"model": ErrorResponse, "description": "Data unavailable"},
        500: {"model": ErrorResponse, "description": "Server error"},
    },
    tags=["dragon-tiger"],
)
@endpoint_meta(
    summary="龙虎榜（全市场）",
    markets=["csi"],
    capabilities=["DRAGON_TIGER"],
)
def get_daily_dragon_tiger(
    trade_date: str = Query(default="", description="Trade date (YYYY-MM-DD)"),
    min_net_buy: float | None = Query(default=None, description="Min net buy (万元)"),
) -> DailyDragonTigerResponse:
    manager = get_manager()
    data = manager.get_daily_dragon_tiger(trade_date, min_net_buy)
    return DailyDragonTigerResponse(
        date=data["date"],
        total=data["total"],
        stocks=[DailyDragonTigerStock(**s) for s in data["stocks"]],
    )


get_daily_dragon_tiger = cached_endpoint(
    get_dragontiger_cache,
    make_daily_dragon_tiger_cache_key,
    "daily_dragon_tiger",
    "Daily dragon tiger",
)(get_daily_dragon_tiger)


@router.get(
    "/stocks/{stock_code}/margin",
    response_model=MarginTradingResponse,
    responses={
        503: {"model": ErrorResponse, "description": "Data unavailable"},
        500: {"model": ErrorResponse, "description": "Server error"},
    },
    tags=["stocks"],
)
@endpoint_meta(
    summary="融资融券",
    markets=["csi"],
    capabilities=["MARGIN_TRADING"],
)
def get_margin(
    stock_code: str = Path(max_length=20),
    page_size: int = Query(default=30, ge=1, le=100),
) -> MarginTradingResponse:
    manager = get_manager()
    data = manager.get_margin_trading(stock_code, page_size)
    stock_name = stock_cache.get_stock_name(stock_code, manager=manager)
    return MarginTradingResponse(
        code=stock_code,
        name=stock_name or "",
        records=[MarginTradingRecord(**r) for r in data],
    )


get_margin = cached_endpoint(
    get_margin_cache, make_margin_cache_key, "margin", "Margin trading"
)(get_margin)


@router.get(
    "/stocks/{stock_code}/block-trade",
    response_model=BlockTradeResponse,
    responses={
        503: {"model": ErrorResponse, "description": "Data unavailable"},
        500: {"model": ErrorResponse, "description": "Server error"},
    },
    tags=["stocks"],
)
@endpoint_meta(
    summary="大宗交易",
    markets=["csi"],
    capabilities=["BLOCK_TRADE"],
)
def get_block_trade(
    stock_code: str = Path(max_length=20),
    page_size: int = Query(default=20, ge=1, le=100),
) -> BlockTradeResponse:
    manager = get_manager()
    data = manager.get_block_trade(stock_code, page_size)
    stock_name = stock_cache.get_stock_name(stock_code, manager=manager)
    records = [BlockTradeRecord(**r) for r in data]
    return BlockTradeResponse(
        code=stock_code, name=stock_name or "", records=records, total=len(records)
    )


get_block_trade = cached_endpoint(
    get_block_trade_cache, make_block_trade_cache_key, "block_trade", "Block trade"
)(get_block_trade)


@router.get(
    "/stocks/{stock_code}/holder-num",
    response_model=HolderNumResponse,
    responses={
        503: {"model": ErrorResponse, "description": "Data unavailable"},
        500: {"model": ErrorResponse, "description": "Server error"},
    },
    tags=["stocks"],
)
@endpoint_meta(
    summary="股东户数变化",
    markets=["csi"],
    capabilities=["HOLDER_NUM"],
)
def get_holder_num(
    stock_code: str = Path(max_length=20),
    page_size: int = Query(default=10, ge=1, le=50),
) -> HolderNumResponse:
    manager = get_manager()
    data = manager.get_holder_num_change(stock_code, page_size)
    stock_name = stock_cache.get_stock_name(stock_code, manager=manager)
    return HolderNumResponse(
        code=stock_code,
        name=stock_name or "",
        records=[HolderNumRecord(**r) for r in data],
    )


get_holder_num = cached_endpoint(
    get_holder_num_cache, make_holder_num_cache_key, "holder_num", "Holder num"
)(get_holder_num)


@router.get(
    "/stocks/{stock_code}/dividend",
    response_model=DividendResponse,
    responses={
        503: {"model": ErrorResponse, "description": "Data unavailable"},
        500: {"model": ErrorResponse, "description": "Server error"},
    },
    tags=["stocks"],
)
@endpoint_meta(
    summary="分红送转",
    markets=["csi"],
    capabilities=["DIVIDEND"],
)
def get_dividend(
    stock_code: str = Path(max_length=20),
    page_size: int = Query(default=20, ge=1, le=100),
) -> DividendResponse:
    manager = get_manager()
    data = manager.get_dividend(stock_code, page_size)
    stock_name = stock_cache.get_stock_name(stock_code, manager=manager)
    return DividendResponse(
        code=stock_code,
        name=stock_name or "",
        records=[DividendRecord(**r) for r in data],
    )


get_dividend = cached_endpoint(
    get_dividend_cache, make_dividend_cache_key, "dividend", "Dividend"
)(get_dividend)


@router.get(
    "/stocks/{stock_code}/fund-flow",
    response_model=FundFlowResponse,
    responses={
        503: {"model": ErrorResponse, "description": "Data unavailable"},
        500: {"model": ErrorResponse, "description": "Server error"},
    },
    tags=["stocks"],
)
@endpoint_meta(
    summary="资金流（分钟级）",
    markets=["csi"],
    capabilities=["FUND_FLOW"],
)
def get_fund_flow(stock_code: str = Path(max_length=20)) -> FundFlowResponse:
    """Get minute-level capital flow for a stock."""
    manager = get_manager()
    data = manager.get_fund_flow_minute(stock_code)
    stock_name = stock_cache.get_stock_name(stock_code, manager=manager)
    return FundFlowResponse(
        code=stock_code,
        name=stock_name or "",
        type="minute",
        records=[FundFlowMinuteRecord(**r) for r in data],
    )


get_fund_flow = cached_endpoint(
    get_fund_flow_cache, make_fund_flow_cache_key, "fund_flow", "Fund flow"
)(get_fund_flow)


@router.get(
    "/stocks/{stock_code}/fund-flow/daily",
    response_model=FundFlowResponse,
    responses={
        503: {"model": ErrorResponse, "description": "Data unavailable"},
        500: {"model": ErrorResponse, "description": "Server error"},
    },
    tags=["stocks"],
)
@endpoint_meta(
    summary="资金流（120 日）",
    markets=["csi"],
    capabilities=["FUND_FLOW"],
)
def get_fund_flow_daily(stock_code: str = Path(max_length=20)) -> FundFlowResponse:
    """Get 120-day capital flow history for a stock."""
    manager = get_manager()
    data = manager.get_fund_flow_120d(stock_code)
    stock_name = stock_cache.get_stock_name(stock_code, manager=manager)
    return FundFlowResponse(
        code=stock_code,
        name=stock_name or "",
        type="daily",
        records=[FundFlowDailyRecord(**r) for r in data],
    )


get_fund_flow_daily = cached_endpoint(
    get_fund_flow_daily_cache,
    make_fund_flow_daily_cache_key,
    "fund_flow_daily",
    "Fund flow daily",
)(get_fund_flow_daily)


@router.get(
    "/hot/topics",
    response_model=HotTopicResponse,
    responses={
        503: {"model": ErrorResponse, "description": "Data unavailable"},
        500: {"model": ErrorResponse, "description": "Server error"},
    },
    tags=["hot"],
)
@endpoint_meta(
    summary="热点题材",
    markets=["csi"],
    capabilities=["HOT_TOPICS"],
)
def get_hot_topics(
    date: str = Query(default="", description="Date (YYYY-MM-DD), empty=today"),
) -> HotTopicResponse:
    """Get daily hot stocks with reason tags."""
    manager = get_manager()
    data = manager.get_hot_topics(date)
    topics = [HotTopicRecord(**r) for r in data]
    actual_date = date or datetime.now().strftime("%Y-%m-%d")
    return HotTopicResponse(date=actual_date, total=len(topics), topics=topics)


get_hot_topics = cached_endpoint(
    get_hot_topics_cache, make_hot_topics_cache_key, "hot_topics", "Hot topics"
)(get_hot_topics)


@router.get(
    "/north-flow/realtime",
    response_model=NorthFlowResponse,
    responses={
        503: {"model": ErrorResponse, "description": "Data unavailable"},
        500: {"model": ErrorResponse, "description": "Server error"},
    },
    tags=["north-flow"],
)
@endpoint_meta(
    summary="北向资金",
    markets=["csi"],
    capabilities=["NORTH_FLOW"],
)
def get_north_flow() -> NorthFlowResponse:
    """Get north-bound capital flow (minute-level)."""
    manager = get_manager()
    data = manager.get_north_flow()
    return NorthFlowResponse(records=[NorthFlowRecord(**r) for r in data])


get_north_flow = cached_endpoint(
    get_north_flow_cache, make_north_flow_cache_key, "north_flow", "North flow"
)(get_north_flow)


@router.get(
    "/stocks/{stock_code}/reports",
    response_model=ReportResponse,
    responses={
        503: {"model": ErrorResponse, "description": "Data unavailable"},
        500: {"model": ErrorResponse, "description": "Server error"},
    },
    tags=["stocks"],
)
@endpoint_meta(
    summary="研报列表",
    markets=["csi"],
    capabilities=["RESEARCH_REPORT"],
)
def get_reports(
    stock_code: str = Path(max_length=20),
    max_pages: int = Query(default=3, ge=1, le=10, description="Max pages"),
) -> ReportResponse:
    """Get research reports for a stock."""
    manager = get_manager()
    data = manager.get_reports(stock_code, max_pages)
    stock_name = stock_cache.get_stock_name(stock_code, manager=manager)
    reports = [ReportRecord(**r) for r in data]
    return ReportResponse(
        code=stock_code, name=stock_name or "", reports=reports, total=len(reports)
    )


get_reports = cached_endpoint(
    get_reports_cache, make_reports_cache_key, "reports", "Reports"
)(get_reports)


@router.get(
    "/stocks/{stock_code}/reports/{report_id}/pdf",
    response_model=ReportPDFResponse,
    responses={
        503: {"model": ErrorResponse, "description": "Data unavailable"},
        500: {"model": ErrorResponse, "description": "Server error"},
    },
    tags=["stocks"],
)
@endpoint_meta(
    summary="研报 PDF 下载",
    markets=["csi"],
    capabilities=["RESEARCH_REPORT"],
)
def get_report_pdf(
    stock_code: str = Path(max_length=20),
    report_id: str = Path(description="info_code"),
) -> ReportPDFResponse:
    """Download a research report PDF. Returns local file path."""
    try:
        manager = get_manager()
        path, url = manager.get_report_pdf(report_id)
        return ReportPDFResponse(report_id=report_id, download_path=path, url=url)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500, detail={"error": "internal_error", "message": str(e)}
        ) from e


@router.get(
    "/indicators/catalog",
    response_model=IndicatorCatalogResponse,
    tags=["indicators"],
)
@endpoint_meta(
    summary="技术指标目录",
    markets=["csi", "hk", "us"],
    capabilities=[],
)
def get_indicator_catalog() -> IndicatorCatalogResponse:
    """
    List all available technical indicators.

    Returns a catalog describing each indicator's key, default options,
    output columns, and the default lookback (how many historical bars
    the orchestrator needs to fetch to fully warm it up). Useful for
    AI agents that want to introspect what's available before sending
    `?indicators=...` on /stocks/{code}/history.
    """
    catalog = available_catalog()
    return IndicatorCatalogResponse(
        indicators=[IndicatorCatalogEntry(**entry) for entry in catalog]
    )


@router.get(
    "/stocks/{stock_code}/announcements",
    response_model=AnnouncementResponse,
    responses={
        503: {"model": ErrorResponse, "description": "Data unavailable"},
        500: {"model": ErrorResponse, "description": "Server error"},
    },
    tags=["stocks"],
)
@endpoint_meta(
    summary="公告",
    markets=["csi"],
    capabilities=["ANNOUNCEMENT"],
)
def get_announcements(
    stock_code: str = Path(max_length=20),
    page_size: int = Query(default=30, ge=1, le=100, description="Page size"),
) -> AnnouncementResponse:
    """Get corporate announcements for a stock."""
    manager = get_manager()
    data = manager.get_announcements(stock_code, page_size)
    stock_name = stock_cache.get_stock_name(stock_code, manager=manager)
    announcements = [AnnouncementRecord(**r) for r in data]
    return AnnouncementResponse(
        code=stock_code,
        name=stock_name or "",
        announcements=announcements,
        total=len(announcements),
    )


get_announcements = cached_endpoint(
    get_announcements_cache,
    make_announcements_cache_key,
    "announcements",
    "Announcements",
)(get_announcements)
