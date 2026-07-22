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
    volume_unit: str = Field(
        default="share", description="Volume unit. Always 'share' (股) per spec §3.4."
    )
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
    # Per-bar frequency tag. Mirrors the request's `?frequency=` so each
    # row self-identifies its timeframe (the top-level `period` field
    # on the response is also a tag, but per-row tagging gives a
    # defense-in-depth check the bar's data matches the request's
    # intent — a mismatch means the fetcher hit the wrong upstream
    # segment, which would otherwise be invisible at the row level).
    # Populated by the route layer from `row.get("frequency")` (set
    # by the fetcher) or the request's `frequency` parameter (fallback
    # for fetchers that don't tag their rows yet).
    # Date format depends on frequency: YYYY-MM-DD for d/w/m,
    # YYYY-MM-DD HH:MM for 1m/5m/15m/30m/60m.
    frequency: Literal["d", "w", "m", "1m", "5m", "15m", "30m", "60m"] | None = Field(
        default=None,
        description="Per-bar frequency tag. Same as the request's `?frequency=`. "
        "Use this to verify each bar's timeframe matches the requested "
        "frequency (defense against wrong-upstream-segment bugs).",
    )
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
        # Per-bar frequency tag: only emit when populated. The route
        # layer falls back to the request's `?frequency=` for fetchers
        # that don't tag their rows, so by the time we reach the
        # serializer this should always be set. We still guard with
        # `is not None` to keep the serializer's "drop optional
        # fields" contract consistent with `indicators` below —
        # clients that don't care about the per-bar tag won't see it.
        if self.frequency is not None:
            data["frequency"] = self.frequency
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
    last_success_time: float | None = Field(
        default=None, description="Unix timestamp of last successful call"
    )
    last_failure_time: float | None = Field(
        default=None, description="Unix timestamp of last failure"
    )
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
    sources: list[SourceHealth] | None = Field(
        default=None, description="Per-source health details (only when details=true)"
    )


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
    type: str | None = Field(
        default=None,
        description=(
            "Board type (concept/industry/index/special). Always populated "
            "by the route layer (both fresh fetcher rows and cache-hit rows "
            "tag every board with its type). Required for the all-types "
            "response (``GET /boards?source=...`` without ``type=``) so "
            "callers can split the result by type."
        ),
    )
    price: float | None = Field(
        default=None, description="Latest price (requires include_quote=True)"
    )
    change_pct: float | None = Field(
        default=None, description="Change percent (requires include_quote=True)"
    )
    change_amount: float | None = Field(
        default=None, description="Change amount (requires include_quote=True)"
    )
    volume: int | None = Field(default=None, description="Volume (requires include_quote=True)")
    amount: float | None = Field(default=None, description="Amount (requires include_quote=True)")
    turnover_rate: float | None = Field(
        default=None, description="Turnover rate (requires include_quote=True)"
    )
    total_mv: float | None = Field(
        default=None, description="Total market value (requires include_quote=True)"
    )
    net_inflow: float | None = Field(
        default=None,
        description=(
            "Net inflow (资金净流入) in 亿元 (CNY 100M units). "
            "Industry rank table only; None for sources/types that don't expose it."
        ),
    )
    up_count: int | None = Field(
        default=None, description="Number of rising stocks (requires include_quote=True)"
    )
    down_count: int | None = Field(
        default=None, description="Number of falling stocks (requires include_quote=True)"
    )
    leading_stock: str | None = Field(
        default=None, description="Leading stock name (requires include_quote=True)"
    )
    leading_stock_price: float | None = Field(
        default=None,
        description=(
            "Leading stock's latest price in CNY. "
            "Industry rank table only; None when upstream doesn't expose it."
        ),
    )
    leading_stock_pct: float | None = Field(
        default=None, description="Leading stock change percent (requires include_quote=True)"
    )


class BoardStockInfo(BaseModel):
    """Stock in a board, optionally with quote data."""

    code: str = Field(description="Stock code")
    name: str = Field(default="", description="Stock name")
    price: float | None = Field(default=None, description="Current price")
    change_pct: float | None = Field(default=None, description="Change percent")
    change_amount: float | None = Field(default=None, description="Change amount (元)")
    volume: int | None = Field(
        default=None, description="Volume (shares; only populated when upstream exposes it)"
    )
    amount: float | None = Field(default=None, description="Trading amount (元)")
    turnover_rate: float | None = Field(default=None, description="Turnover rate (%)")
    # === 2026-07-13 新增 (THS /field/<code> 14 列全部暴露) ===
    change_speed: float | None = Field(
        default=None, description="涨速(%) — THS upstream column 6")
    volume_ratio: float | None = Field(
        default=None, description="量比 — THS upstream column 8")
    amplitude: float | None = Field(
        default=None, description="振幅(%) — THS upstream column 9")
    free_float_shares: int | None = Field(
        default=None, description="流通股(股) — THS upstream column 11 parsed from 'N.NN亿'")
    float_market_cap: float | None = Field(
        default=None, description="流通市值(元) — THS upstream column 12")
    pe_ratio: float | None = Field(
        default=None, description="市盈率 — THS upstream column 13")


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
    # 成分股实际 upstream (post-2026-07-10 optimization).
    # 总是填充 (P4): 主要 fetcher 链 = 'ths' / 'zzshare' / 'eastmoney' / 'zhitu'.
    # 当 query_source == effective_source 时未触发 fallback; 不同时表示
    # source='ths' + include_quote=False 路径内部 fallback 到 ZZSHARE.
    # 自 2026-07-21 起 F10 全量页胜出时也归一到 'ths' (不再单独暴露 ths-f10).
    effective_source: str | None = Field(
        default=None,
        description=(
            "实际服务本响应的 fetcher 名称 (ths / zzshare / eastmoney / zhitu). "
            "路由层总是填充——None 只在直构造 Pydantic 模型 (如 schema 测试) 不传参时出现. "
            "区别于 query_source 即可判 fallback: "
            "query_source='ths' 且 effective_source='zzshare' 表示走 ZZSHARE fallback; "
            "query_source='ths' 且 effective_source='ths' 表示 F10 全量或 THS AJAX 直胜出. "
            "缓存命中时该字段固定为 'ths' (因为 stock_board_membership 表不存 per-row origin 列); "
            "需要暴露真实 upstream 时传 ?refresh=true."
        ),
    )
    # Realtime quote block metadata (only meaningful when include_quote=true).
    # Pre-2026-07-10 the realtime failure path was silent (board.price=null
    # + debug log); post-2026-07-10 these fields give the client an explicit
    # signal so they can distinguish "no quote requested" / "quote succeeded"
    # / "source doesn't support quote" / "upstream failed".
    quote_source: str | None = Field(
        default=None,
        description=(
            "板块实时行情数据来源 (ths / null). 与 query_source 解耦: "
            "成分股走 query_source, 但实时行情目前仅 ths 实现. None 表示未请求或未拉到."
        ),
    )
    quote_error: str | None = Field(
        default=None,
        description=(
            "实时行情失败原因: 'unsupported' (source 不实现 get_board_realtime) / "
            "'board_type_unresolved' (持久化层无 board_type 数据) / "
            "'upstream_failed: <reason>' (上游异常) / null (成功或未请求)."
        ),
    )
    # === 2026-07-13 新增 (top_n / sort echo) ===
    # These five fields echo the request's sort/top_n parameters and the
    # helper's heuristic outcome back to the client, so callers can
    # distinguish "no sort applied" / "sort applied without truncation" /
    # "sort applied + truncated to top_n + remaining filled from zzshare".
    quote_truncated: bool | None = Field(
        default=None,
        description=(
            "True when the board's full member count exceeded top_n and "
            "the remaining stocks were filled in from ZZSHARE without "
            "quote fields. None when the caller did not request sorting."
        ),
    )
    quote_top_n: int | None = Field(
        default=None,
        description=(
            "Echo of the request's top_n value (1-50). None when the "
            "caller did not request sorting (defaults used)."
        ),
    )
    quote_sort_by: str | None = Field(
        default=None,
        description=(
            "Echo of the request's sort_by literal. None when the "
            "caller did not request sorting."
        ),
    )
    quote_sort_order: str | None = Field(
        default=None,
        description=(
            "Echo of the request's sort_order literal ('asc' or 'desc'). "
            "None when the caller did not request sorting."
        ),
    )
    quote_total_in_board: int | None = Field(
        default=None,
        description=(
            "Total number of stocks in the board. Always populated on "
            "include_quote=true (server does a ZZSHARE fill-in to discover "
            "the true board size). May be None on include_quote=false cold "
            "cache; populated with cached count when cache has rows."
        ),
    )


class BoardQuoteResponse(BaseModel):
    """Response for board realtime quote endpoint (`/boards/{board_code}/quote`)."""

    board_code: str = Field(description="Board platecode (e.g. 885595)")
    board_name: str = Field(default="", description="Board name")
    source: str = Field(
        default="",
        description=(
            "实际数据来源 fetcher 实现名 (当前仅 ths). 这是 fetcher 的实现身份, "
            "不是用户可选参数 — /boards/{code}/quote 路由不接受 ?source= 查询参数, "
            "因为只有 ThsFetcher 实现了 get_board_realtime. 当其他 fetcher "
            "实现该方法后, 此字段会反映实际被调用的 fetcher 名."
        ),
    )
    price: float | None = Field(default=None, description="板块指数/现价 (指数点)")
    change_pct: float | None = Field(default=None, description="涨跌幅 (%)")
    change_amount: float | None = Field(default=None, description="涨跌额 (指数点)")
    open: float | None = Field(default=None, description="今开 (指数点)")
    high: float | None = Field(default=None, description="最高 (指数点)")
    low: float | None = Field(default=None, description="最低 (指数点)")
    prev_close: float | None = Field(default=None, description="昨收 (指数点)")
    volume: int | None = Field(
        default=None,
        description=(
            "成交量 (万手, 整数). 上游 (q.10jqka 概念详情页) 返回的是浮点字符串 "
            "(如 '15343.80'), fetcher 用 safe_int 截断为 int — 精度损失约 0.005% "
            "(约 80,000 股 / 1.5 亿手). 下游消费者如需小数精度应直接调用 fetcher "
            "层 (Stage 2: /control/fetcher-test) 或在 route 层把字段类型升级为 float."
        ),
    )
    amount: float | None = Field(default=None, description="成交额 (亿元)")
    net_inflow: float | None = Field(default=None, description="资金净流入 (亿元)")
    up_count: int | None = Field(default=None, description="上涨家数")
    down_count: int | None = Field(default=None, description="下跌家数")
    rank: str | None = Field(default=None, description="涨幅排名 (e.g. '229/389')")


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
            "Data source fetcher name — one of 'EastMoneyFetcher', 'ZzshareFetcher', 'ThsFetcher'"
        ),
    )


# ────────────────────────────────────────────────────────────────────────
# Board F10 page sections (added 2026-07-20 per spec §3.5.2 / §3.5.3).
# Both endpoints source-routed to ``source='ths'`` (THS-only v1).
# ────────────────────────────────────────────────────────────────────────


class BoardNewsItem(BaseModel):
    """A single news item from a board's THS timeline news feed."""

    title: str = Field(description="News title (Chinese)")
    url: str = Field(description="Absolute URL to the article on news.10jqka.com.cn")
    publish_date: str = Field(
        default="",
        description="Publish date in 'YYYY-MM-DD' format (from upstream publishTime epoch; '' when missing)",
    )
    publish_time: str = Field(
        default="",
        description="Publish time in 'HH:MM' format (from upstream publishTime epoch; '' when missing)",
    )
    summary: str = Field(
        default="",
        description="Optional one-line preview text from the upstream card; '' when upstream has no preview",
    )
    source_domain: str = Field(
        default="news.10jqka.com.cn",
        description="Source domain of the news URL",
    )


class BoardNewsResponse(BaseModel):
    """Response for /boards/{board_code}/news (THS 板块新闻 timeline feed)."""

    board_code: str = Field(description="Board code echoed back")
    source: str = Field(default="ths", description="Source label (THS-only v1)")
    total: int = Field(description="Number of items in `data`")
    data: list[BoardNewsItem] = Field(default_factory=list, description="News items")


class BoardSurgeItem(BaseModel):
    """A single 炒作周期 entry from a board's THS F10 surges section."""

    date: str = Field(description="Date label (typically YYYY-MM-DD)")
    board_change_pct: float | None = Field(
        default=None,
        description="Board index change percent for the cycle (positive=up, negative=down)",
    )
    sh_change_pct: float | None = Field(
        default=None,
        description="Shanghai composite change percent for the same cycle",
    )
    limit_up_count: int = Field(
        default=0,
        description="Count of stocks that hit the 涨停 limit during this cycle",
    )
    limit_up_stocks: list[str] = Field(
        default_factory=list,
        description="Six-digit stock codes that hit the 涨停 limit during this cycle",
    )
    up_count: int | None = Field(
        default=None,
        description="Count of up-movers on the cycle day (F10 doesn't expose; reserved for future)",
    )
    down_count: int | None = Field(
        default=None,
        description="Count of down-movers on the cycle day (F10 doesn't expose; reserved for future)",
    )


class BoardSurgesResponse(BaseModel):
    """Response for /boards/{board_code}/surges (THS F10 板块炒作周期)."""

    board_code: str = Field(description="Board code echoed back")
    source: str = Field(default="ths", description="Source label (THS-only v1)")
    total: int = Field(description="Number of items in `data`")
    data: list[BoardSurgeItem] = Field(default_factory=list, description="Surge/cycle entries")


class StockBoardInfo(BaseModel):
    """A board that a stock belongs to."""

    code: str = Field(description="Board code (source-specific, e.g. 'sw_yx' for Zhitu)")
    name: str = Field(description="Board full name (e.g. 'A股-申万行业-银行')")
    type: str = Field(description="Board type: concept / industry / index / special")
    subtype: str = Field(
        default="",
        description="Source-specific subtype (e.g. '申万行业' for Zhitu, 'concept' for EastMoney)",
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
    volume_unit: str = Field(
        default="share", description="Volume unit. Always 'share' (股) per spec §3.4."
    )
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
    lb_count: int | None = Field(
        default=None, description="Consecutive limit-up count (涨停连板数) / 连续跌停次数"
    )
    first_seal_time: str | None = Field(default=None, description="First seal time (HH:mm:ss)")
    last_seal_time: str | None = Field(default=None, description="Last seal time (HH:mm:ss)")
    seal_amount: float | None = Field(
        default=None, description="Seal amount (封板资金/封单资金, 元)"
    )
    seal_count: int | None = Field(default=None, description="Seal break count (炸板次数)")
    zt_count: str | None = Field(default=None, description="Limit-up statistics (x天/y板)")


class ZTPoolResponse(BaseModel):
    """ZT (涨跌停) pool response."""

    date: str = Field(description="Pool date (YYYY-MM-DD)")
    type: str = Field(description="Pool type: zt (涨停) / dt (跌停) / zbgc (炸板)")
    total: int = Field(description="Total number of stocks in the pool")
    stocks: list[ZTPoolStock] = Field(
        default_factory=list, description="List of stocks in the pool"
    )
    source: str = Field(
        default="",
        description="数据来源 fetcher 名 或 'persistence' (历史日期的池数据从 SQLite 读取)",
    )
    warning: str | None = Field(
        default=None,
        description=(
            "非空表示数据涉及交易时段（今天 + 是交易日 + 当前时间早于 16:00），"
            "涨跌停股池可能仍在变化，建议收盘（16:00 后）重新查询以获取稳定快照。"
            "历史日期或收盘后的当日数据该字段为 null。"
        ),
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
    close: float | None = Field(
        default=None,
        description="收盘价(元);上游无此字段时为 null (e.g. zzshare lhb_list)",
    )
    change_pct: float = Field(default=0, description="涨跌幅(%)")
    net_buy_wan: float = Field(default=0, description="净买入(万元)")
    buy_wan: float | None = Field(
        default=None,
        description="买入金额(万元);上游未拆分 buy/sell 时为 null (e.g. zzshare lhb_list 仅返回净买入 buy_in)",
    )
    sell_wan: float | None = Field(
        default=None,
        description="卖出金额(万元);上游未拆分 buy/sell 时为 null (e.g. zzshare lhb_list 仅返回净买入 buy_in)",
    )
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
    # raw_url 上游仅 ThsFetcher (basic.10jqka.com.cn) 携带; 其他 fetcher 留空.
    # Pydantic v2 默认 extra='ignore': 老 fetcher dict 缺 raw_url → 用 "" 默认.
    raw_url: str = Field(default="", description="巨潮原文 PDF 直链 (ThsFetcher only)")


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
    registered_capital: str = Field(
        default="", description="注册资本 (Zhitu, 字符串格式如 '9.82亿')"
    )
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


NewsContentStatus = Literal[
    "ok",
    "empty",
    "unsupported",
    "javascript_required",
    "blocked",
    "fetch_error",
]


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
    content_status: NewsContentStatus = Field(default="ok", description="正文提取状态")
    reason: str | None = Field(default=None, description="失败原因（仅供诊断）")
    canonical_url: str | None = Field(default=None, description="页面规范 URL")
    http_status: int | None = Field(default=None, description="最终上游 HTTP 状态码")


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


class ClsArticle(BaseModel):
    """Single CLS article (早报 / 复盘) — body_text is the BS4-extracted plain text."""

    article_id: int
    title: str
    brief: str
    author: str
    date: str  # YYYY-MM-DD
    ctime: int  # unix timestamp
    read_num: int
    comments_num: int
    share_num: int
    images: list[str] = []
    body_text: str  # BS4 抽出的纯文本，保留段落分隔（get_text("\n", strip=True) + 折叠空行）


class ClsFeedResponse(BaseModel):
    """Response shape for /api/v1/news/morning-briefing and /api/v1/news/market-recap."""

    subject: str  # "morning_briefing" | "market_review"
    subject_id: int
    date: str  # 入参 date
    article: ClsArticle | None  # None → 404
    source: str = Field(default="", description="数据来源 fetcher 名")
