"""
Tests for TushareFetcher index K-line dispatch (regression for INDEX_KLINE bug).

Background
----------
``TushareFetcher`` declares ``DataCapability.INDEX_KLINE`` so the manager
routes ``/indices/{code}/kline`` to it (P0 highest priority). However, the
inherited ``BaseFetcher.get_kline_data`` → ``_fetch_raw_data`` always calls
``api.query("daily", ...)`` (line 124 of tushare_fetcher.py), which is
Tushare's **stock** API. For index codes (``000001.SH``, ``000300.SH``,
``399006.SZ``), ``daily`` returns empty data because it expects stock
``ts_code`` like ``000001.SZ`` — not index codes. The exception raised is
``DataFetchError("Tushare returned no data for 000001")``.

This is the exact same shape as the MyquantFetcher bug fixed in commit
e420527: a fetcher declares INDEX_KLINE but its ``get_kline_data`` is a
silent dead participant on the index failover chain.

Fix: override ``get_kline_data`` to dispatch on ``index_market_tag`` and
call Tushare's ``index_daily`` / ``index_weekly`` / ``index_monthly`` API
directly (mirrors ZhituFetcher / MyquantFetcher pattern).
"""

import inspect
from unittest.mock import MagicMock

import pandas as pd
import pytest

from stock_data.data_provider.base import DataCapability, DataFetchError
from stock_data.data_provider.fetchers.tushare_fetcher import TushareFetcher

# ────────────────────────────────────────────────────────────────────────────
# Helpers — class-level init state isolation (mirrors test_myquant_fetcher.py)
# ────────────────────────────────────────────────────────────────────────────


class _TushareInitState:
    """Snapshot/restore for ``TushareFetcher`` class-level init state.

    Tushare uses the same ``SDKFetcherMixin`` init-cache pattern as Myquant:
    once ``is_available()`` returns True, the result is sticky at the class
    level. Tests force-True by patching ``_init_ok`` directly. Snapshot
    before, restore after, so we don't leak into the next test.

    Note: ``__exit__`` restores the saved ``_api`` (likely ``None`` in this
    test environment). All assertions on the mocked API must happen INSIDE
    the ``with`` block, before restoration.
    """

    def __init__(self):
        self._saved_attempted = TushareFetcher._init_attempted
        self._saved_ok = TushareFetcher._init_ok
        self._saved_token = TushareFetcher._cls_token
        self._saved_api = TushareFetcher._api

    def __enter__(self):
        TushareFetcher._init_attempted = True
        TushareFetcher._init_ok = True
        TushareFetcher._cls_token = "test_token"
        TushareFetcher._api = MagicMock(name="tushare._api")
        return TushareFetcher()

    def __exit__(self, *exc):
        TushareFetcher._init_attempted = self._saved_attempted
        TushareFetcher._init_ok = self._saved_ok
        TushareFetcher._cls_token = self._saved_token
        TushareFetcher._api = self._saved_api


def _fake_index_daily_payload() -> pd.DataFrame:
    """Mimic Tushare's ``index_daily`` response for 000001.SH.

    Columns per Tushare docs: ts_code, trade_date, open, high, low,
    close, pre_close, change, pct_chg, vol, amount.
    """
    return pd.DataFrame(
        {
            "ts_code": ["000001.SH"] * 3,
            "trade_date": ["20250701", "20250702", "20250703"],
            "open": [3445.85, 3461.15, 3459.59],
            "high": [3459.59, 3461.50, 3460.98],
            "low": [3441.04, 3457.00, 3457.00],
            "close": [3457.75, 3461.34, 3459.34],
            "pre_close": [3444.43, 3457.75, 3461.34],
            "change": [13.32, 3.59, -2.00],
            "pct_chg": [0.387, 0.104, -0.058],
            "vol": [4.444e8, 4.500e8, 4.999e7],
            "amount": [5.535e11, 5.012e11, 5.359e10],
        }
    )


def _fake_stock_daily_payload() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "ts_code": ["600519.SH"] * 2,
            "trade_date": ["20250701", "20250702"],
            "open": [1700.0, 1710.0],
            "high": [1715.0, 1720.0],
            "low": [1695.0, 1705.0],
            "close": [1710.0, 1715.0],
            "pre_close": [1695.0, 1710.0],
            "change": [15.0, 5.0],
            "pct_chg": [0.88, 0.29],
            "vol": [3.0e7, 2.5e7],  # 手
            "amount": [5.0e10, 4.2e10],  # 千 yuan
        }
    )


# ────────────────────────────────────────────────────────────────────────────
# Capability / supports_kline declarations
# ────────────────────────────────────────────────────────────────────────────


class TestTushareIndexCapabilities:
    def test_declares_index_kline_capability(self):
        assert DataCapability.INDEX_KLINE in TushareFetcher.supported_data_types

    def test_market_is_csi_only(self):
        assert TushareFetcher.supported_markets == {"csi"}

    def test_get_kline_data_signature_matches_base(self):
        """The override must keep the same public signature as BaseFetcher.

        Guards against an accidental signature drift (e.g. dropping the
        ``adjust`` parameter) that would silently break callers using
        keyword arguments via the explorer's fetcher-test endpoint.
        """
        sig = inspect.signature(TushareFetcher.get_kline_data)
        params = list(sig.parameters)
        assert params == [
            "self",
            "stock_code",
            "start_date",
            "end_date",
            "days",
            "frequency",
            "adjust",
        ]


# ────────────────────────────────────────────────────────────────────────────
# get_kline_data — index branch
# ────────────────────────────────────────────────────────────────────────────


class TestGetKlineDataIndexDispatch:
    """Regression tests for the index branch of TushareFetcher.get_kline_data."""

    def test_index_000xxx_calls_index_daily_with_sh_suffix(self):
        """Shanghai index 000001 must use ``index_daily`` API + ``000001.SH``.

        Before the fix: ``api.query('daily', ts_code='000001.SH', ...)``
        returned empty (Tushare's ``daily`` API is stock-only), producing
        ``DataFetchError("Tushare returned no data for 000001")``. After the
        fix: ``api.query('index_daily', ts_code='000001.SH', ...)`` should
        be called instead.
        """
        with _TushareInitState() as fetcher:
            fetcher._api.query.return_value = _fake_index_daily_payload()
            df = fetcher.get_kline_data("000001", days=4, frequency="d")

            # Inspect INSIDE the with block (before __exit__ restores _api)
            args, kwargs = fetcher._api.query.call_args
            api_name = args[0]
            assert api_name == "index_daily", (
                f"expected index_daily for index code, got {api_name!r}"
            )
            assert kwargs["ts_code"] == "000001.SH"

        # DataFrame should be normalized to standard columns
        assert df is not None and not df.empty
        for col in ("date", "open", "high", "low", "close", "volume", "amount"):
            assert col in df.columns, f"missing column {col}"
        # pct_chg is provided by upstream; should pass through (the stock
        # branch also passes it through when present).
        assert "pct_chg" in df.columns

    def test_index_399xxx_calls_index_daily_with_sz_suffix(self):
        """Shenzhen index 399006 must produce ``399006.SZ`` and use ``index_daily``."""
        with _TushareInitState() as fetcher:
            fetcher._api.query.return_value = _fake_index_daily_payload()
            fetcher.get_kline_data("399006", days=4, frequency="d")

            args, kwargs = fetcher._api.query.call_args
            api_name = args[0]
            assert api_name == "index_daily"
            assert kwargs["ts_code"] == "399006.SZ"

    def test_index_weekly_calls_index_weekly(self):
        """``frequency='w'`` must dispatch to ``index_weekly``."""
        with _TushareInitState() as fetcher:
            fetcher._api.query.return_value = _fake_index_daily_payload()
            fetcher.get_kline_data("000300", days=10, frequency="w")

            args, kwargs = fetcher._api.query.call_args
            api_name = args[0]
            assert api_name == "index_weekly"
            assert kwargs["ts_code"] == "000300.SH"

    def test_index_monthly_calls_index_monthly(self):
        """``frequency='m'`` must dispatch to ``index_monthly``."""
        with _TushareInitState() as fetcher:
            fetcher._api.query.return_value = _fake_index_daily_payload()
            fetcher.get_kline_data("000300", days=30, frequency="m")

            args, kwargs = fetcher._api.query.call_args
            api_name = args[0]
            assert api_name == "index_monthly"
            assert kwargs["ts_code"] == "000300.SH"

    def test_index_non_csi_raises(self):
        """Non-CSI indices (HK / US) are unsupported by Tushare.

        ``to_tushare_format`` raises ``ValueError`` for non-CSI indices
        (mirrors MyquantFetcher's behaviour); the override must convert
        this into a ``DataFetchError`` so the manager's failover chain
        transparently moves on to the next fetcher.
        """
        with _TushareInitState() as fetcher:
            with pytest.raises(DataFetchError):
                fetcher.get_kline_data("HSI", days=4, frequency="d")
            # Tushare's API must NOT be called for unsupported index codes
            fetcher._api.query.assert_not_called()

    def test_empty_upstream_response_raises_data_fetch_error(self):
        """Upstream returning empty DataFrame must raise DataFetchError.

        This is the original symptom that surfaced the bug: the index
        branch was never reached, so the empty-response guard in
        ``_fetch_raw_data`` never got a chance to raise.
        """
        with _TushareInitState() as fetcher:
            fetcher._api.query.return_value = pd.DataFrame()  # empty
            with pytest.raises(DataFetchError, match="no data"):
                fetcher.get_kline_data("000001", days=4, frequency="d")


# ────────────────────────────────────────────────────────────────────────────
# get_kline_data — stock branch (regression guard)
# ────────────────────────────────────────────────────────────────────────────


class TestGetKlineDataStockUnchanged:
    """Stock codes must continue to flow through the stock API path.

    Guards against accidentally breaking the stock branch while fixing the
    index one. The stock branch must call ``daily`` (NOT ``index_daily``)
    with the right ``ts_code``. We use unambiguous stock codes that are
    NOT in CSI_INDEX_MAP (600519 / 000002) so the stock branch is
    guaranteed to fire.
    """

    def test_stock_code_600519_calls_daily_not_index_daily(self):
        """The stock branch must continue to use the ``daily`` API."""
        with _TushareInitState() as fetcher:
            fetcher._api.query.return_value = _fake_stock_daily_payload()
            df = fetcher.get_kline_data("600519", days=2, frequency="d")

            args, kwargs = fetcher._api.query.call_args
            api_name = args[0]
            assert api_name == "daily", f"stock branch must use 'daily' API; got {api_name!r}"
            assert kwargs["ts_code"] == "600519.SH"

        assert df is not None and not df.empty

    def test_stock_000002_calls_daily_with_sz_suffix(self):
        """Stock 000002 (Vanke A, SZ) is NOT in CSI_INDEX_MAP.

        000001 IS in CSI_INDEX_MAP (SSE Composite Index) so dispatching on
        ``index_market_tag`` routes it to the index branch. But 000002 is
        NOT in CSI_INDEX_MAP, so it must hit the stock branch — proving
        the dispatch correctly distinguishes ambiguous 000xxx codes by
        checking the index map.
        """
        with _TushareInitState() as fetcher:
            fetcher._api.query.return_value = _fake_stock_daily_payload()
            fetcher.get_kline_data("000002", days=2, frequency="d")

            args, kwargs = fetcher._api.query.call_args
            api_name = args[0]
            assert api_name == "daily"
            assert kwargs["ts_code"] == "000002.SZ"

    def test_stock_qfq_adjust_uses_pro_bar(self, monkeypatch):
        """Stock d/qfq must still use ``pro_bar`` (not ``api.query('daily', ...)``).

        Pins down the existing stock-adjust branch so the override doesn't
        accidentally bypass it. ``pro_bar`` is a module-level function on
        the ``tushare`` package (called via ``import tushare as ts; ts.pro_bar``)
        — not an attribute on the SDK client — so we monkeypatch
        ``tushare.pro_bar`` directly. This works only because
        ``test_lazy_init.py`` now restores ``sys.modules['tushare']`` on
        teardown; without that fix, the tushare module would be a
        SimpleNamespace stub for all subsequent tests in the run.
        """
        import tushare

        captured: dict = {}

        def fake_pro_bar(**kwargs):
            captured.update(kwargs)
            return _fake_stock_daily_payload()

        monkeypatch.setattr(tushare, "pro_bar", fake_pro_bar)

        with _TushareInitState() as fetcher:
            fetcher.get_kline_data("600519", days=2, frequency="d", adjust="qfq")
            # Stock-adjust branch must NOT call api.query at all
            fetcher._api.query.assert_not_called()

        # pro_bar called with adj="qfq"
        assert captured["adj"] == "qfq"
        assert captured["ts_code"] == "600519.SH"


# ────────────────────────────────────────────────────────────────────────────
# get_index_historical — verify it works transitively through the override
# ────────────────────────────────────────────────────────────────────────────


class TestGetIndexHistoricalUsesIndexDaily:
    """``get_index_historical`` already exists and delegates to ``get_kline_data``.

    After the fix, the delegation chain
        get_index_historical → get_kline_data → index_daily API
    should Just Work. This test pins that contract.
    """

    def test_get_index_historical_calls_index_daily(self):
        with _TushareInitState() as fetcher:
            fetcher._api.query.return_value = _fake_index_daily_payload()
            df = fetcher.get_index_historical(
                "000001",
                "2025-07-01",
                "2025-07-04",
                "d",
            )

            assert df is not None and not df.empty
            args, kwargs = fetcher._api.query.call_args
            api_name = args[0]
            assert api_name == "index_daily"
            assert kwargs["ts_code"] == "000001.SH"

    def test_get_index_historical_non_csi_returns_none(self):
        """Non-CSI index codes return None (not raise) so manager failover skips Tushare."""
        with _TushareInitState() as fetcher:
            result = fetcher.get_index_historical("HSI", None, None, "d")
            # Inspect INSIDE the with block (before __exit__ restores _api).
            fetcher._api.query.assert_not_called()
        assert result is None
