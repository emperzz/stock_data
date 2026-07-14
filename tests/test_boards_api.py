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


def test_list_boards_source_ths_passes_ths_to_persistence(client):
    """?source=ths reaches persistence; source hardcoded to 'ths' inside helper."""
    from unittest.mock import patch

    from stock_data.data_provider.persistence import board as board_mod
    with patch.object(board_mod, "fetch_boards_with_zzshare_backfill",
                      return_value=[]) as mock_fetch:
        r = client.get("/api/v1/boards?type=concept&source=ths")
    assert r.status_code == 200
    # After unification, get_board_list doesn't take 'source' kwarg
    for call in mock_fetch.call_args_list:
        assert "source" not in call.kwargs


def test_list_boards_source_zzshare_returns_422(client):
    """?source=zzshare on /boards returns 422 (FastAPI Literal validation)."""
    r = client.get("/api/v1/boards?type=concept&source=zzshare")
    assert r.status_code == 422


def test_list_boards_zhitu_returns_zhitu_boards(client):
    """GET /boards?source=zhitu&type=concept returns Zhitu boards.

    Post-fix: persistence layer's ``get_board_list`` returns the
    user-supplied source slug (``"zhitu"``) as origin for fresh
    fetcher calls, NOT the fetcher's class name (``"ZhituFetcher"``).
    This aligns the response's ``source`` field with the documented
    source-tracking contract (lowercase slug). See CLAUDE.md
    "Source Tracking" section.
    """
    fake_boards = [
        {"code": "sw_mt", "name": "A股-申万行业-煤炭", "type": "industry", "subtype": "申万行业"},
    ]
    with patch(
        _PERSISTENCE_LIST_PATCH,
        return_value=(fake_boards, "zhitu"),
    ):
        r = client.get("/api/v1/boards?type=concept&source=zhitu")
    assert r.status_code == 200
    body = r.json()
    assert body["source"] == "zhitu"
    assert body["data"][0]["code"] == "sw_mt"


def test_list_boards_invalid_subtype_returns_400(client):
    """Subtype not in source's valid set → 400."""
    r = client.get("/api/v1/boards?type=concept&source=eastmoney&subtype=热门概念")
    # EastMoney has subtype=concept, not 热门概念
    assert r.status_code == 400


def test_list_boards_eastmoney_unsupported_type_returns_400(client):
    """?type=index/special&source=eastmoney → 400.

    EastMoneyFetcher.get_all_boards returns [] for index/special (no
    upstream classification). VALID_SUBTYPES_BY_SOURCE['eastmoney']
    must NOT declare these types — otherwise the route validator
    silently lets the request through, the fetcher returns [], and
    the caller gets a 200 with an empty data array instead of a
    clear 400 explaining eastmoney doesn't expose that type.
    """
    for unsupported in ("index", "special"):
        r = client.get(f"/api/v1/boards?type={unsupported}&source=eastmoney")
        assert r.status_code == 400, (
            f"type={unsupported}&source=eastmoney should be 400, got {r.status_code}"
        )
        body = r.json()
        assert "eastmoney" in str(body)
        assert unsupported in str(body)


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
            "source": "ths",
        },
    ]
    # First call: persistence returns the fetcher-sourced result
    with patch(
        _PERSISTENCE_LIST_PATCH,
        return_value=(fake_boards, "ThsFetcher"),
    ) as mock_get:
        r1 = client.get("/api/v1/boards?type=concept&source=ths")
        assert r1.status_code == 200
        assert r1.json()["source"] == "ThsFetcher"

        # Second call (cache hit): persistence returns the cached result
        # with origin="persistence" per CLAUDE.md source-tracking matrix.
        mock_get.return_value = (fake_boards, "persistence")
        r2 = client.get("/api/v1/boards?type=concept&source=ths")
        assert r2.status_code == 200
        assert r2.json()["source"] == "persistence"


def test_list_boards_refresh_forces_fetcher_call(client):
    """refresh=true → persistence is called with refresh=True (forces upstream)."""
    fake = [{"code": "BK0001", "name": "测试"}]
    with patch(_PERSISTENCE_LIST_PATCH, return_value=(fake, "ths")) as mock_get:
        r = client.get("/api/v1/boards?type=concept&source=ths&refresh=true")
    assert r.status_code == 200
    mock_get.assert_called_once()
    _, kwargs = mock_get.call_args
    assert kwargs.get("refresh") is True
    assert kwargs.get("source") == "ths"
    assert kwargs.get("subtype") is None


def test_list_boards_include_quote_forces_fetcher_call(client):
    """include_quote=true → persistence is called with include_quote=True."""
    fake = [{"code": "BK0001", "name": "测试"}]
    with patch(_PERSISTENCE_LIST_PATCH, return_value=(fake, "ths")) as mock_get:
        r = client.get("/api/v1/boards?type=concept&source=ths&include_quote=true")
    assert r.status_code == 200
    _, kwargs = mock_get.call_args
    assert kwargs.get("include_quote") is True


def test_list_boards_subtype_passed_to_persistence(client):
    """subtype param is forwarded to persistence layer (validation + filter)."""
    fake = [{"code": "BK0001", "name": "测试"}]
    with patch(_PERSISTENCE_LIST_PATCH, return_value=(fake, "ths")) as mock_get:
        r = client.get("/api/v1/boards?type=concept&source=ths&subtype=同花顺概念")
    assert r.status_code == 200
    _, kwargs = mock_get.call_args
    assert kwargs.get("subtype") == "同花顺概念"
    assert kwargs.get("source") == "ths"
    assert kwargs.get("board_type") == "concept"


def test_list_boards_persistence_validation_error_propagates(client):
    """ValueError from persistence (e.g. unknown source) → 400, not 500."""
    with patch(
        _PERSISTENCE_LIST_PATCH,
        side_effect=ValueError("No fetcher with name 'zzshare' is registered"),
    ):
        r = client.get("/api/v1/boards?type=concept&source=ths")
    assert r.status_code == 400
    body = r.json()
    # FastAPI wraps HTTPException detail under "detail"
    assert "No fetcher" in str(body)


def test_list_boards_source_zzshare_type_special_returns_422(client):
    """?source=zzshare&type=special returns 422 (Literal check fires before type check)."""
    r = client.get("/api/v1/boards?type=special&source=zzshare")
    assert r.status_code == 422


def test_list_boards_no_type_subtype_returns_400(client):
    """subtype filter without type is rejected at the route layer."""
    r = client.get("/api/v1/boards?source=ths&subtype=同花顺概念")
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
        r = client.get("/api/v1/boards?source=ths")
    assert r.status_code == 200
    body = r.json()
    by_code = {b["code"]: b for b in body["data"]}
    assert by_code["BK_C1"]["type"] == "concept"
    assert by_code["BK_I1"]["type"] == "industry"


def test_list_boards_no_type_eastmoney_iterates_only_concept_industry(client):
    """All-types query for source=eastmoney iterates ONLY concept+industry.

    Regression for 4abad92 + Finding 7: post-fix, the all-types loop
    in ``_get_all_board_types`` uses ``VALID_SUBTYPES_BY_SOURCE[source]``
    (not the old hardcoded ``"ths"``). Eastmoney's entry has only
    concept + industry (index/special were removed because
    ``EastMoneyFetcher.get_all_boards`` returns ``[]`` for those
    types), so the loop must NOT call ``manager.get_all_boards`` with
    board_type in {index, special}.

    Mocking strategy:
    - ``manager.get_all_boards`` is patched (we don't want real network).
    - ``update_cached_boards`` is patched to a no-op (no real DB writes
      that would pollute later tests).
    - ``_refresh_tracker.is_first_call`` is forced to True so we
      always hit the fetcher path regardless of test ordering.
    """
    from unittest.mock import MagicMock
    from unittest.mock import patch as _patch

    from stock_data.data_provider.persistence import board as board_mod

    call_log: list[tuple[str, str | None]] = []
    mgr = MagicMock()

    def fake_get_all_boards(*, source, board_type=None, subtype=None, include_quote=False):
        call_log.append((source, board_type))
        return (
            [{
                "code": f"BK_{board_type}",
                "name": f"{board_type} test",
                "type": board_type,
                "subtype": board_type,
                "source": source,
            }],
            source,
        )

    mgr.get_all_boards.side_effect = fake_get_all_boards
    forced_refresh = type("T", (), {"is_first_call": lambda *a: True})()

    with _patch("stock_data.api.routes.boards.get_manager", return_value=mgr), \
         _patch.object(board_mod, "update_cached_boards", return_value=0), \
         _patch.object(board_mod, "_refresh_tracker", forced_refresh):
        r = client.get("/api/v1/boards?source=eastmoney")

    assert r.status_code == 200
    called_types = {bt for src, bt in call_log}
    assert called_types == {"concept", "industry"}, (
        f"source=eastmoney should iterate only concept+industry; got {called_types}"
    )
    for src, bt in call_log:
        assert src == "eastmoney", f"unexpected source={src} for eastmoney query"

    body = r.json()
    by_type = {b["type"]: b for b in body["data"]}
    assert set(by_type.keys()) == {"concept", "industry"}
    assert "index" not in by_type
    assert "special" not in by_type
    # origin label is the user-supplied slug (post-fix contract).
    assert body["source"] == "eastmoney"


def test_list_boards_no_type_zhitu_iterates_all_four_types(client):
    """All-types query for source=zhitu iterates all 4 VALID_SUBTYPES_BY_SOURCE[zhitu] types.

    Inverse case to the eastmoney test: zhitu genuinely serves
    concept / industry / index / special upstream, so the loop must
    call ``manager.get_all_boards`` once per (board_type, source='zhitu')
    pair. Pairs with the eastmoney test to lock in the source-driven
    loop behavior across both ends of VALID_SUBTYPES_BY_SOURCE.
    """
    from unittest.mock import MagicMock
    from unittest.mock import patch as _patch

    from stock_data.data_provider.persistence import board as board_mod

    call_log: list[tuple[str, str | None]] = []
    mgr = MagicMock()

    def fake_get_all_boards(*, source, board_type=None, subtype=None, include_quote=False):
        call_log.append((source, board_type))
        return (
            [{
                "code": f"ZH_{board_type}",
                "name": f"{board_type} test",
                "type": board_type,
                "subtype": board_type,
                "source": source,
            }],
            source,
        )

    mgr.get_all_boards.side_effect = fake_get_all_boards
    forced_refresh = type("T", (), {"is_first_call": lambda *a: True})()

    with _patch("stock_data.api.routes.boards.get_manager", return_value=mgr), \
         _patch.object(board_mod, "update_cached_boards", return_value=0), \
         _patch.object(board_mod, "_refresh_tracker", forced_refresh):
        r = client.get("/api/v1/boards?source=zhitu")

    assert r.status_code == 200
    called_types = {bt for src, bt in call_log}
    assert called_types == {"concept", "industry", "index", "special"}, (
        f"source=zhitu should iterate all 4 types; got {called_types}"
    )
    for src, bt in call_log:
        assert src == "zhitu"

    body = r.json()
    by_type = {b["type"]: b for b in body["data"]}
    assert set(by_type.keys()) == {"concept", "industry", "index", "special"}


# ===== get_board_stocks =====


def test_get_board_stocks_source_required(client):
    r = client.get("/api/v1/boards/BK0001/stocks")
    assert r.status_code == 422


def test_get_board_stocks_returns_404_on_empty(client):
    """Empty stocks → 404."""
    with patch(
        "stock_data.data_provider.persistence.board.get_board_stocks",
        return_value=([], "eastmoney", "eastmoney", None, False, 0),
    ):
        r = client.get("/api/v1/boards/BK0001/stocks?source=eastmoney")
    assert r.status_code == 404


def test_cid_unresolved_returns_422(client):
    """cid-index miss → HTTP 422 with error='cid_unresolved'.

    Regression test for F2 (2026-07-10). The persistence helper now
    reports ``reason='cid_unresolved'`` when the THS cid-index cache
    misses for the board_code; the route layer maps this to 422 so
    operators can distinguish "board doesn't exist" (404) from
    "cid-index needs warming" (422).
    """
    with patch(
        "stock_data.data_provider.persistence.board.get_board_stocks",
        return_value=([], "ths", "ths", "cid_unresolved", False, 0),
    ):
        r = client.get("/api/v1/boards/885642/stocks?source=ths&include_quote=true")
    assert r.status_code == 422
    body = r.json()
    assert body["detail"]["error"] == "cid_unresolved"
    assert "885642" in body["detail"]["message"]
    assert "?refresh=true" in body["detail"]["message"]


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
        mock_get.return_value = (fake, "eastmoney", "eastmoney", None, False, 1)
        r1 = client.get("/api/v1/boards/BK0001/stocks?source=eastmoney")
        assert r1.status_code == 200
        assert r1.json()["data_source"] == "eastmoney"

        # Second call: cache hit — origin is persistence; effective_source
        # is the historical fetcher label (we keep 'eastmoney' here).
        mock_get.return_value = (fake, "persistence", "eastmoney", None, False, 1)
        r2 = client.get("/api/v1/boards/BK0001/stocks?source=eastmoney")
        assert r2.status_code == 200
        assert r2.json()["data_source"] == "persistence"


def test_get_board_stocks_refresh_forces_persistence_refresh(client):
    """refresh=true is forwarded to persistence layer (no longer silently dropped).

    Post-strict-routing: ``get_board_stocks`` now takes ``source=`` (so the
    route can pass the user's choice down to the helper for strict
    honoring). This test confirms both ``refresh=True`` and ``source``
    are plumbed through.
    """
    fake = [{"stock_code": "600519", "stock_name": "贵州茅台"}]
    with (
        patch(
            "stock_data.data_provider.persistence.board.get_board_stocks",
            return_value=(fake, "eastmoney", "eastmoney", None, False, 1),
        ) as mock_get,
        patch(
            "stock_data.data_provider.persistence.board.get_board_name",
            return_value="互联网服务",
        ),
    ):
        r = client.get("/api/v1/boards/BK0001/stocks?source=eastmoney&refresh=true")
    assert r.status_code == 200
    args, kwargs = mock_get.call_args
    assert kwargs.get("refresh") is True
    # Strict routing: source IS now a kwarg (the route layer plumbs it).
    assert kwargs.get("source") == "eastmoney"
    # board_code is positional (1st arg) in the persistence signature
    assert args[0] == "BK0001"


# ===== /boards/{code}/stocks: source=ths canonical (no alias) =====


def test_get_board_stocks_source_ths_passes_ths_to_persistence(client):
    """?source=ths reaches persistence; fetch helper receives source='ths'.

    Strict source-routing: the user's ``?source=`` is forwarded all the
    way down to ``fetch_board_stocks_with_zzshare_fallback`` so that the
    helper can route to the requested fetcher without ever silently
    falling back to a sibling source.

    ``?refresh=true`` forces the cold-path branch: without it, both
    ``persistence.board._refresh_tracker`` (module-level singleton that
    marks per-day) and the on-disk SQLite cache can short-circuit the
    call before it ever reaches the helper under test. The test is
    asserting that the helper IS called, so the call site must be the
    cold-path branch.
    """
    from unittest.mock import patch

    from stock_data.data_provider.persistence import board as board_mod
    with patch.object(board_mod, "fetch_board_stocks_with_zzshare_fallback",
                      return_value=([], "ths", "ths", None)) as mock_fetch:
        r = client.get("/api/v1/boards/885642/stocks?source=ths&refresh=true")
    assert r.status_code in (200, 404)  # empty may 404
    assert mock_fetch.call_count >= 1
    # Strict routing: the helper MUST receive source='ths'.
    first_call = mock_fetch.call_args_list[0]
    assert first_call.kwargs.get("source") == "ths"


def test_get_board_stocks_source_zzshare_returns_422(client):
    """?source=zzshare on /boards/{code}/stocks returns 422."""
    r = client.get("/api/v1/boards/308709/stocks?source=zzshare")
    assert r.status_code == 422


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
            return_value=(fake, "ths", "ths", None, False, 1),
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
            return_value=(fake, "ths", "ths", None, False, 1),
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
            return_value=(fake, "zzshare", "zzshare", None, False, 1),
        ),
        patch(
            "stock_data.data_provider.persistence.board.get_board_name",
            return_value="多多概念",
        ),
    ):
        r = client.get("/api/v1/boards/308709/stocks?source=ths")
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
            return_value=(fake, "ths", "ths", None, False, 1),
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
    assert body["data_source"] == "ths"
    assert body["effective_source"] == "ths"
    assert len(body["stocks"]) == 1


# ===== get_stock_boards (NEW) =====


def test_get_stock_boards_zhitu_returns_200_with_cold_sources_when_empty(client):
    """No zhitu data -> 200 + cold_sources=['zhitu'].

    The route does not raise 404 -- cold data surfaces in cold_sources.
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


def test_get_stock_boards_zzshare_type_special_returns_400(client):
    """`/stocks/{code}/boards?source=zzshare&type=special` → 400.

    Mirrors the `/boards?source=zzshare&type=special` 400: zzshare dropped
    its ``special`` slot on 2026-07-07. The per-source type guard must
    catch this BEFORE the membership helper runs, regardless of whether
    ``subtype`` is also provided.
    """
    # With no subtype, the guard still fires (subtype-independent).
    r = client.get("/api/v1/stocks/600000/boards?source=zzshare&type=special")
    assert r.status_code == 400
    assert "special" in str(r.json().get("detail", ""))
    assert "zzshare" in str(r.json().get("detail", ""))
    # With a subtype, the existing _validate_subtype also catches it.
    r2 = client.get(
        "/api/v1/stocks/600000/boards?source=zzshare&type=special&subtype=同花顺题材"
    )
    assert r2.status_code == 400


# ===== get_board_history (ths / eastmoney) =====


def test_get_board_history_source_required(client):
    """GET /boards/{code}/history without source → 422 (Query required)."""
    r = client.get("/api/v1/boards/881270/history")
    assert r.status_code == 422


def test_get_board_history_rejects_unknown_source(client):
    """Unknown source returns 400 from _resolve_board_history_source."""
    r = client.get("/api/v1/boards/881270/history?source=bogus")
    assert r.status_code == 400


def test_get_board_history_ths_supports_weekly_frequency(client):
    """Post-2026-07-14: THS supports weekly (upstream segment 02 verified).
    The route accepts frequency='w' for source='ths' and dispatches to
    ThsFetcher, which now serves weekly K-line via the same year-loop."""
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

    with patch(
        "stock_data.data_provider.manager.DataFetcherManager.get_board_history",
        return_value=([], "ThsFetcher"),
    ) as spy:
        client.get(
            "/api/v1/boards/881270/history",
            params={"source": "ths", "frequency": "w", "board_type": "industry"},
        )
    # The manager must receive frequency='w' (no normalization to d).
    assert spy.call_args.kwargs.get("frequency") == "w"


def test_get_board_history_ths_returns_kline(client):
    """Happy path: ths returns rows → 200 with BoardKlineResponse.

    Post-2026-07-14: each row carries a per-bar ``frequency`` tag
    (matches the request's ``?frequency=``). This is the user-visible
    contract for the consistency fix — the row self-identifies its
    timeframe, so a wrong-upstream-segment bug surfaces as a row-level
    mismatch, not just at the response top level.
    """
    fake_rows = [
        {
            "date": "2026-05-20",
            "frequency": "d",  # NEW: row-level tag from the fetcher
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
    # Per-row frequency tag — the user can verify the bar's timeframe
    # independently of the top-level period field.
    assert body["data"][0]["frequency"] == "d"


def test_get_board_history_per_row_frequency_falls_back_to_request(client):
    """Defense-in-depth: if a fetcher doesn't tag its rows with
    ``frequency`` (e.g. a new fetcher that hasn't been updated yet),
    the route falls back to the request's ``?frequency=`` so every
    bar still carries a meaningful tag — never None."""
    fake_rows = [
        # No "frequency" key in the row dict (legacy fetcher output).
        {
            "date": "2026-05-20",
            "open": 1.0, "high": 1.1, "low": 0.9, "close": 1.05,
            "volume": 100, "amount": 105.0, "pct_chg": 5.0,
        },
    ]
    with patch(
        "stock_data.data_provider.manager.DataFetcherManager.get_board_history",
        return_value=(fake_rows, "LegacyFetcher"),
    ):
        r = client.get(
            "/api/v1/boards/881270/history",
            params={"source": "ths", "days": 7, "frequency": "w", "board_type": "industry"},
        )
    body = r.json()
    assert body["period"] == "w"
    # Per-row tag fell back to the request's frequency.
    assert body["data"][0]["frequency"] == "w"


def test_get_board_history_per_row_frequency_distinct_from_top_period(client):
    """Top-level ``period`` and per-row ``frequency`` should match.
    A mismatch would mean a fetcher bug hit the wrong upstream segment
    — this test makes the contract explicit so future regressions
    surface immediately."""
    fake_rows = [
        # Fetcher tagged this row as weekly, but the request was for daily.
        # In production this would be a bug; the test asserts the API
        # surfaces the mismatch by trusting the per-row tag (which is
        # the fetcher's claim about what the bar actually is).
        {
            "date": "2026-05-20",
            "frequency": "w",  # claims weekly
            "open": 1.0, "high": 1.1, "low": 0.9, "close": 1.05,
            "volume": 100, "amount": 105.0, "pct_chg": 5.0,
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
    body = r.json()
    # Top-level echoes the request (intentional — that's the user's
    # intent). Per-row reflects what the data actually claims to be.
    assert body["period"] == "d"
    assert body["data"][0]["frequency"] == "w"  # mismatch is exposed


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


def test_boards_valid_sources_excludes_zzshare():
    """After unification, VALID_SOURCES must not include 'zzshare'."""
    from stock_data.data_provider.persistence import board as board_mod
    assert "zzshare" not in board_mod.VALID_SOURCES
    assert "ths" in board_mod.VALID_SOURCES
    assert "eastmoney" in board_mod.VALID_SOURCES
    assert "zhitu" in board_mod.VALID_SOURCES


def test_boards_stocks_valid_sources_excludes_zzshare():
    """_BOARD_STOCKS_VALID_SOURCES must not include 'zzshare' either."""
    from stock_data.data_provider.persistence import board as board_mod
    assert "zzshare" not in board_mod._BOARD_STOCKS_VALID_SOURCES
    assert "ths" in board_mod._BOARD_STOCKS_VALID_SOURCES
    assert "eastmoney" in board_mod._BOARD_STOCKS_VALID_SOURCES
    assert "zhitu" in board_mod._BOARD_STOCKS_VALID_SOURCES


def test_get_board_list_signature_has_source_arg():
    """get_board_list must accept 'source' param (default 'ths') for source routing."""
    import inspect

    from stock_data.data_provider.persistence import board as board_mod
    sig = inspect.signature(board_mod.get_board_list)
    assert "source" in sig.parameters, (
        f"get_board_list missing 'source' param: {list(sig.parameters)}"
    )
    assert sig.parameters["source"].default == "ths"


def test_get_board_stocks_signature_has_source_kwarg():
    """get_board_stocks accepts source='' for strict source routing (post-2026-07-10).

    Previously (after ths+zzshare unification) the helper dropped 'source' and
    let the fallback helper decide internally. The strict-routing refactor
    brought 'source' back as a required kwarg so callers can route their
    board-stocks request to the chosen fetcher without silent cross-source
    fallback.
    """
    import inspect

    from stock_data.data_provider.persistence import board as board_mod
    sig = inspect.signature(board_mod.get_board_stocks)
    assert "source" in sig.parameters, (
        f"get_board_stocks missing 'source' param: {list(sig.parameters)}"
    )


class TestBoardStocksTopNAndSort:
    """Route-level tests for sort_by / sort_order / top_n (Task 7 of plan)."""

    @patch("stock_data.data_provider.persistence.board.get_board_stocks",
           return_value=([{"stock_code": "000034", "stock_name": "x"}],
                         "persistence", "ths", None, False, 1))
    def test_default_request_no_new_fields(self, mock_pers, client):
        """不传 sort/top_n 时 response 行为不变 (quote_* echo 全部 None)."""
        r = client.get("/api/v1/boards/885756/stocks?source=ths")
        assert r.status_code == 200
        body = r.json()
        assert body["quote_truncated"] is False
        assert body["quote_top_n"] is None
        assert body["quote_sort_by"] is None
        assert body["quote_sort_order"] is None
        assert body["quote_total_in_board"] is None

    @patch("stock_data.data_provider.persistence.board.get_board_stocks",
           return_value=([{"stock_code": "000034", "stock_name": "x"}],
                         "ths", "ths", None, False, 1))
    def test_sort_by_echoed_back(self, mock_pers, client):
        """?sort_by=price 返回时 echo 回 quote_sort_by."""
        r = client.get(
            "/api/v1/boards/885756/stocks?source=ths&include_quote=true"
            "&sort_by=price&sort_order=asc&top_n=10"
        )
        assert r.status_code == 200
        body = r.json()
        assert body["quote_sort_by"] == "price"
        assert body["quote_sort_order"] == "asc"
        assert body["quote_top_n"] == 10
        assert body["quote_total_in_board"] == 1

    def test_sort_by_with_non_ths_source_returns_400(self, client):
        """source='eastmoney' + sort_by=price → 400 invalid_combination (route cross-validation)."""
        r = client.get(
            "/api/v1/boards/885756/stocks?source=eastmoney&include_quote=true"
            "&sort_by=price"
        )
        assert r.status_code == 400
        body = r.json()
        detail = body.get("detail", {})
        assert detail.get("error") == "invalid_combination"
        assert "source='ths'" in detail.get("message", "")

    def test_sort_by_without_include_quote_returns_400(self, client):
        """?sort_by=price 不带 include_quote=true → 400 (与 /boards sibling 一致)."""
        r = client.get(
            "/api/v1/boards/885756/stocks?source=ths"
            "&sort_by=price"
        )
        assert r.status_code == 400
        detail = r.json().get("detail", {})
        assert detail.get("error") == "invalid_combination"

    def test_top_n_above_50_returns_422(self, client):
        """Query(le=50) → FastAPI 自带 422 validation."""
        r = client.get(
            "/api/v1/boards/885756/stocks?source=ths&include_quote=true&top_n=100"
        )
        assert r.status_code == 422

    def test_sort_by_invalid_literal_returns_422(self, client):
        """Literal[...] 校验 → 422."""
        r = client.get(
            "/api/v1/boards/885756/stocks?source=ths&include_quote=true"
            "&sort_by=magic"
        )
        assert r.status_code == 422
