"""Post-split acceptance invariants (spec §13/§15).

Assertions are invariants, not row counts, so they survive upstream drift.
The one exception is the seeded-DB shape check, which exists precisely to
catch a mis-split artifact.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from stock_data.data_provider.persistence import board as board_mod
from stock_data.data_provider.persistence import board_csv
from stock_data.data_provider.persistence import db as db_mod

BACKUP = Path(__file__).resolve().parents[1] / "stock_data" / "stock_data_backup"
ZZ_PREFIXES = ("801", "803", "710", "883")


@pytest.fixture(scope="module")
def seeded_db(tmp_path_factory):
    """Seed a throwaway DB once for the module, then put globals back.

    Module scope is deliberate (115k membership rows are slow to re-seed),
    which means ``monkeypatch`` is unavailable. So the env var, the memoised
    ``db._db_path`` / ``db._conn``, and ``board_mod._schema_initialized_paths``
    are saved and restored BY HAND — otherwise every later test in the session
    re-resolves ``get_db_path()`` to this temp file and the suite order starts
    mattering.
    """
    import os

    path = tmp_path_factory.mktemp("acceptance") / "acc.db"
    saved_env = os.environ.get("STOCK_CACHE_DB_PATH")
    saved_db_path = db_mod._db_path
    saved_conn = db_mod._conn
    saved_schema = board_mod._schema_initialized_paths

    os.environ["STOCK_CACHE_DB_PATH"] = str(path)
    db_mod._db_path = None
    db_mod._conn = None
    board_mod._schema_initialized_paths = set()
    try:
        board_mod.init_schema()
        board_csv.seed_all_from_backup_dir(BACKUP)
        yield
    finally:
        temp_conn = db_mod._conn
        if temp_conn is not None and temp_conn is not saved_conn:
            temp_conn.close()
        db_mod._conn = saved_conn
        db_mod._db_path = saved_db_path
        board_mod._schema_initialized_paths = saved_schema
        if saved_env is None:
            os.environ.pop("STOCK_CACHE_DB_PATH", None)
        else:
            os.environ["STOCK_CACHE_DB_PATH"] = saved_env


class TestInvariants:
    def test_no_zzshare_code_is_labelled_ths(self, seeded_db):
        rows = board_mod.get_connection().execute(
            "SELECT code FROM stock_board WHERE source='ths'"
        ).fetchall()
        offenders = [r["code"] for r in rows if r["code"][:3] in ZZ_PREFIXES]
        assert offenders == []

    def test_no_ths_code_is_labelled_zzshare(self, seeded_db):
        rows = board_mod.get_connection().execute(
            "SELECT code FROM stock_board WHERE source='zzshare'"
        ).fetchall()
        offenders = [r["code"] for r in rows if r["code"][:3] not in ZZ_PREFIXES]
        assert offenders == []

    def test_ths_cid_is_null_or_a_real_cid(self, seeded_db):
        """spec §4 rule 6: non-NULL ths_cid must be 3xxxxx or 881xxx.

        This is the invariant the 2026-09-11 CSV split exists to satisfy —
        without nulling the 110 legacy `cid == code == 885/886` rows it fails.
        """
        rows = board_mod.get_connection().execute(
            "SELECT code, cid FROM stock_board WHERE cid IS NOT NULL"
        ).fetchall()
        assert rows, "seeded ths rows must carry cids"
        for r in rows:
            assert r["cid"][:1] == "3" or r["cid"].startswith("881"), dict(r)

    def test_no_zzshare_row_carries_a_ths_cid(self, seeded_db):
        rows = board_mod.get_connection().execute(
            "SELECT code FROM stock_board WHERE source='zzshare' AND cid IS NOT NULL"
        ).fetchall()
        assert rows == [], f"zzshare rows carry a THS cid: {[dict(r) for r in rows[:5]]}"

    def test_advertised_cids_agree_with_the_id_map(self, seeded_db):
        """Every ths row carrying a cid must agree with ths_board_id_map.

        The real cross-artifact invariant: it ties the board table (seeded
        from stock_board_ths.csv) to the map table (seeded from
        ths_board_id_map.csv). Both come from the same source file, so a
        disagreement means one of the two loaders or the split is wrong.

        Verified on the split artifacts 2026-09-11: all 479 ths rows with a
        non-NULL cid satisfy `resolve_ths_platecode(cid) == code`, and all
        104 industry rows are identity (cid == code == 881xxx).

        NOTE: an earlier draft of this test ended in
        `assert all(… or True for c in unresolved)` — a tautology that
        asserts nothing. Do not reintroduce that shape.
        """
        rows = board_mod.get_connection().execute(
            "SELECT code, cid FROM stock_board WHERE source='ths' AND cid IS NOT NULL"
        ).fetchall()
        mismatched = [
            (r["code"], r["cid"], board_mod.resolve_ths_platecode(r["cid"]))
            for r in rows
            if board_mod.resolve_ths_platecode(r["cid"]) != r["code"]
        ]
        assert mismatched == [], f"cid/board_code disagree with the map: {mismatched[:5]}"

    def test_no_ths_board_code_is_a_bare_cid(self, seeded_db):
        """spec §4 rule 2: a cid must never be written into board_code.

        (881xxx industry codes are exempt — there cid == code by design.)
        """
        rows = board_mod.get_connection().execute(
            "SELECT code FROM stock_board WHERE source='ths'"
        ).fetchall()
        offenders = [
            r["code"] for r in rows if r["code"].startswith("3") and not r["code"].startswith("881")
        ]
        assert offenders == [], f"bare cids leaked into board_code: {offenders}"

    def test_no_board_name_maps_to_two_codes_within_ths_or_zzshare(self, seeded_db):
        """Scoped to the two sources this split governs.

        Upstream EastMoney genuinely has two distinct boards sharing one
        Chinese name (`跨境电商` = BK1547 + BK1115), so a global assertion
        would be wrong — and deleting it entirely would lose the invariant
        that actually matters here, which is that the old by-name merge can
        no longer reintroduce a name→multi-code group inside ths.
        """
        rows = board_mod.get_connection().execute(
            "SELECT source, name, COUNT(DISTINCT code) n FROM stock_board "
            "WHERE source IN ('ths', 'zzshare') "
            "GROUP BY source, name HAVING n > 1"
        ).fetchall()
        assert rows == [], f"duplicate board names within a source: {[dict(r) for r in rows[:5]]}"

    def test_membership_sources_are_all_known(self, seeded_db):
        rows = board_mod.get_connection().execute(
            "SELECT DISTINCT source FROM stock_board_membership"
        ).fetchall()
        assert {r["source"] for r in rows} <= {"ths", "zzshare", "eastmoney", "zhitu"}

    def test_membership_seed_is_present(self, seeded_db):
        """The full 115k zzshare membership must survive the seed."""
        n = board_mod.get_connection().execute(
            "SELECT COUNT(*) n FROM stock_board_membership WHERE source='zzshare'"
        ).fetchone()["n"]
        assert n == 115081, n

    def test_no_ths_membership_rows_from_the_seed(self, seeded_db):
        """The legacy file was zzshare data end to end; seeding any of it as
        ths is exactly the mislabelling this split removes."""
        n = board_mod.get_connection().execute(
            "SELECT COUNT(*) n FROM stock_board_membership WHERE source='ths'"
        ).fetchone()["n"]
        assert n == 0, n


class TestOmittedSourceAggregate:
    def test_default_stock_boards_includes_zzshare(self, seeded_db):
        from stock_data.api.routes import boards as routes_mod

        assert "zzshare" in routes_mod._parse_stock_boards_source_csv(None)
