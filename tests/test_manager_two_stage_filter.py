"""Two-stage manager filter per spec §4.4: capability bit → supports_kline."""
import pandas as pd
import pytest

from stock_data.data_provider.base import BaseFetcher, DataCapability, DataFetchError


class _FakeFetcher(BaseFetcher):
    """Configurable fake fetcher for two-stage filter tests."""

    def is_available(self) -> bool:
        return True

    def __init__(self, name, priority, supported_markets,
                 supported_data_types, supports_kline_result=True,
                 supports_quote_result=True):
        self.name = name
        self.priority = priority
        self.supported_markets = supported_markets
        self.supported_data_types = supported_data_types
        self._supports_kline_result = supports_kline_result
        self._supports_quote_result = supports_quote_result

    def supports_kline(self, period, adjust, market, asset):
        return self._supports_kline_result

    def supports_quote(self, market):
        return self._supports_quote_result

    # ABC stubs — not exercised in this test file
    def _fetch_raw_data(self, stock_code, start_date, end_date,
                        frequency="d", adjust=None):
        return pd.DataFrame()

    def _normalize_data(self, df, stock_code):
        return df

    def get_kline_data(self, stock_code, start_date, end_date, days, frequency, adjust):
        return pd.DataFrame({"date": ["2026-06-29"], "close": [1.0]}), "fake"


def test_manager_filters_by_supports_kline_when_empty_raises():
    """All candidates declare capability but supports_kline returns False → DataFetchError."""
    from stock_data.data_provider.manager import DataFetcherManager

    mg = DataFetcherManager()
    f1 = _FakeFetcher("A", 1, {"csi"},
                       DataCapability.STOCK_KLINE,
                       supports_kline_result=False)
    f2 = _FakeFetcher("B", 2, {"csi"},
                       DataCapability.STOCK_KLINE,
                       supports_kline_result=False)
    mg.add_fetcher(f1)
    mg.add_fetcher(f2)
    with pytest.raises(DataFetchError) as exc:
        mg.get_kline_data(
            "600519", start_date=None, end_date="2026-06-29",
            days=1, frequency="1", adjust="qfq",
        )
    # Error message must include asset, period, adjust, market.
    msg = str(exc.value)
    assert "asset=stock" in msg
    assert "period=1" in msg
    assert "adjust='qfq'" in msg
    assert "market=csi" in msg


def test_manager_picks_only_supporting_fetcher():
    """When at least one supports_kline is True, manager picks the supporting one."""
    from stock_data.data_provider.manager import DataFetcherManager

    mg = DataFetcherManager()
    captured = []

    class _PickerFetcher(BaseFetcher):
        def is_available(self) -> bool:
            return True

        def __init__(self, name, priority, supports_kline):
            self.name = name
            self.priority = priority
            self.supported_markets = {"csi"}
            self.supported_data_types = DataCapability.STOCK_KLINE
            self._supports_kline = supports_kline

        def supports_kline(self, period, adjust, market, asset):
            return self._supports_kline

        def _fetch_raw_data(self, stock_code, start_date, end_date,
                            frequency="d", adjust=None):
            return pd.DataFrame()

        def _normalize_data(self, df, stock_code):
            return df

        def get_kline_data(self, stock_code, start_date, end_date, days, frequency, adjust):
            captured.append((self.name, frequency, adjust))
            return pd.DataFrame({"date": ["2026-06-29"], "close": [1.0]}), self.name

    mg.add_fetcher(_PickerFetcher("Yes", 1, supports_kline=True))
    mg.add_fetcher(_PickerFetcher("No", 0, supports_kline=False))  # higher priority but rejects

    df, source = mg.get_kline_data(
        "600519", start_date=None, end_date="2026-06-29",
        days=1, frequency="5", adjust="qfq",
    )
    # Higher-priority "No" was filtered out; "Yes" (priority 1, supports) was chosen.
    assert source == "Yes"
    assert captured == [("Yes", "5", "qfq")]


def test_manager_three_stage_drops_unsupported_markets():
    """Fetchers that don't support the requested market are filtered out (manager level)."""
    from stock_data.data_provider.manager import DataFetcherManager

    mg = DataFetcherManager()
    f1 = _FakeFetcher("HKOnly", 1, {"hk"},
                       DataCapability.STOCK_KLINE,
                       supports_kline_result=True)
    mg.add_fetcher(f1)

    with pytest.raises(DataFetchError):
        # 600519 is csi market; HKOnly is filtered out by _filter_by_capability.
        mg.get_kline_data(
            "600519", start_date=None, end_date="2026-06-29",
            days=1, frequency="d",
        )


# ---------- Quote path: two-stage filter (Task 6, spec §4.4) ----------


def test_manager_quote_two_stage_filter_picks_supporting_fetcher():
    """manager.get_realtime_quote filters by supports_quote after capability.

    When at least one fetcher survives both stages (capability + supports_quote),
    manager picks it. We do NOT require a real UnifiedRealtimeQuote because the
    failover loop only needs to return a non-None value to short-circuit
    further fetcher calls.
    """
    from stock_data.data_provider.manager import DataFetcherManager

    mg = DataFetcherManager()
    captured = []

    class _QuoteFetcher(BaseFetcher):
        def is_available(self) -> bool:
            return True

        def __init__(self, name, priority, supports_quote):
            self.name = name
            self.priority = priority
            self.supported_markets = {"csi"}
            self.supported_data_types = DataCapability.STOCK_REALTIME_QUOTE
            self._supports_quote = supports_quote

        def supports_quote(self, market):
            return self._supports_quote

        # ABC stubs
        def _fetch_raw_data(self, stock_code, start_date, end_date,
                            frequency="d", adjust=None):
            return pd.DataFrame()

        def _normalize_data(self, df, stock_code):
            return df

        def get_realtime_quote(self, stock_code):
            captured.append((self.name, stock_code))
            return f"quote-from-{self.name}"

    mg.add_fetcher(_QuoteFetcher("Q1", 1, supports_quote=True))
    mg.add_fetcher(_QuoteFetcher("Q2", 0, supports_quote=False))  # higher priority, but rejected

    result = mg.get_realtime_quote("600519")
    assert result == "quote-from-Q1"
    assert captured == [("Q1", "600519")]


def test_manager_quote_raises_when_no_supporting_fetcher():
    """When all fetchers reject via supports_quote, manager raises DataFetchError.

    The error message mirrors the k-line pattern from Task 5 — the asset
    dimension is implicit (no asset param for quote), so the message
    includes market for client diagnostics.
    """
    from stock_data.data_provider.manager import DataFetcherManager

    mg = DataFetcherManager()
    f1 = _FakeFetcher("NQ1", 1, {"csi"},
                       DataCapability.STOCK_REALTIME_QUOTE,
                       supports_kline_result=True,
                       supports_quote_result=False)
    f2 = _FakeFetcher("NQ2", 2, {"csi"},
                       DataCapability.STOCK_REALTIME_QUOTE,
                       supports_kline_result=True,
                       supports_quote_result=False)
    mg.add_fetcher(f1)
    mg.add_fetcher(f2)

    with pytest.raises(DataFetchError) as exc:
        mg.get_realtime_quote("600519")
    msg = str(exc.value)
    assert "No fetcher supports quote" in msg
    assert "market=csi" in msg
