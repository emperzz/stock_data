"""Tests for ThsFetcher.get_board_history."""


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
        from stock_data.data_provider.fetchers.ths_fetcher import ThsFetcher
        from unittest.mock import patch, MagicMock

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
        from stock_data.data_provider.fetchers.ths_fetcher import ThsFetcher
        from unittest.mock import patch, MagicMock

        f = ThsFetcher.__new__(ThsFetcher)

        def fake_get(url, headers=None, timeout=None, **kw):
            r = MagicMock()
            r.text = "<html><body>no input</body></html>"
            r.status_code = 200
            return r

        with patch.object(ThsFetcher, "_http_get", side_effect=fake_get):
            assert f._resolve_ths_concept_clid("xxx") is None

    def test_http_failure_returns_none(self):
        from stock_data.data_provider.fetchers.ths_fetcher import ThsFetcher
        from unittest.mock import patch

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
