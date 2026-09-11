"""``update_cached_boards`` must be a snapshot replace scoped to (board_type, source).

The board list is refreshed as a whole: phase 1 of the backfill asks THS for
every concept board (or every industry board) in one call, and the result is
the *complete* current membership of that slot. So a board that disappeared
upstream must disappear from ``stock_board`` too — an upsert-only write would
leave delisted/renamed boards in the table forever, and they would keep
showing up in ``/boards`` until someone wiped the DB by hand.

Contract:

* ``update_cached_boards(board_type, source, boards)`` performs
  DELETE-then-INSERT inside one transaction, scoped to exactly
  ``(board_type, source)``.
* Rows for other sources and other board types are untouched.
* ``stock_board_membership`` is never touched by this path (membership has
  its own snapshot replace in ``update_cached_board_stocks``).
* ``cid`` is written only for ``source='ths'`` (spec §4 rule 3) — a zzshare
  row's ``cid`` column stays NULL even if the fetcher row carries ``ths_cid``.
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
    board_mod._refresh_tracker = board_mod.DailyRefreshTracker()
    yield


def _board_codes(board_type: str, source: str) -> set[str]:
    rows = (
        db_mod.get_connection()
        .execute(
            "SELECT code FROM stock_board WHERE board_type = ? AND source = ?",
            (board_type, source),
        )
        .fetchall()
    )
    return {r["code"] for r in rows}


def test_replaced_snapshot_purges_boards_that_left_upstream(fresh_db):
    """The second write is the whole truth for (concept, ths): 885333 is gone."""
    board_mod.update_cached_boards("concept", "ths", [{"board_code": "885333", "name": "移动支付"}])
    assert _board_codes("concept", "ths") == {"885333"}

    board_mod.update_cached_boards("concept", "ths", [{"board_code": "886071", "name": "AI PC"}])

    assert _board_codes("concept", "ths") == {"886071"}
    all_ths = (
        db_mod.get_connection()
        .execute("SELECT code FROM stock_board WHERE source = 'ths'")
        .fetchall()
    )
    assert {r["code"] for r in all_ths} == {"886071"}


def test_purge_is_scoped_to_the_source(fresh_db):
    """A ths snapshot replace must not delete zzshare rows."""
    board_mod.update_cached_boards("concept", "zzshare", [{"board_code": "801001", "name": "zz"}])
    board_mod.update_cached_boards("concept", "ths", [{"board_code": "885333", "name": "移动支付"}])
    board_mod.update_cached_boards("concept", "ths", [{"board_code": "886071", "name": "AI PC"}])

    assert _board_codes("concept", "zzshare") == {"801001"}
    assert _board_codes("concept", "ths") == {"886071"}


def test_purge_is_scoped_to_the_board_type(fresh_db):
    """A concept snapshot replace must not delete industry rows (same source)."""
    board_mod.update_cached_boards("industry", "ths", [{"board_code": "881121", "name": "半导体"}])
    board_mod.update_cached_boards("concept", "ths", [{"board_code": "885333", "name": "移动支付"}])
    board_mod.update_cached_boards("concept", "ths", [{"board_code": "886071", "name": "AI PC"}])

    assert _board_codes("industry", "ths") == {"881121"}
    assert _board_codes("concept", "ths") == {"886071"}


def test_cid_is_written_only_for_ths_rows(fresh_db):
    """spec §4 rule 3: only THS rows may carry a cid."""
    board_mod.update_cached_boards(
        "concept",
        "zzshare",
        [{"board_code": "801001", "name": "zz", "ths_cid": "300188"}],
    )
    board_mod.update_cached_boards(
        "concept",
        "ths",
        [{"board_code": "885333", "name": "移动支付", "ths_cid": "300188"}],
    )

    rows = {
        (r["source"], r["code"]): r["cid"]
        for r in db_mod.get_connection()
        .execute("SELECT source, code, cid FROM stock_board")
        .fetchall()
    }
    assert rows[("zzshare", "801001")] is None
    assert rows[("ths", "885333")] == "300188"


def test_purge_does_not_touch_membership(fresh_db):
    """Membership has its own snapshot replace; the board-list write leaves it alone."""
    board_mod.update_cached_boards("concept", "ths", [{"board_code": "885333", "name": "移动支付"}])
    board_mod.update_cached_board_stocks(
        "885333", "ths", [{"stock_code": "600519", "stock_name": "贵州茅台"}]
    )

    # Snapshot replace the board list — 885333 disappears from stock_board.
    board_mod.update_cached_boards("concept", "ths", [{"board_code": "886071", "name": "AI PC"}])

    assert _board_codes("concept", "ths") == {"886071"}
    membership = (
        db_mod.get_connection()
        .execute(
            "SELECT COUNT(*) AS n FROM stock_board_membership "
            "WHERE board_code = '885333' AND source = 'ths'"
        )
        .fetchone()["n"]
    )
    assert membership == 1
