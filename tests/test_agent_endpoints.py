"""Tests for /api/v1/agent/* endpoints (Phase 1)."""
from unittest.mock import patch

import pytest

from stock_data.api.routes import reset_manager


@pytest.fixture(autouse=True)
def reset_before_test():
    reset_manager()
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


_STOCK_MEMBERSHIPS_PATCH = (
    "stock_data.data_provider.persistence.board.get_stock_memberships"
)


class TestStocksBoardOverlap:
    def test_two_stocks_common_boards(self, client):
        with patch(_STOCK_MEMBERSHIPS_PATCH) as mock_sm:
            mock_sm.side_effect = [
                (
                    [
                        {"code": "885xxx", "name": "半导体", "type": "concept", "subtype": "", "source": "ths"},
                        {"code": "881yyy", "name": "电子", "type": "industry", "subtype": "", "source": "ths"},
                    ],
                    [],
                    "persistence",
                ),
                (
                    [
                        {"code": "885xxx", "name": "半导体", "type": "concept", "subtype": "", "source": "ths"},
                        {"code": "882zzz", "name": "新能源", "type": "concept", "subtype": "", "source": "ths"},
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
                    [{"code": "885xxx", "name": "X", "type": "concept", "subtype": "", "source": "ths"}],
                    [],
                    "persistence",
                ),
                # Second stock upstream fails
                DataFetchError("network error"),
                # Third stock OK
                (
                    [{"code": "885xxx", "name": "X", "type": "concept", "subtype": "", "source": "ths"}],
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
        return patch(_BOARD_STOCKS_PATCH, return_value=(
            stocks, "persistence", "ths", None, False, len(stocks),
        ))

    def test_filter_turnover_min_excludes_below(self, client):
        """Stocks below the turnover minimum are excluded."""
        rows = [
            {"stock_code": "A", "stock_name": "A", "price": 10.0, "change_pct": 5.0,
             "turnover_rate": 3.0, "amount": 1e9, "total_mv": 1e9, "open": 9.0, "high": 10.0,
             "low": 9.0, "volume": 0},
            {"stock_code": "B", "stock_name": "B", "price": 20.0, "change_pct": 7.0,
             "turnover_rate": 8.0, "amount": 5e9, "total_mv": 5e9, "open": 19.0, "high": 21.0,
             "low": 19.0, "volume": 0},
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
            {"stock_code": "A", "stock_name": "A", "price": 10.0, "change_pct": 1.0,
             "turnover_rate": 5.0, "amount": 1e9, "total_mv": 1e9, "open": 10.0, "high": 10.2,
             "low": 9.8, "volume": 0},
            {"stock_code": "B", "stock_name": "B", "price": 20.0, "change_pct": 6.0,
             "turnover_rate": 10.0, "amount": 5e9, "total_mv": 5e9, "open": 19.0, "high": 21.0,
             "low": 19.0, "volume": 0},
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
            {"stock_code": f"S{i}", "stock_name": f"S{i}", "price": 10.0 + i,
             "change_pct": 5.0, "turnover_rate": 5.0, "amount": 1e9, "total_mv": 1e9,
             "open": 9.0, "high": 10.0, "low": 9.0, "volume": 0}
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
            {"stock_code": "A", "stock_name": "A", "price": 10.0, "change_pct": 0.0,
             "turnover_rate": 1.0, "amount": 0, "total_mv": 1e8, "open": 10.0, "high": 10.0,
             "low": 10.0, "volume": 0},
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
            {"stock_code": "A", "stock_name": "A", "price": 10.0, "change_pct": 5.0,
             "turnover_rate": None, "amount": 1e9, "total_mv": 1e9, "open": 9.0,
             "high": 10.0, "low": 9.0, "volume": 0},
            # B: turnover_rate field omitted entirely → also None → excluded
            {"stock_code": "B", "stock_name": "B", "price": 10.0, "change_pct": 5.0,
             "amount": 1e9, "total_mv": 1e9, "open": 9.0, "high": 10.0,
             "low": 9.0, "volume": 0},
            # C: turnover_rate=8.0 (>= 5.0) → included
            {"stock_code": "C", "stock_name": "C", "price": 20.0, "change_pct": 7.0,
             "turnover_rate": 8.0, "amount": 5e9, "total_mv": 5e9, "open": 19.0,
             "high": 21.0, "low": 19.0, "volume": 0},
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
                    [{"code": "885xxx", "name": "半导体", "type": "concept",
                      "subtype": "", "source": "ths"}],
                    [],
                    "persistence",
                ),
                (
                    [{"code": "885xxx", "name": "半导体", "type": "concept",
                      "subtype": "", "source": "ths"}],
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

    def test_cache_hit_filter_stocks(self, client):
        rows = [
            {"stock_code": "X", "stock_name": "X", "price": 10.0, "change_pct": 5.0,
             "turnover_rate": 8.0, "amount": 1e9, "total_mv": 1e9, "open": 9.0,
             "high": 10.0, "low": 9.0, "volume": 0},
        ]
        with patch(_BOARD_STOCKS_PATCH, return_value=(
            rows, "persistence", "ths", None, False, len(rows),
        )) as mock_bs:
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
