"""Tests for stock_board_cache.get_board_name_with_fallback.

Review 2026-07-06 finding #10: the /boards/{code}/stocks route was
calling manager.get_all_boards(...) directly to resolve board names,
violating CLAUDE.md's Persistence-Only Routing rule. Move the fallback
loop + exception handling into persistence.board and have the route
call the helper instead.
"""

from unittest.mock import MagicMock

import pytest

from stock_data.data_provider.base import DataFetchError
from stock_data.data_provider.persistence import board as board_mod
from stock_data.data_provider.persistence import db as db_mod


@pytest.fixture(autouse=True)
def _clean_db(tmp_path, monkeypatch):
    """Use a tmp_path DB instead of the production stock_cache.db.

    Older versions of this fixture deleted rows from the real DB,
    which silently nuked user data whenever this test ran. Switch to
    a per-test tmp_path DB so tests cannot affect production state.
    """
    monkeypatch.setattr(db_mod, "_db_path", None)
    monkeypatch.setattr(db_mod, "_conn", None)
    board_mod._schema_initialized_paths = set()
    monkeypatch.setenv("STOCK_CACHE_DB_PATH", str(tmp_path / "test.db"))
    board_mod.init_schema()
    yield


def test_get_board_name_with_fallback_returns_cached_when_present():
    """Cache hit returns cached name; no manager call."""
    board_mod.update_cached_boards(
        "concept",
        "eastmoney",
        [{"code": "BK0996", "name": "人形机器人", "type": "concept", "subtype": "concept"}],
    )
    manager = MagicMock()
    name = board_mod.get_board_name_with_fallback("BK0996", "eastmoney", manager=manager)
    assert name == "人形机器人"
    manager.get_all_boards.assert_not_called()


def test_get_board_name_with_fallback_returns_none_when_no_manager_and_cache_miss():
    """Cache miss + no manager → None (caller substitutes bare board_code).

    No manager = no fetcher fallback at all. Helper short-circuits and
    returns None. The caller (route layer) substitutes the bare code.
    """
    name = board_mod.get_board_name_with_fallback("BK_MISSING", "eastmoney")
    assert name is None


def test_get_board_name_with_fallback_queries_manager_on_cache_miss():
    """Cache miss → manager.get_all_boards called for both concept and industry."""
    manager = MagicMock()
    # First call (concept) returns the target board; industry never reached.
    manager.get_all_boards.return_value = (
        [{"code": "BK0996", "name": "人形机器人", "type": "concept"}],
        "EastMoneyFetcher",
    )
    name = board_mod.get_board_name_with_fallback("BK0996", "eastmoney", manager=manager)
    assert name == "人形机器人"
    assert manager.get_all_boards.call_count == 1
    # The single call should have been for concept (the first match).
    call_kwargs = manager.get_all_boards.call_args.kwargs
    assert call_kwargs["source"] == "eastmoney"
    assert call_kwargs["board_type"] == "concept"


def test_get_board_name_with_fallback_swallows_data_fetch_error():
    """DataFetchError from manager → return None (non-fatal)."""
    manager = MagicMock()
    manager.get_all_boards.side_effect = DataFetchError("EM upstream down")
    name = board_mod.get_board_name_with_fallback("BK0996", "eastmoney", manager=manager)
    assert name is None


def test_get_board_name_with_fallback_swallows_value_error():
    """ValueError from manager._with_source rejection → return None."""
    manager = MagicMock()
    manager.get_all_boards.side_effect = ValueError("Unknown source 'foo'")
    name = board_mod.get_board_name_with_fallback("BK0996", "eastmoney", manager=manager)
    assert name is None


def test_get_board_name_with_fallback_swallows_attribute_error():
    """AttributeError when fetcher lacks get_all_boards (e.g., ThsFetcher) → None."""
    manager = MagicMock()
    manager.get_all_boards.side_effect = AttributeError(
        "'ThsFetcher' object has no attribute 'get_all_boards'"
    )
    name = board_mod.get_board_name_with_fallback("BK0996", "ths", manager=manager)
    assert name is None


def test_get_board_name_with_fallback_returns_none_when_no_match_in_boards():
    """Cache miss + fetcher returns boards but none match the code → None."""
    manager = MagicMock()
    manager.get_all_boards.return_value = (
        [{"code": "BK_OTHER", "name": "其他概念"}],
        "EastMoneyFetcher",
    )
    name = board_mod.get_board_name_with_fallback("BK0996", "eastmoney", manager=manager)
    assert name is None


def test_get_board_name_matches_ths_concept_by_platecode():
    """THS concept board: input is platecode (885xxx) but stock_board stores code=cid.

    Regression for the board.name==code bug: get_board_name must match on
    platecode too (mirrors _read_membership_entries' OR-join fix, 2026-07-09).
    """
    board_mod.update_cached_boards(
        "concept",
        "ths",
        [{"code": "301546", "name": "央企国企改革", "platecode": "885595"}],
    )
    # Client addresses the board by platecode (885595), not cid.
    assert board_mod.get_board_name("885595", "ths") == "央企国企改革"
    # cid still works (industry boards pass code==platecode).
    assert board_mod.get_board_name("301546", "ths") == "央企国企改革"


def test_get_board_name_platecode_or_no_false_match_for_eastmoney():
    """eastmoney rows have platecode=NULL → OR's second arm is UNKNOWN, no false hit."""
    board_mod.update_cached_boards(
        "concept",
        "eastmoney",
        [{"code": "BK0996", "name": "人形机器人"}],  # platecode defaults to NULL
    )
    assert board_mod.get_board_name("BK0996", "eastmoney") == "人形机器人"
    assert board_mod.get_board_name("885595", "eastmoney") is None


def test_get_board_name_with_fallback_matches_platecode_in_slow_path():
    """Slow path (manager.get_all_boards) must also compare platecode."""
    from unittest.mock import MagicMock

    manager = MagicMock()
    manager.get_all_boards.return_value = (
        [{"code": "301546", "name": "央企国企改革", "platecode": "885595"}],
        "ThsFetcher",
    )
    name = board_mod.get_board_name_with_fallback("885595", "ths", manager=manager)
    assert name == "央企国企改革"
