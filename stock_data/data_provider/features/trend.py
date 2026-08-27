"""Trend block for the agent batch-profile feature layer.

Thin wrappers over the existing indicator layer (`indicator_service.compute`).
Returns the *latest* MA values, the 1-bar MA slope vs the previous bar, and
the latest ADX / PDI / MDI (from DMI), RSI and BOLL values. Pure compute —
the caller is responsible for fetching enough history to warm MA60.
"""

from __future__ import annotations

import pandas as pd

from ..indicators import indicator_service

_MA_PERIODS = [5, 10, 15, 20, 30, 60]


def _last(out: pd.DataFrame, key: str):
    """Return the last non-None value for an indicator column, else None."""
    if "indicators" not in out.columns or out.empty:
        return None
    row = out["indicators"].iloc[-1]
    if not isinstance(row, dict):
        return None
    v = row.get(key)
    return None if v is None or pd.isna(v) else float(v)


def compute_trend(df: pd.DataFrame) -> dict:
    if df is None or df.empty:
        return {
            "ma": {},
            "ma_change": {},
            "adx": None,
            "pdi": None,
            "mdi": None,
            "rsi": {"rsi_6": None, "rsi_12": None, "rsi_24": None},
            "boll": {"mid": None, "upper": None, "lower": None, "bandwidth": None},
        }

    spec = {
        "ma": {"periods": _MA_PERIODS, "type": "sma"},
        "dmi": {},   # defaults: period 14, adxPeriod 14
        "rsi": {},   # defaults: periods [6, 12, 24]
        "boll": {},  # defaults: period 20, stdDev 2.0
    }
    out = indicator_service.compute(df, spec)
    rows = out["indicators"]

    def _at(offset: int) -> dict:
        if len(rows) == 0:
            return {}
        if offset < 0:
            idx = len(rows) + offset
            if idx < 0:
                # e.g. _at(-2) on a 1-row frame — no previous bar to look at.
                return {}
        else:
            idx = min(offset, len(rows) - 1)
        row = rows.iloc[idx]
        return row if isinstance(row, dict) else {}

    last_row = _at(-1)
    prev_row = _at(-2)

    ma: dict[str, float | None] = {}
    ma_change: dict[str, float | None] = {}
    for p in _MA_PERIODS:
        key = f"ma{p}"
        cur, prev = last_row.get(key), prev_row.get(key)
        ma[key] = None if cur is None or pd.isna(cur) else float(cur)
        if cur is not None and not pd.isna(cur) and prev is not None and not pd.isna(prev) and prev != 0:
            ma_change[key] = (float(cur) - float(prev)) / float(prev) * 100
        else:
            ma_change[key] = None

    return {
        "ma": ma,
        "ma_change": ma_change,
        "adx": _last(out, "dmi_adx"),
        "pdi": _last(out, "dmi_pdi"),
        "mdi": _last(out, "dmi_mdi"),
        "rsi": {f"rsi_{p}": _last(out, f"rsi_{p}") for p in (6, 12, 24)},
        "boll": {
            "mid": _last(out, "boll_mid"),
            "upper": _last(out, "boll_upper"),
            "lower": _last(out, "boll_lower"),
            "bandwidth": _last(out, "boll_bandwidth"),
        },
    }
