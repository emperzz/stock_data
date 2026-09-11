"""Live: after the id-map seed, almost no concept row should lack a platecode.

Before this change the sidebar-only set (~88 of ~383 rows per snapshot) had
``platecode=None`` — see the old note at ths_fetcher.py:1784-1790. The
runtime detail-page fallback (and its write-back) now resolves those too.
Marked live_network; the suite xfails network-class failures automatically.
"""

from __future__ import annotations

import pytest

from stock_data.data_provider.fetchers.ths_fetcher import ThsFetcher

pytestmark = pytest.mark.live_network


def test_concept_platecode_coverage_is_high():
    rows = ThsFetcher().get_all_boards(board_type="concept")
    assert rows, "upstream returned no concept boards"
    unresolved = [r for r in rows if not r.get("platecode")]
    # Measured 3/141 unresolved before the runtime fallback existed. Allow
    # headroom for boards created after the seed snapshot whose detail page
    # also fails to parse.
    assert len(unresolved) <= max(5, len(rows) // 50), (
        f"{len(unresolved)}/{len(rows)} concept rows lack a platecode: "
        f"{[r.get('name') for r in unresolved[:10]]}"
    )
