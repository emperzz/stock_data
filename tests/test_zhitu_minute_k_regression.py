"""Zhitu minute-K regression guard.

Currently (rev 3, post-Task 1+4) Zhitu declares STOCK_KLINE but its
get_kline_data raises DataFetchError for minute frequencies. The
manager falls back to the next fetcher (which serves minute K), so
end-to-end minute K works — but the redundant failover cost is
real and Zhitu's `supports_kline()` override (Task 3) + manager
two-stage filter (Task 5) should make this clean.

This test is xfail until Tasks 2+3 land. Remove the xfail once the
failover cost is eliminated (Zhitu filtered out at supports_kline()
time).
"""
import pytest


@pytest.mark.xfail(
    reason=(
        "Zhitu minute K currently costs an extra failover; awaits "
        "Task 2 (BaseFetcher.supports_kline default) + Task 3 "
        "(Zhitu override returning True for minutes) + Task 5 "
        "(manager two-stage filter)."
    ),
    strict=False,  # mark xpass when actually fixed
)
def test_zhitu_supports_minute_k_returns_true():
    """When Task 3 lands, Zhitu.supports_kline('5', '', 'csi', 'stock') should be True.

    Today (Task 1+4 only) Zhitu still declares STOCK_KLINE for both
    daily and minute, so manager enters Zhitu -> raises DataFetchError
    -> failover to next fetcher. End-to-end minute K works (via the
    failover), but at the cost of one extra upstream attempt.

    Task 3 will add Zhitu.supports_kline() override that returns True
    ONLY for minute frequencies (Zhitu has minute K via its SDK but
    not daily). Task 5 will add the two-stage manager filter so Zhitu
    is selected on the first try.
    """
    from stock_data.data_provider.fetchers.zhitu_fetcher import ZhituFetcher

    # Scaffolding: probe Zhitu.supports_kline(...) once it's defined.
    if not hasattr(ZhituFetcher, "supports_kline"):
        pytest.xfail("supports_kline method not yet on BaseFetcher (Task 2)")

    # Construct without __init__ (avoids reading ZHITU_TOKEN env var).
    f = ZhituFetcher.__new__(ZhituFetcher)
    f.supported_markets = ZhituFetcher.supported_markets

    # Once Task 3 lands, Zhitu should support minute frequencies.
    assert f.supports_kline("5", "", "csi", "stock") is True


@pytest.mark.xfail(
    reason=(
        "Zhitu daily K currently routes through Zhitu -> raise -> "
        "failover (Zhitu is daily-only via get_intraday_data, not "
        "get_kline_data). Task 3+5 should filter Zhitu out for daily."
    ),
    strict=False,
)
def test_zhitu_supports_daily_k_returns_false():
    """When Task 3 lands, Zhitu.supports_kline('d', '', 'csi', 'stock') should be False.

    Zhitu's daily K is implemented as get_intraday_data + aggregation
    on the SDK side; its get_kline_data raises for daily. The two-
    stage manager filter (Task 5) needs to know Zhitu handles minutes
    only — not dailies.
    """
    from stock_data.data_provider.fetchers.zhitu_fetcher import ZhituFetcher

    if not hasattr(ZhituFetcher, "supports_kline"):
        pytest.xfail("supports_kline method not yet on BaseFetcher (Task 2)")

    f = ZhituFetcher.__new__(ZhituFetcher)
    f.supported_markets = ZhituFetcher.supported_markets

    # Once Task 3 lands, Zhitu should NOT be a candidate for daily K.
    assert f.supports_kline("d", "", "csi", "stock") is False
