"""Endpoint tests for GET /api/v1/agent/market-recap."""

import pytest
from fastapi.testclient import TestClient

from stock_data.api.cache import get_quote_cache, make_market_recap_cache_key
from stock_data.api.routes import agent as agent_mod
from stock_data.api.schemas import (
    IndexQuote,
    MarketContextMessages,
    MarketContextResponse,
    MarketRecapIndicesBlock,
    MarketStatsResponse,
)


@pytest.fixture(autouse=True)
def _clear_market_recap_cache():
    """Ensure each test starts with a clean 60s cache window."""
    cache_key = make_market_recap_cache_key(20, True, True)
    get_quote_cache().pop(cache_key, None)
    yield


def _ctx_stub():
    # Use a real MarketContextMessages (NOT None) so the response carries
    # the messages sub-object end-to-end. A `None` here makes
    # render_market_context_as_md raise and silently fall through to the
    # JSON-fallback in `_render_markdown`, which would mask regressions.
    return MarketContextResponse.model_construct(
        trade_date="2026-09-03",
        is_trade_day=True,
        market_session="intraday",
        messages=MarketContextMessages(
            morning_briefing=None, market_recap=None, flash_news=[]
        ),
        summary={"requested": 3, "ok": 3, "failed": 0, "elapsed_ms": 10},
    )


def _stats_stub():
    return MarketStatsResponse.model_construct(
        stocks=None,
        boards=None,
        limit_pools=None,
        errors=[],
        summary={"requested": 1, "ok": 1, "failed": 0, "elapsed_ms": 10},
    )


def test_market_recap_happy_path(monkeypatch):
    """All 5 sub-blocks OK → 200, all populated, errors empty, summary.ok == 5."""
    from stock_data.server import app

    # Stub the two extracted builders + the index helper
    monkeypatch.setattr(agent_mod, "build_market_context_response", lambda **_: _ctx_stub())
    monkeypatch.setattr(agent_mod, "build_market_stats_response", lambda **_: _stats_stub())
    monkeypatch.setattr(
        agent_mod,
        "_build_three_index_quotes_block",
        lambda mgr: (
            MarketRecapIndicesBlock(
                sh=IndexQuote(code="000001", change_pct=0.5),
                shenzhen_composite=IndexQuote(code="399001", change_pct=1.2),
                chinext=IndexQuote(code="399006", change_pct=-0.3),
            ),
            [],
        ),
    )

    client = TestClient(app)
    resp = client.get("/api/v1/agent/market-recap")
    assert resp.status_code == 200
    body = resp.json()
    assert body["errors"] == []
    assert body["summary"]["ok"] == 5
    assert body["indices"]["sh"]["code"] == "000001"
    assert body["indices"]["shenzhen_composite"]["code"] == "399001"
    assert body["indices"]["chinext"]["code"] == "399006"


def test_market_recap_context_block_fails_others_ok(monkeypatch):
    """context builder raises → response still 200, context field is the null stub,
    errors[] has {block: 'context'}, other blocks still populated."""
    from stock_data.server import app

    def _raise(**_):
        raise RuntimeError("context boom")

    monkeypatch.setattr(agent_mod, "build_market_context_response", _raise)
    monkeypatch.setattr(agent_mod, "build_market_stats_response", lambda **_: _stats_stub())
    monkeypatch.setattr(
        agent_mod,
        "_build_three_index_quotes_block",
        lambda mgr: (
            MarketRecapIndicesBlock(
                sh=IndexQuote(code="000001"),
                shenzhen_composite=IndexQuote(code="399001"),
                chinext=IndexQuote(code="399006"),
            ),
            [],
        ),
    )

    client = TestClient(app)
    resp = client.get("/api/v1/agent/market-recap")
    assert resp.status_code == 200
    body = resp.json()
    assert any(e["block"] == "context" for e in body["errors"])
    assert body["summary"]["failed"] == 1
    # context is the null stub (requested==0), stats + indices are real
    assert body["context"]["summary"]["requested"] == 0
    assert body["stats"]["summary"]["requested"] == 1
    assert body["indices"]["sh"]["code"] == "000001"


def test_market_recap_index_failure_isolated(monkeypatch):
    """_build_three_index_quotes_block returns (block, errors) with one error;
    that index is null, others populated, response is 200."""
    from stock_data.server import app

    monkeypatch.setattr(agent_mod, "build_market_context_response", lambda **_: _ctx_stub())
    monkeypatch.setattr(agent_mod, "build_market_stats_response", lambda **_: _stats_stub())

    def _fake_block(_mgr):
        return (
            MarketRecapIndicesBlock(
                sh=IndexQuote(code="000001"),
                shenzhen_composite=None,  # <-- the failed one
                chinext=IndexQuote(code="399006"),
            ),
            [
                agent_mod.MarketRecapErrorEntry(
                    block="indices.shenzhen_composite",
                    error="DataFetchError",
                    message="upstream timeout",
                )
            ],
        )

    monkeypatch.setattr(agent_mod, "_build_three_index_quotes_block", _fake_block)

    client = TestClient(app)
    resp = client.get("/api/v1/agent/market-recap")
    assert resp.status_code == 200
    body = resp.json()
    assert body["indices"]["sh"]["code"] == "000001"
    assert body["indices"]["shenzhen_composite"] is None
    assert body["indices"]["chinext"]["code"] == "399006"
    assert any(
        e["block"] == "indices.shenzhen_composite" for e in body["errors"]
    )


def test_market_recap_cache_hit_skips_fanout(monkeypatch):
    """Second call within TTL reuses the cached response; the underlying builders
    are NOT invoked a second time."""
    from stock_data.server import app

    call_counts = {"context": 0, "stats": 0, "indices": 0}

    def _counted_ctx(**_):
        call_counts["context"] += 1
        return _ctx_stub()

    def _counted_stats(**_):
        call_counts["stats"] += 1
        return _stats_stub()

    def _counted_indices(_mgr):
        call_counts["indices"] += 1
        return (
            MarketRecapIndicesBlock(
                sh=IndexQuote(code="000001"),
                shenzhen_composite=IndexQuote(code="399001"),
                chinext=IndexQuote(code="399006"),
            ),
            [],
        )

    monkeypatch.setattr(agent_mod, "build_market_context_response", _counted_ctx)
    monkeypatch.setattr(agent_mod, "build_market_stats_response", _counted_stats)
    monkeypatch.setattr(agent_mod, "_build_three_index_quotes_block", _counted_indices)

    # Two consecutive calls — first misses + populates the cache, second hits.
    # The 3-segment cache key (no trade_date) makes the hit deterministic.
    client = TestClient(app)
    r1 = client.get("/api/v1/agent/market-recap")
    r2 = client.get("/api/v1/agent/market-recap")
    assert r1.status_code == 200
    assert r2.status_code == 200
    assert call_counts["context"] == 1
    assert call_counts["stats"] == 1
    assert call_counts["indices"] == 1


def test_market_recap_md_format_no_field_drop(monkeypatch):
    """`?format=md` must include every JSON field name from the response."""
    from stock_data.server import app

    monkeypatch.setattr(agent_mod, "build_market_context_response", lambda **_: _ctx_stub())
    monkeypatch.setattr(agent_mod, "build_market_stats_response", lambda **_: _stats_stub())
    monkeypatch.setattr(
        agent_mod,
        "_build_three_index_quotes_block",
        lambda mgr: (
            MarketRecapIndicesBlock(
                sh=IndexQuote(code="000001", name="上证综指", change_pct=0.5, amount=1.0),
                shenzhen_composite=IndexQuote(code="399001", name="深证成指", change_pct=1.2, amount=2.0),
                chinext=IndexQuote(code="399006", name="创业板指", change_pct=-0.3, amount=3.0),
            ),
            [],
        ),
    )

    client = TestClient(app)
    resp = client.get("/api/v1/agent/market-recap?format=md")
    assert resp.status_code == 200
    md = resp.text

    # CLAUDE.md `?format=md` "no field dropped" contract: data values must
    # be present in MD. The renderer uses Chinese section headings for the
    # sub-blocks (市场全景 / 市场全量统计 / 指数快讯) rather than the English
    # JSON field names — that's the established convention for context/stats
    # sub-renderers. What we DO require verbatim:
    # 1. All 14 IndexQuote columns in the indices table (per spec §3.5).
    # 2. The 3 index codes + Chinese names from the input.
    # 3. Section headings ("市场全景", "市场全量统计", "指数快讯") + summary keys.
    index_cols = [
        "code", "name", "source", "current_price", "change_amount",
        "change_pct", "open", "high", "low", "prev_close",
        "volume", "volume_unit", "amount", "update_time",
    ]
    section_markers = ["市场全景", "市场全量统计", "指数快讯"]
    summary_keys = ["requested", "ok", "failed", "elapsed"]
    data_values = [
        "000001", "399001", "399006",
        "上证综指", "深证成指", "创业板指",
    ]

    missing_cols = [c for c in index_cols if c not in md]
    assert not missing_cols, f"IndexQuote columns missing from MD: {missing_cols}"

    missing_sections = [s for s in section_markers if s not in md]
    assert not missing_sections, f"Section headings missing: {missing_sections}"

    missing_summary = [k for k in summary_keys if k not in md]
    assert not missing_summary, f"Summary keys missing: {missing_summary}"

    missing_data = [d for d in data_values if d not in md]
    assert not missing_data, f"Data values missing: {missing_data}"
