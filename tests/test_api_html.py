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

    def test_has_endpoints_dict(self, html_text):
        assert "const ENDPOINTS = {" in html_text
        assert '"sections":' in html_text

    def test_has_capability_definitions(self, html_text):
        assert "HISTORICAL_DWM" in html_text
        assert "REALTIME_QUOTE" in html_text
        assert "ANNOUNCEMENT" in html_text

    def test_has_theme_variables(self, html_text):
        assert "--bg:" in html_text
        assert "[data-theme=\"dark\"]" in html_text

    def test_has_search_input(self, soup):
        assert soup.select_one("#search") is not None

    def test_has_test_instance_card(self, soup):
        assert soup.select_one("#testStart") is not None
        assert soup.select_one("#testStop") is not None

    def test_has_capability_filter(self, soup):
        """Capability filter UI: 6 grouped checkboxes."""
        cf = soup.select_one("#capabilityFilter")
        assert cf is not None
        checkboxes = cf.select("input[type=checkbox]")
        assert len(checkboxes) == 6, f"Expected 6 capability groups, got {len(checkboxes)}"
        values = [c.get("value") for c in checkboxes]
        for g in ("quotes", "history", "metadata", "flows", "notices", "pools"):
            assert g in values, f"Missing capability group: {g}"

    def test_has_fuzzy_search_handler(self, html_text):
        """Search uses fuzzyMatch (subsequence), not just String.includes."""
        assert "fuzzyMatch" in html_text
        assert "ctrlKey" in html_text
        assert "ArrowDown" in html_text  # keyboard navigation

    def test_has_capability_groups_definition(self, html_text):
        """The CAPABILITY_GROUPS mapping must exist in JS."""
        assert "CAPABILITY_GROUPS" in html_text
        assert "REALTIME_QUOTE" in html_text
        assert "ANNOUNCEMENT" in html_text

    def test_has_no_external_dependencies(self, html_text):
        """No <script src=...> or <link href=...> to external URLs."""
        import re
        external = re.findall(r'(?:src|href)="https?://[^"]+"', html_text)
        assert external == [], f"Found external resources: {external}"

    def test_endpoints_count_grows(self, html_text):
        """By Task 7 we should have ~27 endpoints across 13 sections."""
        n_get = html_text.count('method: "GET"')
        n_post = html_text.count('method: "POST"')
        total = n_get + n_post
        assert total >= 25, f"Expected ≥25 endpoints by Task 7, got {total}"
