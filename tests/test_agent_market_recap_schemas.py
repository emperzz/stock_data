"""Schema smoke tests for the new MarketRecap response models."""

from stock_data.api.schemas import (
    IndexQuote,
    MarketContextResponse,
    MarketRecapErrorEntry,
    MarketRecapIndicesBlock,
    MarketRecapResponse,
    MarketStatsResponse,
)

from stock_data.api.cache import make_market_recap_cache_key
from stock_data.api.routes.agent import (
    _index_quote_from_unified,
    build_market_context_response,
    build_market_stats_response,
)
from stock_data.data_provider.core.types import RealtimeSource, UnifiedRealtimeQuote


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


def test_make_market_recap_cache_key_format():
    key = make_market_recap_cache_key(20, True, True)
    assert key == "agent_market_recap:20:True:True"


def test_make_market_recap_cache_key_changes_with_each_param():
    base = make_market_recap_cache_key(20, True, True)
    assert make_market_recap_cache_key(40, True, True) != base
    assert make_market_recap_cache_key(20, False, True) != base
    assert make_market_recap_cache_key(20, True, False) != base


def test_build_market_context_response_returns_model(monkeypatch):
    """Smoke test: the helper returns a MarketContextResponse for valid inputs."""
    from stock_data.api.routes import agent as agent_mod

    class _FakeManager:
        def get_morning_briefing(self, _date):
            return (None, "ths")

        def get_market_recap(self, _date):
            return (None, "ths")

        def get_flash_news(self, *, limit):
            return ([], "ths")

    monkeypatch.setattr(agent_mod, "get_manager", lambda: _FakeManager())

    result = build_market_context_response(
        flash_limit=20, target_date="2026-09-03", today_str="2026-09-03"
    )
    assert isinstance(result, MarketContextResponse)
    assert result.trade_date == "2026-09-03"
    # is_trade_day is whatever trade_calendar.is_trade_date(today_str) returns;
    # the test DB may be cold, so accept either bool. The helper's contract is
    # to delegate, not to assert — the date semantics are tested upstream.
    assert isinstance(result.is_trade_day, bool)
    assert result.market_session in {"pre-market", "intraday", "post-market", "closed"}
    assert result.messages.morning_briefing is None
    assert result.messages.market_recap is None
    assert result.messages.flash_news == []
    assert result.summary["requested"] == 3


def test_build_market_stats_response_returns_model(monkeypatch):
    """Smoke test: the helper returns a MarketStatsResponse for valid inputs."""
    from stock_data.api.routes import agent as agent_mod

    class _FakeManager:
        def get_realtime_quotes(self, market):
            return ([], "akshare")

    monkeypatch.setattr(agent_mod, "get_manager", lambda: _FakeManager())
    # Patch the `stock_board_cache` symbol as bound on agent_mod (it's
    # imported into agent.py's namespace at module load; the helper resolves
    # it as a free variable via the module globals).
    monkeypatch.setattr(
        agent_mod.stock_board_cache, "get_board_list", lambda **kwargs: ([], "ths")
    )

    result = build_market_stats_response(
        include_boards=True, include_pools=False, target_date="2026-09-03"
    )
    assert isinstance(result, MarketStatsResponse)
    assert result.summary["requested"] == 2  # stocks + boards (no pools)
    assert result.limit_pools.zt is None
    assert result.limit_pools.dt is None


def test_index_quote_from_unified_none_input():
    assert _index_quote_from_unified("000001", None) is None


def test_index_quote_from_unified_populates_all_fields():
    # UnifiedRealtimeQuote field names differ from IndexQuote — see
    # `stock_data/data_provider/core/types.py:56-100`. Notably:
    #   open_price (not open), pre_close (not prev_close),
    #   source is RealtimeSource enum, no update_time field.
    q = UnifiedRealtimeQuote(
        code="000001",
        name="上证综指",
        source=RealtimeSource.AKSHARE,
        price=3245.67,
        change_amount=12.34,
        change_pct=0.38,
        open_price=3230.0,
        high=3255.0,
        low=3228.0,
        pre_close=3233.33,
        volume=350_000_000,
        amount=4.5e10,
    )
    out = _index_quote_from_unified("000001", q)
    assert isinstance(out, IndexQuote)
    assert out.code == "000001"
    assert out.name == "上证综指"
    assert out.source == "akshare"  # .value of RealtimeSource.AKSHARE
    assert out.current_price == 3245.67
    assert out.change_pct == 0.38
    assert out.open == 3230.0
    assert out.prev_close == 3233.33
    assert out.volume == 350_000_000
    assert out.volume_unit == "share"
    assert out.amount == 4.5e10
    assert out.update_time is None  # always None on recap path


def test_index_quote_from_unified_handles_missing_fields():
    """All optional fields default to None / empty / 0.0 — no raises."""
    q = UnifiedRealtimeQuote(code="000001")  # only required field
    out = _index_quote_from_unified("000001", q)
    assert isinstance(out, IndexQuote)
    assert out.name == ""
    assert out.source == ""
    assert out.current_price == 0.0
    assert out.change_pct is None
    assert out.volume is None
    assert out.volume_unit == "share"
    assert out.update_time is None
