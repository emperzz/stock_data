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