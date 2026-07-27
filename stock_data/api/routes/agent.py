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

from ._router import router  # noqa: F401 -- scaffold for upcoming /api/v1/agent/* routes (Task 5+)

logger = logging.getLogger(__name__)
