"""Unit tests for persistence.board.read_memberships_by_codes helper.

Bulk OR-query of stock_board_membership. Empty axes = no filter on that axis.
Both empty = all rows for the given source.
"""

from __future__ import annotations

import pytest

from stock_data.data_provider.persistence import board as board_mod
from stock_data.data_provider.persistence import db as db_mod


@pytest.fixture
def fresh_db(tmp_path, monkeypatch):
    """Per-test isolated SQLite + fresh schema."""
    monkeypatch.setattr(db_mod, "_db_path", None)
    board_mod._schema_initialized_paths = set()
    monkeypatch.setenv("STOCK_CACHE_DB_PATH", str(tmp_path / "test.db"))
    board_mod.init_schema()
    yield


def _seed(
    stock_code: str,
    source: str,
    board_code: str,
    board_type: str = "concept",
    board_name: str = "",
) -> None:
    """Seed a single (board, stock, source) membership row.

    Wraps upsert_membership_bulk with a 1-stock list. NOTE: each call does
    DELETE-then-INSERT scoped to (board_code, source), so two calls with
    the same (board_code, source) overwrite each other — use the local
    ``_seed_board`` helper when you want multiple stocks in one board.
    """
    _seed_board([stock_code], source, board_code, board_type, board_name)


def _seed_board(
    stock_codes: list[str],
    source: str,
    board_code: str,
    board_type: str = "concept",
    board_name: str = "",
) -> None:
    """Seed an entire board with N stocks in one snapshot."""
    board_mod.upsert_membership_bulk(
        source=source,
        stocks=[{"stock_code": sc, "stock_name": sc} for sc in stock_codes],
        board_code=board_code,
        board_name=board_name or f"Board-{board_code}",
        board_type=board_type,
        subtype=None,
    )


class TestReadMembershipsByCodes:
    def test_board_codes_only_returns_matching_rows(self, fresh_db):
        """Forward direction: filter on board_code alone."""
        _seed_board(["600519", "000001"], "ths", "885595")
        _seed("600036", "ths", "881270")  # different board, should NOT match

        rows = board_mod.read_memberships_by_codes(
            board_codes=["885595"], stock_codes=None, source="ths"
        )
        codes = sorted(r["stock_code"] for r in rows)
        assert codes == ["000001", "600519"]

    def test_stock_codes_only_returns_matching_rows(self, fresh_db):
        """Reverse direction: filter on stock_code alone."""
        # 885595 contains BOTH 600519 and 000001; 881270 contains 600519.
        _seed_board(["600519", "000001"], "ths", "885595")
        _seed_board(["600519"], "ths", "881270")  # 600519 belongs to two boards

        rows = board_mod.read_memberships_by_codes(
            board_codes=None, stock_codes=["600519"], source="ths"
        )
        boards = sorted(r["board_code"] for r in rows)
        assert boards == ["881270", "885595"]

    def test_both_codes_returns_union(self, fresh_db):
        """Forward ∪ reverse — rows for either set are returned, no duplicates."""
        _seed_board(["600519", "000001"], "ths", "885595")
        _seed_board(["600519"], "ths", "881270")
        _seed_board(["000002"], "ths", "999999")  # unrelated row

        rows = board_mod.read_memberships_by_codes(
            board_codes=["885595"], stock_codes=["600519"], source="ths"
        )
        # Expect: 885595→600519, 885595→000001, 881270→600519 (3 rows; 999999→000002 excluded)
        keys = {(r["board_code"], r["stock_code"]) for r in rows}
        assert keys == {
            ("885595", "000001"),
            ("885595", "600519"),
            ("881270", "600519"),
        }

    def test_both_empty_returns_all_rows_for_source(self, fresh_db):
        """Both axes empty = full snapshot for the given source.

        Asserts source isolation by seeding rows under TWO different sources
        with overlapping stock codes. ``source='ths'`` must return exactly 2
        rows; ``source='zzshare'`` must return exactly 1. If the helper
        forgot to scope by `source`, both would return all 3 rows.
        """
        _seed_board(["600519", "000001"], "ths", "885595")
        _seed("600519", "zzshare", "885540")  # different source, must not appear in ths

        ths_rows = board_mod.read_memberships_by_codes(
            board_codes=None, stock_codes=None, source="ths"
        )
        assert len(ths_rows) == 2
        assert {r["stock_code"] for r in ths_rows} == {"600519", "000001"}

        zzshare_rows = board_mod.read_memberships_by_codes(
            board_codes=None, stock_codes=None, source="zzshare"
        )
        assert len(zzshare_rows) == 1
        assert zzshare_rows[0]["board_code"] == "885540"

    def test_source_filter_isolates_rows(self, fresh_db):
        """source='zzshare' must not return rows from source='ths'."""
        _seed("600519", "ths", "885595")
        _seed("600519", "zzshare", "885540")

        rows = board_mod.read_memberships_by_codes(
            board_codes=None, stock_codes=["600519"], source="zzshare"
        )
        assert len(rows) == 1
        assert rows[0]["board_code"] == "885540"

    def test_result_shape_has_six_fields(self, fresh_db):
        """Each row dict has exactly the 6 documented keys; no subtype, no source."""
        _seed("600519", "ths", "885595", board_type="concept", board_name="煤炭概念")

        rows = board_mod.read_memberships_by_codes(
            board_codes=["885595"], stock_codes=None, source="ths"
        )
        assert len(rows) == 1
        row = rows[0]
        assert set(row.keys()) == {
            "board_code",
            "stock_code",
            "board_name",
            "stock_name",
            "board_type",
            "refreshed_at",
        }
        assert row["board_code"] == "885595"
        assert row["board_name"] == "煤炭概念"
        assert row["board_type"] == "concept"
        assert row["stock_code"] == "600519"
        assert row["stock_name"] == "600519"
        assert isinstance(row["refreshed_at"], str)
        assert len(row["refreshed_at"]) > 0

    def test_result_order_is_by_board_then_stock(self, fresh_db):
        """Stable sort: (board_code ASC, stock_code ASC) regardless of insertion order."""
        _seed_board(["600003", "600000"], "ths", "881270")
        _seed_board(["600001", "600002"], "ths", "885595")

        rows = board_mod.read_memberships_by_codes(
            board_codes=None, stock_codes=None, source="ths"
        )
        keys = [(r["board_code"], r["stock_code"]) for r in rows]
        assert keys == [
            ("881270", "600000"),
            ("881270", "600003"),
            ("885595", "600001"),
            ("885595", "600002"),
        ]

    def test_empty_db_returns_empty_list(self, fresh_db):
        """No rows for source → empty list, not None, no exception."""
        rows = board_mod.read_memberships_by_codes(
            board_codes=["885595"], stock_codes=None, source="ths"
        )
        assert rows == []

    def test_sql_injection_does_not_leak_other_sources(self, fresh_db):
        """Malicious ``board_code`` containing ``'`` or ``OR 1=1`` must NOT
        return rows from another source.

        The helper uses parameterised ``?`` placeholders (sqlite3 driver
        escapes them), so a malicious value is matched as a literal string
        and finds no rows. This test pins that contract end-to-end: if a
        future refactor switches to f-string interpolation, the test will
        fail (the malicious value would either raise or, worse, leak rows).
        """
        # Seed a row in a different source. If source scoping breaks,
        # the malicious value would surface this row.
        _seed("000001", "zzshare", "885540")
        # Malicious: classic SQLi probe (no row literally matches it).
        malicious = "', 'OR1=1", "x' UNION SELECT 1--"
        rows = board_mod.read_memberships_by_codes(
            board_codes=list(malicious), stock_codes=None, source="ths"
        )
        assert rows == []
        # Defence-in-depth: also assert that even querying both axes of
        # malicious codes against an unrelated source returns nothing.
        rows2 = board_mod.read_memberships_by_codes(
            board_codes=list(malicious),
            stock_codes=list(malicious),
            source="zzshare",
        )
        assert rows2 == []
