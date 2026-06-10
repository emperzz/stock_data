"""
Tests for the market-tag boundary between API and fetcher layers.

Refactor invariant:
- External API (`/api/v1/stocks?market=...`) accepts ONLY csi/hk/us.
  `cn` is rejected with 422 (FastAPI validation) — it's an internal
  fetcher detail, not a public tag.
- Fetcher `get_all_stocks(market=...)` accepts ONLY cn/hk/us.
  `csi` is a public tag, not a fetcher tag.
- The conversion `csi -> cn` (A-shares only) happens in EXACTLY one
  place: `persistence/stock_list.py` at the call site to
  `fetcher.get_all_stocks(...)`. DB cache key stays `csi` for stability
  with on-disk data.
"""

from unittest.mock import patch

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from stock_data.api.routes import reset_manager
from stock_data.api.schemas import (
    AnnouncementRecord,
    DividendRecord,
    ReportRecord,
)
from stock_data.data_provider.fetchers.akshare import AkshareFetcher
from stock_data.data_provider.fetchers.baostock_fetcher import BaostockFetcher
from stock_data.data_provider.persistence import stock_list as stock_cache
from stock_data.server import app


@pytest.fixture(autouse=True)
def reset_before_test():
    """Reset manager state before each test."""
    reset_manager()
    yield


@pytest.fixture
def client():
    return TestClient(app)


# ============================================================================
# Layer 1: External API — accepts csi/hk/us, rejects cn
# ============================================================================


class TestExternalApiMarketTag:
    """Layer 1 boundary: /api/v1/stocks accepts ONLY csi/hk/us."""

    def test_market_csi_is_accepted(self, client):
        """Public-facing tag for A-shares is csi."""
        # The response may be empty (cache miss + offline), but it must
        # be 200, not 422.
        response = client.get("/api/v1/stocks?market=csi&limit=1")
        assert response.status_code == 200

    def test_market_cn_is_rejected_with_422(self, client):
        """cn is an internal fetcher tag, NOT a public tag. The route
        pattern must reject it with FastAPI 422 validation error."""
        response = client.get("/api/v1/stocks?market=cn")
        assert response.status_code == 422


# ============================================================================
# Layer 3: Fetcher — accepts cn/hk/us, rejects csi
# ============================================================================


class TestFetcherMarketTag:
    """Layer 3 boundary: fetcher.get_all_stocks accepts ONLY cn/hk/us."""

    def test_akshare_get_all_stocks_cn_dispatches(self):
        """cn is the fetcher-internal tag for A-shares — must hit the
        A-share branch (ak.stock_info_a_code_name)."""
        fetcher = AkshareFetcher()
        fake_df = pd.DataFrame(
            {"code": ["600519", "000001"], "name": ["贵州茅台", "平安银行"]}
        )
        with patch("akshare.stock_info_a_code_name", return_value=fake_df) as mock_ak:
            stocks = fetcher.get_all_stocks("cn")
            assert len(stocks) == 2
            assert mock_ak.called

    def test_akshare_get_all_stocks_csi_returns_empty(self):
        """csi is the public tag. The fetcher's if/elif chain does not
        match 'csi', so it returns [] — the boundary conversion in
        persistence is responsible for turning csi into cn before
        reaching the fetcher."""
        fetcher = AkshareFetcher()
        stocks = fetcher.get_all_stocks("csi")
        assert stocks == []

    def test_baostock_get_all_stocks_csi_returns_empty(self):
        """Same invariant for baostock: 'csi' is not a valid fetcher
        market tag."""
        fetcher = BaostockFetcher()
        # Don't init baostock — we want the early-return path on
        # unrecognized market.
        stocks = fetcher.get_all_stocks("csi")
        assert stocks == []


# ============================================================================
# Layer 2: Persistence — converts csi→cn at the fetcher call site
# ============================================================================


class TestPersistenceMarketConversion:
    """Layer 2 boundary: persistence converts public csi to internal cn
    at the single call site to fetcher.get_all_stocks()."""

    def test_persistence_calls_fetcher_with_cn_for_csi_market(self):
        """When the public API asks for market=csi, the fetcher must be
        called with market='cn' (not 'csi'). Verified by patching
        akshare's underlying API and asserting it was called."""
        from stock_data.data_provider.manager import create_default_manager

        manager = create_default_manager()
        fake_df = pd.DataFrame({"code": ["600519"], "name": ["贵州茅台"]})
        with patch(
            "akshare.stock_info_a_code_name", return_value=fake_df
        ) as mock_ak:
            # force refresh so we hit the upstream path
            stocks = stock_cache.get_stock_list(
                "csi", refresh=True, manager=manager
            )
            assert len(stocks) == 1
            # The fetcher's if/elif would NOT match 'csi', so the
            # underlying akshare call would never fire if the conversion
            # is missing. Verifying mock_ak was called proves the
            # conversion happened.
            assert mock_ak.called, (
                "akshare underlying API was not called — "
                "persistence did not convert csi→cn before "
                "fetcher.get_all_stocks()"
            )


# ============================================================================
# Pydantic v2 strict-input (kept from prior bugfix — these don't change)
# ============================================================================


class TestPydanticV2StrictInput:
    """Bug 2: schemas must tolerate upstream None / '' on these specific
    fields without raising ValidationError. Field semantics preserved
    (None/'' → declared default, NOT a type change)."""

    def test_dividend_record_accepts_none_for_bonus_ratio(self):
        record = DividendRecord(
            date="2024-01-01",
            bonus_rmb=10.0,
            transfer_ratio=0.0,
            bonus_ratio=None,
            plan="实施",
        )
        assert record.bonus_ratio == 0
        assert record.date == "2024-01-01"

    def test_dividend_record_accepts_none_for_bonus_rmb_and_transfer(self):
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
        record = ReportRecord(
            title="test",
            publish_date="2024-01-01",
            org="券商A",
            info_code="XYZ",
            rating="买入",
            predict_eps_this=1.0,
            predict_eps_next=1.2,
            predict_eps_next2="",
        )
        assert record.predict_eps_next2 is None

    def test_announcement_record_accepts_none_for_type(self):
        record = AnnouncementRecord(
            title="公告标题",
            type=None,
            date="2024-01-01",
            url="https://example.com",
        )
        assert record.type == ""

    def test_announcement_record_accepts_none_for_title_and_url(self):
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
