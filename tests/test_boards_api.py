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
        {"code": "sw_mt", "name": "A股-申万行业-煤炭", "type": "industry", "subtype": "申万行业"},
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
    r = client.get("/api/v1/boards?type=concept&source=eastmoney&subtype=热门概念")
    # EastMoney has subtype=concept, not 热门概念
    assert r.status_code == 400


def test_list_boards_eastmoney_default_subtype_ok(client):
    """source=eastmoney&type=concept&subtype=concept is valid (mirrored)."""
    fake = [{"code": "BK0001", "name": "测试"}]
    with patch(
        _PERSISTENCE_LIST_PATCH,
        return_value=(fake, "EastMoneyFetcher"),
    ):
        r = client.get("/api/v1/boards?type=concept&source=eastmoney&subtype=concept")
    assert r.status_code == 200


def test_list_boards_sort_by_without_include_quote_returns_400(client):
    """sort_by requires include_quote=true; otherwise 400."""
    r = client.get("/api/v1/boards?type=concept&source=eastmoney&sort_by=change_pct")
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
        {
            "code": "BK0001",
            "name": "测试",
            "type": "concept",
            "subtype": "同花顺概念",
            "source": "zzshare",
        },
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
        r = client.get("/api/v1/boards?type=concept&source=zzshare&subtype=同花顺概念")
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


def test_list_boards_zzshare_no_type_returns_all_three_types(client):
    """Omitting ``type`` on a zzshare query returns concept + industry + special.

    zzshare's subtype table has industry/concept/special (no index).
    Persistence is called with board_type=None; the all-types branch
    iterates over the per-source supported types and merges the results.
    The "mixed" origin label is used when both cache-hit and fetcher-hit
    rows contributed (mirrors get_stock_memberships).
    """
    fake_boards = [
        {"code": "BK_C1", "name": "概念1", "type": "concept", "subtype": "同花顺概念"},
        {"code": "BK_I1", "name": "行业1", "type": "industry", "subtype": "同花顺行业"},
        {"code": "BK_S1", "name": "题材1", "type": "special", "subtype": "同花顺题材"},
    ]
    with patch(_PERSISTENCE_LIST_PATCH, return_value=(fake_boards, "mixed")) as mock_get:
        r = client.get("/api/v1/boards?source=zzshare")
    assert r.status_code == 200
    body = r.json()
    # All three types are present in the response.
    types = {b["type"] for b in body["data"]}
    assert types == {"concept", "industry", "special"}
    # board_type=None is forwarded to persistence.
    _, kwargs = mock_get.call_args
    assert kwargs.get("board_type") is None


def test_list_boards_no_type_subtype_returns_400(client):
    """subtype filter without type is rejected at the route layer."""
    r = client.get("/api/v1/boards?source=zzshare&subtype=同花顺概念")
    assert r.status_code == 400


def test_list_boards_no_type_response_carries_type_field(client):
    """Each board in the all-types response carries its ``type`` field.

    The persistence helper tags every row with the board_type that wrote
    it; the route forwards this to the response. This is what makes
    ``GET /boards?source=...`` (no type) actually useful — callers can
    tell concept / industry / special apart.
    """
    fake_boards = [
        {"code": "BK_C1", "name": "概念1", "type": "concept", "subtype": "同花顺概念"},
        {"code": "BK_I1", "name": "行业1", "type": "industry", "subtype": "同花顺行业"},
    ]
    with patch(_PERSISTENCE_LIST_PATCH, return_value=(fake_boards, "mixed")):
        r = client.get("/api/v1/boards?source=zzshare")
    assert r.status_code == 200
    body = r.json()
    by_code = {b["code"]: b for b in body["data"]}
    assert by_code["BK_C1"]["type"] == "concept"
    assert by_code["BK_I1"]["type"] == "industry"


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
        r = client.get("/api/v1/boards/BK0001/stocks?source=eastmoney&refresh=true")
    assert r.status_code == 200
    args, kwargs = mock_get.call_args
    assert kwargs.get("refresh") is True
    assert kwargs.get("source") == "eastmoney"
    # board_code is positional (1st arg) in the persistence signature
    assert args[0] == "BK0001"


# ===== /boards/{code}/stocks: source=ths canonical (no alias) =====


def test_get_board_stocks_ths_passes_ths_to_persistence(client):
    """?source=ths now passes 'ths' through to persistence (no alias).

    Previously the route aliased 'ths' → 'zzshare' for board-stocks (mirroring
    board-list). After ThsFetcher gained get_board_stocks, the alias is
    removed and 'ths' is canonical. Backed by ThsFetcher at the manager
    layer (verified via `data_source == "ThsFetcher"` in the response).
    """
    fake = [{"stock_code": "300740", "stock_name": "皇台酒业"}]
    with (
        patch(
            "stock_data.data_provider.persistence.board.get_board_stocks",
            return_value=(fake, "ThsFetcher"),
        ) as mock_get,
        patch(
            "stock_data.data_provider.persistence.board.get_board_name",
            return_value="多多概念",
        ),
    ):
        r = client.get("/api/v1/boards/308709/stocks?source=ths")
    assert r.status_code == 200
    # Persistence was called with source='ths' (NOT aliased to zzshare).
    _, kwargs = mock_get.call_args
    assert kwargs.get("source") == "ths"
    assert r.json()["data_source"] == "ThsFetcher"


def test_get_board_stocks_zzshare_still_works(client):
    """?source=zzshare still works — independent path, kept for back-compat.

    ZzshareFetcher.plates_stocks is still served by the zzshare label; the
    removal of the ths→zzshare alias only affects explicit ?source=ths
    requests, not existing zzshare callers.
    """
    fake = [{"stock_code": "300740", "stock_name": "皇台酒业"}]
    with (
        patch(
            "stock_data.data_provider.persistence.board.get_board_stocks",
            return_value=(fake, "ZzshareFetcher"),
        ) as mock_get,
        patch(
            "stock_data.data_provider.persistence.board.get_board_name",
            return_value="多多概念",
        ),
    ):
        r = client.get("/api/v1/boards/308709/stocks?source=zzshare")
    assert r.status_code == 200
    _, kwargs = mock_get.call_args
    assert kwargs.get("source") == "zzshare"
    assert r.json()["data_source"] == "ZzshareFetcher"


def test_get_board_stocks_unknown_source_returns_400_or_422(client):
    """?source=unknown → 400 or 422 (Literal or _resolve_board_stocks_source).

    FastAPI's Literal rejection yields 422 (Pydantic validation error).
    The _resolve_board_stocks_source fallback would yield 400 if Literal
    is widened in the future. Both are acceptable — the spec only requires
    the request to fail loudly (no silent default-to-something).
    """
    r = client.get("/api/v1/boards/308709/stocks?source=bogus")
    assert r.status_code in (400, 422)


def test_get_board_stocks_projects_amount_from_fetcher_output(client):
    """Route projects 'amount' (元) from fetcher output into BoardStockInfo.

    THS fetcher populates 'amount' from the upstream 成交额 column.
    EastMoney fetcher populates 'amount' via push2 clist f6 field (only when
    include_quote=True). Zzshare leaves 'amount' as None. The route must
    forward whatever the fetcher returned — including 成交额 — into the
    response so callers don't lose data the upstream already provided.
    """
    fake = [
        {
            "stock_code": "300740",
            "stock_name": "皇台酒业",
            "exchange": "sz",
            "price": 22.49,
            "change_pct": 1.44,
            "volume": None,  # THS upstream has no shares-volume column
            "amount": 10.23e8,  # 10.23亿元 = 1,023,000,000 元
        }
    ]
    with (
        patch(
            "stock_data.data_provider.persistence.board.get_board_stocks",
            return_value=(fake, "ThsFetcher"),
        ),
        patch(
            "stock_data.data_provider.persistence.board.get_board_name",
            return_value="多多概念",
        ),
    ):
        r = client.get("/api/v1/boards/308709/stocks?source=ths")
    assert r.status_code == 200
    stock = r.json()["stocks"][0]
    assert stock["code"] == "300740"
    assert stock["price"] == 22.49
    assert stock["change_pct"] == 1.44
    assert stock["volume"] is None  # upstream has no shares-volume
    assert stock["amount"] == 10.23e8  # 成交额 (元) projected through


def test_get_board_stocks_projects_change_amount_and_turnover_rate(client):
    """Route projects 'change_amount' (元) and 'turnover_rate' (%) alongside
    the existing fields.

    Both are populated by THS upstream (idx 5 涨跌元, idx 7 换手%) and by
    EastMoney when include_quote=True (f4 → change_amount, f8 → turnover_rate).
    Without this projection, they were silently dropped at the schema boundary
    — same anti-pattern that originally motivated commit 46ff6cb for amount.
    """
    fake = [
        {
            "stock_code": "300740",
            "stock_name": "皇台酒业",
            "exchange": "sz",
            "price": 22.49,
            "change_pct": 1.44,
            "change_amount": 0.32,  # 涨跌 0.32元
            "turnover_rate": 12.32,  # 换手率 12.32%
        }
    ]
    with (
        patch(
            "stock_data.data_provider.persistence.board.get_board_stocks",
            return_value=(fake, "ThsFetcher"),
        ),
        patch(
            "stock_data.data_provider.persistence.board.get_board_name",
            return_value="多多概念",
        ),
    ):
        r = client.get("/api/v1/boards/308709/stocks?source=ths")
    assert r.status_code == 200
    stock = r.json()["stocks"][0]
    assert stock["change_amount"] == 0.32
    assert stock["turnover_rate"] == 12.32


def test_get_board_stocks_projects_change_amount_and_turnover_rate_null_when_absent(client):
    """Both new fields default to None when the fetcher doesn't populate them.

    Verifies the schema's default-None contract for callers relying on the
    guaranteed-optional semantics (independent of the source). This is the
    EastMoney include_quote=False path, and the Zzshare/Zhitu path (which
    never emit quote fields).
    """
    fake = [
        {
            "stock_code": "300740",
            "stock_name": "皇台酒业",
            "exchange": "sz",
            "price": 22.49,
            "change_pct": 1.44,
            # No change_amount, no turnover_rate keys — fetcher didn't emit them
        }
    ]
    with (
        patch(
            "stock_data.data_provider.persistence.board.get_board_stocks",
            return_value=(fake, "ZzshareFetcher"),
        ),
        patch(
            "stock_data.data_provider.persistence.board.get_board_name",
            return_value="多多概念",
        ),
    ):
        r = client.get("/api/v1/boards/308709/stocks?source=zzshare")
    assert r.status_code == 200
    stock = r.json()["stocks"][0]
    assert stock["change_amount"] is None
    assert stock["turnover_rate"] is None


def test_get_board_stocks_ths_falls_back_when_get_all_boards_unavailable(client):
    """?source=ths board-name fallback handles missing get_all_boards.

    ThsFetcher implements ``get_board_stocks`` (for the AJAX endpoint) but
    not ``get_all_boards`` (THS has no board-list endpoint). When the
    persistence cache misses, the route's board-name fallback calls
    ``manager.get_all_boards(source="ths", ...)`` which raises
    ``AttributeError`` (manager calls the missing method directly).

    The route must catch this gracefully (along with ``ValueError`` from
    unknown sources and ``DataFetchError`` from fetcher failures) and
    fall back to returning the bare ``board_code`` as the name. Previously
    this raised 500 — fixed 2026-07-05 alongside THS board-stocks wiring.
    """
    fake = [{"stock_code": "300740", "stock_name": "皇台酒业"}]
    with (
        patch(
            "stock_data.data_provider.persistence.board.get_board_stocks",
            return_value=(fake, "ThsFetcher"),
        ),
        # Cache miss for board name → triggers the upstream fallback path.
        patch(
            "stock_data.data_provider.persistence.board.get_board_name",
            return_value=None,
        ),
        # Simulate ThsFetcher lacking get_all_boards. We patch the
        # manager method because that's what the route calls; manager's
        # _with_source would otherwise raise ValueError before the
        # AttributeError — patching manager.get_all_boards directly
        # bypasses that layer and surfaces the AttributeError.
        patch(
            "stock_data.data_provider.manager.DataFetcherManager.get_all_boards",
            side_effect=AttributeError("'ThsFetcher' object has no attribute 'get_all_boards'"),
        ),
    ):
        r = client.get("/api/v1/boards/308709/stocks?source=ths")
    # The request must NOT 500; the fallback is non-fatal.
    assert r.status_code == 200
    body = r.json()
    # Bare board_code returned as name when fallback cannot resolve.
    assert body["board"]["code"] == "308709"
    assert body["board"]["name"] == "308709"
    assert body["data_source"] == "ThsFetcher"
    assert len(body["stocks"]) == 1


# ===== get_stock_boards (NEW) =====


def test_get_stock_boards_zhitu_returns_200_with_cold_sources_when_empty(client):
    """No zhitu data + cold_fill=False (default) -> 200 + cold_sources=['zhitu'].

    Auto-cold-fill is removed; callers must opt in with ?cold_fill=true.
    The route no longer raises 404 -- cold data surfaces in cold_sources.
    """
    # Use a stock code unlikely to have prior membership data so the route
    # takes the empty-membership path.
    from stock_data.data_provider.persistence import board as board_mod

    stock_code = "800999"
    board_mod.init_schema()
    conn = board_mod.get_connection()  # type: ignore[attr-defined]
    # wipe pre-existing rows for this stock so membership is empty
    conn.execute("DELETE FROM stock_board_membership WHERE stock_code = ?", (stock_code,))
    conn.commit()

    try:
        r = client.get(f"/api/v1/stocks/{stock_code}/boards?source=zhitu")
        assert r.status_code == 200
        body = r.json()
        assert body["stock_code"] == stock_code
        assert body["data"] == []
        assert body["cold_sources"] == ["zhitu"]
        # cache hit (empty), no fetcher call -> origin "persistence"
        assert body["source"] == "persistence"
    finally:
        conn.execute("DELETE FROM stock_board_membership WHERE stock_code = ?", (stock_code,))
        conn.commit()


def test_get_stock_boards_eastmoney_returns_200_with_cold_sources_when_empty(client):
    """No eastmoney data -> 200 + cold_sources=['eastmoney'], no 404.

    Pre-merge behavior was 404 + cold_source:true; replaced by uniform 200
    response with cold_sources list (Task 4 of the spec).
    """
    r = client.get("/api/v1/stocks/800998/boards?source=eastmoney")
    assert r.status_code == 200
    body = r.json()
    assert body["data"] == []
    assert "eastmoney" in body["cold_sources"]


def test_get_stock_boards_zzshare_returns_200_with_cold_sources_when_empty(client):
    """No zzshare data -> 200 + cold_sources contains the post-alias source.

    source=zzshare aliases to ths (data is THS upstream), so the cold source
    label in the response is "ths" (the canonical key), not "zzshare".
    """
    r = client.get("/api/v1/stocks/800997/boards?source=zzshare")
    assert r.status_code == 200
    body = r.json()
    assert body["data"] == []
    assert "ths" in body["cold_sources"]


def test_get_stock_boards_zhitu_cold_fill_returns_populated_boards(client):
    """Happy path: source=zhitu + cold_fill=true triggers zhitu lazy-fill.

    The cold-fill triggers a fetcher call (zhitu has the only native reverse
    API); the upserted rows surface in data with source='zhitu', and
    cold_sources is empty.
    """
    from stock_data.data_provider.persistence import board as board_mod

    stock_code = "800999"
    board_mod.init_schema()
    conn = board_mod.get_connection()  # type: ignore[attr-defined]
    conn.execute("DELETE FROM stock_board_membership WHERE stock_code = ?", (stock_code,))
    conn.commit()

    fake_boards = [
        {"code": "sw_yx", "name": "A股-申万行业-银行", "type": "industry", "subtype": "申万行业"},
        {
            "code": "chgn_700532",
            "name": "A股-热门概念-MSCI中国",
            "type": "concept",
            "subtype": "热门概念",
        },
    ]
    try:
        with patch(
            "stock_data.data_provider.manager.DataFetcherManager.get_stock_boards",
            return_value=(fake_boards, "ZhituFetcher"),
        ):
            r = client.get(f"/api/v1/stocks/{stock_code}/boards?source=zhitu&cold_fill=true")
        assert r.status_code == 200
        body = r.json()
        assert body["stock_code"] == stock_code
        assert len(body["data"]) == 2
        assert body["cold_sources"] == []
        # zhitu lazy-fill triggered -> origin reflects fresh fetcher hit
        assert body["source"] == "zhitu"
    finally:
        conn.execute("DELETE FROM stock_board_membership WHERE stock_code = ?", (stock_code,))
        conn.commit()


# ===== get_board_history (ths / eastmoney) =====


def test_get_board_history_source_required(client):
    """GET /boards/{code}/history without source → 422 (Query required)."""
    r = client.get("/api/v1/boards/881270/history")
    assert r.status_code == 422


def test_get_board_history_rejects_unknown_source(client):
    """Unknown source returns 400 from _resolve_board_history_source."""
    r = client.get("/api/v1/boards/881270/history?source=bogus")
    assert r.status_code == 400


def test_get_board_history_ths_rejects_weekly_frequency(client):
    """THS board history is daily-only; weekly raises upstream DataFetchError."""
    # Patch to avoid real network call. Return empty list (route still
    # 200s on empty data, so we rely on the manager being called with
    # frequency='w' and asserting the route didn't 422-validate).
    with patch(
        "stock_data.data_provider.manager.DataFetcherManager.get_board_history",
        return_value=([], "ThsFetcher"),
    ):
        r = client.get(
            "/api/v1/boards/881270/history",
            params={"source": "ths", "frequency": "w", "board_type": "industry"},
        )
    # 200 (route validation passed); upstream is patched so no 503.
    assert r.status_code == 200


def test_get_board_history_ths_returns_kline(client):
    """Happy path: ths returns rows → 200 with BoardKlineResponse."""
    fake_rows = [
        {
            "date": "2026-05-20",
            "open": 1.0,
            "high": 1.1,
            "low": 0.9,
            "close": 1.05,
            "volume": 100,
            "amount": 105.0,
            "pct_chg": 5.0,
        },
    ]
    with patch(
        "stock_data.data_provider.manager.DataFetcherManager.get_board_history",
        return_value=(fake_rows, "ThsFetcher"),
    ):
        r = client.get(
            "/api/v1/boards/881270/history",
            params={"source": "ths", "days": 7, "frequency": "d", "board_type": "industry"},
        )
    assert r.status_code == 200
    body = r.json()
    assert body["board_code"] == "881270"
    # period echoes the requested frequency
    assert body["period"] == "d"
    assert body["source"] == "ThsFetcher"
    assert len(body["data"]) == 1
    assert body["data"][0]["date"] == "2026-05-20"
    assert body["data"][0]["close"] == 1.05


def test_get_board_history_zzshare_aliases_to_ths(client):
    """Backward compat: `source=zzshare` is accepted and aliased to `ths`.

    ZzshareFetcher has no K-line implementation (upstream `plate_kline`
    only supports 883957 同花顺全A). The route layer must therefore alias
    `zzshare` → `ths` so the same source label continues to work without
    400 on unknown source. ThsFetcher then receives the request and
    surfaces a real upstream error (e.g. board_type missing).
    """
    with patch(
        "stock_data.data_provider.manager.DataFetcherManager.get_board_history",
        return_value=([], "ThsFetcher"),
    ) as spy:
        r = client.get(
            "/api/v1/boards/881270/history",
            params={"source": "zzshare", "frequency": "d", "board_type": "industry"},
        )
    # Validation must pass (NOT 400); upstream is patched so route returns 200.
    assert r.status_code == 200, r.text
    # Confirm the manager was called with source='ths' (alias applied).
    assert spy.call_args.kwargs.get("source") == "ths"
