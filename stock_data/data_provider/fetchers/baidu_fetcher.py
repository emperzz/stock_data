"""
Baidu Qianfan Web Search API fetcher — news search only.

Provides: NEWS_SEARCH (Baidu 千帆 v2 ai_search/web_search)

API: POST https://qianfan.baidubce.com/v2/ai_search/web_search
Auth: Authorization: Bearer <BAIDU_API_KEY>

Reference: https://cloud.baidu.com/doc/qianfan-api/s/Wmbq4z7e5

Domain restriction: by default `search_news` only returns results from three
authoritative Chinese financial-news sources (东方财富 / 财联社 / 同花顺). The
list is sent upstream inside the `search_filter.match.site` body field (the
API's official whitelist mechanism) and is also enforced client-side as a
safety net (records outside the whitelist are dropped). Override via the
`BAIDU_NEWS_DOMAINS` env var (comma-separated), or set it to an empty
string to disable the filter entirely.

Domain denylist: a curated list of subdomains is sent upstream in the
`block_websites` body field (the API's official denylist mechanism) AND
mirrored client-side as a safety net. The default list excludes (a)
sub-par eastmoney.com entry points — `emwap` (mobile WAP), `quote`
(quote pages, not news articles), `guba` (user forum) — and (b) all
known mobile subdomains of the 3 whitelisted sources. Override via the
`BAIDU_NEWS_BLOCKED_DOMAINS` env var (comma-separated); empty string
disables the filter entirely.

Mobile-prefix safety net: in addition to the explicit denylist above,
records served from a mobile subdomain (`m.`, `wap.`, `mobile.`, `mb.`)
are also dropped client-side. This is purely a defense-in-depth check
for unknown future mobile subdomains (Baidu's `block_websites` only
takes exact hosts, not prefix globs). Override via the
`BAIDU_NEWS_MOBILE_PREFIXES` env var (comma-separated); empty string
disables the filter.
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

# Default whitelist of authoritative Chinese financial-news domains.
# Matched as a suffix on the URL host (covers all subdomains, e.g. finance.eastmoney.com
# is allowed by "eastmoney.com"). These are passed to Baidu inside the
# `search_filter.match.site` body field (the API's official whitelist
# mechanism); see search_news() for the client-side post-filter that
# mirrors it as a safety net.
DEFAULT_NEWS_DOMAINS: tuple[str, ...] = (
    "eastmoney.com",  # 东方财富 (finance.eastmoney.com, stock.eastmoney.com, ...)
    "cls.cn",  # 财联社 (www.cls.cn, m.cls.cn, ...)
    "10jqka.com.cn",  # 同花顺 (stock.10jqka.com.cn, news.10jqka.com.cn, ...)
)

# Env-var override (comma-separated). Empty string disables the filter.
NEWS_DOMAINS_ENV = "BAIDU_NEWS_DOMAINS"

# Subdomain prefixes that denote a mobile (or WAP) site. Records whose
# URL host starts with one of these — e.g. `m.cls.cn`, `wap.eastmoney.com`,
# `mobile.10jqka.com.cn` — are dropped by the client-side post-filter, even
# if their parent domain is in the whitelist. The default prefixes cover
# the common mobile entry points used by 东方财富 / 财联社 / 同花顺.
DEFAULT_MOBILE_PREFIXES: tuple[str, ...] = (
    "m.",  # standard mobile subdomain
    "wap.",  # legacy WAP-era mobile site
    "mobile.",  # full-word mobile subdomain
    "mb.",  # mobile-banking-style prefix
)

# Env-var override (comma-separated). Empty string disables the filter.
MOBILE_PREFIXES_ENV = "BAIDU_NEWS_MOBILE_PREFIXES"

# Explicit denylist of hosts to exclude from search results. Sent upstream
# inside the `block_websites` body field (the API's official denylist) and
# mirrored client-side as a safety net. The default list combines:
#   1. Sub-par eastmoney.com entry points we don't want as news sources
#      (mobile WAP, quote pages, user forum).
#   2. Known mobile subdomains of the 3 whitelisted sources (because the
#      whitelist uses suffix-match, these would otherwise leak through).
# Matched as an exact host (no suffix or glob — `block_websites` only
# supports exact hosts per the official docs).
DEFAULT_BLOCKED_DOMAINS: tuple[str, ...] = (
    # --- eastmoney.com sub-par entry points ---
    "emwap.eastmoney.com",  # 东方财富 WAP 入口 (mobile)
    "emdatah5.eastmoney.com",  # 东方财富 数据 H5 页面 (mobile)
    "quote.eastmoney.com",  # 行情页(无正文,无标题)
    "guba.eastmoney.com",  # 股吧(用户评论,质量参差)
    "mguba.eastmoney.com",  # 股吧 移动版 (mobile forum)
    "fund.eastmoney.com",  # 基金页(无新闻正文)
    "data.eastmoney.com",  # 数据中心页(无新闻正文)
    # --- 东方财富 mobile subdomains ---
    "m.eastmoney.com",
    "wap.eastmoney.com",
    "mobile.eastmoney.com",
    "mb.eastmoney.com",
    # --- 财联社 mobile subdomains ---
    "m.cls.cn",
    "wap.cls.cn",
    "mobile.cls.cn",
    "mb.cls.cn",
    # --- 同花顺 mobile subdomains ---
    "m.10jqka.com.cn",
    "wap.10jqka.com.cn",
    "mobile.10jqka.com.cn",
    "mb.10jqka.com.cn",
)

# Env-var override (comma-separated). Empty string disables the filter.
BLOCKED_DOMAINS_ENV = "BAIDU_NEWS_BLOCKED_DOMAINS"


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

        Search results are filtered in three layers (see module docstring for
        the full design rationale):

        1. **Whitelist** (upstream + client-side mirror). Sent to Baidu as
           `search_filter.match.site`; client-side drops any record whose
           `source_domain` doesn't suffix-match a whitelisted domain.
        2. **Denylist** (upstream + client-side mirror). Sent to Baidu as
           `block_websites`; client-side drops any record whose `source_domain`
           is in the explicit denylist (e.g. `guba.eastmoney.com`, mobile
           subdomains of the whitelisted sources).
        3. **Mobile-prefix safety net** (client-side only). Drops records
           whose `source_domain` starts with a known mobile prefix like
           `m.`, `wap.`, `mobile.`, `mb.` — a defense against future
           mobile subdomains that may not be in the explicit denylist yet.
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
            raise DataFetchError(f"[BaiduFetcher] search_news: limit must be 1..100 (got {limit})")

        # ---- request ----
        api_key = os.getenv(API_KEY_ENV, "").strip()
        if not api_key:
            raise DataFetchError(f"[BaiduFetcher] search_news: {API_KEY_ENV} not set")

        domains = _load_news_domains()
        mobile_prefixes = _load_mobile_prefixes()
        blocked_domains = _load_blocked_domains()

        body: dict[str, Any] = {
            "messages": [{"content": q, "role": "user"}],
            "search_source": "baidu_search_v2",
            "resource_type_filter": [
                {"type": "web", "top_k": min(limit, BAIDU_MAX_TOP_K)},
            ],
        }
        if domains:
            # Baidu's official whitelist mechanism is `search_filter.match.site`
            # (NOT `search_domain_filter` — that field doesn't exist on this
            # endpoint). See https://cloud.baidu.com/doc/qianfan-api/s/Wmbq4z7e5
            body["search_filter"] = {"match": {"site": list(domains)}}
        if blocked_domains:
            # Baidu's official denylist mechanism is `block_websites` — an
            # exact-host list (no prefix globs). See the URL above.
            body["block_websites"] = list(blocked_domains)
        recency = _derive_recency(from_date)
        if recency:
            body["search_recency_filter"] = recency

        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

        logger.info(
            f"[BaiduFetcher] news search q={q!r} limit={limit} "
            f"domains={domains or 'unrestricted'} "
            f"blocked={blocked_domains or 'allow-all'} "
            f"mobile_prefixes={mobile_prefixes or 'allow-mobile'}"
        )
        try:
            resp = requests.post(WEB_SEARCH_URL, headers=headers, json=body, timeout=15)
        except Exception as e:
            raise DataFetchError(f"[BaiduFetcher] search_news network error: {e}") from e

        if not (200 <= resp.status_code < 300):
            raise DataFetchError(f"[BaiduFetcher] search_news HTTP {resp.status_code}")

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
            if domains and not _domain_matches(item["source_domain"], domains):
                logger.debug(
                    f"[BaiduFetcher] dropping record outside whitelist: "
                    f"domain={item['source_domain']!r} title={item['title']!r}"
                )
                continue
            if blocked_domains and item["source_domain"].lower() in blocked_domains:
                logger.debug(
                    f"[BaiduFetcher] dropping record on denylist: "
                    f"domain={item['source_domain']!r} title={item['title']!r}"
                )
                continue
            if mobile_prefixes and _is_mobile_host(item["source_domain"], mobile_prefixes):
                logger.debug(
                    f"[BaiduFetcher] dropping mobile-host record: "
                    f"domain={item['source_domain']!r} title={item['title']!r}"
                )
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


def _load_news_domains() -> tuple[str, ...]:
    """Resolve the active news-domain whitelist.

    Reads `BAIDU_NEWS_DOMAINS` (comma-separated). Empty string → no filter.
    Env var unset → `DEFAULT_NEWS_DOMAINS`. Whitespace-only entries are dropped.
    Returned tuple preserves the user's configured order.
    """
    raw = os.getenv(NEWS_DOMAINS_ENV)
    if raw is None:
        return DEFAULT_NEWS_DOMAINS
    parts = tuple(p.strip() for p in raw.split(",") if p.strip())
    # Empty string (or all-whitespace) explicitly disables the filter.
    return parts


def _domain_matches(host: str, whitelist: tuple[str, ...]) -> bool:
    """Return True iff `host` ends in any suffix in `whitelist` (or equals one).

    Match is case-insensitive and suffix-based, so `finance.eastmoney.com`
    matches the entry `eastmoney.com`. Empty host is rejected.
    """
    if not host:
        return False
    h = host.lower().rstrip(".")
    return any(h == d or h.endswith("." + d) for d in whitelist)


def _load_mobile_prefixes() -> tuple[str, ...]:
    """Resolve the active mobile-subdomain denylist.

    Reads `BAIDU_NEWS_MOBILE_PREFIXES` (comma-separated). Empty string → no
    filter (allow mobile). Env var unset → `DEFAULT_MOBILE_PREFIXES`.
    Whitespace-only entries are dropped. The match is case-insensitive;
    prefixes are normalized to lowercase with a trailing dot.
    """
    raw = os.getenv(MOBILE_PREFIXES_ENV)
    if raw is None:
        return DEFAULT_MOBILE_PREFIXES
    parts = tuple(p.strip().lower().rstrip(".") + "." for p in raw.split(",") if p.strip())
    # Empty string (or all-whitespace) explicitly disables the filter.
    return parts


def _is_mobile_host(host: str, mobile_prefixes: tuple[str, ...]) -> bool:
    """Return True iff `host` starts with any of the configured mobile prefixes.

    Match is case-insensitive. The host must have at least one label beyond
    the prefix (e.g. `m.` alone is not a valid host) — though in practice
    this is unreachable because `_normalize_news_item` always produces a
    real netloc from a real URL.
    """
    if not host or not mobile_prefixes:
        return False
    h = host.lower().rstrip(".")
    return any(h.startswith(prefix) for prefix in mobile_prefixes)


def _load_blocked_domains() -> tuple[str, ...]:
    """Resolve the active exact-host denylist.

    Reads `BAIDU_NEWS_BLOCKED_DOMAINS` (comma-separated). Empty string → no
    filter. Env var unset → `DEFAULT_BLOCKED_DOMAINS`. Whitespace-only
    entries are dropped. Entries are normalized to lowercase. The list is
    returned in the user's configured order; downstream code does a simple
    membership test (`host in denylist`), so order doesn't affect
    correctness — but the upstream `block_websites` body field is sent
    in this order to Baidu.
    """
    raw = os.getenv(BLOCKED_DOMAINS_ENV)
    if raw is None:
        return DEFAULT_BLOCKED_DOMAINS
    parts = tuple(p.strip().lower() for p in raw.split(",") if p.strip())
    # Empty string (or all-whitespace) explicitly disables the filter.
    return parts
