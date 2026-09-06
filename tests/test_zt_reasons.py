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
    from stock_data.api.cache import get_reasons_cache

    reset_manager()
    get_reasons_cache().clear()
    yield
    get_reasons_cache().clear()


_MANAGER_GET_REASONS = "stock_data.data_provider.manager.DataFetcherManager.get_zt_reasons"

_SAMPLE_STOCK = {
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

    def test_route_uses_zt_pools_tag(self):
        """Route is tagged ``zt-pools`` so it shares the explorer's 涨跌停股池
        section with ``/zt-pools`` (both endpoints relate to ZT/涨跌停 data)."""
        from stock_data.api.routes.boards import router

        for route in router.routes:
            if getattr(route, "path", "") == "/zt-reasons":
                assert "zt-pools" in (getattr(route, "tags", None) or [])
                return
        pytest.fail("Route not found")


class TestZtReasonsDefaultDate:
    """No ``?date=`` → same trade-calendar resolution ``/zt-pools`` uses.

    Before this contract existed the route did a bare ``date or today``,
    so a weekend/holiday request asked zzshare for a non-trade date,
    got nothing back, and surfaced as 503 ``data_unavailable`` while
    ``/zt-pools`` happily returned the previous trade day.
    """

    def test_omitted_date_on_non_trade_day_uses_latest_trade_date(self, client):
        from stock_data.data_provider.persistence import trade_calendar

        with (
            patch.object(trade_calendar, "is_trade_date", return_value=False),
            patch.object(
                trade_calendar,
                "get_latest_trade_date_on_or_before",
                return_value="2026-09-04",
            ),
            patch(_MANAGER_GET_REASONS) as mock_get,
        ):
            mock_get.return_value = ([_SAMPLE_STOCK], "zzshare", None)
            resp = client.get("/api/v1/zt-reasons")

            assert resp.status_code == 200
            assert resp.json()["date"] == "2026-09-04"
            assert mock_get.call_args.kwargs["date"] == "2026-09-04"

    def test_omitted_date_on_trade_day_uses_today(self, client):
        from datetime import date as date_cls

        from stock_data.data_provider.persistence import trade_calendar

        today_str = date_cls.today().strftime("%Y-%m-%d")
        with (
            patch.object(trade_calendar, "is_trade_date", return_value=True),
            patch(_MANAGER_GET_REASONS) as mock_get,
        ):
            mock_get.return_value = ([_SAMPLE_STOCK], "zzshare", None)
            resp = client.get("/api/v1/zt-reasons")

            assert resp.status_code == 200
            assert resp.json()["date"] == today_str
            assert mock_get.call_args.kwargs["date"] == today_str

    def test_omitted_date_with_empty_calendar_falls_back_to_today(self, client):
        """Empty trade_calendar table → today, so the caller gets a clear
        upstream error instead of a silent 404 (same edge case /zt-pools
        documents at boards.py:1325)."""
        from datetime import date as date_cls

        from stock_data.data_provider.persistence import trade_calendar

        today_str = date_cls.today().strftime("%Y-%m-%d")
        with (
            patch.object(trade_calendar, "is_trade_date", return_value=False),
            patch.object(trade_calendar, "get_latest_trade_date_on_or_before", return_value=None),
            patch(_MANAGER_GET_REASONS) as mock_get,
        ):
            mock_get.return_value = ([_SAMPLE_STOCK], "zzshare", None)
            resp = client.get("/api/v1/zt-reasons")

            assert resp.status_code == 200
            assert mock_get.call_args.kwargs["date"] == today_str

    def test_explicit_date_bypasses_calendar_resolution(self, client):
        """An explicit ?date= is passed through untouched — even a
        non-trade date (the caller asked for it on purpose)."""
        from stock_data.data_provider.persistence import trade_calendar

        with (
            patch.object(trade_calendar, "is_trade_date", return_value=False),
            patch.object(
                trade_calendar,
                "get_latest_trade_date_on_or_before",
                return_value="2026-09-04",
            ),
            patch(_MANAGER_GET_REASONS) as mock_get,
        ):
            mock_get.return_value = ([_SAMPLE_STOCK], "zzshare", None)
            resp = client.get("/api/v1/zt-reasons?date=2026-09-06")

            assert resp.status_code == 200
            assert resp.json()["date"] == "2026-09-06"
            assert mock_get.call_args.kwargs["date"] == "2026-09-06"


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
