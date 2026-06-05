"""
IndicatorService — the orchestrator that binds the registry to a K-line
DataFrame and produces a final frame with indicator columns.

Pure compute: it does NOT touch the network, the fetcher system, or
the cache. Callers are expected to:

    1. Fetch the K-line via DataFetcherManager.get_kline_data().
    2. Hand the resulting DataFrame to IndicatorService.compute().
    3. Truncate to the user's requested bar count if you over-fetched.

Why a class and not a flat function? We want a single place to:
    - merge default options with user options
    - look up lookback
    - coerce a DataFrame into the (closes, ohlcv) shapes the
      indicator functions need
    - merge each indicator's per-bar dict back onto the DataFrame
    - expose list_available() for the catalog endpoint
"""

from __future__ import annotations

import math
from typing import Any

import pandas as pd

from .registry import INDICATOR_REGISTRY, estimate_lookback, list_indicators
from .types import IndicatorKey, OHLCV


class IndicatorService:
    """Stateless orchestrator. One instance is fine to share across requests."""

    def compute(
        self,
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
        if spec is None:
            return self._attach_indicators_dict(df, [])

        # Normalize spec: list[str] -> dict[str, default_options]
        if isinstance(spec, list):
            spec_dict: dict[str, dict[str, Any]] = {}
            for key in spec:
                try:
                    indicator_key = IndicatorKey(key)
                except ValueError:
                    raise ValueError(
                        f"unknown indicator: {key!r}. "
                        f"Supported: {sorted(k.value for k in IndicatorKey)}"
                    ) from None
                descriptor = INDICATOR_REGISTRY.get(indicator_key)
                if descriptor is None:
                    raise ValueError(f"unknown indicator: {key!r}")
                spec_dict[key] = dict(descriptor.default_options)
        else:
            spec_dict = {}
            for key, options in spec.items():
                try:
                    indicator_key = IndicatorKey(key)
                except ValueError:
                    raise ValueError(
                        f"unknown indicator: {key!r}. "
                        f"Supported: {sorted(k.value for k in IndicatorKey)}"
                    ) from None
                descriptor = INDICATOR_REGISTRY.get(indicator_key)
                if descriptor is None:
                    raise ValueError(f"unknown indicator: {key!r}")
                # Merge user options onto defaults so partially specified
                # options still work.
                merged = dict(descriptor.default_options)
                if options:
                    merged.update(options)
                spec_dict[key] = merged

        if not spec_dict:
            return self._attach_indicators_dict(df, [])

        closes = self._extract_closes(df)
        ohlcv = self._extract_ohlcv(df)

        per_bar_results: list[dict[str, float | None]] = [{} for _ in range(len(df))]
        for key_str, options in spec_dict.items():
            descriptor = INDICATOR_REGISTRY[IndicatorKey(key_str)]
            rows = descriptor.run(closes, ohlcv, options)
            # `rows` is a list of dicts aligned to df; merge onto the
            # accumulator.
            for i, row in enumerate(rows):
                per_bar_results[i].update(row)

        return self._attach_indicators_dict(df, per_bar_results)

    def estimate_lookback(self, spec: dict[str, dict[str, Any]] | list[str] | None) -> int:
        """How many bars of K-line are required to fully warm up `spec`?

        For empty spec / None / unknown indicators, returns 0.
        """
        if not spec:
            return 0
        if isinstance(spec, list):
            normalized: dict[str, dict[str, Any]] = {}
            for key in spec:
                descriptor = INDICATOR_REGISTRY.get(IndicatorKey(key))
                if descriptor is None:
                    continue
                normalized[key] = dict(descriptor.default_options)
            return estimate_lookback(normalized)
        return estimate_lookback(spec)

    def list_available(self) -> list[dict[str, Any]]:
        """Return the catalog of supported indicators (for /indicators/catalog)."""
        return list_indicators()

    # ---------- private helpers ----------

    @staticmethod
    def _extract_closes(df: pd.DataFrame) -> list[float | None]:
        series = df["close"] if "close" in df.columns else pd.Series([], dtype=float)
        return [None if pd.isna(v) else float(v) for v in series]

    @staticmethod
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

    @staticmethod
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
                if v is None:
                    clean_row[k] = None
                elif isinstance(v, float) and math.isnan(v):
                    clean_row[k] = None
                else:
                    clean_row[k] = v
            cleaned.append(clean_row)
        result["indicators"] = cleaned
        return result


__all__ = ["IndicatorService"]
