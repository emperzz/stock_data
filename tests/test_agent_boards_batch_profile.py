"""Tests for /api/v1/agent/boards/batch-profile (THS board-level features)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from stock_data.api.schemas import (
    BatchFeatures,
    BoardProfile,
    BoardsBatchProfileRequest,
    BoardsBatchProfileResponse,
    MinimalQuote,
)


class TestSchemas:
    def test_board_profile_defaults(self):
        bp = BoardProfile(code="885595")
        assert bp.code == "885595"
        assert bp.name == ""
        assert bp.quote is None
        assert bp.features is None
        assert bp.errors == {}

    def test_board_profile_with_full_payload(self):
        bp = BoardProfile(
            code="881270",
            name="半导体",
            quote=MinimalQuote(price=1234.5, change_pct=1.23),
            features=BatchFeatures(),
            errors={"quote": None, "features": None},
        )
        assert bp.name == "半导体"
        assert bp.quote.price == 1234.5
        assert bp.features == BatchFeatures()
        assert bp.errors == {"quote": None, "features": None}

    def test_request_accepts_codes_and_defaults(self):
        req = BoardsBatchProfileRequest(codes=["885595", "881270"])
        assert req.codes == ["885595", "881270"]
        assert req.frequency == "d"
        assert req.days is None

    def test_request_rejects_empty_codes(self):
        with pytest.raises(ValidationError):
            BoardsBatchProfileRequest(codes=[])

    def test_request_rejects_too_many_codes(self):
        with pytest.raises(ValidationError):
            BoardsBatchProfileRequest(codes=[f"88{i:04d}" for i in range(6)])

    def test_request_accepts_all_supported_frequencies(self):
        for f in ("d", "w", "m", "1m", "5m", "15m", "30m", "60m"):
            req = BoardsBatchProfileRequest(codes=["885595"], frequency=f)
            assert req.frequency == f

    def test_request_rejects_unsupported_frequency(self):
        with pytest.raises(ValidationError):
            BoardsBatchProfileRequest(codes=["885595"], frequency="2h")

    def test_response_defaults(self):
        resp = BoardsBatchProfileResponse()
        assert resp.frequency == "d"
        assert resp.days == 0
        assert resp.boards == []
        assert resp.summary == {}

    def test_response_carries_boards_in_order(self):
        resp = BoardsBatchProfileResponse(
            frequency="d",
            days=60,
            boards=[
                BoardProfile(code="881270"),
                BoardProfile(code="885595"),
            ],
            summary={"requested": 2, "ok": 2, "failed": 0, "elapsed_ms": 100},
        )
        assert [b.code for b in resp.boards] == ["881270", "885595"]
        assert resp.summary["elapsed_ms"] == 100