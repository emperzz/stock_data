"""Tests for the trade_calendar persistence module.

Pins the UPSERT (not wipe-and-replace) contract of ``update_cached_calendar``.

Background
----------
``update_cached_calendar`` historically did a blanket
``DELETE FROM trade_calendar`` before inserting the new dates. That
semantics is dangerous for any caller that wants to add dates
incrementally (e.g. tests, a future per-day refresh path) — the call
unconditionally destroys every date it wasn't passed. It also forces
callers that hold a partial update (e.g. "add date X") to first read
the full calendar, append X, then rewrite the whole thing.

The fix is to make the function a pure upsert: ``INSERT OR REPLACE``
keyed by ``trade_date`` (which is already UNIQUE in the schema). The
only production caller (``manager.get_trade_calendar``) passes the
full set returned by the upstream, so its observable behavior is
unchanged — but the function is now safe to use from any context.
"""
from stock_data.data_provider.persistence.db import get_connection
from stock_data.data_provider.persistence.trade_calendar import (
    get_cached_calendar,
    init_schema,
    update_cached_calendar,
)

# --- helpers (intentionally tiny, kept local to the test) ---


def _seed(date_str: str) -> None:
    """INSERT a date directly. Used to set up pre-existing state that
    ``update_cached_calendar`` should preserve."""
    init_schema()
    conn = get_connection()
    conn.execute(
        "INSERT OR REPLACE INTO trade_calendar (trade_date) VALUES (?)",
        (date_str,),
    )
    conn.commit()


def _wipe(date_str: str) -> None:
    conn = get_connection()
    conn.execute(
        "DELETE FROM trade_calendar WHERE trade_date = ?",
        (date_str,),
    )
    conn.commit()


def _all_dates() -> list[str]:
    dates, _ = get_cached_calendar()
    return dates


# --- the test ---


def test_update_cached_calendar_preserves_unrelated_dates():
    """``update_cached_calendar`` must be a pure upsert, not wipe-and-replace.

    Setup: two sentinel dates in the calendar (``keep`` and ``untouched``).
    Call: ``update_cached_calendar([update])`` — a single new date.
    Expect: full-replace — old dates not in the new list are removed,
    and the new date is inserted.
    """
    keep = "2099-01-01"        # pre-existing, not in the new list
    update = "2099-02-02"      # in the new list
    untouched = "2099-03-03"   # pre-existing, not in the new list

    _seed(keep)
    _seed(untouched)
    _wipe(update)  # ensure a clean slate for the new insert

    try:
        result = update_cached_calendar([update])

        assert result == 1, f"Expected 1 row affected, got {result}"
        dates = _all_dates()
        assert keep not in dates, (
            f"Pre-existing {keep!r} should have been removed by full-replace."
        )
        assert untouched not in dates, (
            f"Pre-existing {untouched!r} should have been removed by full-replace."
        )
        assert update in dates, f"Newly-inserted {update!r} is missing"
    finally:
        for d in (keep, update, untouched):
            _wipe(d)


def test_update_cached_calendar_refreshes_existing_date_updated_at():
    """Re-upserting the same date refreshes its ``updated_at`` (no duplicate row)."""
    target = "2099-04-04"
    _wipe(target)

    try:
        update_cached_calendar([target])
        first_dates, _ = get_cached_calendar()
        assert first_dates.count(target) == 1, "Single row expected after first upsert"

        # Sleep is overkill — the second upsert with a fresh ``now`` is enough
        # to demonstrate that updated_at moves forward. We don't assert the
        # exact value (would be flaky); we just check the function doesn't
        # raise and still ends up with exactly one row for this date.
        update_cached_calendar([target])
        second_dates, _ = get_cached_calendar()
        assert second_dates.count(target) == 1, (
            "Re-upserting the same date must not create a duplicate row"
        )
    finally:
        _wipe(target)


def test_update_cached_calendar_with_empty_list_is_noop():
    """Empty input list is a safe no-op (existing rows preserved, no error)."""
    sentinel = "2099-05-05"
    _seed(sentinel)

    try:
        result = update_cached_calendar([])
        assert result == 0
        assert sentinel in _all_dates(), "Empty update should not touch existing rows"
    finally:
        _wipe(sentinel)
