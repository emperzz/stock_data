"""Integration test: backfill → reverse lookup completeness.

Verifies the spec §1.1 problem: a stock belonging to multiple boards used
to return only the boards that happened to be queried once. After
``run_ths_board_backfill`` populates both tables, the reverse lookup
returns the COMPLETE set.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from stock_data.data_provider.persistence import board as board_mod
from stock_data.data_provider.persistence import db as db_mod
from stock_data.data_provider.persistence.backfill import run_ths_board_backfill


@pytest.fixture
def fresh_db(tmp_path, monkeypatch):
    monkeypatch.setattr(db_mod, "_db_path", None)
    monkeypatch.setattr(db_mod, "_conn", None)
    monkeypatch.setattr(board_mod, "_schema_initialized_paths", set())
    monkeypatch.setenv("STOCK_CACHE_DB_PATH", str(tmp_path / "test.db"))
    board_mod.init_schema()
    yield tmp_path / "test.db"


def _make_backfill_manager():
    """Two boards, both contain stock_code='000034'.

    Without backfill, the cache is empty → reverse lookup returns [].
    After backfill populates stock_board_membership, reverse lookup
    returns BOTH boards.
    """
    boards = [
        {
            "board_code": "885001",
            "name": "ConceptA",
            "board_type": "concept",
            "subtype": "同花顺概念",
            "ths_cid": "301558",
        },
        {
            "board_code": "885002",
            "name": "ConceptB",
            "board_type": "concept",
            "subtype": "同花顺概念",
            "ths_cid": "301559",
        },
    ]
    mock = MagicMock()

    def get_all_boards(source, board_type=None, subtype=None, include_quote=False):
        # THS-only backfill: one sweep per board_type.
        if source != "ths":
            return ([], source)
        return ([b for b in boards if b["board_type"] == board_type], "ths")

    mock.get_all_boards.side_effect = get_all_boards

    def get_board_stocks_full(board_code, source="ths", *, board_type=None):
        # Phase 2 reads the THS F10 page (the only leg post-2026-09-11).
        assert source == "ths"
        return (
            [
                {"stock_code": "000034", "stock_name": "Starter-000034"},
                {"stock_code": "999999", "stock_name": "Other"},
            ],
            "ths",
        )

    mock.get_board_stocks_full.side_effect = get_board_stocks_full
    return mock


def test_reverse_lookup_after_backfill_returns_all_boards(fresh_db, monkeypatch):
    """After backfill, both boards containing stock 000034 surface in reverse lookup."""
    mock = _make_backfill_manager()
    monkeypatch.setattr("time.sleep", lambda *_a, **_kw: None)

    # 1. Run backfill directly (no real network — mock manager handles all calls)
    run_ths_board_backfill(mock, inter_call_sleep_s=0.0)

    # 2. Reverse lookup via persistence helper (the route layer's read path)
    entries, cold_sources, origin = board_mod.get_stock_memberships(
        stock_code="000034",
        sources=["ths"],
        manager=mock,
    )

    # 3. Both boards now appear (this is the bug-fix assertion).
    # ``get_stock_memberships`` returns internal board rows (board_code /
    # board_type); the route layer maps them to the public code/type keys.
    assert len(entries) == 2
    board_codes = {e["board_code"] for e in entries}
    assert board_codes == {"885001", "885002"}
    board_names = {e["name"] for e in entries}
    assert board_names == {"ConceptA", "ConceptB"}
    assert cold_sources == []
    assert origin == "persistence"
