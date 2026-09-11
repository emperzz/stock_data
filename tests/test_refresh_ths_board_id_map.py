"""Tests for stock_data/tools/refresh_ths_board_id_map.py (offline, fake fetcher)."""

from __future__ import annotations

import csv
from pathlib import Path

from stock_data.tools import refresh_ths_board_id_map as tool

FIXTURES = Path(__file__).parent / "fixtures"
GN_INDEX = (FIXTURES / "ths_gn_index.html").read_text(encoding="utf-8")
DETAIL_309121 = (FIXTURES / "ths_gn_detail_309121.html").read_text(encoding="utf-8")


class FakeFetcher:
    """Stands in for ThsFetcher: serves the gn index + detail pages."""

    def __init__(self, detail_pages: dict[str, str] | None = None):
        self.detail_pages = detail_pages or {"309999": "<html>待定</html>"}
        self.requested: list[str] = []

    def _http_get_ths_board_index(self, url: str) -> str:
        self.requested.append(url)
        if url.endswith("/gn/"):
            return GN_INDEX
        for cid, html in self.detail_pages.items():
            if f"/gn/detail/code/{cid}/" in url:
                return html
        raise AssertionError(f"unexpected url {url}")


class TestDiffMaps:
    def test_reports_added_changed_removed(self):
        old = {"300001": "885001", "300002": "885002", "300003": "885003"}
        new = {"300001": "885001", "300002": "885999", "300004": "885004"}
        d = tool.diff_maps(old, new)
        assert d["added"] == ["300004"]
        assert d["changed"] == ["300002"]
        assert d["removed"] == ["300003"]

    def test_identical_maps_produce_empty_diff(self):
        m = {"300001": "885001"}
        d = tool.diff_maps(m, m)
        assert d == {"added": [], "changed": [], "removed": []}


class TestSnapshotGn:
    def test_extracts_pairs_and_sidebar_cids(self):
        snap = tool.snapshot_gn(FakeFetcher())
        assert snap["mapped"]["309121"] == "886071"
        assert snap["mapped"]["308614"] == "886056"
        assert set(snap["sidebar_cids"]) == {"308614", "309121", "309999"}
        assert snap["names"]["309999"] == "未收录概念"


class TestResolveUnmapped:
    def test_resolves_via_detail_page(self):
        f = FakeFetcher({"309999": DETAIL_309121.replace("886071", "886123")})
        snap = tool.snapshot_gn(f)
        added, failed = tool.resolve_unmapped(f, snap, sleep_s=0.0, limit=None, log=lambda *_: None)
        assert added["309999"] == "886123"
        assert failed == []

    def test_unparsable_detail_page_is_reported_not_guessed(self):
        f = FakeFetcher({"309999": "<html>没有代码</html>"})
        snap = tool.snapshot_gn(f)
        added, failed = tool.resolve_unmapped(f, snap, sleep_s=0.0, limit=None, log=lambda *_: None)
        assert added == {}
        assert failed == ["309999"]

    def test_limit_caps_detail_requests(self):
        f = FakeFetcher({"309999": DETAIL_309121.replace("886071", "886123")})
        snap = tool.snapshot_gn(f)
        tool.resolve_unmapped(f, snap, sleep_s=0.0, limit=0, log=lambda *_: None)
        assert f.requested == [tool.ThsFetcher._THS_CONCEPT_INDEX_URL]


class TestCsvRoundtrip:
    def test_write_then_read(self, tmp_path):
        p = tmp_path / "m.csv"
        rows = [
            {"cid": "309121", "platecode": "886071", "name": "AI PC", "board_type": "concept"},
            {"cid": "881121", "platecode": "881121", "name": "半导体", "board_type": "industry"},
        ]
        tool.write_map_csv(p, rows)
        back = tool.read_map_csv(p)
        assert back["309121"]["platecode"] == "886071"
        assert back["881121"]["name"] == "半导体"

    def test_read_missing_file_returns_empty(self, tmp_path):
        assert tool.read_map_csv(tmp_path / "nope.csv") == {}

    def test_written_csv_has_stable_column_order(self, tmp_path):
        p = tmp_path / "m.csv"
        tool.write_map_csv(
            p, [{"cid": "309121", "platecode": "886071", "name": "AI PC", "board_type": "concept"}]
        )
        with p.open(encoding="utf-8") as f:
            assert next(csv.reader(f)) == ["cid", "platecode", "name", "board_type"]


class TestMainDryRun:
    def test_dry_run_writes_nothing(self, tmp_path, monkeypatch):
        target = tmp_path / "m.csv"
        tool.write_map_csv(
            target, [{"cid": "300001", "platecode": "885001", "name": "旧", "board_type": "concept"}]
        )
        before = target.read_text(encoding="utf-8")

        monkeypatch.setattr(tool, "ThsFetcher", lambda: FakeFetcher())
        rc = tool.main(["--out", str(target), "--dry-run", "--sleep", "0"])

        assert rc == 0
        assert target.read_text(encoding="utf-8") == before

    def test_apply_merges_live_over_base(self, tmp_path, monkeypatch):
        target = tmp_path / "m.csv"
        tool.write_map_csv(
            target, [{"cid": "309121", "platecode": "885000", "name": "AI PC", "board_type": "concept"}]
        )

        monkeypatch.setattr(tool, "ThsFetcher", lambda: FakeFetcher())
        rc = tool.main(["--out", str(target), "--apply", "--sleep", "0", "--no-detail"])

        assert rc == 0
        assert tool.read_map_csv(target)["309121"]["platecode"] == "886071"
