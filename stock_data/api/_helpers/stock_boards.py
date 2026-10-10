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

# The 7 THS per-board enrichment fields. Module-level so the cache writer
# (``fetch_stock_boards_quote_enrichment``) and the merge helper
# (``merge_live_board_fields``) cannot drift apart.
ENRICHMENT_KEYS: tuple[str, ...] = (
    "change_pct",
    "up_count",
    "down_count",
    "limit_up_count",
    "limit_down_count",
    "explain",
    "relevance",
)


def merge_live_board_fields(
    base: dict,
    enrichment: dict | None = None,
    live_row: dict | None = None,
) -> dict:
    """Merge the live THS envelope onto one public-shape board entry.

    Two responsibilities:

    1. **Copy the 7 enrichment fields** (``ENRICHMENT_KEYS``) out of
       ``enrichment``. Only keys the dict actually carries are copied, so a
       partial dict can never blank a value that is already on ``base``.
    2. **Heal placeholder legacy metadata.** ``base`` is in the *public*
       response shape (``code`` / ``name`` / ``type`` / ``subtype`` /
       ``source``) while ``live_row`` is the fetcher's *internal* row shape
       (``board_code`` / ``board_type`` / ...) — hence the asymmetric key
       names below.

    Why the heal is needed
    ----------------------
    ``persistence.board.update_cached_board_stocks`` writes
    ``board_name = board_code`` and ``board_type = ""`` whenever
    ``stock_board`` has no metadata for the board at write time, and
    ``_read_membership_entries`` falls back to those placeholders when its
    LEFT JOIN misses. The fallback is documented as self-healing, but for a
    THS concept that the forward board list doesn't carry (its ``gnSection``
    is only the 今日热门 subset) it never heals — measured 2026-10-10 on
    600519, where ``/stocks/600519/boards`` returned ``886086`` as
    ``{"name": "886086", "type": ""}`` instead of ``西部大开发`` / ``concept``.
    The live reverse payload knows the answer, so the read uses it.

    Scope
    -----
    Only fires when ``base`` carries no real value: ``name`` equal to the
    code, or an empty ``type`` / ``subtype``. Persistence stays authoritative
    for every board it actually knows — reconciling a genuine upstream rename
    (or a delisting) is the backfill's job, not a read's.
    """
    out = dict(base)
    if enrichment:
        for key in ENRICHMENT_KEYS:
            if key in enrichment:
                out[key] = enrichment[key]
    if not live_row:
        return out
    if out.get("name") == out.get("code") and live_row.get("name"):
        out["name"] = live_row["name"]
    if not out.get("type") and live_row.get("board_type"):
        out["type"] = live_row["board_type"]
    if not out.get("subtype") and live_row.get("subtype"):
        out["subtype"] = live_row["subtype"]
    return out


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
        logger.warning(f"[boards.get_stock_boards] live enrichment failed for {stock_code!r}: {e}")
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
    for entry in result:
        code = entry.get("board_code")
        if not code:
            continue
        # Keyed by the board's public code (board_code). Forward ONLY the 7
        # enrichment keys — name/type/subtype are NOT carried here, because a
        # blind dict update would let upstream shadow the persistence layer's
        # authoritative read. Callers that need the live name (to heal a
        # placeholder row) read it off ``fetcher_full_result`` via
        # ``merge_live_board_fields``, which scopes the substitution.
        enrichment[code] = {k: entry.get(k) for k in ENRICHMENT_KEYS}
    cached_store(get_stock_boards_quote_cache, cache_key, (result, enrichment))
    return result, enrichment
