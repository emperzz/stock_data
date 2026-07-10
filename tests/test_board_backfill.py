"""Tests for persistence.backfill module."""
from __future__ import annotations

import os
from unittest.mock import patch, MagicMock

import pytest

from stock_data.data_provider.persistence import board as board_mod
from stock_data.data_provider.persistence import db as db_mod
from stock_data.data_provider.persistence.backfill import run_ths_board_backfill


def test_auto_rate_limit_s_with_token_returns_1_2():
    """`_auto_rate_limit_s` returns 1.2s when ZZSHARE_TOKEN is set."""
    from stock_data.data_provider.persistence.backfill import _auto_rate_limit_s

    with patch.dict(os.environ, {"ZZSHARE_TOKEN": "any-value"}):
        assert _auto_rate_limit_s() == pytest.approx(1.2)


def test_auto_rate_limit_s_without_token_returns_3_0():
    """`_auto_rate_limit_s` returns 3.0s when ZZSHARE_TOKEN is absent."""
    from stock_data.data_provider.persistence.backfill import _auto_rate_limit_s

    env = {k: v for k, v in os.environ.items() if k != "ZZSHARE_TOKEN"}
    with patch.dict(os.environ, env, clear=True):
        assert _auto_rate_limit_s() == pytest.approx(3.0)


@pytest.fixture
def fresh_db(tmp_path, monkeypatch):
    """Ephemeral SQLite DB — reset module singletons so init_schema reruns."""
    monkeypatch.setattr(db_mod, "_db_path", None)
    monkeypatch.setattr(db_mod, "_conn", None)
    monkeypatch.setattr(board_mod, "_schema_initialized_paths", set())
    monkeypatch.setenv("STOCK_CACHE_DB_PATH", str(tmp_path / "test.db"))
    board_mod.init_schema()
    yield tmp_path / "test.db"


def _make_phase1_only_manager(boards):
    """Manager mock: get_all_boards returns boards for ths filtered by board_type;
    returns [] for zzshare (best-effort platecode backfill). get_board_stocks returns []
    (phase 1 doesn't fetch stocks)."""
    mock = MagicMock()

    def get_all_boards(source, board_type=None, subtype=None, include_quote=False):
        if source == "ths":
            filtered = [b for b in boards if board_type is None or b.get("type") == board_type]
            return (filtered, "ths")
        return ([], source)

    mock.get_all_boards.side_effect = get_all_boards
    mock.get_board_stocks.return_value = ([], "zzshare")
    return mock


def test_phase1_writes_to_stock_board(fresh_db, monkeypatch):
    """Phase 1 fetches boards, groupby type, writes to stock_board via update_cached_boards."""
    boards = [
        {"code": "C1", "name": "Concept-1", "type": "concept",
         "subtype": "同花顺概念", "platecode": "885001"},
        {"code": "C2", "name": "Concept-2", "type": "concept",
         "subtype": "同花顺概念", "platecode": "885002"},
        {"code": "I1", "name": "Industry-1", "type": "industry",
         "subtype": "同花顺行业", "platecode": "881001"},
    ]
    mock = _make_phase1_only_manager(boards)
    monkeypatch.setattr("time.sleep", lambda *_a, **_kw: None)

    report = run_ths_board_backfill(
        mock, inter_call_sleep_s=0.0, include_quote=False,
    )

    # phase1 success count = boards written to stock_board
    assert report.phase1.success == 3
    assert report.phase1_boards_emitted == 3
    # rows persisted: 2 concept + 1 industry
    concept_rows = board_mod._read_boards_from_db("concept", "ths")
    industry_rows = board_mod._read_boards_from_db("industry", "ths")
    assert len(concept_rows) == 2
    assert len(industry_rows) == 1
    # phase2 untouched (no boards had membership data)
    assert report.phase2.success == 0
