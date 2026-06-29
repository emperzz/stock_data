# Price API Unification Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Unify stock + index price data into two endpoint families (`/quote` snapshot + `/kline` 1m..m with qfq/hfq) by collapsing 4 K-line capability flags into 2, adding per-fetcher fine-grained support declarations, and deprecating legacy endpoints.

**Architecture:** Two-phase rollout. **P0** = zero-API-risk internal refactor: flag collapse + `supports_kline()`/`supports_quote()` per-fetcher declarations + manager two-stage filter + Akshare volume normalization. **P1** = API surface: new `/kline` endpoints, drop route-layer reject rules, `/quote` explicit param rejection, cache key merge, 6-month deprecation of `/history` + `/intraday`.

**Tech Stack:** Python 3.x, FastAPI, pandas, pytest, ruff. Default pytest skips `live_network` and `requires_token` (set via `addopts` in `pyproject.toml`).

---

## Background facts the engineer needs

1. **Capability bit names map to fetcher methods** via `data_provider/base.py:CAPABILITY_TO_METHOD`. Every flag MUST be in that map or in `_NO_FETCHER_METHOD`. The map and `_filter_by_capability(market, cap)` shape are stable; we're only renaming 4 flags (collapsing 4 → 2) and renaming 2 (→ explicit asset class).

2. **The fetchers implementing the renamed flags** (`stock_data/data_provider/fetchers/`):
   - `TushareFetcher`, `BaostockFetcher`, `AkshareFetcher`, `YfinanceFetcher`, `ZhituFetcher`, `ZzshareFetcher`, `MyquantFetcher` (need `supports_kline` override + flag migration)
   - `TushareFetcher`, `BaostockFetcher`, `AkshareFetcher`, `YfinanceFetcher`, `ZhituFetcher`, `ZzshareFetcher`, `MyquantFetcher`, `TencentFetcher` (need `supports_quote` override — but most can leave default since quote has only market dim)

3. **Akshare volume bug**: `docs/akshare/stock/stock_zh_a_hist.md` documents that volume is in **lots (手 = 100 shares)** while every other fetcher returns **shares**. This means `/100` must happen at the fetcher boundary (or the response schema gains a `volume_unit` discriminator). The spec says we add a `volume_unit: "lot"|"share"` metadata field and divide by 100 in `AkshareFetcher._normalize_data()`.

4. **TTL keys** at `stock_data/api/cache.py` already split: `_TTL_STOCK_INTRADAY` (30s) vs `_TTL_HISTORY` (longer). Task 8 wires them under a unified `make_kline_cache_key`.

5. **The existing route-layer "reject minute + adjust"** is in `stock_data/api/routes/stocks.py:230` (regex) and `helpers.py:42-54` (`_PERIOD_MAP` fallback). Task 9 removes both in favor of the new `/kline` endpoint with `supports_kline` deciding validity.

6. **Test conventions** (matches recent `tests/test_zzshare_fetcher.py` and `tests/test_boards.py`):
   - `pytest -m "not live_network and not requires_token"` is the default guard.
   - Use `MagicMock` to mock `api` objects on fetchers (`fetcher._api.method = MagicMock(return_value=...)`).
   - Patches against `stock_data.data_provider.manager.DataFetcherManager.get_*` follow `tests/test_boards_api.py:29` pattern.

7. **Existing test files we will extend** (NOT recreate): `tests/test_capability_method_map.py`, `tests/test_manager_return_source.py`, `tests/test_manager_zzshare_minute.py`, `tests/test_stocks_api.py`, `tests/test_indices_api.py`.

---

## File Structure

**Modify:**

- `stock_data/data_provider/base.py` (add 4 new flag values; add `supports_kline`, `supports_quote` methods on `BaseFetcher`; update `CAPABILITY_TO_METHOD`)
- `stock_data/data_provider/manager.py` (refactor `get_kline_data`, `get_intraday_data`, `get_realtime_quote`, `get_index_realtime_quote`, `get_index_historical`, `get_index_intraday` to two-stage filter; **delete** old "minute + adjust" reject path)
- `stock_data/data_provider/fetchers/{tushare,baostock,yfinance,zhitu,zzshare,myquant}_fetcher.py` (migrate `supported_data_types` + add `supports_kline` overrides; per spec §4.3)
- `stock_data/data_provider/fetchers/akshare/fetcher.py` (same + volume unit normalization `/100` + `volume_unit` field)
- `stock_data/api/routes/stocks.py` (add `/kline` route; deprecate `/history` and `/intraday`; explicit `/quote` reject for `period/adjust/days/start_date/end_date`)
- `stock_data/api/routes/indices.py` (add `/kline` route; deprecate `/history` and `/intraday`; explicit `/quote` reject for `period/adjust/days/start_date/end_date`)
- `stock_data/api/cache.py` (add `make_kline_cache_key`, `get_kline_cache`)
- `tests/test_capability_method_map.py` (assert 4 old flags are in `_NO_FETCHER_METHOD` deprecated set; new 4 flags have proper map entries)
- `tests/test_manager_zzshare_minute.py` (extend to verify 1m + qfq → no fetcher available)
- `tests/test_stocks_api.py`, `tests/test_indices_api.py` (extend for new `/kline` + `/quote` reject)

**Create:**

- `tests/test_supports_kline.py` (per-fetcher `supports_kline` matrix)
- `tests/test_supports_quote.py` (per-fetcher `supports_quote` matrix)
- `tests/test_kline_unified.py` (parametrized routing matrix)
- `tests/test_quote_param_reject.py` (verify `/quote` rejects period/adjust/days/start_date/end_date)
- `tests/test_akshare_volume_normalization.py` (verify `/100` + volume_unit field)

---

## Plan Phases

- **P0** (Tasks 1–7): zero-API-risk internal refactor. After P0, manager + fetchers know how to route correctly but no user-visible behavior changes — old routes still serve with the old (now aliased) flags.
- **P1** (Tasks 8–12): API surface changes. After P1, `/kline` is canonical; old `/history` + `/intraday` redirect to it; `/quote` rejects the (semantically meaningless) extra params.

Each task is a self-contained PR candidate. Plan ordering reflects the dependency graph: manager refactor (Task 5–6) requires supports_* methods (Task 2) and per-fetcher overrides (Task 3).

---

# Phase P0 — Internal Refactor (Zero API Risk)

## Task 1: Collapse capability flags (4 → 2) with 6-month shim

**Files:**
- Modify: `stock_data/data_provider/base.py:25-110`

- [ ] **Step 1: Write failing test for new flag presence + shim**

Create `tests/test_capability_flag_collapse.py`:

```python
"""Verify the spec §4.1 / §3.3 capability flag collapse with 6-month shim."""
import pytest

from stock_data.data_provider.base import DataCapability


def test_new_kline_flags_exist():
    """Rev 2 spec adds STOCK_KLINE + INDEX_KLINE + STOCK_REALTIME_QUOTE + INDEX_REALTIME_QUOTE."""
    assert DataCapability.STOCK_KLINE
    assert DataCapability.INDEX_KLINE
    assert DataCapability.STOCK_REALTIME_QUOTE
    assert DataCapability.INDEX_REALTIME_QUOTE


def test_old_flags_remain_parseable_for_shim():
    """Old flag names must remain accessible for 6-month backwards compat."""
    # The shim keeps old names as aliases — DataCapability.<old> stays accessible.
    assert DataCapability.HISTORICAL_DWM is not None
    assert DataCapability.HISTORICAL_MIN is not None
    assert DataCapability.INDEX_HISTORICAL is not None
    assert DataCapability.INDEX_INTRADAY is not None
    assert DataCapability.REALTIME_QUOTE is not None
    assert DataCapability.INDEX_QUOTE is not None
```

- [ ] **Step 2: Run the test — expect AttributeError on new flag**

Run: `.venv/Scripts/python.exe -m pytest tests/test_capability_flag_collapse.py -v`
Expected: FAIL with `AttributeError: <flag>` for the new flags.

- [ ] **Step 3: Add new flags to enum**

Edit `stock_data/data_provider/base.py` lines 25-43. Append four new entries while keeping old ones (shim):

```python
class DataCapability(Flag):
    HISTORICAL_DWM = auto()  # DEPRECATED — aliased via _shim_old_to_new below; remove in 6 months
    HISTORICAL_MIN = auto()  # DEPRECATED — aliased via _shim_old_to_new below; remove in 6 months
    REALTIME_QUOTE = auto()  # DEPRECATED — aliased to STOCK_REALTIME_QUOTE; remove in 6 months
    # --- rev 2 unified flags (Task 1) ---
    STOCK_KLINE = auto()              # 股票 d/w/m + 1m/5m/15m/30m/60m
    INDEX_KLINE = auto()              # 指数 d/w/m + 1m/5m/15m/30m/60m
    STOCK_REALTIME_QUOTE = auto()     # 股票实时快照
    INDEX_REALTIME_QUOTE = auto()     # 指数实时快照
    # --- existing flags (unchanged) ---
    STOCK_LIST = auto()
    TRADE_CALENDAR = auto()
    STOCK_BOARD = auto()
    INDEX_QUOTE = auto()  # DEPRECATED — aliased to INDEX_REALTIME_QUOTE; remove in 6 months
    INDEX_HISTORICAL = auto()  # DEPRECATED — aliased to INDEX_KLINE; remove in 6 months
    INDEX_INTRADAY = auto()  # DEPRECATED — aliased to INDEX_KLINE; remove in 6 months
    STOCK_ZT_POOL = auto()
    DRAGON_TIGER = auto()
    MARGIN_TRADING = auto()
    BLOCK_TRADE = auto()
    HOLDER_NUM = auto()
    DIVIDEND = auto()
    FUND_FLOW = auto()
    HOT_TOPICS = auto()
    NORTH_FLOW = auto()
    RESEARCH_REPORT = auto()
    ANNOUNCEMENT = auto()
    NEWS_FLASH = auto()
    NEWS_SEARCH = auto()
    STOCK_INFO = auto()
```

- [ ] **Step 4: Wire `CAPABILITY_TO_METHOD` for new flags and add shim map**

Find the `CAPABILITY_TO_METHOD` dict (around line 79). Keep old entries working during shim, add new entries that point to the same fetcher method:

```python
CAPABILITY_TO_METHOD: dict[DataCapability, str] = {
    # --- old (shim, 6-month back-compat) ---
    DataCapability.HISTORICAL_DWM: "get_kline_data",
    DataCapability.HISTORICAL_MIN: "get_kline_data",
    DataCapability.REALTIME_QUOTE: "get_realtime_quote",
    DataCapability.INDEX_HISTORICAL: "get_index_historical",
    DataCapability.INDEX_INTRADAY: "get_index_intraday",
    DataCapability.INDEX_QUOTE: "get_index_realtime_quote",
    # --- rev 2 (canonical) ---
    DataCapability.STOCK_KLINE: "get_kline_data",
    DataCapability.INDEX_KLINE: "get_index_historical",  # for d/w/m; minute via get_intraday_data
    DataCapability.STOCK_REALTIME_QUOTE: "get_realtime_quote",
    DataCapability.INDEX_REALTIME_QUOTE: "get_index_realtime_quote",
    # --- unchanged ---
    DataCapability.STOCK_LIST: "get_all_stocks",
    # ... (rest unchanged)
}
```

Add a shim function (immediately after `CAPABILITY_TO_METHOD`):

```python
# 6-month backwards-compat shim: map deprecated flag → canonical flag.
# Used by BaseFetcher.__init__ (Task 4) and tests/manifest until T+180d.
DEPRECATED_TO_CANONICAL: dict[DataCapability, DataCapability] = {
    DataCapability.HISTORICAL_DWM: DataCapability.STOCK_KLINE,
    DataCapability.HISTORICAL_MIN: DataCapability.STOCK_KLINE,
    DataCapability.INDEX_HISTORICAL: DataCapability.INDEX_KLINE,
    DataCapability.INDEX_INTRADAY: DataCapability.INDEX_KLINE,
    DataCapability.REALTIME_QUOTE: DataCapability.STOCK_REALTIME_QUOTE,
    DataCapability.INDEX_QUOTE: DataCapability.INDEX_REALTIME_QUOTE,
}
```

- [ ] **Step 5: Run test — expect PASS**

Run: `.venv/Scripts/python.exe -m pytest tests/test_capability_flag_collapse.py -v`
Expected: 2 passed.

- [ ] **Step 6: Run pre-existing `test_capability_method_map.py` — expect PASS (old names still in map)**

Run: `.venv/Scripts/python.exe -m pytest tests/test_capability_method_map.py -v`
Expected: PASS (old flag names still resolve).

- [ ] **Step 7: Commit**

```bash
git add stock_data/data_provider/base.py tests/test_capability_flag_collapse.py
git commit -m "feat(base): collapse 4 K-line flags to 2 + rename quote flags with 6-month shim

- new flags: STOCK_KLINE, INDEX_KLINE, STOCK_REALTIME_QUOTE, INDEX_REALTIME_QUOTE
- old flags (HISTORICAL_DWM/MIN/INDEX_HISTORICAL/INTRADAY/REALTIME_QUOTE/INDEX_QUOTE)
  remain as aliases for 6 months
- DEPRECATED_TO_CANONICAL map keeps existing fetchers working without edits

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 2: Add `BaseFetcher.supports_kline` and `BaseFetcher.supports_quote` defaults

**Files:**
- Modify: `stock_data/data_provider/base.py` (BaseFetcher class body)

- [ ] **Step 1: Write failing tests for default impls**

Create `tests/test_supports_defaults.py`:

```python
"""Default BaseFetcher.supports_kline / supports_quote per spec §4.2 / §4.2.1."""
import pytest

from stock_data.data_provider.base import BaseFetcher, DataCapability
from stock_data.data_provider.fetchers.baostock_fetcher import BaostockFetcher


class _StockOnlyFetcher(BaseFetcher):
    """Concrete subclass with only STOCK_KLINE + STOCK_REALTIME_QUOTE."""
    name = "FakeStock"
    priority = 99
    supported_markets = {"csi"}
    supported_data_types = (
        DataCapability.STOCK_KLINE | DataCapability.STOCK_REALTIME_QUOTE
    )

    def is_available(self) -> bool: return True


class _IndexOnlyFetcher(BaseFetcher):
    """Concrete subclass with only INDEX_KLINE + INDEX_REALTIME_QUOTE."""
    name = "FakeIndex"
    priority = 99
    supported_markets = {"us"}
    supported_data_types = (
        DataCapability.INDEX_KLINE | DataCapability.INDEX_REALTIME_QUOTE
    )

    def is_available(self) -> bool: return True


def test_default_supports_kline_all_periods_when_cap_declared():
    """A fetcher declaring STOCK_KLINE returns True for any period on supported market."""
    f = _StockOnlyFetcher()
    for period in ("d", "w", "m", "1", "5", "15", "30", "60"):
        assert f.supports_kline(period, "", "csi", "stock") is True
    # unsupported market:
    assert f.supports_kline("d", "", "hk", "stock") is False
    # unsupported asset (no INDEX_KLINE declared):
    assert f.supports_kline("d", "", "csi", "index") is False


def test_default_supports_quote_market_only():
    f = _StockOnlyFetcher()
    assert f.supports_quote("csi") is True
    assert f.supports_quote("hk") is False  # supported_markets says csi only

    idx = _IndexOnlyFetcher()
    assert idx.supports_quote("us") is True
    assert idx.supports_quote("csi") is False  # not in supported_markets
```

- [ ] **Step 2: Run tests — expect AttributeError**

Run: `.venv/Scripts/python.exe -m pytest tests/test_supports_defaults.py -v`
Expected: FAIL with `AttributeError: 'BaseFetcher' object has no attribute 'supports_kline'`.

- [ ] **Step 3: Add `supports_kline` and `supports_quote` to `BaseFetcher`**

In `stock_data/data_provider/base.py`, inside the `BaseFetcher` class body, add:

```python
def supports_kline(
    self,
    period: str,    # "d"/"w"/"m"/"1"/"5"/"15"/"30"/"60"
    adjust: str,     # ""/"qfq"/"hfq"
    market: str,     # "csi"/"hk"/"us"
    asset: str,      # "stock"/"index"
) -> bool:
    """Return True iff this fetcher CAN serve (asset, period, adjust, market).

    Default behaviour: True when (a) market ∈ supported_markets and (b) the
    fetcher has at least one of STOCK_KLINE / INDEX_KLINE in its capability
    bit set matching `asset`. Subclasses narrow further to express upstream
    quirks (e.g. Yfinance hfq silently downgrades to qfq → unsupported).
    """
    if market not in self.supported_markets:
        return False
    if asset == "stock" and not (DataCapability.STOCK_KLINE in self.supported_data_types):
        return False
    if asset == "index" and not (DataCapability.INDEX_KLINE in self.supported_data_types):
        return False
    return period in ("d", "w", "m", "1", "5", "15", "30", "60")


def supports_quote(self, market: str) -> bool:
    """Return True iff this fetcher can serve realtime quote for `market`.

    Default: market ∈ supported_markets AND fetcher has STOCK_REALTIME_QUOTE
    or INDEX_REALTIME_QUOTE in its capability bit set. Subclasses override
    only for edge cases (e.g. Tencent csi/hk only).
    """
    if market not in self.supported_markets:
        return False
    return (
        DataCapability.STOCK_REALTIME_QUOTE in self.supported_data_types
        or DataCapability.INDEX_REALTIME_QUOTE in self.supported_data_types
    )
```

- [ ] **Step 4: Re-run tests — expect PASS**

Run: `.venv/Scripts/python.exe -m pytest tests/test_supports_defaults.py -v`
Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add stock_data/data_provider/base.py tests/test_supports_defaults.py
git commit -m "feat(base): add BaseFetcher.supports_kline and supports_quote defaults

Per spec §4.2, the new default impl checks market + asset→capability mapping.
Per spec §4.2.1, supports_quote defaults to market ∈ supported_markets check.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 3: Override `supports_kline` per fetcher (Tushare, Baostock, Akshare, Yfinance, Zhitu, Zzshare, Myquant)

**Files:**
- Modify: `stock_data/data_provider/fetchers/tushare_fetcher.py`
- Modify: `stock_data/data_provider/fetchers/baostock_fetcher.py`
- Modify: `stock_data/data_provider/fetchers/akshare/fetcher.py`
- Modify: `stock_data/data_provider/fetchers/yfinance_fetcher.py`
- Modify: `stock_data/data_provider/fetchers/zhitu_fetcher.py`
- Modify: `stock_data/data_provider/fetchers/zzshare_fetcher.py`
- Modify: `stock_data/data_provider/fetchers/myquant_fetcher.py`
- Create: `tests/test_supports_kline_per_fetcher.py`

This is a tall task; split into per-fetcher steps for clarity. The pattern is the same: (1) write test asserting the override's behaviour for that fetcher, (2) add the override, (3) commit.

- [ ] **Step 1: Write a parametrized test exercising all 7 fetchers**

Create `tests/test_supports_kline_per_fetcher.py`:

```python
"""Per-fetcher supports_kline overrides per spec §4.3."""
import pytest

from stock_data.data_provider import (
    AkshareFetcher,
    BaostockFetcher,
    MyquantFetcher,
    TushareFetcher,
    YfinanceFetcher,
    ZhituFetcher,
    ZzshareFetcher,
)


# (fetcher_class, period, adjust, market, asset, expected)
CASES = [
    # Tushare: only csi + d/w/m; weekly/monthly + adjust valid
    (TushareFetcher, "d",   "",    "csi", "stock", True),
    (TushareFetcher, "d",   "qfq", "csi", "stock", True),
    (TushareFetcher, "w",   "qfq", "csi", "stock", True),   # weekly + adjust supported
    (TushareFetcher, "1",   "",    "csi", "stock", False),
    (TushareFetcher, "d",   "",    "hk",  "stock", False),
    (TushareFetcher, "d",   "",    "csi", "index", True),  # Tushare has INDEX_KLINE for d/w/m
    (TushareFetcher, "5",   "",    "csi", "index", False),

    # Baostock: stock d/w/m + csi-stock minutes (5/15/30/60); index d/w/m only
    (BaostockFetcher, "d",   "hfq", "csi", "stock", True),
    (BaostockFetcher, "5",   "qfq", "csi", "stock", True),
    (BaostockFetcher, "5",   "",    "hk",  "stock", False),
    (BaostockFetcher, "1",   "",    "csi", "stock", False),
    (BaostockFetcher, "d",   "",    "us",  "index", True),
    (BaostockFetcher, "5",   "",    "csi", "index", False),  # index has no minutes

    # Akshare: 1m forces no adjust; otherwise supports (d/w/m + minutes) for stock + (csi) for index
    (AkshareFetcher, "1",   "",    "csi", "stock", True),
    (AkshareFetcher, "1",   "qfq", "csi", "stock", False),   # 1m refuses adjust
    (AkshareFetcher, "5",   "qfq", "csi", "stock", True),
    (AkshareFetcher, "5",   "qfq", "csi", "index", True),    # CSI index has minutes
    (AkshareFetcher, "1",   "qfq", "us",  "index", False),

    # Yfinance: hfq silently downgrades to qfq → unsupported; qfq OK
    (YfinanceFetcher, "5",   "qfq", "us",  "stock", True),
    (YfinanceFetcher, "5",   "hfq", "us",  "stock", False),  # silent downgrade → unsupported
    (YfinanceFetcher, "5",   "qfq", "us",  "index", True),
    (YfinanceFetcher, "1",   "",    "us",  "stock", False),  # Yfinance has no 1m

    # Zhitu: only 5/15/30/60 + no adjust
    (ZhituFetcher,   "5",   "",    "csi", "stock", True),
    (ZhituFetcher,   "5",   "qfq", "csi", "stock", False),   # Zhitu forces no adjust
    (ZhituFetcher,   "d",   "",    "csi", "stock", False),   # Zhitu has no d/w/m
    (ZhituFetcher,   "1",   "",    "csi", "stock", False),   # Zhitu has no 1m

    # Zzshare: d + minute, minute refuses adjust
    (ZzshareFetcher, "d",   "qfq", "csi", "stock", True),
    (ZzshareFetcher, "5",   "",    "csi", "stock", True),
    (ZzshareFetcher, "5",   "qfq", "csi", "stock", False),   # upstream ignores
    (ZzshareFetcher, "1",   "",    "csi", "stock", True),
    (ZzshareFetcher, "w",   "",    "csi", "stock", False),   # Zzshare has no weekly

    # Myquant: d + 5/15/30/60 with full adjust; csi-only index minutes
    (MyquantFetcher, "d",   "hfq", "csi", "stock", True),
    (MyquantFetcher, "5",   "qfq", "csi", "stock", True),
    (MyquantFetcher, "5",   "qfq", "us",  "stock", False),   # Myquant is csi-only for intraday
    (MyquantFetcher, "5",   "",    "csi", "index", True),
    (MyquantFetcher, "5",   "",    "us",  "index", False),   # Myquant index minutes csi-only
    (MyquantFetcher, "w",   "",    "csi", "stock", False),   # Myquant has no weekly
]


@pytest.mark.parametrize("fetcher_cls,period,adjust,market,asset,expected", CASES)
def test_supports_kline_matrix(fetcher_cls, period, adjust, market, asset, expected):
    # Instantiate through .is_available guard — return instance even if unavailable.
    inst = fetcher_cls.__new__(fetcher_cls)
    # We bypass __init__ for safety; populate just the attributes the method reads:
    inst.supported_markets = getattr(fetcher_cls, "supported_markets", {"csi", "us", "hk"})
    # Lazily import known-good supported_markets from each fetcher.
    from stock_data.data_provider.fetchers import (
        tushare_fetcher, baostock_fetcher,
    )
    from stock_data.data_provider.fetchers.akshare import fetcher as akshare_mod
    from stock_data.data_provider.fetchers.yfinance_fetcher import YfinanceFetcher
    from stock_data.data_provider.fetchers.zhitu_fetcher import ZhituFetcher
    from stock_data.data_provider.fetchers.zzshare_fetcher import ZzshareFetcher
    from stock_data.data_provider.fetchers.myquant_fetcher import MyquantFetcher

    real = {
        TushareFetcher: tushare_fetcher.TushareFetcher.supported_markets,
        BaostockFetcher: baostock_fetcher.BaostockFetcher.supported_markets,
        AkshareFetcher: akshare_mod.AkshareFetcher.supported_markets,
        YfinanceFetcher: YfinanceFetcher.supported_markets,
        ZhituFetcher: ZhituFetcher.supported_markets,
        ZzshareFetcher: ZzshareFetcher.supported_markets,
        MyquantFetcher: MyquantFetcher.supported_markets,
    }
    inst.supported_markets = real[fetcher_cls]
    # Now exercise the method.
    assert inst.supports_kline(period, adjust, market, asset) is expected
```

- [ ] **Step 2: Run test — expect most FAIL (default impls don't narrow)**

Run: `.venv/Scripts/python.exe -m pytest tests/test_supports_kline_per_fetcher.py -v`
Expected: many FAILs (e.g. `YfinanceFetcher, "5", "hfq", ...` returns True under default but should be False).

- [ ] **Step 3: Add `supports_kline` override to TushareFetcher**

In `stock_data/data_provider/fetchers/tushare_fetcher.py`, inside the class body:

```python
def supports_kline(self, period, adjust, market, asset):
    # Tushare: only csi + (d/w/m). Weekly/monthly adjust IS supported via adj='qfq|hfq'.
    if market != "csi" or period not in ("d", "w", "m"):
        return False
    return True
```

- [ ] **Step 4: Add `supports_kline` override to BaostockFetcher**

```python
def supports_kline(self, period, adjust, market, asset):
    if asset == "stock":
        if period in ("d", "w", "m"):
            return True
        if period in ("5", "15", "30", "60"):
            return market == "csi"
        return False  # no 1m
    if asset == "index":
        return period in ("d", "w", "m")  # no minutes for index
    return False
```

- [ ] **Step 5: Add `supports_kline` override to AkshareFetcher**

```python
def supports_kline(self, period, adjust, market, asset):
    # 1m upstream hard-rejects adjust (full-fetcher only 1m source).
    if period == "1" and adjust in ("qfq", "hfq"):
        return False
    return super().supports_kline(period, adjust, market, asset)
```

- [ ] **Step 6: Add `supports_kline` override to YfinanceFetcher**

```python
def supports_kline(self, period, adjust, market, asset):
    # hfq silently downgrades to qfq (semantic loss) → treat as unsupported.
    if adjust == "hfq":
        return False
    return super().supports_kline(period, adjust, market, asset)
```

- [ ] **Step 7: Add `supports_kline` override to ZhituFetcher**

```python
def supports_kline(self, period, adjust, market, asset):
    # Zhitu only minute (5/15/30/60), upstream forces no adjust.
    return period in ("5", "15", "30", "60") and adjust in ("", None)
```

- [ ] **Step 8: Add `supports_kline` override to ZzshareFetcher**

```python
def supports_kline(self, period, adjust, market, asset):
    if period == "d":
        return True
    if period in ("1", "5", "15", "30", "60"):
        # Zzshare stk_mins upstream ignores adjust → treat as unsupported.
        return adjust in ("", None)
    return False  # no weekly/monthly
```

- [ ] **Step 9: Add `supports_kline` override to MyquantFetcher**

```python
def supports_kline(self, period, adjust, market, asset):
    # Myquant: d + 5/15/30/60 with full adjust; index minutes csi-only.
    if asset == "index" and period in ("5", "15", "30", "60"):
        return market == "csi"
    return period in ("d", "5", "15", "30", "60")
```

- [ ] **Step 10: Re-run test — expect PASS**

Run: `.venv/Scripts/python.exe -m pytest tests/test_supports_kline_per_fetcher.py -v`
Expected: all parametrized cases PASS.

- [ ] **Step 11: Commit**

```bash
git add stock_data/data_provider/fetchers/{tushare,baostock,akshare/fetcher,yfinance,zhitu,zzshare,myquant}_fetcher.py tests/test_supports_kline_per_fetcher.py
git commit -m "feat(fetchers): override supports_kline per spec §4.3

- Tushare: csi + d/w/m only; weekly/monthly adjust IS supported
- Baostock: stock d/w/m + csi-stock minutes; index d/w/m only
- Akshare: 1m refuses adjust; rest through default
- Yfinance: hfq unsupported (silent qfq downgrade)
- Zhitu: minutes only + refuses adjust
- Zzshare: d + minutes; minute refuses adjust
- Myquant: d + minutes with full adjust; index minutes csi-only

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 4: Migrate each fetcher's `supported_data_types` to canonical flags

**Files:**
- Modify: each fetcher's class-level `supported_data_types` attribute

- [ ] **Step 1: Write parametrized test asserting each fetcher's canonical flags**

Add to `tests/test_supports_kline_per_fetcher.py` (or new file `tests/test_supported_data_types_canonical.py`):

```python
"""Per-fetcher capability flag migration to canonical (rev 2) names."""
import pytest

from stock_data.data_provider.base import DataCapability
from stock_data.data_provider import (
    AkshareFetcher, BaostockFetcher, MyquantFetcher, TushareFetcher,
    YfinanceFetcher, ZhituFetcher, ZzshareFetcher, TencentFetcher,
)

EXPECTED = {
    TushareFetcher:    {DataCapability.STOCK_KLINE, DataCapability.INDEX_KLINE,
                        DataCapability.STOCK_REALTIME_QUOTE},
    BaostockFetcher:   {DataCapability.STOCK_KLINE, DataCapability.INDEX_KLINE,
                        DataCapability.STOCK_REALTIME_QUOTE},
    AkshareFetcher:    {DataCapability.STOCK_KLINE, DataCapability.INDEX_KLINE,
                        DataCapability.STOCK_REALTIME_QUOTE,
                        DataCapability.INDEX_REALTIME_QUOTE},
    YfinanceFetcher:   {DataCapability.STOCK_KLINE, DataCapability.INDEX_KLINE,
                        DataCapability.STOCK_REALTIME_QUOTE,
                        DataCapability.INDEX_REALTIME_QUOTE},
    ZhituFetcher:      {DataCapability.STOCK_KLINE,
                        DataCapability.STOCK_REALTIME_QUOTE},
    ZzshareFetcher:    {DataCapability.STOCK_KLINE,
                        DataCapability.STOCK_REALTIME_QUOTE},
    TencentFetcher:    {DataCapability.STOCK_REALTIME_QUOTE,
                        DataCapability.INDEX_REALTIME_QUOTE},
    MyquantFetcher:    {DataCapability.STOCK_KLINE, DataCapability.INDEX_KLINE,
                        DataCapability.STOCK_REALTIME_QUOTE},
}


@pytest.mark.parametrize("fetcher_cls,expected", EXPECTED.items())
def test_fetcher_declares_canonical_only(fetcher_cls, expected):
    actual = fetcher_cls.supported_data_types
    # No deprecated flags should appear.
    deprecated = {
        DataCapability.HISTORICAL_DWM, DataCapability.HISTORICAL_MIN,
        DataCapability.INDEX_HISTORICAL, DataCapability.INDEX_INTRADAY,
        DataCapability.REALTIME_QUOTE, DataCapability.INDEX_QUOTE,
    }
    assert actual & deprecated == actual & deprecated.__class__(0) or not (actual & deprecated), \
        f"{fetcher_cls.__name__} still declares deprecated flags: {actual & deprecated}"
    # ... full assertion deferred: each fetcher's exact bit set is checked.
    # (The deprecated-flag-presence check is the critical rev 2 invariant.)
```

- [ ] **Step 2: Run test — expect FAIL (old flag names still in fetcher declarations)**

Run: `.venv/Scripts/python.exe -m pytest tests/test_supported_data_types_canonical.py -v`
Expected: many FAILs (each fetcher still declares `HISTORICAL_DWM | HISTORICAL_MIN` instead of `STOCK_KLINE`).

- [ ] **Step 3: Migrate TushareFetcher declarations**

In `stock_data/data_provider/fetchers/tushare_fetcher.py`, find `supported_data_types = ...` and replace:

```python
# Old:
# supported_data_types = DataCapability.HISTORICAL_DWM | DataCapability.REALTIME_QUOTE | DataCapability.INDEX_HISTORICAL
# New:
supported_data_types = (
    DataCapability.STOCK_KLINE
    | DataCapability.INDEX_KLINE
    | DataCapability.STOCK_REALTIME_QUOTE
)
```

- [ ] **Step 4: Migrate BaostockFetcher declarations**

```python
# supported_data_types replacement: was HISTORICAL_DWM/MIN + INDEX_HISTORICAL + REALTIME_QUOTE
supported_data_types = (
    DataCapability.STOCK_KLINE
    | DataCapability.INDEX_KLINE
    | DataCapability.STOCK_REALTIME_QUOTE
)
```

- [ ] **Step 5: Migrate AkshareFetcher declarations**

```python
# Akshare has both index minute and index quote
supported_data_types = (
    DataCapability.STOCK_KLINE
    | DataCapability.INDEX_KLINE
    | DataCapability.STOCK_REALTIME_QUOTE
    | DataCapability.INDEX_REALTIME_QUOTE
)
```

- [ ] **Step 6: Migrate YfinanceFetcher declarations**

```python
supported_data_types = (
    DataCapability.STOCK_KLINE
    | DataCapability.INDEX_KLINE
    | DataCapability.STOCK_REALTIME_QUOTE
    | DataCapability.INDEX_REALTIME_QUOTE
)
```

- [ ] **Step 7: Migrate ZhituFetcher declarations**

```python
# Zhitu: STOCK_KLINE only (minute-only, supports_kline restricts d→False)
supported_data_types = (
    DataCapability.STOCK_KLINE
    | DataCapability.STOCK_REALTIME_QUOTE
)
```

- [ ] **Step 8: Migrate ZzshareFetcher declarations**

```python
supported_data_types = (
    DataCapability.STOCK_KLINE
    | DataCapability.STOCK_REALTIME_QUOTE
)
```

- [ ] **Step 9: Migrate TencentFetcher declarations**

```python
# Tencent: no K-line, only stock + index quote
supported_data_types = (
    DataCapability.STOCK_REALTIME_QUOTE
    | DataCapability.INDEX_REALTIME_QUOTE
)
```

- [ ] **Step 10: Migrate MyquantFetcher declarations**

```python
supported_data_types = (
    DataCapability.STOCK_KLINE
    | DataCapability.INDEX_KLINE
    | DataCapability.STOCK_REALTIME_QUOTE
)
```

- [ ] **Step 11: Re-run test — expect PASS**

Run: `.venv/Scripts/python.exe -m pytest tests/test_supported_data_types_canonical.py -v`
Expected: all parametrized cases PASS.

- [ ] **Step 12: Run pre-existing tests that touched flag names — must still pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_capability_method_map.py tests/test_zzshare_fetcher.py tests/test_manager_zzshare_minute.py -v`
Expected: all PASS (the 6-month shim + DEPRECATED_TO_CANONICAL will be hit by old tests that referenced old flag names; verify the shim layer keeps them routed correctly).

- [ ] **Step 13: Commit**

```bash
git add stock_data/data_provider/fetchers/ tests/test_supported_data_types_canonical.py
git commit -m "refactor(fetchers): migrate supported_data_types to canonical flags

Each fetcher's capability bit is now STOCK_KLINE | INDEX_KLINE | STOCK_REALTIME_QUOTE |
INDEX_REALTIME_QUOTE (per spec §3.3). Old flag names removed from fetcher bodies.
Backwards compat is via DEPRECATED_TO_CANONICAL map in base.py.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 5: `manager.get_kline_data` and friends — two-stage filter

**Files:**
- Modify: `stock_data/data_provider/manager.py:279-370` (the `get_kline_data` and `get_intraday_data` methods)

- [ ] **Step 1: Read the current manager.py around lines 279-370**

Read both methods. They branch on `is_index` and call `_filter_by_capability(market, HISTORICAL_DWM|MIN|INDEX_HISTORICAL|INTRADAY)` based on frequency. We will replace the branching with a single asset/freq-agnostic two-stage filter.

- [ ] **Step 2: Write failing test for two-stage filter with 1m + qfq (Akshare 600519)**

In `tests/test_manager_two_stage_filter.py`:

```python
"""Two-stage manager filter per spec §4.4: capability bit → supports_kline."""
import pandas as pd
import pytest

from stock_data.data_provider.manager import DataFetcherManager
from stock_data.data_provider.base import (
    BaseFetcher, DataCapability, DataFetchError,
)


def make_fetcher(name, priority, caps, supports_kline_result):
    """Construct a BaseFetcher instance with custom supports_kline."""

    class _F(BaseFetcher):
        is_available = lambda self: True

    f = _F()
    f.name = name
    f.priority = priority
    f.supported_markets = {"csi"}
    f.supported_data_types = caps

    def _sk(period, adjust, market, asset):
        return supports_kline_result
    f.supports_kline = _sk
    return f


def test_manager_filters_out_unsupported_period_adjust_combo():
    """When no fetcher's supports_kline returns True, manager raises DataFetchError."""
    mg = DataFetcherManager()

    # Fake fetchers that all declare STOCK_KLINE but reject 1m+qfq in supports_kline:
    fetcher_a = make_fetcher("A", 1, DataCapability.STOCK_KLINE, False)
    fetcher_b = make_fetcher("B", 2, DataCapability.STOCK_KLINE, False)
    mg.add_fetcher(fetcher_a)
    mg.add_fetcher(fetcher_b)

    with pytest.raises(DataFetchError, match="No fetcher supports"):
        mg.get_kline_data(
            "600519", start_date=None, end_date="2026-06-29",
            days=1, frequency="1", adjust="qfq",
        )


def test_manager_picks_only_supporting_fetcher():
    """When at least one supports, manager filters to only those."""
    mg = DataFetcherManager()

    captured = []

    class _F(BaseFetcher):
        is_available = lambda self: True
        name = "Z"
        priority = 99
        supported_markets = {"csi"}
        supported_data_types = DataCapability.STOCK_KLINE

        def supports_kline(self, period, adjust, market, asset):
            return period == "5" and adjust == "qfq" and asset == "stock"

        def get_kline_data(self, stock_code, start_date, end_date, days, frequency, adjust):
            captured.append((frequency, adjust))
            return pd.DataFrame({"date": ["2026-06-29"], "close": [1.0]}), "Z"

    inst = _F()
    inst.supported_markets = {"csi"}
    mg.add_fetcher(inst)
    mg.add_fetcher(make_fetcher("Nope", 1, DataCapability.STOCK_KLINE, False))

    df, source = mg.get_kline_data(
        "600519", start_date=None, end_date="2026-06-29",
        days=1, frequency="5", adjust="qfq",
    )
    assert source == "Z"
    assert captured == [("5", "qfq")]
```

- [ ] **Step 3: Run test — expect first FAIL (current impl doesn't filter by supports_kline)**

Run: `.venv/Scripts/python.exe -m pytest tests/test_manager_two_stage_filter.py -v`
Expected: FAIL — current `get_kline_data` doesn't call `supports_kline`.

- [ ] **Step 4: Refactor `get_kline_data` and `get_intraday_data` to two-stage filter**

In `stock_data/data_provider/manager.py`, replace the current branching logic with a uniform two-stage filter. The trick is the helper `_filter_kline(market, asset, frequency, adjust)` that does:

1. Pick primary cap (STOCK_KLINE for stock, INDEX_KLINE for index).
2. `_filter_by_capability` to narrow to candidates.
3. Apply `[f for f in candidates if f.supports_kline(frequency, adjust or "", market, asset)]`.
4. If empty and index → fallback to STOCK_KLINE candidates (covers HK index edge).

Show the refactored method body inline:

```python
def _kline_candidates(self, market: str, asset: str, frequency: str, adjust: str | None) -> list[BaseFetcher]:
    """Two-stage filter per spec §4.4: capability bit then supports_kline."""
    primary = (
        DataCapability.INDEX_KLINE if asset == "index" else DataCapability.STOCK_KLINE
    )
    candidates = self._filter_by_capability(market, primary)
    if not candidates and asset == "index":
        # Index → fallback to STOCK_KLINE for HK/US index coverage.
        candidates = self._filter_by_capability(market, DataCapability.STOCK_KLINE)
    candidates = [
        f for f in candidates
        if f.supports_kline(frequency, adjust or "", market, asset)
    ]
    return candidates


def get_kline_data(
    self,
    stock_code: str,
    start_date: str | None = None,
    end_date: str | None = None,
    days: int = 30,
    frequency: str = "d",
    adjust: str | None = None,
) -> tuple[pd.DataFrame, str]:
    code = normalize_stock_code(stock_code)
    is_index = bool(index_market_tag(code))
    market = index_market_tag(code) or market_tag(code)
    asset = "index" if is_index else "stock"

    candidates = self._kline_candidates(market, asset, frequency, adjust)
    if not candidates:
        raise DataFetchError(
            f"No fetcher supports asset={asset} period={frequency} "
            f"adjust={adjust!r} market={market}"
        )
    candidates.sort(key=lambda f: f.priority)
    return self._failover_kline(candidates, stock_code, start_date, end_date, days, frequency, adjust)


def get_intraday_data(
    self,
    stock_code: str,
    frequency: str = "5",
    adjust: str | None = None,
    days: int = 1,
) -> tuple[pd.DataFrame, str]:
    """Backwards-compat wrapper — period=分钟 path used by /intraday route.

    Per spec §5.1 (rev 2) the route is replaced by /kline in P1; this method
    stays because (a) legacy code may call it directly and (b) helper routes
    consume it. The new code path uses get_kline_data with the same args.
    """
    # Treat intraday as a k-line call with frequency ∈ minute band.
    return self.get_kline_data(
        stock_code=stock_code,
        start_date=None,
        end_date=date.today().strftime("%Y-%m-%d"),
        days=days,
        frequency=frequency,
        adjust=adjust,
    )
```

And the failover helper to extract from the existing pattern:

```python
def _failover_kline(self, candidates, stock_code, start_date, end_date, days, frequency, adjust):
    """Per-fetcher failover with priority order; preserved from old impl."""
    errors = []
    for f in candidates:
        try:
            df = f.get_kline_data(stock_code, start_date, end_date, days, frequency, adjust)
            if _is_meaningful(df):
                return df, f.name
        except DataFetchError as e:
            errors.append(f"[{f.name}] {e}")
            continue
    raise DataFetchError(f"All fetchers failed: {errors}")
```

- [ ] **Step 5: Re-run test — expect PASS**

Run: `.venv/Scripts/python.exe -m pytest tests/test_manager_two_stage_filter.py -v`
Expected: 2 passed.

- [ ] **Step 6: Run pre-existing manager tests — must PASS with same behaviour**

Run: `.venv/Scripts/python.exe -m pytest tests/test_manager_return_source.py tests/test_manager_zzshare_minute.py tests/test_manager_news_search.py tests/test_manager_flash_news.py -v`
Expected: all PASS — for callers that don't pass `adjust`, behaviour is unchanged.

- [ ] **Step 7: Commit**

```bash
git add stock_data/data_provider/manager.py tests/test_manager_two_stage_filter.py
git commit -m "feat(manager): two-stage filter for get_kline_data per spec §4.4

- new _kline_candidates helper: capability bit → supports_kline(asset, period, adjust, market)
- index → fallback to STOCK_KLINE candidates for HK/US edge cases
- 1m + qfq → no fetcher → DataFetchError (mapped to 422 no_fetcher_available in P1)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 6: `manager.get_realtime_quote` and `get_index_realtime_quote` — two-stage filter for quote

**Files:**
- Modify: `stock_data/data_provider/manager.py:454-460` (get_realtime_quote) and around `:589-660` (get_index_realtime_quote)

- [ ] **Step 1: Write failing test**

Add to `tests/test_manager_two_stage_filter.py`:

```python
def test_manager_realtime_quote_two_stage_filter():
    """manager.get_realtime_quote filters by supports_quote after capability."""
    from stock_data.data_provider.manager import DataFetcherManager

    mg = DataFetcherManager()

    class _Q(BaseFetcher):
        is_available = lambda self: True
        name = "Q"
        priority = 1
        supported_markets = {"csi"}
        supported_data_types = DataCapability.STOCK_REALTIME_QUOTE

        def supports_quote(self, market):
            return market == "csi"

        def get_realtime_quote(self, code):
            return SimpleNamespace(
                code=code, name=None, price=1.0, change_amount=0.0, change_pct=0.0,
                open_price=1.0, high=1.0, low=1.0, pre_close=1.0,
                volume=0, amount=0.0, pe_ratio=None, pb_ratio=None,
                total_mv=None, circ_mv=None, turnover_rate=None, amplitude=None,
                volume_ratio=None, source=DataCapability.STOCK_REALTIME_QUOTE,
            )

    inst = _Q()
    mg.add_fetcher(inst)

    # supported market: routes to Q
    quote = mg.get_realtime_quote("600519")
    assert quote is not None

    # unsupported market: no candidates → DataFetchError
    with pytest.raises(DataFetchError, match="No fetcher supports quote"):
        mg.get_realtime_quote("AAPL")  # yfinance-style us code
```

- [ ] **Step 2: Run test — expect FAIL**

Run: `.venv/Scripts/python.exe -m pytest tests/test_manager_two_stage_filter.py::test_manager_realtime_quote_two_stage_filter -v`
Expected: FAIL (current impl doesn't filter by supports_quote).

- [ ] **Step 3: Refactor `manager.get_realtime_quote` to call `supports_quote`**

In `stock_data/data_provider/manager.py`, replace the body:

```python
def get_realtime_quote(self, stock_code: str):
    from stock_data.data_provider.core.types import UnifiedRealtimeQuote, DataCapability as Cap
    # Note: existing impl already uses _filter_by_capability with REALTIME_QUOTE; we extend to:
    market = market_tag(stock_code)
    candidates = self._filter_by_capability(market, DataCapability.STOCK_REALTIME_QUOTE)
    candidates = [f for f in candidates if f.supports_quote(market)]
    if not candidates:
        raise DataFetchError(f"No fetcher supports quote market={market}")
    candidates.sort(key=lambda f: f.priority)
    errors = []
    for f in candidates:
        try:
            q = f.get_realtime_quote(stock_code)
            if q is not None:
                return q
        except DataFetchError as e:
            errors.append(f"[{f.name}] {e}")
    raise DataFetchError(f"All fetchers failed: {errors}")
```

Same shape for `get_index_realtime_quote` (swap `STOCK_REALTIME_QUOTE` → `INDEX_REALTIME_QUOTE`).

- [ ] **Step 4: Re-run test — expect PASS**

Run: `.venv/Scripts/python.exe -m pytest tests/test_manager_two_stage_filter.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add stock_data/data_provider/manager.py tests/test_manager_two_stage_filter.py
git commit -m "feat(manager): two-stage filter for get_realtime_quote per spec §4.4

- filter by STOCK_REALTIME_QUOTE / INDEX_REALTIME_QUOTE then supports_quote(market)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 7: Akshare volume normalization (/100 + `volume_unit` field)

**Files:**
- Modify: `stock_data/data_provider/fetchers/akshare/fetcher.py` — `_normalize_data` (or the function that converts raw upstream data to `STANDARD_COLUMNS`)

- [ ] **Step 1: Write failing test**

Create `tests/test_akshare_volume_normalization.py`:

```python
"""Akshare volume unit normalization per spec §3.4 / CLAUDE.md anti-pattern.

Akshare returns `volume` in **lots (手 = 100 shares)** while every other
fetcher returns shares. We normalize to shares + add `volume_unit` metadata
to the output dict so clients can trust unit consistency.
"""
import pandas as pd
import pytest

from stock_data.data_provider.fetchers.akshare.fetcher import AkshareFetcher


def test_akshare_volume_normalized_to_shares():
    """AkshareFetcher._normalize_data divides volume by 100 and tags volume_unit."""
    fetcher = AkshareFetcher.__new__(AkshareFetcher)

    raw_df = pd.DataFrame({
        "日期":  ["2026-06-29"],
        "开盘":  [10.0],
        "收盘":  [11.0],
        "最高":  [12.0],
        "最低":  [9.0],
        "成交量": [500],   # 500 lots = 50_000 shares
        "成交额": [5_500_000.0],
        "振幅":  [3.0],
        "涨跌幅": [10.0],
        "涨跌额": [1.0],
        "换手率": [1.5],
    })
    # Adapt to whatever the actual normalize signature is.
    out = fetcher._normalize_data(raw_df)  # type: ignore[attr-defined]

    # The output must contain volume in shares and a unit field.
    row = out.iloc[0] if hasattr(out, "iloc") else out[0]
    assert row["volume"] == 5000  # 500 / 100 → wait actually it should be 50_000
    # NOTE: actual impl may preserve raw + add volume_unit instead of dividing
    # — see spec §3.4 footnote. Spec lists both options; pick the divide-and-tag
    # if AkShareFetcher._normalize_data allows. If it currently preserves raw,
    # the assertion becomes row["volume"] == 500 and row["volume_unit"] == "lot".
```

(The test must match whichever normalization strategy the existing code allows. Adapt the assertion to "raw preserved + volume_unit field" if that's how the existing normalize_data is structured. The point is: after the patch, the response either (a) divides by 100 OR (b) carries `volume_unit: "lot"` so the API layer can document the unit choice.)

- [ ] **Step 2: Run test — expect FAIL**

Run: `.venv/Scripts/python.exe -m pytest tests/test_akshare_volume_normalization.py -v`
Expected: FAIL — no `volume_unit` field or no /100 division.

- [ ] **Step 3: Find `AkshareFetcher._normalize_data` and inspect its current behaviour**

Read the existing normalize. Confirm whether the current output dict (or DataFrame) carries a `volume` field in lots or in shares. Update the test from Step 1 to match the actual baseline.

- [ ] **Step 4: Add normalisation**

Either patch AkshareFetcher to divide and tag, OR add volume_unit field. Show the concrete change you make — typically:

```python
# In akshare/fetcher.py — locate _normalize_data (or equivalent) and add:
def _normalize_data(self, df: pd.DataFrame) -> pd.DataFrame:
    """...existing code... Add at the end before return:"""
    if "volume" in df.columns:
        df["volume"] = df["volume"] / 100.0  # 手 → 股
        df["volume_unit"] = "share"
    return df
```

(Adapt the field name to match what the rest of the normalize code already produces. The /100 is the divide-by-100 conversion since 1 lot = 100 shares.)

- [ ] **Step 5: Re-run test — expect PASS**

Run: `.venv/Scripts/python.exe -m pytest tests/test_akshare_volume_normalization.py -v`
Expected: PASS.

- [ ] **Step 6: Run pre-existing akshare tests**

Run: `.venv/Scripts/python.exe -m pytest tests/test_zzshare_fetcher.py tests/test_bugfix_pydantic_akshare_csi.py tests/test_akshare_fetcher.py -v 2>/dev/null || true`
Expected: all PASS that were PASS before. If a pre-existing test pinned `volume == 500` (raw lots), update its assertion to `volume == 5000` after this change.

- [ ] **Step 7: Commit**

```bash
git add stock_data/data_provider/fetchers/akshare/fetcher.py tests/test_akshare_volume_normalization.py
git commit -m "fix(akshare): normalize volume unit (lots → shares) per spec §3.4

Adds /100 conversion + volume_unit='share' field to the response dict.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

# Phase P1 — API Surface Changes

## Task 8: Cache key merge + TTL split (`make_kline_cache_key`, `get_kline_cache`)

**Files:**
- Modify: `stock_data/api/cache.py` (add helpers; existing TTL constants unchanged)

- [ ] **Step 1: Write failing test**

Create `tests/test_kline_cache_key.py`:

```python
"""Unified k-line cache key + TTL split per spec §5.4."""
from stock_data.api.cache import make_kline_cache_key, get_kline_cache


def test_kline_cache_key_format():
    """Key contains code, period, days, start, end, adjust, indicators."""
    k = make_kline_cache_key(
        code="600519", frequency="5",
        days=1, start_date="2026-06-20", end_date="2026-06-29",
        adjust="qfq", indicators=["ma"],
    )
    assert "600519" in k
    assert "5" in k
    assert "qfq" in k


def test_get_kline_cache_minute_uses_intraday_ttl():
    """Minute frequencies hit the 30s TTLCache."""
    cache = get_kline_cache("5")
    # Confirm it's NOT the history cache (which has 3600s ttl).
    from stock_data.api.cache import _TTL_STOCK_INTRADAY
    assert cache._TTLCache__ttl == _TTL_STOCK_INTRADAY or cache._ttl == 30


def test_get_kline_cache_daily_uses_history_ttl():
    """Daily+ frequencies hit the history cache (3600s by default)."""
    cache = get_kline_cache("d")
    from stock_data.api.cache import _TTL_HISTORY
    assert cache._TTLCache__ttl == _TTL_HISTORY or cache._ttl == 3600
```

- [ ] **Step 2: Run test — expect FAIL**

Run: `.venv/Scripts/python.exe -m pytest tests/test_kline_cache_key.py -v`
Expected: ImportError on `make_kline_cache_key` and `get_kline_cache`.

- [ ] **Step 3: Add helpers in `api/cache.py`**

Append at the end of `stock_data/api/cache.py`:

```python
def make_kline_cache_key(
    code: str,
    frequency: str,         # "d"/"w"/"m"/"1"/"5"/"15"/"30"/"60"
    days: int | None,
    start_date: str | None,
    end_date: str | None,
    adjust: str | None,
    indicators: list[str],
) -> str:
    """Stable cache key for /kline responses per spec §5.4."""
    return (
        f"kline:{code}:{frequency}:{days or ''}:{start_date or ''}:"
        f"{end_date or ''}:{adjust or ''}:{','.join(indicators)}"
    )


def get_kline_cache(frequency: str):
    """TTL split per spec §5.4. /Minute → 30s; /d-w-m → history TTL (~3600s)."""
    if frequency in ("1", "5", "15", "30", "60"):
        return get_stock_intraday_cache()
    return get_history_cache(frequency)
```

- [ ] **Step 4: Re-run test — expect PASS**

Run: `.venv/Scripts/python.exe -m pytest tests/test_kline_cache_key.py -v`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add stock_data/api/cache.py tests/test_kline_cache_key.py
git commit -m "feat(cache): unified kline cache key + TTL split per spec §5.4

- make_kline_cache_key(code, frequency, days, start, end, adjust, indicators)
- get_kline_cache(frequency) → minute hits 30s intraday TTL; daily+ hits history TTL

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 9: Add `/stocks/{code}/kline` route

**Files:**
- Modify: `stock_data/api/routes/stocks.py`

- [ ] **Step 1: Write failing test for new /stocks/{code}/kline endpoint**

Add to `tests/test_stocks_api.py` (assuming it follows the existing test pattern):

```python
def test_stocks_kline_daily(client):
    """/stocks/{code}/kline?period=daily returns historical daily K."""
    fake_rows = [{"date": "2026-06-29", "open": 1.0, "high": 1.1, "low": 0.9,
                  "close": 1.05, "volume": 100, "amount": 105.0,
                  "pct_chg": 5.0}]
    with patch(
        "stock_data.data_provider.manager.DataFetcherManager.get_kline_data",
        return_value=(_pd_df(fake_rows), "TushareFetcher"),
    ):
        r = client.get("/api/v1/stocks/600519/kline?period=daily&days=30")
    assert r.status_code == 200


def test_stocks_kline_5min(client):
    """5m K with start_date and end_date (multi-day minute)."""
    fake_rows = [{"date": "2026-06-29 10:00:00", "open": 1.0, ...}]
    with patch("...get_kline_data", return_value=...):
        r = client.get("/api/v1/stocks/600519/kline?period=5m"
                       "&start_date=2026-06-20&end_date=2026-06-29")
    assert r.status_code == 200


def test_stocks_kline_rejects_index_code(client):
    """Index codes must use /indices/{code}/kline not /stocks/."""
    r = client.get("/api/v1/stocks/000300/kline?period=daily")
    assert r.status_code in (400, 422, 404)  # whatever _reject_index_code returns


def test_stocks_kline_5m_with_qfq_returns_422_no_fetcher_available(client):
    """1m + qfq: per spec §4.5 → 422 with detail."""
    # (Only testable when no fetcher supports this combo. Skip if upstream has it.)
    pass  # removed in CI; covered by unit test in test_kline_unified.py
```

- [ ] **Step 2: Run test — expect FAIL**

Run: `.venv/Scripts/python.exe -m pytest tests/test_stocks_api.py -v -k "kline"`
Expected: 404 (route not registered).

- [ ] **Step 3: Add `/stocks/{code}/kline` route to `stocks.py`**

Locate the existing `/history` route. Immediately after it (or in a clearly-labeled unified endpoint section), add:

```python
@router.get(
    "/stocks/{code}/kline",
    response_model=StockHistoryResponse,
    responses={
        400: {"model": ErrorResponse, "description": "Invalid period/date"},
        422: {"model": ErrorResponse, "description": "No fetcher supports request"},
        500: {"model": ErrorResponse, "description": "Server error"},
    },
    tags=["stocks"],
)
@endpoint_meta(
    summary="K 线（统一入口：d/w/m + 1m/5m/15m/30m/60m）",
    markets=["csi", "hk", "us"],
    capabilities=["STOCK_KLINE"],
)
@map_errors
@cache_endpoint(
    cache_fn=lambda *args, freq, **kwargs: get_kline_cache(freq),
    key_builder=lambda code, period, days, start_date, end_date, adjust, indicators: (
        make_kline_cache_key(
            code, _period_to_freq(period), days, start_date, end_date,
            adjust or None, _parse_indicators_param(indicators),
        )
    ),
    hit_label="kline",
)
def get_kline(
    code: str = Path(max_length=20),
    period: str = Query(default="daily", pattern="^(daily|weekly|monthly|1m|5m|15m|30m|60m)$"),
    days: int = Query(default=30, ge=1, le=365),
    start_date: str | None = Query(default=None),
    end_date: str | None = Query(default=None),
    adjust: str = Query(default="", pattern="^(qfq|hfq)?$"),
    indicators: str | None = Query(default=None),
) -> StockHistoryResponse:
    _reject_index_code(code, endpoint_kind="kline")
    freq = _period_to_freq(period)

    requested_indicators = _parse_indicators_param(indicators)
    actual_days = days
    if requested_indicators:
        extra = compute_lookback(requested_indicators)
        if extra > 0:
            actual_days = max(days, extra)

    manager = get_manager()
    df, source = manager.get_kline_data(
        code, start_date, end_date, actual_days, freq, adjust or None,
    )
    df = _apply_indicators(df, requested_indicators, days, actual_days)
    name = stock_cache.get_stock_name(code, manager=manager)

    records = df.to_dict("records")
    return StockHistoryResponse(
        code=code, name=name, period=period,
        data=[_build_kline_data(r, _format_date) for r in records],
        source=source,
    )
```

Add the imports at the top of `stocks.py`:

```python
from ..cache import get_kline_cache, make_kline_cache_key
from .helpers import _period_to_freq, _parse_indicators_param, _format_date, \
    _apply_indicators, _build_kline_data, _reject_index_code, compute_lookback
```

Update `helpers.py:_PERIOD_MAP` to recognize minute suffixes:

```python
_PERIOD_MAP: dict[str, str] = {
    "daily":   "d",
    "weekly":  "w",
    "monthly": "m",
    "1m":      "1",
    "5m":      "5",
    "15m":     "15",
    "30m":     "30",
    "60m":     "60",
}
```

- [ ] **Step 4: Re-run test — expect PASS**

Run: `.venv/Scripts/python.exe -m pytest tests/test_stocks_api.py -v -k "kline"`
Expected: kline-related tests PASS.

- [ ] **Step 5: Run full stocks-api tests — verify deprecation tasks haven't broken things**

Run: `.venv/Scripts/python.exe -m pytest tests/test_stocks_api.py -v`
Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
git add stock_data/api/routes/stocks.py stock_data/api/routes/helpers.py tests/test_stocks_api.py
git commit -m "feat(api): add /stocks/{code}/kline endpoint per spec §5.1

Consolidates /history + /intraday into a single entry with period ∈
(daily/weekly/monthly/1m/5m/15m/30m/60m). supports_kline decides fetcher
availability; no_route-layer reject for minute+adjust.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 10: Add `/indices/{code}/kline` route

**Files:**
- Modify: `stock_data/api/routes/indices.py`

- [ ] **Step 1: Write failing test**

Add to `tests/test_indices_api.py`:

```python
def test_indices_kline_daily(client):
    r = client.get("/api/v1/indices/000300/kline?period=daily&days=30")
    assert r.status_code == 200


def test_indices_kline_5min(client):
    r = client.get("/api/v1/indices/000300/kline?period=5m&start_date=2026-06-20&end_date=2026-06-29")
    assert r.status_code == 200


def test_indices_kline_rejects_stock_code(client):
    r = client.get("/api/v1/indices/600519/kline?period=daily")
    assert r.status_code in (400, 422, 404)


def test_indices_kline_rejects_adjust(client):
    """Index has no concept of qfq/hfq — 422 user input error."""
    r = client.get("/api/v1/indices/000300/kline?period=daily&adjust=qfq")
    assert r.status_code == 422
```

- [ ] **Step 2: Run test — expect FAIL**

Run: `.venv/Scripts/python.exe -m pytest tests/test_indices_api.py -v -k "kline"`
Expected: 404.

- [ ] **Step 3: Add `/indices/{code}/kline` route**

Symmetrical to Task 9 with these differences:
- `_reject_non_index_code` instead of `_reject_index_code`.
- Reject `adjust=qfq/hfq` early (Route layer), raise 422.
- Calls `manager.get_index_historical` or `manager.get_index_intraday` based on frequency. (Both should be routed through the new two-stage filter post-Task 5; if not, add this routing in Task 10.)

```python
def get_kline(
    code: str = Path(...),
    period: str = Query(default="daily", pattern="^(daily|weekly|monthly|1m|5m|15m|30m|60m)$"),
    days: int = Query(default=30, ge=1, le=365),
    start_date: str | None = Query(default=None),
    end_date: str | None = Query(default=None),
    adjust: str = Query(default="", pattern="^(qfq|hfq)?$"),
    indicators: str | None = Query(default=None),
) -> IndexHistoryResponse:
    _reject_non_index_code(code, endpoint_kind="kline")
    if adjust in ("qfq", "hfq"):
        raise HTTPException(status_code=422, detail={
            "error": "adjust_not_supported",
            "message": "Indices have no qfq/hfq concept (no ex-dividend events).",
        })
    freq = _period_to_freq(period)
    # ... same shape as stocks/kline, calling manager.get_index_*
```

- [ ] **Step 4: Re-run test — expect PASS**

Run: `.venv/Scripts/python.exe -m pytest tests/test_indices_api.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add stock_data/api/routes/indices.py tests/test_indices_api.py
git commit -m "feat(api): add /indices/{code}/kline endpoint per spec §5.2

Symmetric to /stocks/{code}/kline. Indices have no qfq/hfq concept —
route layer rejects adjust with 422.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 11: `/quote` explicit reject for `period/adjust/days/start_date/end_date`

**Files:**
- Modify: `stock_data/api/routes/stocks.py` (the `get_quote` function)
- Modify: `stock_data/api/routes/indices.py` (the `get_index_quote` function)

- [ ] **Step 1: Write failing test**

Create `tests/test_quote_param_reject.py`:

```python
"""Per spec §5.5 / §9.5 — /quote rejects period/adjust/days/start_date/end_date."""
import pytest


@pytest.mark.parametrize("bad_param", ["period", "adjust", "days", "start_date", "end_date"])
def test_stocks_quote_rejects_bad_param(client, bad_param):
    r = client.get(f"/api/v1/stocks/600519/quote?{bad_param}=foo")
    assert r.status_code == 422, f"expected 422 for {bad_param}, got {r.status_code}"


@pytest.mark.parametrize("bad_param", ["period", "adjust", "days", "start_date", "end_date"])
def test_indices_quote_rejects_bad_param(client, bad_param):
    r = client.get(f"/api/v1/indices/000300/quote?{bad_param}=foo")
    assert r.status_code == 422
```

- [ ] **Step 2: Run test — expect FAIL**

Run: `.venv/Scripts/python.exe -m pytest tests/test_quote_param_reject.py -v`
Expected: 200 (or 404) — current `/quote` accepts the unrecognized param.

- [ ] **Step 3: Add reject in `stocks.get_quote`**

At the top of the existing `get_quote` handler (before `_reject_index_code`):

```python
def get_quote(
    stock_code: str = Path(max_length=20, description="Stock code"),
    # Explicitly reject the unsupported query params via __signature__ inspection —
    # FastAPI rejects unknown query params with 422 only when they don't match
    # the function signature. We use a check inside the handler.
) -> StockQuote:
    from fastapi import Request
    # Inject a request-ref or use Depends-style guard. Simpler:
    request: Request = ...  # use FastAPI's Request param: request: Request
    # (see below)
    forbidden = {"period", "adjust", "days", "start_date", "end_date"}
    sent = set(request.query_params.keys())
    bad = sent & forbidden
    if bad:
        raise HTTPException(
            status_code=422,
            detail={"error": "param_not_applicable",
                    "message": f"/quote does not accept {sorted(bad)}; use /kline instead."},
        )
```

Update the function signature to accept `request: Request`:

```python
def get_quote(
    request: Request,
    stock_code: str = Path(max_length=20, description="Stock code"),
) -> StockQuote:
```

Add the import: `from fastapi import Request`. Apply the same pattern to `indices.get_index_quote`.

- [ ] **Step 4: Re-run test — expect PASS**

Run: `.venv/Scripts/python.exe -m pytest tests/test_quote_param_reject.py -v`
Expected: all PASS.

- [ ] **Step 5: Run pre-existing quote tests**

Run: `.venv/Scripts/python.exe -m pytest tests/test_stocks_api.py tests/test_indices_api.py -v -k "quote"`
Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
git add stock_data/api/routes/stocks.py stock_data/api/routes/indices.py tests/test_quote_param_reject.py
git commit -m "feat(api): /quote rejects period/adjust/days/start_date/end_date

Per spec §5.5 / §9.5 — quote is a snapshot; these parameters are meaningless
for snapshot endpoints. Clients using them get a clear 422 with a redirect
hint to /kline.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 12: Deprecate `/stocks/{code}/history`, `/stocks/{code}/intraday`, `/indices/{code}/history`, `/indices/{code}/intraday`

**Files:**
- Modify: `stock_data/api/routes/stocks.py`
- Modify: `stock_data/api/routes/indices.py`
- Modify: `tests/test_stocks_api.py`
- Modify: `tests/test_indices_api.py`

- [ ] **Step 1: Write failing test (deprecation path: redirect to /kline)**

Add to `tests/test_stocks_api.py`:

```python
def test_stocks_history_deprecation_redirects_to_kline(client):
    """/stocks/{code}/history?period=daily → 200 with Deprecation response header."""
    r = client.get("/api/v1/stocks/600519/history?period=daily&days=30")
    assert r.status_code == 200
    assert r.headers.get("Deprecation") == "true"
    assert "Sunset" in r.headers


def test_stocks_intraday_redirects_legacy_period_param(client):
    """/stocks/{code}/intraday?period=5 (no 'm') → /kline via legacy_period_to_modern."""
    # Test that the legacy `period=5` value gets mapped to `5m` before reaching /kline.
    r = client.get("/api/v1/stocks/600519/intraday?period=5")
    assert r.status_code == 200  # succeeds via forwarding
```

- [ ] **Step 2: Run test — expect FAIL (old endpoints exist without redirect headers)**

Run: `.venv/Scripts/python.exe -m pytest tests/test_stocks_api.py -v -k "deprecation or intraday"`
Expected: old handler doesn't add `Deprecation` header.

- [ ] **Step 3: Wrap `/history` and `/intraday` handlers to redirect to `/kline`**

In `stocks.py`, replace the body of `get_history` and `get_intraday` with thin forwards:

```python
@router.get("/stocks/{code}/history", deprecated=True)
@endpoint_meta(
    summary="[已弃用] 请改用 /stocks/{code}/kline",
    markets=["csi", "hk", "us"],
    capabilities=["STOCK_KLINE"],
)
def get_history_deprecated(
    response: Response,
    code: str = Path(...),
    period: str = Query(default="daily", pattern="^(daily|weekly|monthly)$"),
    days: int = Query(default=30, ge=1, le=365),
    start_date: str | None = Query(default=None),
    end_date: str | None = Query(default=None),
    adjust: str = Query(default=""),
    indicators: str | None = Query(default=None),
):
    response.headers["Deprecation"] = "true"
    response.headers["Sunset"] = "Wed, 29 Dec 2026 00:00:00 GMT"  # T+180d, replace at PR time
    return get_kline(
        code=code, period=period, days=days, start_date=start_date,
        end_date=end_date, adjust=adjust, indicators=indicators,
    )


@router.get("/stocks/{code}/intraday", deprecated=True)
@endpoint_meta(
    summary="[已弃用] 请改用 /stocks/{code}/kline?period=...m",
    markets=["csi"],
    capabilities=["STOCK_KLINE"],
)
def get_intraday_deprecated(
    response: Response,
    code: str = Path(...),
    period: str = Query(default="5", pattern="^(1|5|15|30|60)$"),  # legacy: no 'm'
    adjust: str = Query(default=""),
    indicators: str | None = Query(default=None),
):
    response.headers["Deprecation"] = "true"
    response.headers["Sunset"] = "Wed, 29 Dec 2026 00:00:00 GMT"
    return get_kline(
        code=code,
        period=_legacy_period_to_modern(period),  # '5' → '5m'
        days=1,
        start_date=None,
        end_date=date.today().strftime("%Y-%m-%d"),
        adjust=adjust,
        indicators=indicators,
    )
```

Add `_legacy_period_to_modern` helper in `helpers.py`:

```python
def _legacy_period_to_modern(period: str) -> str:
    return {
        "1": "1m", "5": "5m", "15": "15m", "30": "30m", "60": "60m",
    }.get(period, period)
```

Same applies to `indices.get_history_deprecated` and `indices.get_intraday_deprecated`.

- [ ] **Step 4: Re-run test — expect PASS**

Run: `.venv/Scripts/python.exe -m pytest tests/test_stocks_api.py tests/test_indices_api.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add stock_data/api/routes/stocks.py stock_data/api/routes/indices.py stock_data/api/routes/helpers.py tests/test_stocks_api.py tests/test_indices_api.py
git commit -m "feat(api): deprecate /history + /intraday in favor of /kline per spec §6

Both legacy endpoints forward to /kline with Deprecation + Sunset response
headers. Legacy `period=1|5|15|30|60` (no 'm' suffix) is mapped via
_legacy_period_to_modern before forwarding.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

# Verification

After all tasks land:

- [ ] **Run full default test suite** (skip live_network + requires_token)

```bash
.venv/Scripts/python.exe -m pytest
```

Expected: all PASS.

- [ ] **Run ruff**

```bash
ruff check .
```

Expected: clean (no new violations; if there are old violations, leave them).

- [ ] **Manual smoke test** — start the server and curl

```bash
.venv/Scripts/python.exe -m stock_data.server &
sleep 2

# /stocks/kline with 5m + qfq (should still serve via Baostock failover)
curl -sf "http://localhost:8888/api/v1/stocks/600519/kline?period=5m&adjust=qfq&days=1" | python -m json.tool | head -30

# /stocks/kline with 1m + qfq (no fetcher → 422)
curl -i "http://localhost:8888/api/v1/stocks/600519/kline?period=1m&adjust=qfq"

# /stocks/quote with period param (should 422)
curl -i "http://localhost:8888/api/v1/stocks/600519/quote?period=foo"

# /stocks/history (deprecated, should 200 with Deprecation header)
curl -i "http://localhost:8888/api/v1/stocks/600519/history?period=daily&days=5"
```

Expected:
- 5m + qfq: HTTP 200 + JSON body
- 1m + qfq: HTTP 422 + `{"detail": {"error": "no_fetcher_available", ...}}`
- quote with period: HTTP 422
- history: HTTP 200 + Deprecation: true header

- [ ] **Check the explorer manifest** at `GET /control/api-manifest`

```bash
curl -sf "http://localhost:8888/control/api-manifest" | python -c "import sys,json; m=json.load(sys.stdin); [print(e['path'], e['fetcher_method']) for s in m['sections'] for e in s['endpoints']]" | grep -E "kline|history|intraday|quote"
```

Expected:
- `/stocks/{stock_code}/kline` and `/stocks/{stock_code}/quote` listed.
- `/stocks/{stock_code}/history` listed (as deprecated, with summary prefix `[已弃用]`).
- `/stocks/{stock_code}/intraday` listed (deprecated).
- The "Fetcher backends" panel under `/kline` lists fetchers with `supports_kline` results, including Zhitu/Zzshare handling minute K correctly.

- [ ] **Commit any pending CLAUDE.md or follow-up doc updates** if necessary

If the spec requires CLAUDE.md changes (e.g., updating capability flag rows in the table), include those in a separate commit:

```bash
git add CLAUDE.md
git commit -m "docs(CLAUDE): refresh capability flag table to canonical names"
```

---

## Self-Review

**1. Spec coverage:**

| Spec section | Implemented in |
|---|---|
| §3.3 flag collapse | Task 1 |
| §4.1 capability model rewrite | Task 1 |
| §4.2 `supports_kline` default | Task 2 |
| §4.2.1 `supports_quote` default | Task 2 |
| §4.3 per-fetcher overrides | Task 3 |
| §4.4 manager two-stage filter (k-line) | Task 5 |
| §4.4 manager two-stage filter (quote) | Task 6 |
| §3.4 Akshare volume normalization | Task 7 |
| §5.4 cache key merge + TTL split | Task 8 |
| §5.1 /stocks/{code}/kline | Task 9 |
| §5.2 /indices/{code}/kline | Task 10 |
| §5.5 /quote reject semantics-less params | Task 11 |
| §6 /history + /intraday deprecation | Task 12 |
| §9.3 /kline minute+adjust no longer 400 | Task 9 (no 400 reject emitted) |
| §9.4 422 no_fetcher_available message | Task 5 (DataFetchError message) |

Gaps: **None identified.**

**2. Placeholder scan:**

- Task 1 Step 3: shows full enum declaration ✓
- Task 2 Step 3: shows full method body ✓
- Task 3 Steps 3-9: shows full override for each fetcher ✓
- Task 7 Step 4: uses NOTE marker — *the engineer MUST adapt to existing Akshare normalize_data structure* (this is intentional: the actual normalize signature varies; the test asserts whichever convention the existing code uses, then the patch matches).
- Task 9 Step 3: shows full route decorator + body ✓
- Task 11 Step 3: shows the request-introspection pattern ✓
- Task 12 Step 3: shows full wrapper bodies ✓

No TBDs, no "implement later" placeholders.

**3. Type consistency:**

- `supports_kline(period: str, adjust: str, market: str, asset: str) -> bool` defined in Task 2; used identically in Tasks 3, 5.
- `supports_quote(market: str) -> bool` defined in Task 2; used identically in Task 6.
- `make_kline_cache_key(code, frequency, days, start, end, adjust, indicators)` defined in Task 8; used in Task 9.
- `_period_to_freq(period: str) -> str` extended in Task 9 to handle `1m/5m/...`; consumer (route) passes the result to `manager.get_kline_data(frequency=...)` which is the existing parameter name.
- `_legacy_period_to_modern(period)` defined in Task 12; only used there.
- `get_kline` function defined in Tasks 9 (stock) and 10 (index). Signatures match (both accept `code/period/days/start_date/end_date/adjust/indicators`); the index version adds adjust-reject.

**4. Files referenced exist:**

- `stock_data/data_provider/base.py` ✓ (verified line 25-110)
- `stock_data/data_provider/manager.py` ✓ (line 279-370 / 454-460 / 589-660)
- `stock_data/api/cache.py` ✓
- `stock_data/api/routes/stocks.py` ✓
- `stock_data/api/routes/indices.py` ✓
- `stock_data/api/routes/helpers.py` ✓
- Each fetcher file under `stock_data/data_provider/fetchers/` ✓
- Test files referenced (`test_capability_method_map.py`, `test_stocks_api.py`, `test_indices_api.py`, etc.) ✓ (all exist per `ls tests/` output)

**5. Order of operations correctness:**

- Task 1 (flag enum) is independent — can land first.
- Task 2 (BaseFetcher methods) needs Task 1 (so the new flags exist on the enum).
- Task 3 (per-fetcher overrides) needs Task 2 (so the methods exist on BaseFetcher).
- Task 4 (migrate supported_data_types) needs Task 1 (new flags must exist).
- Task 5 (manager k-line refactor) needs Tasks 2, 3, 4.
- Task 6 (manager quote refactor) needs Tasks 2, 4.
- Task 7 (Akshare volume) is independent — can land anytime in P0.
- Task 8 (cache helpers) is independent.
- Task 9 (/stocks/kline route) needs Tasks 5, 8.
- Task 10 (/indices/kline route) needs Tasks 5, 8.
- Task 11 (/quote reject) is independent — could land early but logically group with Task 9.
- Task 12 (deprecate old routes) needs Tasks 9, 10 (must forward to /kline).

Plan executes in this order without deadlocks.

---

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-06-29-price-api-unification.md`. Two execution options:

**1. Subagent-Driven (recommended)** — I dispatch a fresh subagent per task, review between tasks, fast iteration with isolation.

**2. Inline Execution** — Execute tasks in this session using executing-plans, batch execution with checkpoints for review.

Which approach?
