"""Tests for /api/v1/agent/* endpoints (Phase 1 + Phase 2)."""

import contextlib
from unittest.mock import patch

import pandas as pd
import pytest

from stock_data.api.routes import reset_manager
from stock_data.data_provider.core.types import RealtimeSource, UnifiedRealtimeQuote


@pytest.fixture(autouse=True)
def reset_before_test():
    reset_manager()
    # Clear all response-level TTLCaches (incl. the get_quote_cache slot
    # reused by agent endpoints) so the same body+codes tuple doesn't
    # leak a result from a prior test.
    from stock_data.api import cache as api_cache

    for getter_name in (
        "get_quote_cache",
        "get_index_quote_cache",
        "get_history_cache",
        "get_pools_cache",
        "get_stock_info_cache",
        "get_news_flash_cache",
        "get_cls_feed_cache",
        "get_dragontiger_cache",
    ):
        getter = getattr(api_cache, getter_name, None)
        if getter is None:
            continue
        with contextlib.suppress(TypeError):
            getter().clear()
        # get_history_cache needs a frequency arg
        for f in ("d", "w", "m", "1", "5", "15", "30", "60"):
            with contextlib.suppress(Exception):
                api_cache.get_history_cache(f).clear()
    yield


_BOARD_STOCKS_PATCH = "stock_data.data_provider.persistence.board.get_board_stocks"


class TestBoardsOverlap:
    def test_two_boards_intersection_jaccard(self, client):
        """Two boards with overlap → intersection + jaccard computed."""
        with patch(_BOARD_STOCKS_PATCH) as mock_bs:
            mock_bs.side_effect = [
                # First board: 600519, 000001
                (
                    [
                        {"stock_code": "600519", "stock_name": "贵州茅台"},
                        {"stock_code": "000001", "stock_name": "平安银行"},
                    ],
                    "persistence",
                    "ths",
                    None,
                    False,
                    2,
                ),
                # Second board: 600519, 688981
                (
                    [
                        {"stock_code": "600519", "stock_name": "贵州茅台"},
                        {"stock_code": "688981", "stock_name": "中芯国际"},
                    ],
                    "persistence",
                    "ths",
                    None,
                    False,
                    2,
                ),
            ]
            response = client.post(
                "/api/v1/agent/boards/stock-overlap",
                json={"codes": ["885xxx", "881yyy"]},
            )
            assert response.status_code == 200
            data = response.json()
            assert len(data["sets"]) == 2
            assert data["sets"][0]["count"] == 2
            assert len(data["pairs"]) == 1
            pair = data["pairs"][0]
            assert {pair["a"], pair["b"]} == {"885xxx", "881yyy"} or (
                pair["a"] == "885xxx" and pair["b"] == "881yyy"
            )
            assert pair["intersection"] == ["600519"]
            assert pair["intersection_count"] == 1
            # union = {600519, 000001, 688981} = 3, intersection = 1
            assert abs(pair["jaccard"] - 1 / 3) < 1e-9

    def test_codes_too_few_400(self, client):
        """codes < 2 → 400."""
        response = client.post(
            "/api/v1/agent/boards/stock-overlap",
            json={"codes": ["885xxx"]},
        )
        # Pydantic min_length=2 → 422 (FastAPI validation)
        assert response.status_code == 422

    def test_codes_too_many_400(self, client):
        """codes > 10 → 400 (422 from Pydantic)."""
        response = client.post(
            "/api/v1/agent/boards/stock-overlap",
            json={"codes": [f"885{i:03d}" for i in range(11)]},
        )
        assert response.status_code == 422

    def test_one_board_upstream_fails_other_succeeds(self, client):
        """One board fails upstream → errors[] populated, other pairs still computed."""
        with patch(_BOARD_STOCKS_PATCH) as mock_bs:
            from stock_data.data_provider.base import DataFetchError

            mock_bs.side_effect = [
                # First board succeeds
                (
                    [{"stock_code": "600519", "stock_name": "贵州茅台"}],
                    "persistence",
                    "ths",
                    None,
                    False,
                    1,
                ),
                # Second board raises
                DataFetchError("upstream timeout"),
                # Third board succeeds
                (
                    [{"stock_code": "600519", "stock_name": "贵州茅台"}],
                    "persistence",
                    "ths",
                    None,
                    False,
                    1,
                ),
            ]
            response = client.post(
                "/api/v1/agent/boards/stock-overlap",
                json={"codes": ["A", "B", "C"]},
            )
            assert response.status_code == 200
            data = response.json()
            # B is missing from sets, recorded in errors
            assert {s["code"] for s in data["sets"]} == {"A", "C"}
            assert any(e.get("code") == "B" for e in data["errors"])
            # Pairs that include B are dropped; A-C pair still present
            assert all("B" not in (p["a"], p["b"]) for p in data["pairs"])


_STOCK_MEMBERSHIPS_PATCH = "stock_data.data_provider.persistence.board.get_stock_memberships"


class TestStocksBoardOverlap:
    def test_two_stocks_common_boards(self, client):
        with patch(_STOCK_MEMBERSHIPS_PATCH) as mock_sm:
            mock_sm.side_effect = [
                (
                    [
                        {
                            "code": "885xxx",
                            "name": "半导体",
                            "type": "concept",
                            "subtype": "",
                            "source": "ths",
                        },
                        {
                            "code": "881yyy",
                            "name": "电子",
                            "type": "industry",
                            "subtype": "",
                            "source": "ths",
                        },
                    ],
                    [],
                    "persistence",
                ),
                (
                    [
                        {
                            "code": "885xxx",
                            "name": "半导体",
                            "type": "concept",
                            "subtype": "",
                            "source": "ths",
                        },
                        {
                            "code": "882zzz",
                            "name": "新能源",
                            "type": "concept",
                            "subtype": "",
                            "source": "ths",
                        },
                    ],
                    [],
                    "persistence",
                ),
            ]
            response = client.post(
                "/api/v1/agent/stocks/board-overlap",
                json={"codes": ["600519", "688981"]},
            )
            assert response.status_code == 200
            data = response.json()
            assert len(data["sets"]) == 2
            assert len(data["pairs"]) == 1
            pair = data["pairs"][0]
            assert pair["intersection_count"] == 1
            assert pair["common_boards"][0]["code"] == "885xxx"
            # union = {885xxx, 881yyy, 882zzz} = 3, intersection = 1
            assert abs(pair["jaccard"] - 1 / 3) < 1e-9

    def test_codes_out_of_range_422(self, client):
        response = client.post(
            "/api/v1/agent/stocks/board-overlap",
            json={"codes": ["600519"]},
        )
        assert response.status_code == 422

    def test_per_stock_error_isolated(self, client):
        with patch(_STOCK_MEMBERSHIPS_PATCH) as mock_sm:
            from stock_data.data_provider.base import DataFetchError

            mock_sm.side_effect = [
                # First stock OK
                (
                    [
                        {
                            "code": "885xxx",
                            "name": "X",
                            "type": "concept",
                            "subtype": "",
                            "source": "ths",
                        }
                    ],
                    [],
                    "persistence",
                ),
                # Second stock upstream fails
                DataFetchError("network error"),
                # Third stock OK
                (
                    [
                        {
                            "code": "885xxx",
                            "name": "X",
                            "type": "concept",
                            "subtype": "",
                            "source": "ths",
                        }
                    ],
                    [],
                    "persistence",
                ),
            ]
            response = client.post(
                "/api/v1/agent/stocks/board-overlap",
                json={"codes": ["A", "B", "C"]},
            )
            assert response.status_code == 200
            data = response.json()
            assert {s["code"] for s in data["sets"]} == {"A", "C"}
            assert any(e["code"] == "B" for e in data["errors"])


class TestFilterStocks:
    def _patch_board(self, stocks):
        return patch(
            _BOARD_STOCKS_PATCH,
            return_value=(
                stocks,
                "persistence",
                "ths",
                None,
                False,
                len(stocks),
            ),
        )

    def test_filter_turnover_min_excludes_below(self, client):
        """Stocks below the turnover minimum are excluded."""
        rows = [
            {
                "stock_code": "A",
                "stock_name": "A",
                "price": 10.0,
                "change_pct": 5.0,
                "turnover_rate": 3.0,
                "amount": 1e9,
                "total_mv": 1e9,
                "open": 9.0,
                "high": 10.0,
                "low": 9.0,
                "volume": 0,
            },
            {
                "stock_code": "B",
                "stock_name": "B",
                "price": 20.0,
                "change_pct": 7.0,
                "turnover_rate": 8.0,
                "amount": 5e9,
                "total_mv": 5e9,
                "open": 19.0,
                "high": 21.0,
                "low": 19.0,
                "volume": 0,
            },
        ]
        with self._patch_board(rows):
            response = client.post(
                "/api/v1/agent/boards/filter-stocks",
                json={
                    "board_code": "885001",
                    "source": "ths",
                    "filters": {"turnover_pct": {"min": 5.0}},
                },
            )
            assert response.status_code == 200
            data = response.json()
            assert data["summary"]["total_in_board"] == 2
            assert data["summary"]["matched"] == 1
            assert data["matched_stocks"][0]["code"] == "B"
            # B: amount = 5e9 元 → 50 亿; mcap = 5e9 → 50 亿
            assert abs(data["matched_stocks"][0]["amount_yi"] - 50.0) < 1e-6
            assert abs(data["matched_stocks"][0]["mcap_yi"] - 50.0) < 1e-6
            # max_gain = (21 - 19) / 19 * 100 ≈ 10.526
            assert abs(data["matched_stocks"][0]["max_gain_pct"] - (2 / 19 * 100)) < 1e-6

    def test_max_gain_pct_min_filter(self, client):
        """max_gain_pct < min excludes stocks with low intraday gain."""
        rows = [
            {
                "stock_code": "A",
                "stock_name": "A",
                "price": 10.0,
                "change_pct": 1.0,
                "turnover_rate": 5.0,
                "amount": 1e9,
                "total_mv": 1e9,
                "open": 10.0,
                "high": 10.2,
                "low": 9.8,
                "volume": 0,
            },
            {
                "stock_code": "B",
                "stock_name": "B",
                "price": 20.0,
                "change_pct": 6.0,
                "turnover_rate": 10.0,
                "amount": 5e9,
                "total_mv": 5e9,
                "open": 19.0,
                "high": 21.0,
                "low": 19.0,
                "volume": 0,
            },
        ]
        with self._patch_board(rows):
            response = client.post(
                "/api/v1/agent/boards/filter-stocks",
                json={
                    "board_code": "885002",
                    "source": "ths",
                    "filters": {"max_gain_pct": {"min": 5.0}},
                },
            )
            assert response.status_code == 200
            data = response.json()
            # A: max_gain = 0.2/10*100 = 2% (excluded)
            # B: max_gain = 2/19*100 ≈ 10.526% (included)
            assert data["summary"]["matched"] == 1
            assert data["matched_stocks"][0]["code"] == "B"

    def test_limit_truncates(self, client):
        rows = [
            {
                "stock_code": f"S{i}",
                "stock_name": f"S{i}",
                "price": 10.0 + i,
                "change_pct": 5.0,
                "turnover_rate": 5.0,
                "amount": 1e9,
                "total_mv": 1e9,
                "open": 9.0,
                "high": 10.0,
                "low": 9.0,
                "volume": 0,
            }
            for i in range(10)
        ]
        with self._patch_board(rows):
            response = client.post(
                "/api/v1/agent/boards/filter-stocks",
                json={
                    "board_code": "885003",
                    "source": "ths",
                    "filters": {},
                    "limit": 3,
                },
            )
            assert response.status_code == 200
            data = response.json()
            assert data["summary"]["matched"] == 3
            assert data["summary"]["limit_applied"] is True
            assert len(data["matched_stocks"]) == 3

    def test_empty_filters_returns_all(self, client):
        rows = [
            {
                "stock_code": "A",
                "stock_name": "A",
                "price": 10.0,
                "change_pct": 0.0,
                "turnover_rate": 1.0,
                "amount": 0,
                "total_mv": 1e8,
                "open": 10.0,
                "high": 10.0,
                "low": 10.0,
                "volume": 0,
            },
        ]
        with self._patch_board(rows):
            response = client.post(
                "/api/v1/agent/boards/filter-stocks",
                json={"board_code": "885004", "source": "ths", "filters": {}},
            )
            assert response.status_code == 200
            data = response.json()
            assert data["summary"]["matched"] == 1
            assert data["matched_stocks"][0]["code"] == "A"

    def test_filter_excludes_row_when_value_is_none(self, client):
        """When a filter is set but the row's value is None, the row is excluded.

        Pins the contract: ``_passes_range(value, range_)`` returns False when
        ``value is None and range_ is not None`` (the "no data → no match"
        rule). Stocks with ``turnover_rate=None`` (or missing) must be
        filtered out when ``turnover_pct.min`` is set.
        """
        rows = [
            # A: turnover_rate explicitly None → excluded
            {
                "stock_code": "A",
                "stock_name": "A",
                "price": 10.0,
                "change_pct": 5.0,
                "turnover_rate": None,
                "amount": 1e9,
                "total_mv": 1e9,
                "open": 9.0,
                "high": 10.0,
                "low": 9.0,
                "volume": 0,
            },
            # B: turnover_rate field omitted entirely → also None → excluded
            {
                "stock_code": "B",
                "stock_name": "B",
                "price": 10.0,
                "change_pct": 5.0,
                "amount": 1e9,
                "total_mv": 1e9,
                "open": 9.0,
                "high": 10.0,
                "low": 9.0,
                "volume": 0,
            },
            # C: turnover_rate=8.0 (>= 5.0) → included
            {
                "stock_code": "C",
                "stock_name": "C",
                "price": 20.0,
                "change_pct": 7.0,
                "turnover_rate": 8.0,
                "amount": 5e9,
                "total_mv": 5e9,
                "open": 19.0,
                "high": 21.0,
                "low": 19.0,
                "volume": 0,
            },
        ]
        with self._patch_board(rows):
            response = client.post(
                "/api/v1/agent/boards/filter-stocks",
                json={
                    "board_code": "885005",
                    "source": "ths",
                    "filters": {"turnover_pct": {"min": 5.0}},
                },
            )
            assert response.status_code == 200
            data = response.json()
            assert data["summary"]["total_in_board"] == 3
            assert data["summary"]["matched"] == 1
            assert data["matched_stocks"][0]["code"] == "C"


class TestAgentManifest:
    def test_agent_endpoints_appear_in_manifest(self, client):
        """All 3 new agent endpoints surface in /control/api-manifest under tag=agent."""
        # No mocking needed: the manifest is built from the live router.
        response = client.get("/control/api-manifest")
        assert response.status_code == 200
        manifest = response.json()
        # Find the agent section. Manifest emits `id` (the route tag, see
        # explorer/manifest.py:99), not `tag` — the brief code used `tag`,
        # which doesn't exist on the section dict.
        agent_section = next(
            (s for s in manifest.get("sections", []) if s.get("id") == "agent"),
            None,
        )
        assert agent_section is not None, "No 'agent' tag section in manifest"
        paths = {ep.get("path") for ep in agent_section.get("endpoints", [])}
        assert "/api/v1/agent/boards/stock-overlap" in paths
        assert "/api/v1/agent/stocks/board-overlap" in paths
        assert "/api/v1/agent/boards/filter-stocks" in paths


class TestAgentCacheHit:
    """Second request with identical body must hit the TTLCache and skip the
    persistence/manager call. One test per agent endpoint (3 endpoints).
    """

    def test_cache_hit_boards_stock_overlap(self, client):
        with patch(_BOARD_STOCKS_PATCH) as mock_bs:
            mock_bs.return_value = (
                [{"stock_code": "600519", "stock_name": "贵州茅台"}],
                "persistence",
                "ths",
                None,
                False,
                1,
            )
            payload = {"codes": ["cache_boards_overlap_a", "cache_boards_overlap_b"]}
            r1 = client.post("/api/v1/agent/boards/stock-overlap", json=payload)
            # 1 board fetch per stock; 2 boards → 2 calls. Then assert the 2nd
            # request is a cache hit (call count stays at 2, not 4).
            assert mock_bs.call_count == 2
            r2 = client.post("/api/v1/agent/boards/stock-overlap", json=payload)
            assert r1.status_code == 200
            assert r2.status_code == 200
            assert r1.json() == r2.json()
            assert mock_bs.call_count == 2  # 2nd request hit cache, no extra calls

    def test_cache_hit_stocks_board_overlap(self, client):
        with patch(_STOCK_MEMBERSHIPS_PATCH) as mock_sm:
            mock_sm.side_effect = [
                (
                    [
                        {
                            "code": "885xxx",
                            "name": "半导体",
                            "type": "concept",
                            "subtype": "",
                            "source": "ths",
                        }
                    ],
                    [],
                    "persistence",
                ),
                (
                    [
                        {
                            "code": "885xxx",
                            "name": "半导体",
                            "type": "concept",
                            "subtype": "",
                            "source": "ths",
                        }
                    ],
                    [],
                    "persistence",
                ),
            ]
            payload = {"codes": ["cache_stocks_overlap_c", "cache_stocks_overlap_d"]}
            r1 = client.post("/api/v1/agent/stocks/board-overlap", json=payload)
            # 1 membership fetch per stock; 2 stocks → 2 calls. Then assert
            # the 2nd request is a cache hit (call count stays at 2, not 4).
            assert mock_sm.call_count == 2
            r2 = client.post("/api/v1/agent/stocks/board-overlap", json=payload)
            assert r1.status_code == 200
            assert r2.status_code == 200
            assert r1.json() == r2.json()
            assert mock_sm.call_count == 2  # 2nd request hit cache, no extra calls

    def test_different_limits_use_different_cache_entries(self, client):
        """Limit participates in the cache key because it is applied upstream."""
        rows = [
            {
                "stock_code": f"L{i}",
                "stock_name": f"L{i}",
                "price": 10.0 + i,
                "change_pct": 5.0,
                "turnover_rate": 5.0,
                "amount": 1e9,
                "total_mv": 1e9,
                "open": 9.0,
                "high": 10.0,
                "low": 9.0,
                "volume": 0,
            }
            for i in range(4)
        ]
        with patch(
            _BOARD_STOCKS_PATCH,
            return_value=(
                rows,
                "persistence",
                "ths",
                None,
                False,
                len(rows),
            ),
        ) as mock_bs:
            base = {
                "board_code": "cache_filter_limit_board_001",
                "source": "ths",
                "filters": {},
            }
            first = client.post(
                "/api/v1/agent/boards/filter-stocks",
                json={**base, "limit": 1},
            )
            second = client.post(
                "/api/v1/agent/boards/filter-stocks",
                json={**base, "limit": 3},
            )

            assert first.status_code == 200
            assert second.status_code == 200
            assert len(first.json()["matched_stocks"]) == 1
            assert len(second.json()["matched_stocks"]) == 3
            assert mock_bs.call_count == 2
            assert mock_bs.call_args_list[0].kwargs["top_n"] == 1
            assert mock_bs.call_args_list[1].kwargs["top_n"] == 3

        rows = [
            {
                "stock_code": "X",
                "stock_name": "X",
                "price": 10.0,
                "change_pct": 5.0,
                "turnover_rate": 8.0,
                "amount": 1e9,
                "total_mv": 1e9,
                "open": 9.0,
                "high": 10.0,
                "low": 9.0,
                "volume": 0,
            },
        ]
        with patch(
            _BOARD_STOCKS_PATCH,
            return_value=(
                rows,
                "persistence",
                "ths",
                None,
                False,
                len(rows),
            ),
        ) as mock_bs:
            payload = {
                "board_code": "cache_filter_stocks_board_001",
                "source": "ths",
                "filters": {"turnover_pct": {"min": 5.0}},
            }
            r1 = client.post("/api/v1/agent/boards/filter-stocks", json=payload)
            r2 = client.post("/api/v1/agent/boards/filter-stocks", json=payload)
            assert r1.status_code == 200
            assert r2.status_code == 200
            assert r1.json() == r2.json()
            mock_bs.assert_called_once()


# ============================================================================
# Phase 2 endpoints (3.2.1 / 3.2.2 / 3.2.3 of agent-batch-api-proposal)
# ============================================================================


def _make_unified_quote(code: str, price: float = 100.0) -> UnifiedRealtimeQuote:
    return UnifiedRealtimeQuote(
        code=code,
        name=code,
        source=RealtimeSource.AKSHARE,
        price=price,
        change_pct=1.5,
        change_amount=1.5,
        open_price=99.0,
        high=101.0,
        low=98.5,
        pre_close=98.5,
        volume=1000000,
        amount=1e8,
    )


def _make_kline_df(rows: list[dict]) -> pd.DataFrame:
    return pd.DataFrame(rows)


class TestMarketContext:
    """GET /agent/market-context — news + zt + dt + dragon-tiger + session."""

    def _patch_all_ok(self, monkeypatch):
        """Standard happy-path manager mock: all 6 sources return data."""
        from unittest.mock import MagicMock

        from stock_data.api.routes import agent as agent_module

        mock_manager = MagicMock()
        mock_manager.get_morning_briefing.return_value = (
            {"article_id": 1, "title": "早报", "date": "2026-07-25"},
            "cls",
        )
        mock_manager.get_market_recap.return_value = (
            {"article_id": 2, "title": "复盘", "date": "2026-07-25"},
            "cls",
        )
        mock_manager.get_flash_news.return_value = (
            [{"title": "快讯1", "url": "u1", "publish_time": "2026-07-25 09:30:00"}],
            "eastmoney",
        )
        mock_manager.get_zt_pool.return_value = (
            [{"code": "600519", "name": "茅台"}],
            "akshare",
            None,
        )
        mock_manager.get_daily_dragon_tiger.return_value = (
            {
                "date": "2026-07-25",
                "total": 2,
                "stocks": [
                    {"code": "600519", "name": "茅台", "net_buy_wan": 5000.0},
                    {"code": "000001", "name": "平安", "net_buy_wan": -2000.0},
                ],
            },
            "zzshare",
        )
        monkeypatch.setattr(agent_module, "get_manager", lambda: mock_manager)
        return mock_manager

    def test_happy_path_all_blocks_present(self, client, monkeypatch):
        from stock_data.api.routes import agent as agent_module

        self._patch_all_ok(monkeypatch)
        # Force post-market so zt/dt pools are not nulled out by pre-market
        # session logic (the real clock would make this test flaky around
        # 09:15 CST).
        monkeypatch.setattr(
            agent_module,
            "_classify_market_session",
            lambda _is_td: "post-market",
        )
        response = client.get("/api/v1/agent/market-context?flash_limit=10")
        assert response.status_code == 200
        data = response.json()
        # trade_date resolved to a YYYY-MM-DD
        assert len(data["trade_date"]) == 10
        assert "is_trade_day" in data
        assert data["market_session"] in {"pre-market", "intraday", "post-market", "closed"}
        # news block
        assert data["messages"]["morning_briefing"]["title"] == "早报"
        assert data["messages"]["market_recap"]["title"] == "复盘"
        assert len(data["messages"]["flash_news"]) == 1
        # zt/dt pool
        assert data["limit_pools"]["zt"] is not None
        assert len(data["limit_pools"]["zt"]) == 1
        assert data["limit_pools"]["dt"] is not None
        # dragon-tiger
        assert data["dragon_tiger"] is not None
        assert len(data["dragon_tiger"]["stocks"]) == 2
        assert data["dragon_tiger"]["summary"]["total_net_buy_wan"] == 3000.0
        assert data["dragon_tiger"]["summary"]["top_by_net_buy"][0]["code"] == "600519"
        assert data["dragon_tiger"]["summary"]["top_by_net_sell"][0]["code"] == "000001"

    def test_pre_market_pools_forced_null(self, client, monkeypatch):
        """During pre-market (09:15 CST) zt and dt are forced to null regardless of upstream."""

        from stock_data.api.routes import agent as agent_module

        mock_manager = self._patch_all_ok(monkeypatch)

        # Patch the helper to return 'pre-market' regardless of real time
        monkeypatch.setattr(
            agent_module,
            "_classify_market_session",
            lambda _is_td: "pre-market",
        )
        response = client.get("/api/v1/agent/market-context")
        assert response.status_code == 200
        data = response.json()
        assert data["market_session"] == "pre-market"
        # pools forced null even though upstream returned data
        assert data["limit_pools"]["zt"] is None
        assert data["limit_pools"]["dt"] is None
        # But the underlying manager was NOT called for pools in pre-market
        mock_manager.get_zt_pool.assert_not_called()

    def test_morning_briefing_null_on_no_article(self, client, monkeypatch):
        """morning_briefing returns (None, '') (no article for this date) → morning_briefing=null in response."""
        from unittest.mock import MagicMock

        from stock_data.api.routes import agent as agent_module

        mock_manager = MagicMock()
        mock_manager.get_morning_briefing.return_value = (None, "")
        mock_manager.get_market_recap.return_value = (
            {"title": "复盘", "date": "2026-07-25"},
            "cls",
        )
        mock_manager.get_flash_news.return_value = ([], "eastmoney")
        mock_manager.get_zt_pool.return_value = ([], "akshare", None)
        mock_manager.get_daily_dragon_tiger.return_value = ({"stocks": []}, "zzshare")
        monkeypatch.setattr(agent_module, "get_manager", lambda: mock_manager)

        response = client.get("/api/v1/agent/market-context")
        assert response.status_code == 200
        data = response.json()
        assert data["messages"]["morning_briefing"] is None
        # market_recap still ok
        assert data["messages"]["market_recap"] is not None

    def test_dragon_tiger_failure_isolated_other_blocks_served(self, client, monkeypatch):
        """Dragon-tiger upstream fails → dragon_tiger=null; news + pools still emitted."""
        from unittest.mock import MagicMock

        from stock_data.api.routes import agent as agent_module
        from stock_data.data_provider.base import DataFetchError

        mock_manager = MagicMock()
        mock_manager.get_morning_briefing.return_value = (
            {"title": "早报", "date": "2026-07-25"},
            "cls",
        )
        mock_manager.get_market_recap.return_value = (None, "")
        mock_manager.get_flash_news.return_value = ([], "eastmoney")
        mock_manager.get_zt_pool.return_value = ([], "akshare", None)
        mock_manager.get_daily_dragon_tiger.side_effect = DataFetchError("dragon-tiger down")
        monkeypatch.setattr(agent_module, "get_manager", lambda: mock_manager)

        response = client.get("/api/v1/agent/market-context")
        assert response.status_code == 200
        data = response.json()
        assert data["dragon_tiger"] is None
        # Other blocks unaffected
        assert data["messages"]["morning_briefing"] is not None
        assert data["limit_pools"]["zt"] is not None

    def test_trade_date_query_param(self, client, monkeypatch):
        """?trade_date=YYYY-MM-DD is plumbed to morning/recap/dragon-tiger."""
        from unittest.mock import MagicMock

        from stock_data.api.routes import agent as agent_module

        mock_manager = MagicMock()
        mock_manager.get_morning_briefing.return_value = (None, "")
        mock_manager.get_market_recap.return_value = (None, "")
        mock_manager.get_flash_news.return_value = ([], "eastmoney")
        mock_manager.get_zt_pool.return_value = ([], "akshare", None)
        mock_manager.get_daily_dragon_tiger.return_value = ({"stocks": []}, "zzshare")
        monkeypatch.setattr(agent_module, "get_manager", lambda: mock_manager)

        response = client.get("/api/v1/agent/market-context?trade_date=2026-07-20")
        assert response.status_code == 200
        data = response.json()
        assert data["trade_date"] == "2026-07-20"
        # All date-keyed calls got 2026-07-20
        assert mock_manager.get_morning_briefing.call_args.args[0] == "2026-07-20"
        assert mock_manager.get_market_recap.call_args.args[0] == "2026-07-20"
        assert mock_manager.get_daily_dragon_tiger.call_args.args[0] == "2026-07-20"

    def test_cache_hit_same_flash_limit_and_date(self, client, monkeypatch):
        """Second request with same (flash_limit, trade_date) hits cache."""
        from unittest.mock import MagicMock

        from stock_data.api.routes import agent as agent_module

        mock_manager = MagicMock()
        mock_manager.get_morning_briefing.return_value = (None, "")
        mock_manager.get_market_recap.return_value = (None, "")
        mock_manager.get_flash_news.return_value = ([], "eastmoney")
        mock_manager.get_zt_pool.return_value = ([], "akshare", None)
        mock_manager.get_daily_dragon_tiger.return_value = ({"stocks": []}, "zzshare")
        monkeypatch.setattr(agent_module, "get_manager", lambda: mock_manager)

        client.get("/api/v1/agent/market-context?flash_limit=20&trade_date=2026-07-25")
        # First call: 1 morning + 1 recap + 1 flash + 1 zt + 1 dt + 1 dtiger = 6
        assert mock_manager.get_morning_briefing.call_count == 1
        client.get("/api/v1/agent/market-context?flash_limit=20&trade_date=2026-07-25")
        # Second call: still 1 (cache hit)
        assert mock_manager.get_morning_briefing.call_count == 1


class TestPhase2Manifest:
    """All 3 new Phase 2 endpoints appear in /control/api-manifest under tag=agent."""

    def test_phase2_endpoints_in_manifest(self, client):
        response = client.get("/control/api-manifest")
        assert response.status_code == 200
        manifest = response.json()
        agent_section = next(
            (s for s in manifest.get("sections", []) if s.get("id") == "agent"),
            None,
        )
        assert agent_section is not None
        paths = {ep.get("path") for ep in agent_section.get("endpoints", [])}
        assert "/api/v1/agent/indices/batch-profile" in paths
        assert "/api/v1/agent/market-context" in paths
        assert "/api/v1/agent/stocks/batch-profile" in paths


class TestPhase2DefensiveGuards:
    """Belt-and-suspenders against silent contract drift."""

    def test_market_context_trade_date_malformed_400(self, client):
        """trade_date=not-a-date must 400, not silently 200 with empty result."""
        r = client.get("/api/v1/agent/market-context?trade_date=not-a-date")
        assert r.status_code == 400

    def test_market_context_pre_market_summary_drops_pool_attempts(self, client, monkeypatch):
        """In pre-market, n_requested drops to 4 (skipping zt+dt attempts).

        Without this fix the summary reported requested=6/failed=2 even
        though pools were intentionally skipped (not failed).
        """
        from unittest.mock import MagicMock

        from stock_data.api.routes import agent as agent_module

        mock_manager = MagicMock()
        mock_manager.get_morning_briefing.return_value = (None, "")
        mock_manager.get_market_recap.return_value = (None, "")
        mock_manager.get_flash_news.return_value = ([], "eastmoney")
        mock_manager.get_zt_pool.return_value = ([], "akshare", None)
        mock_manager.get_daily_dragon_tiger.return_value = ({"stocks": []}, "zzshare")
        monkeypatch.setattr(agent_module, "get_manager", lambda: mock_manager)
        monkeypatch.setattr(
            agent_module,
            "_classify_market_session",
            lambda _is_td: "pre-market",
        )

        r = client.get("/api/v1/agent/market-context?flash_limit=20&trade_date=2026-07-25")
        assert r.status_code == 200
        data = r.json()
        # 4 attempted (briefing + recap + flash + dtiger); 2 skipped (zt + dt)
        assert data["summary"]["requested"] == 4
        # Pools NOT attempted in pre-market
        mock_manager.get_zt_pool.assert_not_called()

    def test_market_context_cache_key_includes_session(self, client, monkeypatch):
        """Same (flash_limit, trade_date) but different session → different cache entries."""
        from unittest.mock import MagicMock

        from stock_data.api.routes import agent as agent_module

        mock_manager = MagicMock()
        mock_manager.get_morning_briefing.return_value = (None, "")
        mock_manager.get_market_recap.return_value = (None, "")
        mock_manager.get_flash_news.return_value = ([], "eastmoney")
        mock_manager.get_zt_pool.return_value = ([], "akshare", None)
        mock_manager.get_daily_dragon_tiger.return_value = ({"stocks": []}, "zzshare")
        monkeypatch.setattr(agent_module, "get_manager", lambda: mock_manager)

        # First call: pre-market
        monkeypatch.setattr(agent_module, "_classify_market_session", lambda *_: "pre-market")
        client.get("/api/v1/agent/market-context?flash_limit=20&trade_date=2026-07-25")
        # Second call: post-market — same flash_limit + date, different session
        monkeypatch.setattr(agent_module, "_classify_market_session", lambda *_: "post-market")
        client.get("/api/v1/agent/market-context?flash_limit=20&trade_date=2026-07-25")
        # Without session in cache key, the 2nd request would hit cache and
        # call counts would stay flat. With it, both calls execute fresh.
        assert mock_manager.get_morning_briefing.call_count == 2

    def test_quote_none_counted_as_failure(self, client, monkeypatch):
        """If get_index_realtime_quote returns None (no fetcher could serve),
        it's reported as a failure, not a successful empty quote.
        """
        from unittest.mock import MagicMock

        from stock_data.api.routes import agent as agent_module

        mock_manager = MagicMock()
        mock_manager.get_index_realtime_quote.return_value = None
        mock_manager.get_kline_data.return_value = (
            _make_kline_df(
                [
                    {
                        "date": "2026-07-25",
                        "open": 1,
                        "high": 2,
                        "low": 0.5,
                        "close": 1.5,
                        "volume": 100,
                        "amount": 1e6,
                        "pct_chg": 0.1,
                    }
                ]
            ),
            "akshare",
        )
        monkeypatch.setattr(agent_module, "get_manager", lambda: mock_manager)

        r = client.get("/api/v1/agent/indices/batch-profile?codes=000001")
        assert r.status_code == 200
        data = r.json()
        first = data["indices"][0]
        # quote=None should mark the entry as failed
        assert first["quote"] is None
        assert first["errors"]["quote"] is not None
        assert data["summary"]["ok"] == 0
        assert data["summary"]["failed"] == 1


# ============================================================================
# Phase 2.4: ?format=json|md projection (see agent-batch-api-proposal §2.2 / §8.2.4)
# ============================================================================


_MD_CT = "text/markdown; charset=utf-8"


class TestFormatMd:
    """``?format=md`` projection: each agent endpoint must support
    markdown output with the right Content-Type and a stable layout.

    Backwards-compat is pinned by TestFormatMdDefaults below: the existing
    JSON clients (no ?format param) keep their shape.
    """

    def test_boards_stock_overlap_md(self, client):
        with patch(_BOARD_STOCKS_PATCH) as mock_bs:
            mock_bs.side_effect = [
                (
                    [{"stock_code": "600519"}, {"stock_code": "000001"}],
                    "persistence",
                    "ths",
                    None,
                    False,
                    2,
                ),
                (
                    [{"stock_code": "600519"}, {"stock_code": "688981"}],
                    "persistence",
                    "ths",
                    None,
                    False,
                    2,
                ),
            ]
            r = client.post(
                "/api/v1/agent/boards/stock-overlap?format=md",
                json={"codes": ["885xxx", "881yyy"]},
            )
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("text/markdown")
        body = r.text
        # H1 + per-section headers
        assert "# 板块成分股两两重叠度" in body
        assert "## 板块成分股数" in body
        assert "## 板块对重叠度" in body
        # Pair table has the expected intersection + jaccard row
        assert "| 885xxx | 881yyy | 1 | 0.3333 |" in body
        # Sets table renders both boards
        assert "| 885xxx | 2 | ths |" in body
        assert "| 881yyy | 2 | ths |" in body

    def test_stocks_board_overlap_md(self, client):
        with patch(_STOCK_MEMBERSHIPS_PATCH) as mock_sm:
            mock_sm.side_effect = [
                (
                    [
                        {
                            "code": "885xxx",
                            "name": "半导体",
                            "type": "concept",
                            "subtype": "",
                            "source": "ths",
                        }
                    ],
                    [],
                    "persistence",
                ),
                (
                    [
                        {
                            "code": "885xxx",
                            "name": "半导体",
                            "type": "concept",
                            "subtype": "",
                            "source": "ths",
                        }
                    ],
                    [],
                    "persistence",
                ),
            ]
            r = client.post(
                "/api/v1/agent/stocks/board-overlap?format=md",
                json={"codes": ["600519", "688981"]},
            )
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("text/markdown")
        body = r.text
        assert "# 股票所属板块两两重叠度" in body
        assert "## 股票所属板块" in body
        assert "### 600519" in body
        assert "### 688981" in body
        # Boards listed per-stock (code / type/subtype / name / source)
        assert "- 885xxx (concept/-) 半导体 — source: ths" in body
        # Pairs table — common_boards column carries the actual shared boards
        assert "| 600519 | 688981 | 1 | 1.0000 | 885xxx(半导体) |" in body

    def test_filter_stocks_md(self, client):
        rows = [
            {
                "stock_code": "B",
                "stock_name": "B",
                "price": 20.0,
                "change_pct": 7.0,
                "turnover_rate": 8.0,
                "amount": 5e9,
                "total_mv": 5e9,
                "open": 19.0,
                "high": 21.0,
                "low": 19.0,
                "volume": 0,
            },
        ]
        with patch(
            _BOARD_STOCKS_PATCH,
            return_value=(rows, "persistence", "ths", None, False, 1),
        ):
            r = client.post(
                "/api/v1/agent/boards/filter-stocks?format=md",
                json={
                    "board_code": "885001",
                    "source": "ths",
                    "filters": {"turnover_pct": {"min": 5.0}},
                },
            )
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("text/markdown")
        body = r.text
        assert "# 板块成分股过滤 — 885001" in body
        # Filter rendered as one line
        assert "**过滤条件**:" in body
        assert "换手率(%): 5.00" in body
        # Summary line
        assert "总成分股 1, 匹配 1" in body
        # Matched table — header has all 17 cols (data-loss regression net)
        assert "| 代码 | 名称 | 现价 | 涨跌额 | 涨跌幅 | 最高涨幅 | 换手率(%) |" in body
        assert "| 成交额(亿) | 市值(亿) | 量(股) | 量比 | PE | 振幅(%) |" in body
        assert "| 开 | 高 | 低 | 昨收 |" in body
        # All 16 MatchedStock fields present in the row. The test row only sets
        # a subset, so unset fields render as '—' (no field is dropped from
        # the row). Pin the full shape.
        expected_row = (
            "| B | B | 20.000 | — | +7.00% | +10.53% | 8.00 | 50.00 | 50.00 | "
            "0 | — | — | — | 19.000 | 21.000 | 19.000 | — |"
        )
        assert expected_row in body

    def test_market_context_md(self, client, monkeypatch):
        from stock_data.api.routes import agent as agent_module

        # Reuse the same _patch_all_ok helper from TestMarketContext (same module)
        TestMarketContext._patch_all_ok(self, monkeypatch)
        monkeypatch.setattr(agent_module, "_classify_market_session", lambda _is_td: "post-market")
        r = client.get("/api/v1/agent/market-context?flash_limit=10&format=md")
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("text/markdown")
        body = r.text
        assert "# 市场全景 —" in body
        assert "post-market" in body
        # news section
        assert "## 消息面" in body
        assert "### 早报" in body
        assert "### 复盘" in body
        assert "### 快讯" in body
        # pool section
        assert "## 涨跌停" in body
        # dragon-tiger section
        assert "## 龙虎榜" in body
        assert "**全市场净买入合计**: 3,000" in body


class TestFormatMdDefaults:
    """format defaults to json; the new param doesn't change existing behavior."""

    def test_default_format_is_json(self, client):
        r = client.post(
            "/api/v1/agent/boards/stock-overlap",
            json={"codes": ["885xxx", "881yyy"]},
        )
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("application/json")
        # Same shape as before
        assert "sets" in r.json() and "pairs" in r.json()

    def test_format_html_rejected_as_422(self, client):
        """format must be json|md; unknown values 422 from FastAPI's Query validator."""
        r = client.get("/api/v1/agent/indices/batch-profile?format=html")
        assert r.status_code == 422

    def test_md_renders_consistently_across_calls(self, client, monkeypatch):
        """Two consecutive requests (json then md) both render correctly.

        Post-2026-08-28: no composite cache layer on batch-profile, so the
        manager runs on every call. The assertion that previously pinned
        "manager called only once" is intentionally gone — the regression
        this test guards against is "format switching breaks MD rendering",
        not "second call hits cache".
        """
        from unittest.mock import MagicMock

        from stock_data.api.routes import agent as agent_module

        mock_manager = MagicMock()
        mock_manager.get_index_realtime_quote.return_value = _make_unified_quote("000001")
        mock_manager.get_kline_data.return_value = (_make_kline_df([]), "akshare")
        monkeypatch.setattr(agent_module, "get_manager", lambda: mock_manager)

        r1 = client.get("/api/v1/agent/indices/batch-profile?codes=000001")
        assert r1.headers["content-type"].startswith("application/json")
        r2 = client.get("/api/v1/agent/indices/batch-profile?codes=000001&format=md")
        assert r2.status_code == 200
        assert r2.headers["content-type"].startswith("text/markdown")
        assert "## 000001" in r2.text
        # No composite cache → manager invoked once per request.
        assert mock_manager.get_index_realtime_quote.call_count == 2


class TestFormatMdFallback:
    """When a template raises, the helper falls back to JSON + X-MD-Render-Error header."""

    def test_template_failure_returns_json_with_warning_header(self, client, monkeypatch):
        """Inject a broken template; endpoint must still 200 with the original JSON
        payload and a header naming the failure (per proposal §9)."""
        from stock_data.api.routes import agent as agent_module

        # Swap the dict entry directly. The dispatch table holds REFERENCES
        # captured at import time, so monkeypatch.setattr on the module-level
        # function name would NOT affect the call site.
        def boom(_p):
            raise RuntimeError("template exploded")

        monkeypatch.setitem(agent_module._MD_TEMPLATES, "market-context", boom)

        from unittest.mock import MagicMock

        mock_manager = MagicMock()
        mock_manager.get_morning_briefing.return_value = (None, "")
        mock_manager.get_market_recap.return_value = (None, "")
        mock_manager.get_flash_news.return_value = ([], "eastmoney")
        mock_manager.get_zt_pool.return_value = ([], "akshare", None)
        mock_manager.get_daily_dragon_tiger.return_value = ({"stocks": []}, "zzshare")
        monkeypatch.setattr(agent_module, "get_manager", lambda: mock_manager)
        monkeypatch.setattr(agent_module, "_classify_market_session", lambda _is_td: "post-market")

        r = client.get(
            "/api/v1/agent/market-context?flash_limit=10&trade_date=2026-07-25&format=md"
        )
        assert r.status_code == 200
        # Falls back to JSON (NOT markdown)
        assert r.headers["content-type"].startswith("application/json")
        # Header carries the failure reason
        assert "X-MD-Render-Error" in r.headers
        assert "RuntimeError" in r.headers["X-MD-Render-Error"]
        assert "template exploded" in r.headers["X-MD-Render-Error"]
        # Original payload is still in the body
        data = r.json()
        assert "trade_date" in data and "messages" in data


# ============================================================================
# Data-completeness tests (Phase 2.4 no-data-loss contract)
# ============================================================================
#
# The MD projection must not drop fields from the JSON. These tests feed rich
# payloads and assert every field survives the markdown render. If a future
# template refactor accidentally drops a column, the matching test fails
# before the change ships.


class TestFormatMdDataCompleteness:
    """Pins the no-data-loss contract: every field in the JSON must appear
    in the MD output (or be explicitly noted as absent)."""

    def test_boards_stock_overlap_intersection_codes_shown(self, client):
        """The `intersection: list[str]` per pair MUST be rendered (not just count)."""
        with patch(_BOARD_STOCKS_PATCH) as mock_bs:
            mock_bs.side_effect = [
                (
                    [
                        {"stock_code": "600519"},
                        {"stock_code": "000001"},
                        {"stock_code": "300750"},
                    ],
                    "persistence",
                    "ths",
                    None,
                    False,
                    3,
                ),
                (
                    [
                        {"stock_code": "600519"},
                        {"stock_code": "688981"},
                    ],
                    "persistence",
                    "ths",
                    None,
                    False,
                    2,
                ),
            ]
            r = client.post(
                "/api/v1/agent/boards/stock-overlap?format=md",
                json={"codes": ["885xxx", "881yyy"]},
            )
        body = r.text
        # The actual stock codes must appear (not just the count)
        assert "600519, 000001, 300750" in body or "600519" in body
        # 交集代码 column header is present
        assert "| 交集代码 |" in body

    def test_stocks_board_overlap_common_boards_shown(self, client):
        """The `common_boards: list[dict]` per pair MUST be rendered, plus
        per-stock board entries show subtype + source (not just code/name)."""
        with patch(_STOCK_MEMBERSHIPS_PATCH) as mock_sm:
            mock_sm.side_effect = [
                (
                    [
                        {
                            "code": "885xxx",
                            "name": "半导体",
                            "type": "concept",
                            "subtype": "技术",
                            "source": "ths",
                        },
                        {
                            "code": "881yyy",
                            "name": "电子",
                            "type": "industry",
                            "subtype": "-",
                            "source": "ths",
                        },
                    ],
                    [],
                    "persistence",
                ),
                (
                    [
                        {
                            "code": "885xxx",
                            "name": "半导体",
                            "type": "concept",
                            "subtype": "技术",
                            "source": "ths",
                        },
                    ],
                    [],
                    "persistence",
                ),
            ]
            r = client.post(
                "/api/v1/agent/stocks/board-overlap?format=md",
                json={"codes": ["600519", "688981"]},
            )
        body = r.text
        # Per-stock board entries: subtype + source are present
        assert "(concept/技术)" in body
        assert "— source: ths" in body
        # Pair common_boards column carries the actual shared board
        assert "共同板块 |" in body
        assert "885xxx(半导体)" in body

    def test_market_context_all_flash_news_rendered(self, client, monkeypatch):
        """flash_news > 20 entries must all be rendered (no [:20] truncation)."""
        from unittest.mock import MagicMock

        from stock_data.api.routes import agent as agent_module

        mock_manager = MagicMock()
        mock_manager.get_morning_briefing.return_value = (None, "")
        mock_manager.get_market_recap.return_value = (None, "")
        # 25 flash items — verifies the 20-truncation bug is fixed
        mock_manager.get_flash_news.return_value = (
            [
                {
                    "title": f"快讯{i}",
                    "publish_time": f"2026-07-25 09:{i:02d}:00",
                    "source": "eastmoney",
                }
                for i in range(25)
            ],
            "eastmoney",
        )
        mock_manager.get_zt_pool.return_value = ([], "akshare", None)
        mock_manager.get_daily_dragon_tiger.return_value = ({"stocks": []}, "zzshare")
        monkeypatch.setattr(agent_module, "get_manager", lambda: mock_manager)
        monkeypatch.setattr(agent_module, "_classify_market_session", lambda _is_td: "post-market")

        r = client.get(
            "/api/v1/agent/market-context?flash_limit=200&trade_date=2026-07-25&format=md"
        )
        body = r.text
        # All 25 must appear; the last one's title is unique
        assert "快讯0" in body
        assert "快讯24" in body
        # Section header reflects the actual count, not the truncate-cap
        assert "### 快讯 (25 条)" in body

    def test_market_context_zt_dt_full_pool_table(self, client, monkeypatch):
        """zt/dt pools must be rendered as a full table, not just a count."""
        from unittest.mock import MagicMock

        from stock_data.api.routes import agent as agent_module

        mock_manager = MagicMock()
        mock_manager.get_morning_briefing.return_value = (None, "")
        mock_manager.get_market_recap.return_value = (None, "")
        mock_manager.get_flash_news.return_value = ([], "eastmoney")
        mock_manager.get_zt_pool.side_effect = [
            (
                [
                    {
                        "code": "600519",
                        "name": "茅台",
                        "pct_chg": 10.0,
                        "limit_time": "10:00",
                        "limit_count": 2,
                        "industry": "白酒",
                    },
                    {
                        "code": "688981",
                        "name": "中芯",
                        "pct_chg": 20.0,
                        "limit_time": "13:30",
                        "limit_count": 1,
                        "industry": "半导体",
                    },
                ],
                "akshare",
                None,
            ),
            (
                [
                    {
                        "code": "000001",
                        "name": "平安",
                        "pct_chg": -10.0,
                        "limit_time": "10:00",
                        "industry": "银行",
                    }
                ],
                "akshare",
                None,
            ),
        ]
        mock_manager.get_daily_dragon_tiger.return_value = ({"stocks": []}, "zzshare")
        monkeypatch.setattr(agent_module, "get_manager", lambda: mock_manager)
        monkeypatch.setattr(agent_module, "_classify_market_session", lambda _is_td: "post-market")

        r = client.get(
            "/api/v1/agent/market-context?flash_limit=10&trade_date=2026-07-25&format=md"
        )
        body = r.text
        # zt pool table headers
        assert "| 代码 | 名称 | 涨跌幅 | 涨停时间 | 连板数 | 所属行业 |" in body
        # zt pool rows
        assert "| 600519 | 茅台 | +10.00% | 10:00 | 2 | 白酒 |" in body
        assert "| 688981 | 中芯 | +20.00% | 13:30 | 1 | 半导体 |" in body
        # dt pool table headers + rows
        assert "| 代码 | 名称 | 涨跌幅 | 跌停时间 | 所属行业 |" in body
        assert "| 000001 | 平安 | -10.00% | 10:00 | 银行 |" in body

    def test_market_context_morning_recap_rendered_in_full(self, client, monkeypatch):
        """morning_briefing / market_recap dicts must be rendered with all fields,
        not just title+date."""
        from unittest.mock import MagicMock

        from stock_data.api.routes import agent as agent_module

        mock_manager = MagicMock()
        mock_manager.get_morning_briefing.return_value = (
            {
                "article_id": 123,
                "title": "早报标题",
                "date": "2026-07-25",
                "url": "https://example.com/123",
                "content": "详细早报内容...",
                "tags": ["宏观", "市场"],
            },
            "cls",
        )
        mock_manager.get_market_recap.return_value = (
            {
                "article_id": 456,
                "title": "复盘标题",
                "date": "2026-07-25",
                "url": "https://example.com/456",
                "content": "详细复盘内容...",
            },
            "cls",
        )
        mock_manager.get_flash_news.return_value = ([], "eastmoney")
        mock_manager.get_zt_pool.return_value = ([], "akshare", None)
        mock_manager.get_daily_dragon_tiger.return_value = ({"stocks": []}, "zzshare")
        monkeypatch.setattr(agent_module, "get_manager", lambda: mock_manager)
        monkeypatch.setattr(agent_module, "_classify_market_session", lambda _is_td: "post-market")

        r = client.get(
            "/api/v1/agent/market-context?flash_limit=10&trade_date=2026-07-25&format=md"
        )
        body = r.text
        # Every field of the morning_briefing dict appears
        for field in ("article_id", "title", "date", "url", "content", "tags"):
            assert f"| {field} |" in body, f"morning_briefing field {field} missing"
        # Every field of the market_recap dict appears
        for field in ("article_id", "title", "date", "url", "content"):
            assert body.count(f"| {field} |") >= 2, (
                f"market_recap field {field} missing (count={body.count('| ' + field + ' |')})"
            )

    def test_market_context_dragon_tiger_full_table(self, client, monkeypatch):
        """dragon_tiger.stocks MUST be rendered as a full table, not only the
        top-10 summary."""
        from unittest.mock import MagicMock

        from stock_data.api.routes import agent as agent_module

        mock_manager = MagicMock()
        mock_manager.get_morning_briefing.return_value = (None, "")
        mock_manager.get_market_recap.return_value = (None, "")
        mock_manager.get_flash_news.return_value = ([], "eastmoney")
        mock_manager.get_zt_pool.return_value = ([], "akshare", None)
        # 12 stocks so the top-10 summary is NOT the full list
        mock_manager.get_daily_dragon_tiger.return_value = (
            {
                "date": "2026-07-25",
                "stocks": [
                    {
                        "code": f"60{i:04d}",
                        "name": f"股票{i}",
                        "net_buy_wan": 1000.0 * (12 - i),
                        "buy_wan": 5000.0,
                        "sell_wan": 4000.0,
                        "total_amount_wan": 50000.0,
                        "pct_chg": 5.0,
                        "pct_chg_after": 7.0,
                    }
                    for i in range(12)
                ],
            },
            "zzshare",
        )
        monkeypatch.setattr(agent_module, "get_manager", lambda: mock_manager)
        monkeypatch.setattr(agent_module, "_classify_market_session", lambda _is_td: "post-market")

        r = client.get(
            "/api/v1/agent/market-context?flash_limit=10&trade_date=2026-07-25&format=md"
        )
        body = r.text
        # Full table header
        assert (
            "| 代码 | 名称 | 净买入(万元) | 买入金额(万元) | 卖出金额(万元) | "
            "成交额(万元) | 涨跌幅 | 解读后涨幅 |"
        ) in body
        # Full table is the full list — not just top 10
        assert "龙虎榜全表 (12 只)" in body
        # The 12th stock (lowest net_buy) only appears in the FULL table,
        # not in top_by_net_buy (which is sorted desc, top 10). So this row
        # is the regression net for "was the full table dropped?".
        assert "600011" in body  # code from the 12th item
        # And the full table cell carries its computed buy/sell/total:
        # code 600011, name 股票11, net_buy = 1000.00 (12 - 11 = 1 × 1000).
        assert "| 600011 | 股票11 | 1,000 | 5,000 | 4,000 | 50,000 |" in body

    def test_market_context_dragon_tiger_summary_still_present(self, client, monkeypatch):
        """The summary top-10 sections stay (alongside the full table) — they're
        complementary, not a replacement."""
        from unittest.mock import MagicMock

        from stock_data.api.routes import agent as agent_module

        mock_manager = MagicMock()
        mock_manager.get_morning_briefing.return_value = (None, "")
        mock_manager.get_market_recap.return_value = (None, "")
        mock_manager.get_flash_news.return_value = ([], "eastmoney")
        mock_manager.get_zt_pool.return_value = ([], "akshare", None)
        mock_manager.get_daily_dragon_tiger.return_value = (
            {
                "stocks": [
                    {
                        "code": "600519",
                        "name": "茅台",
                        "net_buy_wan": 5000.0,
                        "buy_wan": 8000.0,
                        "sell_wan": 3000.0,
                        "total_amount_wan": 100000.0,
                        "pct_chg": 5.0,
                        "pct_chg_after": 7.0,
                    }
                ],
            },
            "zzshare",
        )
        monkeypatch.setattr(agent_module, "get_manager", lambda: mock_manager)
        monkeypatch.setattr(agent_module, "_classify_market_session", lambda _is_td: "post-market")

        r = client.get(
            "/api/v1/agent/market-context?flash_limit=10&trade_date=2026-07-25&format=md"
        )
        body = r.text
        # Summary header + full table both present
        assert "### 净买入 Top 10" in body
        assert "### 龙虎榜全表 (1 只)" in body
        # Summary aggregate value
        assert "**全市场净买入合计**: 5,000" in body
