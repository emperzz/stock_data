"""Tests for StockQuote schema behavior.

Covers three pieces added 2026-07-30:

1. ``update_time`` field removed from ``StockQuote`` — was always
   None in practice (no upstream fetcher populated it) and only
   contributed to bloat.
2. ``_nested`` flag (set via ``from_unified_quote(..., nested=True)``)
   drops ``code`` / ``name`` / ``source`` from the serialized JSON.
   Top-level callers (default ``nested=False``) keep them; nested
   callers (``/stocks?include_quote=true`` → ``StockInfo.quote``) drop them.
3. ``amplitude_pct`` fallback: when upstream didn't carry ``amplitude``
   but ``high`` / ``low`` / ``pre_close`` are all available, compute
   ``(high - low) / pre_close * 100``. Same formula YfinanceFetcher uses.
"""

import pytest

from stock_data.api.schemas import StockQuote
from stock_data.data_provider.core.types import (
    RealtimeSource,
    UnifiedRealtimeQuote,
)


def _make_quote(**overrides) -> UnifiedRealtimeQuote:
    """Build a UnifiedRealtimeQuote with sensible defaults for testing."""
    defaults: dict = {
        "code": "600519",
        "name": "贵州茅台",
        "source": RealtimeSource.AKSHARE,
        "price": 1700.0,
        "pre_close": 1650.0,
        "open_price": 1660.0,
        "high": 1710.0,
        "low": 1655.0,
        "change_pct": 3.03,
        "change_amount": 50.0,
        "volume": 1_000_000,
        "amount": 1_700_000_000,
        "turnover_rate": 0.5,
        "amplitude": None,  # default: upstream omitted, force fallback path
        "volume_ratio": 1.2,
        "pe_ratio": 30.0,
        "pb_ratio": 10.0,
        "total_mv": 2.0e12,
        "circ_mv": 2.0e12,
    }
    defaults.update(overrides)
    return UnifiedRealtimeQuote(**defaults)


class TestStockQuoteNestedFlag:
    """``nested=True`` drops code/name/source; default keeps them."""

    def test_top_level_includes_identifiers(self):
        """Default (nested=False) keeps code/name/source in JSON."""
        q = _make_quote()
        sq = StockQuote.from_unified_quote(q)
        d = sq.model_dump()
        assert d["code"] == "600519"
        assert d["name"] == "贵州茅台"
        assert d["source"] == "akshare"

    def test_nested_drops_identifiers(self):
        """nested=True drops code/name/source from JSON."""
        q = _make_quote()
        sq = StockQuote.from_unified_quote(q, nested=True)
        d = sq.model_dump()
        assert "code" not in d
        assert "name" not in d
        assert "source" not in d

    def test_nested_keeps_other_quote_fields(self):
        """nested=True only drops identifiers — every other field survives."""
        q = _make_quote()
        sq = StockQuote.from_unified_quote(q, nested=True)
        d = sq.model_dump()
        # Spot-check a representative slice of the remaining fields
        for key in (
            "current_price", "open", "high", "low", "prev_close",
            "volume", "volume_unit", "amount", "pe_ttm", "pb",
            "mcap_yi", "float_mcap_yi", "turnover_pct", "volume_ratio",
        ):
            assert key in d, f"nested quote must keep {key}"

    def test_nested_toggle_is_per_instance(self):
        """Two instances built with different ``nested`` flags don't bleed."""
        q = _make_quote()
        top = StockQuote.from_unified_quote(q)
        nested = StockQuote.from_unified_quote(q, nested=True)
        assert "code" in top.model_dump()
        assert "code" not in nested.model_dump()


class TestUpdateTimeRemoved:
    """``update_time`` field is gone from StockQuote."""

    def test_update_time_field_absent(self):
        q = _make_quote()
        sq = StockQuote.from_unified_quote(q)
        assert "update_time" not in sq.model_dump()

    def test_update_time_not_in_top_level(self):
        q = _make_quote()
        sq = StockQuote.from_unified_quote(q, nested=False)
        assert "update_time" not in sq.model_dump()

    def test_update_time_not_in_nested(self):
        q = _make_quote()
        sq = StockQuote.from_unified_quote(q, nested=True)
        assert "update_time" not in sq.model_dump()


class TestAmplitudePctDerivation:
    """amplitude_pct is derived from high/low/pre_close when upstream omits."""

    def test_derived_when_upstream_omits_amplitude(self):
        """amplitude=None + high/low/pre_close all set → compute (h-l)/prev_close*100."""
        q = _make_quote(amplitude=None, high=1710.0, low=1655.0, pre_close=1650.0)
        sq = StockQuote.from_unified_quote(q)
        assert sq.model_dump()["amplitude_pct"] == pytest.approx(3.3333, rel=1e-3)

    def test_upstream_value_preserved(self):
        """When upstream carries amplitude, derived formula does NOT override."""
        q = _make_quote(amplitude=99.99)
        sq = StockQuote.from_unified_quote(q)
        assert sq.model_dump()["amplitude_pct"] == 99.99

    def test_no_derivation_when_pre_close_is_zero(self):
        """Guard against division-by-zero: pre_close=0 → None."""
        q = _make_quote(amplitude=None, pre_close=0.0, high=10.0, low=9.0)
        sq = StockQuote.from_unified_quote(q)
        assert sq.model_dump()["amplitude_pct"] is None

    def test_no_derivation_when_high_is_none(self):
        """high=None → can't compute → None."""
        q = _make_quote(amplitude=None, high=None, low=9.0, pre_close=10.0)
        sq = StockQuote.from_unified_quote(q)
        assert sq.model_dump()["amplitude_pct"] is None

    def test_no_derivation_when_low_is_none(self):
        """low=None → can't compute → None."""
        q = _make_quote(amplitude=None, high=10.0, low=None, pre_close=10.0)
        sq = StockQuote.from_unified_quote(q)
        assert sq.model_dump()["amplitude_pct"] is None

    def test_amplitude_pct_present_in_nested(self):
        """Derived value is still serialized in nested mode."""
        q = _make_quote(amplitude=None)
        sq = StockQuote.from_unified_quote(q, nested=True)
        d = sq.model_dump()
        assert "amplitude_pct" in d
        assert d["amplitude_pct"] == pytest.approx(3.3333, rel=1e-3)


class TestRouteLevelNested:
    """End-to-end: /stocks?include_quote=true emits nested quotes without identifiers."""

    def test_list_stocks_quote_drops_identifiers(self, monkeypatch):
        """`GET /stocks?market=csi&include_quote=true` → each row's `quote`
        object does NOT contain `code` / `name` / `source`, but the outer
        `StockInfo` envelope does."""
        from fastapi.testclient import TestClient

        from stock_data.api.cache import get_stock_list_quote_cache
        from stock_data.api.routes import reset_manager
        from stock_data.server import app

        reset_manager()
        get_stock_list_quote_cache().clear()

        from stock_data.data_provider.core.types import (
            RealtimeSource,
            UnifiedRealtimeQuote,
        )

        fake_quotes = [
            UnifiedRealtimeQuote(
                code="600519", name="贵州茅台",
                source=RealtimeSource.AKSHARE, price=1680.5,
                change_pct=1.23, amount=2.07e8,
                turnover_rate=0.5, total_mv=2.16e12,
                high=1700.0, low=1660.0, pre_close=1650.0,
            ),
        ]

        from stock_data.api.routes.helpers import get_manager
        mgr = get_manager()
        monkeypatch.setattr(mgr, "get_realtime_quotes",
                            lambda market: (fake_quotes, "akshare"))

        client = TestClient(app)
        response = client.get("/api/v1/stocks?market=csi&include_quote=true&limit=10")
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        row = data[0]
        # Outer envelope carries identifiers (unchanged contract)
        assert row["code"] == "600519"
        assert row["name"] == "贵州茅台"
        assert row["source"] == "akshare"
        # Nested quote drops them
        quote = row["quote"]
        assert "code" not in quote
        assert "name" not in quote
        assert "source" not in quote
        # Spot-check non-identifier fields survive
        assert quote["current_price"] == 1680.5
        assert "amplitude_pct" in quote  # derived: (1700-1660)/1650*100 ≈ 2.4242
        assert "update_time" not in quote
