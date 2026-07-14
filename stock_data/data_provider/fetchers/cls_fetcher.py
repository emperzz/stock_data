"""财联社 (CLS) HTTP fetcher — 早报 + 焦点复盘.

数据源:
- 列表: GET https://www.cls.cn/subject/{1151│1135}  →  __NEXT_DATA__.props.pageProps.data.articles[]
- 详情: GET https://www.cls.cn/detail/{article_id}    →  __NEXT_DATA__.props.pageProps.articleDetail

List page returns ~20 most recent articles (~20-28 day window — CLS has no
pagination API; requests for older dates return 404).

Capabilities: MORNING_BRIEFING (subject 1151) | MARKET_RECAP (subject 1135).
"""

import json
import logging
import os
import re
from typing import Any

import requests  # noqa: F401  # used in Task 9 (_http_get_text)

from ..base import BaseFetcher, DataCapability, DataFetchError
from ..core.types import safe_int  # noqa: F401  # used in Task 7 (_parse_subject_articles)

logger = logging.getLogger(__name__)

# CLS list page 早报 subject id (verified 2026-07-14)
CLS_SUBJECT_MORNING_BRIEFING = 1151
# CLS list page 焦点复盘 subject id (verified 2026-07-14)
CLS_SUBJECT_MARKET_RECAP = 1135

CLS_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/117.0.0.0 Safari/537.36"

# Subject id → human-readable name (used in error messages and as cache namespace)
CLS_SUBJECT_NAMES: dict[int, str] = {
    CLS_SUBJECT_MORNING_BRIEFING: "morning_briefing",
    CLS_SUBJECT_MARKET_RECAP: "market_review",
}

_NEXT_DATA_RE = re.compile(
    r'<script\s+id="__NEXT_DATA__"[^>]*>(.*?)</script>',
    re.DOTALL,
)


class ClsFetcher(BaseFetcher):
    """财联社 fetcher — 早报 (subject 1151) + 焦点复盘 (subject 1135)."""

    name = "ClsFetcher"
    priority = int(os.getenv("CLS_PRIORITY", "8"))
    supported_markets: set[str] = {"csi"}
    supported_data_types = (
        DataCapability.MORNING_BRIEFING | DataCapability.MARKET_RECAP
    )

    def is_available(self) -> bool:
        return True

    def _normalize_data(self, df, stock_code):
        raise DataFetchError("ClsFetcher does not support historical K-line data")

    # ------------------------------------------------------------------
    # Internal: __NEXT_DATA__ JSON extraction
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_next_data(html: str) -> dict[str, Any]:
        """Extract the __NEXT_DATA__ JSON object embedded in the SSR HTML.

        Raises DataFetchError if the script tag is missing or the JSON
        is malformed. Returns the parsed dict.
        """
        if not html:
            raise DataFetchError("[ClsFetcher] empty HTML body")
        m = _NEXT_DATA_RE.search(html)
        if m is None:
            raise DataFetchError(
                "[ClsFetcher] __NEXT_DATA__ script tag not found in HTML"
            )
        try:
            return json.loads(m.group(1))
        except (ValueError, json.JSONDecodeError) as e:
            raise DataFetchError(f"[ClsFetcher] __NEXT_DATA__ JSON parse failed: {e}") from e
