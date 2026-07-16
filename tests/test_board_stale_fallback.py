"""Tests for P3-a1 (H4): board upstream-fail → fall back to stale SQLite cache.

The non-quote path of ``get_board_stocks`` previously raised DataFetchError
up to the route layer (503) when both ZZSHARE and THS failed upstream, even
when ``stock_board_membership`` already contained a usable snapshot from a
prior refresh. Compare with ``pool_daily.get_pool:325-336`` which already
does the right thing.

These tests pin the fallback contract: on upstream DataFetchError the
helper must (a) return the cached rows, (b) tag origin='persistence',
(c) tag effective_source='ths' (the unified cache key), and (d) leave
``reason`` set so the route layer can surface the staleness in the response.
"""
from __future__ import annotations

import pytest

from stock_data.data_provider.base import DataFetchError
from stock_data.data_provider.persistence import board as board_mod
from stock_data.data_provider.persistence import db as db_mod


@pytest.fixture
def fresh_db(tmp_path, monkeypatch):
    monkeypatch.setattr(db_mod, "_db_path", None)
    monkeypatch.setattr(db_mod, "_conn", None)
    monkeypatch.setattr(board_mod, "_schema_initialized_paths", set())
    monkeypatch.setenv("STOCK_CACHE_DB_PATH", str(tmp_path / "test.db"))
    board_mod.init_schema()
    yield tmp_path / "test.db"


def _seed_stock_board(board_code: str, name: str) -> None:
    conn = db_mod.get_connection()
    conn.execute(
        """INSERT INTO stock_board (code, name, board_type, subtype, source)
           VALUES (?, ?, ?, ?, 'ths')""",
        (board_code, name, "concept", "concept"),
    )
    conn.commit()


def _seed_membership(board_code: str, stock_code: str, stock_name: str) -> None:
    conn = db_mod.get_connection()
    conn.execute(
        """INSERT INTO stock_board_membership
           (board_code, source, stock_code, stock_name,
            board_name, board_type, subtype)
           VALUES (?, 'ths', ?, ?, ?, 'concept', 'concept')""",
        (board_code, stock_code, stock_name, board_code),
    )
    conn.commit()


def test_upstream_failure_falls_back_to_cached_stocks(fresh_db, monkeypatch):
    """When upstream DataFetchError fires, the helper must return cached rows
    with origin='persistence' instead of raising a 503."""
    _seed_stock_board("BK2001", "测试板块")
    _seed_membership("BK2001", "600519", "贵州茅台")
    _seed_membership("BK2001", "000001", "平安银行")

    # Force needs_refresh by setting the tracker to first-call
    monkeypatch.setattr(
        board_mod._refresh_tracker, "is_first_call", lambda key: True
    )
    # Simulate both ZZSHARE and THS failing
    monkeypatch.setattr(
        board_mod,
        "fetch_board_stocks_with_zzshare_fallback",
        lambda **kwargs: (_ for _ in ()).throw(
            DataFetchError("simulated upstream outage")
        ),
    )

    (
        stocks,
        origin,
        effective_source,
        reason,
        quote_truncated,
        cached_count,
    ) = board_mod.get_board_stocks(
        board_code="BK2001",
        source="ths",
        manager=object(),  # not reached because fallback fires first
        include_quote=False,
    )

    # Cached rows are returned untouched
    assert {s["stock_code"] for s in stocks} == {"600519", "000001"}
    assert origin == "persistence"
    assert effective_source == "ths"
    assert reason == "stale_after_upstream_failure"
    assert quote_truncated is False
    assert cached_count == 2


def test_upstream_failure_without_cache_raises(fresh_db, monkeypatch):
    """When both upstream and cache are empty, the DataFetchError must
    still bubble up — we never silently return an empty list."""
    # No cache seed → cached_full is []
    monkeypatch.setattr(
        board_mod._refresh_tracker, "is_first_call", lambda key: True
    )
    monkeypatch.setattr(
        board_mod,
        "fetch_board_stocks_with_zzshare_fallback",
        lambda **kwargs: (_ for _ in ()).throw(
            DataFetchError("simulated upstream outage")
        ),
    )

    with pytest.raises(DataFetchError, match="simulated upstream outage"):
        board_mod.get_board_stocks(
            board_code="BK2002",
            source="ths",
            manager=object(),
            include_quote=False,
        )