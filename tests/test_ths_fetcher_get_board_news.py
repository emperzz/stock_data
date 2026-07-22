"""Tests for ThsFetcher.get_board_news (news.10jqka.com.cn timeline API).

Rewritten 2026-07-21: board news switched from the F10-page scrape (14-item
cap, no summary) to the unauthenticated timeline endpoint
``news.10jqka.com.cn/timeline_web/web/v1/news/list``. Fixture mirrors the real
upstream payload shape (probed 2026-07-21 on 885756): each item carries
title / source / summary / publishTime(ms) / jumpUrl / picUrl.
"""

from __future__ import annotations

from datetime import datetime
from unittest.mock import patch

from stock_data.data_provider.fetchers import ths_fetcher as tff
from stock_data.data_provider.fetchers.ths_fetcher import ThsFetcher


def _payload(items, status_code=0):
    return {
        "data": {"newsList": items, "hasMore": True, "offset": "1784462957.274388"},
        "status_code": status_code,
        "status_msg": "",
    }


_ITEM = {
    "id": "1_678298741",
    "type": 1,
    "title": "芯原股份：公司采用晶圆厂中立策略",
    "author": "",
    "source": "证券日报网",
    "summary": "　　证券日报网7月20日讯，芯原股份在接受调研时表示……",
    "publishTime": 1784548905000,
    "jumpUrl": "https://news.10jqka.com.cn/20260720/c678298741.shtml",
    "picUrl": "https://u.thsi.cn/imgsrc/news/aa937.jpg",
}


def test_get_board_news_maps_fields():
    with patch.object(tff, "json_get", return_value=_payload([_ITEM])) as jg:
        news = ThsFetcher().get_board_news("885756", limit=20)
    # Contract: right endpoint, marketId=48, size == clamped limit.
    jg.assert_called_once()
    assert jg.call_args.args[0] == tff._THS_TIMELINE_NEWS_URL
    assert jg.call_args.kwargs["params"] == {"marketId": "48", "code": "885756", "size": 20}
    assert len(news) == 1
    n = news[0]
    assert n["title"] == _ITEM["title"]
    assert n["url"] == _ITEM["jumpUrl"]
    assert n["summary"] == _ITEM["summary"].strip()
    assert n["source_domain"] == "news.10jqka.com.cn"
    dt = datetime.fromtimestamp(_ITEM["publishTime"] / 1000, tff._THS_TZ)
    assert n["publish_date"] == dt.strftime("%Y-%m-%d")
    assert n["publish_time"] == dt.strftime("%H:%M")


def test_get_board_news_limit_clamped_to_1_50():
    with patch.object(tff, "json_get", return_value=_payload([])) as jg:
        ThsFetcher().get_board_news("885756", limit=999)
    assert jg.call_args.kwargs["params"]["size"] == 50
    with patch.object(tff, "json_get", return_value=_payload([])) as jg:
        ThsFetcher().get_board_news("885756", limit=0)
    assert jg.call_args.kwargs["params"]["size"] == 1


def test_get_board_news_missing_publishtime_yields_blank_dates():
    item = {k: v for k, v in _ITEM.items() if k != "publishTime"}
    with patch.object(tff, "json_get", return_value=_payload([item])):
        news = ThsFetcher().get_board_news("885756")
    assert news[0]["publish_date"] == "" and news[0]["publish_time"] == ""


def test_get_board_news_limit_truncates():
    items = [
        dict(_ITEM, id=str(i), jumpUrl=f"https://news.10jqka.com.cn/x{i}.shtml") for i in range(10)
    ]
    with patch.object(tff, "json_get", return_value=_payload(items)):
        news = ThsFetcher().get_board_news("885756", limit=3)
    assert len(news) == 3


def test_get_board_news_bad_status_returns_empty():
    with patch.object(tff, "json_get", return_value=_payload([_ITEM], status_code=-1)):
        assert ThsFetcher().get_board_news("885756") == []


def test_get_board_news_non_dict_returns_empty():
    with patch.object(tff, "json_get", return_value=None):
        assert ThsFetcher().get_board_news("885756") == []


def test_get_board_news_empty_list_returns_empty():
    with patch.object(tff, "json_get", return_value=_payload([])):
        assert ThsFetcher().get_board_news("885756") == []


def test_get_board_news_skips_items_missing_title_or_url():
    items = [
        dict(_ITEM, title="", jumpUrl="https://news.10jqka.com.cn/a.shtml"),
        dict(_ITEM, jumpUrl=""),
        _ITEM,
    ]
    with patch.object(tff, "json_get", return_value=_payload(items)):
        news = ThsFetcher().get_board_news("885756")
    assert len(news) == 1
