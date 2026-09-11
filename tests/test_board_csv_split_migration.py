"""The split CSV artifacts must be self-consistent and source-pure.

Guards the committed data files themselves (not just the loader): a
mis-split CSV is a data bug that no amount of loader correctness catches.
"""

from __future__ import annotations

import csv
from pathlib import Path

import pytest

from stock_data.data_provider.persistence import board as board_mod
from stock_data.data_provider.persistence import board_csv
from stock_data.data_provider.persistence import db as db_mod

BACKUP = Path(__file__).resolve().parents[1] / "stock_data" / "stock_data_backup"
ZZ_PREFIXES = ("801", "803", "710", "883")


def _rows(name: str) -> list[dict]:
    with (BACKUP / name).open(encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def _is_ths_cid(v: str) -> bool:
    return len(v) == 6 and v.isascii() and v.isdigit() and (
        v.startswith("3") or v.startswith("881")
    )


@pytest.fixture
def fresh_db(tmp_path, monkeypatch):
    monkeypatch.setattr(db_mod, "_db_path", None)
    monkeypatch.setattr(db_mod, "_conn", None)
    monkeypatch.setattr(board_mod, "_schema_initialized_paths", set())
    monkeypatch.setenv("STOCK_CACHE_DB_PATH", str(tmp_path / "test.db"))
    board_mod.init_schema()
    yield


class TestSourcePurity:
    def test_ths_board_csv_has_no_zzshare_codes(self):
        bad = [r["code"] for r in _rows("stock_board_ths.csv") if r["code"][:3] in ZZ_PREFIXES]
        assert bad == [], f"zzshare codes still in ths CSV: {bad[:5]}"

    def test_ths_board_csv_is_labelled_ths(self):
        assert {r["source"] for r in _rows("stock_board_ths.csv")} == {"ths"}

    def test_zzshare_board_csv_is_labelled_zzshare(self):
        assert {r["source"] for r in _rows("stock_board_zzshare.csv")} == {"zzshare"}

    def test_zzshare_board_csv_has_no_ths_cid(self):
        assert {r["cid"] for r in _rows("stock_board_zzshare.csv")} <= {""}

    def test_membership_csv_is_zzshare_labelled(self):
        """All 115,081 rows are zzshare data — the prefix is NOT a source marker.

        zzshare's own board space spans 885xxx/886xxx (plate_type 15 概念),
        881xxx (plate_type 14 行业) and 801xxx/803xxx/710xxx/883xxx
        (plate_type 17 题材), so a row's code prefix says nothing about which
        fetcher produced it. An earlier revision of this file split the
        membership CSV by prefix on the theory that 885/886/881 were THS; that
        was wrong — live zzshare returns those boards, matching the CSV at
        Jaccard 0.97-0.99 (verified 2026-09-11).
        """
        assert {r["source"] for r in _rows("stock_board_membership_zzshare.csv")} == {"zzshare"}

    def test_membership_rows_are_conserved(self):
        assert len(_rows("stock_board_membership_zzshare.csv")) == 115081

    def test_no_ths_membership_seed(self):
        """There is no THS membership data to seed — the file was all
        zzshare. ths-side membership accumulates from the F10 sweep
        (BOARD_BACKFILL_ON_STARTUP) and runtime lazy fill."""
        assert not (BACKUP / "stock_board_membership_ths.csv").exists()

    def test_membership_codes_span_every_zzshare_plate_type(self):
        """Pins the code-space fact the split got wrong.

        801/803/710/883 (题材) AND 885/886 (概念) AND 881 (行业) must all be
        present — if a future 'cleanup' assumed zzshare only serves
        801xxx-style codes, it would drop two thirds of the seed.
        """
        codes = {r["board_code"] for r in _rows("stock_board_membership_zzshare.csv")}
        for prefix, label in (("801", "题材 801xxx"), ("885", "概念 885xxx"),
                              ("886", "概念 886xxx"), ("881", "行业 881xxx")):
            assert any(c.startswith(prefix) for c in codes), f"missing {label}"

    def test_ths_board_csv_cid_column_is_only_real_cids(self):
        """spec §4 rule 6 + the 110-row legacy pollution (§3.1).

        Those 110 rows stay in the ths file (their `code` is 885/886), so if
        the split forgets to null their `cid`, this is where it shows.
        """
        bad = [
            r["cid"]
            for r in _rows("stock_board_ths.csv")
            if r["cid"] and not _is_ths_cid(r["cid"])
        ]
        assert bad == [], f"platecode-shaped cid survived the split: {bad[:5]}"

    def test_ths_board_csv_cid_nulled_count(self):
        """479 real cids + 109 blank == 588 (measured 2026-09-11).

        Blank = 15 rows already blank + 110 polluted rows nulled − 1 polluted
        row that disappeared in the 16-code de-duplication.
        """
        rows = _rows("stock_board_ths.csv")
        blank = sum(1 for r in rows if not r["cid"])
        real = sum(1 for r in rows if r["cid"])
        assert (real, blank) == (479, 109), f"got real={real} blank={blank}"

    def test_no_duplicate_board_codes_in_either_file(self):
        """The split must de-duplicate: the loader's INSERT OR REPLACE is
        last-wins, and for 885940 the last source row carried the polluted
        cid — letting the loader decide would silently lose cid 308791."""
        for name in ("stock_board_ths.csv", "stock_board_zzshare.csv"):
            codes = [r["code"] for r in _rows(name)]
            dups = sorted({c for c in codes if codes.count(c) > 1})
            assert dups == [], f"{name} still has duplicate codes: {dups[:5]}"

    def test_885940_keeps_its_real_cid(self):
        """The one code whose de-duplication choice is load-bearing."""
        by_code = {r["code"]: r for r in _rows("stock_board_ths.csv")}
        assert by_code["885940"]["cid"] == "308791"

    def test_row_counts_are_conserved(self):
        """797 source rows = 588 ths + 186 zzshare + 16 collapsed dup + 7 empty-code.

        Measured 2026-09-11 against the split source file. The 7 empty-code
        rows are junk the loader skips anyway; the 16 duplicate ths codes are
        collapsed BY THE SPLIT (deterministically, preferring a real cid)
        rather than by the loader's last-wins INSERT OR REPLACE.
        """
        ths = len(_rows("stock_board_ths.csv"))
        zz = len(_rows("stock_board_zzshare.csv"))
        assert ths == 588, f"ths row count drifted: {ths}"
        assert zz == 186, f"zzshare row count drifted: {zz}"
        assert ths + zz + 16 + 7 == 797, "the split must not drop or duplicate valid rows"


class TestSeedRoundTrip:
    def test_seed_all_populates_five_steps(self, fresh_db):
        results = board_csv.seed_all_from_backup_dir(BACKUP)
        assert results["ths_board_id_map"] > 0
        assert results["stock_board_ths"] == 588
        assert results["stock_board_zzshare"] == 186
        assert results["stock_board_eastmoney"] > 0
        assert results["stock_board_membership_zzshare"] == 115081
        assert "stock_board_membership_ths" not in results

    def test_no_zzshare_codes_under_ths_after_seed(self, fresh_db):
        board_csv.seed_all_from_backup_dir(BACKUP)
        conn = board_mod.get_connection()
        bad = conn.execute(
            "SELECT code FROM stock_board WHERE source='ths' "
            "AND (code LIKE '801%' OR code LIKE '803%' OR code LIKE '710%' OR code LIKE '883%')"
        ).fetchall()
        assert bad == []

    def test_no_ths_cid_on_zzshare_rows_after_seed(self, fresh_db):
        board_csv.seed_all_from_backup_dir(BACKUP)
        conn = board_mod.get_connection()
        bad = conn.execute(
            "SELECT code, cid FROM stock_board WHERE source='zzshare' AND cid IS NOT NULL"
        ).fetchall()
        assert bad == [], f"zzshare rows carry a THS cid: {[dict(r) for r in bad[:5]]}"

    def test_every_ths_cid_is_a_real_cid_after_seed(self, fresh_db):
        board_csv.seed_all_from_backup_dir(BACKUP)
        conn = board_mod.get_connection()
        rows = conn.execute(
            "SELECT code, cid FROM stock_board WHERE source='ths' AND cid IS NOT NULL"
        ).fetchall()
        assert rows, "seeded ths rows must carry cids"
        bad = [dict(r) for r in rows if not _is_ths_cid(r["cid"])]
        assert bad == [], f"non-cid values in ths_cid: {bad[:5]}"

    def test_orphan_membership_boards_are_bounded(self, fresh_db):
        """Membership references more boards than the board CSVs hold.

        Measured 2026-09-11: the zzshare membership covers 788 distinct
        board_codes while stock_board_zzshare.csv holds 186, leaving 602
        orphans. That is a *snapshot* gap, not a split bug — the board CSVs
        come from one day's `plates_rank`, the membership from a longer
        `plates_stocks` window. Querying an orphan still works (the
        fetchers take the code directly); only its metadata row is missing.

        Pinned so the number is visible if it drifts, and so nobody
        "fixes" it by deleting membership rows.
        """
        board_csv.seed_all_from_backup_dir(BACKUP)
        conn = board_mod.get_connection()
        orphans = conn.execute(
            """SELECT DISTINCT m.board_code FROM stock_board_membership m
               WHERE m.source='zzshare' AND NOT EXISTS (
                   SELECT 1 FROM stock_board b
                   WHERE b.source='zzshare' AND b.code = m.board_code)"""
        ).fetchall()
        assert len(orphans) <= 602, f"orphan growth: {[o['board_code'] for o in orphans[:10]]}"
