"""Pin the removal of ?with_zt_flags from /api/v1/boards/{code}/stocks.

The feature has been retired: ``with_zt_flags`` query parameter is gone,
``BoardStockInfo.is_limit_up`` and ``lb_count`` fields are gone, and the
helper ``_build_board_stock_info`` no longer accepts those kwargs.

These tests pin the post-removal contract; before the refactor they must
FAIL (proving the parameter / fields still exist).
"""
from __future__ import annotations

import inspect

import pytest


class TestBoardStockInfoNoZtFields:
    """``BoardStockInfo`` must not expose ZT-pool-join fields anymore."""

    def test_is_limit_up_field_is_gone(self):
        from stock_data.api.schemas import BoardStockInfo

        assert "is_limit_up" not in BoardStockInfo.model_fields

    def test_lb_count_field_is_gone(self):
        from stock_data.api.schemas import BoardStockInfo

        assert "lb_count" not in BoardStockInfo.model_fields

    def test_minimal_board_stock_info_still_serializes(self):
        from stock_data.api.schemas import BoardStockInfo

        row = BoardStockInfo(code="600519", name="贵州茅台")
        dumped = row.model_dump()
        assert dumped["code"] == "600519"
        assert dumped["name"] == "贵州茅台"
        assert "is_limit_up" not in dumped
        assert "lb_count" not in dumped


class TestBuildBoardStockInfoSignature:
    """``_build_board_stock_info`` must reject zt kwargs."""

    def test_rejects_is_limit_up_kwarg(self):
        from stock_data.api.routes.boards import _build_board_stock_info

        with pytest.raises(TypeError):
            _build_board_stock_info(
                {"stock_code": "600519", "stock_name": "贵州茅台"},
                is_limit_up=True,
            )

    def test_rejects_lb_count_kwarg(self):
        from stock_data.api.routes.boards import _build_board_stock_info

        with pytest.raises(TypeError):
            _build_board_stock_info(
                {"stock_code": "600519", "stock_name": "贵州茅台"},
                lb_count=3,
            )


class TestRouteSignatureNoWithZtFlags:
    """``/api/v1/boards/{code}/stocks`` must not accept ``with_zt_flags``."""

    def test_route_endpoint_lacks_with_zt_flags_param(self):
        from stock_data.api.routes.boards import router

        # Find the GET /boards/{board_code}/stocks handler.
        stocks_route = None
        for route in router.routes:
            if (
                getattr(route, "path", "").endswith("/boards/{board_code}/stocks")
                and "GET" in getattr(route, "methods", set())
            ):
                stocks_route = route
                break
        assert stocks_route is not None, "GET /boards/{board_code}/stocks route not found"
        sig = inspect.signature(stocks_route.endpoint)
        assert "with_zt_flags" not in sig.parameters
