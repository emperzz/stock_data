"""Unit tests for _resolve_fetchers in explorer/manifest.py."""
from unittest.mock import MagicMock, patch

from stock_data.api.endpoint_meta import EndpointMeta
from stock_data.data_provider.base import BaseFetcher, DataCapability
from stock_data.explorer import manifest as _manifest_mod
from stock_data.explorer.manifest import _resolve_fetchers


class _FakeFetcher(BaseFetcher):
    """Minimal concrete BaseFetcher subclass for tests.

    Default arg values let ``_resolve_fetchers`` instantiate via
    ``fetcher_cls()`` (no args) when the manager has no registered
    instance for that fetcher name.

    Note: `_resolve_fetchers` iterates over *classes* (not instances) and
    dedupes by ``(fetcher_name, method_name)``. So tests that need distinct
    entries must declare distinct subclasses — see _FakeFetcherA /
    _FakeFetcherB below.
    """

    def __init__(self, name: str = "_FakeFetcher", priority: int = 99,
                 markets: set[str] | None = None,
                 caps: DataCapability = DataCapability(0),
                 extra_methods: tuple[str, ...] = ()):
        self.name = name
        self.priority = priority
        self.supported_markets = markets or set()
        self.supported_data_types = caps
        # Bind named methods on this instance so `getattr(f, m)` finds them
        for m in extra_methods:
            setattr(self, m, lambda *a, **k: None)

    def _fetch_raw_data(self, *a, **k):
        return None

    def _normalize_data(self, *a, **k):
        return None


class _FakeFetcherA(_FakeFetcher):
    name = "alpha"
    # Must be declared at CLASS level (not just in __init__) — the manifest's
    # _classes_declaring_capability walks BaseFetcher.__subclasses__() and
    # reads `cls.supported_data_types`, the same convention real fetchers
    # follow (Tushare/Zhitu/Myquant all declare it on the class).
    supported_data_types = DataCapability.STOCK_REALTIME_QUOTE

    def __init__(self):
        super().__init__(name="alpha", priority=99, markets={"csi"},
                         caps=DataCapability.STOCK_REALTIME_QUOTE)


class _FakeFetcherB(_FakeFetcher):
    name = "beta"
    supported_data_types = DataCapability.STOCK_REALTIME_QUOTE

    def __init__(self):
        super().__init__(name="beta", priority=99, markets={"csi"},
                         caps=DataCapability.STOCK_REALTIME_QUOTE)


def _mock_manager(fetchers):
    """Build a mock manager. `_filter_by_capability` is no longer consulted
    by _resolve_fetchers (it walks BaseFetcher.__subclasses__() directly);
    the mock exists only so the function's `manager._fetchers` access works.
    """
    m = MagicMock()
    m._fetchers = list(fetchers)
    return m


def _with_only_fake_classes(mock_caps_only, fake_classes):
    """Patch `_classes_declaring_capability` so the unit test sees ONLY the
    fake classes, not the real fetchers. Tests assert on the fakes' behavior
    without coupling to whatever concrete fetchers happen to be importable
    in the test environment.

    Patches via the imported module reference (`_manifest_mod`) so we hit
    the same module object that `_resolve_fetchers` looks up at call time —
    patching by string can miss when pytest's import machinery caches a
    different module object than `from X import Y` resolved at import.
    """
    return patch.object(
        _manifest_mod, "_classes_declaring_capability",
        side_effect=lambda cap: [c for c in fake_classes
                                 if cap in (getattr(c, "supported_data_types", DataCapability(0))
                                            or DataCapability(0))],
    )


def test_empty_capabilities_returns_empty_list():
    manager = _mock_manager([])
    meta = EndpointMeta(summary="x", markets=["csi"], capabilities=[])
    with _with_only_fake_classes(None, []):
        assert _resolve_fetchers(meta, manager) == []


def test_single_capability_returns_sorted_fetchers():
    a = _FakeFetcherA()
    b = _FakeFetcherB()
    # Override priorities to test sort order
    a.priority = 1
    b.priority = 0
    manager = _mock_manager([a, b])
    meta = EndpointMeta(summary="x", markets=["csi"], capabilities=["STOCK_REALTIME_QUOTE"])
    with _with_only_fake_classes(None, [type(a), type(b)]):
        result = _resolve_fetchers(meta, manager)
    assert [r["name"] for r in result] == ["beta", "alpha"]  # priority 0 first
    assert all(r["method"] == "get_realtime_quote" for r in result)


def test_multi_capability_same_method_merges_to_one_row():
    """Approach A: baostock supports DWM+MIN (rev 3 → STOCK_KLINE). Result is ONE row."""

    class _Baostock(_FakeFetcher):
        name = "baostock"
        supported_data_types = DataCapability.STOCK_KLINE
        def __init__(self):
            super().__init__(
                name="baostock", priority=1, markets={"csi"},
                caps=DataCapability.STOCK_KLINE,
            )

    f = _Baostock()
    manager = _mock_manager([f])
    meta = EndpointMeta(
        summary="K线", markets=["csi"],
        capabilities=["STOCK_KLINE"],
    )
    with _with_only_fake_classes(None, [type(f)]):
        result = _resolve_fetchers(meta, manager)
    assert len(result) == 1
    assert result[0]["name"] == "baostock"
    assert result[0]["method"] == "get_kline_data"
    assert set(result[0]["capabilities"]) == {"STOCK_KLINE"}


def test_fetcher_method_override_wins_over_capability_default():

    class _Eastmoney(_FakeFetcher):
        name = "eastmoney"
        supported_data_types = DataCapability.DRAGON_TIGER
        def __init__(self):
            super().__init__(
                name="eastmoney", priority=0, markets={"csi"},
                caps=DataCapability.DRAGON_TIGER,
                extra_methods=("get_daily_dragon_tiger",),
            )

    f = _Eastmoney()
    manager = _mock_manager([f])
    meta = EndpointMeta(
        summary="龙虎榜每日", markets=["csi"],
        capabilities=["DRAGON_TIGER"],
        fetcher_method="get_daily_dragon_tiger",
    )
    with _with_only_fake_classes(None, [type(f)]):
        result = _resolve_fetchers(meta, manager)
    assert len(result) == 1
    assert result[0]["method"] == "get_daily_dragon_tiger"  # override, not default


def test_unknown_capability_string_is_skipped():
    """Capability name that doesn't match any DataCapability enum member is silently ignored."""
    manager = _mock_manager([])
    meta = EndpointMeta(summary="x", markets=["csi"], capabilities=["NONEXISTENT_CAP"])
    with _with_only_fake_classes(None, []):
        assert _resolve_fetchers(meta, manager) == []


def test_signature_field_is_populated():
    """The returned entries include a signature field reflecting the method."""

    class _Alpha(_FakeFetcher):
        name = "alpha"
        supported_data_types = DataCapability.STOCK_REALTIME_QUOTE
        def __init__(self):
            super().__init__(name="alpha", priority=0, markets={"csi"},
                             caps=DataCapability.STOCK_REALTIME_QUOTE)

    f = _Alpha()
    manager = _mock_manager([f])
    meta = EndpointMeta(summary="x", markets=["csi"], capabilities=["STOCK_REALTIME_QUOTE"])
    with _with_only_fake_classes(None, [type(f)]):
        result = _resolve_fetchers(meta, manager)
    sig = result[0]["signature"]
    assert isinstance(sig, list)
    # BaseFetcher.get_realtime_quote(self, stock_code) → 1 param after self
    assert any(p["name"] == "stock_code" for p in sig)
