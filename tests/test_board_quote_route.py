"""Integration tests for GET /boards/{board_code}/quote."""

from unittest.mock import patch

import pytest

from stock_data.api.routes import reset_manager


@pytest.fixture(autouse=True)
def reset_before_test():
    reset_manager()
    yield


_QUOTE = {
    "board_code": "885595",
    "board_name": "央企国企改革",
    "cid": "301546",
    "price": 2934.39,
    "change_amount": 10.92,
    "change_pct": 0.37,
    "open": 2921.12,
    "prev_close": 2923.48,
    "high": 2936.89,
    "low": 2870.11,
    "volume": 15343,
    "amount": 2642.50,
    "up_count": 175,
    "down_count": 207,
    "net_inflow": 34.79,
    "rank": "229/389",
}


def test_board_quote_source_required(client):
    """source is required → 422."""
    r = client.get("/api/v1/boards/885595/quote")
    assert r.status_code == 422


def test_board_quote_rejects_non_ths_source(client):
    """Literal['ths'] rejects eastmoney/zhitu at the FastAPI layer (422)."""
    r = client.get("/api/v1/boards/885595/quote?source=eastmoney")
    assert r.status_code == 422


def test_board_quote_returns_fields(client):
    from stock_data.data_provider import manager as mgr_mod

    with patch.object(
        mgr_mod.DataFetcherManager, "get_board_realtime", return_value=(_QUOTE, "ths")
    ):
        r = client.get("/api/v1/boards/885595/quote?source=ths")
    assert r.status_code == 200
    body = r.json()
    assert body["board_code"] == "885595"
    assert body["board_name"] == "央企国企改革"
    assert body["open"] == 2921.12
    assert body["up_count"] == 175
    assert body["net_inflow"] == 34.79
    assert body["rank"] == "229/389"
    assert body["source"] == "ths"


def test_board_quote_upstream_error_returns_503(client):
    from stock_data.data_provider import manager as mgr_mod
    from stock_data.data_provider.base import DataFetchError

    with patch.object(
        mgr_mod.DataFetcherManager,
        "get_board_realtime",
        side_effect=DataFetchError("upstream down"),
    ):
        r = client.get("/api/v1/boards/885595/quote?source=ths")
    assert r.status_code == 503
