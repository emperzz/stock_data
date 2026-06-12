"""
Tests for stock board (concept/industry) API and cache.
"""

from unittest.mock import MagicMock, patch

import pytest

from stock_data.api.routes import reset_manager
from stock_data.server import app


@pytest.fixture(autouse=True)
def reset_before_test():
    """Reset manager state before each test."""
    reset_manager()
    yield


@pytest.fixture
def client():
    from fastapi.testclient import TestClient
    return TestClient(app)


class TestBoardAPIRoutes:
    """Tests for board API routes."""

    def test_get_concept_boards(self, client):
        """Test GET /api/v1/boards with type=concept."""
        with patch("stock_data.api.routes.stock_board_cache.get_board_list") as mock_get:
            mock_get.return_value = (
                [
                    {"code": "BK1048", "name": "互联网服务", "board_type": "concept", "source": "eastmoney"},
                    {"code": "BK1049", "name": "云计算", "board_type": "concept", "source": "eastmoney"},
                ],
                "akshare",
            )
            response = client.get("/api/v1/boards?type=concept")
            assert response.status_code == 200
            data = response.json()
            assert "data" in data
            assert len(data["data"]) == 2
            assert data["data"][0]["code"] == "BK1048"

    def test_get_industry_boards(self, client):
        """Test GET /api/v1/boards with type=industry."""
        with patch("stock_data.api.routes.stock_board_cache.get_board_list") as mock_get:
            mock_get.return_value = (
                [{"code": "BK0816", "name": "银行", "board_type": "industry", "source": "eastmoney"}],
                "akshare",
            )
            response = client.get("/api/v1/boards?type=industry")
            assert response.status_code == 200
            data = response.json()
            assert "data" in data
            assert len(data["data"]) == 1
            # BoardInfo only has code and name, not board_type
            assert data["data"][0]["code"] == "BK0816"
            assert data["data"][0]["name"] == "银行"

    def test_get_boards_missing_type(self, client):
        """Test GET /api/v1/boards without type parameter returns 422."""
        response = client.get("/api/v1/boards")
        assert response.status_code == 422

    def test_get_boards_invalid_type(self, client):
        """Test GET /api/v1/boards with invalid type parameter returns 422."""
        response = client.get("/api/v1/boards?type=invalid")
        # FastAPI validation error returns 422
        assert response.status_code == 422

    def test_get_board_stocks(self, client):
        """Test GET /api/v1/boards/{board_code}/stocks."""
        with (
            patch("stock_data.api.routes.stock_board_cache.get_board_stocks") as mock_get_stocks,
            patch("stock_data.api.routes.stock_board_cache.get_board_list") as mock_get_boards,
        ):
            mock_get_stocks.return_value = (
                [
                    {"stock_code": "600519", "stock_name": "贵州茅台"},
                    {"stock_code": "000001", "stock_name": "平安银行"},
                ],
                "akshare",
            )
            mock_get_boards.return_value = (
                [{"code": "BK1048", "name": "互联网服务", "board_type": "concept", "source": "eastmoney"}],
                "akshare",
            )
            response = client.get("/api/v1/boards/BK1048/stocks")
            assert response.status_code == 200
            data = response.json()
            assert "board" in data
            assert "stocks" in data
            assert data["board"]["code"] == "BK1048"
            assert len(data["stocks"]) == 2

    def test_get_board_stocks_with_quote(self, client):
        """Test GET /api/v1/boards/{board_code}/stocks?include_quote=true."""
        with (
            patch("stock_data.api.routes.stock_board_cache.get_board_stocks") as mock_get_stocks,
            patch("stock_data.api.routes.stock_board_cache.get_board_list") as mock_get_boards,
        ):
            mock_get_stocks.return_value = (
                [{"stock_code": "600519", "stock_name": "贵州茅台"}],
                "akshare",
            )
            mock_get_boards.return_value = (
                [{"code": "BK1048", "name": "互联网服务", "board_type": "concept", "source": "eastmoney"}],
                "akshare",
            )
            with patch("stock_data.api.routes.get_manager") as mock_manager:
                mock_mgr = MagicMock()
                mock_quote = MagicMock()
                mock_quote.code = "600519"
                mock_quote.name = "贵州茅台"
                mock_quote.price = 1800.0
                mock_quote.change_pct = 2.5
                mock_quote.volume = 1000000
                mock_mgr.get_realtime_quote.return_value = mock_quote
                mock_manager.return_value = mock_mgr

                response = client.get("/api/v1/boards/BK1048/stocks?include_quote=true")
                assert response.status_code == 200
                data = response.json()
                assert "stocks" in data
                assert len(data["stocks"]) == 1
                assert "price" in data["stocks"][0]

    def test_get_boards_with_refresh(self, client):
        """Test GET /api/v1/boards?refresh=true forces refresh."""
        with patch("stock_data.api.routes.stock_board_cache.get_board_list") as mock_get:
            mock_get.return_value = (
                [{"code": "BK1048", "name": "互联网服务", "board_type": "concept", "source": "eastmoney"}],
                "akshare",
            )
            response = client.get("/api/v1/boards?type=concept&refresh=true")
            assert response.status_code == 200
            mock_get.assert_called_once()
            _, kwargs = mock_get.call_args
            assert kwargs.get("refresh") is True

    def test_get_boards_with_source(self, client):
        """Test GET /api/v1/boards?source=tonghuashun."""
        with patch("stock_data.api.routes.stock_board_cache.get_board_list") as mock_get:
            mock_get.return_value = ([], "")
            response = client.get("/api/v1/boards?type=concept&source=tonghuashun")
            assert response.status_code == 200
            mock_get.assert_called_once()
            args, kwargs = mock_get.call_args
            # source is passed as positional arg (2nd arg)
            assert args[1] == "tonghuashun"

    def test_get_boards_with_include_quote(self, client):
        """Test GET /api/v1/boards?include_quote=true passes include_quote to cache layer."""
        with patch("stock_data.api.routes.stock_board_cache.get_board_list") as mock_get:
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
                "akshare",
            )
            response = client.get("/api/v1/boards?type=concept&include_quote=true")
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
            # Verify include_quote was passed to cache layer
            mock_get.assert_called_once()
            _, kwargs = mock_get.call_args
            assert kwargs.get("include_quote") is True

    def test_get_boards_include_quote_still_hits_persistence(self, client):
        """Test GET /api/v1/boards?include_quote=true calls persistence (no TTLCache)."""
        with (
            patch("stock_data.api.routes.stock_board_cache.get_board_list") as mock_get,
        ):
            mock_get.return_value = (
                [{"code": "BK1048", "name": "互联网服务", "board_type": "concept", "source": "eastmoney"}],
                "akshare",
            )
            response = client.get("/api/v1/boards?type=concept&include_quote=true")
            assert response.status_code == 200
            mock_get.assert_called_once()
            _, kwargs = mock_get.call_args
            assert kwargs.get("include_quote") is True


class TestAkshareFetcherBoards:
    """Tests for AkshareFetcher board methods."""

    def test_get_all_concept_boards(self):
        """Test get_all_concept_boards returns list of dicts."""
        from stock_data.data_provider.fetchers.akshare import AkshareFetcher

        fetcher = AkshareFetcher()
        assert hasattr(fetcher, "get_all_concept_boards")

    def test_get_all_industry_boards(self):
        """Test get_all_industry_boards returns list of dicts."""
        from stock_data.data_provider.fetchers.akshare import AkshareFetcher

        fetcher = AkshareFetcher()
        assert hasattr(fetcher, "get_all_industry_boards")

    def test_get_concept_board_stocks(self):
        """Test get_concept_board_stocks method exists."""
        from stock_data.data_provider.fetchers.akshare import AkshareFetcher

        fetcher = AkshareFetcher()
        assert hasattr(fetcher, "get_concept_board_stocks")

    def test_get_industry_board_stocks(self):
        """Test get_industry_board_stocks method exists."""
        from stock_data.data_provider.fetchers.akshare import AkshareFetcher

        fetcher = AkshareFetcher()
        assert hasattr(fetcher, "get_industry_board_stocks")

    def test_get_all_concept_boards_include_quote_parameter(self):
        """Test get_all_concept_boards accepts include_quote parameter."""
        import inspect

        from stock_data.data_provider.fetchers.akshare import AkshareFetcher

        fetcher = AkshareFetcher()
        sig = inspect.signature(fetcher.get_all_concept_boards)
        assert "include_quote" in sig.parameters

    def test_get_all_industry_boards_include_quote_parameter(self):
        """Test get_all_industry_boards accepts include_quote parameter."""
        import inspect

        from stock_data.data_provider.fetchers.akshare import AkshareFetcher

        fetcher = AkshareFetcher()
        sig = inspect.signature(fetcher.get_all_industry_boards)
        assert "include_quote" in sig.parameters

    def test_board_capability_declared(self):
        """Test AkshareFetcher has STOCK_BOARD capability."""
        from stock_data.data_provider.base import DataCapability
        from stock_data.data_provider.fetchers.akshare import AkshareFetcher

        fetcher = AkshareFetcher()
        assert DataCapability.STOCK_BOARD in fetcher.supported_data_types


class TestDataFetcherManagerBoards:
    """Tests for DataFetcherManager board methods."""

    def test_manager_has_board_methods(self):
        """Test DataFetcherManager has board methods."""
        from stock_data.data_provider.base import DataFetcherManager

        manager = DataFetcherManager()
        assert hasattr(manager, "get_all_concept_boards")
        assert hasattr(manager, "get_all_industry_boards")
        assert hasattr(manager, "get_concept_board_stocks")
        assert hasattr(manager, "get_industry_board_stocks")


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

        stock = BoardStockInfo(code="600519", name="贵州茅台", price=1800.0, change_pct=2.5, volume=1000000)
        assert stock.price == 1800.0
        assert stock.change_pct == 2.5
        assert stock.volume == 1000000
