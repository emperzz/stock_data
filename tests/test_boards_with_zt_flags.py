"""Tests for the ?with_zt_flags=true extension on /boards/{code}/stocks."""
from unittest.mock import patch

import pytest

from stock_data.api.routes import reset_manager


@pytest.fixture(autouse=True)
def reset_before_test():
    reset_manager()
    yield


_PERSISTENCE_PATCH = "stock_data.data_provider.persistence.board.get_board_stocks"
_ZT_POOL_PATCH = "stock_data.data_provider.manager.DataFetcherManager.get_zt_pool"


class TestWithZtFlags:
    def test_default_no_zt_flags_no_is_limit_up(self, client):
        """with_zt_flags omitted (default) → is_limit_up and lb_count are None on every stock."""
        with patch(_PERSISTENCE_PATCH) as mock_bs, patch(_ZT_POOL_PATCH) as mock_zt:
            mock_bs.return_value = (
                [{"stock_code": "600519", "stock_name": "贵州茅台"}],
                "persistence",
                "ths",
                None,
                False,
                1,
            )
            response = client.get(
                "/api/v1/boards/885595/stocks?source=ths&include_quote=false"
            )
            assert response.status_code == 200
            data = response.json()
            assert data["stocks"][0]["is_limit_up"] is None
            assert data["stocks"][0]["lb_count"] is None
            # zt-pool should NOT be called when with_zt_flags is not set
            mock_zt.assert_not_called()

    def test_with_zt_flags_true_marks_limit_up(self, client):
        """with_zt_flags=true → stock present in zt-pool → is_limit_up=True, lb_count echoed."""
        with patch(_PERSISTENCE_PATCH) as mock_bs, patch(_ZT_POOL_PATCH) as mock_zt:
            mock_bs.return_value = (
                [
                    {"stock_code": "600519", "stock_name": "贵州茅台"},
                    {"stock_code": "000001", "stock_name": "平安银行"},
                ],
                "persistence",
                "ths",
                None,
                False,
                2,
            )
            mock_zt.return_value = (
                [
                    {"code": "600519", "name": "贵州茅台", "lb_count": 3},
                    {"code": "688981", "name": "中芯国际", "lb_count": 1},
                ],
                "akshare",
                None,
            )
            response = client.get(
                "/api/v1/boards/885595/stocks?source=ths&include_quote=false&with_zt_flags=true"
            )
            assert response.status_code == 200
            data = response.json()
            assert data["stocks"][0]["is_limit_up"] is True
            assert data["stocks"][0]["lb_count"] == 3
            assert data["stocks"][1]["is_limit_up"] is False
            assert data["stocks"][1]["lb_count"] is None

    def test_with_zt_flags_pool_empty(self, client):
        """zt-pool returns empty list → all is_limit_up=False, no error."""
        with patch(_PERSISTENCE_PATCH) as mock_bs, patch(_ZT_POOL_PATCH) as mock_zt:
            mock_bs.return_value = (
                [{"stock_code": "600519", "stock_name": "贵州茅台"}],
                "persistence",
                "ths",
                None,
                False,
                1,
            )
            mock_zt.return_value = ([], "akshare", None)
            response = client.get(
                "/api/v1/boards/885595/stocks?source=ths&include_quote=false&with_zt_flags=true"
            )
            assert response.status_code == 200
            data = response.json()
            assert data["stocks"][0]["is_limit_up"] is False
            assert data["stocks"][0]["lb_count"] is None
