"""Tests for ClsFetcher — uses real-upstream-shape fixtures from
tests/fixtures/cls_*.json (per project memory: fixture must mirror real
upstream, not just field names/types)."""

import json
import pathlib

import pytest

from stock_data.data_provider.base import DataFetchError
from stock_data.data_provider.fetchers.cls_fetcher import ClsFetcher

FIXTURE_DIR = pathlib.Path(__file__).parent / "fixtures"


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
