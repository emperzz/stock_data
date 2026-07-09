"""Integration test: /boards/{code}/stocks reads from membership table."""

from __future__ import annotations

from unittest.mock import MagicMock

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
    yield tmp_path / "test.db"


def test_get_board_stocks_reads_from_membership_table(fresh_db, monkeypatch):
    """get_board_stocks returns rows from stock_board_membership.

    Post-unification (2026-07-08): the cache is keyed on source='ths', so
    we seed membership with 'ths' and call get_board_stocks without a
    source kwarg (the parameter was removed). The mock manager's
    get_board_stocks raises if invoked — proving the cache-read path
    is exercised without delegating to upstream.
    """
    # Seed membership directly (cache is keyed on 'ths' post-unification)
    board_mod.upsert_membership_bulk(
        source="ths",
        stocks=[
            {"stock_code": "600519", "stock_name": "贵州茅台"},
            {"stock_code": "000858", "stock_name": "五粮液"},
        ],
        board_code="BK1001",
        board_name="白酒",
        board_type="concept",
        subtype="concept",
    )
    # Skip daily-refresh tracking so the cache read path is exercised
    # (this test specifically validates that _read_board_stocks_from_db
    # now reads from the membership table — without disabling the tracker,
    # the first call of the day always forces a refresh and bypasses cache).
    monkeypatch.setattr(
        board_mod,
        "_refresh_tracker",
        type("T", (), {"is_first_call": lambda *a: False})(),
    )
    # Mock manager so cold path would fail if triggered
    mock_manager = MagicMock()
    mock_manager.get_board_stocks.side_effect = AssertionError(
        "Cold path should NOT trigger when membership has data"
    )

    stocks, origin = board_mod.get_board_stocks(
        board_code="BK1001",
        manager=mock_manager,
    )
    assert origin == "persistence"
    assert len(stocks) == 2
    assert {s["stock_code"] for s in stocks} == {"600519", "000858"}
    mock_manager.get_board_stocks.assert_not_called()


def test_get_board_stocks_lazy_fill_when_membership_empty(fresh_db):
    """Cold path: membership empty → fetcher called → upsert → return.

    Post-unification: cache is keyed on source='ths' and the helper
    fetch_board_stocks_with_zzshare_fallback serves via ZzshareFetcher
    (origin='zzshare') or ThsFetcher (origin='ths') based on include_quote.
    With include_quote=False (default), zzshare is tried first.
    """
    # Seed stock_board so board_name/board_type resolve on lazy-fill
    board_mod.update_cached_boards(
        board_type="concept",
        source="ths",
        boards=[{"code": "BK1001", "name": "白酒", "subtype": "concept"}],
    )

    # Mock manager returns 3 stocks
    mock_manager = MagicMock()
    mock_manager.get_board_stocks.return_value = (
        [
            {"stock_code": "600519", "stock_name": "贵州茅台"},
            {"stock_code": "000858", "stock_name": "五粮液"},
            {"stock_code": "600809", "stock_name": "山西汾酒"},
        ],
        "ths",
    )

    stocks, origin = board_mod.get_board_stocks(
        board_code="BK1001",
        manager=mock_manager,
    )
    # zzshare path runs first (include_quote=False), so origin is 'zzshare'.
    assert origin == "zzshare"
    assert len(stocks) == 3
    # Verify membership was populated (cache is keyed on 'ths')
    rows = board_mod.read_membership(board_code="BK1001", source="ths")
    assert len(rows) == 3


def test_board_stocks_include_quote_fills_board_block(client):
    """include_quote=true → board block populated from manager.get_board_realtime."""
    from unittest.mock import patch
    from stock_data.data_provider import manager as mgr_mod
    from stock_data.data_provider.persistence import board as board_mod

    quote = {
        "board_code": "885595", "board_name": "央企国企改革",
        "price": 2934.39, "change_pct": 0.37, "change_amount": 10.92,
        "volume": 15343, "amount": 2642.50, "net_inflow": 34.79,
        "up_count": 175, "down_count": 207,
    }
    with patch.object(
        board_mod, "get_board_stocks",
        return_value=([{"stock_code": "600519", "stock_name": "贵州茅台"}], "ths"),
    ), patch.object(
        board_mod, "get_board_name_with_fallback", return_value="央企国企改革"
    ), patch.object(
        mgr_mod.DataFetcherManager, "get_board_realtime", return_value=(quote, "ths")
    ):
        r = client.get("/api/v1/boards/885595/stocks?source=ths&include_quote=true")
    assert r.status_code == 200
    board = r.json()["board"]
    assert board["name"] == "央企国企改革"
    assert board["price"] == 2934.39
    assert board["up_count"] == 175
    assert board["net_inflow"] == 34.79


def test_board_stocks_include_quote_false_no_realtime_call(client):
    """include_quote=false → get_board_realtime NOT called; board is code+name only."""
    from unittest.mock import patch
    from stock_data.data_provider import manager as mgr_mod
    from stock_data.data_provider.persistence import board as board_mod

    with patch.object(
        board_mod, "get_board_stocks",
        return_value=([{"stock_code": "600519", "stock_name": "贵州茅台"}], "ths"),
    ), patch.object(
        board_mod, "get_board_name_with_fallback", return_value="央企国企改革"
    ), patch.object(
        mgr_mod.DataFetcherManager, "get_board_realtime"
    ) as mock_rt:
        r = client.get("/api/v1/boards/885595/stocks?source=ths&include_quote=false")
    assert r.status_code == 200
    assert r.json()["board"]["price"] is None
    mock_rt.assert_not_called()


def test_board_stocks_include_quote_best_effort_on_failure(client):
    """get_board_realtime failure → board falls back to code+name, no 500."""
    from unittest.mock import patch
    from stock_data.data_provider import manager as mgr_mod
    from stock_data.data_provider.persistence import board as board_mod
    from stock_data.data_provider.base import DataFetchError

    with patch.object(
        board_mod, "get_board_stocks",
        return_value=([{"stock_code": "600519", "stock_name": "贵州茅台"}], "ths"),
    ), patch.object(
        board_mod, "get_board_name_with_fallback", return_value="央企国企改革"
    ), patch.object(
        mgr_mod.DataFetcherManager, "get_board_realtime",
        side_effect=DataFetchError("upstream down"),
    ):
        r = client.get("/api/v1/boards/885595/stocks?source=ths&include_quote=true")
    assert r.status_code == 200
    board = r.json()["board"]
    assert board["name"] == "央企国企改革"
    assert board["price"] is None