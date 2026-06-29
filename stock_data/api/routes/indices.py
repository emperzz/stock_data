"""Index endpoints: list, realtime quote, history K-line, intraday minute K-line.

All four endpoints share the main ``router`` declared in ``routes/__init__.py``.
"""

from fastapi import HTTPException, Path, Query

from ...data_provider.fetchers.index_symbols import get_all_indices
from ...data_provider.indicators import compute_lookback
from ..cache import (
    cache_endpoint,
    get_history_cache,
    get_index_intraday_cache,
    get_index_quote_cache,
    get_kline_cache,
    make_index_history_cache_key,
    make_index_intraday_cache_key,
    make_index_quote_cache_key,
    make_kline_cache_key,
)
from ..endpoint_meta import endpoint_meta
from ..schemas import (
    ErrorResponse,
    IndexHistoryResponse,
    IndexInfo,
    IndexIntradayResponse,
    IndexQuote,
    IntradayData,
)

# This module relies on the main ``router`` from ``routes/__init__.py``.
# Importing the package (rather than a submodule) guarantees the router is
# constructed before our @router.get decorators run.
from ._router import router
from .errors import map_errors
from .helpers import (
    _apply_indicators,
    _build_kline_data,
    _format_date,
    _parse_indicators_param,
    _period_to_freq,
    _reject_non_index_code,
    _resolve_index_name,
    get_manager,
)


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
    """List all available indices with code, name, and market type."""
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
    capabilities=["INDEX_REALTIME_QUOTE"],
)
@map_errors
@cache_endpoint(
    cache_fn=lambda *args, **kwargs: get_index_quote_cache(),
    key_builder=lambda index_code: make_index_quote_cache_key(index_code),
    hit_label="index_quote",
)
def get_index_quote(
    index_code: str = Path(max_length=20, description="Index code"),
) -> IndexQuote:
    """Get realtime quote for an index."""
    _reject_non_index_code(index_code, endpoint_kind="quote")

    manager = get_manager()
    quote = manager.get_index_realtime_quote(index_code)

    if quote is None:
        raise HTTPException(
            status_code=404,
            detail={"error": "not_found", "message": f"Quote not available for {index_code}"},
        )

    return IndexQuote(
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
    capabilities=["INDEX_KLINE"],
)
@map_errors
@cache_endpoint(
    # cache_fn closes over the kwargs `period` to pick the per-frequency cache.
    cache_fn=lambda index_code, period, days, start_date, end_date, indicators: get_history_cache(
        _period_to_freq(period)
    ),
    key_builder=lambda index_code, period, days, start_date, end_date, indicators: (
        make_index_history_cache_key(
            index_code,
            _period_to_freq(period),
            days,
            start_date,
            end_date,
            _parse_indicators_param(indicators),
        )
    ),
    hit_label="index_history",
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
    """Get historical K-line data for an index, optionally with technical indicators."""
    _reject_non_index_code(index_code, endpoint_kind="history")

    # Parse indicators param (same semantics as /stocks/{code}/history).
    # Doing it here keeps the key_builder a pure (str → str) function and
    # makes validation order explicit at the route level.
    requested_indicators = _parse_indicators_param(indicators)

    # If indicators are requested, fetch enough history to warm them up.
    actual_days = days
    if requested_indicators:
        extra_lookback = compute_lookback(requested_indicators)
        if extra_lookback > 0:
            actual_days = max(days, extra_lookback)

    manager = get_manager()
    df, source = manager.get_index_historical(
        index_code,
        start_date=start_date,
        end_date=end_date,
        days=actual_days,
        frequency=_period_to_freq(period),
    )

    df = _apply_indicators(df, requested_indicators, days=days, actual_days=actual_days)

    index_name = _resolve_index_name(index_code)

    records = df.to_dict("records")
    data = [_build_kline_data(row, _format_date) for row in records]

    return IndexHistoryResponse(
        code=index_code, name=index_name, period=period, data=data, source=source
    )


# ============================================================================
# Unified K-line (daily + minute)
# ============================================================================


@router.get(
    "/indices/{index_code}/kline",
    response_model=IndexHistoryResponse,
    responses={
        400: {"model": ErrorResponse, "description": "Invalid index code"},
        422: {"model": ErrorResponse, "description": "Adjust not supported for indices"},
        500: {"model": ErrorResponse, "description": "Server error"},
    },
    tags=["indices"],
)
@endpoint_meta(
    summary="指数 K 线（统一入口：d/w/m + 1m/5m/15m/30m/60m）",
    markets=["csi", "hk", "us"],
    capabilities=["INDEX_KLINE"],
)
@map_errors
@cache_endpoint(
    cache_fn=lambda index_code, period, days, start_date, end_date, adjust, indicators: (
        get_kline_cache(_period_to_freq(period))
    ),
    key_builder=lambda index_code, period, days, start_date, end_date, adjust, indicators: (
        make_kline_cache_key(
            index_code,
            _period_to_freq(period),
            days,
            start_date,
            end_date,
            adjust or None,
            _parse_indicators_param(indicators),
        )
    ),
    hit_label="index_kline",
)
def get_index_kline(
    index_code: str = Path(max_length=20, description="Index code"),
    period: str = Query(
        default="daily",
        pattern="^(daily|weekly|monthly|1m|5m|15m|30m|60m)$",
    ),
    days: int = Query(default=30, ge=1, le=365),
    start_date: str | None = Query(default=None),
    end_date: str | None = Query(default=None),
    adjust: str = Query(default="", pattern="^(qfq|hfq)?$"),
    indicators: str | None = Query(default=None),
) -> IndexHistoryResponse:
    """Unified K-line endpoint for indices: daily/weekly/monthly + minute.

    Symmetric to /stocks/{code}/kline but with INDEX_KLINE capability.
    Indices have no qfq/hfq concept (no ex-dividend events) — adjust is
    rejected at the route layer with 422.
    """
    _reject_non_index_code(index_code, endpoint_kind="kline")

    # Indices have no qfq/hfq — reject early (user input error).
    if adjust in ("qfq", "hfq"):
        raise HTTPException(
            status_code=422,
            detail={
                "error": "adjust_not_supported",
                "message": "Indices have no qfq/hfq concept (no ex-dividend events).",
            },
        )

    freq = _period_to_freq(period)

    requested_indicators = _parse_indicators_param(indicators)
    actual_days = days
    if requested_indicators:
        extra = compute_lookback(requested_indicators)
        if extra > 0:
            actual_days = max(days, extra)

    manager = get_manager()
    df, source = manager.get_kline_data(
        index_code,
        start_date=start_date,
        end_date=end_date,
        days=actual_days,
        frequency=freq,
        adjust=None,  # adjust already rejected above
    )
    df = _apply_indicators(df, requested_indicators, days=days, actual_days=actual_days)
    index_name = _resolve_index_name(index_code)

    records = df.to_dict("records")
    return IndexHistoryResponse(
        code=index_code,
        name=index_name,
        period=period,
        data=[_build_kline_data(r, _format_date) for r in records],
        source=source,
    )


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
    capabilities=["INDEX_KLINE"],
)
@map_errors
@cache_endpoint(
    cache_fn=lambda *args, **kwargs: get_index_intraday_cache(),
    key_builder=lambda index_code, period: make_index_intraday_cache_key(index_code, period),
    hit_label="index_intraday",
)
def get_index_intraday(
    index_code: str = Path(max_length=20, description="Index code"),
    period: str = Query(
        default="5",
        pattern="^(1|5|15|30|60)$",
        description="Minute period: 1, 5, 15, 30, 60",
    ),
) -> IndexIntradayResponse:
    """Get intraday minute-level data for an index."""
    _reject_non_index_code(index_code, endpoint_kind="intraday")

    manager = get_manager()
    df, source = manager.get_index_intraday(index_code, period=period)

    index_name = _resolve_index_name(index_code)

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
    return IndexIntradayResponse(
        code=index_code,
        name=index_name,
        period=period_label,
        date=trade_date,
        data=data,
        source=source,
    )
