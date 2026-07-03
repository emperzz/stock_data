"""Per-stock endpoints. Everything under ``/stocks/{code}/...`` plus the
related dragon-tiger / margin / block-trade / holder-num / dividend / fund-flow /
reports / announcements / info / quote / kline surfaces.

The stock-list endpoint (``GET /stocks``) lives in :mod:`.calendar` because
it's a list-level query, not per-stock.
"""

from fastapi import HTTPException, Path, Query, Request

from ...data_provider.persistence import stock_list
from ...data_provider.utils.normalize import code_to_exchange
from ..cache import (
    cache_endpoint,
    get_announcements_cache,
    get_block_trade_cache,
    get_dividend_cache,
    get_dragontiger_cache,
    get_fund_flow_cache,
    get_fund_flow_daily_cache,
    get_holder_num_cache,
    get_kline_cache,
    get_margin_cache,
    get_quote_cache,
    get_reports_cache,
    get_stock_info_cache,
    make_announcements_cache_key,
    make_block_trade_cache_key,
    make_dividend_cache_key,
    make_dragon_tiger_cache_key,
    make_fund_flow_cache_key,
    make_fund_flow_daily_cache_key,
    make_holder_num_cache_key,
    make_kline_cache_key,
    make_margin_cache_key,
    make_quote_cache_key,
    make_reports_cache_key,
    make_stock_info_cache_key,
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
    _expand_indicator_lookback,
    _forbid_quote_params,
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
    """公司画像（Zhitu → Myquant failover）。A 股限定.

    ``exchange`` 由 code prefix 推断 (SH/SZ/BJ), 不依赖上游字段 — 3 个
    fetcher (Zhitu/Myquant/Zzshare) 的 get_stock_info payload 均不含
    exchange, 走 prefix 推断确定性更高且零成本。
    """
    manager = get_manager()
    data, source = manager.get_stock_info(code)
    return StockInfoResponse(
        **data,
        source=source,
        exchange=code_to_exchange(code),
    )


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
    capabilities=["STOCK_REALTIME_QUOTE"],
)
@map_errors
@cache_endpoint(
    cache_fn=lambda *args, **kwargs: get_quote_cache(),
    key_builder=lambda request, stock_code: make_quote_cache_key(stock_code),
    hit_label="quote",
)
def get_quote(
    request: Request,
    stock_code: str = Path(max_length=20, description="Stock code"),
) -> StockQuote:
    """Get realtime quote for a stock.

    Note:
        Index codes are not supported. Use /indices/{index_code}/quote instead.
    """
    _forbid_quote_params(request)
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
        stock_name=quote.name or stock_list.get_stock_name(stock_code, manager=manager),
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
# Unified K-line (daily + minute)
# ============================================================================


@router.get(
    "/stocks/{code}/kline",
    response_model=StockHistoryResponse,
    responses={
        400: {"model": ErrorResponse, "description": "Invalid period/date"},
        422: {"model": ErrorResponse, "description": "No fetcher supports request"},
        500: {"model": ErrorResponse, "description": "Server error"},
    },
    tags=["stocks"],
)
@endpoint_meta(
    summary="K 线（统一入口：d/w/m + 1m/5m/15m/30m/60m）",
    markets=["csi", "hk", "us"],
    capabilities=["STOCK_KLINE"],
)
@map_errors
@cache_endpoint(
    cache_fn=lambda code, period, days, start_date, end_date, adjust, indicators: (
        get_kline_cache(_period_to_freq(period))
    ),
    key_builder=lambda code, period, days, start_date, end_date, adjust, indicators: (
        make_kline_cache_key(
            code,
            _period_to_freq(period),
            days,
            start_date,
            end_date,
            adjust or None,
            _parse_indicators_param(indicators),
        )
    ),
    hit_label="kline",
)
def get_kline(
    code: str = Path(max_length=20),
    period: str = Query(
        default="daily",
        pattern="^(daily|weekly|monthly|1m|5m|15m|30m|60m)$",
    ),
    days: int = Query(default=30, ge=1, le=365),
    start_date: str | None = Query(default=None),
    end_date: str | None = Query(default=None),
    adjust: str = Query(default="", pattern="^(qfq|hfq)?$"),
    indicators: str | None = Query(default=None),
) -> StockHistoryResponse:
    """Unified K-line endpoint: daily/weekly/monthly + minute (1m/5m/15m/30m/60m).

    ``supports_kline`` at manager level decides fetcher availability;
    no route-layer reject for minute+adjust.
    """
    _reject_index_code(code, endpoint_kind="kline")
    freq = _period_to_freq(period)

    requested_indicators = _parse_indicators_param(indicators)
    actual_days = _expand_indicator_lookback(requested_indicators, days)

    manager = get_manager()
    df, source = manager.get_kline_data(
        code,
        start_date=start_date,
        end_date=end_date,
        days=actual_days,
        frequency=freq,
        adjust=adjust or None,
    )
    df = _apply_indicators(df, requested_indicators, days=days, actual_days=actual_days)
    name = stock_list.get_stock_name(code, manager=manager)

    records = df.to_dict("records")
    return StockHistoryResponse(
        code=code,
        stock_name=name,
        period=period,
        data=[_build_kline_data(r, _format_date) for r in records],
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
    stock_name = stock_list.get_stock_name(stock_code, manager=manager)
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
    stock_name = stock_list.get_stock_name(stock_code, manager=manager)
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
    stock_name = stock_list.get_stock_name(stock_code, manager=manager)
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
    stock_name = stock_list.get_stock_name(stock_code, manager=manager)
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
    stock_name = stock_list.get_stock_name(stock_code, manager=manager)
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
    stock_name = stock_list.get_stock_name(stock_code, manager=manager)
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
    stock_name = stock_list.get_stock_name(stock_code, manager=manager)
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
    stock_name = stock_list.get_stock_name(stock_code, manager=manager)
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
    stock_name = stock_list.get_stock_name(stock_code, manager=manager)
    announcements = [AnnouncementRecord(**r) for r in data]
    return AnnouncementResponse(
        code=stock_code,
        name=stock_name or "",
        announcements=announcements,
        total=len(announcements),
        source=source,
    )
