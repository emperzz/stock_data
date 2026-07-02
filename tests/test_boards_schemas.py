"""Tests for board-related Pydantic schemas."""
import pytest

from stock_data.api.schemas import StockBoardInfo, StockBoardsResponse


def test_stock_board_info_required_fields():
    info = StockBoardInfo(
        code="sw_mt", name="A股-申万行业-煤炭",
        type="industry", subtype="申万行业", source="zhitu",
    )
    assert info.code == "sw_mt"
    assert info.name == "A股-申万行业-煤炭"
    assert info.type == "industry"
    assert info.subtype == "申万行业"
    assert info.source == "zhitu"


def test_stock_board_info_optional_subtype():
    """subtype is required by spec but may be empty string when unknown."""
    info = StockBoardInfo(
        code="some_code", name="some_board",
        type="concept", subtype="", source="eastmoney",
    )
    assert info.subtype == ""
    assert info.source == "eastmoney"


def test_stock_boards_response_shape():
    resp = StockBoardsResponse(
        stock_code="000001",
        source="zhitu",
        data=[
            StockBoardInfo(
                code="sw_yx", name="A股-申万行业-银行",
                type="industry", subtype="申万行业", source="zhitu",
            ),
            StockBoardInfo(
                code="chgn_700532", name="A股-热门概念-MSCI中国",
                type="concept", subtype="热门概念", source="zhitu",
            ),
        ],
    )
    assert resp.stock_code == "000001"
    assert resp.source == "zhitu"
    assert len(resp.data) == 2
    assert resp.data[0].code == "sw_yx"
    assert resp.data[0].source == "zhitu"
    assert resp.data[1].type == "concept"


def test_stock_boards_response_empty_data():
    """Empty boards list is valid (stock belongs to no known boards)."""
    resp = StockBoardsResponse(stock_code="000001", source="zhitu", data=[])
    assert resp.data == []
    assert resp.cold_sources == []


def test_stock_boards_response_default_source_empty():
    """source field defaults to empty string (matches existing patterns)."""
    resp = StockBoardsResponse(stock_code="000001")
    assert resp.source == ""
    assert resp.data == []
    assert resp.cold_sources == []


def test_stock_boards_response_serialization():
    """JSON serialization produces camel/snake as configured."""
    resp = StockBoardsResponse(
        stock_code="000001",
        source="zhitu",
        data=[StockBoardInfo(
            code="sw_yx", name="银行", type="industry", subtype="申万行业", source="zhitu",
        )],
    )
    json_data = resp.model_dump()
    assert json_data["stock_code"] == "000001"
    assert json_data["source"] == "zhitu"
    assert json_data["data"][0]["code"] == "sw_yx"
    assert json_data["data"][0]["source"] == "zhitu"
    assert json_data["cold_sources"] == []


class TestStockBoardInfoSchema:
    """StockBoardInfo must carry per-entry source after merge."""

    def test_stock_board_info_has_source_field(self):
        from stock_data.api.schemas import StockBoardInfo
        info = StockBoardInfo(
            code="BK1048", name="互联网服务", type="concept",
            subtype="concept", source="eastmoney",
        )
        assert info.source == "eastmoney"

    def test_stock_board_info_source_required_after_merge(self):
        from stock_data.api.schemas import StockBoardInfo
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            StockBoardInfo(code="BK1048", name="x", type="concept", subtype="concept")
        # No source → ValidationError (we made it required post-merge)


class TestStockBoardsResponseSchema:
    """StockBoardsResponse must have cold_sources field after merge."""

    def test_response_has_cold_sources_default_empty(self):
        from stock_data.api.schemas import StockBoardsResponse
        r = StockBoardsResponse(stock_code="600519", source="eastmoney", data=[])
        assert r.cold_sources == []

    def test_response_cold_sources_populated(self):
        from stock_data.api.schemas import StockBoardsResponse
        r = StockBoardsResponse(
            stock_code="600519", source="merged", data=[], cold_sources=["zhitu", "zzshare"]
        )
        assert r.cold_sources == ["zhitu", "zzshare"]
