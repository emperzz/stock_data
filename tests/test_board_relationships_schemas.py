"""Unit tests for BoardRelationships* Pydantic schemas.

Pure schema tests — no DB, no fetcher. Pin field set + constraints.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from stock_data.api.schemas import (
    BoardRelationshipRow,
    BoardRelationshipsRequest,
    BoardRelationshipsResponse,
)


class TestBoardRelationshipRow:
    def test_six_required_fields(self):
        row = BoardRelationshipRow(
            board_code="885595",
            board_name="煤炭概念",
            board_type="concept",
            stock_code="600188",
            stock_name="兖矿能源",
            refreshed_at="2026-09-14 03:21:00",
        )
        assert row.board_code == "885595"
        assert row.stock_name == "兖矿能源"

    def test_missing_required_field_raises(self):
        with pytest.raises(ValidationError):
            BoardRelationshipRow(
                board_code="885595",
                # board_name omitted
                board_type="concept",
                stock_code="600188",
                stock_name="x",
                refreshed_at="2026-09-14",
            )


class TestBoardRelationshipsRequest:
    def test_minimal_payload(self):
        req = BoardRelationshipsRequest(source="ths")
        assert req.board_codes == []
        assert req.stock_codes == []

    def test_full_payload(self):
        req = BoardRelationshipsRequest(
            source="eastmoney",
            board_codes=["BK0438"],
            stock_codes=["600519", "000001"],
        )
        assert req.source == "eastmoney"
        assert req.board_codes == ["BK0438"]
        assert req.stock_codes == ["600519", "000001"]

    def test_invalid_source_rejected(self):
        with pytest.raises(ValidationError):
            BoardRelationshipsRequest(source="not-a-source")

    @pytest.mark.parametrize("size", [0, 100])
    def test_max_length_boundary_ok(self, size):
        codes = ["c"] * size
        # 0 = empty (valid), 100 = at the cap (valid)
        req = BoardRelationshipsRequest(source="ths", board_codes=codes)
        assert len(req.board_codes) == size

    def test_max_length_exceeded_rejected(self):
        codes = ["c"] * 101
        with pytest.raises(ValidationError):
            BoardRelationshipsRequest(source="ths", board_codes=codes)

    def test_max_length_exceeded_rejected_stock(self):
        codes = ["c"] * 101
        with pytest.raises(ValidationError):
            BoardRelationshipsRequest(source="ths", stock_codes=codes)


class TestBoardRelationshipsResponse:
    def test_default_serialisation(self):
        resp = BoardRelationshipsResponse(
            source="ths",
            count=0,
            rows=[],
        )
        assert resp.source == "ths"
        assert resp.count == 0
        assert resp.rows == []

    def test_row_serialised_as_dict(self):
        resp = BoardRelationshipsResponse(
            source="ths",
            count=1,
            rows=[
                BoardRelationshipRow(
                    board_code="885595",
                    board_name="煤炭概念",
                    board_type="concept",
                    stock_code="600188",
                    stock_name="兖矿能源",
                    refreshed_at="2026-09-14 03:21:00",
                )
            ],
        )
        d = resp.model_dump()
        assert d["source"] == "ths"
        assert d["count"] == 1
        assert len(d["rows"]) == 1
        # Pin the field set on the row level too — no subtype, no per-row source.
        assert set(d["rows"][0].keys()) == {
            "board_code",
            "board_name",
            "board_type",
            "stock_code",
            "stock_name",
            "refreshed_at",
        }
