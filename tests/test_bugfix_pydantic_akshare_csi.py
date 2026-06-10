"""
Tests for the akshare csi-market bug and Pydantic v2 strict-input bugs.

Bug 1: AkshareFetcher.get_all_stocks('csi') returns [] because the if/elif
       chain only matches market='cn', but the persistence layer normalizes
       'cn' → 'csi' before calling the fetcher.

Bug 2: Pydantic v2 rejects upstream-supplied None/'' for fields that have
       non-Optional default values, raising ValidationError → 500 on the
       /stocks/{code}/dividend, /stocks/{code}/reports, and
       /stocks/{code}/announcements endpoints.
"""

from unittest.mock import patch

import pandas as pd
import pytest

from stock_data.api.schemas import (
    AnnouncementRecord,
    DividendRecord,
    ReportRecord,
)
from stock_data.data_provider.fetchers.akshare import AkshareFetcher


class TestAkshareCsiMarket:
    """Bug 1: akshare fetcher must accept market='csi' just like 'cn'."""

    def test_get_all_stocks_csi_returns_stocks(self):
        """When called with market='csi', akshare must dispatch to the
        same A-share branch as market='cn' (the persistence layer
        normalizes cn → csi before calling the fetcher)."""
        fetcher = AkshareFetcher()
        fake_df = pd.DataFrame(
            {"code": ["600519", "000001"], "name": ["贵州茅台", "平安银行"]}
        )
        with patch("akshare.stock_info_a_code_name", return_value=fake_df):
            stocks = fetcher.get_all_stocks("csi")
        assert len(stocks) == 2
        assert stocks[0]["code"] == "600519"
        assert stocks[0]["name"] == "贵州茅台"

    def test_get_all_stocks_cn_still_works(self):
        """Backward compat: market='cn' must keep working (legacy callers)."""
        fetcher = AkshareFetcher()
        fake_df = pd.DataFrame(
            {"code": ["600519"], "name": ["贵州茅台"]}
        )
        with patch("akshare.stock_info_a_code_name", return_value=fake_df):
            stocks = fetcher.get_all_stocks("cn")
        assert len(stocks) == 1


class TestPydanticV2StrictInput:
    """Bug 2: schemas must tolerate upstream None / '' on these specific
    fields without raising ValidationError. Field semantics preserved
    (None/'' → declared default, NOT a type change)."""

    def test_dividend_record_accepts_none_for_bonus_ratio(self):
        """Upstream (EastMoneyFetcher.get_dividend) returns None for
        bonus_ratio on rows where the company had no bonus shares.
        Schema declares `bonus_ratio: float = 0`; that default must be
        honored instead of raising."""
        record = DividendRecord(
            date="2024-01-01",
            bonus_rmb=10.0,
            transfer_ratio=0.0,
            bonus_ratio=None,  # upstream value
            plan="实施",
        )
        assert record.bonus_ratio == 0
        assert record.date == "2024-01-01"

    def test_dividend_record_accepts_none_for_bonus_rmb_and_transfer(self):
        """Same upstream quirk applies to other numeric fields; test
        that the sanitizer handles the full row, not just bonus_ratio."""
        record = DividendRecord(
            date="2024-01-01",
            bonus_rmb=None,
            transfer_ratio=None,
            bonus_ratio=None,
            plan="实施",
        )
        assert record.bonus_rmb == 0
        assert record.transfer_ratio == 0
        assert record.bonus_ratio == 0

    def test_report_record_accepts_empty_string_for_predict_eps_next2(self):
        """Upstream (EastMoneyFetcher.get_reports) returns '' for
        predict_eps_next2 when the forecast is not published. Schema
        declares `predict_eps_next2: float | None = None`; the empty
        string must be coerced to None."""
        record = ReportRecord(
            title="test",
            publish_date="2024-01-01",
            org="券商A",
            info_code="XYZ",
            rating="买入",
            predict_eps_this=1.0,
            predict_eps_next=1.2,
            predict_eps_next2="",  # upstream value
        )
        assert record.predict_eps_next2 is None

    def test_announcement_record_accepts_none_for_type(self):
        """Upstream (CninfoFetcher.get_announcements) returns None for
        `type` on some announcement rows. Schema declares
        `type: str = ""`; the default must be honored."""
        record = AnnouncementRecord(
            title="公告标题",
            type=None,  # upstream value
            date="2024-01-01",
            url="https://example.com",
        )
        assert record.type == ""

    def test_announcement_record_accepts_none_for_title_and_url(self):
        """Same upstream quirk: any str field with a default can receive
        None; all must be sanitized."""
        record = AnnouncementRecord(
            title=None,
            type=None,
            date="2024-01-01",
            url=None,
        )
        assert record.title == ""
        assert record.type == ""
        assert record.url == ""

    def test_dividend_record_numeric_zero_is_preserved(self):
        """Sanitizer must NOT confuse a legitimate 0 with None — `or`
        style coercion would clobber 0. We use the field's declared
        default for None, but a real 0.0 must stay 0.0."""
        record = DividendRecord(
            date="2024-01-01",
            bonus_rmb=0.0,
            transfer_ratio=0.0,
            bonus_ratio=0.0,
            plan="实施",
        )
        assert record.bonus_rmb == 0.0
        assert record.transfer_ratio == 0.0
        assert record.bonus_ratio == 0.0
