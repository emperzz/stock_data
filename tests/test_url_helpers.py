"""Tests for stock_data.data_provider.utils.url_helpers."""

from stock_data.data_provider.utils.url_helpers import source_domain


class TestSourceDomain:
    def test_strips_scheme(self):
        assert source_domain("https://news.10jqka.com.cn/article") == "news.10jqka.com.cn"

    def test_strips_port(self):
        """Review 2026-07-06 finding #4: hostname, not netloc, so port is stripped."""
        assert source_domain("http://example.com:8080/news") == "example.com"

    def test_preserves_subdomain(self):
        assert source_domain("https://finance.eastmoney.com/news/123") == "finance.eastmoney.com"

    def test_handles_ip_without_port(self):
        assert source_domain("http://192.168.1.1/path") == "192.168.1.1"

    def test_handles_ip_with_port(self):
        assert source_domain("http://192.168.1.1:8080/path") == "192.168.1.1"

    def test_empty_string_returns_empty(self):
        assert source_domain("") == ""

    def test_none_returns_empty(self):
        assert source_domain(None) == ""

    def test_garbage_returns_empty(self):
        """urlparse is forgiving — non-strings raise; we return empty."""
        # Numbers raise TypeError from urlparse
        assert source_domain(12345) == ""

    def test_no_scheme_returns_empty(self):
        """urlparse('example.com/path') puts the host in .path, not .hostname.

        We can't reliably recover a hostname from a scheme-less URL — the
        caller should pass fully-qualified URLs. Returns "" rather than
        trying to be clever.
        """
        assert source_domain("example.com/path") == ""

    def test_whitespace_only(self):
        """Non-empty but unparseable → empty hostname."""
        # urlparse(" ") returns ParseResult(scheme='', netloc='', path=' ', ...)
        assert source_domain("   ") == ""
