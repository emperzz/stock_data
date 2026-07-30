"""Session-aware caching for GET /api/v1/stocks?include_quote=true.

Pins the contract from the slow-cache proposal:
- Intraday (09:15-11:30 + 13:00-15:00) → 60s fast cache.
- Non-intraday → 7d slow cache, tagged with (close_date, close_session);
  entry is reused only if the stored tag still matches the current
  ``_latest_past_close()``; on 11:30 / 15:00 / cross-day drift, upstream
  is re-queried.

All times are simulated by patching the route's `datetime.now` and the
trade_calendar helpers, so the tests don't depend on the wall clock or
on the SQLite trade-calendar table contents.
"""

import datetime as _dt
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

import pytest

from stock_data.api.cache import (
    get_stock_list_quote_cache,
    get_stock_list_quote_slow,
)
from stock_data.api.routes import stocks as stocks_mod
from stock_data.api.routes.stocks import _list_stocks_with_quote
from stock_data.data_provider.core.types import UnifiedRealtimeQuote

CST = ZoneInfo("Asia/Shanghai")

# Trade dates used across the tests. ``FRIDAY`` is treated as a trade day;
# ``SATURDAY`` and ``SUNDAY`` as non-trade days. The trade_calendar helpers
# are mocked per-test so the actual SQLite content doesn't matter.
FRIDAY = _dt.date(2026, 7, 31)
SATURDAY = _dt.date(2026, 8, 1)
SUNDAY = _dt.date(2026, 8, 2)
MONDAY = _dt.date(2026, 8, 3)


def _make_quote(code: str = "600519", price: float = 1000.0) -> UnifiedRealtimeQuote:
    return UnifiedRealtimeQuote(code=code, name="测试", price=price)


def _make_manager() -> MagicMock:
    mgr = MagicMock()
    mgr.get_realtime_quotes.return_value = ([_make_quote()], "akshare")
    return mgr


@pytest.fixture(autouse=True)
def _clear_caches():
    get_stock_list_quote_cache().clear()
    get_stock_list_quote_slow().clear()
    yield
    get_stock_list_quote_cache().clear()
    get_stock_list_quote_slow().clear()


def _at(now: _dt.datetime, *, is_trade_day: bool, prev_trade_date: _dt.date):
    """Patch route's `datetime.now` + trade_calendar helpers.

    Returns a contextmanager. Inside the block, every call to the route's
    `datetime.now()` returns `now`, `trade_calendar.is_trade_date` returns
    `is_trade_day`, and `get_latest_trade_date_on_or_before` returns
    `prev_trade_date.isoformat()`.
    """
    from contextlib import contextmanager

    @contextmanager
    def _ctx():
        with patch.object(stocks_mod, "datetime") as mock_dt:
            mock_dt.now.return_value = now
            with patch.object(stocks_mod.trade_calendar, "is_trade_date", return_value=is_trade_day), \
                 patch.object(
                     stocks_mod.trade_calendar,
                     "get_latest_trade_date_on_or_before",
                     return_value=prev_trade_date.isoformat(),
                 ):
                yield
    return _ctx()


# ---------------------------------------------------------------------------
# (date, session) helper
# ---------------------------------------------------------------------------

class TestLatestPastClose:
    """_latest_past_close() returns (date, session) for the most recent close."""

    def test_intraday_uses_today_afternoon_if_past_1500(self):
        now = _dt.datetime(FRIDAY.year, FRIDAY.month, FRIDAY.day, 15, 30, tzinfo=CST)
        with _at(now, is_trade_day=True, prev_trade_date=FRIDAY):
            d, s = stocks_mod._latest_past_close()
        assert (d, s) == (FRIDAY, "afternoon")

    def test_lunch_uses_today_morning(self):
        # Friday 12:00 — between 11:30 and 15:00
        now = _dt.datetime(FRIDAY.year, FRIDAY.month, FRIDAY.day, 12, 0, tzinfo=CST)
        with _at(now, is_trade_day=True, prev_trade_date=FRIDAY):
            d, s = stocks_mod._latest_past_close()
        assert (d, s) == (FRIDAY, "morning")

    def test_pre_market_uses_previous_afternoon(self):
        # Friday 09:00 — before 09:15, target = previous trading day's afternoon
        prev = _dt.date(2026, 7, 30)  # Thursday
        now = _dt.datetime(FRIDAY.year, FRIDAY.month, FRIDAY.day, 9, 0, tzinfo=CST)
        with _at(now, is_trade_day=True, prev_trade_date=prev):
            d, s = stocks_mod._latest_past_close()
        assert (d, s) == (prev, "afternoon")

    def test_non_trade_day_uses_last_afternoon(self):
        # Saturday 12:00 — not a trade day, target = last trade day's afternoon
        now = _dt.datetime(SATURDAY.year, SATURDAY.month, SATURDAY.day, 12, 0, tzinfo=CST)
        with _at(now, is_trade_day=False, prev_trade_date=FRIDAY):
            d, s = stocks_mod._latest_past_close()
        assert (d, s) == (FRIDAY, "afternoon")

    def test_1130_exact_boundary(self):
        """11:30:00.000 — `_MORNING_CLOSE` is exclusive upper bound (`<`),
        so 11:30:00 itself is non-intraday, target (today, morning)."""
        now = _dt.datetime(FRIDAY.year, FRIDAY.month, FRIDAY.day, 11, 30, 0, tzinfo=CST)
        with _at(now, is_trade_day=True, prev_trade_date=FRIDAY):
            d, s = stocks_mod._latest_past_close()
        assert (d, s) == (FRIDAY, "morning")

    def test_1500_exact_boundary(self):
        """15:00:00.000 — `_AFTERNOON_CLOSE` is exclusive upper bound (`<`),
        so 15:00:00 itself is non-intraday, target (today, afternoon)."""
        now = _dt.datetime(FRIDAY.year, FRIDAY.month, FRIDAY.day, 15, 0, 0, tzinfo=CST)
        with _at(now, is_trade_day=True, prev_trade_date=FRIDAY):
            d, s = stocks_mod._latest_past_close()
        assert (d, s) == (FRIDAY, "afternoon")

    def test_empty_calendar_falls_back_safely(self):
        """Fresh-boot case: trade_calendar table is empty so both
        is_trade_date and get_latest_trade_date_on_or_before return falsy.
        Must NOT crash — should fall back to (today, afternoon)."""
        now = _dt.datetime(FRIDAY.year, FRIDAY.month, FRIDAY.day, 9, 0, tzinfo=CST)
        with patch.object(stocks_mod, "datetime") as mock_dt:
            mock_dt.now.return_value = now
            with patch.object(stocks_mod.trade_calendar, "is_trade_date", return_value=False), \
                 patch.object(
                     stocks_mod.trade_calendar,
                     "get_latest_trade_date_on_or_before",
                     return_value=None,
                 ):
                d, s = stocks_mod._latest_past_close()
        assert (d, s) == (FRIDAY, "afternoon")


# ---------------------------------------------------------------------------
# Intraday path: fast cache (60s TTL), 1 upstream call per window
# ---------------------------------------------------------------------------

class TestIntradayFastCache:
    def test_repeated_intraday_calls_only_fetch_once(self):
        mgr = _make_manager()
        now = _dt.datetime(FRIDAY.year, FRIDAY.month, FRIDAY.day, 10, 0, tzinfo=CST)
        with _at(now, is_trade_day=True, prev_trade_date=FRIDAY):
            for _ in range(3):
                _list_stocks_with_quote(mgr, 0, 10, None, "desc")
        assert mgr.get_realtime_quotes.call_count == 1

    def test_intraday_does_not_populate_slow_cache(self):
        mgr = _make_manager()
        now = _dt.datetime(FRIDAY.year, FRIDAY.month, FRIDAY.day, 10, 0, tzinfo=CST)
        with _at(now, is_trade_day=True, prev_trade_date=FRIDAY):
            _list_stocks_with_quote(mgr, 0, 10, None, "desc")
        assert len(get_stock_list_quote_slow()) == 0
        assert len(get_stock_list_quote_cache()) == 1


# ---------------------------------------------------------------------------
# Non-intraday path: slow cache with (date, session) tag
# ---------------------------------------------------------------------------

class TestSlowCacheFreshness:
    def test_first_non_intraday_call_populates_slow_with_4_tuple(self):
        mgr = _make_manager()
        now = _dt.datetime(SATURDAY.year, SATURDAY.month, SATURDAY.day, 12, 0, tzinfo=CST)
        with _at(now, is_trade_day=False, prev_trade_date=FRIDAY):
            _list_stocks_with_quote(mgr, 0, 10, None, "desc")
        slow = get_stock_list_quote_slow()
        assert len(slow) == 1
        entry = next(iter(slow.values()))
        assert len(entry) == 4  # (close_date, close_session, quotes, source)
        cached_date, cached_session, _, _ = entry
        assert (cached_date, cached_session) == (FRIDAY, "afternoon")

    def test_same_target_repeated_call_hits_slow_no_refetch(self):
        mgr = _make_manager()
        now = _dt.datetime(SATURDAY.year, SATURDAY.month, SATURDAY.day, 12, 0, tzinfo=CST)
        with _at(now, is_trade_day=False, prev_trade_date=FRIDAY):
            for _ in range(3):
                _list_stocks_with_quote(mgr, 0, 10, None, "desc")
        assert mgr.get_realtime_quotes.call_count == 1

    def test_cross_day_to_next_lunch_refetches(self):
        """Saturday 12:00 → Monday 12:00: target shifts from (FRIDAY, afternoon)
        to (MONDAY, morning) → refetch must fire."""
        mgr = _make_manager()
        sat = _dt.datetime(SATURDAY.year, SATURDAY.month, SATURDAY.day, 12, 0, tzinfo=CST)
        mon = _dt.datetime(MONDAY.year, MONDAY.month, MONDAY.day, 12, 0, tzinfo=CST)
        with _at(sat, is_trade_day=False, prev_trade_date=FRIDAY):
            _list_stocks_with_quote(mgr, 0, 10, None, "desc")
        with _at(mon, is_trade_day=True, prev_trade_date=FRIDAY):
            _list_stocks_with_quote(mgr, 0, 10, None, "desc")
        assert mgr.get_realtime_quotes.call_count == 2
        entry = next(iter(get_stock_list_quote_slow().values()))
        cached_date, cached_session, _, _ = entry
        assert (cached_date, cached_session) == (MONDAY, "morning")

    def test_lunch_to_post_market_same_day_refetches(self):
        """Friday 12:00 → Friday 15:30: target shifts from (FRIDAY, morning)
        to (FRIDAY, afternoon) → refetch must fire."""
        mgr = _make_manager()
        lunch = _dt.datetime(FRIDAY.year, FRIDAY.month, FRIDAY.day, 12, 0, tzinfo=CST)
        post = _dt.datetime(FRIDAY.year, FRIDAY.month, FRIDAY.day, 15, 30, tzinfo=CST)
        with _at(lunch, is_trade_day=True, prev_trade_date=FRIDAY):
            _list_stocks_with_quote(mgr, 0, 10, None, "desc")
        with _at(post, is_trade_day=True, prev_trade_date=FRIDAY):
            _list_stocks_with_quote(mgr, 0, 10, None, "desc")
        assert mgr.get_realtime_quotes.call_count == 2
        entry = next(iter(get_stock_list_quote_slow().values()))
        cached_date, cached_session, _, _ = entry
        assert (cached_date, cached_session) == (FRIDAY, "afternoon")

    def test_pre_market_to_lunch_same_day_refetches(self):
        """Friday 09:00 → Friday 12:00: target shifts from (THU, afternoon)
        to (FRI, morning) → refetch must fire."""
        mgr = _make_manager()
        prev = _dt.date(2026, 7, 30)  # Thursday
        pre = _dt.datetime(FRIDAY.year, FRIDAY.month, FRIDAY.day, 9, 0, tzinfo=CST)
        lunch = _dt.datetime(FRIDAY.year, FRIDAY.month, FRIDAY.day, 12, 0, tzinfo=CST)
        with _at(pre, is_trade_day=True, prev_trade_date=prev):
            _list_stocks_with_quote(mgr, 0, 10, None, "desc")
        with _at(lunch, is_trade_day=True, prev_trade_date=FRIDAY):
            _list_stocks_with_quote(mgr, 0, 10, None, "desc")
        assert mgr.get_realtime_quotes.call_count == 2

    def test_weekend_full_hold_only_fetches_once(self):
        """Friday 15:30 → Saturday 12:00 → Sunday 12:00 → Monday 09:00: all
        share target (FRIDAY, afternoon) until Monday's morning boundary.
        """
        mgr = _make_manager()
        moments = [
            (_dt.datetime(FRIDAY.year, FRIDAY.month, FRIDAY.day, 15, 30, tzinfo=CST), True, FRIDAY),
            (_dt.datetime(SATURDAY.year, SATURDAY.month, SATURDAY.day, 12, 0, tzinfo=CST), False, FRIDAY),
            (_dt.datetime(SUNDAY.year, SUNDAY.month, SUNDAY.day, 12, 0, tzinfo=CST), False, FRIDAY),
            (_dt.datetime(MONDAY.year, MONDAY.month, MONDAY.day, 9, 0, tzinfo=CST), True, FRIDAY),
        ]
        for now, is_td, prev in moments:
            with _at(now, is_trade_day=is_td, prev_trade_date=prev):
                _list_stocks_with_quote(mgr, 0, 10, None, "desc")
        # Fri 15:30 fetched; Sat/Sun/Mon 09:00 all hit the same (FRIDAY, afternoon) entry
        assert mgr.get_realtime_quotes.call_count == 1


# ---------------------------------------------------------------------------
# Cross-path: intraday does not write to slow, non-intraday does not pollute fast
# ---------------------------------------------------------------------------

class TestCacheSeparation:
    def test_intraday_does_not_touch_slow(self):
        mgr = _make_manager()
        now = _dt.datetime(FRIDAY.year, FRIDAY.month, FRIDAY.day, 10, 0, tzinfo=CST)
        with _at(now, is_trade_day=True, prev_trade_date=FRIDAY):
            _list_stocks_with_quote(mgr, 0, 10, None, "desc")
        assert len(get_stock_list_quote_slow()) == 0
        assert len(get_stock_list_quote_cache()) == 1

    def test_non_intraday_does_not_touch_fast(self):
        mgr = _make_manager()
        now = _dt.datetime(SATURDAY.year, SATURDAY.month, SATURDAY.day, 12, 0, tzinfo=CST)
        with _at(now, is_trade_day=False, prev_trade_date=FRIDAY):
            _list_stocks_with_quote(mgr, 0, 10, None, "desc")
        assert len(get_stock_list_quote_cache()) == 0
        assert len(get_stock_list_quote_slow()) == 1

    def test_lunch_12_routes_to_slow_with_morning_tag(self):
        """Friday 12:00 (lunch) is non-intraday → slow path; entry tagged
        (FRIDAY, morning); fast cache stays empty."""
        mgr = _make_manager()
        now = _dt.datetime(FRIDAY.year, FRIDAY.month, FRIDAY.day, 12, 0, tzinfo=CST)
        with _at(now, is_trade_day=True, prev_trade_date=FRIDAY):
            _list_stocks_with_quote(mgr, 0, 10, None, "desc")
        assert len(get_stock_list_quote_cache()) == 0
        assert len(get_stock_list_quote_slow()) == 1
        entry = next(iter(get_stock_list_quote_slow().values()))
        cached_date, cached_session, _, _ = entry
        assert (cached_date, cached_session) == (FRIDAY, "morning")

    def test_1130_exact_routes_to_slow(self):
        """11:30:00 boundary is non-intraday (exclusive upper bound) → slow."""
        mgr = _make_manager()
        now = _dt.datetime(FRIDAY.year, FRIDAY.month, FRIDAY.day, 11, 30, 0, tzinfo=CST)
        with _at(now, is_trade_day=True, prev_trade_date=FRIDAY):
            _list_stocks_with_quote(mgr, 0, 10, None, "desc")
        assert len(get_stock_list_quote_cache()) == 0
        assert len(get_stock_list_quote_slow()) == 1


# ---------------------------------------------------------------------------
# 503 contract when upstream returns empty
# ---------------------------------------------------------------------------

class TestFetchQuoteError:
    def test_empty_list_raises_503(self):
        from fastapi import HTTPException

        mgr = MagicMock()
        mgr.get_realtime_quotes.return_value = ([], "akshare")
        now = _dt.datetime(FRIDAY.year, FRIDAY.month, FRIDAY.day, 10, 0, tzinfo=CST)
        with _at(now, is_trade_day=True, prev_trade_date=FRIDAY):
            with pytest.raises(HTTPException) as exc:
                _list_stocks_with_quote(mgr, 0, 10, None, "desc")
        assert exc.value.status_code == 503
        assert exc.value.detail["error"] == "quote_unavailable"

    def test_empty_list_does_not_pollute_cache(self):
        """Failed fetch must not write to either cache — otherwise the next
        request would serve a stale entry for 60s/7d."""
        from fastapi import HTTPException

        mgr = MagicMock()
        mgr.get_realtime_quotes.return_value = ([], "akshare")
        now = _dt.datetime(FRIDAY.year, FRIDAY.month, FRIDAY.day, 10, 0, tzinfo=CST)
        with _at(now, is_trade_day=True, prev_trade_date=FRIDAY):
            with pytest.raises(HTTPException):
                _list_stocks_with_quote(mgr, 0, 10, None, "desc")
        assert len(get_stock_list_quote_cache()) == 0
        assert len(get_stock_list_quote_slow()) == 0
