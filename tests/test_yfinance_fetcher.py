"""Tests for YfinanceFetcher K-line end-date + 1 day adjustment.

Yfinance's ``yf.download`` treats the ``end`` parameter as EXCLUSIVE —
passing ``end_date=today`` returns data through yesterday, not today.
The fetcher adjusts ``end_date`` to ``end_date + 1 day`` before the
upstream call so the caller's inclusive end_date semantics hold.
"""

from unittest.mock import patch

import pandas as pd

from stock_data.data_provider.fetchers.yfinance_fetcher import YfinanceFetcher


def _empty_yf_df() -> pd.DataFrame:
    """A minimal non-empty DataFrame yfinance would return."""
    return pd.DataFrame(
        {"Open": [10.0], "High": [11.0], "Low": [9.5], "Close": [10.5], "Volume": [1000]},
        index=pd.to_datetime(["2026-07-24"]),
    )


def test_yfinance_end_date_inclusive_adds_one_day():
    """end_date=2026-07-24 → yfinance receives end=2026-07-25."""
    fetcher = YfinanceFetcher()
    fake_df = _empty_yf_df()
    with patch("yfinance.download") as mock_dl:
        mock_dl.return_value = fake_df
        fetcher._fetch_raw_data("AAPL", "2026-07-01", "2026-07-24", frequency="d", asset="stock")
        _, kwargs = mock_dl.call_args
        assert kwargs["start"] == "2026-07-01"
        assert kwargs["end"] == "2026-07-25"
        assert kwargs["interval"] == "1d"


def test_yfinance_end_date_year_boundary():
    """end_date=2026-12-31 → yfinance receives end=2027-01-01 (跨年)."""
    fetcher = YfinanceFetcher()
    fake_df = _empty_yf_df()
    with patch("yfinance.download") as mock_dl:
        mock_dl.return_value = fake_df
        fetcher._fetch_raw_data("AAPL", "2026-01-01", "2026-12-31", frequency="d", asset="stock")
        _, kwargs = mock_dl.call_args
        assert kwargs["end"] == "2027-01-01"


def test_yfinance_end_date_leap_year():
    """end_date=2028-02-28 → yfinance receives end=2028-02-29 (闰年)."""
    fetcher = YfinanceFetcher()
    fake_df = _empty_yf_df()
    with patch("yfinance.download") as mock_dl:
        mock_dl.return_value = fake_df
        fetcher._fetch_raw_data("AAPL", "2028-02-01", "2028-02-28", frequency="d", asset="stock")
        _, kwargs = mock_dl.call_args
        assert kwargs["end"] == "2028-02-29"


def test_yfinance_end_date_weekly_interval_also_adjusted():
    """Weekly frequency 也 +1 day (end-exclusive 跨所有 interval)."""
    fetcher = YfinanceFetcher()
    fake_df = _empty_yf_df()
    with patch("yfinance.download") as mock_dl:
        mock_dl.return_value = fake_df
        fetcher._fetch_raw_data("AAPL", "2026-01-01", "2026-07-24", frequency="w", asset="stock")
        _, kwargs = mock_dl.call_args
        assert kwargs["end"] == "2026-07-25"
        assert kwargs["interval"] == "1wk"
