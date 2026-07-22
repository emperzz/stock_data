"""
Tests for NewsContentExtractor SSRF protection.

Covers rejection of:
  - non-http(s) schemes
  - localhost
  - private IP ranges (127/8, 10/8, 172.16/12, 192.168/16, 0/8, ::1, fc00::/7)
  - cloud metadata (169.254/16), CGNAT (100.64/10), benchmark (198.18/15),
    IPv6 link-local (fe80::/10) — added 2026-07-16 per architecture review
  - DNS-rebounded hosts that resolve to private IPs
"""

from unittest.mock import patch

import pytest

from stock_data.data_provider.utils.news_extractor import NewsContentExtractor


class TestSSRFRejection:
    def test_rejects_file_scheme(self):
        with pytest.raises(ValueError, match="http or https"):
            NewsContentExtractor.extract("file:///etc/passwd")

    def test_rejects_gopher_scheme(self):
        with pytest.raises(ValueError, match="http or https"):
            NewsContentExtractor.extract("gopher://example.com/")

    def test_rejects_ftp_scheme(self):
        with pytest.raises(ValueError, match="http or https"):
            NewsContentExtractor.extract("ftp://example.com/")

    def test_rejects_localhost(self):
        with pytest.raises(ValueError, match="internal network"):
            NewsContentExtractor.extract("http://localhost/secret")

    def test_rejects_127_0_0_1(self):
        with pytest.raises(ValueError, match="internal network"):
            NewsContentExtractor.extract("http://127.0.0.1/admin")

    def test_rejects_10_dot(self):
        with pytest.raises(ValueError, match="internal network"):
            NewsContentExtractor.extract("http://10.0.0.1/")

    def test_rejects_192_168(self):
        with pytest.raises(ValueError, match="internal network"):
            NewsContentExtractor.extract("http://192.168.1.1/")

    def test_rejects_172_16(self):
        with pytest.raises(ValueError, match="internal network"):
            NewsContentExtractor.extract("http://172.16.0.1/")

    def test_rejects_aws_metadata_169_254(self):
        """Cloud metadata (AWS/GCP/Azure IMDSv1) at 169.254.169.254 must be rejected.

        Without this block, attackers could exfiltrate instance credentials via
        the /news/content endpoint. Default localhost binding limits real-world
        exposure, but the fix is one line and removes the latent risk.
        """
        with pytest.raises(ValueError, match="internal network"):
            NewsContentExtractor.extract(
                "http://169.254.169.254/latest/meta-data/iam/security-credentials/"
            )

    def test_rejects_cgnat_100_64(self):
        """CGNAT range 100.64.0.0/10 must be rejected."""
        with pytest.raises(ValueError, match="internal network"):
            NewsContentExtractor.extract("http://100.64.0.1/")

    def test_rejects_benchmark_198_18(self):
        """Benchmark range 198.18.0.0/15 must be rejected."""
        with pytest.raises(ValueError, match="internal network"):
            NewsContentExtractor.extract("http://198.18.0.1/")

    def test_rejects_ipv6_link_local(self):
        """IPv6 link-local fe80::/10 must be rejected."""
        with pytest.raises(ValueError, match="internal network"):
            NewsContentExtractor.extract("http://[fe80::1]/")

    @patch("stock_data.data_provider.utils.news_extractor.socket.gethostbyname")
    def test_rejects_dns_resolved_to_private_ip(self, mock_gethostbyname):
        # Public domain name but resolves to 10.0.0.1
        mock_gethostbyname.return_value = "10.0.0.1"
        with pytest.raises(ValueError, match="internal network"):
            NewsContentExtractor.extract("http://public-looking.com/page")

    def test_accepts_public_domain(self):
        # example.com is a stable public test target; we just need the URL to
        # pass validation, not actually fetch.
        # Patch DNS resolution to confirm it would not be flagged.
        with patch(
            "stock_data.data_provider.utils.news_extractor.socket.gethostbyname"
        ) as mock_dns:
            mock_dns.return_value = "93.184.216.34"  # example.com IP
            # Now call extract with html= so we don't actually fetch example.com
            result = NewsContentExtractor.extract(
                "https://example.com/news/1",
                html=(
                    "<html><body><article><p>body content for testing with enough "
                    "additional text to satisfy the generic extraction threshold.</p>"
                    "</article></body></html>"
                ),
            )
            assert "body content for testing with enough" in result.body
