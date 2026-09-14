"""Tests for the indicator-aware history endpoint and the catalog endpoint.

These tests bypass the network by monkey-patching the DataFetcherManager's
`get_kline_data` method to return a synthetic K-line. The real fetcher
system is irrelevant for these tests — we only care that the API layer
plumbs `?indicators=` through to the indicator orchestrator correctly.

Post days-removal (Plan §3.1): the route passes explicit ``start_date`` /
``end_date`` down to the manager; the stub generates business-day bars over
that window (ending YESTERDAY, mirroring real fetchers that have not
backfilled today), and the response row count is the number of trading bars
inside the user's window — no more "days = bar count" aliasing.
"""

from datetime import date, timedelta

import pandas as pd
import pytest

TODAY = date.today()
YESTERDAY = TODAY - timedelta(days=1)


def _window(days: int) -> tuple[str, str]:
    """(start_date, end_date=today) spanning ``days`` calendar days back —
    the old ``?days=N`` equivalent."""
    return (TODAY - timedelta(days=days)).isoformat(), TODAY.isoformat()


def _bars_in_user_window(days: int) -> int:
    """Expected response length for a ``days``-calendar-day window: trading
    bars in [TODAY-days, YESTERDAY] (stub never returns today's bar)."""
    return len(pd.bdate_range(start=TODAY - timedelta(days=days), end=YESTERDAY))


def _synthetic_kline_between(start: str, end: str) -> pd.DataFrame:
    """Business-day bars covering [start, end], capped at YESTERDAY.

    The YESTERDAY cap emulates every real fetcher in the fleet (see
    docs/kline-today-bar-merge-spec-2026-07-24.md §1.1): today's settled
    bar is not yet available, so the route's merge logic can splice it.
    """
    end_dt = min(pd.Timestamp(end), pd.Timestamp(YESTERDAY.isoformat()))
    dates = pd.bdate_range(start=start, end=end_dt)
    n = len(dates)
    return pd.DataFrame(
        {
            "date": dates,
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
    def fake_get_kline_data(self, stock_code, start_date, end_date, **kwargs):
        return _synthetic_kline_between(start_date, end_date), "StubFetcher"

    # Import the FastAPI app
    from stock_data.server import app

    monkeypatch.setattr(
        "stock_data.data_provider.DataFetcherManager.get_kline_data",
        fake_get_kline_data,
    )

    # Pin today-bar merging out of these tests. The /kline routes
    # best-effort merge today's realtime bar when the trade calendar is
    # warm, which (a) would make the row count depend on the wall clock and
    # the session DB contents, and (b) would hit the real network here.
    # is_trade_date=False is the documented "no today bar" path.
    monkeypatch.setattr(
        "stock_data.data_provider.DataFetcherManager.get_realtime_quote",
        lambda self, stock_code: None,
    )
    monkeypatch.setattr(
        "stock_data.data_provider.DataFetcherManager.get_index_realtime_quote",
        lambda self, index_code: None,
    )
    monkeypatch.setattr(
        "stock_data.api.routes.helpers.is_trade_date",
        lambda day: False,
    )

    # Also stub the stock-name lookup so /kline doesn't try a network call
    def fake_get_stock_name(code, manager=None):
        return "贵州茅台"

    monkeypatch.setattr(
        "stock_data.data_provider.persistence.stock_list.get_stock_name",
        fake_get_stock_name,
    )

    from fastapi.testclient import TestClient

    return TestClient(app)


def test_catalog_endpoint_lists_all_indicators(client):
    r = client.get("/api/v1/indicators")
    assert r.status_code == 200
    body = r.json()
    assert "indicators" in body
    assert len(body["indicators"]) == 14
    keys = {entry["key"] for entry in body["indicators"]}
    assert keys == {
        "ma",
        "macd",
        "boll",
        "kdj",
        "rsi",
        "wr",
        "bias",
        "cci",
        "atr",
        "obv",
        "roc",
        "dmi",
        "sar",
        "kc",
    }
    # Each entry has the expected fields
    for entry in body["indicators"]:
        assert "input_shape" in entry
        assert "default_options" in entry
        assert "output_columns" in entry
        assert "default_lookback" in entry


def test_history_default_no_indicators(client):
    start, end = _window(30)
    r = client.get(f"/api/v1/stocks/600519/kline?start_date={start}&end_date={end}")
    assert r.status_code == 200
    body = r.json()
    assert body["code"] == "600519"
    # calendar window → trading bars inside it (no padding, no tail-N)
    assert len(body["data"]) == _bars_in_user_window(30)
    # No indicators requested -> indicators field is OMITTED from
    # the response entirely (model_serializer drops it when None/empty).
    for row in body["data"]:
        assert "indicators" not in row
        # amount / change_pct keep the original "null when missing"
        # semantics — always present, possibly null.
        assert "amount" in row
        assert "change_pct" in row


def test_history_with_ma_indicator(client):
    start, end = _window(30)
    r = client.get(f"/api/v1/stocks/600519/kline?start_date={start}&end_date={end}&indicators=ma")
    assert r.status_code == 200
    body = r.json()
    assert len(body["data"]) == _bars_in_user_window(30)
    # The last row should have all the MA columns in the indicators dict
    last_inds = body["data"][-1]["indicators"]
    assert "ma5" in last_inds
    assert "ma10" in last_inds
    assert "ma20" in last_inds


def test_history_with_multiple_indicators(client):
    start, end = _window(30)
    r = client.get(
        f"/api/v1/stocks/600519/kline?start_date={start}&end_date={end}&indicators=ma,macd,boll"
    )
    assert r.status_code == 200
    body = r.json()
    last_inds = body["data"][-1]["indicators"]
    assert "ma5" in last_inds
    assert "macd_dif" in last_inds
    assert "boll_mid" in last_inds


def test_history_unknown_indicator_rejected(client):
    start, end = _window(30)
    r = client.get(
        f"/api/v1/stocks/600519/kline?start_date={start}&end_date={end}&indicators=macd,nope"
    )
    assert r.status_code == 400
    body = r.json()
    assert body["detail"]["error"] == "invalid_indicator"
    assert "nope" in body["detail"]["message"]


def test_history_indicators_trigger_lookback_expansion(client):
    """When indicators need more lookback than the user window, the FETCH
    start_date moves earlier; the response still covers only the user window."""
    captured_kwargs: list[dict] = []

    def spy_get_kline_data(self, stock_code, start_date, end_date, **kwargs):
        captured_kwargs.append({"start_date": start_date, "end_date": end_date, **kwargs})
        return _synthetic_kline_between(start_date, end_date), "StubFetcher"

    import stock_data.data_provider as dp

    original = dp.DataFetcherManager.get_kline_data
    dp.DataFetcherManager.get_kline_data = spy_get_kline_data
    try:
        start, end = _window(30)
        # macd lookback = 87 bars on daily → 87 calendar days of warm-up
        r = client.get(
            f"/api/v1/stocks/600519/kline?start_date={start}&end_date={end}&indicators=macd"
        )
        assert r.status_code == 200
        # The route-level fetch used a start_date earlier than the user's
        assert captured_kwargs, "stub never saw a manager call"
        fetched = captured_kwargs[-1]
        assert fetched["start_date"] < start
        # response is still cut to the user's window
        body = r.json()
        assert len(body["data"]) == _bars_in_user_window(30)
        # and every visible bar is inside the user window
        assert all(row["date"] >= start for row in body["data"])
    finally:
        dp.DataFetcherManager.get_kline_data = original


def test_index_history_supports_indicators(client):
    """The /indices/{code}/kline endpoint accepts the same `?indicators=`
    query param as /stocks/{code}/kline. With it, the indicators dict
    appears; without it, it's omitted."""
    start, end = _window(30)
    # With indicators
    r = client.get(f"/api/v1/indices/000300/kline?start_date={start}&end_date={end}&indicators=ma")
    assert r.status_code == 200
    body = r.json()
    assert len(body["data"]) == _bars_in_user_window(30)
    last = body["data"][-1]
    # ma indicator should be computed and surfaced in indicators dict
    assert "indicators" in last
    assert "ma5" in last["indicators"]
    assert "ma30" in last["indicators"]

    # Without indicators — indicators field must be omitted
    r2 = client.get(f"/api/v1/indices/000300/kline?start_date={start}&end_date={end}")
    assert r2.status_code == 200
    last2 = r2.json()["data"][-1]
    assert "indicators" not in last2
    # amount/change_pct remain
    assert "amount" in last2
    assert "change_pct" in last2


def test_index_history_unknown_indicator_rejected(client):
    start, end = _window(30)
    r = client.get(
        f"/api/v1/indices/000300/kline?start_date={start}&end_date={end}&indicators=macd,nope"
    )
    assert r.status_code == 400
    body = r.json()
    assert body["detail"]["error"] == "invalid_indicator"
    assert "nope" in body["detail"]["message"]


# ============================================================================
# Regression: today's partial bar must feed the indicator window
# ============================================================================
#
# Before the fix these two routes raised:
#   400 | 1 validation error for KLineData
#       | indicators  Input should be a valid dictionary
#       |   [type=dict_type, input_value=nan, input_type=float]
# because _maybe_merge_today_bar appended today's row AFTER `compute()`,
# leaving the spliced row's object-dtype `indicators` cell as NaN — and
# `nan` is truthy, so it reached Pydantic instead of being treated as
# "no indicators".


@pytest.fixture
def merging_client(monkeypatch):
    """Like `client`, but with today-bar merging ACTIVE (warm calendar)."""
    from stock_data.data_provider.core.types import UnifiedRealtimeQuote

    def fake_get_kline_data(self, stock_code, start_date, end_date, **kwargs):
        return _synthetic_kline_between(start_date, end_date), "StubFetcher"

    from stock_data.server import app

    monkeypatch.setattr(
        "stock_data.data_provider.DataFetcherManager.get_kline_data",
        fake_get_kline_data,
    )
    # Warm calendar: today IS a trading day → merge runs.
    monkeypatch.setattr("stock_data.api.routes.helpers.is_trade_date", lambda day: True)
    # Deterministic realtime quote for the synthesized today bar.
    quote = UnifiedRealtimeQuote(
        code="600519",
        name="",
        price=200.0,
        open_price=198.0,
        high=201.0,
        low=197.5,
        volume=12345,
        amount=2_400_000.0,
        change_pct=1.0,
    )
    monkeypatch.setattr(
        "stock_data.data_provider.DataFetcherManager.get_realtime_quote",
        lambda self, stock_code: quote,
    )
    monkeypatch.setattr(
        "stock_data.data_provider.DataFetcherManager.get_index_realtime_quote",
        lambda self, index_code: quote,
    )
    monkeypatch.setattr(
        "stock_data.data_provider.persistence.stock_list.get_stock_name",
        lambda code, manager=None: "贵州茅台",
    )

    from fastapi.testclient import TestClient

    return TestClient(app)


def test_kline_with_indicators_and_today_merge_returns_200(merging_client):
    """The exact original failure: indicators + today bar must not 400."""
    start, end = _window(285)
    r = merging_client.get(
        f"/api/v1/stocks/600519/kline?period=daily&start_date={start}&end_date={end}&indicators=ma"
    )
    assert r.status_code == 200, r.text
    body = r.json()
    # window bars + today's partial bar (the merge adds exactly one row)
    assert len(body["data"]) == _bars_in_user_window(285) + 1
    assert body["data"][-1]["date"] == TODAY.isoformat()


def test_today_bar_indicators_include_realtime_price(merging_client):
    """Today's realtime close participates: ma5 reflects the 200.0 quote."""
    start, end = _window(10)
    r = merging_client.get(
        f"/api/v1/stocks/600519/kline?start_date={start}&end_date={end}&indicators=ma"
    )
    assert r.status_code == 200, r.text
    data = r.json()["data"]
    assert len(data) == _bars_in_user_window(10) + 1

    # Every row carries an indicators dict — no NaN, no missing key.
    assert all(isinstance(row.get("indicators"), dict) for row in data)

    today = data[-1]
    assert today["date"] == TODAY.isoformat()
    assert today["close"] == 200.0

    # ma5 must be the mean of the last 5 closes INCLUDING today's realtime
    # 200.0 — i.e. the merged bar is genuinely inside the indicator window,
    # not appended to an already-finished series.
    last5 = [row["close"] for row in data[-5:]]
    assert today["indicators"]["ma5"] == pytest.approx(sum(last5) / 5)

    # ...and that is strictly higher than a window that excludes today.
    assert today["indicators"]["ma5"] > sum(last5[:-1]) / 4


def test_index_kline_with_indicators_and_today_merge_returns_200(merging_client):
    """Index route shares the helpers — same regression coverage."""
    start, end = _window(10)
    r = merging_client.get(
        f"/api/v1/indices/000300/kline?start_date={start}&end_date={end}&indicators=ma"
    )
    assert r.status_code == 200, r.text
    data = r.json()["data"]
    assert len(data) == _bars_in_user_window(10) + 1
    assert all(isinstance(row.get("indicators"), dict) for row in data)
