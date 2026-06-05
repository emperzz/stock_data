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

from dataclasses import dataclass, field
from typing import Any, Callable

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


ComputeFn = Callable[[list[float | None], dict[str, Any]], list[dict[str, float | None]]]
ComputeFnOHLCV = Callable[[list[OHLCV], dict[str, Any]], list[dict[str, float | None]]]
LookbackFn = Callable[[dict[str, Any]], int]
ColumnsFn = Callable[[dict[str, Any]], list[str]]


@dataclass(frozen=True)
class IndicatorDescriptor:
    key: IndicatorKey
    input_shape: str  # "closes" or "ohlcv"
    default_options: dict[str, Any] = field(default_factory=dict)
    estimate_lookback: LookbackFn = field(default=lambda opt: 0)
    output_columns: ColumnsFn = field(default=lambda opt: [])
    compute_closes: ComputeFn | None = None
    compute_ohlcv: ComputeFnOHLCV | None = None

    def run(
        self, closes: list[float | None], ohlcv: list[OHLCV], options: dict[str, Any]
    ) -> list[dict[str, float | None]]:
        if self.input_shape == "closes":
            assert self.compute_closes is not None
            return self.compute_closes(closes, options)
        assert self.compute_ohlcv is not None
        return self.compute_ohlcv(ohlcv, options)


# ---------- per-indicator lookback estimators ----------

# We over-estimate slightly to account for EMA's recursive nature
# (MACD needs roughly 3*long + signal bars to fully warm up).


def _ma_lookback(opt: dict[str, Any]) -> int:
    periods = opt.get("periods") or [5, 10, 20, 30, 60, 120, 250]
    ma_type = opt.get("type") or "sma"
    max_period = max(periods)
    if ma_type == "ema":
        return max_period * 3  # EMA needs ~3x its period to stabilize
    return max_period


def _macd_lookback(opt: dict[str, Any]) -> int:
    long = int(opt.get("long") or 26)
    signal = int(opt.get("signal") or 9)
    return long * 3 + signal


def _kdj_lookback(opt: dict[str, Any]) -> int:
    return int(opt.get("period") or 9) * 2


def _rsi_lookback(opt: dict[str, Any]) -> int:
    periods = opt.get("periods") or [6, 12, 24]
    # Wilder's smoothing needs ~2x the period to stabilize
    return max(periods) * 2


def _wr_lookback(opt: dict[str, Any]) -> int:
    periods = opt.get("periods") or [6, 10]
    return max(periods)


def _bias_lookback(opt: dict[str, Any]) -> int:
    periods = opt.get("periods") or [6, 12, 24]
    return max(periods)


def _cci_lookback(opt: dict[str, Any]) -> int:
    return int(opt.get("period") or 14)


def _atr_lookback(opt: dict[str, Any]) -> int:
    return int(opt.get("period") or 14) * 2


def _obv_lookback(opt: dict[str, Any]) -> int:
    return int(opt.get("maPeriod") or 0) + 1


def _roc_lookback(opt: dict[str, Any]) -> int:
    period = int(opt.get("period") or 12)
    signal = int(opt.get("signalPeriod") or 0)
    return period + signal * 3 if signal else period


def _dmi_lookback(opt: dict[str, Any]) -> int:
    period = int(opt.get("period") or 14)
    adx = int(opt.get("adxPeriod") or period)
    return period * 2 + adx * 2


def _sar_lookback(_opt: dict[str, Any]) -> int:
    return 5  # SAR stabilizes after a handful of bars


def _kc_lookback(opt: dict[str, Any]) -> int:
    ema_p = int(opt.get("emaPeriod") or 20)
    atr_p = int(opt.get("atrPeriod") or 10)
    return max(ema_p * 3, atr_p * 2)


# ---------- per-indicator output column estimators ----------


def _ma_columns(opt: dict[str, Any]) -> list[str]:
    periods = opt.get("periods") or [5, 10, 20, 30, 60, 120, 250]
    return [f"ma{p}" for p in periods]


def _rsi_columns(opt: dict[str, Any]) -> list[str]:
    return [f"rsi_{p}" for p in (opt.get("periods") or [6, 12, 24])]


def _wr_columns(opt: dict[str, Any]) -> list[str]:
    return [f"wr_{p}" for p in (opt.get("periods") or [6, 10])]


def _bias_columns(opt: dict[str, Any]) -> list[str]:
    return [f"bias_{p}" for p in (opt.get("periods") or [6, 12, 24])]


def _obv_columns(opt: dict[str, Any]) -> list[str]:
    cols = ["obv"]
    if int(opt.get("maPeriod") or 0) > 0:
        cols.append("obv_ma")
    return cols


def _roc_columns(opt: dict[str, Any]) -> list[str]:
    cols = ["roc"]
    if int(opt.get("signalPeriod") or 0) > 0:
        cols.append("roc_signal")
    return cols


# ---------- the registry itself ----------


INDICATOR_REGISTRY: dict[IndicatorKey, IndicatorDescriptor] = {
    IndicatorKey.MA: IndicatorDescriptor(
        key=IndicatorKey.MA,
        input_shape="closes",
        default_options={"periods": [5, 10, 20, 30, 60], "type": "sma"},
        estimate_lookback=_ma_lookback,
        output_columns=_ma_columns,
        compute_closes=_ma.calcMA,
    ),
    IndicatorKey.MACD: IndicatorDescriptor(
        key=IndicatorKey.MACD,
        input_shape="closes",
        default_options={"short": 12, "long": 26, "signal": 9},
        estimate_lookback=_macd_lookback,
        output_columns=lambda _o: ["macd_dif", "macd_dea", "macd_hist"],
        compute_closes=_macd.calcMACD,
    ),
    IndicatorKey.BOLL: IndicatorDescriptor(
        key=IndicatorKey.BOLL,
        input_shape="closes",
        default_options={"period": 20, "stdDev": 2.0},
        estimate_lookback=lambda o: int(o.get("period") or 20),
        output_columns=lambda _o: ["boll_mid", "boll_upper", "boll_lower", "boll_bandwidth"],
        compute_closes=_boll.calcBOLL,
    ),
    IndicatorKey.KDJ: IndicatorDescriptor(
        key=IndicatorKey.KDJ,
        input_shape="ohlcv",
        default_options={"period": 9, "kPeriod": 3, "dPeriod": 3},
        estimate_lookback=_kdj_lookback,
        output_columns=lambda _o: ["kdj_k", "kdj_d", "kdj_j"],
        compute_ohlcv=_kdj.calcKDJ,
    ),
    IndicatorKey.RSI: IndicatorDescriptor(
        key=IndicatorKey.RSI,
        input_shape="closes",
        default_options={"periods": [6, 12, 24]},
        estimate_lookback=_rsi_lookback,
        output_columns=_rsi_columns,
        compute_closes=_rsi.calcRSI,
    ),
    IndicatorKey.WR: IndicatorDescriptor(
        key=IndicatorKey.WR,
        input_shape="ohlcv",
        default_options={"periods": [6, 10]},
        estimate_lookback=_wr_lookback,
        output_columns=_wr_columns,
        compute_ohlcv=_wr.calcWR,
    ),
    IndicatorKey.BIAS: IndicatorDescriptor(
        key=IndicatorKey.BIAS,
        input_shape="closes",
        default_options={"periods": [6, 12, 24]},
        estimate_lookback=_bias_lookback,
        output_columns=_bias_columns,
        compute_closes=_bias.calcBIAS,
    ),
    IndicatorKey.CCI: IndicatorDescriptor(
        key=IndicatorKey.CCI,
        input_shape="ohlcv",
        default_options={"period": 14},
        estimate_lookback=_cci_lookback,
        output_columns=lambda _o: ["cci"],
        compute_ohlcv=_cci.calcCCI,
    ),
    IndicatorKey.ATR: IndicatorDescriptor(
        key=IndicatorKey.ATR,
        input_shape="ohlcv",
        default_options={"period": 14},
        estimate_lookback=_atr_lookback,
        output_columns=lambda _o: ["atr", "tr"],
        compute_ohlcv=_atr.calcATR,
    ),
    IndicatorKey.OBV: IndicatorDescriptor(
        key=IndicatorKey.OBV,
        input_shape="ohlcv",
        default_options={"maPeriod": 0},
        estimate_lookback=_obv_lookback,
        output_columns=_obv_columns,
        compute_ohlcv=_obv.calcOBV,
    ),
    IndicatorKey.ROC: IndicatorDescriptor(
        key=IndicatorKey.ROC,
        input_shape="closes",
        default_options={"period": 12, "signalPeriod": 0},
        estimate_lookback=_roc_lookback,
        output_columns=_roc_columns,
        compute_closes=_roc.calcROC,
    ),
    IndicatorKey.DMI: IndicatorDescriptor(
        key=IndicatorKey.DMI,
        input_shape="ohlcv",
        default_options={"period": 14, "adxPeriod": 14},
        estimate_lookback=_dmi_lookback,
        output_columns=lambda _o: ["dmi_pdi", "dmi_mdi", "dmi_adx", "dmi_adxr"],
        compute_ohlcv=_dmi.calcDMI,
    ),
    IndicatorKey.SAR: IndicatorDescriptor(
        key=IndicatorKey.SAR,
        input_shape="ohlcv",
        default_options={"afStart": 0.02, "afIncrement": 0.02, "afMax": 0.20},
        estimate_lookback=_sar_lookback,
        output_columns=lambda _o: ["sar", "sar_trend", "sar_ep", "sar_af"],
        compute_ohlcv=_sar.calcSAR,
    ),
    IndicatorKey.KC: IndicatorDescriptor(
        key=IndicatorKey.KC,
        input_shape="ohlcv",
        default_options={"emaPeriod": 20, "atrPeriod": 10, "multiplier": 2.0},
        estimate_lookback=_kc_lookback,
        output_columns=lambda _o: ["kc_mid", "kc_upper", "kc_lower", "kc_width"],
        compute_ohlcv=_kc.calcKC,
    ),
}


def list_indicators() -> list[dict[str, Any]]:
    """Public catalog: a list of {key, default_options, output_columns, lookback}.

    Used by the `/indicators/catalog` endpoint to advertise capability
    to AI agents without their having to read the source.
    """
    catalog: list[dict[str, Any]] = []
    for descriptor in INDICATOR_REGISTRY.values():
        catalog.append(
            {
                "key": descriptor.key.value,
                "input_shape": descriptor.input_shape,
                "default_options": descriptor.default_options,
                "output_columns": descriptor.output_columns(descriptor.default_options),
                "default_lookback": descriptor.estimate_lookback(descriptor.default_options),
            }
        )
    return catalog


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
        descriptor = INDICATOR_REGISTRY.get(key)
        if descriptor is None:
            continue
        lookback = descriptor.estimate_lookback(options or {})
        max_lookback = max(max_lookback, lookback)
    return max_lookback


__all__ = [
    "IndicatorDescriptor",
    "INDICATOR_REGISTRY",
    "list_indicators",
    "estimate_lookback",
]
