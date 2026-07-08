"""
Live-network tests for ThsFetcher.get_all_boards.

Added 2026-07-08 alongside the ThsFetcher.get_all_boards implementation.
Default ``pytest`` skips this file (addopts in pyproject.toml excludes
``live_network``). Run with:

    .venv/Scripts/python.exe -m pytest -m live_network tests/test_ths_fetcher_get_all_boards_live.py
    .venv/Scripts/python.exe -m pytest -m ""       # run everything
"""

import pytest

from stock_data.data_provider.base import DataFetchError
from stock_data.data_provider.fetchers.ths_fetcher import ThsFetcher
from stock_data.data_provider.persistence import board as board_persistence

THS_CONCEPT_SUBTYPE = board_persistence.THS_CONCEPT_SUBTYPE
THS_INDUSTRY_SUBTYPE = board_persistence.THS_INDUSTRY_SUBTYPE


# ── Pure-unit tests (no network) ─────────────────────────────────────
#
# These lock the parser behavior against well-known HTML fixtures so a
# silent upstream-side field rename doesn't sneak past code review.
# Cheap to run; safe to keep in the default test loop.

# A minimal /gn/ page fixture: 1 gnSection entry + 1 sidebar-only entry
# (the sidebar-only entry has a cid that gnSection does NOT carry, so we
# can verify the merge logic appends it with platecode=None).
_GN_FIXTURE = """
<html><body>
<input type="hidden" id="gnSection" value="{&quot;1&quot;:{&quot;platecode&quot;:&quot;885333&quot;,&quot;platename&quot;:&quot;移动支付&quot;,&quot;cid&quot;:&quot;300188&quot;,&quot;zjjlr&quot;:8.91,&quot;zfl&quot;:65,&quot;199112&quot;:1.39},&quot;2&quot;:{&quot;platecode&quot;:&quot;885343&quot;,&quot;platename&quot;:&quot;稀土永磁&quot;,&quot;cid&quot;:&quot;300382&quot;,&quot;zjjlr&quot;:-13.51,&quot;zfl&quot;:12,&quot;199112&quot;:-1.73}}">
<div class="cate_inner">
  <div class="cate_items">
    <a href="/gn/detail/code/300188/">移动支付</a>
    <a href="/gn/detail/code/300382/">稀土永磁</a>
    <a href="/gn/detail/code/301558/">阿里巴巴概念</a>
  </div>
</div>
</body></html>
"""

# A minimal /thshy/ page fixture: 2 industries, 881xxx platecodes.
_THSHY_FIXTURE = """
<html><body>
<div class="cate_inner">
  <div class="cate_items">
    <a href="/thshy/detail/code/881121/">半导体</a>
    <a href="/thshy/detail/code/881273/">白酒</a>
  </div>
</div>
</body></html>
"""


class TestParseGnSectionFixture:
    """Lock the gnSection JSON parser behavior against a minimal fixture."""

    def setup_method(self):
        self.fetcher = ThsFetcher()

    def test_parses_cid_platecode_name(self):
        rows = self.fetcher._parse_gn_section(_GN_FIXTURE)
        assert len(rows) == 2
        for r in rows:
            assert r["code"] in ("300188", "300382")
            assert r["platecode"] in ("885333", "885343")
            assert r["name"]
            assert r["source"] == "ths"

    def test_carries_change_pct_and_net_inflow(self):
        rows = self.fetcher._parse_gn_section(_GN_FIXTURE)
        by_cid = {r["code"]: r for r in rows}
        assert by_cid["300188"]["change_pct"] == 1.39
        assert by_cid["300188"]["net_inflow"] == 8.91
        assert by_cid["300382"]["change_pct"] == -1.73
        assert by_cid["300382"]["net_inflow"] == -13.51

    def test_skips_gnsection_row_missing_cid(self):
        bad = """<input type="hidden" id="gnSection" value="{&quot;1&quot;:{&quot;platecode&quot;:&quot;885333&quot;,&quot;platename&quot;:&quot;X&quot;}}">"""
        rows = self.fetcher._parse_gn_section(bad)
        assert rows == []

    def test_skips_gnsection_row_missing_platecode(self):
        bad = """<input type="hidden" id="gnSection" value="{&quot;1&quot;:{&quot;cid&quot;:&quot;300188&quot;,&quot;platename&quot;:&quot;X&quot;}}">"""
        rows = self.fetcher._parse_gn_section(bad)
        assert rows == []

    def test_skips_gnsection_row_missing_name(self):
        bad = """<input type="hidden" id="gnSection" value="{&quot;1&quot;:{&quot;cid&quot;:&quot;300188&quot;,&quot;platecode&quot;:&quot;885333&quot;}}">"""
        rows = self.fetcher._parse_gn_section(bad)
        assert rows == []

    def test_raises_on_malformed_gnsection_json(self):
        """Bad JSON is an upstream change, not a transient fault — fail loud."""
        bad = """<input type="hidden" id="gnSection" value="{not json">"""
        with pytest.raises(DataFetchError, match="malformed gnSection JSON"):
            self.fetcher._parse_gn_section(bad)


class TestParseGnSidebarFixture:
    """Lock the sidebar HTML parser behavior."""

    def setup_method(self):
        self.fetcher = ThsFetcher()

    def test_extracts_cid_name_pairs(self):
        rows = self.fetcher._parse_ths_gn_sidebar(_GN_FIXTURE)
        cids = {r["code"] for r in rows}
        names = {r["name"] for r in rows}
        assert cids == {"300188", "300382", "301558"}
        assert "移动支付" in names
        assert "阿里巴巴概念" in names  # sidebar-only (not in gnSection)

    def test_returns_empty_on_blank_html(self):
        assert self.fetcher._parse_ths_gn_sidebar("") == []
        assert self.fetcher._parse_ths_gn_sidebar("<html><body></body></html>") == []


class TestParseIndustrySidebarFixture:
    """Lock the /thshy/ sidebar parser behavior."""

    def setup_method(self):
        self.fetcher = ThsFetcher()

    def test_extracts_industry_codes(self):
        rows = self.fetcher._parse_ths_thshy_sidebar(_THSHY_FIXTURE)
        assert len(rows) == 2
        codes = {r["code"] for r in rows}
        assert codes == {"881121", "881273"}

    def test_industry_code_is_881_prefix(self):
        rows = self.fetcher._parse_ths_thshy_sidebar(_THSHY_FIXTURE)
        for r in rows:
            assert r["code"].startswith("881"), (
                f"industry code {r['code']!r} should start with '881'"
            )


class TestMergeConceptSources:
    """Lock the merge logic — gnSection primary, sidebar fills gaps."""

    def setup_method(self):
        self.fetcher = ThsFetcher()

    def test_gnsection_wins(self):
        gn = [{"code": "300188", "name": "移动支付", "platecode": "885333", "source": "ths"}]
        sb = [{"code": "300188", "name": "OVERRIDDEN", "source": "ths"}]
        merged = self.fetcher._merge_concept_sources(gn, sb)
        assert len(merged) == 1
        assert merged[0]["name"] == "移动支付"
        assert merged[0]["platecode"] == "885333"

    def test_sidebar_only_gets_null_platecode(self):
        gn = [{"code": "300188", "name": "移动支付", "platecode": "885333", "source": "ths"}]
        sb = [{"code": "301558", "name": "阿里巴巴概念", "source": "ths"}]
        merged = self.fetcher._merge_concept_sources(gn, sb)
        by_cid = {r["code"]: r for r in merged}
        assert by_cid["301558"]["platecode"] is None
        assert by_cid["301558"]["name"] == "阿里巴巴概念"

    def test_sidebar_fills_missing_name(self):
        # gnSection row with empty name; sidebar should fill it
        gn = [{"code": "300188", "name": "", "platecode": "885333", "source": "ths"}]
        sb = [{"code": "300188", "name": "移动支付", "source": "ths"}]
        merged = self.fetcher._merge_concept_sources(gn, sb)
        assert merged[0]["name"] == "移动支付"


# ── Live-network smoke tests ─────────────────────────────────────────

@pytest.fixture(scope="module")
def ths() -> ThsFetcher:
    return ThsFetcher()


@pytest.mark.live_network
def test_ths_get_all_boards_concept(ths):
    """Concept boards: 200+ rows, all carry platecode (after merge)."""
    rows = ths.get_all_boards(board_type="concept")
    assert isinstance(rows, list)
    assert len(rows) > 200, f"expected >200 concept boards, got {len(rows)}"

    # All rows tagged correctly
    for r in rows:
        assert r["type"] == "concept"
        assert r["subtype"] == THS_CONCEPT_SUBTYPE
        assert r["source"] == "ths"
        assert r["code"], f"row missing code: {r}"
        assert r["name"], f"row missing name: {r}"
        # platecode may be None for sidebar-only entries — that's
        # expected (documented in the docstring). What MUST be true:
        # every platecode is 6 digits starting with 88x.
        if r["platecode"] is not None:
            assert r["platecode"].isdigit() and len(r["platecode"]) == 6
            assert r["platecode"].startswith("88"), (
                f"concept platecode should start with 88, got {r['platecode']!r}"
            )

    # Spot-check a known board: 移动支付 is always present
    move_payment = next((r for r in rows if r["name"] == "移动支付"), None)
    assert move_payment is not None, "移动支付 should be in the concept board list"
    assert move_payment["code"] == "300188"
    assert move_payment["platecode"] == "885333"

    # No duplicate codes (UNIQUE(code, source) constraint compliance)
    codes = [r["code"] for r in rows]
    assert len(codes) == len(set(codes)), "duplicate codes in concept list"


@pytest.mark.live_network
def test_ths_get_all_boards_industry(ths):
    """Industry boards: 80+ rows, every code starts with 881."""
    rows = ths.get_all_boards(board_type="industry")
    assert isinstance(rows, list)
    assert len(rows) > 60, f"expected >60 industry boards, got {len(rows)}"

    for r in rows:
        assert r["type"] == "industry"
        assert r["subtype"] == THS_INDUSTRY_SUBTYPE
        assert r["source"] == "ths"
        # For industry, code == platecode (no separate cid).
        assert r["code"] == r["platecode"]
        assert r["code"].startswith("881"), (
            f"industry code {r['code']!r} should start with '881'"
        )

    # Spot-check: 半导体 should be present
    semi = next((r for r in rows if r["name"] == "半导体"), None)
    assert semi is not None, "半导体 should be in the industry board list"
    assert semi["code"] == "881121"
    assert semi["platecode"] == "881121"


@pytest.mark.live_network
def test_ths_get_all_boards_combined(ths):
    """board_type=None returns both concept and industry."""
    rows = ths.get_all_boards(board_type=None)
    assert isinstance(rows, list)
    types_present = {r["type"] for r in rows}
    assert "concept" in types_present
    assert "industry" in types_present

    # No duplicate (code, type) within a source.
    seen = set()
    for r in rows:
        key = (r["code"], r["type"], r["source"])
        assert key not in seen, f"duplicate (code, type, source): {key}"
        seen.add(key)


@pytest.mark.live_network
def test_ths_get_all_boards_subtype_filter(ths):
    """subtype filter narrows result to one type's rows."""
    concept_rows = ths.get_all_boards(
        board_type="concept", subtype=THS_CONCEPT_SUBTYPE
    )
    assert all(r["subtype"] == THS_CONCEPT_SUBTYPE for r in concept_rows)
    # Should match the unfiltered concept count (only one subtype)
    unfiltered = ths.get_all_boards(board_type="concept")
    assert len(concept_rows) == len(unfiltered)


@pytest.mark.live_network
def test_ths_get_all_boards_rejects_invalid_board_type(ths):
    """board_type=index is not supported by ThsFetcher."""
    with pytest.raises(DataFetchError, match="board_type"):
        ths.get_all_boards(board_type="index")
