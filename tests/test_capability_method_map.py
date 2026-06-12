"""Tests for CAPABILITY_TO_METHOD lookup table in data_provider/base.py.

This table is the single source of truth used by the explorer manifest to
decide which fetcher method corresponds to which DataCapability.
Every DataCapability flag MUST be either:
  - in CAPABILITY_TO_METHOD (maps to a fetcher method name), OR
  - in _NO_FETCHER_METHOD (explicit "this capability has no method").
This forces every new capability author to declare intent.
"""
import pytest

from stock_data.data_provider.base import (
    BaseFetcher,
    DataCapability,
    CAPABILITY_TO_METHOD,
    _NO_FETCHER_METHOD,
)
from stock_data.data_provider import (
    AkshareFetcher,
    BaostockFetcher,
    CninfoFetcher,
    EastMoneyFetcher,
    TencentFetcher,
    ThsFetcher,
    TushareFetcher,
    YfinanceFetcher,
    ZhituFetcher,
)
from stock_data.data_provider.fetchers.myquant_fetcher import MyquantFetcher


# Concrete fetcher subclasses used to verify that method names in
# CAPABILITY_TO_METHOD resolve to a real method on at least one subclass
# (BaseFetcher only declares a subset; the rest are added on the concrete
# fetchers that support the corresponding capability).
_CONCRETE_FETCHERS = (
    AkshareFetcher,
    BaostockFetcher,
    CninfoFetcher,
    EastMoneyFetcher,
    MyquantFetcher,
    TencentFetcher,
    ThsFetcher,
    TushareFetcher,
    YfinanceFetcher,
    ZhituFetcher,
)


@pytest.mark.parametrize("cap", list(DataCapability))
def test_every_capability_has_intent_declared(cap):
    """Every DataCapability MUST be either mapped to a method or explicitly excluded."""
    in_map = cap in CAPABILITY_TO_METHOD
    in_no_method = cap in _NO_FETCHER_METHOD
    assert in_map ^ in_no_method, (
        f"DataCapability.{cap.name} must be in CAPABILITY_TO_METHOD "
        f"OR _NO_FETCHER_METHOD (not both, not neither). "
        f"Currently: in_map={in_map}, in_no_method={in_no_method}"
    )


@pytest.mark.parametrize("cap,method_name", list(CAPABILITY_TO_METHOD.items()))
def test_mapped_method_exists_on_base_or_subclass(cap, method_name):
    """Every method name in the map must exist on BaseFetcher OR a concrete subclass.

    BaseFetcher only declares a minimal abstract interface; most
    capability-specific methods are added on the concrete fetchers that
    support them. We therefore check that the method resolves to a callable
    on at least one of the registered fetchers — this catches typos
    ("get_ktline_data") without requiring every method to be on the ABC.
    """
    found_on = []
    for cls in (BaseFetcher, *_CONCRETE_FETCHERS):
        if hasattr(cls, method_name) and callable(getattr(cls, method_name, None)):
            found_on.append(cls.__name__)
    assert found_on, (
        f"DataCapability.{cap.name} maps to method '{method_name}', "
        f"but no fetcher class (BaseFetcher or any concrete subclass) "
        f"defines such a method. Did you typo the method name?"
    )


def test_known_mappings():
    """Spot-check a few well-known mappings to catch refactor regressions."""
    assert CAPABILITY_TO_METHOD[DataCapability.HISTORICAL_DWM] == "get_kline_data"
    assert CAPABILITY_TO_METHOD[DataCapability.HISTORICAL_MIN] == "get_kline_data"
    assert CAPABILITY_TO_METHOD[DataCapability.REALTIME_QUOTE] == "get_realtime_quote"
    assert CAPABILITY_TO_METHOD[DataCapability.STOCK_BOARD] == "get_all_concept_boards"
    assert CAPABILITY_TO_METHOD[DataCapability.DRAGON_TIGER] == "get_dragon_tiger"
    assert CAPABILITY_TO_METHOD[DataCapability.FUND_FLOW] == "get_fund_flow_minute"
