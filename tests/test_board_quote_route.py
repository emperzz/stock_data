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

    Post-2026-07-10: the route also requires a stock_board cache hit to
    resolve board_type. The cache lookup is mocked here to keep the test
    independent of the DB.
    """
    from stock_data.data_provider import manager as mgr_mod
    from stock_data.data_provider.persistence import board as board_mod

    with (
        patch.object(
            board_mod,
            "get_board_metadata",
            return_value={"name": "央企国企改革", "type": "concept", "subtype": "同花顺概念"},
        ),
        patch.object(
            mgr_mod.DataFetcherManager, "get_board_realtime", return_value=(_QUOTE, "ths")
        ) as mgr_call,
    ):
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
    # Route internally routes to ths unconditionally, and forwards
    # board_type from the cache (C2: persistence is the source of truth).
    args, _kwargs = mgr_call.call_args
    assert args[0] == "885595"
    assert _kwargs.get("source") == "ths"
    assert _kwargs.get("board_type") == "concept"


def test_board_quote_extra_source_query_ignored(client):
    """/boards/{code}/quote?source=anything is accepted; source is not a route param."""
    from stock_data.data_provider import manager as mgr_mod
    from stock_data.data_provider.persistence import board as board_mod

    with (
        patch.object(
            board_mod,
            "get_board_metadata",
            return_value={"name": "央企国企改革", "type": "concept", "subtype": "同花顺概念"},
        ),
        patch.object(
            mgr_mod.DataFetcherManager, "get_board_realtime", return_value=(_QUOTE, "ths")
        ),
    ):
        # Pass a non-existing source query — should NOT 422 since the route
        # no longer declares a source param at all.
        r = client.get("/api/v1/boards/885595/quote?source=eastmoney")
    assert r.status_code == 200


def test_board_quote_upstream_error_returns_503(client):
    from stock_data.data_provider import manager as mgr_mod
    from stock_data.data_provider.base import DataFetchError
    from stock_data.data_provider.persistence import board as board_mod

    with (
        patch.object(
            board_mod,
            "get_board_metadata",
            return_value={"name": "央企国企改革", "type": "concept", "subtype": "同花顺概念"},
        ),
        patch.object(
            mgr_mod.DataFetcherManager,
            "get_board_realtime",
            side_effect=DataFetchError("upstream down"),
        ),
    ):
        r = client.get("/api/v1/boards/885595/quote")
    assert r.status_code == 503


def test_board_quote_422_when_cache_misses(client):
    """Cache miss for board_type → 422 with clear error.

    Post-2026-07-10 (C2): the route refuses to call the fetcher when the
    stock_board cache has no row for the board. Failure is loud and
    actionable — the client can refresh the board list and retry.
    """
    from stock_data.data_provider import manager as mgr_mod
    from stock_data.data_provider.persistence import board as board_mod

    with (
        patch.object(board_mod, "get_board_metadata", return_value=None),
        patch.object(mgr_mod.DataFetcherManager, "get_board_realtime") as mgr_call,
    ):
        r = client.get("/api/v1/boards/885595/quote")
    assert r.status_code == 422
    body = r.json()
    assert body["detail"]["error"] == "board_type_unresolved"
    assert "885595" in body["detail"]["message"]
    # Fetcher MUST NOT be called when board_type is unresolvable.
    mgr_call.assert_not_called()
