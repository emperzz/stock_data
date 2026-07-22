"""Unified k-line cache key + TTL split per spec §5.4."""

from stock_data.api.cache import (
    _TTL_HISTORY_DAILY,
    _TTL_HISTORY_MONTHLY,
    _TTL_HISTORY_WEEKLY,
    _TTL_STOCK_INTRADAY,
    get_kline_cache,
    make_kline_cache_key,
)


def test_kline_cache_key_contains_all_components():
    """Key contains code, frequency, days, start_date, end_date, adjust, indicators."""
    k = make_kline_cache_key(
        code="600519",
        frequency="5",
        days=1,
        start_date="2026-06-20",
        end_date="2026-06-29",
        adjust="qfq",
        indicators=["ma"],
    )
    assert "600519" in k
    assert "5" in k
    assert "qfq" in k
    assert "2026-06-20" in k
    assert "2026-06-29" in k
    assert "ma" in k


def test_kline_cache_key_empty_indicators():
    """Empty indicators list produces key without trailing comma."""
    k = make_kline_cache_key(
        code="600519",
        frequency="d",
        days=30,
        start_date=None,
        end_date=None,
        adjust=None,
        indicators=[],
    )
    assert "600519" in k
    assert "d" in k
    # No trailing comma from empty indicators join
    assert not k.endswith(",")


def test_kline_cache_key_prefix():
    """All kline cache keys start with 'kline:' prefix."""
    k = make_kline_cache_key(
        code="000001",
        frequency="d",
        days=30,
        start_date=None,
        end_date=None,
        adjust=None,
        indicators=[],
    )
    assert k.startswith("kline:")


def test_get_kline_cache_minute_uses_intraday_ttl():
    """Minute frequencies hit the 30s TTLCache."""
    for freq in ("1", "5", "15", "30", "60"):
        cache = get_kline_cache(freq)
        assert cache.ttl == _TTL_STOCK_INTRADAY, (
            f"frequency={freq!r} should use intraday TTL ({_TTL_STOCK_INTRADAY}s)"
        )


def test_get_kline_cache_daily_uses_history_ttl():
    """Daily frequency hits the daily history cache."""
    cache = get_kline_cache("d")
    assert cache.ttl == _TTL_HISTORY_DAILY


def test_get_kline_cache_weekly_uses_history_ttl():
    """Weekly uses the weekly history cache."""
    cache = get_kline_cache("w")
    assert cache.ttl == _TTL_HISTORY_WEEKLY


def test_get_kline_cache_monthly_uses_history_ttl():
    """Monthly uses the monthly history cache."""
    cache = get_kline_cache("m")
    assert cache.ttl == _TTL_HISTORY_MONTHLY


def test_kline_cache_key_indicator_order_independent():
    """Same indicator set in different orders produces the same cache key."""
    k1 = make_kline_cache_key(
        code="600519",
        frequency="d",
        days=30,
        start_date=None,
        end_date=None,
        adjust=None,
        indicators=["ma", "macd", "kdj"],
    )
    k2 = make_kline_cache_key(
        code="600519",
        frequency="d",
        days=30,
        start_date=None,
        end_date=None,
        adjust=None,
        indicators=["kdj", "ma", "macd"],
    )
    assert k1 == k2
