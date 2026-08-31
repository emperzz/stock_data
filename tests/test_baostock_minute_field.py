"""
Tests for BaostockFetcher minute-K field-string handling.

Background: Baostock's ``query_history_k_data_plus`` accepts different
field sets for daily vs minute frequencies. ``pctChg`` is in the daily
set but is **rejected** for minute frequencies (5/15/30/60) with the
error ``"5分钟线指标参数传入错误:pctChg"`` (and the symmetric wording
for 15/30/60m). The fetcher historically passed the same hard-coded
field string for every frequency, so every minute-K request blew up
inside Baostock before any data was returned.

This test pins the contract that the fields string is **frequency-aware**:

  * ``frequency ∈ {"d", "w", "m"}`` → includes ``pctChg`` (legacy behavior).
  * ``frequency ∈ {"5", "15", "30", "60"}`` → omits ``pctChg`` (the fix).

Tests call ``_fetch_raw_data`` directly (not ``get_kline_data``) so the
assertion runs on the fields string before the downstream
``_normalize_data`` / ``_clean_data`` pipeline parses cell values.
This isolates the fix surface area: only the fields string at the
``bs.query_history_k_data_plus`` call site is in scope.

Source: ``stock_data/data_provider/fetchers/baostock_fetcher.py``
"""

from unittest.mock import patch

import pytest

from stock_data.data_provider.fetchers.baostock_fetcher import BaostockFetcher


# ──────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────

def _enable_fetcher_init():
    """Mark BaostockFetcher._init_ok = True so _fetch_raw_data's
    ``if not BaostockFetcher._init_ok: raise`` check passes.

    Mirrors the helper in ``test_baostock_socket_self_heal.py`` — duplicated
    here rather than imported so each test file stays self-contained.
    """
    BaostockFetcher._init_attempted = True
    BaostockFetcher._init_ok = True


def _capture_fields(call_log: list):
    """Return a side_effect that records the (bs_code, fields, frequency)
    of every bs.query_history_k_data_plus call into ``call_log`` and
    returns a successful result with one row of placeholder values.

    The row length matches the requested field list so ``pd.DataFrame``
    can build a frame if any caller reads the return value; this test
    only inspects ``call_log``, not the DataFrame.
    """
    def side_effect(*args, **kwargs):
        # bs.query_history_k_data_plus(bs_code, fields, start_date=..., ...)
        # — fields is the 2nd positional arg.
        bs_code = args[0] if len(args) >= 1 else kwargs.get("code", "")
        fields = args[1] if len(args) >= 2 else kwargs.get("fields", "")
        frequency = kwargs.get("frequency", "")
        call_log.append({"bs_code": bs_code, "fields": fields, "frequency": frequency})

        field_list = fields.split(",") if isinstance(fields, str) else []
        rs = type("Rs", (), {})()
        rs.error_code = "0"
        rs.error_msg = ""
        rs.fields = field_list

        # Build a row of placeholder values matching field count.
        # Real cell values would be needed only if downstream
        # _normalize_data / _clean_data parsed them; this test calls
        # _fetch_raw_data directly, so placeholders are fine.
        row = ["2026-08-31"] + ["0.0"] * (len(field_list) - 1)

        cursor = {"i": 0}

        def nxt():
            return cursor["i"] < 1

        def grow():
            cursor["i"] += 1
            return row

        rs.next = nxt
        rs.get_row_data = grow
        return rs

    return side_effect


# ──────────────────────────────────────────────────────────────────
# Autouse fixture: isolate BaostockFetcher init state across tests
# ──────────────────────────────────────────────────────────────────
@pytest.fixture(autouse=True)
def _isolate_baostock_init():
    """Snapshot the class-level init flags so a failure here doesn't leak
    into other Baostock tests (which assume a clean state)."""
    orig_attempted = BaostockFetcher._init_attempted
    orig_ok = BaostockFetcher._init_ok
    yield
    BaostockFetcher._init_attempted = orig_attempted
    BaostockFetcher._init_ok = orig_ok


# ──────────────────────────────────────────────────────────────────
# Test 1: minute frequency — fields string MUST NOT contain pctChg
# ──────────────────────────────────────────────────────────────────
def test_minute_frequency_omits_pct_chg_in_fields_string():
    """frequency='5' → bs.query_history_k_data_plus receives a fields
    string without 'pctChg'. The current (buggy) fetcher passes
    'pctChg' for all frequencies, so Baostock SDK rejects minute-K
    requests with '5分钟线指标参数传入错误:pctChg'."""
    _enable_fetcher_init()
    fetcher = BaostockFetcher()
    call_log: list = []

    with patch(
        "baostock.query_history_k_data_plus",
        side_effect=_capture_fields(call_log),
    ):
        fetcher._fetch_raw_data(
            "000001",
            start_date="2026-08-30",
            end_date="2026-08-31",
            frequency="5",
            adjust=None,
            asset="stock",
        )

    assert len(call_log) == 1, (
        f"Expected exactly 1 bs.query call, got {len(call_log)}"
    )
    fields = call_log[0]["fields"]
    assert isinstance(fields, str)
    assert "pctChg" not in fields.split(","), (
        f"Baostock SDK rejects pctChg for minute K-line; "
        f"got fields={fields!r}"
    )
    # Sanity: the standard OHLCV+amount columns must still be requested.
    for required in ("date", "open", "high", "low", "close", "volume", "amount"):
        assert required in fields.split(","), (
            f"Expected {required!r} in fields={fields!r}"
        )


# ──────────────────────────────────────────────────────────────────
# Test 2: daily frequency — fields string MUST still include pctChg
# ──────────────────────────────────────────────────────────────────
def test_daily_frequency_still_includes_pct_chg():
    """Regression guard: the fix must not drop pctChg for daily K-line.
    Daily rows from Baostock have 8 columns (date..pctChg) and the
    unified schema relies on the pct_chg column for change_pct. Removing
    pctChg from the daily fields would silently break the change%
    contract on every /stocks/{code}/kline response.
    """
    _enable_fetcher_init()
    fetcher = BaostockFetcher()
    call_log: list = []

    with patch(
        "baostock.query_history_k_data_plus",
        side_effect=_capture_fields(call_log),
    ):
        fetcher._fetch_raw_data(
            "000001",
            start_date="2026-08-30",
            end_date="2026-08-31",
            frequency="d",
            adjust=None,
            asset="stock",
        )

    assert len(call_log) == 1
    fields = call_log[0]["fields"]
    assert "pctChg" in fields.split(","), (
        f"Daily K-line MUST include pctChg (legacy contract); "
        f"got fields={fields!r}"
    )


# ──────────────────────────────────────────────────────────────────
# Test 3: weekly/monthly — fields string MUST include pctChg
# ──────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("period", ["w", "m"])
def test_weekly_monthly_includes_pct_chg(period):
    """Same regression guard for w/m frequencies: Baostock supports
    pctChg for weekly/monthly aggregates, and removing it would break
    the unified change_pct column for /stocks/{code}/kline?frequency=w.
    """
    _enable_fetcher_init()
    fetcher = BaostockFetcher()
    call_log: list = []

    with patch(
        "baostock.query_history_k_data_plus",
        side_effect=_capture_fields(call_log),
    ):
        fetcher._fetch_raw_data(
            "000001",
            start_date="2026-07-01",
            end_date="2026-08-31",
            frequency=period,
            adjust=None,
            asset="stock",
        )

    assert len(call_log) == 1
    fields = call_log[0]["fields"]
    assert "pctChg" in fields.split(","), (
        f"frequency={period!r} MUST include pctChg; got fields={fields!r}"
    )


# ──────────────────────────────────────────────────────────────────
# Test 4: all four minute frequencies — pctChg omitted
# ──────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("period", ["5", "15", "30", "60"])
def test_all_minute_frequencies_omit_pct_chg(period):
    """Pin the omission across every minute frequency Baostock supports
    (5/15/30/60). Each of these hits the same SDK validation path, so a
    per-frequency fix (e.g. only patching '5') would still leave 15/30/60
    broken. Symmetric with test_daily_frequency_still_includes_pct_chg.
    """
    _enable_fetcher_init()
    fetcher = BaostockFetcher()
    call_log: list = []

    with patch(
        "baostock.query_history_k_data_plus",
        side_effect=_capture_fields(call_log),
    ):
        fetcher._fetch_raw_data(
            "000001",
            start_date="2026-08-30",
            end_date="2026-08-31",
            frequency=period,
            adjust=None,
            asset="stock",
        )

    assert len(call_log) == 1
    fields = call_log[0]["fields"]
    assert "pctChg" not in fields.split(","), (
        f"frequency={period!r} must omit pctChg; got fields={fields!r}"
    )
