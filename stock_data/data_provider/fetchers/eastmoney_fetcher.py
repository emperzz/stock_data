"""Backwards-compat shim — see ``stock_data.data_provider.fetchers.eastmoney``.

The EastMoneyFetcher implementation was split into a sub-package
(``_endpoints``, ``_boards_mixin``, ``_news_mixin``, ``fetcher``) for
readability and per-protocol isolation. The public API is preserved:
``EastMoneyFetcher`` and ``_DCEndpoint`` (the dataclass parameterising the
datacenter query, used in ``tests/test_eastmoney_fetcher.py``) remain
importable from this module path so existing call sites and tests
(``from stock_data.data_provider.fetchers.eastmoney_fetcher import
EastMoneyFetcher, _DCEndpoint``) continue to work.

``ENDPOINTS`` (the central URL/registry singleton) is also re-exported —
tests like ``test_eastmoney_fetcher_board.py`` derive their fixture shapes
from ``ENDPOINTS.BOARD_LIST_CONCEPT["fields"].split(",")``.

Direct imports from the new sub-package are also supported:
``from stock_data.data_provider.fetchers.eastmoney import EastMoneyFetcher``.
"""
from .eastmoney import EastMoneyFetcher, _DCEndpoint
from .eastmoney._endpoints import ENDPOINTS

__all__ = ["EastMoneyFetcher", "_DCEndpoint", "ENDPOINTS"]
