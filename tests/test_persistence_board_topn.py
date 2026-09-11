"""Persistence-layer tests for top_n / sort / cid routing (Task 6 of plan).

Post-2026-09-11 the ``include_quote=True`` tier is single-source THS AJAX:
there is no zzshare suffix leg and no 50-row heuristic (spec §2 D2). The
tier is cid-addressed, so ``resolve_ths_cid`` is the gate — an unresolvable
cid short-circuits with ``reason="cid_unresolved"`` and no manager call.
"""

from unittest.mock import MagicMock, patch

import pytest

from stock_data.api.routes import reset_manager
from stock_data.data_provider.persistence import board as stock_board_cache


@pytest.fixture(autouse=True)
def reset_mgr():
    reset_manager()
    # get_board_stocks' include_quote=True path calls
    # get_cached_market_quotes for quote-field enrichment. Tests in this
    # file are about top_n / cid routing, not cross-endpoint enrichment,
    # so the market-quote helper is stubbed to return None (no
    # enrichment) by default.
    with patch.object(stock_board_cache, "get_cached_market_quotes", return_value=None):
        yield


def _ths_row(code: str, name: str = "x") -> dict:
    return {
        "stock_code": code,
        "stock_name": name,
        "exchange": "sh",
        "price": 1.0,
        "change_pct": 1.0,
        "change_amount": 0.01,
        "volume": None,
        "amount": 1e8,
        "turnover_rate": 1.0,
    }


def test_persistence_get_board_stocks_returns_6_tuple():
    """per spec section 3.4.1, 返回 (list, str, str, str|None, bool, int)."""
    manager = MagicMock()
    fake_ths_response = [_ths_row("000034")]

    with (
        patch.object(stock_board_cache, "_read_board_stocks_from_db", return_value=[]),
        patch.object(stock_board_cache, "resolve_ths_cid", return_value="300188"),
        patch.object(manager, "get_board_stocks", return_value=(fake_ths_response, "ths")),
        patch.object(stock_board_cache, "update_cached_board_stocks", return_value=1),
    ):
        result = stock_board_cache.get_board_stocks(
            board_code="885756",
            source="ths",
            refresh=True,
            include_quote=True,
            manager=manager,
            sort_by="change_pct",
            sort_order="desc",
            top_n=10,
        )
    # 6-tuple
    assert len(result) == 6
    stocks, origin, es, reason, quote_truncated, total_in_board = result
    assert origin == "ths"
    assert es == "ths"
    assert reason is None
    assert len(stocks) == 1
    # 1 row < top_n=10 → we did not touch the upstream cap.
    assert quote_truncated is False
    assert total_in_board == 1


def test_ths_row_at_top_n_is_reported_truncated():
    """A row count that reaches ``top_n`` is reported as truncated.

    ``quote_truncated`` means "possibly cut off at the AJAX cap" — the
    honest answer even when the board genuinely has exactly ``top_n``
    members. The old zzshare-suffix heuristic that used to set this flag
    is gone; it is now a straight ``len(stocks) >= top_n``.
    """
    manager = MagicMock()
    ths_50 = [_ths_row(f"0000{i:02d}", f"t{i}") for i in range(50)]

    with (
        patch.object(stock_board_cache, "_read_board_stocks_from_db", return_value=[]),
        patch.object(stock_board_cache, "resolve_ths_cid", return_value="300188"),
        patch.object(manager, "get_board_stocks", return_value=(ths_50, "ths")),
        patch.object(stock_board_cache, "update_cached_board_stocks", return_value=50),
    ):
        result = stock_board_cache.get_board_stocks(
            board_code="885756",
            source="ths",
            refresh=True,
            include_quote=True,
            manager=manager,
            sort_by="change_pct",
            sort_order="desc",
            top_n=50,
        )
    stocks, _origin, _es, _reason, quote_truncated, total = result
    assert len(stocks) == 50
    assert quote_truncated is True
    assert total == 50


def test_sort_and_top_n_forwarded_to_manager_with_resolved_cid():
    """The AJAX tier is cid-addressed: manager sees the cid, not the
    public board_code, and every sort/top_n knob is forwarded verbatim."""
    manager = MagicMock()
    manager.get_board_stocks.return_value = ([_ths_row("000034")], "ths")

    with (
        patch.object(stock_board_cache, "_read_board_stocks_from_db", return_value=[]),
        patch.object(stock_board_cache, "resolve_ths_cid", return_value="300188"),
        patch.object(stock_board_cache, "update_cached_board_stocks", return_value=1),
    ):
        stock_board_cache.get_board_stocks(
            board_code="885756",
            source="ths",
            refresh=True,
            include_quote=True,
            manager=manager,
            sort_by="turnover_rate",
            sort_order="asc",
            top_n=10,
        )

    manager.get_board_stocks.assert_called_once()
    kwargs = manager.get_board_stocks.call_args.kwargs
    assert kwargs["board_code"] == "300188"  # cid, not 885756
    assert kwargs["source"] == "ths"
    assert kwargs["include_quote"] is True
    assert kwargs["sort_by"] == "turnover_rate"
    assert kwargs["sort_order"] == "asc"
    assert kwargs["top_n"] == 10


def test_cid_unresolved_short_circuits_without_manager_call():
    """An unresolvable cid means "we cannot address this board on the AJAX
    tier" — reason="cid_unresolved" (route → 422), and no upstream call."""
    manager = MagicMock()

    with (
        patch.object(stock_board_cache, "_read_board_stocks_from_db", return_value=[]),
        patch.object(stock_board_cache, "resolve_ths_cid", return_value=None),
    ):
        result = stock_board_cache.get_board_stocks(
            board_code="801001",
            source="ths",
            refresh=True,
            include_quote=True,
            manager=manager,
            top_n=10,
        )

    stocks, origin, es, reason, quote_truncated, total = result
    assert stocks == []
    assert origin == "ths"
    assert es == "ths"
    assert reason == "cid_unresolved"
    assert quote_truncated is False
    assert total == 0
    manager.get_board_stocks.assert_not_called()
