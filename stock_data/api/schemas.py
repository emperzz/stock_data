"""
Pydantic schemas for API request/response models.
"""


from pydantic import BaseModel, Field


class StockQuote(BaseModel):
    """Stock realtime quote response."""

    stock_code: str = Field(description="Stock code")
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

    stock_code: str = Field(description="Stock code")
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

    stock_code: str = Field(description="Stock code")
    stock_name: str = Field(default="", description="Stock name")
    period: str = Field(description="Minute period (1m/5m/15m/30m/60m)")
    adjust: str = Field(default="", description="Adjustment type")
    date: str = Field(description="Trade date (YYYY-MM-DD)")
    data: list[IntradayData] = Field(default_factory=list, description="Minute-level data points")
