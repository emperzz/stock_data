# -*- coding: utf-8 -*-
"""
Pytest configuration and fixtures.
"""

import pytest


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
