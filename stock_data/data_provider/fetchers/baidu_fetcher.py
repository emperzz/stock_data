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
