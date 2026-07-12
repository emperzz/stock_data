"""Tests for persistence.board_csv module (CSV seed for stock_board + membership)."""
from __future__ import annotations

import logging
import os
import re
from pathlib import Path

import pytest

from stock_data.data_provider.persistence import board as board_mod
from stock_data.data_provider.persistence import board_csv
from stock_data.data_provider.persistence import db as db_mod


@pytest.fixture
def fresh_db(tmp_path, monkeypatch):
    """Ephemeral SQLite DB — reset module singletons so init_schema reruns.

    Mirrors the pattern in tests/test_board_backfill.py.
    """
    monkeypatch.setattr(db_mod, "_db_path", None)
    monkeypatch.setattr(db_mod, "_conn", None)
    monkeypatch.setattr(board_mod, "_schema_initialized_paths", set())
    monkeypatch.setenv("STOCK_CACHE_DB_PATH", str(tmp_path / "test.db"))
    board_mod.init_schema()
    yield tmp_path / "test.db"


def test_seed_stock_board_ths_full_schema(fresh_db, tmp_path):
    """7-col THS CSV → all rows written to stock_board with source='ths'."""
    csv_path = tmp_path / "stock_board_ths.csv"
    csv_path.write_text(
        "code,name,board_type,subtype,source,platecode,updated_at\n"
        "885001,煤炭,industry,同花顺行业,ths,881001,2026-07-12 17:30:00\n"
        "885002,白酒,concept,同花顺概念,ths,885002,2026-07-12 17:30:00\n",
        encoding="utf-8-sig",
    )

    n = board_csv.seed_stock_board_from_csv("ths", csv_path)
    assert n == 2

    industry_rows = board_mod._read_boards_from_db("industry", "ths")
    assert len(industry_rows) == 1
    assert industry_rows[0]["code"] == "885001"
    assert industry_rows[0]["platecode"] == "881001"

    concept_rows = board_mod._read_boards_from_db("concept", "ths")
    assert len(concept_rows) == 1
    assert concept_rows[0]["code"] == "885002"


def test_seed_eastmoney_3col_fills_defaults(fresh_db, tmp_path):
    """3-col eastmoney CSV: source/subtype/platecode 由 loader 填充.

    Verifies both industry AND concept rows are written correctly
    (not just industry — avoids half-coverage regression).
    """
    csv_path = tmp_path / "stock_board_eastmoney.csv"
    csv_path.write_text(
        "board_type,board_code,board_name\n"
        "industry,BK1627,综合Ⅲ\n"
        "concept,BK1701,融资融券\n",
        encoding="utf-8-sig",
    )

    n = board_csv.seed_stock_board_from_csv("eastmoney", csv_path)
    assert n == 2

    industry_rows = board_mod._read_boards_from_db("industry", "eastmoney")
    assert len(industry_rows) == 1
    assert industry_rows[0]["code"] == "BK1627"
    assert industry_rows[0]["subtype"] == "industry"
    assert industry_rows[0]["platecode"] is None
    assert industry_rows[0]["source"] == "eastmoney"

    # concept 行也必须正确写入(否则只验了 industry 一半覆盖)
    concept_rows = board_mod._read_boards_from_db("concept", "eastmoney")
    assert len(concept_rows) == 1
    assert concept_rows[0]["code"] == "BK1701"
    assert concept_rows[0]["subtype"] == "concept"


def test_seed_membership_with_valid_codes(fresh_db, tmp_path):
    """8-col membership CSV → all rows written to stock_board_membership."""
    csv_path = tmp_path / "stock_board_membership_ths.csv"
    csv_path.write_text(
        "board_code,stock_code,source,board_name,stock_name,"
        "board_type,subtype,refreshed_at\n"
        "885002,600519,ths,白酒,贵州茅台,concept,同花顺概念,2026-07-12 17:30:00\n"
        "885002,000858,ths,白酒,五粮液,concept,同花顺概念,2026-07-12 17:30:00\n",
        encoding="utf-8-sig",
    )

    n = board_csv.seed_membership_from_csv(csv_path)
    assert n == 2

    rows = board_mod.read_membership(board_code="885002", source="ths")
    assert len(rows) == 2
    stock_codes = {r["stock_code"] for r in rows}
    assert stock_codes == {"600519", "000858"}
    assert any(r["stock_name"] == "贵州茅台" for r in rows)