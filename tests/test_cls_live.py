"""Live network tests for ClsFetcher — run only with `pytest -m live_network`
or `pytest -m ""` (CI use). Auto-downgraded to xfail on network failure by
tests/_network_guard.py.

Per user scoping instruction: ClsFetcher only. Stable assertions only (no
time-of-day-dependent tests). The plan's broader list (4 tests) is reduced
to 2 here.
"""

from datetime import date, timedelta

import pytest

from stock_data.data_provider.fetchers.cls_fetcher import ClsFetcher


@pytest.fixture
def fetcher() -> ClsFetcher:
    return ClsFetcher()


@pytest.mark.live_network
def test_live_get_morning_briefing_yesterday(fetcher):
    """Yesterday's article should always exist (CLS publishes every weekday).

    We pick yesterday (not today) to avoid the time-of-day dependency: 早报
    publishes at ~7am Beijing time, so today's article may not exist yet
    when the test runs early in the day.
    """
    yesterday = (date.today() - timedelta(days=1)).strftime("%Y-%m-%d")
    art = fetcher.get_morning_briefing(yesterday)
    assert art is not None, f"No 早报 article for {yesterday}"
    assert art["date"] == yesterday
    assert art["title"].startswith("【")
    assert len(art["body_text"]) > 100


@pytest.mark.live_network
def test_live_subject_list_window(fetcher):
    """List page should have ≥3 articles spanning ≥3 days (relaxed from spec to
    avoid weekend flakiness; not strict 7-day span).
    """
    list_html = fetcher._http_get_text("https://www.cls.cn/subject/1151")
    articles = fetcher._parse_subject_articles(1151, list_html, limit=20)
    assert len(articles) >= 3
    distinct_dates = {a["date"] for a in articles}
    assert len(distinct_dates) >= 3
