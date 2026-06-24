"""Tests for board-related Pydantic schemas."""
from stock_data.api.schemas import StockBoardInfo, StockBoardsResponse


def test_stock_board_info_required_fields():
    info = StockBoardInfo(
        code="sw_mt", name="A股-申万行业-煤炭",
        type="industry", subtype="申万行业",
    )
    assert info.code == "sw_mt"
    assert info.name == "A股-申万行业-煤炭"
    assert info.type == "industry"
    assert info.subtype == "申万行业"


def test_stock_board_info_optional_subtype():
    """subtype is required by spec but may be empty string when unknown."""
    info = StockBoardInfo(
        code="some_code", name="some_board",
        type="concept", subtype="",
    )
    assert info.subtype == ""


def test_stock_boards_response_shape():
    resp = StockBoardsResponse(
        stock_code="000001",
        source="zhitu",
        data=[
            StockBoardInfo(
                code="sw_yx", name="A股-申万行业-银行",
                type="industry", subtype="申万行业",
            ),
            StockBoardInfo(
                code="chgn_700532", name="A股-热门概念-MSCI中国",
                type="concept", subtype="热门概念",
            ),
        ],
    )
    assert resp.stock_code == "000001"
    assert resp.source == "zhitu"
    assert len(resp.data) == 2
    assert resp.data[0].code == "sw_yx"
    assert resp.data[1].type == "concept"


def test_stock_boards_response_empty_data():
    """Empty boards list is valid (stock belongs to no known boards)."""
    resp = StockBoardsResponse(stock_code="000001", source="zhitu", data=[])
    assert resp.data == []


def test_stock_boards_response_default_source_empty():
    """source field defaults to empty string (matches existing patterns)."""
    resp = StockBoardsResponse(stock_code="000001")
    assert resp.source == ""
    assert resp.data == []


def test_stock_boards_response_serialization():
    """JSON serialization produces camel/snake as configured."""
    resp = StockBoardsResponse(
        stock_code="000001",
        source="zhitu",
        data=[StockBoardInfo(
            code="sw_yx", name="银行", type="industry", subtype="申万行业",
        )],
    )
    json_data = resp.model_dump()
    assert json_data["stock_code"] == "000001"
    assert json_data["source"] == "zhitu"
    assert json_data["data"][0]["code"] == "sw_yx"