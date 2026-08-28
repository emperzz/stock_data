"""Unit tests for the two MinimalQuote builder helpers and the schema."""

import pytest

from stock_data.api.schemas import MinimalQuote
from stock_data.data_provider.core.types import RealtimeSource, UnifiedRealtimeQuote


class TestMinimalQuoteSchema:
    def test_all_fields_constructable_with_just_required(self):
        """All new fields are Optional; the bare-class instance must
        validate against `None` defaults."""
        q = MinimalQuote()
        assert q.price is None
        assert q.change_pct is None
        assert q.change_amount is None
        assert q.open is None
        assert q.high is None
        assert q.low is None
        assert q.prev_close is None
        assert q.volume is None
        assert q.volume_unit == "share"
        assert q.amount is None
        assert q.turnover_pct is None
        assert q.amplitude_pct is None
        assert q.volume_ratio is None
        assert q.pe_ratio is None
        assert q.pb_ratio is None
        assert q.mcap_yi is None
        assert q.float_mcap_yi is None
        assert q.limit_up is None
        assert q.limit_down is None
        assert q.up_count is None
        assert q.down_count is None
        assert q.net_inflow is None
        assert q.rank is None

    def test_volume_unit_default_is_share(self):
        """The default MUST be "share" — matches KLineData.volume_unit
        invariant (spec §3.4). Board callers override to "wan_shou"."""
        assert MinimalQuote().volume_unit == "share"

    def test_full_population_serializes_all_keys(self):
        q = MinimalQuote(
            price=12.34, change_pct=1.23, change_amount=0.15,
            open=12.20, high=12.40, low=12.10, prev_close=12.19,
            volume=1_234_567, volume_unit="share",
            amount=205_000_000.0,
            turnover_pct=0.45, amplitude_pct=2.11, volume_ratio=1.20,
            pe_ratio=25.3, pb_ratio=8.7,
            mcap_yi=21_123.5, float_mcap_yi=21_000.1,
            limit_up=13.41, limit_down=11.10,
            up_count=None, down_count=None, net_inflow=None, rank=None,
        )
        dumped = q.model_dump()
        # every field the spec promises is present (even None)
        expected_keys = {
            "price", "change_pct", "change_amount",
            "open", "high", "low", "prev_close",
            "volume", "volume_unit", "amount",
            "turnover_pct", "amplitude_pct", "volume_ratio",
            "pe_ratio", "pb_ratio", "mcap_yi", "float_mcap_yi",
            "limit_up", "limit_down",
            "up_count", "down_count", "net_inflow", "rank",
        }
        assert expected_keys <= dumped.keys()


def _mk_unified(**overrides) -> UnifiedRealtimeQuote:
    """Build a fully-populated UnifiedRealtimeQuote for tests."""
    base = dict(
        code="600519",
        name="贵州茅台",
        source=RealtimeSource.ZZSHARE,
        price=1680.0,
        change_pct=1.23,
        change_amount=20.4,
        volume=12_345_678,
        volume_unit="share",
        amount=2_050_000_000.0,
        volume_ratio=1.2,
        turnover_rate=0.45,
        amplitude=2.11,
        open_price=1660.0,
        high=1690.0,
        low=1655.0,
        pre_close=1659.6,
        limit_up=1825.56,
        limit_down=1493.64,
        pe_ratio=25.3,
        pb_ratio=8.7,
        total_mv=2_112_350_000_000.0,
        circ_mv=2_100_010_000_000.0,
    )
    base.update(overrides)
    return UnifiedRealtimeQuote(**base)


class TestBuildMinimalQuoteFromUnified:
    def test_all_fields_populated(self):
        from stock_data.api.routes.agent import _build_minimal_quote_from_unified

        q = _build_minimal_quote_from_unified(_mk_unified())
        assert q.price == 1680.0
        assert q.change_pct == 1.23
        assert q.change_amount == 20.4
        assert q.open == 1660.0
        assert q.high == 1690.0
        assert q.low == 1655.0
        assert q.prev_close == 1659.6
        assert q.volume == 12_345_678
        assert q.volume_unit == "share"
        assert q.amount == 2_050_000_000.0  # 元 pass-through
        assert q.turnover_pct == 0.45
        assert q.amplitude_pct == 2.11
        assert q.volume_ratio == 1.2
        assert q.pe_ratio == 25.3
        assert q.pb_ratio == 8.7
        assert q.mcap_yi == pytest.approx(21_123.5)
        assert q.float_mcap_yi == pytest.approx(21_000.1)
        assert q.limit_up == 1825.56
        assert q.limit_down == 1493.64
        # board-only fields stay None on stock/index
        assert q.up_count is None
        assert q.down_count is None
        assert q.net_inflow is None
        assert q.rank is None

    def test_amplitude_fallback_when_upstream_missing(self):
        from stock_data.api.routes.agent import _build_minimal_quote_from_unified

        q = _build_minimal_quote_from_unified(_mk_unified(amplitude=None))
        expected = (1690.0 - 1655.0) / 1659.6 * 100
        assert q.amplitude_pct == pytest.approx(expected, rel=1e-6)

    def test_amplitude_fallback_skipped_when_prev_close_zero(self):
        """Defense-in-depth: don't divide by zero."""
        from stock_data.api.routes.agent import _build_minimal_quote_from_unified

        q = _build_minimal_quote_from_unified(_mk_unified(amplitude=None, pre_close=0.0))
        assert q.amplitude_pct is None

    def test_mcap_yi_divided_by_1e8(self):
        from stock_data.api.routes.agent import _build_minimal_quote_from_unified

        q = _build_minimal_quote_from_unified(
            _mk_unified(total_mv=123_456_789_012.0, circ_mv=987_654_321_098.0)
        )
        assert q.mcap_yi == pytest.approx(1234.56789012)
        assert q.float_mcap_yi == pytest.approx(9876.54321098)

    def test_none_fields_pass_through(self):
        from stock_data.api.routes.agent import _build_minimal_quote_from_unified

        bare = UnifiedRealtimeQuote(code="600519", source=RealtimeSource.AKSHARE)
        q = _build_minimal_quote_from_unified(bare)
        assert q.price is None
        assert q.change_pct is None
        assert q.change_amount is None
        assert q.open is None
        assert q.high is None
        assert q.low is None
        assert q.prev_close is None
        assert q.volume is None
        assert q.volume_unit == "share"  # default fallback when q.volume_unit is ""
        assert q.amount is None
        assert q.turnover_pct is None
        assert q.amplitude_pct is None
        assert q.volume_ratio is None
        assert q.pe_ratio is None
        assert q.pb_ratio is None
        assert q.mcap_yi is None
        assert q.float_mcap_yi is None
        assert q.limit_up is None
        assert q.limit_down is None

    def test_volume_unit_falls_back_to_share_when_empty(self):
        from stock_data.api.routes.agent import _build_minimal_quote_from_unified

        q = _build_minimal_quote_from_unified(_mk_unified(volume_unit=""))
        assert q.volume_unit == "share"
