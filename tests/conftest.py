"""
Pytest configuration and fixtures.

This module also installs the **network-to-xfail hook** that reclassifies
upstream/network errors in any test marked ``@pytest.mark.live_network``
as ``xfail`` (output line ``x``) rather than ``failed`` (``F``). See
``tests/_network_guard.py`` for the rationale and the legend.
"""

from __future__ import annotations

import os

import pytest

# Force the pure-Python protobuf parser before any test imports ``gm.api``.
# The shipped gm 3.0.180 wheel's auto-generated _pb2 descriptors are
# incompatible with the C++-backed parser in modern protobuf; this env
# var must be set BEFORE the very first ``import gm.api`` (which happens
# transitively via monkeypatch.setattr's __import__ path-resolution).
os.environ.setdefault("PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION", "python")


# ── network-to-xfail hook ─────────────────────────────────────────────────
#
# Strategy: for any test marked ``@pytest.mark.live_network`` whose "call"
# phase failed, look at the exception. If it is a network/upstream error
# (per ``_network_guard.UPSTREAM_ERRORS``), rewrite the pytest report from
# "failed" to "skipped" with ``wasxfail=True`` so it shows as ``x`` in the
# summary instead of ``F``. The reason string identifies the cause.
#
# Why a hook (not per-test try/except): zero boilerplate in test bodies,
# uniform behaviour across all live_network tests, and a single place to
# evolve the classification logic.

# Import here to keep the import resolution explicit and avoid cycles.
from ._network_guard import (
    is_upstream_error,
    short_reason,
)


@pytest.hookimpl(tryfirst=True, hookwrapper=True)
def pytest_runtest_makereport(item, call):
    outcome = yield
    report = outcome.get_result()

    # Only the "call" phase can raise the test body's exception.
    if call.when != "call":
        return
    # Only reclassify for live_network tests.
    if "live_network" not in item.keywords:
        return
    # Only act on actual failures (don't downgrade xfails/xpasses).
    if report.outcome != "failed":
        return
    excinfo = call.excinfo
    if excinfo is None:
        return
    # AssertionError, ValueError, etc. are real bugs — leave them alone.
    if not is_upstream_error(excinfo.value):
        return

    # Reclassify: "failed" → "skipped" with wasxfail=<reason>. Pytest then
    # displays the test as ``x`` (xfail) in the summary, with the reason
    # string visible in the long output. An agent reading the summary
    # knows this is a network issue, not a code regression, and should
    # not retry.
    #
    # NOTE: ``wasxfail`` is a string in pytest (the reason), not a bool.
    # Setting it to ``True`` triggers an internal ``AttributeError`` in
    # ``_pytest/terminal.py`` because the reporter calls
    # ``reason.startswith("reason: ")``.
    report.outcome = "skipped"
    report.wasxfail = short_reason(excinfo.value)
    report.longrepr = short_reason(excinfo.value)


# ── fixtures ──────────────────────────────────────────────────────────────
# (sample_* fixtures were removed 2026-07-03 — verified zero consumers
# across the entire test suite.)


# ── Shared FastAPI app + TestClient fixtures ──────────────────────────────
#
# Five test files previously duplicated the same boilerplate:
#
#     from stock_data.server import app
#     @pytest.fixture(autouse=True)
#     def reset_before_test():
#         reset_manager(); yield
#     @pytest.fixture
#     def client():
#         from fastapi.testclient import TestClient
#         return TestClient(app)
#
# Centralising `app` / `client` here avoids the 5× `from stock_data.server
# import app` (which eagerly imports every fetcher and the SQLite schema
# init) at test-collection time. Session scope is safe because:
#   * `stock_data.server.app` is fully built at import (mounts + includes
#     happen there, not in lifespan);
#   * The lifespan body only sets `app.state.manager = get_manager()` and
#     runs `persistence.init_schema()` — both idempotent;
#   * Tests that mutate `app.state` (e.g. patching the manager) override
#     via `with patch(...)` and don't rely on per-test re-import.
#
# Per-test state isolation is the responsibility of individual test files
# (e.g. `test_zt_pools.py` clears the response TTLCaches locally; that
# concern is intentionally NOT autouse here because most tests mock at
# the manager layer and never touch the cache).

from fastapi.testclient import TestClient  # noqa: E402

from stock_data.server import app as _app  # noqa: E402


@pytest.fixture(scope="session")
def app():
    """Session-scoped FastAPI app — shared across the whole pytest worker."""
    return _app


@pytest.fixture(scope="session")
def client(app):
    """Session-scoped TestClient.

    Used as a context manager so the lifespan handler runs exactly once
    (populates `app.state.manager`, runs `persistence.init_schema()`).
    Per-test re-entry would be wasted work.
    """
    with TestClient(app) as c:
        yield c
