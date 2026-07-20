"""Schema unit tests for BoardNewsResponse and BoardSurgesResponse.

Added 2026-07-20 per spec. Validates the Pydantic models construct from
fetcher-shaped dicts (with full snake_case fields).
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from stock_data.api.schemas import (
    BoardNewsItem,
    BoardNewsResponse,
    BoardSurgeItem,
    BoardSurgesResponse,
)


def test_board_news_item_required_fields():
    """title + url required; rest optional."""
    item = BoardNewsItem(title="x", url="http://example.com/x")
    assert item.title == "x"
    assert item.url == "http://example.com/x"
    assert item.publish_date == ""
    assert item.publish_time == ""
    assert item.summary == ""
    assert item.source_domain == "news.10jqka.com.cn"


def test_board_news_item_full():
    item = BoardNewsItem(
        title="t", url="http://x",
        publish_date="2026-07-20", publish_time="08:44",
        summary="s", source_domain="custom.example",
    )
    assert item.source_domain == "custom.example"


def test_board_news_response_construction():
    resp = BoardNewsResponse(
        board_code="885914", source="ThsFetcher", total=1,
        data=[BoardNewsItem(title="t", url="http://x")],
    )
    assert resp.total == 1
    assert len(resp.data) == 1


def test_board_surge_item_required_fields():
    """date required; board_change_pct / sh_change_pct optional floats."""
    item = BoardSurgeItem(date="2026-07-14", limit_up_count=8)
    assert item.date == "2026-07-14"
    assert item.board_change_pct is None
    assert item.limit_up_count == 8
    assert item.limit_up_stocks == []
    assert item.up_count is None


def test_board_surge_item_full():
    item = BoardSurgeItem(
        date="2026-07-14",
        board_change_pct=3.67,
        sh_change_pct=0.01,
        limit_up_count=4,
        limit_up_stocks=["600180", "600595"],
        up_count=10,
        down_count=5,
    )
    assert item.board_change_pct == 3.67
    assert item.up_count == 10


def test_board_surges_response_construction():
    resp = BoardSurgesResponse(
        board_code="885914", source="ThsFetcher", total=1,
        data=[BoardSurgeItem(date="2026-07-14", limit_up_count=4)],
    )
    assert resp.total == 1
    assert resp.data[0].limit_up_count == 4


def test_board_news_item_rejects_missing_title():
    """title is required; missing → ValidationError."""
    with pytest.raises(ValidationError):
        BoardNewsItem(url="http://x")  # type: ignore[call-arg]


def test_board_news_item_rejects_missing_url():
    with pytest.raises(ValidationError):
        BoardNewsItem(title="x")  # type: ignore[call-arg]


def test_board_surge_item_rejects_missing_date():
    with pytest.raises(ValidationError):
        BoardSurgeItem(limit_up_count=4)  # type: ignore[call-arg]
