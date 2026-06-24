"""Integration tests for board API endpoints.

After the board-API refactor, the 4 board endpoints all share:
- a required ``source`` query parameter
- routing through the new ``DataFetcherManager.{get_all_boards, get_board_stocks,
  get_stock_boards, get_board_history}`` Manager methods
"""
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from stock_data.api.routes import reset_manager
from stock_data.server import app


@pytest.fixture(autouse=True)
def reset_before_test():
    """Reset manager state before each test."""
    reset_manager()
    yield


@pytest.fixture
def client():
    return TestClient(app)


# ===== list_boards =====


def test_list_boards_source_required(client):
    """GET /boards without source returns 422 (source is now required)."""
    r = client.get("/api/v1/boards?type=concept")
    assert r.status_code == 422


def test_list_boards_invalid_source_returns_400(client):
    """GET /boards with unknown source returns 400 or 422 (literal-validated by FastAPI)."""
    r = client.get("/api/v1/boards?type=concept&source=unknown")
    # FastAPI's Literal validation rejects unknown sources at 422; if we
    # ever widen the type to plain str, _resolve_source will raise 400.
    assert r.status_code in (400, 422)


def test_list_boards_zhitu_returns_zhitu_boards(client):
    """GET /boards?source=zhitu&type=concept returns Zhitu boards."""
    fake_boards = [
        {"code": "sw_mt", "name": "A股-申万行业-煤炭",
         "type": "industry", "subtype": "申万行业"},
    ]
    with patch(
        "stock_data.data_provider.manager.DataFetcherManager.get_all_boards",
        return_value=(fake_boards, "ZhituFetcher"),
    ):
        r = client.get("/api/v1/boards?type=concept&source=zhitu")
    assert r.status_code == 200
    body = r.json()
    assert body["source"] == "ZhituFetcher"
    assert body["data"][0]["code"] == "sw_mt"


def test_list_boards_invalid_subtype_returns_400(client):
    """Subtype not in source's valid set → 400."""
    r = client.get(
        "/api/v1/boards?type=concept&source=eastmoney&subtype=热门概念"
    )
    # EastMoney has subtype=concept, not 热门概念
    assert r.status_code == 400


def test_list_boards_eastmoney_default_subtype_ok(client):
    """source=eastmoney&type=concept&subtype=concept is valid (mirrored)."""
    fake = [{"code": "BK0001", "name": "测试"}]
    with patch(
        "stock_data.data_provider.manager.DataFetcherManager.get_all_boards",
        return_value=(fake, "EastMoneyFetcher"),
    ):
        r = client.get(
            "/api/v1/boards?type=concept&source=eastmoney&subtype=concept"
        )
    assert r.status_code == 200


def test_list_boards_sort_by_without_include_quote_returns_400(client):
    """sort_by requires include_quote=true; otherwise 400."""
    r = client.get(
        "/api/v1/boards?type=concept&source=eastmoney&sort_by=change_pct"
    )
    assert r.status_code == 400


def test_list_boards_limit_truncates_results(client):
    """limit=2 truncates the data array to 2 items."""
    fake = [{"code": f"BK{i:04d}", "name": f"测试{i}"} for i in range(5)]
    with patch(
        "stock_data.data_provider.manager.DataFetcherManager.get_all_boards",
        return_value=(fake, "EastMoneyFetcher"),
    ):
        r = client.get(
            "/api/v1/boards?type=concept&source=eastmoney&include_quote=true"
            "&sort_by=change_pct&limit=2"
        )
    assert r.status_code == 200
    assert len(r.json()["data"]) == 2


# ===== get_board_stocks =====


def test_get_board_stocks_source_required(client):
    r = client.get("/api/v1/boards/BK0001/stocks")
    assert r.status_code == 422


def test_get_board_stocks_returns_404_on_empty(client):
    """Empty stocks → 404."""
    with patch(
        "stock_data.data_provider.manager.DataFetcherManager.get_board_stocks",
        return_value=([], "EastMoneyFetcher"),
    ):
        r = client.get("/api/v1/boards/BK0001/stocks?source=eastmoney")
    assert r.status_code == 404


# ===== get_stock_boards (NEW) =====


def test_get_stock_boards_zhitu_returns_boards(client):
    fake_boards = [
        {"code": "sw_yx", "name": "A股-申万行业-银行",
         "type": "industry", "subtype": "申万行业"},
        {"code": "chgn_700532", "name": "A股-热门概念-MSCI中国",
         "type": "concept", "subtype": "热门概念"},
    ]
    with patch(
        "stock_data.data_provider.manager.DataFetcherManager.get_stock_boards",
        return_value=(fake_boards, "ZhituFetcher"),
    ):
        r = client.get("/api/v1/stocks/000001/boards?source=zhitu")
    assert r.status_code == 200
    body = r.json()
    assert body["stock_code"] == "000001"
    assert body["source"] == "ZhituFetcher"
    assert len(body["data"]) == 2


def test_get_stock_boards_eastmoney_returns_501(client):
    """source=eastmoney not yet supported → 501."""
    r = client.get("/api/v1/stocks/000001/boards?source=eastmoney")
    assert r.status_code == 501


# ===== get_board_history (NEW, stub) =====


def test_get_board_history_returns_501_for_zhitu(client):
    """Board K-line stub returns 501 Not Implemented."""
    r = client.get("/api/v1/boards/sw_mt/history?source=zhitu")
    assert r.status_code == 501


def test_get_board_history_returns_501_for_eastmoney(client):
    r = client.get("/api/v1/boards/BK0001/history?source=eastmoney")
    assert r.status_code == 501
