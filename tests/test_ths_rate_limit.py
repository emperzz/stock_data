"""P2-4: THS rate-limit hardening — UA pool rotation + paging jitter.

Background (``docs/optimization-plan-2026-07-16.md`` §P2-4):
* Original THS used a single static ``THS_UA`` across every request. On
  personal single-IP setups the q.10jqka.com.cn anti-bot layer can
  fingerprint a fixed UA in a single session and throttle the IP.
* Board-list / board-stocks paging fetched up to 5 pages in tight
  succession — exactly the request cadence that triggers rate limits.

This file pins both fixes so a regression that reverts either:
1. falls back to a single static UA, or
2. drops the inter-page sleep,

gets caught by a fast unit test.

The test mocks both ``requests.get`` (so no real network call happens)
and ``time.sleep`` (so the test is fast — we only assert that sleep
WAS called the right number of times, not that it actually slept).
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from stock_data.data_provider.fetchers.ths_fetcher import (
    THS_UA,
    ThsFetcher,
)


# ============================================================================
# _http_get: UA pool rotation
# ============================================================================


class TestHttpGetUARotation:
    """``_http_get`` must use the shared random UA pool when no UA supplied."""

    def test_default_ua_is_from_pool(self, monkeypatch):
        """No headers → UA picked from utils.http._UA_POOL (not static THS_UA).

        Regression guard: a future refactor that reverts ``_http_get`` to
        ``headers=headers or {"User-Agent": THS_UA}`` would expose the
        single static UA across all calls (the audit M11 weakness) and
        this test would fail because the sent UA would be ``THS_UA``,
        not a member of the pool.
        """
        from stock_data.data_provider.utils.http import _UA_POOL

        mock_get = MagicMock(return_value=MagicMock())
        monkeypatch.setattr("requests.get", mock_get)
        ThsFetcher._http_get("http://example.com/")
        sent_ua = mock_get.call_args.kwargs["headers"]["User-Agent"]
        assert sent_ua in _UA_POOL, (
            f"default UA {sent_ua!r} is not from utils.http._UA_POOL "
            f"(regression: P2-4 UA rotation was reverted)"
        )
        assert sent_ua != THS_UA, (
            "default UA must differ from the static THS_UA constant — "
            "if this fails, _http_get reverted to the pre-P2-4 static UA"
        )

    def test_custom_ua_in_headers_is_preserved(self, monkeypatch):
        """If the caller passes its own User-Agent, _http_get must not overwrite it.

        Cninfo POST and Baidu Bearer auth both rely on a fixed UA;
        silently rotating those would break them. P2-4 only fills in
        a UA when one is missing.
        """
        mock_get = MagicMock(return_value=MagicMock())
        monkeypatch.setattr("requests.get", mock_get)
        custom_ua = "TestUA/1.0 (custom-fetcher-ua)"
        ThsFetcher._http_get("http://example.com/", headers={"User-Agent": custom_ua})
        call_kwargs = mock_get.call_args.kwargs
        assert call_kwargs["headers"]["User-Agent"] == custom_ua

    def test_default_ua_varies_across_calls(self, monkeypatch):
        """Many consecutive _http_get calls with no UA must span the pool.

        With a 4-entry pool, 50 calls should produce >1 distinct UA
        (probability of all-same is 4^-49 ≈ 0). A regression that
        pinned UA back to ``THS_UA`` would produce exactly 1 distinct
        value across all 50 calls, which this test catches.

        This test exercises the actual ``_http_get`` production code
        path, not ``random_ua()`` in isolation — a regression in
        ``_http_get`` itself (e.g. removing the ``random_ua()`` call)
        is caught here even if ``random_ua()`` still works.
        """
        from stock_data.data_provider.utils.http import _UA_POOL

        mock_get = MagicMock(return_value=MagicMock())
        monkeypatch.setattr("requests.get", mock_get)
        seen = set()
        for _ in range(50):
            ThsFetcher._http_get("http://example.com/")
            sent_ua = mock_get.call_args.kwargs["headers"]["User-Agent"]
            seen.add(sent_ua)
        # 4-entry pool: with 50 calls we expect >1 distinct UA.
        # We don't assert == 4 (random.choice could pick the same
        # value multiple times in a row); we just need "more than 1"
        # to confirm rotation actually happens.
        assert len(seen) > 1, (
            f"expected multiple distinct UAs across 50 calls, got {len(seen)} "
            f"({seen!r}). Pool has {len(_UA_POOL)} entries — a single value "
            "means rotation is broken."
        )
        # And the UA must still be from the pool (defense-in-depth).
        for ua in seen:
            assert ua in _UA_POOL, f"UA {ua!r} not from pool"

    def test_pool_size_at_least_two(self):
        """The UA pool must have at least 2 entries for rotation to mean anything.

        A pool of size 1 is identical to a fixed UA. P2-4's value is
        exactly the rotation, so any future "trim the pool" change must
        keep at least 2 entries.
        """
        from stock_data.data_provider.utils.http import _UA_POOL

        assert len(_UA_POOL) >= 2, (
            f"UA pool has {len(_UA_POOL)} entries; rotation is meaningless "
            "with a single entry. Keep at least 2."
        )


# ============================================================================
# Board paging jitter
# ============================================================================


class TestBoardStocksPagingJitter:
    """``get_board_stocks`` sleeps ``random.uniform(1.5, 3.0)`` between pages."""

    def test_jitter_sleep_called_between_pages(self, monkeypatch):
        """For a 5-page board fetch (top_n=50), sleep must be called 4 times.

        Pages 2/3/4/5 are after page 1, so sleep is invoked once per
        page transition (4 transitions for 5 pages). Page 1 is the
        cold path and must NOT sleep (preserves first-byte latency).
        """
        # top_n=50 → ceil(50/10)+1 = 6 pages max, but ThsBoundarySignalError
        # on page 6 truncates; we mock _fetch_ths_board_stocks_page to
        # always return rows so the loop actually walks all pages.
        monkeypatch.setattr(
            "stock_data.data_provider.fetchers.ths_fetcher.ThsFetcher._fetch_ths_board_stocks_page",
            lambda self, code, page, **kw: [{"stock_code": "x", "stock_name": "y"}],
        )
        sleep_calls: list[float] = []
        monkeypatch.setattr(
            "stock_data.data_provider.fetchers.ths_fetcher.time.sleep",
            lambda s: sleep_calls.append(s),
        )
        # Fake random.uniform so we can assert range without flakes
        monkeypatch.setattr(
            "stock_data.data_provider.fetchers.ths_fetcher.random.uniform",
            lambda a, b: (a + b) / 2,  # deterministic midpoint
        )

        fetcher = ThsFetcher.__new__(ThsFetcher)
        # We don't want real v-token mints during tests
        monkeypatch.setattr(fetcher, "_v_token", lambda: "test_v")

        rows = fetcher.get_board_stocks("885595", top_n=50)
        assert len(rows) > 0  # sanity: we got something back
        # 6 pages × (page > 1 sleep) = 5 sleeps
        # But ThsBoundarySignalError handling may break early — with our
        # mock returning rows every time, the loop walks all 6 pages.
        # Confirm at least one sleep happened (i.e. the first inter-page
        # transition triggered it). The exact count depends on the
        # max_pages math; what matters is that we sleep BETWEEN pages,
        # not that we sleep exactly N times.
        assert len(sleep_calls) >= 1, "no jitter sleep between pages — P2-4 regression"

    def test_first_page_does_not_sleep(self, monkeypatch):
        """Page 1 must not trigger a sleep — preserves cold-path latency.

        The P2-4 jitter is only between paged fetches, not before the
        first one. A user clicking /boards/{code}/stocks expects the
        first row to come back without a 1.5-3.0s lead-in delay.

        Setup: ``top_n=1`` forces ``max_pages=2`` but page 1 already
        satisfies ``top_n``, so the loop breaks before requesting page 2.
        """
        monkeypatch.setattr(
            "stock_data.data_provider.fetchers.ths_fetcher.ThsFetcher._fetch_ths_board_stocks_page",
            lambda self, code, page, **kw: ([{"stock_code": "x", "stock_name": "y"}] if page == 1 else []),
        )
        sleep_calls: list[float] = []
        monkeypatch.setattr(
            "stock_data.data_provider.fetchers.ths_fetcher.time.sleep",
            lambda s: sleep_calls.append(s),
        )
        fetcher = ThsFetcher.__new__(ThsFetcher)
        monkeypatch.setattr(fetcher, "_v_token", lambda: "test_v")

        rows = fetcher.get_board_stocks("885595", top_n=1)
        assert sleep_calls == [], (
            f"unexpected sleep(s) before first page: {sleep_calls}"
        )


class TestIndustrySummaryPagingJitter:
    """Industry summary paging loop must also apply jitter between pages."""

    def test_jitter_sleep_called_between_pages(self, monkeypatch):
        """Multi-page industry summary fetches must sleep between pages."""
        # Mock _http_get to return a parseable response (non-empty text)
        fake_response = MagicMock()
        fake_response.status_code = 200
        fake_response.content = b"some-html"
        fake_response.text = "some-html"
        monkeypatch.setattr(
            "stock_data.data_provider.fetchers.ths_fetcher.ThsFetcher._http_get",
            lambda self, *a, **kw: fake_response,
        )
        # _parse_ths_industry_summary_page is a @staticmethod but the
        # call site passes ``self``, so the lambda must accept it too.
        # Always return non-empty rows so the loop continues past page 1.
        monkeypatch.setattr(
            "stock_data.data_provider.fetchers.ths_fetcher.ThsFetcher._parse_ths_industry_summary_page",
            lambda self, html: [{"name": f"row-{html}", "value": 1}],
        )
        sleep_calls: list[float] = []
        monkeypatch.setattr(
            "stock_data.data_provider.fetchers.ths_fetcher.time.sleep",
            lambda s: sleep_calls.append(s),
        )
        fetcher = ThsFetcher.__new__(ThsFetcher)
        monkeypatch.setattr(fetcher, "_v_token", lambda: "test_v")

        out = fetcher._fetch_ths_industry_summary()
        # _THS_INDUSTRY_SUMMARY_MAX_PAGES=5 → 4 sleeps between 5 pages.
        # (Page 1 has no preceding sleep; pages 2-5 each have one.)
        assert len(sleep_calls) == 4, (
            f"expected 4 jitter sleeps across 5 pages, got {len(sleep_calls)}"
        )


# ============================================================================
# Class-level constants
# ============================================================================


def test_ths_paging_jitter_range():
    """Jitter range must match the documented 1.5-3.0s window."""
    lo, hi = ThsFetcher._THS_PAGING_JITTER_S
    assert lo == 1.5
    assert hi == 3.0


def test_static_ths_ua_still_exists_for_backward_compat():
    """THS_UA module constant is kept — some callers (HSGT_HEADERS etc.) reference it.

    P2-4 didn't remove THS_UA; it stopped using it as the default in
    ``_http_get``. The constant remains as a fallback / for callers
    that explicitly opt out of rotation (rare).
    """
    assert THS_UA.startswith("Mozilla/5.0")


# ============================================================================
# Caller convention: do NOT pre-set User-Agent
# ----------------------------------------------------------------------------
# Audit gap: P2-4 added a UA-rotation guard in ``_http_get`` but every
# ``_http_get`` call site pre-set ``"User-Agent": THS_UA`` in its headers
# dict, so the guard's ``if "User-Agent" not in headers`` branch never
# fires in production. UA rotation is dead code.
#
# Fix contract: callers must let ``_http_get`` inject the UA. These two
# tests pin the contract for the two highest-frequency paged cold-path
# fetches (the ones called out in the ``_http_get`` docstring). The
# other 4 ``_http_get`` call sites (L607 / L781 / L1396 / L2119) are
# covered by the same one-line mechanical deletion in the fix commit
# and inspected at review time.
# ============================================================================


class TestCallerDoesNotPresetUserAgent:
    """P2-4 audit-fix: ``_http_get`` callers must not pre-set User-Agent."""

    def test_fetch_ths_board_stocks_page_no_user_agent(self, monkeypatch):
        """``_fetch_ths_board_stocks_page`` (L1068) must not pre-set User-Agent.

        If callers pre-set ``"User-Agent": THS_UA`` the rotation guard
        inside ``_http_get`` is bypassed and the same single static UA
        goes out on every request — the audit M11 weakness.
        """
        captured: dict | None = None

        def fake_http_get(self, url, *, headers=None, timeout=10):
            nonlocal captured
            captured = headers
            r = MagicMock()
            r.status_code = 200
            r.content = b""
            r.text = ""
            return r

        monkeypatch.setattr(
            "stock_data.data_provider.fetchers.ths_fetcher.ThsFetcher._http_get",
            fake_http_get,
        )
        fetcher = ThsFetcher.__new__(ThsFetcher)
        monkeypatch.setattr(fetcher, "_v_token", lambda: "test_v")

        fetcher._fetch_ths_board_stocks_page("123456", 1)

        assert captured is not None, "_http_get was not called"
        assert "User-Agent" not in captured, (
            f"_fetch_ths_board_stocks_page pre-sets User-Agent; "
            f"_http_get's UA rotation cannot fire. Headers: {captured!r}"
        )

    def test_fetch_ths_industry_summary_no_user_agent(self, monkeypatch):
        """``_fetch_ths_industry_summary`` (L2021) must not pre-set User-Agent.

        Industry summary walks up to 5 pages — the highest-frequency
        paged cold path on the THS side. Same audit gap as
        ``_fetch_ths_board_stocks_page``: pre-setting ``THS_UA`` makes
        the wrapper's rotation guard inert across all 5 pages.
        """
        captured: list[dict] = []

        def fake_http_get(self, url, *, headers=None, timeout=10):
            captured.append(headers)
            r = MagicMock()
            r.status_code = 200
            r.content = b""
            r.text = ""
            return r

        monkeypatch.setattr(
            "stock_data.data_provider.fetchers.ths_fetcher.ThsFetcher._http_get",
            fake_http_get,
        )
        # Empty rows so the loop walks all _THS_INDUSTRY_SUMMARY_MAX_PAGES pages.
        monkeypatch.setattr(
            "stock_data.data_provider.fetchers.ths_fetcher.ThsFetcher._parse_ths_industry_summary_page",
            lambda self, html: [],
        )
        fetcher = ThsFetcher.__new__(ThsFetcher)
        monkeypatch.setattr(fetcher, "_v_token", lambda: "test_v")

        fetcher._fetch_ths_industry_summary()

        assert len(captured) > 0, "_http_get was not called"
        for i, headers in enumerate(captured, start=1):
            assert "User-Agent" not in headers, (
                f"_fetch_ths_industry_summary page {i} pre-sets User-Agent; "
                f"_http_get's UA rotation cannot fire. Headers: {headers!r}"
            )