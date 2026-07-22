"""Per-fetcher supports_kline overrides per spec §4.3."""

import pytest

from stock_data.data_provider.fetchers.akshare.fetcher import AkshareFetcher
from stock_data.data_provider.fetchers.baostock_fetcher import BaostockFetcher
from stock_data.data_provider.fetchers.myquant_fetcher import MyquantFetcher
from stock_data.data_provider.fetchers.tushare_fetcher import TushareFetcher
from stock_data.data_provider.fetchers.yfinance_fetcher import YfinanceFetcher
from stock_data.data_provider.fetchers.zhitu_fetcher import ZhituFetcher
from stock_data.data_provider.fetchers.zzshare_fetcher import ZzshareFetcher

# (fetcher_cls, period, adjust, market, asset, expected)
CASES = [
    # Tushare: csi + d/w/m only; weekly/monthly + adjust valid.
    (TushareFetcher, "d", "", "csi", "stock", True),
    (TushareFetcher, "d", "qfq", "csi", "stock", True),
    (TushareFetcher, "w", "qfq", "csi", "stock", True),
    (TushareFetcher, "1", "", "csi", "stock", False),
    (TushareFetcher, "d", "", "hk", "stock", False),
    (TushareFetcher, "d", "", "csi", "index", True),
    (TushareFetcher, "5", "", "csi", "index", False),
    # Baostock: stock d/w/m + csi-stock minutes; index d/w/m only.
    (BaostockFetcher, "d", "hfq", "csi", "stock", True),
    (BaostockFetcher, "5", "qfq", "csi", "stock", True),
    (BaostockFetcher, "5", "", "hk", "stock", False),
    (BaostockFetcher, "1", "", "csi", "stock", False),
    (BaostockFetcher, "d", "", "us", "index", True),
    (BaostockFetcher, "5", "", "csi", "index", False),
    # Akshare: 1m refuses adjust; otherwise supports full matrix.
    (AkshareFetcher, "1", "", "csi", "stock", True),
    (AkshareFetcher, "1", "qfq", "csi", "stock", False),
    (AkshareFetcher, "5", "qfq", "csi", "stock", True),
    (AkshareFetcher, "5", "qfq", "csi", "index", True),
    (AkshareFetcher, "1", "qfq", "us", "index", False),
    # Yfinance: hfq silently downgrades to qfq -> unsupported; qfq OK.
    (YfinanceFetcher, "5", "qfq", "us", "stock", True),
    (YfinanceFetcher, "5", "hfq", "us", "stock", False),
    (YfinanceFetcher, "5", "qfq", "us", "index", True),
    (YfinanceFetcher, "1", "", "us", "stock", False),
    # Zhitu: 5/15/30/60 + forces no adjust; no d/w/m; no 1m.
    (ZhituFetcher, "5", "", "csi", "stock", True),
    (ZhituFetcher, "5", "qfq", "csi", "stock", False),
    (ZhituFetcher, "d", "", "csi", "stock", False),
    (ZhituFetcher, "1", "", "csi", "stock", False),
    # Zzshare: d + minute, minute refuses adjust.
    (ZzshareFetcher, "d", "qfq", "csi", "stock", True),
    (ZzshareFetcher, "5", "", "csi", "stock", True),
    (ZzshareFetcher, "5", "qfq", "csi", "stock", False),
    (ZzshareFetcher, "1", "", "csi", "stock", True),
    (ZzshareFetcher, "w", "", "csi", "stock", False),
    # Myquant: d + minutes full adjust for **stock**; **index is daily-only**
    # because ``get_index_historical`` only supports ``d``. Tightened 2026-07-06
    # so the manager's two-stage filter excludes Myquant from non-d index
    # routing (previously Myquant would be included and immediately fail
    # over out of ``get_index_historical``).
    (MyquantFetcher, "d", "hfq", "csi", "stock", True),
    (MyquantFetcher, "5", "qfq", "csi", "stock", True),
    (MyquantFetcher, "5", "qfq", "us", "stock", False),
    (MyquantFetcher, "w", "", "csi", "stock", False),
    (MyquantFetcher, "d", "", "csi", "index", True),
    (MyquantFetcher, "5", "", "csi", "index", False),
    (MyquantFetcher, "w", "", "csi", "index", False),
    (MyquantFetcher, "5", "", "us", "index", False),
    (MyquantFetcher, "d", "", "us", "index", False),
]


@pytest.mark.parametrize("fetcher_cls,period,adjust,market,asset,expected", CASES)
def test_supports_kline_matrix(fetcher_cls, period, adjust, market, asset, expected):
    """Each fetcher's supports_kline override matches spec §4.3."""
    # Construct an instance without invoking __init__ (some fetchers need
    # SDK availability to instantiate normally). We set just the
    # attributes the method reads.
    inst = fetcher_cls.__new__(fetcher_cls)
    inst.supported_markets = fetcher_cls.supported_markets
    inst.supported_data_types = fetcher_cls.supported_data_types
    actual = inst.supports_kline(period, adjust, market, asset)
    assert actual is expected
