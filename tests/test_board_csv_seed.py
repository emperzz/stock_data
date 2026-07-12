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