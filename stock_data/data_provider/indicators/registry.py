"""
Indicator registry — metadata for introspection and orchestration.

Each entry in INDICATOR_REGISTRY describes one indicator:
    - default_options: the options the user gets if they don't pass any
    - estimate_lookback: how many bars of K-line are needed to compute
                        this indicator from scratch (used by the service
                        to ensure we fetch enough history)
    - output_columns:  the dict keys this indicator will produce
    - compute:         the actual calc function (closes-only or OHLCV)
    - input_shape:     'closes' (1-D list) or 'ohlcv' (list of OHLCV dicts)

The orchestrator (IndicatorService) walks the registry once per
`compute()` call. The lookback estimator lets callers fetch the right
amount of history without ever publishing a half-warmed indicator.
"""

from __future__ import annotations

from typing import Any, Callable, NamedTuple

from . import (
    atr as _atr,
    bias as _bias,
    boll as _boll,
    cci as _cci,
    dmi as _dmi,
    kc as _kc,
    kdj as _kdj,
    ma as _ma,
    macd as _macd,
    obv as _obv,
    rsi as _rsi,
    sar as _sar,
    wr as _wr,
    roc as _roc,
)
from .types import IndicatorKey, OHLCV

# Per-bar output shape: column -> value (or None when not yet defined).
IndicatorBar = dict[str, float | None]


class _IndicatorSpec(NamedTuple):
    """Internal descriptor for one indicator.

    `compute` accepts the appropriate input shape (closes list or OHLCV
    list) plus the merged options dict, and returns a list of per-bar
    dicts aligned to the input index.
    """

    key: IndicatorKey
    input_shape: str  # "closes" or "ohlcv"
    default_options: dict[str, Any]
    estimate_lookback: Callable[[dict[str, Any]], int]
    output_columns: Callable[[dict[str, Any]], list[str]]
    compute: Callable[..., list[IndicatorBar]]


# ---------- the registry itself ----------
#
# Lookback & column helpers are inline lambdas. EMA-based indicators
# over-estimate (~3x period) to account for the recursive nature of EMA
# needing extra warmup bars to fully stabilize.

INDICATOR_REGISTRY: dict[IndicatorKey, _IndicatorSpec] = {
    IndicatorKey.MA: _IndicatorSpec(
        IndicatorKey.MA,
        "closes",
        {"periods": [5, 10, 20, 30, 60], "type": "sma"},
        lambda o: max(o.get("periods") or [5, 10, 20, 30, 60, 120, 250]) * (
            3 if (o.get("type") or "sma") == "ema" else 1
        ),
        lambda o: [f"ma{p}" for p in (o.get("periods") or [5, 10, 20, 30, 60, 120, 250])],
        _ma.calcMA,
    ),
    IndicatorKey.MACD: _IndicatorSpec(
        IndicatorKey.MACD,
        "closes",
        {"short": 12, "long": 26, "signal": 9},
        lambda o: int(o.get("long") or 26) * 3 + int(o.get("signal") or 9),
        lambda _o: ["macd_dif", "macd_dea", "macd_hist"],
        _macd.calcMACD,
    ),
    IndicatorKey.BOLL: _IndicatorSpec(
        IndicatorKey.BOLL,
        "closes",
        {"period": 20, "stdDev": 2.0},
        lambda o: int(o.get("period") or 20),
        lambda _o: ["boll_mid", "boll_upper", "boll_lower", "boll_bandwidth"],
        _boll.calcBOLL,
    ),
    IndicatorKey.KDJ: _IndicatorSpec(
        IndicatorKey.KDJ,
        "ohlcv",
        {"period": 9, "kPeriod": 3, "dPeriod": 3},
        lambda o: int(o.get("period") or 9) * 2,
        lambda _o: ["kdj_k", "kdj_d", "kdj_j"],
        _kdj.calcKDJ,
    ),
    IndicatorKey.RSI: _IndicatorSpec(
        IndicatorKey.RSI,
        "closes",
        {"periods": [6, 12, 24]},
        # Wilder's smoothing needs ~2x the period to stabilize
        lambda o: max(o.get("periods") or [6, 12, 24]) * 2,
        lambda o: [f"rsi_{p}" for p in (o.get("periods") or [6, 12, 24])],
        _rsi.calcRSI,
    ),
    IndicatorKey.WR: _IndicatorSpec(
        IndicatorKey.WR,
        "ohlcv",
        {"periods": [6, 10]},
        lambda o: max(o.get("periods") or [6, 10]),
        lambda o: [f"wr_{p}" for p in (o.get("periods") or [6, 10])],
        _wr.calcWR,
    ),
    IndicatorKey.BIAS: _IndicatorSpec(
        IndicatorKey.BIAS,
        "closes",
        {"periods": [6, 12, 24]},
        lambda o: max(o.get("periods") or [6, 12, 24]),
        lambda o: [f"bias_{p}" for p in (o.get("periods") or [6, 12, 24])],
        _bias.calcBIAS,
    ),
    IndicatorKey.CCI: _IndicatorSpec(
        IndicatorKey.CCI,
        "ohlcv",
        {"period": 14},
        lambda o: int(o.get("period") or 14),
        lambda _o: ["cci"],
        _cci.calcCCI,
    ),
    IndicatorKey.ATR: _IndicatorSpec(
        IndicatorKey.ATR,
        "ohlcv",
        {"period": 14},
        lambda o: int(o.get("period") or 14) * 2,
        lambda _o: ["atr", "tr"],
        _atr.calcATR,
    ),
    IndicatorKey.OBV: _IndicatorSpec(
        IndicatorKey.OBV,
        "ohlcv",
        {"maPeriod": 0},
        lambda o: int(o.get("maPeriod") or 0) + 1,
        lambda o: ["obv", "obv_ma"] if int(o.get("maPeriod") or 0) > 0 else ["obv"],
        _obv.calcOBV,
    ),
    IndicatorKey.ROC: _IndicatorSpec(
        IndicatorKey.ROC,
        "closes",
        {"period": 12, "signalPeriod": 0},
        lambda o: int(o.get("period") or 12) + (
            int(o.get("signalPeriod") or 0) * 3
            if int(o.get("signalPeriod") or 0)
            else 0
        ),
        lambda o: ["roc", "roc_signal"] if int(o.get("signalPeriod") or 0) > 0 else ["roc"],
        _roc.calcROC,
    ),
    IndicatorKey.DMI: _IndicatorSpec(
        IndicatorKey.DMI,
        "ohlcv",
        {"period": 14, "adxPeriod": 14},
        lambda o: int(o.get("period") or 14) * 2 + int(o.get("adxPeriod") or 14) * 2,
        lambda _o: ["dmi_pdi", "dmi_mdi", "dmi_adx", "dmi_adxr"],
        _dmi.calcDMI,
    ),
    IndicatorKey.SAR: _IndicatorSpec(
        IndicatorKey.SAR,
        "ohlcv",
        {"afStart": 0.02, "afIncrement": 0.02, "afMax": 0.20},
        lambda _o: 5,  # SAR stabilizes after a handful of bars
        lambda _o: ["sar", "sar_trend", "sar_ep", "sar_af"],
        _sar.calcSAR,
    ),
    IndicatorKey.KC: _IndicatorSpec(
        IndicatorKey.KC,
        "ohlcv",
        {"emaPeriod": 20, "atrPeriod": 10, "multiplier": 2.0},
        lambda o: max(
            int(o.get("emaPeriod") or 20) * 3,
            int(o.get("atrPeriod") or 10) * 2,
        ),
        lambda _o: ["kc_mid", "kc_upper", "kc_lower", "kc_width"],
        _kc.calcKC,
    ),
}


def list_indicators() -> list[dict[str, Any]]:
    """Public catalog: a list of {key, default_options, output_columns, lookback}.

    Used by the `/indicators/catalog` endpoint to advertise capability
    to AI agents without their having to read the source.
    """
    return [
        {
            "key": spec.key.value,
            "input_shape": spec.input_shape,
            "default_options": spec.default_options,
            "output_columns": spec.output_columns(spec.default_options),
            "default_lookback": spec.estimate_lookback(spec.default_options),
        }
        for spec in INDICATOR_REGISTRY.values()
    ]


def estimate_lookback(spec: dict[str, Any]) -> int:
    """Compute the largest lookback across multiple requested indicators.

    `spec` maps IndicatorKey.value (or IndicatorKey) -> options dict.
    Returns the maximum number of historical bars the orchestrator
    should fetch to fully warm up all requested indicators.
    """
    if not spec:
        return 0
    max_lookback = 0
    for key_value, options in spec.items():
        if isinstance(key_value, str):
            try:
                key = IndicatorKey(key_value)
            except ValueError:
                continue
        else:
            key = key_value
        spec_obj = INDICATOR_REGISTRY.get(key)
        if spec_obj is None:
            continue
        max_lookback = max(max_lookback, spec_obj.estimate_lookback(options or {}))
    return max_lookback


__all__ = [
    "INDICATOR_REGISTRY",
    "estimate_lookback",
    "list_indicators",
]
