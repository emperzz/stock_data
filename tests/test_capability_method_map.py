"""Tests for CAPABILITY_TO_METHOD lookup table in data_provider/base.py.

This table is the single source of truth used by the explorer manifest to
decide which fetcher method corresponds to which DataCapability.
Every DataCapability flag MUST be in CAPABILITY_TO_METHOD.

Also enforces the explorer-side mappings that every DataCapability flag MUST
appear in: (a) `explorer.tags.CAPABILITY_LABELS` (decorative icon/label)
and (b) `explorer/static/index.html` `CAPABILITY_GROUPS` (sidebar filter).
Missing entries silently drop endpoints from the UI.
"""
import re
from pathlib import Path

import pytest

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
    CninfoFetcher,
    EastMoneyFetcher,
    MyquantFetcher,
    TencentFetcher,
    ThsFetcher,
    TushareFetcher,
    YfinanceFetcher,
    ZhituFetcher,
    ZzshareFetcher,   # NEW
)


@pytest.mark.parametrize("cap", list(DataCapability))
def test_every_capability_has_intent_declared(cap):
    """Every DataCapability MUST be mapped to a method in CAPABILITY_TO_METHOD."""
    assert cap in CAPABILITY_TO_METHOD, (
        f"DataCapability.{cap.name} is not in CAPABILITY_TO_METHOD. "
        f"Add it to declare intent."
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


_HTML_PATH = Path(__file__).resolve().parent.parent / "stock_data" / "explorer" / "static" / "index.html"


def _extract_capability_groups(html_text: str) -> dict[str, list[str]]:
    """Parse the literal `const CAPABILITY_GROUPS = { ... }` block from index.html.

    Keeps this test resilient to JS formatting changes (single-line vs.
    multi-line, trailing commas) by scanning line-by-line for entries of
    the shape `<group>: [<caps>],`.
    """
    groups: dict[str, list[str]] = {}
    in_block = False
    depth = 0
    for line in html_text.splitlines():
        stripped = line.strip()
        if not in_block:
            if stripped.startswith("const CAPABILITY_GROUPS"):
                in_block = True
                # Single-line form: const CAPABILITY_GROUPS = { quotes: [...] };
                if "}" in stripped:
                    return _parse_inline_groups(stripped)
            continue
        # multi-line: collect entries until matching closing brace
        if "{" in stripped:
            depth += stripped.count("{")
        if "}" in stripped:
            depth -= stripped.count("}")
            if depth <= 0:
                break
        m = re.match(r'^([A-Za-z_]\w*):\s*\[([^\]]*)\],?\s*$', stripped)
        if m:
            group, caps_str = m.group(1), m.group(2)
            groups[group] = re.findall(r'"([^"]+)"', caps_str)
    return groups


def _parse_inline_groups(stripped: str) -> dict[str, list[str]]:
    """Fallback: extract `key: [a, b]` entries from a single-line literal."""
    groups: dict[str, list[str]] = {}
    for m in re.finditer(r'(\w+):\s*\[([^\]]*)\]', stripped):
        groups[m.group(1)] = re.findall(r'"([^"]+)"', m.group(2))
    return groups


def test_every_capability_is_in_some_capability_group():
    """Every DataCapability flag must appear in at least one HTML capability group.

    `renderContent()` filters endpoints by `epMatchesCapabilityFilter`, which
    checks `ep.capabilities.some(c => activeCaps.includes(c))`. If a
    capability is in NONE of the active groups, the endpoint is silently
    dropped. This test catches the STOCK_INFO-style gap where the server
    registers the capability but the UI filter has no slot for it.
    """
    if not _HTML_PATH.exists():
        pytest.skip("explorer/static/index.html not found")
    html_text = _HTML_PATH.read_text(encoding="utf-8")
    groups = _extract_capability_groups(html_text)
    assert groups, "Could not parse CAPABILITY_GROUPS from index.html"

    all_caps_in_groups = {cap for caps in groups.values() for cap in caps}
    missing = [c.name for c in DataCapability if c.name not in all_caps_in_groups]
    assert not missing, (
        f"DataCapability flag(s) missing from every CAPABILITY_GROUPS entry "
        f"in stock_data/explorer/static/index.html: {missing}. "
        f"Add each flag to at least one group, otherwise "
        f"epMatchesCapabilityFilter silently hides the endpoint card. "
        f"Current groups: {groups}"
    )
