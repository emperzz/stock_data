"""
DMI — Directional Movement Index (Wilder's smoothing).

    +DM = high - prev_high   (only if positive AND > prev_low - prev_low)
    -DM = prev_low - low     (only if positive AND > +DM above)

    TR  = max(high - low, |high - prev_close|, |low - prev_close|)

    +DI = 100 * WilderSmooth(+DM, period) / WilderSmooth(TR, period)
    -DI = 100 * WilderSmooth(-DM, period) / WilderSmooth(TR, period)
    DX  = 100 * |+DI - -DI| / (+DI + -DI)
    ADX = WilderSmooth(DX, adxPeriod)
    ADXR = (ADX[i] + ADX[i - adxPeriod]) / 2
"""

from __future__ import annotations
from typing import Any

from .types import OHLCV


def _wilder_smooth(values: list[float | None], period: int) -> list[float | None]:
    """Wilder smoothing: seed = SMA of first `period` non-None values.

    A None in the input short-circuits to None output until enough data
    accumulates again. For our use the inputs are dense (every bar
    produces a value), so this branch rarely fires.
    """
    out: list[float | None] = []
    seed_buf: list[float] = []
    smoothed: float | None = None
    for v in values:
        if v is None:
            out.append(None)
            continue
        if smoothed is None:
            seed_buf.append(v)
            if len(seed_buf) == period:
                smoothed = sum(seed_buf) / period
                out.append(smoothed)
            else:
                out.append(None)
        else:
            smoothed = (smoothed * (period - 1) + v) / period
            out.append(smoothed)
    return out


def calcDMI(
    bars: list[OHLCV],
    options: dict[str, Any] | None = None,
) -> list[dict[str, float | None]]:
    options = options or {}
    period: int = int(options.get("period", 14))
    adx_period: int = int(options.get("adxPeriod", period))
    if period <= 0 or adx_period <= 0:
        raise ValueError("period and adxPeriod must be > 0")

    plus_dm: list[float | None] = []
    minus_dm: list[float | None] = []
    trs: list[float | None] = []
    prev_high: float | None = None
    prev_low: float | None = None
    prev_close: float | None = None

    for bar in bars:
        h = bar.get("high")
        l = bar.get("low")
        c = bar.get("close")
        if h is None or l is None or c is None or prev_high is None or prev_low is None or prev_close is None:
            plus_dm.append(None)
            minus_dm.append(None)
            trs.append(None)
        else:
            up = h - prev_high
            down = prev_low - l
            if up > down and up > 0:
                plus_dm.append(up)
            else:
                plus_dm.append(0.0)
            if down > up and down > 0:
                minus_dm.append(down)
            else:
                minus_dm.append(0.0)
            tr = max(h - l, abs(h - prev_close), abs(l - prev_close))  # type: ignore[arg-type]
            trs.append(tr)
        prev_high, prev_low, prev_close = h, l, c

    smooth_plus = _wilder_smooth(plus_dm, period)
    smooth_minus = _wilder_smooth(minus_dm, period)
    smooth_tr = _wilder_smooth(trs, period)

    # +DI / -DI / DX
    dx: list[float | None] = []
    pdi: list[float | None] = []
    mdi: list[float | None] = []
    for i in range(len(bars)):
        sp = smooth_plus[i]
        sm = smooth_minus[i]
        st = smooth_tr[i]
        if sp is None or sm is None or st is None or st == 0:
            pdi.append(None)
            mdi.append(None)
            dx.append(None)
            continue
        p = 100.0 * sp / st
        m = 100.0 * sm / st
        pdi.append(round(p, 2))
        mdi.append(round(m, 2))
        if (p + m) == 0:
            dx.append(None)
        else:
            dx.append(100.0 * abs(p - m) / (p + m))

    adx = _wilder_smooth(dx, adx_period)
    # ADXR = (ADX[i] + ADX[i - adx_period]) / 2
    adxr: list[float | None] = []
    for i, a in enumerate(adx):
        if a is None or i - adx_period < 0 or adx[i - adx_period] is None:
            adxr.append(None)
        else:
            adxr.append(round((a + adx[i - adx_period]) / 2.0, 2))  # type: ignore[operator]

    out: list[dict[str, float | None]] = []
    for i in range(len(bars)):
        out.append(
            {
                "dmi_pdi": pdi[i],
                "dmi_mdi": mdi[i],
                "dmi_adx": round(adx[i], 2) if adx[i] is not None else None,
                "dmi_adxr": adxr[i],
            }
        )

    return out


__all__ = ["calcDMI"]
