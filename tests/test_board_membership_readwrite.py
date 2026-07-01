"""Tests for read_membership + upsert_membership_bulk."""

from __future__ import annotations

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


def test_read_membership_by_board_code(fresh_db):
    """read_membership(board_code=...) returns forward-direction rows for that board."""
    board_mod.upsert_membership_bulk(
        source="eastmoney",
        stocks=[{"stock_code": "600519", "stock_name": "贵州茅台"}],
        board_code="BK1001",
        board_name="白酒",
        board_type="concept",
        subtype="concept",
    )
    rows = board_mod.read_membership(board_code="BK1001", source="eastmoney")
    assert len(rows) == 1
    assert rows[0]["stock_code"] == "600519"
    assert rows[0]["stock_name"] == "贵州茅台"
    assert rows[0]["board_name"] == "白酒"


def test_read_membership_by_stock_code(fresh_db):
    """read_membership(stock_code=...) returns reverse-direction rows for that stock."""
    # Stock 600519 in 2 boards, 2 sources
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
        board_code="sw_yx_baijiu",
        board_name="白酒",
        board_type="industry",
        subtype="申万行业",
    )
    rows = board_mod.read_membership(stock_code="600519")
    assert len(rows) == 2
    sources = {r["source"] for r in rows}
    assert sources == {"eastmoney", "zhitu"}


def test_read_membership_source_isolation(fresh_db):
    """source= filter limits results to one source."""
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
    rows = board_mod.read_membership(stock_code="600519", source="eastmoney")
    assert len(rows) == 1
    assert rows[0]["source"] == "eastmoney"


def test_read_membership_validates_one_of_keys(fresh_db):
    """read_membership without board_code and stock_code (or with both) raises ValueError."""
    with pytest.raises(ValueError, match="Exactly one"):
        board_mod.read_membership()
    with pytest.raises(ValueError, match="Exactly one"):
        board_mod.read_membership(board_code="X", stock_code="Y")
