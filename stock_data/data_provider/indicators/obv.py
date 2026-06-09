"""
OBV — On-Balance Volume.

    OBV[i] = OBV[i-1] + (volume[i] if close[i] > close[i-1]
                         else -volume[i] if close[i] < close[i-1]
                         else 0)

Optionally smooth with an SMA: `obv_ma{N}`.
"""

from __future__ import annotations
from typing import Any

from .ma import calcSMA
from .types import OHLCV


def calcOBV(
    bars: list[OHLCV],
    options: dict[str, Any] | None = None,
) -> list[dict[str, float | None]]:
    options = options or {}
    ma_period: int = int(options.get("maPeriod", 0))
    if ma_period < 0:
        raise ValueError(f"maPeriod must be >= 0, got {ma_period}")

    obvs: list[float | None] = []
    prev_close: float | None = None
    obv = 0.0
    for bar in bars:
        c = bar.get("close")
        v = bar.get("volume")
        if c is None or v is None:
            obvs.append(obv if prev_close is not None else None)
        elif prev_close is None:
            # First bar: OBV is conventionally 0
            obvs.append(0.0)
        else:
            if c > prev_close:
                obv += v
            elif c < prev_close:
                obv -= v
            # else flat: no change
            obvs.append(obv)
        prev_close = c

    ma_obv: list[float | None] | None = None
    if ma_period > 0:
        # calcSMA works on float|None, so we need a list of float for it.
        # We pad the leading None with the obv values shifted in.
        obv_for_sma: list[float | None] = [v if v is not None else 0.0 for v in obvs]
        # Actually, the leading None already carries obv=0 implicitly. Let's
        # pass them through and accept that the SMA may compute against 0s
        # for those bars — it will only publish values from the seed onward
        # anyway, so the leading 0s are harmless. Replace leading Nones with
        # 0 to be safe.
        ma_obv = calcSMA(obv_for_sma, ma_period)

    out: list[dict[str, float | None]] = []
    for i, value in enumerate(obvs):
        row: dict[str, float | None] = {"obv": value}
        if ma_obv is not None:
            ma_val = ma_obv[i]
            row["obv_ma"] = round(ma_val, 2) if ma_val is not None else None
        out.append(row)
    return out


__all__ = ["calcOBV"]
