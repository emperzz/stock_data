"""
Unit tests for BaostockFetcher.get_dividend.

Exercises the bs.query_dividend_data → DividendRecord mapping:
- Per-share → per-10-share scaling (×10)
- Newest ex-date first ordering
- Records without an ex-date (预案 / 预披露) are dropped
- page_size cap
- Failure paths (no init, no rows, exception) → empty list
"""

import sys
from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest

from stock_data.data_provider.base import DataCapability
from stock_data.data_provider.fetchers.baostock_fetcher import BaostockFetcher

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_baostock_result(rows: list[list[str]], fields: list[str] | None = None):
    """Build a MagicMock that mimics ``baostock`` Result objects.

    baostock's API surface for ``query_*`` is:
        .error_code == "0"   (str)
        .next() → bool
        .get_row_data() → list[str]
        .fields → list[str]
    """
    if fields is None:
        fields = [
            "code",
            "dividPreNoticeDate",
            "dividAgmPumDate",
            "dividPlanAnnounceDate",
            "dividPlanDate",
            "dividRegistDate",
            "dividOperateDate",
            "dividPayDate",
            "dividStockMarketDate",
            "dividCashPsBeforeTax",
            "dividCashPsAfterTax",
            "dividStocksPs",
            "dividCashStock",
            "dividReserveToStockPs",
        ]
    rs = MagicMock()
    rs.error_code = "0"
    rs.fields = fields
    cursor = {"i": 0}

    def next_call():
        return cursor["i"] < len(rows)

    def get_row():
        i = cursor["i"]
        cursor["i"] += 1
        return rows[i]

    rs.next.side_effect = next_call
    rs.get_row_data.side_effect = get_row
    return rs


def _patch_baostock_init(*, ok: bool = True):
    """Mark BaostockFetcher._init_ok = ok without actually calling bs.login().

    The fetcher's ``_ensure_initialized`` runs ``bs.login()`` which hits the
    network. We bypass it by setting the class-level flag directly so the
    downstream ``import baostock as bs`` inside ``get_dividend`` still works
    against our patched ``sys.modules["baostock"]``.
    """
    BaostockFetcher._init_attempted = True
    BaostockFetcher._init_ok = ok


@pytest.fixture(autouse=True)
def _restore_init_flags():
    """Reset init flags around each test so leakage doesn't poison neighbours."""
    saved = (
        BaostockFetcher._init_attempted,
        BaostockFetcher._init_ok,
    )
    yield
    BaostockFetcher._init_attempted, BaostockFetcher._init_ok = saved


@pytest.fixture(autouse=True)
def _no_real_baostock():
    """Each test starts with a clean ``sys.modules['baostock']`` so patches work."""
    real = sys.modules.pop("baostock", None)
    yield
    # Restore so subsequent test files (or this one, on re-import) see
    # whatever the next test set.
    if real is not None:
        sys.modules["baostock"] = real


# ---------------------------------------------------------------------------
# Capability
# ---------------------------------------------------------------------------


class TestCapability:
    def test_dividend_capability_declared(self):
        assert DataCapability.DIVIDEND in BaostockFetcher.supported_data_types

    def test_method_resolves(self):
        assert callable(getattr(BaostockFetcher, "get_dividend", None))


# ---------------------------------------------------------------------------
# Happy path: per-share → per-10-share mapping
# ---------------------------------------------------------------------------


class TestGetDividendNormalPayload:
    @patch.dict(sys.modules, {"baostock": MagicMock()})
    def test_maps_per_share_to_per_10_share(self):
        """baostock fields are per-share; schema is per-10-share (×10)."""
        sys.modules["baostock"].query_dividend_data.return_value = _make_baostock_result(
            [
                [
                    "sh.600519",
                    "",
                    "",
                    "",
                    "",
                    "2025-06-18",
                    "2025-06-23",
                    "2025-06-23",
                    "",
                    "21.91",  # dividCashPsBeforeTax (元/股)
                    "19.72",  # dividCashPsAfterTax
                    "0.0",  # dividStocksPs (送股/股)
                    "10派21.91元(含税)",  # dividCashStock
                    "0.0",  # dividReserveToStockPs (转增/股)
                ],
            ]
        )
        _patch_baostock_init(ok=True)

        fetcher = BaostockFetcher()
        result = fetcher.get_dividend("600519", page_size=20)

        assert len(result) == 1
        assert result[0]["date"] == "2025-06-23"
        assert result[0]["bonus_rmb"] == 21.91
        # 0.0 × 10 = 0.0 (送股)
        assert result[0]["bonus_ratio"] == 0.0
        # 0.0 × 10 = 0.0 (转增)
        assert result[0]["transfer_ratio"] == 0.0
        assert result[0]["plan"] == "实施"

    @patch.dict(sys.modules, {"baostock": MagicMock()})
    def test_scales_bonus_and_transfer_to_per_10(self):
        """送股 / 转增 should be multiplied by 10 to match schema."""
        sys.modules["baostock"].query_dividend_data.return_value = _make_baostock_result(
            [
                [
                    "sh.600519",
                    "",
                    "",
                    "",
                    "",
                    "2024-05-15",
                    "2024-05-20",
                    "2024-05-20",
                    "",
                    "0.50",  # dividCashPsBeforeTax
                    "0.45",  # dividCashPsAfterTax
                    "0.30",  # dividStocksPs = 0.30 股/股  → ×10 = 3 股/10股
                    "10转3派5元",  # dividCashStock
                    "0.20",  # dividReserveToStockPs = 0.20 股/股 → ×10 = 2 股/10股
                ],
            ]
        )
        _patch_baostock_init(ok=True)

        fetcher = BaostockFetcher()
        result = fetcher.get_dividend("600519")

        assert len(result) == 1
        assert result[0]["bonus_rmb"] == 0.50
        assert result[0]["bonus_ratio"] == 3.0  # 0.30 × 10
        assert result[0]["transfer_ratio"] == 2.0  # 0.20 × 10

    @patch.dict(sys.modules, {"baostock": MagicMock()})
    def test_sorts_newest_first(self):
        """Results must be sorted by ex-date desc (matches EastMoney/Zhitu)."""
        sys.modules["baostock"].query_dividend_data.return_value = _make_baostock_result(
            [
                [
                    "sh.600000",
                    "",
                    "",
                    "",
                    "",
                    "2023-07-10",
                    "2023-07-15",
                    "2023-07-15",
                    "",
                    "0.10",
                    "0.09",
                    "0.0",
                    "10派1元",
                    "0.0",
                ],
                [
                    "sh.600000",
                    "",
                    "",
                    "",
                    "",
                    "2025-06-18",
                    "2025-06-23",
                    "2025-06-23",
                    "",
                    "0.50",
                    "0.45",
                    "0.0",
                    "10派5元",
                    "0.0",
                ],
                [
                    "sh.600000",
                    "",
                    "",
                    "",
                    "",
                    "2024-06-12",
                    "2024-06-17",
                    "2024-06-17",
                    "",
                    "0.30",
                    "0.27",
                    "0.0",
                    "10派3元",
                    "0.0",
                ],
            ]
        )
        _patch_baostock_init(ok=True)

        fetcher = BaostockFetcher()
        result = fetcher.get_dividend("600000")

        assert [r["date"] for r in result] == [
            "2025-06-23",
            "2024-06-17",
            "2023-07-15",
        ]

    @patch.dict(sys.modules, {"baostock": MagicMock()})
    def test_drops_records_without_ex_date(self):
        """预案 / 预披露 rows have empty dividOperateDate — drop them."""
        sys.modules["baostock"].query_dividend_data.return_value = _make_baostock_result(
            [
                # Pre-disclosure (预案 only) — must be filtered.
                [
                    "sh.600000",
                    "2026-01-10",
                    "",
                    "",
                    "",
                    "",
                    "",
                    "",
                    "",
                    "0.20",
                    "0.18",
                    "0.0",
                    "10派2元",
                    "0.0",
                ],
                # Operated — kept.
                [
                    "sh.600000",
                    "",
                    "",
                    "",
                    "",
                    "2025-06-18",
                    "2025-06-23",
                    "2025-06-23",
                    "",
                    "0.50",
                    "0.45",
                    "0.0",
                    "10派5元",
                    "0.0",
                ],
            ]
        )
        _patch_baostock_init(ok=True)

        fetcher = BaostockFetcher()
        result = fetcher.get_dividend("600000")

        assert len(result) == 1
        assert result[0]["date"] == "2025-06-23"

    @patch.dict(sys.modules, {"baostock": MagicMock()})
    def test_page_size_caps_results(self):
        """page_size is a hard cap applied after the desc sort."""
        rows = []
        for year in range(2020, 2025):
            rows.append(
                [
                    "sh.600000",
                    "",
                    "",
                    "",
                    "",
                    f"{year}-06-18",
                    f"{year}-06-23",
                    f"{year}-06-23",
                    "",
                    "0.50",
                    "0.45",
                    "0.0",
                    "10派5元",
                    "0.0",
                ]
            )
        sys.modules["baostock"].query_dividend_data.return_value = _make_baostock_result(rows)
        _patch_baostock_init(ok=True)

        fetcher = BaostockFetcher()
        result = fetcher.get_dividend("600000", page_size=2)

        assert len(result) == 2
        assert result[0]["date"] == "2024-06-23"
        assert result[1]["date"] == "2023-06-23"

    @patch.dict(sys.modules, {"baostock": MagicMock()})
    def test_empty_string_numeric_fields_default_to_zero(self):
        """Baostock may return "" for any numeric field — must coerce to 0."""
        sys.modules["baostock"].query_dividend_data.return_value = _make_baostock_result(
            [
                [
                    "sh.600000",
                    "",
                    "",
                    "",
                    "",
                    "2025-06-18",
                    "2025-06-23",
                    "2025-06-23",
                    "",
                    "",  # dividCashPsBeforeTax blank
                    "",  # dividCashPsAfterTax blank
                    "",  # dividStocksPs blank
                    "",  # dividCashStock blank
                    "",
                ],  # dividReserveToStockPs blank
            ]
        )
        _patch_baostock_init(ok=True)

        fetcher = BaostockFetcher()
        result = fetcher.get_dividend("600000")

        assert len(result) == 1
        assert result[0]["bonus_rmb"] == 0.0
        assert result[0]["bonus_ratio"] == 0.0
        assert result[0]["transfer_ratio"] == 0.0

    @patch.dict(sys.modules, {"baostock": MagicMock()})
    def test_short_tuple_does_not_raise(self):
        """Tuple shorter than the dividend schema (corrupted row) — length guard wins."""
        sys.modules["baostock"].query_dividend_data.return_value = _make_baostock_result(
            [
                ["sh.600000"],  # only 1 element
            ]
        )
        _patch_baostock_init(ok=True)

        fetcher = BaostockFetcher()
        result = fetcher.get_dividend("600000")

        # Short row → no ex-date → filtered out → empty list.
        assert result == []


# ---------------------------------------------------------------------------
# Failure paths — empty list (so manager failover moves on)
# ---------------------------------------------------------------------------


class TestGetDividendFailurePaths:
    def test_returns_empty_when_init_failed(self):
        """``_init_ok=False`` (e.g. no token / login failed) → []."""
        _patch_baostock_init(ok=False)

        fetcher = BaostockFetcher()
        result = fetcher.get_dividend("600519")
        assert result == []

    @patch.dict(sys.modules, {"baostock": MagicMock()})
    def test_returns_empty_when_no_rows(self):
        """Both years query empty (e.g. delisted code) → []."""
        sys.modules["baostock"].query_dividend_data.return_value = _make_baostock_result([])
        _patch_baostock_init(ok=True)

        fetcher = BaostockFetcher()
        result = fetcher.get_dividend("600519")
        assert result == []

    @patch.dict(sys.modules, {"baostock": MagicMock()})
    def test_returns_empty_on_exception(self):
        """Any bs.query_dividend_data exception → [] (failover signal)."""
        sys.modules["baostock"].query_dividend_data.side_effect = RuntimeError(
            "baostock backend down"
        )
        _patch_baostock_init(ok=True)

        fetcher = BaostockFetcher()
        result = fetcher.get_dividend("600519")
        assert result == []

    @patch.dict(sys.modules, {"baostock": None})
    def test_returns_empty_when_baostock_not_installed(self):
        """``import baostock`` raises ImportError → []."""
        # ``None`` in sys.modules makes import raise ImportError.
        _patch_baostock_init(ok=True)
        fetcher = BaostockFetcher()
        result = fetcher.get_dividend("600519")
        assert result == []

    @patch.dict(sys.modules, {"baostock": MagicMock()})
    def test_pulls_both_previous_and_current_year(self):
        """We query ``current_year - 1`` and ``current_year`` — covers recent ex-dates."""
        sys.modules["baostock"].query_dividend_data.return_value = _make_baostock_result([])
        _patch_baostock_init(ok=True)

        fetcher = BaostockFetcher()
        fetcher.get_dividend("600519")

        # 2 calls (prev year + this year), both with yearType="operate".
        assert sys.modules["baostock"].query_dividend_data.call_count == 2
        years = {
            call.kwargs["year"]
            for call in sys.modules["baostock"].query_dividend_data.call_args_list
        }
        assert str(datetime.now().year) in years
        assert str(datetime.now().year - 1) in years
        # All calls must use the "operate" yearType so we get ex-dated records.
        for call in sys.modules["baostock"].query_dividend_data.call_args_list:
            assert call.kwargs["yearType"] == "operate"
