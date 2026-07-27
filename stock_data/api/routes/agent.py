"""Agent batch / aggregation endpoints.

All endpoints under ``/api/v1/agent/*`` live here. They fan-out across
multiple existing ``DataFetcherManager`` calls and apply server-side
join / set-arithmetic that the agent would otherwise do by hand.

Design contract (see ``docs/agent-batch-api-proposal-2026-07-27.md``):
- Per-item error isolation: one failure never aborts the response.
- JSON-only output (Phase 1); ``?format=md`` lands in Phase 2.4.
- No LLM judgment — only numeric filter, set-op, count statistics.
- ``@endpoint_meta(capabilities=[])`` because the endpoints don't map
  to a single capability flag.

Routes added in Phase 1 (this file):
- POST /agent/boards/stock-overlap (renamed from boards/overlap per 2026-07-27 user request)
- POST /agent/stocks/board-overlap
- POST /agent/boards/filter-stocks
"""

import logging
from itertools import combinations

from ...data_provider.base import DataFetchError
from ...data_provider.persistence import board as stock_board_cache
from ..cache import (
    cached_lookup,
    cached_store,
    get_quote_cache,  # reused as generic in-memory slot for agent results
    is_cache_enabled,
    make_boards_overlap_cache_key,
)
from ..endpoint_meta import endpoint_meta
from ..schemas import (
    BoardsOverlapPair,
    BoardsOverlapRequest,
    BoardsOverlapResponse,
    BoardsOverlapSet,
    ErrorResponse,
)
from ._router import router
from .errors import map_errors
from .helpers import get_manager

logger = logging.getLogger(__name__)


@router.post(
    "/agent/boards/stock-overlap",
    response_model=BoardsOverlapResponse,
    responses={
        400: {"model": ErrorResponse, "description": "Invalid request"},
        500: {"model": ErrorResponse, "description": "Server error"},
    },
    tags=["agent"],
)
@endpoint_meta(
    summary="板块成分股两两重叠度（set-op 服务端化，替代 LLM 手算交集）",
    markets=["csi"],
    capabilities=[],
)
@map_errors
def post_boards_stock_overlap(payload: BoardsOverlapRequest) -> BoardsOverlapResponse:
    """Compute pairwise stock-set overlap across 2-10 boards.

    Each board is fetched via ``stock_board_cache.get_board_stocks`` with
    ``source='ths', include_quote=False`` (consistent with the existing
    /boards/{code}/stocks path). Per-board failures surface in
    ``errors[]`` without aborting the response.
    """
    cache_key = make_boards_overlap_cache_key(payload.codes)
    hit = cached_lookup(get_quote_cache, cache_key, "agent_boards_stock_overlap")
    if hit is not None:
        return hit

    manager = get_manager()
    sets_out: list[BoardsOverlapSet] = []
    sets_index: dict[str, set[str]] = {}  # code -> set of stock codes
    errors: list[dict] = []

    for code in payload.codes:
        try:
            stocks, _origin, effective_source, _reason, _qtrunc, _total = (
                stock_board_cache.get_board_stocks(
                    code,
                    source="ths",
                    include_quote=False,
                    manager=manager,
                )
            )
        except (DataFetchError, ValueError) as exc:
            logger.warning(f"[agent/boards/stock-overlap] {code} failed: {exc}")
            errors.append({"code": code, "error": type(exc).__name__, "message": str(exc)})
            continue
        codes_set = {
            (s.get("stock_code") or s.get("code") or "").strip()
            for s in stocks
            if (s.get("stock_code") or s.get("code"))
        }
        sets_index[code] = codes_set
        sets_out.append(
            BoardsOverlapSet(code=code, count=len(codes_set), source=effective_source or "ths")
        )

    pairs: list[BoardsOverlapPair] = []
    for a, b in combinations(sets_index.keys(), 2):
        sa, sb = sets_index[a], sets_index[b]
        inter = sorted(sa & sb)
        union = sa | sb
        jaccard = (len(inter) / len(union)) if union else 0.0
        pairs.append(
            BoardsOverlapPair(
                a=a,
                b=b,
                intersection=inter,
                intersection_count=len(inter),
                jaccard=jaccard,
            )
        )

    result = BoardsOverlapResponse(sets=sets_out, pairs=pairs, errors=errors)
    if is_cache_enabled():
        cached_store(get_quote_cache, cache_key, result)
    return result
