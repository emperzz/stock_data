# -*- coding: utf-8 -*-
"""
Pydantic schemas for API request/response models.
"""

from datetime import datetime
from typing import Any, List, Optional

from pydantic import BaseModel, Field


class StockQuote(BaseModel):
    """Stock realtime quote response."""

    stock_code: str = Field(description="Stock code")
    stock_name: str = Field(default="", description="Stock name")
    source: str = Field(default="", description="Data source")
    current_price: float = Field(default=0.0, description="Current price")
    change: Optional[float] = Field(default=None, description="Price change amount")
    change_percent: Optional[float] = Field(default=None, description="Price change percent")
    open: Optional[float] = Field(default=None, description="Opening price")
    high: Optional[float] = Field(default=None, description="Highest price")
    low: Optional[float] = Field(default=None, description="Lowest price")
    prev_close: Optional[float] = Field(default=None, description="Previous close price")
    volume: Optional[int] = Field(default=None, description="Trading volume")
    amount: Optional[float] = Field(default=None, description="Trading amount")
    update_time: Optional[str] = Field(default=None, description="Update timestamp")


class KLineData(BaseModel):
    """Single K-line data point."""

    date: str = Field(description="Date")
    open: float = Field(description="Opening price")
    high: float = Field(description="Highest price")
    low: float = Field(description="Lowest price")
    close: float = Field(description="Closing price")
    volume: int = Field(description="Volume")
    amount: Optional[float] = Field(default=None, description="Amount")
    change_percent: Optional[float] = Field(default=None, description="Change percent")
    ma5: Optional[float] = Field(default=None, description="5-day moving average")
    ma10: Optional[float] = Field(default=None, description="10-day moving average")
    ma20: Optional[float] = Field(default=None, description="20-day moving average")


class StockHistoryResponse(BaseModel):
    """Stock historical K-line response."""

    stock_code: str = Field(description="Stock code")
    stock_name: str = Field(default="", description="Stock name")
    period: str = Field(default="daily", description="K-line period")
    data: List[KLineData] = Field(default_factory=list, description="K-line data points")


class ErrorResponse(BaseModel):
    """Error response."""

    error: str = Field(description="Error code")
    message: str = Field(description="Error message")


class HealthResponse(BaseModel):
    """Health check response."""

    status: str = Field(default="ok", description="Service status")
    version: str = Field(default="0.1.0", description="Server version")
    available_sources: List[str] = Field(default_factory=list, description="Available data sources")
