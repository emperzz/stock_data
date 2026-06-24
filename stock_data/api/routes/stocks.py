"""Per-stock endpoints. Everything under ``/stocks/{code}/...`` plus the
related dragon-tiger / margin / block-trade / holder-num / dividend / fund-flow /
reports / announcements / info / quote / history / intraday surfaces.

The stock-list endpoint (``GET /stocks``) lives in :mod:`.calendar` because
it's a list-level query, not per-stock.
"""

from fastapi import HTTPException, Path, Query

from ...data_provider.indicators import compute_lookback
from ...data_provider.persistence import stock_list as stock_cache
from ...data_provider.utils.normalize import (
    is_hk_market,
    is_index_code,
    is_us_market,
    normalize_stock_code,
)
from ..cache import (
    cache_endpoint,
    get_announcements_cache,
    get_block_trade_cache,
    get_dividend_cache,
    get_dragontiger_cache,
    get_fund_flow_cache,
    get_fund_flow_daily_cache,
    get_history_cache,
    get_holder_num_cache,
    get_margin_cache,
    get_quote_cache,
    get_reports_cache,
    get_stock_info_cache,
    get_stock_intraday_cache,
    make_announcements_cache_key,
    make_block_trade_cache_key,
    make_dividend_cache_key,
    make_dragon_tiger_cache_key,
    make_fund_flow_cache_key,
    make_fund_flow_daily_cache_key,
    make_history_cache_key,
    make_holder_num_cache_key,
    make_margin_cache_key,
    make_quote_cache_key,
    make_reports_cache_key,
    make_stock_info_cache_key,
    make_stock_intraday_cache_key,
)
from ..endpoint_meta import endpoint_meta
from ..schemas import (
    AnnouncementRecord,
    AnnouncementResponse,
    BlockTradeRecord,
    BlockTradeResponse,
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
    HolderNumRecord,
    HolderNumResponse,
    IntradayData,
    IntradayResponse,
    MarginTradingRecord,
    MarginTradingResponse,
    ReportPDFResponse,
    ReportRecord,
    ReportResponse,
    StockHistoryResponse,
    StockInfoResponse,
    StockQuote,
)
from ._router import router
from .errors import map_errors
from .helpers import (
    _apply_indicators,
    _build_kline_data,
    _format_date,
    _parse_indicators_param,
    _period_to_freq,
    _reject_index_code,
    get_manager,
)

# ============================================================================
# Stock info (公司画像)
# ============================================================================


@router.get(
    "/stocks/{code}/info",
    response_model=StockInfoResponse,
    responses={
        503: {"model": ErrorResponse, "description": "All fetchers failed"},
        500: {"model": ErrorResponse, "description": "Server error"},
    },
    tags=["stocks"],
)
@endpoint_meta(
    summary="公司画像",
    markets=["csi"],
    capabilities=["STOCK_INFO"],
)
@map_errors
@cache_endpoint(
    cache_fn=lambda *args, **kwargs: get_stock_info_cache(),
    key_builder=lambda code: make_stock_info_cache_key(code),
    hit_label="stock_info",
)
def get_stock_info(code: str = Path(max_length=20)) -> StockInfoResponse:
    """公司画像（Zhitu → Myquant failover）。A 股限定."""
    manager = get_manager()
    data, source = manager.get_stock_info(code)
    return StockInfoResponse(**data, source=source)


# ============================================================================
# Realtime quote
# ============================================================================


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
@map_errors
@cache_endpoint(
    cache_fn=lambda *args, **kwargs: get_quote_cache(),
    key_builder=lambda stock_code: make_quote_cache_key(stock_code),
    hit_label="quote",
)
def get_quote(
    stock_code: str = Path(max_length=20, description="Stock code"),
) -> StockQuote:
    """Get realtime quote for a stock.

    Note:
        Index codes are not supported. Use /indices/{index_code}/quote instead.
    """
    _reject_index_code(stock_code, endpoint_kind="quote")

    manager = get_manager()
    quote = manager.get_realtime_quote(stock_code)

    if quote is None:
        raise HTTPException(
            status_code=404,
            detail={"error": "not_found", "message": f"Quote not available for {stock_code}"},
        )

    return StockQuote(
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
        pe_ttm=quote.pe_ratio,
        pe_static=None,
        pb=quote.pb_ratio,
        mcap_yi=quote.total_mv / 1e8 if quote.total_mv else None,
        float_mcap_yi=quote.circ_mv / 1e8 if quote.circ_mv else None,
        turnover_pct=quote.turnover_rate,
        amplitude_pct=quote.amplitude,
        limit_up=None,
        limit_down=None,
        vol_ratio=quote.volume_ratio,
    )


# ============================================================================
# History K-line (with optional indicators)
# ============================================================================


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
@map_errors
@cache_endpoint(
    cache_fn=lambda stock_code, period, days, start_date, end_date, adjust, indicators: (
        get_history_cache(_period_to_freq(period))
    ),
    key_builder=lambda stock_code, period, days, start_date, end_date, adjust, indicators: (
        make_history_cache_key(
            stock_code,
            _period_to_freq(period),
            days,
            start_date,
            end_date,
            adjust or None,
            _parse_indicators_param(indicators),
        )
    ),
    hit_label="history",
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
    """Get historical K-line data for a stock, optionally with technical indicators.

    Note:
        Index codes are not supported. Use /indices/{index_code}/history instead.
    """
    _reject_index_code(stock_code, endpoint_kind="history")

    adj_value = adjust or None

    # Parse indicators before issuing the upstream call (used by both the
    # cache key builder and the lookback expansion below).
    requested_indicators = _parse_indicators_param(indicators)

    # If indicators are requested, fetch enough history to warm them up.
    actual_days = days
    if requested_indicators:
        extra_lookback = compute_lookback(requested_indicators)
        if extra_lookback > 0:
            actual_days = max(days, extra_lookback)

    manager = get_manager()
    df, source = manager.get_kline_data(
        stock_code,
        start_date=start_date,
        end_date=end_date,
        days=actual_days,
        frequency=_period_to_freq(period),
        adjust=adj_value,
    )

    df = _apply_indicators(df, requested_indicators, days=days, actual_days=actual_days)

    stock_name = stock_cache.get_stock_name(stock_code, manager=manager)

    records = df.to_dict("records")
    data = [_build_kline_data(row, _format_date) for row in records]

    return StockHistoryResponse(
        code=stock_code, stock_name=stock_name, period=period, data=data, source=source
    )


# ============================================================================
# Intraday minute K-line
# ============================================================================


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
@map_errors
@cache_endpoint(
    cache_fn=lambda *args, **kwargs: get_stock_intraday_cache(),
    key_builder=lambda stock_code, period, adjust: make_stock_intraday_cache_key(
        stock_code, period, adjust
    ),
    hit_label="stock_intraday",
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
    """Get intraday minute-level data for a stock.

    Note:
        - period=1 is only supported by Akshare (Zhitu does not support 1-minute data)
        - Intraday data is only available for A-share stocks.
    """
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

    manager = get_manager()
    df, source = manager.get_intraday_data(stock_code, period=period, adjust=adjust)
    stock_name = stock_cache.get_stock_name(stock_code, manager=manager)

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
        source=source,
    )


# ============================================================================
# Per-stock dragon-tiger (full-market version lives in data.py)
# ============================================================================


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
@map_errors
@cache_endpoint(
    cache_fn=lambda *args, **kwargs: get_dragontiger_cache(),
    key_builder=lambda stock_code, trade_date, look_back: make_dragon_tiger_cache_key(
        stock_code, trade_date, look_back
    ),
    hit_label="dragontiger",
)
def get_dragon_tiger(
    stock_code: str = Path(max_length=20),
    trade_date: str = Query(default="", description="Trade date (YYYY-MM-DD)"),
    look_back: int = Query(default=30, ge=1, le=365),
) -> DragonTigerResponse:
    manager = get_manager()
    data, source = manager.get_dragon_tiger(stock_code, trade_date, look_back)
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
        source=source,
    )


# ============================================================================
# Margin / block-trade / holder-num / dividend
# ============================================================================


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
@map_errors
@cache_endpoint(
    cache_fn=lambda *args, **kwargs: get_margin_cache(),
    key_builder=lambda stock_code, page_size: make_margin_cache_key(stock_code, page_size),
    hit_label="margin",
)
def get_margin(
    stock_code: str = Path(max_length=20),
    page_size: int = Query(default=30, ge=1, le=100),
) -> MarginTradingResponse:
    manager = get_manager()
    data, source = manager.get_margin_trading(stock_code, page_size)
    stock_name = stock_cache.get_stock_name(stock_code, manager=manager)
    return MarginTradingResponse(
        code=stock_code,
        name=stock_name or "",
        records=[MarginTradingRecord(**r) for r in data],
        source=source,
    )


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
@map_errors
@cache_endpoint(
    cache_fn=lambda *args, **kwargs: get_block_trade_cache(),
    key_builder=lambda stock_code, page_size: make_block_trade_cache_key(stock_code, page_size),
    hit_label="block_trade",
)
def get_block_trade(
    stock_code: str = Path(max_length=20),
    page_size: int = Query(default=20, ge=1, le=100),
) -> BlockTradeResponse:
    manager = get_manager()
    data, source = manager.get_block_trade(stock_code, page_size)
    stock_name = stock_cache.get_stock_name(stock_code, manager=manager)
    records = [BlockTradeRecord(**r) for r in data]
    return BlockTradeResponse(
        code=stock_code,
        name=stock_name or "",
        records=records,
        total=len(records),
        source=source,
    )


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
@map_errors
@cache_endpoint(
    cache_fn=lambda *args, **kwargs: get_holder_num_cache(),
    key_builder=lambda stock_code, page_size: make_holder_num_cache_key(stock_code, page_size),
    hit_label="holder_num",
)
def get_holder_num(
    stock_code: str = Path(max_length=20),
    page_size: int = Query(default=10, ge=1, le=50),
) -> HolderNumResponse:
    manager = get_manager()
    data, source = manager.get_holder_num_change(stock_code, page_size)
    stock_name = stock_cache.get_stock_name(stock_code, manager=manager)
    return HolderNumResponse(
        code=stock_code,
        name=stock_name or "",
        records=[HolderNumRecord(**r) for r in data],
        source=source,
    )


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
@map_errors
@cache_endpoint(
    cache_fn=lambda *args, **kwargs: get_dividend_cache(),
    key_builder=lambda stock_code, page_size: make_dividend_cache_key(stock_code, page_size),
    hit_label="dividend",
)
def get_dividend(
    stock_code: str = Path(max_length=20),
    page_size: int = Query(default=20, ge=1, le=100),
) -> DividendResponse:
    manager = get_manager()
    data, source = manager.get_dividend(stock_code, page_size)
    stock_name = stock_cache.get_stock_name(stock_code, manager=manager)
    return DividendResponse(
        code=stock_code,
        name=stock_name or "",
        records=[DividendRecord(**r) for r in data],
        source=source,
    )


# ============================================================================
# Fund flow (minute-level + 120-day)
# ============================================================================


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
@map_errors
@cache_endpoint(
    cache_fn=lambda *args, **kwargs: get_fund_flow_cache(),
    key_builder=lambda stock_code: make_fund_flow_cache_key(stock_code),
    hit_label="fund_flow",
)
def get_fund_flow(stock_code: str = Path(max_length=20)) -> FundFlowResponse:
    """Get minute-level capital flow for a stock."""
    manager = get_manager()
    data, source = manager.get_fund_flow_minute(stock_code)
    stock_name = stock_cache.get_stock_name(stock_code, manager=manager)
    return FundFlowResponse(
        code=stock_code,
        name=stock_name or "",
        type="minute",
        records=[FundFlowMinuteRecord(**r) for r in data],
        source=source,
    )


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
    fetcher_method="get_fund_flow_120d",  # default get_fund_flow_minute is minute-level variant
)
@map_errors
@cache_endpoint(
    cache_fn=lambda *args, **kwargs: get_fund_flow_daily_cache(),
    key_builder=lambda stock_code: make_fund_flow_daily_cache_key(stock_code),
    hit_label="fund_flow_daily",
)
def get_fund_flow_daily(stock_code: str = Path(max_length=20)) -> FundFlowResponse:
    """Get 120-day capital flow history for a stock."""
    manager = get_manager()
    data, source = manager.get_fund_flow_120d(stock_code)
    stock_name = stock_cache.get_stock_name(stock_code, manager=manager)
    return FundFlowResponse(
        code=stock_code,
        name=stock_name or "",
        type="daily",
        records=[FundFlowDailyRecord(**r) for r in data],
        source=source,
    )


# ============================================================================
# Reports + announcements
# ============================================================================


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
@map_errors
@cache_endpoint(
    cache_fn=lambda *args, **kwargs: get_reports_cache(),
    key_builder=lambda stock_code, max_pages: make_reports_cache_key(stock_code, max_pages),
    hit_label="reports",
)
def get_reports(
    stock_code: str = Path(max_length=20),
    max_pages: int = Query(default=3, ge=1, le=10, description="Max pages"),
) -> ReportResponse:
    """Get research reports for a stock."""
    manager = get_manager()
    data, source = manager.get_reports(stock_code, max_pages)
    stock_name = stock_cache.get_stock_name(stock_code, manager=manager)
    reports = [ReportRecord(**r) for r in data]
    return ReportResponse(
        code=stock_code,
        name=stock_name or "",
        reports=reports,
        total=len(reports),
        source=source,
    )


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
@map_errors
def get_report_pdf(
    stock_code: str = Path(max_length=20),
    report_id: str = Path(description="info_code"),
) -> ReportPDFResponse:
    """Download a research report PDF. Returns local file path."""
    manager = get_manager()
    path, url = manager.get_report_pdf(report_id)
    return ReportPDFResponse(report_id=report_id, download_path=path, url=url)


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
@map_errors
@cache_endpoint(
    cache_fn=lambda *args, **kwargs: get_announcements_cache(),
    key_builder=lambda stock_code, page_size: make_announcements_cache_key(stock_code, page_size),
    hit_label="announcements",
)
def get_announcements(
    stock_code: str = Path(max_length=20),
    page_size: int = Query(default=30, ge=1, le=100, description="Page size"),
) -> AnnouncementResponse:
    """Get corporate announcements for a stock."""
    manager = get_manager()
    data, source = manager.get_announcements(stock_code, page_size)
    stock_name = stock_cache.get_stock_name(stock_code, manager=manager)
    announcements = [AnnouncementRecord(**r) for r in data]
    return AnnouncementResponse(
        code=stock_code,
        name=stock_name or "",
        announcements=announcements,
        total=len(announcements),
        source=source,
    )
