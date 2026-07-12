"""
Tests for NewsContentExtractor: default handler + finance.eastmoney.com handler.

Default handler finds <article> / <div class=content> / <main> in priority
order. The eastmoney handler uses the .topbox / .contentbox structure verified
during spec validation (2026-06-16 playwright).
"""
import pytest

from stock_data.data_provider.utils import news_extractor
from stock_data.data_provider.utils.news_extractor import NewsContentExtractor


@pytest.fixture(autouse=True)
def bypass_ssrf(monkeypatch):
    """Disable ``_is_private_ip`` for these tests.

    The extraction logic under test does NOT need real DNS — these tests
    always pass ``html=html`` so no upstream fetch happens. The validation
    in :func:`_validate_url` would otherwise fail on hosts that don't
    resolve on this particular dev box (``example.com`` DNS returns
    ``gaierror`` here), which is environment-specific noise that has
    nothing to do with the extraction contract. SSRF protection is
    covered separately by integration / smoke tests, not unit tests of
    the HTML parser.
    """
    monkeypatch.setattr(news_extractor, "_is_private_ip", lambda host: False)
    yield


# ---------------------- Default handler ----------------------

class TestDefaultHandler:
    def test_finds_article_tag(self):
        html = """
        <html><body>
          <nav>navigation</nav>
          <article><p>Hello world.</p><p>Second paragraph.</p></article>
          <footer>copyright</footer>
        </body></html>
        """
        result = NewsContentExtractor.extract("https://example.com/news/1", html=html)
        assert "Hello world." in result.body
        assert "Second paragraph." in result.body
        assert result.extractor == "default"

    def test_falls_back_to_div_content(self):
        html = """
        <html><body>
          <div class="content"><p>Inside content div.</p></div>
        </body></html>
        """
        result = NewsContentExtractor.extract("https://example.com/x", html=html)
        assert "Inside content div." in result.body

    def test_strips_script_and_style(self):
        html = """
        <html><body>
          <article>
            <script>alert('x')</script>
            <style>body{}</style>
            <p>Real content.</p>
          </article>
        </body></html>
        """
        result = NewsContentExtractor.extract("https://example.com/x", html=html)
        assert "Real content." in result.body
        assert "alert" not in result.body
        assert "body{}" not in result.body

    def test_short_body_raises(self):
        html = "<html><body><nav>only nav</nav></body></html>"
        with pytest.raises(ValueError, match="could not extract main content"):
            NewsContentExtractor.extract("https://example.com/x", html=html)

    def test_extracts_title_from_og_meta(self):
        html = """
        <html>
          <head>
            <meta property="og:title" content="OG Title Here">
          </head>
          <body><article><p>Body content here for length test.</p></article></body>
        </html>
        """
        result = NewsContentExtractor.extract("https://example.com/x", html=html)
        assert result.title == "OG Title Here"


# ---------------------- Domain dispatch ----------------------

class TestDomainDispatch:
    def test_eastmoney_domain_routes_to_em_handler(self):
        # finance.eastmoney.com has a specific structure: .topbox + .contentbox
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
        # First paragraph (ad) is skipped
        assert "看资讯行情" not in result.body
        # Stops at "文章来源"
        assert "责任编辑" not in result.body
        assert "这是第一段真正的正文内容" in result.body
        assert "第二段继续讨论相关话题" in result.body

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
            "example.com", lambda url: NewsContentExtractor._build(
                url=url, title="custom", body="custom body", extractor="custom_v1"
            )
        )
        try:
            html = "<html><body><article><p>default article body content here.</p></article></body></html>"
            result = NewsContentExtractor.extract("https://example.com/x", html=html)
            assert result.extractor == "custom_v1"
            assert result.title == "custom"
        finally:
            NewsContentExtractor.unregister_domain_handler("example.com")
