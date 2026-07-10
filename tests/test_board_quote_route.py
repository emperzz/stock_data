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


def test_board_quote_no_source_param_works(client):
    """/boards/{code}/quote has only one impl (ths); no source param needed → 200.

    Regression test for the route accepting an implicit source=ths (the
    source literal was already locked to 'ths', so making it a required
    Query only added a 422-class failure mode for callers who forgot the
    trailing query string). The route must work without ?source= and
    internally route to ths.
    """
    from stock_data.data_provider import manager as mgr_mod

    with patch.object(
        mgr_mod.DataFetcherManager, "get_board_realtime", return_value=(_QUOTE, "ths")
    ) as mgr_call:
        r = client.get("/api/v1/boards/885595/quote")
    assert r.status_code == 200
    body = r.json()
    assert body["board_code"] == "885595"
    assert body["board_name"] == "央企国企改革"
    assert body["open"] == 2921.12
    assert body["up_count"] == 175
    assert body["net_inflow"] == 34.79
    assert body["rank"] == "229/389"
    assert body["source"] == "ths"
    # Route internally routes to ths unconditionally
    args, _kwargs = mgr_call.call_args
    assert args[0] == "885595"
    assert _kwargs.get("source") == "ths"


def test_board_quote_extra_source_query_ignored(client):
    """/boards/{code}/quote?source=anything is accepted; source is not a route param."""
    from stock_data.data_provider import manager as mgr_mod

    with patch.object(
        mgr_mod.DataFetcherManager, "get_board_realtime", return_value=(_QUOTE, "ths")
    ):
        # Pass a non-existing source query — should NOT 422 since the route
        # no longer declares a source param at all.
        r = client.get("/api/v1/boards/885595/quote?source=eastmoney")
    assert r.status_code == 200


def test_board_quote_upstream_error_returns_503(client):
    from stock_data.data_provider import manager as mgr_mod
    from stock_data.data_provider.base import DataFetchError

    with patch.object(
        mgr_mod.DataFetcherManager,
        "get_board_realtime",
        side_effect=DataFetchError("upstream down"),
    ):
        r = client.get("/api/v1/boards/885595/quote")
    assert r.status_code == 503
