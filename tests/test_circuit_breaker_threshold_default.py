"""
Tests for the default CircuitBreaker failure_threshold (post-2026-07-30 bump).

Contract: the default ``failure_threshold`` (when neither the env var nor
an explicit kwarg is supplied) is 5. Five consecutive failures should
NOT open the circuit; six should.

Rationale: a single batch-profile fan-out (3 indices × 3 frequencies =
9 calls) can hit every INDEX_KLINE fetcher 1-3 times. With the old
default of 3, a single fan-out could simultaneously trip every CB into
OPEN state for the next 5 minutes — manifesting as "all fetchers fail"
on every subsequent request within the cooldown window. Bumping the
default to 5 widens the noise floor without sacrificing protective
behavior on sustained failures.

This is a sentinel-level config change — no business logic changes.

Source: ``stock_data/data_provider/core/types.py:CircuitBreaker.__init__``
"""

import os

import pytest

from stock_data.data_provider.core.types import CircuitBreaker


# ──────────────────────────────────────────────────────────────────
# Test 1: 默认 threshold = 5 (was 3)
# ──────────────────────────────────────────────────────────────────
def test_default_failure_threshold_is_5():
    """With no env var and no explicit kwarg, ``failure_threshold``
    defaults to 5. The previous value of 3 made a single batch-profile
    fan-out trip every INDEX_KLINE fetcher into OPEN state, which
    produced the persistent "all fetchers fail" pattern.
    """
    with pytest.MonkeyPatch.context() as m:
        m.delenv("CB_FAILURE_THRESHOLD", raising=False)
        cb = CircuitBreaker()
        assert cb.failure_threshold == 5, (
            f"Expected default failure_threshold=5 (was 3 before this bump), "
            f"got {cb.failure_threshold}"
        )
        assert cb.cooldown_seconds == 300.0  # unchanged
        assert cb.half_open_max_calls == 1  # unchanged


# ──────────────────────────────────────────────────────────────────
# Test 2: 4 次连续失败仍 CLOSED；第 5 次 OPEN（threshold=5 时）
# ──────────────────────────────────────────────────────────────────
def test_4_failures_stay_closed_5th_opens():
    """With failure_threshold=5 (the new default), 4 consecutive
    failures should leave the circuit CLOSED, and the 5th failure
    should transition it to OPEN.

    Pin: the CB opens AT the threshold (failures >= threshold), not
    strictly AFTER. Mirrors the existing test in
    ``tests/test_core_types.py::TestCircuitBreaker::test_record_failure_opens``
    which uses threshold=2 and asserts that the 2nd failure opens.

    The new noise floor implication: a single batch-profile fan-out
    (which hits each INDEX_KLINE fetcher 1-3 times) is now BELOW
    the trip threshold for everyone.
    """
    with pytest.MonkeyPatch.context() as m:
        m.delenv("CB_FAILURE_THRESHOLD", raising=False)
        cb = CircuitBreaker()

        for i in range(4):
            cb.record_failure("TestFetcher")
            assert cb.is_available("TestFetcher"), (
                f"CB should still be CLOSED after {i+1} failures "
                "(threshold=5 default)"
            )

        cb.record_failure("TestFetcher")
        assert not cb.is_available("TestFetcher"), (
            "CB should be OPEN after 5th failure (threshold=5 default)"
        )


# ──────────────────────────────────────────────────────────────────
# Test 3: env var 覆盖仍生效（覆盖 default，但 singletons 显式传 5，
#         env 仍 override 那些）
# ──────────────────────────────────────────────────────────────────
def test_env_var_still_overrides_default():
    """``CB_FAILURE_THRESHOLD=7`` env var takes precedence over the
    new default of 5. The env-override contract must stay intact.
    """
    with pytest.MonkeyPatch.context() as m:
        m.setenv("CB_FAILURE_THRESHOLD", "7")
        cb = CircuitBreaker()
        assert cb.failure_threshold == 7


# ──────────────────────────────────────────────────────────────────
# Test 4: 显式 kwarg 在 env 缺席时生效（env 优先的现有契约）
# ──────────────────────────────────────────────────────────────────
def test_explicit_kwarg_used_when_env_unset():
    """Pre-existing contract (unchanged by this fix): the env var
    ``CB_FAILURE_THRESHOLD`` WINS over the explicit kwarg. The kwarg
    only kicks in when the env var is unset. This test pins that
    contract — it documents why call sites that want a custom
    threshold should mutate the env, not the kwarg.

    See ``stock_data/data_provider/core/types.py:CircuitBreaker.__init__``
    for the priority order.
    """
    with pytest.MonkeyPatch.context() as m:
        m.delenv("CB_FAILURE_THRESHOLD", raising=False)
        cb = CircuitBreaker(failure_threshold=11)
        assert cb.failure_threshold == 11, (
            "kwarg should win when env is unset"
        )
