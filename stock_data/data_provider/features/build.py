"""Orchestrator: assemble the trend / pivots / volume feature blocks.

``window_by_days`` slices a K-line df to the bars whose date falls within
the last ``days`` calendar days — this is the "周期范围" used for window
stats and Z-score anomaly detection. Indicators / swing detection use the
full (warm) frame.
"""

from __future__ import annotations

import pandas as pd

from .pivots import compute_pivots
from .trend import compute_trend
from .volume import compute_volume


def window_by_days(df: pd.DataFrame, days: int) -> pd.DataFrame:
    """Bars within the last ``days`` calendar days (inclusive of the last bar)."""
    if df is None or df.empty:
        return df
    last = pd.Timestamp(df["date"].iloc[-1])
    cutoff = last - pd.Timedelta(days=days)
    dates = pd.to_datetime(df["date"])
    return df[dates >= cutoff]


def build_features(df: pd.DataFrame, *, frequency: str, days: int) -> dict:
    """Return {"trend": ..., "pivots": ..., "volume": ...} for one code.

    ``frequency`` is unused by the pure computation itself but is kept in
    the signature so the route's fetch window (which differs per frequency)
    is decided at the call site.
    """
    if df is None or df.empty:
        return {"trend": {}, "pivots": {}, "volume": {}}
    window_df = window_by_days(df, days)
    return {
        "trend": compute_trend(df),
        "pivots": compute_pivots(df, window_df),
        "volume": compute_volume(df, window_df),
    }
