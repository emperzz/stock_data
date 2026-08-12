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
    # The schema caps each list at 10; this payload (11 stocks) hits the
    # Pydantic max-length validator, which surfaces as 422. The 400 branch
    # in `_parse_and_validate` is unreachable on this code path.
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


def test_calendar_padding_trims_to_days(monkeypatch):
    """days=30 → fetcher called with days+60 (90), response alignment is trimmed."""
    # Provide 120 days of history. days=30 → effective window should be the
    # LAST 30 rows (trim spec §3.1); alignment.common_bars == 30.
    idx = pd.date_range("2026-01-01", periods=120, freq="D")
    s1 = pd.DataFrame({"trade_date": idx, "close": np.linspace(100, 130, 120)})
    s2 = pd.DataFrame({"trade_date": idx, "close": np.linspace(200, 260, 120)})
    mgr = _mgr_stub({"600519": s1, "000001": s2})
    _patch_manager(monkeypatch, mgr)

    r = client.post("/api/v1/agent/correlation/matrix", json={
        "stocks": ["600519", "000001"], "boards": [], "frequency": "d", "days": 30,
    })
    assert r.status_code == 200
    # Fetcher was called with days + 60 (calendar padding)
    called = mgr.get_kline_data.call_args.kwargs
    assert called["days"] == 30 + 60
    # Response alignment echoes back the user's days value
    body = r.json()
    assert body["alignment"]["requested_days"] == 30
    # Trim: only the LAST `days` rows participate; common_bars must equal 30
    assert body["alignment"]["common_bars"] == 30, (
        f"expected 30 trimmed rows; got {body['alignment']['common_bars']}. "
        "The trim-to-trailing-window step in _align_series is missing or wrong."
    )
