"""Tests for NewsContentExtractor handlers and structured failure states."""

from pathlib import Path
from types import SimpleNamespace

import pytest
import requests

from stock_data.data_provider.utils import news_extractor
from stock_data.data_provider.utils.news_extractor import NewsContentExtractor

_FIXTURES = Path(__file__).resolve().parent / "fixtures" / "news_content"


def _fixture(name: str) -> str:
    return (_FIXTURES / name).read_text(encoding="utf-8")


@pytest.fixture(autouse=True)
def bypass_ssrf(monkeypatch):
    """Keep HTML parsing tests independent of local DNS."""
    monkeypatch.setattr(news_extractor, "_is_private_ip", lambda host: False)
    yield


def test_network_error_returns_structured_fetch_error(monkeypatch):
    def fail(*args, **kwargs):
        raise requests.Timeout("timed out")

    monkeypatch.setattr(news_extractor.requests, "get", fail)
    result = NewsContentExtractor.extract("https://example.com/news")
    assert result.content_status == "fetch_error"
    assert result.http_status is None


def test_redirect_to_private_still_raises(monkeypatch):
    response = SimpleNamespace(url="http://127.0.0.1/secret", status_code=200, text="")
    monkeypatch.setattr(news_extractor, "_is_private_ip", lambda host: host == "127.0.0.1")
    monkeypatch.setattr(news_extractor.requests, "get", lambda *a, **k: response)
    with pytest.raises(ValueError, match="internal network"):
        NewsContentExtractor.extract("https://example.com/news")


def test_http_403_returns_blocked_status(monkeypatch):
    response = SimpleNamespace(
        url="https://example.com/blocked", status_code=403, text="Access Denied"
    )
    monkeypatch.setattr(news_extractor.requests, "get", lambda *a, **k: response)
    result = NewsContentExtractor.extract("https://example.com/blocked")
    assert result.content_status == "blocked"
    assert result.http_status == 403
    assert result.body == ""


def test_http_500_returns_fetch_error_status(monkeypatch):
    response = SimpleNamespace(
        url="https://example.com/error", status_code=500, text="upstream error"
    )
    monkeypatch.setattr(news_extractor.requests, "get", lambda *a, **k: response)
    result = NewsContentExtractor.extract("https://example.com/error")
    assert result.content_status == "fetch_error"
    assert result.http_status == 500
    assert result.body == ""


def test_success_has_structured_status_and_metadata():
    result = NewsContentExtractor.extract(
        "https://example.com/article", html=_fixture("generic_metadata.html")
    )
    assert result.content_status == "ok"
    assert result.reason is None
    assert result.http_status is None
    assert result.title == "OG title"
    assert result.publish_date == "2026-07-15"
    assert result.author == "JSON Author"
    assert result.body
    assert result.byte_size == len(result.body.encode("utf-8"))


def test_json_ld_graph_metadata_is_extracted():
    html = """
    <html><body>
      <article><p>This article body is long enough to pass the generic extraction threshold.</p></article>
      <script type="application/ld+json">
        {"@context":"https://schema.org","@graph":[
          {"@type":"NewsArticle","headline":"Graph title","datePublished":"2026-07-15T09:30:00+08:00","author":{"name":"Graph Author"}}
        ]}
      </script>
    </body></html>
    """
    result = NewsContentExtractor.extract("https://example.com/graph", html=html)
    assert result.title == "Graph title"
    assert result.publish_date == "2026-07-15"
    assert result.author == "Graph Author"


def test_oversized_response_returns_fetch_error(monkeypatch):
    response = SimpleNamespace(
        url="https://example.com/large",
        status_code=200,
        headers={},
        iter_content=lambda chunk_size: iter(
            [b"x" * (news_extractor._MAX_RESPONSE_BYTES + 1)]
        ),
    )
    monkeypatch.setattr(news_extractor.requests, "get", lambda *a, **k: response)
    result = NewsContentExtractor.extract(response.url)
    assert result.content_status == "fetch_error"
    assert "5 MiB" in (result.reason or "")


def test_handler_typeerror_is_not_retried_as_legacy_handler():
    calls = []

    def broken_handler(url, html):
        calls.append((url, html))
        raise TypeError("handler body bug")

    NewsContentExtractor.register_domain_handler("typeerror.example", broken_handler)
    try:
        with pytest.raises(TypeError, match="handler body bug"):
            NewsContentExtractor.extract(
                "https://typeerror.example/news", html="<html></html>"
            )
    finally:
        NewsContentExtractor.unregister_domain_handler("typeerror.example")
    assert len(calls) == 1


def test_marker_text_in_real_article_is_not_blocked():
    html = """
    <html><body><article><p>This article discusses captcha and access denied messages in cybersecurity reporting, but it is a normal article body with enough text to pass extraction.</p></article></body></html>
    """
    result = NewsContentExtractor.extract("https://example.com/security", html=html)
    assert result.content_status == "ok"
    assert result.body


def test_extracts_canonical_url_from_generic_page():
    html = """
    <html><head><link rel="canonical" href="https://example.com/canonical"></head>
    <body><article><p>This generic article contains enough text to pass the body threshold and expose canonical metadata.</p></article></body></html>
    """
    result = NewsContentExtractor.extract("https://example.com/original", html=html)
    assert result.canonical_url == "https://example.com/canonical"


def test_decodes_gb18030_response(monkeypatch):
    html = """
    <html><body><article><p>这是一个使用 GB18030 编码的新闻正文，包含足够的中文内容用于验证解码过程。本文继续补充第二句内容，确保正文长度达到通用抽取阈值。encoding verification text keeps this fixture above the generic body threshold.</p></article></body></html>
    """
    response = SimpleNamespace(
        url="https://news.10jqka.com.cn/encoding.html",
        status_code=200,
        content=html.encode("gb18030"),
        headers={"Content-Type": "text/html"},
        apparent_encoding="gb18030",
    )
    monkeypatch.setattr(news_extractor.requests, "get", lambda *a, **k: response)
    result = NewsContentExtractor.extract(response.url)
    assert result.content_status == "ok"
    assert "GB18030 编码的新闻正文" in result.body


def test_js_shell_with_noscript_body_is_extractable():
    html = """
    <html><head><script>window.__NEXT_DATA__ = {};</script></head>
    <body><div id="app"></div><noscript>这是 JS 壳页面中仍然提供的服务端正文，包含足够的文字用于直接提取。本文继续补充第二句内容，确保 noscript 正文超过检测阈值。</noscript></body></html>
    """
    result = NewsContentExtractor.extract("https://example.com/app", html=html)
    assert result.content_status == "ok"
    assert result.extractor == "generic_noscript"
    assert "服务端正文" in result.body


def test_js_shell_returns_structured_status():
    result = NewsContentExtractor.extract(
        "https://example.com/app", html=_fixture("js_shell.html")
    )
    assert result.content_status == "javascript_required"
    assert result.body == ""
    assert result.byte_size == 0


def test_block_page_returns_blocked_status():
    result = NewsContentExtractor.extract(
        "https://example.com/blocked", html=_fixture("blocked.html")
    )
    assert result.content_status == "blocked"
    assert result.body == ""


class TestDefaultHandler:
    def test_finds_article_tag(self):
        html = """
        <html><body>
          <nav>navigation</nav>
          <article><p>Hello world with a sufficiently long first paragraph.</p><p>Second paragraph contains enough text to satisfy the generic article threshold.</p></article>
          <footer>copyright</footer>
        </body></html>
        """
        result = NewsContentExtractor.extract("https://example.com/news/1", html=html)
        assert "Hello world with a sufficiently long" in result.body
        assert "Second paragraph contains enough text" in result.body
        assert result.extractor == "generic_article"

    def test_falls_back_to_div_content(self):
        html = """
        <html><body>
          <div class="content"><p>Inside content div with enough text to satisfy the generic content threshold and return a real body.</p></div>
        </body></html>
        """
        result = NewsContentExtractor.extract("https://example.com/x", html=html)
        assert "Inside content div" in result.body

    def test_strips_script_and_style(self):
        html = """
        <html><body>
          <article>
            <script>alert('x')</script>
            <style>body{}</style>
            <p>Real content with enough text to satisfy the generic extraction threshold and remain visible.</p>
          </article>
        </body></html>
        """
        result = NewsContentExtractor.extract("https://example.com/x", html=html)
        assert "Real content" in result.body
        assert "alert" not in result.body
        assert "body{}" not in result.body

    def test_short_body_returns_structured_status(self):
        html = "<html><body><nav>only nav</nav></body></html>"
        result = NewsContentExtractor.extract("https://example.com/x", html=html)
        assert result.content_status in {"empty", "unsupported"}
        assert result.body == ""

    def test_extracts_title_from_og_meta(self):
        html = """
        <html>
          <head>
            <meta property="og:title" content="OG Title Here">
          </head>
          <body><article><p>Body content here for length test with enough additional text to satisfy the generic threshold.</p></article></body>
        </html>
        """
        result = NewsContentExtractor.extract("https://example.com/x", html=html)
        assert result.title == "OG Title Here"


class TestDomainDispatch:
    def test_eastmoney_standard_fixture_is_covered(self):
        result = NewsContentExtractor.extract(
            "https://finance.eastmoney.com/a/test.html",
            html=_fixture("eastmoney_standard.html"),
        )
        assert result.content_status == "ok"
        assert result.extractor == "eastmoney_v1"
        assert result.canonical_url == "https://finance.eastmoney.com/a/test.html"

    def test_eastmoney_domain_routes_to_em_handler(self):
        em_html = """
        <html><body>
          <div class="topbox">A Test Title\n2026年06月15日 11:32 来源： TestMedia </div>
          <div class="contentbox">
            <p>在东方财富看资讯行情, 选东方财富证券一站式开户交易>></p>
            <p>这是第一段真正的正文内容。包含一些有意义的文字。</p>
            <p>第二段继续讨论相关话题,内容比较长以通过长度检查。</p>
            <p>文章来源: test</p>
            <p>责任编辑: 1</p>
          </div>
        </body></html>
        """
        result = NewsContentExtractor.extract(
            "https://finance.eastmoney.com/a/202606153771411317.html", html=em_html
        )
        assert result.extractor == "eastmoney_v1"
        assert result.title == "A Test Title"
        assert result.publish_date == "2026-06-15"
        assert result.author == "TestMedia"
        assert "看资讯行情" not in result.body
        assert "责任编辑" not in result.body
        assert "这是第一段真正的正文内容" in result.body
        assert "第二段继续讨论相关话题" in result.body

    def test_ths_news_domain_uses_article_handler(self):
        result = NewsContentExtractor.extract(
            "https://news.10jqka.com.cn/20260715/c1.html",
            html=_fixture("ths_article.html"),
        )
        assert result.extractor == "ths_news_v1"
        assert result.title == "THS 测试标题"
        assert result.publish_date == "2026-07-15"
        assert "正文第一段" in result.body
        assert "站点菜单" not in result.body
        assert "相关推荐" not in result.body

    def test_ths_noscript_body_is_returned(self):
        html = """
        <html><head><script>window.__NEXT_DATA__ = {};</script></head>
        <body><div id="app"></div><noscript>这是同花顺 JS 壳页面提供的服务端正文，包含足够的文字用于直接提取并返回给客户端。</noscript></body></html>
        """
        result = NewsContentExtractor.extract(
            "https://news.10jqka.com.cn/20260715/noscript.html", html=html
        )
        assert result.content_status == "ok"
        assert result.extractor == "ths_news_v1_noscript"
        assert "服务端正文" in result.body

    def test_ths_hostname_normalization_uses_handler(self):
        result = NewsContentExtractor.extract(
            "https://NEWS.10JQKA.COM.CN:443/20260715/c1.html",
            html=_fixture("ths_article.html"),
        )
        assert result.extractor == "ths_news_v1"

    def test_data_eastmoney_uses_notice_handler(self):
        html = """
        <html><head><title>公告标题</title></head>
        <body><main><p>公告正文包含足够的内容，用于验证公告页面能够复用通用提取器并保留 notice extractor。This notice body includes enough English text to pass the generic threshold.</p></main></body></html>
        """
        result = NewsContentExtractor.extract(
            "https://data.eastmoney.com/notice/1.html", html=html
        )
        assert result.extractor == "eastmoney_notice"
        assert result.content_status == "ok"

    def test_stock_eastmoney_also_routes_to_em_handler(self):
        em_html = """
        <html><body>
          <div class="topbox">Title Here\n2026年05月29日 17:50 来源： StockSource</div>
          <div class="contentbox">
            <p>在东方财富看资讯行情, 选东方财富证券一站式开户交易>></p>
            <p>Stock subdomain paragraph 1, contains the article body content.</p>
            <p>Stock subdomain paragraph 2, more text to satisfy length check.</p>
            <p>文章来源: x</p>
          </div>
        </body></html>
        """
        result = NewsContentExtractor.extract(
            "https://stock.eastmoney.com/a/1.html", html=em_html
        )
        assert result.extractor == "eastmoney_v1"
        assert result.publish_date == "2026-05-29"
        assert result.author == "StockSource"
        assert "Stock subdomain paragraph 1" in result.body


class TestRegisterDomainHandler:
    def test_custom_handler_replaces_default(self):
        NewsContentExtractor.register_domain_handler(
            "example.com",
            lambda url: NewsContentExtractor._build(
                url=url, title="custom", body="custom body", extractor="custom_v1"
            ),
        )
        try:
            html = "<html><body><article><p>default article body content here.</p></article></body></html>"
            result = NewsContentExtractor.extract("https://example.com/x", html=html)
            assert result.extractor == "custom_v1"
            assert result.title == "custom"
        finally:
            NewsContentExtractor.unregister_domain_handler("example.com")
