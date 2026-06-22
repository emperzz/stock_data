"""验证 manager wrappers 返回 (data, source) 元组。

Task 1 of the source-tracking implementation plan: 12 manager wrapper
methods must return ``(data, source_name)`` tuples so the API layer can
report which fetcher served each response.

Reference: ``stock_data/data_provider/manager.py`` (manager wrappers
at lines 495-567). All wrappers share the same shape: a thin
``_with_failover`` call that already supports ``return_source=True``.
"""
import pytest

from stock_data.data_provider.base import DataCapability
from stock_data.data_provider.manager import DataFetcherManager

# ---------------------------------------------------------------------------
# Mock fetcher that implements all 12 methods under test
# ---------------------------------------------------------------------------


class _MockFetcher:
    """In-memory fetcher that declares every capability the 12 wrappers need.

    Using a single mock keeps the test fixture trivial — one registration
    covers all 12 wrappers. Each method returns a minimal "found" value
    so the manager's ``_is_meaningful`` check passes and the source name
    surfaces as the tuple's second element.
    """

    name = "mock_fetcher"
    priority = 1
    supported_markets = {"csi"}
    supported_data_types = (
        DataCapability.DRAGON_TIGER
        | DataCapability.MARGIN_TRADING
        | DataCapability.BLOCK_TRADE
        | DataCapability.HOLDER_NUM
        | DataCapability.DIVIDEND
        | DataCapability.FUND_FLOW
        | DataCapability.HOT_TOPICS
        | DataCapability.NORTH_FLOW
        | DataCapability.RESEARCH_REPORT
        | DataCapability.ANNOUNCEMENT
    )

    def get_dragon_tiger(self, code, trade_date, look_back):
        return {
            "records": [],
            "seats": {"buy": [], "sell": []},
            "institution": {},
        }

    def get_daily_dragon_tiger(self, trade_date, min_net_buy):
        return {
            "records": [],
            "seats": {"buy": [], "sell": []},
            "institution": {},
        }

    def get_margin_trading(self, code, page_size):
        return [{"code": code, "margin_balance": 100.0}]

    def get_block_trade(self, code, page_size):
        return [{"code": code, "price": 10.0}]

    def get_holder_num_change(self, code, page_size):
        return [{"code": code, "holder_num": 1000}]

    def get_dividend(self, code, page_size):
        return [{"code": code, "dividend": 0.5}]

    def get_fund_flow_minute(self, code):
        return [{"code": code, "net_inflow": 100.0}]

    def get_fund_flow_120d(self, code):
        return [{"code": code, "net_inflow": 100.0}]

    def get_hot_topics(self, date_str):
        return [{"topic": "test", "heat": 100}]

    def get_north_flow(self):
        return [{"date": "2024-01-01", "net_buy": 100.0}]

    def get_reports(self, code, max_pages):
        return [{"code": code, "title": "test report"}]

    def get_announcements(self, code, page_size):
        return [{"code": code, "title": "test announcement"}]


# ---------------------------------------------------------------------------
# Fixture: a manager wired to a single mock fetcher
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_manager():
    """Manager with one mock fetcher registered (priority 1)."""
    manager = DataFetcherManager()
    manager.add_fetcher(_MockFetcher())
    return manager


# ---------------------------------------------------------------------------
# Tests: each of the 12 wrappers must return (data, source)
# ---------------------------------------------------------------------------


def test_get_dragon_tiger_returns_tuple(mock_manager):
    data, source = mock_manager.get_dragon_tiger("600519", "", 30)
    assert source == "mock_fetcher"
    assert isinstance(data, dict)


def test_get_daily_dragon_tiger_returns_tuple(mock_manager):
    data, source = mock_manager.get_daily_dragon_tiger("", None)
    assert source == "mock_fetcher"
    assert isinstance(data, dict)


def test_get_margin_trading_returns_tuple(mock_manager):
    data, source = mock_manager.get_margin_trading("600519", 30)
    assert source == "mock_fetcher"
    assert isinstance(data, list)


def test_get_block_trade_returns_tuple(mock_manager):
    data, source = mock_manager.get_block_trade("600519", 20)
    assert source == "mock_fetcher"
    assert isinstance(data, list)


def test_get_holder_num_change_returns_tuple(mock_manager):
    data, source = mock_manager.get_holder_num_change("600519", 10)
    assert source == "mock_fetcher"
    assert isinstance(data, list)


def test_get_dividend_returns_tuple(mock_manager):
    data, source = mock_manager.get_dividend("600519", 20)
    assert source == "mock_fetcher"
    assert isinstance(data, list)


def test_get_fund_flow_minute_returns_tuple(mock_manager):
    data, source = mock_manager.get_fund_flow_minute("600519")
    assert source == "mock_fetcher"
    assert isinstance(data, list)


def test_get_fund_flow_120d_returns_tuple(mock_manager):
    data, source = mock_manager.get_fund_flow_120d("600519")
    assert source == "mock_fetcher"
    assert isinstance(data, list)


def test_get_hot_topics_returns_tuple(mock_manager):
    data, source = mock_manager.get_hot_topics("")
    assert source == "mock_fetcher"
    assert isinstance(data, list)


def test_get_north_flow_returns_tuple(mock_manager):
    data, source = mock_manager.get_north_flow()
    assert source == "mock_fetcher"
    assert isinstance(data, list)


def test_get_reports_returns_tuple(mock_manager):
    data, source = mock_manager.get_reports("600519", 5)
    assert source == "mock_fetcher"
    assert isinstance(data, list)


def test_get_announcements_returns_tuple(mock_manager):
    data, source = mock_manager.get_announcements("600519", 30)
    assert source == "mock_fetcher"
    assert isinstance(data, list)


# ---------------------------------------------------------------------------
# Coverage: tuple structure (2-element, second element is the fetcher name)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "method_name, args",
    [
        ("get_dragon_tiger", ("600519", "", 30)),
        ("get_daily_dragon_tiger", ("", None)),
        ("get_margin_trading", ("600519", 30)),
        ("get_block_trade", ("600519", 20)),
        ("get_holder_num_change", ("600519", 10)),
        ("get_dividend", ("600519", 20)),
        ("get_fund_flow_minute", ("600519",)),
        ("get_fund_flow_120d", ("600519",)),
        ("get_hot_topics", ("",)),
        ("get_north_flow", ()),
        ("get_reports", ("600519", 5)),
        ("get_announcements", ("600519", 30)),
    ],
)
def test_wrapper_returns_2tuple(mock_manager, method_name, args):
    """Every wrapper must return a 2-tuple (data, source_name)."""
    method = getattr(mock_manager, method_name)
    result = method(*args)
    assert isinstance(result, tuple)
    assert len(result) == 2
    data, source = result
    assert source == "mock_fetcher"
    assert source == _MockFetcher.name
