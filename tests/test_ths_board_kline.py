"""Tests for ThsFetcher.get_board_history."""

from unittest.mock import MagicMock, patch

import pytest


class TestVToken:
    def test_v_token_is_nonempty_string(self):
        from stock_data.data_provider.fetchers.ths_fetcher import _get_ths_v_token

        v = _get_ths_v_token()
        assert isinstance(v, str) and len(v) >= 8

    def test_v_token_is_cached(self):
        from stock_data.data_provider.fetchers.ths_fetcher import _get_ths_v_token

        v1 = _get_ths_v_token()
        v2 = _get_ths_v_token()
        assert v1 == v2  # cached (lru_cache)


class TestResolveConceptClid:
    def test_extracts_clid_from_html(self, monkeypatch):
        from unittest.mock import patch

        from stock_data.data_provider.fetchers.ths_fetcher import ThsFetcher

        fake_html = '<html><body><input id="clid" value="T000267467"/></body></html>'

        f = ThsFetcher.__new__(ThsFetcher)

        def fake_get(url, headers=None, timeout=None, **kw):
            assert "/gn/detail/code/" in url
            r = MagicMock()
            r.text = fake_html
            r.status_code = 200
            return r

        with patch.object(ThsFetcher, "_http_get", side_effect=fake_get):
            clid = f._resolve_ths_concept_clid("301558")
        assert clid == "T000267467"

    def test_missing_clid_returns_none(self):
        from unittest.mock import patch

        from stock_data.data_provider.fetchers.ths_fetcher import ThsFetcher

        f = ThsFetcher.__new__(ThsFetcher)

        def fake_get(url, headers=None, timeout=None, **kw):
            r = MagicMock()
            r.text = "<html><body>no input</body></html>"
            r.status_code = 200
            return r

        with patch.object(ThsFetcher, "_http_get", side_effect=fake_get):
            assert f._resolve_ths_concept_clid("xxx") is None

    def test_http_failure_returns_none(self):
        from unittest.mock import patch

        from stock_data.data_provider.fetchers.ths_fetcher import ThsFetcher

        f = ThsFetcher.__new__(ThsFetcher)

        def fake_get(url, headers=None, timeout=None, **kw):
            raise RuntimeError("network down")

        with patch.object(ThsFetcher, "_http_get", side_effect=fake_get):
            assert f._resolve_ths_concept_clid("301558") is None


class TestParseThsKlineBody:
    def test_parses_typical_response(self):
        from stock_data.data_provider.fetchers.ths_fetcher import ThsFetcher

        f = ThsFetcher.__new__(ThsFetcher)
        body = (
            'var v_abc123={"data":"2025-06-30,1234.5,1260.0,1220.3,1255.7,12345678,1.234e10,2.5,1.7,21.2,1.5;'
            '2025-06-29,1200.0,1240.0,1190.0,1230.0,10000000,1.0e10,2.0,1.0,12.0,1.0;"};'
        )
        rows = f._parse_ths_kline_body(body)
        assert len(rows) == 2
        assert rows[0]["date"] == "2025-06-30"
        assert rows[0]["open"] == 1234.5
        assert rows[1]["close"] == 1230.0
        for r in rows:
            assert set(r.keys()) >= {"date", "open", "high", "low", "close", "volume", "amount"}

    def test_empty_data_returns_empty_list(self):
        from stock_data.data_provider.fetchers.ths_fetcher import ThsFetcher

        f = ThsFetcher.__new__(ThsFetcher)
        assert f._parse_ths_kline_body('var v_x={"data":""};') == []

    def test_handles_11_or_12_column_rows(self):
        from stock_data.data_provider.fetchers.ths_fetcher import ThsFetcher

        f = ThsFetcher.__new__(ThsFetcher)
        body = 'var v_x={"data":"2025-06-30,1,2,3,4,5,6,7,8,9,10,11;"};'
        rows = f._parse_ths_kline_body(body)
        assert len(rows) == 1
        assert rows[0]["close"] == 4.0

    def test_skips_malformed_rows(self):
        from stock_data.data_provider.fetchers.ths_fetcher import ThsFetcher

        f = ThsFetcher.__new__(ThsFetcher)
        body = 'var v_x={"data":"2025-06-30,1,2,3,4,5,6,7,8,9,10;garbage_row;2025-06-29,1,2,3,4,5,6,7,8,9,10;"};'
        rows = f._parse_ths_kline_body(body)
        assert len(rows) == 2

    def test_missing_var_wrapper_still_parses(self):
        from stock_data.data_provider.fetchers.ths_fetcher import ThsFetcher

        f = ThsFetcher.__new__(ThsFetcher)
        body = '{"data":"2025-06-30,1,2,3,4,5,6,7,8,9,10;"}'
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
    def test_concept_calls_clid_then_year_js(self):
        from stock_data.data_provider.fetchers.ths_fetcher import ThsFetcher

        f = ThsFetcher.__new__(ThsFetcher)
        body_2024 = 'var v_x={"data":"2024-12-15,1,2,3,4,5,6,7,8,9,10;"};'
        body_2025 = (
            'var v_x={"data":"2025-06-30,1,2,3,4,5,6,7,8,9,10;'
            '2025-06-29,1.1,2.1,3.1,4.1,5.1,6.1,7.1,8.1,9.1,10.1;"};'
        )

        def fetch_year(inner, year):
            return body_2025 if year == 2025 else body_2024

        with (
            patch.object(ThsFetcher, "_resolve_ths_concept_clid", return_value="T000267467"),
            patch.object(ThsFetcher, "_fetch_ths_board_year", side_effect=fetch_year),
        ):
            rows = f.get_board_history(
                board_code="301558",
                board_type="concept",
                frequency="d",
                days=400,
                end_date="2025-06-30",
                start_date="2024-12-01",
            )
        # 2024 body contributes 1 row, 2025 body contributes 2 rows
        assert len(rows) == 3
        # Sorted oldest → newest per get_board_history docstring
        assert [r["date"] for r in rows] == ["2024-12-15", "2025-06-29", "2025-06-30"]

    def test_industry_skips_clid_step(self):
        from stock_data.data_provider.fetchers.ths_fetcher import ThsFetcher

        f = ThsFetcher.__new__(ThsFetcher)
        # Scope to a single year so a single-year body satisfies len(rows) == 1.
        # start_d = 2025-12-31 - 180 days → still 2025 → only 2025 fetched.
        year_js_body = 'var v_x={"data":"2025-12-30,1,2,3,4,5,6,7,8,9,10;"};'
        with (
            patch.object(ThsFetcher, "_resolve_ths_concept_clid") as clid_mock,
            patch.object(ThsFetcher, "_fetch_ths_board_year", return_value=year_js_body),
        ):
            rows = f.get_board_history(
                board_code="881270",
                board_type="industry",
                frequency="d",
                days=180,
                end_date="2025-12-31",
            )
        clid_mock.assert_not_called()
        assert len(rows) == 1

    def test_unsupported_frequency_raises(self):
        from stock_data.data_provider.fetchers.ths_fetcher import DataFetchError, ThsFetcher

        f = ThsFetcher.__new__(ThsFetcher)
        try:
            f.get_board_history("881270", board_type="industry", frequency="w")
        except DataFetchError as e:
            assert "frequency" in str(e).lower() or "w" in str(e)
        else:
            raise AssertionError("expected DataFetchError for non-daily THS freq")

    def test_missing_board_type_raises(self):
        from stock_data.data_provider.fetchers.ths_fetcher import DataFetchError, ThsFetcher

        f = ThsFetcher.__new__(ThsFetcher)
        try:
            f.get_board_history("881270", board_type=None)
        except DataFetchError as e:
            assert "board_type" in str(e).lower()
        else:
            raise AssertionError("expected DataFetchError when board_type missing")

    def test_invalid_board_type_raises(self):
        from stock_data.data_provider.fetchers.ths_fetcher import DataFetchError, ThsFetcher

        f = ThsFetcher.__new__(ThsFetcher)
        try:
            f.get_board_history("881270", board_type="foobar")
        except DataFetchError as e:
            assert "board_type" in str(e).lower() or "foobar" in str(e)
        else:
            raise AssertionError("expected DataFetchError for unknown board_type")

    def test_concept_clid_failure_raises(self):
        from stock_data.data_provider.fetchers.ths_fetcher import DataFetchError, ThsFetcher

        f = ThsFetcher.__new__(ThsFetcher)
        with patch.object(ThsFetcher, "_resolve_ths_concept_clid", return_value=None):
            try:
                f.get_board_history("301558", board_type="concept")
            except DataFetchError as e:
                assert "301558" in str(e) or "clid" in str(e).lower()
            else:
                raise AssertionError("expected DataFetchError when clid resolves to None")

    def test_date_range_filter(self):
        from stock_data.data_provider.fetchers.ths_fetcher import ThsFetcher

        f = ThsFetcher.__new__(ThsFetcher)
        year_js_body = (
            'var v_x={"data":"2025-06-30,1,2,3,4,5,6,7,8,9,10;'
            "2024-12-31,1,2,3,4,5,6,7,8,9,10;"
            '2023-01-01,1,2,3,4,5,6,7,8,9,10;"};'
        )
        with (
            patch.object(ThsFetcher, "_resolve_ths_concept_clid", return_value="T000267467"),
            patch.object(ThsFetcher, "_fetch_ths_board_year", return_value=year_js_body),
        ):
            rows = f.get_board_history(
                board_code="301558",
                board_type="concept",
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
            'var v_x={"data":"2025-06-29,1,2,3,4,5,6,7,8,9,10;'
            "2025-06-30,1,2,3,4,5,6,7,8,9,10;"
            '2025-06-28,1,2,3,4,5,6,7,8,9,10;"};'
        )
        with (
            patch.object(ThsFetcher, "_resolve_ths_concept_clid", return_value="T000267467"),
            patch.object(ThsFetcher, "_fetch_ths_board_year", return_value=year_js_body),
        ):
            rows = f.get_board_history(
                board_code="301558",
                board_type="concept",
                start_date="2025-06-01",
                end_date="2025-06-30",
            )
        dates = [r["date"] for r in rows]
        assert dates == sorted(dates)


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
        from stock_data.data_provider.fetchers.ths_fetcher import (
            DataFetchError,
        )

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
        # Direct setattr with manual restore — pytest's monkeypatch.setattr has
        # been flaky in our setup for module-level function references.
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
        """MiniRacer VM instantiated once across calls — saves ~200ms per re-mint."""
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
        mod._ths_js_vm = None  # force lazy init on next call
        try:
            t1 = mod._get_ths_v_token()
            t2 = mod._get_ths_v_token()
            t3 = mod._get_ths_v_token()
            # First call instantiates VM; subsequent calls return cached token,
            # so `_get_ths_js_vm` is NOT re-invoked. instantiations == 1.
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
        # d.10jqka.com.cn cache-bust combo variant emits two var= assignments.
        # Old greedy regex joined them into invalid JSON; new positional
        # extraction parses the FIRST object only.
        body = (
            'var v_a={"data":"2025-06-30,1,2,3,4,5,6,7,8,9,10;"};'
            'var v_b={"data":"ignored,row,data"};'
        )
        rows = f._parse_ths_kline_body(body)
        assert len(rows) == 1
        assert rows[0]["date"] == "2025-06-30"

    def test_no_trailing_semicolon_still_parses(self):
        # Variant: `}` but no trailing `;`. Old code required ";" exactly.
        from stock_data.data_provider.fetchers.ths_fetcher import ThsFetcher

        f = ThsFetcher.__new__(ThsFetcher)
        body = '{"data":"2025-06-30,1,2,3,4,5,6,7,8,9,10;"}'
        rows = f._parse_ths_kline_body(body)
        assert len(rows) == 1

    def test_js_unquoted_keys_accepted(self):
        # demjson3 lenient on JS-style literals
        from stock_data.data_provider.fetchers.ths_fetcher import ThsFetcher

        f = ThsFetcher.__new__(ThsFetcher)
        body = 'var v_x={data:"2025-06-30,1,2,3,4,5,6,7,8,9,10;"};'
        rows = f._parse_ths_kline_body(body)
        assert len(rows) == 1

    def test_empty_after_strip_returns_empty(self):
        from stock_data.data_provider.fetchers.ths_fetcher import ThsFetcher

        f = ThsFetcher.__new__(ThsFetcher)
        assert f._parse_ths_kline_body("") == []
        assert f._parse_ths_kline_body("   ") == []
        assert f._parse_ths_kline_body(";;;") == []


class TestClidExtractionRobustness:
    """A4 — BS4 find() replaces attribute-order-sensitive regex."""

    def test_extracts_clid_when_value_precedes_id(self):
        # The OLD regex required id-then-value ordering; this body flipped
        # the order. BS4 picks up the input regardless.
        from unittest.mock import patch

        from stock_data.data_provider.fetchers.ths_fetcher import ThsFetcher

        f = ThsFetcher.__new__(ThsFetcher)
        html = '<html><body><input value="T000888999" id="clid" /></body></html>'

        def fake_get(url, headers=None, timeout=None, **kw):
            r = MagicMock()
            r.text = html
            return r

        with patch.object(ThsFetcher, "_http_get", side_effect=fake_get):
            assert f._resolve_ths_concept_clid("301558") == "T000888999"

    def test_missing_value_attribute_returns_none(self):
        # input has id=clid but no value → BS4 returns None cleanly instead
        # of KeyError.
        from unittest.mock import patch

        from stock_data.data_provider.fetchers.ths_fetcher import ThsFetcher

        f = ThsFetcher.__new__(ThsFetcher)
        html = '<html><body><input id="clid" /></body></html>'

        def fake_get(url, headers=None, timeout=None, **kw):
            r = MagicMock()
            r.text = html
            return r

        with patch.object(ThsFetcher, "_http_get", side_effect=fake_get):
            assert f._resolve_ths_concept_clid("301558") is None


class TestGetBoardHistoryEdgeCases:
    """A5/A6/A7 — all-empty raise, span cap raise, reverse-date raise."""

    def test_all_years_failed_raises(self):
        from unittest.mock import patch

        from stock_data.data_provider.fetchers.ths_fetcher import (
            DataFetchError,
            ThsFetcher,
        )

        f = ThsFetcher.__new__(ThsFetcher)
        # All years return "" → upstream auth or 5xx for every year.
        with (
            patch.object(ThsFetcher, "_resolve_ths_concept_clid", return_value="T000267467"),
            patch.object(ThsFetcher, "_fetch_ths_board_year", return_value=""),
            patch.object(ThsFetcher, "_v_token", return_value="x"),
            pytest.raises(DataFetchError, match="all .* year-fetches returned empty"),
        ):
            f.get_board_history(
                board_code="301558",
                board_type="concept",
                frequency="d",
                days=400,
                end_date="2025-06-30",
                start_date="2024-12-01",
                )

    def test_partial_years_success_passes_through(self):
        # Some years empty, others valid → no raise, returns what came back.
        from unittest.mock import patch

        from stock_data.data_provider.fetchers.ths_fetcher import ThsFetcher

        f = ThsFetcher.__new__(ThsFetcher)
        body_2025 = 'var v_x={"data":"2025-06-30,1,2,3,4,5,6,7,8,9,10;"};'

        def fetch_year(inner, year):
            return body_2025 if year == 2025 else ""  # 2024 empty, 2025 ok

        with (
            patch.object(ThsFetcher, "_resolve_ths_concept_clid", return_value="T000267467"),
            patch.object(ThsFetcher, "_fetch_ths_board_year", side_effect=fetch_year),
        ):
            rows = f.get_board_history(
                board_code="301558",
                board_type="concept",
                frequency="d",
                days=400,
                end_date="2025-06-30",
                start_date="2024-12-01",
            )
        # 2024 returned "" but skipped silently; 2025 contributed 1 row.
        assert len(rows) == 1
        assert rows[0]["date"] == "2025-06-30"

    def test_year_span_cap_raises(self):
        # 11+ year span → reject
        from unittest.mock import patch

        from stock_data.data_provider.fetchers.ths_fetcher import (
            DataFetchError,
            ThsFetcher,
        )

        f = ThsFetcher.__new__(ThsFetcher)
        with (
            patch.object(ThsFetcher, "_v_token", return_value="x"),
            pytest.raises(DataFetchError, match="year span .* > 10"),
        ):
            f.get_board_history(
                board_code="881270",
                board_type="industry",
                frequency="d",
                days=10,
                start_date="2010-01-01",
                end_date="2025-12-31",  # 16-year span
            )

    def test_year_span_at_boundary_passes(self):
        # Exactly 10 years (2016..2025) → passes span cap (cap is _MAX_YEAR_SPAN, exclusive).
        # The mocked body returns one row per year → 10 rows total.
        from unittest.mock import patch

        from stock_data.data_provider.fetchers.ths_fetcher import ThsFetcher

        f = ThsFetcher.__new__(ThsFetcher)
        body = 'var v_x={"data":"2025-06-30,1,2,3,4,5,6,7,8,9,10;"};'

        def fetch_year(inner, year):
            return body

        with (
            patch.object(ThsFetcher, "_fetch_ths_board_year", side_effect=fetch_year),
            patch.object(ThsFetcher, "_v_token", return_value="x"),
        ):
            rows = f.get_board_history(
                board_code="881270",
                board_type="industry",
                frequency="d",
                days=10,
                start_date="2016-01-01",
                end_date="2025-12-31",
            )
        # 2016..2025 inclusive = 10 years; each year contributes 1 row → 10 rows total.
        assert len(rows) == 10

    def test_reversed_dates_raises(self):
        from unittest.mock import patch

        from stock_data.data_provider.fetchers.ths_fetcher import (
            DataFetchError,
            ThsFetcher,
        )

        f = ThsFetcher.__new__(ThsFetcher)
        with (
            patch.object(ThsFetcher, "_v_token", return_value="x"),
            pytest.raises(DataFetchError, match="start_date .* > end_date"),
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

        from stock_data.data_provider.fetchers.ths_fetcher import (
            DataFetchError,
            ThsFetcher,
        )

        f = ThsFetcher.__new__(ThsFetcher)
        with (
            patch.object(ThsFetcher, "_v_token", return_value="x"),
            pytest.raises(DataFetchError, match="start_date=.*not YYYY-MM-DD"),
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

        from stock_data.data_provider.fetchers.ths_fetcher import (
            DataFetchError,
            ThsFetcher,
        )

        f = ThsFetcher.__new__(ThsFetcher)
        with (
            patch.object(ThsFetcher, "_v_token", return_value="x"),
            pytest.raises(DataFetchError, match="end_date=.*not YYYY-MM-DD"),
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
    """Packaging regression — vendored ths.js must ship + load."""

    def test_ths_assets_shipped(self):
        from importlib.resources import files

        import stock_data.data_provider.fetchers.ths_assets as assets

        js = files(assets).joinpath("ths.js")
        assert js.is_file(), (
            "ths.js missing from stock_data package — check "
            "pyproject.toml [tool.hatch.build.targets.wheel.force-include]"
        )

    def test_ths_js_has_entry_signature(self):
        from importlib.resources import files

        import stock_data.data_provider.fetchers.ths_assets as assets

        js = files(assets).joinpath("ths.js")
        text = js.read_text(encoding="utf-8")
        assert "function v_cookie" in text
        assert "function v ()" in text
