"""
同花顺 HTTP API fetcher for signal layer data.

Provides: 热点题材(hot-topics), 北向资金(north-flow)

APIs:
- 热点: zx.10jqka.com.cn/event/api/getharden/
- 北向: data.hexin.cn/market/hsgtApi/method/dayChart/
"""

import logging
import os
from datetime import date as _date

import requests

from ..base import BaseFetcher, DataCapability, DataFetchError

logger = logging.getLogger(__name__)

THS_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "Chrome/117.0.0.0 Safari/537.36"
)

HSGT_HEADERS = {
    "User-Agent": THS_UA,
    "Host": "data.hexin.cn",
    "Referer": "https://data.hexin.cn/",
}


class ThsFetcher(BaseFetcher):
    """同花顺 HTTP API fetcher for signal data."""

    name = "ThsFetcher"
    priority = int(os.getenv("THS_PRIORITY", "7"))
    supported_markets: set[str] = {"csi"}
    supported_data_types = (
        DataCapability.HOT_TOPICS
        | DataCapability.NORTH_FLOW
    )

    def is_available(self) -> bool:
        return True

    def _fetch_raw_data(self, stock_code, start_date, end_date, frequency="d", adjust=None):
        raise DataFetchError("ThsFetcher does not support historical K-line data")

    def _normalize_data(self, df, stock_code):
        raise DataFetchError("ThsFetcher does not support historical K-line data")

    # ------------------------------------------------------------------
    # 热点题材 (Hot Topics)
    # ------------------------------------------------------------------

    def get_hot_topics(self, date_str: str = "") -> list[dict]:
        """Get daily hot stocks with reason tags.

        Returns list of dicts: code, name, reason(题材归因), change_pct,
                                turnover_rate, amount, dde_net
        """
        if not date_str:
            date_str = _date.today().strftime("%Y-%m-%d")

        url = (
            f"http://zx.10jqka.com.cn/event/api/getharden/"
            f"date/{date_str}/orderby/date/orderway/desc/charset/GBK/"
        )
        headers = {"User-Agent": THS_UA}
        try:
            r = requests.get(url, headers=headers, timeout=10)
            data = r.json()
            if data.get("errocode", 0) != 0:
                logger.warning(f"[ThsFetcher] hot topics API error: {data.get('errormsg', '')}")
                return []
            rows = data.get("data") or []
            return [self._normalize_hot_topic(row) for row in rows]
        except Exception as e:
            logger.warning(f"[ThsFetcher] hot topics failed: {e}")
            return []

    def _normalize_hot_topic(self, row: dict) -> dict:
        return {
            "code": row.get("code", ""),
            "name": row.get("name", ""),
            "reason": row.get("reason", ""),
            "change_pct": row.get("zhangfu", 0),
            "turnover_rate": row.get("huanshou", 0),
            "volume": row.get("chengjiaoliang", 0),
            "amount": row.get("chengjiaoe", 0),
            "dde_net": row.get("ddejingliang", 0),
        }

    # ------------------------------------------------------------------
    # 北向资金 (North-bound Flow)
    # ------------------------------------------------------------------

    def get_north_flow(self) -> list[dict]:
        """Get north-bound (沪股通/深股通) minute-level flow.

        Returns list of dicts: time, hgt_yi(沪股通累计净买入, 亿元),
                                sgt_yi(深股通累计净买入, 亿元)
        """
        url = "https://data.hexin.cn/market/hsgtApi/method/dayChart/"
        try:
            r = requests.get(url, headers=HSGT_HEADERS, timeout=10)
            d = r.json()
            times = d.get("time", [])
            hgt = d.get("hgt", [])
            sgt = d.get("sgt", [])

            n = len(times)
            rows = []
            for i in range(n):
                hgt_val = float(hgt[i]) if i < len(hgt) and hgt[i] else None
                sgt_val = float(sgt[i]) if i < len(sgt) and sgt[i] else None
                rows.append({
                    "time": times[i],
                    "hgt_yi": hgt_val,
                    "sgt_yi": sgt_val,
                })
            return rows
        except Exception as e:
            logger.warning(f"[ThsFetcher] north flow failed: {e}")
            return []
