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
        # 2026-07-13: include_quote=true 总是调 ZZSHARE. 此 board 只有 1 只成分股
        # (单元素 dict), 模拟 ZZSHARE 返回同一只 → suffix 空 → quote_truncated=False.
        patch.object(manager, "get_board_stocks", return_value=(fake_ths_response, "zzshare")),
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
    # suffix 空 (ZZSHARE 返回同一只, dedup) → board 真小, not truncated
    assert quote_truncated is False
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
        {"stock_code": f"0002{i:02d}", "stock_name": f"z{i}", "exchange": "sz"} for i in range(10)
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


def test_zzshare_always_called_for_include_quote_true():
    """include_quote=true 总是调 ZZSHARE; quote_truncated 取决于 suffix.

    2026-07-13 重构: 移除 needs_fill_in (len(stocks) >= 50) heuristic.
    之前的实现让 top_n<50 的请求静默截断大 board, client 误以为 board
    真的只有 top_n 只成员 — 契约撒谎. 新行为: include_quote=true 总是
    调一次 ZZSHARE 拉全量清单, quote_truncated=True iff suffix 非空.
    """
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
    zz_suffix = [
        {"stock_code": f"0009{i:02d}", "stock_name": "z", "exchange": "sz"} for i in range(5)
    ]  # 5 NEW codes not in ths_30
    with (
        patch.object(stock_board_cache, "_read_board_stocks_from_db", return_value=[]),
        patch.object(
            stock_board_cache,
            "fetch_board_stocks_with_zzshare_fallback",
            return_value=(ths_30, "ths", "ths", None),
        ),
        patch.object(manager, "get_board_stocks", return_value=(zz_suffix, "zzshare")) as mock_zz,
        patch.object(stock_board_cache, "update_cached_board_stocks", return_value=35),
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
    # ZZSHARE 总是被调 (新行为, 不再 heuristic short-circuit)
    assert mock_zz.called
    stocks, _, _, _, quote_truncated, total = result
    # suffix 非空 → quote_truncated=True
    assert quote_truncated is True
    # 拼接后 = top-30 THS + 5 ZZSHARE suffix = 35
    assert len(stocks) == 35
    assert total == 35
