"""Tests for the pure-compute helpers in stock_data.api.routes.agent_correlation."""
import numpy as np
import pandas as pd
import pytest

from stock_data.api.routes.agent_correlation import (
    _align_series,
    _compute_matrices,
    _finalize_matrix,
    _pct_change,
)


def _make_series(values, start="2026-01-01"):
    """Build a pd.Series with a daily DatetimeIndex (no time-of-day)."""
    idx = pd.date_range(start=start, periods=len(values), freq="D")
    return pd.Series(values, index=idx, dtype=float)


def test_align_inner_join_drops_non_common_dates():
    a = _make_series([100, 101, 102, 103, 104])
    b = _make_series([200, 201, 203, 204])  # missing 2026-01-03 (idx 2)
    df, common, missing = _align_series({"a": a, "b": b})
    assert common == 4
    assert missing == 1
    assert len(df) == 4


def test_align_strips_time_of_day():
    a = _make_series([100, 101, 102])
    # Force a time-of-day on the index
    a.index = a.index + pd.Timedelta(hours=9)
    b = _make_series([200, 201, 202])
    b.index = b.index + pd.Timedelta(hours=15)
    df, common, _ = _align_series({"a": a, "b": b})
    assert common == 3   # would be 0 if time-of-day weren't stripped


def test_align_empty_raises():
    with pytest.raises(ValueError):
        _align_series({})


def test_compute_pearson_diagonal_one():
    df = pd.DataFrame({"a": [1.0, 2, 3, 4], "b": [2.0, 4, 6, 8]})  # perfectly correlated
    out = _compute_matrices(df, ["pearson"])
    m = np.array(out["pearson"])
    assert m.shape == (2, 2)
    assert np.allclose(np.diag(m), 1.0)
    # Perfect linear relationship → rho ~ 1.0
    assert abs(m[0, 1] - 1.0) < 1e-4


def test_compute_spearman_is_robust_to_outliers():
    """Spearman (rank-based) is robust to a single large outlier; Pearson drops.

    This is the canonical Spearman-vs-Pearson asymmetry test. A linear
    monotonic but non-linear relationship (e.g. x²) does NOT separate them
    because rank order is preserved — Pearson and Spearman both ≈ 1.
    """
    # Build a perfectly linear pair, then add one extreme outlier to y
    x = np.arange(1, 11, dtype=float)
    y = x.copy().astype(float)
    y[-1] = 100.0  # outlier: 10 → 100

    df = pd.DataFrame({"a": x, "b": y})
    out = _compute_matrices(df, ["pearson", "spearman"])
    p = np.array(out["pearson"])[0, 1]
    s = np.array(out["spearman"])[0, 1]

    # Pearson drops due to the outlier; Spearman barely moves (rank preserved)
    assert s > p, (
        f"expected Spearman={s} > Pearson={p} under one-rank outlier; "
        "got the opposite"
    )
    # Magnitudes: Spearman ≈ 1, Pearson < 0.9
    assert s > 0.9
    assert p < 0.9


def test_compute_methods_subset_returns_none():
    df = pd.DataFrame({"a": [1.0, 2, 3], "b": [2.0, 4, 6]})
    out = _compute_matrices(df, ["pearson"])
    assert "pearson" in out
    assert out["spearman"] is None


def test_compute_nan_in_input_becomes_zero_in_matrix():
    # Constant column → zero variance → NaN correlation → must become 0
    df = pd.DataFrame({"a": [1.0, 2, 3, 4], "b": [5.0, 5, 5, 5]})
    out = _compute_matrices(df, ["pearson"])
    m = np.array(out["pearson"])
    assert m.shape == (2, 2)
    assert not np.any(np.isnan(m))
    # diagonal still 1
    assert np.allclose(np.diag(m), 1.0)


def test_finalize_matrix_symmetrize():
    # Build an asymmetric matrix and a NaN; verify it's symmetrized and NaN→0
    m = np.array([[1.0, 0.5], [0.7, 1.0]])
    out = np.array(_finalize_matrix(m, ["a", "b"]))
    # After symmetrize: [[1, 0.6], [0.6, 1]]
    assert abs(out[0, 1] - 0.6) < 1e-4
    assert abs(out[1, 0] - 0.6) < 1e-4


def test_pct_change_does_not_forward_fill():
    """NaN closes must propagate as NaN pct_change (NOT forward-fill to 0).

    Two assertions pin the same invariant from different angles:
      1) _pct_change on a 4-row series with NaN in position 2 → dropna
         yields a single surviving row whose value matches the legitimate
         101→100 jump.
      2) The raw `df.pct_change(fill_method=None)` keeps position 2 as NaN
         instead of fabricating 0.0 (the legacy pandas-2 default behavior).
    """
    # 4 closes; the 3rd is NaN. pct_change: [NaN, 0.0099, NaN, NaN].
    s = pd.Series(
        [100.0, 101.0, np.nan, 104.0],
        index=pd.date_range("2026-01-01", periods=4, freq="D"),
    )
    df = s.to_frame("a")

    out = _pct_change(df)
    assert len(out) == 1
    assert abs(out["a"].iloc[0] - 0.0099) < 1e-3

    # Direct check on the raw pct_change before dropna
    raw = df.pct_change(fill_method=None)
    assert np.isnan(raw["a"].iloc[2]), (
        "pct_change must NOT forward-fill NaN closes to 0; "
        "got a numeric value, which means fill_method=None was dropped."
    )
