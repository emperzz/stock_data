"""Top/bottom block for the agent batch-profile feature layer.

"Tops / bottoms you can see on a chart" = local extrema filtered by a
minimum reversal significance (ZigZag), NOT every bar's high/low (noise)
and NOT the window's single global max/min (loses intermediate structure).

Algorithm:
  1. Candidate extrema: bar `i` is a candidate swing-high iff
     `high[i] == max(high[i-k .. i+k])` (k = pivot_window). The last `k`
     bars cannot be candidates yet (right-side confirmation incomplete).
  2. ZigZag significance pass: walk candidates chronologically, alternating
     high / low; confirm an extreme as a pivot only when price has reversed
     >= atr_mult * ATR14 from it.
  3. Pending: the final tracked extreme is not confirmed (no reversal yet).
     It is surfaced separately so callers do not treat an in-flight
     top/bottom as confirmed.
"""

from __future__ import annotations

import pandas as pd

from ..indicators import atr as _atr

_DEFAULT_PIVOT_WINDOW = 2
_DEFAULT_ATR_MULT = 1.0
_DEFAULT_ATR_PERIOD = 14
_DEFAULT_MAX_SWINGS = 6


def _atr_value(df: pd.DataFrame, period: int) -> float | None:
    rows: list[dict] = []
    if not df.empty:
        ohlcv = []
        for _, r in df.iterrows():
            ohlcv.append(
                {
                    "open": r["open"],
                    "high": r["high"],
                    "low": r["low"],
                    "close": r["close"],
                    "volume": r["volume"],
                }
            )
        computed = _atr.calcATR(ohlcv, {"period": period})
        rows = [x if isinstance(x, dict) else {} for x in computed]
    if not rows:
        return None
    v = rows[-1].get("atr")
    if v is not None and not pd.isna(v) and v > 0:
        return float(v)
    # Fallback for short series: ATR-14 cannot seed (needs `period` non-None
    # TRs; the first bar's TR is always None). Use the mean True Range of the
    # available bars as the significance unit — same semantics, still valid
    # for a warm full frame (there the primary ATR value wins above).
    trs = [x.get("tr") for x in rows if isinstance(x, dict) and x.get("tr") is not None]
    if not trs:
        return None
    mean_tr = sum(trs) / len(trs)
    return None if mean_tr <= 0 else float(mean_tr)


def _detect_swings(df: pd.DataFrame, pivot_window: int, atr_mult: float, atr_value: float):
    highs = [float(h) for h in df["high"]]
    lows = [float(low) for low in df["low"]]
    dates = [str(d) for d in df["date"]]
    n = len(df)
    if n < pivot_window * 2 + 2 or atr_value is None:
        return [], None

    candidates: list[tuple[int, str]] = []
    for i in range(pivot_window, n - pivot_window):
        if highs[i] >= max(highs[i - pivot_window : i + pivot_window + 1]):
            candidates.append((i, "high"))
        if lows[i] <= min(lows[i - pivot_window : i + pivot_window + 1]):
            candidates.append((i, "low"))

    swings: list[dict] = []
    direction: str | None = None
    extreme_i, extreme_price = None, None

    for i, kind in candidates:
        price = highs[i] if kind == "high" else lows[i]
        if direction is None:
            direction = "up" if kind == "high" else "down"
            extreme_i, extreme_price = i, price
            continue
        if direction == "up":
            if kind == "high":
                if price >= extreme_price:
                    extreme_i, extreme_price = i, price
            elif price <= extreme_price - atr_mult * atr_value:
                swings.append({"date": dates[extreme_i], "type": "high", "price": extreme_price, "confirmed": True})
                direction, extreme_i, extreme_price = "down", i, price
        else:  # direction == "down"
            if kind == "low":
                if price <= extreme_price:
                    extreme_i, extreme_price = i, price
            elif price >= extreme_price + atr_mult * atr_value:
                swings.append({"date": dates[extreme_i], "type": "low", "price": extreme_price, "confirmed": True})
                direction, extreme_i, extreme_price = "up", i, price

    pending = None
    if extreme_i is not None:
        pending = {
            "side": "high" if direction == "up" else "low",
            "bars": n - 1 - extreme_i,
            "price": extreme_price,
            "date": dates[extreme_i],
        }
    return swings, pending


def _window_stats(window_df: pd.DataFrame) -> dict:
    if window_df is None or window_df.empty:
        return {"window_high": None, "window_low": None, "max_vol_bar": None}
    hi = window_df.loc[window_df["high"].idxmax()]
    lo = window_df.loc[window_df["low"].idxmin()]
    mv = window_df.loc[window_df["volume"].idxmax()]
    return {
        "window_high": {"price": float(hi["close"]), "date": str(hi["date"])},
        "window_low": {"price": float(lo["close"]), "date": str(lo["date"])},
        "max_vol_bar": {"price": float(mv["close"]), "volume": float(mv["volume"]), "date": str(mv["date"])},
    }


def compute_pivots(
    df: pd.DataFrame,
    window_df: pd.DataFrame,
    *,
    pivot_window: int = _DEFAULT_PIVOT_WINDOW,
    atr_mult: float = _DEFAULT_ATR_MULT,
    atr_period: int = _DEFAULT_ATR_PERIOD,
    max_swings: int = _DEFAULT_MAX_SWINGS,
) -> dict:
    if df is None or df.empty:
        return {
            "window_high": None,
            "window_low": None,
            "max_vol_bar": None,
            "swings": [],
            "pending": None,
            "params": {
                "pivot_window": pivot_window,
                "reversal_atr_mult": atr_mult,
                "atr_period": atr_period,
            },
        }
    atr_value = _atr_value(df, atr_period)
    swings, pending = _detect_swings(df, pivot_window, atr_mult, atr_value)
    return {
        **_window_stats(window_df),
        "swings": swings[-max_swings:],
        "pending": pending,
        "params": {
            "pivot_window": pivot_window,
            "reversal_atr_mult": atr_mult,
            "atr_period": atr_period,
        },
    }
