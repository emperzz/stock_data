"""Sidebar-only concept rows must get their platecode from ths_board_id_map."""

from __future__ import annotations

from pathlib import Path

import pytest

from stock_data.data_provider.base import DataFetchError
from stock_data.data_provider.fetchers.ths_fetcher import ThsFetcher
from stock_data.data_provider.persistence import board as board_mod
from stock_data.data_provider.persistence import db as db_mod

FIXTURES = Path(__file__).parent / "fixtures"
DETAIL_309121 = (FIXTURES / "ths_gn_detail_309121.html").read_text(encoding="utf-8")


@pytest.fixture
def fresh_db(tmp_path, monkeypatch):
    monkeypatch.setattr(db_mod, "_db_path", None)
    monkeypatch.setattr(db_mod, "_conn", None)
    monkeypatch.setattr(board_mod, "_schema_initialized_paths", set())
    monkeypatch.setenv("STOCK_CACHE_DB_PATH", str(tmp_path / "test.db"))
    board_mod.init_schema()
    yield


class TestExtractPlatecodeFromDetail:
    def test_single_candidate_returned(self):
        assert ThsFetcher.extract_platecode_from_detail(DETAIL_309121) == "886071"

    def test_no_candidate_returns_none(self):
        assert ThsFetcher.extract_platecode_from_detail("<html>没有代码</html>") is None

    def test_ambiguous_page_returns_none(self):
        """Two distinct candidates must not be guessed."""
        html = "<a>885001</a><a>886002</a>"
        assert ThsFetcher.extract_platecode_from_detail(html) is None

    def test_repeated_same_candidate_is_not_ambiguous(self):
        assert ThsFetcher.extract_platecode_from_detail(html="886071 ... 886071") == "886071"

    def test_empty_html_returns_none(self):
        assert ThsFetcher.extract_platecode_from_detail("") is None


class TestMergeConceptSources:
    def test_sidebar_only_row_resolved_from_map(self, fresh_db):
        board_mod.upsert_ths_board_id_map(
            [{"cid": "308614", "platecode": "886056", "name": "阿尔茨海默概念", "board_type": "concept"}]
        )
        gn = [{"ths_cid": "309121", "name": "AI PC", "board_code": "886071", "source": "ths"}]
        sidebar = [
            {"ths_cid": "309121", "name": "AI PC", "source": "ths"},
            {"ths_cid": "308614", "name": "阿尔茨海默概念", "source": "ths"},
        ]
        merged = ThsFetcher._merge_concept_sources(gn, sidebar)
        by_cid = {r["ths_cid"]: r for r in merged}
        assert by_cid["309121"]["board_code"] == "886071"  # gnSection wins
        assert by_cid["308614"]["board_code"] == "886056"  # resolved from the map

    def test_unmapped_sidebar_row_keeps_none(self, fresh_db, monkeypatch):
        """No map entry, no detail-page candidate — None, never a guess."""
        monkeypatch.setattr(
            ThsFetcher, "_http_get_ths_board_index", lambda self, url: "<html>没有代码</html>"
        )
        merged = ThsFetcher._merge_concept_sources(
            [], [{"ths_cid": "309999", "name": "未收录概念", "source": "ths"}]
        )
        assert merged[0]["board_code"] is None

    def test_gn_section_platecode_not_overwritten_by_map(self, fresh_db):
        board_mod.upsert_ths_board_id_map(
            [{"cid": "309121", "platecode": "886999", "name": "AI PC", "board_type": "concept"}]
        )
        gn = [{"ths_cid": "309121", "name": "AI PC", "board_code": "886071", "source": "ths"}]
        merged = ThsFetcher._merge_concept_sources(gn, [])
        assert merged[0]["board_code"] == "886071"

    def test_name_backfilled_from_sidebar(self, fresh_db):
        gn = [{"ths_cid": "309121", "name": "", "board_code": "886071", "source": "ths"}]
        sidebar = [{"ths_cid": "309121", "name": "AI PC", "source": "ths"}]
        merged = ThsFetcher._merge_concept_sources(gn, sidebar)
        assert merged[0]["name"] == "AI PC"

    def test_duplicate_cids_deduped(self, fresh_db):
        gn = [
            {"ths_cid": "309121", "name": "AI PC", "board_code": "886071", "source": "ths"},
            {"ths_cid": "309121", "name": "AI PC", "board_code": "886071", "source": "ths"},
        ]
        assert len(ThsFetcher._merge_concept_sources(gn, [])) == 1


class TestRuntimeDetailFallback:
    """Map miss → one detail-page GET → write back to ths_board_id_map."""

    def test_unmapped_sidebar_row_resolved_from_detail_page_and_cached(
        self, fresh_db, monkeypatch
    ):
        detail_html = DETAIL_309121.replace("886071", "886123")
        calls: list[str] = []

        def fake_get(self, url):
            calls.append(url)
            return detail_html

        monkeypatch.setattr(ThsFetcher, "_http_get_ths_board_index", fake_get)

        gn: list[dict] = []
        sidebar = [{"ths_cid": "309999", "name": "未收录概念", "source": "ths"}]
        merged = ThsFetcher._merge_concept_sources(gn, sidebar)

        assert merged[0]["board_code"] == "886123"
        assert len(calls) == 1 and "309999" in calls[0]
        # write-back: the next call must not hit the network again
        calls.clear()
        merged2 = ThsFetcher._merge_concept_sources(gn, sidebar)
        assert merged2[0]["board_code"] == "886123"
        assert calls == [], "resolved platecode must be persisted to ths_board_id_map"

    def test_detail_fetch_failure_keeps_none(self, fresh_db, monkeypatch):
        """A board whose platecode we cannot learn is still a valid row."""

        def boom(self, url):
            raise DataFetchError("ths down")

        monkeypatch.setattr(ThsFetcher, "_http_get_ths_board_index", boom)
        merged = ThsFetcher._merge_concept_sources(
            [], [{"ths_cid": "309999", "name": "未收录概念", "source": "ths"}]
        )
        assert merged[0]["board_code"] is None

    def test_unparsable_detail_page_keeps_none_and_does_not_write(self, fresh_db, monkeypatch):
        monkeypatch.setattr(
            ThsFetcher, "_http_get_ths_board_index", lambda self, url: "<html>没有代码</html>"
        )
        merged = ThsFetcher._merge_concept_sources(
            [], [{"ths_cid": "309998", "name": "待定", "source": "ths"}]
        )
        assert merged[0]["board_code"] is None
        assert board_mod.resolve_ths_platecode("309998") is None

    def test_gnsection_row_never_triggers_a_fetch(self, fresh_db, monkeypatch):
        def boom(self, url):
            raise AssertionError("gnSection rows must not fetch a detail page")

        monkeypatch.setattr(ThsFetcher, "_http_get_ths_board_index", boom)
        gn = [{"ths_cid": "309121", "name": "AI PC", "board_code": "886071", "source": "ths"}]
        assert ThsFetcher._merge_concept_sources(gn, [])[0]["board_code"] == "886071"
