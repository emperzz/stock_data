"""
Structural / unit tests for fetchers that previously lacked coverage:
Akshare, Baostock, Yfinance, Zhitu, Tushare.

Tests verify code-converter delegation, basic metadata, and key edge
cases without hitting upstream APIs.
"""

from unittest.mock import patch

import pytest

from stock_data.data_provider.base import DataCapability
from stock_data.data_provider.utils import code_converter as cc

# ====================================================================
# AkshareFetcher
# ====================================================================

class TestAkshareFetcher:
    @pytest.fixture
    def fetcher(self):
        from stock_data.data_provider.fetchers.akshare import AkshareFetcher
        return AkshareFetcher()

    def test_name_and_priority(self, fetcher):
        assert fetcher.name == "AkshareFetcher"
        assert fetcher.priority == 2

    def test_is_available(self, fetcher):
        """is_available() must reflect whether the akshare package is importable.

        Mirrors the yfinance pattern: probe via importlib.util.find_spec.
        Mock find_spec to simulate "akshare installed" so this test is
        environment-independent.
        """
        from unittest.mock import MagicMock
        with patch("importlib.util.find_spec", return_value=MagicMock()) as m:
            assert fetcher.is_available() is True
            m.assert_called_with("akshare")

    def test_is_available_unavailable(self, fetcher):
        """When akshare is not installed, is_available() must return False."""
        with patch("importlib.util.find_spec", return_value=None):
            assert fetcher.is_available() is False

    def test_supported_markets(self, fetcher):
        assert "csi" in fetcher.supported_markets
        assert "hk" in fetcher.supported_markets

    def test_capabilities(self, fetcher):
        caps = [
            DataCapability.HISTORICAL_DWM, DataCapability.HISTORICAL_MIN,
            DataCapability.REALTIME_QUOTE, DataCapability.STOCK_LIST,
            DataCapability.TRADE_CALENDAR,
            DataCapability.INDEX_QUOTE, DataCapability.INDEX_HISTORICAL,
            DataCapability.INDEX_INTRADAY, DataCapability.STOCK_ZT_POOL,
        ]
        for c in caps:
            assert c in fetcher.supported_data_types

    def test_stock_board_capability_removed(self, fetcher):
        """STOCK_BOARD migrated to EastMoney/Zhitu; Akshare no longer declares it."""
        assert DataCapability.STOCK_BOARD not in fetcher.supported_data_types

    def test_convert_code_delegates_to_converter(self, fetcher):
        """_convert_code delegates to to_akshare_format."""
        code = fetcher._convert_code("600519")
        assert code == cc.to_akshare_format("600519")

    def test_convert_code_hk(self, fetcher):
        assert fetcher._convert_code("HK00700") == "00700.hk"

    def test_convert_code_us_index(self, fetcher):
        assert fetcher._convert_code("SPX") == ".INX"

    def test_map_adjust(self, fetcher):
        # Akshare maps "" to "" (not None), unlike other fetchers
        assert fetcher._map_adjust("") == ""
        assert fetcher._map_adjust("qfq") == "qfq"
        assert fetcher._map_adjust("hfq") == "hfq"

    def test_board_methods_removed(self, fetcher):
        """STOCK_BOARD migrated off AkshareFetcher; legacy methods should be gone."""
        assert not hasattr(fetcher, "get_all_concept_boards")
        assert not hasattr(fetcher, "get_all_industry_boards")
        assert not hasattr(fetcher, "get_concept_board_stocks")
        assert not hasattr(fetcher, "get_industry_board_stocks")

    def test_index_methods_exist(self, fetcher):
        assert hasattr(fetcher, "get_index_realtime_quote")
        assert hasattr(fetcher, "get_index_historical")
        assert hasattr(fetcher, "get_index_intraday")


# ====================================================================
# BaostockFetcher
# ====================================================================

class TestBaostockFetcher:
    @pytest.fixture
    def fetcher(self):
        from stock_data.data_provider.fetchers.baostock_fetcher import BaostockFetcher
        return BaostockFetcher()

    def test_name_and_priority(self, fetcher):
        assert fetcher.name == "BaostockFetcher"
        assert fetcher.priority == 1

    def test_supported_markets(self, fetcher):
        assert fetcher.supported_markets == {"csi"}

    def test_capabilities(self, fetcher):
        caps = [
            DataCapability.HISTORICAL_DWM, DataCapability.HISTORICAL_MIN,
            DataCapability.TRADE_CALENDAR, DataCapability.INDEX_HISTORICAL,
        ]
        for c in caps:
            assert c in fetcher.supported_data_types

    def test_convert_code_delegates_to_converter(self, fetcher):
        """_convert_code delegates to to_baostock_format."""
        bs_code, yw_code = fetcher._convert_code("600519")
        assert (bs_code, yw_code) == cc.to_baostock_format("600519")

    def test_convert_code_non_csi_index_raises(self, fetcher):
        from stock_data.data_provider.base import DataFetchError
        with pytest.raises(DataFetchError, match="Baostock does not support"):
            fetcher._convert_code("SPX")

    def test_convert_code_csi_index(self, fetcher):
        bs_code, yw_code = fetcher._convert_code("000300")
        assert bs_code == "sh.000300"

    def test_map_adjust(self, fetcher):
        assert fetcher._map_adjust("") == "3"
        assert fetcher._map_adjust("qfq") == "2"
        assert fetcher._map_adjust("hfq") == "1"

    def test_realtime_quote_returns_none(self, fetcher):
        """Baostock has no realtime API."""
        assert fetcher.get_realtime_quote("600519") is None


# ====================================================================
# YfinanceFetcher
# ====================================================================

class TestYfinanceFetcher:
    @pytest.fixture
    def fetcher(self):
        from stock_data.data_provider.fetchers.yfinance_fetcher import YfinanceFetcher
        return YfinanceFetcher()

    def test_name_and_priority(self, fetcher):
        assert fetcher.name == "YfinanceFetcher"
        assert fetcher.priority == 3

    def test_supported_markets(self, fetcher):
        assert fetcher.supported_markets == {"csi", "hk", "us"}

    def test_capabilities(self, fetcher):
        caps = [
            DataCapability.HISTORICAL_DWM, DataCapability.HISTORICAL_MIN,
            DataCapability.REALTIME_QUOTE, DataCapability.INDEX_HISTORICAL,
            DataCapability.INDEX_QUOTE,
        ]
        for c in caps:
            assert c in fetcher.supported_data_types

    def test_convert_code_delegates_to_converter(self, fetcher):
        assert fetcher._convert_code("600519") == cc.to_yfinance_format("600519")

    def test_convert_code_a_share(self, fetcher):
        assert fetcher._convert_code("600519") == "600519.SS"

    def test_convert_code_us_stock(self, fetcher):
        assert fetcher._convert_code("AAPL") == "AAPL"

    def test_convert_code_us_index(self, fetcher):
        assert fetcher._convert_code("SPX") == "^GSPC"

    def test_convert_code_hk_stock(self, fetcher):
        assert fetcher._convert_code("HK00700") == "00700.HK"

    def test_map_adjust(self, fetcher):
        assert fetcher._map_adjust("") is None
        assert fetcher._map_adjust("qfq") == "qfq"
        assert fetcher._map_adjust("hfq") == "qfq"

    def test_index_methods_exist(self, fetcher):
        assert hasattr(fetcher, "get_index_realtime_quote")
        assert hasattr(fetcher, "get_index_historical")


# ====================================================================
# ZhituFetcher
# ====================================================================

class TestZhituFetcher:
    @pytest.fixture
    def fetcher(self):
        from stock_data.data_provider.fetchers.zhitu_fetcher import ZhituFetcher
        return ZhituFetcher()

    def test_name_and_priority(self, fetcher):
        assert fetcher.name == "ZhituFetcher"
        assert fetcher.priority == 4

    def test_supported_markets(self, fetcher):
        assert fetcher.supported_markets == {"csi"}

    def test_capabilities(self, fetcher):
        caps = [DataCapability.REALTIME_QUOTE, DataCapability.STOCK_ZT_POOL]
        for c in caps:
            assert c in fetcher.supported_data_types

    def test_convert_code_delegates_to_converter(self, fetcher):
        assert fetcher._convert_code("600519") == cc.to_zhitu_format("600519")

    def test_market_suffix_delegates_to_converter(self, fetcher):
        assert fetcher._market_suffix("600519") == cc.to_zhitu_market_suffix("600519")

    def test_market_suffix_sh(self, fetcher):
        assert fetcher._market_suffix("600519") == ".sh"

    def test_market_suffix_sz(self, fetcher):
        assert fetcher._market_suffix("000001") == ".sz"


# ====================================================================
# TushareFetcher
# ====================================================================

class TestTushareFetcher:
    @pytest.fixture
    def fetcher(self):
        from stock_data.data_provider.fetchers.tushare_fetcher import TushareFetcher
        return TushareFetcher()

    def test_name_and_priority(self, fetcher):
        assert fetcher.name == "TushareFetcher"
        assert fetcher.priority == 0

    def test_supported_markets(self, fetcher):
        assert fetcher.supported_markets == {"csi"}

    def test_capabilities(self, fetcher):
        caps = [
            DataCapability.HISTORICAL_DWM, DataCapability.REALTIME_QUOTE,
            DataCapability.INDEX_HISTORICAL,
        ]
        for c in caps:
            assert c in fetcher.supported_data_types

    def test_map_adjust(self, fetcher):
        assert fetcher._map_adjust("") is None
        assert fetcher._map_adjust("qfq") == "qfq"

    @patch("stock_data.data_provider.fetchers.tushare_fetcher.TushareFetcher._ensure_api")
    def test_is_available_without_token(self, mock_ensure, fetcher):
        fetcher._api = None
        fetcher._initialized = True
        assert fetcher.is_available() is False

    def test_index_methods_exist(self, fetcher):
        assert hasattr(fetcher, "get_index_historical")


# ====================================================================
# MyquantFetcher
# ====================================================================

class TestMyquantFetcher:
    @pytest.fixture
    def fetcher(self, monkeypatch):
        """Build a fetcher with token pre-set.

        Mocks ``gm.api.set_token`` so the lazy ``_ensure_initialized()`` in
        ``is_available()`` succeeds in test environments where the real
        gm SDK is incompatible with the installed protobuf version
        (``Descriptors cannot be created directly``). Also sets
        ``PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION=python`` so the gm.pb
        protobuf chain imports via the pure-Python parser — the C++-backed
        parser chokes on the auto-generated _pb2 descriptors in the
        shipped gm 3.0.180 wheel. Production code with a working gm
        install will exercise the real set_token path.
        """
        monkeypatch.setenv("MYQUANT_TOKEN", "test-token")
        monkeypatch.setenv("PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION", "python")
        pytest.importorskip("gm")
        monkeypatch.setattr("gm.api.set_token", lambda *_a, **_k: None, raising=False)
        from stock_data.data_provider.fetchers.myquant_fetcher import MyquantFetcher
        return MyquantFetcher()

    @pytest.fixture
    def fetcher_no_token(self, monkeypatch):
        """Build a fetcher without a token."""
        monkeypatch.delenv("MYQUANT_TOKEN", raising=False)
        from stock_data.data_provider.fetchers.myquant_fetcher import MyquantFetcher
        return MyquantFetcher()

    def test_name_and_priority(self, fetcher):
        assert fetcher.name == "MyquantFetcher"
        # Myquant is a last-resort backup — default priority 9 places it
        # after every richer source in the failover chain.
        assert fetcher.priority == 9

    def test_supported_markets(self, fetcher):
        assert fetcher.supported_markets == {"csi"}

    def test_capabilities(self, fetcher):
        caps = [
            DataCapability.HISTORICAL_DWM, DataCapability.HISTORICAL_MIN,
            DataCapability.REALTIME_QUOTE, DataCapability.STOCK_LIST,
            DataCapability.TRADE_CALENDAR, DataCapability.INDEX_HISTORICAL,
            DataCapability.INDEX_INTRADAY,
        ]
        for c in caps:
            assert c in fetcher.supported_data_types, f"missing {c}"

    def test_is_available_with_token(self, fetcher):
        # is_available() must trigger _ensure_initialized() — once it
        # returns True, _initialized stays True so subsequent gm.api calls
        # have a configured token.
        assert fetcher.is_available() is True
        assert fetcher._initialized is True

    def test_is_available_without_token(self, fetcher_no_token):
        # Without MYQUANT_TOKEN, is_available() returns False (and rolls
        # _initialized back to False so the fetcher is not registered).
        assert fetcher_no_token.is_available() is False
        assert fetcher_no_token._initialized is False

    def test_map_adjust(self, fetcher):
        from stock_data.data_provider.fetchers.myquant_fetcher import (
            ADJUST_NONE,
            ADJUST_POST,
            ADJUST_PREV,
        )
        assert fetcher._map_adjust("") == ADJUST_NONE
        assert fetcher._map_adjust(None) == ADJUST_NONE
        assert fetcher._map_adjust("qfq") == ADJUST_PREV
        assert fetcher._map_adjust("hfq") == ADJUST_POST

    def test_convert_code_sh(self, fetcher):
        from stock_data.data_provider.utils.code_converter import to_myquant_format
        assert fetcher._convert_code("600519") == to_myquant_format("600519")

    def test_convert_code_sz(self, fetcher):
        from stock_data.data_provider.utils.code_converter import to_myquant_format
        assert fetcher._convert_code("000002") == to_myquant_format("000002")

    def test_convert_code_hk_raises(self, fetcher):
        from stock_data.data_provider.base import DataFetchError
        with pytest.raises(DataFetchError, match="Myquant does not support"):
            fetcher._convert_code("HK00700")

    def test_fetch_unsupported_weekly_raises(self, fetcher):
        from stock_data.data_provider.base import DataFetchError
        with pytest.raises(DataFetchError, match="does not support frequency"):
            fetcher._fetch_raw_data("600519", "2024-01-01", "2024-01-31", frequency="w")

    def test_fetch_unsupported_monthly_raises(self, fetcher):
        from stock_data.data_provider.base import DataFetchError
        with pytest.raises(DataFetchError, match="does not support frequency"):
            fetcher._fetch_raw_data("600519", "2024-01-01", "2024-01-31", frequency="m")

    def test_fetch_unsupported_1min_raises(self, fetcher):
        from stock_data.data_provider.base import DataFetchError
        with pytest.raises(DataFetchError, match="does not support frequency"):
            fetcher._fetch_raw_data("600519", "2024-01-01", "2024-01-31", frequency="1")

    def test_normalize_history_dataframe(self, fetcher):
        """myquant history returns columns: open, close, high, low, amount, volume, bob, eob.
        Normalization should map 'bob' → 'date' and produce STANDARD_COLUMNS."""
        import pandas as pd
        raw = pd.DataFrame({
            "symbol": ["SHSE.600519"] * 3,
            "frequency": ["1d"] * 3,
            "open": [1700.0, 1710.0, 1720.0],
            "close": [1710.0, 1720.0, 1730.0],
            "high": [1715.0, 1725.0, 1735.0],
            "low": [1695.0, 1705.0, 1715.0],
            "amount": [1e9, 1.1e9, 1.2e9],
            "volume": [1e6, 1.1e6, 1.2e6],
            "bob": pd.to_datetime(["2024-01-01", "2024-01-02", "2024-01-03"]),
            "eob": pd.to_datetime(["2024-01-01 15:00", "2024-01-02 15:00", "2024-01-03 15:00"]),
        })
        normalized = fetcher._normalize_data(raw, "600519")
        # Required STANDARD_COLUMNS
        for col in ["date", "open", "high", "low", "close", "volume", "amount"]:
            assert col in normalized.columns, f"missing {col}"
        # pct_chg is derived from previous row's close (close_t / close_{t-1} - 1) * 100
        # to match the rest of the codebase's convention (not close vs open).
        assert "pct_chg" in normalized.columns
        # First row has no prior reference → pct_chg is NaN/None.
        assert pd.isna(normalized.iloc[0]["pct_chg"]) or normalized.iloc[0]["pct_chg"] is None
        # Second row: (1720-1710)/1710 * 100 ≈ 0.58
        assert abs(normalized.iloc[1]["pct_chg"] - 0.58) < 0.01
        # Third row: (1730-1720)/1720 * 100 ≈ 0.58
        assert abs(normalized.iloc[2]["pct_chg"] - 0.58) < 0.01
        # code column added
        assert "code" in normalized.columns
        assert normalized.iloc[0]["code"] == "600519"

    def test_normalize_data_sorts_by_date_before_pct_chg(self, fetcher):
        """Inter-bar pct_chg derivation requires chronological order.

        If myquant returns rows out of order, _normalize_data must sort by
        date before computing pct_chg so the result is correct.
        """
        import pandas as pd
        raw = pd.DataFrame({
            # Note: deliberately out of order
            "bob": pd.to_datetime(["2024-01-03", "2024-01-01", "2024-01-02"]),
            "open": [1720.0, 1700.0, 1710.0],
            "close": [1730.0, 1710.0, 1720.0],
            "high": [1735.0, 1715.0, 1725.0],
            "low": [1715.0, 1695.0, 1705.0],
            "amount": [1.2e9, 1.0e9, 1.1e9],
            "volume": [1.2e6, 1.0e6, 1.1e6],
        })
        normalized = fetcher._normalize_data(raw, "600519")
        # After sort by date, the rows are [1710, 1720, 1730] and pct_chg
        # is derived as [(NaN), (1720-1710)/1710, (1730-1720)/1720].
        assert pd.isna(normalized.iloc[0]["pct_chg"]) or normalized.iloc[0]["pct_chg"] is None
        assert abs(normalized.iloc[1]["pct_chg"] - 0.58) < 0.01
        assert abs(normalized.iloc[2]["pct_chg"] - 0.58) < 0.01
        # And the dates are in ascending order after the sort.
        assert list(normalized["date"]) == sorted(normalized["date"])

    def test_realtime_quote_without_token_returns_none(self, fetcher_no_token):
        assert fetcher_no_token.get_realtime_quote("600519") is None

    def test_realtime_quote_uses_myquant_source(self, fetcher, monkeypatch):
        """When gm returns data, source should be RealtimeSource.MYQUANT.

        Also asserts that is_available() → _ensure_initialized() is
        exercised end-to-end (set_token must be called before any
        gm.api.current_price invocation, mirroring the Baostock/Tushare
        pattern).
        """
        pytest.importorskip("gm")  # Skip gracefully if gm SDK is not installed
        from stock_data.data_provider.core.types import RealtimeSource

        def fake_set_token(token, **_kwargs):
            # Record the call so the test can verify it happened.
            fake_set_token.called_with = token

        def fake_current_price(symbols, **_kwargs):
            return [{"symbol": "SHSE.600519", "price": 1700.5, "created_at": None}]

        monkeypatch.setattr("gm.api.set_token", fake_set_token, raising=False)
        monkeypatch.setattr("gm.api.current_price", fake_current_price, raising=False)

        quote = fetcher.get_realtime_quote("600519")
        # set_token must have been invoked via _ensure_initialized() —
        # this guards against the "lazy init is defined but never called"
        # regression that commit 14ab96b introduced for myquant.
        assert getattr(fake_set_token, "called_with", None) == "test-token"
        assert quote is not None
        assert quote.code == "600519"
        assert quote.price == 1700.5
        assert quote.source == RealtimeSource.MYQUANT
        # Other fields are intentionally None
        assert quote.volume is None
        assert quote.change_pct is None
        assert quote.pre_close is None

    def test_trade_calendar_without_token_returns_none(self, fetcher_no_token):
        assert fetcher_no_token.get_trade_calendar() is None

    def test_trade_calendar_parses_myquant_dataframe(self, fetcher, monkeypatch):
        pytest.importorskip("gm")
        import pandas as pd

        def fake_calendar(*_args, **_kwargs):
            return pd.DataFrame({
                "date": ["2024-01-01", "2024-01-02", "2024-01-03"],
                "trade_date": ["", "2024-01-02", "2024-01-03"],
                "pre_trade_date": ["", "2023-12-29", "2024-01-02"],
                "next_trade_date": ["2024-01-02", "2024-01-03", "2024-01-04"],
            })

        monkeypatch.setattr(
            "gm.api.get_trading_dates_by_year", fake_calendar, raising=False
        )
        dates = fetcher.get_trade_calendar()
        assert dates == ["2024-01-02", "2024-01-03"]  # Empty trade_date filtered, sorted asc

    def test_get_all_stocks_without_token_returns_empty(self, fetcher_no_token):
        assert fetcher_no_token.get_all_stocks("csi") == []

    def test_get_all_stocks_normalizes_myquant_dataframe(self, fetcher, monkeypatch):
        pytest.importorskip("gm")
        import pandas as pd

        def _g(s: str) -> str:
            """Simulate gm's double-encoding: GBK bytes read as latin-1 string."""
            return bytes(s, "gbk").decode("latin-1")

        def fake_get_symbols(*_args, **_kwargs):
            return pd.DataFrame({
                # 600519 (Shanghai main, passes filter)
                # 002415 (Shenzhen main, starts with "002" — passes filter)
                # 000001 (Shenzhen, starts with "000" — fails filter; 000xxx
                #   is reserved for Shanghai indices in A_SHARE_STOCK_PREFIXES
                #   and defensively excluded even when returned under SZSE)
                "symbol": ["SHSE.600519", "SZSE.002415", "SZSE.000001"],
                # gm 3.x returns these double-encoded; the fetcher's
                # _decode_gm_name helper must reverse the encoding.
                "sec_name": [_g("贵州茅台"), _g("海康威视"), _g("平安银行")],
                "is_st": [False, False, False],
                "is_suspended": [False, False, False],
                "upper_limit": [1872.10, 35.00, 11.55],
                "lower_limit": [1531.72, 28.50, 9.45],
                "turn_rate": [0.5, 0.3, 0.4],
                "adj_factor": [1.0, 1.0, 1.0],
                "pre_close": [1701.91, 30.00, 10.50],
            })

        monkeypatch.setattr("gm.api.get_symbols", fake_get_symbols, raising=False)
        stocks = fetcher.get_all_stocks("csi")
        # 000001 dropped by is_a_share_stock_code defensive filter.
        assert len(stocks) == 2
        # SHSE.600519 → "600519" (strip exchange prefix)
        assert stocks[0]["code"] == "600519"
        assert stocks[0]["name"] == "贵州茅台"
        assert stocks[0]["upper_limit"] == 1872.10
        # SZSE.002415 → "002415"
        assert stocks[1]["code"] == "002415"
        assert stocks[1]["name"] == "海康威视"

    def test_decode_gm_name_passes_through_clean_utf8(self):
        """Future gm fix: helper must not corrupt already-clean names."""
        pytest.importorskip("gm")
        from stock_data.data_provider.fetchers.myquant_fetcher import _decode_gm_name

        assert _decode_gm_name("贵州茅台") == "贵州茅台"
        assert _decode_gm_name("") == ""
        assert _decode_gm_name(None) == ""

    def test_decode_gm_name_handles_garbled_input(self):
        """Current gm 3.x behavior: must reverse the double-encoding."""
        pytest.importorskip("gm")
        from stock_data.data_provider.fetchers.myquant_fetcher import _decode_gm_name

        garbled = bytes("浦发银行", "gbk").decode("latin-1")
        assert _decode_gm_name(garbled) == "浦发银行"

    def test_get_all_stocks_filters_non_a_share_codes(self, fetcher, monkeypatch):
        """Defensive filter drops ETFs/funds/indices (sec_type1 widening guard)."""
        pytest.importorskip("gm")
        import pandas as pd

        def fake_get_symbols(*_args, **_kwargs):
            return pd.DataFrame({
                "symbol": [
                    "SHSE.600519",   # pass — Shanghai main
                    "SHSE.510500",   # drop — ETF (51 prefix)
                    "SHSE.510880",   # drop — ETF
                    "SHSE.000300",   # drop — index (000xxx reserved for indices)
                    "SHSE.600000",   # pass — Shanghai main
                ],
                "sec_name": ["贵州茅台", "ETF1", "ETF2", "沪深300", "浦发银行"],
            })

        monkeypatch.setattr("gm.api.get_symbols", fake_get_symbols, raising=False)
        stocks = fetcher.get_all_stocks("csi")
        codes = [s["code"] for s in stocks]
        assert "600519" in codes
        assert "600000" in codes
        assert "510500" not in codes
        assert "510880" not in codes
        assert "000300" not in codes

    def test_get_all_stocks_non_csi_returns_empty(self, fetcher):
        assert fetcher.get_all_stocks("hk") == []
        assert fetcher.get_all_stocks("us") == []

    def test_intraday_data_without_token_returns_none(self, fetcher_no_token):
        assert fetcher_no_token.get_intraday_data("600519", period="5") is None

    def test_intraday_data_unsupported_1min_raises(self, fetcher):
        from stock_data.data_provider.base import DataFetchError
        with pytest.raises(DataFetchError, match="intraday does not support period"):
            fetcher.get_intraday_data("600519", period="1")

    def test_intraday_data_uses_myquant(self, fetcher, monkeypatch):
        """Stock intraday minute line routes through myquant when token is set."""
        pytest.importorskip("gm")
        import pandas as pd

        def fake_history(*_args, **_kwargs):
            return pd.DataFrame({
                "symbol": ["SHSE.600519"] * 3,
                "frequency": ["300s"] * 3,
                "open": [1700.0, 1705.0, 1710.0],
                "close": [1705.0, 1710.0, 1715.0],
                "high": [1708.0, 1712.0, 1717.0],
                "low": [1698.0, 1702.0, 1708.0],
                "amount": [1e8, 1.1e8, 1.2e8],
                "volume": [1e5, 1.1e5, 1.2e5],
                "bob": pd.to_datetime([
                    "2024-01-15 09:35:00",
                    "2024-01-15 09:40:00",
                    "2024-01-15 09:45:00",
                ]),
                "eob": pd.to_datetime([
                    "2024-01-15 09:40:00",
                    "2024-01-15 09:45:00",
                    "2024-01-15 09:50:00",
                ]),
            })

        monkeypatch.setattr("gm.api.history", fake_history, raising=False)
        df = fetcher.get_intraday_data("600519", period="5")
        assert df is not None
        # time column derived from 'bob', formatted as HH:MM:SS
        assert "time" in df.columns
        assert list(df["time"]) == ["09:35:00", "09:40:00", "09:45:00"]
        for col in ("open", "high", "low", "close", "volume", "amount"):
            assert col in df.columns
        # No 'code' / 'symbol' / 'frequency' / 'eob' noise in the response
        assert "symbol" not in df.columns
        assert "frequency" not in df.columns
        assert "eob" not in df.columns
        assert "bob" not in df.columns

    def test_intraday_data_swallow_errors_returns_none(self, fetcher, monkeypatch):
        """gm.api exceptions are logged with exc_info and return None (akshare pattern)."""
        pytest.importorskip("gm")
        import gm.api  # noqa: F401  -- ensure module exists

        def boom(*_args, **_kwargs):
            raise RuntimeError("upstream is down")

        monkeypatch.setattr("gm.api.history", boom, raising=False)
        assert fetcher.get_intraday_data("600519", period="5") is None

    def test_index_historical_without_token_returns_none(self, fetcher_no_token):
        assert fetcher_no_token.get_index_historical(
            "000300", "2024-01-01", "2024-01-31", "d"
        ) is None

    def test_index_historical_uses_myquant(self, fetcher, monkeypatch):
        pytest.importorskip("gm")
        import pandas as pd

        def fake_history(*_args, **_kwargs):
            return pd.DataFrame({
                "symbol": ["SHSE.000300"] * 2,
                "frequency": ["1d"] * 2,
                "open": [3500.0, 3510.0],
                "close": [3510.0, 3520.0],
                "high": [3520.0, 3530.0],
                "low": [3490.0, 3500.0],
                "amount": [1e11, 1.1e11],
                "volume": [1e8, 1.1e8],
                "bob": pd.to_datetime(["2024-01-01", "2024-01-02"]),
                "eob": pd.to_datetime(["2024-01-01 15:00", "2024-01-02 15:00"]),
            })

        monkeypatch.setattr("gm.api.history", fake_history, raising=False)
        df = fetcher.get_index_historical("000300", "2024-01-01", "2024-01-31", "d")
        assert df is not None
        assert "date" in df.columns
        assert "pct_chg" in df.columns

    def test_index_historical_minute_raises(self, fetcher):
        from stock_data.data_provider.base import DataFetchError
        with pytest.raises(DataFetchError, match="index does not support frequency"):
            fetcher.get_index_historical("000300", "2024-01-01", "2024-01-31", "5")

    def test_index_intraday_unsupported_1min_raises(self, fetcher):
        from stock_data.data_provider.base import DataFetchError
        with pytest.raises(DataFetchError, match="index intraday does not support"):
            fetcher.get_index_intraday("000300", period="1")

    def test_index_intraday_non_csi_raises(self, fetcher):
        from stock_data.data_provider.base import DataFetchError
        with pytest.raises(DataFetchError, match="Myquant does not support"):
            fetcher.get_index_intraday("HSI", period="5")
