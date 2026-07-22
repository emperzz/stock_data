"""Tests for CAPABILITY_TO_METHOD lookup table in data_provider/base.py.

This table is the single source of truth used by the explorer manifest to
decide which fetcher method corresponds to which DataCapability.
Every DataCapability flag MUST be in CAPABILITY_TO_METHOD.

Also enforces the explorer-side mapping that every DataCapability flag MUST
have a {label, icon} entry in `explorer.tags.CAPABILITY_LABELS` (the
HTML `CAPABILITY_GROUPS` sidebar filter was removed in commit 37e52ed).
Missing entries silently drop endpoints from the UI.
"""

from pathlib import Path

import pytest

from stock_data.data_provider import (
    AkshareFetcher,
    BaostockFetcher,
    ClsFetcher,  # CLS 早报 + 复盘
    CninfoFetcher,
    EastMoneyFetcher,
    TencentFetcher,
    ThsFetcher,
    TushareFetcher,
    YfinanceFetcher,
    ZhituFetcher,
    ZzshareFetcher,  # NEW
)
from stock_data.data_provider.base import (
    CAPABILITY_TO_METHOD,
    BaseFetcher,
    DataCapability,
)
from stock_data.data_provider.fetchers.myquant_fetcher import MyquantFetcher

# Concrete fetcher subclasses used to verify that method names in
# CAPABILITY_TO_METHOD resolve to a real method on at least one subclass
# (BaseFetcher only declares a subset; the rest are added on the concrete
# fetchers that support the corresponding capability).
_CONCRETE_FETCHERS = (
    AkshareFetcher,
    BaostockFetcher,
    ClsFetcher,
    CninfoFetcher,
    EastMoneyFetcher,
    MyquantFetcher,
    TencentFetcher,
    ThsFetcher,
    TushareFetcher,
    YfinanceFetcher,
    ZhituFetcher,
    ZzshareFetcher,  # NEW
)


@pytest.mark.parametrize("cap", list(DataCapability))
def test_every_capability_has_intent_declared(cap):
    """Every DataCapability MUST be mapped to a method in CAPABILITY_TO_METHOD."""
    assert cap in CAPABILITY_TO_METHOD, (
        f"DataCapability.{cap.name} is not in CAPABILITY_TO_METHOD. Add it to declare intent."
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
    assert CAPABILITY_TO_METHOD[DataCapability.STOCK_KLINE] == "get_kline_data"
    assert CAPABILITY_TO_METHOD[DataCapability.STOCK_REALTIME_QUOTE] == "get_realtime_quote"
    assert CAPABILITY_TO_METHOD[DataCapability.STOCK_BOARD] == "get_all_boards"
    assert CAPABILITY_TO_METHOD[DataCapability.DRAGON_TIGER] == "get_dragon_tiger"
    assert CAPABILITY_TO_METHOD[DataCapability.FUND_FLOW] == "get_fund_flow_minute"


# ---------------------------------------------------------------------------
# Explorer-side mappings: CAPABILITY_LABELS + HTML CAPABILITY_GROUPS
# ---------------------------------------------------------------------------
# These guard the same root cause from the server side:
#   - CAPABILITY_LABELS (explorer/tags.py) drives the icon/label exposed in
#     `manifest.meta.capabilities` so the UI can decorate capability chips.
#   - CAPABILITY_GROUPS (HTML sidebar) drives the capability filter that
#     decides whether an endpoint card is rendered. A flag missing from
#     every group is silently dropped from view.
# Both must contain every DataCapability flag — otherwise the endpoint
# disappears from the explorer UI (the bug we hit with STOCK_INFO).


def test_every_capability_is_in_capability_labels():
    """Every DataCapability flag must have a label+icon entry in tags.CAPABILITY_LABELS.

    Mirrors the contract enforced by `test_every_capability_has_intent_declared`
    for the server-side CAPABILITY_TO_METHOD map. Missing entries cause the
    manifest's `meta.capabilities` to silently lack icon/label decoration.
    """
    from stock_data.explorer.tags import CAPABILITY_LABELS

    missing = [c.name for c in DataCapability if c.name not in CAPABILITY_LABELS]
    assert not missing, (
        f"DataCapability flag(s) missing from CAPABILITY_LABELS in "
        f"stock_data/explorer/tags.py: {missing}. Each flag needs a "
        f"{{label, icon}} entry — the manifest exposes this dict to the "
        f"UI via meta.capabilities."
    )


_HTML_PATH = (
    Path(__file__).resolve().parent.parent / "stock_data" / "explorer" / "static" / "index.html"
)


def _extract_capability_groups(html_text: str) -> dict[str, list[str]]:
    """DEPRECATED: capability filter UI was removed in commit 37e52ed.

    Kept as a no-op stub for one release cycle so external imports don't
    break. Remove in the next cleanup pass. The new equivalent test
    `test_every_capability_has_a_label_in_capability_labels` validates
    coverage via `explorer.tags.CAPABILITY_LABELS` (server-side source
    of truth) instead of parsing the HTML constant.
    """
    return {}


def _parse_inline_groups(stripped: str) -> dict[str, list[str]]:
    """DEPRECATED: see `_extract_capability_groups`."""
    return {}


def test_every_capability_has_a_label_in_capability_labels():
    """Every DataCapability flag must have a decorative label/icon entry in
    `explorer.tags.CAPABILITY_LABELS`.

    The HTML no longer carries a `CAPABILITY_GROUPS` constant (commit 37e52ed
    removed the capability filter UI). Capabilities are now sourced dynamically
    from the server-side `/control/api-manifest`, and `CAPABILITY_LABELS` is
    the new source of truth for how each capability renders (label + icon).
    A capability missing from `CAPABILITY_LABELS` shows up as raw `STOCK_XXX`
    text in the explorer's fetcher-row capability chips, hurting UX and
    signalling the developer forgot to register a new flag here.
    """
    from stock_data.explorer.tags import CAPABILITY_LABELS

    missing = [c.name for c in DataCapability if c.name not in CAPABILITY_LABELS]
    assert not missing, (
        f"DataCapability flag(s) missing from CAPABILITY_LABELS in "
        f"stock_data/explorer/tags.py: {missing}. "
        f"Add a {{label, icon}} entry for each, otherwise the explorer's "
        f"fetcher-row chips render the raw flag name. "
        f"Current labels: {sorted(CAPABILITY_LABELS.keys())}"
    )

    # Every entry must have both a label and an icon (icon can be any
    # non-empty string — typically an emoji).
    for cap_name, entry in CAPABILITY_LABELS.items():
        assert "label" in entry, f"CAPABILITY_LABELS[{cap_name!r}] missing 'label'"
        assert "icon" in entry, f"CAPABILITY_LABELS[{cap_name!r}] missing 'icon'"
        assert entry["label"].strip(), f"CAPABILITY_LABELS[{cap_name!r}] label is empty"
        assert entry["icon"].strip(), f"CAPABILITY_LABELS[{cap_name!r}] icon is empty"
