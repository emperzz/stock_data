"""Tests for /api/v1/agent/boards/batch-profile (THS board-level features)."""

from __future__ import annotations

import contextlib
import random
from unittest.mock import MagicMock

import pandas as pd
import pytest
from pydantic import ValidationError

from stock_data.api.routes import agent as agent_module
from stock_data.api.routes import reset_manager
from stock_data.api.schemas import (
    BatchFeatures,
    BoardProfile,
    BoardsBatchProfileRequest,
    BoardsBatchProfileResponse,
    MinimalQuote,
)
from stock_data.data_provider.base import DataFetchError


class TestSchemas:
    def test_board_profile_defaults(self):
        bp = BoardProfile(code="885595")
        assert bp.code == "885595"
        assert bp.name == ""
        assert bp.quote is None
        assert bp.features is None
        assert bp.errors == {}

    def test_board_profile_with_full_payload(self):
        bp = BoardProfile(
            code="881270",
            name="半导体",
            quote=MinimalQuote(price=1234.5, change_pct=1.23),
            features=BatchFeatures(),
            errors={"quote": None, "features": None},
        )
        assert bp.name == "半导体"
        assert bp.quote.price == 1234.5
        assert bp.features == BatchFeatures()
        assert bp.errors == {"quote": None, "features": None}

    def test_request_accepts_codes_and_defaults(self):
        req = BoardsBatchProfileRequest(codes=["885595", "881270"])
        assert req.codes == ["885595", "881270"]
        assert req.frequency == "d"
        assert req.days is None

    def test_request_rejects_empty_codes(self):
        with pytest.raises(ValidationError):
            BoardsBatchProfileRequest(codes=[])

    def test_request_rejects_too_many_codes(self):
        with pytest.raises(ValidationError):
            BoardsBatchProfileRequest(codes=[f"88{i:04d}" for i in range(6)])

    def test_request_accepts_all_supported_frequencies(self):
        for f in ("d", "w", "m", "1m", "5m", "15m", "30m", "60m"):
            req = BoardsBatchProfileRequest(codes=["885595"], frequency=f)
            assert req.frequency == f

    def test_request_rejects_unsupported_frequency(self):
        with pytest.raises(ValidationError):
            BoardsBatchProfileRequest(codes=["885595"], frequency="2h")

    def test_response_defaults(self):
        resp = BoardsBatchProfileResponse()
        assert resp.frequency == "d"
        assert resp.days == 0
        assert resp.boards == []
        assert resp.summary == {}

    def test_response_carries_boards_in_order(self):
        resp = BoardsBatchProfileResponse(
            frequency="d",
            days=60,
            boards=[
                BoardProfile(code="881270"),
                BoardProfile(code="885595"),
            ],
            summary={"requested": 2, "ok": 2, "failed": 0, "elapsed_ms": 100},
        )
        assert [b.code for b in resp.boards] == ["881270", "885595"]
        assert resp.summary["elapsed_ms"] == 100


@pytest.fixture(autouse=True)
def reset_before_test():
    """Same cache-clear as tests/test_agent_batch_features.py — boards/batch-profile
    MUST NOT touch any cache layer, but we still clear in case other tests
    in this run wrote to the caches."""
    reset_manager()
    from stock_data.api import cache as api_cache

    for getter_name in (
        "get_quote_cache",
        "get_index_quote_cache",
        "get_history_cache",
        "get_pools_cache",
        "get_stock_info_cache",
        "get_news_flash_cache",
        "get_cls_feed_cache",
        "get_dragontiger_cache",
    ):
        getter = getattr(api_cache, getter_name, None)
        if getter is None:
            continue
        with contextlib.suppress(TypeError):
            getter().clear()
    for f in ("d", "w", "m", "1", "5", "15", "30", "60"):
        with contextlib.suppress(Exception):
            api_cache.get_history_cache(f).clear()
    yield


def _make_kline_df(rows: int = 90, *, seed: int = 1) -> pd.DataFrame:
    """Deterministic OHLCV frame with 90 bars — enough to warm MA60."""
    rng = random.Random(seed)
    closes = [10.0]
    for _ in range(rows - 1):
        closes.append(closes[-1] * (1 + rng.uniform(-0.02, 0.03)))
    dates = pd.date_range("2026-01-01", periods=rows, freq="B")
    vols = [1_000_000 * (1 + abs(rng.gauss(0, 0.3))) for _ in range(rows)]
    return pd.DataFrame(
        {
            "date": [d.strftime("%Y-%m-%d") for d in dates],
            "open": [round(c * 0.995, 3) for c in closes],
            "high": [round(c * 1.01, 3) for c in closes],
            "low": [round(c * 0.99, 3) for c in closes],
            "close": [round(c, 3) for c in closes],
            "volume": vols,
            "amount": [v * c for v, c in zip(vols, closes, strict=True)],
            "pct_chg": [0.0] * rows,
        }
    )


def _mock_manager(*, realtime_results: dict, history_results: dict):
    """Build a MagicMock manager matching the manager interface used by handler.

    realtime_results: {code: dict | Exception} — what get_board_realtime(code, source='ths')
        returns as its 1st tuple item. Exception instances are raised (not returned).
    history_results:  {code: pd.DataFrame | Exception} — what get_board_history(code, source='ths', ...)
        returns as its 1st tuple item. Exception instances are raised.
    """
    manager = MagicMock()
    manager.get_board_realtime.side_effect = lambda code, source: (
        (realtime_results[code], "ths")
        if not isinstance(realtime_results.get(code), Exception)
        else (_ for _ in ()).throw(realtime_results[code])
    )
    manager.get_board_history.side_effect = lambda code, source, frequency, days: (
        (history_results[code], "ths")
        if not isinstance(history_results.get(code), Exception)
        else (_ for _ in ()).throw(history_results[code])
    )
    return manager


class TestHandler:
    def test_happy_path_returns_features_and_quote(self, client, monkeypatch):
        df = _make_kline_df(90)
        realtime = {"885595": {"price": 1234.5, "change_pct": 1.23}}
        history = {"885595": df}
        manager = _mock_manager(realtime_results=realtime, history_results=history)
        monkeypatch.setattr(agent_module, "get_manager", lambda: manager)
        monkeypatch.setattr(
            "stock_data.data_provider.persistence.board.get_board_name_with_fallback",
            lambda code, source, manager=None: "人形机器人",
        )
        r = client.post(
            "/api/v1/agent/boards/batch-profile",
            json={"codes": ["885595"], "frequency": "d", "days": 60},
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["frequency"] == "d"
        assert body["days"] == 60
        assert len(body["boards"]) == 1
        board = body["boards"][0]
        assert board["code"] == "885595"
        assert board["name"] == "人形机器人"
        assert board["quote"] == {"price": 1234.5, "change_pct": 1.23}
        assert board["features"]["trend"]  # non-empty (90 bars → MA values)
        assert board["errors"] == {"quote": None, "features": None}
        assert body["summary"]["requested"] == 1
        assert body["summary"]["ok"] == 1

    def test_per_code_error_isolation(self, client, monkeypatch):
        """One board fails on both quote + features; the other succeeds."""
        df_ok = _make_kline_df(90, seed=1)
        realtime = {
            "881270": {"price": 567.8, "change_pct": -0.45},
            "885595": DataFetchError("upstream timeout"),
        }
        history = {
            "881270": df_ok,
            "885595": DataFetchError("no K-line for this code"),
        }
        manager = _mock_manager(realtime_results=realtime, history_results=history)
        monkeypatch.setattr(agent_module, "get_manager", lambda: manager)
        monkeypatch.setattr(
            "stock_data.data_provider.persistence.board.get_board_name_with_fallback",
            lambda code, source, manager=None: {"881270": "半导体", "885595": None}[code],
        )
        r = client.post(
            "/api/v1/agent/boards/batch-profile",
            json={"codes": ["881270", "885595"], "frequency": "d"},
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert len(body["boards"]) == 2
        ok_board, bad_board = body["boards"]
        assert ok_board["code"] == "881270"
        assert ok_board["name"] == "半导体"
        assert ok_board["quote"] == {"price": 567.8, "change_pct": -0.45}
        assert ok_board["features"]["trend"]
        assert ok_board["errors"] == {"quote": None, "features": None}
        assert bad_board["code"] == "885595"
        assert bad_board["name"] == ""
        assert bad_board["quote"] is None
        assert bad_board["features"] is None
        assert "DataFetchError" in bad_board["errors"]["quote"]
        assert "DataFetchError" in bad_board["errors"]["features"]
        assert body["summary"]["requested"] == 2
        assert body["summary"]["ok"] == 1
        assert body["summary"]["failed"] == 1

    def test_response_preserves_input_order(self, client, monkeypatch):
        df = _make_kline_df(90, seed=2)
        realtime = {c: {"price": 1.0, "change_pct": 0.1} for c in ("881270", "885595", "883957")}
        history = {c: df for c in ("881270", "885595", "883957")}
        manager = _mock_manager(realtime_results=realtime, history_results=history)
        monkeypatch.setattr(agent_module, "get_manager", lambda: manager)
        monkeypatch.setattr(
            "stock_data.data_provider.persistence.board.get_board_name_with_fallback",
            lambda code, source, manager=None: code,
        )
        r = client.post(
            "/api/v1/agent/boards/batch-profile",
            json={"codes": ["883957", "881270", "885595"], "frequency": "d"},
        )
        body = r.json()
        assert [b["code"] for b in body["boards"]] == ["883957", "881270", "885595"]

    def test_unsupported_frequency_returns_422(self, client):
        r = client.post(
            "/api/v1/agent/boards/batch-profile",
            json={"codes": ["885595"], "frequency": "2h"},
        )
        assert r.status_code == 422  # Pydantic Literal catches it before the route

    def test_days_out_of_range_returns_422(self, client):
        r = client.post(
            "/api/v1/agent/boards/batch-profile",
            json={"codes": ["885595"], "frequency": "1m", "days": 10},  # 1m max=3
        )
        assert r.status_code == 422
        assert "days" in str(r.json()).lower()

    def test_empty_codes_returns_422(self, client):
        r = client.post(
            "/api/v1/agent/boards/batch-profile",
            json={"codes": []},
        )
        assert r.status_code == 422

    def test_too_many_codes_returns_422(self, client):
        r = client.post(
            "/api/v1/agent/boards/batch-profile",
            json={"codes": [f"88{i:04d}" for i in range(6)]},
        )
        assert r.status_code == 422

    def test_empty_kline_dataframe_yields_empty_features(self, client, monkeypatch):
        """Empty DataFrame → build_features returns {} for all 3 blocks,
        handler wraps in BatchFeatures(...) which expands default_factory."""
        empty_df = pd.DataFrame(
            {"date": [], "open": [], "high": [], "low": [], "close": [], "volume": [], "amount": [], "pct_chg": []}
        )
        realtime = {"885595": {"price": 1.0, "change_pct": 0.0}}
        history = {"885595": empty_df}
        manager = _mock_manager(realtime_results=realtime, history_results=history)
        monkeypatch.setattr(agent_module, "get_manager", lambda: manager)
        monkeypatch.setattr(
            "stock_data.data_provider.persistence.board.get_board_name_with_fallback",
            lambda code, source, manager=None: None,
        )
        r = client.post(
            "/api/v1/agent/boards/batch-profile",
            json={"codes": ["885595"], "frequency": "d"},
        )
        assert r.status_code == 200, r.text
        body = r.json()
        board = body["boards"][0]
        # Empty DataFrame → BatchFeatures sub-models serialized with default_factory values.
        # Quote succeeded, features succeeded (no exception raised), errors{} stays all-null,
        # summary counts it as ok. Compare specific empty markers — NOT the full dict.
        f = board["features"]
        assert f["trend"]["ma"] == {} and f["trend"]["ma_change"] == {}
        assert f["trend"]["adx"] is None and f["trend"]["pdi"] is None and f["trend"]["mdi"] is None
        assert f["pivots"]["swings"] == [] and f["pivots"]["params"] == {}
        assert f["pivots"]["window_high"] is None and f["pivots"]["window_low"] is None
        assert f["volume"]["z_anomalies"] == [] and f["volume"]["latest_volume"] is None
        assert board["errors"] == {"quote": None, "features": None}
        assert body["summary"]["ok"] == 1

    def test_handler_does_not_touch_quote_cache(self, client, monkeypatch):
        """Regression guard: the handler MUST NOT call cached_lookup / cached_store.
        Verifies the no-composite-cache decision from spec §5.

        Implementation note: ``agent.py`` does ``from ..cache import cached_lookup,
        cached_store`` — this creates LOCAL bindings in agent_module's namespace.
        ``patch.object(api_cache, "cached_lookup", ...)`` would NOT be seen by the
        handler because Python looks up the name in agent's globals, not in
        api_cache. Patch the handler's namespace instead.
        """
        df = _make_kline_df(90)
        realtime = {"885595": {"price": 1.0, "change_pct": 0.0}}
        history = {"885595": df}
        manager = _mock_manager(realtime_results=realtime, history_results=history)
        monkeypatch.setattr(agent_module, "get_manager", lambda: manager)
        monkeypatch.setattr(
            "stock_data.data_provider.persistence.board.get_board_name_with_fallback",
            lambda code, source, manager=None: None,
        )
        lookup_spy = MagicMock(wraps=agent_module.cached_lookup)
        store_spy = MagicMock(wraps=agent_module.cached_store)
        monkeypatch.setattr(agent_module, "cached_lookup", lookup_spy)
        monkeypatch.setattr(agent_module, "cached_store", store_spy)
        r = client.post(
            "/api/v1/agent/boards/batch-profile",
            json={"codes": ["885595"], "frequency": "d"},
        )
        assert r.status_code == 200
        # The handler MUST NOT use the composite agent cache layer.
        assert lookup_spy.call_count == 0, (
            "cached_lookup was called; boards/batch-profile must NOT add a composite cache"
        )
        assert store_spy.call_count == 0, (
            "cached_store was called; boards/batch-profile must NOT add a composite cache"
        )