"""Unit tests for THS / ZZSHARE merge helpers in persistence/board.py."""

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


def _seed_board(
    code: str,
    platecode: str | None,
    name: str,
    board_type: str = "concept",
    source: str = "ths",
) -> None:
    """Insert a row into stock_board directly via the public upsert helper."""
    from datetime import datetime

    conn = board_mod.get_connection()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with conn:
        conn.execute(
            """INSERT OR REPLACE INTO stock_board
               (code, name, board_type, subtype, source, platecode, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                code,
                name,
                board_type,
                "同花顺概念" if board_type == "concept" else "同花顺行业",
                source,
                platecode,
                now,
            ),
        )


class TestResolveThsCidFromPlatecode:
    def test_concept_returns_different_cid(self, fresh_db):
        """Concept: platecode=885642 → cid=301558 (different value)."""
        _seed_board(
            code="301558",
            platecode="885642",
            name="跨境电商",
            board_type="concept",
            source="ths",
        )
        assert board_mod._resolve_ths_cid_from_platecode("885642") == "301558"

    def test_industry_returns_same_as_platecode(self, fresh_db):
        """Industry: platecode=881270 → code=881270 (industry has no separate cid)."""
        _seed_board(
            code="881270",
            platecode="881270",
            name="半导体",
            board_type="industry",
            source="ths",
        )
        assert board_mod._resolve_ths_cid_from_platecode("881270") == "881270"

    def test_unknown_returns_none(self, fresh_db):
        """Unknown platecode → None (caller falls back to zzshare-only)."""
        assert board_mod._resolve_ths_cid_from_platecode("999999") is None

    def test_only_matches_ths_source(self, fresh_db):
        """Platecode row under source='zzshare' must NOT match (we want ths only)."""
        _seed_board(
            code="300000",
            platecode="885000",
            name="x",
            board_type="concept",
            source="zzshare",
        )
        assert board_mod._resolve_ths_cid_from_platecode("885000") is None


class TestMergeThsZzshareByName:
    def test_ths_wins_by_default(self):
        """Same name in both: ths row kept (cid=3xxxxx), platecode from ths.

        Realistic ZzshareFetcher output has no separate 'platecode' field —
        the plate_code value lives under 'code' only.
        """
        ths = [{"code": "301558", "name": "跨境电商", "platecode": "885642",
                "type": "concept", "subtype": "同花顺概念", "source": "ths"}]
        zz = [{"code": "885642", "name": "跨境电商",
               "type": "concept", "subtype": "同花顺概念", "source": "zzshare"}]
        out = board_mod._merge_ths_zzshare_by_name(ths, zz)
        assert len(out) == 1
        assert out[0]["code"] == "301558"  # ths's cid, not zzshare's plate_code
        assert out[0]["platecode"] == "885642"  # ths's platecode
        assert out[0]["source"] == "ths"

    def test_zzshare_backfills_missing_platecode(self):
        """THS sidebar-only row (platecode=None), zzshare has same name →
        platecode backfilled from zzshare's plate_code (r['code']).

        Realistic ZzshareFetcher output: no 'platecode' field — backfill
        must read r['code'] on the zzshare row, not r['platecode'].
        Regression test for the production bug where 412/797 rows in
        stock_board had platecode=NULL because backfill never fired.
        """
        ths = [{"code": "301558", "name": "跨境电商", "platecode": None,
                "type": "concept", "subtype": "同花顺概念", "source": "ths"}]
        zz = [{"code": "885642", "name": "跨境电商",
               "type": "concept", "subtype": "同花顺概念", "source": "zzshare"}]
        out = board_mod._merge_ths_zzshare_by_name(ths, zz)
        assert len(out) == 1
        assert out[0]["code"] == "301558"
        assert out[0]["platecode"] == "885642"  # ← backfilled

    def test_zzshare_only_rows_appended(self):
        """zzshare has a board ths doesn't → appended with platecode=code.

        Appending rows must also carry platecode so the DB write in
        update_cached_boards doesn't store NULL. Realistic zzshare input
        has no separate platecode field; the merge helper must promote
        r['code'] (the plate_code) into r['platecode'] before the append,
        so the persisted row has a non-NULL platecode.
        """
        ths = [{"code": "301558", "name": "跨境电商", "platecode": "885642",
                "type": "concept", "subtype": "同花顺概念", "source": "ths"}]
        zz = [{"code": "885999", "name": "独此一家",
               "type": "concept", "subtype": "同花顺概念", "source": "zzshare"}]
        out = board_mod._merge_ths_zzshare_by_name(ths, zz)
        codes = [r["code"] for r in out]
        assert "301558" in codes
        assert "885999" in codes  # zzshare-only appended
        appended = next(r for r in out if r["code"] == "885999")
        assert appended["source"] == "ths"
        # NEW contract: appended zzshare-only row MUST have platecode set
        # (so the DB write stores a non-NULL value).
        assert appended["platecode"] == "885999", (
            f"expected platecode='885999' (from zzshare.code), "
            f"got {appended.get('platecode')!r}"
        )

    def test_dedup_by_code_and_name(self):
        """Same (code, name) emitted twice → one row. Both fetchers may emit
        the same cid in rare overlap cases — dedup must still hold."""
        ths = [{"code": "301558", "name": "跨境电商", "platecode": "885642",
                "type": "concept", "subtype": "同花顺概念", "source": "ths"}]
        zz = [{"code": "301558", "name": "跨境电商",
               "type": "concept", "subtype": "同花顺概念", "source": "zzshare"}]
        out = board_mod._merge_ths_zzshare_by_name(ths, zz)
        assert len(out) == 1

    def test_empty_inputs(self):
        assert board_mod._merge_ths_zzshare_by_name([], []) == []
        # Realistic zzshare-only: no 'platecode' key — backfill must promote
        # r['code'] into r['platecode'] before persisting.
        out = board_mod._merge_ths_zzshare_by_name(
            [], [{"code": "885999", "name": "x",
                  "type": "concept", "subtype": "同花顺概念", "source": "zzshare"}]
        )
        assert len(out) == 1
        assert out[0]["code"] == "885999"
        assert out[0]["platecode"] == "885999"
        assert out[0]["source"] == "ths"
        # ths-only sanity check.
        assert board_mod._merge_ths_zzshare_by_name(
            [{"code": "301558", "name": "x", "platecode": "885642",
              "type": "concept", "subtype": "同花顺概念", "source": "ths"}], []
        ) == [{"code": "301558", "name": "x", "platecode": "885642",
               "type": "concept", "subtype": "同花顺概念", "source": "ths"}]


class TestFetchBoardsWithZzshareBackfill:
    def test_returns_ths_rows_with_zzshare_backfill(self):
        """THS primary + ZZSHARE backfill; merged, source='ths' on every row."""
        from unittest.mock import MagicMock
        ths_rows = [
            {"code": "301558", "name": "跨境电商", "platecode": "885642",
             "type": "concept", "subtype": "同花顺概念", "source": "ths"},
            {"code": "301999", "name": "无名板块", "platecode": None,  # sidebar-only
             "type": "concept", "subtype": "同花顺概念", "source": "ths"},
        ]
        # Realistic ZzshareFetcher output: no 'platecode' key — the plate_code
        # value lives under 'code' only.
        zz_rows = [
            {"code": "885642", "name": "跨境电商",
             "type": "concept", "subtype": "同花顺概念", "source": "zzshare"},
            {"code": "885777", "name": "无名板块",  # backfills THS via name
             "type": "concept", "subtype": "同花顺概念", "source": "zzshare"},
            {"code": "885888", "name": "独此一家",  # zzshare-only
             "type": "concept", "subtype": "同花顺概念", "source": "zzshare"},
        ]
        mgr = MagicMock()
        # Real manager returns tuple[list[dict], str]
        mgr.get_all_boards.side_effect = [(ths_rows, "ths"), (zz_rows, "zzshare")]

        out = board_mod.fetch_boards_with_zzshare_backfill(
            board_type="concept", refresh=True, include_quote=False,
            subtype=None, manager=mgr,
        )

        # 1. THS called first
        assert mgr.get_all_boards.call_args_list[0].kwargs["source"] == "ths"
        # 2. ZZSHARE called second
        assert mgr.get_all_boards.call_args_list[1].kwargs["source"] == "zzshare"
        # 3. "无名板块" platecode backfilled from None → "885777" (from zz.code)
        by_code = {r["code"]: r for r in out}
        assert by_code["301999"]["platecode"] == "885777"
        # 4. zzshare-only "独此一家" appended, with platecode=code (regression:
        #    pre-fix this row had platecode=None → DB wrote NULL on persist).
        assert "885888" in by_code
        assert by_code["885888"]["platecode"] == "885888"
        # 5. All rows tagged source='ths'
        assert all(r["source"] == "ths" for r in out)

    def test_zzshare_failure_does_not_break(self):
        """ZZSHARE upstream fails → still return THS rows + WARNING log."""
        from unittest.mock import MagicMock
        ths_rows = [{"code": "301558", "name": "x", "platecode": "885642",
                     "type": "concept", "subtype": "同花顺概念", "source": "ths"}]
        mgr = MagicMock()
        # First call (ths) returns data; second call (zzshare) raises
        mgr.get_all_boards.side_effect = [
            (ths_rows, "ths"),
            Exception("upstream 503"),
        ]

        out = board_mod.fetch_boards_with_zzshare_backfill(
            board_type="concept", refresh=True, include_quote=False,
            subtype=None, manager=mgr,
        )
        assert len(out) == 1
        assert out[0]["code"] == "301558"

class TestFetchBoardStocksWithZzshareFallback:
    """Tests for the source-routing contract.

    Post-2026-07-10 the helper applies ONE cross-source fallback:
        ``source='ths'`` + ``include_quote=False`` → ZZSHARE primary,
        THS fallback on empty/error.

    For all other source/includes (source='zzshare', 'eastmoney', 'zhitu',
    or source='ths' + include_quote=True) the helper is strict-routed —
    no silent cross-source fallback. ``include_quote=True`` is THS-only
    because ZZSHARE emits no quote fields; falling back there would
    silently degrade the response to null quotes. See CLAUDE.md "Board
    Cache Source-Normalization → effective_source" for the user-visible
    contract on the response shape.
    """

    def _mgr(self, by_source_return):
        """Mock manager that returns different rows based on kwargs['source']."""
        from unittest.mock import MagicMock

        mgr = MagicMock()
        def side_effect(*a, **kw):
            return by_source_return.get(kw.get('source'), ([], 'unknown'))
        mgr.get_board_stocks.side_effect = side_effect
        return mgr

    def test_source_ths_routes_to_ths_only(self, mock_cid_resolver):
        """source='ths' → only ThsFetcher is called (zzshare NOT tried)."""
        mgr = self._mgr({
            'ths': ([{'stock_code': '300740', 'stock_name': 'x'}], 'ths'),
            'zzshare': ([{'stock_code': '300740', 'stock_name': 'should-not-be-called'}],
                        'zzshare'),
        })
        with mock_cid_resolver({('885642',): '301558'}):
            stocks, origin, _effective_source = board_mod.fetch_board_stocks_with_zzshare_fallback(
                board_code='885642', source='ths',
                include_quote=True, manager=mgr,
            )
        assert stocks == [{'stock_code': '300740', 'stock_name': 'x'}]
        assert origin == 'ths'
        # Only the THS call should have happened.
        assert mgr.get_board_stocks.call_count == 1
        ths_call = mgr.get_board_stocks.call_args_list[0]
        assert ths_call.kwargs['source'] == 'ths'
        assert ths_call.kwargs['board_code'] == '301558'   # cid translated

    def test_source_zzshare_routes_to_zzshare_with_platecode(self):
        """source='zzshare' → ZzshareFetcher called with platecode (no cid translation)."""
        mgr = self._mgr({
            'zzshare': ([{'stock_code': '300740', 'stock_name': 'x'}], 'zzshare'),
        })
        stocks, origin, _effective_source = board_mod.fetch_board_stocks_with_zzshare_fallback(
            board_code='885642', source='zzshare',
            include_quote=False, manager=mgr,
        )
        assert stocks == [{'stock_code': '300740', 'stock_name': 'x'}]
        assert origin == 'zzshare'
        zz_call = mgr.get_board_stocks.call_args_list[0]
        assert zz_call.kwargs['source'] == 'zzshare'
        assert zz_call.kwargs['board_code'] == '885642'   # platecode as-is

    def test_zzshare_empty_triggers_ths_fallback(self, mock_cid_resolver):
        """source='ths' returning empty rows → falls back to ZZSHARE.

        Post-2026-07-10 optimization: ``source='ths'`` +
        ``include_quote=False`` prefers ZZSHARE first (lighter
        request), and falls back to THS only when ZZSHARE returns 0 rows
        or raises. This test covers the second-half behaviour: empty
        rows on the ZZSHARE leg (return value [] from the mgr for
        'zzshare') triggers THS as the fallback fetch.
        """
        mgr = self._mgr({
            'zzshare': ([], 'zzshare'),         # leg 1: empty → triggers fallback
            'ths': ([{'stock_code': '300740', 'stock_name': 'ths-row'}], 'ths'),
        })
        with mock_cid_resolver({('885642',): '301558'}):
            stocks, origin, effective_source = board_mod.fetch_board_stocks_with_zzshare_fallback(
                board_code='885642', source='ths',
                include_quote=False, manager=mgr,
            )
        assert stocks == [{'stock_code': '300740', 'stock_name': 'ths-row'}]
        assert origin == 'ths'
        # effective_source reports 'ths' even though requested source was 'ths'
        # AND a fallback was attempted — the THS leg actually served.
        assert effective_source == 'ths'
        # Both zzshare (empty) and ths (served) attempts; cid resolved too.
        assert mgr.get_board_stocks.call_count == 2

    def test_source_ths_raises_propagates_no_fallback(self, mock_cid_resolver):
        """source='ths' raising → DataFetchError propagates; NO zzshare fallback."""
        from stock_data.data_provider.base import DataFetchError

        mgr = self._mgr({'ths': ([], 'ths')})

        def ths_side_effect(*a, **kw):
            raise DataFetchError('ths 503')

        mgr.get_board_stocks.side_effect = ths_side_effect
        with mock_cid_resolver({('885642',): '301558'}), \
             pytest.raises(DataFetchError):
            board_mod.fetch_board_stocks_with_zzshare_fallback(
                board_code='885642', source='ths',
                include_quote=True, manager=mgr,
            )
        # Single attempt to THS, then the exception propagates.
        assert mgr.get_board_stocks.call_count == 1

    def test_cid_unresolved_returns_empty_label_ths(self, mock_cid_resolver):
        """cid resolution miss → ZZSHARE leg ran (no cid needed), THS leg skipped.

        ZZSHARE doesn't need the cid (it accepts the platecode
        directly), so the ZZSHARE leg still runs when cid resolution
        misses. The THS fallback leg is then skipped because cid is
        required for the THS URL. Effective source is 'zzshare' on the
        empty path because the THS leg didn't actually fire
        (``effective_source` is only updated when a leg completes).
        """
        mgr = self._mgr({
            'zzshare': ([{'stock_code': 'x', 'stock_name': 'x'}], 'zzshare'),
            'ths': ([{'stock_code': 'x'}], 'ths'),
        })
        with mock_cid_resolver({('999999',): None}):
            stocks, origin, effective_source = board_mod.fetch_board_stocks_with_zzshare_fallback(
                board_code='999999', source='ths',
                include_quote=False, manager=mgr,
            )
        assert stocks == [{'stock_code': 'x', 'stock_name': 'x'}]
        assert origin == 'ths'
        assert effective_source == 'zzshare'
        # One ZZSHARE call (success — not the THS path, which requires cid).
        assert mgr.get_board_stocks.call_count == 1

    def test_unsupported_source_raises_value_error(self):
        """Unknown source slug → ValueError (route layer maps to 400)."""
        mgr = self._mgr({})
        with pytest.raises(ValueError, match="unsupported source"):
            board_mod.fetch_board_stocks_with_zzshare_fallback(
                board_code='885642', source='bogus',
                include_quote=False, manager=mgr,
            )


@pytest.fixture
def mock_cid_resolver(monkeypatch):
    from contextlib import contextmanager
    @contextmanager
    def _ctx(mapping):
        def fake(platecode):
            return mapping.get((platecode,))
        monkeypatch.setattr(board_mod, '_resolve_ths_cid_from_platecode', fake)
        yield
    return _ctx
