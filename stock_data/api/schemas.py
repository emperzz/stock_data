"""
Pydantic schemas for API request/response models.
"""

from pydantic import BaseModel, Field


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
    volume: int | None = Field(default=None, description="Trading volume")
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
    """Single K-line data point."""

    date: str = Field(description="Date")
    open: float = Field(description="Opening price")
    high: float = Field(description="Highest price")
    low: float = Field(description="Lowest price")
    close: float = Field(description="Closing price")
    volume: int = Field(description="Volume")
    amount: float | None = Field(default=None, description="Amount")
    change_percent: float | None = Field(default=None, description="Change percent")
    ma5: float | None = Field(default=None, description="5-day moving average")
    ma10: float | None = Field(default=None, description="10-day moving average")
    ma20: float | None = Field(default=None, description="20-day moving average")


class StockHistoryResponse(BaseModel):
    """Stock historical K-line response."""

    code: str = Field(description="Stock code")
    stock_name: str = Field(default="", description="Stock name")
    period: str = Field(default="daily", description="K-line period")
    data: list[KLineData] = Field(default_factory=list, description="K-line data points")


class ErrorResponse(BaseModel):
    """Error response."""

    error: str = Field(description="Error code")
    message: str = Field(description="Error message")


class HealthResponse(BaseModel):
    """Health check response."""

    status: str = Field(default="ok", description="Service status")
    version: str = Field(default="0.1.0", description="Server version")
    available_sources: list[str] = Field(default_factory=list, description="Available data sources")


class IndexInfo(BaseModel):
    """Index information response."""

    code: str = Field(description="Index code (e.g., 000300, SPX, HSI)")
    name: str = Field(description="Index name (e.g., 沪深300, S&P 500)")
    market: str = Field(description="Market type: csi/hk/us")


class StockInfo(BaseModel):
    """Stock information response."""

    code: str = Field(description="Stock code (e.g., 600519, AAPL, HK00700)")
    name: str = Field(description="Stock name")
    market: str = Field(description="Market type: cn/hk/us")


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
    volume: int = Field(description="Volume")
    amount: float | None = Field(default=None, description="Amount")


class IntradayResponse(BaseModel):
    """Intraday minute-level data response."""

    code: str = Field(description="Stock code")
    stock_name: str = Field(default="", description="Stock name")
    period: str = Field(description="Minute period (1m/5m/15m/30m/60m)")
    adjust: str = Field(default="", description="Adjustment type")
    date: str = Field(description="Trade date (YYYY-MM-DD)")
    data: list[IntradayData] = Field(default_factory=list, description="Minute-level data points")


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


class BoardStocksResponse(BaseModel):
    """Response for board stocks endpoint."""

    board: BoardInfo = Field(description="Board info")
    stocks: list[BoardStockInfo] = Field(default_factory=list, description="Stocks in the board")
    source: str = Field(default="", description="Data source")


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
    volume: int | None = Field(default=None, description="Trading volume")
    amount: float | None = Field(default=None, description="Trading amount")
    update_time: str | None = Field(default=None, description="Update timestamp")


class IndexHistoryResponse(BaseModel):
    """Index historical K-line response."""

    code: str = Field(description="Index code")
    name: str = Field(default="", description="Index name")
    period: str = Field(default="daily", description="K-line period: daily/weekly/monthly")
    data: list[KLineData] = Field(default_factory=list, description="K-line data points")


class IndexIntradayResponse(BaseModel):
    """Index intraday minute-level data response."""

    code: str = Field(description="Index code")
    name: str = Field(default="", description="Index name")
    period: str = Field(description="Minute period (1m/5m/15m/30m/60m)")
    date: str = Field(description="Trade date (YYYY-MM-DD)")
    data: list[IntradayData] = Field(default_factory=list, description="Minute-level data points")


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
    source: str = Field(default="eastmoney")


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
    source: str = Field(default="eastmoney")


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
    source: str = Field(default="eastmoney")


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
    source: str = Field(default="eastmoney")


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
    source: str = Field(default="eastmoney")


class DividendRecord(BaseModel):
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
    source: str = Field(default="eastmoney")
