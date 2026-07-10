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

    stocks, origin, effective_source, reason = board_mod.get_board_stocks(
        board_code="BK1001",
        manager=mock_manager,
    )
    assert origin == "persistence"
    assert effective_source == "ths"   # cache hit → default (historical fetcher label)
    assert reason is None             # cache hit has no annotation
    assert len(stocks) == 2
    assert {s["stock_code"] for s in stocks} == {"600519", "000858"}
    mock_manager.get_board_stocks.assert_not_called()


def test_get_board_stocks_lazy_fill_when_membership_empty(fresh_db):
    """Cold path: membership empty → fetcher called → upsert → return.

    Post-strict-routing (2026-07-10): ``get_board_stocks`` honors the
    caller's ``source=`` strictly. There is no more include_quote-driven
    zzshare↔THS auto-preference — callers that want zzshare can pass
    ``source='zzshare'`` explicitly. This test exercises the THS path.
    """
    # Seed stock_board so board_name/board_type resolve on lazy-fill
    # and so _resolve_ths_cid_from_platecode(885642) returns a cid we
    # can route against.
    board_mod.update_cached_boards(
        board_type="concept",
        source="ths",
        boards=[
            {
                "code": "301558",       # upstream cid used in mock return
                "name": "白酒",
                "subtype": "concept",
                "platecode": "885642",
            },
        ],
    )

    # Mock manager returns 3 stocks when THS path is invoked
    mock_manager = MagicMock()
    mock_manager.get_board_stocks.return_value = (
        [
            {"stock_code": "600519", "stock_name": "贵州茅台"},
            {"stock_code": "000858", "stock_name": "五粮液"},
            {"stock_code": "600809", "stock_name": "山西汾酒"},
        ],
        "ths",
    )

    stocks, origin, effective_source, reason = board_mod.get_board_stocks(
        board_code="885642",     # platecode
        source="ths",
        manager=mock_manager,
    )
    # Post-2026-07-10: include_quote=False + source=ths prefers ZZSHARE
    # primary; if the ZZSHARE leg returns rows (mock always returns the
    # 3-stock payload), the helper takes the ZZSHARE primary and reports
    # effective_source='zzshare'. The mock always returns the same rows
    # regardless of source, so the ZZSHARE leg grabs them.
    assert origin == "ths"
    assert effective_source == "zzshare"  # ZZSHARE primary served
    assert reason is None                  # success path has no annotation
    assert len(stocks) == 3
    assert mock_manager.get_board_stocks.call_count == 1
    # Verify membership was populated (cache is keyed on the platecode
    # that the route layer passed in, with source='ths').
    rows = board_mod.read_membership(board_code="885642", source="ths")
    assert len(rows) == 3


def test_board_stocks_include_quote_fills_board_block(client):
    """include_quote=true → board block populated from manager.get_board_realtime."""
    from unittest.mock import patch

    from stock_data.data_provider import manager as mgr_mod
    from stock_data.data_provider.persistence import board as board_mod

    quote = {
        "board_code": "885595",
        "board_name": "央企国企改革",
        "price": 2934.39,
        "change_pct": 0.37,
        "change_amount": 10.92,
        "volume": 15343,
        "amount": 2642.50,
        "net_inflow": 34.79,
        "up_count": 175,
        "down_count": 207,
    }
    with (
        patch.object(
            board_mod,
            "get_board_stocks",
            return_value=([{"stock_code": "600519", "stock_name": "贵州茅台"}], "ths", "ths", None),
        ),
        patch.object(board_mod, "get_board_name_with_fallback", return_value="央企国企改革"),
        # C2: route now requires board_type from the cache to dispatch the
        # realtime call. Mock the metadata lookup.
        patch.object(
            board_mod,
            "get_board_metadata",
            return_value={"name": "央企国企改革", "type": "concept", "subtype": "同花顺概念"},
        ),
        patch.object(mgr_mod.DataFetcherManager, "get_board_realtime", return_value=(quote, "ths")),
    ):
        r = client.get("/api/v1/boards/885595/stocks?source=ths&include_quote=true")
    assert r.status_code == 200
    body = r.json()
    board = body["board"]
    assert board["name"] == "央企国企改革"
    assert board["price"] == 2934.39
    assert board["up_count"] == 175
    assert board["net_inflow"] == 34.79
    # A1: explicit quote_source / quote_error signaling.
    assert body["quote_source"] == "ths"
    assert body["quote_error"] is None


def test_board_stocks_include_quote_false_no_realtime_call(client):
    """include_quote=false → get_board_realtime NOT called; board is code+name only."""
    from unittest.mock import patch

    from stock_data.data_provider import manager as mgr_mod
    from stock_data.data_provider.persistence import board as board_mod

    with (
        patch.object(
            board_mod,
            "get_board_stocks",
            return_value=([{"stock_code": "600519", "stock_name": "贵州茅台"}], "ths", "ths", None),
        ),
        patch.object(board_mod, "get_board_name_with_fallback", return_value="央企国企改革"),
        patch.object(mgr_mod.DataFetcherManager, "get_board_realtime") as mock_rt,
    ):
        r = client.get("/api/v1/boards/885595/stocks?source=ths&include_quote=false")
    assert r.status_code == 200
    assert r.json()["board"]["price"] is None
    mock_rt.assert_not_called()


def test_board_stocks_include_quote_best_effort_on_failure(client):
    """get_board_realtime failure → board falls back to code+name, no 500.

    Post-2026-07-10 (A1): the failure is now visible in the response
    via ``quote_error``. Clients can distinguish upstream failure from
    "no quote requested" by reading this field.
    """
    from unittest.mock import patch

    from stock_data.data_provider import manager as mgr_mod
    from stock_data.data_provider.base import DataFetchError
    from stock_data.data_provider.persistence import board as board_mod

    with (
        patch.object(
            board_mod,
            "get_board_stocks",
            return_value=([{"stock_code": "600519", "stock_name": "贵州茅台"}], "ths", "ths", None),
        ),
        patch.object(board_mod, "get_board_name_with_fallback", return_value="央企国企改革"),
        # C2: route requires board_type from cache before calling the fetcher.
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
        r = client.get("/api/v1/boards/885595/stocks?source=ths&include_quote=true")
    assert r.status_code == 200
    body = r.json()
    board = body["board"]
    assert board["name"] == "央企国企改革"
    assert board["price"] is None
    # A1: explicit error signaling. quote_source is None, quote_error
    # describes the failure.
    assert body["quote_source"] is None
    assert body["quote_error"] is not None
    assert "upstream_failed" in body["quote_error"]


def test_board_stocks_board_block_has_type_from_cache(client):
    """board.type is populated from the stock_board cache (not null).

    Regression test: previously the route built BoardInfo(code, name)
    without setting ``type``, serializing as ``"type": null``. The fix
    plumbs ``board_type`` from the SQLite ``stock_board`` cache into the
    response so callers can split the result by type without re-querying.
    """
    from unittest.mock import patch

    from stock_data.data_provider import manager as mgr_mod
    from stock_data.data_provider.base import DataFetchError
    from stock_data.data_provider.persistence import board as board_mod

    with (
        patch.object(
            board_mod,
            "get_board_stocks",
            return_value=([{"stock_code": "600519", "stock_name": "贵州茅台"}], "ths", "ths", None),
        ),
        patch.object(board_mod, "get_board_name_with_fallback", return_value="央企国企改革"),
        # Cache hits: route should plug board_type='concept' into BoardInfo.
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
        r = client.get("/api/v1/boards/885595/stocks?source=ths&include_quote=true")
    assert r.status_code == 200
    board = r.json()["board"]
    assert board["type"] == "concept"
    assert board["code"] == "885595"
    assert board["name"] == "央企国企改革"


def test_board_stocks_board_block_type_none_on_cache_miss(client):
    """board.type is null when the cache has no row for this board code.

    Post-2026-07-10 (A1): cache miss also surfaces a ``quote_error``
    because the route can't dispatch the realtime call without
    board_type. The error message names the missing piece.
    """
    from unittest.mock import patch

    from stock_data.data_provider import manager as mgr_mod
    from stock_data.data_provider.base import DataFetchError
    from stock_data.data_provider.persistence import board as board_mod

    with (
        patch.object(
            board_mod,
            "get_board_stocks",
            return_value=([{"stock_code": "600519", "stock_name": "贵州茅台"}], "ths", "ths", None),
        ),
        patch.object(board_mod, "get_board_name_with_fallback", return_value="x"),
        # Cache miss: helper returns None.
        patch.object(board_mod, "get_board_metadata", return_value=None),
        patch.object(
            mgr_mod.DataFetcherManager,
            "get_board_realtime",
            side_effect=DataFetchError("upstream down"),
        ) as mgr_call,
    ):
        r = client.get("/api/v1/boards/885595/stocks?source=ths&include_quote=true")
    assert r.status_code == 200
    body = r.json()
    assert body["board"]["type"] is None
    # A1: cache miss for board_type → quote_error names the gap.
    assert body["quote_source"] is None
    assert body["quote_error"] == "board_type_unresolved"
    # Fetcher must NOT be called when board_type is unresolvable.
    mgr_call.assert_not_called()


def test_board_stocks_unsupported_source_returns_quote_error(client):
    """?source=eastmoney&include_quote=true → quote_error='unsupported'.

    EastMoneyFetcher declares STOCK_BOARD but does not implement
    ``get_board_realtime``. The route pre-checks with hasattr via
    manager.get_fetcher (B2) and returns a clear ``quote_error`` so
    the client knows the chosen source doesn't support quote.
    """
    from unittest.mock import patch

    from stock_data.data_provider import manager as mgr_mod
    from stock_data.data_provider.persistence import board as board_mod

    with (
        patch.object(
            board_mod,
            "get_board_stocks",
            return_value=([{"stock_code": "600519", "stock_name": "x"}], "eastmoney", "eastmoney", None),
        ),
        patch.object(board_mod, "get_board_name_with_fallback", return_value="x"),
        patch.object(
            mgr_mod.DataFetcherManager, "get_board_realtime"
        ) as mgr_call,
    ):
        r = client.get(
            "/api/v1/boards/885595/stocks?source=eastmoney&include_quote=true"
        )
    assert r.status_code == 200
    body = r.json()
    # Stocks still served by eastmoney — that part of the contract is
    # unchanged. The realtime block is the only thing that fails.
    assert body["data_source"] == "eastmoney"
    assert body["board"]["price"] is None
    # A1: explicit error signaling.
    assert body["quote_source"] is None
    assert body["quote_error"] == "unsupported"
    # Fetcher must NOT be called when source doesn't implement the method.
    mgr_call.assert_not_called()


def test_board_stocks_include_quote_false_does_not_lookup_metadata(client):
    """include_quote=false → get_board_metadata is NOT called (D3 efficiency).

    Pre-A1 the route looked up board metadata on every call regardless
    of include_quote. Post-A1 the lookup is gated on include_quote=true
    only, so the common (no-quote) path skips the extra DB query.
    """
    from unittest.mock import patch

    from stock_data.data_provider import manager as mgr_mod
    from stock_data.data_provider.persistence import board as board_mod

    with (
        patch.object(
            board_mod,
            "get_board_stocks",
            return_value=([{"stock_code": "600519", "stock_name": "贵州茅台"}], "ths", "ths", None),
        ),
        patch.object(board_mod, "get_board_name_with_fallback", return_value="x"),
        patch.object(board_mod, "get_board_metadata") as meta_call,
        patch.object(mgr_mod.DataFetcherManager, "get_board_realtime") as mgr_call,
    ):
        r = client.get("/api/v1/boards/885595/stocks?source=ths&include_quote=false")
    assert r.status_code == 200
    body = r.json()
    # No realtime requested → no quote fields populated.
    assert body["quote_source"] is None
    assert body["quote_error"] is None
    # Crucially: get_board_metadata must NOT be called on the no-quote
    # path. Pre-A1 this was an unconditional DB hit.
    meta_call.assert_not_called()
    mgr_call.assert_not_called()
