"""Regression tests for once-per-process lazy SDK init.

Locks in the invariant introduced when fetchers moved SDK init from
per-instance to class-level state (commit 632ee46 + subsequent
refactors):

  - A fetcher's first ``is_available()`` (or any method that triggers
    ``_ensure_initialized``) runs the underlying SDK init exactly once.
  - A SECOND instance of the same fetcher — created via ``Fetcher()`` —
    must NOT re-run init. Class-level state (``_init_attempted``)
    short-circuits the second call.

Why this matters: the manifest builder (explorer/manifest.py) reflects
over app routes and instantiates one fetcher per endpoint per request.
Per-instance state would re-run bs.login() / ts.pro_api() / set_token()
on every page load — a burst of "login failed!" log spam.

Without these tests, a future refactor that accidentally reverted to
instance-level state would pass CI silently; the user-visible bug
would come back unnoticed.
"""

from __future__ import annotations

import sys as _sys
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from stock_data.data_provider.fetchers.baostock_fetcher import BaostockFetcher
from stock_data.data_provider.fetchers.myquant_fetcher import MyquantFetcher
from stock_data.data_provider.fetchers.tushare_fetcher import TushareFetcher

# ---- SDK stubs (module-level so all tests share them) ----

_baostock_stub = SimpleNamespace(login=MagicMock())
_baostock_stub.login.return_value = SimpleNamespace(error_code="0", error_msg="ok")

_tushare_stub = SimpleNamespace(pro_api=MagicMock(return_value=object()))

_gm_api_stub = SimpleNamespace(set_token=MagicMock())


def _reset_baostock():
    BaostockFetcher._init_attempted = False
    BaostockFetcher._init_ok = False


def _reset_tushare():
    TushareFetcher._init_attempted = False
    TushareFetcher._init_ok = False
    TushareFetcher._cls_token = ""
    TushareFetcher._init_error = None
    TushareFetcher._api = None


def _reset_myquant():
    MyquantFetcher._init_attempted = False
    MyquantFetcher._init_ok = False
    MyquantFetcher._cls_token = ""
    MyquantFetcher._init_error = None


@pytest.fixture(autouse=True)
def _install_sdk_stubs(monkeypatch):
    """Install SDK module stubs, reset mocks, reset class state, and
    force-empty token env vars so the ``_ensure_api`` path is
    deterministic regardless of dev env.
    """
    # ``gm.api`` must be a separate sys.modules entry — fetcher does
    # ``from gm.api import set_token`` which expects a real submodule.
    _gm_module = _sys.modules.get("gm")
    if _gm_module is None:
        _gm_module = MagicMock()
        _sys.modules["gm"] = _gm_module
    _gm_module.api = _gm_api_stub
    _sys.modules["gm.api"] = _gm_api_stub

    _sys.modules["baostock"] = _baostock_stub
    _sys.modules["tushare"] = _tushare_stub

    # Force empty tokens by default. Tests that need a token set it
    # explicitly via the ``monkeypatch`` parameter.
    monkeypatch.setenv("TUSHARE_TOKEN", "")
    monkeypatch.setenv("MYQUANT_TOKEN", "")

    _baostock_stub.login.reset_mock()
    _baostock_stub.login.return_value = SimpleNamespace(error_code="0", error_msg="ok")
    _tushare_stub.pro_api.reset_mock()
    _gm_api_stub.set_token.reset_mock()

    _reset_baostock()
    _reset_tushare()
    _reset_myquant()
    yield


class TestBaostockInitOncePerProcess:
    """Two BaostockFetcher() instances must share one bs.login() call."""

    def test_second_instance_does_not_relogin(self):
        first = BaostockFetcher()
        first.is_available()
        assert _baostock_stub.login.call_count == 1

        second = BaostockFetcher()
        second.is_available()

        assert _baostock_stub.login.call_count == 1, (
            f"expected 1 bs.login() call across two instances, "
            f"got {_baostock_stub.login.call_count}"
        )

    def test_failed_init_is_cached_too(self):
        """If first init fails, subsequent instances must NOT retry.

        Without this, the manifest page-load would trigger a fresh
        bs.login() on every failed init.
        """
        _baostock_stub.login.side_effect = ConnectionError("network down")

        first = BaostockFetcher()
        first.is_available()
        assert _baostock_stub.login.call_count == 1
        assert BaostockFetcher._init_attempted is True
        assert BaostockFetcher._init_ok is False

        # Even after resetting the failure mode, second instance must
        # NOT retry — the attempt flag is sticky.
        _baostock_stub.login.side_effect = None
        second = BaostockFetcher()
        second.is_available()

        assert _baostock_stub.login.call_count == 1, (
            f"failed init should be cached; got {_baostock_stub.login.call_count} calls"
        )


class TestTushareInitOncePerProcess:
    """Two TushareFetcher() instances share one pro_api() call."""

    def test_second_instance_does_not_reinit(self, monkeypatch):
        monkeypatch.setenv("TUSHARE_TOKEN", "fake_token")

        first = TushareFetcher()
        first.is_available()
        assert _tushare_stub.pro_api.call_count == 1
        assert TushareFetcher._init_ok is True

        second = TushareFetcher()
        second.is_available()

        assert _tushare_stub.pro_api.call_count == 1, (
            f"expected 1 pro_api() call, got {_tushare_stub.pro_api.call_count}"
        )


class TestMyquantInitOncePerProcess:
    """Two MyquantFetcher() instances share one set_token() call."""

    def test_second_instance_does_not_recall_set_token(self, monkeypatch):
        monkeypatch.setenv("MYQUANT_TOKEN", "fake_token")

        first = MyquantFetcher()
        first.is_available()
        assert _gm_api_stub.set_token.call_count == 1
        assert MyquantFetcher._init_ok is True

        second = MyquantFetcher()
        second.is_available()

        assert _gm_api_stub.set_token.call_count == 1, (
            f"expected set_token() called once, got {_gm_api_stub.set_token.call_count}"
        )
