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
