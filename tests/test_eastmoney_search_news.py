"""
Unit tests for EastMoneyFetcher.search_news().

Covers the JSONP request shape, <em> tag stripping, date normalization,
post-filter on from_date/to_date, and error handling for the spec-defined
failure modes.
"""

import json
import re
import time
from unittest.mock import MagicMock, patch

import pytest

from stock_data.data_provider.base import DataFetchError
from stock_data.data_provider.fetchers.eastmoney_fetcher import EastMoneyFetcher

FIXTURE_PATH = "tests/fixtures/news_search_jsonp.txt"


def _load_fixture() -> str:
    with open(FIXTURE_PATH, encoding="utf-8") as f:
        return f.read()


def _mock_response(text: str, status: int = 200) -> MagicMock:
    mock_response = MagicMock()
    mock_response.status_code = status
    mock_response.text = text
    return mock_response


class _SearchNewsTestBase:
    """Sets up a fetcher whose session warmup is pre-skipped, so each test
    only has to mock the actual ``search_news`` HTTP call. Warmup itself is
    covered by TestSessionWarmup below."""

    def setup_method(self):
        self.fetcher = EastMoneyFetcher()
        self.fetcher._news_warmed = True


class TestSearchNewsHappyPath(_SearchNewsTestBase):
    def test_returns_normalized_dicts(self):
        with patch.object(
            self.fetcher._session, "get", return_value=_mock_response(_load_fixture())
        ):
            results = self.fetcher.search_news(q="603777", limit=20)

        assert len(results) == 2
        first = results[0]
        assert first["title"] == "白酒概念下跌1.10%, 8股主力资金净流出超3000万元"  # <em> stripped
        assert first["url"] == "http://finance.eastmoney.com/a/202606093765150130.html"
        assert first["source_domain"] == "finance.eastmoney.com"
        assert first["publish_date"] == "2026-06-09"
        assert first["media_name"] == "证券时报网"
        assert "<em>" not in first["snippet"]

    def test_request_uses_jsonp_endpoint(self):
        with patch.object(
            self.fetcher._session, "get", return_value=_mock_response(_load_fixture())
        ) as mock_get:
            self.fetcher.search_news(q="白酒概念", limit=5)

        called_url = mock_get.call_args.args[0]
        called_kwargs = mock_get.call_args.kwargs
        assert called_url == "https://search-api-web.eastmoney.com/search/jsonp"
        params = called_kwargs["params"]
        # JSONP callback name + millisecond-timestamp cache-buster, both
        # required to match the shape the real EastMoney frontend sends.
        assert params["cb"].startswith("jQuery")
        assert "_" in params["cb"]
        assert params["_"].isdigit() and len(params["_"]) == 13
        decoded = json.loads(params["param"])
        assert decoded["keyword"] == "白酒概念"
        assert decoded["type"] == ["cmsArticleWebOld"]
        assert decoded["param"]["cmsArticleWebOld"]["pageSize"] == 5
        # Browser-fingerprint headers live on the session, not per-call.
        session_headers = self.fetcher._session.headers
        assert "User-Agent" in session_headers
        assert "Referer" in session_headers
        assert "Origin" in session_headers
        assert "sec-ch-ua" in session_headers
        assert "sec-fetch-site" in session_headers
        assert session_headers["sec-fetch-mode"] == "no-cors"
        assert session_headers["Cache-Control"] == "no-cache"
        assert session_headers["Pragma"] == "no-cache"

    def test_jsonp_callback_matches_jquery_pattern(self):
        """Real-browser JSONP callbacks look like ``jQuery<digits>_<timestamp>``.
        A random hex/hash suffix signals 'script caller' to the backend."""
        with patch.object(
            self.fetcher._session, "get", return_value=_mock_response(_load_fixture())
        ) as mock_get:
            self.fetcher.search_news(q="贵州茅台")

        cb = mock_get.call_args.kwargs["params"]["cb"]
        assert re.match(r"^jQuery\d+_\d{13}$", cb), f"unexpected cb format: {cb}"

    def test_jsonp_callback_changes_per_call(self):
        """Each call gets a fresh timestamp suffix — both for cache-busting and
        to match what jQuery.ajax() produces per request in a real browser."""
        with patch.object(
            self.fetcher._session, "get", return_value=_mock_response(_load_fixture())
        ) as mock_get:
            self.fetcher.search_news(q="贵州茅台")
            time.sleep(0.002)  # ensure timestamp differs
            self.fetcher.search_news(q="贵州茅台")

        cb_first = mock_get.call_args_list[0].kwargs["params"]["cb"]
        cb_second = mock_get.call_args_list[1].kwargs["params"]["cb"]
        assert cb_first != cb_second


class TestSearchNewsFilters(_SearchNewsTestBase):
    def test_from_date_filter(self):
        with patch.object(
            self.fetcher._session, "get", return_value=_mock_response(_load_fixture())
        ):
            results = self.fetcher.search_news(q="603777", from_date="2026-05-01")

        assert len(results) == 1  # Only 2026-06-09 matches; 2026-04-29 excluded
        assert results[0]["publish_date"] == "2026-06-09"

    def test_to_date_filter(self):
        with patch.object(
            self.fetcher._session, "get", return_value=_mock_response(_load_fixture())
        ):
            results = self.fetcher.search_news(q="603777", to_date="2026-05-01")

        assert len(results) == 1  # Only 2026-04-29 matches
        assert results[0]["publish_date"] == "2026-04-29"

    def test_date_range_filter(self):
        with patch.object(
            self.fetcher._session, "get", return_value=_mock_response(_load_fixture())
        ):
            results = self.fetcher.search_news(
                q="603777", from_date="2026-05-01", to_date="2026-06-30"
            )

        assert len(results) == 1
        assert results[0]["publish_date"] == "2026-06-09"


class TestSearchNewsErrors(_SearchNewsTestBase):
    def test_http_non_200_raises(self):
        with (
            patch.object(self.fetcher._session, "get", return_value=_mock_response("", status=500)),
            pytest.raises(DataFetchError),
        ):
            self.fetcher.search_news(q="603777")

    def test_jsonp_parse_error_raises(self):
        with (
            patch.object(
                self.fetcher._session, "get", return_value=_mock_response("not jsonp at all")
            ),
            pytest.raises(DataFetchError),
        ):
            self.fetcher.search_news(q="603777")

    def test_api_code_nonzero_raises(self):
        body = 'jQuery_cb({"code": 403, "msg": "rate limited", "result": {}})'
        with (
            patch.object(self.fetcher._session, "get", return_value=_mock_response(body)),
            pytest.raises(DataFetchError),
        ):
            self.fetcher.search_news(q="603777")

    def test_q_too_long_raises(self):
        with pytest.raises(DataFetchError):
            self.fetcher.search_news(q="x" * 201)

    def test_limit_out_of_range_raises(self):
        with pytest.raises(DataFetchError):
            self.fetcher.search_news(q="ok", limit=0)
        with pytest.raises(DataFetchError):
            self.fetcher.search_news(q="ok", limit=101)

    def test_limit_as_string_is_coerced(self):
        """limit is sent as a string from the explorer mini-form (HTML inputs
        yield strings). The fetcher must coerce to int and accept a valid
        numeric string, otherwise the comparison ``1 <= limit <= 100`` raises
        a raw TypeError that the manager treats as a network failure."""
        with patch.object(
            self.fetcher._session, "get", return_value=_mock_response(_load_fixture())
        ) as mock_get:
            results = self.fetcher.search_news(q="603777", limit="20")

        assert len(results) == 2
        assert mock_get.call_args.kwargs["params"]["cb"].startswith("jQuery")

    def test_limit_non_numeric_string_raises(self):
        """A non-numeric string can't be coerced — surface a clear
        DataFetchError rather than letting a TypeError leak out."""
        with pytest.raises(DataFetchError):
            self.fetcher.search_news(q="ok", limit="abc")

    def test_records_missing_critical_fields_are_skipped(self):
        # First record OK, second missing 'url', third missing 'date'
        body = (
            'jQuery_cb({"code":0,"hitsTotal":3,"msg":"OK","result":{"cmsArticleWebOld":['
            '{"date":"2026-06-09 16:36:00","title":"<em>603777</em>","url":"http://finance.eastmoney.com/a/1.html","mediaName":"A"},'
            '{"date":"2026-06-09 16:36:00","title":"missing url","mediaName":"B"},'
            '{"title":"missing date","url":"http://finance.eastmoney.com/a/3.html","mediaName":"C"}'
            "]}})"
        )
        with patch.object(self.fetcher._session, "get", return_value=_mock_response(body)):
            results = self.fetcher.search_news(q="603777")

        assert len(results) == 1
        assert results[0]["media_name"] == "A"


class TestSessionWarmup:
    """Verifies the cookie-seed warmup behavior added in the P0 hardening."""

    def test_warmup_fires_once_on_first_search(self):
        fetcher = EastMoneyFetcher()
        assert fetcher._news_warmed is False

        warmup_resp = _mock_response("<html>warmup</html>")
        search_resp = _mock_response(_load_fixture())

        # First call is the warmup GET to so.eastmoney.com; second is the
        # actual search. side_effect feeds them in order.
        with patch.object(
            fetcher._session, "get", side_effect=[warmup_resp, search_resp]
        ) as mock_get:
            fetcher.search_news(q="603777")

        assert len(mock_get.call_args_list) == 2
        assert mock_get.call_args_list[0].args[0] == EastMoneyFetcher._NEWS_WARMUP_URL
        assert mock_get.call_args_list[1].args[0] == EastMoneyFetcher._NEWS_SEARCH_URL
        assert fetcher._news_warmed is True

    def test_warmup_skipped_on_subsequent_calls(self):
        fetcher = EastMoneyFetcher()
        fetcher._news_warmed = True  # simulate already-warmed state

        with patch.object(
            fetcher._session, "get", return_value=_mock_response(_load_fixture())
        ) as mock_get:
            fetcher.search_news(q="603777")
            fetcher.search_news(q="603777")
            fetcher.search_news(q="603777")

        # Three searches, zero warmups.
        assert len(mock_get.call_args_list) == 3
        for call in mock_get.call_args_list:
            assert call.args[0] == EastMoneyFetcher._NEWS_SEARCH_URL

    def test_warmup_failure_is_non_fatal(self):
        """A network blip during warmup must not block the actual search."""
        fetcher = EastMoneyFetcher()

        with patch.object(
            fetcher._session,
            "get",
            side_effect=[ConnectionError("seed failed"), _mock_response(_load_fixture())],
        ):
            results = fetcher.search_news(q="603777")

        # Search still succeeded despite warmup raising.
        assert len(results) == 2
        assert fetcher._news_warmed is True


class TestSessionHeaders:
    """Verifies the browser-fingerprint base headers are set on the session
    at construction time (so every request inherits them)."""

    def test_session_has_chrome_desktop_fingerprint(self):
        fetcher = EastMoneyFetcher()
        h = fetcher._session.headers
        # Core browser fingerprint headers
        assert "User-Agent" in h
        assert "Chrome" in h["User-Agent"]
        assert "Windows" in h["User-Agent"]
        assert h["Referer"] == "https://so.eastmoney.com/news/s"
        assert h["Origin"] == "https://so.eastmoney.com"
        assert h["Accept-Language"].startswith("zh-CN")
        assert "Chromium" in h["sec-ch-ua"]
        assert h["sec-fetch-mode"] == "no-cors"
        assert h["sec-fetch-site"] == "same-site"
        # Cache-busting headers akshare also sends — missing these can trigger
        # the backend's "stale/replay" detection.
        assert h["Cache-Control"] == "no-cache"
        assert h["Pragma"] == "no-cache"


class TestNormalizeNewsItem:
    """Mirrors akshare's stock_news_em extraction logic."""

    BASE_REC = {
        "date": "2026-06-09 16:36:00",
        "code": "202606093765150130",
        "title": "白酒<em>概念</em>",
        "content": "正文内容",
        "mediaName": "证券时报网",
        "url": "http://finance.eastmoney.com/a/SHOULD_NOT_USE.html",
        "image": "https://example.com/img.png",
    }

    def test_url_is_rebuilt_from_code_field(self):
        """akshare always rebuilds URL from `code`, treating the upstream's
        `url` field as untrusted. Our BASE_REC provides a deliberately
        different upstream `url` to verify our impl matches akshare's."""
        item = EastMoneyFetcher._normalize_news_item(self.BASE_REC)
        assert item["url"] == "http://finance.eastmoney.com/a/202606093765150130.html"

    def test_url_falls_back_to_rec_url_when_code_missing(self):
        """Defensive: if upstream ever omits `code`, fall back to rec['url']."""
        rec = {**self.BASE_REC, "code": None}
        del rec["code"]  # truly missing
        item = EastMoneyFetcher._normalize_news_item(rec)
        assert item["url"] == self.BASE_REC["url"]

    def test_em_tags_stripped_from_title(self):
        item = EastMoneyFetcher._normalize_news_item(
            {**self.BASE_REC, "title": "白酒<em>概念</em>涨停"}
        )
        assert item["title"] == "白酒概念涨停"
        assert "<em>" not in item["title"]

    def test_em_tags_with_parens_stripped_from_title(self):
        """akshare's stock_news_em also removes the parenthesized variant
        ``(<em>...</em>)`` in addition to bare em tags — both parens and
        em tags go. Mirrors akshare's chained str.replace sequence."""
        item = EastMoneyFetcher._normalize_news_item(
            {**self.BASE_REC, "title": "白酒(<em>概念</em>)涨停"}
        )
        # The ( and ) are removed together with the em pair — see _strip_em.
        assert item["title"] == "白酒概念涨停"
        assert "<em>" not in item["title"]
        assert "(" not in item["title"]
        assert ")" not in item["title"]

    def test_em_tags_stripped_from_snippet(self):
        item = EastMoneyFetcher._normalize_news_item(
            {**self.BASE_REC, "content": "<em>白酒</em>板块异动"}
        )
        assert item["snippet"] == "白酒板块异动"
        assert "<em>" not in item["snippet"]

    def test_full_width_space_stripped_from_snippet(self):
        """akshare strips 　 (U+3000) from content — these appear as
        padding/indentation in upstream article snippets."""
        item = EastMoneyFetcher._normalize_news_item({**self.BASE_REC, "content": "　白酒　板块　"})
        assert item["snippet"] == "白酒板块"

    def test_crlf_collapsed_to_single_space_in_snippet(self):
        """akshare replaces \\r\\n in content with a single space."""
        item = EastMoneyFetcher._normalize_news_item(
            {**self.BASE_REC, "content": "第一段\r\n第二段\r\n第三段"}
        )
        assert item["snippet"] == "第一段 第二段 第三段"

    def test_publish_date_truncated_to_yyyy_mm_dd(self):
        item = EastMoneyFetcher._normalize_news_item(self.BASE_REC)
        assert item["publish_date"] == "2026-06-09"

    def test_source_domain_extracted_from_constructed_url(self):
        item = EastMoneyFetcher._normalize_news_item(self.BASE_REC)
        assert item["source_domain"] == "finance.eastmoney.com"

    def test_media_name_passes_through(self):
        item = EastMoneyFetcher._normalize_news_item(self.BASE_REC)
        assert item["media_name"] == "证券时报网"

    def test_missing_media_name_defaults_to_empty_string(self):
        rec = {**self.BASE_REC}
        del rec["mediaName"]
        item = EastMoneyFetcher._normalize_news_item(rec)
        assert item["media_name"] == ""
