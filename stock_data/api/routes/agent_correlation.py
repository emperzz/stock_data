"""POST /api/v1/agent/correlation/matrix — server-side correlation aggregator."""
from __future__ import annotations

from collections.abc import Iterable

import numpy as np
import pandas as pd
from fastapi import APIRouter  # noqa: F401  (Task 6 will use it for the route decorator)

from ._router import (
    router,  # noqa: F401  (Task 6 will register @router.post("/correlation/matrix"))
)

# ----- pure-compute helpers (private) -----

def _align_series(
    series_by_label: dict[str, pd.Series],
    trailing_window: int | None = None,
) -> tuple[pd.DataFrame, int, int]:
    """Inner-join on date index, return aligned close DataFrame + stats.

    Each input series's index is normalized (drop time-of-day). Sorted ascending.
    Inner-join retains only dates present in EVERY series. When
    `trailing_window` is given, the joined result is trimmed to the LAST
    `trailing_window` rows (matches Vibe-Trading
    `correlation._rolling_correlation_matrix` at lines 168–169).

    Returns
    -------
    aligned : pd.DataFrame
        Columns = labels (the dict keys); index = sorted DatetimeIndex of dates
        common to every series. Values are raw `close` prices (not returns).
    common_bars : int
        Number of rows in `aligned` (post-trim, when `trailing_window` set).
    missing_after_join : int
        How many dates were dropped from the longest source minus common_bars
        (rough heuristic — counts full-length delta only).
    """
    if not series_by_label:
        raise ValueError("series_by_label is empty")

    normalized: dict[str, pd.Series] = {}
    for label, s in series_by_label.items():
        if not isinstance(s.index, pd.DatetimeIndex):
            s = s.copy()
            s.index = pd.to_datetime(s.index)
        s = s.copy()
        s.index = s.index.normalize()   # strip time-of-day (Vibe-Trading correlation.py:146)
        s = s.sort_index()
        normalized[label] = s

    # Inner-join: concat on columns, drop rows with any NaN (= not present in some series)
    df = pd.concat(normalized, axis=1)
    df = df.dropna(how="any")

    # Trim trailing window (spec §3.1 "trim to trailing `days` bars")
    if trailing_window is not None and len(df) > trailing_window:
        df = df.iloc[-trailing_window:].copy()

    common_bars = len(df)
    max_len = max(len(s) for s in normalized.values())
    missing = max_len - common_bars
    return df, common_bars, missing


def _compute_matrices(
    returns: pd.DataFrame,
    methods: Iterable[str],
) -> dict[str, list[list[float]] | None]:
    """For each method, return NxN correlation matrix (4-dp, NaN→0, symmetric).

    Always emits both ``"pearson"`` and ``"spearman"`` keys; absent methods
    get ``None`` so callers can rely on key existence for shape checks.
    """
    out: dict[str, list[list[float]] | None] = {"pearson": None, "spearman": None}

    cols = list(returns.columns)
    method_set = set(methods)

    if "pearson" in method_set:
        # np.corrcoef returns NaN if a column has zero variance (constant series)
        with np.errstate(invalid="ignore"):
            m = np.corrcoef(returns.values, rowvar=False)
        out["pearson"] = _finalize_matrix(m, cols)

    if "spearman" in method_set:
        # Compute rank-transform once, then np.corrcoef on ranks (pairwise).
        ranks = returns.rank(method="average")
        with np.errstate(invalid="ignore"):
            m = np.corrcoef(ranks.values, rowvar=False)
        out["spearman"] = _finalize_matrix(m, cols)

    return out


def _finalize_matrix(
    m: np.ndarray,
    cols: list[str],
) -> list[list[float]]:
    """Symmetrize (numerical), NaN→0, force diagonal=1, round to 4 dp, return list-of-lists."""
    m = np.asarray(m, dtype=float)
    # Symmetrize: average with transpose (defensive — both np.corrcoef and scipy already symmetric)
    m = (m + m.T) / 2.0
    # Diagonal = 1 (defensive — zero-variance rows can give NaN diagonal)
    np.fill_diagonal(m, 1.0)
    # NaN → 0
    m = np.where(np.isnan(m), 0.0, m)
    # Round to 4 dp
    m = np.round(m, 4)
    return m.tolist()


def _pct_change(close_df: pd.DataFrame) -> pd.DataFrame:
    """Per-column `pct_change(fill_method=None)`.

    fill_method=None is load-bearing under pandas>=2,<3 (default was bfill).
    Move the call here so test #3 below pins it.
    """
    return close_df.pct_change(fill_method=None).dropna(how="any")
