"""Integration test: /stocks/{code}/boards reads membership, fallback to zhitu fetcher."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from stock_data.data_provider.persistence import board as board_mod
from stock_data.data_provider.persistence import db as db_mod
from stock_data.data_provider.persistence import stock_list as stock_list_mod


@pytest.fixture
def fresh_db(tmp_path, monkeypatch):
    # NOTE: project's `.env` sets STOCK_DB_INIT=true, which causes the FastAPI
    # lifespan to DROP+recreate all tables on every TestClient startup. We
    # must disable it BEFORE lifespan runs, otherwise our seeded stock_list
    # row gets wiped.
    monkeypatch.setenv("STOCK_DB_INIT", "false")
    monkeypatch.setattr(db_mod, "_db_path", None)
    monkeypatch.setattr(db_mod, "_conn", None)
    monkeypatch.setattr(board_mod, "_schema_initialized_paths", set())
    monkeypatch.setattr(stock_list_mod, "_schema_initialized_paths", set())
    monkeypatch.setenv("STOCK_CACHE_DB_PATH", str(tmp_path / "test.db"))
    board_mod.init_schema()
    stock_list_mod.init_schema()
    # Seed stock_list with one entry
    conn = db_mod.get_connection()
    conn.execute("""
        INSERT INTO stock_list (code, name, market) VALUES ('600519', '贵州茅台', 'csi')
    """)
    conn.commit()
    yield tmp_path / "test.db"


def test_reverse_route_returns_persisted_zhitu_boards(fresh_db):
    """Stock with rows in membership table → route returns them with source='persistence'."""
    board_mod.upsert_membership_bulk(
        source="zhitu",
        stocks=[{"stock_code": "600519", "stock_name": "贵州茅台"}],
        board_code="sw_yx_baijiu", board_name="白酒", board_type="industry", subtype="申万行业",
    )
    with TestClient(_app_for_test) as client:
        r = client.get("/api/v1/stocks/600519/boards?source=zhitu")
    assert r.status_code == 200
    body = r.json()
    assert body["source"] == "persistence"
    assert len(body["data"]) == 1
    assert body["data"][0]["code"] == "sw_yx_baijiu"


def test_reverse_route_zhitu_cold_path_populates_membership(fresh_db):
    """Cold path for zhitu: membership empty → fetcher called → upsert → return."""
    fake_boards = [
        {"code": "sw_yx_baijiu", "name": "白酒", "type": "industry", "subtype": "申万行业"},
    ]
    mock_manager = MagicMock()
    mock_manager.get_stock_boards.return_value = (fake_boards, "zhitu")

    # Patch get_manager at the boards route's import point so the route uses
    # our mock instead of constructing the real (network-using) manager.
    import stock_data.api.routes.boards as boards_route
    original_get_manager = boards_route.get_manager
    boards_route.get_manager = lambda: mock_manager
    try:
        with TestClient(_app_for_test) as client:
            r = client.get("/api/v1/stocks/600519/boards?source=zhitu")
    finally:
        boards_route.get_manager = original_get_manager

    assert r.status_code == 200
    body = r.json()
    assert body["source"] == "zhitu"
    # Verify membership was populated
    rows = board_mod.read_membership(stock_code="600519", source="zhitu")
    assert len(rows) == 1
    assert rows[0]["stock_name"] == "贵州茅台"  # from stock_list lookup


def test_reverse_route_eastmoney_404_with_cold_source_true(fresh_db):
    """Cold path for non-zhitu: no fetcher available → 404 + cold_source=true."""
    with TestClient(_app_for_test) as client:
        r = client.get("/api/v1/stocks/600519/boards?source=eastmoney")
    assert r.status_code == 404
    detail = r.json()["detail"]
    assert detail["error"] == "cold_stock_board_data"
    assert detail["cold_source"] is True
    assert "build_membership_index" in detail["message"]


# Lazy import — keeps this module cheap to collect when only the persistence
# tests above are being run via -k "not stock_boards_reverse_route".
from stock_data.server import app as _app_for_test  # noqa: E402