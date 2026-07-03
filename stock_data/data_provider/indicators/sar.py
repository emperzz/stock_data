"""
SAR — Parabolic SAR (J. Welles Wilder).

State machine:
    - We track the extreme point (EP), the acceleration factor (AF),
      and the current trend (1 = uptrend, -1 = downtrend).
    - On each bar:
        * If uptrend: SAR[i] = SAR[i-1] + AF * (EP - SAR[i-1]).
          If low[i] < SAR[i], flip to downtrend.
        * If downtrend: SAR[i] = SAR[i-1] + AF * (EP - SAR[i-1]).
          If high[i] > SAR[i], flip to uptrend.
        * If the new EP sets a new extreme, bump AF by afIncrement
          (capped at afMax). If no new extreme, AF stays put.

We emit the SAR value for bar i (the SAR for that bar), plus the trend
direction (1/-1), the EP and the AF — so callers can plot the dots and
the trend line.
"""

from __future__ import annotations

from typing import Any

from .types import OHLCV


def calcSAR(  # noqa: N802
    bars: list[OHLCV],
    options: dict[str, Any] | None = None,
) -> list[dict[str, float | None]]:
    options = options or {}
    af_start: float = float(options.get("afStart", 0.02))
    af_increment: float = float(options.get("afIncrement", 0.02))
    af_max: float = float(options.get("afMax", 0.20))

    if af_start <= 0 or af_increment <= 0 or af_max < af_start:
        raise ValueError("afStart > 0, afIncrement > 0, afMax > afStart required")

    if not bars:
        return []

    out: list[dict[str, float | None]] = []

    # Seed: assume uptrend if first two bars rise, else downtrend.
    # The very first bar's SAR is undefined; emit None.
    first = bars[0]
    h0 = first.get("high")
    l0 = first.get("low")
    if h0 is None or l0 is None:
        out.append({"sar": None, "sar_trend": None, "sar_ep": None, "sar_af": None})
        # If we have no high/low, all subsequent bars will be None too.
        for _ in bars[1:]:
            out.append({"sar": None, "sar_trend": None, "sar_ep": None, "sar_af": None})
        return out

    h1 = bars[1].get("high") if len(bars) > 1 else None
    l1 = bars[1].get("low") if len(bars) > 1 else None
    if h1 is None or l1 is None or len(bars) < 2:
        out.append({"sar": None, "sar_trend": None, "sar_ep": None, "sar_af": None})
        for _ in bars[1:]:
            out.append({"sar": None, "sar_trend": None, "sar_ep": None, "sar_af": None})
        return out

    # Trend initialization
    if h1 >= h0:
        trend = 1
        ep = max(h0, h1)
        sar_value = min(l0, l1)  # SAR starts below price in uptrend
    else:
        trend = -1
        ep = min(l0, l1)
        sar_value = max(h0, h1)  # SAR starts above price in downtrend

    af = af_start
    out.append({"sar": None, "sar_trend": None, "sar_ep": round(ep, 2), "sar_af": round(af, 4)})

    # Iterate from bar 1 onward (bar 0 was the seed)
    for i in range(1, len(bars)):
        bar = bars[i]
        h = bar.get("high")
        low = bar.get("low")
        if h is None or low is None:
            out.append({"sar": None, "sar_trend": trend, "sar_ep": round(ep, 2), "sar_af": round(af, 4)})
            continue

        # Next SAR
        next_sar = sar_value + af * (ep - sar_value)
        # Trend check BEFORE assigning new EP/AF (to use the old EP)
        flipped = False
        if trend == 1 and low < next_sar:
            # Flip to downtrend
            trend = -1
            next_sar = ep  # SAR resets to the prior EP
            ep = low
            af = af_start
            flipped = True
        elif trend == -1 and h > next_sar:
            trend = 1
            next_sar = ep
            ep = h
            af = af_start
            flipped = True

        if not flipped:
            # Update EP / AF based on whether a new extreme was set
            if trend == 1 and h > ep:
                ep = h
                af = min(af + af_increment, af_max)
            elif trend == -1 and low < ep:
                ep = low
                af = min(af + af_increment, af_max)
            # SAR must not penetrate the prior two bars' extremes
            if i >= 2:
                p1 = bars[i - 1]
                p2 = bars[i - 2]
                # Use explicit None check — `p1.get("low") or low` would
                # incorrectly fall through to `low` when p1's low is 0.0
                # (a valid extreme). See CLAUDE.md anti-pattern.
                p1_low = p1.get("low") if p1.get("low") is not None else low
                p2_low = p2.get("low") if p2.get("low") is not None else low
                p1_high = p1.get("high") if p1.get("high") is not None else h
                p2_high = p2.get("high") if p2.get("high") is not None else h
                if trend == 1:
                    floor_ = min(p1_low, p2_low)
                    next_sar = min(next_sar, floor_)
                else:
                    ceil_ = max(p1_high, p2_high)
                    next_sar = max(next_sar, ceil_)

        sar_value = next_sar
        out.append(
            {
                "sar": round(sar_value, 2),
                "sar_trend": trend,
                "sar_ep": round(ep, 2),
                "sar_af": round(af, 4),
            }
        )

    return out


__all__ = ["calcSAR"]
