"""Persistence-layer tests for top_n + sort + 50-stock heuristic (Task 6 of plan)."""
from unittest.mock import MagicMock, patch

import pytest

from stock_data.api.routes import reset_manager
from stock_data.data_provider.persistence import board as stock_board_cache


@pytest.fixture(autouse=True)
def reset_mgr():
    reset_manager()
    yield


def test_persistence_get_board_stocks_returns_6_tuple():
    """per spec section 3.4.1, 返回 (list, str, str, str|None, bool, int)."""
    manager = MagicMock()
    fake_ths_response = [
        {
            "stock_code": "000034",
            "stock_name": "x",
            "exchange": "sh",
            "price": 1.0,
            "change_pct": 1.0,
            "change_amount": 0.01,
            "volume": None,
            "amount": 1e8,
            "turnover_rate": 1.0,
        },
    ]
    with (
        patch.object(stock_board_cache, "_read_board_stocks_from_db", return_value=[]),
        patch.object(
            stock_board_cache,
            "fetch_board_stocks_with_zzshare_fallback",
            return_value=(fake_ths_response, "ths", "ths", None),
        ),
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
    assert quote_truncated is False  # ths returned only 1 row, < 50
    assert len(stocks) == 1


def test_heuristic_triggers_zzshare_when_ths_returns_50():
    """当 THS 返回正好 50 只 → 调用 ZZSHARE 补全 suffix."""
    manager = MagicMock()
    ths_50 = [
        {
            "stock_code": f"0000{i:02d}",
            "stock_name": f"t{i}",
            "exchange": "sh",
            "price": i * 0.1,
            "change_pct": i,
            "change_amount": 0.01,
            "volume": None,
            "amount": 1e8,
            "turnover_rate": 1.0,
        }
        for i in range(50)
    ]
    zz_suffix = [
        {"stock_code": f"0002{i:02d}", "stock_name": f"z{i}", "exchange": "sz"}
        for i in range(10)
    ]
    with (
        patch.object(stock_board_cache, "_read_board_stocks_from_db", return_value=[]),
        patch.object(
            stock_board_cache,
            "fetch_board_stocks_with_zzshare_fallback",
            return_value=(ths_50, "ths", "ths", None),
        ),
        patch.object(manager, "get_board_stocks", return_value=(zz_suffix, "zzshare")) as mock_zz,
        patch.object(stock_board_cache, "update_cached_board_stocks", return_value=60),
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
    assert mock_zz.called
    _, _, _, _, quote_truncated, total = result
    assert quote_truncated is True
    assert total == 60


def test_heuristic_short_circuit_when_ths_below_50():
    """THS 返回 <50 → 不调 ZZSHARE."""
    manager = MagicMock()
    ths_30 = [
        {
            "stock_code": f"000{i:03d}",
            "stock_name": "x",
            "exchange": "sh",
            "price": 1.0,
            "change_pct": 1.0,
            "change_amount": 0.01,
            "volume": None,
            "amount": 1e8,
            "turnover_rate": 1.0,
        }
        for i in range(30)
    ]
    with (
        patch.object(stock_board_cache, "_read_board_stocks_from_db", return_value=[]),
        patch.object(
            stock_board_cache,
            "fetch_board_stocks_with_zzshare_fallback",
            return_value=(ths_30, "ths", "ths", None),
        ),
        patch.object(manager, "get_board_stocks") as mock_zz,
        patch.object(stock_board_cache, "update_cached_board_stocks", return_value=30),
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
    assert not mock_zz.called
    _, _, _, _, quote_truncated, total = result
    assert quote_truncated is False
