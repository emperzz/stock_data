"""Verify the spec rev 3 capability flag rename.

Old flag names should NOT exist (cleanly deleted); new names must exist.
"""
import pytest

from stock_data.data_provider.base import DataCapability


def test_new_kline_flags_exist():
    """Spec rev 3 adds STOCK_KLINE + INDEX_KLINE + STOCK_REALTIME_QUOTE + INDEX_REALTIME_QUOTE."""
    assert DataCapability.STOCK_KLINE
    assert DataCapability.INDEX_KLINE
    assert DataCapability.STOCK_REALTIME_QUOTE
    assert DataCapability.INDEX_REALTIME_QUOTE


def test_old_flags_deleted_no_shim():
    """Old flag names are gone — no DEPRECATED_TO_CANONICAL shim (rev 3)."""
    for old_name in (
        "HISTORICAL_DWM", "HISTORICAL_MIN",
        "INDEX_HISTORICAL", "INDEX_INTRADAY",
        "REALTIME_QUOTE", "INDEX_QUOTE",
    ):
        with pytest.raises(AttributeError, match=old_name):
            getattr(DataCapability, old_name)


def test_no_deprecated_to_canonical_map_in_base():
    """DEPRECATED_TO_CANONICAL was the shim — should not exist."""
    from stock_data.data_provider import base as base_mod
    assert not hasattr(base_mod, "DEPRECATED_TO_CANONICAL")
