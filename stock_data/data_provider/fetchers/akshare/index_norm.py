"""
Index and intraday DataFrame normalisation helpers for AkshareFetcher.

Internal implementation detail — merges the previously duplicated
``_normalize_index_daily*`` methods and the three intraday-normalisation
copies (``_normalize_intraday_minute``, ``_normalize_intraday``, and the
inline block in ``get_index_intraday``) into a single parameterised
function each.
"""

from __future__ import annotations

import pandas as pd

# ---------------------------------------------------------------------------
# Daily K-line: per-source column maps for the three index-history endpoints
# ---------------------------------------------------------------------------
# These were previously class attributes on AkshareFetcher but are pure
# data — no `self` access — so they belong here as module-level constants.

_INDEX_SINA_MAP: dict[str, str] = {
    "date": "date", "open": "open", "high": "high",
    "low": "low", "close": "close", "volume": "volume",
}
_INDEX_SINA_NUMERIC: tuple[str, ...] = ("open", "high", "low", "close", "volume")

_INDEX_TX_MAP: dict[str, str] = {
    "date": "date", "open": "open", "close": "close",
    "high": "high", "low": "low", "amount": "volume",
}
_INDEX_TX_NUMERIC: tuple[str, ...] = ("open", "high", "low", "close", "volume")

_INDEX_EM_MAP: dict[str, str] = {
    "date": "date", "open": "open", "close": "close",
    "high": "high", "low": "low", "volume": "volume", "amount": "amount",
}
_INDEX_EM_NUMERIC: tuple[str, ...] = ("open", "high", "low", "close", "volume", "amount")


# ---------------------------------------------------------------------------
# Daily K-line normalisation (replaces 3 duplicate _normalize_index_daily*)
# ---------------------------------------------------------------------------

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

    Volume unit conversion (P2-2 + P3-a5 of ``docs/optimization-plan-2026-07-16.md``):
    the canonical contract is **股 (shares)** per ``KLineData.volume_unit``
    schema invariant. All three index daily endpoints upstream report
    volume in **手 (lots = 100 shares)**:
    - Sina / EM: raw column literally named ``volume`` → maps to ``volume``
    - Tencent: raw column literally named ``amount`` (per akshare docs
      "注意单位: 手") → mapped to ``volume`` via ``_INDEX_TX_MAP``

    The ``*100`` conversion therefore runs for ANY mapping that produces a
    ``volume`` column. Pre-P3-a5 the detection rule wrongly excluded the
    ``amount → volume`` rename, leaving Tencent volume 100× smaller than
    Sina/EM and breaking the failover invariant. The fix was verified by
    live probe (``scripts/probe_tencent_index_amount.py``, 2026-07-17):
    HS300 daily Tencent value ~2.8e8 matches Sina/EM magnitude, and the
    akshare docstring explicitly annotates ``amount`` as 手.

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
    # 手 -> 股 (lots -> shares) per spec §3.4. All three index daily
    # endpoints (Sina / Tencent / EM) report volume in 手. Tencent's
    # column is literally named ``amount`` upstream (per akshare docs:
    # "注意单位: 手"), so the mapping renames ``amount`` → ``volume``
    # — but the underlying unit is still 手. The original code skipped
    # the *100 conversion for the amount→volume mapping under the
    # (wrong) assumption that Tencent might be reporting yuan; live
    # probe (scripts/probe_tencent_index_amount.py, 2026-07-17) plus
    # the akshare docstring "注意单位: 手" confirm the unit IS 手 and
    # the conversion must run for all three sources.
    volume_source_is_lots = (
        "volume" in df.columns
        and any(v == "volume" for k, v in column_mapping.items())
    )
    if volume_source_is_lots:
        df["volume"] = df["volume"].apply(
            lambda v: int(v) * 100 if pd.notna(v) else 0
        )
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


# ---------------------------------------------------------------------------
# Intraday / minute K-line: single helper replacing 3 duplicates
# ---------------------------------------------------------------------------
# The three previously separate intraday-normalisation call sites all did
# the same thing: rename Chinese columns to English, extract HH:MM:SS from
# the time column, coerce numeric types, and select the standard column
# layout.  ``normalize_intraday_df`` is the single source of truth.

_INTRADAY_COLUMN_MAPPING: dict[str, str] = {
    "时间": "time",
    "开盘": "open",
    "收盘": "close",
    "最高": "high",
    "最低": "low",
    "成交量": "volume",
    "成交额": "amount",
}
_INTRADAY_NUMERIC_COLS: tuple[str, ...] = ("open", "high", "low", "close", "volume", "amount")
_INTRADAY_STANDARD_COLS: tuple[str, ...] = ("time", "open", "high", "low", "close", "volume", "amount")


def normalize_intraday_df(df: pd.DataFrame, time_col: str = "时间") -> pd.DataFrame:
    """Normalize an akshare intraday DataFrame to the standard column layout.

    Replaces the three previously duplicated helpers
    (``_normalize_intraday_minute``, ``_normalize_intraday``, and the
    inline block in ``get_index_intraday``).  Behaviour:

    1. Renames Chinese columns (or any ``time_col``) to English.
    2. Strips the time column to ``HH:MM:SS`` (the 8 rightmost chars) when
       present — akshare's EM and Sina endpoints return full timestamps.
    3. Coerces the OHLCV/amount columns via ``pd.to_numeric``.
    4. **Akshare volume is 手 (lots = 100 shares); converts to 股 (shares)**
       by ``int(v) * 100`` per spec §3.4.
    5. Returns only the standard columns that exist after rename, in
       the canonical order.

    Args:
        df: Raw DataFrame from an akshare minute/intraday API.
        time_col: Source column name holding the timestamp.  Defaults to
            ``"时间"`` (akshare's standard).  Pass ``"day"`` for the
            Sina-fallback format used by ``stock_zh_a_minute``.

    Returns:
        DataFrame with the standard intraday columns (subset of
        ``time/open/high/low/close/volume/amount``) in canonical order.
    """
    column_mapping = {time_col: "time", **_INTRADAY_COLUMN_MAPPING}
    out = df.rename(columns={k: v for k, v in column_mapping.items() if k in df.columns})
    if "time" in out.columns:
        out["time"] = out["time"].astype(str).str[-8:]
    for col in _INTRADAY_NUMERIC_COLS:
        if col in out.columns:
            out[col] = pd.to_numeric(out[col], errors="coerce")
    # 手 -> 股 (lots -> shares) per spec §3.4.
    # 1 手 = 100 股, so multiply by 100. NaN/None → 0.
    if "volume" in out.columns:
        out["volume"] = out["volume"].apply(
            lambda v: int(v) * 100 if pd.notna(v) else 0
        )
    # Ensure all standard columns are present (None for missing) and
    # in canonical order.
    for col in _INTRADAY_STANDARD_COLS:
        if col not in out.columns:
            out[col] = None
    return out[list(_INTRADAY_STANDARD_COLS)]
