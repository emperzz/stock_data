"""Tests for persistence.board_csv module (CSV seed for stock_board + membership)."""

from __future__ import annotations

import logging

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
        "board_type,board_code,board_name\nindustry,BK1627,综合Ⅲ\nconcept,BK1701,融资融券\n",
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


def test_seed_membership_skips_invalid_stock_code(fresh_db, tmp_path, caplog):
    """无效 stock_code (非 6 位数字) warning + skip, 其余行写入."""
    csv_path = tmp_path / "stock_board_membership_ths.csv"
    csv_path.write_text(
        "board_code,stock_code,source,board_name,stock_name,"
        "board_type,subtype,refreshed_at\n"
        "885002,600519,ths,白酒,贵州茅台,concept,同花顺概念,2026-07-12 17:30:00\n"
        "885002,贵州茅台,ths,白酒,五粮液,concept,同花顺概念,2026-07-12 17:30:00\n"
        "885002,000858,ths,白酒,五粮液,concept,同花顺概念,2026-07-12 17:30:00\n",
        encoding="utf-8-sig",
    )

    with caplog.at_level(
        logging.WARNING,
        logger="stock_data.data_provider.persistence.board_csv",
    ):
        n = board_csv.seed_membership_from_csv(csv_path)
    assert n == 2
    assert any(
        "invalid stock_code" in r.message and "贵州茅台" in r.message for r in caplog.records
    ), f"expected invalid_code warning; got: {[r.message for r in caplog.records]}"


def test_seed_full_schema_skips_wrong_source_row(fresh_db, tmp_path, caplog):
    """CSV 里混一行 source='eastmoney' → 该行被 skip, summary warning 触发.

    验证 wrong-source 行被跳过(不写入 DB)+ 一条 summary warning(不是逐行
    warning, 避免 5000 行 spam)。
    """
    csv_path = tmp_path / "stock_board_ths.csv"
    csv_path.write_text(
        "code,name,board_type,subtype,source,platecode,updated_at\n"
        "885001,煤炭,industry,同花顺行业,ths,881001,2026-07-12 17:30:00\n"
        "885002,白酒,concept,同花顺概念,eastmoney,885002,2026-07-12 17:30:00\n"
        "885003,医药,concept,同花顺概念,ths,885003,2026-07-12 17:30:00\n",
        encoding="utf-8-sig",
    )

    with caplog.at_level(
        logging.WARNING,
        logger="stock_data.data_provider.persistence.board_csv",
    ):
        n = board_csv.seed_stock_board_from_csv("ths", csv_path)
    assert n == 2  # only 2 rows with source='ths'

    # Summary warning should mention count=1 and source='eastmoney'
    summary_records = [
        r for r in caplog.records if "wrong source" in r.message and "1 rows" in r.message
    ]
    assert len(summary_records) == 1, (
        f"expected exactly one summary warning; got: {[r.message for r in caplog.records]}"
    )

    # Verify the wrong-source row was NOT inserted
    rows = board_mod.read_membership(board_code="885002", source="ths")
    assert rows == []


def test_seed_missing_columns_raises_value_error(fresh_db, tmp_path):
    """缺必需列 → ValueError(被 seed_all_from_backup_dir 包成 log error, 不致命)."""
    csv_path = tmp_path / "stock_board_ths.csv"
    csv_path.write_text(
        "code,name,board_type,subtype,source,updated_at\n"  # missing platecode
        "885001,煤炭,industry,同花顺行业,ths,2026-07-12 17:30:00\n",
        encoding="utf-8-sig",
    )

    with pytest.raises(ValueError, match="missing required columns"):
        board_csv.seed_stock_board_from_csv("ths", csv_path)

    # seed_all_from_backup_dir should swallow the ValueError (log error + skip)
    backup_dir = tmp_path / "backup"
    backup_dir.mkdir()
    (backup_dir / "stock_board_ths.csv").write_text(
        csv_path.read_text(encoding="utf-8-sig"),
        encoding="utf-8-sig",
    )
    results = board_csv.seed_all_from_backup_dir(backup_dir)
    # ths board skipped due to schema error; nothing else to load
    assert "stock_board_ths" not in results


def test_seed_all_from_backup_dir_missing_dir(tmp_path, caplog):
    """backup_dir 不存在 → 返回空 dict, log warning."""
    missing = tmp_path / "does_not_exist"
    with caplog.at_level(
        logging.WARNING,
        logger="stock_data.data_provider.persistence.board_csv",
    ):
        results = board_csv.seed_all_from_backup_dir(missing)
    assert results == {}
    assert any("does not exist" in r.message for r in caplog.records)


def test_seed_all_from_backup_dir_missing_files(tmp_path, caplog):
    """目录存在但 3 个文件全缺 → 每个都 warning, 返回空 dict."""
    empty_dir = tmp_path / "empty_backup"
    empty_dir.mkdir()
    with caplog.at_level(
        logging.WARNING,
        logger="stock_data.data_provider.persistence.board_csv",
    ):
        results = board_csv.seed_all_from_backup_dir(empty_dir)
    assert results == {}
    not_found_warnings = [r for r in caplog.records if "not found" in r.message]
    assert len(not_found_warnings) == 3


def test_seed_all_from_backup_dir_partial_files(fresh_db, tmp_path):
    """只有 ths board 在 → 返回 {'stock_board_ths': N}, 其余 key 不在 dict 里.

    关键: missing entries are absent (NOT present-with-zero) — spec §5.2.5
    """
    backup_dir = tmp_path / "partial_backup"
    backup_dir.mkdir()
    (backup_dir / "stock_board_ths.csv").write_text(
        "code,name,board_type,subtype,source,platecode,updated_at\n"
        "885001,煤炭,industry,同花顺行业,ths,881001,2026-07-12 17:30:00\n",
        encoding="utf-8-sig",
    )
    # membership + eastmoney files intentionally absent

    results = board_csv.seed_all_from_backup_dir(backup_dir)
    assert results == {"stock_board_ths": 1}
    # Explicitly assert the other two keys are absent (not present-with-zero)
    assert "stock_board_membership_ths" not in results
    assert "stock_board_eastmoney" not in results


def test_seed_idempotent_re_run(fresh_db, tmp_path):
    """同 CSV 跑两次 → 行数不变 (INSERT OR REPLACE)."""
    csv_path = tmp_path / "stock_board_ths.csv"
    csv_path.write_text(
        "code,name,board_type,subtype,source,platecode,updated_at\n"
        "885001,煤炭,industry,同花顺行业,ths,881001,2026-07-12 17:30:00\n"
        "885002,白酒,concept,同花顺概念,ths,885002,2026-07-12 17:30:00\n",
        encoding="utf-8-sig",
    )

    n1 = board_csv.seed_stock_board_from_csv("ths", csv_path)
    rows_after_first = board_mod._read_boards_from_db("industry", "ths")
    rows_after_first += board_mod._read_boards_from_db("concept", "ths")
    first_count = len(rows_after_first)

    n2 = board_csv.seed_stock_board_from_csv("ths", csv_path)
    rows_after_second = board_mod._read_boards_from_db("industry", "ths")
    rows_after_second += board_mod._read_boards_from_db("concept", "ths")
    second_count = len(rows_after_second)

    assert n1 == 2 and n2 == 2
    assert first_count == second_count == 2
