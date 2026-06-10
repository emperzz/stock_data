"""
Pytest configuration and fixtures.
"""

import os

import pandas as pd
import pytest


# Force the pure-Python protobuf parser before any test imports ``gm.api``.
# The shipped gm 3.0.180 wheel's auto-generated _pb2 descriptors are
# incompatible with the C++-backed parser in modern protobuf; this env
# var must be set BEFORE the very first ``import gm.api`` (which happens
# transitively via monkeypatch.setattr's __import__ path-resolution).
os.environ.setdefault("PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION", "python")


@pytest.fixture
def sample_stock_code():
    """Sample A-share stock code."""
    return "600519"


@pytest.fixture
def sample_us_stock_code():
    """Sample US stock code."""
    return "AAPL"


@pytest.fixture
def sample_hk_stock_code():
    """Sample HK stock code."""
    return "HK00700"


@pytest.fixture
def sample_kline_df():
    """Sample K-line DataFrame with standard columns."""
    dates = pd.date_range("2024-01-01", periods=10, freq="B")
    return pd.DataFrame(
        {
            "date": dates,
            "open": [100 + i for i in range(10)],
            "high": [102 + i for i in range(10)],
            "low": [99 + i for i in range(10)],
            "close": [101 + i for i in range(10)],
            "volume": [10000 + i * 1000 for i in range(10)],
            "amount": [1000000 + i * 10000 for i in range(10)],
            "pct_chg": [0.5] * 10,
            "code": ["600519"] * 10,
        }
    )


@pytest.fixture
def sample_intraday_df():
    """Sample intraday DataFrame."""
    return pd.DataFrame(
        {
            "time": [f"09:{30 + i}:00" for i in range(5)],
            "open": [100.0, 100.5, 101.0, 100.8, 101.2],
            "high": [100.5, 101.0, 101.5, 101.2, 101.5],
            "low": [99.8, 100.2, 100.5, 100.5, 100.8],
            "close": [100.5, 101.0, 100.8, 101.2, 101.5],
            "volume": [5000, 6000, 5500, 7000, 6500],
            "amount": [500000, 600000, 550000, 700000, 650000],
        }
    )
