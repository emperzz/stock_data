"""
Unit tests for MyquantFetcher.
"""
import pandas as pd
import pytest

from stock_data.data_provider.base import DataCapability
from stock_data.data_provider.fetchers.myquant_fetcher import MyquantFetcher


class TestMyquantFetcherBasics:
    def test_name(self):
        assert MyquantFetcher().name == "MyquantFetcher"

    def test_priority_default(self):
        assert MyquantFetcher().priority == 9

    def test_capabilities(self):
        caps = MyquantFetcher().supported_data_types
        assert DataCapability.STOCK_KLINE in caps
        assert DataCapability.STOCK_LIST in caps
        assert DataCapability.STOCK_INFO in caps  # NEW


class TestGetStockInfo:
    def setup_method(self):
        # Save class-level state for isolation
        self._saved_attempted = MyquantFetcher._init_attempted
        self._saved_ok = MyquantFetcher._init_ok
        self._saved_token = MyquantFetcher._cls_token
        # Force is_available to return True (skip gm.init check)
        MyquantFetcher._init_attempted = True
        MyquantFetcher._init_ok = True
        MyquantFetcher._cls_token = "test_token"
        self.fetcher = MyquantFetcher()

    def teardown_method(self):
        MyquantFetcher._init_attempted = self._saved_attempted
        MyquantFetcher._init_ok = self._saved_ok
        MyquantFetcher._cls_token = self._saved_token

    def test_returns_none_when_unavailable(self):
        MyquantFetcher._init_attempted = True
        MyquantFetcher._init_ok = False
        MyquantFetcher._cls_token = ""
        f = MyquantFetcher()
        assert f.get_stock_info("600519") is None

    def test_normalizes_minimal_payload(self, monkeypatch):
        pytest.importorskip("gm")
        # Simulate gm.api.get_symbols returning a DataFrame. We only use 3 columns:
        # sec_name (encoded), listed_date, delisted_date.
        # Inject a known double-UTF-8-encoded string to verify _decode_gm_name
        encoded = bytes("贵州茅台", "gbk").decode("latin-1")
        df = pd.DataFrame(
            {
                "symbol": ["SHSE.600519"],
                "sec_name": [encoded],
                "listed_date": [pd.Timestamp("2001-08-27 00:00:00+08:00")],
                "delisted_date": [pd.Timestamp("2038-01-01 00:00:00+08:00")],
            }
        )

        def fake_get_symbols(**_kwargs):
            return df

        monkeypatch.setattr("gm.api.get_symbols", fake_get_symbols, raising=False)

        result = self.fetcher.get_stock_info("600519")
        assert result is not None
        assert result["code"] == "600519"
        assert result["name"] == "贵州茅台"  # decoded from double-encoded
        assert result["ename"] == ""
        assert result["market"] == "csi"
        assert result["listed_date"] == "2001-08-27"
        assert result["delisted_date"] == "2038-01-01"
        # Free tier doesn't provide these
        assert result["total_shares"] is None
        assert result["float_shares"] is None
        assert result["concepts"] == []
        # All Zhitu-specific fields are blank
        assert result["registered_address"] == ""
        assert result["secretary"] == ""
        # No 'source' key — manager injects it
        assert "source" not in result

    def test_returns_none_on_empty_df(self, monkeypatch):
        pytest.importorskip("gm")

        def fake_get_symbols(**_kwargs):
            return pd.DataFrame()

        monkeypatch.setattr("gm.api.get_symbols", fake_get_symbols, raising=False)
        assert self.fetcher.get_stock_info("600519") is None

    def test_returns_none_on_exception(self, monkeypatch):
        pytest.importorskip("gm")

        def boom(**_kwargs):
            raise Exception("network error")

        monkeypatch.setattr("gm.api.get_symbols", boom, raising=False)
        assert self.fetcher.get_stock_info("600519") is None

    def test_handles_nat_dates_gracefully(self, monkeypatch):
        """Edge case: upstream returns NaT/None for listed_date / delisted_date.

        Verifies the helper coerces missing timestamps to "" instead of "NaT"
        or a TypeError. This is the common case for *delisted* stocks where
        myquant has no delisted_date yet (or vice versa).
        """
        from stock_data.data_provider.fetchers.myquant_fetcher import _ts_to_date

        # None, NaT, and the empty Timestamp all coerce to "".
        assert _ts_to_date(None) == ""
        assert _ts_to_date(pd.NaT) == ""
        assert _ts_to_date(pd.Timestamp("")) == ""
        # A normal timestamp still works.
        assert _ts_to_date(pd.Timestamp("2001-08-27")) == "2001-08-27"
        # A non-Timestamp object that can be coerced also works.
        assert _ts_to_date("2001-08-27") == "2001-08-27"
