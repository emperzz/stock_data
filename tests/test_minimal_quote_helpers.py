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


class TestBuildMinimalQuoteFromBoardDict:
    def test_populated_fields(self):
        from stock_data.api.routes.agent import _build_minimal_quote_from_board_dict

        raw = {
            "price": 1234.5,
            "change_pct": 1.23,
            "change_amount": 15.0,
            "open": 1230.0,
            "high": 1240.0,
            "low": 1225.0,
            "prev_close": 1219.5,
            "volume": 15343,  # 万手 (int-truncated upstream)
            "amount": 12.5,  # 亿元 upstream
            "up_count": 12,
            "down_count": 5,
            "net_inflow": 1.23,  # 亿元
            "rank": "229/389",
        }
        q = _build_minimal_quote_from_board_dict(raw)
        assert q.price == 1234.5
        assert q.change_pct == 1.23
        assert q.change_amount == 15.0
        assert q.open == 1230.0
        assert q.high == 1240.0
        assert q.low == 1225.0
        assert q.prev_close == 1219.5
        assert q.volume == 15343
        assert q.volume_unit == "wan_shou"
        assert q.amount == pytest.approx(12.5 * 1e8)  # 1.25e9
        assert q.up_count == 12
        assert q.down_count == 5
        assert q.net_inflow == 1.23
        assert q.rank == "229/389"
        # stock-only fields stay None on board
        assert q.turnover_pct is None
        assert q.amplitude_pct is None
        assert q.volume_ratio is None
        assert q.pe_ratio is None
        assert q.pb_ratio is None
        assert q.mcap_yi is None
        assert q.float_mcap_yi is None
        assert q.limit_up is None
        assert q.limit_down is None

    def test_volume_unit_is_wan_shou(self):
        from stock_data.api.routes.agent import _build_minimal_quote_from_board_dict

        q = _build_minimal_quote_from_board_dict({"price": 100.0})
        assert q.volume_unit == "wan_shou"

    def test_amount_multiplied_by_1e8_from_yi(self):
        """Round-trip: upstream 亿元 → response 元 = ×1e8."""
        from stock_data.api.routes.agent import _build_minimal_quote_from_board_dict

        q = _build_minimal_quote_from_board_dict({"amount": 1.23})
        assert q.amount == pytest.approx(123_000_000.0)

    def test_amount_none_when_upstream_missing(self):
        """The None branch must NOT call ×1e8."""
        from stock_data.api.routes.agent import _build_minimal_quote_from_board_dict

        q = _build_minimal_quote_from_board_dict({})
        assert q.amount is None

    def test_net_inflow_pass_through_no_division(self):
        """net_inflow is in 亿元 upstream AND stays in 亿元 in the response
        (server convention for fund flow; no conversion)."""
        from stock_data.api.routes.agent import _build_minimal_quote_from_board_dict

        q = _build_minimal_quote_from_board_dict({"net_inflow": -2.5})
        assert q.net_inflow == -2.5

    def test_empty_dict_returns_default_instance(self):
        from stock_data.api.routes.agent import _build_minimal_quote_from_board_dict

        q = _build_minimal_quote_from_board_dict({})
        assert q.price is None
        assert q.change_pct is None
        assert q.open is None
        assert q.volume is None
        assert q.volume_unit == "wan_shou"  # always set on board
        assert q.amount is None
        assert q.up_count is None


class TestMdQuoteBlock:
    """Pin the 4-subgroup MD projection: 价格 / 量价 / 估值 / 板块统计.

    Pinned per api-reference.md 'No data is dropped' contract and the
    TestFormatMdFeatureCompleteness pattern.
    """

    def _render(self, q):
        from stock_data.api.routes.agent import _md_quote_block

        out: list[str] = []
        _md_quote_block(out, q)
        return "\n".join(out)

    def test_stock_quote_renders_all_four_subgroups(self):
        q = MinimalQuote(
            price=12.34, change_pct=1.23, change_amount=0.15,
            open=12.20, high=12.40, low=12.10, prev_close=12.19,
            volume=1_234_567, volume_unit="share",
            amount=2_050_000_000.0,
            turnover_pct=0.45, amplitude_pct=2.11, volume_ratio=1.20,
            pe_ratio=25.3, pb_ratio=8.7,
            mcap_yi=21_123.5, float_mcap_yi=21_000.1,
            limit_up=13.41, limit_down=11.10,
        )
        body = self._render(q)
        assert "### 行情" in body
        assert "### 价格" in body
        assert "### 量价" in body
        assert "### 估值" in body
        assert "### 板块统计" not in body  # no board-only fields populated
        # unit-aware volume
        assert "股" in body
        # 涨跌停价 is the 价格 subgroup's last row when present
        assert "涨跌停价" in body

    def test_index_quote_omits_valuation_subgroup(self):
        """Index realtime doesn't carry PE/PB/mcap; the 估值 subgroup must
        be skipped (not rendered with all-`—` cells — that's the
        'computed but blank' anti-pattern)."""
        q = MinimalQuote(
            price=3000.0, change_pct=0.5,
            volume=5_000_000, volume_unit="share",
            amount=1e10,
            turnover_pct=0.3,
        )
        body = self._render(q)
        assert "### 价格" in body
        assert "### 量价" in body
        assert "### 估值" not in body  # all stock-only valuation is None
        assert "### 板块统计" not in body

    def test_board_quote_uses_wan_shou_and_omits_valuation(self):
        q = MinimalQuote(
            price=1234.5, change_pct=1.23,
            volume=15343, volume_unit="wan_shou",
            amount=1_250_000_000.0,
            up_count=12, down_count=5,
            net_inflow=1.23, rank="229/389",
        )
        body = self._render(q)
        assert "### 行情" in body
        assert "### 价格" in body
        assert "### 量价" in body
        assert "### 估值" not in body
        assert "### 板块统计" in body
        assert "万手" in body
        assert "上涨家数" in body
        assert "229/389" in body

    def test_empty_quote_renders_only_header_with_no_subgroups(self):
        """A fully-None MinimalQuote (cold-path failure) renders just the
        heading with no subgroup table — the agent can detect via
        `errors.quote` and via the absent subgroups."""
        body = self._render(MinimalQuote())
        assert "### 行情" in body
        assert "### 价格" not in body  # all values None → subgroup skipped
        assert "### 量价" not in body
        assert "### 估值" not in body
        assert "### 板块统计" not in body

    def test_partial_quote_renders_em_dash_for_none_cells(self):
        """When SOME fields in a subgroup are populated and others None,
        render the subgroup with None cells as '—' (NOT omit the
        subgroup, NOT 'omit the cell')."""
        q = MinimalQuote(
            price=12.34, change_pct=1.23,
            # all other 价格 fields None
            volume=1_000_000, volume_unit="share",
            amount=2_000_000_000.0,
            # turnover / amplitude / volume_ratio all None
        )
        body = self._render(q)
        # 价格 subgroup is rendered (has price+change_pct+change_amount)
        assert "### 价格" in body
        # 量价 subgroup is rendered (has volume+amount)
        assert "### 量价" in body
        # None cells in 价格 show as '—'
        assert "—" in body
