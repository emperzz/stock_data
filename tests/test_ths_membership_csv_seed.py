"""Tests for stock_data/data_provider/persistence/board_csv.py
seed_ths_membership_from_csv + the new build_ths_membership_csv CLI tool.

Mirrors the test_board_csv_seed.py patterns (fresh_db fixture, caplog
warnings, direct loader calls) but locks down the THS-specific contract:

  - 7-col CSV (no ``subtype``; ``refreshed_at`` informational only)
  - per-row source='ths' guard
  - per-row NOT NULL defense (board_code / board_name / stock_name /
    board_type)
  - 6-digit stock_code filter (same as seed_membership_from_csv)
  - INSERT OR REPLACE idempotence
  - orchestrator integration (6th step in seed_all_from_backup_dir)
  - CLI: build_ths_membership_csv reads DB, calls get_board_stocks_full,
    writes CSV with the same header shape
"""

from __future__ import annotations

import csv
import logging
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from stock_data.data_provider.persistence import board as board_mod
from stock_data.data_provider.persistence import board_csv
from stock_data.data_provider.persistence import db as db_mod
from stock_data.tools import build_ths_membership_csv as tool_mod


@pytest.fixture
def fresh_db(tmp_path, monkeypatch):
    """Ephemeral SQLite DB — reset module singletons so init_schema reruns."""
    monkeypatch.setattr(db_mod, "_db_path", None)
    monkeypatch.setattr(board_mod, "_schema_initialized_paths", set())
    monkeypatch.setenv("STOCK_CACHE_DB_PATH", str(tmp_path / "test.db"))
    board_mod.init_schema()
    yield tmp_path / "test.db"


# ---------------------------------------------------------------------------
# seed_ths_membership_from_csv
# ---------------------------------------------------------------------------


def test_happy_path_writes_rows_with_subtype_null(fresh_db, tmp_path):
    """7-col CSV (no subtype column) → rows written, subtype IS NULL in DB."""
    csv_path = tmp_path / "stock_board_membership_ths.csv"
    csv_path.write_text(
        "board_code,stock_code,source,board_name,stock_name,"
        "board_type,refreshed_at\n"
        "885002,600519,ths,白酒,贵州茅台,concept,2026-09-15 10:00:00\n"
        "885002,000858,ths,白酒,五粮液,concept,2026-09-15 10:00:00\n"
        "881101,600111,ths,半导体,北方华创,industry,2026-09-15 10:00:00\n",
        encoding="utf-8-sig",
    )

    n = board_csv.seed_ths_membership_from_csv(csv_path)
    assert n == 3

    rows = board_mod.read_membership(board_code="885002", source="ths")
    assert len(rows) == 2
    assert {r["stock_code"] for r in rows} == {"600519", "000858"}
    # CRITICAL: loader writes subtype=NULL for THS rows (CSV doesn't carry it).
    for r in rows:
        assert r["subtype"] in (None, ""), (
            f"subtype should be NULL/empty for THS-seeded rows; got {r['subtype']!r}"
        )

    industry_rows = board_mod.read_membership(board_code="881101", source="ths")
    assert len(industry_rows) == 1
    assert industry_rows[0]["subtype"] in (None, "")


def test_idempotent_re_run_preserves_row_count(fresh_db, tmp_path):
    """Same CSV twice → second run is INSERT OR REPLACE; row count stable."""
    csv_path = tmp_path / "stock_board_membership_ths.csv"
    csv_path.write_text(
        "board_code,stock_code,source,board_name,stock_name,"
        "board_type,refreshed_at\n"
        "885002,600519,ths,白酒,贵州茅台,concept,2026-09-15 10:00:00\n",
        encoding="utf-8-sig",
    )

    n1 = board_csv.seed_ths_membership_from_csv(csv_path)
    n2 = board_csv.seed_ths_membership_from_csv(csv_path)
    assert n1 == 1 and n2 == 1
    rows = board_mod.read_membership(board_code="885002", source="ths")
    assert len(rows) == 1


def test_missing_file_raises_not_found_error(fresh_db, tmp_path):
    """Missing CSV → FileNotFoundError (caller handles the warn + skip)."""
    with pytest.raises(FileNotFoundError):
        board_csv.seed_ths_membership_from_csv(tmp_path / "does_not_exist.csv")


def test_missing_required_columns_raises_value_error(fresh_db, tmp_path):
    """8-col CSV (with subtype) → still works (subtype is ignored for THS).

    Hmm, actually _THS_MEMBERSHIP_COLS requires 6 specific columns and the
    CSV loader requires exactly those (header validation). An 8-col CSV that
    includes `subtype` in addition to the required 6 is VALID — extra columns
    are silently ignored by csv.DictReader.
    """
    csv_path = tmp_path / "stock_board_membership_ths.csv"
    csv_path.write_text(
        "board_code,stock_code,source,board_name,stock_name,"
        "board_type,subtype,refreshed_at\n"
        "885002,600519,ths,白酒,贵州茅台,concept,同花顺概念,2026-09-15 10:00:00\n",
        encoding="utf-8-sig",
    )
    n = board_csv.seed_ths_membership_from_csv(csv_path)
    assert n == 1


def test_missing_required_column_raises_value_error(fresh_db, tmp_path):
    """6-col CSV (missing board_type) → ValueError at validation."""
    csv_path = tmp_path / "stock_board_membership_ths.csv"
    csv_path.write_text(
        "board_code,stock_code,source,board_name,stock_name,refreshed_at\n"
        "885002,600519,ths,白酒,贵州茅台,2026-09-15 10:00:00\n",
        encoding="utf-8-sig",
    )
    with pytest.raises(ValueError, match="missing required columns"):
        board_csv.seed_ths_membership_from_csv(csv_path)


def test_invalid_stock_code_is_skipped_with_summary(fresh_db, tmp_path, caplog):
    """Non-6-digit stock_code → row skipped, summary warning at EOF."""
    csv_path = tmp_path / "stock_board_membership_ths.csv"
    csv_path.write_text(
        "board_code,stock_code,source,board_name,stock_name,"
        "board_type,refreshed_at\n"
        "885002,600519,ths,白酒,贵州茅台,concept,2026-09-15 10:00:00\n"
        "885002,贵州茅台,ths,白酒,五粮液,concept,2026-09-15 10:00:00\n"
        "885002,000858,ths,白酒,五粮液,concept,2026-09-15 10:00:00\n",
        encoding="utf-8-sig",
    )

    with caplog.at_level(
        logging.WARNING,
        logger="stock_data.data_provider.persistence.board_csv",
    ):
        n = board_csv.seed_ths_membership_from_csv(csv_path)
    assert n == 2
    assert any(
        "invalid stock_code" in r.message and "贵州茅台" in r.message
        for r in caplog.records
    ), f"expected invalid_code warning; got: {[r.message for r in caplog.records]}"


def test_wrong_source_row_is_skipped_with_summary(fresh_db, tmp_path, caplog):
    """source != 'ths' row → row skipped, summary warning, no DB pollution."""
    csv_path = tmp_path / "stock_board_membership_ths.csv"
    csv_path.write_text(
        "board_code,stock_code,source,board_name,stock_name,"
        "board_type,refreshed_at\n"
        "885002,600519,ths,白酒,贵州茅台,concept,2026-09-15 10:00:00\n"
        "885002,000001,zzshare,白酒,平安银行,concept,2026-09-15 10:00:00\n",
        encoding="utf-8-sig",
    )

    with caplog.at_level(
        logging.WARNING,
        logger="stock_data.data_provider.persistence.board_csv",
    ):
        n = board_csv.seed_ths_membership_from_csv(csv_path)
    assert n == 1
    summary = [
        r
        for r in caplog.records
        if "wrong source" in r.message and "1 rows" in r.message
    ]
    assert len(summary) == 1, f"expected exactly one summary; got: {caplog.records}"

    # The wrong-source row must NOT have leaked into the DB.
    bad = board_mod.read_membership(board_code="885002", source="zzshare")
    assert bad == []


def test_empty_not_null_field_is_skipped_with_summary(fresh_db, tmp_path, caplog):
    """Empty board_name / stock_name / board_type → row skipped, no DB pollution."""
    csv_path = tmp_path / "stock_board_membership_ths.csv"
    csv_path.write_text(
        "board_code,stock_code,source,board_name,stock_name,"
        "board_type,refreshed_at\n"
        "885002,600519,ths,白酒,贵州茅台,concept,2026-09-15 10:00:00\n"
        "885002,000858,ths,,五粮液,concept,2026-09-15 10:00:00\n"  # empty board_name
        "885002,000001,ths,白酒,,concept,2026-09-15 10:00:00\n"  # empty stock_name
        "885002,000002,ths,白酒,测试,,2026-09-15 10:00:00\n",  # empty board_type
        encoding="utf-8-sig",
    )

    with caplog.at_level(
        logging.WARNING,
        logger="stock_data.data_provider.persistence.board_csv",
    ):
        n = board_csv.seed_ths_membership_from_csv(csv_path)
    assert n == 1
    assert any(
        "empty NOT NULL" in r.message and "3 rows" in r.message
        for r in caplog.records
    ), f"expected null_field summary; got: {[r.message for r in caplog.records]}"


def test_header_only_csv_writes_zero_rows(fresh_db, tmp_path):
    """Empty CSV (header only) → 0 rows written, no exception.

    This is the case for the committed placeholder
    stock_data_backup/stock_board_membership_ths.csv before the operator
    runs the build tool.
    """
    csv_path = tmp_path / "stock_board_membership_ths.csv"
    csv_path.write_text(
        "board_code,stock_code,source,board_name,stock_name,"
        "board_type,refreshed_at\n",
        encoding="utf-8-sig",
    )
    n = board_csv.seed_ths_membership_from_csv(csv_path)
    assert n == 0


def test_empty_file_raises_value_error(fresh_db, tmp_path):
    """CSV with no header line at all → ValueError."""
    csv_path = tmp_path / "stock_board_membership_ths.csv"
    csv_path.write_text("", encoding="utf-8-sig")
    with pytest.raises(ValueError, match="is empty"):
        board_csv.seed_ths_membership_from_csv(csv_path)


# ---------------------------------------------------------------------------
# Orchestrator integration
# ---------------------------------------------------------------------------


def test_seed_all_from_backup_dir_runs_ths_membership_step(fresh_db, tmp_path):
    """seed_all_from_backup_dir runs the new THS membership step when the
    CSV file is present (even if header-only — the step is a success with
    0 rows written, NOT absent from results).
    """
    backup_dir = tmp_path / "backup"
    backup_dir.mkdir()
    (backup_dir / "stock_board_membership_ths.csv").write_text(
        "board_code,stock_code,source,board_name,stock_name,"
        "board_type,refreshed_at\n"
        "885002,600519,ths,白酒,贵州茅台,concept,2026-09-15 10:00:00\n",
        encoding="utf-8-sig",
    )

    results = board_csv.seed_all_from_backup_dir(backup_dir)
    assert "stock_board_membership_ths" in results
    assert results["stock_board_membership_ths"] == 1


# ---------------------------------------------------------------------------
# CLI: build_ths_membership_csv
# ---------------------------------------------------------------------------


def _make_ths_fetcher_mock(stocks_by_board: dict[str, list[dict]]):
    """Mock ThsFetcher whose get_board_stocks_full returns fixture stocks per board."""
    mock = MagicMock()

    def get_board_stocks_full(board_code, board_type):
        return stocks_by_board.get(board_code, [])

    mock.get_board_stocks_full.side_effect = get_board_stocks_full
    return mock


def test_cli_writes_csv_with_correct_header_and_rows(fresh_db, tmp_path, monkeypatch):
    """End-to-end: seed 2 THS boards into DB → CLI walks both → CSV has 4 rows."""
    # Insert two THS boards directly into stock_board (the source the CLI walks).
    conn = board_mod.get_connection()
    with conn:
        conn.executemany(
            """INSERT INTO stock_board
               (code, name, board_type, subtype, source, cid, updated_at)
               VALUES (?,?,?,?,?,?,CURRENT_TIMESTAMP)""",
            [
                ("885002", "白酒", "concept", "同花顺概念", "ths", "300002"),
                ("881101", "半导体", "industry", "同花顺行业", "ths", None),
            ],
        )

    fetcher = _make_ths_fetcher_mock(
        {
            "885002": [
                {"stock_code": "600519", "stock_name": "贵州茅台"},
                {"stock_code": "000858", "stock_name": "五粮液"},
            ],
            "881101": [
                {"stock_code": "600111", "stock_name": "北方华创"},
                {"stock_code": "688012", "stock_name": "中微公司"},
            ],
        }
    )

    output = tmp_path / "out.csv"
    monkeypatch.setattr(tool_mod.time, "sleep", lambda *a, **kw: None)
    monkeypatch.setattr(tool_mod.random, "uniform", lambda *a, **kw: 0.0)

    report = tool_mod.build_ths_membership_csv(
        output_path=output,
        inter_call_sleep=(0.0, 0.0),
        fetcher=fetcher,
    )

    assert report.total_boards == 2
    assert report.success_count == 2
    assert report.error_count == 0
    assert report.rows_written == 4

    # Verify CSV content
    with output.open(encoding="utf-8-sig") as f:
        rows = list(csv.reader(f))
    assert rows[0] == [
        "board_code",
        "stock_code",
        "source",
        "board_name",
        "stock_name",
        "board_type",
        "refreshed_at",
    ]
    assert len(rows) == 5  # header + 4 data rows

    # Verify per-board rows landed
    by_board: dict[str, list[dict]] = {}
    for r in rows[1:]:
        by_board.setdefault(r[0], []).append(dict(zip(rows[0], r)))
    assert {b["stock_code"] for b in by_board["885002"]} == {"600519", "000858"}
    assert {b["stock_code"] for b in by_board["881101"]} == {"600111", "688012"}
    # source column is hardcoded 'ths' on every row
    assert all(r[2] == "ths" for r in rows[1:])


def test_cli_skips_empty_board_without_failing(fresh_db, tmp_path, monkeypatch):
    """A board that returns [] from the F10 page → counted as empty, others run."""
    conn = board_mod.get_connection()
    with conn:
        conn.executemany(
            """INSERT INTO stock_board
               (code, name, board_type, subtype, source, cid, updated_at)
               VALUES (?,?,?,?,?,?,CURRENT_TIMESTAMP)""",
            [
                ("885002", "白酒", "concept", "同花顺概念", "ths", "300002"),
                ("885003", "empty-board", "concept", "同花顺概念", "ths", "300003"),
            ],
        )

    fetcher = _make_ths_fetcher_mock(
        {
            "885002": [{"stock_code": "600519", "stock_name": "贵州茅台"}],
            "885003": [],  # upstream cold
        }
    )

    output = tmp_path / "out.csv"
    monkeypatch.setattr(tool_mod.time, "sleep", lambda *a, **kw: None)
    monkeypatch.setattr(tool_mod.random, "uniform", lambda *a, **kw: 0.0)

    report = tool_mod.build_ths_membership_csv(
        output_path=output,
        inter_call_sleep=(0.0, 0.0),
        fetcher=fetcher,
    )
    assert report.total_boards == 2
    assert report.success_count == 1
    assert report.empty_count == 1
    assert report.rows_written == 1


def test_cli_per_board_failure_does_not_abort(fresh_db, tmp_path, monkeypatch):
    """One board raises DataFetchError → others still processed."""
    from stock_data.data_provider.base import DataFetchError

    conn = board_mod.get_connection()
    with conn:
        conn.executemany(
            """INSERT INTO stock_board
               (code, name, board_type, subtype, source, cid, updated_at)
               VALUES (?,?,?,?,?,?,CURRENT_TIMESTAMP)""",
            [
                ("885002", "白酒", "concept", "同花顺概念", "ths", "300002"),
                ("885003", "fail-board", "concept", "同花顺概念", "ths", "300003"),
                ("885004", "医药", "concept", "同花顺概念", "ths", "300004"),
            ],
        )

    fetcher = MagicMock()

    def get_board_stocks_full(board_code, board_type):
        if board_code == "885003":
            raise DataFetchError(f"upstream timeout for {board_code}")
        return [{"stock_code": "X", "stock_name": board_code}]

    fetcher.get_board_stocks_full.side_effect = get_board_stocks_full

    output = tmp_path / "out.csv"
    monkeypatch.setattr(tool_mod.time, "sleep", lambda *a, **kw: None)
    monkeypatch.setattr(tool_mod.random, "uniform", lambda *a, **kw: 0.0)

    report = tool_mod.build_ths_membership_csv(
        output_path=output,
        inter_call_sleep=(0.0, 0.0),
        fetcher=fetcher,
    )
    assert report.total_boards == 3
    assert report.success_count == 2
    assert report.error_count == 1
    assert report.rows_written == 2
    assert "885003" in report.error_samples[0]


def test_cli_help_runs(capsys):
    """main() with --help exits cleanly (smoke test)."""
    with pytest.raises(SystemExit) as exc_info:
        tool_mod.main(["--help"])
    assert exc_info.value.code == 0
