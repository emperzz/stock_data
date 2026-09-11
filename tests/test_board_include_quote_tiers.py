"""include_quote=true must never call zzshare, at any top_n (spec §8).

Two tiers, both THS-only:
  top_n <= 50  → AJAX (cid-addressed, hard-capped at 50 rows).
                 18/18 BoardStockInfo fields after the quote-cache union.
  top_n >  50  → F10 full membership + /stocks quote-cache union
                 (15/18 fields; change_speed / free_float_shares /
                  float_market_cap are structurally absent from F10 —
                  probed 2026-09-11: the F10 row template simply has no
                  such keys, and _enrich_rows_with_market_quote never
                  sets them either, so they stay None on this tier)
"""

from __future__ import annotations

import pytest

from stock_data.data_provider.core.types import UnifiedRealtimeQuote
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


def _seed_metadata() -> None:
    conn = board_mod.get_connection()
    with conn:
        conn.execute(
            """INSERT OR REPLACE INTO stock_board
               (code, name, board_type, subtype, source, cid, updated_at)
               VALUES ('885333','移动支付','concept','同花顺概念','ths','300188',
                       CURRENT_TIMESTAMP)"""
        )


def _quote(code: str, **kw) -> UnifiedRealtimeQuote:
    base = {
        "code": code,
        "name": "x",
        "price": 1.0,
        "change_pct": 1.0,
        "change_amount": 0.0,
        "volume": 100,
        "amount": 1000.0,
        "turnover_rate": 1.0,
        "volume_ratio": 1.0,
        "pe_ratio": 10.0,
        "open_price": 1.0,
        "high": 1.1,
        "low": 0.9,
        "pre_close": 1.0,
        "amplitude": 2.0,
    }
    base.update(kw)
    return UnifiedRealtimeQuote(**base)


class _Recorder:
    """Fake manager that records every call, so we can assert zzshare is never hit."""

    name = "recorder"

    def __init__(self, ajax_rows=None, f10_rows=None):
        self.ajax_rows = ajax_rows or []
        self.f10_rows = f10_rows or []
        self.calls: list[tuple[str, dict]] = []

    def get_board_stocks(self, board_code, **kw):
        self.calls.append(("get_board_stocks", {"board_code": board_code, **kw}))
        return list(self.ajax_rows), self.name

    def get_board_stocks_full(self, board_code, **kw):
        self.calls.append(("get_board_stocks_full", {"board_code": board_code, **kw}))
        return list(self.f10_rows), self.name

    def get_realtime_quotes(self, market):
        return [_quote("600519")], self.name


def _assert_no_zzshare(mgr: _Recorder) -> None:
    assert not any(c[1].get("source") == "zzshare" for c in mgr.calls), mgr.calls


class TestAjaxTierAtOrBelow50:
    def test_uses_ajax_and_never_zzshare(self, fresh_db, monkeypatch):
        _seed_metadata()
        monkeypatch.setattr(board_mod, "get_cached_market_quotes", lambda m: [_quote("600519")])
        mgr = _Recorder(
            ajax_rows=[{"stock_code": "600519", "stock_name": "贵州茅台", "price": 1800.0}]
        )
        stocks, _origin, effective, _reason, _trunc, _total = board_mod.get_board_stocks(
            "885333", source="ths", include_quote=True, manager=mgr, top_n=10
        )
        assert effective == "ths"
        _assert_no_zzshare(mgr)
        assert [c[0] for c in mgr.calls].count("get_board_stocks_full") == 0
        assert stocks and stocks[0]["price"] == 1800.0

    def test_ajax_is_cid_addressed(self, fresh_db, monkeypatch):
        """The AJAX slug is THS's internal cid, NOT the public platecode."""
        _seed_metadata()
        monkeypatch.setattr(board_mod, "get_cached_market_quotes", lambda m: None)
        mgr = _Recorder(ajax_rows=[{"stock_code": "600519", "stock_name": "贵州茅台"}])
        board_mod.get_board_stocks(
            "885333", source="ths", include_quote=True, manager=mgr, top_n=10
        )
        assert mgr.calls[-1][1]["board_code"] == "300188", mgr.calls
        assert mgr.calls[-1][1]["top_n"] == 10

    def test_ajax_row_gains_the_five_cached_fields(self, fresh_db, monkeypatch):
        """THS's 14 columns lack open/high/low/prev_close/volume."""
        _seed_metadata()
        monkeypatch.setattr(board_mod, "get_cached_market_quotes", lambda m: [_quote("600519")])
        mgr = _Recorder(ajax_rows=[{"stock_code": "600519", "stock_name": "贵州茅台"}])
        stocks, *_ = board_mod.get_board_stocks(
            "885333", source="ths", include_quote=True, manager=mgr, top_n=10
        )
        row = stocks[0]
        assert row["open"] == 1.0 and row["high"] == 1.1 and row["low"] == 0.9
        assert row["prev_close"] == 1.0 and row["volume"] == 100

    def test_quote_truncated_true_when_the_cap_is_hit(self, fresh_db, monkeypatch):
        """AJAX hard-caps at 50, so `len(stocks) >= top_n` is the honest flag."""
        _seed_metadata()
        monkeypatch.setattr(board_mod, "get_cached_market_quotes", lambda m: None)
        rows = [{"stock_code": f"60{i:04d}", "stock_name": f"s{i}"} for i in range(50)]
        mgr = _Recorder(ajax_rows=rows)
        _stocks, _o, _e, _r, trunc, _t = board_mod.get_board_stocks(
            "885333", source="ths", include_quote=True, manager=mgr, top_n=50
        )
        assert trunc is True

    def test_quote_truncated_false_when_below_the_cap(self, fresh_db, monkeypatch):
        _seed_metadata()
        monkeypatch.setattr(board_mod, "get_cached_market_quotes", lambda m: None)
        mgr = _Recorder(ajax_rows=[{"stock_code": "600519", "stock_name": "贵州茅台"}])
        _stocks, _o, _e, _r, trunc, _t = board_mod.get_board_stocks(
            "885333", source="ths", include_quote=True, manager=mgr, top_n=50
        )
        assert trunc is False


class TestF10TierAbove50:
    def test_switches_to_f10_and_never_zzshare(self, fresh_db, monkeypatch):
        _seed_metadata()
        monkeypatch.setattr(board_mod, "get_cached_market_quotes", lambda m: [_quote("600519")])
        mgr = _Recorder(f10_rows=[{"stock_code": "600519", "stock_name": "贵州茅台", "rank": 1}])
        stocks, _origin, _effective, _reason, _trunc, _total = board_mod.get_board_stocks(
            "885333", source="ths", include_quote=True, manager=mgr, top_n=200
        )
        _assert_no_zzshare(mgr)
        assert [c[0] for c in mgr.calls].count("get_board_stocks_full") == 1
        assert [c[0] for c in mgr.calls].count("get_board_stocks") == 0
        assert len(stocks) == 1

    def test_f10_is_platecode_addressed(self, fresh_db, monkeypatch):
        """F10 takes the public platecode; no cid translation."""
        _seed_metadata()
        monkeypatch.setattr(board_mod, "get_cached_market_quotes", lambda m: None)
        mgr = _Recorder(f10_rows=[{"stock_code": "600519", "stock_name": "贵州茅台"}])
        board_mod.get_board_stocks(
            "885333", source="ths", include_quote=True, manager=mgr, top_n=200
        )
        assert mgr.calls[-1][1]["board_code"] == "885333", mgr.calls

    def test_f10_rows_get_quote_fields_from_the_union(self, fresh_db, monkeypatch):
        _seed_metadata()
        monkeypatch.setattr(board_mod, "get_cached_market_quotes", lambda m: [_quote("600519", price=1800.0)])
        mgr = _Recorder(f10_rows=[{"stock_code": "600519", "stock_name": "贵州茅台"}])
        stocks, *_ = board_mod.get_board_stocks(
            "885333", source="ths", include_quote=True, manager=mgr, top_n=200
        )
        assert stocks[0]["price"] == 1800.0

    def test_f10_structurally_absent_fields_stay_none(self, fresh_db, monkeypatch):
        """Contract: these three are None on the >50 tier (probed 2026-09-11)."""
        _seed_metadata()
        monkeypatch.setattr(board_mod, "get_cached_market_quotes", lambda m: [_quote("600519")])
        mgr = _Recorder(f10_rows=[{"stock_code": "600519", "stock_name": "贵州茅台"}])
        stocks, *_ = board_mod.get_board_stocks(
            "885333", source="ths", include_quote=True, manager=mgr, top_n=200
        )
        for field in ("change_speed", "free_float_shares", "float_market_cap"):
            assert stocks[0].get(field) is None

    def test_f10_result_is_sliced_and_sorted_in_process(self, fresh_db, monkeypatch):
        """F10 has no upstream sort, and can return more rows than top_n."""
        _seed_metadata()
        monkeypatch.setattr(board_mod, "get_cached_market_quotes", lambda m: None)
        rows = [{"stock_code": "600519", "stock_name": "a", "change_pct": 1.0},
                {"stock_code": "600520", "stock_name": "b", "change_pct": 9.0},
                {"stock_code": "600521", "stock_name": "c", "change_pct": 5.0}]
        mgr = _Recorder(f10_rows=rows)
        stocks, *_ = board_mod.get_board_stocks(
            "885333", source="ths", include_quote=True, manager=mgr,
            top_n=51, sort_by="change_pct", sort_order="desc",
        )
        assert [s["stock_code"] for s in stocks] == ["600520", "600521", "600519"]


class TestTopNLimitWidened:
    def test_route_accepts_top_n_above_50(self, app):
        """Read the COMPILED route's query-param spec, not source text.

        Two traps this avoids:

        * the app is built with ``openapi_url=None``, so there is no
          ``/openapi.json`` to assert against; and
        * ``inspect.getsource(routes_mod.get_board_stocks)`` would be a
          false-green — ``@map_errors`` / ``@cache_endpoint`` replace the
          module attribute with a WRAPPER (CLAUDE.md's decorator-order
          rule), and getsource reports the wrapper's source in errors.py.
        """
        from fastapi.routing import APIRoute

        route = next(
            r
            for r in app.routes
            if isinstance(r, APIRoute)
            and r.path == "/api/v1/boards/{board_code}/stocks"
            and "GET" in r.methods
        )
        top_n = next(p for p in route.dependant.query_params if p.name == "top_n")
        fi = top_n.field_info
        assert fi.default == 50, fi
        # pydantic v2 keeps the ge/le constraints in `metadata` (as Ge/Le
        # objects), not as attributes on the FieldInfo itself.
        bounds = {type(m).__name__.lower(): getattr(m, "le", None) or getattr(m, "ge", None)
                  for m in fi.metadata}
        assert bounds.get("le") == 800, fi.metadata
        assert bounds.get("ge") == 1, fi.metadata
