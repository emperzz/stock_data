# `/api/v1/agent/{stocks,indices}/batch-profile` — Computed K-line Features

> Spec for replacing the raw K-line bar payloads in the two batch-profile
> endpoints with **server-computed trend / pivot / volume features**, so the
> LLM agent receives judgment-ready numeric facts instead of hundreds of raw
> bars it would otherwise have to re-arithmetic over.
>
> Design is grounded in the skills' trend-analysis requirements:
> `market-principles` §5.6 (trend time-frames: long=daily, weekly if needed;
> short=daily + minute), §5.2 (volume-price is the core), §5.4 (indicators
> are reference-only), and `stock-picking` §7 (60-bar daily fetch for MA60)
> / §8 (5-minute intraday volume comparison).

**Date**: 2026-08-27
**Status**: Draft
**Scope**: rewrite both batch-profile routes (request + response contract),
a new pure-compute feature module, schema changes, MD projections, tests.
Reuses the existing indicator layer (MA / RSI / BOLL / DMI) and
`manager.get_kline_data` (which already accepts `adjust=`). **No new
fetcher, no new `DataCapability` flag, no new manager method.**

---

## 1. Background

Today `/agent/indices/batch-profile` and `/agent/stocks/batch-profile` fan
out to raw K-line bars (indices: 5m×2d + d×30 + w×48; stocks: d×60 +
5m×2d) with hard-coded frequency → bar-count maps
(`_INDICES_KLINE_DAYS`, `_STOCK_ASPECT_DISPATCH` in `routes/agent.py`).

Problems with raw bars as the agent-facing payload:

1. **Token cost scales with bars.** 3 indices ≈ 520 bars, 5 stocks ≈ 780
   bars, ~7 fields each. The whole point of the batch endpoints (one-call,
   low-latency agent consumption) is undermined by the payload size.
2. **LLMs are bad at arithmetic over raw bars.** "Is there a top
   divergence? Volume coordination?" requires the agent to reduce ~200
   rows itself — slow and error-prone.
3. **Fixed windows are the wrong axis.** The real lever is *representation*:
   return the computed facts the agent reasons over, not the bars it must
   reduce.

This spec changes the contract: **the batch endpoints now return computed
features (trend / pivots / volume) instead of raw K-line bars.** Agents that
need raw bars use the existing `/stocks/{code}/kline` / `/indices/{code}/kline`
endpoints (which keep arbitrary `days` + `?indicators=`).

**Non-goals**: no MTM indicator (user dropped it); no raw bars in the
response; no `adjust` request param (server fixes `qfq` for stocks); no
exposed pivot-detection tuning params (server-fixed defaults); no judgment
labels (龙头 / 候选 / 强弱) — the endpoints keep emitting numeric facts
only, per the existing agent-endpoint contract.

---

## 2. Public API

Both endpoints share the same `frequency` + `days` input model (mirroring
the raw `/kline` interface) and the same per-code feature shape. `frequency`
is **single-valued per call** — the caller picks one time-frame and the
days that make sense for it; getting both long and short frames means two
calls (cheap under the 60s shared cache).

### 2.1 `POST /agent/stocks/batch-profile`

**Request body**:

```jsonc
{
  "codes": ["600519", "000858"],     // 1-5 (hard cap)
  "frequency": "d",                  // one of d/w/m/1m/5m/15m/30m/60m
  "days": 60                         // optional; per-frequency default; per-frequency max (see §3.4)
}
```

**Response** (top-level `frequency` / `days` echoed):

```jsonc
{
  "frequency": "d", "days": 60,
  "results": [
    {
      "code": "600519", "name": "贵州茅台",
      "ok": true,
      "quote": { "price": 1721.0, "change_pct": 1.2 },     // 极简当前价锚点
      "features": { "trend": {...}, "pivots": {...}, "volume": {...} },
      "info":  {...},                                      // 保留 aspect
      "boards": [...],                                     // 保留 aspect
      "errors": []                                         // per-aspect/per-code failure
    }
  ],
  "summary": { "requested": 2, "ok": 2, "failed": 0, "elapsed_ms": 85 }
}
```

- `quote` is the minimal current-price anchor (price + change_pct). The
  previous `StockQuote.from_unified_quote` full shape is **not** used here.
- `info` / `boards` are retained (they are not K-line detail, cost little,
  and `stock-picking` §9 needs them for business-comparison). The old
  `aspects` request param is dropped; all four fields are always present.
- The old `kline` / `kline_5m` aspects are replaced by the single
  `features` block computed at the requested `frequency`.

### 2.2 `GET /agent/indices/batch-profile`

**Query params**: `codes` (comma-separated, 1-5, default 3 core CSI),
`frequency` (default `d`), `days` (optional).

**Response**:

```jsonc
{
  "frequency": "d", "days": 120,
  "indices": [
    {
      "code": "000001", "name": "上证指数",
      "quote": { "price": 3540.2, "change_pct": 0.8 },
      "features": { "trend": {...}, "pivots": {...}, "volume": {...} },
      "errors": {}                                       // per-block failure map
    }
  ],
  "summary": { "requested": 3, "ok": 3, "failed": 0, "elapsed_ms": 95 }
}
```

- Indices have no `info` / `boards` (not applicable). `errors` is the
  existing per-block dict (`{quote: null|msg, features: null|msg}`).

### 2.3 Unified feature block (shared by both endpoints)

```jsonc
"features": {
  "trend": {
    "ma":        {"ma5": 12.30, "ma10": 12.10, "ma15": 12.00, "ma20": 11.80, "ma30": 11.40, "ma60": 10.90},
    "ma_change": {"ma5": 0.82, "ma10": 0.61, "ma15": 0.55, "ma20": 0.40, "ma30": 0.25, "ma60": 0.10},
    "adx": 28.3, "pdi": 24.1, "mdi": 18.6,
    "rsi":  {"rsi_6": 72.1, "rsi_12": 65.4, "rsi_24": 58.2},
    "boll": {"mid": 11.80, "upper": 13.10, "lower": 10.50, "bandwidth": 22.0}
  },
  "pivots": {
    "window_high": { "price": 13.20, "date": "2026-08-10" },
    "window_low":  { "price": 10.10, "date": "2026-07-15" },
    "max_vol_bar": { "price": 12.80, "volume": 5.2e7, "date": "2026-08-08" },
    "swings": [
      { "date": "2026-07-15", "type": "low",  "price": 10.10, "confirmed": true },
      { "date": "2026-08-03", "type": "high", "price": 12.60, "confirmed": true },
      { "date": "2026-08-18", "type": "low",  "price": 11.40, "confirmed": true }
    ],
    "pending": { "side": "topping", "bars": 2, "price": 13.10, "date": "2026-08-26" },
    "params": { "pivot_window": 2, "reversal_atr_mult": 1.0, "atr_period": 14 }
  },
  "volume": {
    "latest_volume": 3.1e7,
    "vol_ratio_5": 1.45,
    "z_anomalies": [
      { "date": "2026-08-25", "open": 12.10, "high": 13.00, "low": 12.05,
        "close": 12.90, "volume": 8.4e7, "z_score": 3.1,
        "direction": "up", "change_pct": 6.6 }
    ]
  }
}
```

Field semantics are defined in §3.

---

## 3. Feature computation

All three blocks are pure functions of the fetched K-line DataFrame,
computed server-side. The existing indicator layer
(`data_provider/indicators/`, via `indicator_service.compute` or direct
`calc*` calls) is reused for MA / RSI / BOLL / DMI(ADX). The pivot and
volume-z logic is new pure code (see §6 for module placement).

### 3.1 `trend` — trend-frame snapshot

- `ma`: latest value of SMA at periods **[5, 10, 15, 20, 30, 60]**.
  Computed via the existing `calcMA` with `periods=[5,10,15,20,30,60]`
  (the registry default is `[5,10,20,30,60]`; `15` and `30` are already
  supported periods, no indicator-layer change needed).
- `ma_change`: per-period percent change of the MA vs the previous bar
  (`(ma_p[t] - ma_p[t-1]) / ma_p[t-1] * 100`), i.e. the 1-bar slope.
- `adx` / `pdi` / `mdi`: latest values from `calcDMI` (period 14).
  ADX is a DMI output column — no separate ADX module.
- `rsi`: latest values for periods **[6, 12, 24]** (existing `calcRSI`).
- `boll`: latest `mid / upper / lower / bandwidth` from `calcBOLL`
  (period 20, stdDev 2.0).

Trend is deliberately a *cross-sectional + 1-bar-slope* snapshot. Direction
and structure are left to the `pivots` block (HH/HL vs LH/LL) and to the
agent's methodology — per user decision, no trend_consistency /
close_vs_ma / deviation / swing_structure derived fields are emitted.

### 3.2 `pivots` — significance-filtered swing points (ZigZag)

The "tops / bottoms you can see on a chart" are **local extrema filtered
by a minimum reversal significance**, not every bar's high/low (that is
noise) and not the window's single global max/min (that loses all
intermediate structure).

Algorithm:

1. **Candidate extrema** (`pivot_window = 2`): bar `i` is a candidate
   swing-high iff `high[i] == max(high[i-k .. i+k])` (k=2 → higher than
   the 2 bars on each side); candidate low is symmetric on `low`.
   The last `k` bars cannot be candidates yet (right-side confirmation
   incomplete).
2. **ZigZag significance pass** (`reversal_atr_mult = 1.0`, ATR14):
   walk candidates chronologically, alternating high / low. Track the
   running extreme; confirm it as a pivot and flip direction only when
   price has reversed ≥ `reversal_atr_mult × ATR14` from it. ATR is the
   existing `calcATR` (period 14) — using ATR (not a fixed %) keeps the
   threshold comparable across price scales.
3. **Pending state**: after the pass, the last tracked extreme has not
   been confirmed (no reversal yet). Emit it as `pending`
   `{side: "high"|"low", bars, price, date}` so the agent does not treat
   an in-flight top/bottom as confirmed. This confirmation-lag is inherent
   to pivot detection and must be explicit.

Output (see §2.3):

- `window_high` / `window_low`: the max `high` / min `low` within the
  **requested `days` window** (with dates) — the user-visible "周期范围内
  的最高价 / 最低价".
- `max_vol_bar`: the bar with the max `volume` within the window — its
  `{price, volume, date}` — the "成交量最高的价格".
- `swings`: last ≤6 confirmed pivots, `{date, type: high|low, price,
  confirmed: true}`, ordered chronologically.
- `pending`: the in-flight extreme (see step 3).
- `params`: the fixed algorithm settings, echoed for transparency
  (`{pivot_window, reversal_atr_mult, atr_period}`). Not request-tunable.

### 3.3 `volume` — volume-price coordination

- `latest_volume`: the newest bar's `volume`.
- `vol_ratio_5`: `latest_volume / mean(volume of the previous 5 bars)`
  (the user's "当期成交量 / 前 5 个 K 线的平均成交量"). Denominator
  excludes the current bar.
- `z_anomalies`: bars in the requested `days` window whose volume
  **Z-score > 2.0**, where `z = (vol - mean) / std` over the window.
  Each entry carries `{date, open, high, low, close, volume, z_score,
  direction, change_pct}`:
  - `direction`: `"up"` (阳线, `close >= open`) / `"down"` (阴线).
  - `change_pct`: `(close - prev_close) / prev_close * 100` (涨跌幅度).
  Sorted by `z_score` descending, capped at **20 entries** to bound the
  payload. These are the "放量异动" bars the agent uses for
  §5.2 volume-price judgment (e.g. 大涨 + 缩量 = warning) and
  `stock-picking` §8's 放量段 identification.

### 3.4 Per-frequency `days` validation

`days` is in calendar days ("最近多少天"). Max follows
`agent_correlation._FREQ_DAYS_RANGE` with the minute-frequency caps
enlarged per user decision:

| frequency | min | max | default (days omitted) |
|---|---|---|---|
| `d`  | 2   | 365  | 60  |
| `w`  | 14  | 1095 | 156 |
| `m`  | 60  | 1825 | 365 |
| `1m` | 2   | 3    | 3   |
| `5m` | 2   | **5**  | 5   |
| `15m`| 2   | **8**  | 8   |
| `30m`| 2   | **15** | 15  |
| `60m`| 2   | **30** | 30  |

> Deltas vs `correlation/matrix`: `5m` 3→5, `15m` 5→8, `30m` 10→15,
> `60m` 20→30. **Caveat**: the enlarged minute-frequency caps are the
> server-side validation ceiling; actual availability is upstream-bounded
> (minute K-line fetchers may serve less depth). A fetch that exceeds what
> upstream serves surfaces as a per-code feature error, not a silent
> truncation.
>
> Out-of-range `days` → 422 (consistent with `/agent/*` peers).

---

## 4. Data flow & lookback

1. Route validates `frequency` / `days` (per §3.4 table) and normalizes
   `codes` (max 5; bare 6-digit; `HKxxxx` / US letters as canonical).
2. Per code: `manager.get_kline_data(code, days=feature_days,
   frequency=<mgr-freq>, adjust="qfq" if asset=="stock" else None,
   asset=<stock|index>)`.
   - `feature_days = max(requested days, indicator warm-up)` — the
     existing `max(days, lookback)` pattern (see CLAUDE.md "Indicator
     Computation"). MA60 + 20-bar context + ATR14 + swing detection want
     ≥ ~90 daily bars to be warm; minute frames warm in fewer bars.
   - `adjust="qfq"` is **hard-coded** for stocks (user decision: no
     `adjust` request param; 前复权 so ex-dividend gaps do not corrupt
     MA / support-resistance math). Indices: no adjust. Minute
     frequencies: qfq applied where the serving fetcher supports it;
     otherwise upstream returns unadjusted bars (documented, not an
     error).
3. The fetched df feeds the pure feature module (trend / pivots / volume).
   Window-scoped values (`window_high/low`, `max_vol_bar`, `z_anomalies`,
   `vol_ratio_5`) use the bars within the requested `days` window; the
   indicator-latest values and swing detection use the full (warm) df.
4. Response assembled per §2; per-code failures isolated in `errors[]`
   without aborting the batch (existing contract).

---

## 5. Cache & errors

- Cache: reuse `get_quote_cache` (60s TTL), key = sorted `codes` +
  `frequency` + `days`. Existing `make_indices_batch_profile_cache_key` /
  `make_stocks_batch_profile_cache_key` signatures change to include
  `frequency` + `days` (the old key hashed code/aspect sets only). Cache
  hit reorders to input `codes` order (existing `_reorder_by_code`).
- Errors: per-code isolation, same as today. A code that fails
  everything → `ok=false` + reason; a partial failure (e.g. feature block
  only) → `errors[]` with the rest populated. Indices keep the per-block
  dict.
- `?format=md`: both endpoints keep the `_render_agent` MD projection.
  `render_*_batch_profile_as_md` are rewritten to render the three
  feature blocks as compact tables / lists (no data loss).

---

## 6. Files touched

| File | Change |
|---|---|
| `stock_data/api/routes/agent.py` | Rewrite `get_indices_batch_profile` + `post_stocks_batch_profile`: new request/response, per-frequency fetch with `adjust=qfq`, assemble feature blocks. Update `_serialize_stock_aspect_value` (drop kline branches), `_INDICES_KLINE_DAYS` / `_STOCK_ASPECT_DISPATCH` (remove), cache-key builders, MD renderers. |
| `stock_data/api/schemas.py` | New models: `BatchFeatures`, `TrendFeatures`, `PivotFeatures`, `VolumeFeatures`, `SwingPoint`, `PendingSwing`, `ZAnomalyBar`, rewritten `StockBatchProfileEntry` / `IndexProfile` / request + response models. |
| `stock_data/data_provider/features/` (new package) | Pure-compute module(s): `trend.py` (MA latest + change, DMI/RSI/BOLL latest — thin wrappers over indicator calc functions), `pivots.py` (ZigZag + window stats + max_vol_bar), `volume.py` (vol_ratio_5 + z_anomalies). |
| `tests/test_agent_endpoints.py` (+ new feature tests) | Pin: per-frequency max-days 422, qfq passed to manager, window stats over requested window, swing confirmation-lag, z>2 filter + 20-cap, MD projection, error isolation. |

No fetcher, manager, or `DataCapability` changes. The indicator layer
already ships MA / RSI / BOLL / DMI; MA periods `[5,10,15,20,30,60]` are
passed as options (no registry change).

---

## 7. Non-goals

- **No MTM** (user dropped it). ROC remains available via `/kline?indicators=`.
- **No raw K-line bars** in batch-profile responses. Detail via
  `/stocks/{code}/kline` / `/indices/{code}/kline`.
- **No `adjust` param** — stocks always `qfq`, indices no-adjust.
- **No exposed pivot params** — `pivot_window=2`, `reversal_atr_mult=1.0`,
  ATR14 server-fixed; echoed in `pivots.params` only.
- **No judgment labels** (龙头 / 候选 / 强弱分) — numeric facts only.
- **No multi-frequency per call** — one `frequency` per call; long + short
  = two calls under the shared 60s cache.
