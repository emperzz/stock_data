"""`?source=ths` must never reach zzshare, and vice versa (spec §2 D2).

Pre-split, `?source=ths` + include_quote=false had zzshare as its PRIMARY
fetcher and `?source=zzshare` was an alias of ths (spec §1.3). These tests
pin the strict-isolation contract so it cannot silently come back.
"""

from __future__ import annotations

import pytest

from stock_data.data_provider.persistence import board as board_mod
from stock_data.data_provider.persistence import db as db_mod


@pytest.fixture
def fresh_db(tmp_path, monkeypatch):
    monkeypatch.setattr(db_mod, "_db_path", None)
    monkeypatch.setattr(db_mod, "_conn", None)
    monkeypatch.setattr(board_mod, "_schema_initialized_paths", set())
    monkeypatch.setenv("STOCK_CACHE_DB_PATH", str(tmp_path / "test.db"))
    board_mod.init_schema()
    board_mod._refresh_tracker = board_mod.DailyRefreshTracker()
    yield


class _Spy:
    name = "spy"

    def __init__(self):
        self.calls: list[tuple[str, dict]] = []

    def get_all_boards(self, **kw):
        self.calls.append(("get_all_boards", kw))
        return [], self.name

    def get_board_stocks(self, board_code, **kw):
        self.calls.append(("get_board_stocks", {"board_code": board_code, **kw}))
        return [], self.name

    def get_board_stocks_full(self, board_code, **kw):
        self.calls.append(("get_board_stocks_full", {"board_code": board_code, **kw}))
        return [], self.name

    def get_realtime_quotes(self, market):
        return [], self.name


def _sources(calls) -> set[str]:
    return {c[1].get("source") for c in calls if c[1].get("source")}


def _seed(code: str, cid: str | None, board_type: str = "concept", source: str = "ths") -> None:
    with board_mod.get_connection() as conn:
        conn.execute(
            """INSERT OR REPLACE INTO stock_board
               (code, name, board_type, subtype, source, cid, updated_at)
               VALUES (?,?,?,?,?,?,CURRENT_TIMESTAMP)""",
            (code, "n", board_type, "sub", source, cid),
        )


class TestBoardListIsolation:
    def test_ths_board_list_never_asks_zzshare(self, fresh_db, monkeypatch):
        monkeypatch.setattr(board_mod, "get_cached_market_quotes", lambda m: None)
        spy = _Spy()
        board_mod.get_board_list("concept", source="ths", refresh=True, manager=spy)
        assert _sources(spy.calls) <= {"ths"}, spy.calls

    def test_zzshare_board_list_never_asks_ths(self, fresh_db, monkeypatch):
        monkeypatch.setattr(board_mod, "get_cached_market_quotes", lambda m: None)
        spy = _Spy()
        board_mod.get_board_list("concept", source="zzshare", refresh=True, manager=spy)
        assert _sources(spy.calls) <= {"zzshare"}, spy.calls


class TestBoardStocksIsolation:
    def test_ths_include_quote_false_never_asks_zzshare(self, fresh_db, monkeypatch):
        _seed("885333", "300188")
        monkeypatch.setattr(board_mod, "get_cached_market_quotes", lambda m: None)
        spy = _Spy()
        board_mod.get_board_stocks("885333", source="ths", include_quote=False, manager=spy)
        assert _sources(spy.calls) <= {"ths"}, spy.calls

    def test_ths_include_quote_true_never_asks_zzshare(self, fresh_db, monkeypatch):
        _seed("885333", "300188")
        monkeypatch.setattr(board_mod, "get_cached_market_quotes", lambda m: None)
        spy = _Spy()
        board_mod.get_board_stocks(
            "885333", source="ths", include_quote=True, manager=spy, top_n=50
        )
        assert _sources(spy.calls) <= {"ths"}, spy.calls

    def test_ths_include_quote_true_above_50_never_asks_zzshare(self, fresh_db, monkeypatch):
        """The F10 tier is THS-only too — no zzshare membership fill-in."""
        _seed("885333", "300188")
        monkeypatch.setattr(board_mod, "get_cached_market_quotes", lambda m: None)
        spy = _Spy()
        board_mod.get_board_stocks(
            "885333", source="ths", include_quote=True, manager=spy, top_n=200
        )
        assert _sources(spy.calls) <= {"ths"}, spy.calls

    def test_zzshare_request_never_asks_ths(self, fresh_db, monkeypatch):
        _seed("801001", None, source="zzshare")
        monkeypatch.setattr(board_mod, "get_cached_market_quotes", lambda m: None)
        spy = _Spy()
        board_mod.get_board_stocks("801001", source="zzshare", include_quote=False, manager=spy)
        assert _sources(spy.calls) <= {"zzshare"}, spy.calls


class TestNoCrossSourceFallbackOnFailure:
    def test_ths_failure_propagates_without_zzshare_fallback(self, fresh_db, monkeypatch):
        """THS failure must surface, not be masked by a zzshare leg (spec §2 D2)."""
        from stock_data.data_provider.base import DataFetchError

        monkeypatch.setattr(board_mod, "get_cached_market_quotes", lambda m: None)
        spy = _Spy()

        def boom(**kw):
            spy.calls.append(("get_all_boards", kw))
            raise DataFetchError("ths down")

        monkeypatch.setattr(spy, "get_all_boards", boom, raising=False)
        with pytest.raises(DataFetchError):
            board_mod.get_board_list("concept", source="ths", refresh=True, manager=spy)
        assert _sources(spy.calls) <= {"ths"}, spy.calls
