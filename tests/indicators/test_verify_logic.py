"""Independent verification of indicator computation logic.

This script does NOT use the indicator implementation under test for the
"expected" values. Instead, it computes reference values from scratch
following the textbook formula, then compares against the implementation
output.

The point: a test that imports `calcMA` and asserts `result == calcMA(input)`
verifies consistency, not correctness. To verify correctness, we need an
*independent* reference.

Run: python -m pytest tests/indicators/verify_logic.py -v -s
"""

from __future__ import annotations

import math

import pytest

from stock_data.data_provider.indicators import (
    calcBOLL,
    calcCCI,
    calcEMA,
    calcKDJ,
    calcMA,
    calcMACD,
    calcOBV,
    calcRSI,
    calcSMA,
    calcWMA,
)
from stock_data.data_provider.indicators.bias import calcBIAS


# ============================================================================
# Independent reference implementations (textbook formulas, no shortcuts)
# ============================================================================


def ref_sma(data: list[float | None], period: int) -> list[float | None]:
    """Reference SMA: simple `sum(window) / period`, no rolling optimization."""
    out: list[float | None] = []
    for i in range(len(data)):
        window = data[max(0, i - period + 1) : i + 1]
        valid = [v for v in window if v is not None]
        if len(valid) == period and len(window) == period:
            out.append(sum(valid) / period)
        else:
            out.append(None)
    return out


def ref_ema(data: list[float | None], period: int) -> list[float | None]:
    """Reference EMA: seed = SMA of first `period`, then recursive."""
    alpha = 2.0 / (period + 1.0)
    out: list[float | None] = []
    ema: float | None = None
    seed: list[float] = []
    for v in data:
        if ema is None:
            if v is not None:
                seed.append(v)
            if len(seed) == period:
                ema = sum(seed) / period
                out.append(ema)
            else:
                out.append(None)
        else:
            if v is None:
                out.append(ema)
            else:
                ema = alpha * v + (1 - alpha) * ema
                out.append(ema)
    return out


def ref_wma(data: list[float | None], period: int) -> list[float | None]:
    """Reference WMA: linearly weighted by position."""
    weights = list(range(1, period + 1))
    wsum = sum(weights)
    out: list[float | None] = []
    for i in range(len(data)):
        window = data[max(0, i - period + 1) : i + 1]
        if len(window) < period or any(v is None for v in window):
            out.append(None)
        else:
            out.append(sum(w * v for w, v in zip(weights, window)) / wsum)
    return out


def ref_stddev_pop(window: list[float], mean: float) -> float:
    """Population stddev (N divisor)."""
    if not window:
        return 0.0
    return math.sqrt(sum((v - mean) ** 2 for v in window) / len(window))


def ref_boll(closes: list[float | None], period: int, std_dev: float):
    out = []
    for i in range(len(closes)):
        window = closes[max(0, i - period + 1) : i + 1]
        if len(window) < period or any(v is None for v in window):
            out.append(
                {"boll_mid": None, "boll_upper": None, "boll_lower": None, "boll_bandwidth": None}
            )
            continue
        mid = sum(window) / period
        sd = ref_stddev_pop(window, mid)
        upper = mid + std_dev * sd
        lower = mid - std_dev * sd
        bw = (upper - lower) / mid * 100 if mid != 0 else None
        out.append(
            {
                "boll_mid": round(mid, 2),
                "boll_upper": round(upper, 2),
                "boll_lower": round(lower, 2),
                "boll_bandwidth": round(bw, 2) if bw is not None else None,
            }
        )
    return out


def ref_bias(closes: list[float | None], periods: list[int]):
    arrays = {p: ref_sma(closes, p) for p in periods}
    out = []
    for i in range(len(closes)):
        close = closes[i]
        row = {}
        for p in periods:
            ma = arrays[p][i]
            if close is None or ma is None or ma == 0:
                row[f"bias_{p}"] = None
            else:
                row[f"bias_{p}"] = round((close - ma) / ma * 100.0, 2)
        out.append(row)
    return out


def ref_cci(bars: list[dict], period: int):
    """Reference CCI: textbook formula, uses unrounded MA for arithmetic."""
    tp = []
    for bar in bars:
        h, low, c = bar.get("high"), bar.get("low"), bar.get("close")
        if h is None or low is None or c is None:
            tp.append(None)
        else:
            tp.append((h + low + c) / 3.0)

    # Use unrounded SMA for CCI arithmetic (textbook says use exact MA)
    ma_tp = []
    for i in range(len(tp)):
        window = tp[max(0, i - period + 1) : i + 1]
        valid = [v for v in window if v is not None]
        if len(valid) == period and len(window) == period:
            ma_tp.append(sum(valid) / period)
        else:
            ma_tp.append(None)

    out = []
    for i, bar in enumerate(bars):
        ma = ma_tp[i]
        if ma is None or bar.get("high") is None or bar.get("low") is None:
            out.append({"cci": None})
            continue
        window = [v for v in tp[max(0, i - period + 1) : i + 1] if v is not None]
        if len(window) < period:
            out.append({"cci": None})
            continue
        md = sum(abs(v - ma) for v in window) / period
        if md == 0:
            out.append({"cci": None})
            continue
        cci = (tp[i] - ma) / (0.015 * md)
        out.append({"cci": round(cci, 2)})
    return out


def ref_macd(closes: list[float | None], short: int, long: int, signal: int):
    ema_short = ref_ema(closes, short)
    ema_long = ref_ema(closes, long)
    dif = [
        None if (s is None or long_e is None) else s - long_e
        for s, long_e in zip(ema_short, ema_long)
    ]
    dea = ref_ema(dif, signal)
    out = []
    for d, e in zip(dif, dea):
        out.append(
            {
                "macd_dif": round(d, 2) if d is not None else None,
                "macd_dea": round(e, 2) if e is not None else None,
                "macd_hist": (
                    round((d - e) * 2.0, 2) if d is not None and e is not None else None
                ),
            }
        )
    return out


# ============================================================================
# Verification tests — each compares implementation against reference
# ============================================================================

# ---------- SMA ----------


def test_sma_matches_reference_basic():
    closes = [10.0, 11.0, 12.0, 13.0, 14.0, 15.0, 16.0, 17.0]
    assert calcSMA(closes, 5) == ref_sma(closes, 5)


def test_sma_matches_reference_with_rounded_outputs():
    """The implementation rounds to 2 decimals; verify that's the only diff."""
    closes = [10.123, 11.456, 12.789, 13.123, 14.456, 15.789]
    expected = ref_sma(closes, 3)
    actual = calcSMA(closes, 3)
    # Implementation rounds to 2 decimals; reference keeps full precision.
    # We allow 0.01 tolerance for that.
    for e, a in zip(expected, actual):
        if e is None:
            assert a is None
        else:
            assert math.isclose(e, a, abs_tol=0.01), f"{e} vs {a}"


def test_sma_matches_reference_with_nones():
    closes = [10.0, None, 12.0, 13.0, 14.0]
    assert calcSMA(closes, 3) == ref_sma(closes, 3)


# ---------- EMA ----------


def test_ema_matches_reference_basic():
    closes = list(range(1, 30))
    expected = ref_ema(closes, 12)
    actual = calcEMA(closes, 12)
    for e, a in zip(expected, actual):
        if e is None:
            assert a is None
        else:
            assert math.isclose(e, a, abs_tol=0.01), f"bar diverged: ref={e} impl={a}"


def test_ema_matches_reference_with_none_propagation():
    closes = [1.0, 2.0, 3.0, None, 5.0, 6.0]
    expected = ref_ema(closes, 3)
    actual = calcEMA(closes, 3)
    for e, a in zip(expected, actual):
        if e is None:
            assert a is None
        else:
            assert math.isclose(e, a, abs_tol=0.01)


# ---------- WMA ----------


def test_wma_matches_reference_basic():
    closes = [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0]
    expected = ref_wma(closes, 5)
    actual = calcWMA(closes, 5)
    for e, a in zip(expected, actual):
        if e is None:
            assert a is None
        else:
            assert math.isclose(e, a, abs_tol=0.01)


# ---------- BOLL ----------


def test_boll_matches_reference_exact():
    closes = [float(i) for i in range(1, 26)]
    expected = ref_boll(closes, 20, 2.0)
    actual = calcBOLL(closes, {"period": 20, "stdDev": 2.0})
    assert len(actual) == len(expected)
    for e_row, a_row in zip(expected, actual):
        for key in ("boll_mid", "boll_upper", "boll_lower", "boll_bandwidth"):
            assert e_row[key] == a_row[key], f"{key}: ref={e_row[key]} impl={a_row[key]}"


def test_boll_custom_stddev_matches_reference():
    closes = [10.0] * 20 + [11.0] * 20
    expected = ref_boll(closes, 20, 1.5)
    actual = calcBOLL(closes, {"period": 20, "stdDev": 1.5})
    for e_row, a_row in zip(expected, actual):
        for key in ("boll_mid", "boll_upper", "boll_lower", "boll_bandwidth"):
            assert e_row[key] == a_row[key]


# ---------- BIAS ----------


def test_bias_matches_reference():
    closes = [float(i) for i in range(1, 31)]
    expected = ref_bias(closes, [6, 12, 24])
    actual = calcBIAS(closes, {"periods": [6, 12, 24]})
    assert len(actual) == len(expected)
    for e_row, a_row in zip(expected, actual):
        for key in e_row:
            assert e_row[key] == a_row[key], f"{key}: ref={e_row[key]} impl={a_row[key]}"


def test_bias_with_constant_prices():
    """Constant prices → BIAS must be exactly 0.0 (no rounding artifacts).

    Early bars (where the SMA window is not yet full) return None, which
    is correct — only check bars where bias is defined.
    """
    closes = [50.0] * 30
    rows = calcBIAS(closes, {"periods": [6, 12, 24]})
    for i, row in enumerate(rows):
        for k, v in row.items():
            if v is None:
                # Window not full yet — None is correct
                assert i < int(k.split("_")[1]) - 1, (
                    f"bar {i} {k} unexpectedly None (window should be full)"
                )
                continue
            assert v == 0.0, f"bar {i} {k}={v} should be exactly 0"


# ---------- CCI ---------- (the critical one — _sma was replaced)


def test_cci_matches_reference_unrounded():
    """Compare CCI implementation against textbook (unrounded MA) reference.

    Both the implementation and the reference use rounded MA internally
    (the implementation explicitly, the reference because we round in the
    final `round(cci, 2)` after arithmetic on the unrounded MA — but the
    implementation's MA is rounded BEFORE arithmetic).

    For inputs without None, the rounding error on MA is bounded by 0.005,
    so CCI delta is bounded by 0.005 / (0.015 * MD). For typical bars with
    MD ≥ 0.1, CCI delta is bounded by ~3.3. We use 5.0 as a generous
    tolerance to detect actual algorithm bugs while accepting rounding.
    """
    bars = [
        {
            "open": 10.0 + i,
            "high": 10.0 + i + 0.5,
            "low": 10.0 + i - 0.5,
            "close": 10.0 + i,
            "volume": 1000.0,
        }
        for i in range(30)
    ]
    expected = ref_cci(bars, 14)
    actual = calcCCI(bars, {"period": 14})
    assert len(actual) == len(expected)
    for i, (e_row, a_row) in enumerate(zip(expected, actual)):
        e_cci = e_row["cci"]
        a_cci = a_row["cci"]
        if e_cci is None:
            assert a_cci is None, f"bar {i}: ref=None, impl={a_cci}"
        else:
            # Allow tolerance for the rounding-at-MA difference
            assert math.isclose(e_cci, a_cci, abs_tol=5.0), (
                f"bar {i}: ref={e_cci} impl={a_cci}"
            )


def test_cci_arbitrary_input_specific_values():
    """Hand-computed CCI for a tiny case to nail down the algorithm.

    3 bars, period=3 (so only bar 2 has valid MA):
        bar 0: H=12 L=10 C=11 → TP = 11
        bar 1: H=13 L=11 C=12 → TP = 12
        bar 2: H=14 L=12 C=13 → TP = 13

    MA(TP, 3) at bar 2 = (11+12+13)/3 = 12

    MD at bar 2 = (|11-12| + |12-12| + |13-12|) / 3 = 2/3 ≈ 0.6667

    CCI = (13 - 12) / (0.015 * 0.6667) = 1 / 0.01 = 100.0
    """
    bars = [
        {"high": 12.0, "low": 10.0, "close": 11.0, "open": 11.0, "volume": 100.0},
        {"high": 13.0, "low": 11.0, "close": 12.0, "open": 12.0, "volume": 100.0},
        {"high": 14.0, "low": 12.0, "close": 13.0, "open": 13.0, "volume": 100.0},
    ]
    rows = calcCCI(bars, {"period": 3})
    assert rows[0]["cci"] is None  # window not full
    assert rows[1]["cci"] is None  # window not full
    # Bar 2: MA=12 (rounded to 12.0), MD=0.6667, CCI = (13-12)/(0.015*0.6667) = 100.0
    # Note: impl rounds MA to 12.0 first, so tp - ma = 1 exactly.
    assert rows[2]["cci"] is not None
    # In this case rounded MA happens to equal unrounded MA (12.0 is exact)
    assert math.isclose(rows[2]["cci"], 100.0, abs_tol=1.0)


def test_cci_first_valid_bar_is_period_minus_one_indexed():
    """Bar (period-1) is the first bar with a full TP window → first valid CCI."""
    bars = [
        {
            "open": 10.0 + i,
            "high": 11.0 + i,
            "low": 9.0 + i,
            "close": 10.0 + i,
            "volume": 1000.0,
        }
        for i in range(40)
    ]
    for period in [7, 14, 20]:
        rows = calcCCI(bars, {"period": period})
        # Bars 0..period-2 are None
        for i in range(period - 1):
            assert rows[i]["cci"] is None, f"period={period}, bar {i}"
        # Bar period-1 is the first valid
        assert rows[period - 1]["cci"] is not None, f"period={period}, bar {period-1}"


# ---------- MACD ----------


def test_macd_matches_reference():
    closes = [10.0 + 0.1 * i for i in range(60)]
    expected = ref_macd(closes, 12, 26, 9)
    from stock_data.data_provider.indicators.macd import calcMACD
    actual = calcMACD(closes)
    for e_row, a_row in zip(expected, actual):
        for key in ("macd_dif", "macd_dea", "macd_hist"):
            e_v = e_row[key]
            a_v = a_row[key]
            if e_v is None:
                assert a_v is None
            else:
                assert math.isclose(e_v, a_v, abs_tol=0.01), f"{key}: {e_v} vs {a_v}"


def test_macd_seeding_boundary():
    """For short=12, long=26: ema_long seeds at bar 25 (the 26th value),
    so DIF becomes valid at bar 25."""
    closes = list(range(1, 50))
    from stock_data.data_provider.indicators.macd import calcMACD
    rows = calcMACD(closes, {"short": 12, "long": 26, "signal": 9})
    for i in range(25):
        assert rows[i]["macd_dif"] is None
    assert rows[25]["macd_dif"] is not None


# ---------- OBV ----------


def test_obv_correctness_documented_example():
    """OBV textbook example: up-down-flat sequence."""
    bars = [
        {"close": 10, "volume": 100},
        {"close": 11, "volume": 200},  # up 200
        {"close": 10, "volume": 300},  # down 300 → -100
        {"close": 10, "volume": 400},  # flat → -100
    ]
    rows = calcOBV(bars)
    assert rows[0]["obv"] == 0
    assert rows[1]["obv"] == 200
    assert rows[2]["obv"] == -100
    assert rows[3]["obv"] == -100


def test_obv_ma_matches_standalone_sma():
    """OBV's ma should equal what calcSMA would compute on the OBV series."""
    bars = [
        {
            "open": 10.0 + (i % 2),
            "high": 11.0 + (i % 2),
            "low": 9.0 + (i % 2),
            "close": 10.0 + (i % 2),
            "volume": 100.0 + i,
        }
        for i in range(30)
    ]
    # Compute OBV directly to derive expected OBV series
    obvs = []
    prev = None
    obv = 0.0
    for bar in bars:
        c = bar["close"]
        v = bar["volume"]
        if prev is None:
            obvs.append(0.0)
        elif c > prev:
            obv += v
            obvs.append(obv)
        elif c < prev:
            obv -= v
            obvs.append(obv)
        else:
            obvs.append(obv)
        prev = c

    rows = calcOBV(bars, {"maPeriod": 5})
    expected_ma = calcSMA(obvs, 5)
    actual_ma = [row["obv_ma"] for row in rows]
    for e, a in zip(expected_ma, actual_ma):
        if e is None:
            assert a is None
        else:
            assert math.isclose(e, a, abs_tol=0.01)


# ---------- calcMA bulk (the helper that wires them all together) ----------


def test_calcma_sma_matches_individual_calls():
    """calcMA's per-period output should match calling calcSMA per period."""
    closes = list(range(1, 51))
    rows = calcMA(closes, {"periods": [5, 10, 20, 50], "type": "sma"})
    expected = {
        5: calcSMA(closes, 5),
        10: calcSMA(closes, 10),
        20: calcSMA(closes, 20),
        50: calcSMA(closes, 50),
    }
    for i, row in enumerate(rows):
        for p, arr in expected.items():
            assert row[f"ma{p}"] == arr[i], f"bar {i}, ma{p}"


def test_calcma_ema_matches_individual_calls():
    closes = list(range(1, 51))
    rows = calcMA(closes, {"periods": [12, 26], "type": "ema"})
    for p in [12, 26]:
        expected = calcEMA(closes, p)
        for i, row in enumerate(rows):
            # Allow tolerance for rounding
            e = expected[i]
            a = row[f"ma{p}"]
            if e is None:
                assert a is None
            else:
                assert math.isclose(e, a, abs_tol=0.01)


# ============================================================================
# Cross-indicator dedup — prove the MABatch wiring actually shares arrays
# ============================================================================


def test_ma20_shared_between_ma_and_boll_is_byte_identical():
    """When MA(periods=[20]) and BOLL(period=20) are computed in one shot,
    the ma20 and boll_mid values must be byte-identical — same underlying
    array reference (after final rounding)."""
    import pandas as pd

    from stock_data.data_provider.indicators.indicator_service import compute

    df = pd.DataFrame(
        {
            "date": pd.date_range("2024-01-01", periods=100, freq="B"),
            "open": [100.0 + i * 0.13 for i in range(100)],
            "high": [101.0 + i * 0.13 for i in range(100)],
            "low": [99.0 + i * 0.13 for i in range(100)],
            "close": [100.5 + i * 0.13 for i in range(100)],
            "volume": [1000.0] * 100,
            "amount": [1_000_000.0] * 100,
        }
    )
    out = compute(df, {"ma": {"periods": [20]}, "boll": {"period": 20}})

    indicators_per_bar = list(out["indicators"])
    for i, inds in enumerate(indicators_per_bar):
        # Both indicators write to the same SMA(20) array. After the
        # orchestrator's per-bar dict merge, ma20 and boll_mid must agree
        # at every bar where both are defined.
        if inds.get("ma20") is not None and inds.get("boll_mid") is not None:
            assert inds["ma20"] == inds["boll_mid"], (
                f"bar {i}: ma20={inds['ma20']} vs boll_mid={inds['boll_mid']}"
            )


def test_no_ma_duplicate_computation_in_full_spec():
    """Run the full orchestrator with raw-calc counting. The dedup means
    raw calls == unique (MA type, period) pairs across the spec.

    For {ma:[5,10,20], macd, boll:[20], bias, kc}, the unique pairs on
    the SHARED closes array are:
      SMA: {5, 10, 20, 6, 12, 24} = 6  (BOLL's period=20 dedups with MA's)
      EMA: {12, 26, 20}           = 3  (KC's 20, MACD's 12/26 on closes)

    The 4th EMA in MACD's pipeline is EMA(DIF, 9) — DIF is a freshly-
    built array that never enters the cache (cache keys by id(data)),
    so it goes through plain calcEMA, NOT through batch.ema. That call
    isn't dedupable and isn't counted as a "cache miss" either.
    """
    import pandas as pd

    from stock_data.data_provider.indicators import ma as _ma_mod
    from stock_data.data_provider.indicators.indicator_service import compute

    df = pd.DataFrame(
        {
            "date": pd.date_range("2024-01-01", periods=100, freq="B"),
            "open": [100.0 + i * 0.1 for i in range(100)],
            "high": [101.0 + i * 0.1 for i in range(100)],
            "low": [99.0 + i * 0.1 for i in range(100)],
            "close": [100.5 + i * 0.1 for i in range(100)],
            "volume": [1000.0] * 100,
            "amount": [1_000_000.0] * 100,
        }
    )

    raw_calls: dict[str, int] = {"sma": 0, "ema": 0}

    real_sma = _ma_mod.calcSMA
    real_ema = _ma_mod.calcEMA

    def counting_sma(data, period):
        raw_calls["sma"] = raw_calls.get("sma", 0) + 1
        return real_sma(data, period)

    def counting_ema(data, period):
        raw_calls["ema"] = raw_calls.get("ema", 0) + 1
        return real_ema(data, period)

    _ma_mod.calcSMA = counting_sma
    _ma_mod.calcEMA = counting_ema
    try:
        compute(
            df,
            {
                "ma": {"periods": [5, 10, 20]},
                "macd": {},
                "boll": {"period": 20},
                "bias": {},
                "kc": {},
            },
        )
    finally:
        _ma_mod.calcSMA = real_sma
        _ma_mod.calcEMA = real_ema

    # With MABatch dedup:
    #   SMA: 5, 10, 20, 6, 12, 24 = 6 unique (BOLL's 20 dedups)
    #   EMA: 12, 26, 20 = 3 unique (EMA(DIF, 9) bypasses batch by design)
    print(f"\n[dedup] raw SMA/EMA calls observed: {raw_calls}")
    assert raw_calls["sma"] == 6, f"expected 6 unique SMA, got {raw_calls['sma']}"
    assert raw_calls["ema"] == 3, f"expected 3 unique EMA, got {raw_calls['ema']}"