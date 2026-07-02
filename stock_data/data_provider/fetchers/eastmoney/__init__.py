"""EastMoneyFetcher sub-package.

Public surface:
- ``EastMoneyFetcher`` — the fetcher class (single, no parallel classes per
  the [[extend-not-spawn-fetcher]] rule).
- ``_DCEndpoint`` — kept public-by-convention because
  ``tests/test_eastmoney_fetcher.py`` constructs ``_DCEndpoint(report_name=...)``
  instances for parametrized testing.

Modules in this package:
- ``_endpoints`` — URL registry, ``ENDPOINTS`` dataclass+dict registry, board
  field-code maps. No fetcher state, no HTTP. Shared by both mixins.
- ``fetcher`` — class ``EastMoneyFetcher`` (the main entry). Composes the
  two mixins and the BaseFetcher, plus datacenter / fund-flow / research
  methods that don't fit either mixin's protocol family.
- ``_boards_mixin`` — clist protocol methods (board listings, board stock
  membership). Single class attrs ``_BOARD_*`` and ``_STOCK_BOARDS_*``.
- ``_news_mixin`` — news / announcements / 7×24 flash methods. Owns the
  session baseline headers (``_NEWS_SEARCH_BASE_HEADERS``) consumed by
  ``EastMoneyFetcher.__init__``.

Backward-compat: ``stock_data.data_provider.fetchers.eastmoney_fetcher`` is
a thin shim that re-exports ``EastMoneyFetcher`` and ``_DCEndpoint``.
"""
from ._endpoints import _DCEndpoint
from .fetcher import EastMoneyFetcher

__all__ = ["EastMoneyFetcher", "_DCEndpoint"]
