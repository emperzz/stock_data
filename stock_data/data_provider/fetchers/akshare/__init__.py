"""Akshare data fetcher.

Internal sub-package — the public surface is ``AkshareFetcher``.
Helper modules (``board``, ``index_norm``) are implementation
details and should not be imported directly from outside this package.
"""

from .fetcher import AkshareFetcher

__all__ = ["AkshareFetcher"]
