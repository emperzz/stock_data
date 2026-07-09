"""Unit tests for persistence.board.get_stock_memberships helper."""

from __future__ import annotations

from unittest.mock import MagicMock

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


class TestResolveBoardTypes:
    """resolve_board_types — single source of truth for board type/subtype lookup."""

    def test_empty_codes_returns_empty_dict(self, fresh_db):
        """Empty input is a no-op (no SQL)."""
        assert board_mod.resolve_board_types([], source="eastmoney") == {}

    def test_returns_type_and_subtype_for_known_codes(self, fresh_db):
        """Codes present in stock_board → dict mapping to {type, subtype}."""
        conn = db_mod.get_connection()
        # Seed two rows with non-default subtype (region-style)
        conn.execute(
            "INSERT INTO stock_board (code, name, board_type, subtype, source) "
            "VALUES (?, ?, ?, ?, ?)",
            ("BK0615", "中药概念", "concept", "concept", "eastmoney"),
        )
        conn.execute(
            "INSERT INTO stock_board (code, name, board_type, subtype, source) "
            "VALUES (?, ?, ?, ?, ?)",
            ("BK0481", "光伏设备", "industry", "industry", "eastmoney"),
        )
        conn.commit()

        result = board_mod.resolve_board_types(
            ["BK0615", "BK0481"], source="eastmoney"
        )
        assert result == {
            "BK0615": {"type": "concept", "subtype": "concept"},
            "BK0481": {"type": "industry", "subtype": "industry"},
        }

    def test_unknown_codes_absent_from_result(self, fresh_db):
        """Codes not in stock_board are simply missing — callers default-fill."""
        conn = db_mod.get_connection()
        conn.execute(
            "INSERT INTO stock_board (code, name, board_type, subtype, source) "
            "VALUES (?, ?, ?, ?, ?)",
            ("BK0615", "中药概念", "concept", "concept", "eastmoney"),
        )
        conn.commit()

        result = board_mod.resolve_board_types(
            ["BK0615", "BK9999"], source="eastmoney"
        )
        # BK9999 absent → not in dict; caller decides what to do.
        assert "BK0615" in result
        assert "BK9999" not in result

    def test_source_filters_correctly(self, fresh_db):
        """Same code under different sources returns source-specific rows."""
        conn = db_mod.get_connection()
        conn.execute(
            "INSERT INTO stock_board (code, name, board_type, subtype, source) "
            "VALUES (?, ?, ?, ?, ?)",
            ("sw_yx", "申万行业", "industry", "申万行业", "zhitu"),
        )
        conn.execute(
            "INSERT INTO stock_board (code, name, board_type, subtype, source) "
            "VALUES (?, ?, ?, ?, ?)",
            ("sw_yx", "Bank Industry", "industry", "industry", "eastmoney"),
        )
        conn.commit()

        zhitu = board_mod.resolve_board_types(["sw_yx"], source="zhitu")
        em = board_mod.resolve_board_types(["sw_yx"], source="eastmoney")
        assert zhitu["sw_yx"]["subtype"] == "申万行业"
        assert em["sw_yx"]["subtype"] == "industry"


class TestGetStockMembershipsColdFill:
    """Cold-fill behavior: only triggers for zhitu, only when cold_fill=True."""

    def test_cold_fill_true_writes_to_membership_and_returns_zhitu_origin(self, fresh_db, monkeypatch):
        """cold_fill=True + cold zhitu data → fetcher called, rows upserted, origin='zhitu'."""
        # Mock manager that returns boards for the cold zhitu path
        mock_manager = MagicMock()
        mock_manager.get_stock_boards.return_value = (
            [
                {"code": "sw_yx", "name": "SW", "type": "industry", "subtype": "申万行业"},
                {"code": "chgn_700532", "name": "MSCI中国", "type": "concept", "subtype": "热门概念"},
            ],
            "zhitu",
        )

        # Seed stock_list so the upsert path can resolve stock_name
        from stock_data.data_provider.persistence import stock_list as stock_list_mod

        stock_list_mod._schema_initialized_paths = set()
        stock_list_mod.init_schema()
        conn = db_mod.get_connection()
        conn.execute("INSERT INTO stock_list (code, name, market) VALUES ('600519', '贵州茅台', 'csi')")
        conn.commit()

        # Stock has no zhitu data in membership yet → cold-fill should fire
        entries, cold, origin = board_mod.get_stock_memberships(
            stock_code="600519", sources=["zhitu"], cold_fill=True, manager=mock_manager
        )

        # Fetcher was called
        mock_manager.get_stock_boards.assert_called_once_with("600519", source="zhitu")

        # Rows were written to membership
        conn = db_mod.get_connection()
        rows = conn.execute(
            "SELECT board_code, source FROM stock_board_membership WHERE stock_code='600519'"
        ).fetchall()
        assert len(rows) == 2
        assert {r["source"] for r in rows} == {"zhitu"}

        # Return values reflect the cold-fill
        assert len(entries) == 2
        assert {e["source"] for e in entries} == {"zhitu"}
        assert cold == []
        assert origin == "zhitu"

    def test_cold_fill_empty_when_fetcher_returns_no_rows(self, fresh_db, monkeypatch):
        """cold_fill=True + fetcher returns [] → origin='cold_fill_empty'.

        区分于 cache-miss (origin='persistence') 和 cold-fill-写入 (origin=fetcher 名)。
        触发场景: 北交所 (4/8 前缀) 调 source=ths + cold_fill=True → ThsFetcher
        早退返回 [],但网络层逻辑已生效 (或本想生效)。这个 sentinel 让上层能
        区分"没有命中缓存" 与 "命中了但上游拒绝/不支持"。
        """
        mock_manager = MagicMock()
        mock_manager.get_stock_boards.return_value = ([], "ths")  # 上游返回空

        from stock_data.data_provider.persistence import stock_list as stock_list_mod
        stock_list_mod._schema_initialized_paths = set()
        stock_list_mod.init_schema()

        entries, cold, origin = board_mod.get_stock_memberships(
            stock_code="830799", sources=["ths"], cold_fill=True, manager=mock_manager
        )
        assert entries == []
        assert cold == ["ths"]
        assert origin == "cold_fill_empty"
        mock_manager.get_stock_boards.assert_called_once_with("830799", source="ths")


class TestGetStockMembershipsBoardNameOverride:
    """When stock_board_membership.board_name equals board_code (legacy write
    from update_cached_board_stocks pre-2026-07-09, when stock_board was
    empty at write time), get_stock_memberships MUST resolve name from
    the authoritative stock_board table, not from the membership row.

    Root cause (pre-fix): update_cached_board_stocks fell back to
    ``board_name = board_code`` when stock_board had no row for the
    (code, source) pair. That stale value is what's persisted in
    stock_board_membership.board_name, and _read_membership_entries
    previously trusted it. Result: /stocks/{code}/boards from
    persistence returned ``name == code``.

    Fix: at read time, LEFT JOIN stock_board on (board_code, source)
    and use stock_board.name when available; fall back to the
    membership row's board_name otherwise (legacy boards absent from
    the board-list cache).
    """

    def test_returns_name_from_stock_board_over_membership_stale_code(self, fresh_db):
        """stock_board has the real name; membership row stores board_code.

        Membership row is the legacy buggy state (board_name == board_code).
        Read path must return the authoritative stock_board.name.
        """
        conn = db_mod.get_connection()
        # Authoritative name in stock_board
        conn.execute(
            "INSERT INTO stock_board (code, name, board_type, subtype, source) "
            "VALUES (?, ?, ?, ?, ?)",
            ("BK1001", "白酒", "industry", "industry", "eastmoney"),
        )
        # Membership row with the legacy buggy value (board_name = board_code)
        conn.execute(
            "INSERT INTO stock_board_membership "
            "(board_code, stock_code, source, board_name, stock_name, "
            " board_type, subtype, refreshed_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            ("BK1001", "600519", "eastmoney", "BK1001", "贵州茅台",
             "industry", "industry", "2026-07-01 00:00:00"),
        )
        conn.commit()

        entries, _, _ = board_mod.get_stock_memberships(
            stock_code="600519", sources=["eastmoney"]
        )
        assert len(entries) == 1
        assert entries[0]["code"] == "BK1001"
        # The fix: name comes from stock_board, NOT from membership's stale value.
        assert entries[0]["name"] == "白酒", (
            f"expected authoritative name from stock_board; got {entries[0]['name']!r} "
            f"(== code means the membership row's stale board_name leaked through)"
        )

    def test_falls_back_to_membership_board_name_when_stock_board_missing(self, fresh_db):
        """stock_board has no row for (code, source) → fall back to membership row.

        The legacy buggy value (board_name == board_code) still surfaces,
        but only when stock_board genuinely has no authoritative row. This
        matches the pre-fix behavior for boards that were never written to
        stock_board — the route layer's get_board_name_with_fallback
        separately handles those.
        """
        conn = db_mod.get_connection()
        # No stock_board row for BK9999 → fallback path
        conn.execute(
            "INSERT INTO stock_board_membership "
            "(board_code, stock_code, source, board_name, stock_name, "
            " board_type, subtype, refreshed_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            ("BK9999", "600519", "eastmoney", "BK9999", "贵州茅台",
             "concept", "concept", "2026-07-01 00:00:00"),
        )
        conn.commit()

        entries, _, _ = board_mod.get_stock_memberships(
            stock_code="600519", sources=["eastmoney"]
        )
        assert len(entries) == 1
        assert entries[0]["code"] == "BK9999"
        # No stock_board row → fall back to membership's stored board_name
        assert entries[0]["name"] == "BK9999"
        # Type/subtype also fall back to membership's stored values
        assert entries[0]["type"] == "concept"
        assert entries[0]["subtype"] == "concept"

    def test_keeps_membership_name_when_both_agree(self, fresh_db):
        """stock_board.name == stock_board_membership.board_name → no change.

        Sanity check: when both layers agree (the normal post-fix write
        path), the read path returns that value verbatim.
        """
        conn = db_mod.get_connection()
        conn.execute(
            "INSERT INTO stock_board (code, name, board_type, subtype, source) "
            "VALUES (?, ?, ?, ?, ?)",
            ("BK1001", "白酒", "industry", "industry", "eastmoney"),
        )
        conn.execute(
            "INSERT INTO stock_board_membership "
            "(board_code, stock_code, source, board_name, stock_name, "
            " board_type, subtype, refreshed_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            ("BK1001", "600519", "eastmoney", "白酒", "贵州茅台",
             "industry", "industry", "2026-07-09 00:00:00"),
        )
        conn.commit()

        entries, _, _ = board_mod.get_stock_memberships(
            stock_code="600519", sources=["eastmoney"]
        )
        assert len(entries) == 1
        assert entries[0]["name"] == "白酒"

    def test_override_is_source_scoped(self, fresh_db):
        """stock_board row under source='eastmoney' only overrides the matching source.

        The same board_code under a different source (no stock_board row for
        it) keeps the membership row's stored name. Verifies the JOIN is
        scoped to (code, source), not just (code).
        """
        conn = db_mod.get_connection()
        # Only eastmoney has stock_board row
        conn.execute(
            "INSERT INTO stock_board (code, name, board_type, subtype, source) "
            "VALUES (?, ?, ?, ?, ?)",
            ("BK1001", "白酒-eastmoney", "industry", "industry", "eastmoney"),
        )
        # zhitu row has the same code but no stock_board counterpart
        conn.execute(
            "INSERT INTO stock_board_membership "
            "(board_code, stock_code, source, board_name, stock_name, "
            " board_type, subtype, refreshed_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            ("BK1001", "600519", "zhitu", "BK1001", "贵州茅台",
             "industry", "industry", "2026-07-01 00:00:00"),
        )
        conn.commit()

        entries, _, _ = board_mod.get_stock_memberships(
            stock_code="600519", sources=["zhitu"]
        )
        assert len(entries) == 1
        # zhitu has no stock_board row → fall back to membership's board_name
        assert entries[0]["name"] == "BK1001"

    def test_returns_board_type_from_stock_board_over_membership_stale_empty(self, fresh_db):
        """stock_board has the real board_type; membership row stores '' (legacy bug).

        Same root cause as the name override: update_cached_board_stocks fell
        back to ``board_type = ''`` when stock_board had no row at write time.
        Read path must return the authoritative stock_board.board_type.
        """
        conn = db_mod.get_connection()
        conn.execute(
            "INSERT INTO stock_board (code, name, board_type, subtype, source) "
            "VALUES (?, ?, ?, ?, ?)",
            ("BK1001", "白酒", "industry", "industry", "eastmoney"),
        )
        # Legacy buggy state: board_type = '' (the pre-fix fallback)
        conn.execute(
            "INSERT INTO stock_board_membership "
            "(board_code, stock_code, source, board_name, stock_name, "
            " board_type, subtype, refreshed_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            ("BK1001", "600519", "eastmoney", "BK1001", "贵州茅台",
             "", "industry", "2026-07-01 00:00:00"),
        )
        conn.commit()

        entries, _, _ = board_mod.get_stock_memberships(
            stock_code="600519", sources=["eastmoney"]
        )
        assert len(entries) == 1
        # The fix: board_type comes from stock_board, NOT from membership's empty value.
        assert entries[0]["type"] == "industry", (
            f"expected authoritative type from stock_board; got {entries[0]['type']!r} "
            f"(empty means the membership row's stale board_type leaked through)"
        )

    def test_returns_subtype_from_stock_board_over_membership_stale_empty(self, fresh_db):
        """stock_board has the real subtype; membership row stores NULL.

        Symmetric to name/type override. update_cached_board_stocks fell
        back to ``subtype = NULL`` when stock_board had no row at write
        time. Read path must return the authoritative stock_board.subtype.
        """
        conn = db_mod.get_connection()
        conn.execute(
            "INSERT INTO stock_board (code, name, board_type, subtype, source) "
            "VALUES (?, ?, ?, ?, ?)",
            ("BK1001", "白酒", "industry", "industry", "eastmoney"),
        )
        # Legacy buggy state: subtype = NULL (the pre-fix fallback)
        conn.execute(
            "INSERT INTO stock_board_membership "
            "(board_code, stock_code, source, board_name, stock_name, "
            " board_type, subtype, refreshed_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            ("BK1001", "600519", "eastmoney", "BK1001", "贵州茅台",
             "industry", None, "2026-07-01 00:00:00"),
        )
        conn.commit()

        entries, _, _ = board_mod.get_stock_memberships(
            stock_code="600519", sources=["eastmoney"]
        )
        assert len(entries) == 1
        # The fix: subtype comes from stock_board, NOT from membership's NULL.
        assert entries[0]["subtype"] == "industry"

    def test_override_applies_to_name_type_subtype_together(self, fresh_db):
        """One read returns all three fields overridden by stock_board in a single pass."""
        conn = db_mod.get_connection()
        conn.execute(
            "INSERT INTO stock_board (code, name, board_type, subtype, source) "
            "VALUES (?, ?, ?, ?, ?)",
            ("BK1001", "白酒", "industry", "industry", "eastmoney"),
        )
        # All three fields buggy: name=code, type='', subtype=NULL
        conn.execute(
            "INSERT INTO stock_board_membership "
            "(board_code, stock_code, source, board_name, stock_name, "
            " board_type, subtype, refreshed_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            ("BK1001", "600519", "eastmoney", "BK1001", "贵州茅台",
             "", None, "2026-07-01 00:00:00"),
        )
        conn.commit()

        entries, _, _ = board_mod.get_stock_memberships(
            stock_code="600519", sources=["eastmoney"]
        )
        assert len(entries) == 1
        e = entries[0]
        assert e["name"] == "白酒"
        assert e["type"] == "industry"
        assert e["subtype"] == "industry"

    def test_override_source_scoped_in_mixed_response(self, fresh_db):
        """Multi-source query: each row overrides only by its own (code, source).

        eastmoney has a stock_board row (so its membership row gets the
        override); zhitu does NOT (so its row keeps the membership value).
        One query, one response, both behaviors visible side-by-side.
        """
        conn = db_mod.get_connection()
        # eastmoney authoritative row
        conn.execute(
            "INSERT INTO stock_board (code, name, board_type, subtype, source) "
            "VALUES (?, ?, ?, ?, ?)",
            ("BK1001", "白酒-eastmoney", "industry", "industry", "eastmoney"),
        )
        # eastmoney membership: buggy
        conn.execute(
            "INSERT INTO stock_board_membership "
            "(board_code, stock_code, source, board_name, stock_name, "
            " board_type, subtype, refreshed_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            ("BK1001", "600519", "eastmoney", "BK1001", "贵州茅台",
             "", None, "2026-07-01 00:00:00"),
        )
        # zhitu membership: no stock_board counterpart — keeps legacy values
        conn.execute(
            "INSERT INTO stock_board_membership "
            "(board_code, stock_code, source, board_name, stock_name, "
            " board_type, subtype, refreshed_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            ("BK1001", "600519", "zhitu", "BK1001-zhitu-fallback", "贵州茅台",
             "concept", "concept", "2026-07-01 00:00:00"),
        )
        conn.commit()

        entries, _, _ = board_mod.get_stock_memberships(
            stock_code="600519", sources=["eastmoney", "zhitu"]
        )
        by_source = {e["source"]: e for e in entries}
        assert set(by_source) == {"eastmoney", "zhitu"}
        # eastmoney: override applied
        assert by_source["eastmoney"]["name"] == "白酒-eastmoney"
        assert by_source["eastmoney"]["type"] == "industry"
        # zhitu: no stock_board row → fallback to membership's stored values
        assert by_source["zhitu"]["name"] == "BK1001-zhitu-fallback"
        assert by_source["zhitu"]["type"] == "concept"

    def test_ths_concept_override_matches_via_platecode_not_code(self, fresh_db):
        """THS concept boards: membership stores board_code=platecode (885xxx),
        stock_board stores code=cid (3xxxxx) with platecode=885xxx.

        The naive JOIN ``sb.code = m.board_code`` misses these rows because
        cid != platecode. The fix joins on ``sb.code OR sb.platecode`` so the
        platecode arm picks up THS concept boards. Without this override, the
        user sees ``name=board_code`` for every THS concept membership row.

        Reproduces the exact user-reported symptom: stock_code=000688,
        board_code=885652 (THS concept), name/board_type/subtype all buggy.
        """
        conn = db_mod.get_connection()
        # stock_board row mimicking ThsFetcher.get_all_boards output:
        # code = cid, platecode = the 885xxx the public API uses
        conn.execute(
            "INSERT INTO stock_board (code, name, board_type, subtype, source, platecode) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            ("300351", "东百集团", "concept", "同花顺概念", "ths", "885652"),
        )
        # membership row with the buggy legacy values (board_code = platecode,
        # NOT cid; board_name = board_code; board_type = ''; subtype = NULL)
        conn.execute(
            "INSERT INTO stock_board_membership "
            "(board_code, stock_code, source, board_name, stock_name, "
            " board_type, subtype, refreshed_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            ("885652", "000688", "ths", "885652", "国华人寿",
             "", None, "2026-07-01 00:00:00"),
        )
        conn.commit()

        entries, _, _ = board_mod.get_stock_memberships(
            stock_code="000688", sources=["ths"]
        )
        assert len(entries) == 1
        e = entries[0]
        # The fix: the platecode arm of the JOIN matches 885652.
        assert e["code"] == "885652"
        assert e["name"] == "东百集团", (
            f"expected override name from stock_board; got {e['name']!r}"
        )
        assert e["type"] == "concept"
        assert e["subtype"] == "同花顺概念"
