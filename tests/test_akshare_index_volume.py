"""P2-2: akshare index daily K-line volume must be converted 手→股.

Background (``docs/optimization-plan-2026-07-16.md`` §P2-2):
* Stock K-line already multiplies volume by 100 (lots → shares) per
  spec §3.4 — verified by ``tests/test_volume_unit_unification.py``.
* Index daily K-line silently stayed in 手 until this change, so an
  akshare(P3)→zhitu(P5) failover would jump the volume by 100× with
  no signal to the client (no volume_unit field on index responses).
* Tencent's ``_INDEX_TX_MAP`` maps upstream ``amount`` (not ``volume``)
  into the standard ``volume`` column; that mapping is the M8 audit
  flag and must NOT be multiplied by 100 here.

These tests pin both branches of the new logic so a future refactor
that reverts Sina/EM (real volume) or accidentally multiplies Tencent
(amount-as-volume) gets caught immediately.
"""
from __future__ import annotations

import pandas as pd
import pytest

from stock_data.data_provider.fetchers.akshare.index_norm import (
    _INDEX_EM_MAP,
    _INDEX_SINA_MAP,
    _INDEX_TX_MAP,
    normalize_index_df,
)


def _raw_df_with_volume(volume_col: str = "volume", value: int = 1234) -> pd.DataFrame:
    """Build a synthetic akshare index-daily payload with one row.

    The upstream schema (Sina/EM) names the volume column ``volume``;
    Tencent renames ``amount`` → ``volume`` in the local map.
    """
    return pd.DataFrame(
        {
            "date": ["2026-06-29"],
            "open": [3500.0],
            "close": [3510.0],
            "high": [3520.0],
            "low": [3490.0],
            volume_col: [value],
            "amount": [123_456_789.0],
        }
    )


class TestSinaIndexVolumeMultiplied:
    """Sina's ``_INDEX_SINA_MAP`` brings ``volume`` from upstream ``volume`` → *100."""

    def test_sina_volume_is_multiplied_by_100(self):
        raw = _raw_df_with_volume(volume_col="volume", value=1234)
        out = normalize_index_df(raw, "000300", _INDEX_SINA_MAP)
        assert out["volume"].iloc[0] == 123_400, (
            f"expected 1234 手 × 100 = 123400 股, got {out['volume'].iloc[0]!r}"
        )


class TestEastMoneyIndexVolumeMultiplied:
    """EM's ``_INDEX_EM_MAP`` brings ``volume`` from upstream ``volume`` → *100."""

    def test_em_volume_is_multiplied_by_100(self):
        raw = _raw_df_with_volume(volume_col="volume", value=25_000)
        out = normalize_index_df(raw, "000300", _INDEX_EM_MAP)
        assert out["volume"].iloc[0] == 2_500_000


class TestTencentIndexVolumeSkipped:
    """Tencent's ``_INDEX_TX_MAP`` maps upstream ``amount`` to ``volume`` (M8).

    Multiplying by 100 would compound the unit confusion flagged in the
    M8 audit. The normalize path must leave the value as-is until M8 is
    resolved (live probe + decide whether to drop the column or rename
    it to ``amount``).
    """

    def test_tx_volume_is_not_multiplied(self):
        # Build a fixture that mimics Tencent's actual column layout:
        # there is no upstream ``volume`` column, only ``amount``.
        raw = pd.DataFrame(
            {
                "date": ["2026-06-29"],
                "open": [3500.0],
                "close": [3510.0],
                "high": [3520.0],
                "low": [3490.0],
                "amount": [9_999_999.0],  # value that should NOT be touched
            }
        )
        out = normalize_index_df(raw, "000300", _INDEX_TX_MAP)
        assert "volume" in out.columns
        # Tencent maps amount→volume; the *100 logic must detect the
        # mapping brought volume from ``amount`` (not ``volume``) and
        # skip multiplication. If a future change accidentally applies
        # *100 here, the volume becomes 999_999_900 and this fails.
        assert int(out["volume"].iloc[0]) == 9_999_999


class TestVolumeEdgeCases:
    """NaN / missing volume must not blow up the normalize path."""

    def test_nan_volume_becomes_zero(self):
        raw = pd.DataFrame(
            {
                "date": ["2026-06-29"],
                "open": [3500.0],
                "close": [3510.0],
                "high": [3520.0],
                "low": [3490.0],
                "volume": [float("nan")],
                "amount": [0.0],
            }
        )
        out = normalize_index_df(raw, "000300", _INDEX_SINA_MAP)
        # per the existing _normalize_data pattern, NaN volume → 0
        # (skipping *100 rather than multiplying nan).
        assert int(out["volume"].iloc[0]) == 0

    def test_missing_volume_column_is_silent(self):
        """No ``volume`` upstream (e.g. minute fixture without amount) → no error."""
        raw = pd.DataFrame(
            {
                "date": ["2026-06-29"],
                "open": [3500.0],
                "close": [3510.0],
                "high": [3520.0],
                "low": [3490.0],
            }
        )
        out = normalize_index_df(raw, "000300", _INDEX_SINA_MAP)
        assert "volume" not in out.columns


class TestVolumeCrossSourceConsistency:
    """Sina and EM (both real volume) should now agree on the same canonical unit.

    This is the regression the user reported: same index from Sina vs EM
    gave 100× disagreement. After P2-2, the ratio should be 1:1 (within
    actual trading-volume noise — the test pins the deterministic case
    where the raw values are identical).
    """

    def test_sina_and_em_produce_same_unit_for_same_raw(self):
        sina_raw = _raw_df_with_volume(volume_col="volume", value=10_000)
        em_raw = _raw_df_with_volume(volume_col="volume", value=10_000)
        sina_out = normalize_index_df(sina_raw, "000300", _INDEX_SINA_MAP)
        em_out = normalize_index_df(em_raw, "000300", _INDEX_EM_MAP)
        assert int(sina_out["volume"].iloc[0]) == int(em_out["volume"].iloc[0])