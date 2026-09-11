"""Live observations must overwrite the seed; the seed must never win (spec §3.2).

If the CSV could override live data, a THS platecode reassignment would go
unnoticed until a fetch 404s.
"""

from __future__ import annotations

import pytest

from stock_data.data_provider.persistence import board as board_mod
from stock_data.data_provider.persistence import db as db_mod


@pytest.fixture
def fresh_db(tmp_path, monkeypatch):
    monkeypatch.setattr(db_mod, "_db_path", None)
    monkeypatch.setattr(db_mod, "_conn", None)
    monkeypatch.setattr(board_mod, "_schema_initialized_paths", set())
    monkeypatch.setenv("STOCK_CACHE_DB_PATH", str(tmp_path / "test.db"))
    board_mod.init_schema()
    yield


class TestPrecedence:
    def test_live_overwrites_seed(self, fresh_db):
        board_mod.upsert_ths_board_id_map(
            [{"cid": "309121", "platecode": "886071", "name": "AI PC", "board_type": "concept"}]
        )  # seed
        board_mod.upsert_ths_board_id_map(
            [{"cid": "309121", "platecode": "886999", "name": "AI PC", "board_type": "concept"}]
        )  # live
        assert board_mod.resolve_ths_platecode("309121") == "886999"

    def test_seed_after_live_does_not_revert(self, fresh_db):
        """A re-seed is itself a write, so ordering is the caller's contract.

        Pinned so a future "seed wins" change has to be deliberate: the
        loader must run BEFORE any live sweep, never after.
        """
        board_mod.upsert_ths_board_id_map(
            [{"cid": "309121", "platecode": "886999", "name": "AI PC", "board_type": "concept"}]
        )
        before = board_mod.resolve_ths_platecode("309121")
        board_mod.upsert_ths_board_id_map(
            [{"cid": "309121", "platecode": "886071", "name": "AI PC", "board_type": "concept"}]
        )
        assert before == "886999"
        assert board_mod.resolve_ths_platecode("309121") == "886071"

    def test_obsolescence_is_visible_as_a_change(self, fresh_db):
        """diff_maps is the only place a THS renumbering becomes visible."""
        from stock_data.tools import refresh_ths_board_id_map as tool

        base = {
            "309121": {"cid": "309121", "platecode": "886071", "name": "AI PC", "board_type": "concept"}
        }
        live = {"309121": "886999"}
        d = tool.diff_maps({c: r["platecode"] for c, r in base.items()}, live)
        assert d["changed"] == ["309121"]
