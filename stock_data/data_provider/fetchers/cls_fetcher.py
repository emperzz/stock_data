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
from datetime import datetime, timedelta, timezone
from importlib import util as importlib_util
from typing import Any

import requests

from ..base import BaseFetcher, DataCapability, DataFetchError
from ..core.types import safe_int
from ..utils.http import random_ua

logger = logging.getLogger(__name__)

# CLS publishes in Asia/Shanghai (UTC+8). Server-local time would silently
# mis-attribute 07:00 +0800 articles to the previous day on UTC machines,
# breaking _find_article_id_by_date for every request.
_CLS_TZ = timezone(timedelta(hours=8))

# CLS list page 早报 subject id (verified 2026-07-14)
CLS_SUBJECT_MORNING_BRIEFING = 1151
# CLS list page 焦点复盘 subject id (verified 2026-07-14)
CLS_SUBJECT_MARKET_RECAP = 1135

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
        # Lazy bs4 import in _extract_body_text / _dedup_images; probe before
        # registering so a missing dep surfaces as unavailability, not a 500.
        return importlib_util.find_spec("bs4") is not None

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
        except ValueError as e:
            # JSONDecodeError is a subclass of ValueError; catching the
            # parent class handles both. Use the parent for clarity.
            raise DataFetchError(f"[ClsFetcher] __NEXT_DATA__ JSON parse failed: {e}") from e

    # ------------------------------------------------------------------
    # Internal: list page parsing
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_subject_articles(subject_id: int, html: str, limit: int = 20) -> list[dict]:
        """Parse the list-page __NEXT_DATA__ → list of normalized article dicts.

        Path: __NEXT_DATA__.props.pageProps.data.articles[]
        Each article is normalized to: {article_id, title, brief, author, ctime,
        date (YYYY-MM-DD), read_num, comments_num, share_num, images}.

        Returns at most `limit` entries (default 20, matching upstream's
        observed article count per subject).
        """
        next_data = ClsFetcher._parse_next_data(html)
        data = next_data.get("props", {}).get("pageProps", {}).get("data", {})
        # Validate the shape — if subject_id mismatch, this is a real upstream change
        actual_subject_id = safe_int(data.get("id"))
        if actual_subject_id is not None and actual_subject_id != int(subject_id):
            logger.warning(
                f"[ClsFetcher] subject_id mismatch: requested={subject_id} "
                f"upstream={actual_subject_id}; parsing anyway"
            )
        articles_raw = data.get("articles", [])
        out: list[dict] = []
        for raw in articles_raw[:limit]:
            article_id = safe_int(raw.get("article_id"))
            if article_id is None or article_id == 0:
                continue
            ctime = safe_int(raw.get("article_time"))
            # Pin to Asia/Shanghai so a UTC server doesn't mis-attribute the
            # 07:00 +0800 publish time to the previous calendar day.
            date = (
                datetime.fromtimestamp(int(ctime), _CLS_TZ).strftime("%Y-%m-%d")
                if ctime
                else ""
            )
            out.append(
                {
                    "article_id": article_id,
                    "title": str(raw.get("article_title", "")),
                    "brief": str(raw.get("article_brief", "")),
                    "author": str(raw.get("article_author", "")),
                    "ctime": int(ctime) if ctime else 0,
                    "date": date,
                    "read_num": safe_int(raw.get("read_num"), default=0),
                    "comments_num": safe_int(raw.get("comments_num"), default=0),
                    "share_num": safe_int(raw.get("share_num"), default=0),
                    "images": [str(raw.get("article_img", ""))] if raw.get("article_img") else [],
                }
            )
        return out

    @staticmethod
    def _find_article_id_by_date(
        articles: list[dict], date: str
    ) -> int | None:
        """Find the article_id whose `date` matches the given YYYY-MM-DD.

        Linear scan — the upstream returns ~20 entries so a dict index is overkill.
        Returns None if no match (route layer should map None → 404).
        """
        for art in articles:
            if art.get("date") == date:
                return art["article_id"]
        return None

    # ------------------------------------------------------------------
    # Internal: detail page parsing
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_body_text(soup) -> str:
        """BS4 抽出纯文本，保留段落分隔。

        get_text(separator='\\n') 让 <p> 之间的换行保留；strip=True 去行内空白；
        最后 re.sub 折叠连续 3+ 空行为 2 个（避免 <p>嵌套产生过多空行）。

        Accepts a pre-parsed ``BeautifulSoup`` so callers can share the parse
        with ``_dedup_images`` (one BS4 parse per detail page, not two).
        """
        if soup is None:
            return ""
        text = soup.get_text("\n", strip=True)
        # 折叠连续 3+ 空行为 2 个
        return re.sub(r"\n{3,}", "\n\n", text)

    @staticmethod
    def _dedup_images(article_detail: dict, soup=None) -> list[str]:
        """从 `content` 内 <img src> 抽取正文图，去重保序。

        跳过 content 里的**第一个** <img> — 那是文章头部封面图（紧跟 lead 段、
        第一个 section header 之前），用户/agent 场景下没有信息量（可视为 logo）。

        **不**合并 `article_detail["images"]` 列表页缩略图 — 那是文章在列表/分享时
        用的封面，与正文无关。仅保留正文 (`content`) 内嵌图。

        Accepts a pre-parsed ``BeautifulSoup`` so callers can share the parse
        with ``_extract_body_text`` (one BS4 parse per detail page, not two).
        """
        seen: set[str] = set()
        out: list[str] = []
        content = article_detail.get("content", "") or ""
        if not content:
            return out
        if soup is None:
            from bs4 import BeautifulSoup

            soup = BeautifulSoup(content, "lxml")
        for i, img in enumerate(soup.find_all("img")):
            if i == 0:
                # Skip the first <img> — it's the article header cover (logo-like,
                # always positioned right after the lead paragraph and before
                # the first <p><strong> section heading).
                continue
            src = img.get("src")
            if src and src not in seen:
                seen.add(src)
                out.append(str(src))
        return out

    @staticmethod
    def _fetch_article_detail(
        article_id: int, html: str, *, share_num: int = 0
    ) -> dict | None:
        """Parse a detail-page __NEXT_DATA__ → ClsArticle-shaped dict.

        Path: __NEXT_DATA__.props.pageProps.articleDetail
        Returns dict with: article_id, title, brief, author, ctime, date,
        read_num, comments_num, share_num, images, body_text.

        ``share_num`` is passed in by the caller (the list-page fetch already
        extracted it; the detail-page payload does not expose it).

        ``article_id`` is the ID the caller used to fetch the URL; we assert
        it matches the detail page's ``id`` field to defend against upstream
        drift (e.g. if /detail/{id}/ serves a different article than
        /subject/{subject_id}/'s articles[] claims).

        Returns None if the articleDetail is missing (CLS returns an empty
        object for invalid IDs). Raises DataFetchError on a mismatched
        article_id (defensive — should never happen in practice).
        """
        next_data = ClsFetcher._parse_next_data(html)
        detail = (
            next_data.get("props", {})
            .get("pageProps", {})
            .get("articleDetail", {})
        )
        # CLS returns an empty dict (or just an error code) for invalid article IDs
        served_id = safe_int(detail.get("id"))
        if not detail or served_id is None:
            return None
        # Defensive: assert the served article matches the requested id.
        # If the list page's article_id and the detail page's id diverge,
        # we'd silently serve the wrong article — fail loud instead.
        if served_id != article_id:
            raise DataFetchError(
                f"[ClsFetcher] article_id mismatch: requested={article_id} "
                f"served={served_id} — list↔detail drift, investigate"
            )
        ctime = safe_int(detail.get("ctime"))
        # Pin to Asia/Shanghai so a UTC server doesn't mis-attribute the
        # 07:00 +0800 publish time to the previous calendar day.
        date = (
            datetime.fromtimestamp(int(ctime), _CLS_TZ).strftime("%Y-%m-%d")
            if ctime
            else ""
        )
        # One BS4 parse per detail page, shared between body_text + img scan.
        content = detail.get("content", "") or ""
        soup = None
        if content:
            from bs4 import BeautifulSoup

            soup = BeautifulSoup(content, "lxml")
        body_text = ClsFetcher._extract_body_text(soup)
        images = ClsFetcher._dedup_images(detail, soup=soup)
        # author may be a dict {name, ...} or a flat string in newer payloads —
        # fall back to the string form so we don't silently drop the value.
        author_obj = detail.get("author")
        if isinstance(author_obj, dict):
            author = str(author_obj.get("name", ""))
        elif isinstance(author_obj, str):
            author = author_obj
        else:
            author = ""
        return {
            "article_id": int(served_id),
            "title": str(detail.get("title", "")),
            "brief": str(detail.get("brief", "")),
            "author": author,
            "ctime": int(ctime) if ctime else 0,
            "date": date,
            "read_num": safe_int(detail.get("readingNum"), default=0),
            "comments_num": safe_int(detail.get("commentNum"), default=0),
            "share_num": int(share_num) if share_num else 0,
            "images": images,
            "body_text": body_text,
        }

    # ------------------------------------------------------------------
    # HTTP helpers
    # ------------------------------------------------------------------

    def _http_get_text(self, url: str, *, timeout: int = 15) -> str:
        """Plain requests.get returning the response body text.

        On 4xx/5xx raises DataFetchError so the manager's _with_failover
        can route to the next fetcher (currently only ClsFetcher, but the
        contract is forward-compatible with EastMoney failover).
        Uses the project's rotating UA pool to avoid fingerprint-based
        throttling on Chinese financial endpoints.
        """
        try:
            r = requests.get(
                url,
                headers={"User-Agent": random_ua()},
                timeout=timeout,
            )
        except requests.RequestException as e:
            raise DataFetchError(f"[ClsFetcher] HTTP GET failed: {url} → {e}") from e
        if not (200 <= r.status_code < 300):
            raise DataFetchError(
                f"[ClsFetcher] HTTP {r.status_code} for {url} ({len(r.content)}B body)"
            )
        return r.text

    # ------------------------------------------------------------------
    # Public methods (called by DataFetcherManager)
    # ------------------------------------------------------------------

    def get_morning_briefing(self, date: str) -> dict | None:
        """Return the 财联社早报 article for `date` (YYYY-MM-DD) or None if no article.

        Internally fetches the list page (subject 1151) to find the article_id
        for the given date, then fetches the detail page for the full body.
        Returns None when either step yields nothing (route layer maps to 404).
        """
        return self._get_subject_article(CLS_SUBJECT_MORNING_BRIEFING, date)

    def get_market_recap(self, date: str) -> dict | None:
        """Return the 财联社焦点复盘 article for `date` (YYYY-MM-DD) or None.

        Subject 1135; same orchestration as get_morning_briefing.
        """
        return self._get_subject_article(CLS_SUBJECT_MARKET_RECAP, date)

    def _get_subject_article(self, subject_id: int, date: str) -> dict | None:
        """Shared orchestration: list page → find article_id by date → detail page.

        DataFetchError from either HTTP call propagates to the caller (the
        manager's failover loop handles routing to the next fetcher).

        Threads the list-page ``share_num`` through to the detail-page dict —
        the detail payload doesn't expose it, but the list article entry does.
        """
        list_url = f"https://www.cls.cn/subject/{subject_id}"
        list_html = self._http_get_text(list_url)
        articles = self._parse_subject_articles(subject_id, list_html, limit=20)
        # Map article_id → share_num so the detail parser can surface it.
        share_by_id = {
            art["article_id"]: art.get("share_num", 0) for art in articles
        }
        article_id = self._find_article_id_by_date(articles, date)
        if article_id is None:
            return None
        detail_url = f"https://www.cls.cn/detail/{article_id}"
        detail_html = self._http_get_text(detail_url)
        return self._fetch_article_detail(
            article_id, detail_html, share_num=share_by_id.get(article_id, 0)
        )
