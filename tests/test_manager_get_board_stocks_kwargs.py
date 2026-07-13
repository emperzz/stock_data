"""Verify DataFetcherManager.get_board_stocks forwards sort_by / sort_order / top_n kwargs.

Commit 396800f: feat(manager): forward sort_by / sort_order / top_n in get_board_stocks.
"""
from unittest.mock import MagicMock, patch

from stock_data.data_provider.manager import DataFetcherManager


def test_manager_forwards_sort_kwargs_to_ths_fetcher():
    """当 fetcher 是 ThsFetcher 时, sort_by / sort_order / top_n 应被 call() 注入."""
    manager = DataFetcherManager()

    fake_ths_fetcher = MagicMock()
    fake_ths_fetcher.name = "ThsFetcher"
    fake_ths_fetcher.get_board_stocks.return_value = (
        [{"stock_code": "000034", "stock_name": "x"}],
        "ths",
    )

    with patch.object(manager, "_with_source", return_value=(
        fake_ths_fetcher.get_board_stocks.return_value[0],
        fake_ths_fetcher.name,
    )) as mock_with_source:
        manager.get_board_stocks(
            board_code="885756", source="ths", include_quote=True,
            sort_by="price", sort_order="asc", top_n=10,
        )
        call_kwargs = mock_with_source.call_args.kwargs["call"]
        call_kwargs(fake_ths_fetcher)
        fake_ths_fetcher.get_board_stocks.assert_called_once()
        _, kwargs = fake_ths_fetcher.get_board_stocks.call_args
        assert kwargs.get("sort_by") == "price"
        assert kwargs.get("sort_order") == "asc"
        assert kwargs.get("top_n") == 10
        assert kwargs.get("include_quote") is True
        assert kwargs.get("source") == "ths"


def test_manager_forwards_default_sort_kwargs_when_omitted():
    """Default sort kwargs (None / 'desc' / 50) flow to fetcher when caller omits them.

    Task 5 code quality review Important #1: catches regressions in default values.
    Issue #2 deferred — test works despite full-bootstrap cost.
    """
    manager = DataFetcherManager()

    fake_ths_fetcher = MagicMock()
    fake_ths_fetcher.name = "ThsFetcher"
    fake_ths_fetcher.get_board_stocks.return_value = ([], "ths")

    with patch.object(manager, "_with_source", return_value=(
        fake_ths_fetcher.get_board_stocks.return_value[0],
        fake_ths_fetcher.name,
    )) as mock_with_source:
        # Caller omits sort_by / sort_order / top_n — defaults should still propagate.
        manager.get_board_stocks(
            board_code="885756", source="ths", include_quote=True,
        )
        call_kwargs = mock_with_source.call_args.kwargs["call"]
        call_kwargs(fake_ths_fetcher)
        _, kwargs = fake_ths_fetcher.get_board_stocks.call_args
        assert kwargs.get("sort_by") is None
        assert kwargs.get("sort_order") == "desc"
        assert kwargs.get("top_n") == 50
        # All other kwargs still forwarded
        assert kwargs.get("source") == "ths"
        assert kwargs.get("include_quote") is True
