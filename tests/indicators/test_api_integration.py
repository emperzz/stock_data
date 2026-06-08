"""Tests for the indicator-aware history endpoint and the catalog endpoint.

These tests bypass the network by monkey-patching the DataFetcherManager's
`get_kline_data` method to return a synthetic K-line. The real fetcher
system is irrelevant for these tests — we only care that the API layer
plumbs `?indicators=` through to IndicatorService correctly.
"""

import sys
import types
from unittest.mock import patch

import pandas as pd
import pytest


def _synthetic_kline(n: int) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "date": pd.date_range("2024-01-01", periods=n, freq="B"),
            "open": [100.0 + i * 0.1 for i in range(n)],
            "high": [101.0 + i * 0.1 for i in range(n)],
            "low": [99.0 + i * 0.1 for i in range(n)],
            "close": [100.5 + i * 0.1 for i in range(n)],
            "volume": [1000.0 + i * 10 for i in range(n)],
            "amount": [1_000_000.0 + i * 1000 for i in range(n)],
            "pct_chg": [0.1] * n,
            "code": ["600519"] * n,
        }
    )


@pytest.fixture
def client(monkeypatch):
    """Build a FastAPI TestClient with all network calls stubbed out."""
    # Stub the network-touching bits before importing the app.
    fake_kline = _synthetic_kline(60)

    def fake_get_kline_data(self, stock_code, **kwargs):
        # Truncate to whatever the caller asked for, simulating a real fetcher.
        requested = int(kwargs.get("days") or 30)
        return fake_kline.tail(requested).reset_index(drop=True), "StubFetcher"

    def fake_get_index_historical(self, index_code, **kwargs):
        # Same shape as the stock stub — return the synthetic frame.
        requested = int(kwargs.get("days") or 30)
        return fake_kline.tail(requested).reset_index(drop=True), "StubFetcher"

    # Import the FastAPI app
    from stock_data.server import app  # noqa: F401

    monkeypatch.setattr(
        "stock_data.data_provider.DataFetcherManager.get_kline_data",
        fake_get_kline_data,
    )
    monkeypatch.setattr(
        "stock_data.data_provider.DataFetcherManager.get_index_historical",
        fake_get_index_historical,
    )

    # Also stub the stock-name lookup so /history doesn't try a network call
    def fake_get_stock_name(code, manager=None):
        return "贵州茅台"

    monkeypatch.setattr(
        "stock_data.data_provider.cache.api_cache.get_stock_name",
        fake_get_stock_name,
    )

    from fastapi.testclient import TestClient

    return TestClient(app)


def test_catalog_endpoint_lists_all_indicators(client):
    r = client.get("/api/v1/indicators/catalog")
    assert r.status_code == 200
    body = r.json()
    assert "indicators" in body
    assert len(body["indicators"]) == 14
    keys = {entry["key"] for entry in body["indicators"]}
    assert keys == {
        "ma", "macd", "boll", "kdj", "rsi", "wr", "bias",
        "cci", "atr", "obv", "roc", "dmi", "sar", "kc",
    }
    # Each entry has the expected fields
    for entry in body["indicators"]:
        assert "input_shape" in entry
        assert "default_options" in entry
        assert "output_columns" in entry
        assert "default_lookback" in entry


def test_history_default_no_indicators(client):
    r = client.get("/api/v1/stocks/600519/history?days=30")
    assert r.status_code == 200
    body = r.json()
    assert body["code"] == "600519"
    assert len(body["data"]) == 30
    # No indicators requested -> the 4 indicator fields are OMITTED from
    # the response entirely (model_serializer drops them when None/empty).
    for row in body["data"]:
        assert "indicators" not in row
        assert "ma5" not in row
        assert "ma10" not in row
        assert "ma20" not in row
        # amount / change_percent keep the original "null when missing"
        # semantics — always present, possibly null.
        assert "amount" in row
        assert "change_percent" in row


def test_history_with_ma_indicator(client):
    r = client.get("/api/v1/stocks/600519/history?days=30&indicators=ma")
    assert r.status_code == 200
    body = r.json()
    assert len(body["data"]) == 30
    # The last row should have all the MA columns
    last_inds = body["data"][-1]["indicators"]
    assert "ma5" in last_inds
    assert "ma10" in last_inds
    assert "ma20" in last_inds
    # ma5/ma10/ma20 fields should be backfilled from the indicators dict
    last = body["data"][-1]
    assert last["ma5"] == last_inds["ma5"]
    assert last["ma10"] == last_inds["ma10"]
    assert last["ma20"] == last_inds["ma20"]


def test_history_with_multiple_indicators(client):
    r = client.get("/api/v1/stocks/600519/history?days=30&indicators=ma,macd,boll")
    assert r.status_code == 200
    body = r.json()
    last_inds = body["data"][-1]["indicators"]
    assert "ma5" in last_inds
    assert "macd_dif" in last_inds
    assert "boll_mid" in last_inds


def test_history_unknown_indicator_rejected(client):
    r = client.get("/api/v1/stocks/600519/history?days=30&indicators=macd,nope")
    assert r.status_code == 400
    body = r.json()
    assert body["detail"]["error"] == "invalid_indicator"
    assert "nope" in body["detail"]["message"]


def test_history_indicators_trigger_lookback_expansion(client):
    """When indicators need more lookback than `days`, the underlying
    fetch should request the larger amount."""
    captured_kwargs: list[dict] = []

    def spy_get_kline_data(self, stock_code, **kwargs):
        captured_kwargs.append(kwargs)
        fake_kline = _synthetic_kline(200)
        requested = int(kwargs.get("days") or 30)
        return fake_kline.tail(requested).reset_index(drop=True), "StubFetcher"

    import stock_data.data_provider as dp

    original = dp.DataFetcherManager.get_kline_data
    dp.DataFetcherManager.get_kline_data = spy_get_kline_data
    try:
        # Asking for days=30 but with macd (lookback=87)
        r = client.get("/api/v1/stocks/600519/history?days=30&indicators=macd")
        assert r.status_code == 200
        # The last captured request should have requested at least 87 days
        assert any(int(kw.get("days", 0)) >= 87 for kw in captured_kwargs)
        # But the response should only contain 30 bars
        body = r.json()
        assert len(body["data"]) == 30
    finally:
        dp.DataFetcherManager.get_kline_data = original


def test_index_history_supports_indicators(client):
    """The /indices/{code}/history endpoint accepts the same `?indicators=`
    query param as /stocks/{code}/history. With it, the 4 indicator
    fields appear; without it, they're omitted."""
    # With indicators
    r = client.get("/api/v1/indices/000300/history?days=30&indicators=ma")
    assert r.status_code == 200
    body = r.json()
    assert len(body["data"]) == 30
    last = body["data"][-1]
    # ma indicator should be computed and surfaced
    assert "ma5" in last and last["ma5"] is not None
    assert "ma10" in last and last["ma10"] is not None
    assert "ma20" in last and last["ma20"] is not None
    assert "indicators" in last
    assert "ma5" in last["indicators"]
    assert "ma30" in last["indicators"]

    # Without indicators — same 4 fields must be omitted
    r2 = client.get("/api/v1/indices/000300/history?days=30")
    assert r2.status_code == 200
    last2 = r2.json()["data"][-1]
    assert "ma5" not in last2
    assert "ma10" not in last2
    assert "ma20" not in last2
    assert "indicators" not in last2
    # amount/change_percent remain
    assert "amount" in last2
    assert "change_percent" in last2


def test_index_history_unknown_indicator_rejected(client):
    r = client.get("/api/v1/indices/000300/history?days=30&indicators=macd,nope")
    assert r.status_code == 400
    body = r.json()
    assert body["detail"]["error"] == "invalid_indicator"
    assert "nope" in body["detail"]["message"]
