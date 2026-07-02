"""Unit tests for persistence.board.get_stock_memberships helper."""

from __future__ import annotations

import pytest

from stock_data.data_provider.persistence import board as board_mod
from stock_data.data_provider.persistence import db as db_mod


@pytest.fixture
def fresh_db(tmp_path, monkeypatch):
    monkeypatch.setattr(db_mod, "_db_path", None)
    monkeypatch.setattr(db_mod, "_conn", None)
    board_mod._schema_initialized_paths = set()
    monkeypatch.setenv("STOCK_CACHE_DB_PATH", str(tmp_path / "test.db"))
    board_mod.init_schema()
    yield


def _seed_membership(stock_code: str, source: str, board_code: str,
                     board_type: str = "concept", subtype: str = "concept") -> None:
    """Helper: insert one membership row."""
    board_mod.upsert_membership_bulk(
        source=source,
        stocks=[{"stock_code": stock_code, "stock_name": "x"}],
        board_code=board_code,
        board_name=f"Board-{board_code}",
        board_type=board_type,
        subtype=subtype,
    )


class TestGetStockMemberships:
    """Helper semantics: returns entries, cold_sources, origin_summary."""

    def test_single_source_with_data(self, fresh_db):
        """Single source, all data in cache → entries=[...], cold=[], origin='persistence'."""
        _seed_membership("600519", "zhitu", "sw_yx")
        entries, cold, origin = board_mod.get_stock_memberships(
            stock_code="600519", sources=["zhitu"]
        )
        assert len(entries) == 1
        assert entries[0]["source"] == "zhitu"
        assert entries[0]["code"] == "sw_yx"
        assert cold == []
        assert origin == "persistence"

    def test_single_source_cold_no_fill(self, fresh_db):
        """Single source, no data, cold_fill=False → cold=[source], origin='persistence'."""
        entries, cold, origin = board_mod.get_stock_memberships(
            stock_code="600519", sources=["zhitu"], cold_fill=False
        )
        assert entries == []
        assert cold == ["zhitu"]
        assert origin == "persistence"

    def test_multi_source_partial_cold(self, fresh_db):
        """Multi source, only zhitu has data → cold=[others], origin='mixed'."""
        _seed_membership("600519", "zhitu", "sw_yx")
        entries, cold, origin = board_mod.get_stock_memberships(
            stock_code="600519", sources=["eastmoney", "zhitu", "zzshare"]
        )
        assert {e["source"] for e in entries} == {"zhitu"}
        assert set(cold) == {"eastmoney", "zzshare"}
        assert origin == "mixed"

    def test_filter_by_type(self, fresh_db):
        """type filter applied per-entry, in-memory after fetch."""
        _seed_membership("600519", "zhitu", "sw_yx", board_type="industry")
        _seed_membership("600519", "zhitu", "chgn_700532", board_type="concept")
        entries, cold, origin = board_mod.get_stock_memberships(
            stock_code="600519", sources=["zhitu"], type="concept"
        )
        assert len(entries) == 1
        assert entries[0]["code"] == "chgn_700532"

    def test_filter_by_subtype(self, fresh_db):
        """subtype filter applied per-entry."""
        _seed_membership("600519", "zhitu", "sw_yx", subtype="申万行业")
        _seed_membership("600519", "zhitu", "chgn_700532", subtype="热门概念")
        entries, cold, _ = board_mod.get_stock_memberships(
            stock_code="600519", sources=["zhitu"], subtype="申万行业"
        )
        assert len(entries) == 1
        assert entries[0]["code"] == "sw_yx"

    def test_no_sources_returns_empty(self, fresh_db):
        """Empty sources list → empty entries, empty cold."""
        entries, cold, origin = board_mod.get_stock_memberships(
            stock_code="600519", sources=[]
        )
        assert entries == []
        assert cold == []
        assert origin == ""

    def test_stock_not_in_any_source(self, fresh_db):
        """Stock has no membership rows → all sources cold, empty entries."""
        entries, cold, origin = board_mod.get_stock_memberships(
            stock_code="600519", sources=["eastmoney", "zhitu", "zzshare"]
        )
        assert entries == []
        assert set(cold) == {"eastmoney", "zhitu", "zzshare"}
        assert origin == "persistence"  # all cold, no fetcher called