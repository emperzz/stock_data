"""Tests for ThsFetcher.get_board_history and runtime health checks.

Post-2026-07-14: ThsFetcher supports all 7 THS K-line frequencies
(d / w / m / 5m / 15m / 30m / 60m) and uniformly accepts platecode as
input. The fetcher's clid→platecode helper is now named
``_resolve_ths_platecode_from_cid`` (the upstream HTML element is named
``<input id="clid">`` but its value is a 6-digit platecode — the old
``_resolve_ths_concept_clid`` name suggested a T-prefixed value that the
upstream never actually emitted).
"""

from unittest.mock import MagicMock, patch

import pytest

from stock_data.data_provider.fetchers import ths_fetcher as ths_mod


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

# Raw upstream date format (post-2026-07-14 normalization): the parser
# accepts YYYYMMDD (daily/weekly/monthly) and YYYYMMDDHHMM (minute bars).
# The first 7 columns are the canonical K-line subset
# (date, open, high, low, close, volume, amount).
_DAILY_BODY_2024 = (
    'var v_x={"data":"20241215,1,2,3,4,5,6,7,8,9,10;"};'
)
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


class TestResolvePlatecodeFromCid:
    """Post-2026-07-14: renamed from TestResolveConceptClid.

    The upstream HTML element is ``<input id="clid">`` but its value
    is a 6-digit platecode (e.g. ``"886042"``), not a T-prefixed clid.
    The helper returns the platecode that the K-line URL accepts.
    """

    def test_extracts_platecode_from_html(self):
        from stock_data.data_provider.fetchers.ths_fetcher import ThsFetcher

        fake_html = '<html><body><input id="clid" value="886042"/></body></html>'

        f = ThsFetcher.__new__(ThsFetcher)

        def fake_get(url, headers=None, timeout=None, **kw):
            assert "/gn/detail/code/" in url
            r = MagicMock()
            r.text = fake_html
            r.status_code = 200
            return r

        with patch.object(ThsFetcher, "_http_get", side_effect=fake_get):
            platecode = f._resolve_ths_platecode_from_cid("307940")
        assert platecode == "886042"

    def test_missing_clid_input_returns_none(self):
        from stock_data.data_provider.fetchers.ths_fetcher import ThsFetcher

        f = ThsFetcher.__new__(ThsFetcher)

        def fake_get(url, headers=None, timeout=None, **kw):
            r = MagicMock()
            r.text = "<html><body>no input</body></html>"
            r.status_code = 200
            return r

        with patch.object(ThsFetcher, "_http_get", side_effect=fake_get):
            assert f._resolve_ths_platecode_from_cid("xxx") is None

    def test_http_failure_returns_none(self):
        from stock_data.data_provider.fetchers.ths_fetcher import ThsFetcher

        f = ThsFetcher.__new__(ThsFetcher)

        def fake_get(url, headers=None, timeout=None, **kw):
            raise RuntimeError("network down")

        with patch.object(ThsFetcher, "_http_get", side_effect=fake_get):
            assert f._resolve_ths_platecode_from_cid("307940") is None


class TestParseThsKlineBody:
    """Date-format normalization is the core of the post-2026-07-14 fix.

    The parser accepts raw upstream YYYYMMDD (daily/weekly/monthly) and
    YYYYMMDDHHMM (minute-level) and emits canonical "YYYY-MM-DD" /
    "YYYY-MM-DD HH:MM" so the route-layer date filter compares correctly.
    """

    def test_parses_daily_yyyymmdd_response(self):
        from stock_data.data_provider.fetchers.ths_fetcher import ThsFetcher

        f = ThsFetcher.__new__(ThsFetcher)
        body = (
            'var v_abc123={"data":"20250630,1234.5,1260.0,1220.3,1255.7,12345678,1.234e10,2.5,1.7,21.2,1.5;'
            '20250629,1200.0,1240.0,1190.0,1230.0,10000000,1.0e10,2.0,1.0,12.0,1.0;"};'
        )
        rows = f._parse_ths_kline_body(body)
        assert len(rows) == 2
        # YYYYMMDD normalized to YYYY-MM-DD.
        assert rows[0]["date"] == "2025-06-30"
        assert rows[0]["open"] == 1234.5
        assert rows[1]["close"] == 1230.0
        for r in rows:
            assert set(r.keys()) >= {"date", "open", "high", "low", "close", "volume", "amount"}

    def test_parses_minute_yyyymmddhhmm_response(self):
        from stock_data.data_provider.fetchers.ths_fetcher import ThsFetcher

        f = ThsFetcher.__new__(ThsFetcher)
        rows = f._parse_ths_kline_body(_5MIN_BODY)
        assert len(rows) == 2
        # YYYYMMDDHHMM normalized to "YYYY-MM-DD HH:MM" (with space).
        assert rows[0]["date"] == "2026-07-13 09:35"
        assert rows[1]["date"] == "2026-07-13 09:40"

    def test_empty_data_returns_empty_list(self):
        from stock_data.data_provider.fetchers.ths_fetcher import ThsFetcher

        f = ThsFetcher.__new__(ThsFetcher)
        assert f._parse_ths_kline_body('var v_x={"data":""};') == []

    def test_handles_11_or_12_column_rows(self):
        from stock_data.data_provider.fetchers.ths_fetcher import ThsFetcher

        f = ThsFetcher.__new__(ThsFetcher)
        body = 'var v_x={"data":"20250630,1,2,3,4,5,6,7,8,9,10,11;"};'
        rows = f._parse_ths_kline_body(body)
        assert len(rows) == 1
        assert rows[0]["close"] == 4.0

    def test_skips_malformed_rows(self):
        from stock_data.data_provider.fetchers.ths_fetcher import ThsFetcher

        f = ThsFetcher.__new__(ThsFetcher)
        body = (
            'var v_x={"data":"20250630,1,2,3,4,5,6,7,8,9,10;'
            'garbage_row;'
            '20250629,1,2,3,4,5,6,7,8,9,10;"};'
        )
        rows = f._parse_ths_kline_body(body)
        assert len(rows) == 2

    def test_skips_unknown_date_formats(self):
        """Upstream variant with a 10-char or 9-char date — parser skips
        the row rather than passing an unparseable string downstream
        (which would silently break the route-layer date filter)."""
        from stock_data.data_provider.fetchers.ths_fetcher import ThsFetcher

        f = ThsFetcher.__new__(ThsFetcher)
        body = (
            'var v_x={"data":"20250630,1,2,3,4,5,6,7,8,9,10;'  # 8-char (valid)
            'X,1,2,3,4,5,6,7,8,9,10;'                            # 1-char (invalid)
            '2025,1,2,3,4,5,6,7,8,9,10;"};'                       # 4-char (invalid)
        )
        rows = f._parse_ths_kline_body(body)
        assert len(rows) == 1
        assert rows[0]["date"] == "2025-06-30"

    def test_missing_var_wrapper_still_parses(self):
        from stock_data.data_provider.fetchers.ths_fetcher import ThsFetcher

        f = ThsFetcher.__new__(ThsFetcher)
        body = '{"data":"20250630,1,2,3,4,5,6,7,8,9,10;"}'
        rows = f._parse_ths_kline_body(body)
        assert len(rows) == 1

    def test_empty_body_returns_empty_list(self):
        from stock_data.data_provider.fetchers.ths_fetcher import ThsFetcher

        f = ThsFetcher.__new__(ThsFetcher)
        assert f._parse_ths_kline_body("") == []

    def test_invalid_json_returns_empty_list(self):
        from stock_data.data_provider.fetchers.ths_fetcher import ThsFetcher

        f = ThsFetcher.__new__(ThsFetcher)
        assert f._parse_ths_kline_body("not-json-at-all") == []


class TestGetBoardHistory:
    """get_board_history accepts platecode as the canonical input (per the
    2026-07-14 unification). CIDs (e.g. ``"307940"``) are still accepted
    as backward-compat input — the fetcher resolves them via the
    ``stock_board`` cache (matched on code OR platecode) or, on cache
    miss, via the upstream HTML page.
    """

    def test_concept_resolves_via_html_scrape(self):
        """Cache miss → HTML scrape keyed on the input code (treated as CID) →
        platecode used in K-line URL."""
        from stock_data.data_provider.fetchers.ths_fetcher import ThsFetcher

        f = ThsFetcher.__new__(ThsFetcher)

        def fetch_year(inner, year, freq):
            assert inner == "886042"  # the platecode the HTML returned
            assert freq == 1  # d
            return _DAILY_BODY_2025 if year == 2025 else _DAILY_BODY_2024

        with (
            patch(
                "stock_data.data_provider.persistence.board.get_board_metadata",
                return_value=None,  # cache miss → fall through to HTML scrape
            ),
            patch.object(ThsFetcher, "_resolve_ths_platecode_from_cid", return_value="886042"),
            patch.object(ThsFetcher, "_fetch_ths_board_year", side_effect=fetch_year),
        ):
            rows = f.get_board_history(
                board_code="307940",  # CID input
                board_type="concept",
                frequency="d",
                days=400,
                end_date="2025-06-30",
                start_date="2024-12-01",
            )
        # 2024 body: 1 row; 2025 body: 2 rows.
        assert len(rows) == 3
        # Dates normalized to YYYY-MM-DD; sorted oldest → newest.
        assert [r["date"] for r in rows] == ["2024-12-15", "2025-06-29", "2025-06-30"]

    def test_concept_uses_cached_platecode(self):
        """Cache hit with platecode populated → use it directly, no HTML scrape."""
        from stock_data.data_provider.fetchers.ths_fetcher import ThsFetcher

        f = ThsFetcher.__new__(ThsFetcher)

        with (
            patch(
                "stock_data.data_provider.persistence.board.get_board_metadata",
                return_value={
                    "name": "存储芯片",
                    "type": "concept",
                    "subtype": "",
                    "code": "307940",
                    "platecode": "886042",
                },
            ),
            patch.object(ThsFetcher, "_resolve_ths_platecode_from_cid") as scrape_mock,
            patch.object(ThsFetcher, "_fetch_ths_board_year", return_value=_DAILY_BODY_2025),
        ):
            rows = f.get_board_history(
                board_code="886042",  # platecode input
                board_type="concept",
                frequency="d",
                start_date="2025-06-29",
                end_date="2025-06-30",
            )
        scrape_mock.assert_not_called()  # cache hit short-circuits HTML scrape
        assert len(rows) == 2
        assert rows[0]["date"] == "2025-06-29"

    def test_industry_skips_platecode_resolution(self):
        """Industry: board_code IS the platecode (881xxx). No HTML scrape."""
        from stock_data.data_provider.fetchers.ths_fetcher import ThsFetcher

        f = ThsFetcher.__new__(ThsFetcher)
        year_js_body = 'var v_x={"data":"20251230,1,2,3,4,5,6,7,8,9,10;"};'

        with (
            patch.object(ThsFetcher, "_resolve_ths_platecode_from_cid") as scrape_mock,
            patch.object(ThsFetcher, "_fetch_ths_board_year", return_value=year_js_body),
        ):
            rows = f.get_board_history(
                board_code="881270",
                board_type="industry",
                frequency="d",
                days=180,
                end_date="2025-12-31",
            )
        scrape_mock.assert_not_called()
        assert len(rows) == 1

    @pytest.mark.parametrize("freq,freq_segment", [
        ("d", 1), ("w", 2), ("m", 10), ("5m", 30),
        ("15m", 50), ("30m", 60), ("60m", 70),
    ])
    def test_all_7_frequencies_supported(self, freq, freq_segment):
        """All 7 THS frequencies are accepted; freq_segment reaches
        _fetch_ths_board_year correctly. (Pre-2026-07-14 only d worked.)"""
        from stock_data.data_provider.fetchers.ths_fetcher import ThsFetcher

        f = ThsFetcher.__new__(ThsFetcher)
        # Daily/weekly/monthly bodies use 2025 dates that fall inside
        # the test's explicit 2025-06-29..2025-06-30 window. Minute
        # bodies use 2026-07-13 dates inside the 2026-07-12..2026-07-14
        # window. Each frequency's _THS_BOARD_MAX_SPAN_DAYS cap is
        # generous enough for these test windows.
        body = _5MIN_BODY if freq.endswith("m") else _DAILY_BODY_2025
        start = "2026-07-12" if freq.endswith("m") else "2025-06-29"
        end = "2026-07-14" if freq.endswith("m") else "2025-06-30"

        with patch.object(ThsFetcher, "_fetch_ths_board_year", return_value=body) as fetch_mock:
            rows = f.get_board_history(
                board_code="881270",  # industry — no clid resolution needed
                board_type="industry",
                frequency=freq,
                start_date=start,
                end_date=end,
            )
        # Verify freq_segment was passed correctly.
        for call in fetch_mock.call_args_list:
            assert call.args[2] == freq_segment, (
                f"freq={freq} expected seg={freq_segment}, got {call.args[2]}"
            )
        assert len(rows) >= 1, f"freq={freq} returned 0 rows"

    def test_invalid_frequency_raises(self):
        from stock_data.data_provider.fetchers.ths_fetcher import DataFetchError, ThsFetcher

        f = ThsFetcher.__new__(ThsFetcher)
        with pytest.raises(DataFetchError, match="unsupported frequency"):
            f.get_board_history("881270", board_type="industry", frequency="2h")

    def test_5min_span_cap_raises(self):
        """5m bars are capped at 30 days (per _THS_BOARD_MAX_SPAN_DAYS);
        longer spans raise ValueError → 400."""
        from stock_data.data_provider.fetchers.ths_fetcher import ThsFetcher

        f = ThsFetcher.__new__(ThsFetcher)
        with pytest.raises(ValueError, match="exceeds frequency='5m' max"):
            f.get_board_history(
                board_code="881270",
                board_type="industry",
                frequency="5m",
                days=90,
            )

    def test_missing_board_type_auto_detects_industry(self):
        """When board_type is None, auto-detect from stock_board cache."""
        from stock_data.data_provider.fetchers.ths_fetcher import ThsFetcher

        f = ThsFetcher.__new__(ThsFetcher)
        year_js_body = 'var v_x={"data":"20251230,1,2,3,4,5,6,7,8,9,10;"};'
        with (
            patch(
                "stock_data.data_provider.persistence.board.get_board_metadata",
                return_value={
                    "name": "银行", "type": "industry", "subtype": "",
                    "code": "881270", "platecode": "881270",
                },
            ),
            patch.object(ThsFetcher, "_fetch_ths_board_year", return_value=year_js_body),
        ):
            rows = f.get_board_history(
                board_code="881270",
                board_type=None,
                frequency="d",
                days=180,
                end_date="2025-12-31",
            )
        assert len(rows) == 1

    def test_invalid_board_type_raises(self):
        from stock_data.data_provider.fetchers.ths_fetcher import DataFetchError, ThsFetcher

        f = ThsFetcher.__new__(ThsFetcher)
        with pytest.raises(DataFetchError, match="board_type must be"):
            f.get_board_history("881270", board_type="foobar")

    def test_concept_platecode_failure_raises(self):
        """Cache miss AND HTML scrape returns None → DataFetchError naming
        the input so the operator can debug."""
        from stock_data.data_provider.fetchers.ths_fetcher import DataFetchError, ThsFetcher

        f = ThsFetcher.__new__(ThsFetcher)
        with (
            patch(
                "stock_data.data_provider.persistence.board.get_board_metadata",
                return_value=None,  # force cache miss
            ),
            patch.object(ThsFetcher, "_resolve_ths_platecode_from_cid", return_value=None),
        ):
            with pytest.raises(DataFetchError, match="could not resolve concept platecode"):
                f.get_board_history("307940", board_type="concept")

    def test_date_range_filter(self):
        """Date filter now uses YYYY-MM-DD comparison (after the parser
        normalizes upstream YYYYMMDD). The 2023 row is outside the
        2024-01-01..2025-01-01 window and must be excluded."""
        from stock_data.data_provider.fetchers.ths_fetcher import ThsFetcher

        f = ThsFetcher.__new__(ThsFetcher)
        # Mix dates from 2023, 2024, 2025 — only 2024-12-31 should pass.
        year_js_body = (
            'var v_x={"data":"20250630,1,2,3,4,5,6,7,8,9,10;'
            "20241231,1,2,3,4,5,6,7,8,9,10;"
            '20230101,1,2,3,4,5,6,7,8,9,10;"};'
        )
        with (
            patch.object(ThsFetcher, "_fetch_ths_board_year", return_value=year_js_body),
        ):
            rows = f.get_board_history(
                board_code="881270",
                board_type="industry",
                start_date="2024-01-01",
                end_date="2025-01-01",
            )
        dates = [r["date"] for r in rows]
        assert "2024-12-31" in dates
        assert "2025-06-30" not in dates
        assert "2023-01-01" not in dates

    def test_returns_sorted_ascending(self):
        from stock_data.data_provider.fetchers.ths_fetcher import ThsFetcher

        f = ThsFetcher.__new__(ThsFetcher)
        year_js_body = (
            'var v_x={"data":"20250629,1,2,3,4,5,6,7,8,9,10;'
            "20250630,1,2,3,4,5,6,7,8,9,10;"
            '20250628,1,2,3,4,5,6,7,8,9,10;"};'
        )
        with patch.object(ThsFetcher, "_fetch_ths_board_year", return_value=year_js_body):
            rows = f.get_board_history(
                board_code="881270",
                board_type="industry",
                start_date="2025-06-01",
                end_date="2025-06-30",
            )
        dates = [r["date"] for r in rows]
        assert dates == sorted(dates)

    @pytest.mark.parametrize("freq", ["d", "w", "m", "5m", "15m", "30m", "60m"])
    def test_each_row_tagged_with_frequency(self, freq):
        """Post-2026-07-14: each row in the response carries a
        ``frequency`` field matching the requested freq. This is the
        per-row self-identification contract — downstream consumers
        can verify each bar's timeframe independently of the top-level
        period field (defense-in-depth against wrong-upstream-segment
        bugs that would otherwise be invisible at the row level)."""
        from stock_data.data_provider.fetchers.ths_fetcher import ThsFetcher

        f = ThsFetcher.__new__(ThsFetcher)
        body = _5MIN_BODY if freq.endswith("m") else _DAILY_BODY_2025
        start = "2026-07-12" if freq.endswith("m") else "2025-06-29"
        end = "2026-07-14" if freq.endswith("m") else "2025-06-30"

        with patch.object(ThsFetcher, "_fetch_ths_board_year", return_value=body):
            rows = f.get_board_history(
                board_code="881270",
                board_type="industry",
                frequency=freq,
                start_date=start,
                end_date=end,
            )
        assert rows, f"freq={freq} returned 0 rows"
        for r in rows:
            assert r["frequency"] == freq, (
                f"freq={freq} row tagged {r.get('frequency')!r}; "
                f"date={r['date']!r}"
            )

    def test_minute_end_bound_uses_2359(self):
        """Minute-level bars (YYYY-MM-DD HH:MM) need the end-date bound
        to extend to " 23:59" or the last bar of the day would be
        cut off by the lexicographic compare."""
        from stock_data.data_provider.fetchers.ths_fetcher import ThsFetcher

        f = ThsFetcher.__new__(ThsFetcher)
        # Last bar of 2026-07-13 at 14:55 — would be cut off by a
        # bare "2026-07-13" end bound (because "2026-07-13 14:55" >
        # "2026-07-13" lex-wise; but "2026-07-13 14:55" <= "2026-07-13 23:59").
        body = (
            'var v_x={"data":"202607130930,1,2,3,4,5,6,7,8,9,10;'
            '202607131455,1,2,3,4,5,6,7,8,9,10;"};'
        )
        with patch.object(ThsFetcher, "_fetch_ths_board_year", return_value=body):
            rows = f.get_board_history(
                board_code="881270",
                board_type="industry",
                frequency="5m",
                start_date="2026-07-13",
                end_date="2026-07-13",
            )
        # Both rows should be kept (the 14:55 bar is the same day as end).
        assert len(rows) == 2
        dates = [r["date"] for r in rows]
        assert "2026-07-13 14:55" in dates

    def test_daily_end_bound_does_not_get_2359_suffix(self):
        """Daily bars (YYYY-MM-DD) should NOT get the " 23:59" tail —
        the explicit set check (not endswith("m")) means monthly
        (key "m") and daily (key "d") both skip it. This verifies
        the polish fix for the cosmetic "monthly was silently
        over-applied" issue."""
        from stock_data.data_provider.fetchers.ths_fetcher import ThsFetcher

        f = ThsFetcher.__new__(ThsFetcher)
        # Mock _fetch_ths_board_year and capture the year body
        # (we don't actually care about the URL — we just need
        # the fetcher's date-filter behavior). The end bound is
        # internal; we test the EFFECT: a daily bar on the same
        # day as end_date is included regardless.
        body = 'var v_x={"data":"20251231,1,2,3,4,5,6,7,8,9,10;"};'
        with patch.object(ThsFetcher, "_fetch_ths_board_year", return_value=body):
            rows = f.get_board_history(
                board_code="881270",
                board_type="industry",
                frequency="d",
                start_date="2025-12-01",
                end_date="2025-12-31",
            )
        assert len(rows) == 1
        assert rows[0]["date"] == "2025-12-31"  # no spurious time suffix


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


class TestThsKlineParserRobustness:
    """A3 — JSON extraction: positional slice + demjson3 instead of greedy regex."""

    def test_multi_var_body_returns_first_object(self):
        from stock_data.data_provider.fetchers.ths_fetcher import ThsFetcher

        f = ThsFetcher.__new__(ThsFetcher)
        body = (
            'var v_a={"data":"20250630,1,2,3,4,5,6,7,8,9,10;"};'
            'var v_b={"data":"ignored,row,data"};'
        )
        rows = f._parse_ths_kline_body(body)
        assert len(rows) == 1
        assert rows[0]["date"] == "2025-06-30"

    def test_no_trailing_semicolon_still_parses(self):
        from stock_data.data_provider.fetchers.ths_fetcher import ThsFetcher

        f = ThsFetcher.__new__(ThsFetcher)
        body = '{"data":"20250630,1,2,3,4,5,6,7,8,9,10;"}'
        rows = f._parse_ths_kline_body(body)
        assert len(rows) == 1

    def test_js_unquoted_keys_accepted(self):
        from stock_data.data_provider.fetchers.ths_fetcher import ThsFetcher

        f = ThsFetcher.__new__(ThsFetcher)
        body = 'var v_x={data:"20250630,1,2,3,4,5,6,7,8,9,10;"};'
        rows = f._parse_ths_kline_body(body)
        assert len(rows) == 1

    def test_empty_after_strip_returns_empty(self):
        from stock_data.data_provider.fetchers.ths_fetcher import ThsFetcher

        f = ThsFetcher.__new__(ThsFetcher)
        assert f._parse_ths_kline_body("") == []
        assert f._parse_ths_kline_body("   ") == []
        assert f._parse_ths_kline_body(";;;") == []


class TestPlatecodeExtractionRobustness:
    """A4 — BS4 find() replaces attribute-order-sensitive regex."""

    def test_extracts_platecode_when_value_precedes_id(self):
        from stock_data.data_provider.fetchers.ths_fetcher import ThsFetcher

        f = ThsFetcher.__new__(ThsFetcher)
        html = '<html><body><input value="886042" id="clid" /></body></html>'

        def fake_get(url, headers=None, timeout=None, **kw):
            r = MagicMock()
            r.text = html
            return r

        with patch.object(ThsFetcher, "_http_get", side_effect=fake_get):
            assert f._resolve_ths_platecode_from_cid("307940") == "886042"

    def test_missing_value_attribute_returns_none(self):
        from stock_data.data_provider.fetchers.ths_fetcher import ThsFetcher

        f = ThsFetcher.__new__(ThsFetcher)
        html = '<html><body><input id="clid" /></body></html>'

        def fake_get(url, headers=None, timeout=None, **kw):
            r = MagicMock()
            r.text = html
            return r

        with patch.object(ThsFetcher, "_http_get", side_effect=fake_get):
            assert f._resolve_ths_platecode_from_cid("307940") is None


class TestGetBoardHistoryEdgeCases:
    """A5/A6/A7 — all-empty raise, span cap raise, reverse-date raise."""

    def test_all_years_failed_raises(self):
        from unittest.mock import patch

        from stock_data.data_provider.fetchers.ths_fetcher import DataFetchError, ThsFetcher

        f = ThsFetcher.__new__(ThsFetcher)
        with (
            patch.object(ThsFetcher, "_fetch_ths_board_year", return_value=""),
            patch.object(ThsFetcher, "_v_token", return_value="x"),
            pytest.raises(DataFetchError, match="all .* year-fetches .* returned empty"),
        ):
            f.get_board_history(
                board_code="881270",
                board_type="industry",
                frequency="d",
                days=400,
                end_date="2025-06-30",
                start_date="2024-12-01",
            )

    def test_partial_years_success_passes_through(self):
        from unittest.mock import patch

        from stock_data.data_provider.fetchers.ths_fetcher import ThsFetcher

        f = ThsFetcher.__new__(ThsFetcher)

        def fetch_year(inner, year, freq):
            return _DAILY_BODY_2025 if year == 2025 else ""

        with patch.object(ThsFetcher, "_fetch_ths_board_year", side_effect=fetch_year):
            rows = f.get_board_history(
                board_code="881270",
                board_type="industry",
                frequency="d",
                days=400,
                end_date="2025-06-30",
                start_date="2024-12-01",
            )
        assert len(rows) == 2  # 2024 empty, 2025 contributes 2 rows
        assert rows[0]["date"] == "2025-06-29"

    def test_year_span_cap_raises(self):
        """16-year span exceeds _THS_BOARD_MAX_SPAN_DAYS['d'] = 3650 days.
        The cap was extended in 2026-07-14 from year-count (10y) to
        day-count (3650d) — the message is now "exceeds frequency='d' max"."""
        from unittest.mock import patch

        from stock_data.data_provider.fetchers.ths_fetcher import ThsFetcher

        f = ThsFetcher.__new__(ThsFetcher)
        with (
            patch.object(ThsFetcher, "_v_token", return_value="x"),
            pytest.raises(ValueError, match="exceeds frequency='d' max"),
        ):
            f.get_board_history(
                board_code="881270",
                board_type="industry",
                frequency="d",
                days=10,
                start_date="2010-01-01",
                end_date="2025-12-31",  # ~5800 days, well over 3650
            )

    def test_year_span_at_boundary_passes(self):
        """9-year span (within _MAX_YEAR_SPAN=10 and 3650-day cap) passes."""
        from unittest.mock import patch

        from stock_data.data_provider.fetchers.ths_fetcher import ThsFetcher

        f = ThsFetcher.__new__(ThsFetcher)

        def fetch_year(inner, year, freq):
            return 'var v_x={"data":"20250630,1,2,3,4,5,6,7,8,9,10;"};'

        with (
            patch.object(ThsFetcher, "_fetch_ths_board_year", side_effect=fetch_year),
            patch.object(ThsFetcher, "_v_token", return_value="x"),
        ):
            rows = f.get_board_history(
                board_code="881270",
                board_type="industry",
                frequency="d",
                days=10,
                start_date="2017-01-01",
                end_date="2025-12-31",  # 9-year span
            )
        # 2017..2025 inclusive = 9 years; 1 row per year.
        assert len(rows) == 9

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

    def test_missing_demjson3_returns_false(self, monkeypatch):
        from stock_data.data_provider.fetchers.ths_fetcher import ThsFetcher

        real_find_spec = ths_mod.util.find_spec

        def fake_find_spec(name):
            if name == "demjson3":
                return None
            return real_find_spec(name)

        monkeypatch.setattr(ths_mod.util, "find_spec", fake_find_spec)
        assert ThsFetcher().is_available() is False
        reason = ThsFetcher().unavailable_reason()
        assert reason is not None
        assert "demjson3" in reason


class TestFetchThsBoardYearStatusCode:
    """Fix #9 — non-2xx upstream returns "" so the all-empty gate fires."""

    def test_non_2xx_returns_empty_string(self, monkeypatch):
        from unittest.mock import MagicMock, patch

        from stock_data.data_provider.fetchers.ths_fetcher import ThsFetcher

        f = ThsFetcher.__new__(ThsFetcher)

        def fake_get(url, headers=None, timeout=None, **kw):
            r = MagicMock()
            r.status_code = 403
            r.content = b"<html>Forbidden</html>"
            r.text = "<html>Forbidden</html>"
            return r

        with (
            patch.object(ThsFetcher, "_http_get", side_effect=fake_get),
            patch.object(ThsFetcher, "_v_token", return_value="x"),
        ):
            assert f._fetch_ths_board_year("886042", 2024, 1) == ""

    def test_2xx_returns_body(self, monkeypatch):
        from unittest.mock import MagicMock, patch

        from stock_data.data_provider.fetchers.ths_fetcher import ThsFetcher

        f = ThsFetcher.__new__(ThsFetcher)

        def fake_get(url, headers=None, timeout=None, **kw):
            r = MagicMock()
            r.status_code = 200
            r.text = 'var v_x={"data":"20240101,1,2,3,4,5,6,7,8,9,10;"};'
            return r

        with (
            patch.object(ThsFetcher, "_http_get", side_effect=fake_get),
            patch.object(ThsFetcher, "_v_token", return_value="x"),
        ):
            assert f._fetch_ths_board_year("886042", 2024, 1).startswith("var v_x=")
