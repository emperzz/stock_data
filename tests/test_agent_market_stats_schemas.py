"""Schema validation tests for GET /api/v1/agent/market-stats."""

from stock_data.api.schemas import (
    BoardStats,
    DistributionBucket,
    MarketStatsErrorEntry,
    MarketStatsResponse,
    StockStats,
)


def _bucket(label: str, lower, upper, count: int) -> DistributionBucket:
    return DistributionBucket(label=label, lower=lower, upper=upper, count=count)


def test_distribution_bucket_serialization():
    b = _bucket("(-∞, -12%]", None, -12.0, 8)
    assert b.model_dump() == {"label": "(-∞, -12%]", "lower": None, "upper": -12.0, "count": 8}


def test_stock_stats_default_bin_width_is_3():
    s = StockStats(
        sample_size=10,
        mean_pct=0.5,
        median_pct=0.3,
        max_pct=2.0,
        min_pct=-1.0,
        up_count=6,
        down_count=3,
        flat_count=1,
        buckets=[_bucket("(-∞, -12%]", None, -12.0, 0)],
    )
    assert s.bin_width == 3.0
    assert s.sample_size == 10


def test_board_stats_default_bin_width_is_1_and_carries_source():
    s = BoardStats(
        sample_size=5,
        mean_pct=None,
        median_pct=None,
        max_pct=None,
        min_pct=None,
        up_count=0,
        down_count=0,
        flat_count=0,
        source="ths",
        buckets=[],
    )
    assert s.bin_width == 1.0
    assert s.source == "ths"


def test_market_stats_error_entry_block_literal():
    e = MarketStatsErrorEntry(block="stocks", error="DataFetchError", message="upstream down")
    assert e.block == "stocks"
    assert e.error == "DataFetchError"


def test_market_stats_response_accepts_null_blocks():
    r = MarketStatsResponse(
        stocks=None,
        boards=None,
        errors=[
            MarketStatsErrorEntry(block="stocks", error="DataFetchError", message="x"),
            MarketStatsErrorEntry(block="boards", error="ValueError", message="y"),
        ],
        summary={"requested": 2, "ok": 0, "failed": 2, "elapsed_ms": 42},
    )
    assert r.stocks is None and r.boards is None
    assert len(r.errors) == 2
    assert r.summary["ok"] == 0


def test_market_stats_response_summary_is_dict():
    """summary stays a free-form dict so we don't lock ourselves to a
    fixed schema before the contract stabilises (matches the pattern
    in IndicesBatchProfileResponse / MarketContextResponse)."""
    r = MarketStatsResponse(stocks=None, boards=None, errors=[], summary={})
    assert r.summary == {}


# ----- Post-2026-09-02: pools block (NEW) -----


def test_market_stats_limit_pools_both_populated():
    """zt + dt both populated — happy path."""
    from stock_data.api.schemas import MarketStatsLimitPools

    p = MarketStatsLimitPools(
        zt=[{"code": "600519", "name": "茅台"}],
        dt=[{"code": "000001", "name": "平安"}],
    )
    assert p.zt is not None and len(p.zt) == 1
    assert p.dt is not None and len(p.dt) == 1
    assert p.zt[0]["code"] == "600519"


def test_market_stats_limit_pools_both_null():
    """Both null — per-pool upstream failure or include_pools=false."""
    from stock_data.api.schemas import MarketStatsLimitPools

    p = MarketStatsLimitPools(zt=None, dt=None)
    assert p.zt is None and p.dt is None


def test_market_stats_limit_pools_zt_only():
    """Asymmetric — zt OK, dt failed (per-pool error isolation)."""
    from stock_data.api.schemas import MarketStatsLimitPools

    p = MarketStatsLimitPools(zt=[{"code": "600519"}], dt=None)
    assert p.zt is not None and p.dt is None


def test_market_stats_error_entry_pool_literals():
    """New block literals 'zt_pool' and 'dt_pool' must validate."""
    from stock_data.api.schemas import MarketStatsErrorEntry

    zt_err = MarketStatsErrorEntry(block="zt_pool", error="DataFetchError", message="zt down")
    dt_err = MarketStatsErrorEntry(block="dt_pool", error="ValueError", message="dt down")
    assert zt_err.block == "zt_pool"
    assert dt_err.block == "dt_pool"


def test_market_stats_error_entry_pool_literal_rejects_unknown():
    """Unknown block literal must raise ValidationError."""
    import pytest
    from pydantic import ValidationError

    from stock_data.api.schemas import MarketStatsErrorEntry

    with pytest.raises(ValidationError):
        MarketStatsErrorEntry(block="unknown_block", error="X", message="x")


def test_market_stats_response_includes_limit_pools_field():
    """MarketStatsResponse.model_fields MUST contain 'limit_pools'."""
    from stock_data.api.schemas import MarketStatsResponse

    assert "limit_pools" in MarketStatsResponse.model_fields


def test_market_stats_response_default_limit_pools_is_none():
    """Omitting limit_pools keyword → field is None."""
    from stock_data.api.schemas import MarketStatsResponse

    r = MarketStatsResponse(stocks=None, boards=None, errors=[], summary={})
    assert r.limit_pools is None
