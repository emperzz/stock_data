"""NewsMixin — news / announcements / 7×24 flash methods for EastMoneyFetcher.

Mixed into ``EastMoneyFetcher`` so the public class surface is unchanged.
Owns:

Class attrs:
- ``_NEWS_SEARCH_BASE_HEADERS`` — Chrome-120 desktop fingerprint with
  cache-busting headers required by search-api-web. Consumed by
  ``EastMoneyFetcher.__init__`` to seed the curl_cffi Session's default
  headers before the first request.
- ``_FLASH_NEWS_MAX_PAGE_SIZE`` / ``_FLASH_NEWS_MIN_LIMIT`` — the
  upstream 7×24 hard caps.

Instance attrs set by ``__init__``:
- ``self._news_warmed`` — bool flag, gates the per-session warmup GET so
  we hit ``so.eastmoney.com/news/s`` at most once per process.

Methods:
- ``_ensure_news_session`` — once-per-session warmup GET.
- ``_news_callback_name`` — JSONP callback name generator.
- ``search_news``, ``get_stock_news``, ``get_announcements``,
  ``fetch_flash_news`` — the four public news endpoints.
- ``_normalize_news_item`` — private text-cleaning helper mirroring
  akshare's ``stock_news_em`` extraction. The ``<em>`` strip lives in
  :func:`stock_data.data_provider.utils.text.strip_em_tags` and is
  shared with :class:`ThsFetcher`.
"""

from __future__ import annotations

import json
import logging
import os
import re
import time
from urllib.parse import quote

from ...base import DataFetchError
from ...utils.normalize import normalize_stock_code
from ...utils.text import strip_em_tags
from ...utils.url_helpers import source_domain as source_domain_from_url
from ._cffi_json import cffi_json_get, cffi_json_get_resp
from ._endpoints import UA, URLS

logger = logging.getLogger(__name__)


class NewsMixin:
    """News-protocol methods for EastMoneyFetcher.

    Endpoints:
    - search_news      → search-api-web (JSONP)
    - get_stock_news   → np-listapi.getListInfo (per-stock 6-digit code)
    - get_announcements → np-anotice-stock (per-stock bare 6-digit code;
      note this differs from boards/news which use secid {market}.{code})
    - fetch_flash_news → np-weblist.getFastNewsList (7×24 global feed)

    Header fingerprint: search-api-web explicitly fingerprints UA +
    sec-ch-* + sec-fetch-*. Missing ``Cache-Control: no-cache`` or
    ``Pragma: no-cache`` signals "cached/replay request" and triggers
    silent empty results — ``_NEWS_SEARCH_BASE_HEADERS`` below must be
    applied at session init.
    """

    # ---- Class attrs ----

    # pageSize 上游硬 cap 200; 超过就 cap; 下限 1
    _FLASH_NEWS_MAX_PAGE_SIZE = 200
    _FLASH_NEWS_MIN_LIMIT = 1
    # Full Chrome 120 desktop fingerprint + cache-busting headers. The
    # search backend fingerprints UA + sec-ch-* + sec-fetch-*; missing
    # Cache-Control/Pragma no-cache signals "this is a cached/replay
    # request" and triggers silent empty results.
    _NEWS_SEARCH_BASE_HEADERS = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        ),
        "Referer": "https://so.eastmoney.com/news/s",
        "Origin": "https://so.eastmoney.com",
        "Accept": "*/*",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        "Accept-Encoding": "gzip, deflate, br",
        "Cache-Control": "no-cache",
        "Pragma": "no-cache",
        "sec-ch-ua": '"Not_A Brand";v="8", "Chromium";v="120", "Google Chrome";v="120"',
        "sec-ch-ua-mobile": "?0",
        "sec-ch-ua-platform": '"Windows"',
        "sec-fetch-dest": "script",
        "sec-fetch-mode": "no-cors",
        "sec-fetch-site": "same-site",
    }

    # ------------------------------------------------------------------
    # Session warmup
    # ------------------------------------------------------------------

    def _ensure_news_session(self) -> None:
        """Seed cookies by GETting the public search page once per session.

        The search-api-web backend silently downgrades cookie-less requests to
        empty results, so we prime the session with a real-browser visit to
        so.eastmoney.com before the first search. Failures are non-fatal
        (we'd rather attempt the search than crash on the warmup).
        """
        if self._news_warmed:
            return
        try:
            self._session.get(URLS.NEWS_WARMUP, timeout=8)
        except Exception as e:  # warmup is best-effort; we still attempt the search
            logger.debug(f"[EastMoneyFetcher] news warmup failed (non-fatal): {e}")
        self._news_warmed = True

    @staticmethod
    def _news_callback_name() -> str:
        """Generate a jQuery-style JSONP callback name.

        Pattern: ``jQuery<PID>_<millisecond-timestamp>``. Matches what
        jQuery.ajax() produces in a real browser when jsonpCallback is left
        unspecified — the per-call timestamp suffix also doubles as
        cache-busting. EastMoneyFetcher is a singleton in DataFetcherManager,
        so no locking is needed around the name.
        """
        timestamp_ms = int(time.time() * 1000)
        return f"jQuery{os.getpid()}_{timestamp_ms}"

    # ------------------------------------------------------------------
    # News search (search-api-web JSONP)
    # ------------------------------------------------------------------

    def search_news(
        self,
        q: str,
        from_date: str | None = None,
        to_date: str | None = None,
        limit: int = 20,
    ) -> list[dict]:
        """Search EastMoney news by keyword.

        Returns a list of normalized news-item dicts; see spec §6.1 for schema.
        Raises DataFetchError on upstream failure.
        """
        if not q or len(q) > 200:
            raise DataFetchError(
                f"[EastMoneyFetcher] search_news: invalid q (len={len(q) if q else 0})"
            )
        # Coerce limit to int (the explorer mini-form sends HTML input values
        # as strings; without coercion the range check raises TypeError).
        try:
            limit = int(limit)
        except (TypeError, ValueError) as e:
            raise DataFetchError(
                f"[EastMoneyFetcher] search_news: limit must be an integer 1..100 (got {limit!r})"
            ) from e
        if not (1 <= limit <= 100):
            raise DataFetchError(
                f"[EastMoneyFetcher] search_news: limit must be 1..100 (got {limit})"
            )

        # JSONP callback name mimics jQuery's auto-generated pattern (e.g.
        # ``jQuery35101792940631092459_1764599530176``) — the leading counter
        # + per-call timestamp suffix is what a real browser produces when
        # jsonpCallback is left unspecified.
        cb = self._news_callback_name()
        inner = {
            "uid": "",
            "keyword": q,
            "type": ["cmsArticleWebOld"],
            "client": "web",
            "clientType": "web",
            "clientVersion": "curr",
            "param": {
                "cmsArticleWebOld": {
                    "searchScope": "default",
                    "sort": "default",
                    "pageIndex": 1,
                    "pageSize": limit,
                    "preTag": "<em>",
                    "postTag": "</em>",
                }
            },
        }
        # The trailing ``_`` is a millisecond-timestamp cache-buster that
        # akshare (and the real browser frontend) always send; the backend
        # silently returns empty results when it's missing.
        params = {
            "cb": cb,
            "param": json.dumps(inner, ensure_ascii=False),
            "_": str(int(time.time() * 1000)),
        }

        logger.info(f"[EastMoneyFetcher] news search q={q!r} limit={limit}")
        self._ensure_news_session()
        # Referer includes the search keyword — matches akshare and the
        # real-browser frontend (the search result page URL itself carries
        # ?keyword=...). The session default lacks the keyword and would
        # only match a "blank /news/s" navigation.
        #
        # The keyword MUST be percent-encoded before being interpolated
        # into the header. Raw non-ASCII (e.g. Chinese) characters trip
        # Python's latin-1 codec on the http.client layer and raise
        # UnicodeEncodeError("'latin-1' codec can't encode characters in
        # position 40-43") *before* the request goes out — i.e. the search
        # fails with "Network error" on the very first Chinese character
        # of the keyword. Akshare doesn't hit this because its default
        # ``symbol`` is the ASCII stock code "603777"; we accept arbitrary
        # Chinese queries from the explorer mini-form, so we encode
        # explicitly. UTF-8 percent-encoding matches what a real browser
        # sends for `?keyword=...` in the URL bar.
        resp = cffi_json_get_resp(
            self._session,
            URLS.NEWS_SEARCH,
            params=params,
            headers={
                "Referer": f"https://so.eastmoney.com/news/s?keyword={quote(q)}",
            },
            error_label="search_news",
        )

        text = resp.text.strip()
        # Strip JSONP wrapper: "jQuery_cb_name({"...": ...})"
        m = re.match(r"^\w+\((.*)\)$", text, re.DOTALL)
        if not m:
            raise DataFetchError("[EastMoneyFetcher] search_news: response not JSONP")
        try:
            payload = json.loads(m.group(1))
        except json.JSONDecodeError as e:
            raise DataFetchError(f"[EastMoneyFetcher] search_news: bad JSON: {e}") from e

        if payload.get("code") != 0:
            raise DataFetchError(
                f"[EastMoneyFetcher] search_news API code={payload.get('code')} msg={payload.get('msg')}"
            )

        records = (payload.get("result") or {}).get("cmsArticleWebOld") or []
        out: list[dict] = []
        for rec in records:
            try:
                item = self._normalize_news_item(rec)
            except (KeyError, TypeError, ValueError) as e:
                logger.warning(f"[EastMoneyFetcher] skipping malformed record: {e}")
                continue
            if from_date and item["publish_date"] < from_date:
                continue
            if to_date and item["publish_date"] > to_date:
                continue
            out.append(item)
        return out

    # ------------------------------------------------------------------
    # Per-stock news feed (np-listapi)
    # ------------------------------------------------------------------

    def get_stock_news(self, stock_code: str, limit: int = 20) -> list[dict]:
        """Get news feed for a specific stock via np-listapi.getListInfo.

        Complementary to ``search_news(q)`` (which uses search-api-web and needs
        a keyword / 中文 stock name) — this method takes a 6-digit stock code
        directly and does not need any name lookup.

        Returns a list of normalized dicts with fields:
            title, url, source_domain, publish_date (YYYY-MM-DD), media_name.
        Returns [] on invalid code or empty upstream list. Raises
        ``DataFetchError`` on network/HTTP/JSON failure.
        """
        code = normalize_stock_code(stock_code)
        if not code:
            return []
        try:
            limit = max(1, min(int(limit), 100))
        except (TypeError, ValueError):
            limit = 20

        secid = self._secid(code)
        params = {
            "cfh": 1,
            "client": "web",
            "mTypeAndCode": secid,
            "type": 1,
            "pageSize": limit,
        }
        payload = cffi_json_get(
            self._session,
            URLS.STOCK_NEWS,
            params=params,
            headers={"Referer": "https://quote.eastmoney.com/"},
            error_label=f"get_stock_news({code})",
        )

        if payload.get("code") != 1:
            logger.warning(
                f"[EastMoneyFetcher] get_stock_news({code}) code={payload.get('code')} "
                f"msg={payload.get('message')}"
            )
            return []

        data = payload.get("data") or {}
        rows = data.get("list") or []
        out: list[dict] = []
        for rec in rows:
            try:
                url = rec.get("Art_Url") or rec.get("Art_OriginUrl") or ""
                source_domain = source_domain_from_url(url)
                out.append(
                    {
                        "title": rec.get("Art_Title", ""),
                        "url": url,
                        "source_domain": source_domain,
                        "publish_date": (rec.get("Art_ShowTime") or "")[:10],
                        "media_name": rec.get("Np_dst", "") or rec.get("Author", "") or "",
                    }
                )
            except (KeyError, TypeError) as e:
                logger.warning(f"[EastMoneyFetcher] skipping malformed news row: {e}")
                continue
        return out

    # ------------------------------------------------------------------
    # Announcements (np-anotice-stock)
    # ------------------------------------------------------------------

    def get_announcements(self, code: str, page_size: int = 30, page_index: int = 1) -> list[dict]:
        """Get corporate announcements via np-anotice-stock.

        Mirrors CninfoFetcher.get_announcements
        shape so the route layer can merge both sources transparently.

        Returns a list of normalized dicts with fields:
            title, type (e.g. "A,SHA"), date (YYYY-MM-DD), url.

        Note: the method was originally named ``get_stock_announcements``;
        renamed to ``get_announcements`` in Task 7 so the manager's
        ``_with_failover(DataCapability.ANNOUNCEMENT, ...)`` lambda
        (``lambda f: f.get_announcements(code, page_size)``) can call it
        alongside CninfoFetcher without per-fetcher method overrides.
        """
        code = normalize_stock_code(code)
        if not code:
            return []
        try:
            page_size = max(1, min(int(page_size), 100))
        except (TypeError, ValueError):
            page_size = 30
        try:
            page_index = max(1, int(page_index))
        except (TypeError, ValueError):
            page_index = 1

        params = {
            "sr": -1,
            "page_size": page_size,
            "page_index": page_index,
            "ann_type": "A",
            "client_source": "web",
            "stock_list": code,  # 6-digit code, NOT secid (unlike boards/news)
            "f_node": 0,
            "s_node": 0,
        }
        payload = cffi_json_get(
            self._session,
            URLS.STOCK_ANNOUNCEMENTS,
            params=params,
            headers={"Referer": "https://data.eastmoney.com/"},
            error_label=f"get_announcements({code})",
        )

        data = payload.get("data") or {}
        rows = data.get("list") or []
        out: list[dict] = []
        for rec in rows:
            try:
                art_code = rec.get("art_code", "")
                date_str = (rec.get("notice_date") or "")[:10]
                codes = rec.get("codes") or []
                ann_type = ""
                if codes and isinstance(codes[0], dict):
                    ann_type = codes[0].get("ann_type", "") or ""
                url = f"https://data.eastmoney.com/notices/detail/{code}/{art_code}.html"
                out.append(
                    {
                        "title": rec.get("title", ""),
                        "type": ann_type,
                        "date": date_str,
                        "url": url,
                    }
                )
            except (KeyError, TypeError) as e:
                logger.warning(f"[EastMoneyFetcher] skipping malformed announcement row: {e}")
                continue
        return out

    # ------------------------------------------------------------------
    # News record normalisation helpers (private)
    # ------------------------------------------------------------------

    @staticmethod
    def _normalize_news_item(rec: dict) -> dict:
        """Convert one upstream record to the spec's NewsItem dict.

        Mirrors akshare's stock_news_em extraction:
        - URL is rebuilt from the ``code`` field (akshare trusts code as the
          source of truth; the upstream's ``url`` field is sometimes stale).
          Falls back to ``rec["url"]`` only when ``code`` is missing.
        - ``content`` is cleaned of <em> tags, full-width spaces (``\\u3000``),
          and ``\\r\\n`` (collapsed to single space).
        - ``image`` and the raw ``code`` are not exposed in the output.

        Raises KeyError/TypeError/ValueError on missing critical fields,
        which the caller treats as a skip.
        """
        # URL: akshare always rebuilds from `code`. We do the same but fall
        # back to rec["url"] when `code` is missing (defensive — has not been
        # observed in production responses).
        code = rec.get("code")
        url = f"http://finance.eastmoney.com/a/{code}.html" if code else rec["url"]

        date_str = rec["date"][:10]  # "YYYY-MM-DD HH:MM:SS" -> "YYYY-MM-DD"

        # Snippet: akshare strips <em> tags, full-width space (\\u3000), and
        # collapses \\r\\n to a single space.
        raw_content = rec.get("content", "")
        snippet = strip_em_tags(raw_content).replace("　", "").replace("\r\n", " ")

        return {
            "title": strip_em_tags(rec["title"]),
            "url": url,
            "source_domain": source_domain_from_url(url),
            "publish_date": date_str,
            "snippet": snippet,
            "media_name": rec.get("mediaName", ""),
        }

    # ------------------------------------------------------------------
    # 7×24 全球财经快讯 (Flash News)
    # ------------------------------------------------------------------

    def fetch_flash_news(self, limit: int = 50) -> list[dict]:
        """Get 7x24 global financial flash news.

        上游 URL: https://np-weblist.eastmoney.com/comm/web/getFastNewsList
        上游 pageSize 硬 cap 200;超过就 cap 到 200。
        响应: ``{"code": 0, "data": {"size": N, "fastNewsList": [...]}}``
        每个 item 字段: title, summary, code (文章 ID), showTime, ...

        Returns:
            归一化后的 list[dict],每条形如:
            ``{title, url, source_domain, publish_time, snippet}``
            当上游 fastNewsList 缺失或为 null 时返回 ``[]``。

        Raises:
            DataFetchError: 网络异常 / HTTP 非 200 / 上游 code != 0 / limit 越界
        """
        # 参数防御: 路由层 FastAPI Query(ge=1, le=200) 会拦,但 fetcher 也独立校验
        # (单一职责, 跨调用方安全)。
        try:
            limit = int(limit)
        except (TypeError, ValueError) as e:
            raise DataFetchError(
                f"[EastMoneyFetcher] fetch_flash_news: limit must be int (got {limit!r})"
            ) from e
        if limit < self._FLASH_NEWS_MIN_LIMIT:
            raise DataFetchError(
                f"[EastMoneyFetcher] fetch_flash_news: limit must be "
                f"at least {self._FLASH_NEWS_MIN_LIMIT} (got {limit})"
            )
        # 上限不报错, 直接 cap 到 _FLASH_NEWS_MAX_PAGE_SIZE。
        # 路由层 FastAPI Query(le=200) 会拦, 但 fetcher 也防御, 避免一条坏数据废整个 list。

        page_size = min(limit, self._FLASH_NEWS_MAX_PAGE_SIZE)
        params = {
            "client": "web",
            "biz": "web_724",
            "fastColumn": "102",
            "sortEnd": "",
            "pageSize": str(page_size),
            "req_trace": str(int(time.time() * 1000)),
        }
        headers = {
            "User-Agent": UA,
            "Referer": "https://kuaixun.eastmoney.com/",
        }
        payload = cffi_json_get(
            self._session,
            URLS.FLASH_NEWS,
            params=params,
            headers=headers,
            error_label="fetch_flash_news",
        )

        # 上游 code 在成功时是字符串 "1" (有时是 int 0/1, 视端点而异);
        # 接受所有"成功"指示符。仅当 code 是已知失败值(-1 等)时才报错。
        if payload.get("code") not in (0, "0", 1, "1"):
            raise DataFetchError(
                f"[EastMoneyFetcher] fetch_flash_news API code={payload.get('code')} "
                f"msg={payload.get('message')}"
            )

        raw_list = (payload.get("data") or {}).get("fastNewsList")
        if not raw_list:
            return []

        out: list[dict] = []
        for rec in raw_list:
            try:
                code = rec["code"]
                out.append(
                    {
                        "title": rec.get("title", ""),
                        "url": f"https://finance.eastmoney.com/a/{code}.html",
                        "source_domain": "finance.eastmoney.com",
                        "publish_time": rec.get("showTime", ""),
                        "snippet": rec.get("summary", ""),
                    }
                )
            except (KeyError, TypeError) as e:
                # 单条记录缺关键字段(article code)就跳过, 避免一条坏数据废整个 list
                logger.warning(
                    f"[EastMoneyFetcher] fetch_flash_news: skipping malformed record: {e}"
                )
                continue
        return out
