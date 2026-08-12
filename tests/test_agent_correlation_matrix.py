"""Integration tests for POST /api/v1/agent/correlation/matrix.

These cover the 10-case test list from
docs/superpowers/specs/2026-08-12-correlation-matrix-design.md §6.
"""
from unittest.mock import MagicMock

import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from stock_data.api.routes import agent_correlation as ac
from stock_data.server import app

client = TestClient(app)


@pytest.fixture(autouse=True)
def _reset_state():
    """Clear TTL caches + reset the manager singleton between tests.

    Mirrors `tests/test_agent_endpoints.py::reset_before_test`
    (tests/conftest.py:13-40). Without this, mocks from prior tests can
    leak into the inner fetcher cache and silently make later tests green.
    """
    from stock_data.api import cache as _cache
    for name in ("get_quote_cache", "get_history_cache", "get_kline_cache"):
        c = getattr(_cache, name, None)
        if c is not None and hasattr(c, "clear"):
            c.clear()
    try:
        from stock_data.data_provider.manager import reset_manager
        reset_manager()
    except Exception:
        pass
    yield


def _mgr_stub(stock_dfs=None,
              board_rows=None,
              stock_side_effect=None,
              board_side_effect=None):
    """Build a MagicMock DataFetcherManager that returns canned stock/board data."""
    mgr = MagicMock()
    if stock_side_effect is not None:
        mgr.get_kline_data.side_effect = stock_side_effect
    else:
        stock_dfs = stock_dfs or {}
        mgr.get_kline_data.side_effect = lambda **kw: (
            stock_dfs.get(kw["stock_code"], pd.DataFrame()),
            "tushare",
        )
    if board_side_effect is not None:
        mgr.get_board_history.side_effect = board_side_effect
    else:
        board_rows = board_rows or {}
        mgr.get_board_history.side_effect = lambda **kw: (
            board_rows.get((kw["board_code"], kw["source"]), []),
            "ths",
        )
    return mgr


def _patch_manager(monkeypatch, mgr):
    # Patch the route module's `get_manager` symbol — the fetcher helpers
    # and the route handler both call it.
    monkeypatch.setattr(ac, "get_manager", lambda: mgr)


def test_mixed_stock_board_pearson_diagonal_one(monkeypatch):
    # Two stocks + one board, 30 days; deterministic prices
    idx = pd.date_range("2026-04-01", periods=30, freq="D")
    s1 = pd.DataFrame({"trade_date": idx, "close": np.linspace(100, 110, 30)})
    s2 = pd.DataFrame({"trade_date": idx, "close": np.linspace(100, 130, 30)})   # bigger uptrend
    brow = [{"date": str(d.date()), "close": float(v)}
            for d, v in zip(idx, np.linspace(200, 240, 30), strict=False)]
    mgr = _mgr_stub({"600519": s1, "000001": s2}, {("885595", "ths"): brow})
    _patch_manager(monkeypatch, mgr)

    r = client.post("/api/v1/agent/correlation/matrix", json={
        "stocks": ["600519", "000001"],
        "boards": [{"code": "885595", "source": "ths"}],
        "frequency": "d", "days": 30,
    })
    assert r.status_code == 200, r.text
    body = r.json()
    assert len(body["labels"]) == 3
    m = np.array(body["matrices"]["pearson"])
    assert m.shape == (3, 3)
    assert np.allclose(np.diag(m), 1.0)
    assert np.allclose(m, m.T, atol=1e-4)


def test_methods_subset_returns_only_pearson(monkeypatch):
    idx = pd.date_range("2026-04-01", periods=30, freq="D")
    s1 = pd.DataFrame({"trade_date": idx, "close": np.linspace(100, 110, 30)})
    s2 = pd.DataFrame({"trade_date": idx, "close": np.linspace(100, 130, 30)})
    mgr = _mgr_stub({"600519": s1, "000001": s2})
    _patch_manager(monkeypatch, mgr)
    r = client.post("/api/v1/agent/correlation/matrix", json={
        "stocks": ["600519", "000001"], "boards": [],
        "frequency": "d", "days": 30,
        "methods": ["pearson"],
    })
    assert r.status_code == 200
    assert r.json()["matrices"]["pearson"] is not None
    assert r.json()["matrices"]["spearman"] is None


def test_per_item_failure_isolation(monkeypatch):
    """One stock fails; another stock + board succeed; matrix has 2 survivors."""
    from stock_data.data_provider.base import DataFetchError
    idx = pd.date_range("2026-04-01", periods=30, freq="D")
    good_stock = pd.DataFrame({"trade_date": idx, "close": np.linspace(100, 110, 30)})
    board_rows = [{"date": str(d.date()), "close": float(v)}
                  for d, v in zip(idx, np.linspace(200, 240, 30), strict=False)]
    mgr = MagicMock()

    def kline_side_effect(**kw):
        if kw["stock_code"] == "000001":
            raise DataFetchError("upstream 503")
        return (good_stock, "tushare")

    mgr.get_kline_data.side_effect = kline_side_effect
    mgr.get_board_history.return_value = (board_rows, "ths")
    _patch_manager(monkeypatch, mgr)

    r = client.post("/api/v1/agent/correlation/matrix", json={
        "stocks": ["600519", "000001"],
        "boards": [{"code": "885595", "source": "ths"}],
        "frequency": "d", "days": 30,
    })
    assert r.status_code == 200
    body = r.json()
    # 600519 + 885595 succeed; 000001 fails
    assert any(e["code"] == "000001" for e in body["errors"])
    assert len(body["labels"]) == 2   # 2 survivors


def test_all_fail_returns_422(monkeypatch):
    from stock_data.data_provider.base import DataFetchError
    mgr = MagicMock()
    mgr.get_kline_data.side_effect = lambda **kw: (_ for _ in ()).throw(DataFetchError("down"))
    mgr.get_board_history.side_effect = lambda **kw: (_ for _ in ()).throw(DataFetchError("down"))
    _patch_manager(monkeypatch, mgr)
    r = client.post("/api/v1/agent/correlation/matrix", json={
        "stocks": ["600519", "000001"], "boards": [], "frequency": "d", "days": 30,
    })
    assert r.status_code == 422


def test_only_one_survives_returns_422(monkeypatch):
    from stock_data.data_provider.base import DataFetchError
    idx = pd.date_range("2026-04-01", periods=30, freq="D")
    good = pd.DataFrame({"trade_date": idx, "close": np.linspace(100, 110, 30)})
    mgr = MagicMock()

    def kline(**kw):
        if kw["stock_code"] == "600519":
            return (good, "tushare")
        raise DataFetchError("down")

    mgr.get_kline_data.side_effect = kline
    mgr.get_board_history.return_value = ([], "ths")
    _patch_manager(monkeypatch, mgr)
    r = client.post("/api/v1/agent/correlation/matrix", json={
        "stocks": ["600519", "000001"], "boards": [], "frequency": "d", "days": 30,
    })
    assert r.status_code == 422


def test_format_md_emits_top_pairs(monkeypatch):
    """format=md returns PlainTextResponse, NOT a JSON dict (review fix #1)."""
    idx = pd.date_range("2026-04-01", periods=30, freq="D")
    s1 = pd.DataFrame({"trade_date": idx, "close": np.linspace(100, 110, 30)})
    s2 = pd.DataFrame({"trade_date": idx, "close": np.linspace(100, 130, 30)})
    mgr = _mgr_stub({"600519": s1, "000001": s2})
    _patch_manager(monkeypatch, mgr)
    r = client.post("/api/v1/agent/correlation/matrix?format=md", json={
        "stocks": ["600519", "000001"], "boards": [], "frequency": "d", "days": 30,
    })
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/markdown")
    assert "## 相关性矩阵 — pearson" in r.text


def test_too_many_assets_rejected(monkeypatch):
    mgr = MagicMock()
    _patch_manager(monkeypatch, mgr)
    r = client.post("/api/v1/agent/correlation/matrix", json={
        "stocks": [str(i).zfill(6) for i in range(11)], "boards": [],
        "frequency": "d", "days": 30,
    })
    # CorrelationMatrixRequest.stocks has no Pydantic max_length — the 422
    # fires in `_parse_and_validate`'s `len(stocks_raw) > 10` cap.
    assert r.status_code == 422


def test_normalize_strip_suffix(monkeypatch):
    idx = pd.date_range("2026-04-01", periods=30, freq="D")
    s1 = pd.DataFrame({"trade_date": idx, "close": np.linspace(100, 110, 30)})
    s2 = pd.DataFrame({"trade_date": idx, "close": np.linspace(100, 130, 30)})
    mgr = _mgr_stub({"600519": s1, "000001": s2})
    _patch_manager(monkeypatch, mgr)
    r = client.post("/api/v1/agent/correlation/matrix", json={
        "stocks": ["SH600519", "sz000001"], "boards": [], "frequency": "d", "days": 30,
    })
    assert r.status_code == 200
    codes = [L["code"] for L in r.json()["labels"]]
    assert codes == ["600519", "000001"]


def test_boards_only_mode(monkeypatch):
    """No stocks at all — boards-only correlation. stocks/boards are
    independent optional lists; any combination with >= 2 assets works."""
    idx = pd.date_range("2026-04-01", periods=30, freq="D")
    brow1 = [{"date": str(d.date()), "close": float(v)}
             for d, v in zip(idx, np.linspace(200, 240, 30), strict=False)]
    brow2 = [{"date": str(d.date()), "close": float(v)}
             for d, v in zip(idx, np.linspace(300, 340, 30), strict=False)]
    mgr = _mgr_stub({}, {("885595", "ths"): brow1, ("885584", "ths"): brow2})
    _patch_manager(monkeypatch, mgr)
    r = client.post("/api/v1/agent/correlation/matrix", json={
        "boards": ["885595", "885584"], "frequency": "d", "days": 30,
    })
    assert r.status_code == 200
    body = r.json()
    assert [L["code"] for L in body["labels"]] == ["885595", "885584"]
    assert all(L["source"] == "ths" for L in body["labels"])
    assert body["matrices"]["pearson"] is not None


def test_boards_as_strings_mixed_with_stocks(monkeypatch):
    """Mixed mode: boards passed as bare codes alongside stocks."""
    idx = pd.date_range("2026-04-01", periods=30, freq="D")
    s1 = pd.DataFrame({"trade_date": idx, "close": np.linspace(100, 110, 30)})
    s2 = pd.DataFrame({"trade_date": idx, "close": np.linspace(100, 130, 30)})
    brow = [{"date": str(d.date()), "close": float(v)}
            for d, v in zip(idx, np.linspace(200, 240, 30), strict=False)]
    mgr = _mgr_stub({"600519": s1, "000001": s2}, {("885595", "ths"): brow})
    _patch_manager(monkeypatch, mgr)
    r = client.post("/api/v1/agent/correlation/matrix", json={
        "stocks": ["600519", "000001"], "boards": ["885595"],
        "frequency": "d", "days": 30,
    })
    assert r.status_code == 200
    body = r.json()
    assert len(body["labels"]) == 3
    assert body["labels"][2]["source"] == "ths"


def test_empty_assets_returns_clean_422(monkeypatch):
    """Both stocks and boards omitted → clean 422 body (no schema-validator
    serialization crash on the server 422 handler)."""
    mgr = MagicMock()
    _patch_manager(monkeypatch, mgr)
    r = client.post("/api/v1/agent/correlation/matrix", json={
        "stocks": [], "boards": [], "frequency": "d", "days": 30,
    })
    assert r.status_code == 422
    body = r.json()
    assert body["detail"]["error"] == "bad_request"
    assert "at least 2 entries" in body["detail"]["message"]


def test_repeat_request_succeeds_without_state_corruption(monkeypatch):
    """Spec §6 #14 contract: handler has no agent-level cache; an identical
    second request must still return a 200 with a non-null matrix (proving
    no state corruption between calls). The MagicMock bypasses real TTL
    behavior; per-call-count assertions are intentionally NOT made for
    the second call because that would require a real fetcher-level cache
    to be observable, which is out of scope for this route.
    """
    idx = pd.date_range("2026-04-01", periods=30, freq="D")
    df = pd.DataFrame({"trade_date": idx, "close": np.linspace(100, 110, 30)})
    mgr = MagicMock()
    mgr.get_kline_data.side_effect = lambda **kw: (df, "tushare")
    _patch_manager(monkeypatch, mgr)

    payload = {"stocks": ["600519", "000001"], "boards": [],
               "frequency": "d", "days": 30}
    r1 = client.post("/api/v1/agent/correlation/matrix", json=payload)
    assert r1.status_code == 200
    first_calls = mgr.get_kline_data.call_count
    assert first_calls == 2, f"first request should call fetcher once per stock; got {first_calls}"
    r2 = client.post("/api/v1/agent/correlation/matrix", json=payload)
    assert r2.status_code == 200
    # The route MUST NOT have stateful cache that prevents the second call from succeeding
    assert r2.json()["matrices"]["pearson"] is not None


def test_inner_cache_avoids_recomputation(monkeypatch):
    """Spec §6 #14: identical repeat request makes 0 NEW fetcher calls.

    Simulates the fetcher-level TTL cache (inner K-line cache) as a dict
    inside the manager stub: the first request pays N cold fetches, the
    second is fully served from the fake cache (delta == 0). Observable
    proof that the endpoint needs no agent-composite cache.
    """
    idx = pd.date_range("2026-04-01", periods=30, freq="D")
    df = pd.DataFrame({"trade_date": idx, "close": np.linspace(100, 110, 30)})
    mgr = MagicMock()
    cache = {}
    fetch_calls = {"n": 0}

    def cached_kline(**kw):
        key = (kw["stock_code"], kw["days"], kw["frequency"])
        if key in cache:
            return cache[key]
        fetch_calls["n"] += 1
        result = (df, "tushare")
        cache[key] = result
        return result

    mgr.get_kline_data.side_effect = cached_kline
    _patch_manager(monkeypatch, mgr)

    payload = {"stocks": ["600519", "000001"], "boards": [],
               "frequency": "d", "days": 30}
    r1 = client.post("/api/v1/agent/correlation/matrix", json=payload)
    assert r1.status_code == 200
    assert fetch_calls["n"] == 2, (
        f"cold request should fetch once per stock; got {fetch_calls['n']}"
    )

    r2 = client.post("/api/v1/agent/correlation/matrix", json=payload)
    assert r2.status_code == 200
    assert fetch_calls["n"] == 2, (
        f"repeat request within inner-TTL window must make 0 new fetches; "
        f"got {fetch_calls['n'] - 2} new"
    )


def test_trailing_trim_fires_when_fetch_over_returns(monkeypatch):
    """Mechanism test: when the fetcher returns MORE bars than trailing_window
    (=days+1), `_align_series` trims to the trailing window. This mock
    deliberately over-returns (120 rows ignoring the `days` param) to prove the
    trim step itself. In production the d/w/m fetchers resolve `days` as a
    calendar window and return ~0.7×days trading bars — FEWER than the window —
    so the trim is usually a no-op; see
    test_calendar_window_yields_real_trading_bars for that behavior."""
    idx = pd.date_range("2026-01-01", periods=120, freq="D")
    s1 = pd.DataFrame({"trade_date": idx, "close": np.linspace(100, 130, 120)})
    s2 = pd.DataFrame({"trade_date": idx, "close": np.linspace(200, 260, 120)})
    mgr = _mgr_stub({"600519": s1, "000001": s2})
    _patch_manager(monkeypatch, mgr)

    r = client.post("/api/v1/agent/correlation/matrix", json={
        "stocks": ["600519", "000001"], "boards": [], "frequency": "d", "days": 30,
    })
    assert r.status_code == 200
    # Fetcher was called with days + 1 (1 buffer for pct_change)
    called = mgr.get_kline_data.call_args.kwargs
    assert called["days"] == 30 + 1
    body = r.json()
    assert body["alignment"]["requested_days"] == 30
    # Trim fired: trailing_window=days+1=31 → 120 rows collapsed to 31.
    assert body["alignment"]["common_bars"] == 31, (
        f"expected 31 trimmed rows (days+1 buffer); got {body['alignment']['common_bars']}. "
        "The trim-to-trailing-window step in _align_series is missing or wrong."
    )
    # 120 fully-aligned rows → the join drops nothing; missing_after_join must
    # be 0, NOT 120 - 30 = 90 (padding/trim is not missing data).
    assert body["alignment"]["missing_after_join"] == 0, (
        f"expected 0 join-dropped dates; got {body['alignment']['missing_after_join']}"
    )


def _kline_for_calendar_window(days: int) -> pd.DataFrame:
    """Simulate the real fetcher: `days` calendar days → only weekday bars."""
    end = pd.Timestamp("2026-08-12")
    idx = pd.bdate_range(end - pd.Timedelta(days=days), end)
    return pd.DataFrame({"trade_date": idx, "close": np.linspace(100, 130, len(idx))})


def test_calendar_window_yields_real_trading_bars(monkeypatch):
    """days is a calendar-day window (spec §2.5): the fetcher gets days+1
    calendar days and returns only trading (weekday) bars — FEWER than `days`
    rows. trailing_window=days+1 is therefore a no-op and common_bars reflects
    the real bar count, NOT days. The 'exactly N returns' invariant holds only
    for dense minute bars; for d/w/m it does not (calendar > trading days)."""
    def kline(**kw):
        return (_kline_for_calendar_window(kw["days"]), "tushare")

    mgr = MagicMock()
    mgr.get_kline_data.side_effect = kline
    _patch_manager(monkeypatch, mgr)

    r = client.post("/api/v1/agent/correlation/matrix", json={
        "stocks": ["600519", "000001"], "boards": [], "frequency": "d", "days": 30,
    })
    assert r.status_code == 200, r.text
    called = mgr.get_kline_data.call_args.kwargs
    assert called["days"] == 30 + 1                      # route passes days+1
    body = r.json()
    assert body["alignment"]["requested_days"] == 30
    expected_bars = len(_kline_for_calendar_window(31))  # 31 calendar days ≈ 22 weekdays
    assert expected_bars < 31                            # calendar days > trading days
    assert body["alignment"]["common_bars"] == expected_bars, (
        f"expected real trading-bar count {expected_bars}, got "
        f"{body['alignment']['common_bars']}"
    )
    assert body["alignment"]["missing_after_join"] == 0  # identical calendars → no join drop
