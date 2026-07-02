"""
Pydantic schemas for API request/response models.
"""

from typing import Any, Literal

from pydantic import BaseModel, Field, model_serializer, model_validator


class _UpstreamSanitizedModel(BaseModel):
    """Mixin: pydantic v2 strict-input handling for upstream data.

    EastMoneyFetcher / CninfoFetcher sometimes emit ``None`` for fields
    that the schema declares as non-Optional ``str`` / ``float``, and
    ``""`` for fields declared as ``float | None``. Pydantic v2 raises
    ``ValidationError`` on these. The pre-validator below normalizes the
    raw dict before field validation runs, so the schema's stated
    defaults (``str = ""``, ``float = 0``, ``float | None = None``) are
    honored in JSON output. The API contract (non-null fields stay
    non-null; Optional fields may be null) is preserved.

    Only affects three response models whose upstream data is known to
    emit these quirks (DividendRecord, ReportRecord, AnnouncementRecord).
    Other models continue to validate strictly.
    """

    @model_validator(mode="before")
    @classmethod
    def _sanitize(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        for field_name, field_info in cls.model_fields.items():
            if field_name not in data:
                continue
            value = data[field_name]
            if value is None:
                # None for a field with a non-None default → use that default.
                # (Field with default None is Optional — leave as None.)
                if field_info.default is not None:
                    data[field_name] = field_info.default
            elif value == "" and field_info.default is None:
                # Empty string for an Optional field → None. (pydantic v2
                # cannot parse "" as float; cninfo also sometimes emits ""
                # where None was meant.)
                data[field_name] = None
        return data


class StockQuote(BaseModel):
    """Stock realtime quote response."""

    code: str = Field(description="Stock code")
    stock_name: str = Field(default="", description="Stock name")
    source: str = Field(default="", description="Data source")
    current_price: float = Field(default=0.0, description="Current price")
    change: float | None = Field(default=None, description="Price change amount")
    change_percent: float | None = Field(default=None, description="Price change percent")
    open: float | None = Field(default=None, description="Opening price")
    high: float | None = Field(default=None, description="Highest price")
    low: float | None = Field(default=None, description="Lowest price")
    prev_close: float | None = Field(default=None, description="Previous close price")
    volume: int | None = Field(default=None, description="Trading volume (股/shares)")
    volume_unit: str = Field(default="share", description="Volume unit. Always 'share' (股) per spec §3.4.")
    amount: float | None = Field(default=None, description="Trading amount")
    update_time: str | None = Field(default=None, description="Update timestamp")
    # Valuation metrics (from Tencent财经)
    pe_ttm: float | None = Field(default=None, description="PE(TTM)")
    pe_static: float | None = Field(default=None, description="PE(静)")
    pb: float | None = Field(default=None, description="PB (市净率)")
    mcap_yi: float | None = Field(default=None, description="Total market cap (亿元)")
    float_mcap_yi: float | None = Field(default=None, description="Float market cap (亿元)")
    turnover_pct: float | None = Field(default=None, description="Turnover rate (%)")
    amplitude_pct: float | None = Field(default=None, description="Amplitude (%)")
    limit_up: float | None = Field(default=None, description="Limit up price (涨停价)")
    limit_down: float | None = Field(default=None, description="Limit down price (跌停价)")
    vol_ratio: float | None = Field(default=None, description="Volume ratio (量比)")


class KLineData(BaseModel):
    """Single K-line data point.

    The ``indicators`` field is conditionally serialized: it is omitted
    from the JSON response entirely when its value is None / empty. This
    keeps the response clean when the caller did not pass
    ``?indicators=...``. The ``amount`` and ``change_percent`` fields
    keep their "null when missing" semantics (always present, possibly
    null).
    """

    date: str = Field(description="Date")
    open: float = Field(description="Opening price")
    high: float = Field(description="Highest price")
    low: float = Field(description="Lowest price")
    close: float = Field(description="Closing price")
    volume: int = Field(description="Volume (in shares / 股; invariant per spec §3.4)")
    volume_unit: Literal["share"] = Field(
        default="share",
        description="Volume unit. Always 'share' (股) — invariant enforced by fetcher "
        "normalization per spec §3.4.",
    )
    amount: float | None = Field(default=None, description="Amount")
    change_percent: float | None = Field(default=None, description="Change percent")
    # Per-bar indicator values. Populated only when the request
    # supplies `?indicators=...` (or a JSON body with `indicators`).
    # Keys are indicator-prefixed (e.g. ma5, macd_dif, kdj_k, boll_upper).
    # Each value is the float value at this bar or null if the
    # indicator is not yet defined at this bar. Default None so the
    # model_serializer below can drop the key entirely.
    indicators: dict[str, float | None] | None = Field(
        default=None,
        description="Per-bar technical indicator values keyed by `<indicator>_<field>`",
    )

    @model_serializer
    def _serialize(self) -> dict[str, Any]:
        # Always-present core + nullable-but-always-serialized fields.
        data: dict[str, Any] = {
            "date": self.date,
            "open": self.open,
            "high": self.high,
            "low": self.low,
            "close": self.close,
            "volume": self.volume,
            "volume_unit": self.volume_unit,
            "amount": self.amount,
            "change_percent": self.change_percent,
        }
        # indicators: only emit when populated. None / empty means the
        # caller didn't ask for them — drop the key from the response.
        if self.indicators:
            data["indicators"] = self.indicators
        return data


class StockHistoryResponse(BaseModel):
    """Stock historical K-line response."""

    code: str = Field(description="Stock code")
    stock_name: str = Field(default="", description="Stock name")
    period: str = Field(default="daily", description="K-line period")
    data: list[KLineData] = Field(default_factory=list, description="K-line data points")
    source: str = Field(
        default="",
        description="数据来源 fetcher 名 (e.g. tushare, akshare) 或 'persistence'",
    )


class ErrorResponse(BaseModel):
    """Error response."""

    error: str = Field(description="Error code")
    message: str = Field(description="Error message")


class IndicatorCatalogEntry(BaseModel):
    """One entry in the /indicators/catalog response."""

    key: str = Field(description="Indicator identifier (e.g. macd, kdj)")
    input_shape: str = Field(description="Required input shape: 'closes' or 'ohlcv'")
    default_options: dict[str, Any] = Field(
        default_factory=dict,
        description="Default options for this indicator",
    )
    output_columns: list[str] = Field(
        default_factory=list,
        description="Dict keys this indicator produces (e.g. ['macd_dif', 'macd_dea', 'macd_hist'])",
    )
    default_lookback: int = Field(
        default=0,
        description="Number of historical bars required to fully warm up the indicator with defaults",
    )


class IndicatorCatalogResponse(BaseModel):
    """Response for /indicators/catalog."""

    indicators: list[IndicatorCatalogEntry] = Field(
        default_factory=list, description="Available technical indicators"
    )


class SourceHealth(BaseModel):
    """Individual source health status."""

    name: str = Field(description="Fetcher name")
    state: str = Field(description="Circuit breaker state: closed/open/half_open")
    available: bool = Field(description="Whether the source can be called")
    last_success_time: float | None = Field(default=None, description="Unix timestamp of last successful call")
    last_failure_time: float | None = Field(default=None, description="Unix timestamp of last failure")
    failure_count: int = Field(default=0, description="Consecutive failure count")
    # Set when the fetcher wasn't registered at startup (is_available()==False).
    # Logic-driven message from `fetcher.unavailable_reason()` — e.g.
    # "TUSHARE_TOKEN not set" or "ZHITU_TOKEN not set". Surfaces blind spots
    # so operators can tell missing-config from a runtime outage.
    unavailable_reason: str | None = Field(
        default=None,
        description="Why this fetcher is unavailable (env var / SDK missing). None when registered.",
    )


class HealthResponse(BaseModel):
    """Health check response."""

    status: str = Field(default="ok", description="Service status: ok/degraded/unhealthy")
    version: str = Field(default="0.1.0", description="Server version")
    sources: list[SourceHealth] | None = Field(default=None, description="Per-source health details (only when details=true)")


class IndexInfo(BaseModel):
    """Index information response."""

    code: str = Field(description="Index code (e.g., 000300, SPX, HSI)")
    name: str = Field(description="Index name (e.g., 沪深300, S&P 500)")
    market: str = Field(description="Market type: csi/hk/us")


class StockInfo(BaseModel):
    """Stock information response."""

    code: str = Field(description="Stock code (e.g., 600519, AAPL, HK00700)")
    name: str = Field(description="Stock name")
    market: str = Field(description="Market type: csi/hk/us")
    exchange: str | None = Field(
        default=None,
        description="Exchange code (SH/SZ/BJ) when known; null otherwise. "
        "Clients may derive from code prefix as a fallback.",
    )


class TradeCalendarResponse(BaseModel):
    """Trade calendar response."""

    trade_dates: list[str] = Field(description="List of trade dates (YYYY-MM-DD), sorted ascending")
    latest_date: str | None = Field(description="Latest trade date in the calendar")
    total: int = Field(description="Total number of trade dates")


class IntradayData(BaseModel):
    """Single intraday minute-level data point."""

    time: str = Field(description="Time (HH:MM:SS)")
    open: float = Field(description="Opening price")
    high: float = Field(description="Highest price")
    low: float = Field(description="Lowest price")
    close: float = Field(description="Closing price")
    volume: int = Field(description="Volume (in shares / 股; invariant per spec §3.4)")
    volume_unit: Literal["share"] = Field(
        default="share",
        description="Volume unit. Always 'share' (股) — invariant enforced by fetcher "
        "normalization per spec §3.4.",
    )
    amount: float | None = Field(default=None, description="Amount")


class IntradayResponse(BaseModel):
    """Intraday minute-level data response."""

    code: str = Field(description="Stock code")
    stock_name: str = Field(default="", description="Stock name")
    period: str = Field(description="Minute period (1m/5m/15m/30m/60m)")
    adjust: str = Field(default="", description="Adjustment type")
    date: str = Field(description="Trade date (YYYY-MM-DD)")
    data: list[IntradayData] = Field(default_factory=list, description="Minute-level data points")
    source: str = Field(
        default="",
        description="数据来源 fetcher 名 (e.g. tushare, akshare) 或 'persistence'",
    )


class BoardInfo(BaseModel):
    """Board information."""

    code: str = Field(description="Board code (e.g., BK1048)")
    name: str = Field(description="Board name (e.g., 互联网服务)")
    price: float | None = Field(default=None, description="Latest price (requires include_quote=True)")
    change_pct: float | None = Field(default=None, description="Change percent (requires include_quote=True)")
    change_amount: float | None = Field(default=None, description="Change amount (requires include_quote=True)")
    volume: int | None = Field(default=None, description="Volume (requires include_quote=True)")
    amount: float | None = Field(default=None, description="Amount (requires include_quote=True)")
    turnover_rate: float | None = Field(default=None, description="Turnover rate (requires include_quote=True)")
    total_mv: float | None = Field(default=None, description="Total market value (requires include_quote=True)")
    up_count: int | None = Field(default=None, description="Number of rising stocks (requires include_quote=True)")
    down_count: int | None = Field(default=None, description="Number of falling stocks (requires include_quote=True)")
    leading_stock: str | None = Field(default=None, description="Leading stock name (requires include_quote=True)")
    leading_stock_pct: float | None = Field(default=None, description="Leading stock change percent (requires include_quote=True)")


class BoardStockInfo(BaseModel):
    """Stock in a board, optionally with quote data."""

    code: str = Field(description="Stock code")
    name: str = Field(default="", description="Stock name")
    price: float | None = Field(default=None, description="Current price")
    change_pct: float | None = Field(default=None, description="Change percent")
    volume: int | None = Field(default=None, description="Volume")


class BoardListResponse(BaseModel):
    """Response for board list endpoint."""

    data: list[BoardInfo] = Field(default_factory=list, description="List of boards")
    source: str = Field(
        default="",
        description="数据来源 fetcher 名 或 'persistence'",
    )


class BoardStocksResponse(BaseModel):
    """Response for board stocks endpoint."""

    board: BoardInfo = Field(description="Board info")
    stocks: list[BoardStockInfo] = Field(default_factory=list, description="Stocks in the board")
    query_source: str = Field(default="eastmoney", description="用户请求时传入的 source 参数")
    data_source: str = Field(default="", description="实际数据来源 fetcher 名 或 'persistence'")


class BoardKlineResponse(BaseModel):
    """Response for board K-line endpoint (`/boards/{board_code}/history`)."""

    board_code: str = Field(description="Board code (source-specific; echoed verbatim)")
    board_name: str = Field(default="", description="Board name (best-effort lookup; may be empty)")
    period: str = Field(
        default="daily",
        description=(
            "K-line period: 'daily'/'weekly'/'monthly' or '5m'/'15m'/'30m'/'60m'. "
            "Source-dependent — zzshare and ths are daily-only."
        ),
    )
    data: list[KLineData] = Field(default_factory=list, description="K-line data points")
    source: str = Field(
        default="",
        description=(
            "Data source fetcher name — one of "
            "'EastMoneyFetcher', 'ZzshareFetcher', 'ThsFetcher'"
        ),
    )


class StockBoardInfo(BaseModel):
    """A board that a stock belongs to."""

    code: str = Field(description="Board code (source-specific, e.g. 'sw_yx' for Zhitu)")
    name: str = Field(description="Board full name (e.g. 'A股-申万行业-银行')")
    type: str = Field(description="Board type: concept / industry / index / special")
    subtype: str = Field(
        default="",
        description="Source-specific subtype (e.g. '申万行业' for Zhitu, "
        "'concept' for EastMoney)",
    )
    source: str = Field(
        description="eastmoney / zhitu / zzshare — which source provided this entry. "
        "Always present after endpoint merge (was implicit before).",
    )


class StockBoardsResponse(BaseModel):
    """Unified response for /stocks/{stock_code}/boards endpoint."""

    stock_code: str = Field(description="Stock code queried")
    source: str = Field(
        default="",
        description="数据来源 fetcher 名 (e.g. 'zhitu'), 'persistence' on cache hit, "
        "'merged' when multiple sources were aggregated.",
    )
    data: list[StockBoardInfo] = Field(
        default_factory=list,
        description="Boards the stock belongs to. Each entry carries its source.",
    )
    cold_sources: list[str] = Field(
        default_factory=list,
        description="Sources with no membership data for this stock. "
        "Always present (empty list = all requested sources returned data).",
    )


class IndexQuote(BaseModel):
    """Index realtime quote response."""

    code: str = Field(description="Index code")
    name: str = Field(default="", description="Index name")
    source: str = Field(default="", description="Data source")
    current_price: float = Field(default=0.0, description="Current price")
    change: float | None = Field(default=None, description="Price change amount")
    change_percent: float | None = Field(default=None, description="Price change percent")
    open: float | None = Field(default=None, description="Opening price")
    high: float | None = Field(default=None, description="Highest price")
    low: float | None = Field(default=None, description="Lowest price")
    prev_close: float | None = Field(default=None, description="Previous close price")
    volume: int | None = Field(default=None, description="Trading volume (股/shares)")
    volume_unit: str = Field(default="share", description="Volume unit. Always 'share' (股) per spec §3.4.")
    amount: float | None = Field(default=None, description="Trading amount")
    update_time: str | None = Field(default=None, description="Update timestamp")


class IndexHistoryResponse(BaseModel):
    """Index historical K-line response."""

    code: str = Field(description="Index code")
    name: str = Field(default="", description="Index name")
    period: str = Field(default="daily", description="K-line period: daily/weekly/monthly")
    data: list[KLineData] = Field(default_factory=list, description="K-line data points")
    source: str = Field(
        default="",
        description="数据来源 fetcher 名 (e.g. tushare, akshare) 或 'persistence'",
    )


class IndexIntradayResponse(BaseModel):
    """Index intraday minute-level data response."""

    code: str = Field(description="Index code")
    name: str = Field(default="", description="Index name")
    period: str = Field(description="Minute period (1m/5m/15m/30m/60m)")
    date: str = Field(description="Trade date (YYYY-MM-DD)")
    data: list[IntradayData] = Field(default_factory=list, description="Minute-level data points")
    source: str = Field(
        default="",
        description="数据来源 fetcher 名 (e.g. tushare, akshare) 或 'persistence'",
    )


class ZTPoolStock(BaseModel):
    """Single stock in a ZT (涨跌停) pool."""

    code: str = Field(description="Stock code")
    name: str = Field(default="", description="Stock name")
    price: float | None = Field(default=None, description="Latest price")
    change_pct: float | None = Field(default=None, description="Change percent (%)")
    amount: float | None = Field(default=None, description="Trading amount (元)")
    circ_mv: float | None = Field(default=None, description="Circulating market value (元)")
    total_mv: float | None = Field(default=None, description="Total market value (元)")
    turnover_rate: float | None = Field(default=None, description="Turnover rate (%)")
    lb_count: int | None = Field(default=None, description="Consecutive limit-up count (涨停连板数) / 连续跌停次数")
    first_seal_time: str | None = Field(default=None, description="First seal time (HH:mm:ss)")
    last_seal_time: str | None = Field(default=None, description="Last seal time (HH:mm:ss)")
    seal_amount: float | None = Field(default=None, description="Seal amount (封板资金/封单资金, 元)")
    seal_count: int | None = Field(default=None, description="Seal break count (炸板次数)")
    zt_count: str | None = Field(default=None, description="Limit-up statistics (x天/y板)")


class ZTPoolResponse(BaseModel):
    """ZT (涨跌停) pool response."""

    date: str = Field(description="Pool date (YYYY-MM-DD)")
    type: str = Field(description="Pool type: zt (涨停) / dt (跌停) / zbgc (炸板)")
    total: int = Field(description="Total number of stocks in the pool")
    stocks: list[ZTPoolStock] = Field(default_factory=list, description="List of stocks in the pool")
    source: str = Field(
        default="",
        description="数据来源 fetcher 名 或 'persistence' (历史日期的池数据从 SQLite 读取)",
    )


class DragonTigerSeat(BaseModel):
    """龙虎榜席位"""
    name: str = Field(default="", description="营业部名称")
    buy_wan: float = Field(default=0, description="买入金额(万元)")
    sell_wan: float = Field(default=0, description="卖出金额(万元)")
    net_wan: float = Field(default=0, description="净买入(万元)")


class DragonTigerInstitution(BaseModel):
    """机构买卖统计"""
    buy_amt: float = Field(default=0, description="机构买入(万元)")
    sell_amt: float = Field(default=0, description="机构卖出(万元)")
    net_amt: float = Field(default=0, description="机构净买入(万元)")


class DragonTigerRecord(BaseModel):
    """上榜记录"""
    date: str = Field(default="", description="上榜日期")
    reason: str = Field(default="", description="上榜原因")
    net_buy_wan: float = Field(default=0, description="净买入(万元)")
    turnover_pct: float = Field(default=0, description="换手率(%)")


class DragonTigerResponse(BaseModel):
    """个股龙虎榜响应"""
    code: str = Field(description="股票代码")
    name: str = Field(default="", description="股票名称")
    records: list[DragonTigerRecord] = Field(default_factory=list)
    seats: dict[str, list[DragonTigerSeat]] = Field(default_factory=dict)
    institution: DragonTigerInstitution = Field(default_factory=DragonTigerInstitution)
    source: str = Field(
        default="",
        description="数据来源 fetcher 名 (e.g. eastmoney) 或 'persistence'",
    )


class DailyDragonTigerStock(BaseModel):
    """全市场龙虎榜个股"""
    code: str = Field(description="股票代码")
    name: str = Field(default="", description="股票名称")
    reason: str = Field(default="", description="上榜原因")
    close: float = Field(default=0, description="收盘价")
    change_pct: float = Field(default=0, description="涨跌幅(%)")
    net_buy_wan: float = Field(default=0, description="净买入(万元)")
    buy_wan: float = Field(default=0, description="买入金额(万元)")
    sell_wan: float = Field(default=0, description="卖出金额(万元)")
    turnover_pct: float = Field(default=0, description="换手率(%)")


class DailyDragonTigerResponse(BaseModel):
    """全市场龙虎榜响应"""
    date: str = Field(description="交易日期")
    total: int = Field(default=0, description="上榜总数")
    stocks: list[DailyDragonTigerStock] = Field(default_factory=list)
    source: str = Field(
        default="",
        description="数据来源 fetcher 名 (e.g. eastmoney) 或 'persistence'",
    )


class MarginTradingRecord(BaseModel):
    """融资融券记录"""
    date: str = Field(default="", description="日期")
    rzye: float = Field(default=0, description="融资余额(元)")
    rzmre: float = Field(default=0, description="融资买入额(元)")
    rzche: float = Field(default=0, description="融资偿还额(元)")
    rqye: float = Field(default=0, description="融券余额(元)")
    rqmcl: float = Field(default=0, description="融券卖出量")
    rqchl: float = Field(default=0, description="融券偿还量")
    rzrqye: float = Field(default=0, description="融资融券余额合计(元)")


class MarginTradingResponse(BaseModel):
    """融资融券响应"""
    code: str = Field(description="股票代码")
    name: str = Field(default="", description="股票名称")
    records: list[MarginTradingRecord] = Field(default_factory=list)
    source: str = Field(
        default="",
        description="数据来源 fetcher 名 (e.g. eastmoney) 或 'persistence'",
    )


class BlockTradeRecord(BaseModel):
    """大宗交易记录"""
    date: str = Field(default="", description="交易日期")
    price: float = Field(default=0, description="成交价")
    close: float = Field(default=0, description="收盘价")
    premium_pct: float = Field(default=0, description="溢价率(%)")
    vol: float = Field(default=0, description="成交量(股)")
    amount: float = Field(default=0, description="成交额(元)")
    buyer: str = Field(default="", description="买方营业部")
    seller: str = Field(default="", description="卖方营业部")


class BlockTradeResponse(BaseModel):
    """大宗交易响应"""
    code: str = Field(description="股票代码")
    name: str = Field(default="", description="股票名称")
    records: list[BlockTradeRecord] = Field(default_factory=list)
    total: int = Field(default=0, description="记录总数")
    source: str = Field(
        default="",
        description="数据来源 fetcher 名 (e.g. eastmoney) 或 'persistence'",
    )


class HolderNumRecord(BaseModel):
    """股东户数记录"""
    date: str = Field(default="", description="报告期")
    holder_num: int = Field(default=0, description="股东户数")
    change_num: int = Field(default=0, description="户数变化")
    change_ratio: float = Field(default=0, description="环比变化(%)")
    avg_shares: float = Field(default=0, description="户均持股")


class HolderNumResponse(BaseModel):
    """股东户数变化响应"""
    code: str = Field(description="股票代码")
    name: str = Field(default="", description="股票名称")
    records: list[HolderNumRecord] = Field(default_factory=list)
    source: str = Field(
        default="",
        description="数据来源 fetcher 名 (e.g. eastmoney) 或 'persistence'",
    )


class DividendRecord(_UpstreamSanitizedModel):
    """分红送转记录"""
    date: str = Field(default="", description="除权除息日")
    bonus_rmb: float = Field(default=0, description="每股派息(税前)")
    transfer_ratio: float = Field(default=0, description="每10股转增")
    bonus_ratio: float = Field(default=0, description="每10股送股")
    plan: str = Field(default="", description="进度")


class DividendResponse(BaseModel):
    """分红送转响应"""
    code: str = Field(description="股票代码")
    name: str = Field(default="", description="股票名称")
    records: list[DividendRecord] = Field(default_factory=list)
    source: str = Field(
        default="",
        description="数据来源 fetcher 名 (e.g. eastmoney) 或 'persistence'",
    )


class FundFlowMinuteRecord(BaseModel):
    """资金流分钟级记录"""
    time: str = Field(default="", description="时间 (HH:mm)")
    main_net: float = Field(default=0, description="主力净流入(元)")
    small_net: float = Field(default=0, description="小单净流入(元)")
    mid_net: float = Field(default=0, description="中单净流入(元)")
    large_net: float = Field(default=0, description="大单净流入(元)")
    super_net: float = Field(default=0, description="超大单净流入(元)")


class FundFlowDailyRecord(BaseModel):
    """资金流日级记录"""
    date: str = Field(default="", description="日期")
    main_net: float = Field(default=0, description="主力净流入(元)")
    small_net: float = Field(default=0, description="小单净流入(元)")
    mid_net: float = Field(default=0, description="中单净流入(元)")
    large_net: float = Field(default=0, description="大单净流入(元)")
    super_net: float = Field(default=0, description="超大单净流入(元)")


class FundFlowResponse(BaseModel):
    """资金流响应"""
    code: str = Field(description="股票代码")
    name: str = Field(default="", description="股票名称")
    type: str = Field(default="minute", description="类型: minute/daily")
    records: list[FundFlowMinuteRecord | FundFlowDailyRecord] = Field(default_factory=list)
    source: str = Field(
        default="",
        description="数据来源 fetcher 名 (e.g. eastmoney) 或 'persistence'",
    )


class HotTopicRecord(BaseModel):
    """热点题材记录"""
    code: str = Field(default="", description="股票代码")
    name: str = Field(default="", description="股票名称")
    reason: str = Field(default="", description="题材归因")
    change_pct: float = Field(default=0, description="涨幅(%)")
    turnover_rate: float = Field(default=0, description="换手率(%)")
    volume: float = Field(default=0, description="成交量")
    amount: float = Field(default=0, description="成交额")
    dde_net: float = Field(default=0, description="大单净量")


class HotTopicResponse(BaseModel):
    """热点题材响应"""
    date: str = Field(description="交易日期")
    total: int = Field(default=0)
    topics: list[HotTopicRecord] = Field(default_factory=list)
    source: str = Field(
        default="",
        description="数据来源 fetcher 名 (e.g. eastmoney) 或 'persistence'",
    )


class NorthFlowRecord(BaseModel):
    """北向资金记录"""
    time: str = Field(default="", description="时间")
    hgt_yi: float | None = Field(default=None, description="沪股通累计净买入(亿元)")
    sgt_yi: float | None = Field(default=None, description="深股通累计净买入(亿元)")


class NorthFlowResponse(BaseModel):
    """北向资金响应"""
    records: list[NorthFlowRecord] = Field(default_factory=list)
    source: str = Field(
        default="",
        description="数据来源 fetcher 名 (e.g. eastmoney) 或 'persistence'",
    )


class ReportRecord(_UpstreamSanitizedModel):
    """研报记录"""
    title: str = Field(default="", description="标题")
    publish_date: str = Field(default="", description="发布日期")
    org: str = Field(default="", description="研究机构")
    info_code: str = Field(default="", description="PDF编号")
    rating: str = Field(default="", description="评级")
    predict_eps_this: float | None = Field(default=None, description="今年EPS预测")
    predict_eps_next: float | None = Field(default=None, description="明年EPS预测")
    predict_eps_next2: float | None = Field(default=None, description="后年EPS预测")


class ReportResponse(BaseModel):
    """研报列表响应"""
    code: str = Field(description="股票代码")
    name: str = Field(default="", description="股票名称")
    reports: list[ReportRecord] = Field(default_factory=list)
    total: int = Field(default=0)
    source: str = Field(
        default="",
        description="数据来源 fetcher 名 (e.g. eastmoney) 或 'persistence'",
    )


class ReportPDFResponse(BaseModel):
    """研报PDF响应"""
    report_id: str = Field(description="info_code")
    download_path: str | None = Field(default=None, description="本地文件路径")
    url: str | None = Field(default=None, description="PDF URL")


class AnnouncementRecord(_UpstreamSanitizedModel):
    """公告记录"""
    title: str = Field(default="", description="标题")
    type: str = Field(default="", description="公告类型")
    date: str = Field(default="", description="发布日期")
    url: str = Field(default="", description="公告链接")


class AnnouncementResponse(BaseModel):
    """公告列表响应"""
    code: str = Field(description="股票代码")
    name: str = Field(default="", description="股票名称")
    announcements: list[AnnouncementRecord] = Field(default_factory=list)
    total: int = Field(default=0)
    source: str = Field(
        default="",
        description="数据来源 fetcher 名 (e.g. eastmoney) 或 'persistence'",
    )


class StockInfoResponse(BaseModel):
    """公司画像 (A 股) — 来自 Zhitu (主) / Myquant (备) 的归一化结果."""

    # 基础识别
    code: str = Field(description="股票代码 (e.g., 600519)")
    name: str = Field(default="", description="中文名")
    ename: str = Field(default="", description="英文名 (Zhitu only)")
    market: str = Field(default="csi", description="市场: csi (本次仅 csi)")

    # 上市与股本
    listed_date: str = Field(default="", description="上市日期 YYYY-MM-DD")
    delisted_date: str = Field(default="", description="退市日期 YYYY-MM-DD (Myquant only)")
    total_shares: float | None = Field(default=None, description="总股本 (万股)")
    float_shares: float | None = Field(default=None, description="流通股本 (万股)")

    # 概念
    concepts: list[str] = Field(default_factory=list, description="概念标签 (Zhitu)")

    # 公司画像
    registered_address: str = Field(default="", description="注册地址 (Zhitu)")
    registered_capital: str = Field(default="", description="注册资本 (Zhitu, 字符串格式如 '9.82亿')")
    legal_representative: str = Field(default="", description="法人代表 (Zhitu)")
    business_scope: str = Field(default="", description="经营范围 (Zhitu)")
    established_date: str = Field(default="", description="成立日期 YYYY-MM-DD (Zhitu)")

    # 董秘联系
    secretary: str = Field(default="", description="董秘姓名 (Zhitu)")
    secretary_phone: str = Field(default="", description="董秘电话 (Zhitu)")
    secretary_email: str = Field(default="", description="董秘邮箱 (Zhitu)")

    # 交易所
    exchange: str | None = Field(
        default=None,
        description="交易所 (SH/SZ/BJ), 由 code prefix 推断, 适用于 A 股; HK/US 返 null",
    )

    # 源
    source: str = Field(default="", description="数据源: 'zhitu' | 'myquant'")


class NewsItem(BaseModel):
    """Single news search result."""
    title: str = Field(default="", description="新闻标题 (已 strip <em>)")
    url: str = Field(description="新闻详情页 URL")
    source_domain: str = Field(default="", description="URL 的域名")
    publish_date: str = Field(default="", description="发布日期 YYYY-MM-DD")
    snippet: str = Field(default="", description="摘要 (已 strip <em>)")
    media_name: str = Field(default="", description="来源媒体名 (e.g. 证券时报网)")


class NewsSearchResponse(BaseModel):
    """News search response."""
    data: list[NewsItem] = Field(default_factory=list)
    total: int = Field(default=0, description="上游 API 报告的命中总数")
    limit: int = Field(default=20, description="请求的 limit")
    query: str = Field(default="", description="请求的搜索词")
    source: str = Field(
        default="",
        description="数据来源 fetcher 名 (e.g. EastMoneyFetcher)",
    )


class NewsContentResponse(BaseModel):
    """News content extraction response."""
    url: str = Field(description="被提取的 URL")
    title: str | None = Field(default=None)
    body: str = Field(default="", description="已清洗的正文纯文本")
    publish_date: str | None = Field(default=None)
    author: str | None = Field(default=None)
    source_domain: str = Field(default="")
    extractor: str = Field(default="default", description="使用的 handler 名")
    byte_size: int = Field(default=0)


class FlashNewsItem(BaseModel):
    """单条全球财经快讯。

    字段命名刻意和 ``NewsItem`` 保持风格一致(英文 snake_case),
    区别:
    - ``publish_time`` (含时分秒) vs ``NewsItem.publish_date`` (只到日)
    - ``snippet`` (摘要) vs ``NewsItem.snippet`` (同名)
    - 没有 ``media_name``: 快讯本身不区分发布媒体
    """

    title: str = Field(default="", description="标题 (原文)")
    url: str = Field(description="详情页 URL (https://finance.eastmoney.com/a/{code}.html)")
    source_domain: str = Field(default="finance.eastmoney.com", description="URL 域名")
    publish_time: str = Field(default="", description="发布时间 YYYY-MM-DD HH:MM:SS")
    snippet: str = Field(default="", description="摘要")


class FlashNewsResponse(BaseModel):
    """全球财经快讯响应。"""

    data: list[FlashNewsItem] = Field(default_factory=list, description="快讯列表")
    total: int = Field(default=0, description="实际返回条数 (= len(data))")
    limit: int = Field(default=50, description="请求的 limit (1..200)")
    source: str = Field(
        default="",
        description="数据来源 fetcher 名 (e.g. EastMoneyFetcher)",
    )


class StockNewsItem(BaseModel):
    """Single news item for the per-stock news feed."""
    title: str = Field(default="")
    url: str = Field(default="")
    source_domain: str = Field(default="")
    publish_date: str = Field(default="", description="YYYY-MM-DD")
    media_name: str = Field(default="")


class StockNewsResponse(BaseModel):
    """Stock-specific news feed response."""
    code: str = Field(description="股票代码")
    data: list[StockNewsItem] = Field(default_factory=list)
    total: int = Field(default=0)
    limit: int = Field(default=20)
    source: str = Field(default="", description="数据来源 fetcher 名")
