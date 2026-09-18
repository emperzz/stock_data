"""End-to-end test for POST /api/v1/boards/relationships.

Uses the real persistence layer (per-test tmp_db fixture) and real
SQL — no mocks. Pins the round-trip: insert rows via
``upsert_membership_bulk``, hit the route, assert response rows match
the seeded data and respect the SQL sort order.
"""

from __future__ import annotations

import pytest

from stock_data.data_provider.persistence import board as board_mod


def _seed(stock_code: str, source: str, board_code: str,
          board_type: str = "concept") -> None:
    """Seed a single membership row.

    Wraps upsert_membership_bulk with a 1-stock list. NOTE: each call does
    DELETE-then-INSERT scoped to (board_code, source), so two calls with the
    same (board_code, source) overwrite each other — use _seed_board when
    you need multiple stocks in one board.
    """
    _seed_board([stock_code], source, board_code, board_type)


def _seed_board(stock_codes: list[str], source: str, board_code: str,
                board_type: str = "concept") -> None:
    board_mod.upsert_membership_bulk(
        source=source,
        stocks=[{"stock_code": sc, "stock_name": f"Stock-{sc}"} for sc in stock_codes],
        board_code=board_code,
        board_name=f"Board-{board_code}",
        board_type=board_type,
        subtype=None,
    )


class TestBoardRelationshipsE2E:
    def test_full_round_trip_with_real_sql(self, client, tmp_db):
        """Seed 4 rows → POST → assert response shape and order."""
        _seed_board(["600519", "000001"], "ths", "885595", "concept")
        _seed("600519", "ths", "881270", "industry")
        # unrelated source — must not appear in ths response
        _seed("600519", "zzshare", "885540", "concept")

        resp = client.post(
            "/api/v1/boards/relationships",
            json={"source": "ths"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["source"] == "ths"
        assert body["count"] == 3
        keys = [(r["board_code"], r["stock_code"]) for r in body["rows"]]
        assert keys == [
            ("881270", "600519"),
            ("885595", "000001"),
            ("885595", "600519"),
        ]

    def test_board_codes_filter_e2e(self, client, tmp_db):
        _seed_board(["600519", "000001"], "ths", "885595")
        _seed("600519", "ths", "881270")

        resp = client.post(
            "/api/v1/boards/relationships",
            json={"source": "ths", "board_codes": ["885595"]},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["count"] == 2
        assert {r["stock_code"] for r in body["rows"]} == {"000001", "600519"}

    def test_stock_codes_filter_e2e(self, client, tmp_db):
        _seed_board(["600519", "000001"], "ths", "885595")
        _seed_board(["600519"], "ths", "881270")

        resp = client.post(
            "/api/v1/boards/relationships",
            json={"source": "ths", "stock_codes": ["600519"]},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["count"] == 2
        assert {r["board_code"] for r in body["rows"]} == {"881270", "885595"}

    def test_union_filter_e2e(self, client, tmp_db):
        """board_codes X ∪ stock_codes Y."""
        _seed_board(["600519", "000001"], "ths", "885595")  # in X
        _seed("600519", "ths", "881270")  # 600519 stock → in Y
        _seed("000002", "ths", "999999")  # unrelated

        resp = client.post(
            "/api/v1/boards/relationships",
            json={
                "source": "ths",
                "board_codes": ["885595"],
                "stock_codes": ["600519"],
            },
        )
        assert resp.status_code == 200
        body = resp.json()
        keys = {(r["board_code"], r["stock_code"]) for r in body["rows"]}
        assert keys == {
            ("881270", "600519"),  # via stock_codes axis
            ("885595", "000001"),  # via board_codes axis
            ("885595", "600519"),  # via both axes
        }

    def test_empty_db_returns_count_zero(self, client, tmp_db):
        resp = client.post(
            "/api/v1/boards/relationships", json={"source": "ths"}
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body == {"source": "ths", "count": 0, "rows": []}