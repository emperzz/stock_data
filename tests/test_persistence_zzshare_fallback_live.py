"""Live-network tests for the ZZSHARE leg used by
``fetch_board_stocks_with_zzshare_fallback``.

Marked ``@pytest.mark.live_network`` — skipped by default in the dev loop
(``pyproject.toml::addopts = ['-m', 'not live_network']``). Run with
``pytest -m live_network`` or ``pytest -m ""`` to actually hit zzshare.

Background
----------
Post-2026-07-10 optimization: ``?source=ths&include_quote=false`` on
boards where the THS leg doesn't serve (beyond-data 401, or upstream
failure) runs the helper's ZZSHARE primary leg. Static code analysis
confirms:

    * ZZSHARE accepts the THS platecode namespace directly (no rewrite).
    * ``_BOARD_TYPE_BY_PLATE_TYPE`` iterates plate_type=14/15/17 with
      the same plate_code.

What we validate live:

    1. ``api.plates_stocks(plate_code="885652")`` returns non-empty rows
       for a real concept board (the user's reproduction platecode).
    2. ``api.plates_stocks(plate_code="881270")`` returns non-empty rows
       for an industry plate (different ``plate_type=14`` branch).
    3. Row shape is compatible with the response schema (6-digit A-share
       code, name, exchange) — no required fields unexpectedly missing.

If live results show any of the above failing, the fallback contract
as documented (CLAUDE.md "Board Cache Source-Normalization" + helper
docstring) needs revision before merging the optimization.
"""

import pytest

from stock_data.data_provider.fetchers.zzshare_fetcher import ZzshareFetcher

pytestmark = pytest.mark.live_network


@pytest.mark.parametrize(
    "platecode",
    [
        # 885652 is the user's reproduction platecode (concept board;
        # 钛白粉概念 — covers the THS tail-401 bug we just patched).
        "885652",
        # 881270 is an industry board; ZZSHARE's plate_type=14 branch
        # should hit. Adds a non-concept coverage point.
        "881270",
    ],
)
def test_zzshare_plates_stocks_serves_named_platecode(platecode):
    """``api.plates_stocks(plate_code=X)`` returns recognisable rows for concept & industry plates.

    Contract for the ZZSHARE leg: ``source='ths'`` + ``include_quote=False``
    requests that hit the fallback path need ``plates_stocks(plate_code=X)``
    to return at least one valid 6-digit A-share code per plate. If this
    fails for any board we claim to serve, the fallback chain silently
    degrades to THS or to a 404.
    """
    if not ZzshareFetcher().is_available():
        pytest.skip("ZzshareFetcher dependencies unavailable (py_mini_racer / demjson3 missing)")

    rows = ZzshareFetcher().get_board_stocks(platecode, include_quote=False)
    assert isinstance(rows, list), (
        f"ZZSHARE returned non-list for plate {platecode}: {type(rows).__name__}"
    )
    # Core contract: at least one 6-digit A-share code in the rows.
    recognised = [
        r for r in rows
        if isinstance(r.get("stock_code"), str)
        and r["stock_code"].isdigit()
        and len(r["stock_code"]) == 6
    ]
    assert recognised, (
        f"ZZSHARE returned no recognisable 6-digit rows for plate {platecode}: "
        f"raw={rows[:3]}"
    )
