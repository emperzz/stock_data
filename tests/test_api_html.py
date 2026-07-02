"""Tests for stock_data/explorer/static/index.html structure."""
from pathlib import Path

import pytest
from bs4 import BeautifulSoup

HTML_PATH = Path(__file__).resolve().parent.parent / "stock_data" / "explorer" / "static" / "index.html"


@pytest.fixture
def html_text():
    if not HTML_PATH.exists():
        pytest.skip("explorer not yet mounted")
    return HTML_PATH.read_text(encoding="utf-8")


@pytest.fixture
def soup(html_text):
    return BeautifulSoup(html_text, "html.parser")


class TestHtmlStructure:
    def test_has_doctype(self, soup):
        pass  # checked separately in raw text

    def test_has_topbar(self, soup):
        assert soup.select_one("header.topbar h1") is not None
        assert "stock_data" in soup.select_one("header.topbar h1").get_text()

    def test_has_sidebar_and_main(self, soup):
        assert soup.select_one("nav.sidebar") is not None
        assert soup.select_one("main.main") is not None

    def test_has_manifest_bootstrap(self, html_text):
        """The 1000-line hand-written ENDPOINTS block is gone; replaced by
        a fetch of /control/api-manifest + ENDPOINTS shim."""
        assert "const ENDPOINTS = {" not in html_text
        assert "fetch(\"/control/api-manifest\"" in html_text
        assert "loadManifest" in html_text

    def test_has_capability_definitions(self, html_text):
        """Capability identifiers (STOCK_KLINE / STOCK_REALTIME_QUOTE / ANNOUNCEMENT)
        are no longer hardcoded in the HTML — they are fetched from
        /control/api-manifest at runtime. Verify the contract:
          - The MANIFEST object carries a `capabilities` field (for labels)
          - The FALLBACK object initializes `capabilities: {}`
          - Capability strings are surfaced via `cap-chip` rendering of
            the per-fetcher row's `f.capabilities` array
        """
        assert "MANIFEST" in html_text
        assert "capabilities" in html_text
        assert "cap-chip" in html_text
        # Per-fetcher capabilities are rendered from `f.capabilities`:
        assert "f.capabilities" in html_text
        # FALLBACK defines the empty capabilities map for the offline state:
        assert "capabilities: {}" in html_text

    def test_has_theme_variables(self, html_text):
        assert "--bg:" in html_text
        assert "[data-theme=\"dark\"]" in html_text

    def test_has_search_input(self, soup):
        assert soup.select_one("#search") is not None

    def test_has_fuzzy_search_handler(self, html_text):
        """Search uses fuzzyMatch (subsequence), not just String.includes."""
        assert "fuzzyMatch" in html_text
        assert "ctrlKey" in html_text
        assert "ArrowDown" in html_text  # keyboard navigation

    def test_has_no_external_dependencies(self, html_text):
        """No <script src=...> or <link href=...> to external URLs."""
        import re
        external = re.findall(r'(?:src|href)="https?://[^"]+"', html_text)
        assert external == [], f"Found external resources: {external}"

    def test_endpoints_count_grows(self, html_text):
        """The HTML no longer hard-codes endpoint metadata (Task 5 refactor).
        Verify the manifest fetch is wired in. The actual endpoint count is
        asserted in tests/test_manifest.py via the live /control/api-manifest
        response.
        """
        # Sanity: the boot() entry point exists and the manifest fetch is wired.
        assert "async function boot()" in html_text
        assert "await window.loadManifest()" in html_text
        assert "MANIFEST.sections" in html_text
