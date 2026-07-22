"""Route-level tests for /boards/{board_code}/history source expansion."""

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    from stock_data.server import app

    return TestClient(app)


class TestSourceExpansion:
    def test_zzshare_source_accepted(self, client):
        """Backward compat: `source=zzshare` is accepted and aliased to `ths`.

        ZzshareFetcher has no K-line implementation (upstream `plate_kline`
        only supports 883957 同花顺全A), so the route layer aliases
        `zzshare` → `ths` instead of 400-ing on unknown source.
        """
        r = client.get(
            "/api/v1/boards/881270/history",
            params={"source": "zzshare", "frequency": "d", "board_type": "industry"},
        )
        # Either 200 (upstream works) or 502/500 (upstream down) — NOT 400/422 (validation)
        assert r.status_code != 422, r.text
        assert r.status_code != 400, r.text

    def test_eastmoney_source_accepted(self, client):
        r = client.get(
            "/api/v1/boards/BK0996/history", params={"source": "eastmoney", "frequency": "d"}
        )
        assert r.status_code != 422, r.text
        assert r.status_code != 400, r.text

    def test_ths_concept_works_without_board_type(self, client):
        """board_type is now auto-detected from cache; no longer 422."""
        with patch(
            "stock_data.data_provider.manager.DataFetcherManager.get_board_history",
            return_value=([], "ThsFetcher"),
        ):
            r = client.get("/api/v1/boards/885595/history", params={"source": "ths", "frequency": "d"})
        # Should NOT be 422 — auto-detection replaces the hard gate.
        assert r.status_code != 422, r.text

    def test_ths_industry_works(self, client):
        r = client.get(
            "/api/v1/boards/881270/history",
            params={"source": "ths", "frequency": "d", "board_type": "industry"},
        )
        assert r.status_code != 422, r.text
        assert r.status_code != 400, r.text

    def test_unknown_source_returns_400(self, client):
        r = client.get(
            "/api/v1/boards/881270/history", params={"source": "bogus", "frequency": "d"}
        )
        assert r.status_code == 400, r.text

    def test_zzshare_alias_to_ths(self, client):
        """`source=zzshare` on /boards/.../history aliases to `ths`.

        Reversed direction from `_resolve_source` (which aliases
        `ths→zzshare` for board-list endpoints). Here `ths` MUST stay
        canonical (different upstream from zzshare's plates_list), and
        `zzshare` is the label that gets remapped.
        """
        with patch(
            "stock_data.data_provider.manager.DataFetcherManager.get_board_history",
            return_value=([], "ThsFetcher"),
        ) as spy:
            r = client.get(
                "/api/v1/boards/881270/history",
                params={"source": "zzshare", "frequency": "d", "board_type": "industry"},
            )
        assert r.status_code == 200, r.text
        # Manager must have received source='ths' (alias applied before dispatch)
        assert spy.call_args.kwargs.get("source") == "ths"


class TestFrequencyExpansion:
    @pytest.mark.parametrize("freq", ["d", "w", "m", "5m", "15m", "30m", "60m"])
    def test_eastmoney_accepts_all_frequencies(self, client, freq):
        r = client.get(
            "/api/v1/boards/BK0996/history",
            params={"source": "eastmoney", "frequency": freq},
        )
        # Validation passes; upstream may fail but route shouldn't 422.
        assert r.status_code != 422, f"freq={freq} rejected: {r.text}"

    def test_eastmoney_rejects_1m(self, client):
        """EastMoney boards don't support 1m (push2his freq_map is 7-freq,
        no klt=1). BOARD_KLINE_FREQ_BY_SOURCE reflects this — manager's
        source×freq check returns 400 with a clear message instead of
        the fetcher's DataFetchError (which would surface as 500)."""
        r = client.get(
            "/api/v1/boards/BK0996/history",
            params={"source": "eastmoney", "frequency": "1m"},
        )
        assert r.status_code == 400, r.text
        body = r.json()
        # Detail shape from manager: ValueError message
        assert "frequency" in body.get("detail", {}).get("message", "").lower() or \
               "1m" in body.get("detail", {}).get("message", "")

    def test_ths_rejects_unknown_frequency(self, client):
        """Post-2026-07-14: THS supports the full 7-frequency set
        (d / w / m / 5m / 15m / 30m / 60m), so weekly is now VALID.
        This test now covers an actually-unsupported frequency like '2h'."""
        r = client.get(
            "/api/v1/boards/881270/history",
            params={"source": "ths", "frequency": "2h", "board_type": "industry"},
        )
        # Route Literal already rejects "2h" at FastAPI level → 422
        # (the manager's source×freq check would also catch it as a
        # defense-in-depth layer, but the route Literal fires first).
        assert r.status_code == 422, r.text

    def test_ths_supports_weekly(self, client):
        """Post-2026-07-14: weekly is now real (upstream segment 02).
        Patched manager call returns empty; route should 200, NOT 422/400."""
        with patch(
            "stock_data.data_provider.manager.DataFetcherManager.get_board_history",
            return_value=([], "ThsFetcher"),
        ):
            r = client.get(
                "/api/v1/boards/881270/history",
                params={"source": "ths", "frequency": "w", "board_type": "industry"},
            )
        assert r.status_code == 200, r.text

    @pytest.mark.parametrize("freq", ["d", "w", "m", "5m", "15m", "30m", "60m"])
    def test_ths_accepts_all_7_frequencies(self, client, freq):
        """THS upstream supports the full 7-frequency set (verified 2026-07-14)."""
        with patch(
            "stock_data.data_provider.manager.DataFetcherManager.get_board_history",
            return_value=([], "ThsFetcher"),
        ):
            r = client.get(
                "/api/v1/boards/881270/history",
                params={"source": "ths", "frequency": freq, "board_type": "industry"},
            )
        assert r.status_code == 200, f"freq={freq} should be accepted: {r.text}"


class TestBoardTypeParam:
    def test_board_type_optional_for_ths(self, client):
        """board_type is now auto-detected; no longer 422."""
        with patch(
            "stock_data.data_provider.manager.DataFetcherManager.get_board_history",
            return_value=([], "ThsFetcher"),
        ):
            r = client.get(
                "/api/v1/boards/881270/history",
                params={"source": "ths", "frequency": "d"},
            )
        assert r.status_code != 422, r.text

    def test_board_type_ignored_for_eastmoney(self, client):
        r = client.get(
            "/api/v1/boards/BK0996/history",
            params={"source": "eastmoney", "frequency": "d", "board_type": "concept"},
        )
        assert r.status_code != 422, r.text


class TestDaysCap:
    """Regression: route days cap raised from 365 → 800 (mirrors lmt=800)."""

    def test_days_365_accepted(self, client):
        r = client.get(
            "/api/v1/boards/BK0996/history",
            params={"source": "eastmoney", "frequency": "d", "days": 365},
        )
        # Validation passes (days <= 800); upstream may fail but route shouldn't 422.
        assert r.status_code != 422, r.text

    def test_days_800_accepted(self, client):
        r = client.get(
            "/api/v1/boards/BK0996/history",
            params={"source": "eastmoney", "frequency": "d", "days": 800},
        )
        assert r.status_code != 422, r.text

    def test_days_801_rejected(self, client):
        r = client.get(
            "/api/v1/boards/BK0996/history",
            params={"source": "eastmoney", "frequency": "d", "days": 801},
        )
        assert r.status_code == 422, r.text

    def test_wide_date_range_under_cap_accepted(self, client):
        """days=30 + start/end spanning 1 year (under 800-day cap) is served.

        Pre-fix this returned only the last 30 bars regardless of date
        span because lmt was derived from days only.  Now the fetcher
        computes effective_lmt = max(days, range_width); test asserts
        the route accepts the (narrow) range without 422.
        """
        r = client.get(
            "/api/v1/boards/BK0996/history",
            params={
                "source": "eastmoney",
                "frequency": "d",
                "start_date": "2020-01-01",
                "end_date": "2020-12-31",  # 366 days (leap year), under 800
                "days": 30,
            },
        )
        assert r.status_code != 422, r.text

    def test_date_range_over_cap_returns_400(self, client):
        """start_date..end_date > 800 days → 400 + 'date_range_too_wide'.

        Without the route-layer cap, the fetcher would silently return
        only the 800 most-recent bars (post-fetch date filter trims
        the older half of the requested range). The fix is to fail
        fast at the route layer with a clear 400 + pagination guidance.
        """
        r = client.get(
            "/api/v1/boards/BK0996/history",
            params={
                "source": "eastmoney",
                "frequency": "d",
                "start_date": "2015-01-01",
                "end_date": "2024-12-31",  # 3653 days, well over 800
                "days": 30,
            },
        )
        assert r.status_code == 400, r.text
        # Detail shape from _validate_board_history_date_range:
        body = r.json()
        assert body.get("detail", {}).get("error") == "date_range_too_wide"

    def test_date_range_at_boundary_accepted(self, client):
        """Exactly 800-day range passes (cap is inclusive)."""
        # 2024-01-01 + 799 days = 2026-03-19 → inclusive width = 800 days.
        r = client.get(
            "/api/v1/boards/BK0996/history",
            params={
                "source": "eastmoney",
                "frequency": "d",
                "start_date": "2024-01-01",
                "end_date": "2026-03-19",  # exactly 800 days inclusive
                "days": 30,
            },
        )
        assert r.status_code != 422, r.text

    def test_date_range_one_over_cap_returns_400(self, client):
        """801-day range (1 over) → 400 + 'date_range_too_wide'."""
        r = client.get(
            "/api/v1/boards/BK0996/history",
            params={
                "source": "eastmoney",
                "frequency": "d",
                "start_date": "2024-01-01",
                "end_date": "2026-03-20",  # 801 days inclusive
                "days": 30,
            },
        )
        assert r.status_code == 400, r.text
        assert r.json().get("detail", {}).get("error") == "date_range_too_wide"


class TestBoardCodeValidation:
    """_board_secid now raises ValueError on bad input → route maps to 400."""

    def test_missing_board_code_rejected_by_route_validation(self, client):
        # FastAPI Path(max_length=30) accepts empty-string board codes
        # via /boards//history; we just want to make sure an obviously
        # garbage code returns 4xx (not 200 with empty data).
        r = client.get(
            "/api/v1/boards/BK/history",
            params={"source": "eastmoney", "frequency": "d", "days": 30},
        )
        # "BK" → ValueError from _board_secid → map_errors → 400
        assert r.status_code == 400, r.text

    def test_garbage_board_code_returns_400(self, client):
        r = client.get(
            "/api/v1/boards/not-a-code/history",
            params={"source": "eastmoney", "frequency": "d", "days": 30},
        )
        assert r.status_code == 400, r.text


class TestFrequencyAwareDaysDefault:
    """Regression: ``days`` default must be frequency-aware so minute-level
    frequencies don't trip the per-frequency span cap when caller doesn't
    pass ``days`` explicitly.

    Pre-fix: route hardcoded ``days=30``. Resolver clamps
    ``start_d = min(start_hint, end_d - days)``, so
    ``frequency=1m&start_date=today`` still computes span=30d > 1m
    cap (2d) → 400 ``date span (30d) exceeds frequency='1m' max (2d)``.

    Post-fix: ``days`` defaults are freq-aware
    (``d/w/m=30, 1m=1, 5m/15m/30m/60m=2``); user-supplied ``days`` wins.
    """

    @pytest.mark.parametrize(
        "freq,expected_default",
        [
            ("d", 30),
            ("w", 30),
            ("m", 30),
            ("1m", 800),
            ("5m", 30),
            ("15m", 30),
            ("30m", 30),
            ("60m", 30),
        ],
    )
    def test_default_days_forwards_to_manager(
        self, client, freq, expected_default
    ):
        """When caller doesn't pass ``days``, manager receives the
        freq-aware default (not the hardcoded 30)."""
        with patch(
            "stock_data.data_provider.manager.DataFetcherManager.get_board_history",
            return_value=([], "ThsFetcher"),
        ) as spy:
            r = client.get(
                "/api/v1/boards/881270/history",
                params={
                    "source": "ths",
                    "frequency": freq,
                    "board_type": "industry",
                },
            )
        assert r.status_code == 200, r.text
        assert spy.call_args.kwargs["days"] == expected_default, (
            f"freq={freq} should default days={expected_default}, "
            f"got {spy.call_args.kwargs['days']}"
        )

    def test_1m_with_start_date_today_does_not_400(self, client):
        """End-to-end: ``frequency=1m&start_date=today`` (no days) must NOT
        hit a span-cap 400. With the freq-aware default (1m=800), the
        resolved window is ~800 days back, which now fits the 1m span
        cap (raised from 2 to 800). The default 800 maps to upstream's
        bar-count cap, so the fetcher returns ~800 1m bars.

        Patch at the ths_fetcher._fetch_ths_single_kline level so the real
        resolver + span check actually runs (only the network call is
        short-circuited)."""
        from stock_data.data_provider.fetchers import ths_fetcher as ths_mod

        # 800 fake 1m rows to simulate upstream's full bar-count cap
        fake_rows = [
            {
                "date": f"2026-07-{20 + i // 240:02d} {(i % 240) // 10:02d}:{(i % 10) * 6:02d}",
                "open": 1.0, "high": 2.0, "low": 0.5, "close": 1.5,
                "volume": 100, "amount": 150.0, "frequency": "1m",
            }
            for i in range(800)
        ]
        with patch.object(
            ths_mod, "_fetch_ths_single_kline", return_value=fake_rows
        ):
            r = client.get(
                "/api/v1/boards/881270/history",
                params={
                    "source": "ths",
                    "frequency": "1m",
                    "start_date": "2026-07-22",
                    "board_type": "industry",
                },
            )
        assert r.status_code == 200, (
            f"frequency=1m&start_date=today should be 200; got "
            f"{r.status_code}: {r.text[:300]}"
        )

    def test_explicit_days_overrides_freq_default(self, client):
        """User-supplied ``days`` flows through unchanged (freq default is
        only the fallback)."""
        with patch(
            "stock_data.data_provider.manager.DataFetcherManager.get_board_history",
            return_value=([], "ThsFetcher"),
        ) as spy:
            r = client.get(
                "/api/v1/boards/881270/history",
                params={
                    "source": "ths",
                    "frequency": "1m",
                    "days": 7,  # would fail 1m cap (2d) at fetcher span check,
                    #   but route shouldn't reject on its own
                    "board_type": "industry",
                },
            )
        assert r.status_code == 200, r.text
        assert spy.call_args.kwargs["days"] == 7
