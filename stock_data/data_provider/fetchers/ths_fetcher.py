"""
同花顺 HTTP API fetcher for signal layer data.

Provides: 热点题材(hot-topics), 北向资金(north-flow), 全球财经快讯(news-flash),
          新闻搜索(news-search), 板块 K 线(board-history)

APIs:
- 热点: zx.10jqka.com.cn/event/api/getharden/
- 北向: data.hexin.cn/market/hsgtApi/method/dayChart/
- 快讯: news.10jqka.com.cn/tapp/news/push/stock  (pageSize 硬编码 20/页, 内部翻页)
- 搜索: www.iwencai.com/gateway/mobilesearch/comprehensive/search  (问财聚合搜索)
- 板块 K 线:
    - 概念(clid 查找): q.10jqka.com.cn/gn/detail/code/{slug}/  →  clid
    - 行业(直查):     q.10jqka.com.cn/thshy/                  →  slug = inner code
    - 通用 K 线:      d.10jqka.com.cn/v4/line/bk_{inner_code}/01/{year}.js

注意: 新闻搜索走的是同花顺问财 iWenCai (www.iwencai.com), 不是 10jqka 域名。
10jqka 财经页的站内搜索框本身就是跳转到 iWenCai 的。详见 search_news 文档。
"""

import logging
import math
import os
import re
from datetime import date as _date
from datetime import datetime
from functools import lru_cache
from importlib import resources
from urllib.parse import urlparse

from ..base import BaseFetcher, DataCapability, DataFetchError
from ..utils.http import json_get, json_post

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


def _mint_ths_v_token() -> str:
    """Mint the `v` cookie token via py_mini_racer + akshare's bundled ths.js.

    akshare ships `akshare/data/ths.js` (~40KB JS obfuscator). py_mini_racer
    evaluates it then calls the `v()` function to produce the cookie value.

    One mint per process is enough (the token rotates on a long interval).
    The cached wrapper `_get_ths_v_token` keeps the MiniRacer VM warm.

    Raises:
        DataFetchError: py_mini_racer not installed or ths.js not found.
    """
    try:
        import py_mini_racer
    except ImportError as e:
        raise DataFetchError(
            f"[ThsFetcher] board history requires py_mini_racer: {e}"
        ) from e
    js_path = resources.files("akshare.data").joinpath("ths.js")
    if not js_path.is_file():
        raise DataFetchError(
            f"[ThsFetcher] akshare/data/ths.js not found at {js_path}"
        )
    js_text = js_path.read_text(encoding="utf-8")
    js = py_mini_racer.MiniRacer()
    js.eval(js_text)
    return js.call("v")


@lru_cache(maxsize=1)
def _get_ths_v_token() -> str:
    """Cached wrapper around `_mint_ths_v_token`."""
    return _mint_ths_v_token()


class ThsFetcher(BaseFetcher):
    """同花顺 HTTP API fetcher for signal data."""

    name = "ThsFetcher"
    priority = int(os.getenv("THS_PRIORITY", "7"))
    supported_markets: set[str] = {"csi"}
    supported_data_types = (
        DataCapability.HOT_TOPICS
        | DataCapability.NORTH_FLOW
        | DataCapability.NEWS_FLASH
        | DataCapability.NEWS_SEARCH
        | DataCapability.STOCK_BOARD  # for board K-line (concept/industry)
    )

    def is_available(self) -> bool:
        return True

    def _normalize_data(self, df, stock_code):
        raise DataFetchError("ThsFetcher does not support historical K-line data")

    # ------------------------------------------------------------------
    # v-token (cookie auth for board K-line; same mechanism as akshare uses)
    # ------------------------------------------------------------------

    def _v_token(self) -> str:
        """Instance accessor for the cached v token (for class-method ergonomics)."""
        return _get_ths_v_token()

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
            data = json_get(url, headers=headers, timeout=10)
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
            d = json_get(url, headers=HSGT_HEADERS, timeout=10)
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

    # ------------------------------------------------------------------
    # 全球财经快讯 (Flash News) — 同花顺 7x24 实时流
    # ------------------------------------------------------------------

    _FLASH_NEWS_URL = "https://news.10jqka.com.cn/tapp/news/push/stock"
    # 上游 pageSize 硬编码 20/页(实测: pageSize/limit/num/size 等参数均无效)
    _FLASH_NEWS_PAGE_SIZE = 20
    # 与 EastMoneyFetcher.fetch_flash_news 对齐;路由层 Query(le=200) 也会拦
    _FLASH_NEWS_MAX_LIMIT = 200
    _FLASH_NEWS_MIN_LIMIT = 1
    # 单页 HTTP 超时(秒)
    _FLASH_NEWS_TIMEOUT = 10

    @staticmethod
    def _normalize_flash_item(item: dict) -> dict:
        """Convert one upstream record to the FlashNewsItem dict shape.

        与 EastMoneyFetcher.fetch_flash_news 输出 schema 对齐:
        {title, url, source_domain, publish_time, snippet}
        """
        # 防御: rtime 可能是 10 位 Unix timestamp、字符串数字、或脏数据
        rtime_raw = item.get("rtime", "")
        publish_time = ""
        if rtime_raw:
            try:
                publish_time = datetime.fromtimestamp(int(rtime_raw)).strftime(
                    "%Y-%m-%d %H:%M:%S"
                )
            except (TypeError, ValueError, OSError):
                publish_time = str(rtime_raw)  # graceful fallback

        return {
            "title": item.get("title", ""),
            "url": item.get("url", ""),
            "source_domain": "news.10jqka.com.cn",
            "publish_time": publish_time,
            "snippet": item.get("digest", ""),
        }

    def fetch_flash_news(self, limit: int = 50) -> list[dict]:
        """Get THS 7x24 global financial flash news.

        上游 URL: https://news.10jqka.com.cn/tapp/news/push/stock
        上游 pageSize 硬编码 20/页;本方法内部翻 ceil(limit/20) 页
        直到拿到 limit 条或上游返回空 list。

        Returns:
            归一化后的 list[dict],每条形如
            {title, url, source_domain, publish_time, snippet}。
            上游 list 缺失/null/空 → 返回 []。

        Raises:
            DataFetchError: 网络异常 / HTTP 非 200 / 上游 code != 200 / limit 越界
        """
        # limit 防御(路由层 Query(ge=1,le=200) 会拦,这里二次防御)
        try:
            limit = int(limit)
        except (TypeError, ValueError) as e:
            raise DataFetchError(
                f"[ThsFetcher] fetch_flash_news: limit must be int (got {limit!r})"
            ) from e
        if limit < self._FLASH_NEWS_MIN_LIMIT:
            raise DataFetchError(
                f"[ThsFetcher] fetch_flash_news: limit must be "
                f">= {self._FLASH_NEWS_MIN_LIMIT} (got {limit})"
            )
        # 上限不报错,直接 cap,与 EastMoneyFetcher 行为一致
        effective_limit = min(limit, self._FLASH_NEWS_MAX_LIMIT)
        max_pages = math.ceil(effective_limit / self._FLASH_NEWS_PAGE_SIZE)

        out: list[dict] = []
        for page in range(1, max_pages + 1):
            rows = self._fetch_flash_news_page(page)
            if not rows:
                break  # 翻到末页 / 越界,立即停
            out.extend(rows)
            if len(out) >= effective_limit:
                break

        return out[:effective_limit]

    def _fetch_flash_news_page(self, page: int) -> list[dict]:
        """Fetch one upstream page; return normalized list (empty on no-data)."""
        params = {"page": str(page), "tag": "", "track": "website"}
        headers = {
            "User-Agent": THS_UA,
            "Referer": "https://news.10jqka.com.cn/realtimenews.html",
        }
        payload = json_get(
            self._FLASH_NEWS_URL,
            params=params,
            headers=headers,
            timeout=self._FLASH_NEWS_TIMEOUT,
        )

        # 上游成功时 code 是字符串 "200"(实测,不是 int 200)。
        # 与 EastMoneyFetcher.fetch_flash_news 一致,接受 str 和 int 两种"成功"
        # 指示符。仅当 code 是已知失败值(-1、"0"、None)时才报错。
        # 参考 commit 3ae6dfa "fix(eastmoney): accept real upstream code values"。
        if payload.get("code") not in (200, "200"):
            raise DataFetchError(
                f"[ThsFetcher] fetch_flash_news API code={payload.get('code')} "
                f"msg={payload.get('msg')}"
            )

        raw_list = (payload.get("data") or {}).get("list")
        if not raw_list:
            return []

        out: list[dict] = []
        for rec in raw_list:
            # url 是必填字段(对应 EastMoney 校验 rec["code"] 的模式);
            # 缺失视为坏数据,跳过但不抛错。
            if not rec.get("url"):
                logger.warning(
                    f"[ThsFetcher] fetch_flash_news: skipping record without url: "
                    f"id={rec.get('id', '?')}"
                )
                continue
            try:
                out.append(self._normalize_flash_item(rec))
            except (KeyError, TypeError, ValueError) as e:
                # 单条记录缺关键字段就跳过,避免一条坏数据废整个 list
                logger.warning(
                    f"[ThsFetcher] fetch_flash_news: skipping malformed record: {e}"
                )
                continue
        return out

    # ------------------------------------------------------------------
    # 新闻搜索 (News Search) — 同花顺问财 iWenCai 聚合搜索
    # ------------------------------------------------------------------

    # 问财 PC 聚合搜索接口。注意是 www.iwencai.com 域名(同花顺问财),不是
    # 10jqka —— 10jqka 财经页的站内搜索框 (#search_input) 本身就跳转到这里。
    _NEWS_SEARCH_URL = (
        "https://www.iwencai.com/gateway/mobilesearch/comprehensive/search"
    )
    # channels 选 news_filter+web → 资讯/网页聚合(多源: 新浪/百度/10jqka 等)。
    _NEWS_SEARCH_CHANNELS = ["news_filter", "web"]
    _NEWS_SEARCH_MAX_Q_LEN = 200
    _NEWS_SEARCH_TIMEOUT = 15
    _NEWS_SEARCH_HEADERS = {
        "User-Agent": THS_UA,
        "Content-Type": "application/json",
        "Referer": "https://www.iwencai.com/",
        "Origin": "https://www.iwencai.com",
    }

    @staticmethod
    def _strip_em(s: str) -> str:
        """剥离 <em>/</em> 高亮标签(与 EastMoneyFetcher._strip_em 对齐)。"""
        return (
            s.replace("(<em>", "")
            .replace("</em>)", "")
            .replace("<em>", "")
            .replace("</em>", "")
        )

    @classmethod
    def _normalize_search_item(cls, rec: dict) -> dict:
        """Convert one iWenCai record to the shared NewsItem dict shape.

        归一化到与 EastMoneyFetcher._normalize_news_item / NewsItem schema
        完全一致的 6 字段: {title, url, source_domain, publish_date,
        snippet, media_name}。

        - ``url`` 直接用上游原文链接(问财聚合, 指向源站如新浪/百度/10jqka)。
        - ``publish_date`` 取 ``publish_date`` 的前 10 位 (YYYY-MM-DD)。
        - ``source_domain`` 优先用 ``extra.host_name``, 缺失时回退 urlparse(url)。
        - ``media_name`` 用 ``extra.publish_source`` (e.g. 新浪财经)。

        Raises KeyError/TypeError/ValueError on missing url/title, which the
        caller treats as a skip.
        """
        url = rec["url"]  # 必填: 缺失视为坏数据 → KeyError → 上层跳过
        title = cls._strip_em(rec["title"])
        extra = rec.get("extra") or {}
        # publish_date 形如 "2026-06-30 18:28:21"; 截到日。
        publish_date = (rec.get("publish_date") or "")[:10]
        snippet = cls._strip_em(rec.get("summary") or "").replace("　", "").strip()
        source_domain = extra.get("host_name") or urlparse(url).netloc
        return {
            "title": title,
            "url": url,
            "source_domain": source_domain,
            "publish_date": publish_date,
            "snippet": snippet,
            "media_name": extra.get("publish_source") or "",
        }

    def search_news(
        self,
        q: str,
        from_date: str | None = None,
        to_date: str | None = None,
        limit: int = 20,
    ) -> list[dict]:
        """Search news via 同花顺问财 iWenCai (EastMoney-fetcher backup).

        ThsFetcher 作为 ``NEWS_SEARCH`` 能力的又一路 failover backup(EastMoney
        P6 primary → Baidu/Ths P7 backup)。

        上游: ``POST www.iwencai.com/gateway/mobilesearch/comprehensive/search``
        请求体: ``{offset, size, app_id:"wencai_pc", query, channels:[...],
        scroll_mode:"web", platform:"pc"}``。问财是全网聚合搜索, 结果来源不限于
        同花顺自家(新浪/百度/10jqka 等都可能出现)。

        鉴权: 实测当前**无需** hexin-v / v cookie token, 普通 UA + JSON body
        即可。若上游日后收紧, 可复用 akshare 自带的 ``ths.js`` + py_mini_racer
        生成 ``v`` token (``js.eval(ths.js); js.call("v")``), 以 ``Cookie: v=...``
        头补上 —— 目前刻意不引入该依赖路径 (YAGNI)。

        Returns:
            归一化后的 list[dict], 每条匹配 NewsItem schema:
            ``{title, url, source_domain, publish_date, snippet, media_name}``。

        Raises:
            DataFetchError: 参数越界 / 网络异常 / HTTP 非 200 / 上游 status_code != 0。
        """
        # ---- 参数校验(与 EastMoney/Baidu 的 search_news 对齐)----
        if not q or len(q) > self._NEWS_SEARCH_MAX_Q_LEN:
            raise DataFetchError(
                f"[ThsFetcher] search_news: invalid q (len={len(q) if q else 0})"
            )
        try:
            limit = int(limit)
        except (TypeError, ValueError) as e:
            raise DataFetchError(
                f"[ThsFetcher] search_news: limit must be an integer 1..100 (got {limit!r})"
            ) from e
        if not (1 <= limit <= 100):
            raise DataFetchError(
                f"[ThsFetcher] search_news: limit must be 1..100 (got {limit})"
            )

        body = {
            "offset": 0,
            "size": limit,
            "app_id": "wencai_pc",
            "query": q,
            "channels": self._NEWS_SEARCH_CHANNELS,
            "scroll_mode": "web",
            "platform": "pc",
        }

        logger.info(f"[ThsFetcher] news search q={q!r} limit={limit}")
        payload = json_post(
            self._NEWS_SEARCH_URL,
            json_body=body,
            headers=self._NEWS_SEARCH_HEADERS,
            timeout=self._NEWS_SEARCH_TIMEOUT,
        )

        if payload.get("status_code") != 0:
            raise DataFetchError(
                f"[ThsFetcher] search_news API status_code={payload.get('status_code')} "
                f"msg={payload.get('status_msg')}"
            )

        records = payload.get("data") or []
        out: list[dict] = []
        for rec in records:
            try:
                item = self._normalize_search_item(rec)
            except (KeyError, TypeError, ValueError) as e:
                logger.warning(f"[ThsFetcher] search_news: skipping malformed record: {e}")
                continue
            # 日期过滤(publish_date 为 "YYYY-MM-DD", 字符串比较即可)。空日期不被过滤掉。
            if from_date and item["publish_date"] and item["publish_date"] < from_date:
                continue
            if to_date and item["publish_date"] and item["publish_date"] > to_date:
                continue
            out.append(item)
        return out
