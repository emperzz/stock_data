"""Pin the removal of ZzshareFetcher's STOCK_ZT_POOL capability.

Per the 2026-09-03 refactor: ZzshareFetcher no longer serves /zt-pools.
The upstream `review_uplimit_reason` endpoint is now exposed via a
dedicated ``get_zt_reason`` method (DataCapability.STOCK_ZT_REASON).
"""
from __future__ import annotations


class TestZzshareNoLongerServesZtPool:
    def test_zzshare_does_not_declare_zt_pool_capability(self):
        from stock_data.data_provider.base import DataCapability
        from stock_data.data_provider.fetchers.zzshare_fetcher import ZzshareFetcher

        assert DataCapability.STOCK_ZT_POOL not in ZzshareFetcher.supported_data_types

    def test_zzshare_get_zt_pool_method_is_gone(self):
        from stock_data.data_provider.fetchers.zzshare_fetcher import ZzshareFetcher

        assert not hasattr(ZzshareFetcher, "get_zt_pool"), (
            "ZzshareFetcher.get_zt_pool was retired on 2026-09-03; the "
            "upstream review_uplimit_reason is now served via "
            "get_zt_reason with DataCapability.STOCK_ZT_REASON."
        )
