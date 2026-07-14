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
from datetime import datetime
from typing import Any

from ..base import BaseFetcher, DataCapability, DataFetchError
from ..core.types import safe_int

logger = logging.getLogger(__name__)

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
        actual_subject_id = data.get("id")
        if actual_subject_id is not None and int(actual_subject_id) != int(subject_id):
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
            date = (
                datetime.fromtimestamp(int(ctime)).strftime("%Y-%m-%d")
                if ctime is not None
                else ""
            )
            out.append(
                {
                    "article_id": article_id,
                    "title": str(raw.get("article_title", "")),
                    "brief": str(raw.get("article_brief", "")),
                    "author": str(raw.get("article_author", "")),
                    "ctime": int(ctime) if ctime is not None else 0,
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
    def _extract_body_text(html_content: str) -> str:
        """BS4 抽出纯文本，保留段落分隔。

        get_text(separator='\\n') 让 <p> 之间的换行保留；strip=True 去行内空白；
        最后 re.sub 折叠连续 3+ 空行为 2 个（避免 <p>嵌套产生过多空行）。
        """
        if not html_content:
            return ""
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(html_content, "lxml")
        text = soup.get_text("\n", strip=True)
        # 折叠连续 3+ 空行为 2 个
        return re.sub(r"\n{3,}", "\n\n", text)

    @staticmethod
    def _dedup_images(article_detail: dict) -> list[str]:
        """合并 `images` 字段和 `content` 内 <img src>，去重保序。"""
        seen: set[str] = set()
        out: list[str] = []
        # 1) articleDetail.images[] 优先
        for url in article_detail.get("images", []) or []:
            if url and url not in seen:
                seen.add(url)
                out.append(str(url))
        # 2) 从 content HTML 里提取 <img src>
        content = article_detail.get("content", "") or ""
        if content:
            from bs4 import BeautifulSoup

            soup = BeautifulSoup(content, "lxml")
            for img in soup.find_all("img"):
                src = img.get("src")
                if src and src not in seen:
                    seen.add(src)
                    out.append(str(src))
        return out

    @staticmethod
    def _fetch_article_detail(article_id: int, html: str) -> dict | None:
        """Parse a detail-page __NEXT_DATA__ → ClsArticle-shaped dict.

        Path: __NEXT_DATA__.props.pageProps.articleDetail
        Fields: id, title, brief, content (HTML), ctime, readingNum, author.name,
                commentNum, images[], subject[].

        Returns None if the articleDetail is missing (CLS returns an empty
        object for invalid IDs).
        """
        next_data = ClsFetcher._parse_next_data(html)
        detail = (
            next_data.get("props", {})
            .get("pageProps", {})
            .get("articleDetail", {})
        )
        # CLS returns an empty dict (or just an error code) for invalid article IDs
        if not detail or not detail.get("id"):
            return None
        ctime = safe_int(detail.get("ctime"), default=0)
        date = (
            datetime.fromtimestamp(int(ctime)).strftime("%Y-%m-%d")
            if ctime
            else ""
        )
        body_text = ClsFetcher._extract_body_text(detail.get("content", "") or "")
        images = ClsFetcher._dedup_images(detail)
        author_obj = detail.get("author") or {}
        return {
            "article_id": int(detail["id"]),
            "title": str(detail.get("title", "")),
            "brief": str(detail.get("brief", "")),
            "author": str(author_obj.get("name", "")) if isinstance(author_obj, dict) else "",
            "ctime": int(ctime),
            "date": date,
            "read_num": safe_int(detail.get("readingNum"), default=0),
            "comments_num": safe_int(detail.get("commentNum"), default=0),
            "share_num": 0,  # detail page doesn't expose share_num; list does
            "images": images,
            "body_text": body_text,
        }
