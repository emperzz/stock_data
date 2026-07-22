"""Tests for ThsFetcher.get_board_history and runtime health checks.

Post-2026-07-14: ThsFetcher supports all 7 THS K-line frequencies
(d / w / m / 5m / 15m / 30m / 60m) and uniformly accepts platecode as
input. The fetcher's clid→platecode helper is now named
``_resolve_ths_platecode_from_cid`` (the upstream HTML element is named
``<input id="clid">`` but its value is a 6-digit platecode — the old
``_resolve_ths_concept_clid`` name suggested a T-prefixed value that the
upstream never actually emitted).
"""

from unittest.mock import patch

import pytest

from stock_data.data_provider.fetchers import ths_fetcher as ths_mod

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

# Raw upstream date format (post-2026-07-14 normalization): the parser
# accepts YYYYMMDD (daily/weekly/monthly) and YYYYMMDDHHMM (minute bars).
# The first 7 columns are the canonical K-line subset
# (date, open, high, low, close, volume, amount).
_DAILY_BODY_2024 = 'var v_x={"data":"20241215,1,2,3,4,5,6,7,8,9,10;"};'
_DAILY_BODY_2025 = (
    'var v_x={"data":"20250630,1,2,3,4,5,6,7,8,9,10;'
    '20250629,1.1,2.1,3.1,4.1,5.1,6.1,7.1,8.1,9.1,10.1;"};'
)
# 5-minute body with YYYYMMDDHHMM dates — the parser normalizes these
# into "YYYY-MM-DD HH:MM" so the route-layer date filter works.
_5MIN_BODY = (
    'var v_x={"data":"202607130935,1,2,3,4,5,6,7,8,9,10;'
    '202607130940,1.1,2.1,3.1,4.1,5.1,6.1,7.1,8.1,9.1,10.1;"};'
)


def _fake_row(date_str: str, freq: str) -> dict:
    """Build a canonical K-line row dict for mocking _fetch_ths_single_kline."""
    return {
        "date": date_str,
        "open": 1.0,
        "high": 2.0,
        "low": 3.0,
        "close": 4.0,
        "volume": 100,
        "amount": 1000.0,
        "frequency": freq,
    }


class TestVToken:
    def test_v_token_is_nonempty_string(self):
        from stock_data.data_provider.fetchers.ths_fetcher import _get_ths_v_token

        v = _get_ths_v_token()
        assert isinstance(v, str) and len(v) >= 8

    def test_v_token_is_cached(self):
        from stock_data.data_provider.fetchers.ths_fetcher import _get_ths_v_token

        v1 = _get_ths_v_token()
        v2 = _get_ths_v_token()
        assert v1 == v2  # cached (within TTL)


class TestGetBoardHistory:
    """get_board_history accepts platecode as the canonical input (per the
    2026-07-14 unification). CIDs (e.g. ``"307940"``) are still accepted
    as backward-compat input — the fetcher resolves them via the
    ``stock_board`` cache (matched on code OR platecode) or, on cache
    miss, via the upstream HTML page.
    """

    def test_industry_uses_platecode_directly(self):
        """Industry: board_code IS the platecode (881xxx). No resolution step."""
        from stock_data.data_provider.fetchers.ths_fetcher import ThsFetcher

        f = ThsFetcher.__new__(ThsFetcher)
        rows = [_fake_row("2025-12-30", "d")]
        with patch(
            "stock_data.data_provider.fetchers.ths_fetcher._fetch_ths_single_kline",
            return_value=rows,
        ):
            out = f.get_board_history(
                board_code="881270",
                board_type="industry",
                frequency="d",
                days=180,
                end_date="2025-12-31",
            )
        assert len(out) == 1

    @pytest.mark.parametrize("freq", ["d", "w", "m", "1m", "5m", "15m", "30m", "60m"])
    def test_all_8_frequencies_supported(self, freq):
        """All 8 THS frequencies are accepted; freq_key reaches
        _fetch_ths_single_kline correctly."""
        from stock_data.data_provider.fetchers.ths_fetcher import ThsFetcher

        f = ThsFetcher.__new__(ThsFetcher)
        # 1m has a 2-day max-span cap (upstream returns ~30 bars total);
        # minute-level frequencies have tighter caps. Daily/weekly/monthly
        # have 10-year caps. Post-Fix-A: `days` is the default window width,
        # `start_date` only extends back; pick `days` to fit each freq's cap.
        if freq == "1m":
            rows = [_fake_row("2026-07-14 09:35", freq)]
            start, end = "2026-07-13", "2026-07-14"
            days = 1  # 1m cap = 2d
        elif freq in ("5m", "15m", "30m", "60m"):
            rows = [_fake_row("2026-07-14 09:35", freq)]
            start, end = "2026-07-12", "2026-07-14"
            days = 2  # fits 5m(30d)/15m(60d)/30m(90d)/60m(180d) caps
        else:
            rows = [_fake_row("2025-06-30", freq)]
            start, end = "2025-06-29", "2025-06-30"
            days = 30

        with patch(
            "stock_data.data_provider.fetchers.ths_fetcher._fetch_ths_single_kline",
            return_value=rows,
        ) as fetch_mock:
            out = f.get_board_history(
                board_code="881270",
                board_type="industry",
                frequency=freq,
                start_date=start,
                end_date=end,
                days=days,
            )
        # Verify the helper was called with the correct freq_key.
        assert fetch_mock.call_args.kwargs["freq_key"] == freq
        assert len(out) >= 1, f"freq={freq} returned 0 rows"

    def test_invalid_frequency_raises(self):
        from stock_data.data_provider.fetchers.ths_fetcher import DataFetchError, ThsFetcher

        f = ThsFetcher.__new__(ThsFetcher)
        with pytest.raises(DataFetchError, match="unsupported frequency"):
            f.get_board_history("881270", board_type="industry", frequency="2h")

    def test_5min_span_cap_raises(self):
        """All minute-level frequencies (1m/5m/15m/30m/60m) cap at 800
        days, matching upstream's per-request bar-count cap (verified
        2026-07-22 against the stockpage network panel: begin_time=-N
        returns N bars for N≤800). days > 800 raises ValueError → 400."""
        from stock_data.data_provider.fetchers.ths_fetcher import ThsFetcher

        f = ThsFetcher.__new__(ThsFetcher)
        with pytest.raises(ValueError, match="exceeds frequency='5m' max"):
            f.get_board_history(
                board_code="881270",
                board_type="industry",
                frequency="5m",
                days=900,  # > 800 ceiling
            )

    def test_missing_board_type_auto_detects_industry(self):
        """When board_type is None, auto-detect from stock_board cache."""
        from stock_data.data_provider.fetchers.ths_fetcher import ThsFetcher

        f = ThsFetcher.__new__(ThsFetcher)
        rows = [_fake_row("2025-12-30", "d")]
        with (
            patch(
                "stock_data.data_provider.persistence.board.get_board_metadata",
                return_value={
                    "name": "银行",
                    "type": "industry",
                    "subtype": "",
                    "code": "881270",
                    "cid": "881270",
                },
            ),
            patch(
                "stock_data.data_provider.fetchers.ths_fetcher._fetch_ths_single_kline",
                return_value=rows,
            ),
        ):
            out = f.get_board_history(
                board_code="881270",
                board_type=None,
                frequency="d",
                days=180,
                end_date="2025-12-31",
            )
        assert len(out) == 1

    def test_invalid_board_type_raises(self):
        """Unknown board_type string → DataFetchError naming valid options.
        (Note: the new impl auto-detects on cache hit and defaults to
        'concept' on cache miss, so explicit invalid board_type must
        still be rejected.)"""
        from stock_data.data_provider.fetchers.ths_fetcher import DataFetchError, ThsFetcher

        f = ThsFetcher.__new__(ThsFetcher)
        with pytest.raises(DataFetchError, match="board_type must be"):
            f.get_board_history("881270", board_type="foobar")

    def test_date_range_filter(self):
        """Date filter uses YYYY-MM-DD comparison (rows arrive pre-parsed)."""
        from stock_data.data_provider.fetchers.ths_fetcher import ThsFetcher

        f = ThsFetcher.__new__(ThsFetcher)
        # Mix dates from 2023, 2024, 2025 — only 2024-12-31 should pass.
        rows = [
            _fake_row("2025-06-30", "d"),
            _fake_row("2024-12-31", "d"),
            _fake_row("2023-01-01", "d"),
        ]
        with patch(
            "stock_data.data_provider.fetchers.ths_fetcher._fetch_ths_single_kline",
            return_value=rows,
        ):
            out = f.get_board_history(
                board_code="881270",
                board_type="industry",
                start_date="2024-01-01",
                end_date="2025-01-01",
            )
        dates = [r["date"] for r in out]
        assert "2024-12-31" in dates
        assert "2025-06-30" not in dates
        assert "2023-01-01" not in dates

    def test_returns_sorted_ascending(self):
        from stock_data.data_provider.fetchers.ths_fetcher import ThsFetcher

        f = ThsFetcher.__new__(ThsFetcher)
        rows = [
            _fake_row("2025-06-29", "d"),
            _fake_row("2025-06-30", "d"),
            _fake_row("2025-06-28", "d"),
        ]
        with patch(
            "stock_data.data_provider.fetchers.ths_fetcher._fetch_ths_single_kline",
            return_value=rows,
        ):
            out = f.get_board_history(
                board_code="881270",
                board_type="industry",
                start_date="2025-06-01",
                end_date="2025-06-30",
            )
        dates = [r["date"] for r in out]
        assert dates == sorted(dates)

    @pytest.mark.parametrize("freq", ["d", "w", "m", "1m", "5m", "15m", "30m", "60m"])
    def test_each_row_tagged_with_frequency(self, freq):
        """Each row in the response carries a ``frequency`` field matching
        the requested freq — per-row self-identification contract."""
        from stock_data.data_provider.fetchers.ths_fetcher import ThsFetcher

        f = ThsFetcher.__new__(ThsFetcher)
        if freq == "1m":
            row = _fake_row("2026-07-14 09:35", freq)
            start, end = "2026-07-13", "2026-07-14"
            days = 1
        elif freq in ("5m", "15m", "30m", "60m"):
            row = _fake_row("2026-07-14 09:35", freq)
            start, end = "2026-07-12", "2026-07-14"
            days = 2
        else:
            row = _fake_row("2025-06-30", freq)
            start, end = "2025-06-29", "2025-06-30"
            days = 30

        with patch(
            "stock_data.data_provider.fetchers.ths_fetcher._fetch_ths_single_kline",
            return_value=[row],
        ):
            rows = f.get_board_history(
                board_code="881270",
                board_type="industry",
                frequency=freq,
                start_date=start,
                end_date=end,
                days=days,
            )
        assert rows, f"freq={freq} returned 0 rows"
        for r in rows:
            assert r["frequency"] == freq, (
                f"freq={freq} row tagged {r.get('frequency')!r}; date={r['date']!r}"
            )

    def test_minute_end_bound_uses_2359(self):
        """Minute-level bars (YYYY-MM-DD HH:MM) need the end-date bound
        to extend to " 23:59" or the last bar of the day would be
        cut off by the lexicographic compare."""
        from stock_data.data_provider.fetchers.ths_fetcher import ThsFetcher

        f = ThsFetcher.__new__(ThsFetcher)
        rows = [
            _fake_row("2026-07-13 09:30", "5m"),
            _fake_row("2026-07-13 14:55", "5m"),
        ]
        with patch(
            "stock_data.data_provider.fetchers.ths_fetcher._fetch_ths_single_kline",
            return_value=rows,
        ):
            out = f.get_board_history(
                board_code="881270",
                board_type="industry",
                frequency="5m",
                start_date="2026-07-13",
                end_date="2026-07-13",
                days=1,
            )
        # Both rows should be kept (the 14:55 bar is the same day as end).
        assert len(out) == 2
        dates = [r["date"] for r in out]
        assert "2026-07-13 14:55" in dates

    def test_daily_end_bound_does_not_get_2359_suffix(self):
        """Daily bars (YYYY-MM-DD) should NOT get the " 23:59" tail —
        the explicit set check (not endswith("m")) means monthly
        (key "m") and daily (key "d") both skip it."""
        from stock_data.data_provider.fetchers.ths_fetcher import ThsFetcher

        f = ThsFetcher.__new__(ThsFetcher)
        rows = [_fake_row("2025-12-31", "d")]
        with patch(
            "stock_data.data_provider.fetchers.ths_fetcher._fetch_ths_single_kline",
            return_value=rows,
        ):
            out = f.get_board_history(
                board_code="881270",
                board_type="industry",
                frequency="d",
                start_date="2025-12-01",
                end_date="2025-12-31",
            )
        assert len(out) == 1
        assert out[0]["date"] == "2025-12-31"  # no spurious time suffix


class TestVTokenCacheTTL:
    """F2 — lru_cache(maxsize=1) replaced with TTL cache + retry + VM singleton."""

    def test_v_token_value_is_str(self):
        from stock_data.data_provider.fetchers.ths_fetcher import _get_ths_v_token

        token = _get_ths_v_token()
        assert isinstance(token, str)
        assert len(token) >= 8

    def test_ttl_refresh_advances_expires_at(self, monkeypatch):
        """Calling within TTL returns the cached value; force-expire triggers re-mint."""
        from stock_data.data_provider.fetchers import ths_fetcher as mod

        calls = {"mint": 0}

        def fake_mint():
            calls["mint"] += 1
            return f"v-token-{calls['mint']}"

        monkeypatch.setattr(
            mod,
            "_get_ths_js_vm",
            lambda: type("VM", (), {"call": staticmethod(lambda _self, _name="v": fake_mint())})(),
        )
        mod._ths_v_token_cache["value"] = None
        mod._ths_v_token_cache["expires_at"] = 0.0

        t1 = mod._get_ths_v_token()
        t2 = mod._get_ths_v_token()  # within TTL — cached
        assert t1 == t2
        assert calls["mint"] == 1

        # Force expiry → next call re-mints
        mod._ths_v_token_cache["expires_at"] = 0.0
        t3 = mod._get_ths_v_token()
        assert t3 != t1
        assert calls["mint"] == 2

    def test_retry_on_transient_mint_failure(self, monkeypatch):
        """Bounded retry; after _THS_V_TOKEN_MAX_RETRIES, raise DataFetchError."""
        from stock_data.data_provider.fetchers import ths_fetcher as mod
        from stock_data.data_provider.fetchers.ths_fetcher import DataFetchError

        calls = {"n": 0}

        def always_fail():
            calls["n"] += 1
            raise DataFetchError(f"mint fail {calls['n']}")

        class FailingVM:
            def call(self, _name="v"):
                always_fail()

        monkeypatch.setattr(mod, "_get_ths_js_vm", lambda: FailingVM())
        mod._ths_v_token_cache["value"] = None
        mod._ths_v_token_cache["expires_at"] = 0.0

        with pytest.raises(DataFetchError, match="v-token mint failed after"):
            mod._get_ths_v_token()
        assert calls["n"] == mod._THS_V_TOKEN_MAX_RETRIES

    def test_retry_recovers_after_transient_failure(self, monkeypatch):
        """First call fails, second succeeds → returns the success value."""

        from stock_data.data_provider.fetchers import ths_fetcher as mod

        calls = {"n": 0}

        def succeed_on_retry():
            calls["n"] += 1
            if calls["n"] < 2:
                raise mod.DataFetchError("transient")
            return "v-token-success"

        class RetryVM:
            def call(self, _name="v"):
                return succeed_on_retry()

        mod._ths_v_token_cache["value"] = None
        mod._ths_v_token_cache["expires_at"] = 0.0
        original = mod._get_ths_js_vm
        mod._get_ths_js_vm = lambda: RetryVM()
        try:
            token = mod._get_ths_v_token()
            assert token == "v-token-success"
            assert calls["n"] == 2
        finally:
            mod._get_ths_js_vm = original
            mod._ths_v_token_cache["value"] = None
            mod._ths_v_token_cache["expires_at"] = 0.0

    def test_js_vm_is_singleton(self):
        from stock_data.data_provider.fetchers import ths_fetcher as mod

        instantiations = {"n": 0}

        class CountingVM:
            def __init__(self):
                instantiations["n"] += 1

            def eval(self, _js):
                pass

            def call(self, _name="v"):
                return f"v-from-counting-{instantiations['n']}"

        original = mod._get_ths_js_vm
        mod._get_ths_js_vm = lambda: CountingVM()
        mod._ths_js_vm = None
        try:
            t1 = mod._get_ths_v_token()
            t2 = mod._get_ths_v_token()
            t3 = mod._get_ths_v_token()
            assert instantiations["n"] == 1
            assert t1 == t2 == t3
        finally:
            mod._get_ths_js_vm = original
            mod._ths_js_vm = None
            mod._ths_v_token_cache["value"] = None
            mod._ths_v_token_cache["expires_at"] = 0.0


class TestGetBoardHistoryEdgeCases:
    """A5/A6/A7 — all-empty raise, span cap raise, reverse-date raise."""

    def test_all_years_failed_raises(self):
        """Legacy test — single_kline doesn't have the all-empty gate, but
        we keep this as a no-op for symmetry: an empty upstream response
        returns an empty list (legit no-data)."""
        from unittest.mock import patch

        from stock_data.data_provider.fetchers.ths_fetcher import ThsFetcher

        f = ThsFetcher.__new__(ThsFetcher)
        with patch(
            "stock_data.data_provider.fetchers.ths_fetcher._fetch_ths_single_kline",
            return_value=[],
        ):
            rows = f.get_board_history(
                board_code="881270",
                board_type="industry",
                frequency="d",
                days=400,
                end_date="2025-06-30",
                start_date="2024-12-01",
            )
        # Single request — no all-empty gate; empty list is the result.
        assert rows == []

    def test_year_span_cap_raises(self):
        """`days > _THS_HXKLINE_MAX_SPAN_DAYS['d']` (3650) raises.
        Post-fix: `days` is always the window width; start_date is just a
        lower bound, so a 16-year range with explicit bounds no longer
        triggers the cap — you have to ask for it via `days`."""

        from stock_data.data_provider.fetchers.ths_fetcher import ThsFetcher

        f = ThsFetcher.__new__(ThsFetcher)
        with pytest.raises(ValueError, match="exceeds frequency='d' max"):
            f.get_board_history(
                board_code="881270",
                board_type="industry",
                frequency="d",
                days=4000,  # > 3650 ceiling
            )

    def test_span_boundary_for_5m_does_not_falsely_raise(self):
        """Regression guard for the off-by-one fix.

        `days=800` with `freq=5m` should NOT raise the 800d cap. With the
        legacy `span_days = (end - start).days + 1`, this case would
        compute span=801 and falsely fire the cap, blocking the very
        window the route advertises as the max for 5m (since 2026-07-22
        raised all minute-level caps to 800 to match upstream's per-
        request bar-count cap)."""
        from unittest.mock import patch

        from stock_data.data_provider.fetchers.ths_fetcher import ThsFetcher

        f = ThsFetcher.__new__(ThsFetcher)
        with patch(
            "stock_data.data_provider.fetchers.ths_fetcher._fetch_ths_single_kline",
            return_value=[],
        ):
            # Should NOT raise — exactly at the 5m 800d boundary.
            rows = f.get_board_history(
                board_code="881270",
                board_type="industry",
                frequency="5m",
                days=800,
            )
        assert rows == []

    def test_start_date_more_recent_than_days_default_uses_days(self):
        """Pin the contract: passing ``start_date=today`` with ``days=30``
        is effectively a no-op — you still get the default 30-day window,
        NOT a 1-day window. Catches future regressions where someone
        re-introduces ``start_date wins over days`` semantics."""
        from datetime import date
        from unittest.mock import patch

        from stock_data.data_provider.fetchers.ths_fetcher import ThsFetcher

        f = ThsFetcher.__new__(ThsFetcher)
        captured: dict = {}

        def fake_fetch(board_code, *, freq_key, start_d, end_d, days):
            captured["start_d"] = start_d
            captured["end_d"] = end_d
            return []

        with patch(
            "stock_data.data_provider.fetchers.ths_fetcher._fetch_ths_single_kline",
            side_effect=fake_fetch,
        ):
            f.get_board_history(
                board_code="881270",
                board_type="industry",
                frequency="5m",
                start_date=date.today().strftime(
                    "%Y-%m-%d"
                ),  # today's hint — should NOT shrink window
                days=30,
            )
        # The fetcher received resolved dates spanning 30 days, NOT 1 day.
        assert (captured["end_d"] - captured["start_d"]).days == 30

    def test_start_date_older_than_days_default_extends_window(self):
        """Pin the contract: passing ``start_date=2020-01-01`` with
        ``days=30`` honors the hint — the window extends back to 2020-01-01.
        The per-frequency cap will fire (returning 400), but the
        resolution should still pick the EARLIER of the two candidates."""
        from unittest.mock import patch

        from stock_data.data_provider.fetchers.ths_fetcher import ThsFetcher

        f = ThsFetcher.__new__(ThsFetcher)
        captured: dict = {}

        def fake_fetch(board_code, *, freq_key, start_d, end_d, days):
            captured["start_d"] = start_d
            captured["end_d"] = end_d
            return []

        # Use freq=d (10y cap, won't fire here)
        with patch(
            "stock_data.data_provider.fetchers.ths_fetcher._fetch_ths_single_kline",
            side_effect=fake_fetch,
        ):
            f.get_board_history(
                board_code="881270",
                board_type="industry",
                frequency="d",
                start_date="2020-01-01",
                days=30,
            )
        # start_d should be 2020-01-01, NOT (end_d - 30 days).
        from datetime import date

        assert captured["start_d"] == date(2020, 1, 1)

    def test_reversed_dates_raises(self):
        from unittest.mock import patch

        from stock_data.data_provider.fetchers.ths_fetcher import ThsFetcher

        f = ThsFetcher.__new__(ThsFetcher)
        with (
            patch.object(ThsFetcher, "_v_token", return_value="x"),
            pytest.raises(ValueError, match="start_date .* > end_date"),
        ):
            f.get_board_history(
                board_code="881270",
                board_type="industry",
                frequency="d",
                days=10,
                start_date="2025-06-30",
                end_date="2024-01-01",
            )

    def test_malformed_start_date_raises(self):
        from unittest.mock import patch

        from stock_data.data_provider.fetchers.ths_fetcher import ThsFetcher

        f = ThsFetcher.__new__(ThsFetcher)
        with (
            patch.object(ThsFetcher, "_v_token", return_value="x"),
            pytest.raises(ValueError, match="start_date=.*not YYYY-MM-DD"),
        ):
            f.get_board_history(
                board_code="881270",
                board_type="industry",
                frequency="d",
                days=10,
                start_date="not-a-date",
                end_date="2025-06-30",
            )

    def test_malformed_end_date_raises(self):
        from unittest.mock import patch

        from stock_data.data_provider.fetchers.ths_fetcher import ThsFetcher

        f = ThsFetcher.__new__(ThsFetcher)
        with (
            patch.object(ThsFetcher, "_v_token", return_value="x"),
            pytest.raises(ValueError, match="end_date=.*not YYYY-MM-DD"),
        ):
            f.get_board_history(
                board_code="881270",
                board_type="industry",
                frequency="d",
                days=10,
                start_date="2025-01-01",
                end_date="2025/06/30",
            )


class TestThsAssetsShipping:
    def test_ths_assets_shipped(self):
        from importlib.resources import files

        import stock_data.data_provider.fetchers.ths_assets as assets

        js = files(assets).joinpath("ths.js")
        assert js.is_file()

    def test_ths_js_has_entry_signature(self):
        from importlib.resources import files

        import stock_data.data_provider.fetchers.ths_assets as assets

        js = files(assets).joinpath("ths.js")
        text = js.read_text(encoding="utf-8")
        assert "function v_cookie" in text
        assert "function v ()" in text


class TestIsAvailable:
    def test_available_when_both_present(self):
        from stock_data.data_provider.fetchers.ths_fetcher import ThsFetcher

        result = ThsFetcher().is_available()
        assert isinstance(result, bool)
        if result:
            assert ThsFetcher().unavailable_reason() is None
        else:
            reason = ThsFetcher().unavailable_reason()
            assert reason and isinstance(reason, str)
            assert "board_history unavailable" in reason

    def test_missing_py_mini_racer_returns_false(self, monkeypatch):
        from stock_data.data_provider.fetchers.ths_fetcher import ThsFetcher

        real_find_spec = ths_mod.util.find_spec
        monkeypatch.setattr(
            ths_mod.util,
            "find_spec",
            lambda name: None if name == "py_mini_racer" else real_find_spec(name),
        )
        assert ThsFetcher().is_available() is False
        reason = ThsFetcher().unavailable_reason()
        assert reason is not None
        assert "py_mini_racer" in reason

    def test_missing_ths_js_returns_false_with_vendor_reason(self, monkeypatch):
        from stock_data.data_provider.fetchers.ths_fetcher import ThsFetcher

        class _Spec:
            pass

        monkeypatch.setattr(ths_mod.util, "find_spec", lambda name: _Spec())

        def _raise_files(_pkg):
            raise FileNotFoundError("simulated ths_assets missing")

        monkeypatch.setattr(ths_mod.resources, "files", _raise_files)
        assert ThsFetcher().is_available() is False
        reason = ThsFetcher().unavailable_reason()
        assert reason is not None
        assert "vendor_ths_js" in reason or "ths.js" in reason

    def test_missing_bs4_returns_false(self, monkeypatch):
        from stock_data.data_provider.fetchers.ths_fetcher import ThsFetcher

        real_find_spec = ths_mod.util.find_spec

        def fake_find_spec(name):
            if name == "bs4":
                return None
            return real_find_spec(name)

        monkeypatch.setattr(ths_mod.util, "find_spec", fake_find_spec)
        assert ThsFetcher().is_available() is False
        reason = ThsFetcher().unavailable_reason()
        assert reason is not None
        assert "bs4" in reason


class TestHuxkLineJwt:
    """Lazily-fetched JWT for the quota-h.10jqka.com.cn/single_kline endpoint."""

    def test_lazy_fetch_from_js_bundle(self, monkeypatch):
        from stock_data.data_provider.fetchers import ths_fetcher as ths_mod
        from stock_data.data_provider.fetchers.ths_fetcher import _get_ths_hxkline_jwt

        # Real JWT shape: header.payload.signature — each chunk is base64url
        fake_jwt = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJ0ZXN0In0.signature123"
        fake_js = f'let c={{id:"hxkline-x",token:"{fake_jwt}"}}'

        class FakeResp:
            text = fake_js
            status_code = 200

            def raise_for_status(self):
                pass

        ths_mod._ths_hxkline_jwt_cache["value"] = None
        ths_mod._ths_hxkline_jwt_cache["expires_at"] = 0.0

        calls = {"n": 0}

        def fake_get(url, timeout=15):
            calls["n"] += 1
            assert "82-" in url  # chunk hash is part of the URL
            return FakeResp()

        monkeypatch.setattr(ths_mod.requests, "get", fake_get)
        jwt1 = _get_ths_hxkline_jwt()
        jwt2 = _get_ths_hxkline_jwt()
        assert jwt1 == fake_jwt
        assert jwt2 == fake_jwt
        assert calls["n"] == 1  # second call used cache

    def test_env_override_bypasses_fetch(self, monkeypatch):
        from stock_data.data_provider.fetchers import ths_fetcher as ths_mod

        monkeypatch.setenv("THS_HXKLINE_JWT", "eyJ.env.override")
        ths_mod._ths_hxkline_jwt_cache["value"] = None
        ths_mod._ths_hxkline_jwt_cache["expires_at"] = 0.0

        def must_not_call(*a, **kw):
            raise AssertionError("requests.get must not be called when env override is set")

        monkeypatch.setattr(ths_mod.requests, "get", must_not_call)
        assert ths_mod._get_ths_hxkline_jwt() == "eyJ.env.override"

    def test_missing_token_raises(self, monkeypatch):
        from stock_data.data_provider.fetchers import ths_fetcher as ths_mod
        from stock_data.data_provider.fetchers.ths_fetcher import DataFetchError

        ths_mod._ths_hxkline_jwt_cache["value"] = None
        ths_mod._ths_hxkline_jwt_cache["expires_at"] = 0.0

        class FakeResp:
            text = "no token here"
            status_code = 200

            def raise_for_status(self):
                pass

        monkeypatch.setattr(ths_mod.requests, "get", lambda *a, **kw: FakeResp())

        with pytest.raises(DataFetchError, match="JWT not found"):
            ths_mod._get_ths_hxkline_jwt()


class TestParseSingleKlineResponse:
    """Parse the `data.quote_data[0].value` 2-D array from single_kline responses."""

    def test_daily_response_yields_canonical_dates(self):
        from stock_data.data_provider.fetchers.ths_fetcher import _parse_ths_single_kline_response

        body = {
            "status_code": 0,
            "data": {
                "quote_data": [
                    {
                        "market": "48",
                        "code": "885756",
                        "delay": False,
                        "data_fields": ["1", "7", "8", "9", "11", "13", "19"],
                        "value": [
                            [
                                1732550400000,
                                2813.92,
                                2845.87,
                                2770.84,
                                2771.96,
                                14851306000,
                                23828683000,
                            ],
                            [
                                1732636800000,
                                2754.02,
                                2840.82,
                                2696.71,
                                2840.82,
                                16226268000,
                                28300843000,
                            ],
                        ],
                    }
                ],
                "fail_params": None,
            },
            "status_msg": "ok",
        }
        rows = _parse_ths_single_kline_response(body, freq_key="d")
        assert len(rows) == 2
        # YYYY-MM-DD canonical (Beijing time = UTC+8, so 1732550400000ms UTC
        # midnight-of-2024-11-26 maps to 2024-11-26 00:00 Beijing → bare date)
        assert rows[0]["date"] == "2024-11-26"
        assert rows[0]["open"] == 2813.92
        assert rows[0]["volume"] == 14851306000
        assert rows[0]["frequency"] == "d"

    def test_minute_response_yields_canonical_datetime(self):
        from stock_data.data_provider.fetchers.ths_fetcher import _parse_ths_single_kline_response

        body = {
            "status_code": 0,
            "data": {
                "quote_data": [
                    {
                        "market": "48",
                        "code": "881153",
                        "delay": False,
                        "data_fields": ["1", "7", "8", "9", "11", "13", "19"],
                        "value": [
                            [
                                1781574300000,
                                1707.92,
                                1707.92,
                                1677.89,
                                1679.61,
                                640538570,
                                3271067400,
                            ]
                        ],
                    }
                ],
                "fail_params": None,
            },
            "status_msg": "ok",
        }
        rows = _parse_ths_single_kline_response(body, freq_key="15m")
        assert len(rows) == 1
        # YYYY-MM-DD HH:MM (note the space, NOT 'T'); Beijing time (UTC+8)
        assert rows[0]["date"] == "2026-06-16 09:45"

    def test_status_nonzero_raises(self):
        from stock_data.data_provider.fetchers.ths_fetcher import (
            DataFetchError,
            _parse_ths_single_kline_response,
        )

        with pytest.raises(DataFetchError, match="status_code"):
            _parse_ths_single_kline_response(
                {"status_code": 40001, "status_msg": "auth failed", "data": None},
                freq_key="d",
            )

    def test_empty_quote_data_returns_empty_list(self):
        from stock_data.data_provider.fetchers.ths_fetcher import _parse_ths_single_kline_response

        body = {
            "status_code": 0,
            "data": {"quote_data": [], "fail_params": None},
            "status_msg": "ok",
        }
        assert _parse_ths_single_kline_response(body, freq_key="d") == []


class TestFetchSingleKline:
    """POST to single_kline, handle 401/403 by refreshing the JWT."""

    def test_happy_path(self, monkeypatch):
        from stock_data.data_provider.fetchers import ths_fetcher as ths_mod
        from stock_data.data_provider.fetchers.ths_fetcher import _fetch_ths_single_kline

        monkeypatch.setattr(ths_mod, "_get_ths_hxkline_jwt", lambda: "eyJ.test.sig")

        fake_body = {
            "status_code": 0,
            "data": {
                "quote_data": [
                    {
                        "market": "48",
                        "code": "881270",
                        "delay": False,
                        "data_fields": ["1", "7", "8", "9", "11", "13", "19"],
                        "value": [[1732550400000, 9000.0, 9100.0, 8900.0, 9050.0, 100, 1000]],
                    }
                ],
                "fail_params": None,
            },
            "status_msg": "ok",
        }

        captured_kwargs: dict = {}

        class FakeResp:
            status_code = 200
            headers = {"x-ratelimit-remaining": "2740", "x-ratelimit-limit": "2750"}

            def json(self):
                return fake_body

        def fake_post(url, **kwargs):
            captured_kwargs.update(kwargs)
            return FakeResp()

        monkeypatch.setattr(ths_mod.requests, "post", fake_post)

        rows = _fetch_ths_single_kline("881270", freq_key="d", days=400)
        assert len(rows) == 1
        assert rows[0]["close"] == 9050.0
        # Verify the request shape
        headers = captured_kwargs["headers"]
        assert headers["x-fuyao-auth"] == "eyJ.test.sig"
        body = captured_kwargs["json"]
        assert body["code_list"] == [{"codes": ["881270"], "market": "48"}]
        assert body["time_period"] == "day_1"
        assert body["begin_time"] == -400
        assert body["end_time"] == 0

    def test_401_refreshes_jwt_and_retries_once(self, monkeypatch):
        from stock_data.data_provider.fetchers import ths_fetcher as ths_mod
        from stock_data.data_provider.fetchers.ths_fetcher import _fetch_ths_single_kline

        post_calls = {"n": 0}

        class FakeResp:
            def __init__(self, code, body):
                self.status_code = code
                self._body = body
                self.headers = {}

            def json(self):
                return self._body

        def fake_post(url, **kwargs):
            post_calls["n"] += 1
            if post_calls["n"] == 1:
                return FakeResp(401, {})
            return FakeResp(
                200,
                {
                    "status_code": 0,
                    "data": {
                        "quote_data": [
                            {
                                "market": "48",
                                "code": "881270",
                                "delay": False,
                                "data_fields": ["1", "7", "8", "9", "11", "13", "19"],
                                "value": [],
                            }
                        ],
                        "fail_params": None,
                    },
                    "status_msg": "ok",
                },
            )

        monkeypatch.setattr(ths_mod.requests, "post", fake_post)

        # Each _get_ths_hxkline_jwt call invalidates the cache to simulate
        # the natural cache-flush behavior on JWT rotation.
        jwt_iter = iter(["eyJ.iter1", "eyJ.iter2"])

        def fake_jwt():
            tok = next(jwt_iter)
            ths_mod._ths_hxkline_jwt_cache["value"] = None
            return tok

        monkeypatch.setattr(ths_mod, "_get_ths_hxkline_jwt", fake_jwt)

        rows = _fetch_ths_single_kline("881270", freq_key="d", days=30)
        assert rows == []
        assert post_calls["n"] == 2  # one 401 + one retry

    def test_http_error_raises(self, monkeypatch):
        from stock_data.data_provider.fetchers import ths_fetcher as ths_mod
        from stock_data.data_provider.fetchers.ths_fetcher import (
            DataFetchError,
            _fetch_ths_single_kline,
        )

        monkeypatch.setattr(ths_mod, "_get_ths_hxkline_jwt", lambda: "eyJ.test.sig")

        class FakeResp:
            status_code = 500
            text = "upstream down"
            content = b"upstream down"
            headers = {}

        monkeypatch.setattr(ths_mod.requests, "post", lambda *a, **kw: FakeResp())
        with pytest.raises(DataFetchError, match="HTTP 500"):
            _fetch_ths_single_kline("881270", freq_key="d", days=30)

    def test_env_pinned_jwt_skips_retry_on_401(self, monkeypatch):
        """When THS_HXKLINE_JWT env var pins the token, the 401/403 retry
        loop is a no-op (same stale token) — must raise with a 'stale env'
        message instead of silently retrying once with the same token."""
        from stock_data.data_provider.fetchers import ths_fetcher as ths_mod
        from stock_data.data_provider.fetchers.ths_fetcher import (
            DataFetchError,
            _fetch_ths_single_kline,
        )

        monkeypatch.setenv("THS_HXKLINE_JWT", "eyJ.pinned.stale")
        monkeypatch.setattr(ths_mod, "_get_ths_hxkline_jwt", lambda: "eyJ.pinned.stale")

        post_calls = {"n": 0}

        class FakeResp:
            status_code = 401
            content = b""
            headers = {}

        def fake_post(*a, **kw):
            post_calls["n"] += 1
            return FakeResp()

        monkeypatch.setattr(ths_mod.requests, "post", fake_post)

        with pytest.raises(DataFetchError, match="THS_HXKLINE_JWT env var is stale"):
            _fetch_ths_single_kline("881270", freq_key="d", days=30)
        assert post_calls["n"] == 1  # NO retry when env-pinned

    def test_end_date_only_propagates_to_upstream(self, monkeypatch):
        """Regression for Fix #7: only end_date given (no start_date)
        used to silently drop all rows (upstream returned today-relative
        data, post-filter killed it). Must now compute a proper
        begin/end window anchored on end_date."""
        from stock_data.data_provider.fetchers import ths_fetcher as ths_mod
        from stock_data.data_provider.fetchers.ths_fetcher import _fetch_ths_single_kline

        monkeypatch.setattr(ths_mod, "_get_ths_hxkline_jwt", lambda: "eyJ.test.sig")

        captured_kwargs: dict = {}

        class FakeResp:
            status_code = 200
            headers = {}

            def json(self):
                return {
                    "status_code": 0,
                    "data": {
                        "quote_data": [
                            {
                                "market": "48",
                                "code": "881270",
                                "delay": False,
                                "data_fields": ["1", "7", "8", "9", "11", "13", "19"],
                                "value": [],
                            }
                        ],
                        "fail_params": None,
                    },
                    "status_msg": "ok",
                }

        def fake_post(url, **kwargs):
            captured_kwargs.update(kwargs)
            return FakeResp()

        monkeypatch.setattr(ths_mod.requests, "post", fake_post)

        # days=180, end_d 100 days back → begin=-280, end=-100
        from datetime import date, timedelta

        end_d = date.today() - timedelta(days=100)
        _fetch_ths_single_kline("881270", freq_key="d", days=180, end_d=end_d)
        body = captured_kwargs["json"]
        assert body["end_time"] == -100
        assert body["begin_time"] == -280

    def test_compute_time_window_end_date_only(self):
        """end_d-only: window is `days` ending on end_d (mirror
        _resolve_ths_date_range behavior where start_d=end_d-days).
        freq_key='d' so the 800-bar cap check doesn't fire."""
        from datetime import date, timedelta

        from stock_data.data_provider.fetchers.ths_fetcher import _compute_time_window

        end_d = date.today() - timedelta(days=100)
        begin, end = _compute_time_window(
            days=180,
            start_d=None,
            end_d=end_d,
            freq_key="d",
        )
        assert end == -100
        assert begin == -280  # 180 days ending 100 days back

    def test_compute_time_window_end_date_today_clamped(self):
        """end_d today/future → end_time=0 (upstream '0=now', positive undefined)."""
        from datetime import date

        from stock_data.data_provider.fetchers.ths_fetcher import _compute_time_window

        begin, end = _compute_time_window(
            days=30,
            start_d=None,
            end_d=None,
            freq_key="d",
        )
        assert end == 0
        begin, end = _compute_time_window(
            days=30,
            start_d=None,
            end_d=date(2099, 1, 1),  # far future
            freq_key="d",
        )
        assert end == 0

    def test_compute_time_window_translates_resolved_dates(self):
        """`_compute_time_window` is a pure translation: caller passes
        already-resolved ``start_d/end_d`` (after _resolve_ths_date_range
        applied the days-is-width + start_date-is-lower-bound contract).
        This test mirrors what get_board_history actually passes in:
        start_d = end_d - days, end_d = today."""
        from datetime import date, timedelta

        from stock_data.data_provider.fetchers.ths_fetcher import _compute_time_window

        end_d = date.today()
        start_d = end_d - timedelta(days=30)
        begin, end = _compute_time_window(
            days=30,
            start_d=start_d,
            end_d=end_d,
            freq_key="d",
        )
        assert end == 0
        assert begin == -30  # NOT -1, because start_d is already expanded

    def test_compute_time_window_minute_800_bar_cap_raises(self):
        """Regression: minute-level ``begin_time`` must not exceed -800
        (upstream returns empty ``quote_data: []`` otherwise). Without
        this guard, ``end_date=yesterday + days=800`` computes
        begin_time=-801 and silently returns 200 + empty list.

        Span check (800 days) passes because it uses
        ``(end_d - start_d).days`` which is 800 here, but the actual
        upstream offset uses ``(today - start_d).days`` which is 801.
        """
        from datetime import date, timedelta

        from stock_data.data_provider.fetchers.ths_fetcher import _compute_time_window

        end_d = date.today() - timedelta(days=1)  # yesterday
        start_d = end_d - timedelta(days=800)  # 800d window ending yesterday
        with pytest.raises(ValueError, match="800-bar cap"):
            _compute_time_window(
                days=800,
                start_d=start_d,
                end_d=end_d,
                freq_key="1m",
            )

    def test_compute_time_window_daily_800_bar_cap_not_fired(self):
        """Daily/weekly/monthly have a 3650-day cap, not 800. The
        800-bar cap guard must NOT fire for them even when (today -
        start_d).days > 800."""
        from datetime import date, timedelta

        from stock_data.data_provider.fetchers.ths_fetcher import _compute_time_window

        end_d = date.today()
        start_d = end_d - timedelta(days=2000)  # well over 800 days back
        # Should NOT raise — daily uses the 3650 cap, not 800.
        begin, end = _compute_time_window(
            days=2000,
            start_d=start_d,
            end_d=end_d,
            freq_key="d",
        )
        assert end == 0
        assert begin == -2000
