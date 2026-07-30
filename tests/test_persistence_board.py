"""Unit + integration tests for stock_data.data_provider.persistence.board.

Added 2026-07-30: _project_unified_quote_to_dict helper unit tests
(spec 2026-07-30, plan task 1).
"""
import pytest
from zoneinfo import ZoneInfo

from stock_data.data_provider.core.types import (
    RealtimeSource,
    UnifiedRealtimeQuote,
)


def _q(**overrides) -> UnifiedRealtimeQuote:
    """Build a UnifiedRealtimeQuote with sensible defaults."""
    defaults = dict(
        code="600519",
        name="贵州茅台",
        source=RealtimeSource.ZZSHARE,
        price=1700.0,
        change_pct=1.5,
        change_amount=25.0,
        volume=1000000,
        amount=1.7e9,
        volume_ratio=1.2,
        turnover_rate=0.5,
        amplitude=2.0,
        open_price=1680.0,
        high=1710.0,
        low=1675.0,
        pre_close=1675.0,
        pe_ratio=30.0,
    )
    defaults.update(overrides)
    return UnifiedRealtimeQuote(**defaults)


class TestProjectUnifiedQuoteToDict:
    """Tests for the suffix-quote projection helper (spec 2026-07-30)."""

    def test_returns_upstream_style_keys(self):
        """Result uses fetcher-style keys (stock_code/stock_name/turnover_rate/
        amplitude), NOT BoardStockInfo model field names (code/name/
        turnover_pct/amplitude_pct). This is the contract that keeps
        update_cached_board_stocks happy."""
        from stock_data.data_provider.persistence import board as pb

        q = _q()
        d = pb._project_unified_quote_to_dict("600519", "贵州茅台", q)
        # stock_code/stock_name (NOT code/name)
        assert d["stock_code"] == "600519"
        assert d["stock_name"] == "贵州茅台"
        assert "code" not in d
        assert "name" not in d
        # turnover_rate (NOT turnover_pct)
        assert d["turnover_rate"] == 0.5
        assert "turnover_pct" not in d
        # amplitude (NOT amplitude_pct)
        assert d["amplitude"] == 2.0
        assert "amplitude_pct" not in d
        # 4 new fields use their own names
        assert d["open"] == 1680.0
        assert d["high"] == 1710.0
        assert d["low"] == 1675.0
        assert d["prev_close"] == 1675.0
        # 7 other quote fields
        assert d["price"] == 1700.0
        assert d["change_pct"] == 1.5
        assert d["change_amount"] == 25.0
        assert d["volume"] == 1000000
        assert d["amount"] == 1.7e9
        assert d["volume_ratio"] == 1.2
        assert d["pe_ratio"] == 30.0

    def test_amplitude_fallback_when_unified_amplitude_is_none(self):
        """q.amplitude=None, high/low/pre_close set → fallback computes amplitude."""
        from stock_data.data_provider.persistence import board as pb

        q = _q(amplitude=None)
        d = pb._project_unified_quote_to_dict("600519", "贵州茅台", q)
        # (1710 - 1675) / 1675 * 100 ≈ 2.0896
        assert d["amplitude"] == pytest.approx(2.0896, rel=1e-3)

    def test_amplitude_none_when_no_fallback_inputs(self):
        """q.amplitude=None and high/low/pre_close missing → dict["amplitude"]=None."""
        from stock_data.data_provider.persistence import board as pb

        q = _q(amplitude=None, high=None, low=None, pre_close=None)
        d = pb._project_unified_quote_to_dict("600519", "贵州茅台", q)
        assert d["amplitude"] is None

    def test_amplitude_passthrough_when_unified_amplitude_set(self):
        """q.amplitude already set → use it directly, do not recompute."""
        from stock_data.data_provider.persistence import board as pb

        q = _q(amplitude=3.5)
        d = pb._project_unified_quote_to_dict("600519", "贵州茅台", q)
        assert d["amplitude"] == 3.5

    def test_ths_only_fields_not_in_dict(self):
        """change_speed / free_float_shares / float_market_cap must NOT appear
        in the dict (they're absent, not None). The route layer's
        _build_board_stock_info reads s.get('change_speed') → default None."""
        from stock_data.data_provider.persistence import board as pb

        q = _q()
        d = pb._project_unified_quote_to_dict("600519", "贵州茅台", q)
        for k in (
            "change_speed", "free_float_shares", "float_market_cap",
            "is_limit_up", "lb_count",
        ):
            assert k not in d

    def test_name_fallback_to_quote_name_when_param_empty(self):
        """name param empty → fallback to q.name."""
        from stock_data.data_provider.persistence import board as pb

        q = _q(name="茅台")
        d = pb._project_unified_quote_to_dict("600519", "", q)
        assert d["stock_name"] == "茅台"

    def test_param_name_wins_over_quote_name(self):
        """name param set → use it (preserves upstream board member name)."""
        from stock_data.data_provider.persistence import board as pb

        q = _q(name="Moutai")
        d = pb._project_unified_quote_to_dict("600519", "贵州茅台", q)
        assert d["stock_name"] == "贵州茅台"


class TestGetCachedMarketQuotes:
    """Tests for the cross-endpoint /stocks quote cache reader.

    Added 2026-07-30 alongside the cross-endpoint quote-cache fillup
    for /boards/{code}/stocks suffix rows (spec 2026-07-30, plan task 3).

    Note: the helper inlines the intraday/slow-cache branch logic
    rather than extracting helpers, so these tests use trade_calendar
    + time mocking via monkeypatch to control the branch without
    exposing internal hooks.
    """

    def test_returns_none_when_both_caches_miss_and_fetch_returns_none(self, monkeypatch):
        """Cache miss + upstream returns None → helper returns None, never raises."""
        from stock_data.data_provider.persistence import board as pb
        from datetime import datetime
        from zoneinfo import ZoneInfo
        import stock_data.api.cache as cache_mod

        cache_mod._stock_list_quote_cache.clear()
        cache_mod._stock_list_quote_slow.clear()
        # Force non-intraday by making is_trade_date return False
        # (then in_intraday becomes False, slow-cache path is taken;
        # both caches are clear, fetch is called, returns None).
        monkeypatch.setattr(
            "stock_data.data_provider.persistence.trade_calendar.is_trade_date",
            lambda d: False,
        )

        class _Mgr:
            def get_realtime_quotes(self, market):
                return None, ""

        result = pb.get_cached_market_quotes(_Mgr())
        assert result is None

    def test_cache_hit_returns_quotes_without_calling_manager(self, monkeypatch):
        """Cache hit → helper returns cached list, manager is never called.
        Pre-populate BOTH caches; helper should hit one and not call manager."""
        from stock_data.data_provider.persistence import board as pb
        import stock_data.api.cache as cache_mod

        cache_mod._stock_list_quote_cache.clear()
        cache_mod._stock_list_quote_slow.clear()
        # Force intraday: is_trade_day=True + mock time to 10:00.
        monkeypatch.setattr(
            "stock_data.data_provider.persistence.trade_calendar.is_trade_date",
            lambda d: True,
        )
        import datetime as _dt
        fake_now = _dt.datetime(2026, 7, 30, 10, 0, 0, tzinfo=ZoneInfo("Asia/Shanghai"))
        real_datetime = _dt.datetime
        class _Frozen(real_datetime):
            @classmethod
            def now(cls, tz=None):
                return fake_now if tz else fake_now.replace(tzinfo=None)
        monkeypatch.setattr(
            "stock_data.data_provider.persistence.board.datetime",
            _Frozen,
        )

        cached = [object(), object()]
        cache_mod._stock_list_quote_cache["stock_list_quote:csi"] = (
            cached, "zzshare",
        )

        class _Mgr:
            def __init__(self):
                self.called = False
            def get_realtime_quotes(self, market):
                self.called = True
                return None, ""

        mgr = _Mgr()
        result = pb.get_cached_market_quotes(mgr)
        assert result is cached
        assert mgr.called is False
        # Cleanup
        cache_mod._stock_list_quote_cache.clear()

    def test_cache_miss_triggers_fetch_and_writes_back(self, monkeypatch):
        """Cache miss → manager called, result written back to either cache, helper returns it."""
        from stock_data.data_provider.persistence import board as pb
        from zoneinfo import ZoneInfo
        import datetime as _dt
        import stock_data.api.cache as cache_mod

        cache_mod._stock_list_quote_cache.clear()
        cache_mod._stock_list_quote_slow.clear()
        # Force intraday via frozen time.
        monkeypatch.setattr(
            "stock_data.data_provider.persistence.trade_calendar.is_trade_date",
            lambda d: True,
        )
        fake_now = _dt.datetime(2026, 7, 30, 10, 0, 0, tzinfo=ZoneInfo("Asia/Shanghai"))
        real_datetime = _dt.datetime
        class _Frozen(real_datetime):
            @classmethod
            def now(cls, tz=None):
                return fake_now if tz else fake_now.replace(tzinfo=None)
        monkeypatch.setattr(
            "stock_data.data_provider.persistence.board.datetime",
            _Frozen,
        )

        fetched = [object(), object(), object()]

        class _Mgr:
            def get_realtime_quotes(self, market):
                return fetched, "zzshare"

        result = pb.get_cached_market_quotes(_Mgr())
        assert result is fetched
        # Write-back hit the fast cache (intraday forced).
        assert cache_mod._stock_list_quote_cache.get("stock_list_quote:csi") == (
            fetched, "zzshare",
        )
        # Cleanup
        cache_mod._stock_list_quote_cache.clear()

    def test_slow_cache_hit_returns_unwrapped_quotes(self, monkeypatch):
        """Slow cache entry is (date, session, quotes, source) 4-tuple → unwrap to quotes.
        Force non-intraday (is_trade_day=False) to take the slow-cache read path."""
        from stock_data.data_provider.persistence import board as pb
        from datetime import date
        import stock_data.api.cache as cache_mod

        cache_mod._stock_list_quote_cache.clear()
        cache_mod._stock_list_quote_slow.clear()
        # is_trade_day=False → in_intraday=False → slow-cache read path
        monkeypatch.setattr(
            "stock_data.data_provider.persistence.trade_calendar.is_trade_date",
            lambda d: False,
        )
        # Override get_latest_trade_date_on_or_before to avoid calendar
        # dependency in the (date, session) tag computation for the
        # cache write in the other tests; not strictly needed here since
        # we hit the slow cache read path before any write.
        cached = [object()]
        cache_mod._stock_list_quote_slow["stock_list_quote:csi"] = (
            date(2026, 7, 30), "afternoon", cached, "akshare",
        )

        class _Mgr:
            def __init__(self):
                self.called = False
            def get_realtime_quotes(self, market):
                self.called = True
                return None, ""

        mgr = _Mgr()
        result = pb.get_cached_market_quotes(mgr)
        assert result is cached
        assert mgr.called is False
        # Cleanup
        cache_mod._stock_list_quote_slow.clear()
