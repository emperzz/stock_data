"""Tests for the ths_board_id_map CSV seed path."""

from __future__ import annotations

import csv
from pathlib import Path

import pytest

from stock_data.data_provider.persistence import board as board_mod
from stock_data.data_provider.persistence import board_csv
from stock_data.data_provider.persistence import db as db_mod

REPO_CSV = (
    Path(__file__).resolve().parents[1]
    / "stock_data"
    / "stock_data_backup"
    / "ths_board_id_map.csv"
)


@pytest.fixture
def fresh_db(tmp_path, monkeypatch):
    monkeypatch.setattr(db_mod, "_db_path", None)
    monkeypatch.setattr(db_mod, "_conn", None)
    monkeypatch.setattr(board_mod, "_schema_initialized_paths", set())
    monkeypatch.setenv("STOCK_CACHE_DB_PATH", str(tmp_path / "test.db"))
    board_mod.init_schema()
    yield


def _write_csv(path: Path, rows: list[tuple[str, str, str, str]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["cid", "platecode", "name", "board_type"])
        w.writerows(rows)


class TestCommittedArtifact:
    """Guards the repo-committed CSV itself, not just the loader."""

    def test_file_exists_and_has_required_columns(self):
        assert REPO_CSV.exists()
        with REPO_CSV.open(encoding="utf-8-sig") as f:
            header = next(csv.reader(f))
        assert set(header) >= {"cid", "platecode", "name", "board_type"}

    def test_no_zzshare_cid_leaked_in(self):
        with REPO_CSV.open(encoding="utf-8-sig") as f:
            bad = [
                r["cid"]
                for r in csv.DictReader(f)
                if not (r["cid"][:1] == "3" or r["cid"].startswith("881"))
            ]
        assert bad == [], f"non-THS cid rows leaked into the seed: {bad[:5]}"

    def test_contains_live_verified_pair(self):
        """Probed 2026-09-11: /gn/ gnSection entry 358 + /gn/detail/code/309121/."""
        with REPO_CSV.open(encoding="utf-8-sig") as f:
            m = {r["cid"]: r["platecode"] for r in csv.DictReader(f)}
        assert m.get("309121") == "886071"
        assert m.get("300188") == "885333"


class TestSeedLoader:
    def test_seeds_mappings(self, fresh_db, tmp_path):
        p = tmp_path / "m.csv"
        _write_csv(p, [("309121", "886071", "AI PC", "concept")])
        assert board_csv.seed_ths_board_id_map_from_csv(p) == 1
        assert board_mod.resolve_ths_platecode("309121") == "886071"

    def test_skips_zzshare_cid_rows(self, fresh_db, tmp_path):
        p = tmp_path / "m.csv"
        _write_csv(
            p,
            [
                ("710002", "710002", "DeFi", "concept"),
                ("309121", "886071", "AI PC", "concept"),
            ],
        )
        assert board_csv.seed_ths_board_id_map_from_csv(p) == 1
        assert board_mod.resolve_ths_platecode("710002") is None

    def test_missing_file_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            board_csv.seed_ths_board_id_map_from_csv(tmp_path / "nope.csv")

    def test_missing_column_raises(self, fresh_db, tmp_path):
        p = tmp_path / "bad.csv"
        p.write_text("cid,name\n309121,AI PC\n", encoding="utf-8")
        with pytest.raises(ValueError, match="missing required columns"):
            board_csv.seed_ths_board_id_map_from_csv(p)


class TestSeedAllOrdering:
    def test_id_map_seeded_before_board_csv(self, fresh_db, tmp_path, monkeypatch):
        """The map must be loaded first — sidebar resolution depends on it."""
        calls: list[str] = []
        monkeypatch.setattr(
            board_csv,
            "seed_ths_board_id_map_from_csv",
            lambda p: calls.append("id_map") or 1,
            raising=True,
        )
        monkeypatch.setattr(
            board_csv,
            "seed_stock_board_from_csv",
            lambda source, p: calls.append(f"board:{source}") or 1,
            raising=True,
        )
        monkeypatch.setattr(
            board_csv, "seed_membership_from_csv", lambda p: calls.append("membership") or 1
        )
        for name in (
            "ths_board_id_map.csv",
            "stock_board_ths.csv",
            "stock_board_eastmoney.csv",
            "stock_board_membership_ths.csv",
        ):
            (tmp_path / name).write_text("x", encoding="utf-8")

        results = board_csv.seed_all_from_backup_dir(tmp_path)

        assert calls[0] == "id_map", f"id_map must be first, got {calls}"
        assert results["ths_board_id_map"] == 1

    def test_missing_id_map_is_non_fatal(self, fresh_db, tmp_path, caplog):
        results = board_csv.seed_all_from_backup_dir(tmp_path)
        assert "ths_board_id_map" not in results
