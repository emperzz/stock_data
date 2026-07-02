"""Smoke test: /stocks/{code}/boards?source=eastmoney triggers eastmoney cold-fill.

Verifies the eastmoney branch in ``stock_board_cache.get_stock_memberships``
mirrors the zhitu pattern: when the persistence cache is empty for eastmoney
and cold_fill=true, the fetcher is called and rows are written via
``upsert_membership_for_stock_boards``. When the fetcher returns ``None``
(invalid stock code), the response is a 200 with eastmoney in ``cold_sources``
(no 500).
"""
from unittest.mock import patch


def _make_fake_manager(*, boards, fetcher_name="EastMoneyFetcher"):
    """Build a MagicMock manager whose get_stock_boards returns (boards, name)."""
    from unittest.mock import MagicMock

    mgr = MagicMock()
    mgr.get_stock_boards = MagicMock(return_value=(boards, fetcher_name))
    return mgr


def test_eastmoney_source_lazy_fill_writes_membership(client):
    """Happy path: empty cache + cold_fill=true -> fetcher called, rows upserted.

    Mirrors ``test_get_stock_boards_zhitu_cold_fill_returns_populated_boards``
    for eastmoney (Task 6).
    """
    from stock_data.data_provider.persistence import board as board_mod

    stock_code = "600876"  # arbitrary — clear any prior membership rows first
    board_mod.init_schema()
    conn = board_mod.get_connection()
    conn.execute(
        "DELETE FROM stock_board_membership WHERE stock_code = ?", (stock_code,)
    )
    conn.commit()

    fake_boards = [
        {
            "code": "BK0438", "name": "食品饮料",
            "type": "industry", "subtype": "industry",
            "change_pct": 0.34, "change_amount": 81.80,
            "leading_stock_code": "600872",
            "leading_stock_name": "中炬高新",
        },
        {
            "code": "BK0481", "name": "光伏设备",
            "type": "industry", "subtype": "industry",
            "change_pct": -1.12, "change_amount": -42.30,
            "leading_stock_code": "601012",
            "leading_stock_name": "隆基绿能",
        },
    ]
    try:
        with patch(
            "stock_data.data_provider.manager.DataFetcherManager.get_stock_boards",
            return_value=(fake_boards, "EastMoneyFetcher"),
        ):
            r = client.get(
                f"/api/v1/stocks/{stock_code}/boards?source=eastmoney&cold_fill=true"
            )
        assert r.status_code == 200
        body = r.json()
        assert body["stock_code"] == stock_code
        assert len(body["data"]) == 2
        assert body["cold_sources"] == []
        # Single-source eastmoney cold-fill -> origin reflects fresh fetcher hit
        assert body["source"] == "eastmoney"
        # All entries are tagged with source=eastmoney
        assert all(e["source"] == "eastmoney" for e in body["data"])
    finally:
        conn.execute(
            "DELETE FROM stock_board_membership WHERE stock_code = ?", (stock_code,)
        )
        conn.commit()


def test_eastmoney_source_invalid_code_returns_200_with_cold_sources(client):
    """If eastmoney returns None (invalid code), surface as cold_sources, not error.

    The route returns 200 with empty data and eastmoney in cold_sources —
    never 500. This mirrors the pre-existing 800998 case in
    ``test_get_stock_boards_eastmoney_returns_200_with_cold_sources_when_empty``.
    """
    r = client.get("/api/v1/stocks/800998/boards?source=eastmoney")
    assert r.status_code == 200
    body = r.json()
    assert body["data"] == []
    assert "eastmoney" in body["cold_sources"]


def test_eastmoney_lazy_fill_skipped_when_manager_missing(monkeypatch, tmp_path):
    """When cold_fill=true but manager is None, the persistence layer should
    gracefully skip the fetch and return whatever is in the cache.

    This guards against a regression where the new eastmoney branch could
    dereference a None manager (the zhitu branch already has this guard via
    ``manager is not None``).
    """
    from stock_data.data_provider.persistence import board as board_mod
    from stock_data.data_provider.persistence import db as db_mod

    # Fresh DB so we don't see stale eastmoney rows from the dev cache.
    monkeypatch.setattr(db_mod, "_db_path", None)
    monkeypatch.setattr(db_mod, "_conn", None)
    board_mod._schema_initialized_paths = set()
    monkeypatch.setenv("STOCK_CACHE_DB_PATH", str(tmp_path / "no_manager.db"))
    board_mod.init_schema()

    # No cache rows, manager=None, cold_fill=True -> empty entries, eastmoney in cold_sources,
    # and importantly: no exception, no 500.
    entries, cold_sources, origin = board_mod.get_stock_memberships(
        stock_code="600519",
        sources=["eastmoney"],
        cold_fill=True,
        manager=None,
    )
    assert entries == []
    assert cold_sources == ["eastmoney"]
    assert origin == "persistence"


def test_eastmoney_source_routes_through_persistence_layer(client):
    """Sanity check: the route delegates to ``stock_board_cache.get_stock_memberships``,
    not directly to ``manager.get_stock_boards``. We patch the persistence helper
    and confirm the route picks it up.
    """
    from stock_data.api.routes import boards as boards_route

    fake_entries = [
        {"code": "BK0001", "name": "测试板块",
         "type": "industry", "subtype": "industry", "source": "eastmoney"},
    ]
    with patch.object(
        boards_route.stock_board_cache,
        "get_stock_memberships",
        return_value=(fake_entries, [], "persistence"),
    ):
        r = client.get("/api/v1/stocks/600519/boards?source=eastmoney")
    assert r.status_code == 200
    body = r.json()
    assert len(body["data"]) == 1
    assert body["data"][0]["code"] == "BK0001"
    assert body["cold_sources"] == []
