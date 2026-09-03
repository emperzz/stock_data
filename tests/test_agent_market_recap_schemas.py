"""Schema smoke tests for the new MarketRecap response models."""

from stock_data.api.schemas import (
    IndexQuote,
    MarketContextResponse,
    MarketRecapErrorEntry,
    MarketRecapIndicesBlock,
    MarketRecapResponse,
    MarketStatsResponse,
)


def test_market_recap_indices_block_accepts_three_quotes():
    block = MarketRecapIndicesBlock(
        sh=IndexQuote(code="000001", change_pct=1.2),
        shenzhen_composite=IndexQuote(code="399001", change_pct=0.5),
        chinext=IndexQuote(code="399006", change_pct=-0.3),
    )
    assert block.sh.code == "000001"
    assert block.shenzhen_composite.code == "399001"
    assert block.chinext.code == "399006"


def test_market_recap_indices_block_defaults_to_all_none():
    block = MarketRecapIndicesBlock()
    assert block.sh is None
    assert block.shenzhen_composite is None
    assert block.chinext is None


def test_market_recap_error_entry_accepts_all_block_literals():
    for block_literal in (
        "context",
        "stats",
        "indices.sh",
        "indices.shenzhen_composite",
        "indices.chinext",
    ):
        entry = MarketRecapErrorEntry(block=block_literal, error="X", message="Y")  # type: ignore[arg-type]
        assert entry.block == block_literal


def test_market_recap_response_constructs_with_minimum_required_fields():
    # Stub the inner models with empty bodies — the test only checks shape composition.
    ctx = MarketContextResponse.model_construct(
        trade_date="2026-09-03",
        is_trade_day=True,
        market_session="intraday",
        messages=None,
        summary={"requested": 1, "ok": 1, "failed": 0, "elapsed_ms": 10},
    )
    stats = MarketStatsResponse.model_construct(
        stocks=None,
        boards=None,
        limit_pools=None,
        errors=[],
        summary={"requested": 1, "ok": 1, "failed": 0, "elapsed_ms": 10},
    )
    resp = MarketRecapResponse(
        context=ctx,
        stats=stats,
        indices=MarketRecapIndicesBlock(),
        summary={"requested": 5, "ok": 5, "failed": 0, "elapsed_ms": 100},
    )
    assert resp.errors == []
    assert resp.indices.sh is None
    assert resp.summary["ok"] == 5
