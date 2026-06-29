"""Default BaseFetcher.supports_kline / supports_quote per spec §4.2 / §4.2.1."""
from stock_data.data_provider.base import BaseFetcher, DataCapability


class _StockOnlyFetcher(BaseFetcher):
    """Concrete subclass with only STOCK_KLINE + STOCK_REALTIME_QUOTE."""
    name = "FakeStock"
    priority = 99
    supported_markets = {"csi"}
    supported_data_types = (
        DataCapability.STOCK_KLINE | DataCapability.STOCK_REALTIME_QUOTE
    )

    def is_available(self) -> bool: return True

    def _fetch_raw_data(self, *args, **kwargs):  # pragma: no cover - not exercised here
        return None

    def _normalize_data(self, df, code):  # pragma: no cover
        return df


class _IndexOnlyFetcher(BaseFetcher):
    """Concrete subclass with only INDEX_KLINE + INDEX_REALTIME_QUOTE."""
    name = "FakeIndex"
    priority = 99
    supported_markets = {"us"}
    supported_data_types = (
        DataCapability.INDEX_KLINE | DataCapability.INDEX_REALTIME_QUOTE
    )

    def is_available(self) -> bool: return True

    def _fetch_raw_data(self, *args, **kwargs):  # pragma: no cover - not exercised here
        return None

    def _normalize_data(self, df, code):  # pragma: no cover
        return df


def test_default_supports_kline_all_periods_when_cap_declared():
    """A fetcher declaring STOCK_KLINE returns True for any period on supported market."""
    f = _StockOnlyFetcher()
    for period in ("d", "w", "m", "1", "5", "15", "30", "60"):
        assert f.supports_kline(period, "", "csi", "stock") is True
    # unsupported market
    assert f.supports_kline("d", "", "hk", "stock") is False
    # asset="index" not declared
    assert f.supports_kline("d", "", "csi", "index") is False


def test_default_supports_kline_rejects_bad_period():
    """A non-canonical period value (not in the 8 known) returns False."""
    f = _StockOnlyFetcher()
    assert f.supports_kline("2h", "", "csi", "stock") is False
    assert f.supports_kline("", "", "csi", "stock") is False


def test_default_supports_kline_index_asset():
    """A fetcher declaring INDEX_KLINE returns True for asset='index'."""
    f = _IndexOnlyFetcher()
    assert f.supports_kline("d", "", "us", "index") is True
    assert f.supports_kline("5", "", "us", "index") is True
    # asset="stock" not declared on this fetcher
    assert f.supports_kline("d", "", "us", "stock") is False


def test_default_supports_quote_market_only():
    f = _StockOnlyFetcher()
    assert f.supports_quote("csi") is True
    assert f.supports_quote("hk") is False

    idx = _IndexOnlyFetcher()
    assert idx.supports_quote("us") is True
    assert idx.supports_quote("csi") is False


def test_default_supports_quote_unsupported_market():
    """Fetcher with supported_markets={"csi"} returns False for hk/us."""
    f = _StockOnlyFetcher()
    assert f.supports_quote("hk") is False
    assert f.supports_quote("us") is False
