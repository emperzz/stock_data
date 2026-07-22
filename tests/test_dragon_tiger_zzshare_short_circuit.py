"""Verify that when ZzshareFetcher (P2) returns an empty result for
``get_daily_dragon_tiger`` / ``get_dragon_tiger``, the manager treats the
empty answer as "no data" and falls through to the next fetcher
(EastMoney P6) — the empty result must NOT short-circuit the failover
chain.

Why:  Zzshare is the P2 primary for ``DRAGON_TIGER``, but its return
shape (``{"date", "total", "stocks": []}``) is a dict — and the manager's
``_is_meaningful`` helper historically treats *any* non-None dict as
meaningful, so an empty dict slipped through as a "success". The fix
opts the dragon-tiger call sites into ``empty_is_failure=True``, which
adds a "structurally empty" check: a dict whose list/dict values are all
empty is treated as a soft failure and the chain continues.

EastMoney is the documented fallback (different coverage, different
field shape — see ``zzshare_fetcher.get_daily_dragon_tiger`` docstring
§"Field-mapping notes"). The corrected contract is:

- zzshare returns a populated dict → source = "zzshare", never call
  EastMoney (priority + short-circuit on meaningful result).
- zzshare returns an empty dict → fall through to EastMoney. If
  EastMoney also returns empty, raise ``DataFetchError`` (or return
  empty via ``last_empty_result`` when all candidates returned empty
  without raising).

See ``/api/v1/dragon-tiger`` route: ``routes/data.py::get_daily_dragon_tiger``.
"""

import pandas as pd

from stock_data.data_provider.base import BaseFetcher, DataCapability, DataFetchError


class _FakeDragonTigerFetcher(BaseFetcher):
    """Minimal BaseFetcher that records calls and returns a configured value."""

    def is_available(self) -> bool:
        return True

    def __init__(self, name: str, priority: int, return_value):
        self.name = name
        self.priority = priority
        self.supported_markets = {"csi"}
        self.supported_data_types = DataCapability.DRAGON_TIGER
        self._return_value = return_value
        self.call_count = 0

    def _fetch_raw_data(self, stock_code, start_date, end_date, frequency="d", adjust=None):
        return pd.DataFrame()

    def _normalize_data(self, df, stock_code):
        return df

    def get_daily_dragon_tiger(self, trade_date="", min_net_buy=None):
        self.call_count += 1
        return self._return_value

    def get_dragon_tiger(self, code: str, trade_date: str = ""):
        self.call_count += 1
        return self._return_value


def _build_manager(zzshare_return, eastmoney_return):
    """Return (manager, zzshare_fake, eastmoney_fake) — both pre-wired."""
    from stock_data.data_provider.manager import DataFetcherManager

    zzshare = _FakeDragonTigerFetcher("ZzshareFetcher", 2, zzshare_return)
    eastmoney = _FakeDragonTigerFetcher("EastMoneyFetcher", 6, eastmoney_return)
    mgr = DataFetcherManager()
    mgr.add_fetcher(zzshare)
    mgr.add_fetcher(eastmoney)
    return mgr, zzshare, eastmoney


# ---------- /api/v1/dragon-tiger (全市场) ----------


def test_daily_dragon_tiger_zzshare_empty_falls_through_to_eastmoney():
    """zzshare returns an empty dict → manager treats it as 'no data',
    falls through to EastMoney, source is reported as 'EastMoneyFetcher'."""
    empty_daily = {"date": "2026-07-21", "total": 0, "stocks": []}
    eastmoney_daily = {
        "date": "2026-07-21",
        "total": 1,
        "stocks": [
            {
                "code": "000001",
                "name": "X",
                "reason": "r",
                "change_pct": 0.0,
                "net_buy_wan": 0.0,
                "turnover_pct": 0.0,
            }
        ],
    }
    mgr, zzshare, eastmoney = _build_manager(
        zzshare_return=empty_daily,
        eastmoney_return=eastmoney_daily,
    )

    data, source = mgr.get_daily_dragon_tiger("2026-07-21", None)

    assert source == "EastMoneyFetcher", f"expected eastmoney fallback, got {source!r}"
    assert data == eastmoney_daily
    assert zzshare.call_count == 1, "zzshare should be tried first"
    assert eastmoney.call_count == 1, (
        f"eastmoney should be called when zzshare returns empty; got {eastmoney.call_count} calls"
    )


def test_daily_dragon_tiger_zzshare_populated_short_circuits():
    """zzshare returns a populated dict → manager short-circuits with
    source='zzshare' and never calls EastMoney. Locks in the priority
    order Zzshare (P2) → EastMoney (P6)."""
    full_daily = {
        "date": "2026-07-21",
        "total": 1,
        "stocks": [
            {
                "code": "600519",
                "name": "Kweichow",
                "reason": "r",
                "change_pct": 10.0,
                "net_buy_wan": 1.0,
                "turnover_pct": 0.0,
            }
        ],
    }
    mgr, zzshare, eastmoney = _build_manager(
        zzshare_return=full_daily,
        eastmoney_return={"date": "2026-07-21", "total": 99, "stocks": []},
    )

    data, source = mgr.get_daily_dragon_tiger("2026-07-21", None)

    assert source == "ZzshareFetcher"
    assert data == full_daily
    assert zzshare.call_count == 1
    assert eastmoney.call_count == 0


def test_daily_dragon_tiger_both_empty_raises():
    """When BOTH fetchers return empty (no candidate has data), the manager
    must NOT silently return a misleading empty result — it raises
    DataFetchError. The 'last_empty_result' path is gated on
    empty_is_failure semantics: with empty_is_failure=True, empty counts
    as failure, so errors aggregate and the caller sees an explicit error."""
    empty = {"date": "2026-07-21", "total": 0, "stocks": []}
    mgr, zzshare, eastmoney = _build_manager(
        zzshare_return=empty,
        eastmoney_return=empty,
    )

    import pytest

    with pytest.raises(DataFetchError):
        mgr.get_daily_dragon_tiger("2026-07-21", None)

    assert zzshare.call_count == 1
    assert eastmoney.call_count == 1


def test_daily_dragon_tiger_zzshare_raises_then_eastmoney_serves():
    """Regression guard: when zzshare raises (not returns empty), eastmoney
    IS used as fallback. Distinct from the empty-result fall-through —
    exceptions still cascade."""
    eastmoney_populated = {
        "date": "2026-07-21",
        "total": 1,
        "stocks": [
            {
                "code": "000001",
                "name": "X",
                "reason": "r",
                "change_pct": 0.0,
                "net_buy_wan": 0.0,
                "turnover_pct": 0.0,
            }
        ],
    }
    mgr, zzshare, eastmoney = _build_manager(
        zzshare_return=None,  # sentinel; we patch below
        eastmoney_return=eastmoney_populated,
    )

    def _raise(*a, **kw):
        zzshare.call_count += 1
        raise RuntimeError("simulated zzshare outage")

    zzshare.get_daily_dragon_tiger = _raise  # type: ignore[assignment]

    data, source = mgr.get_daily_dragon_tiger("2026-07-21", None)

    assert source == "EastMoneyFetcher"
    assert data == eastmoney_populated
    assert zzshare.call_count == 1
    assert eastmoney.call_count == 1


# ---------- /stocks/{code}/dragon-tiger (个股) ----------


def test_dragon_tiger_zzshare_empty_falls_through_to_eastmoney():
    """Same contract for the per-stock variant: empty records from zzshare
    → fall through to EastMoney. EastMoneyFetcher.get_dragon_tiger
    returns a dict shaped {records[], seats{institution}, institution{}} —
    empty means records==[]."""
    empty_per_stock = {
        "records": [],
        "seats": {"buy": [], "sell": []},
        "institution": {},
    }
    eastmoney_per_stock = {
        "records": [{"date": "2026-07-21", "reason": "r", "net_buy_wan": 0.0, "turnover_pct": 0.0}],
        "seats": {"buy": [], "sell": []},
        "institution": {},
    }
    mgr, zzshare, eastmoney = _build_manager(
        zzshare_return=empty_per_stock,
        eastmoney_return=eastmoney_per_stock,
    )

    data, source = mgr.get_dragon_tiger("600519", "2026-07-21")

    assert source == "EastMoneyFetcher", f"expected eastmoney fallback, got {source!r}"
    assert data == eastmoney_per_stock
    assert zzshare.call_count == 1
    assert eastmoney.call_count == 1


def test_dragon_tiger_zzshare_populated_short_circuits():
    """zzshare returns a populated per-stock dict → short-circuits,
    EastMoney not called."""
    full_per_stock = {
        "records": [{"date": "2026-07-21", "reason": "r", "net_buy_wan": 1.0, "turnover_pct": 0.0}],
        "seats": {
            "buy": [{"name": "X", "buy_wan": 1.0, "sell_wan": 0.0, "net_wan": 1.0}],
            "sell": [],
        },
        "institution": {},
    }
    mgr, zzshare, eastmoney = _build_manager(
        zzshare_return=full_per_stock,
        eastmoney_return={"records": [], "seats": {"buy": [], "sell": []}, "institution": {}},
    )

    data, source = mgr.get_dragon_tiger("600519", "2026-07-21")

    assert source == "ZzshareFetcher"
    assert data == full_per_stock
    assert zzshare.call_count == 1
    assert eastmoney.call_count == 0
