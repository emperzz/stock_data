"""Tests for ThsFetcher.get_board_history."""

from unittest.mock import patch


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
        from unittest.mock import MagicMock, patch

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
        from unittest.mock import MagicMock, patch

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

        with patch.object(ThsFetcher, "_resolve_ths_concept_clid", return_value="T000267467"), \
             patch.object(ThsFetcher, "_fetch_ths_board_year", side_effect=fetch_year):
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
        with patch.object(ThsFetcher, "_resolve_ths_concept_clid") as clid_mock, \
             patch.object(ThsFetcher, "_fetch_ths_board_year", return_value=year_js_body):
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
            '2024-12-31,1,2,3,4,5,6,7,8,9,10;'
            '2023-01-01,1,2,3,4,5,6,7,8,9,10;"};'
        )
        with patch.object(ThsFetcher, "_resolve_ths_concept_clid", return_value="T000267467"), \
             patch.object(ThsFetcher, "_fetch_ths_board_year", return_value=year_js_body):
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
            '2025-06-30,1,2,3,4,5,6,7,8,9,10;'
            '2025-06-28,1,2,3,4,5,6,7,8,9,10;"};'
        )
        with patch.object(ThsFetcher, "_resolve_ths_concept_clid", return_value="T000267467"), \
             patch.object(ThsFetcher, "_fetch_ths_board_year", return_value=year_js_body):
            rows = f.get_board_history(
                board_code="301558",
                board_type="concept",
                start_date="2025-06-01",
                end_date="2025-06-30",
            )
        dates = [r["date"] for r in rows]
        assert dates == sorted(dates)
