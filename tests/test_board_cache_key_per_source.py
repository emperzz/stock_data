"""Per-source keying of the board cache + the refresh tracker.

Post-2026-09-11 the board layer is strictly routed (spec §2 D2): a ``ths``
request and a ``zzshare`` request for the same ``board_code`` are different
boards living in disjoint code spaces (885xxx/881xxx platecodes vs 801xxx
zzshare plates). Nothing may read across that boundary:

* ``stock_board_membership`` rows are keyed ``(board_code, source)`` — a row
  written by one source must be invisible to the other.
* ``_refresh_tracker`` is keyed ``f"{board_code}:{source}"`` — otherwise the
  first ``ths`` call of the day would mark a ``zzshare`` query as "already
  refreshed today" and serve it the wrong source's rows.
* ``resolve_ths_cid`` resolves ONLY THS rows, and deliberately does NOT fall
  back to the row's ``code`` column when ``cid`` is NULL.

Reference: docs/superpowers/specs/2026-09-11-board-source-split-design.md
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


def _membership_row_count(board_code: str, source: str) -> int:
    row = (
        db_mod.get_connection()
        .execute(
            "SELECT COUNT(*) AS n FROM stock_board_membership WHERE board_code = ? AND source = ?",
            (board_code, source),
        )
        .fetchone()
    )
    return row["n"]


# ── stock_board_membership: rows are keyed (board_code, source) ──────────


def test_zzshare_membership_invisible_to_ths(fresh_db):
    """A zzshare write must not leak into the ths read path."""
    board_mod.update_cached_board_stocks(
        "801001", "zzshare", [{"stock_code": "600519", "stock_name": "贵州茅台"}]
    )

    assert board_mod._read_board_stocks_from_db("801001", "ths") == []
    zz = board_mod._read_board_stocks_from_db("801001", "zzshare")
    assert len(zz) == 1
    assert zz[0]["stock_code"] == "600519"
    assert _membership_row_count("801001", "ths") == 0
    assert _membership_row_count("801001", "zzshare") == 1


def test_ths_membership_invisible_to_zzshare(fresh_db):
    """Mirror case: a ths write must not leak into the zzshare read path."""
    board_mod.update_cached_board_stocks(
        "885333", "ths", [{"stock_code": "000001", "stock_name": "平安银行"}]
    )

    assert board_mod._read_board_stocks_from_db("885333", "zzshare") == []
    ths = board_mod._read_board_stocks_from_db("885333", "ths")
    assert len(ths) == 1
    assert ths[0]["stock_code"] == "000001"


# ── refresh tracker: key is f"{board_code}:{source}" ─────────────────────


def test_refresh_tracker_key_includes_source(fresh_db, monkeypatch):
    """Both sources must probe their own tracker key.

    Neither request will find anything in the cache read (the DB is empty),
    so ``get_board_stocks`` falls through to the F10 leg; the point is which
    tracker keys were consulted on the way.
    """
    seen_keys: list[str] = []

    def _spy(key: str) -> bool:
        seen_keys.append(key)
        return True  # first call of the day → forces the fetch path

    monkeypatch.setattr(board_mod._refresh_tracker, "is_first_call", _spy)
    monkeypatch.setattr(board_mod, "get_cached_market_quotes", lambda m: None)

    class _FakeManager:
        """Empty upstream for both the F10 and the AJAX tier."""

        def get_board_stocks_full(self, **kw):
            return [], "fake"

        def get_board_stocks(self, **kw):
            return [], "fake"

    manager = _FakeManager()
    board_mod.get_board_stocks("885333", source="ths", manager=manager)
    board_mod.get_board_stocks("801001", source="zzshare", manager=manager)

    assert "885333:ths" in seen_keys
    assert "801001:zzshare" in seen_keys
    # No cross-source key was ever probed.
    assert "885333:zzshare" not in seen_keys
    assert "801001:ths" not in seen_keys


# ── resolve_ths_cid: THS-only, and no `code` fallback ────────────────────


def _seed_board_row(code: str, source: str, cid: str | None, board_type: str = "concept") -> None:
    conn = db_mod.get_connection()
    conn.execute(
        """INSERT INTO stock_board (code, name, board_type, subtype, source, cid)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (code, f"board-{code}", board_type, board_type, source, cid),
    )
    conn.commit()


def test_resolve_ths_cid_returns_none_for_null_cid(fresh_db):
    """The pre-2026-09-11 code fell back to the row's ``code`` column when
    ``cid`` was NULL. That is exactly how a zzshare plate code (801xxx) got
    handed to ThsFetcher as if it were a cid — so the fallback is gone and
    a NULL cid now resolves to ``None``."""
    _seed_board_row("801001", "ths", None)
    assert board_mod.resolve_ths_cid("801001") is None


def test_resolve_ths_cid_returns_concept_cid(fresh_db):
    _seed_board_row("885333", "ths", "300188")
    assert board_mod.resolve_ths_cid("885333") == "300188"


def test_resolve_ths_cid_returns_industry_cid(fresh_db):
    """Industry rows keep ``cid == code`` (881xxx) by construction."""
    _seed_board_row("881121", "ths", "881121", board_type="industry")
    assert board_mod.resolve_ths_cid("881121") == "881121"


def test_resolve_ths_cid_unknown_code_is_none(fresh_db):
    assert board_mod.resolve_ths_cid("999999") is None


def test_resolve_ths_cid_ignores_non_ths_sources(fresh_db):
    """A row that only exists under another source is not resolvable."""
    _seed_board_row("801001", "zzshare", "300188")
    assert board_mod.resolve_ths_cid("801001") is None
