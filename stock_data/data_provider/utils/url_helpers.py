"""URL-domain helpers shared by fetchers.

Review 2026-07-06 finding #4: ``urlparse(url).hostname`` vs ``.netloc``
was inconsistent across fetchers (ths / eastmoney / baidu / news_extractor).
A URL with explicit port (e.g. ``http://example.com:8080/news``) yielded
different ``source_domain`` strings depending on which fetcher processed
it — breaking cross-source dedup.

This module is the single source of truth for "domain name for source
attribution" — strip port, never raise.
"""

from __future__ import annotations

from urllib.parse import urlparse


def source_domain(url: str | None) -> str:
    """Return the bare domain for source attribution. Strips port.

    Returns ``""`` on parse failure, empty input, or ``None``. Never
    raises — fetcher code can call this without try/except and trust
    the result is safe to put in a response field.

    Examples:
        >>> source_domain("https://news.10jqka.com.cn/article")
        'news.10jqka.com.cn'
        >>> source_domain("http://example.com:8080/news")
        'example.com'
        >>> source_domain("")
        ''
        >>> source_domain(None)
        ''
    """
    if not url:
        return ""
    try:
        parsed = urlparse(url)
    except (ValueError, TypeError, AttributeError):
        return ""
    # .hostname strips the port; .netloc keeps it. Use .hostname for
    # source-attribution consistency.
    return parsed.hostname or ""
