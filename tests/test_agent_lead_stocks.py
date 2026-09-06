"""Tests for /agent/lead-stocks endpoint and its pure ranking functions.

Spec: docs/superpowers/specs/2026-09-06-agent-lead-stocks-design.md §3.3
"""

from types import SimpleNamespace
from unittest.mock import MagicMock

from stock_data.api.routes.agent import (
    apply_change_pct_filter,
    rank_lead_stocks,
)


def _make_unified_quote(**overrides):
    defaults = {
        "price": 10.0,
        "change_pct": 5.0,
        "change_amount": 0.5,
        "open_price": 10.0,
        "high": 10.5,
        "low": 9.5,
        "pre_close": 9.5,
        "volume": 1000,
        "volume_unit": "share",
        "amount": 10000.0,
        "turnover_rate": 1.0,
        "amplitude": 10.0,
        "volume_ratio": 1.5,
        "total_mv": 1e11,
        "circ_mv": 5e10,
        "pe_ratio": 20.0,
        "pb_ratio": 3.0,
        "limit_up": 11.0,
        "limit_down": 9.0,
        "name": "测试股",
    }
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


def _sample_zt_pool_stocks():
    return [
        {
            "code": "300750",
            "name": "宁德时代",
            "change_pct": 20.02,
            "lb_count": 3,
            "zt_count": "3连板",
            "last_seal_time": "10:23:14",
            "seal_amount": 1.23e9,
        },
        {
            "code": "600519",
            "name": "贵州茅台",
            "change_pct": 10.01,
            "lb_count": 2,
            "zt_count": "2连板",
            "last_seal_time": "11:00:00",
            "seal_amount": 5e8,
        },
        {
            "code": "000001",
            "name": "平安银行",
            "change_pct": 9.99,
            "lb_count": 1,
            "zt_count": "首板",
            "last_seal_time": "14:30:00",
            "seal_amount": 2e8,
        },
        # 30cm
        {
            "code": "830799",
            "name": "北交所某",
            "change_pct": 30.0,
            "lb_count": 1,
            "zt_count": "首板",
            "last_seal_time": "10:00:00",
            "seal_amount": 1e7,
        },
        # ST
        {
            "code": "600200",
            "name": "ST江苏",
            "change_pct": 5.0,
            "lb_count": 1,
            "zt_count": "首板",
            "last_seal_time": "10:00:00",
            "seal_amount": 1e7,
        },
    ]


def _sample_reasons():
    return [
        {"code": "300750", "reason": "新能源车产业链"},
        {"code": "600519", "reason": "消费复苏"},
        {"code": "000001", "reason": "银行板块联动"},
    ]


def _make_zt_pool_mock(stocks, origin="akshare"):
    m = MagicMock()
    m.get_zt_pool.return_value = (stocks, origin, None)
    return m


def _patch_manager_and_boards(monkeypatch, manager, *, board_stocks=None):
    """Wire up manager + persistence mocks for the full handler flow.

    `board_stocks` is a list of stock dicts (or None) returned by
    `stock_board_cache.get_stock_memberships` (3-tuple).
    """
    from stock_data.api._helpers import stock_boards as sb_helper
    from stock_data.api.routes import agent as agent_module
    from stock_data.data_provider.persistence import board as stock_board_cache

    monkeypatch.setattr(agent_module, "get_manager", lambda: manager)

    memberships = (board_stocks or [], [], "persistence")
    monkeypatch.setattr(
        stock_board_cache,
        "get_stock_memberships",
        lambda stock_code, sources, manager=None, **kw: memberships,
    )
    monkeypatch.setattr(
        sb_helper,
        "fetch_stock_boards_quote_enrichment",
        lambda stock_code, manager: (None, {}),
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


class TestLeadStocksHappyPath:
    """GET /api/v1/agent/lead-stocks — main flow."""

    def test_default_top_n_returns_three(self, client, monkeypatch):
        manager = _make_zt_pool_mock(_sample_zt_pool_stocks())
        manager.get_zt_reasons.return_value = (_sample_reasons(), "zzshare", None)
        manager.get_realtime_quote.return_value = _make_unified_quote()
        manager.get_kline_data.return_value = (None, "akshare")
        manager.get_stock_info.return_value = ({}, "zhitu")
        _patch_manager_and_boards(monkeypatch, manager)

        response = client.get("/api/v1/agent/lead-stocks")
        assert response.status_code == 200
        body = response.json()
        assert body["date"]
        assert body["top_n"] == 3
        assert body["board_code"] is None
        # 30cm (830799) and ST (600200) excluded by change_pct filter
        codes = [l["code"] for l in body["leads"]]
        assert "830799" not in codes
        assert "600200" not in codes
        # Order: score = lb * pct → 300750=60.06, 600519=20.02, 000001=9.99
        assert codes == ["300750", "600519", "000001"]
        # scores correctly computed
        assert body["leads"][0]["score"] == 60.06
        # ranking ranks 1-indexed
        assert [l["rank"] for l in body["leads"]] == [1, 2, 3]
        # reasons populated from zt-reasons
        assert body["leads"][0]["reason"] == "新能源车产业链"
        # summary populated
        assert body["summary"]["requested"] == 3
        assert body["summary"]["matched"] == 3
        assert body["summary"]["excluded"] == {"below_9pct": 1, "above_22pct": 1}

    def test_explicit_top_n_respected(self, client, monkeypatch):
        manager = _make_zt_pool_mock(_sample_zt_pool_stocks())
        manager.get_zt_reasons.return_value = (_sample_reasons(), "zzshare", None)
        manager.get_realtime_quote.return_value = _make_unified_quote()
        manager.get_kline_data.return_value = (None, "akshare")
        manager.get_stock_info.return_value = ({}, "zhitu")
        _patch_manager_and_boards(monkeypatch, manager)

        response = client.get("/api/v1/agent/lead-stocks?top_n=1")
        assert response.status_code == 200
        body = response.json()
        assert len(body["leads"]) == 1
        assert body["leads"][0]["code"] == "300750"


class TestLeadStocksBoardFilter:
    """board_code filter restricts leads to board members."""

    def test_board_intersection_filters_pool(self, client, monkeypatch):
        from stock_data.data_provider.persistence import board as stock_board_cache

        manager = _make_zt_pool_mock(_sample_zt_pool_stocks())
        manager.get_zt_reasons.return_value = (_sample_reasons(), "zzshare", None)
        manager.get_realtime_quote.return_value = _make_unified_quote()
        manager.get_kline_data.return_value = (None, "akshare")
        manager.get_stock_info.return_value = ({}, "zhitu")

        monkeypatch.setattr(
            "stock_data.api.routes.agent.get_manager",
            lambda: manager,
        )
        monkeypatch.setattr(
            stock_board_cache,
            "get_board_stocks",
            lambda board_code, source, include_quote, manager, **kw: (
                [{"stock_code": "300750", "stock_name": "宁德时代"}],
                "ths",
                "ths",
                None,
                False,
                1,
            ),
        )
        # get_stock_memberships for build_stock_profile → empty
        monkeypatch.setattr(
            stock_board_cache,
            "get_stock_memberships",
            lambda stock_code, sources, manager=None, **kw: ([], [], "persistence"),
        )
        # fetch_stock_boards_quote_enrichment → no-op
        from stock_data.api._helpers import stock_boards as sb_helper

        monkeypatch.setattr(
            sb_helper,
            "fetch_stock_boards_quote_enrichment",
            lambda stock_code, manager: (None, {}),
        )

        response = client.get("/api/v1/agent/lead-stocks?board_code=885595")
        assert response.status_code == 200
        body = response.json()
        codes = [l["code"] for l in body["leads"]]
        assert codes == ["300750"]
        assert body["board_code"] == "885595"

    def test_empty_intersection_returns_empty_leads(self, client, monkeypatch):
        from stock_data.data_provider.persistence import board as stock_board_cache

        manager = _make_zt_pool_mock(_sample_zt_pool_stocks())
        manager.get_zt_reasons.return_value = (_sample_reasons(), "zzshare", None)

        monkeypatch.setattr(
            "stock_data.api.routes.agent.get_manager",
            lambda: manager,
        )
        monkeypatch.setattr(
            stock_board_cache,
            "get_board_stocks",
            lambda board_code, source, include_quote, manager, **kw: (
                [{"stock_code": "999999", "stock_name": "无关"}],
                "ths",
                "ths",
                None,
                False,
                1,
            ),
        )

        response = client.get("/api/v1/agent/lead-stocks?board_code=885595")
        assert response.status_code == 200
        body = response.json()
        assert body["leads"] == []
        assert body["summary"]["matched"] == 0


class TestLeadStocksErrorIsolation:
    """Upstream failure isolation matrix per spec §3.4."""

    def test_zt_pool_failure_returns_503(self, client, monkeypatch):
        from stock_data.data_provider.base import DataFetchError

        manager = MagicMock()
        manager.get_zt_pool.side_effect = DataFetchError("pool down")
        monkeypatch.setattr(
            "stock_data.api.routes.agent.get_manager",
            lambda: manager,
        )

        response = client.get("/api/v1/agent/lead-stocks")
        assert response.status_code == 503

    def test_zt_reasons_failure_degrades_to_null(self, client, monkeypatch):
        """zt-reasons 失败 → 200 + reason=null + errors[] 记录。"""
        from stock_data.data_provider.base import DataFetchError

        manager = _make_zt_pool_mock(_sample_zt_pool_stocks())
        manager.get_zt_reasons.side_effect = DataFetchError("reasons down")
        manager.get_realtime_quote.return_value = _make_unified_quote()
        manager.get_kline_data.return_value = (None, "akshare")
        manager.get_stock_info.return_value = ({}, "zhitu")
        _patch_manager_and_boards(monkeypatch, manager)

        response = client.get("/api/v1/agent/lead-stocks")
        assert response.status_code == 200
        body = response.json()
        # reason 全 null
        assert all(l["reason"] is None for l in body["leads"])
        # errors[] 有 reasons 块
        assert any(e.get("block") == "reasons" for e in body["errors"])

    def test_board_stocks_failure_with_board_code_returns_503(self, client, monkeypatch):
        from stock_data.data_provider.base import DataFetchError
        from stock_data.data_provider.persistence import board as stock_board_cache

        manager = _make_zt_pool_mock(_sample_zt_pool_stocks())
        manager.get_realtime_quote.return_value = _make_unified_quote()

        monkeypatch.setattr(
            "stock_data.api.routes.agent.get_manager",
            lambda: manager,
        )

        def _raise(*args, **kwargs):
            raise DataFetchError("board down")

        monkeypatch.setattr(stock_board_cache, "get_board_stocks", _raise)

        response = client.get("/api/v1/agent/lead-stocks?board_code=885595")
        assert response.status_code == 503


class TestLeadStocksTopN:
    """top_n validation + boundary behavior."""

    def test_top_n_zero_returns_422(self, client):
        response = client.get("/api/v1/agent/lead-stocks?top_n=0")
        assert response.status_code == 422

    def test_top_n_above_max_returns_422(self, client):
        response = client.get("/api/v1/agent/lead-stocks?top_n=21")
        assert response.status_code == 422

    def test_top_n_max_boundary_accepted(self, client, monkeypatch):
        manager = _make_zt_pool_mock(_sample_zt_pool_stocks())
        manager.get_zt_reasons.return_value = (_sample_reasons(), "zzshare", None)
        manager.get_realtime_quote.return_value = _make_unified_quote()
        manager.get_kline_data.return_value = (None, "akshare")
        manager.get_stock_info.return_value = ({}, "zhitu")
        _patch_manager_and_boards(monkeypatch, manager)

        response = client.get("/api/v1/agent/lead-stocks?top_n=20")
        assert response.status_code == 200


class TestLeadStocksDateDefault:
    """date query param + default resolution."""

    def test_explicit_date_passes_through(self, client, monkeypatch):
        manager = _make_zt_pool_mock([])
        manager.get_zt_reasons.return_value = ([], "zzshare", None)
        _patch_manager_and_boards(monkeypatch, manager)

        response = client.get("/api/v1/agent/lead-stocks?date=2026-08-01")
        assert response.status_code == 200
        assert response.json()["date"] == "2026-08-01"

    def test_malformed_date_returns_422(self, client):
        response = client.get("/api/v1/agent/lead-stocks?date=not-a-date")
        assert response.status_code == 422


class TestLeadStocksProfileHelperReuse:
    """build_stock_profile 被 lead-stocks 复用（与 batch-profile 共享）。"""

    def test_lead_stocks_calls_helper_for_each_top_n_code(self, client, monkeypatch):
        from stock_data.api._helpers.agent_stock_profile import build_stock_profile

        mock_helper = MagicMock(wraps=build_stock_profile)
        monkeypatch.setattr(
            "stock_data.api.routes.agent.build_stock_profile",
            mock_helper,
        )
        manager = _make_zt_pool_mock(_sample_zt_pool_stocks()[:1])
        manager.get_zt_reasons.return_value = (_sample_reasons()[:1], "zzshare", None)
        manager.get_realtime_quote.return_value = _make_unified_quote()
        manager.get_kline_data.return_value = (None, "akshare")
        manager.get_stock_info.return_value = ({}, "zhitu")
        _patch_manager_and_boards(monkeypatch, manager)

        response = client.get("/api/v1/agent/lead-stocks?top_n=1")
        assert response.status_code == 200
        assert mock_helper.call_count == 1
        assert mock_helper.call_args.args[1] == "300750"
