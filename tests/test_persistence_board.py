"""Unit + integration tests for stock_data.data_provider.persistence.board.

Added 2026-07-30: union-semantic _enrich_rows_with_market_quote helper
unit tests + E2E (spec 2026-07-30, plan task 4).
"""
from zoneinfo import ZoneInfo

import pytest

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


class TestEnrichRowsWithMarketQuote:
    """Tests for _enrich_rows_with_market_quote (spec 2026-07-30, plan task 4).

    Union semantics: for each row, fill in any quote-shaped field whose
    value is None or missing by looking up the row's stock_code in the
    market-quote index. Existing non-None values are preserved (THS rows
    take priority for fields they have; /stocks cache fills the gaps).

    THS-only fields (change_speed, free_float_shares, float_market_cap)
    are NEVER set here. ZT-pool fields (is_limit_up, lb_count) are
    NEVER set here (set by route-layer ZT join).

    Fillable fields (13):
        price, change_pct, change_amount, volume, amount,
        turnover_rate, volume_ratio, pe_ratio,
        open, high, low, prev_close, amplitude
    """

    def test_rows_with_all_none_filled_with_13_fields(self):
        """Suffix-like row (all None quote fields) gets all 13 fillable
        fields from the market quote. This is the original suffix
        enrichment behavior — the union semantics subsumes it because
        all fields are None."""
        from stock_data.data_provider.persistence import board as pb

        rows = [
            {"stock_code": "600000", "stock_name": "浦发银行"},
            {"stock_code": "601318", "stock_name": "中国平安"},
        ]
        market_quotes = [
            _q(
                code="600000", name="浦发银行", price=8.0, change_pct=0.0,
                change_amount=0.0, volume=5000000, amount=4.0e7,
                turnover_rate=0.3, volume_ratio=1.1, amplitude=1.5,
                open_price=7.95, high=8.05, low=7.90, pre_close=8.0,
                pe_ratio=5.0,
            ),
            _q(
                code="601318", name="中国平安", price=50.0, change_pct=2.0,
                change_amount=1.0, volume=10000000, amount=5.0e8,
                turnover_rate=0.4, volume_ratio=1.2, amplitude=2.5,
                open_price=49.5, high=50.5, low=49.0, pre_close=49.0,
                pe_ratio=8.0,
            ),
        ]

        enriched = pb._enrich_rows_with_market_quote(rows, market_quotes)
        assert len(enriched) == 2
        # 600000 was enriched with upstream-style dict keys
        row_600000 = next(r for r in enriched if r["stock_code"] == "600000")
        assert row_600000["stock_code"] == "600000"
        assert row_600000["stock_name"] == "浦发银行"
        assert row_600000["price"] == 8.0
        assert row_600000["open"] == 7.95
        assert row_600000["amplitude"] == 1.5
        assert row_600000["turnover_rate"] == 0.3
        # 13 fillable fields populated
        for f in ("price", "change_pct", "change_amount", "volume", "amount",
                  "turnover_rate", "amplitude", "volume_ratio", "pe_ratio",
                  "open", "high", "low", "prev_close"):
            assert row_600000.get(f) is not None, f"{f} should be filled"
        # THS-only fields stay absent
        assert "change_speed" not in row_600000
        assert "free_float_shares" not in row_600000
        assert "float_market_cap" not in row_600000
        # 601318 was enriched
        row_601318 = next(r for r in enriched if r["stock_code"] == "601318")
        assert row_601318["price"] == 50.0
        assert row_601318["turnover_rate"] == 0.4

    def test_ths_row_keeps_existing_values_only_fills_missing(self):
        """Union semantics: THS top-50 row (has price/change_pct/etc
        populated but open/high/low/prev_close/volume are None) only
        gets the missing fields filled. Existing non-None values
        are preserved (no overwrite)."""
        from stock_data.data_provider.persistence import board as pb

        # Simulate a THS top-50 row: most fields set, but
        # open/high/low/prev_close/volume/amplitude are None (THS 14
        # columns don't include them).
        ths_row = {
            "stock_code": "300469", "stock_name": "信息发展",
            "price": 51.4,
            "change_pct": 6.71,
            "change_amount": 3.23,
            "amount": 425000000.0,
            "turnover_rate": 3.57,
            "amplitude": 11.31,  # THS column 9
            "change_speed": -0.04,  # THS column 6
            "volume_ratio": 0.95,  # THS column 8
            "free_float_shares": 248000000,  # THS column 11
            "float_market_cap": 12753000000.0,  # THS column 12
            "pe_ratio": None,  # THS upstream `--`
            # open / high / low / prev_close / volume are None (THS missing)
        }
        market_quote = _q(
            code="300469", name="信息发展",
            # /stocks has different values (cache could be 0-60s old)
            price=99.9,  # DIFFERENT from THS
            change_pct=99.9,  # DIFFERENT
            change_amount=99.9,  # DIFFERENT
            volume=1234567,  # /stocks has it, THS doesn't
            amount=888e6,  # DIFFERENT
            turnover_rate=99.9,  # DIFFERENT
            amplitude=99.9,  # DIFFERENT
            volume_ratio=99.9,  # DIFFERENT
            pe_ratio=42.0,  # /stocks has it, THS was None
            open_price=50.5,  # /stocks has it
            high=52.0,
            low=50.0,
            pre_close=48.17,
        )

        enriched = pb._enrich_rows_with_market_quote([ths_row], [market_quote])
        assert len(enriched) == 1
        out = enriched[0]

        # Existing THS values PRESERVED (no overwrite from /stocks)
        assert out["price"] == 51.4  # not 99.9
        assert out["change_pct"] == 6.71  # not 99.9
        assert out["change_amount"] == 3.23  # not 99.9
        assert out["amount"] == 425000000.0  # not 888e6
        assert out["turnover_rate"] == 3.57  # not 99.9
        assert out["amplitude"] == 11.31  # not 99.9
        assert out["volume_ratio"] == 0.95  # not 99.9
        # THS-only fields preserved
        assert out["change_speed"] == -0.04
        assert out["free_float_shares"] == 248000000
        assert out["float_market_cap"] == 12753000000.0

        # Missing fields FILLED from /stocks
        assert out["volume"] == 1234567
        assert out["open"] == 50.5
        assert out["high"] == 52.0
        assert out["low"] == 50.0
        assert out["prev_close"] == 48.17
        # pe_ratio was None in THS, filled from /stocks
        assert out["pe_ratio"] == 42.0

    def test_row_not_in_market_quote_kept_as_is(self):
        """A code absent from market quote (停牌/新上市) is kept as-is."""
        from stock_data.data_provider.persistence import board as pb

        rows = [{"stock_code": "688999", "stock_name": "新股A"}]
        market_quotes = [
            _q(code="600000", name="浦发银行"),
        ]
        enriched = pb._enrich_rows_with_market_quote(rows, market_quotes)
        # 688999 not in index → kept as-is
        assert len(enriched) == 1
        assert enriched[0]["stock_code"] == "688999"
        assert enriched[0].get("price") is None
        assert enriched[0].get("amplitude") is None

    def test_empty_market_quote_returns_input_unchanged(self):
        """Empty market_quote → return copy of rows without enrichment."""
        from stock_data.data_provider.persistence import board as pb

        rows = [{"stock_code": "600000", "stock_name": "x"}]
        enriched = pb._enrich_rows_with_market_quote(rows, [])
        assert enriched == rows
        assert enriched is not rows

    def test_input_list_not_mutated(self):
        """Helper returns a new list; input rows is not mutated."""
        from stock_data.data_provider.persistence import board as pb

        rows = [{"stock_code": "600000", "stock_name": "x"}]
        market_quotes = [
            _q(code="600000", name="x", price=10.0),
        ]
        pb._enrich_rows_with_market_quote(rows, market_quotes)
        # Input dict not mutated
        assert "price" not in rows[0]
        assert "amplitude" not in rows[0]

    def test_amplitude_fallback_fills_when_unified_amplitude_is_none(self):
        """When q.amplitude is None but high/low/pre_close are set, the
        (h-l)/pre_close*100 formula fills the amplitude field. Applies
        to both suffix rows and THS top-50 rows missing amplitude."""
        from stock_data.data_provider.persistence import board as pb

        row = {"stock_code": "600000", "stock_name": "x", "amplitude": None}
        q = _q(
            code="600000", name="x", amplitude=None,
            high=10.5, low=10.0, pre_close=10.0,
        )
        enriched = pb._enrich_rows_with_market_quote([row], [q])
        # (10.5 - 10.0) / 10.0 * 100 = 5.0
        assert enriched[0]["amplitude"] == pytest.approx(5.0, rel=1e-3)


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

        import stock_data.api.cache as cache_mod
        from stock_data.data_provider.persistence import board as pb

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
        import stock_data.api.cache as cache_mod
        from stock_data.data_provider.persistence import board as pb

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
        """Cache miss → manager called, result written back to cache, helper returns it."""
        import datetime as _dt
        from zoneinfo import ZoneInfo

        import stock_data.api.cache as cache_mod
        from stock_data.data_provider.persistence import board as pb

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
        # Cache was written back.
        assert cache_mod._stock_list_quote_cache.get("stock_list_quote:csi") == (
            fetched, "zzshare",
        )
        # Cleanup
        cache_mod._stock_list_quote_cache.clear()

    def test_slow_cache_hit_returns_unwrapped_quotes(self, monkeypatch):
        """Slow cache entry is (date, session, quotes, source) 4-tuple → unwrap to quotes.
        Force non-intraday (is_trade_day=False) to take the slow-cache read path."""
        from datetime import date

        import stock_data.api.cache as cache_mod
        from stock_data.data_provider.persistence import board as pb

        cache_mod._stock_list_quote_cache.clear()
        cache_mod._stock_list_quote_slow.clear()
        # is_trade_day=False → in_intraday=False → slow-cache read path
        monkeypatch.setattr(
            "stock_data.data_provider.persistence.trade_calendar.is_trade_date",
            lambda d: False,
        )
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


class TestGetBoardStocksUnionFillupE2E:
    """End-to-end test for /boards/{code}/stocks union fillup behavior.

    Verifies the new spec union semantics: include_quote=true returns
    THS top-50 rows with the 5 fields THS upstream doesn't have
    (open/high/low/prev_close/volume) filled from /stocks quote cache.
    Suffix rows (members beyond THS 50-cap) get all 13 fillable
    fields from /stocks cache.

    Uses monkeypatch to mock all upstream calls; no real network.
    """

    def test_ths_top50_row_gets_missing_fields_filled(self, monkeypatch, tmp_path):
        """THS top-50 row: 11 quote fields from THS, 5 missing fields
        (open/high/low/prev_close/volume) filled from /stocks cache.
        THS existing values are NOT overwritten.
        """
        from stock_data.data_provider.persistence import board as pb

        # Set up: 1 THS top-50 row (has price/change_pct/etc, missing
        # open/high/low/prev_close/volume) + 1 suffix row (only code/name).
        ths_top_row = {
            "stock_code": "300469", "stock_name": "信息发展",
            "price": 51.4, "change_pct": 6.71, "change_amount": 3.23,
            "amount": 425000000.0, "turnover_rate": 3.57,
            "amplitude": 11.31, "change_speed": -0.04, "volume_ratio": 0.95,
            "free_float_shares": 248000000, "float_market_cap": 12753000000.0,
            "pe_ratio": None,
            # open / high / low / prev_close / volume all None
        }
        suffix_row = {"stock_code": "688999", "stock_name": "新股A"}

        # THS upstream returns 1 row (the top-50 row).
        # ZZSHARE returns the suffix row.
        # /stocks cache has data for both codes.
        market_quotes = [
            _q(
                code="300469", name="信息发展",
                volume=1234567,
                open_price=50.5, high=52.0, low=50.0, pre_close=48.17,
                pe_ratio=42.0,
            ),
            _q(
                code="688999", name="新股A", price=10.0, change_pct=0.0,
                change_amount=0.0, volume=500000, amount=5e6,
                turnover_rate=0.5, volume_ratio=1.0,
                open_price=9.9, high=10.1, low=9.8, pre_close=9.85,
                pe_ratio=15.0, amplitude=2.5,
            ),
        ]

        # Stub the DB to be empty so the cache branch is taken.
        monkeypatch.setattr(pb, "_read_board_stocks_from_db", lambda *a, **kw: [])
        monkeypatch.setattr(pb, "update_cached_board_stocks", lambda *a, **kw: 0)
        # CID resolution returns a valid CID so THS branch proceeds.
        monkeypatch.setattr(pb, "_resolve_ths_cid_from_platecode", lambda code: "301558")

        # Stub get_cached_market_quotes to return our market quotes.
        monkeypatch.setattr(pb, "get_cached_market_quotes", lambda mgr: market_quotes)

        # Stub the upstream fetcher calls.
        class _Mgr:
            def get_board_stocks(self, board_code, source, **kwargs):
                if kwargs.get("include_quote"):
                    return [ths_top_row], "ths"
                return [suffix_row], "zzshare"
            def get_realtime_quotes(self, market):
                return market_quotes, "zzshare"

        result = pb.get_board_stocks(
            board_code="885406",
            source="ths",
            refresh=True,
            include_quote=True,
            manager=_Mgr(),
        )
        # 6-tuple return
        assert len(result) == 6
        stocks, origin, es, reason, quote_truncated, total_in_board = result
        # Order: THS top-50 first, suffix after
        assert len(stocks) == 2
        assert stocks[0]["stock_code"] == "300469"
        assert stocks[1]["stock_code"] == "688999"

        # THS top-50 row: existing fields preserved, 5 missing filled
        ths_row = stocks[0]
        assert ths_row["price"] == 51.4  # THS preserved
        assert ths_row["change_pct"] == 6.71  # THS preserved
        assert ths_row["turnover_rate"] == 3.57  # THS preserved
        assert ths_row["amplitude"] == 11.31  # THS preserved
        assert ths_row["change_speed"] == -0.04  # THS-only preserved
        assert ths_row["free_float_shares"] == 248000000  # THS-only preserved
        # 5 missing fields filled from /stocks cache
        assert ths_row["volume"] == 1234567
        assert ths_row["open"] == 50.5
        assert ths_row["high"] == 52.0
        assert ths_row["low"] == 50.0
        assert ths_row["prev_close"] == 48.17
        # pe_ratio was None in THS, filled from /stocks
        assert ths_row["pe_ratio"] == 42.0

        # Suffix row: all 13 fillable fields filled
        suf_row = stocks[1]
        assert suf_row["price"] == 10.0
        assert suf_row["volume"] == 500000
        assert suf_row["open"] == 9.9
        assert suf_row["high"] == 10.1
        assert suf_row["low"] == 9.8
        assert suf_row["prev_close"] == 9.85
        assert suf_row["amplitude"] == 2.5
        assert suf_row["pe_ratio"] == 15.0

        # quote_truncated: suffix was non-empty → True
        assert quote_truncated is True
