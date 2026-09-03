"""Pin the new ``STOCK_ZT_REASON`` capability + ``get_zt_reason`` method.

Per the 2026-09-03 refactor: zzshare's upstream ``review_uplimit_reason``
endpoint is now exposed as a dedicated ZT-REASON capability distinct
from the deprecated ``STOCK_ZT_POOL``. The new method:

- declares ``DataCapability.STOCK_ZT_REASON`` in
  ``ZzshareFetcher.supported_data_types``;
- exposes the method ``get_zt_reason(self, date)``;
- uses zzshare's existing row-level ``reason`` field (probe
  fixture pins the upstream key);
- reads ``up_limit_time`` as ``last_seal_time`` (NOT ``first_seal_time`` —
  zzshare's up_limit_time is the LAST seal, per 2026-09-03 clarification).
"""
from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _isolate_zzshare_cls_state():
    """Reset class-level init state between tests (mirrors test_zzshare_fetcher.py)."""
    from stock_data.data_provider.fetchers.zzshare_fetcher import ZzshareFetcher

    saved = (
        ZzshareFetcher._init_attempted,
        ZzshareFetcher._init_ok,
        ZzshareFetcher._cls_token,
        ZzshareFetcher._init_error,
        ZzshareFetcher._api,
    )
    ZzshareFetcher._init_attempted = False
    ZzshareFetcher._init_ok = False
    ZzshareFetcher._cls_token = ""
    ZzshareFetcher._init_error = None
    ZzshareFetcher._api = None
    yield
    (
        ZzshareFetcher._init_attempted,
        ZzshareFetcher._init_ok,
        ZzshareFetcher._cls_token,
        ZzshareFetcher._init_error,
        ZzshareFetcher._api,
    ) = saved


class TestZtReasonCapability:
    def test_capability_flag_exists(self):
        from stock_data.data_provider.base import DataCapability

        assert hasattr(DataCapability, "STOCK_ZT_REASON"), (
            "DataCapability.STOCK_ZT_REASON must be added in base.py."
        )

    def test_capability_in_method_map(self):
        from stock_data.data_provider.base import (
            CAPABILITY_TO_METHOD,
            DataCapability,
        )

        cap = DataCapability.STOCK_ZT_REASON
        assert cap in CAPABILITY_TO_METHOD
        assert CAPABILITY_TO_METHOD[cap] == "get_zt_reason"

    def test_capability_explorer_label_registered(self):
        from stock_data.data_provider.base import DataCapability
        from stock_data.explorer.tags import CAPABILITY_LABELS

        cap = DataCapability.STOCK_ZT_REASON
        assert cap.name in CAPABILITY_LABELS
        entry = CAPABILITY_LABELS[cap.name]
        assert "label" in entry and entry["label"].strip()
        assert "icon" in entry and entry["icon"].strip()

    def test_zzshare_declares_zt_reason_capability(self):
        from stock_data.data_provider.base import DataCapability
        from stock_data.data_provider.fetchers.zzshare_fetcher import ZzshareFetcher

        assert DataCapability.STOCK_ZT_REASON in ZzshareFetcher.supported_data_types


class TestZzshareGetZtReason:
    def _fetcher_with_api(self, plates=None, rt_value=None):
        from unittest.mock import MagicMock

        from stock_data.data_provider.fetchers.zzshare_fetcher import ZzshareFetcher

        fetcher = ZzshareFetcher()
        fake_api = MagicMock()
        fake_api.uplimit_hot = MagicMock(return_value={})
        fake_api.review_uplimit_reason = MagicMock(
            return_value=plates if plates is not None else []
        )
        ZzshareFetcher._api = fake_api
        ZzshareFetcher._init_attempted = True
        return fetcher

    # Real upstream shape probed 2026-07-10 from review_uplimit_reason.
    _STOCK_ROW = {
        "id": 364247,
        "date1": "2026-07-10",
        "plate_code": "801843",
        "plate_name": "业绩增长",
        "plate_score": 20234,
        "stock_code": "002115",
        "stock_name": "三维通信",
        "stock_price": 10.95,
        "up_limit_keep_times": 1,
        "up_limit_desc": "首板",
        "up_limit_type": "封",
        "up_limit_time": "09:31",
        "reason": "业绩增长+行业利好",
        "fengdan_volumn": 225468.0,
        "fengdan_money": 246887000.0,
        "fengdan_rate": 2.33,
        "feng_circulation_rate": 3.34,
        "actualcirculation_value": 7387130000.0,
        "turnover_ration_real": 1.43,
    }

    def _make_plate(self, stocks, plate_code="801843", plate_name="业绩增长"):
        return {
            "plate_code": plate_code,
            "plate_name": plate_name,
            "plate_score": 20234,
            "stocks": stocks,
        }

    def test_get_zt_reason_returns_required_zzshare_actual_fields(self):
        """Pin the kept fields: code/name/price/change_pct/circ_mv/turnover_rate
        /lb_count/last_seal_time/seal_amount/zt_count/+reason."""
        plates = [self._make_plate([dict(self._STOCK_ROW)])]
        fetcher = self._fetcher_with_api(plates=plates)

        result = fetcher.get_zt_reason("2026-05-20")

        assert result is not None
        assert len(result) == 1
        row = result[0]
        # Required upstream fields actually present.
        assert row["code"] == "002115"
        assert row["name"] == "三维通信"
        assert row["price"] == 10.95
        assert row["change_pct"] is None  # zzshare `fd_close` is missing in fixture
        assert row["circ_mv"] == 7387130000.0
        assert row["turnover_rate"] == 1.43
        assert row["lb_count"] == 1
        assert row["last_seal_time"] == "09:31:00"
        assert row["seal_amount"] == 246887000.0
        assert row["zt_count"] == "首板"
        assert row["reason"] == "业绩增长+行业利好"

    def test_get_zt_reason_drops_unsupported_fields(self):
        """zzshare does not surface amount/total_mv/seal_count/first_seal_time —
        these fields are dropped from the contract."""
        plates = [self._make_plate([dict(self._STOCK_ROW)])]
        fetcher = self._fetcher_with_api(plates=plates)
        result = fetcher.get_zt_reason("2026-05-20")
        row = result[0]
        # Dropped fields MUST NOT appear (not even as None keys).
        assert "amount" not in row
        assert "total_mv" not in row
        assert "seal_count" not in row
        assert "first_seal_time" not in row

    def test_get_zt_reason_last_seal_time_not_first(self):
        """Per 2026-09-03 user clarification: zzshare's ``up_limit_time``
        is the LAST seal, NOT the first; first_seal_time is therefore
        absent from the row (we only have last). last_seal_time carries
        the upstream value."""
        plates = [self._make_plate([dict(self._STOCK_ROW)])]
        fetcher = self._fetcher_with_api(plates=plates)
        result = fetcher.get_zt_reason("2026-05-20")
        row = result[0]
        assert "first_seal_time" not in row
        assert row["last_seal_time"] == "09:31:00"

    def test_get_zt_reason_seal_time_hhmm_to_hhmmss(self):
        stock = dict(self._STOCK_ROW, up_limit_time="14:55")
        plates = [self._make_plate([stock])]
        fetcher = self._fetcher_with_api(plates=plates)
        result = fetcher.get_zt_reason("2026-05-20")
        assert result[0]["last_seal_time"] == "14:55:00"

    def test_get_zt_reason_deduplicates_across_plates(self):
        stock = dict(self._STOCK_ROW)
        plates = [
            self._make_plate([stock], plate_code="801843", plate_name="业绩增长"),
            self._make_plate([stock], plate_code="801574", plate_name="5G概念"),
        ]
        fetcher = self._fetcher_with_api(plates=plates)
        result = fetcher.get_zt_reason("2026-05-20")
        assert len(result) == 1
        assert result[0]["code"] == "002115"

    def test_get_zt_reason_empty_returns_none(self):
        """Empty upstream response (no token / no data) → None to trigger failover."""
        fetcher = self._fetcher_with_api(plates=[])
        assert fetcher.get_zt_reason("2026-05-20") is None

    def test_get_zt_reason_date_converted_to_yyyymmdd(self):
        plates = [self._make_plate([dict(self._STOCK_ROW)])]
        fetcher = self._fetcher_with_api(plates=plates)
        fetcher.get_zt_reason("2026-05-20")
        from stock_data.data_provider.fetchers.zzshare_fetcher import ZzshareFetcher

        call = ZzshareFetcher._api.review_uplimit_reason.call_args
        assert call.kwargs.get("date1") == "20260520"

    def test_get_zt_reason_sdk_unavailable_returns_none(self, monkeypatch):
        from unittest.mock import patch

        from stock_data.data_provider.fetchers.zzshare_fetcher import ZzshareFetcher

        monkeypatch.delenv("ZZSHARE_TOKEN", raising=False)
        with patch("importlib.util.find_spec", return_value=None):
            fetcher = ZzshareFetcher()
            assert fetcher.get_zt_reason("2026-05-20") is None

    def test_get_zt_reason_skips_non_dict_plates(self):
        """Defensive: non-dict plate entries (e.g. legacy payloads) must be skipped."""
        plates = [self._make_plate([dict(self._STOCK_ROW)]), "broken", None]
        fetcher = self._fetcher_with_api(plates=plates)
        result = fetcher.get_zt_reason("2026-05-20")
        assert result is not None
        assert len(result) == 1
        assert result[0]["code"] == "002115"

    def test_get_zt_reason_preserves_normalized_code(self):
        """Outbound ts_code suffix (.SZ/.SH) MUST NOT leak into the
        code field — ``normalize_stock_code`` is the only code formatter
        we use on the response side."""
        from stock_data.data_provider.utils.normalize import normalize_stock_code

        stock = dict(self._STOCK_ROW, stock_code="002115.SZ")
        plates = [self._make_plate([stock])]
        fetcher = self._fetcher_with_api(plates=plates)
        result = fetcher.get_zt_reason("2026-05-20")
        assert result[0]["code"] == normalize_stock_code("002115.SZ")
        assert ".SZ" not in result[0]["code"]
