"""Integration tests for board API endpoints.

After the board-API refactor, the 4 board endpoints all share:
- a required ``source`` query parameter
- routing through the new ``DataFetcherManager.{get_all_boards, get_board_stocks,
  get_stock_boards, get_board_history}`` Manager methods
- the ``/boards`` list endpoint additionally routes through the persistence
  layer (``stock_board_cache.get_board_list``) so cache hits return
  ``source="persistence"`` per CLAUDE.md's source-tracking matrix.
"""
from unittest.mock import patch

import pytest

from stock_data.api.routes import reset_manager


@pytest.fixture(autouse=True)
def reset_before_test():
    """Reset manager state before each test."""
    reset_manager()
    yield


# Module-level patch target for the /boards list endpoint. The route layer
# delegates to the persistence module, so list_boards tests mock at that
# boundary. /boards/{code}/stocks and /stocks/{code}/boards still go
# directly through the manager and continue to mock there.
_PERSISTENCE_LIST_PATCH = "stock_data.data_provider.persistence.board.get_board_list"


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
        _PERSISTENCE_LIST_PATCH,
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
        _PERSISTENCE_LIST_PATCH,
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
        _PERSISTENCE_LIST_PATCH,
        return_value=(fake, "EastMoneyFetcher"),
    ):
        r = client.get(
            "/api/v1/boards?type=concept&source=eastmoney&include_quote=true"
            "&sort_by=change_pct&limit=2"
        )
    assert r.status_code == 200
    assert len(r.json()["data"]) == 2


# ===== Regression: cache hit returns origin="persistence" =====
#
# Reproduces the user-reported bug: calling GET /api/v1/boards twice with
# the same params used to return origin="ZzshareFetcher" both times because
# the route bypassed the persistence layer. After wiring through the
# persistence layer, the second call (cache hit) must return
# origin="persistence" while the first call returns the fetcher name.


def test_list_boards_cache_hit_returns_persistence(client):
    """Second call with same (type, source) → origin='persistence'."""
    fake_boards = [
        {"code": "BK0001", "name": "测试", "type": "concept",
         "subtype": "同花顺概念", "source": "zzshare"},
    ]
    # First call: persistence returns the fetcher-sourced result
    with patch(
        _PERSISTENCE_LIST_PATCH,
        return_value=(fake_boards, "ZzshareFetcher"),
    ) as mock_get:
        r1 = client.get("/api/v1/boards?type=concept&source=zzshare")
        assert r1.status_code == 200
        assert r1.json()["source"] == "ZzshareFetcher"

        # Second call (cache hit): persistence returns the cached result
        # with origin="persistence" per CLAUDE.md source-tracking matrix.
        mock_get.return_value = (fake_boards, "persistence")
        r2 = client.get("/api/v1/boards?type=concept&source=zzshare")
        assert r2.status_code == 200
        assert r2.json()["source"] == "persistence"


def test_list_boards_refresh_forces_fetcher_call(client):
    """refresh=true → persistence is called with refresh=True (forces upstream)."""
    fake = [{"code": "BK0001", "name": "测试"}]
    with patch(_PERSISTENCE_LIST_PATCH, return_value=(fake, "ZzshareFetcher")) as mock_get:
        r = client.get("/api/v1/boards?type=concept&source=zzshare&refresh=true")
    assert r.status_code == 200
    mock_get.assert_called_once()
    _, kwargs = mock_get.call_args
    assert kwargs.get("refresh") is True
    assert kwargs.get("source") == "zzshare"
    assert kwargs.get("subtype") is None


def test_list_boards_include_quote_forces_fetcher_call(client):
    """include_quote=true → persistence is called with include_quote=True."""
    fake = [{"code": "BK0001", "name": "测试"}]
    with patch(_PERSISTENCE_LIST_PATCH, return_value=(fake, "ZzshareFetcher")) as mock_get:
        r = client.get("/api/v1/boards?type=concept&source=zzshare&include_quote=true")
    assert r.status_code == 200
    _, kwargs = mock_get.call_args
    assert kwargs.get("include_quote") is True


def test_list_boards_subtype_passed_to_persistence(client):
    """subtype param is forwarded to persistence layer (validation + filter)."""
    fake = [{"code": "BK0001", "name": "测试"}]
    with patch(_PERSISTENCE_LIST_PATCH, return_value=(fake, "ZzshareFetcher")) as mock_get:
        r = client.get(
            "/api/v1/boards?type=concept&source=zzshare&subtype=同花顺概念"
        )
    assert r.status_code == 200
    _, kwargs = mock_get.call_args
    assert kwargs.get("subtype") == "同花顺概念"
    assert kwargs.get("source") == "zzshare"
    assert kwargs.get("board_type") == "concept"


def test_list_boards_persistence_validation_error_propagates(client):
    """ValueError from persistence (e.g. unknown source) → 400, not 500."""
    with patch(
        _PERSISTENCE_LIST_PATCH,
        side_effect=ValueError("No fetcher with name 'zzshare' is registered"),
    ):
        r = client.get("/api/v1/boards?type=concept&source=zzshare")
    assert r.status_code == 400
    body = r.json()
    # FastAPI wraps HTTPException detail under "detail"
    assert "No fetcher" in str(body)


# ===== get_board_stocks =====


def test_get_board_stocks_source_required(client):
    r = client.get("/api/v1/boards/BK0001/stocks")
    assert r.status_code == 422


def test_get_board_stocks_returns_404_on_empty(client):
    """Empty stocks → 404."""
    with patch(
        "stock_data.data_provider.persistence.board.get_board_stocks",
        return_value=([], "EastMoneyFetcher"),
    ):
        r = client.get("/api/v1/boards/BK0001/stocks?source=eastmoney")
    assert r.status_code == 404


# ===== Regression: /boards/{code}/stocks cache hit returns "persistence" =====


def test_get_board_stocks_cache_hit_returns_persistence(client):
    """Second call with same (board_code, source) → origin='persistence'."""
    fake = [{"stock_code": "600519", "stock_name": "贵州茅台"}]
    with (
        patch(
            "stock_data.data_provider.persistence.board.get_board_stocks",
        ) as mock_get,
        # Skip the fetcher-fallback name lookup (real network call)
        patch(
            "stock_data.data_provider.persistence.board.get_board_name",
            return_value="互联网服务",
        ),
    ):
        # First call: fetcher-sourced
        mock_get.return_value = (fake, "EastMoneyFetcher")
        r1 = client.get("/api/v1/boards/BK0001/stocks?source=eastmoney")
        assert r1.status_code == 200
        assert r1.json()["data_source"] == "EastMoneyFetcher"

        # Second call: cache hit
        mock_get.return_value = (fake, "persistence")
        r2 = client.get("/api/v1/boards/BK0001/stocks?source=eastmoney")
        assert r2.status_code == 200
        assert r2.json()["data_source"] == "persistence"


def test_get_board_stocks_refresh_forces_persistence_refresh(client):
    """refresh=true is forwarded to persistence layer (no longer silently dropped)."""
    fake = [{"stock_code": "600519", "stock_name": "贵州茅台"}]
    with (
        patch(
            "stock_data.data_provider.persistence.board.get_board_stocks",
            return_value=(fake, "EastMoneyFetcher"),
        ) as mock_get,
        # Fast-path: skip the fetcher-fallback board-name lookup (would
        # otherwise trigger a real network call to EastMoney).
        patch(
            "stock_data.data_provider.persistence.board.get_board_name",
            return_value="互联网服务",
        ),
    ):
        r = client.get(
            "/api/v1/boards/BK0001/stocks?source=eastmoney&refresh=true"
        )
    assert r.status_code == 200
    args, kwargs = mock_get.call_args
    assert kwargs.get("refresh") is True
    assert kwargs.get("source") == "eastmoney"
    # board_code is positional (1st arg) in the persistence signature
    assert args[0] == "BK0001"


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


# ===== get_board_history (zzshare) =====


def test_get_board_history_source_required(client):
    """GET /boards/{code}/history without source → 422 (Pydantic Literal validation)."""
    r = client.get("/api/v1/boards/883957/history")
    assert r.status_code == 422


def test_get_board_history_rejects_non_zzshare_source(client):
    """source must be 'zzshare' (Literal validated by FastAPI)."""
    r = client.get("/api/v1/boards/883957/history?source=eastmoney")
    assert r.status_code == 422


def test_get_board_history_rejects_non_daily_frequency(client):
    """frequency must be 'd' (Literal validated by FastAPI)."""
    r = client.get("/api/v1/boards/883957/history?source=zzshare&frequency=w")
    assert r.status_code == 422


def test_get_board_history_zzshare_returns_kline(client):
    """Happy path: zzshare returns rows → 200 with BoardKlineResponse."""
    fake_rows = [
        {
            "date": "2026-05-20", "open": 1.0, "high": 1.1, "low": 0.9,
            "close": 1.05, "volume": 100, "amount": 105.0, "pct_chg": 5.0,
        },
    ]
    with patch(
        "stock_data.data_provider.manager.DataFetcherManager.get_board_history",
        return_value=(fake_rows, "ZzshareFetcher"),
    ):
        r = client.get("/api/v1/boards/883957/history?source=zzshare&days=7")
    assert r.status_code == 200
    body = r.json()
    assert body["board_code"] == "883957"
    assert body["period"] == "daily"
    assert body["source"] == "ZzshareFetcher"
    assert len(body["data"]) == 1
    assert body["data"][0]["date"] == "2026-05-20"
    assert body["data"][0]["close"] == 1.05
