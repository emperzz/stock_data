"""Integration test: /stocks/{code}/board-memberships cross-source view."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from stock_data.data_provider.persistence import board as board_mod
from stock_data.data_provider.persistence import db as db_mod
from stock_data.server import app


@pytest.fixture
def fresh_db(tmp_path, monkeypatch):
    # Disable STOCK_DB_INIT=true from .env so the FastAPI lifespan doesn't
    # DROP+recreate tables and wipe our seed data.
    monkeypatch.setenv("STOCK_DB_INIT", "false")
    monkeypatch.setattr(db_mod, "_db_path", None)
    monkeypatch.setattr(db_mod, "_conn", None)
    monkeypatch.setattr(board_mod, "_schema_initialized_paths", set())
    monkeypatch.setenv("STOCK_CACHE_DB_PATH", str(tmp_path / "test.db"))
    board_mod.init_schema()
    yield tmp_path / "test.db"


def test_view_returns_per_source_groups(fresh_db):
    """Cross-source view groups membership rows by source."""
    board_mod.upsert_membership_bulk(
        source="eastmoney",
        stocks=[{"stock_code": "600519", "stock_name": "贵州茅台"}],
        board_code="BK1001",
        board_name="白酒",
        board_type="concept",
        subtype="concept",
    )
    board_mod.upsert_membership_bulk(
        source="zhitu",
        stocks=[{"stock_code": "600519", "stock_name": "贵州茅台"}],
        board_code="sw_yx",
        board_name="白酒",
        board_type="industry",
        subtype="申万行业",
    )
    # zzshare has no data for this stock

    with TestClient(app) as client:
        r = client.get("/api/v1/stocks/600519/board-memberships")
    assert r.status_code == 200
    body = r.json()
    assert "eastmoney" in body["memberships"]
    assert "zhitu" in body["memberships"]
    assert "zzshare" not in body["memberships"]
    assert "zzshare" in body["cold_sources"]
    assert body["cold_sources"] == ["zzshare"]


def test_view_filters_by_type(fresh_db):
    """?type=concept limits results to concept boards."""
    board_mod.upsert_membership_bulk(
        source="eastmoney",
        stocks=[{"stock_code": "600519", "stock_name": "贵州茅台"}],
        board_code="BK1",
        board_name="白酒",
        board_type="concept",
        subtype="concept",
    )
    board_mod.upsert_membership_bulk(
        source="eastmoney",
        stocks=[{"stock_code": "600519", "stock_name": "贵州茅台"}],
        board_code="BK2",
        board_name="饮料制造",
        board_type="industry",
        subtype="industry",
    )
    with TestClient(app) as client:
        r = client.get("/api/v1/stocks/600519/board-memberships?type=concept")
    assert r.status_code == 200
    body = r.json()
    eastmoney = body["memberships"]["eastmoney"]
    assert len(eastmoney) == 1
    assert eastmoney[0]["board_code"] == "BK1"


def test_view_empty_stock_returns_all_cold_sources(fresh_db):
    """Stock not in any membership row → all sources cold."""
    with TestClient(app) as client:
        r = client.get("/api/v1/stocks/999999/board-memberships")
    assert r.status_code == 200
    body = r.json()
    assert body["memberships"] == {}
    assert set(body["cold_sources"]) == {"eastmoney", "zhitu", "zzshare"}


def test_view_filters_by_subtype(fresh_db):
    """?subtype= filters by source-specific subtype."""
    board_mod.upsert_membership_bulk(
        source="zhitu",
        stocks=[{"stock_code": "600519", "stock_name": "贵州茅台"}],
        board_code="sw_yx",
        board_name="白酒",
        board_type="industry",
        subtype="申万行业",
    )
    board_mod.upsert_membership_bulk(
        source="zhitu",
        stocks=[{"stock_code": "600519", "stock_name": "贵州茅台"}],
        board_code="sw_yx_2",
        board_name="白酒2",
        board_type="industry",
        subtype="申万二级",
    )
    with TestClient(app) as client:
        r = client.get("/api/v1/stocks/600519/board-memberships?subtype=申万行业")
    body = r.json()
    zhitu = body["memberships"]["zhitu"]
    assert len(zhitu) == 1
    assert zhitu[0]["board_code"] == "sw_yx"
    assert zhitu[0]["subtype"] == "申万行业"


def test_wrapper_response_matches_helper_reshape(fresh_db):
    """Sanity: wrapper's {memberships: {src: [...]}} is the helper's
    flat list reshaped by source. Verify a multi-source seed round-trips."""
    board_mod.upsert_membership_bulk(
        source="zhitu",
        stocks=[{"stock_code": "600519", "stock_name": "贵州茅台"}],
        board_code="sw_yx",
        board_name="SW",
        board_type="industry",
        subtype="申万行业",
    )
    board_mod.upsert_membership_bulk(
        source="eastmoney",
        stocks=[{"stock_code": "600519", "stock_name": "贵州茅台"}],
        board_code="BK1048",
        board_name="EM",
        board_type="concept",
        subtype="concept",
    )
    with TestClient(app) as client:
        r = client.get("/api/v1/stocks/600519/board-memberships")
    assert r.status_code == 200
    body = r.json()
    assert set(body["memberships"].keys()) == {"zhitu", "eastmoney"}
    assert "zzshare" in body["cold_sources"]
    assert body["memberships"]["zhitu"][0]["board_code"] == "sw_yx"
    assert body["memberships"]["eastmoney"][0]["board_code"] == "BK1048"
