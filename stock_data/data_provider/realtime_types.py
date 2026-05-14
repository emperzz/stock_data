"""
Realtime types and utilities for stock data providers.
"""

import logging
import math
import time
from dataclasses import dataclass
from enum import Enum
from threading import RLock
from typing import Any

logger = logging.getLogger(__name__)


def safe_float(val: Any, default: float | None = None) -> float | None:
    """Safely convert value to float, handling None, NaN, and string cases."""
    if val is None:
        return default
    try:
        if isinstance(val, str):
            val = val.strip()
            if val in ("", "-", "--", "nan", "None"):
                return default
        if math.isnan(float(val)):
            return default
        return float(val)
    except (ValueError, TypeError):
        return default


def safe_int(val: Any, default: int | None = None) -> int | None:
    """Safely convert value to int via float."""
    f_val = safe_float(val, None)
    if f_val is not None:
        return int(f_val)
    return default


class RealtimeSource(Enum):
    """Data source identifiers for realtime quotes."""

    TUSHARE = "tushare"
    AKSHARE = "akshare"
    YFINANCE = "yfinance"
    STOOQ = "stooq"
    LONGBRIDGE = "longbridge"
    ZHITU = "zhitu"
    FALLBACK = "fallback"


@dataclass
class UnifiedRealtimeQuote:
    """
    Unified realtime quote dataclass.

    All fetchers return this structure for realtime quotes.
    Missing fields are None.
    """

    code: str
    name: str = ""
    source: RealtimeSource = RealtimeSource.FALLBACK

    # Core price data
    price: float | None = None
    change_pct: float | None = None
    change_amount: float | None = None

    # Volume indicators
    volume: int | None = None
    amount: float | None = None
    volume_ratio: float | None = None
    turnover_rate: float | None = None
    amplitude: float | None = None

    # Price range
    open_price: float | None = None
    high: float | None = None
    low: float | None = None
    pre_close: float | None = None

    # Valuation
    pe_ratio: float | None = None
    pb_ratio: float | None = None
    total_mv: float | None = None
    circ_mv: float | None = None

    def has_basic_data(self) -> bool:
        """Check if basic price data is available."""
        return self.price is not None and self.price > 0

    def to_dict(self) -> dict:
        """Convert to dict, excluding None and empty values."""
        result = {}
        for attr in [
            "code",
            "name",
            "source",
            "price",
            "change_pct",
            "change_amount",
            "volume",
            "amount",
            "volume_ratio",
            "turnover_rate",
            "amplitude",
            "open_price",
            "high",
            "low",
            "pre_close",
            "pe_ratio",
            "pb_ratio",
            "total_mv",
            "circ_mv",
        ]:
            val = getattr(self, attr, None)
            if val is not None and val != "":
                result[attr] = val
        return result


class CircuitBreaker:
    """
    Circuit breaker for data source protection.

    States:
    - CLOSED: Normal operation
    - OPEN: Failing, skip requests
    - HALF_OPEN: Probe after cooldown, allow limited requests
    """

    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"

    def __init__(
        self,
        failure_threshold: int = 3,
        cooldown_seconds: float = 300.0,
        half_open_max_calls: int = 1,
    ):
        self.failure_threshold = failure_threshold
        self.cooldown_seconds = cooldown_seconds
        self.half_open_max_calls = half_open_max_calls
        self._states: dict = {}
        self._lock = RLock()

    def _get_state(self, source: str) -> dict:
        """Get or create state for a source."""
        if source not in self._states:
            self._states[source] = {
                "state": self.CLOSED,
                "failures": 0,
                "last_failure_time": 0.0,
                "half_open_calls": 0,
            }
        return self._states[source]

    def is_available(self, source: str) -> bool:
        """Check if source can be called."""
        with self._lock:
            state = self._get_state(source)
            now = time.time()

            if state["state"] == self.CLOSED:
                return True

            if state["state"] == self.OPEN:
                elapsed = now - state["last_failure_time"]
                if elapsed >= self.cooldown_seconds:
                    state["state"] = self.HALF_OPEN
                    state["half_open_calls"] = 0
                    state["last_failure_time"] = now
                    logger.info(f"[CircuitBreaker] {source} cooling complete, probing")
                else:
                    return False

            if state["state"] == self.HALF_OPEN:
                if state["half_open_calls"] < self.half_open_max_calls:
                    state["half_open_calls"] += 1
                    return True
                elapsed = now - state["last_failure_time"]
                if elapsed >= self.cooldown_seconds:
                    state["half_open_calls"] = 1
                    state["last_failure_time"] = now
                    return True
                return False

            return True

    def record_success(self, source: str) -> None:
        """Record successful call."""
        with self._lock:
            state = self._get_state(source)
            if state["state"] == self.HALF_OPEN:
                logger.info(f"[CircuitBreaker] {source} probe succeeded, recovering")
            state["state"] = self.CLOSED
            state["failures"] = 0
            state["half_open_calls"] = 0

    def record_failure(self, source: str, error: str | None = None) -> None:
        """Record failed call."""
        with self._lock:
            state = self._get_state(source)
            state["failures"] += 1
            state["last_failure_time"] = time.time()

            if state["state"] == self.HALF_OPEN:
                state["state"] = self.OPEN
                state["half_open_calls"] = 0
                logger.warning(f"[CircuitBreaker] {source} probe failed, staying open")
            elif state["failures"] >= self.failure_threshold:
                state["state"] = self.OPEN
                logger.warning(
                    f"[CircuitBreaker] {source} failed {state['failures']} times, opening circuit"
                )


# Global circuit breaker for realtime quotes
_realtime_circuit_breaker = CircuitBreaker(
    failure_threshold=3, cooldown_seconds=300.0, half_open_max_calls=1
)


def get_realtime_circuit_breaker() -> CircuitBreaker:
    """Get the global realtime circuit breaker."""
    return _realtime_circuit_breaker
