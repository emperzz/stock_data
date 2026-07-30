"""Unit + integration tests for stock_data.data_provider.persistence.board.

Added 2026-07-30: _project_unified_quote_to_dict helper unit tests
(spec 2026-07-30, plan task 1).
"""
import pytest

from stock_data.data_provider.core.types import (
    RealtimeSource,
    UnifiedRealtimeQuote,
)


def _q(**overrides) -> UnifiedRealtimeQuote:
    """Build a UnifiedRealtimeQuote with sensible defaults."""
    defaults = dict(
        code="600519",
        name="贵州茅台",
        source=RealtimeSource.ZZSHARE,
        price=1700.0,
        change_pct=1.5,
        change_amount=25.0,
        volume=1000000,
        amount=1.7e9,
        volume_ratio=1.2,
        turnover_rate=0.5,
        amplitude=2.0,
        open_price=1680.0,
        high=1710.0,
        low=1675.0,
        pre_close=1675.0,
        pe_ratio=30.0,
    )
    defaults.update(overrides)
    return UnifiedRealtimeQuote(**defaults)


class TestProjectUnifiedQuoteToDict:
    """Tests for the suffix-quote projection helper (spec 2026-07-30)."""

    def test_returns_upstream_style_keys(self):
        """Result uses fetcher-style keys (stock_code/stock_name/turnover_rate/
        amplitude), NOT BoardStockInfo model field names (code/name/
        turnover_pct/amplitude_pct). This is the contract that keeps
        update_cached_board_stocks happy."""
        from stock_data.data_provider.persistence import board as pb

        q = _q()
        d = pb._project_unified_quote_to_dict("600519", "贵州茅台", q)
        # stock_code/stock_name (NOT code/name)
        assert d["stock_code"] == "600519"
        assert d["stock_name"] == "贵州茅台"
        assert "code" not in d
        assert "name" not in d
        # turnover_rate (NOT turnover_pct)
        assert d["turnover_rate"] == 0.5
        assert "turnover_pct" not in d
        # amplitude (NOT amplitude_pct)
        assert d["amplitude"] == 2.0
        assert "amplitude_pct" not in d
        # 4 new fields use their own names
        assert d["open"] == 1680.0
        assert d["high"] == 1710.0
        assert d["low"] == 1675.0
        assert d["prev_close"] == 1675.0
        # 7 other quote fields
        assert d["price"] == 1700.0
        assert d["change_pct"] == 1.5
        assert d["change_amount"] == 25.0
        assert d["volume"] == 1000000
        assert d["amount"] == 1.7e9
        assert d["volume_ratio"] == 1.2
        assert d["pe_ratio"] == 30.0

    def test_amplitude_fallback_when_unified_amplitude_is_none(self):
        """q.amplitude=None, high/low/pre_close set → fallback computes amplitude."""
        from stock_data.data_provider.persistence import board as pb

        q = _q(amplitude=None)
        d = pb._project_unified_quote_to_dict("600519", "贵州茅台", q)
        # (1710 - 1675) / 1675 * 100 ≈ 2.0896
        assert d["amplitude"] == pytest.approx(2.0896, rel=1e-3)

    def test_amplitude_none_when_no_fallback_inputs(self):
        """q.amplitude=None and high/low/pre_close missing → dict["amplitude"]=None."""
        from stock_data.data_provider.persistence import board as pb

        q = _q(amplitude=None, high=None, low=None, pre_close=None)
        d = pb._project_unified_quote_to_dict("600519", "贵州茅台", q)
        assert d["amplitude"] is None

    def test_amplitude_passthrough_when_unified_amplitude_set(self):
        """q.amplitude already set → use it directly, do not recompute."""
        from stock_data.data_provider.persistence import board as pb

        q = _q(amplitude=3.5)
        d = pb._project_unified_quote_to_dict("600519", "贵州茅台", q)
        assert d["amplitude"] == 3.5

    def test_ths_only_fields_not_in_dict(self):
        """change_speed / free_float_shares / float_market_cap must NOT appear
        in the dict (they're absent, not None). The route layer's
        _build_board_stock_info reads s.get('change_speed') → default None."""
        from stock_data.data_provider.persistence import board as pb

        q = _q()
        d = pb._project_unified_quote_to_dict("600519", "贵州茅台", q)
        for k in (
            "change_speed", "free_float_shares", "float_market_cap",
            "is_limit_up", "lb_count",
        ):
            assert k not in d

    def test_name_fallback_to_quote_name_when_param_empty(self):
        """name param empty → fallback to q.name."""
        from stock_data.data_provider.persistence import board as pb

        q = _q(name="茅台")
        d = pb._project_unified_quote_to_dict("600519", "", q)
        assert d["stock_name"] == "茅台"

    def test_param_name_wins_over_quote_name(self):
        """name param set → use it (preserves upstream board member name)."""
        from stock_data.data_provider.persistence import board as pb

        q = _q(name="Moutai")
        d = pb._project_unified_quote_to_dict("600519", "贵州茅台", q)
        assert d["stock_name"] == "贵州茅台"
