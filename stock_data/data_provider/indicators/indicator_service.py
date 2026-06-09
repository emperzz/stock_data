"""
IndicatorService — orchestrator that binds the registry to a K-line
DataFrame and produces a final frame with indicator columns.

Pure compute: it does NOT touch the network, the fetcher system, or
the cache. Callers are expected to:

    1. Fetch the K-line via DataFetcherManager.get_kline_data().
    2. Hand the resulting DataFrame to IndicatorService.compute().
    3. Truncate to the user's requested bar count if you over-fetched.

Why a class and not a flat function? `routes.py` instantiates it as a
stateless object (`.compute()`, `.estimate_lookback()`, `.list_available()`);
keeping the class shape preserves the public contract while internal
state stays empty.
"""

from __future__ import annotations

import math
from typing import Any

import pandas as pd

from .registry import INDICATOR_REGISTRY, estimate_lookback, list_indicators
from .types import OHLCV, IndicatorKey


def _coerce_indicator_key(raw: Any) -> IndicatorKey:
    """Resolve a key from str or IndicatorKey, raising ValueError on miss."""
    if isinstance(raw, IndicatorKey):
        return raw
    try:
        return IndicatorKey(raw)
    except ValueError:
        raise ValueError(
            f"unknown indicator: {raw!r}. "
            f"Supported: {sorted(k.value for k in IndicatorKey)}"
        ) from None


def _normalize_spec(
    spec: dict[str, dict[str, Any]] | list[str] | None,
) -> dict[str, dict[str, Any]]:
    """Expand list[str] into a full spec dict, merging user options onto defaults."""
    if spec is None:
        return {}
    if isinstance(spec, list):
        out: dict[str, dict[str, Any]] = {}
        for key in spec:
            descriptor = INDICATOR_REGISTRY.get(_coerce_indicator_key(key))
            if descriptor is None:
                raise ValueError(f"unknown indicator: {key!r}")
            out[key] = dict(descriptor.default_options)
        return out
    out = {}
    for key, options in spec.items():
        descriptor = INDICATOR_REGISTRY.get(_coerce_indicator_key(key))
        if descriptor is None:
            raise ValueError(f"unknown indicator: {key!r}")
        merged = dict(descriptor.default_options)
        if options:
            merged.update(options)
        out[key] = merged
    return out


def _extract_closes(df: pd.DataFrame) -> list[float | None]:
    series = df["close"] if "close" in df.columns else pd.Series([], dtype=float)
    return [None if pd.isna(v) else float(v) for v in series]


def _extract_ohlcv(df: pd.DataFrame) -> list[OHLCV]:
    if df.empty:
        return []
    cols = {c: df[c] if c in df.columns else pd.Series([None] * len(df)) for c in ("open", "high", "low", "close", "volume")}
    out: list[OHLCV] = []
    for i in range(len(df)):
        row: OHLCV = {}
        for col_name, series in cols.items():
            v = series.iloc[i]
            row[col_name] = None if pd.isna(v) else float(v)  # type: ignore[literal-required]
        out.append(row)
    return out


def _attach_indicators_dict(
    df: pd.DataFrame,
    per_bar: list[dict[str, float | None]],
) -> pd.DataFrame:
    """Add an `indicators` column to a copy of df.

    For an empty `per_bar` we still attach an empty-dict column so
    downstream serializers (Pydantic) can rely on the shape.
    """
    result = df.copy()
    if not per_bar:
        result["indicators"] = [{} for _ in range(len(df))]
        return result

    # Coerce NaN to None so JSON output is `null` not `NaN`.
    cleaned: list[dict[str, float | None]] = []
    for row in per_bar:
        clean_row: dict[str, float | None] = {}
        for k, v in row.items():
            if v is None or isinstance(v, float) and math.isnan(v):
                clean_row[k] = None
            else:
                clean_row[k] = v
        cleaned.append(clean_row)
    result["indicators"] = cleaned
    return result


def compute(
    df: pd.DataFrame,
    spec: dict[str, dict[str, Any]] | list[str] | None,
) -> pd.DataFrame:
    """Compute the requested indicators and merge them onto `df`.

    Args:
        df: K-line DataFrame (must have `date`, `open`, `high`,
            `low`, `close`, `volume`).
        spec: Either a mapping of `indicator_name -> options` (full
              control), or a list of indicator names (uses defaults),
              or None (no-op, returns df unchanged).

    Returns:
        A *new* DataFrame with the original columns plus a flat
        `indicators` dict per row. We do NOT inject each column as
        its own top-level DataFrame column — that would pollute the
        schema. Instead we put them in a single `indicators` dict
        so the API layer can render them as JSON keys.
    """
    spec_dict = _normalize_spec(spec)
    if not spec_dict:
        return _attach_indicators_dict(df, [])

    closes = _extract_closes(df)
    ohlcv = _extract_ohlcv(df)

    per_bar_results: list[dict[str, float | None]] = [{} for _ in range(len(df))]
    for key_str, options in spec_dict.items():
        spec_obj = INDICATOR_REGISTRY[IndicatorKey(key_str)]
        if spec_obj.input_shape == "closes":
            rows = spec_obj.compute(closes, options)
        else:
            rows = spec_obj.compute(ohlcv, options)
        for i, row in enumerate(rows):
            per_bar_results[i].update(row)

    return _attach_indicators_dict(df, per_bar_results)


def compute_lookback(spec: dict[str, dict[str, Any]] | list[str] | None) -> int:
    """How many bars of K-line are required to fully warm up `spec`?

    For empty spec / None / unknown indicators, returns 0.
    """
    if not spec:
        return 0
    if isinstance(spec, list):
        return estimate_lookback(_normalize_spec(spec))
    return estimate_lookback(spec)


def available_catalog() -> list[dict[str, Any]]:
    """Return the catalog of supported indicators (for /indicators/catalog)."""
    return list_indicators()


class IndicatorService:
    """Stateless orchestrator. One instance is fine to share across requests.

    Thin facade over the module-level functions for callers that prefer
    OO style (`IndicatorService().compute(df, spec)`).
    """

    def compute(
        self,
        df: pd.DataFrame,
        spec: dict[str, dict[str, Any]] | list[str] | None,
    ) -> pd.DataFrame:
        return compute(df, spec)

    def estimate_lookback(self, spec: dict[str, dict[str, Any]] | list[str] | None) -> int:
        return compute_lookback(spec)

    def list_available(self) -> list[dict[str, Any]]:
        return available_catalog()


__all__ = [
    "IndicatorService",
    "compute",
    "compute_lookback",
    "available_catalog",
]
