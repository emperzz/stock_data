"""Stock-board enrichment helpers (THS live quote envelope).

Shared by ``/stocks/{code}/boards`` and ``/agent/stocks/batch-profile``.
Backed by a 60s in-process TTLCache (``_stock_boards_quote_cache``).
"""

import logging

from ...data_provider.base import DataFetchError
from ..cache import (
    cached_lookup,
    cached_store,
    get_stock_boards_quote_cache,
    is_cache_enabled,
)

logger = logging.getLogger(__name__)


def fetch_stock_boards_quote_enrichment(
    stock_code: str, manager
) -> tuple[list[dict] | None, dict[str, dict]]:
    """Live-fetch THS stock_concept_list for /stocks/{code}/boards enrichment.

    The ``manager`` parameter is dependency-injected rather than calling
    ``get_manager()`` internally so tests can swap in a ``MagicMock`` and
    exercise the helper's try/except contract independently of the route
    (see ``test_ths_source_enrichment_helper_internal_try_except_swallows_fetcher_error``
    for the canonical example). Production callers pass the route-level
    ``get_manager()`` singleton; tests pass a fake manager whose
    ``get_stock_boards`` raises / returns / etc.

    Returns ``(fetcher_full_result, enrichment_by_code)`` where:
    - ``fetcher_full_result`` is the full fetcher list (each entry has all
      11 fields: 4 legacy + 7 enrichment), or ``None`` on failure /
      disabled cache. Used by the route as the response data when
      persistence has no rows for THS (cold-cache fallback).
    - ``enrichment_by_code`` is ``{code: {7 enrichment keys}}`` keyed by
      THS platecode (885xxx). Used by the route to merge onto warm-cache
      entries whose source == 'ths'. Empty dict on failure / no rows.

    Both empty / None when:
    - the in-process cache is disabled (``ENABLE_API_CACHE=false``);
    - the fetcher raises (best-effort: WARNING logged, no exception
      propagated — the rest of the response must still ship);
    - the fetcher returns an empty list (no concepts for this stock);
    - every THS board for this stock has no ``quote_code`` (defensive).

    Field naming matches ``BoardQuoteResponse`` (change_pct / up_count /
    down_count) and ``StockBoardInfo`` (limit_up_count / limit_down_count
    / explain / relevance). Numeric values are already coerced by
    ``ThsFetcher.get_stock_boards`` (``safe_int`` / ``safe_float``).

    The 60s TTL bounds upstream QPS to one ``stock_concept_list`` call
    per (stock_code) per minute, regardless of how many
    ``GET /stocks/{code}/boards`` requests land on the server.

    Cache slot: dedicated ``_stock_boards_quote_cache`` (maxsize=512, ttl=60s)
    in ``api/cache.py`` — split out from the shared ``_quote_cache`` so the
    high-fanout enrichment keys don't evict true quote keys
    (e.g. ``"600519"``, ``"idx_quote:000300"``).

    Cache-value contract (m6 review): only store tuples of the form
    ``(list, dict)``. ``cached_lookup`` returns ``None`` on cache miss
    AND on disabled cache AND on missing key — a future caller storing
    ``cached_store(..., None)`` would be indistinguishable from a miss
    and silently re-fetch forever. Storing ``([], {})`` for the empty
    result avoids this footgun and still lets the route distinguish
    "no upstream data" from "first uncached call" (the route handles
    both identically today, but the contract is documented).
    """
    if not is_cache_enabled():
        return None, {}
    cache_key = f"stock_boards_quote:{stock_code}"
    hit = cached_lookup(get_stock_boards_quote_cache, cache_key, "stock_boards_quote")
    if hit is not None:
        return hit
    try:
        result, _name = manager.get_stock_boards(stock_code, source="ths")
    except DataFetchError as e:
        # Circuit-breaker-open / upstream 5xx / business-level stock_concept_list
        # failure: log + skip enrichment. The 5 legacy fields still flow.
        logger.warning(
            f"[boards.get_stock_boards] live enrichment failed for "
            f"{stock_code!r}: {e}"
        )
        return None, {}
    except Exception as e:  # defensive: never break the response
        logger.warning(
            f"[boards.get_stock_boards] live enrichment unexpected error "
            f"for {stock_code!r}: {type(e).__name__}: {e}"
        )
        return None, {}
    if not result:
        # Cache the empty result for 60s so we don't keep retrying the
        # upstream for a stock that genuinely has no concept membership.
        cached_store(get_stock_boards_quote_cache, cache_key, ([], {}))
        return [], {}
    enrichment: dict[str, dict] = {}
    enrichment_keys = (
        "change_pct",
        "up_count",
        "down_count",
        "limit_up_count",
        "limit_down_count",
        "explain",
        "relevance",
    )
    for entry in result:
        code = entry.get("code")
        if not code:
            continue
        # Forward ONLY the 7 enrichment keys — don't shadow code/name/type/
        # subtype/source, which are owned by the persistence layer's
        # authoritative read.
        enrichment[code] = {k: entry.get(k) for k in enrichment_keys}
    cached_store(get_stock_boards_quote_cache, cache_key, (result, enrichment))
    return result, enrichment