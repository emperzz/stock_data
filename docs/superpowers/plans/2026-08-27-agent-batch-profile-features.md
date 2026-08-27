# `/agent/{stocks,indices}/batch-profile` Computed K-line Features — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the raw K-line bar payloads in both batch-profile endpoints with server-computed `trend / pivots / volume` feature blocks, so the LLM agent consumes judgment-ready numeric facts instead of hundreds of raw bars.

**Architecture:** A new pure-compute package `stock_data/data_provider/features/` (sitting on top of the existing indicator layer) turns a K-line DataFrame into the three feature blocks. The two routes in `routes/agent.py` are rewritten to fetch `adjust="qfq"` (stocks) / none (indices) at a single `frequency` + `days`, assemble the blocks, and keep minimal `quote` + retained `info`/`boards` (stocks only). Schemas and cache keys change to carry `frequency` + `days`.

**Tech Stack:** Python 3, pandas, FastAPI, Pydantic v2, pytest. Reuses `indicator_service.compute` and `registry.estimate_lookback` (no new fetcher / manager / DataCapability).

## Global Constraints

- Spec: `docs/superpowers/specs/2026-08-27-agent-batch-profile-features-design.md`.
- Public `frequency` strings (`d / w / m / 1m / 5m / 15m / 30m / 60m`) are validated against the per-freq days table. The manager-facing frequency is `_FREQ_TO_MGR[f]` (`5m`→`5`, `15m`→`15`, …; `d/w/m` unchanged) — **never pass `5m` verbatim to `manager.get_kline_data`** (fetchers only accept bare minute codes `1/5/15/30/60`; confirmed by the plan's cross-check agent).
- Per-frequency `days` (calendar) ranges — route must 422 outside these (min is inclusive, max is inclusive):
  `d:(2,365) w:(14,1095) m:(60,1825) 1m:(2,3) 5m:(2,5) 15m:(2,8) 30m:(2,15) 60m:(2,30)`
- Default `days` when omitted: `d:60 w:156 m:365 1m:3 5m:5 15m:8 30m:15 60m:30`.
- MA periods are FIXED `[5, 10, 15, 20, 30, 60]`.
- Stocks feature fetch always `adjust="qfq"`; indices `adjust=None`. No `adjust` request param.
- Pivot params server-fixed: `pivot_window=2`, `reversal_atr_mult=1.0`, `atr_period=14`. Echoed in `pivots.params` only.
- Volume Z-score: keep bars with `z > 2.0` over the requested `days` window, sorted `z_score` desc, capped at 20.
- Cache key = `(sorted codes, frequency, days)`; 60s `get_quote_cache`; on hit reorder to input `codes` order.
- Run tests with `.venv/Scripts/python.exe -m pytest`.
- Commit after every green test run. Keep commits small.

---

### Task 1: `features/volume.py` — volume block

**Files:**
- Create: `stock_data/data_provider/features/volume.py`
- Test: `tests/test_agent_batch_features.py`

**Interfaces:**
- Consumes: a K-line DataFrame with columns `date / open / high / low / close / volume` (STANDARD_COLUMNS), and a pre-sliced `window_df` (the requested-days window, same columns).
- Produces: `compute_volume(df, window_df) -> dict` with keys `latest_volume` (float|None), `vol_ratio_5` (float|None), `z_anomalies` (list of dicts).

- [ ] **Step 1: Write the failing test**

Create `tests/test_agent_batch_features.py` with the shared reset fixture + helpers, and a first test for `compute_volume`:

```python
"""Tests for /api/v1/agent/* batch-profile computed K-line features."""

import contextlib
import random

import pandas as pd
import pytest

from stock_data.api.routes import reset_manager
from stock_data.data_provider.features.volume import compute_volume


@pytest.fixture(autouse=True)
def reset_before_test():
    reset_manager()
    from stock_data.api import cache as api_cache

    for getter_name in (
        "get_quote_cache",
        "get_index_quote_cache",
        "get_history_cache",
        "get_pools_cache",
        "get_stock_info_cache",
        "get_news_flash_cache",
        "get_cls_feed_cache",
        "get_dragontiger_cache",
    ):
        getter = getattr(api_cache, getter_name, None)
        if getter is None:
            continue
        with contextlib.suppress(TypeError):
            getter().clear()
    for f in ("d", "w", "m", "1", "5", "15", "30", "60"):
        with contextlib.suppress(Exception):
            api_cache.get_history_cache(f).clear()
    yield


def _make_kline_df(rows, *, seed=1, spike_idx=(), spike_mult=4.0) -> pd.DataFrame:
    """Deterministic OHLCV frame. A gentle upward drift + optional volume spikes."""
    rng = random.Random(seed)
    closes = [10.0]
    for _ in range(rows - 1):
        closes.append(closes[-1] * (1 + rng.uniform(-0.02, 0.03)))
    dates = pd.date_range("2026-01-01", periods=rows, freq="B")
    vols = [1_000_000 * (1 + abs(rng.gauss(0, 0.3))) for _ in range(rows)]
    for i in spike_idx:
        vols[i] *= spike_mult
    return pd.DataFrame(
        {
            "date": [d.strftime("%Y-%m-%d") for d in dates],
            "open": [round(c * 0.995, 3) for c in closes],
            "high": [round(c * 1.01, 3) for c in closes],
            "low": [round(c * 0.99, 3) for c in closes],
            "close": [round(c, 3) for c in closes],
            "volume": vols,
            "amount": [v * c for v, c in zip(vols, closes)],
            "pct_chg": [0.0] * rows,
        }
    )


def _window_by_last_days(df, days):
    last = pd.Timestamp(df["date"].iloc[-1])
    cutoff = last - pd.Timedelta(days=days)
    return df[pd.to_datetime(df["date"]) >= cutoff]


class TestVolumeFeatures:
    def test_latest_volume_and_ratio(self):
        df = _make_kline_df(30)
        window = _window_by_last_days(df, 20)
        out = compute_volume(df, window)
        # latest_volume is the last bar's volume
        assert out["latest_volume"] == float(df["volume"].iloc[-1])
        # vol_ratio_5 = latest / mean(previous 5) — verify against manual math
        prev5 = df["volume"].iloc[-6:-1].mean()
        assert out["vol_ratio_5"] == pytest.approx(float(df["volume"].iloc[-1]) / prev5)

    def test_z_anomalies_only_above_2(self):
        df = _make_kline_df(60, spike_idx=(30,), spike_mult=5.0)
        window = _window_by_last_days(df, 50)
        out = compute_volume(df, window)
        assert len(out["z_anomalies"]) >= 1
        # the spike bar must be present and sorted by z desc
        spike_date = df["date"].iloc[30]
        assert out["z_anomalies"][0]["date"] == spike_date
        assert all(a["z_score"] > 2.0 for a in out["z_anomalies"])
        assert all(
            out["z_anomalies"][i]["z_score"] >= out["z_anomalies"][i + 1]["z_score"]
            for i in range(len(out["z_anomalies"]) - 1)
        )

    def test_z_anomalies_capped_at_20(self):
        # every volume differs by a huge amount → many bars exceed z>2
        df = _make_kline_df(60, seed=3)
        vols = [float(v) for v in df["volume"]]
        df["volume"] = [v * (1 + i) for i, v in enumerate(vols)]  # monotone scale → all z>2
        window = _window_by_last_days(df, 50)
        out = compute_volume(df, window)
        assert len(out["z_anomalies"]) <= 20

    def test_anomaly_bar_fields(self):
        df = _make_kline_df(30, spike_idx=(20,), spike_mult=6.0)
        window = _window_by_last_days(df, 25)
        out = compute_volume(df, window)
        a = out["z_anomalies"][0]
        for key in ("date", "open", "high", "low", "close", "volume", "z_score", "direction", "change_pct"):
            assert key in a
        assert a["direction"] in ("up", "down")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_agent_batch_features.py::TestVolumeFeatures -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'stock_data.data_provider.features'`.

- [ ] **Step 3: Write minimal implementation**

Create `stock_data/data_provider/features/volume.py`:

```python
"""Volume block for the agent batch-profile feature layer.

Pure compute: takes a K-line DataFrame (STANDARD_COLUMNS) plus a
pre-sliced window frame and returns the volume facts an agent needs for
`market-principles` §5.2 volume-price judgment:
  - latest_volume: newest bar's volume
  - vol_ratio_5:   newest bar / mean of the previous 5 bars (excl. current)
  - z_anomalies:   bars in the window whose volume Z-score > 2.0
"""

from __future__ import annotations

import pandas as pd

_Z_THRESHOLD = 2.0
_MAX_ANOMALIES = 20


def _float(v) -> float | None:
    return None if v is None or pd.isna(v) else float(v)


def compute_volume(df: pd.DataFrame, window_df: pd.DataFrame) -> dict:
    """Compute the volume block. Returns a dict ready for Pydantic."""
    if df is None or df.empty:
        return {"latest_volume": None, "vol_ratio_5": None, "z_anomalies": []}

    latest_volume = _float(df["volume"].iloc[-1])

    vol_ratio_5: float | None = None
    if len(df) >= 6:
        prev5 = pd.to_numeric(df["volume"].iloc[-6:-1], errors="coerce").mean()
        if latest_volume is not None and prev5 and prev5 > 0:
            vol_ratio_5 = latest_volume / float(prev5)

    anomalies: list[dict] = []
    if window_df is not None and not window_df.empty:
        vols = pd.to_numeric(window_df["volume"], errors="coerce")
        mean, std = vols.mean(), vols.std(ddof=0)
        if std and not pd.isna(std) and std > 0:
            zs = (vols - mean) / std
            for idx in window_df.index[zs > _Z_THRESHOLD]:
                row = window_df.loc[idx]
                pos = df.index.get_loc(idx)
                prev_close = df["close"].iloc[pos - 1] if pos > 0 else None
                pc = _float(prev_close)
                close_v = _float(row["close"])
                open_v = _float(row["open"])
                change_pct = (
                    (close_v - pc) / pc * 100
                    if (close_v is not None and pc and pc != 0)
                    else None
                )
                anomalies.append(
                    {
                        "date": str(row["date"]),
                        "open": open_v,
                        "high": _float(row["high"]),
                        "low": _float(row["low"]),
                        "close": close_v,
                        "volume": _float(row["volume"]),
                        "z_score": round(float(zs.loc[idx]), 2),
                        "direction": "up" if close_v is not None and open_v is not None and close_v >= open_v else "down",
                        "change_pct": change_pct,
                    }
                )
    anomalies.sort(key=lambda a: a["z_score"], reverse=True)
    anomalies = anomalies[:_MAX_ANOMALIES]
    return {"latest_volume": latest_volume, "vol_ratio_5": vol_ratio_5, "z_anomalies": anomalies}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/test_agent_batch_features.py::TestVolumeFeatures -v`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add stock_data/data_provider/features/volume.py tests/test_agent_batch_features.py
git commit -m "feat(features): volume block (latest volume + 5-bar ratio + Z>2 anomalies)"
```

---

### Task 2: `features/trend.py` — trend block

**Files:**
- Create: `stock_data/data_provider/features/trend.py`
- Test: `tests/test_agent_batch_features.py`

**Interfaces:**
- Consumes: a full (warm) K-line DataFrame with STANDARD_COLUMNS.
- Produces: `compute_trend(df) -> dict` with keys `ma`, `ma_change` (dict keyed `ma5..ma60`), `adx`, `pdi`, `mdi`, `rsi` (dict keyed `rsi_6/12/24`), `boll` (dict keyed `mid/upper/lower/bandwidth`).

- [ ] **Step 1: Write the failing test**

Append to `tests/test_agent_batch_features.py`:

```python
from stock_data.data_provider.features.trend import compute_trend


class TestTrendFeatures:
    def test_ma_values_match_sma(self):
        df = _make_kline_df(80)
        out = compute_trend(df)
        closes = df["close"].tolist()
        expected_ma5 = sum(closes[-5:]) / 5
        assert out["ma"]["ma5"] == pytest.approx(expected_ma5, rel=1e-6)
        assert set(out["ma"].keys()) == {"ma5", "ma10", "ma15", "ma20", "ma30", "ma60"}
        assert out["ma"]["ma60"] is not None  # warm (80 rows)

    def test_ma_change_is_vs_previous_bar(self):
        df = _make_kline_df(80)
        out = compute_trend(df)
        closes = df["close"].tolist()
        ma5_cur = sum(closes[-5:]) / 5
        ma5_prev = sum(closes[-6:-1]) / 5
        assert out["ma_change"]["ma5"] == pytest.approx((ma5_cur - ma5_prev) / ma5_prev * 100, rel=1e-6)

    def test_adx_rsi_boll_present(self):
        out = compute_trend(_make_kline_df(120))
        assert out["adx"] is not None
        assert {"pdi", "mdi"} <= set(out)
        assert set(out["rsi"].keys()) == {"rsi_6", "rsi_12", "rsi_24"}
        assert set(out["boll"].keys()) == {"mid", "upper", "lower", "bandwidth"}

    def test_empty_df_returns_empty_blocks(self):
        import pandas as pd
        out = compute_trend(pd.DataFrame())
        assert out["ma"] == {}
        assert out["ma_change"] == {}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_agent_batch_features.py::TestTrendFeatures -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'stock_data.data_provider.features.trend'`.

- [ ] **Step 3: Write minimal implementation**

Create `stock_data/data_provider/features/trend.py`:

```python
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
        row = rows.iloc[min(offset, len(rows) - 1)]
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/test_agent_batch_features.py::TestTrendFeatures -v`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add stock_data/data_provider/features/trend.py tests/test_agent_batch_features.py
git commit -m "feat(features): trend block (MA latest + 1-bar change + DMI/RSI/BOLL)"
```

---

### Task 3: `features/pivots.py` — top/bottom (ZigZag) block

**Files:**
- Create: `stock_data/data_provider/features/pivots.py`
- Test: `tests/test_agent_batch_features.py`

**Interfaces:**
- Consumes: full (warm) K-line df + pre-sliced `window_df`.
- Produces: `compute_pivots(df, window_df, *, pivot_window=2, atr_mult=1.0, atr_period=14, max_swings=6) -> dict` with keys `window_high / window_low / max_vol_bar` (dicts `{price, date}` / `{price, volume, date}` or None), `swings` (list of `{date, type: high|low, price, confirmed: True}`), `pending` (`{side, bars, price, date}` or None), `params` (dict of the fixed settings).

- [ ] **Step 1: Write the failing test**

Append to `tests/test_agent_batch_features.py`:

```python
from stock_data.data_provider.features.pivots import compute_pivots


def _make_pivot_df(prices):
    """Explicit-price K-line for deterministic swing tests."""
    n = len(prices)
    dates = pd.date_range("2026-01-01", periods=n, freq="B")
    return pd.DataFrame(
        {
            "date": [d.strftime("%Y-%m-%d") for d in dates],
            "open": [p * 0.995 for p in prices],
            "high": [p * 1.05 for p in prices],
            "low": [p * 0.95 for p in prices],
            "close": [float(p) for p in prices],
            "volume": [1_000_000 + i * 100_000 for i in range(n)],
            "amount": [0.0] * n,
            "pct_chg": [0.0] * n,
        }
    )


class TestPivotFeatures:
    def test_window_stats(self):
        df = _make_pivot_df([10, 12, 15, 14, 11, 9, 12, 16])
        window = _window_by_last_days(df, 30)
        out = compute_pivots(df, window)
        assert out["window_high"]["price"] == 16.0
        assert out["window_low"]["price"] == 9.0
        assert out["window_high"]["date"]
        # max_vol_bar is the max-volume bar's close (volumes increase over time)
        assert out["max_vol_bar"]["volume"] == float(df["volume"].iloc[-1])

    def test_swings_alternate_with_loose_threshold(self):
        # 10→15→9→16→10 : majors high@15, low@9, high@16, pending low@10
        df = _make_pivot_df([10, 11, 12, 15, 13, 11, 9, 11, 13, 16, 14, 12, 10])
        window = _window_by_last_days(df, 30)
        out = compute_pivots(df, window, pivot_window=1, atr_mult=0.2)
        types = [s["type"] for s in out["swings"]]
        assert types and all(a != b for a, b in zip(types, types[1:]))  # alternates
        assert types[0] == "high"
        assert out["pending"] is not None
        assert out["pending"]["side"] in ("high", "low")

    def test_pending_is_last_unconfirmed(self):
        df = _make_pivot_df([10, 12, 15, 13, 11, 9, 10, 11])
        window = _window_by_last_days(df, 30)
        out = compute_pivots(df, window, pivot_window=1, atr_mult=0.2)
        assert out["pending"] is not None
        assert out["pending"]["bars"] >= 0

    def test_empty_df_returns_empty(self):
        out = compute_pivots(pd.DataFrame(), pd.DataFrame())
        assert out["window_high"] is None
        assert out["swings"] == []
        assert out["pending"] is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_agent_batch_features.py::TestPivotFeatures -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'stock_data.data_provider.features.pivots'`.

- [ ] **Step 3: Write minimal implementation**

Create `stock_data/data_provider/features/pivots.py`:

```python
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
    return None if v is None or pd.isna(v) or v <= 0 else float(v)


def _detect_swings(df: pd.DataFrame, pivot_window: int, atr_mult: float, atr_value: float):
    highs = [float(h) for h in df["high"]]
    lows = [float(l) for l in df["low"]]
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
        "window_high": {"price": float(hi["high"]), "date": str(hi["date"])},
        "window_low": {"price": float(lo["low"]), "date": str(lo["date"])},
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/test_agent_batch_features.py::TestPivotFeatures -v`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add stock_data/data_provider/features/pivots.py tests/test_agent_batch_features.py
git commit -m "feat(features): pivot block (ZigZag significance-filtered swings + window stats)"
```

---

### Task 4: `features/build.py` + package init — orchestrator

**Files:**
- Create: `stock_data/data_provider/features/__init__.py`
- Create: `stock_data/data_provider/features/build.py`
- Test: `tests/test_agent_batch_features.py`

**Interfaces:**
- Consumes: the three `compute_*` functions from Tasks 1-3.
- Produces: `build_features(df, *, frequency: str, days: int) -> dict` returning `{"trend": {...}, "pivots": {...}, "volume": {...}}`. Also exposes `window_by_days(df, days) -> pd.DataFrame`.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_agent_batch_features.py`:

```python
from stock_data.data_provider.features.build import build_features


class TestBuildFeatures:
    def test_assembles_three_blocks(self):
        df = _make_kline_df(120, spike_idx=(80,), spike_mult=5.0)
        out = build_features(df, frequency="d", days=60)
        assert set(out.keys()) == {"trend", "pivots", "volume"}
        assert out["trend"]["ma"]["ma60"] is not None
        assert out["pivots"]["swings"] is not None
        assert out["volume"]["latest_volume"] is not None
        assert len(out["volume"]["z_anomalies"]) >= 1

    def test_window_respects_days(self):
        df = _make_kline_df(120)
        out_60 = build_features(df, frequency="d", days=60)
        # window_high computed on last ~60 calendar days of bars only
        assert out_60["pivots"]["window_high"]["price"] == float(df["high"].iloc[-42:].max())
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_agent_batch_features.py::TestBuildFeatures -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'stock_data.data_provider.features.build'`.

- [ ] **Step 3: Write minimal implementation**

Create `stock_data/data_provider/features/__init__.py`:

```python
"""Computed K-line feature layer for the agent batch-profile endpoints.

Pure compute on top of the indicator layer — never touches the network
or the manager. ``build_features`` turns a K-line DataFrame into the
trend / pivots / volume blocks consumed by ``/agent/*/batch-profile``.
"""

from .build import build_features

__all__ = ["build_features"]
```

Create `stock_data/data_provider/features/build.py`:

```python
"""Orchestrator: assemble the trend / pivots / volume feature blocks.

``window_by_days`` slices a K-line df to the bars whose date falls within
the last ``days`` calendar days — this is the "周期范围" used for window
stats and Z-score anomaly detection. Indicators / swing detection use the
full (warm) frame.
"""

from __future__ import annotations

import pandas as pd

from .pivots import compute_pivots
from .trend import compute_trend
from .volume import compute_volume


def window_by_days(df: pd.DataFrame, days: int) -> pd.DataFrame:
    """Bars within the last ``days`` calendar days (inclusive of the last bar)."""
    if df is None or df.empty:
        return df
    last = pd.Timestamp(df["date"].iloc[-1])
    cutoff = last - pd.Timedelta(days=days)
    dates = pd.to_datetime(df["date"])
    return df[dates >= cutoff]


def build_features(df: pd.DataFrame, *, frequency: str, days: int) -> dict:
    """Return {"trend": ..., "pivots": ..., "volume": ...} for one code.

    ``frequency`` is unused by the pure computation itself but is kept in
    the signature so the route's fetch window (which differs per frequency)
    is decided at the call site.
    """
    if df is None or df.empty:
        return {"trend": {}, "pivots": {}, "volume": {}}
    window_df = window_by_days(df, days)
    return {
        "trend": compute_trend(df),
        "pivots": compute_pivots(df, window_df),
        "volume": compute_volume(df, window_df),
    }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/test_agent_batch_features.py -v`
Expected: PASS (all tests so far).

- [ ] **Step 5: Commit**

```bash
git add stock_data/data_provider/features/__init__.py stock_data/data_provider/features/build.py tests/test_agent_batch_features.py
git commit -m "feat(features): build_features orchestrator + date-window slicing"
```

---

### Task 5: `api/schemas.py` — response models

**Files:**
- Modify: `stock_data/api/schemas.py` (replace the two batch-profile model blocks, lines ~1596-1832)
- Test: `tests/test_agent_batch_features.py`

**Interfaces:**
- Consumes: Pydantic v2 (`BaseModel`, `Field`, `Literal`).
- Produces: new models `MinimalQuote`, `TrendFeatures`, `SwingPoint`, `PendingSwing`, `PivotFeatures`, `ZAnomalyBar`, `VolumeFeatures`, `BatchFeatures`; rewritten `IndexProfile`, `IndicesBatchProfileResponse`, `StockBatchProfileEntry`, `StockBatchProfileRequest`, `StockBatchProfileResponse`. `StockBatchAspectError` keeps `aspect: str`.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_agent_batch_features.py`:

```python
from stock_data.api.schemas import BatchFeatures, MinimalQuote


class TestSchemas:
    def test_batch_features_roundtrip(self):
        m = BatchFeatures(
            trend={
                "ma": {"ma5": 1.0},
                "ma_change": {"ma5": 0.5},
                "adx": 20.0,
                "pdi": 10.0,
                "mdi": 8.0,
                "rsi": {"rsi_6": 50.0},
                "boll": {"mid": 1.0, "upper": 2.0, "lower": 0.0, "bandwidth": 1.0},
            },
            pivots={
                "window_high": {"price": 2.0, "date": "2026-08-10"},
                "window_low": {"price": 1.0, "date": "2026-07-15"},
                "max_vol_bar": None,
                "swings": [{"date": "2026-07-15", "type": "low", "price": 1.0, "confirmed": True}],
                "pending": {"side": "high", "bars": 2, "price": 2.0, "date": "2026-08-10"},
                "params": {"pivot_window": 2},
            },
            volume={
                "latest_volume": 100.0,
                "vol_ratio_5": 1.5,
                "z_anomalies": [
                    {
                        "date": "2026-08-10",
                        "open": 1.0,
                        "high": 2.0,
                        "low": 0.5,
                        "close": 1.5,
                        "volume": 100.0,
                        "z_score": 3.0,
                        "direction": "up",
                        "change_pct": 5.0,
                    }
                ],
            },
        )
        d = m.model_dump()
        assert d["pivots"]["swings"][0]["type"] == "low"
        assert d["volume"]["z_anomalies"][0]["direction"] == "up"

    def test_minimal_quote(self):
        q = MinimalQuote(price=1721.0, change_pct=1.2)
        assert q.model_dump() == {"price": 1721.0, "change_pct": 1.2}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_agent_batch_features.py::TestSchemas -v`
Expected: FAIL with `ImportError: cannot import name 'BatchFeatures' from 'stock_data.api.schemas'`.

- [ ] **Step 3: Implement the models**

In `stock_data/api/schemas.py`, **replace TWO disjoint blocks** — the market-context models between them (`MarketSession` / `MarketContext*`, ~lines 1657-1757) MUST be preserved:

- **Block A** — from the `# Agent indices batch-profile` comment (~1595) through the end of `IndicesBatchProfileResponse` (~1654): replace with the shared feature models + new indices models below.
- **Block B** — from the `# Agent stocks batch-profile` comment (~1761) through the end of `StockBatchProfileResponse` (~1832): replace with the stocks models below.

Do **not** touch the market-context models between the two blocks (agent.py imports `MarketContextResponse` etc. — deleting them breaks the whole agent module). The models below are shown as one block for readability; the implementer splits them at the two `--- indices` / `--- stocks` section markers:

```python
# ---------------------------------------------------------------------------
# Agent batch-profile computed features (replaces raw K-line bars).
# Spec: docs/superpowers/specs/2026-08-27-agent-batch-profile-features-design.md
# ---------------------------------------------------------------------------


class MinimalQuote(BaseModel):
    """极简当前价锚点 (price + change_pct)."""

    price: float | None = None
    change_pct: float | None = None


class TrendFeatures(BaseModel):
    """Trend block — MA latest + 1-bar change + DMI/RSI/BOLL latest."""

    ma: dict[str, float | None] = Field(default_factory=dict)
    ma_change: dict[str, float | None] = Field(default_factory=dict)
    adx: float | None = None
    pdi: float | None = None
    mdi: float | None = None
    rsi: dict[str, float | None] = Field(default_factory=dict)
    boll: dict[str, float | None] = Field(default_factory=dict)


class SwingPoint(BaseModel):
    """One confirmed pivot (a chart-visible top or bottom)."""

    date: str
    type: Literal["high", "low"]
    price: float
    confirmed: bool = True


class PendingSwing(BaseModel):
    """The in-flight (not yet confirmed) extreme."""

    side: Literal["high", "low"]
    bars: int
    price: float
    date: str


class PivotFeatures(BaseModel):
    """Top/bottom block — window stats + ZigZag swings + pending."""

    window_high: dict | None = None
    window_low: dict | None = None
    max_vol_bar: dict | None = None
    swings: list[SwingPoint] = Field(default_factory=list)
    pending: PendingSwing | None = None
    params: dict = Field(default_factory=dict)


class ZAnomalyBar(BaseModel):
    """One volume Z-score anomaly bar (z > 2 in the requested window)."""

    date: str
    open: float | None = None
    high: float | None = None
    low: float | None = None
    close: float | None = None
    volume: float | None = None
    z_score: float
    direction: Literal["up", "down"]
    change_pct: float | None = None


class VolumeFeatures(BaseModel):
    """Volume block — latest volume + 5-bar ratio + Z anomalies."""

    latest_volume: float | None = None
    vol_ratio_5: float | None = None
    z_anomalies: list[ZAnomalyBar] = Field(default_factory=list)


class BatchFeatures(BaseModel):
    """The three feature blocks for one code at one frequency."""

    trend: TrendFeatures = Field(default_factory=TrendFeatures)
    pivots: PivotFeatures = Field(default_factory=PivotFeatures)
    volume: VolumeFeatures = Field(default_factory=VolumeFeatures)


# --- indices /batch-profile ------------------------------------------------

class IndexProfile(BaseModel):
    """One index in /agent/indices/batch-profile."""

    code: str
    name: str = Field(default="", description="Index name (from index_symbols map or upstream)")
    quote: MinimalQuote | None = Field(default=None, description="极简实时价锚点; null when upstream failed.")
    features: BatchFeatures | None = Field(default=None, description="Computed trend/pivots/volume.")
    errors: dict[str, str | None] = Field(
        default_factory=dict,
        description="Quote / features error map; null = ok.",
    )


class IndicesBatchProfileResponse(BaseModel):
    """GET response for /agent/indices/batch-profile."""

    frequency: str = "d"
    days: int = 0
    indices: list[IndexProfile] = Field(default_factory=list)
    summary: dict = Field(default_factory=dict)


# --- stocks /batch-profile -------------------------------------------------

class StockBatchAspectError(BaseModel):
    """Per-aspect failure in /agent/stocks/batch-profile."""

    aspect: str = Field(description="Aspect name (quote/features/info/boards)")
    error: str = Field(description="Error class name (e.g. DataFetchError)")
    message: str = Field(default="", description="Underlying error message")


class StockBatchProfileEntry(BaseModel):
    """One stock in /agent/stocks/batch-profile."""

    code: str
    name: str = Field(default="", description="Stock name (from quote when available).")
    ok: bool = Field(default=True, description="True unless the whole entry is irrecoverable.")
    quote: MinimalQuote | None = Field(default=None)
    features: BatchFeatures | None = Field(default=None)
    info: dict | None = Field(default=None, description="{source, data} company profile.")
    boards: dict | None = Field(default=None, description="{source, data} board memberships.")
    errors: list[StockBatchAspectError] = Field(default_factory=list)


class StockBatchProfileRequest(BaseModel):
    """POST body for /agent/stocks/batch-profile."""

    codes: list[str] = Field(
        ...,
        min_length=1,
        max_length=5,
        description="Stock codes (1-5). Hard cap matches the stock-picking funnel.",
    )
    frequency: Literal["d", "w", "m", "1m", "5m", "15m", "30m", "60m"] = "d"
    days: int | None = Field(default=None, ge=2, description="Calendar days; per-frequency max validated in the route.")


class StockBatchProfileResponse(BaseModel):
    """POST response for /agent/stocks/batch-profile."""

    frequency: str = "d"
    days: int = 0
    results: list[StockBatchProfileEntry] = Field(default_factory=list)
    summary: dict = Field(default_factory=dict)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/test_agent_batch_features.py::TestSchemas -v`
Expected: PASS.

- [ ] **Step 5: Run the full test suite to catch import breaks**

Run: `.venv/Scripts/python.exe -m pytest tests/test_agent_endpoints.py -x -q`
Expected: the existing agent tests that still reference `aspects` / `klines` FAIL — that is expected (Task 7/8 rewrite them). They are fine to remain red until Task 7/8; do **not** fix them here.

- [ ] **Step 6: Commit**

```bash
git add stock_data/api/schemas.py tests/test_agent_batch_features.py
git commit -m "feat(schemas): batch-profile feature response models (trend/pivots/volume)"
```

---

### Task 6: `api/cache.py` — cache key builders

**Files:**
- Modify: `stock_data/api/cache.py` (`make_indices_batch_profile_cache_key` at ~508, `make_stocks_batch_profile_cache_key` at ~529)
- Test: `tests/test_agent_batch_features.py`

**Interfaces:**
- Produces: `make_indices_batch_profile_cache_key(codes, frequency, days) -> str`, `make_stocks_batch_profile_cache_key(codes, frequency, days) -> str` — both `f"agent_<label>:{frequency}:{days}:" + ",".join(sorted(codes))`.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_agent_batch_features.py`:

```python
from stock_data.api.cache import make_indices_batch_profile_cache_key, make_stocks_batch_profile_cache_key


class TestCacheKeys:
    def test_indices_key_includes_freq_and_days(self):
        a = make_indices_batch_profile_cache_key(["000001", "399001"], "d", 60)
        b = make_indices_batch_profile_cache_key(["399001", "000001"], "d", 60)  # order-immune
        c = make_indices_batch_profile_cache_key(["000001", "399001"], "d", 120)  # different days
        assert a == b
        assert a != c
        assert "d:60" in a

    def test_stocks_key_includes_freq_and_days(self):
        a = make_stocks_batch_profile_cache_key(["600519", "000858"], "5m", 5)
        assert "5m:5" in a
        assert "600519" in a and "000858" in a
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_agent_batch_features.py::TestCacheKeys -v`
Expected: FAIL (signature mismatch — the builders still take `aspects` / no freq).

- [ ] **Step 3: Update the builders**

Replace the two builders in `stock_data/api/cache.py`:

```python
def make_indices_batch_profile_cache_key(codes: list[str], frequency: str, days: int) -> str:
    """Cache key for GET /agent/indices/batch-profile.

    Codes are SORTED so the same set in different input order collapses
    to one cache entry (the response is reordered to the input order on
    hit). `frequency` + `days` are part of the key because the features
    differ per (frequency, days) pair.
    """
    return f"agent_indices_batch_profile:{frequency}:{days}:" + ",".join(sorted(codes))


def make_stocks_batch_profile_cache_key(codes: list[str], frequency: str, days: int) -> str:
    """Cache key for POST /agent/stocks/batch-profile.

    Same sorting + (frequency, days) inclusion contract as the indices
    variant.
    """
    return f"agent_stocks_batch_profile:{frequency}:{days}:" + ",".join(sorted(codes))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/test_agent_batch_features.py::TestCacheKeys -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add stock_data/api/cache.py tests/test_agent_batch_features.py
git commit -m "feat(cache): batch-profile keys include (frequency, days)"
```

---

### Task 7: rewrite `post_stocks_batch_profile` route

**Files:**
- Modify: `stock_data/api/routes/agent.py`
- Test: `tests/test_agent_batch_features.py`

**Interfaces:**
- Consumes: `get_manager()` (helpers.py), `build_features` (features/build), `MinimalQuote` + new schemas, `make_stocks_batch_profile_cache_key`, `stock_board_cache.get_stock_memberships`, `_render_agent`, `_batch_summary`, `_reorder_by_code`.
- Produces: the rewritten `post_stocks_batch_profile` returning `StockBatchProfileResponse` with `quote / features / info / boards` per entry. Adds module constants `_FEATURE_FREQ_DAYS_RANGE`, `_FEATURE_FREQ_DEFAULT_DAYS`, `_FEATURE_MA60_WARMUP_DAYS` and helper `_resolve_and_validate_days(frequency, days) -> int` (used by both routes).

- [ ] **Step 1: Write the failing test**

Append to `tests/test_agent_batch_features.py`:

```python
from unittest.mock import MagicMock

from stock_data.api.routes import agent as agent_module
from stock_data.data_provider.base import DataFetchError
from stock_data.data_provider.core.types import RealtimeSource, UnifiedRealtimeQuote

_BOARD_STOCKS_PATCH = "stock_data.data_provider.persistence.board.get_stock_memberships"


def _make_unified_quote(code, price=100.0):
    return UnifiedRealtimeQuote(
        code=code, name=code, source=RealtimeSource.AKSHARE, price=price,
        change_pct=1.5, change_amount=1.5, open_price=99.0, high=101.0,
        low=98.5, pre_close=98.5, volume=1_000_000, amount=1e8,
    )


def _bind_manager(monkeypatch, mock_manager):
    monkeypatch.setattr(agent_module, "get_manager", lambda: mock_manager)
    return mock_manager


def _stock_request(codes, frequency="d", days=None):
    body = {"codes": codes, "frequency": frequency}
    if days is not None:
        body["days"] = days
    return body


class TestStocksBatchProfile:
    def test_all_aspects_populated(self, client, monkeypatch):
        mock_manager = MagicMock()
        mock_manager.get_realtime_quote.return_value = _make_unified_quote("600519")
        mock_manager.get_kline_data.return_value = (_make_kline_df(120, spike_idx=(80,)), "zzshare")
        mock_manager.get_stock_info.return_value = ({"industry": "白酒"}, "zhitu")
        _bind_manager(monkeypatch, mock_manager)
        with patch(_BOARD_STOCKS_PATCH, return_value=([{"code": "885595", "name": "白酒"}], False, "persistence")):
            resp = client.post(
                "/api/v1/agent/stocks/batch-profile",
                json=_stock_request(["600519"], frequency="d", days=60),
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["frequency"] == "d" and data["days"] == 60
        e = data["results"][0]
        assert e["quote"] == {"price": 100.0, "change_pct": 1.5}
        assert e["features"]["trend"]["ma"]["ma60"] is not None
        assert e["features"]["pivots"]["window_high"] is not None
        assert e["features"]["volume"]["latest_volume"] is not None
        assert e["info"]["data"]["industry"] == "白酒"
        assert e["boards"]["data"][0]["code"] == "885595"
        assert e["ok"] is True
        assert e["errors"] == []

    def test_kline_failure_isolated(self, client, monkeypatch):
        mock_manager = MagicMock()
        mock_manager.get_realtime_quote.return_value = _make_unified_quote("600519")
        mock_manager.get_kline_data.side_effect = DataFetchError("kline upstream down")
        mock_manager.get_stock_info.return_value = ({"industry": "白酒"}, "zhitu")
        _bind_manager(monkeypatch, mock_manager)
        with patch(_BOARD_STOCKS_PATCH, return_value=([], False, "persistence")):
            resp = client.post(
                "/api/v1/agent/stocks/batch-profile", json=_stock_request(["600519"])
            )
        data = resp.json()
        e = data["results"][0]
        assert e["features"] is None
        assert e["quote"] is not None
        assert any(err["aspect"] == "features" for err in e["errors"])

    def test_passes_adjust_qfq_and_converts_minute_freq_for_manager(self, client, monkeypatch):
        mock_manager = MagicMock()
        mock_manager.get_realtime_quote.return_value = _make_unified_quote("600519")
        mock_manager.get_kline_data.return_value = (_make_kline_df(120), "zzshare")
        mock_manager.get_stock_info.return_value = ({"industry": "白酒"}, "zhitu")
        _bind_manager(monkeypatch, mock_manager)
        with patch(_BOARD_STOCKS_PATCH, return_value=([], False, "persistence")):
            client.post(
                "/api/v1/agent/stocks/batch-profile",
                json=_stock_request(["600519"], frequency="5m", days=3),
            )
        kwargs = mock_manager.get_kline_data.call_args.kwargs
        assert kwargs["adjust"] == "qfq"
        assert kwargs["asset"] == "stock"
        assert kwargs["frequency"] == "5"  # public "5m" -> manager "5"

    def test_days_out_of_range_422(self, client, monkeypatch):
        _bind_manager(monkeypatch, MagicMock())
        resp = client.post(
            "/api/v1/agent/stocks/batch-profile",
            json=_stock_request(["600519"], frequency="5m", days=99),
        )
        assert resp.status_code == 422

    def test_cache_second_call_skips_manager(self, client, monkeypatch):
        mock_manager = MagicMock()
        mock_manager.get_realtime_quote.return_value = _make_unified_quote("600519")
        mock_manager.get_kline_data.return_value = (_make_kline_df(120), "zzshare")
        mock_manager.get_stock_info.return_value = ({"industry": "白酒"}, "zhitu")
        _bind_manager(monkeypatch, mock_manager)
        with patch(_BOARD_STOCKS_PATCH, return_value=([], False, "persistence")):
            client.post("/api/v1/agent/stocks/batch-profile", json=_stock_request(["600519"], days=60))
            client.post("/api/v1/agent/stocks/batch-profile", json=_stock_request(["600519"], days=60))
        assert mock_manager.get_kline_data.call_count == 1
```

Note: add `from unittest.mock import patch` at the top of the test file if not already imported.

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_agent_batch_features.py::TestStocksBatchProfile -v`
Expected: FAIL (route still uses old `aspects` contract; `StockBatchProfileRequest` rejects the new body shape or route errors).

- [ ] **Step 3: Implement the rewritten route + helpers**

In `stock_data/api/routes/agent.py`:

(a) Update imports — replace `IndexKlineBlock, IndexProfile, IndicesBatchProfileResponse, StockBatchAspect, StockBatchProfileEntry, StockBatchProfileRequest, StockBatchProfileResponse, StockQuote` with the new names (`MinimalQuote, BatchFeatures, IndexProfile, IndicesBatchProfileResponse, StockBatchProfileEntry, StockBatchProfileRequest, StockBatchProfileResponse`). Add `from ...data_provider.features.build import build_features` and `from ..schemas import (... MinimalQuote ...)`.

(b) **Delete** `_INDICES_KLINE_DAYS`, `_STOCK_ASPECT_DISPATCH`, `_PERSISTENCE_ROUTED_ASPECTS` and `_serialize_stock_aspect_value`.

(c) Add module-level feature constants + day-resolution helper (place near the top, after `_DEFAULT_CORE_CSI_INDICES`):

```python
# Per-frequency (frequency -> (min, max)) calendar-day range for the
# batch-profile feature endpoints. Mirrors correlation/matrix with the
# minute caps enlarged per user decision (5m 3->5, 15m 5->8, 30m 10->15,
# 60m 20->30).
_FEATURE_FREQ_DAYS_RANGE: dict[str, tuple[int, int]] = {
    "d": (2, 365), "w": (14, 1095), "m": (60, 1825),
    "1m": (2, 3), "5m": (2, 5), "15m": (2, 8), "30m": (2, 15), "60m": (2, 30),
}
_FEATURE_FREQ_DEFAULT_DAYS: dict[str, int] = {
    "d": 60, "w": 156, "m": 365, "1m": 3, "5m": 5, "15m": 8, "30m": 15, "60m": 30,
}
# Calendar days needed to warm MA60 (60 bars) for d/w/m. Minute frames are
# already warm inside their bounded day windows (240+ bars), so no bump.
_FEATURE_MA60_WARMUP_DAYS: dict[str, int] = {"d": 90, "w": 420, "m": 1825}

# Public frequency string -> manager/fetcher-internal frequency code.
# Fetchers only accept bare minute codes ("5", not "5m") — this is the
# same mapping the /kline route applies via helpers._period_to_freq.
_FREQ_TO_MGR: dict[str, str] = {
    "d": "d", "w": "w", "m": "m",
    "1m": "1", "5m": "5", "15m": "15", "30m": "30", "60m": "60",
}


def _resolve_and_validate_days(frequency: str, days: int | None) -> int:
    """Apply the per-frequency default then 422 if outside the range."""
    lo, hi = _FEATURE_FREQ_DAYS_RANGE[frequency]
    resolved = days if days is not None else _FEATURE_FREQ_DEFAULT_DAYS[frequency]
    if not (lo <= resolved <= hi):
        raise HTTPException(
            status_code=422,
            detail={"error": "invalid_request", "message": f"days must be an int in [{lo}, {hi}] for frequency={frequency}"},
        )
    return resolved
```

(d) Replace the entire `post_stocks_batch_profile` body (keep the decorators; update the `@endpoint_meta` summary):

```python
@router.post(
    "/agent/stocks/batch-profile",
    response_model=StockBatchProfileResponse,
    responses={
        400: {"model": ErrorResponse, "description": "Invalid request (codes out of range)"},
        422: {"model": ErrorResponse, "description": "days out of range / unsupported frequency"},
        500: {"model": ErrorResponse, "description": "Server error"},
    },
    tags=["agent"],
)
@endpoint_meta(
    summary="股票批量画像（trend/pivots/volume 计算指标 + 极简 quote + info + boards）",
    markets=["csi"],
    capabilities=[],
)
@map_errors
def post_stocks_batch_profile(
    payload: StockBatchProfileRequest,
    format: str = Query(
        "json",
        pattern="^(json|md)$",
        description="Output format. json=application/json (default); md=text/markdown.",
    ),
) -> Response:
    """Per-code fan-out across quote / features / info / boards.

    ``features`` replaces the old raw kline / kline_5m aspects: the
    server computes trend / pivots / volume at the requested
    (frequency, days) instead of returning raw bars. Per-aspect failures
    live in ``results[i].errors[]``; the entry is only ``ok=False`` when
    every aspect failed.
    """
    days = _resolve_and_validate_days(payload.frequency, payload.days)
    cache_key = make_stocks_batch_profile_cache_key(payload.codes, payload.frequency, days)
    hit = cached_lookup(get_quote_cache, cache_key, "agent_stocks_batch_profile")
    if hit is not None:
        return _render_agent(
            "stocks/batch-profile",
            _reorder_by_code(hit, payload.codes, "results"),
            format,
        )

    started = time.monotonic()
    manager = get_manager()
    fetch_days = max(days, _FEATURE_MA60_WARMUP_DAYS.get(payload.frequency, days))
    results: list[StockBatchProfileEntry] = []
    n_ok = 0

    for code in payload.codes:
        errors: list[StockBatchAspectError] = []
        quote = None
        features = None
        info = None
        boards = None

        try:
            q = manager.get_realtime_quote(code)
            if q is not None:
                quote = MinimalQuote(price=q.price, change_pct=q.change_pct)
        except Exception as exc:
            logger.warning(f"[agent/stocks/batch-profile] {code} quote failed: {exc}")
            errors.append(StockBatchAspectError(aspect="quote", error=type(exc).__name__, message=str(exc)))

        try:
            df, _src = manager.get_kline_data(
                code,
                days=fetch_days,
                frequency=_FREQ_TO_MGR[payload.frequency],
                adjust="qfq",
                asset="stock",
            )
            features = BatchFeatures(**build_features(df, frequency=payload.frequency, days=days))
        except Exception as exc:
            logger.warning(f"[agent/stocks/batch-profile] {code} features failed: {exc}", exc_info=True)
            errors.append(StockBatchAspectError(aspect="features", error=type(exc).__name__, message=str(exc)))

        try:
            info_dict, info_src = manager.get_stock_info(code)
            info = {"source": info_src, "data": info_dict}
        except Exception as exc:
            logger.warning(f"[agent/stocks/batch-profile] {code} info failed: {exc}")
            errors.append(StockBatchAspectError(aspect="info", error=type(exc).__name__, message=str(exc)))

        try:
            entries, _cold, _origin = stock_board_cache.get_stock_memberships(
                stock_code=code, sources=["ths"], manager=manager
            )
            boards = {"source": "persistence", "data": entries}
        except Exception as exc:
            logger.warning(f"[agent/stocks/batch-profile] {code} boards failed: {exc}")
            errors.append(StockBatchAspectError(aspect="boards", error=type(exc).__name__, message=str(exc)))

        name = quote.name if quote is not None and getattr(quote, "name", None) else ""
        ok = any(v is not None for v in (quote, features, info, boards))
        if ok:
            n_ok += 1
        results.append(
            StockBatchProfileEntry(
                code=code,
                name=name,
                ok=ok,
                quote=quote,
                features=features,
                info=info,
                boards=boards,
                errors=errors,
            )
        )

    resp = StockBatchProfileResponse(
        frequency=payload.frequency,
        days=days,
        results=results,
        summary=_batch_summary(len(payload.codes), n_ok, started),
    )
    cached_store(get_quote_cache, cache_key, resp)
    return _render_agent("stocks/batch-profile", resp, format)
```

Note: `MinimalQuote` has no `name` field — the `name` resolution above reads `quote.name` off the `UnifiedRealtimeQuote` `q`. To keep it correct, capture the name inside the quote try-block:

```python
        try:
            q = manager.get_realtime_quote(code)
            if q is not None:
                quote = MinimalQuote(price=q.price, change_pct=q.change_pct)
                name = getattr(q, "name", "") or ""
            else:
                name = ""
        except Exception as exc:
            ...
            name = ""
```

and drop the `name = quote.name ...` line. (The implementer picks the cleaner of the two — the key contract is `name` defaults to `""` when unavailable.)

- [ ] **Step 4: Run the new tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_agent_batch_features.py::TestStocksBatchProfile -v`
Expected: PASS (5 tests).

- [ ] **Step 5: Run the full agent test file — expect only the OLD batch-profile tests to fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_agent_endpoints.py -q 2>&1 | tail -20`
Expected: the old `TestIndicesBatchProfile` / `TestStocksBatchProfile` / `TestFormatMd::test_*_batch_profile_*` / `TestPhase2DefensiveGuards` batch-profile tests FAIL (they assert the old shape). Other suites (market-context, overlap, filter-stocks, market-stats) PASS. These old tests are **deleted** in Task 9. Do not fix them here.

- [ ] **Step 6: Commit**

```bash
git add stock_data/api/routes/agent.py tests/test_agent_batch_features.py
git commit -m "feat(agent): rewrite stocks/batch-profile to computed features"
```

---

### Task 8: rewrite `get_indices_batch_profile` route

**Files:**
- Modify: `stock_data/api/routes/agent.py`
- Test: `tests/test_agent_batch_features.py`

**Interfaces:**
- Consumes: same constants/helpers from Task 7; `manager.get_index_realtime_quote`, `manager.get_kline_data(..., asset="index", adjust=None)`, `_resolve_index_name`, `_index_quote_from` (no longer used — removed), `make_indices_batch_profile_cache_key`.
- Produces: rewritten `get_indices_batch_profile` returning `IndicesBatchProfileResponse` (single `frequency`, per-index `quote` + `features`).

- [ ] **Step 1: Write the failing test**

Append to `tests/test_agent_batch_features.py`:

```python
class TestIndicesBatchProfile:
    def test_default_3_indices_features(self, client, monkeypatch):
        mock_manager = MagicMock()
        mock_manager.get_index_realtime_quote.return_value = _make_unified_quote("000001")
        mock_manager.get_kline_data.return_value = (_make_kline_df(120, spike_idx=(80,)), "akshare")
        _bind_manager(monkeypatch, mock_manager)

        resp = client.get("/api/v1/agent/indices/batch-profile")
        assert resp.status_code == 200
        data = resp.json()
        assert data["frequency"] == "d"
        assert data["summary"]["requested"] == 3 and data["summary"]["ok"] == 3
        first = data["indices"][0]
        assert first["quote"]["price"] == 100.0
        assert set(first["features"].keys()) == {"trend", "pivots", "volume"}
        assert first["features"]["trend"]["ma"]["ma60"] is not None

    def test_frequency_and_days_echoed(self, client, monkeypatch):
        mock_manager = MagicMock()
        mock_manager.get_index_realtime_quote.return_value = _make_unified_quote("000001")
        mock_manager.get_kline_data.return_value = (_make_kline_df(120), "akshare")
        _bind_manager(monkeypatch, mock_manager)
        resp = client.get(
            "/api/v1/agent/indices/batch-profile?codes=000001&frequency=5m&days=3"
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["frequency"] == "5m" and data["days"] == 3

    def test_index_fetch_no_adjust_and_converts_minute_freq(self, client, monkeypatch):
        mock_manager = MagicMock()
        mock_manager.get_index_realtime_quote.return_value = _make_unified_quote("000001")
        mock_manager.get_kline_data.return_value = (_make_kline_df(120), "akshare")
        _bind_manager(monkeypatch, mock_manager)
        client.get("/api/v1/agent/indices/batch-profile?codes=000001&frequency=5m&days=3")
        kwargs = mock_manager.get_kline_data.call_args.kwargs
        assert kwargs["adjust"] is None
        assert kwargs["asset"] == "index"
        assert kwargs["frequency"] == "5"  # public "5m" -> manager "5"

    def test_out_of_range_days_422(self, client, monkeypatch):
        _bind_manager(monkeypatch, MagicMock())
        resp = client.get("/api/v1/agent/indices/batch-profile?frequency=d&days=9999")
        assert resp.status_code == 422

    def test_unsupported_frequency_422(self, client, monkeypatch):
        _bind_manager(monkeypatch, MagicMock())
        resp = client.get("/api/v1/agent/indices/batch-profile?frequency=xy&days=30")
        assert resp.status_code == 422

    def test_quote_failure_isolated_features_still_served(self, client, monkeypatch):
        mock_manager = MagicMock()

        def quote_side(code):
            if code == "000001":
                raise DataFetchError("quote upstream down")
            return _make_unified_quote(code)

        mock_manager.get_index_realtime_quote.side_effect = quote_side
        mock_manager.get_kline_data.return_value = (_make_kline_df(120), "akshare")
        _bind_manager(monkeypatch, mock_manager)
        resp = client.get("/api/v1/agent/indices/batch-profile?codes=000001,399001")
        data = resp.json()
        assert data["summary"]["ok"] == 1
        failed = next(p for p in data["indices"] if p["code"] == "000001")
        assert failed["quote"] is None
        assert failed["features"] is not None
        assert failed["errors"]["quote"] is not None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_agent_batch_features.py::TestIndicesBatchProfile -v`
Expected: FAIL (route still returns the old `klines` shape).

- [ ] **Step 3: Implement the rewritten route**

In `stock_data/api/routes/agent.py`, replace the entire `get_indices_batch_profile` body (keep decorators; update summary):

```python
@router.get(
    "/agent/indices/batch-profile",
    response_model=IndicesBatchProfileResponse,
    responses={
        422: {"model": ErrorResponse, "description": "days out of range / unsupported frequency"},
        500: {"model": ErrorResponse, "description": "Server error"},
    },
    tags=["agent"],
)
@endpoint_meta(
    summary="指数批量画像（trend/pivots/volume 计算指标 + 极简 quote，单 frequency）",
    markets=["csi"],
    capabilities=[],
)
@map_errors
def get_indices_batch_profile(
    codes: str | None = Query(
        default=None,
        description=(
            "Comma-separated index codes (1-5). Empty = 3 core CSI indices "
            "(上证/深证/创业板). Each code is fanned out to a minimal quote "
            "+ computed features at the requested (frequency, days)."
        ),
    ),
    frequency: str = Query("d", description="One of d/w/m/1m/5m/15m/30m/60m"),
    days: int | None = Query(default=None, ge=2, description="Calendar days; per-frequency max validated server-side."),
    format: str = Query(
        "json",
        pattern="^(json|md)$",
        description="Output format. json=application/json (default); md=text/markdown.",
    ),
) -> Response:
    """Per-index fan-out: minimal quote + computed features at one frequency."""
    if frequency not in _FEATURE_FREQ_DAYS_RANGE:
        raise HTTPException(
            status_code=422,
            detail={"error": "invalid_request", "message": f"unsupported frequency: {frequency}"},
        )
    days = _resolve_and_validate_days(frequency, days)
    code_list = [
        c.strip() for c in (codes.split(",") if codes else _DEFAULT_CORE_CSI_INDICES) if c.strip()
    ] or list(_DEFAULT_CORE_CSI_INDICES)
    if len(code_list) > 5:
        raise HTTPException(status_code=422, detail={"error": "invalid_request", "message": "codes must be 1-5"})

    cache_key = make_indices_batch_profile_cache_key(code_list, frequency, days)
    hit = cached_lookup(get_quote_cache, cache_key, "agent_indices_batch_profile")
    if hit is not None:
        return _render_agent(
            "indices/batch-profile", _reorder_by_code(hit, code_list, "indices"), format
        )

    started = time.monotonic()
    manager = get_manager()
    fetch_days = max(days, _FEATURE_MA60_WARMUP_DAYS.get(frequency, days))
    profiles: list[IndexProfile] = []
    n_ok = 0

    for code in code_list:
        errors: dict[str, str | None] = {"quote": None, "features": None}
        quote = None
        features = None

        try:
            q = manager.get_index_realtime_quote(code)
            if q is None:
                errors["quote"] = "no fetcher could serve realtime quote"
            else:
                quote = MinimalQuote(price=q.price, change_pct=q.change_pct)
        except (DataFetchError, ValueError) as exc:
            logger.warning(f"[agent/indices/batch-profile] quote {code} failed: {exc}")
            errors["quote"] = str(exc)

        try:
            df, _src = manager.get_kline_data(
                code,
                days=fetch_days,
                frequency=_FREQ_TO_MGR[frequency],
                adjust=None,
                asset="index",
            )
            features = BatchFeatures(**build_features(df, frequency=frequency, days=days))
        except Exception as exc:
            logger.warning(
                f"[agent/indices/batch-profile] kline {code} {frequency} failed: {exc}",
                exc_info=True,
            )
            errors["features"] = f"{type(exc).__name__}: {exc}"

        if quote is not None and features is not None:
            n_ok += 1
        profiles.append(
            IndexProfile(
                code=code,
                name=_resolve_index_name(code),
                quote=quote,
                features=features,
                errors=errors,
            )
        )

    result = IndicesBatchProfileResponse(
        frequency=frequency,
        days=days,
        indices=profiles,
        summary=_batch_summary(len(code_list), n_ok, started),
    )
    cached_store(get_quote_cache, cache_key, result)
    return _render_agent("indices/batch-profile", result, format)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/test_agent_batch_features.py::TestIndicesBatchProfile -v`
Expected: PASS (6 tests).

- [ ] **Step 5: Commit**

```bash
git add stock_data/api/routes/agent.py tests/test_agent_batch_features.py
git commit -m "feat(agent): rewrite indices/batch-profile to single-frequency computed features"
```

---

### Task 9: MD renderers + delete dead code + prune old tests

**Files:**
- Modify: `stock_data/api/routes/agent.py` (`render_indices_batch_profile_as_md`, `render_stocks_batch_profile_as_md`, remove `_md_kline_rows`)
- Modify: `tests/test_agent_endpoints.py` (delete the now-invalid batch-profile tests)
- Test: `tests/test_agent_batch_features.py` (new MD tests)

**Interfaces:**
- Consumes: the new response models from Task 5.
- Produces: rewritten `render_indices_batch_profile_as_md(p)` / `render_stocks_batch_profile_as_md(p)`; `_MD_TEMPLATES` unchanged.

- [ ] **Step 1: Write the failing MD test**

Append to `tests/test_agent_batch_features.py`:

```python
class TestFormatMdFeatures:
    def _stub_features_response(self):
        from stock_data.api.schemas import BatchFeatures

        features = BatchFeatures(
            trend={"ma": {"ma5": 1.0}, "ma_change": {"ma5": 0.1}, "adx": 20.0, "pdi": 10.0,
                   "mdi": 8.0, "rsi": {"rsi_6": 50.0}, "boll": {"mid": 1.0, "upper": 2.0, "lower": 0.0, "bandwidth": 1.0}},
            pivots={"window_high": {"price": 2.0, "date": "2026-08-10"}, "window_low": {"price": 1.0, "date": "2026-07-15"},
                    "max_vol_bar": None,
                    "swings": [{"date": "2026-07-15", "type": "low", "price": 1.0, "confirmed": True}],
                    "pending": {"side": "high", "bars": 2, "price": 2.0, "date": "2026-08-10"},
                    "params": {"pivot_window": 2, "reversal_atr_mult": 1.0, "atr_period": 14}},
            volume={"latest_volume": 100.0, "vol_ratio_5": 1.5,
                    "z_anomalies": [{"date": "2026-08-10", "open": 1.0, "high": 2.0, "low": 0.5,
                                     "close": 1.5, "volume": 100.0, "z_score": 3.0,
                                     "direction": "up", "change_pct": 5.0}]},
        )
        return features

    def test_indices_batch_profile_md(self, client, monkeypatch):
        mock_manager = MagicMock()
        mock_manager.get_index_realtime_quote.return_value = _make_unified_quote("000001")
        mock_manager.get_kline_data.return_value = (_make_kline_df(120), "akshare")
        _bind_manager(monkeypatch, mock_manager)
        resp = client.get("/api/v1/agent/indices/batch-profile?format=md")
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("text/markdown")
        body = resp.text
        assert "# 指数批量画像" in body
        assert "trend" in body and "pivots" in body and "volume" in body

    def test_stocks_batch_profile_md(self, client, monkeypatch):
        mock_manager = MagicMock()
        mock_manager.get_realtime_quote.return_value = _make_unified_quote("600519")
        mock_manager.get_kline_data.return_value = (_make_kline_df(120), "zzshare")
        mock_manager.get_stock_info.return_value = ({"industry": "白酒"}, "zhitu")
        _bind_manager(monkeypatch, mock_manager)
        with patch(_BOARD_STOCKS_PATCH, return_value=([], False, "persistence")):
            resp = client.post(
                "/api/v1/agent/stocks/batch-profile?format=md",
                json=_stock_request(["600519"]),
            )
        assert resp.status_code == 200
        assert "趋势" in resp.text or "trend" in resp.text
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_agent_batch_features.py::TestFormatMdFeatures -v`
Expected: FAIL (the renderers still reference the old `p.klines` / `entry.data` shapes and raise).

- [ ] **Step 3: Rewrite the two MD renderers**

In `stock_data/api/routes/agent.py`, replace `render_indices_batch_profile_as_md` and `render_stocks_batch_profile_as_md`, and delete `_md_kline_rows`:

```python
def _md_feature_block(out: list[str], f) -> None:
    """Render the three feature blocks of a BatchFeatures instance."""
    out.append("### 指标")
    out.append("**趋势**")
    _render_dict_block(out, "MA", f.trend.ma)
    _render_dict_block(out, "MA 环比变化 (%)", f.trend.ma_change)
    out.append(f"- ADX: {_md_num(f.trend.adx)} / PDI: {_md_num(f.trend.pdi)} / MDI: {_md_num(f.trend.mdi)}")
    out.append("")
    _render_dict_block(out, "RSI", f.trend.rsi)
    _render_dict_block(out, "BOLL", f.trend.boll)
    out.append("**顶底**")
    if f.pivots.window_high:
        out.append(f"- 区间最高: {_md_num(f.pivots.window_high.get('price'))} @ {f.pivots.window_high.get('date')}")
    if f.pivots.window_low:
        out.append(f"- 区间最低: {_md_num(f.pivots.window_low.get('price'))} @ {f.pivots.window_low.get('date')}")
    if f.pivots.max_vol_bar:
        out.append(f"- 最大量价: {_md_num(f.pivots.max_vol_bar.get('price'))} @ {f.pivots.max_vol_bar.get('date')} (量 {_md_num(f.pivots.max_vol_bar.get('volume'))})")
    out.append("| 日期 | 类型 | 价格 | 确认 |")
    out.append("|---|---|---|---|")
    for s in f.pivots.swings:
        out.append(f"| {s.date} | {s.type} | {_md_num(s.price)} | {'✓' if s.confirmed else '✗'} |")
    if f.pivots.pending:
        p = f.pivots.pending
        out.append(f"- 在途({p.side}): {_md_num(p.price)} @ {p.date} (bars_since {p.bars})")
    out.append("")
    out.append("**量价**")
    out.append(f"- 最新成交量: {_md_num(f.volume.latest_volume)} / 量比(5): {_md_num(f.volume.vol_ratio_5)}")
    if f.volume.z_anomalies:
        out.append("| 日期 | 收盘 | 成交量 | z | 方向 | 涨跌幅 |")
        out.append("|---|---|---|---|---|---|")
        for a in f.volume.z_anomalies:
            out.append(f"| {a.date} | {_md_num(a.close)} | {_md_num(a.volume)} | {_md_num(a.z_score)} | {a.direction} | {_md_pct(a.change_pct)} |")
    else:
        out.append("（无 z>2 放量异动）")
    out.append("")


def render_indices_batch_profile_as_md(p: IndicesBatchProfileResponse) -> str:
    out = [f"# 指数批量画像 — {p.frequency} {p.days}d", ""]
    for idx in p.indices:
        ok_marker = "✓" if idx.quote or idx.features else "✗"
        out.append(f"## {idx.code} {idx.name} {ok_marker}")
        if idx.quote:
            out.append(f"- 最新: {_md_num(idx.quote.price)} ({_md_pct(idx.quote.change_pct)})")
        else:
            out.append(f"- 行情失败: {(idx.errors or {}).get('quote') or 'no quote'}")
        out.append("")
        if idx.features:
            _md_feature_block(out, idx.features)
        else:
            out.append(f"### 指标 — 失败: {(idx.errors or {}).get('features') or 'no features'}")
            out.append("")
    s = p.summary or {}
    out.append(
        f"## 汇总 — requested {s.get('requested', '?')}, "
        f"ok {s.get('ok', '?')}, failed {s.get('failed', '?')}, "
        f"elapsed {s.get('elapsed_ms', '?')}ms"
    )
    return "\n".join(out)


def render_stocks_batch_profile_as_md(p: StockBatchProfileResponse) -> str:
    out = [f"# 股票批量画像 — {p.frequency} {p.days}d", ""]
    for entry in p.results:
        marker = "✓" if entry.ok and not entry.errors else ("△" if entry.ok else "✗")
        out.append(f"## {entry.code} {entry.name} {marker}")
        if entry.errors:
            failed = ", ".join(e.aspect for e in entry.errors)
            out.append(f"**失败 aspects**: {failed}")
        out.append("")
        if entry.quote:
            out.append(f"- 最新: {_md_num(entry.quote.price)} ({_md_pct(entry.quote.change_pct)})")
        out.append("")
        if entry.features:
            _md_feature_block(out, entry.features)
        if entry.info and entry.info.get("data"):
            out.append("### 公司画像")
            for k, v in entry.info["data"].items():
                out.append(f"- **{k}**: {v if v is not None else '—'}")
            out.append("")
        if entry.boards and entry.boards.get("data"):
            out.append("### 所属板块")
            for b in entry.boards["data"]:
                t = b.get("type") or "-"
                out.append(f"- {b.get('code', '?')} ({t}) {b.get('name', '')}")
            out.append("")
    s = p.summary or {}
    out.append(
        f"## 汇总 — requested {s.get('requested', '?')}, "
        f"ok {s.get('ok', '?')}, failed {s.get('failed', '?')}, "
        f"elapsed {s.get('elapsed_ms', '?')}ms"
    )
    return "\n".join(out)
```

- [ ] **Step 4: Prune the dead old tests in `tests/test_agent_endpoints.py`**

Delete the following test classes / methods (they assert the pre-refactor response shape):
- `TestIndicesBatchProfile` (whole class, lines ~719-907)
- `TestStocksBatchProfile` (whole class, lines ~1103-1337)
- `TestPhase2DefensiveGuards::test_indices_batch_profile_order_preserved_in_cache` and `test_stocks_batch_profile_aspects_empty_422` and `test_stocks_batch_profile_kline_passes_asset_stock` and `test_stocks_batch_profile_boards_uses_persistence_not_manager` (batch-profile-only methods)
- `TestFormatMd::test_indices_batch_profile_md` and `test_stocks_batch_profile_md`
- Any other test referencing `aspects=` in a batch-profile request or `klines` in the response.

Also **verify under the new contract** (run them; if they fail on the changed shape, delete them too):
- `TestPhase2DefensiveGuards::test_quote_none_counted_as_failure` (~1474-1511)
- `TestFormatMd::test_md_renders_from_cache_hit` (~1855-1878)

Test helpers: `_make_kline_df` / `_make_unified_quote` stay (still referenced by remaining tests). **`_bind_manager` is only used by `TestIndicesBatchProfile`** — after deleting that class it becomes orphaned; delete `_bind_manager` too.

- [ ] **Step 5: Run the full suite**

Run: `.venv/Scripts/python.exe -m pytest tests/test_agent_endpoints.py tests/test_agent_batch_features.py -q 2>&1 | tail -15`
Expected: PASS (all green).

- [ ] **Step 6: Ruff check**

Run: `.venv/Scripts/python.exe -m ruff check stock_data/api/routes/agent.py stock_data/api/schemas.py stock_data/api/cache.py stock_data/data_provider/features tests/test_agent_batch_features.py`
Expected: no errors (fix any unused-import / undefined-name findings, e.g. remove `IndexKlineBlock`/`StockQuote` imports from agent.py if no longer used).

- [ ] **Step 7: Commit**

```bash
git add stock_data/api/routes/agent.py tests/test_agent_endpoints.py tests/test_agent_batch_features.py
git commit -m "feat(agent): feature-block MD renderers + prune legacy batch-profile tests"
```

---

### Task 10: docs — reflect the new contract

**Files:**
- Modify: `skills/market-data-obtain.md` (§9.1 table rows for both batch-profile endpoints + "关键字段" notes)
- Modify: `api-reference.md` (batch-profile endpoint examples)
- Modify: `README.md` (endpoint table, if it lists batch-profile)
- Modify: `CLAUDE.md` (Agent Batch API routes table + standardized-data-schema notes if it references the old bar counts)

**Interfaces:**
- Consumes: the spec (exact frequencies, days ranges, response fields).

- [ ] **Step 1: Update `skills/market-data-obtain.md`**

In §9.1, replace the two batch-profile rows and the two "关键字段" blocks. New text (English/Chinese per surrounding style):

```markdown
| `GET /api/v1/agent/indices/batch-profile` | `?codes=` (1-5, 默认 3 核心) + `?frequency=` + `?days=` | 指数批量画像：每个指数极简 quote（最新价/涨跌幅）+ trend/pivots/volume 计算指标（替代原 5m/d/w 三频率 raw K 线） | 5xx 不外抛（quote/features 失败写入 `errors[]`） |
| `POST /api/v1/agent/stocks/batch-profile` | `{"codes": [...], "frequency": "d", "days": 60}` (1-5) | 股票批量画像：quote + features（trend/pivots/volume）+ info + boards；raw K 线已移除，需明细走 `/stocks/{code}/kline` | 5xx per-aspect 隔离（quote/features/info/boards） |

**`indices/batch-profile` 关键字段**：

- `frequency`（单值 `d/w/m/1m/5m/15m/30m/60m`）+ `days` 顶层回显；`days` 上限：`d≤365, w≤1095, m≤1825, 1m≤3, 5m≤5, 15m≤8, 30m≤15, 60m≤30`
- `indices[].features` = `{trend, pivots, volume}`；`trend`（MA 5/10/15/20/30/60 最新值 + 环比昨日 % + ADX/PDI/MDI/RSI/BOLL）、`pivots`（区间最高/最低/最大量价 + ZigZag 摆动点 + 在途未确认）、`volume`（最新量 + 5 日量比 + Z>2 放量异动）
- stocks 端固定 `adjust=qfq`；indices 无复权

**`stocks/batch-profile` 关键字段**：

- `codes` 1-5；`aspects` 入参已移除——每次返回 quote + features + info + boards
- 顶底为显著性过滤（`pivot_window=2, reversal_atr_mult=1.0, ATR14`），`pivots.params` 回显算法参数，不对外暴露
```

- [ ] **Step 2: Update `api-reference.md` / `README.md` / `CLAUDE.md`**

Grep the repo for the old contract strings and update the examples to the new request/response shape:

Run: `grep -rn "kline_5m\|aspects\|klines" api-reference.md README.md CLAUDE.md skills/ | head -40`
Update every hit that describes the batch-profile contract (frequency+days input, `features` block, no raw bars). Use the spec's JSON examples verbatim.

- [ ] **Step 3: Final full-suite run**

Run: `.venv/Scripts/python.exe -m pytest -q 2>&1 | tail -15`
Expected: PASS (dev suite; live_network skipped by default). Then run `ruff check .` and `ruff format --check .` — fix any stragglers.

- [ ] **Step 4: Commit**

```bash
git add skills/market-data-obtain.md api-reference.md README.md CLAUDE.md
git commit -m "docs: batch-profile computed-features contract across skills/README/CLAUDE"
```

---

## Self-Review notes (checked before saving)

- **Spec coverage:** §2.1 stocks (quote+features+info+boards) → Task 7; §2.2 indices → Task 8; §2.3 feature block → Tasks 1-4 + 5; §3.1 trend (MA 5/10/15/20/30/60 + change + DMI/RSI/BOLL) → Task 2; §3.2 pivots (ZigZag + window stats + pending + params) → Task 3; §3.3 volume (latest/vol_ratio_5/z>2/cap20) → Task 1; §3.4 per-freq days range + defaults → Task 7/8 constants; §4 qfq/lookback → Task 7/8; §5 cache (freq+days in key) → Task 6; MD projection → Task 9; §6 files touched → all tasks; §7 non-goals (no MTM / no raw bars / no adjust param / no pivot params / no aspects / single frequency) → honored everywhere.
- **Placeholder scan:** no TBD/TODO; every code step has concrete code.
- **Type consistency:** `build_features(df, *, frequency, days)`, `compute_trend(df)`, `compute_pivots(df, window_df, *, ...)`, `compute_volume(df, window_df)`, `_resolve_and_validate_days(frequency, days)`, `make_*_batch_profile_cache_key(codes, frequency, days)` — names and signatures consistent across Tasks 1-8. Schema field names (`ma/ma_change/adx/pdi/mdi/rsi/boll`, `window_high/window_low/max_vol_bar/swings/pending/params`, `latest_volume/vol_ratio_5/z_anomalies`) match the feature-module dict keys and the MD renderers.

- **Cross-check agent fixes (applied after review):** (1) minute frequencies must be converted via `_FREQ_TO_MGR` before calling `manager.get_kline_data` — fetchers only accept bare codes (`5`, not `5m`); Global Constraint + Task 7/8 routes + tests updated. (2) schemas replacement is **two disjoint blocks** (indices 1595-1654 + stocks 1761-1832) preserving the market-context models (1657-1757) between them. (3) Task 10 doc `60m≤30` corrected. (4) Task 9 adds `test_quote_none_counted_as_failure` + `test_md_renders_from_cache_hit` to the verify/delete list and removes the orphaned `_bind_manager`.
