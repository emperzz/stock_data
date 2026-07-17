"""P2-2 + P3-a5: akshare index daily K-line volume must be converted 手→股.

Background (``docs/optimization-plan-2026-07-16.md`` §P2-2 / §P3-a5):
* Stock K-line already multiplies volume by 100 (lots → shares) per
  spec §3.4 — verified by ``tests/test_volume_unit_unification.py``.
* Index daily K-line silently stayed in 手 until this change, so an
  akshare(P3)→zhitu(P5) failover would jump the volume by 100× with
  no signal to the client (no volume_unit field on index responses).
* Tencent's ``_INDEX_TX_MAP`` renames upstream ``amount`` → ``volume``.
  Per akshare docs (``docs/akshare/index/stock_zh_index_daily_tx.md``:
  "amount ... 注意单位: 手"), Tencent's ``amount`` column is in 手 — same
  unit as Sina/EM's ``volume``. The 2026-07-17 live probe
  (``scripts/probe_tencent_index_amount.py``) confirmed via magnitude
  reasoning (5.97e10 股 for 上证指数 daily volume, vs ~5.97e8 元 which
  would be ~1000× too small for actual turnover).
  ⇒ Tencent path ALSO needs *100. The previous "skip *100 for amount"
  assumption was the M8 audit's "wrong-direction hypothesis" — resolved
  by the live probe.
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


class TestTencentIndexVolumeMultiplied:
    """P3-a5 (M8) fix: Tencent's ``amount`` column is in 手 too.

    Resolved by live-network probe 2026-07-17:
    ``scripts/probe_tencent_index_amount.py`` confirmed magnitude (HS300
    daily ~2.8e8, matches Sina/EM volume-in-手), and akshare docs
    ``stock_zh_index_daily_tx.md`` explicitly annotate the ``amount``
    column with "注意单位: 手". The previous "skip *100" assumption was
    the M8 audit's hypothesis — wrong direction. Tencent path now
    behaves identically to Sina/EM: *100 conversion runs.

    This test replaces the prior ``TestTencentIndexVolumeSkipped`` (which
    codified the inverted assumption that every probed live row violated —
    the magnitude heuristic in ``scripts/probe_tencent_index_amount.py``
    matches EM volume-in-手 for HS300 daily, plus akshare docs explicitly
    annotate ``amount`` as 手).
    """

    def test_tx_amount_volume_is_multiplied_by_100(self):
        raw = pd.DataFrame(
            {
                "date": ["2026-06-29"],
                "open": [3500.0],
                "close": [3510.0],
                "high": [3520.0],
                "low": [3490.0],
                "amount": [9_999_999.0],
            }
        )
        out = normalize_index_df(raw, "000300", _INDEX_TX_MAP)
        assert "volume" in out.columns
        # 9_999_999 手 × 100 = 999_999_900 股 — same canonical unit as Sina/EM.
        assert int(out["volume"].iloc[0]) == 999_999_900, (
            f"Tencent amount→volume must apply *100 (per akshare doc "
            f"'注意单位: 手' + live probe); got {out['volume'].iloc[0]!r}"
        )


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