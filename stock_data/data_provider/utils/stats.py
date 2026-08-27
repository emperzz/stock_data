"""Pure-compute distribution aggregation for change_pct values.

Used by /api/v1/agent/market-stats. Bucket math lives here so the
route layer stays a thin orchestration wrapper. No I/O, no fetcher
imports — easy to unit-test with synthetic value lists.
"""

from __future__ import annotations

import statistics
from collections.abc import Iterable
from dataclasses import dataclass


@dataclass(frozen=True)
class DistributionBucket:
    """One percentage bucket in the distribution.

    Convention: left-open right-closed `[lower, upper]` for interior
    buckets. The ±∞ boundary buckets have one of {lower, upper} = None.
    The flat bucket has lower == upper == 0 and is checked FIRST in
    `_assign` (so a value of exactly 0 lands there, not in either
    adjacent open bucket).
    """

    label: str
    lower: float | None
    upper: float | None
    count: int


@dataclass(frozen=True)
class AggregateStats:
    """Aggregated statistics over a non-None change_pct series."""

    sample_size: int
    mean_pct: float | None
    median_pct: float | None
    max_pct: float | None
    min_pct: float | None
    up_count: int
    down_count: int
    flat_count: int
    bin_width: float
    buckets: list[DistributionBucket]


# Module-level constants — kept here so the route layer reads them
# from one place and the unit tests can pin the values.
STOCK_BUCKET_BIN_WIDTH = 3.0
STOCK_BUCKET_EDGES = (-12.0, 12.0)
BOARD_BUCKET_BIN_WIDTH = 1.0
BOARD_BUCKET_EDGES = (-3.0, 3.0)

_EPS = 1e-9


def _label(left: float | None, right: float | None) -> str:
    """Render a bucket label matching the JSON example in the spec.

    Convention:
      - interior buckets → "(lo, hi]" (left-open right-closed)
      - upper = 0 buckets → "(lo%, 0)" (right-open, no '+' sign on 0)
        because flat-bucket {0} is checked first; right-open prevents
        the visual confusion of "value=0 in (-3%, 0]" plus flat bucket
      - lower = 0 buckets → "(0, hi%]" (left-open, no '+' sign on 0)
        mirroring the spec §2.3 example label "(0, +3%]"
      - upper = None → "+∞" (right-closed, +infinity)
      - lower = None → "-∞" (left-open, -infinity)
    """
    lo = "0" if left == 0.0 else "-∞" if left is None else f"{left:+.0f}%"
    if right is None:
        hi = "+∞"
        bracket = "]"
    elif right == 0.0:
        hi = "0"     # no '+' sign; spec example shows "(-3%, 0)"
        bracket = ")" # right-open (flat bucket absorbs 0)
    else:
        hi = f"{right:+.0f}%"
        bracket = "]"
    return f"({lo}, {hi}{bracket}"


def build_stock_buckets() -> list[DistributionBucket]:
    """11 buckets (left-open right-closed, flat = {0}).

    Order: (-∞,-12%], (-12%,-9%], (-9%,-6%], (-6%,-3%], (-3%,0),
    {0}, (0,+3%], (+3%,+6%], (+6%,+9%], (+9%,+12%], (+12%,+∞).
    """
    return [
        DistributionBucket(_label(None, -12.0), lower=None, upper=-12.0, count=0),
        DistributionBucket(_label(-12.0, -9.0), lower=-12.0, upper=-9.0, count=0),
        DistributionBucket(_label(-9.0, -6.0), lower=-9.0, upper=-6.0, count=0),
        DistributionBucket(_label(-6.0, -3.0), lower=-6.0, upper=-3.0, count=0),
        DistributionBucket(_label(-3.0, 0.0), lower=-3.0, upper=0.0, count=0),
        DistributionBucket("0% (平盘)", lower=0.0, upper=0.0, count=0),
        DistributionBucket(_label(0.0, 3.0), lower=0.0, upper=3.0, count=0),
        DistributionBucket(_label(3.0, 6.0), lower=3.0, upper=6.0, count=0),
        DistributionBucket(_label(6.0, 9.0), lower=6.0, upper=9.0, count=0),
        DistributionBucket(_label(9.0, 12.0), lower=9.0, upper=12.0, count=0),
        DistributionBucket(_label(12.0, None), lower=12.0, upper=None, count=0),
    ]


def build_board_buckets() -> list[DistributionBucket]:
    """9 buckets (same convention as stocks):

    (-∞,-3%], (-3%,-2%], (-2%,-1%], (-1%,0),
    {0},
    (0,+1%], (+1%,+2%], (+2%,+3%], (+3%,+∞).
    """
    return [
        DistributionBucket(_label(None, -3.0), lower=None, upper=-3.0, count=0),
        DistributionBucket(_label(-3.0, -2.0), lower=-3.0, upper=-2.0, count=0),
        DistributionBucket(_label(-2.0, -1.0), lower=-2.0, upper=-1.0, count=0),
        DistributionBucket(_label(-1.0, 0.0), lower=-1.0, upper=0.0, count=0),
        DistributionBucket("0% (平盘)", lower=0.0, upper=0.0, count=0),
        DistributionBucket(_label(0.0, 1.0), lower=0.0, upper=1.0, count=0),
        DistributionBucket(_label(1.0, 2.0), lower=1.0, upper=2.0, count=0),
        DistributionBucket(_label(2.0, 3.0), lower=2.0, upper=3.0, count=0),
        DistributionBucket(_label(3.0, None), lower=3.0, upper=None, count=0),
    ]


def _assign(value: float, buckets: list[DistributionBucket]) -> int:
    """Route a single non-None value to its bucket, returning its index.

    Flat bucket is checked FIRST; interior buckets are left-open
    right-closed `[lower, upper]`. Raises AssertionError if no bucket
    matches (should be unreachable given the ±∞ boundaries; signals a
    buggy template).
    """
    if abs(value) <= _EPS:
        for i, b in enumerate(buckets):
            if b.lower == 0.0 and b.upper == 0.0:
                return i
        raise AssertionError("flat bucket missing from template")

    for i, b in enumerate(buckets):
        if b.lower == 0.0 and b.upper == 0.0:
            continue  # already routed above
        lo_ok = (b.lower is None) or value > b.lower
        hi_ok = (b.upper is None) or value <= b.upper
        if lo_ok and hi_ok:
            return i
    raise AssertionError(f"value {value} did not fall in any bucket")


def compute_aggregate(
    values: Iterable[float | None],
    *,
    bin_width: float,
    buckets_template: list[DistributionBucket],
) -> AggregateStats:
    """Aggregate a list of change_pct values.

    - None values are skipped (not in sample_size, not in any bucket).
    - flat = |v| <= 1e-9 (rounded-to-zero guard).
    - Empty / all-None input → zero-valued aggregate; full template
      echoed with all counts = 0.
    - Median via statistics.median; StatisticsError on empty input is
      swallowed and None is returned.
    """
    cleaned: list[float] = [v for v in values if v is not None]
    sample_size = len(cleaned)

    mean_pct: float | None = None
    median_pct: float | None = None
    max_pct: float | None = None
    min_pct: float | None = None
    up_count = 0
    down_count = 0
    flat_count = 0

    if sample_size:
        mean_pct = statistics.fmean(cleaned)
        try:
            median_pct = statistics.median(cleaned)
        except statistics.StatisticsError:
            median_pct = None
        max_pct = max(cleaned)
        min_pct = min(cleaned)
        for v in cleaned:
            if abs(v) <= _EPS:
                flat_count += 1
            elif v > 0:
                up_count += 1
            else:
                down_count += 1

    # Bucket template copy with counts filled in
    buckets = [
        DistributionBucket(
            label=tpl.label,
            lower=tpl.lower,
            upper=tpl.upper,
            count=0,
        )
        for tpl in buckets_template
    ]
    if sample_size:
        for v in cleaned:
            idx = _assign(v, buckets)
            b = buckets[idx]
            buckets[idx] = DistributionBucket(
                label=b.label,
                lower=b.lower,
                upper=b.upper,
                count=b.count + 1,
            )

    return AggregateStats(
        sample_size=sample_size,
        mean_pct=mean_pct,
        median_pct=median_pct,
        max_pct=max_pct,
        min_pct=min_pct,
        up_count=up_count,
        down_count=down_count,
        flat_count=flat_count,
        bin_width=bin_width,
        buckets=buckets,
    )
