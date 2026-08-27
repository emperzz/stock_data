"""Pure-compute unit tests for stock_data.data_provider.utils.stats.

No I/O, no fetcher. The whole file is fast (< 100ms total).
"""
import math

from stock_data.data_provider.utils.stats import (
    BOARD_BUCKET_BIN_WIDTH,
    STOCK_BUCKET_BIN_WIDTH,
    build_board_buckets,
    build_stock_buckets,
    compute_aggregate,
)


def test_stock_bucket_template_has_11_buckets():
    buckets = build_stock_buckets()
    assert len(buckets) == 11


def test_stock_bucket_template_edges():
    """11 buckets: (-∞,-12], (-12,-9], (-9,-6], (-6,-3], (-3,0), {0},
    (0,+3], (+3,+6], (+6,+9], (+9,+12], (+12,+∞)."""
    b = build_stock_buckets()
    assert b[0].lower is None and b[0].upper == -12.0
    assert b[1].lower == -12.0 and b[1].upper == -9.0
    assert b[2].lower == -9.0 and b[2].upper == -6.0
    assert b[3].lower == -6.0 and b[3].upper == -3.0
    assert b[4].lower == -3.0 and b[4].upper == 0.0
    assert b[5].lower == 0.0 and b[5].upper == 0.0  # flat bucket
    assert b[6].lower == 0.0 and b[6].upper == 3.0
    assert b[7].lower == 3.0 and b[7].upper == 6.0
    assert b[8].lower == 6.0 and b[8].upper == 9.0
    assert b[9].lower == 9.0 and b[9].upper == 12.0
    assert b[10].lower == 12.0 and b[10].upper is None


def test_board_bucket_template_has_9_buckets():
    buckets = build_board_buckets()
    assert len(buckets) == 9


def test_board_bucket_template_edges():
    """9 buckets: (-∞,-3], (-3,-2], (-2,-1], (-1,0), {0},
    (0,+1], (+1,+2], (+2,+3], (+3,+∞)."""
    b = build_board_buckets()
    assert b[0].lower is None and b[0].upper == -3.0
    assert b[1].lower == -3.0 and b[1].upper == -2.0
    assert b[2].lower == -2.0 and b[2].upper == -1.0
    assert b[3].lower == -1.0 and b[3].upper == 0.0
    assert b[4].lower == 0.0 and b[4].upper == 0.0  # flat
    assert b[5].lower == 0.0 and b[5].upper == 1.0
    assert b[6].lower == 1.0 and b[6].upper == 2.0
    assert b[7].lower == 2.0 and b[7].upper == 3.0
    assert b[8].lower == 3.0 and b[8].upper is None


def test_compute_aggregate_basic_distribution():
    """Hand-picked values exercise mean, median, max, min, up/down/flat,
    and bucket placement."""
    values = [-12.0, -3.0, 0.0, 3.0, 12.0, 13.0]
    agg = compute_aggregate(
        values, bin_width=STOCK_BUCKET_BIN_WIDTH, buckets_template=build_stock_buckets()
    )
    assert agg.sample_size == 6
    assert math.isclose(agg.mean_pct, (-12.0 - 3.0 + 0.0 + 3.0 + 12.0 + 13.0) / 6, rel_tol=1e-9)
    assert agg.median_pct == 1.5       # median of [-12, -3, 0, 3, 12, 13] = (0 + 3) / 2
    assert agg.max_pct == 13.0
    assert agg.min_pct == -12.0
    assert agg.up_count == 3           # 3.0, 12.0, 13.0
    assert agg.down_count == 2         # -12.0, -3.0
    assert agg.flat_count == 1         # 0.0
    assert agg.bin_width == 3.0
    # Bucket counts (by index in template):
    # Left-open right-closed convention: v belongs to bucket whose
    # `lower < v <= upper`. So -3.0 → (-6%, -3%] (index 3, right-closed
    # at -3%); 0.0 → {0} flat bucket (index 5); 3.0 → (0, +3%]
    # (index 6, right-closed at +3%).
    assert agg.buckets[0].count == 1   # (-∞,-12]   catches -12.0
    assert agg.buckets[3].count == 1   # (-6,-3]    catches -3.0
    assert agg.buckets[4].count == 0   # (-3,0)     catches nothing in this test
    assert agg.buckets[5].count == 1   # {0}        catches 0.0
    assert agg.buckets[6].count == 1   # (0,+3]     catches 3.0
    assert agg.buckets[9].count == 1   # (+9,+12]   catches 12.0
    assert agg.buckets[10].count == 1  # (+12,+∞)   catches 13.0


def test_compute_aggregate_bucket_assignment_edges():
    """Boundary values must land in the correct bucket per the spec's
    left-open right-closed convention with flat-first routing.

    Boundary math:
      -12.0 → (-∞, -12%]   (right-closed at -12%, value <= upper)
      -11.999 → (-12%, -9%] (left-open at -12%, right-closed at -9%)
      -9.0 → (-12%, -9%]   (right-closed at -9%)
      -3.0 → (-6%, -3%]    (right-closed at -3%)
       0.0 → {0}           (flat bucket, checked first)
       1e-10 → {0}          (within _EPS of zero)
       0.001 → (0, +3%]    (right-closed at +3%)
       3.0 → (0, +3%]      (right-closed at +3%)
      12.0 → (+9%, +12%]   (right-closed at +12%)
      12.001 → (+12%, +∞)  (left-open at +12%)
    """
    values = [-12.0, -11.999, -9.0, -3.0, 0.0, 1e-10, 0.001, 3.0, 12.0, 12.001]
    agg = compute_aggregate(
        values, bin_width=STOCK_BUCKET_BIN_WIDTH, buckets_template=build_stock_buckets()
    )
    assert agg.buckets[0].count == 1   # (-∞,-12]    : -12.0
    assert agg.buckets[1].count == 2   # (-12,-9]    : -11.999 + -9.0 (right-closed)
    assert agg.buckets[2].count == 0   # (-9,-6]     : nothing in this test
    assert agg.buckets[3].count == 1   # (-6,-3]     : -3.0 (right-closed)
    assert agg.buckets[4].count == 0   # (-3,0)
    assert agg.buckets[5].count == 2   # {0}         : 0.0 + 1e-10
    assert agg.buckets[6].count == 2   # (0,+3]      : 0.001 + 3.0 (right-closed)
    assert agg.buckets[9].count == 1   # (+9,+12]    : 12.0
    assert agg.buckets[10].count == 1  # (+12,+∞)    : 12.001


def test_compute_aggregate_skips_none():
    """None values are dropped — not in sample_size, not in any bucket."""
    values = [None, None, 1.0]
    agg = compute_aggregate(
        values, bin_width=STOCK_BUCKET_BIN_WIDTH, buckets_template=build_stock_buckets()
    )
    assert agg.sample_size == 1
    assert agg.mean_pct == 1.0
    assert agg.median_pct == 1.0
    assert agg.max_pct == 1.0
    assert agg.min_pct == 1.0
    assert agg.up_count == 1
    assert agg.down_count == 0
    assert agg.flat_count == 0
    # All 11 buckets echoed from template, only the (0,+3] bucket has count=1.
    assert sum(b.count for b in agg.buckets) == 1
    assert agg.buckets[6].count == 1


def test_compute_aggregate_empty_input():
    """Empty input → zero-valued aggregate; full template echoed."""
    agg = compute_aggregate(
        [], bin_width=STOCK_BUCKET_BIN_WIDTH, buckets_template=build_stock_buckets()
    )
    assert agg.sample_size == 0
    assert agg.mean_pct is None
    assert agg.median_pct is None
    assert agg.max_pct is None
    assert agg.min_pct is None
    assert agg.up_count == 0
    assert agg.down_count == 0
    assert agg.flat_count == 0
    assert agg.bin_width == 3.0
    assert len(agg.buckets) == 11
    assert all(b.count == 0 for b in agg.buckets)


def test_compute_aggregate_all_none_input():
    """All-None input → same as empty (sample_size=0, all stats None)."""
    agg = compute_aggregate(
        [None, None], bin_width=STOCK_BUCKET_BIN_WIDTH, buckets_template=build_stock_buckets()
    )
    assert agg.sample_size == 0
    assert agg.mean_pct is None


def test_compute_aggregate_uses_template_invariant():
    """Output buckets length == template length; count labels are stable."""
    template = build_board_buckets()
    agg = compute_aggregate([0.5, -0.5, 0.0], bin_width=1.0, buckets_template=template)
    assert len(agg.buckets) == len(template)
    for out, tpl in zip(agg.buckets, template, strict=True):
        assert out.label == tpl.label
        assert out.lower == tpl.lower
        assert out.upper == tpl.upper


def test_compute_aggregate_board_distribution():
    """Smoke-test the board bucket width and clip boundaries."""
    values = [-3.5, -1.5, -0.5, 0.0, 0.5, 1.5, 3.5]
    agg = compute_aggregate(
        values, bin_width=BOARD_BUCKET_BIN_WIDTH, buckets_template=build_board_buckets()
    )
    assert agg.sample_size == 7
    assert agg.buckets[0].count == 1   # (-∞,-3]   : -3.5
    assert agg.buckets[2].count == 1   # (-2,-1]   : -1.5
    assert agg.buckets[3].count == 1   # (-1,0)    : -0.5
    assert agg.buckets[4].count == 1   # {0}       : 0.0
    assert agg.buckets[5].count == 1   # (0,+1]    : 0.5
    assert agg.buckets[6].count == 1   # (+1,+2]   : 1.5
    assert agg.buckets[8].count == 1   # (+3,+∞)   : 3.5


def test_compute_aggregate_constant_input():
    """All-same-value edge: mean == median == max == min == value."""
    agg = compute_aggregate(
        [2.0] * 5, bin_width=STOCK_BUCKET_BIN_WIDTH, buckets_template=build_stock_buckets()
    )
    assert agg.sample_size == 5
    assert agg.mean_pct == 2.0
    assert agg.median_pct == 2.0
    assert agg.max_pct == 2.0
    assert agg.min_pct == 2.0
    # 2.0 falls in (0, +3] (index 6)
    assert agg.buckets[6].count == 5
