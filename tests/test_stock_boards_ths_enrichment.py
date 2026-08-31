"""Tests for /stocks/{code}/boards live enrichment (THS source only).

The route layer calls ``manager.get_stock_boards(stock_code, source='ths')``
whenever ``ths`` is in the requested source list (gated by API input
parameter, NOT cache state), and merges the per-concept quote envelope
(change_pct / up_count / down_count / limit_up_count / limit_down_count /
explain / relevance) onto the cached membership rows. When persistence
has no rows for the requested stock (cold cache — typically first query
after startup or a stock backfill didn't cover), the live fetcher's full
result IS the response data, with NO persistence writeback (per design
decision 2026-08-30: route always calls thsfetcher for source=ths, so
writeback would be redundant).

Other sources (eastmoney / zhitu) do not trigger THS fetcher calls —
enrichment is gated on ``"ths" in normalized_sources``. They surface
new fields as ``None``.

This file mocks the persistence layer (``stock_board_cache``) and the
enrichment helper (``fetch_stock_boards_quote_enrichment``) at module
boundaries — no live upstream, no DB writes. The fetcher-level tests in
``tests/test_ths_fetcher.py::TestGetStockBoards`` cover the upstream
parsing contract; this file covers the route-layer merge + cold-cache
fallback + naming conventions.
"""

from unittest.mock import patch

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _clear_stock_boards_quote_cache():
    """Wipe the dedicated 60s TTLCache so per-test enrichment results don't leak."""
    from stock_data.api.cache import get_stock_boards_quote_cache

    get_stock_boards_quote_cache().clear()


def _patch_persistence_with_ths_entries(entries, cold_sources=None, origin="persistence"):
    """Replace ``stock_board_cache.get_stock_memberships`` to inject cached rows.

    Args:
        entries: list of persistence-layer entry dicts (5 legacy fields).
        cold_sources: list of source slugs reported as cold. Defaults to [].
        origin: ``origin_summary`` returned by the persistence helper
            (e.g. ``"persistence"``, ``"mixed"``).
    """
    from stock_data.api.routes import boards as boards_route

    if cold_sources is None:
        cold_sources = []
    return patch.object(
        boards_route.stock_board_cache,
        "get_stock_memberships",
        return_value=(entries, cold_sources, origin),
    )


def _patch_enrichment_with(fetcher_result=None, enrichment_by_code=None):
    """Replace ``fetch_stock_boards_quote_enrichment`` with a stub.

    The real helper returns ``(fetcher_full_result, enrichment_by_code)``.
    Tests that need a fetcher failure pass ``None`` (causes a RuntimeError
    via the sentinel branch); tests that need success pass the two
    parallel pieces.

    Args:
        fetcher_result: full fetcher list, used by the route as response
            data when persistence has no rows. ``None`` means no fetcher
            data (used with explicit enrichment map for warm-cache tests).
        enrichment_by_code: keyed by code, 7 enrichment fields each.
            Defaults to {}.
    """
    from stock_data.api._helpers import stock_boards as stock_boards_helper

    if fetcher_result is None and enrichment_by_code is None:
        # Explicit "fetcher failed" sentinel — raise so route's
        # @map_errors surfaces it. Tests for the helper's internal
        # try/except live separately and patch the manager instead.
        return patch.object(
            stock_boards_helper,
            "fetch_stock_boards_quote_enrichment",
            side_effect=RuntimeError("simulated fetcher failure"),
        )
    return patch.object(
        stock_boards_helper,
        "fetch_stock_boards_quote_enrichment",
        return_value=(fetcher_result or [], enrichment_by_code or {}),
    )


# ---------------------------------------------------------------------------
# Warm-cache path: live enrichment populates new fields on existing entries
# ---------------------------------------------------------------------------


def test_ths_source_enriches_change_pct_up_count_down_count(client):
    """The 3 fields shared with BoardQuoteResponse land on the response.

    Pinned 2026-08-30: field naming is identical between
    ``StockBoardInfo.change_pct / up_count / down_count`` and
    ``BoardQuoteResponse.change_pct / up_count / down_count`` so callers
    reading both surfaces can use the same key names without translation.
    """
    _clear_stock_boards_quote_cache()

    cached_entries = [
        {
            "code": "885909",
            "name": "辅助生殖",
            "type": "concept",
            "subtype": "同花顺概念",
            "source": "ths",
        },
    ]
    fetcher_result = [
        {
            "code": "885909", "name": "辅助生殖",
            "type": "concept", "subtype": "同花顺概念",
            "change_pct": -0.4114, "up_count": 30, "down_count": 43,
            "limit_up_count": 1, "limit_down_count": None,
            "explain": "2022年8月23日公司互动回复：...", "relevance": 2,
        },
    ]
    enrichment_by_code = {
        "885909": {
            "change_pct": -0.4114, "up_count": 30, "down_count": 43,
            "limit_up_count": 1, "limit_down_count": None,
            "explain": "2022年8月23日公司互动回复：...", "relevance": 2,
        },
    }

    with _patch_persistence_with_ths_entries(cached_entries), _patch_enrichment_with(
        fetcher_result=fetcher_result, enrichment_by_code=enrichment_by_code
    ):
        r = client.get("/api/v1/stocks/300519/boards?source=ths")

    assert r.status_code == 200
    body = r.json()
    assert len(body["data"]) == 1
    item = body["data"][0]
    assert item["code"] == "885909"
    # Quote envelope flows through
    assert item["change_pct"] == -0.4114
    assert isinstance(item["change_pct"], float)
    assert item["up_count"] == 30
    assert item["down_count"] == 43
    # Bonus fields also flow
    assert item["limit_up_count"] == 1
    assert item["limit_down_count"] is None
    assert item["explain"] == "2022年8月23日公司互动回复：..."
    assert item["relevance"] == 2
    # Warm cache → response origin stays "persistence"
    assert body["source"] == "persistence"
    assert body["cold_sources"] == []


def test_eastmoney_source_leaves_enrichment_fields_as_none(client):
    """Non-THS source → enrichment never queried, new fields stay None.

    eastmoney doesn't expose the per-concept quote envelope upstream, so
    the enrichment helper is gated on ``"ths" in normalized_sources`` —
    verifying this gate keeps the response shape stable for callers that
    pin eastmoney as their source.
    """
    _clear_stock_boards_quote_cache()

    cached_entries = [
        {
            "code": "BK0001",
            "name": "测试板块",
            "type": "industry",
            "subtype": "industry",
            "source": "eastmoney",
        },
    ]

    # Pass explicit (None, None) → stub raises (sentinel). If the
    # enrichment helper is incorrectly called for eastmoney, the test
    # fails with 500. We expect 200 + None fields.
    with _patch_persistence_with_ths_entries(cached_entries), _patch_enrichment_with(
        fetcher_result=None, enrichment_by_code=None
    ):
        r = client.get("/api/v1/stocks/600519/boards?source=eastmoney")

    assert r.status_code == 200
    body = r.json()
    assert len(body["data"]) == 1
    item = body["data"][0]
    # New enrichment fields stay None — eastmoney doesn't expose them.
    assert item["change_pct"] is None
    assert item["up_count"] is None
    assert item["down_count"] is None
    assert item["limit_up_count"] is None
    assert item["limit_down_count"] is None
    assert item["explain"] is None
    assert item["relevance"] is None
    # Legacy fields still present
    assert item["code"] == "BK0001"
    assert item["name"] == "测试板块"
    assert item["source"] == "eastmoney"


def test_ths_source_partial_overlap_enriches_only_matching_codes(client):
    """If fetcher returns 4 boards but cache only has 3, only matching rows get enriched.

    Defensive check against the scenario where fetcher membership drifts
    upstream (board delisted, etc.) — the enrichment loop walks by code,
    so a stale cache row whose code no longer exists in the upstream
    result simply keeps its ``None`` enrichment fields without crashing.
    """
    _clear_stock_boards_quote_cache()

    cached_entries = [
        # Present in enrichment
        {"code": "885909", "name": "辅助生殖", "type": "concept", "subtype": "同花顺概念", "source": "ths"},
        # Stale: not in enrichment (upstream dropped it)
        {"code": "885OLD", "name": "已退市概念", "type": "concept", "subtype": "同花顺概念", "source": "ths"},
    ]
    enrichment_by_code = {
        "885909": {
            "change_pct": -0.4114, "up_count": 30, "down_count": 43,
            "limit_up_count": 1, "limit_down_count": None,
            "explain": "...", "relevance": 2,
        },
        "885NEW": {  # Fetcher has 885NEW but cache doesn't — extra entries ignored
            "change_pct": 1.5, "up_count": 5, "down_count": 2,
            "limit_up_count": 0, "limit_down_count": 0,
            "explain": "...", "relevance": 0,
        },
    }
    fetcher_result = [{"code": k, **v, "name": k, "type": "concept", "subtype": "同花顺概念"}
                      for k, v in enrichment_by_code.items()]

    with _patch_persistence_with_ths_entries(cached_entries), _patch_enrichment_with(
        fetcher_result=fetcher_result, enrichment_by_code=enrichment_by_code
    ):
        r = client.get("/api/v1/stocks/300519/boards?source=ths")

    assert r.status_code == 200
    items = r.json()["data"]
    assert len(items) == 2
    by_code = {it["code"]: it for it in items}
    assert by_code["885909"]["change_pct"] == -0.4114
    assert by_code["885909"]["up_count"] == 30
    # Stale row gets None enrichment, not a crash.
    assert by_code["885OLD"]["change_pct"] is None
    assert by_code["885OLD"]["up_count"] is None


# ---------------------------------------------------------------------------
# Cold-cache fallback (C1): fetcher result IS the response, no writeback
# ---------------------------------------------------------------------------


def test_ths_cold_cache_falls_back_to_fetcher_result(client):
    """When persistence has no row for the stock but THS is in source list:

    - enrichment fires (gated on API input, not cache state)
    - response.data uses the fetcher result directly
    - persistence is NOT written back (design decision 2026-08-30:
      route always calls thsfetcher for source=ths, writeback is
      redundant overhead)
    - response.source = "ths" (served via fetcher, not persistence)
    - cold_sources does NOT include "ths" anymore (we filled it)
    - other cold sources (eastmoney / zhitu) stay in cold_sources
    """
    _clear_stock_boards_quote_cache()

    persistence_empty = []
    fetcher_result = [
        {
            "code": "885909", "name": "辅助生殖",
            "type": "concept", "subtype": "同花顺概念",
            "change_pct": -0.4114, "up_count": 30, "down_count": 43,
            "limit_up_count": 1, "limit_down_count": None,
            "explain": "...", "relevance": 2,
        },
        {
            "code": "885879", "name": "流感",
            "type": "concept", "subtype": "同花顺概念",
            "change_pct": -0.7418, "up_count": 66, "down_count": 114,
            "limit_up_count": 4, "limit_down_count": 0,
            "explain": "...", "relevance": 2,
        },
    ]
    enrichment_by_code = {
        r["code"]: {k: r[k] for k in (
            "change_pct", "up_count", "down_count",
            "limit_up_count", "limit_down_count", "explain", "relevance",
        )}
        for r in fetcher_result
    }

    # Persistence reports all 3 sources cold (typical first query scenario).
    with _patch_persistence_with_ths_entries(
        persistence_empty, cold_sources=["ths", "eastmoney", "zhitu"]
    ), _patch_enrichment_with(
        fetcher_result=fetcher_result, enrichment_by_code=enrichment_by_code
    ):
        r = client.get("/api/v1/stocks/300519/boards")

    assert r.status_code == 200
    body = r.json()
    assert len(body["data"]) == 2
    by_code = {it["code"]: it for it in body["data"]}

    # Fetcher result flows through with all 7 enrichment fields.
    assert by_code["885909"]["change_pct"] == -0.4114
    assert by_code["885909"]["up_count"] == 30
    assert by_code["885879"]["limit_up_count"] == 4
    assert by_code["885879"]["limit_down_count"] == 0

    # origin reflects "served via enrichment"
    assert body["source"] == "ths"
    # ths was filled via enrichment → removed from cold_sources
    # eastmoney / zhitu stay cold (no enrichment for them)
    assert "ths" not in body["cold_sources"]
    assert set(body["cold_sources"]) == {"eastmoney", "zhitu"}


def test_ths_cold_cache_filters_by_type(client):
    """Cold-cache fallback respects ?type= filter.

    The persistence helper applies the type filter before returning;
    on cold cache the fetcher result bypasses the helper, so the route
    must filter the enrichment-derived entries itself.
    """
    _clear_stock_boards_quote_cache()

    fetcher_result = [
        {"code": "885909", "name": "辅助生殖", "type": "concept", "subtype": "同花顺概念",
         "change_pct": 0.0, "up_count": 0, "down_count": 0,
         "limit_up_count": 0, "limit_down_count": 0,
         "explain": None, "relevance": 0},
        {"code": "881121", "name": "医药制造业", "type": "industry", "subtype": "同花顺行业",
         "change_pct": 0.5, "up_count": 10, "down_count": 5,
         "limit_up_count": 0, "limit_down_count": 0,
         "explain": None, "relevance": 0},
    ]
    enrichment_by_code = {
        r["code"]: {k: r[k] for k in (
            "change_pct", "up_count", "down_count",
            "limit_up_count", "limit_down_count", "explain", "relevance",
        )}
        for r in fetcher_result
    }

    with _patch_persistence_with_ths_entries(
        [], cold_sources=["ths", "eastmoney", "zhitu"]
    ), _patch_enrichment_with(
        fetcher_result=fetcher_result, enrichment_by_code=enrichment_by_code
    ):
        r = client.get("/api/v1/stocks/300519/boards?source=ths&type=industry")

    assert r.status_code == 200
    body = r.json()
    assert len(body["data"]) == 1
    assert body["data"][0]["code"] == "881121"
    assert body["data"][0]["type"] == "industry"


# ---------------------------------------------------------------------------
# Failure paths: helper's internal try/except never breaks the response
# ---------------------------------------------------------------------------


def test_ths_source_enrichment_helper_internal_try_except_swallows_fetcher_error():
    """The helper's own try/except catches DataFetchError + Exception.

    This is the production guarantee: a fetcher outage or transient
    upstream 5xx must NOT propagate to the route — the 5 legacy fields
    on cached entries must still flow through, with the 7 enrichment
    fields left as ``None`` (the Pydantic default).
    """
    _clear_stock_boards_quote_cache()

    from unittest.mock import MagicMock

    from stock_data.api._helpers.stock_boards import fetch_stock_boards_quote_enrichment
    from stock_data.data_provider.base import DataFetchError

    fake_mgr = MagicMock()
    fake_mgr.get_stock_boards = MagicMock(
        side_effect=DataFetchError("upstream timeout")
    )

    fetcher_result, enrichment = fetch_stock_boards_quote_enrichment("300519", fake_mgr)
    assert fetcher_result is None
    assert enrichment == {}

    # Also assert a generic Exception is caught (defensive net).
    fake_mgr.get_stock_boards = MagicMock(side_effect=RuntimeError("network reset"))
    fetcher_result, enrichment = fetch_stock_boards_quote_enrichment("300519", fake_mgr)
    assert fetcher_result is None
    assert enrichment == {}


def test_ths_enrichment_helper_leak_surfaces_500_via_map_errors(client):
    """If the helper itself somehow leaks an exception (bypassing its own
    try/except), ``@map_errors`` converts it to 500 — fail-loud rather
    than silently corrupt the response. This is a defensive test: the
    helper's own try/except is the production guarantee; this test
    pins the route-level safety net.
    """
    _clear_stock_boards_quote_cache()

    cached_entries = [
        {
            "code": "885909", "name": "辅助生殖",
            "type": "concept", "subtype": "同花顺概念",
            "source": "ths",
        },
    ]

    from stock_data.api._helpers import stock_boards as stock_boards_helper

    with _patch_persistence_with_ths_entries(cached_entries), patch.object(
        stock_boards_helper, "fetch_stock_boards_quote_enrichment", side_effect=RuntimeError("boom")
    ):
        r = client.get("/api/v1/stocks/300519/boards?source=ths")

    assert r.status_code == 500


def test_ths_cold_cache_with_fetcher_failure_returns_empty(client):
    """Cold cache + fetcher failure / empty result: 200 with empty data.

    When the enrichment helper returns ``(None, {})`` (fetcher raised an
    exception that its internal try/except caught) or ``([], {})`` (fetcher
    returned no concepts for this stock), the cold-cache fallback branch
    is skipped because ``fetcher_full_result`` is falsy. The route falls
    through to the default ``else`` branch: data=[], cold_sources stays
    unchanged (includes "ths"). 200, NOT 500 — the helper's internal
    try/except is the production guarantee that fetcher outages don't
    break the response.
    """
    _clear_stock_boards_quote_cache()

    fetcher_result, enrichment = None, {}  # fetcher "failed" (helper returns this)

    with _patch_persistence_with_ths_entries(
        [], cold_sources=["ths", "eastmoney", "zhitu"]
    ), _patch_enrichment_with(
        fetcher_result=fetcher_result, enrichment_by_code=enrichment
    ):
        r = client.get("/api/v1/stocks/300519/boards?source=ths")

    assert r.status_code == 200
    body = r.json()
    assert body["data"] == []
    # cold_sources unchanged — ths is still cold (enrichment couldn't fill it)
    assert set(body["cold_sources"]) == {"ths", "eastmoney", "zhitu"}
    # origin = "persistence" (the persistence helper returned empty)
    assert body["source"] == "persistence"
