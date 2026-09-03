"""Pin the new ``/api/v1/zt-reasons`` route + ``/zt-reasons`` schema.

Mirrors ``/api/v1/zt-pools`` ergonomics (date-default to latest trade
date; source = zzshare); distinct schema fields (no amount/total_mv/
seal_count/first_seal_time, plus the new ``reason`` field).
"""
from __future__ import annotations

from unittest.mock import patch

import pytest

from stock_data.api.routes import reset_manager


@pytest.fixture(autouse=True)
def reset_before_test():
    reset_manager()
    yield


_MANAGER_GET_REASONS = "stock_data.data_provider.manager.DataFetcherManager.get_zt_reasons"


class TestZtReasonsRoute:
    def test_route_path_exists(self):
        """``GET /zt-reasons`` must be registered on the boards router
        (server.py mounts the router under ``/api/v1``)."""
        from stock_data.api.routes.boards import router

        paths = {getattr(r, "path", "") for r in router.routes}
        assert "/zt-reasons" in paths

    def test_route_accepts_date_query_param(self, client):
        """?date=YYYY-MM-DD is forwarded to the manager call."""
        with patch(_MANAGER_GET_REASONS) as mock_get:
            mock_get.return_value = (
                [
                    {
                        "code": "002115",
                        "name": "三维通信",
                        "price": 10.95,
                        "change_pct": 9.95,
                        "circ_mv": 7387130000.0,
                        "turnover_rate": 1.43,
                        "lb_count": 1,
                        "last_seal_time": "09:31:00",
                        "seal_amount": 246887000.0,
                        "zt_count": "首板",
                        "reason": "业绩增长+行业利好",
                    }
                ],
                "zzshare",
                None,
            )
            resp = client.get("/api/v1/zt-reasons?date=2026-05-20")
            assert resp.status_code == 200
            data = resp.json()
            assert data["date"] == "2026-05-20"
            assert data["type"] == "reason"
            assert data["total"] == 1
            assert data["source"] == "zzshare"
            assert data["stocks"][0]["code"] == "002115"
            assert data["stocks"][0]["reason"] == "业绩增长+行业利好"

            # Manager call signature: only the date param is forwarded; no
            # ``type`` (replacement for legacy pool_type).
            mock_get.assert_called_once()
            call_kwargs = mock_get.call_args.kwargs
            call_args = mock_get.call_args.args
            if "date" in call_kwargs:
                assert call_kwargs["date"] == "2026-05-20"
            else:
                assert call_args[0] == "2026-05-20"

    def test_invalid_date_returns_422(self, client):
        resp = client.get("/api/v1/zt-reasons?date=not-a-date")
        assert resp.status_code == 422

    def test_empty_pool_returns_404(self, client):
        with patch(_MANAGER_GET_REASONS) as mock_get:
            mock_get.return_value = ([], "zzshare", None)
            resp = client.get("/api/v1/zt-reasons?date=2026-05-20")
            assert resp.status_code == 404

    def test_route_excludes_unsupported_fields(self, client):
        """Response stocks MUST NOT carry first_seal_time/amount/total_mv/seal_count."""
        with patch(_MANAGER_GET_REASONS) as mock_get:
            mock_get.return_value = (
                [
                    {
                        "code": "002115",
                        "name": "三维通信",
                        "price": 10.95,
                        "change_pct": 9.95,
                        "circ_mv": 7387130000.0,
                        "turnover_rate": 1.43,
                        "lb_count": 1,
                        "last_seal_time": "09:31:00",
                        "seal_amount": 246887000.0,
                        "zt_count": "首板",
                        "reason": "业绩增长+行业利好",
                    }
                ],
                "zzshare",
                None,
            )
            resp = client.get("/api/v1/zt-reasons?date=2026-05-20")
            stock = resp.json()["stocks"][0]
            assert "first_seal_time" not in stock
            assert "amount" not in stock
            assert "total_mv" not in stock
            assert "seal_count" not in stock
            assert "reason" in stock

    def test_route_uses_zt_reasons_tag(self):
        """Route is tagged ``zt-reasons`` so it shows in its own explorer section."""
        from stock_data.api.routes.boards import router

        for route in router.routes:
            if getattr(route, "path", "") == "/zt-reasons":
                assert "zt-reasons" in (getattr(route, "tags", None) or [])
                return
        pytest.fail("Route not found")


class TestZtReasonResponseSchema:
    def test_schema_field_set(self):
        from stock_data.api.schemas import ZTReasonStock

        fields = set(ZTReasonStock.model_fields.keys())
        # Expected kept fields.
        expected = {
            "code",
            "name",
            "price",
            "change_pct",
            "circ_mv",
            "turnover_rate",
            "lb_count",
            "last_seal_time",
            "seal_amount",
            "zt_count",
            "reason",
        }
        assert expected <= fields
        # Must NOT carry legacy ZTPool keys that are absent for zzshare.
        assert "first_seal_time" not in fields
        assert "amount" not in fields
        assert "total_mv" not in fields
        assert "seal_count" not in fields
