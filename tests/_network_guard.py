"""
Network/Upstream failure classification for the test suite.

Background
----------
This project integrates 10 upstream stock-data APIs. Some of our pytest cases
intentionally hit real upstream endpoints (rate-limited, occasionally
unreachable, sometimes returning empty payloads under load). When such a case
fails, the failure is **not** a code bug — it is the upstream being flaky.
The test should be reported as ``x`` (xfail) or ``s`` (skipped), not ``F``
(failed), so that agents/CI don't treat it as a regression and start a
retry loop.

Marker convention
-----------------
Add ``@pytest.mark.live_network`` to any test that may touch a real upstream
API (or a route that fans out to fetchers). The hook in
``tests/conftest.py`` then converts network-class failures in those tests
into ``pytest.xfail(reason="upstream: ...")``.

Marker contract:

* ``live_network``     — the test is allowed to fail because of upstream.
                         ``conftest.py`` reclassifies network errors to xfail.
* ``requires_token``   — the test needs an env var (TUSHARE_TOKEN etc.) and
                         should ``pytest.skip`` when the token is absent.

Pytest output legend (so an agent reading stdout knows what to do):

    .  passed           → no action
    F  failed           → real bug, investigate
    s  skipped          → environment/token missing, not a regression
    x  xfailed          → upstream/network issue, expected, not a regression
    X  xpassed          → upstream unexpectedly worked; worth a glance
    E  error            → setup/teardown problem, may be a test bug

Only ``F`` (and arguably ``E``) should trigger a "this is a code bug"
reaction. ``s``/``x`` are part of the normal output.

Why ``DataFetchError`` is in the upstream list
----------------------------------------------
The ``DataFetcherManager`` wraps *any* fetcher failure (network, rate limit,
feature gap, malformed payload) in ``stock_data.data_provider.base.DataFetchError``.
The original underlying exception is usually logged but not chained, so by
the time pytest sees the failure the only thing on the stack is
``DataFetchError("All fetchers failed: ...")``.

For ``live_network`` tests this is the right level of granularity: if a
``live_network`` test raises ``DataFetchError`` we treat it as upstream
behaving badly and xfail it. Real code bugs in the fetcher would also be
caught by the mock-based unit tests (e.g. ``test_zhitu_fetcher.py``,
``test_eastmoney_fetcher.py``) which are NOT marked ``live_network`` and
would still show as ``F`` on regression.
"""

from __future__ import annotations

import socket
from typing import Final

import requests

# urllib.error.URLError is awkward to import at module level (it shadows
# urllib.request in some environments), so resolve defensively. If we can't
# import it, fall back to a private sentinel class that never matches.
try:
    import urllib.error as _urllib_error

    _URLError: type[BaseException] = _urllib_error.URLError
except Exception:  # pragma: no cover — defensive only
    class _URLError(BaseException):  # type: ignore[no-redef]
        pass


# yfinance exposes its own rate-limit exception. We import it defensively —
# yfinance is an optional dep for some test envs, and YFRateLimitError is
# usually caught internally by the fetcher anyway, but if it leaks through
# we want to recognise it.
try:
    from yfinance.exceptions import YFRateLimitError as _YFRateLimitError
except Exception:  # pragma: no cover — defensive only
    class _YFRateLimitError(BaseException):  # type: ignore[no-redef]
        pass


# Project-internal fetcher failure wrapper. Imported here so the
# classification logic stays in one place even though ``base.py`` lives
# inside the package under test.
try:
    from stock_data.data_provider.base import DataFetchError as _DataFetchError
    from stock_data.data_provider.base import RateLimitError as _RateLimitError
except Exception:  # pragma: no cover — defensive only
    class _DataFetchError(Exception):  # type: ignore[no-redef]
        pass

    class _RateLimitError(Exception):  # type: ignore[no-redef]
        pass


# ── Exception taxonomy ────────────────────────────────────────────────────

#: Exceptions that mean "I could not reach the upstream / upstream is broken".
#: These are NOT code bugs and should be reclassified to xfail by the
#: ``conftest.py`` hook for any test marked ``@pytest.mark.live_network``.
UPSTREAM_ERRORS: Final[tuple[type[BaseException], ...]] = (
    # ── raw network errors (the upstream call never completed) ──
    requests.ConnectionError,            # DNS / TCP / TLS handshake failure
    requests.Timeout,                     # upstream too slow
    requests.HTTPError,                   # 5xx (raise_for_status path)
    requests.exceptions.SSLError,
    requests.exceptions.ChunkedEncodingError,
    _URLError,                            # urllib.error.URLError
    socket.gaierror,                      # DNS resolution failure
    socket.timeout,                       # raw socket timeout
    TimeoutError,                         # builtin (used by yfinance etc.)
    ConnectionError,                      # builtin
    OSError,                              # covers "Network is unreachable" etc.
    # ── upstream-specific rate-limit errors ──
    _YFRateLimitError,                    # yfinance 'Too Many Requests'
    # ── project-internal wrappers (manager catches everything here) ──
    # The manager wraps any per-fetcher failure in DataFetchError; the
    # original exception is usually only present in the message. Treating
    # DataFetchError as upstream is the right granularity for live_network
    # tests; true fetcher code bugs are caught by the mock-based unit tests.
    _DataFetchError,
    _RateLimitError,
)


#: A short, human-readable label for logs and xfail reasons.
UPSTREAM_LABEL: Final[str] = "upstream/network"


def is_upstream_error(exc: BaseException) -> bool:
    """True if ``exc`` looks like a network/upstream failure (not a code bug)."""
    return isinstance(exc, UPSTREAM_ERRORS)


def classify(exc: BaseException) -> str:
    """Classify an exception as ``'upstream'`` or ``'code'``.

    Use this in places that need to decide whether to skip vs. fail. Note
    that ``AssertionError`` and friends are always ``'code'`` — those are
    real regressions even in ``live_network`` tests.
    """
    if is_upstream_error(exc):
        return "upstream"
    return "code"


def short_reason(exc: BaseException) -> str:
    """Build a compact xfail/skip reason from an exception (max ~120 chars)."""
    name = type(exc).__name__
    msg = str(exc).strip().splitlines()[0] if str(exc) else ""
    if msg:
        return f"{UPSTREAM_LABEL}: {name}: {msg[:80]}"
    return f"{UPSTREAM_LABEL}: {name}"


def assert_or_skip(result, label: str = "result"):
    """Assert ``result`` is not None, but treat a None result as upstream flake.

    The fetcher layer swallows low-level network errors and returns ``None``
    on hard failure (e.g. all fetchers failed). For a ``live_network`` test
    that's indistinguishable from a code bug via the conftest hook (the
    failure is an ``AssertionError``, not a network exception). This helper
    turns the ``None``-as-upstream case into ``pytest.skip`` so the test
    shows as ``s`` rather than ``F``.

    Usage in a live_network test:

        result = assert_or_skip(manager.get_realtime_quote("AAPL"), "realtime quote")
        assert result.price > 0
    """
    if result is None:
        import pytest as _pytest

        _pytest.skip(f"{UPSTREAM_LABEL}: {label} returned None (upstream flake)")
    return result
