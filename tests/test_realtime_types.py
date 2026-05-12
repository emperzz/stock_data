# -*- coding: utf-8 -*-
"""
Tests for realtime types and utilities.
"""

import pytest

from stock_data.data_provider.realtime_types import (
    safe_float,
    safe_int,
    UnifiedRealtimeQuote,
    CircuitBreaker,
    RealtimeSource,
)


class TestSafeFloat:
    """Tests for safe_float function."""

    def test_none(self):
        assert safe_float(None) is None

    def test_none_with_default(self):
        assert safe_float(None, default=1.0) == 1.0

    def test_string_number(self):
        assert safe_float("123.45") == 123.45

    def test_string_empty(self):
        assert safe_float("") is None

    def test_string_dash(self):
        assert safe_float("-") is None

    def test_float(self):
        assert safe_float(123.45) == 123.45

    def test_int(self):
        assert safe_float(123) == 123.0


class TestSafeInt:
    """Tests for safe_int function."""

    def test_none(self):
        assert safe_int(None) is None

    def test_float(self):
        assert safe_int(123.56) == 123

    def test_string_number(self):
        assert safe_int("123") == 123


class TestUnifiedRealtimeQuote:
    """Tests for UnifiedRealtimeQuote dataclass."""

    def test_basic(self):
        quote = UnifiedRealtimeQuote(
            code="600519",
            name="贵州茅台",
            price=1800.0,
            change_pct=2.5,
        )
        assert quote.code == "600519"
        assert quote.price == 1800.0
        assert quote.has_basic_data()

    def test_no_price(self):
        quote = UnifiedRealtimeQuote(code="600519")
        assert not quote.has_basic_data()

    def test_to_dict(self):
        quote = UnifiedRealtimeQuote(
            code="600519",
            price=1800.0,
        )
        d = quote.to_dict()
        assert d["code"] == "600519"
        assert d["price"] == 1800.0
        assert "name" not in d  # Empty values excluded


class TestCircuitBreaker:
    """Tests for CircuitBreaker class."""

    def test_initial_state(self):
        cb = CircuitBreaker()
        assert cb.is_available("test_source")

    def test_record_success(self):
        cb = CircuitBreaker()
        cb.record_success("test_source")
        assert cb.is_available("test_source")

    def test_record_failure_opens(self):
        cb = CircuitBreaker(failure_threshold=2)
        cb.record_failure("test_source")
        assert cb.is_available("test_source")  # Not yet open
        cb.record_failure("test_source")
        assert not cb.is_available("test_source")  # Now open


class TestRealtimeSource:
    """Tests for RealtimeSource enum."""

    def test_values(self):
        assert RealtimeSource.TUSHARE.value == "tushare"
        assert RealtimeSource.AKSHARE.value == "akshare"
        assert RealtimeSource.YFINANCE.value == "yfinance"
