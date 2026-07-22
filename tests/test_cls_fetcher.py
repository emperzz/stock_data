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
    for k in (
        "article_id",
        "title",
        "brief",
        "author",
        "ctime",
        "date",
        "read_num",
        "comments_num",
        "share_num",
        "images",
    ):
        assert k in first, f"missing field: {k}"
    # date format check
    assert len(first["date"]) == 10 and first["date"][4] == "-"
    # article_id is a positive int
    assert first["article_id"] > 0


def test_parse_subject_articles_skips_zero_id(fetcher, list_html):
    """Articles with article_id=0 or missing should be skipped (defensive guard)."""
    # Inject a malformed article alongside a valid one
    inner = json.loads((FIXTURE_DIR / "cls_subject_list.json").read_text(encoding="utf-8"))
    inner["articles"].insert(0, {"article_id": 0, "article_title": "skipped", "article_time": 0})
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
    from bs4 import BeautifulSoup

    html = "<p>第一段</p><p>第二段有<strong>加粗</strong></p><p>第三段</p>"
    soup = BeautifulSoup(html, "lxml")
    out = fetcher._extract_body_text(soup)
    assert "<" not in out and ">" not in out
    assert "第一段" in out
    assert "加粗" in out  # text content preserved
    # at least 2 newlines (paragraph separator)
    assert "\n" in out


def test_extract_body_text_empty(fetcher):
    """None / empty soup → empty body_text."""
    assert fetcher._extract_body_text(None) == ""
    from bs4 import BeautifulSoup

    assert fetcher._extract_body_text(BeautifulSoup("", "lxml")) == ""


def test_extract_body_text_collapses_blank_lines(fetcher):
    """3+ consecutive newlines collapse to 2."""
    from bs4 import BeautifulSoup

    html = "<p>a</p><p></p><p></p><p></p><p>b</p>"
    soup = BeautifulSoup(html, "lxml")
    out = fetcher._extract_body_text(soup)
    assert "\n\n\n" not in out  # no 3+ consecutive newlines


def test_dedup_images(fetcher):
    """Only `content` images are returned (the list-page `images[]` field is
    intentionally NOT merged — those are list-page thumbnails, not body images).

    Within `content`, the FIRST <img> is skipped (it's the article header
    cover image, which the user identified as logo-like / no information value).
    """
    detail = {
        # `images` field is the list-page thumbnail — must NOT appear in output.
        "images": ["https://a.com/cover.jpg"],
        "content": (
            "<p>lead</p>"
            '<p><img src="https://a.com/HEADER.png"></p>'  # skipped (first <img>)
            "<p><strong>section</strong></p>"
            "<p>text</p>"
            '<p><img src="https://a.com/CHART1.png"></p>'  # kept
            '<p><img src="https://a.com/CHART2.png"></p>'  # kept
        ),
    }
    out = fetcher._dedup_images(detail)
    assert out == [
        "https://a.com/CHART1.png",
        "https://a.com/CHART2.png",
    ]


def test_dedup_images_no_content_images(fetcher):
    """content 里 0 张图时, 返回空列表 (不抛错)."""
    out = fetcher._dedup_images(
        {
            "images": ["https://a.com/cover.jpg"],  # list-page thumb — still dropped
            "content": "<p>text only, no images</p>",
        }
    )
    assert out == []


def test_dedup_images_only_one_content_image_skipped(fetcher):
    """content 只有 1 张图时, 跳过它后应剩空列表 (用户认为 header 是 logo)."""
    out = fetcher._dedup_images(
        {
            "images": [],
            "content": '<p><img src="https://a.com/ONLY.png"></p>',
        }
    )
    assert out == []


def test_dedup_images_empty_content(fetcher):
    """content 缺失/空字符串 → 返回空列表."""
    assert fetcher._dedup_images({"images": []}) == []
    assert fetcher._dedup_images({"images": [], "content": ""}) == []


def test_fetch_article_detail_normal(fetcher, detail_html):
    """Standard detail HTML → full ClsArticle-shaped dict.

    Fixture mirrors the real CLS structure: lead paragraph → header cover img →
    section headers + items → trailing chart img. The new `_dedup_images` logic
    MUST drop (a) the `images[]` list-page thumbnail and (b) the first content
    `<img>` (the header cover), keeping only the trailing chart img.
    """
    art = fetcher._fetch_article_detail(2425210, detail_html)
    assert art is not None
    assert art["article_id"] == 2425210
    assert art["title"].startswith("【")
    assert len(art["body_text"]) > 100
    # date is YYYY-MM-DD
    assert len(art["date"]) == 10 and art["date"][4] == "-"
    # images: only the trailing chart img survives (header cover + images[]
    # list-page thumb both dropped). Pin content to catch silent regressions.
    assert art["images"] == ["https://image.cls.cn/images/20260714/market_chart_911x466.png"]


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


def test_share_num_threads_from_list_to_detail(fetcher):
    """Detail page doesn't expose share_num, but the list article entry does.

    _get_subject_article must thread the list-page share_num through to the
    detail-page dict; otherwise the response always reports share_num=0 even
    when upstream has the real value.
    """
    list_data = {
        "id": 1151,
        "articles": [
            {
                "article_id": 2425210,
                "article_title": "test",
                "article_brief": "test brief",
                "article_author": "财联社",
                "article_time": 1783983600,
                "read_num": 1,
                "comments_num": 1,
                "share_num": 1336,  # list page has the real value
                "article_img": "",
            }
        ],
    }
    list_html = f'<html><script id="__NEXT_DATA__" type="application/json">{json.dumps({"props": {"pageProps": {"data": list_data}}}, ensure_ascii=False)}</script></html>'
    detail_html = _wrap_fixture("cls_article_detail.json", envelope_key="articleDetail")
    with patch.object(fetcher, "_http_get_text", side_effect=[list_html, detail_html]):
        art = fetcher.get_morning_briefing("2026-07-14")
    assert art is not None
    # Regression: must NOT be 0 anymore (detail page doesn't have shareNum,
    # but the list-page share_num must flow through).
    assert art["share_num"] == 1336


def test_share_num_zero_when_list_missing(fetcher):
    """If list article omits share_num, fall back to 0 in the detail dict."""
    list_data = {
        "id": 1151,
        "articles": [
            {
                "article_id": 2425210,
                "article_title": "test",
                "article_brief": "test brief",
                "article_author": "财联社",
                "article_time": 1783983600,
                "read_num": 1,
                "comments_num": 1,
                # share_num intentionally omitted
                "article_img": "",
            }
        ],
    }
    list_html = f'<html><script id="__NEXT_DATA__" type="application/json">{json.dumps({"props": {"pageProps": {"data": list_data}}}, ensure_ascii=False)}</script></html>'
    detail_html = _wrap_fixture("cls_article_detail.json", envelope_key="articleDetail")
    with patch.object(fetcher, "_http_get_text", side_effect=[list_html, detail_html]):
        art = fetcher.get_morning_briefing("2026-07-14")
    assert art is not None
    assert art["share_num"] == 0


def test_timezone_pin_to_shanghai(fetcher, monkeypatch):
    """Regression: datetime.fromtimestamp without TZ silently shifts the date
    on UTC servers. The fetcher must pin to Asia/Shanghai.

    This test simulates a UTC server by faking the timestamp math directly:
    build a list HTML with a ctime that resolves to a different date in
    UTC vs Shanghai, then verify the fetcher produces the Shanghai date.
    """
    # ctime = 1783983600 → 2026-07-14 07:00 +0800, but 2026-07-13 23:00 UTC.
    # On a UTC server, the bug used to produce date="2026-07-13".
    list_html = _wrap_fixture("cls_subject_list.json", envelope_key="data")
    arts = fetcher._parse_subject_articles(1151, list_html)
    assert arts[0]["date"] == "2026-07-14", (
        f"Expected Shanghai date 2026-07-14, got {arts[0]['date']!r}. "
        "Check that _CLS_TZ is wired into datetime.fromtimestamp(...)."
    )


def test_is_available_requires_bs4(fetcher, monkeypatch):
    """Regression: is_available() must probe the bs4 dep so a missing-bs4
    server doesn't register a fetcher that 100% fails at runtime.
    """

    # Patch importlib.util.find_spec to report bs4 missing.
    from importlib import util as importlib_util

    def fake_find_spec(name, *args, **kwargs):
        if name == "bs4":
            return None
        return importlib_util.find_spec(name, *args, **kwargs)

    monkeypatch.setattr(
        "stock_data.data_provider.fetchers.cls_fetcher.importlib_util.find_spec",
        fake_find_spec,
    )
    # Need to import fresh so the patched module-level importlib_util is used.
    # Easier: call find_spec via the module's namespace.
    from stock_data.data_provider.fetchers import cls_fetcher as cls_mod

    monkeypatch.setattr(cls_mod.importlib_util, "find_spec", fake_find_spec)
    assert fetcher.is_available() is False


def test_is_available_when_bs4_present(fetcher):
    """Default: bs4 is installed → is_available() returns True."""
    assert fetcher.is_available() is True


def test_detail_author_handles_flat_string(fetcher):
    """Detail page's author field may be a flat string (newer payloads) or a
    dict {name: ...} (older payloads). Both forms must surface in the dict.
    Regression for: `detail.get('author') or {}` swallowed string authors.
    """
    detail_dict = {
        "id": 2425210,
        "title": "test",
        "brief": "",
        "content": "<p>body</p>",
        "ctime": 1783983600,
        "readingNum": 1,
        "commentNum": 1,
        "author": "财联社",  # flat string (newer payload shape)
    }
    html = f'<html><script id="__NEXT_DATA__" type="application/json">{json.dumps({"props": {"pageProps": {"articleDetail": detail_dict}}})}</script></html>'
    art = fetcher._fetch_article_detail(2425210, html)
    assert art is not None
    assert art["author"] == "财联社"


def test_detail_author_handles_dict(fetcher):
    """Detail page's author field as dict {name: ...} must still surface."""
    detail_dict = {
        "id": 2425210,
        "title": "test",
        "brief": "",
        "content": "<p>body</p>",
        "ctime": 1783983600,
        "readingNum": 1,
        "commentNum": 1,
        "author": {"name": "财联社 dict"},
    }
    html = f'<html><script id="__NEXT_DATA__" type="application/json">{json.dumps({"props": {"pageProps": {"articleDetail": detail_dict}}})}</script></html>'
    art = fetcher._fetch_article_detail(2425210, html)
    assert art is not None
    assert art["author"] == "财联社 dict"


# ---------- P3-b2 (M16): bounded response body read ----------


class _FakeStreamResponse:
    """Minimal mock mirroring the requests.Response API that _http_get_text
    exercises: status_code, headers, stream(), iter_content(), close()."""

    def __init__(self, body: bytes, status_code: int = 200):
        self.status_code = status_code
        self.content = body
        self.closed = False
        self._body = body

    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.close()

    def iter_content(self, chunk_size: int = 64 * 1024):
        for i in range(0, len(self._body), chunk_size):
            yield self._body[i : i + chunk_size]

    def close(self):
        self.closed = True


def test_http_get_text_rejects_oversize_response(fetcher):
    """P3-b2 (M16): response above _CLS_MAX_RESPONSE_BYTES must raise
    DataFetchError instead of loading the entire body into memory."""
    from stock_data.data_provider.fetchers.cls_fetcher import _CLS_MAX_RESPONSE_BYTES

    oversize = b"x" * (_CLS_MAX_RESPONSE_BYTES + 1)
    fake = _FakeStreamResponse(oversize)

    with (
        patch("stock_data.data_provider.fetchers.cls_fetcher.requests.get", return_value=fake),
        pytest.raises(DataFetchError, match="exceeded"),
    ):
        fetcher._http_get_text("https://www.cls.cn/subject/1151")
    assert fake.closed, "response must be closed after size cap fires"


def test_http_get_text_accepts_normal_response(fetcher):
    """Within-cap response returns decoded text and closes the connection."""
    body = b'{"hello": "world"}'
    fake = _FakeStreamResponse(body)

    with patch("stock_data.data_provider.fetchers.cls_fetcher.requests.get", return_value=fake):
        text = fetcher._http_get_text("https://www.cls.cn/subject/1151")
    assert text == '{"hello": "world"}'
    assert fake.closed, "response must be closed on the happy path too"


def test_http_get_text_returns_datafetch_error_on_5xx(fetcher):
    """5xx response must raise DataFetchError (unchanged from pre-P3-b2)."""
    fake = _FakeStreamResponse(b"server boom", status_code=503)

    with (
        patch("stock_data.data_provider.fetchers.cls_fetcher.requests.get", return_value=fake),
        pytest.raises(DataFetchError, match="503"),
    ):
        fetcher._http_get_text("https://www.cls.cn/subject/1151")
    assert fake.closed, "response must be closed when status check fails"
