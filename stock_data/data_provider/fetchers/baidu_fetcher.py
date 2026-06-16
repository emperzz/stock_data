"""
Baidu Qianfan Web Search API fetcher — news search only.

Provides: NEWS_SEARCH (Baidu 千帆 v2 ai_search/web_search)

API: POST https://qianfan.baidubce.com/v2/ai_search/web_search
Auth: Authorization: Bearer <BAIDU_API_KEY>

Reference: https://cloud.baidu.com/doc/qianfan-api/s/Wmbq4z7e5
"""

from __future__ import annotations

import json
import logging
import os
from datetime import date
from typing import Any
from urllib.parse import urlparse

import requests

from ..base import BaseFetcher, DataCapability, DataFetchError

logger = logging.getLogger(__name__)

WEB_SEARCH_URL = "https://qianfan.baidubce.com/v2/ai_search/web_search"
API_KEY_ENV = "BAIDU_API_KEY"

# Baidu upstream hard limit on resource_type_filter[].top_k
BAIDU_MAX_TOP_K = 50

# Cap on user-provided q length (matches EastMoneyFetcher convention)
MAX_Q_LEN = 200


class BaiduFetcher(BaseFetcher):
    """Baidu Qianfan Web Search API fetcher — news search only."""

    name = "BaiduFetcher"
    priority = int(os.getenv("BAIDU_PRIORITY", "7"))
    supported_markets: set[str] = {"csi"}
    supported_data_types = DataCapability.NEWS_SEARCH

    def is_available(self) -> bool:
        return bool(os.getenv(API_KEY_ENV, "").strip())

    def unavailable_reason(self) -> str | None:
        if self.is_available():
            return None
        return f"BaiduFetcher unavailable: {API_KEY_ENV} env var is empty"

    # K-line methods are not supported by Baidu Web Search API.
    def _fetch_raw_data(self, stock_code, start_date, end_date, frequency="d", adjust=None):
        raise DataFetchError("BaiduFetcher does not support historical K-line data")

    def _normalize_data(self, df, stock_code):
        raise DataFetchError("BaiduFetcher does not support historical K-line data")

    def search_news(
        self,
        q: str,
        from_date: str | None = None,
        to_date: str | None = None,
        limit: int = 20,
    ) -> list[dict]:
        """Search Baidu news by keyword.

        Returns a list of normalized news-item dicts matching the NewsItem schema.
        Raises DataFetchError on upstream failure.
        """
        # ---- input validation ----
        if not q or len(q) > MAX_Q_LEN:
            raise DataFetchError(
                f"[BaiduFetcher] search_news: invalid q (len={len(q) if q else 0})"
            )
        try:
            limit = int(limit)
        except (TypeError, ValueError) as e:
            raise DataFetchError(
                f"[BaiduFetcher] search_news: limit must be an integer 1..100 (got {limit!r})"
            ) from e
        if not (1 <= limit <= 100):
            raise DataFetchError(
                f"[BaiduFetcher] search_news: limit must be 1..100 (got {limit})"
            )

        # ---- request ----
        api_key = os.getenv(API_KEY_ENV, "").strip()
        if not api_key:
            raise DataFetchError(f"[BaiduFetcher] search_news: {API_KEY_ENV} not set")

        body: dict[str, Any] = {
            "messages": [{"content": q, "role": "user"}],
            "search_source": "baidu_search_v2",
            "resource_type_filter": [
                {"type": "web", "top_k": min(limit, BAIDU_MAX_TOP_K)},
            ],
        }
        recency = _derive_recency(from_date)
        if recency:
            body["search_recency_filter"] = recency

        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

        logger.info(f"[BaiduFetcher] news search q={q!r} limit={limit}")
        try:
            resp = requests.post(WEB_SEARCH_URL, headers=headers, json=body, timeout=15)
        except Exception as e:
            raise DataFetchError(f"[BaiduFetcher] search_news network error: {e}") from e

        if not (200 <= resp.status_code < 300):
            raise DataFetchError(
                f"[BaiduFetcher] search_news HTTP {resp.status_code}"
            )

        try:
            payload = resp.json()
        except (ValueError, json.JSONDecodeError) as e:
            raise DataFetchError(f"[BaiduFetcher] search_news: bad JSON: {e}") from e

        # Baidu returns code/message only on errors; absence means success.
        if "code" in payload and payload["code"] not in (0, None, "0"):
            raise DataFetchError(
                f"[BaiduFetcher] search_news API code={payload['code']} msg={payload.get('message')}"
            )

        records = payload.get("references") or []
        out: list[dict] = []
        for rec in records:
            try:
                item = self._normalize_news_item(rec)
            except (KeyError, TypeError, ValueError) as e:
                logger.warning(f"[BaiduFetcher] skipping malformed record: {e}")
                continue
            if from_date and item["publish_date"] < from_date:
                continue
            if to_date and item["publish_date"] > to_date:
                continue
            out.append(item)
        return out

    @staticmethod
    def _normalize_news_item(rec: dict) -> dict:
        """Convert one upstream reference to the NewsItem dict schema.

        Raises KeyError/TypeError on missing critical fields; caller treats
        as a skip.
        """
        url = rec["url"]
        date_str = rec["date"][:10]
        domain = urlparse(url).netloc
        return {
            "title": rec["title"],
            "url": url,
            "source_domain": domain,
            "publish_date": date_str,
            "snippet": rec.get("content", ""),
            "media_name": domain,  # Baidu 没有专门的 mediaName 字段
        }


def _derive_recency(from_date: str | None) -> str | None:
    """Map from_date (YYYY-MM-DD) to Baidu search_recency_filter enum.

    Returns None if from_date is None or unparseable (Baidu then returns
    default recency — no client filter).
    """
    if not from_date:
        return None
    try:
        days = (date.today() - date.fromisoformat(from_date)).days
    except ValueError:
        return None
    if days <= 7:
        return "week"
    if days <= 30:
        return "month"
    if days <= 180:
        return "semiyear"
    return "year"
