"""
巨潮公告 API fetcher.

API: https://www.cninfo.com.cn/new/hisAnnouncement/query
"""

import logging
import os
from datetime import datetime

import requests

from ..base import BaseFetcher, DataCapability, DataFetchError
from ..utils.normalize import normalize_stock_code

logger = logging.getLogger(__name__)

CNINFO_URL = "https://www.cninfo.com.cn/new/hisAnnouncement/query"
CNINFO_UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"


class CninfoFetcher(BaseFetcher):
    """巨潮公告 API fetcher."""

    name = "CninfoFetcher"
    priority = int(os.getenv("CNINFO_PRIORITY", "8"))
    supported_markets: set[str] = {"csi"}
    supported_data_types = DataCapability.ANNOUNCEMENT

    def is_available(self) -> bool:
        return True

    def _normalize_data(self, df, stock_code):
        raise DataFetchError("CninfoFetcher does not support historical K-line data")

    def _org_id(self, code: str) -> str:
        """Build orgId for cninfo API."""
        if code.startswith("6"):
            return f"gssh0{code}"
        elif code.startswith(("8", "4")):
            return f"gsbj0{code}"
        else:
            return f"gssz0{code}"

    def get_announcements(self, code: str, page_size: int = 30) -> list[dict]:
        """Get announcement list for a stock."""
        code = normalize_stock_code(code)
        org_id = self._org_id(code)
        payload = {
            "stock": f"{code},{org_id}",
            "tabName": "fulltext",
            "pageSize": str(page_size),
            "pageNum": "1",
            "column": "", "category": "", "plate": "",
            "seDate": "", "searchkey": "", "secid": "",
            "sortName": "", "sortType": "", "isHLtitle": "true",
        }
        headers = {
            "User-Agent": CNINFO_UA,
            "Content-Type": "application/x-www-form-urlencoded",
            "Referer": "https://www.cninfo.com.cn/new/disclosure",
            "Origin": "https://www.cninfo.com.cn",
        }
        try:
            r = requests.post(CNINFO_URL, data=payload, headers=headers, timeout=15)
            if r.status_code != 200:
                logger.warning(f"[CninfoFetcher] HTTP {r.status_code}")
                return []
            d = r.json()
            rows = []
            for item in d.get("announcements", []) or []:
                rows.append({
                    "title": item.get("announcementTitle", ""),
                    "type": item.get("announcementTypeName", ""),
                    "date": datetime.fromtimestamp(item.get("announcementTime", 0) / 1000).strftime("%Y-%m-%d"),
                    "url": f"https://www.cninfo.com.cn/new/disclosure/detail?annoId={item.get('announcementId', '')}",
                })
            return rows
        except Exception as e:
            logger.warning(f"[CninfoFetcher] announcements failed: {e}")
            return []
