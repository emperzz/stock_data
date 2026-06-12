"""Unit tests for _resolve_fetchers in explorer/manifest.py."""
from unittest.mock import MagicMock

from stock_data.api.endpoint_meta import EndpointMeta
from stock_data.data_provider.base import BaseFetcher, DataCapability
from stock_data.explorer.manifest import _resolve_fetchers


class _FakeFetcher(BaseFetcher):
    """Minimal concrete BaseFetcher subclass for tests."""

    def __init__(self, name: str, priority: int, markets: set[str], caps: DataCapability,
                 extra_methods: tuple[str, ...] = ()):
        self.name = name
        self.priority = priority
        self.supported_markets = markets
        self.supported_data_types = caps
        # Bind named methods on this instance so `getattr(f, m)` finds them
        for m in extra_methods:
            setattr(self, m, lambda *a, **k: None)

    def _fetch_raw_data(self, *a, **k):
        return None

    def _normalize_data(self, *a, **k):
        return None


def _mock_manager(fetchers):
    """Build a mock manager whose _filter_by_capability returns the right subset."""
    m = MagicMock()
    def _filter(market, cap):
        return sorted(
            [f for f in fetchers if market in f.supported_markets and cap in f.supported_data_types],
            key=lambda f: f.priority,
        )
    m._filter_by_capability.side_effect = _filter
    return m


def test_empty_capabilities_returns_empty_list():
    manager = _mock_manager([])
    meta = EndpointMeta(summary="x", markets=["csi"], capabilities=[])
    assert _resolve_fetchers(meta, manager) == []


def test_single_capability_returns_sorted_fetchers():
    fa = _FakeFetcher("alpha", priority=1, markets={"csi"}, caps=DataCapability.REALTIME_QUOTE)
    fb = _FakeFetcher("beta", priority=0, markets={"csi"}, caps=DataCapability.REALTIME_QUOTE)
    manager = _mock_manager([fa, fb])
    meta = EndpointMeta(summary="x", markets=["csi"], capabilities=["REALTIME_QUOTE"])
    result = _resolve_fetchers(meta, manager)
    assert [r["name"] for r in result] == ["beta", "alpha"]  # priority 0 first
    assert all(r["method"] == "get_realtime_quote" for r in result)


def test_multi_capability_same_method_merges_to_one_row():
    """Approach A: baostock supports DWM+MIN, both map to get_kline_data; result is ONE row."""
    f = _FakeFetcher(
        "baostock", priority=1, markets={"csi"},
        caps=DataCapability.HISTORICAL_DWM | DataCapability.HISTORICAL_MIN,
    )
    manager = _mock_manager([f])
    meta = EndpointMeta(
        summary="K线", markets=["csi"],
        capabilities=["HISTORICAL_DWM", "HISTORICAL_MIN"],
    )
    result = _resolve_fetchers(meta, manager)
    assert len(result) == 1
    assert result[0]["name"] == "baostock"
    assert result[0]["method"] == "get_kline_data"
    assert set(result[0]["capabilities"]) == {"HISTORICAL_DWM", "HISTORICAL_MIN"}


def test_fetcher_method_override_wins_over_capability_default():
    f = _FakeFetcher(
        "eastmoney", priority=0, markets={"csi"},
        caps=DataCapability.DRAGON_TIGER,
        extra_methods=("get_daily_dragon_tiger",),
    )
    manager = _mock_manager([f])
    meta = EndpointMeta(
        summary="龙虎榜每日", markets=["csi"],
        capabilities=["DRAGON_TIGER"],
        fetcher_method="get_daily_dragon_tiger",
    )
    result = _resolve_fetchers(meta, manager)
    assert len(result) == 1
    assert result[0]["method"] == "get_daily_dragon_tiger"  # override, not default


def test_unknown_capability_string_is_skipped():
    """Capability name that doesn't match any DataCapability enum member is silently ignored."""
    manager = _mock_manager([])
    meta = EndpointMeta(summary="x", markets=["csi"], capabilities=["NONEXISTENT_CAP"])
    assert _resolve_fetchers(meta, manager) == []


def test_signature_field_is_populated():
    """The returned entries include a signature field reflecting the method."""
    f = _FakeFetcher("alpha", priority=0, markets={"csi"}, caps=DataCapability.REALTIME_QUOTE)
    manager = _mock_manager([f])
    meta = EndpointMeta(summary="x", markets=["csi"], capabilities=["REALTIME_QUOTE"])
    result = _resolve_fetchers(meta, manager)
    sig = result[0]["signature"]
    assert isinstance(sig, list)
    # BaseFetcher.get_realtime_quote(self, stock_code) → 1 param after self
    assert any(p["name"] == "stock_code" for p in sig)
