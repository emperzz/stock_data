"""
Pytest configuration and fixtures.

This module also installs the **network-to-xfail hook** that reclassifies
upstream/network errors in any test marked ``@pytest.mark.live_network``
as ``xfail`` (output line ``x``) rather than ``failed`` (``F``). See
``tests/_network_guard.py`` for the rationale and the legend.
"""

from __future__ import annotations

import os

import pandas as pd
import pytest

# Force the pure-Python protobuf parser before any test imports ``gm.api``.
# The shipped gm 3.0.180 wheel's auto-generated _pb2 descriptors are
# incompatible with the C++-backed parser in modern protobuf; this env
# var must be set BEFORE the very first ``import gm.api`` (which happens
# transitively via monkeypatch.setattr's __import__ path-resolution).
os.environ.setdefault("PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION", "python")


# ── network-to-xfail hook ─────────────────────────────────────────────────
#
# Strategy: for any test marked ``@pytest.mark.live_network`` whose "call"
# phase failed, look at the exception. If it is a network/upstream error
# (per ``_network_guard.UPSTREAM_ERRORS``), rewrite the pytest report from
# "failed" to "skipped" with ``wasxfail=True`` so it shows as ``x`` in the
# summary instead of ``F``. The reason string identifies the cause.
#
# Why a hook (not per-test try/except): zero boilerplate in test bodies,
# uniform behaviour across all live_network tests, and a single place to
# evolve the classification logic.

# Import here to keep the import resolution explicit and avoid cycles.
from ._network_guard import (  # noqa: E402  (must follow conftest setup above)
    is_upstream_error,
    short_reason,
)


@pytest.hookimpl(tryfirst=True, hookwrapper=True)
def pytest_runtest_makereport(item, call):
    outcome = yield
    report = outcome.get_result()

    # Only the "call" phase can raise the test body's exception.
    if call.when != "call":
        return
    # Only reclassify for live_network tests.
    if "live_network" not in item.keywords:
        return
    # Only act on actual failures (don't downgrade xfails/xpasses).
    if report.outcome != "failed":
        return
    excinfo = call.excinfo
    if excinfo is None:
        return
    # AssertionError, ValueError, etc. are real bugs — leave them alone.
    if not is_upstream_error(excinfo.value):
        return

    # Reclassify: "failed" → "skipped" with wasxfail=<reason>. Pytest then
    # displays the test as ``x`` (xfail) in the summary, with the reason
    # string visible in the long output. An agent reading the summary
    # knows this is a network issue, not a code regression, and should
    # not retry.
    #
    # NOTE: ``wasxfail`` is a string in pytest (the reason), not a bool.
    # Setting it to ``True`` triggers an internal ``AttributeError`` in
    # ``_pytest/terminal.py`` because the reporter calls
    # ``reason.startswith("reason: ")``.
    report.outcome = "skipped"
    report.wasxfail = short_reason(excinfo.value)
    report.longrepr = short_reason(excinfo.value)


# ── fixtures ──────────────────────────────────────────────────────────────


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
            "high": [100.5, 101.0, 101.5, 100.8, 101.5],
            "low": [99.8, 100.2, 100.5, 100.5, 100.8],
            "close": [100.5, 101.0, 100.8, 101.2, 101.5],
            "volume": [5000, 6000, 5500, 7000, 6500],
            "amount": [500000, 600000, 550000, 700000, 650000],
        }
    )
