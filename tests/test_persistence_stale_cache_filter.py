"""Tests for read-time defensive filter against stale cache rows.

Review 2026-07-06 finding #2: pre-fix EastMoneyFetcher writes stored
stock_code=Chinese name (from f14) in stock_board_membership. After
the 2026-07-05 f12/f14 swap fix, fresh writes are correct, but cached
rows are corrupt until calendar-day boundary or ?refresh=true.

Fix: at read time, skip rows whose stock_code is not a valid A-share
6-digit code. This neutralises stale rows regardless of when they were
written — robust against any future upstream reshuffle, not just this
specific bug.
"""

import pytest

from stock_data.data_provider.persistence import board as board_mod
from stock_data.data_provider.persistence import db as db_mod


@pytest.fixture(autouse=True)
def _clean_db(tmp_path, monkeypatch):
    """Use a tmp_path DB instead of the production stock_cache.db.

    Older fixtures in this file deleted rows from the real DB, which
    silently nuked user data whenever this test ran. Switch to a
    per-test tmp_path DB so tests cannot affect production state.
    """
    monkeypatch.setattr(db_mod, "_db_path", None)
    monkeypatch.setattr(db_mod, "_conn", None)
    board_mod._schema_initialized_paths = set()
    monkeypatch.setenv("STOCK_CACHE_DB_PATH", str(tmp_path / "test.db"))
    board_mod.init_schema()
    yield


def _insert_membership_row(
    board_code: str, source: str, stock_code: str, stock_name: str
) -> None:
    """Direct insert bypassing validators — simulates a stale cached row."""
    conn = board_mod.get_connection()
    conn.execute(
        "INSERT INTO stock_board_membership "
        "(board_code, source, stock_code, stock_name, board_name, board_type, subtype, refreshed_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (board_code, source, stock_code, stock_name, board_code, "concept", "concept", "2026-07-04 12:00:00"),
    )
    conn.commit()


def test_read_filters_out_chinese_name_stale_rows():
    """Pre-2026-07-05 eastmoney rows have stock_code=Chinese name (from f14).

    These rows must be silently skipped at read time — returning them
    as-is would emit corrupt BoardStockInfo (code='贵州茅台').
    """
    _insert_membership_row("BK0001", "eastmoney", "贵州茅台", "12345678901.0")  # pre-fix bug
    _insert_membership_row("BK0001", "eastmoney", "600519", "贵州茅台")  # valid row

    rows = board_mod._read_board_stocks_from_db("BK0001", "eastmoney")
    codes = [r["stock_code"] for r in rows]
    assert codes == ["600519"], (
        f"stale rows should be filtered; got {codes}"
    )


def test_read_keeps_valid_six_digit_codes():
    """All A-share 6-digit codes pass the filter (600xxx SH, 000xxx SZ, 300xxx SZ, 688xxx SH, 8xxxxx BJ)."""
    valid_codes = ["600519", "000001", "300750", "688981", "830799", "400001"]
    for code in valid_codes:
        _insert_membership_row("BK0001", "eastmoney", code, f"name-{code}")

    rows = board_mod._read_board_stocks_from_db("BK0001", "eastmoney")
    codes = sorted(r["stock_code"] for r in rows)
    assert codes == sorted(valid_codes)


def test_read_filters_out_various_corrupt_shapes():
    """Defence in depth: filter catches any non-6-digit stock_code.

    Catches:
      - Chinese names (pre-2026-07-05 eastmoney bug)
      - Float-looking strings (pre-fix f16 leak)
      - 7+ digit codes (some random non-A-share code)
      - Whitespace / punctuation
    """
    corrupt = [
        ("贵州茅台", "x"),       # Chinese name from f14
        ("12345678901.0", "y"), # numeric leak from f16 (pre-fix)
        ("12345678", "z"),      # 8 digits (too long)
        ("12345", "a"),         # 5 digits (too short)
        ("", "b"),              # empty
        ("600-519", "c"),       # punctuation
    ]
    for code, name in corrupt:
        _insert_membership_row("BK0001", "eastmoney", code, name)
    _insert_membership_row("BK0001", "eastmoney", "600519", "valid")

    rows = board_mod._read_board_stocks_from_db("BK0001", "eastmoney")
    assert len(rows) == 1
    assert rows[0]["stock_code"] == "600519"


def test_read_returns_empty_when_all_rows_corrupt():
    """All rows corrupt → empty list, not exception."""
    for code in ["贵州茅台", "abc", "12345", ""]:
        _insert_membership_row("BK0001", "eastmoney", code, "x")

    rows = board_mod._read_board_stocks_from_db("BK0001", "eastmoney")
    assert rows == []


def test_read_returns_empty_when_cache_empty():
    """No rows at all → empty list (regression check that filter doesn't break happy path)."""
    rows = board_mod._read_board_stocks_from_db("BK0001", "eastmoney")
    assert rows == []