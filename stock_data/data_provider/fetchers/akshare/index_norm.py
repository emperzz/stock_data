"""
Index DataFrame normalisation helpers for AkshareFetcher.

Internal implementation detail — merges the three previously
duplicated ``_normalize_index_daily*`` methods into a single
parameterised function.
"""

from __future__ import annotations

import pandas as pd


def normalize_index_df(
    df: pd.DataFrame,
    code: str,
    column_mapping: dict[str, str],
    *,
    numeric_cols: tuple[str, ...] = ("open", "high", "low", "close", "volume", "amount"),
) -> pd.DataFrame:
    """Normalize an akshare index DataFrame to the standard column layout.

    This replaces the three previously duplicated methods
    ``_normalize_index_daily`` (Sina), ``_normalize_index_daily_tx``
    (Tencent), and ``_normalize_index_daily_em`` (EM).  All three shared
    the same core pattern — rename columns, coerce types, add code, keep
    standard columns — and differed only in their ``column_mapping`` and
    ``numeric_cols`` lists.

    Args:
        df: Raw DataFrame from an akshare index-history API.
        code: Canonical index code to set on every row.
        column_mapping: ``{raw_col: standard_col}`` rename map.
        numeric_cols: Columns to coerce via ``pd.to_numeric(..., errors="coerce")``.
            Default covers all standard OHLCV + amount columns.

    Returns:
        DataFrame with columns from ``["code", "date"] + numeric_cols``
        (only columns present after rename are kept).
    """
    df = df.rename(
        columns={k: v for k, v in column_mapping.items() if k in df.columns}
    )
    if "date" in df.columns:
        df["date"] = pd.to_datetime(df["date"], errors="coerce")
    for col in numeric_cols:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    if "code" not in df.columns:
        df["code"] = code
    keep_cols = ["code", "date"] + [c for c in numeric_cols if c in df.columns]
    df = df[[c for c in keep_cols if c in df.columns]]
    return df


def filter_by_date(
    df: pd.DataFrame,
    start_date: str | None,
    end_date: str | None,
) -> pd.DataFrame:
    """Filter a DataFrame to rows whose ``"date"`` column falls within
    ``[start_date, end_date]`` (inclusive).  Returns the original frame
    unchanged when both bounds are None or when ``"date"`` is not a column.
    """
    if "date" not in df.columns:
        return df
    if start_date:
        df = df[df["date"] >= pd.to_datetime(start_date, errors="coerce")]
    if end_date:
        df = df[df["date"] <= pd.to_datetime(end_date, errors="coerce")]
    return df
