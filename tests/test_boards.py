"""
Tests for stock board (concept/industry) API and cache.
"""

from unittest.mock import MagicMock, patch

import pytest

from stock_data.api.routes import reset_manager


@pytest.fixture(autouse=True)
def reset_before_test():
    """Reset manager state before each test."""
    reset_manager()
    yield


# Module-level patch target — the route layer delegates board-list reads
# to the persistence module, so tests mock at that boundary to bypass the
# SQL cache + daily-refresh tracker (which would otherwise leak state across
# tests and turn ``mock.assert_called_once()`` into a flaky assertion).
_PERSISTENCE_PATCH = "stock_data.data_provider.persistence.board.get_board_list"


class TestBoardAPIRoutes:
    """Tests for board API routes."""

    def test_get_concept_boards(self, client):
        """Test GET /api/v1/boards with type=concept."""
        with patch(_PERSISTENCE_PATCH) as mock_get:
            mock_get.return_value = (
                [
                    {
                        "code": "BK1048",
                        "name": "互联网服务",
                        "board_type": "concept",
                        "source": "eastmoney",
                    },
                    {
                        "code": "BK1049",
                        "name": "云计算",
                        "board_type": "concept",
                        "source": "eastmoney",
                    },
                ],
                "EastMoneyFetcher",
            )
            response = client.get("/api/v1/boards?type=concept&source=eastmoney")
            assert response.status_code == 200
            data = response.json()
            assert "data" in data
            assert len(data["data"]) == 2
            assert data["data"][0]["code"] == "BK1048"

    def test_get_industry_boards(self, client):
        """Test GET /api/v1/boards with type=industry."""
        with patch(_PERSISTENCE_PATCH) as mock_get:
            mock_get.return_value = (
                [
                    {
                        "code": "BK0816",
                        "name": "银行",
                        "board_type": "industry",
                        "source": "eastmoney",
                    }
                ],
                "EastMoneyFetcher",
            )
            response = client.get("/api/v1/boards?type=industry&source=eastmoney")
            assert response.status_code == 200
            data = response.json()
            assert "data" in data
            assert len(data["data"]) == 1
            # BoardInfo only has code and name, not board_type
            assert data["data"][0]["code"] == "BK0816"
            assert data["data"][0]["name"] == "银行"

    def test_get_boards_missing_type(self, client):
        """Test GET /api/v1/boards without type parameter returns 422.

        ``type`` is now OPTIONAL on this route (omitting it means "all
        types"), but ``source`` is still REQUIRED — a request with neither
        param therefore still 422s on the missing-source FastAPI check.
        """
        response = client.get("/api/v1/boards")
        assert response.status_code == 422

    def test_get_boards_invalid_type(self, client):
        """Test GET /api/v1/boards with invalid type parameter returns 422."""
        response = client.get("/api/v1/boards?type=invalid")
        # FastAPI validation error returns 422
        assert response.status_code == 422

    def test_get_boards_no_type_returns_all_types(self, client):
        """Omitting ``type`` queries every type the source exposes.

        Source = eastmoney (concept + industry); zzshare is tested in
        ``test_boards_api.py`` because it has its own board list
        ``subtype`` table.
        """
        concept_board = {
            "code": "BK1048",
            "name": "互联网服务",
            "type": "concept",
            "subtype": "concept",
        }
        industry_board = {
            "code": "BK0816",
            "name": "银行",
            "type": "industry",
            "subtype": "industry",
        }
        with patch(_PERSISTENCE_PATCH) as mock_get:
            mock_get.return_value = ([concept_board, industry_board], "mixed")
            response = client.get("/api/v1/boards?source=eastmoney")
        assert response.status_code == 200
        data = response.json()
        assert data["source"] == "mixed"
        codes = {b["code"] for b in data["data"]}
        assert codes == {"BK1048", "BK0816"}
        # Each board carries its type in the response so callers can split
        # the result without re-querying.
        by_code = {b["code"]: b["type"] for b in data["data"]}
        assert by_code["BK1048"] == "concept"
        assert by_code["BK0816"] == "industry"

    def test_get_boards_subtype_without_type_returns_400(self, client):
        """subtype filter requires a ``type`` (subtypes are type-scoped)."""
        response = client.get("/api/v1/boards?source=eastmoney&subtype=concept")
        assert response.status_code == 400
        body = response.json()
        assert "subtype" in str(body)
        assert "type" in str(body)

    def test_get_board_stocks(self, client):
        """Test GET /api/v1/boards/{board_code}/stocks."""
        with (
            patch(
                "stock_data.data_provider.manager.DataFetcherManager.get_board_stocks"
            ) as mock_get_stocks,
            patch(
                "stock_data.data_provider.manager.DataFetcherManager.get_all_boards"
            ) as mock_get_boards,
        ):
            mock_get_stocks.return_value = (
                [
                    {"stock_code": "600519", "stock_name": "贵州茅台"},
                    {"stock_code": "000001", "stock_name": "平安银行"},
                ],
                "EastMoneyFetcher",
            )
            mock_get_boards.return_value = (
                [
                    {
                        "code": "BK1048",
                        "name": "互联网服务",
                        "board_type": "concept",
                        "source": "eastmoney",
                    }
                ],
                "EastMoneyFetcher",
            )
            response = client.get("/api/v1/boards/BK1048/stocks?source=eastmoney")
            assert response.status_code == 200
            data = response.json()
            assert "board" in data
            assert "stocks" in data
            assert data["board"]["code"] == "BK1048"
            assert len(data["stocks"]) == 2

    def test_get_board_stocks_with_quote(self, client):
        """Test GET /api/v1/boards/{board_code}/stocks?include_quote=true.

        After the refactor, the route still calls ``get_realtime_quote`` for
        each stock to enrich the response. We patch that on the manager and
        the new board manager methods.
        """
        with (
            patch(
                "stock_data.data_provider.manager.DataFetcherManager.get_board_stocks"
            ) as _mock_get_stocks,
            patch(
                "stock_data.data_provider.manager.DataFetcherManager.get_all_boards"
            ) as _mock_get_boards,
            patch("stock_data.api.routes.boards.get_manager") as mock_manager,
        ):
            mock_mgr = MagicMock()
            mock_quote = MagicMock()
            mock_quote.code = "600519"
            mock_quote.name = "贵州茅台"
            mock_quote.price = 1800.0
            mock_quote.change_pct = 2.5
            mock_quote.volume = 1000000
            mock_mgr.get_realtime_quote.return_value = mock_quote
            mock_mgr.get_board_stocks.return_value = (
                [{"stock_code": "600519", "stock_name": "贵州茅台"}],
                "EastMoneyFetcher",
            )
            mock_mgr.get_all_boards.return_value = (
                [
                    {
                        "code": "BK1048",
                        "name": "互联网服务",
                        "board_type": "concept",
                        "source": "eastmoney",
                    }
                ],
                "EastMoneyFetcher",
            )
            mock_manager.return_value = mock_mgr

            response = client.get(
                "/api/v1/boards/BK1048/stocks?source=eastmoney&include_quote=true"
            )
            assert response.status_code == 200
            data = response.json()
            assert "stocks" in data
            assert len(data["stocks"]) == 1
            assert "price" in data["stocks"][0]

    def test_get_boards_with_refresh(self, client):
        """Test GET /api/v1/boards?refresh=true forces refresh."""
        with patch(_PERSISTENCE_PATCH) as mock_get:
            mock_get.return_value = (
                [
                    {
                        "code": "BK1048",
                        "name": "互联网服务",
                        "board_type": "concept",
                        "source": "eastmoney",
                    }
                ],
                "EastMoneyFetcher",
            )
            response = client.get("/api/v1/boards?type=concept&source=eastmoney&refresh=true")
            assert response.status_code == 200
            mock_get.assert_called_once()
            # source= passed as keyword arg
            _, kwargs = mock_get.call_args
            assert kwargs.get("source") == "eastmoney"

    def test_get_boards_with_source(self, client):
        """Test GET /api/v1/boards?source=eastmoney (zhitu would be 400 from literal)."""
        with patch(_PERSISTENCE_PATCH) as mock_get:
            mock_get.return_value = ([], "EastMoneyFetcher")
            response = client.get("/api/v1/boards?type=concept&source=eastmoney")
            assert response.status_code == 200
            mock_get.assert_called_once()
            _, kwargs = mock_get.call_args
            # source is passed as keyword arg
            assert kwargs.get("source") == "eastmoney"

    def test_get_boards_with_include_quote(self, client):
        """Test GET /api/v1/boards?include_quote=true passes include_quote to manager."""
        with patch(_PERSISTENCE_PATCH) as mock_get:
            mock_get.return_value = (
                [
                    {
                        "code": "BK1048",
                        "name": "互联网服务",
                        "board_type": "concept",
                        "source": "eastmoney",
                        "price": 1850.5,
                        "change_pct": 2.35,
                        "change_amount": 42.3,
                        "volume": 52000000,
                        "amount": 95800000000.0,
                        "turnover_rate": 3.58,
                        "total_mv": 2345000000000.0,
                        "up_count": 45,
                        "down_count": 12,
                        "leading_stock": "科大讯飞",
                        "leading_stock_pct": 8.5,
                    },
                ],
                "EastMoneyFetcher",
            )
            response = client.get("/api/v1/boards?type=concept&source=eastmoney&include_quote=true")
            assert response.status_code == 200
            data = response.json()
            assert len(data["data"]) == 1
            board = data["data"][0]
            assert board["code"] == "BK1048"
            assert board["price"] == 1850.5
            assert board["change_pct"] == 2.35
            assert board["change_amount"] == 42.3
            assert board["volume"] == 52000000
            assert board["up_count"] == 45
            assert board["down_count"] == 12
            assert board["leading_stock"] == "科大讯飞"
            assert board["leading_stock_pct"] == 8.5
            # Verify include_quote was passed through to persistence
            mock_get.assert_called_once()
            _, kwargs = mock_get.call_args
            assert kwargs.get("include_quote") is True

    def test_get_boards_include_quote_still_hits_persistence(self, client):
        """Test GET /api/v1/boards?include_quote=true calls persistence layer."""
        with (
            patch(_PERSISTENCE_PATCH) as mock_get,
        ):
            mock_get.return_value = (
                [
                    {
                        "code": "BK1048",
                        "name": "互联网服务",
                        "board_type": "concept",
                        "source": "eastmoney",
                    }
                ],
                "EastMoneyFetcher",
            )
            response = client.get("/api/v1/boards?type=concept&source=eastmoney&include_quote=true")
            assert response.status_code == 200
            mock_get.assert_called_once()
            _, kwargs = mock_get.call_args
            assert kwargs.get("include_quote") is True


class TestAkshareFetcherBoards:
    """Tests that AkshareFetcher no longer claims STOCK_BOARD.

    STOCK_BOARD was migrated to EastMoneyFetcher (commit 25b7819) and
    ZhituFetcher (commit 9367351). AkshareFetcher should NOT declare the
    capability or expose board methods.
    """

    def test_board_capability_not_declared(self):
        """AkshareFetcher should NOT have STOCK_BOARD capability."""
        from stock_data.data_provider.base import DataCapability
        from stock_data.data_provider.fetchers.akshare import AkshareFetcher

        fetcher = AkshareFetcher()
        assert DataCapability.STOCK_BOARD not in fetcher.supported_data_types

    def test_board_methods_removed(self):
        """AkshareFetcher should NOT expose legacy board methods."""
        from stock_data.data_provider.fetchers.akshare import AkshareFetcher

        fetcher = AkshareFetcher()
        assert not hasattr(fetcher, "get_all_concept_boards")
        assert not hasattr(fetcher, "get_all_industry_boards")
        assert not hasattr(fetcher, "get_concept_board_stocks")
        assert not hasattr(fetcher, "get_industry_board_stocks")
        assert not hasattr(fetcher, "_enrich_stock_from_realtime")


class TestDataFetcherManagerBoards:
    """Tests for DataFetcherManager board methods."""

    def test_manager_has_board_methods(self):
        """Test DataFetcherManager has the unified board entry points."""
        from stock_data.data_provider import DataFetcherManager

        manager = DataFetcherManager()
        assert hasattr(manager, "get_all_boards")
        assert hasattr(manager, "get_board_stocks")
        assert hasattr(manager, "get_stock_boards")
        assert hasattr(manager, "get_board_history")
        # Legacy concept/industry split methods should be removed
        assert not hasattr(manager, "get_all_concept_boards")
        assert not hasattr(manager, "get_all_industry_boards")
        assert not hasattr(manager, "get_concept_board_stocks")
        assert not hasattr(manager, "get_industry_board_stocks")


class TestBoardSchemas:
    """Tests for board Pydantic schemas."""

    def test_board_info_schema(self):
        """Test BoardInfo schema."""
        from stock_data.api.schemas import BoardInfo

        board = BoardInfo(code="BK1048", name="互联网服务")
        assert board.code == "BK1048"
        assert board.name == "互联网服务"

    def test_board_info_schema_with_quote_fields(self):
        """Test BoardInfo schema with all quote fields."""
        from stock_data.api.schemas import BoardInfo

        board = BoardInfo(
            code="BK1048",
            name="互联网服务",
            price=1850.5,
            change_pct=2.35,
            change_amount=42.3,
            volume=52000000,
            amount=95800000000.0,
            turnover_rate=3.58,
            total_mv=2345000000000.0,
            up_count=45,
            down_count=12,
            leading_stock="科大讯飞",
            leading_stock_pct=8.5,
        )
        assert board.code == "BK1048"
        assert board.price == 1850.5
        assert board.change_pct == 2.35
        assert board.volume == 52000000
        assert board.up_count == 45
        assert board.down_count == 12
        assert board.leading_stock == "科大讯飞"
        assert board.leading_stock_pct == 8.5

    def test_board_info_schema_quote_fields_optional(self):
        """Test BoardInfo quote fields default to None."""
        from stock_data.api.schemas import BoardInfo

        board = BoardInfo(code="BK1048", name="互联网服务")
        assert board.price is None
        assert board.change_pct is None
        assert board.volume is None
        assert board.up_count is None
        assert board.leading_stock is None

    def test_board_list_response_schema(self):
        """Test BoardListResponse schema."""
        from stock_data.api.schemas import BoardInfo, BoardListResponse

        boards = [BoardInfo(code="BK1048", name="互联网服务")]
        response = BoardListResponse(data=boards)
        assert len(response.data) == 1

    def test_board_stocks_response_schema(self):
        """Test BoardStocksResponse schema."""
        from stock_data.api.schemas import BoardInfo, BoardStockInfo, BoardStocksResponse

        board = BoardInfo(code="BK1048", name="互联网服务")
        stocks = [BoardStockInfo(code="600519", name="贵州茅台")]
        response = BoardStocksResponse(
            board=board, stocks=stocks, query_source="eastmoney", data_source="akshare"
        )
        assert response.board.code == "BK1048"
        assert len(response.stocks) == 1
        assert response.query_source == "eastmoney"
        assert response.data_source == "akshare"

    def test_board_stock_info_with_quote(self):
        """Test BoardStockInfo with quote data."""
        from stock_data.api.schemas import BoardStockInfo

        stock = BoardStockInfo(
            code="600519", name="贵州茅台", price=1800.0, change_pct=2.5, volume=1000000
        )
        assert stock.price == 1800.0
        assert stock.change_pct == 2.5
        assert stock.volume == 1000000

    def test_board_kline_response_serializes_zhongzheng_shape(self):
        """BoardKlineResponse wraps KLineData[] and exposes source."""
        from stock_data.api.schemas import BoardKlineResponse, KLineData

        r = BoardKlineResponse(
            board_code="883957",
            board_name="同花顺全A",
            period="daily",
            data=[
                KLineData(
                    date="2026-05-20",
                    open=100.0,
                    high=105.0,
                    low=99.0,
                    close=104.0,
                    volume=1_000_000,
                    amount=104_000_000.0,
                    change_percent=4.0,
                ),
            ],
            source="ZzshareFetcher",
        )
        out = r.model_dump()
        assert out["board_code"] == "883957"
        assert out["board_name"] == "同花顺全A"
        assert out["period"] == "daily"
        assert out["source"] == "ZzshareFetcher"
        assert len(out["data"]) == 1
        assert out["data"][0]["date"] == "2026-05-20"
        # KLineData conditional serialization: indicators absent when None
        assert "indicators" not in out["data"][0]  # type: ignore[index]  # fmt: skip
