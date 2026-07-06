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


class TestGetKlineDataIndexDispatch:
    """Regression tests for the index branch of MyquantFetcher.get_kline_data.

    Background
    ----------
    ``MyquantFetcher`` declares ``DataCapability.INDEX_KLINE`` so the manager
    routes ``/indices/{code}/kline`` to it as the last-resort fallback (P9).
    But the inherited ``BaseFetcher.get_kline_data`` → ``_fetch_raw_data`` →
    ``_convert_code`` → ``to_myquant_format`` raises ``ValueError("Use
    to_myquant_index_format for index …")`` for any index code, so Myquant
    has been a dead participant on the index failover chain.

    The fix mirrors ``ZhituFetcher.get_kline_data`` (zhitu_fetcher.py:587):
    override ``get_kline_data`` and dispatch on ``index_market_tag`` to the
    index branch (mirroring the existing ``get_index_historical`` body, but
    re-using it through the unified manager entry).
    """

    def _setup_fetcher(self):
        """Build a fetcher with ``is_available()`` forced True."""
        self._saved_attempted = MyquantFetcher._init_attempted
        self._saved_ok = MyquantFetcher._init_ok
        self._saved_token = MyquantFetcher._cls_token
        MyquantFetcher._init_attempted = True
        MyquantFetcher._init_ok = True
        MyquantFetcher._cls_token = "test_token"
        return MyquantFetcher()

    def teardown_method(self):
        MyquantFetcher._init_attempted = self._saved_attempted
        MyquantFetcher._init_ok = self._saved_ok
        MyquantFetcher._cls_token = self._saved_token

    def _fake_index_history(self):
        """Mimic ``gm.api.history`` payload for a CSI index (000001 / 399006)."""
        return pd.DataFrame(
            {
                "symbol": ["SHSE.000001"] * 3,
                "frequency": ["1d"] * 3,
                "open": [3445.85, 3461.15, 3459.59],
                "close": [3457.75, 3461.34, 3459.34],
                "high": [3459.59, 3461.50, 3460.98],
                "low": [3441.04, 3457.00, 3457.00],
                "amount": [5.535e11, 5.012e11, 5.359e10],
                "volume": [4.444e8, 4.500e8, 4.999e7],
                "bob": pd.to_datetime(["2025-07-01", "2025-07-02", "2025-07-03"]),
                "eob": pd.to_datetime(
                    ["2025-07-01 15:00", "2025-07-02 15:00", "2025-07-03 15:00"]
                ),
            }
        )

    def test_index_code_399006_dispatches_to_index_branch(self, monkeypatch):
        """Shenzhen index 399006 must be routed via to_myquant_index_format.

        Before the fix: ``to_myquant_format("399006")`` raises
        ``ValueError("Use to_myquant_index_format for index 399006")`` and
        the manager sees Myquant as a no-op on the index chain.
        """
        captured: dict = {}

        def fake_history(**kwargs):
            captured.update(kwargs)
            return self._fake_index_history()

        monkeypatch.setattr("gm.api.history", fake_history, raising=False)
        fetcher = self._setup_fetcher()

        df = fetcher.get_kline_data("399006", days=4, frequency="d")

        assert df is not None
        assert not df.empty
        # Index branch must call gm.api.history with the SZSE-prefixed symbol
        # (matches ``to_myquant_index_format("399006") → "SZSE.399006"``).
        assert captured["symbol"] == "SZSE.399006"
        assert captured["frequency"] == "1d"
        # Standard K-line columns must be present — these are what
        # ``_build_kline_data`` in api/routes reads from.
        for col in ("date", "open", "high", "low", "close", "volume", "amount"):
            assert col in df.columns, f"missing column {col}"
        # pct_chg derived from inter-bar close delta (see _normalize_index_df)
        assert "pct_chg" in df.columns

    def test_index_code_000xxx_dispatches_to_index_branch(self, monkeypatch):
        """Shanghai index 000300 must use the SHSE prefix."""
        captured: dict = {}

        def fake_history(**kwargs):
            captured.update(kwargs)
            return self._fake_index_history()

        monkeypatch.setattr("gm.api.history", fake_history, raising=False)
        fetcher = self._setup_fetcher()

        fetcher.get_kline_data("000300", days=4, frequency="d")

        assert captured["symbol"] == "SHSE.000300"

    def test_index_branch_minute_frequency_raises(self, monkeypatch):
        """Myquant index only supports 'd'; w/m/5/15/30/60 must raise.

        Mirrors the existing ``get_index_historical`` guard so the unified
        ``get_kline_data`` entry inherits the same constraint (failover to
        the next fetcher handles non-d frequencies).
        """
        pytest.importorskip("gm")
        from stock_data.data_provider.base import DataFetchError

        fetcher = self._setup_fetcher()
        # 5-minute: should raise WITHOUT calling gm.api.history (early guard)
        with pytest.raises(DataFetchError, match="frequency"):
            fetcher.get_kline_data("399006", days=1, frequency="5")

    def test_index_branch_non_csi_raises(self, monkeypatch):
        """Non-CSI index (e.g. HSI) is unsupported by myquant — must raise."""
        from stock_data.data_provider.base import DataFetchError

        fetcher = self._setup_fetcher()
        with pytest.raises(DataFetchError, match="non-CSI"):
            fetcher.get_kline_data("HSI", days=4, frequency="d")

    def test_index_branch_us_index_raises(self, monkeypatch):
        """US index (SPX) goes through the reverse-lookup → 'us' branch in
        ``index_market_tag`` and must also raise non-CSI.

        Distinct from the HSI test (which is HK) because ``index_market_tag``
        has two non-CSI paths: HK (``HSI`` in ``HK_INDEX_MAP``) and US
        (``SPX`` in ``US_INDEX_MAP``).
        """
        from stock_data.data_provider.base import DataFetchError

        fetcher = self._setup_fetcher()
        with pytest.raises(DataFetchError, match="non-CSI"):
            fetcher.get_kline_data("SPX", days=4, frequency="d")

    def test_supports_kline_index_daily_only(self):
        """Manager two-stage filter gate: index is daily-only.

        Before I-1 tightening: ``supports_kline("5", "", "csi", "index")``
        returned True, so the manager would pick Myquant and then immediately
        fail over out of ``get_index_historical`` (which only supports ``d``).
        Now: only ``"d"`` returns True for index asset. Stocks unaffected.
        """
        fetcher = self._setup_fetcher()
        # Index: only "d" is supported
        assert fetcher.supports_kline("d", "", "csi", "index") is True
        for period in ("w", "m", "5", "15", "30", "60", "1"):
            assert fetcher.supports_kline(period, "", "csi", "index") is False, (
                f"index asset must reject {period!r} per I-1"
            )
        # Stock: unchanged (d/5/15/30/60 still supported; w/m/1 still rejected)
        assert fetcher.supports_kline("d", "", "csi", "stock") is True
        assert fetcher.supports_kline("5", "", "csi", "stock") is True
        for period in ("w", "m", "1"):
            assert fetcher.supports_kline(period, "", "csi", "stock") is False
        # Non-CSI markets: still rejected for both assets
        for asset in ("index", "stock"):
            assert fetcher.supports_kline("d", "", "hk", asset) is False
            assert fetcher.supports_kline("d", "", "us", asset) is False

    def test_stock_code_unchanged(self, monkeypatch):
        """Stock codes must continue to flow through the inherited path.

        Guards against accidentally breaking the stock branch while fixing
        the index one. We don't assert on the upstream symbol here (that's
        covered by other tests) — we just confirm no DataFetchError about
        ``to_myquant_index_format`` is raised.
        """
        def fake_history(**_kwargs):
            return pd.DataFrame(
                {
                    "symbol": ["SHSE.600519"],
                    "frequency": ["1d"],
                    "open": [1700.0],
                    "close": [1710.0],
                    "high": [1715.0],
                    "low": [1695.0],
                    "amount": [5e10],
                    "volume": [3e7],
                    "bob": pd.to_datetime(["2024-01-02"]),
                    "eob": pd.to_datetime(["2024-01-02 15:00"]),
                }
            )

        monkeypatch.setattr("gm.api.history", fake_history, raising=False)
        fetcher = self._setup_fetcher()

        # Must not raise "Use to_myquant_index_format ..." for a stock code.
        df = fetcher.get_kline_data("600519", days=1, frequency="d")
        assert df is not None
        assert "date" in df.columns
