"""Route-level tests for /boards/{board_code}/history source expansion."""

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    from stock_data.server import app

    return TestClient(app)


class TestSourceExpansion:
    def test_zzshare_source_accepted(self, client):
        r = client.get(
            "/api/v1/boards/883957/history", params={"source": "zzshare", "frequency": "d"}
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

    def test_ths_concept_requires_board_type(self, client):
        r = client.get("/api/v1/boards/301558/history", params={"source": "ths", "frequency": "d"})
        # 422 because board_type is missing
        assert r.status_code == 422, r.text

    def test_ths_industry_works(self, client):
        r = client.get(
            "/api/v1/boards/881270/history",
            params={"source": "ths", "frequency": "d", "board_type": "industry"},
        )
        assert r.status_code != 422, r.text
        assert r.status_code != 400, r.text

    def test_unknown_source_returns_400(self, client):
        r = client.get(
            "/api/v1/boards/883957/history", params={"source": "bogus", "frequency": "d"}
        )
        assert r.status_code == 400, r.text

    def test_zzshare_alias_to_ths_not_done_here(self, client):
        # `source=ths` here must NOT be aliased to `zzshare` — it should be
        # validated against the history-source allowlist.
        r = client.get(
            "/api/v1/boards/881270/history",
            params={"source": "ths", "frequency": "d", "board_type": "industry"},
        )
        # If aliased, the route would call ZzshareFetcher.get_board_history
        # which only supports 883957 → 4xx/5xx.
        # We assert the route accepted "ths" (status != 400/422).
        assert r.status_code not in (400, 422), r.text


class TestFrequencyExpansion:
    @pytest.mark.parametrize("freq", ["d", "w", "m", "5m", "15m", "30m", "60m"])
    def test_eastmoney_accepts_all_frequencies(self, client, freq):
        r = client.get(
            "/api/v1/boards/BK0996/history",
            params={"source": "eastmoney", "frequency": freq},
        )
        # Validation passes; upstream may fail but route shouldn't 422.
        assert r.status_code != 422, f"freq={freq} rejected: {r.text}"

    def test_ths_rejects_weekly(self, client):
        r = client.get(
            "/api/v1/boards/881270/history",
            params={"source": "ths", "frequency": "w", "board_type": "industry"},
        )
        # ThsFetcher raises DataFetchError → mapped to 4xx/5xx (NOT 422)
        assert r.status_code != 422, r.text
        assert r.status_code >= 400, r.text


class TestBoardTypeParam:
    def test_board_type_required_for_ths(self, client):
        # Without board_type, route returns 422
        r = client.get(
            "/api/v1/boards/881270/history",
            params={"source": "ths", "frequency": "d"},
        )
        assert r.status_code == 422

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

    def test_wide_date_range_accepted(self, client):
        """days=30 + start/end spanning > days is now served correctly.

        Pre-fix this returned only the last 30 bars regardless of date
        span because lmt was derived from days only.  Now the fetcher
        computes effective_lmt = max(days, range_width); test asserts
        the route accepts the wide range without 422 (upstream may
        5xx but that's a fetcher concern).
        """
        r = client.get(
            "/api/v1/boards/BK0996/history",
            params={
                "source": "eastmoney",
                "frequency": "d",
                "start_date": "2020-01-01",
                "end_date": "2024-12-31",
                "days": 30,
            },
        )
        assert r.status_code != 422, r.text


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
