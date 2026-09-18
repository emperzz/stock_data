"""Route-layer tests for POST /api/v1/boards/relationships.

Pure route integration: real FastAPI app + real Pydantic validation;
persistence layer is mocked so tests don't depend on DB fixtures or
backfill state. Pins the route's behaviour contract:
- response shape (top-level + per-row)
- board_codes / stock_codes passthrough semantics
- max_length / source validation (FastAPI native)
- source echoed at the top level

The route handler does not touch the DataFetcherManager singleton, so
no ``reset_manager`` autouse fixture is needed here.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest


_PERSISTENCE_PATCH = (
    "stock_data.data_provider.persistence.board.read_memberships_by_codes"
)


@pytest.fixture
def patched_persistence():
    """Patch the persistence call. Returns a context-manager helper so
    individual tests can override the return value."""
    with patch(_PERSISTENCE_PATCH) as mock_fn:
        mock_fn.return_value = []
        yield mock_fn


def _seed_rows():
    return [
        {
            "board_code": "885595",
            "board_name": "煤炭概念",
            "board_type": "concept",
            "stock_code": "600188",
            "stock_name": "兖矿能源",
            "refreshed_at": "2026-09-14 03:21:00",
        },
        {
            "board_code": "881270",
            "board_name": "煤炭开采",
            "board_type": "industry",
            "stock_code": "600188",
            "stock_name": "兖矿能源",
            "refreshed_at": "2026-09-14 03:21:00",
        },
    ]


class TestBoardRelationshipsRoute:
    def test_returns_rows_with_top_level_source(self, client, patched_persistence):
        patched_persistence.return_value = _seed_rows()
        resp = client.post(
            "/api/v1/boards/relationships",
            json={"source": "ths"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["source"] == "ths"
        assert body["count"] == 2
        assert len(body["rows"]) == 2
        # First row pinned
        first = body["rows"][0]
        assert first["board_code"] == "885595"
        assert first["stock_code"] == "600188"
        # Field-set pin: no subtype, no per-row source
        assert set(first.keys()) == {
            "board_code",
            "board_name",
            "board_type",
            "stock_code",
            "stock_name",
            "refreshed_at",
        }

    def test_passes_payload_codes_to_persistence(self, client, patched_persistence):
        patched_persistence.return_value = []
        client.post(
            "/api/v1/boards/relationships",
            json={
                "source": "eastmoney",
                "board_codes": ["BK0438"],
                "stock_codes": ["600519", "000001"],
            },
        )
        patched_persistence.assert_called_once_with(
            board_codes=["BK0438"],
            stock_codes=["600519", "000001"],
            source="eastmoney",
        )

    def test_empty_lists_pass_through_as_none(self, client, patched_persistence):
        """Route must convert [] → None before calling the helper (helper
        treats None and [] identically, but tests pin the call shape)."""
        patched_persistence.return_value = []
        client.post(
            "/api/v1/boards/relationships",
            json={"source": "ths", "board_codes": [], "stock_codes": []},
        )
        patched_persistence.assert_called_once_with(
            board_codes=None,
            stock_codes=None,
            source="ths",
        )

    def test_count_matches_len_rows(self, client, patched_persistence):
        patched_persistence.return_value = _seed_rows()
        resp = client.post(
            "/api/v1/boards/relationships", json={"source": "ths"}
        )
        body = resp.json()
        assert body["count"] == len(body["rows"])

    def test_empty_persistence_returns_count_zero(self, client, patched_persistence):
        patched_persistence.return_value = []
        resp = client.post(
            "/api/v1/boards/relationships", json={"source": "ths"}
        )
        body = resp.json()
        assert body["count"] == 0
        assert body["rows"] == []

    def test_invalid_source_returns_422(self, client):
        # FastAPI Literal validation — not our 400
        resp = client.post(
            "/api/v1/boards/relationships", json={"source": "not-a-source"}
        )
        assert resp.status_code == 422

    def test_max_length_exceeded_board_codes(self, client):
        resp = client.post(
            "/api/v1/boards/relationships",
            json={"source": "ths", "board_codes": ["c"] * 101},
        )
        assert resp.status_code == 422

    def test_max_length_exceeded_stock_codes(self, client):
        resp = client.post(
            "/api/v1/boards/relationships",
            json={"source": "ths", "stock_codes": ["c"] * 101},
        )
        assert resp.status_code == 422

    def test_missing_source_returns_422(self, client):
        # source is required
        resp = client.post(
            "/api/v1/boards/relationships",
            json={"board_codes": ["x"]},
        )
        assert resp.status_code == 422