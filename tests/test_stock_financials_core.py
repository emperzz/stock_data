"""Registration + manager routing contract for the financial capabilities.

Spec rev2 §4. Pins the P0 guards that make the failover chain behave:
- snapshot speaks None (never {}) so an empty primary falls through;
- financial methods use default empty_is_failure=False (authoritative
  empty for BJ / new listings must NOT be treated as soft failure);
- every new flag has CAPABILITY_TO_METHOD + CAPABILITY_LABELS entries
  (also enforced fleet-wide by tests/test_capability_method_map.py).
"""

from __future__ import annotations

import threading

import pytest


def _mk_manager(fetchers):
    """Minimal DataFetcherManager scaffold for capability-routing tests."""
    from stock_data.data_provider.manager import DataFetcherManager

    m = DataFetcherManager.__new__(DataFetcherManager)
    m._circuit_breaker = None
    m._lock = threading.RLock()
    m._fetchers = fetchers
    return m


class TestRegistration:
    def test_capability_flags_exist(self):
        from stock_data.data_provider.base import DataCapability

        for name in ("STOCK_FINANCIAL", "STOCK_FINANCIAL_SERIES", "STOCK_MAIN_BUSINESS"):
            assert hasattr(DataCapability, name), name

    def test_capability_method_map(self):
        from stock_data.data_provider.base import CAPABILITY_TO_METHOD, DataCapability

        assert CAPABILITY_TO_METHOD[DataCapability.STOCK_FINANCIAL] == "get_financial_snapshot"
        assert CAPABILITY_TO_METHOD[DataCapability.STOCK_FINANCIAL_SERIES] == "get_financial_history"
        assert CAPABILITY_TO_METHOD[DataCapability.STOCK_MAIN_BUSINESS] == "get_main_business_composition"

    def test_capability_labels_registered(self):
        from stock_data.data_provider.base import DataCapability
        from stock_data.explorer.tags import CAPABILITY_LABELS

        for name in ("STOCK_FINANCIAL", "STOCK_FINANCIAL_SERIES", "STOCK_MAIN_BUSINESS"):
            cap = getattr(DataCapability, name)
            entry = CAPABILITY_LABELS[cap.name]
            assert entry["label"].strip() and entry["icon"].strip()

    def test_fetcher_declarations(self):
        from stock_data.data_provider.base import DataCapability
        from stock_data.data_provider.fetchers.eastmoney.fetcher import EastMoneyFetcher
        from stock_data.data_provider.fetchers.zhitu_fetcher import ZhituFetcher
        from stock_data.data_provider.fetchers.zzshare_fetcher import ZzshareFetcher

        fin = DataCapability.STOCK_FINANCIAL
        ser = DataCapability.STOCK_FINANCIAL_SERIES
        mb = DataCapability.STOCK_MAIN_BUSINESS
        assert fin in ZzshareFetcher.supported_data_types and ser in ZzshareFetcher.supported_data_types
        assert fin in ZhituFetcher.supported_data_types and ser in ZhituFetcher.supported_data_types
        assert mb in EastMoneyFetcher.supported_data_types
        # eastmoney must NOT claim the failover-chain caps, zzshare/zhitu not MAIN_BUSINESS
        assert mb not in ZzshareFetcher.supported_data_types
        assert fin not in EastMoneyFetcher.supported_data_types


class TestManagerRouting:
    def _manager(self, primary, backup, single):
        from stock_data.data_provider.manager import DataFetcherManager

        m = DataFetcherManager.__new__(DataFetcherManager)
        m._circuit_breaker = None
        caps = DataFetcherManager.__mro__  # noqa: F841
        m._fetchers = [primary, backup, single]
        return m

    def test_snapshot_failover_order_and_source(self, monkeypatch):
        from stock_data.data_provider.base import DataCapability
        from stock_data.data_provider.manager import DataFetcherManager

        calls = []

        class ZZ:
            name = "ZzshareFetcher"
            priority = 2
            supported_markets = {"csi"}
            supported_data_types = DataCapability.STOCK_FINANCIAL
            def get_financial_snapshot(self, code):
                calls.append("zz")
                return None  # BJ empty — must fall through

        class ZT:
            name = "ZhituFetcher"
            priority = 5
            supported_markets = {"csi"}
            supported_data_types = DataCapability.STOCK_FINANCIAL
            def get_financial_snapshot(self, code):
                calls.append("zt")
                return {"eps": 1.0}

        m = _mk_manager([ZZ(), ZT()])
        out, source = m.get_financial_snapshot("920002")
        assert calls == ["zz", "zt"]
        assert out == {"eps": 1.0}
        assert source == "ZhituFetcher"

    def test_snapshot_both_empty_returns_coherent_empty(self, monkeypatch):
        from stock_data.data_provider.base import DataCapability
        from stock_data.data_provider.manager import DataFetcherManager

        class Empty:
            priority = 2
            supported_markets = {"csi"}
            supported_data_types = DataCapability.STOCK_FINANCIAL
            def __init__(self, name):
                self.name = name
            def get_financial_snapshot(self, code):
                return None

        m = _mk_manager([Empty("ZzshareFetcher"), Empty("ZhituFetcher")])
        out, source = m.get_financial_snapshot("920002")
        assert out is None
        assert source == ""

    def test_history_window_args_forwarded(self):
        from stock_data.data_provider.base import DataCapability
        from stock_data.data_provider.manager import DataFetcherManager

        seen = {}

        class H:
            name = "ZzshareFetcher"
            priority = 2
            supported_markets = {"csi"}
            supported_data_types = DataCapability.STOCK_FINANCIAL_SERIES
            def get_financial_history(self, code, start_date=None, end_date=None):
                seen.update(code=code, s=start_date, e=end_date)
                return [{"report_date": "2026-06-30"}]

        m = _mk_manager([H()])
        recs, source = m.get_financial_history("600519", start_date="2026-01-01", end_date="2026-10-08")
        assert seen == {"code": "600519", "s": "2026-01-01", "e": "2026-10-08"}
        assert source == "ZzshareFetcher"

    def test_main_business_single_source(self):
        from stock_data.data_provider.base import DataCapability, DataFetchError
        from stock_data.data_provider.manager import DataFetcherManager

        class EM:
            name = "EastMoneyFetcher"
            priority = 6
            supported_markets = {"csi"}
            supported_data_types = DataCapability.STOCK_MAIN_BUSINESS
            def get_main_business_composition(self, code, category=None, report_date=None):
                if code == "boom":
                    raise DataFetchError("down")
                return {"report_date": "2026-06-30", "records": [], "available_report_dates": [], "requested_report_date_available": None}

        m = _mk_manager([EM()])
        out, source = m.get_main_business_composition("600519", category="product")
        assert source == "EastMoneyFetcher"
        with pytest.raises(DataFetchError):
            m.get_main_business_composition("boom")


class TestEmptyOkIsAdditive:
    def test_caps_without_empty_ok_still_raise_on_all_none(self):
        """empty_ok defaults False: a non-opted cap keeps the old
        all-None → DataFetchError behavior byte-identical."""
        from stock_data.data_provider.base import DataCapability, DataFetchError
        from stock_data.data_provider.manager import DataFetcherManager

        class AllNone:
            name = "ZzshareFetcher"
            priority = 2
            supported_markets = {"csi"}
            supported_data_types = DataCapability.STOCK_FINANCIAL_SERIES
            def get_financial_history(self, code, start_date=None, end_date=None):
                return None

        m = _mk_manager([AllNone()])
        with pytest.raises(DataFetchError):
            m.get_financial_history("600519")
