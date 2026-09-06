"""Tests for /agent/lead-stocks endpoint and its pure ranking functions.

Spec: docs/superpowers/specs/2026-09-06-agent-lead-stocks-design.md §3.3
"""

from stock_data.api.routes.agent import (
    apply_change_pct_filter,
    rank_lead_stocks,
)


class TestLeadStocksChangePctFilter:
    """Pin the change_pct ∈ [9.0, 22.0] filter (inclusive)."""

    def test_boundary_9pct_inclusive(self):
        stocks = [{"code": "X", "change_pct": 9.0}]
        kept, exc = apply_change_pct_filter(stocks)
        assert len(kept) == 1
        assert exc == {"below_9pct": 0, "above_22pct": 0}

    def test_boundary_22pct_inclusive(self):
        stocks = [{"code": "X", "change_pct": 22.0}]
        kept, exc = apply_change_pct_filter(stocks)
        assert len(kept) == 1
        assert exc == {"below_9pct": 0, "above_22pct": 0}

    def test_just_below_9_excluded(self):
        stocks = [{"code": "X", "change_pct": 8.99}]
        kept, exc = apply_change_pct_filter(stocks)
        assert kept == []
        assert exc["below_9pct"] == 1

    def test_just_above_22_excluded(self):
        stocks = [{"code": "X", "change_pct": 22.01}]
        kept, exc = apply_change_pct_filter(stocks)
        assert kept == []
        assert exc["above_22pct"] == 1

    def test_none_treated_as_zero_below_9pct(self):
        """change_pct=None 视为 0，落入 below_9pct 桶。"""
        stocks = [{"code": "X", "change_pct": None}]
        kept, exc = apply_change_pct_filter(stocks)
        assert kept == []
        assert exc["below_9pct"] == 1

    def test_excluded_buckets_sum_correctly(self):
        stocks = [
            {"code": "A", "change_pct": 8.0},
            {"code": "B", "change_pct": 23.0},
            {"code": "C", "change_pct": 10.0},
            {"code": "D", "change_pct": 20.0},
        ]
        kept, exc = apply_change_pct_filter(stocks)
        assert {s["code"] for s in kept} == {"C", "D"}
        assert exc == {"below_9pct": 1, "above_22pct": 1}

    def test_mixed_pool_excludes_30cm_and_st(self):
        """典型 case：30cm (北交所, ~30%) + ST (~5%) 都被排除。"""
        stocks = [
            {"code": "300750", "change_pct": 20.02},  # 20cm kept
            {"code": "830799", "change_pct": 30.0},  # 30cm excluded
            {"code": "STX", "change_pct": 5.0},  # ST excluded
            {"code": "600519", "change_pct": 10.01},  # 10cm kept
        ]
        kept, exc = apply_change_pct_filter(stocks)
        assert {s["code"] for s in kept} == {"300750", "600519"}
        assert exc == {"below_9pct": 1, "above_22pct": 1}


class TestLeadStocksRanking:
    """Pin the 3-tier sort chain: score DESC → seal_time ASC → seal_amount DESC."""

    def test_score_descending(self):
        s1 = {
            "code": "A",
            "lb_count": 1,
            "change_pct": 10.0,
            "last_seal_time": "10:00:00",
            "seal_amount": 1e9,
        }
        s2 = {
            "code": "B",
            "lb_count": 3,
            "change_pct": 10.0,
            "last_seal_time": "10:00:00",
            "seal_amount": 1e9,
        }
        s3 = {
            "code": "C",
            "lb_count": 2,
            "change_pct": 20.0,
            "last_seal_time": "10:00:00",
            "seal_amount": 1e9,
        }
        # scores: A=10, B=30, C=40 → order C, B, A
        ranked = rank_lead_stocks([s1, s2, s3])
        assert [s["code"] for s in ranked] == ["C", "B", "A"]

    def test_seal_time_ascending_breaks_score_tie(self):
        s1 = {
            "code": "A",
            "lb_count": 1,
            "change_pct": 10.0,
            "last_seal_time": "10:30:00",
            "seal_amount": 1e9,
        }
        s2 = {
            "code": "B",
            "lb_count": 1,
            "change_pct": 10.0,
            "last_seal_time": "09:30:00",
            "seal_amount": 1e9,
        }
        # same score (10) — earlier time wins → B first
        ranked = rank_lead_stocks([s1, s2])
        assert [s["code"] for s in ranked] == ["B", "A"]

    def test_seal_amount_descending_breaks_time_tie(self):
        s1 = {
            "code": "A",
            "lb_count": 1,
            "change_pct": 10.0,
            "last_seal_time": "10:00:00",
            "seal_amount": 1e8,
        }
        s2 = {
            "code": "B",
            "lb_count": 1,
            "change_pct": 10.0,
            "last_seal_time": "10:00:00",
            "seal_amount": 1e9,
        }
        ranked = rank_lead_stocks([s1, s2])
        assert [s["code"] for s in ranked] == ["B", "A"]

    def test_none_seal_time_pushed_to_bottom(self):
        s1 = {
            "code": "A",
            "lb_count": 1,
            "change_pct": 10.0,
            "last_seal_time": None,
            "seal_amount": 1e9,
        }
        s2 = {
            "code": "B",
            "lb_count": 1,
            "change_pct": 10.0,
            "last_seal_time": "10:00:00",
            "seal_amount": 1e9,
        }
        ranked = rank_lead_stocks([s1, s2])
        assert [s["code"] for s in ranked] == ["B", "A"]

    def test_none_seal_amount_pushed_to_bottom(self):
        s1 = {
            "code": "A",
            "lb_count": 1,
            "change_pct": 10.0,
            "last_seal_time": "10:00:00",
            "seal_amount": None,
        }
        s2 = {
            "code": "B",
            "lb_count": 1,
            "change_pct": 10.0,
            "last_seal_time": "10:00:00",
            "seal_amount": 1e9,
        }
        ranked = rank_lead_stocks([s1, s2])
        assert [s["code"] for s in ranked] == ["B", "A"]

    def test_none_lb_count_treated_as_one(self):
        """lb_count=None 视为 1——缺失数据走"首板"语义，不被推到末尾。"""
        s1 = {
            "code": "A",
            "lb_count": None,
            "change_pct": 10.0,
            "last_seal_time": "10:00:00",
            "seal_amount": 1e9,
        }
        s2 = {
            "code": "B",
            "lb_count": 1,
            "change_pct": 10.0,
            "last_seal_time": "10:00:00",
            "seal_amount": 1e9,
        }
        # both score = 1 * 10 = 10, same time, same amount → unspecified tie
        # Pin: A and B both in output, no exception
        ranked = rank_lead_stocks([s1, s2])
        assert {s["code"] for s in ranked} == {"A", "B"}

    def test_none_change_pct_treated_as_zero(self):
        """change_pct=None → score = lb * 0 = 0 → 排到末尾。"""
        s1 = {
            "code": "A",
            "lb_count": 1,
            "change_pct": None,
            "last_seal_time": "10:00:00",
            "seal_amount": 1e9,
        }
        s2 = {
            "code": "B",
            "lb_count": 1,
            "change_pct": 10.0,
            "last_seal_time": "10:00:00",
            "seal_amount": 1e9,
        }
        ranked = rank_lead_stocks([s1, s2])
        assert [s["code"] for s in ranked] == ["B", "A"]
