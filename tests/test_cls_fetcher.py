"""Tests for ClsFetcher — uses real-upstream-shape fixtures from
tests/fixtures/cls_*.json (per project memory: fixture must mirror real
upstream, not just field names/types)."""

import json
import pathlib
from unittest.mock import patch

import pytest

from stock_data.data_provider.base import DataFetchError
from stock_data.data_provider.fetchers.cls_fetcher import ClsFetcher

FIXTURE_DIR = pathlib.Path(__file__).parent / "fixtures"


def _wrap_fixture(filename: str, *, envelope_key: str) -> str:
    """Helper: wrap a fixture JSON in the full __NEXT_DATA__ envelope the way CLS SSR does.

    The fixture file is the inner object (e.g. `data` for list, `articleDetail` for detail).
    The wrapper adds the upstream `props.pageProps` envelope so the fetcher can
    navigate `.props.pageProps.<envelope_key>.<...>` correctly.
    """
    inner = json.loads((FIXTURE_DIR / filename).read_text(encoding="utf-8"))
    envelope = {"props": {"pageProps": {envelope_key: inner}}}
    return f'<html><body><script id="__NEXT_DATA__" type="application/json">{json.dumps(envelope, ensure_ascii=False)}</script></body></html>'


@pytest.fixture
def fetcher() -> ClsFetcher:
    return ClsFetcher()


@pytest.fixture
def list_html() -> str:
    """Wrap fixture JSON in the full __NEXT_DATA__ envelope the way CLS SSR does.

    The fixture file is the inner `data` object (what the fetcher sees at
    `__NEXT_DATA__.props.pageProps.data`). The wrapper adds the upstream
    `props.pageProps` envelope around it so the fetcher can navigate
    `.props.pageProps.data.articles[]` correctly.
    """
    inner = json.loads((FIXTURE_DIR / "cls_subject_list.json").read_text(encoding="utf-8"))
    envelope = {"props": {"pageProps": {"data": inner}}}
    return f'<html><body><script id="__NEXT_DATA__" type="application/json">{json.dumps(envelope, ensure_ascii=False)}</script></body></html>'


@pytest.fixture
def detail_html() -> str:
    """Same wrapping pattern as list_html, but for the detail page (articleDetail)."""
    inner = json.loads((FIXTURE_DIR / "cls_article_detail.json").read_text(encoding="utf-8"))
    envelope = {"props": {"pageProps": {"articleDetail": inner}}}
    return f'<html><body><script id="__NEXT_DATA__" type="application/json">{json.dumps(envelope, ensure_ascii=False)}</script></body></html>'


def test_parse_next_data_valid(fetcher, list_html):
    """Standard SSR HTML → returns parsed JSON envelope dict.

    The fetcher returns the full __NEXT_DATA__ envelope; downstream callers
    navigate `.props.pageProps.data` (list) or `.props.pageProps.articleDetail`
    (detail) to reach the page-specific payload.
    """
    result = fetcher._parse_next_data(list_html)
    assert isinstance(result, dict)
    data = result["props"]["pageProps"]["data"]
    assert data["id"] == 1151
    assert "article_id" in data["articles"][0]


def test_parse_next_data_empty_html(fetcher):
    """Empty HTML body → DataFetchError."""
    with pytest.raises(DataFetchError, match="empty HTML body"):
        fetcher._parse_next_data("")


def test_parse_next_data_no_script_tag(fetcher):
    """HTML without __NEXT_DATA__ → DataFetchError."""
    with pytest.raises(DataFetchError, match="__NEXT_DATA__ script tag not found"):
        fetcher._parse_next_data("<html><body>no script here</body></html>")


def test_parse_next_data_malformed_json(fetcher):
    """Truncated JSON inside the script tag → DataFetchError."""
    bad = '<script id="__NEXT_DATA__" type="application/json">{"id": 1151,</script>'
    with pytest.raises(DataFetchError, match="JSON parse failed"):
        fetcher._parse_next_data(bad)


def test_parse_subject_articles_normal(fetcher, list_html):
    """Standard list HTML → returns normalized list."""
    arts = fetcher._parse_subject_articles(1151, list_html)
    assert isinstance(arts, list)
    assert len(arts) >= 1
    first = arts[0]
    # All canonical fields present
    for k in ("article_id", "title", "brief", "author", "ctime", "date", "read_num", "comments_num", "share_num", "images"):
        assert k in first, f"missing field: {k}"
    # date format check
    assert len(first["date"]) == 10 and first["date"][4] == "-"
    # article_id is a positive int
    assert first["article_id"] > 0


def test_parse_subject_articles_skips_zero_id(fetcher, list_html):
    """Articles with article_id=0 or missing should be skipped (defensive guard)."""
    # Inject a malformed article alongside a valid one
    inner = json.loads(
        (FIXTURE_DIR / "cls_subject_list.json").read_text(encoding="utf-8")
    )
    inner["articles"].insert(
        0, {"article_id": 0, "article_title": "skipped", "article_time": 0}
    )
    envelope = {"props": {"pageProps": {"data": inner}}}
    html = f'<html><script id="__NEXT_DATA__" type="application/json">{json.dumps(envelope, ensure_ascii=False)}</script></html>'
    arts = fetcher._parse_subject_articles(1151, html)
    # None of the returned articles should be the zero-id one
    assert all(a["article_id"] != 0 for a in arts)
    assert len(arts) >= 1


def test_parse_subject_articles_zero_values_not_treated_as_missing(fetcher):
    """read_num=0 / comments_num=0 should be preserved as 0, not None.

    Regression test for the `or default` anti-pattern: if someone replaces
    `safe_int(x, default=0)` with `safe_int(x) or 0`, a 0 value would be
    treated as missing and converted to None (or fail the int() cast).
    """
    inner = {
        "id": 1151,
        "articles": [
            {
                "article_id": 12345,
                "article_title": "zero-test",
                "article_brief": "test",
                "article_author": "test",
                "article_time": 1783983600,
                "read_num": 0,
                "comments_num": 0,
                "share_num": 0,
                "article_img": "",
            }
        ],
    }
    envelope = {"props": {"pageProps": {"data": inner}}}
    html = f'<html><script id="__NEXT_DATA__" type="application/json">{json.dumps(envelope, ensure_ascii=False)}</script></html>'
    arts = fetcher._parse_subject_articles(1151, html)
    assert len(arts) == 1
    assert arts[0]["read_num"] == 0
    assert arts[0]["comments_num"] == 0
    assert arts[0]["share_num"] == 0


def test_parse_subject_articles_limit(fetcher, list_html):
    """limit=2 → returns at most 2 articles."""
    arts = fetcher._parse_subject_articles(1151, list_html, limit=2)
    assert len(arts) <= 2


def test_parse_subject_articles_empty(fetcher):
    """HTML with empty articles list → returns []."""
    empty_html = '<html><script id="__NEXT_DATA__" type="application/json">{"props":{"pageProps":{"data":{"id":1151,"articles":[]}}}}</script></html>'
    arts = fetcher._parse_subject_articles(1151, empty_html)
    assert arts == []


def test_find_article_id_by_date_match(fetcher, list_html):
    """Find article_id for a date that exists in the fixture."""
    arts = fetcher._parse_subject_articles(1151, list_html)
    assert len(arts) >= 1
    target_date = arts[0]["date"]
    found = fetcher._find_article_id_by_date(arts, target_date)
    assert found == arts[0]["article_id"]


def test_find_article_id_by_date_no_match(fetcher, list_html):
    """Date that doesn't appear in the fixture → None."""
    arts = fetcher._parse_subject_articles(1151, list_html)
    assert fetcher._find_article_id_by_date(arts, "2020-01-01") is None


def test_extract_body_text_strips_html(fetcher):
    """body_text has no HTML tags, preserves paragraph separators."""
    html = "<p>第一段</p><p>第二段有<strong>加粗</strong></p><p>第三段</p>"
    out = fetcher._extract_body_text(html)
    assert "<" not in out and ">" not in out
    assert "第一段" in out
    assert "加粗" in out  # text content preserved
    # at least 2 newlines (paragraph separator)
    assert "\n" in out


def test_extract_body_text_empty(fetcher):
    assert fetcher._extract_body_text("") == ""


def test_extract_body_text_collapses_blank_lines(fetcher):
    """3+ consecutive newlines collapse to 2."""
    html = "<p>a</p><p></p><p></p><p></p><p>b</p>"
    out = fetcher._extract_body_text(html)
    assert "\n\n\n" not in out  # no 3+ consecutive newlines


def test_dedup_images(fetcher):
    detail = {
        "images": ["https://a.com/1.jpg", "https://a.com/2.jpg"],
        "content": '<p><img src="https://a.com/2.jpg"></p><p><img src="https://a.com/3.jpg"></p>',
    }
    out = fetcher._dedup_images(detail)
    assert out == [
        "https://a.com/1.jpg",  # from images field
        "https://a.com/2.jpg",  # appears in both — first occurrence wins
        "https://a.com/3.jpg",  # from content
    ]


def test_fetch_article_detail_normal(fetcher, detail_html):
    """Standard detail HTML → full ClsArticle-shaped dict."""
    art = fetcher._fetch_article_detail(2425210, detail_html)
    assert art is not None
    assert art["article_id"] == 2425210
    assert art["title"].startswith("【")
    assert len(art["body_text"]) > 100
    # date is YYYY-MM-DD
    assert len(art["date"]) == 10 and art["date"][4] == "-"
    # images is a list (possibly empty)
    assert isinstance(art["images"], list)


def test_fetch_article_detail_empty_dict(fetcher):
    """__NEXT_DATA__ with empty articleDetail → None."""
    html = '<html><script id="__NEXT_DATA__" type="application/json">{"props":{"pageProps":{"articleDetail":{}}}}</script></html>'
    assert fetcher._fetch_article_detail(99999, html) is None


def test_fetch_article_detail_id_mismatch_raises(fetcher, detail_html):
    """Caller passes a different article_id than the served detail → DataFetchError.

    Defensive check against upstream drift: if /detail/{A}/ starts
    serving article B, fail loud instead of silently serving the wrong
    article.
    """
    with pytest.raises(DataFetchError, match="article_id mismatch"):
        # detail fixture is article 2425210; pass a different id
        fetcher._fetch_article_detail(99999, detail_html)


def test_get_morning_briefing_full_path(fetcher):
    """Mock list+detail HTTP → full article dict returned."""
    list_html = _wrap_fixture("cls_subject_list.json", envelope_key="data")
    detail_html = _wrap_fixture("cls_article_detail.json", envelope_key="articleDetail")
    with patch.object(fetcher, "_http_get_text", side_effect=[list_html, detail_html]) as m:
        # pick a date that exists in the list fixture
        arts = fetcher._parse_subject_articles(1151, list_html)
        target_date = arts[0]["date"]
        art = fetcher.get_morning_briefing(target_date)
    assert art is not None
    assert art["article_id"] == 2425210
    assert len(art["body_text"]) > 100
    # 2 HTTP calls (list + detail)
    assert m.call_count == 2


def test_get_morning_briefing_not_found(fetcher):
    """Date not in list → returns None (only 1 HTTP call — no detail fetch)."""
    list_html = _wrap_fixture("cls_subject_list.json", envelope_key="data")
    with patch.object(fetcher, "_http_get_text", return_value=list_html) as m:
        art = fetcher.get_morning_briefing("2020-01-01")
    assert art is None
    # Only 1 HTTP call (list); no detail fetch on not-found
    assert m.call_count == 1


def test_get_market_recap_full_path(fetcher):
    """Same as morning_briefing but for subject 1135."""
    # Build a synthetic list HTML for subject 1135 with one article on a known date.
    # The article_id MUST match the detail fixture's id (2425210), because
    # _fetch_article_detail has a defensive mismatch check.
    list_data = {
        "id": 1135,
        "articles": [
            {
                "article_id": 2425210,
                "article_title": "【焦点复盘】test",
                "article_brief": "test brief",
                "article_author": "财联社",
                "article_time": 1783983600,  # 2026-07-14
                "read_num": 100,
                "comments_num": 10,
                "share_num": 100,
                "article_img": "",
            }
        ],
    }
    list_html = f'<html><script id="__NEXT_DATA__" type="application/json">{json.dumps({"props": {"pageProps": {"data": list_data}}}, ensure_ascii=False)}</script></html>'
    detail_html = _wrap_fixture("cls_article_detail.json", envelope_key="articleDetail")
    with patch.object(fetcher, "_http_get_text", side_effect=[list_html, detail_html]):
        art = fetcher.get_market_recap("2026-07-14")
    assert art is not None
    assert art["article_id"] == 2425210  # from the detail fixture


def test_get_morning_briefing_http_failure(fetcher):
    """If list HTTP fails → DataFetchError propagates (no swallow)."""
    with (
        patch.object(fetcher, "_http_get_text", side_effect=DataFetchError("network down")),
        pytest.raises(DataFetchError, match="network down"),
    ):
        fetcher.get_morning_briefing("2026-07-14")
