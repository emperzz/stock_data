"""
Failover integration tests for the gap-fix endpoints:

- /stocks/{code}/dividend           →  DIVIDEND    failover: Baostock → Zhitu → EastMoney
- /stocks/{code}/fund-flow          →  FUND_FLOW   failover: Zhitu → EastMoney
- /stocks/{code}/fund-flow/daily    →  FUND_FLOW   (same chain, different method)
- /stocks/{code}/holder-num         →  HOLDER_NUM  failover: Zhitu → EastMoney

Each test wires the manager with only the relevant fetchers (priority order
matches the production failover chain), patches the fetcher methods to
either succeed / raise / return-empty, and asserts:
1. The correct fetcher is selected as the source.
2. Lower-priority fetchers are NOT called when a higher-priority one wins.
3. Failure of upstream fetcher transparently falls back to the next.
4. ``page_size`` is propagated to whichever fetcher ends up handling the call.

Pattern adapted from ``tests/test_manager_flash_news.py::TestFlashNewsFailover``
which already validates the same failover semantics for ``get_flash_news``.
The motivating bug we're guarding against here is: "EastMoney is the only
source for DIVIDEND/FUND_FLOW/HOLDER_NUM, so any EastMoney outage becomes a
server-wide 503". After the gap-fix, Baostock + Zhitu provide backup.
"""

from unittest.mock import patch

import pytest

from stock_data.data_provider.base import DataFetchError
from stock_data.data_provider.fetchers.baostock_fetcher import BaostockFetcher
from stock_data.data_provider.fetchers.eastmoney_fetcher import EastMoneyFetcher
from stock_data.data_provider.fetchers.zhitu_fetcher import ZhituFetcher
from stock_data.data_provider.manager import DataFetcherManager

# ---------------------------------------------------------------------------
# Canonical payload — kept minimal so the test focuses on routing, not field
# mapping (that's already exhaustively covered in test_baostock_dividend.py
# and test_zhitu_dividend_fund_flow_holder_num.py).
# ---------------------------------------------------------------------------

_DIVIDEND_PAYLOAD = [
    {
        "date": "2025-06-23",
        "bonus_rmb": 0.50,
        "transfer_ratio": 0.0,
        "bonus_ratio": 0.0,
        "plan": "实施",
    },
]

_FUND_FLOW_MINUTE_PAYLOAD = [
    {
        "time": "09:35:00",
        "main_net": 100.0,
        "small_net": 5.0,
        "mid_net": 10.0,
        "large_net": 50.0,
        "super_net": 200.0,
    },
]

_FUND_FLOW_DAILY_PAYLOAD = [
    {
        "date": "2025-06-20",
        "main_net": 100.0,
        "small_net": 5.0,
        "mid_net": 10.0,
        "large_net": 50.0,
        "super_net": 200.0,
    },
]

_HOLDER_NUM_PAYLOAD = [
    {
        "date": "2025-03-31",
        "holder_num": 517695,
        "change_num": 28718,
        "change_ratio": 0.0,
        "avg_shares": 0.0,
    },
]


# ===========================================================================
# DIVIDEND — Baostock (P1) → Zhitu (P4) → EastMoney (P6)
# ===========================================================================


class TestDividendFailover:
    """Validates the 3-way failover for DIVIDEND."""

    def _mgr(self):
        mgr = DataFetcherManager()
        mgr.reset()
        mgr.add_fetcher(BaostockFetcher())  # P1 — I added
        mgr.add_fetcher(ZhituFetcher())  # P4 — I added
        mgr.add_fetcher(EastMoneyFetcher())  # P6 — original
        return mgr

    def test_baostock_succeeds_no_failover(self):
        """Happy path: Baostock wins, Zhitu + EastMoney never called."""
        mgr = self._mgr()
        with (
            patch.object(BaostockFetcher, "get_dividend", return_value=_DIVIDEND_PAYLOAD) as bs,
            patch.object(ZhituFetcher, "get_dividend") as z,
            patch.object(EastMoneyFetcher, "get_dividend") as em,
        ):
            data, source = mgr.get_dividend("600519")

        assert data == _DIVIDEND_PAYLOAD
        assert source == "BaostockFetcher"
        bs.assert_called_once_with("600519", 20)
        z.assert_not_called()
        em.assert_not_called()

    def test_baostock_raises_falls_back_to_zhitu(self):
        """Baostock upstream exception → Zhitu takes over."""
        mgr = self._mgr()
        with (
            patch.object(
                BaostockFetcher,
                "get_dividend",
                side_effect=Exception("bs.query_dividend_data crashed"),
            ),
            patch.object(ZhituFetcher, "get_dividend", return_value=_DIVIDEND_PAYLOAD) as z,
            patch.object(EastMoneyFetcher, "get_dividend") as em,
        ):
            data, source = mgr.get_dividend("600519")

        assert data == _DIVIDEND_PAYLOAD
        assert source == "ZhituFetcher"
        z.assert_called_once_with("600519", 20)
        em.assert_not_called()

    def test_baostock_returns_empty_falls_back_to_zhitu(self):
        """Baostock returns [] → Zhitu takes over.

        ``_is_meaningful`` treats ``[]`` as 'no data', so the failover loop
        keeps trying. This matches the contract documented in test_manager_
        flash_news.py.
        """
        mgr = self._mgr()
        with (
            patch.object(BaostockFetcher, "get_dividend", return_value=[]) as bs,
            patch.object(ZhituFetcher, "get_dividend", return_value=_DIVIDEND_PAYLOAD) as z,
            patch.object(EastMoneyFetcher, "get_dividend") as em,
        ):
            data, source = mgr.get_dividend("600519")

        assert source == "ZhituFetcher"
        bs.assert_called_once()
        z.assert_called_once()
        em.assert_not_called()

    def test_baostock_and_zhitu_fail_falls_back_to_eastmoney(self):
        """Both backup sources fail → EastMoney (the original source) wins."""
        mgr = self._mgr()
        with (
            patch.object(
                BaostockFetcher,
                "get_dividend",
                side_effect=Exception("baostock broken"),
            ),
            patch.object(
                ZhituFetcher,
                "get_dividend",
                side_effect=Exception("zhitu token rejected"),
            ) as z,
            patch.object(EastMoneyFetcher, "get_dividend", return_value=_DIVIDEND_PAYLOAD) as em,
        ):
            data, source = mgr.get_dividend("600519")

        assert data == _DIVIDEND_PAYLOAD
        assert source == "EastMoneyFetcher"
        z.assert_called_once()
        em.assert_called_once()

    def test_all_three_fail_raises_datafetcherror(self):
        """Total upstream outage → DataFetchError surfaces to route as 503."""
        mgr = self._mgr()
        with (
            patch.object(
                BaostockFetcher,
                "get_dividend",
                side_effect=Exception("bs down"),
            ),
            patch.object(
                ZhituFetcher,
                "get_dividend",
                side_effect=Exception("zhitu down"),
            ),
            patch.object(
                EastMoneyFetcher,
                "get_dividend",
                side_effect=Exception("em down"),
            ),pytest.raises(DataFetchError, match="All fetchers failed")
        ):
            mgr.get_dividend("600519")

    def test_page_size_propagates_to_failover_target(self):
        """``page_size=5`` reaches Zhitu when Baostock fails."""
        mgr = self._mgr()
        with (
            patch.object(
                BaostockFetcher,
                "get_dividend",
                side_effect=Exception("bs down"),
            ),
            patch.object(
                ZhituFetcher,
                "get_dividend",
                return_value=_DIVIDEND_PAYLOAD,
            ) as z,
        ):
            mgr.get_dividend("600519", page_size=5)
        z.assert_called_once_with("600519", 5)


# ===========================================================================
# FUND_FLOW — Zhitu (P4) → EastMoney (P6)
# ===========================================================================


class TestFundFlowMinuteFailover:
    """Validates the 2-way failover for /fund-flow (minute variant)."""

    def _mgr(self):
        mgr = DataFetcherManager()
        mgr.reset()
        mgr.add_fetcher(ZhituFetcher())  # P4 — I added
        mgr.add_fetcher(EastMoneyFetcher())  # P6 — original
        return mgr

    def test_zhitu_succeeds_no_failover(self):
        mgr = self._mgr()
        with (
            patch.object(
                ZhituFetcher,
                "get_fund_flow_minute",
                return_value=_FUND_FLOW_MINUTE_PAYLOAD,
            ) as z,
            patch.object(EastMoneyFetcher, "get_fund_flow_minute") as em,
        ):
            data, source = mgr.get_fund_flow_minute("600519")

        assert data == _FUND_FLOW_MINUTE_PAYLOAD
        assert source == "ZhituFetcher"
        z.assert_called_once_with("600519")
        em.assert_not_called()

    def test_zhitu_raises_falls_back_to_eastmoney(self):
        """Zhitu upstream error → EastMoney (the original source) takes over."""
        mgr = self._mgr()
        with (
            patch.object(
                ZhituFetcher,
                "get_fund_flow_minute",
                side_effect=Exception("zhitu token expired"),
            ),
            patch.object(
                EastMoneyFetcher,
                "get_fund_flow_minute",
                return_value=_FUND_FLOW_MINUTE_PAYLOAD,
            ) as em,
        ):
            data, source = mgr.get_fund_flow_minute("600519")

        assert data == _FUND_FLOW_MINUTE_PAYLOAD
        assert source == "EastMoneyFetcher"
        em.assert_called_once_with("600519")

    def test_zhitu_returns_empty_falls_back_to_eastmoney(self):
        mgr = self._mgr()
        with (
            patch.object(ZhituFetcher, "get_fund_flow_minute", return_value=[]),
            patch.object(
                EastMoneyFetcher,
                "get_fund_flow_minute",
                return_value=_FUND_FLOW_MINUTE_PAYLOAD,
            ) as em,
        ):
            data, source = mgr.get_fund_flow_minute("600519")

        assert source == "EastMoneyFetcher"
        em.assert_called_once()

    def test_all_fail_raises_datafetcherror(self):
        mgr = self._mgr()
        with (
            patch.object(
                ZhituFetcher,
                "get_fund_flow_minute",
                side_effect=Exception("zhitu down"),
            ),
            patch.object(
                EastMoneyFetcher,
                "get_fund_flow_minute",
                side_effect=Exception("em down"),
            ),pytest.raises(DataFetchError, match="All fetchers failed")
        ):
            mgr.get_fund_flow_minute("600519")


class TestFundFlowDailyFailover:
    """Validates the 2-way failover for /fund-flow/daily (120d variant).

    Uses the override ``fetcher_method="get_fund_flow_120d"`` registered on
    the route (see ``/stocks/{stock_code}/fund-flow/daily`` in routes/stocks.py).
    The manager itself does NOT consult fetcher_method — that's a Stage-2
    manifest contract. The actual manager routing still picks Zhitu first
    because Zhitu declares FUND_FLOW; the test patches the actual method
    that the manager calls (``get_fund_flow_120d``).
    """

    def _mgr(self):
        mgr = DataFetcherManager()
        mgr.reset()
        mgr.add_fetcher(ZhituFetcher())  # P4 — I added
        mgr.add_fetcher(EastMoneyFetcher())  # P6 — original
        return mgr

    def test_zhitu_succeeds_no_failover(self):
        mgr = self._mgr()
        with (
            patch.object(
                ZhituFetcher,
                "get_fund_flow_120d",
                return_value=_FUND_FLOW_DAILY_PAYLOAD,
            ) as z,
            patch.object(EastMoneyFetcher, "get_fund_flow_120d") as em,
        ):
            data, source = mgr.get_fund_flow_120d("600519")

        assert source == "ZhituFetcher"
        z.assert_called_once_with("600519")
        em.assert_not_called()

    def test_zhitu_raises_falls_back_to_eastmoney(self):
        mgr = self._mgr()
        with (
            patch.object(
                ZhituFetcher,
                "get_fund_flow_120d",
                side_effect=Exception("zhitu rate-limited"),
            ),
            patch.object(
                EastMoneyFetcher,
                "get_fund_flow_120d",
                return_value=_FUND_FLOW_DAILY_PAYLOAD,
            ) as em,
        ):
            data, source = mgr.get_fund_flow_120d("600519")

        assert source == "EastMoneyFetcher"
        em.assert_called_once_with("600519")

    def test_all_fail_raises_datafetcherror(self):
        mgr = self._mgr()
        with (
            patch.object(
                ZhituFetcher,
                "get_fund_flow_120d",
                side_effect=Exception("zhitu down"),
            ),
            patch.object(
                EastMoneyFetcher,
                "get_fund_flow_120d",
                side_effect=Exception("em down"),
            ),pytest.raises(DataFetchError, match="All fetchers failed")
        ):
            mgr.get_fund_flow_120d("600519")


# ===========================================================================
# HOLDER_NUM — Zhitu (P4) → EastMoney (P6)
# ===========================================================================


class TestHolderNumFailover:
    """Validates the 2-way failover for /holder-num."""

    def _mgr(self):
        mgr = DataFetcherManager()
        mgr.reset()
        mgr.add_fetcher(ZhituFetcher())  # P4 — I added
        mgr.add_fetcher(EastMoneyFetcher())  # P6 — original
        return mgr

    def test_zhitu_succeeds_no_failover(self):
        mgr = self._mgr()
        with (
            patch.object(
                ZhituFetcher,
                "get_holder_num_change",
                return_value=_HOLDER_NUM_PAYLOAD,
            ) as z,
            patch.object(EastMoneyFetcher, "get_holder_num_change") as em,
        ):
            data, source = mgr.get_holder_num_change("600519")

        assert data == _HOLDER_NUM_PAYLOAD
        assert source == "ZhituFetcher"
        z.assert_called_once_with("600519", 10)  # default page_size=10
        em.assert_not_called()

    def test_zhitu_raises_falls_back_to_eastmoney(self):
        mgr = self._mgr()
        with (
            patch.object(
                ZhituFetcher,
                "get_holder_num_change",
                side_effect=Exception("zhitu token invalid"),
            ),
            patch.object(
                EastMoneyFetcher,
                "get_holder_num_change",
                return_value=_HOLDER_NUM_PAYLOAD,
            ) as em,
        ):
            data, source = mgr.get_holder_num_change("600519")

        assert source == "EastMoneyFetcher"
        em.assert_called_once_with("600519", 10)

    def test_zhitu_returns_empty_falls_back_to_eastmoney(self):
        mgr = self._mgr()
        with (
            patch.object(ZhituFetcher, "get_holder_num_change", return_value=[]),
            patch.object(
                EastMoneyFetcher,
                "get_holder_num_change",
                return_value=_HOLDER_NUM_PAYLOAD,
            ) as em,
        ):
            data, source = mgr.get_holder_num_change("600519")

        assert source == "EastMoneyFetcher"
        em.assert_called_once()

    def test_page_size_propagates_to_failover_target(self):
        mgr = self._mgr()
        with (
            patch.object(
                ZhituFetcher,
                "get_holder_num_change",
                side_effect=Exception("zhitu down"),
            ),
            patch.object(
                EastMoneyFetcher,
                "get_holder_num_change",
                return_value=_HOLDER_NUM_PAYLOAD,
            ) as em,
        ):
            mgr.get_holder_num_change("600519", page_size=20)
        em.assert_called_once_with("600519", 20)

    def test_all_fail_raises_datafetcherror(self):
        mgr = self._mgr()
        with (
            patch.object(
                ZhituFetcher,
                "get_holder_num_change",
                side_effect=Exception("zhitu down"),
            ),
            patch.object(
                EastMoneyFetcher,
                "get_holder_num_change",
                side_effect=Exception("em down"),
            ),pytest.raises(DataFetchError, match="All fetchers failed")
        ):
            mgr.get_holder_num_change("600519")


# ===========================================================================
# Manager candidate filter — sanity check that the new capabilities are
# actually exposed to the failover chain (catches typos in the capability
# flag declarations I added on BaostockFetcher / ZhituFetcher).
# ===========================================================================


class TestCapabilityFilterWiring:
    """If a fetcher declares the capability, it must appear in the failover list."""

    def test_dividend_candidates_include_baostock_zhitu_eastmoney(self):
        from stock_data.data_provider.base import DataCapability

        mgr = DataFetcherManager()
        mgr.reset()
        mgr.add_fetcher(BaostockFetcher())
        mgr.add_fetcher(ZhituFetcher())
        mgr.add_fetcher(EastMoneyFetcher())
        candidates = mgr._filter_by_capability("csi", DataCapability.DIVIDEND)
        names = [f.name for f in candidates]
        # Priority order: Baostock (1) < Zhitu (4) < EastMoney (6).
        assert names == ["BaostockFetcher", "ZhituFetcher", "EastMoneyFetcher"]

    def test_fund_flow_candidates_include_zhitu_eastmoney(self):
        from stock_data.data_provider.base import DataCapability

        mgr = DataFetcherManager()
        mgr.reset()
        mgr.add_fetcher(ZhituFetcher())
        mgr.add_fetcher(EastMoneyFetcher())
        names = [f.name for f in mgr._filter_by_capability("csi", DataCapability.FUND_FLOW)]
        assert names == ["ZhituFetcher", "EastMoneyFetcher"]

    def test_holder_num_candidates_include_zhitu_eastmoney(self):
        from stock_data.data_provider.base import DataCapability

        mgr = DataFetcherManager()
        mgr.reset()
        mgr.add_fetcher(ZhituFetcher())
        mgr.add_fetcher(EastMoneyFetcher())
        names = [f.name for f in mgr._filter_by_capability("csi", DataCapability.HOLDER_NUM)]
        assert names == ["ZhituFetcher", "EastMoneyFetcher"]
