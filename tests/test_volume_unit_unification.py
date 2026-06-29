"""Volume unit unification per spec §3.4 — all fetchers return shares (股).

Akshare upstream returns lots (手 = 100 shares). KLineData/IntradayData
schema declares volume_unit: Literal['share'] as an invariant. AkshareFetcher
_normalize_data must /100 + int() floor to satisfy the invariant.
"""

import pandas as pd
import pytest
from pydantic import ValidationError

from stock_data.api.schemas import IntradayData, KLineData
from stock_data.data_provider.fetchers.akshare.fetcher import AkshareFetcher

# ============================================================================
# Schema invariant: volume_unit: Literal['share'] is enforced by Pydantic
# ============================================================================


class TestSchemaInvariant:
    """KLineData and IntradayData declare volume_unit: Literal['share']."""

    def test_kline_data_default_volume_unit_is_share(self):
        """KLineData().volume_unit defaults to 'share' (always present)."""
        row = KLineData(
            date="2026-06-29",
            open=10.0,
            high=12.0,
            low=9.0,
            close=11.0,
            volume=50_000,
        )
        assert row.volume_unit == "share"
        out = row.model_dump()
        assert out["volume_unit"] == "share"

    def test_intraday_data_default_volume_unit_is_share(self):
        """IntradayData().volume_unit defaults to 'share' (always present)."""
        row = IntradayData(
            time="10:00:00",
            open=10.0,
            high=12.0,
            low=9.0,
            close=11.0,
            volume=50_000,
        )
        assert row.volume_unit == "share"
        out = row.model_dump()
        assert out["volume_unit"] == "share"

    def test_kline_data_volume_unit_must_be_share(self):
        """Setting volume_unit to 'lot' is rejected by Literal type."""
        with pytest.raises(ValidationError):
            KLineData(
                date="2026-06-29",
                open=10.0,
                high=12.0,
                low=9.0,
                close=11.0,
                volume=50_000,
                volume_unit="lot",  # INVALID — not in Literal['share']
            )

    def test_intraday_data_volume_unit_must_be_share(self):
        """Setting volume_unit to 'lot' is rejected by Literal type."""
        with pytest.raises(ValidationError):
            IntradayData(
                time="10:00:00",
                open=10.0,
                high=12.0,
                low=9.0,
                close=11.0,
                volume=50_000,
                volume_unit="lot",  # INVALID
            )

    def test_kline_data_model_serializer_emits_volume_unit(self):
        """KLineData._serialize includes volume_unit in JSON output."""
        row = KLineData(
            date="2026-06-29",
            open=10.0,
            high=12.0,
            low=9.0,
            close=11.0,
            volume=50_000,
        )
        serialized = row.model_dump()
        assert "volume_unit" in serialized
        assert serialized["volume_unit"] == "share"


# ============================================================================
# AkshareFetcher normalize: convert 手 (lots) to 股 (shares)
# ============================================================================


def _find_normalize_method(fetcher):
    """AkshareFetcher may expose normalize as _normalize_data or normalize."""
    return getattr(fetcher, "_normalize_data", None) or getattr(fetcher, "normalize", None)


class TestAkshareKlineVolumeDivision:
    """AkshareFetcher._normalize_data divides volume by 100 + int() floor.

    Per spec §3.4 — Akshare upstream returns 手; canonical contract is 股.
    `7` lots → `0` shares (NOT 0.07 → Pydantic int coercion failure).
    """

    def test_normalize_data_method_exists(self):
        """AkshareFetcher exposes a normalize method (the entry point for tests)."""
        fetcher = AkshareFetcher.__new__(AkshareFetcher)
        normalize = _find_normalize_method(fetcher)
        assert normalize is not None, (
            "AkshareFetcher has neither _normalize_data nor normalize method"
        )

    def test_volume_is_divided_by_100_with_int_floor(self):
        """Standard k-line normalize: 1234 lots → 12 shares; 7 lots → 0 shares."""
        fetcher = AkshareFetcher.__new__(AkshareFetcher)
        # Akshare upstream: 中文 column names; "成交量" is volume in 手.
        raw_df = pd.DataFrame(
            {
                "日期": ["2026-06-29", "2026-06-29", "2026-06-29", "2026-06-29"],
                "开盘": [10.0, 10.0, 10.0, 10.0],
                "收盘": [11.0, 11.0, 11.0, 11.0],
                "最高": [12.0, 12.0, 12.0, 12.0],
                "最低": [9.0, 9.0, 9.0, 9.0],
                "成交量": [1_234, 7, 25_000, 100],
                "成交额": [12345.0, 2345.0, 34567.0, 4567.0],
                "涨跌幅": [0.5, 0.6, 0.7, 0.8],
            }
        )
        normalize = _find_normalize_method(fetcher)
        out = normalize(raw_df, "600519")

        assert "volume" in out.columns
        volumes = out["volume"].tolist()
        # 1234 // 100 = 12; 7 // 100 = 0; 25_000 // 100 = 250; 100 // 100 = 1
        assert volumes == [12, 0, 250, 1], (
            f"Expected [12, 0, 250, 1] (lots // 100 = shares), got {volumes}"
        )

    def test_volume_is_int_typed_not_fractional_float(self):
        """After /100 + int() floor, volume must NOT be a fractional float.

        `7` 手 → `0` shares (int), not `0.07` (float). The float would
        either fail Pydantic int validation or silently truncate later.
        """
        fetcher = AkshareFetcher.__new__(AkshareFetcher)
        raw_df = pd.DataFrame(
            {
                "日期": ["2026-06-29"],
                "开盘": [10.0],
                "收盘": [11.0],
                "最高": [12.0],
                "最低": [9.0],
                "成交量": [7],
                "成交额": [100.0],
                "涨跌幅": [0.5],
            }
        )
        normalize = _find_normalize_method(fetcher)
        out = normalize(raw_df, "600519")

        v = out["volume"].iloc[0]
        # /100 of 7 is 0.07; without int() floor this is a float. After
        # int() floor, the value is 0 (int) — never a fractional float.
        assert float(v) == float(int(v)), (
            f"volume should be int-typed after /100 + floor, got {v!r} (type {type(v).__name__})"
        )


class TestAkshareIntradayVolumeDivision:
    """akshare/index_norm.normalize_intraday_df divides volume by 100 + int() floor."""

    def test_intraday_volume_is_divided_by_100(self):
        """Intraday normalize: 12_345 手 → 123 shares; 9 手 → 0 shares."""
        from stock_data.data_provider.fetchers.akshare.index_norm import (
            normalize_intraday_df,
        )

        raw_df = pd.DataFrame(
            {
                "时间": ["2026-06-29 10:00:00", "2026-06-29 10:05:00"],
                "开盘": [10.0, 10.1],
                "收盘": [10.1, 10.2],
                "最高": [10.2, 10.3],
                "最低": [9.9, 10.0],
                "成交量": [12_345, 9],
                "成交额": [12345.0, 2345.0],
            }
        )
        out = normalize_intraday_df(raw_df)
        volumes = out["volume"].tolist()
        assert volumes == [123, 0], (
            f"Expected [123, 0] (intraday 手 // 100 = shares), got {volumes}"
        )
