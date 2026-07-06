"""Tests for build_membership_index CLI."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from stock_data.data_provider.persistence import board as board_mod
from stock_data.data_provider.persistence import db as db_mod
from stock_data.tools import build_membership_index as cli_mod


@pytest.fixture
def fresh_db(tmp_path, monkeypatch):
    monkeypatch.setattr(db_mod, "_db_path", None)
    monkeypatch.setattr(db_mod, "_conn", None)
    monkeypatch.setattr(board_mod, "_schema_initialized_paths", set())
    monkeypatch.setenv("STOCK_CACHE_DB_PATH", str(tmp_path / "test.db"))
    board_mod.init_schema()
    yield tmp_path / "test.db"


def _make_manager_mock(boards_per_source: dict[str, list[str]]):
    """Mock manager whose get_all_boards returns a list of board_codes per source."""
    mock = MagicMock()

    def get_all_boards(source, board_type, subtype, include_quote):
        return (
            [
                {
                    "code": code,
                    "name": f"Board-{code}",
                    "type": board_type,
                    "subtype": subtype or board_type,
                }
                for code in boards_per_source.get(source, [])
            ],
            source,
        )

    def get_board_stocks(board_code, source, include_quote):
        return (
            [{"stock_code": f"S{i}", "stock_name": f"Stock-{i}"} for i in range(3)],
            source,
        )

    mock.get_all_boards.side_effect = get_all_boards
    mock.get_board_stocks.side_effect = get_board_stocks
    return mock


def test_build_one_source_populates_membership(fresh_db, monkeypatch):
    """Single source: enumerate boards, fetch stocks, upsert to membership."""
    mock = _make_manager_mock({"eastmoney": ["BK1", "BK2", "BK3"]})
    # Patch time.sleep so test runs fast
    monkeypatch.setattr(cli_mod.time, "sleep", lambda *a, **kw: None)
    monkeypatch.setattr(cli_mod.random, "uniform", lambda *a: 0.0)

    reports = cli_mod.build_membership_index(
        source="eastmoney",
        board_type="concept",
        manager=mock,
    )
    assert len(reports) == 1
    report = reports[0]
    assert report.source == "eastmoney"
    assert report.total_boards == 3
    assert report.success_count == 3
    assert report.error_count == 0
    # Verify membership has rows for all 3 boards × 3 stocks
    rows = []
    for bk in ("BK1", "BK2", "BK3"):
        rows.extend(board_mod.read_membership(board_code=bk, source="eastmoney"))
    assert len(rows) == 9


def test_per_board_failure_does_not_abort_build(fresh_db, monkeypatch):
    """Single board failure: logged, counted, others still processed."""
    mock = MagicMock()
    mock.get_all_boards.return_value = (
        [
            {"code": "BK_OK1", "name": "OK1", "board_type": "concept", "subtype": "concept"},
            {"code": "BK_FAIL", "name": "FAIL", "board_type": "concept", "subtype": "concept"},
            {"code": "BK_OK2", "name": "OK2", "board_type": "concept", "subtype": "concept"},
        ],
        "eastmoney",
    )

    def get_board_stocks(board_code, source, include_quote):
        if board_code == "BK_FAIL":
            raise RuntimeError("upstream timeout")
        return ([{"stock_code": "X", "stock_name": "X"}], source)

    mock.get_board_stocks.side_effect = get_board_stocks
    monkeypatch.setattr(cli_mod.time, "sleep", lambda *a, **kw: None)
    monkeypatch.setattr(cli_mod.random, "uniform", lambda *a: 0.0)

    reports = cli_mod.build_membership_index(
        source="eastmoney",
        board_type="concept",
        manager=mock,
    )
    assert len(reports) == 1
    report = reports[0]
    assert report.total_boards == 3
    assert report.success_count == 2
    assert report.error_count == 1
    assert "BK_FAIL" in report.error_samples[0]


def test_all_sources_single_call(fresh_db, monkeypatch):
    """source=None should iterate all VALID_SOURCES and return one report per source.

    `ths` is in VALID_SOURCES but has no `get_all_boards` (cold-fill only),
    so it walks 0 boards — a zero-board report is still expected.
    """
    mock = _make_manager_mock(
        {
            "eastmoney": ["BK1"],
            "zhitu": ["sw1"],
            "zzshare": ["th1"],
            # 'ths' is not in the mock: 0 boards → 0 success_count.
        }
    )
    monkeypatch.setattr(cli_mod.time, "sleep", lambda *a, **kw: None)
    monkeypatch.setattr(cli_mod.random, "uniform", lambda *a: 0.0)

    reports = cli_mod.build_membership_index(
        source=None,  # the production multi-source path
        board_type="concept",
        manager=mock,
    )
    assert {r.source for r in reports} == set(cli_mod.VALID_SOURCES)
    # eastmoney/zhitu/zzshare each have 1 board → 1 success; ths has 0.
    expected_success = {"eastmoney": 1, "zhitu": 1, "zzshare": 1, "ths": 0}
    for r in reports:
        assert r.success_count == expected_success[r.source]
    # 3 sources with 1 board × 3 stocks (ths contributes 0 rows).
    total_rows = []
    for src in ("eastmoney", "zhitu", "zzshare"):
        total_rows.extend(board_mod.read_membership(source=src, stock_code="S0"))
    assert len(total_rows) == 3


def test_cross_source_parallelism(fresh_db, monkeypatch):
    """When source=None, all VALID_SOURCES must run on distinct worker threads."""
    import threading

    monkeypatch.setattr(cli_mod.time, "sleep", lambda *a, **kw: None)
    monkeypatch.setattr(cli_mod.random, "uniform", lambda *a: 0.0)

    # Spy on _build_one_source to record which thread each source ran on.
    # Must happen before _run_one captures the symbol; rebind on the module.
    thread_ids: dict[str, int] = {}
    real_build = cli_mod._build_one_source

    def spy(source, types, inter_call_sleep, on_progress, manager):
        thread_ids[source] = threading.get_ident()
        return real_build(
            source=source,
            types=types,
            inter_call_sleep=inter_call_sleep,
            on_progress=on_progress,
            manager=manager,
        )

    monkeypatch.setattr(cli_mod, "_build_one_source", spy)

    mock = _make_manager_mock({"eastmoney": ["BK1"], "zhitu": ["sw1"], "zzshare": ["th1"]})
    reports = cli_mod.build_membership_index(source=None, manager=mock)

    assert len(reports) == len(cli_mod.VALID_SOURCES)
    assert set(thread_ids) == set(cli_mod.VALID_SOURCES)
    # One worker thread per source (the main thread is excluded because
    # sources > 1 dispatches via ThreadPoolExecutor).
    assert len(set(thread_ids.values())) == len(cli_mod.VALID_SOURCES)
    main_tid = threading.get_ident()
    assert all(tid != main_tid for tid in thread_ids.values()), (
        "Each source must run on its own worker thread, not the main thread"
    )


def test_single_source_runs_inline(fresh_db, monkeypatch):
    """When --source=X is explicit, walk inline (no thread pool)."""
    import threading

    monkeypatch.setattr(cli_mod.time, "sleep", lambda *a, **kw: None)
    monkeypatch.setattr(cli_mod.random, "uniform", lambda *a: 0.0)

    thread_ids: dict[str, int] = {}
    real_build = cli_mod._build_one_source

    def spy(source, types, inter_call_sleep, on_progress, manager):
        thread_ids[source] = threading.get_ident()
        return real_build(
            source=source,
            types=types,
            inter_call_sleep=inter_call_sleep,
            on_progress=on_progress,
            manager=manager,
        )

    monkeypatch.setattr(cli_mod, "_build_one_source", spy)

    mock = _make_manager_mock({"eastmoney": ["BK1", "BK2"]})
    reports = cli_mod.build_membership_index(source="eastmoney", manager=mock)

    assert len(reports) == 1
    # Single-source path runs inline on the main thread.
    assert thread_ids["eastmoney"] == threading.get_ident()


def test_cli_help_runs(capsys):
    """main() with --help exits cleanly (smoke test)."""
    with pytest.raises(SystemExit) as exc_info:
        cli_mod.main(["--help"])
    assert exc_info.value.code == 0  # argparse exits 0 on --help
