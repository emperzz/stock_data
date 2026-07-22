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
            "code": "301558",
            "name": "ConceptA",
            "type": "concept",
            "subtype": "同花顺概念",
            "platecode": "885001",
        },
        {
            "code": "301559",
            "name": "ConceptB",
            "type": "concept",
            "subtype": "同花顺概念",
            "platecode": "885002",
        },
    ]
    mock = MagicMock()
    mock.get_all_boards.return_value = (boards, "ths")

    def get_board_stocks(board_code, source, include_quote):
        return (
            [
                {"stock_code": "000034", "stock_name": "Starter-000034"},
                {"stock_code": "999999", "stock_name": "Other"},
            ],
            "zzshare",
        )

    mock.get_board_stocks.side_effect = get_board_stocks
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
    # Membership rows store board_code = platecode for THS (the THS quirk
    # documented on _read_membership_entries), so the returned `code`
    # reflects the platecode even though the THS source list emits cid 301558/301559.
    assert len(entries) == 2
    board_codes = {e["code"] for e in entries}
    assert board_codes == {"885001", "885002"}
    board_names = {e["name"] for e in entries}
    assert board_names == {"ConceptA", "ConceptB"}
    assert cold_sources == []
    assert origin == "persistence"
