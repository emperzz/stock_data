"""
News content extractor: given a URL, fetch and extract the article body.

The default handler is a deterministic HTML scraper. Source-specific handlers
are registered per domain at the bottom of this module.
"""

import inspect
import ipaddress
import json
import logging
import re
import socket
from collections.abc import Callable
from dataclasses import dataclass, replace
from typing import Literal
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup
from bs4.element import Tag

from .http import random_ua
from .url_helpers import source_domain as source_domain_from_url

logger = logging.getLogger(__name__)

_EM_BODY_STOP_KEYWORDS = ("文章来源", "责任编辑", "郑重声明", "网友评论")
_EM_AD_KEYWORDS = ("看资讯行情", "选东方财富证券")
_BLOCK_MARKERS = (
    "请输入验证码",
    "访问频繁",
    "请求过于频繁",
    "人机验证",
    "安全验证",
    "登录后查看",
    "access denied",
    "captcha",
    "challenge",
)
_GENERIC_SELECTORS = (
    "article",
    "div.content",
    "div#content",
    "div.article-content",
    "div.article-body",
    "main",
)
_NOISE_SELECTORS = (
    "script",
    "style",
    "nav",
    "aside",
    "header",
    "footer",
    "iframe",
    "form",
    ".recommend",
    ".recommend-list",
    ".related",
    ".comment",
    ".comments",
    ".login",
)

_MAX_RESPONSE_BYTES = 5 * 1024 * 1024
_MAX_JSON_LD_BYTES = 256 * 1024
_MAX_METADATA_CHARS = 512
_RESPONSE_CHUNK_SIZE = 64 * 1024

ContentStatus = Literal[
    "ok",
    "empty",
    "unsupported",
    "javascript_required",
    "blocked",
    "fetch_error",
]


@dataclass
class NewsContent:
    url: str
    title: str | None
    body: str
    publish_date: str | None  # YYYY-MM-DD
    author: str | None
    source_domain: str
    extractor: str
    byte_size: int
    content_status: ContentStatus = "ok"
    reason: str | None = None
    canonical_url: str | None = None
    http_status: int | None = None

    @classmethod
    def _build(
        cls,
        url: str,
        title: str | None = None,
        body: str = "",
        publish_date: str | None = None,
        author: str | None = None,
        source_domain: str = "",
        extractor: str = "default",
        content_status: ContentStatus = "ok",
        reason: str | None = None,
        canonical_url: str | None = None,
        http_status: int | None = None,
    ) -> "NewsContent":
        return cls(
            url=url,
            title=title,
            body=body,
            publish_date=publish_date,
            author=author,
            source_domain=source_domain or source_domain_from_url(url),
            extractor=extractor,
            byte_size=len(body.encode("utf-8")),
            content_status=content_status,
            reason=reason,
            canonical_url=canonical_url,
            http_status=http_status,
        )


class _ResponseTooLargeError(Exception):
    """The upstream HTML exceeded the bounded content-fetch size."""


# --- SSRF protection ---

_PRIVATE_IP_RANGES = [
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("169.254.0.0/16"),  # link-local / cloud metadata (AWS/GCP/Azure IMDS)
    ipaddress.ip_network("100.64.0.0/10"),  # CGNAT
    ipaddress.ip_network("198.18.0.0/15"),  # benchmarking
    ipaddress.ip_network("0.0.0.0/8"),
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("fc00::/7"),
    ipaddress.ip_network("fe80::/10"),  # IPv6 link-local
]


def _is_private_ip(host: str) -> bool:
    """Resolve host to IP and check if it is a private/loopback address."""
    try:
        try:
            ip = ipaddress.ip_address(host)
        except ValueError:
            ip = ipaddress.ip_address(socket.gethostbyname(host))
        return any(ip in net for net in _PRIVATE_IP_RANGES)
    except (socket.gaierror, ValueError):
        # Fail closed when DNS cannot establish that the target is public.
        return True


def _validate_url(url: str) -> str:
    """Return the hostname for a public HTTP(S) URL, otherwise raise."""
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise ValueError(f"url must be http or https (got {parsed.scheme!r})")
    host = parsed.hostname
    if not host:
        raise ValueError("url has no host")
    host = host.lower()
    if host == "localhost":
        raise ValueError("url points to internal network (localhost)")
    if _is_private_ip(host):
        raise ValueError("url points to internal network (private IP)")
    return host


def _read_response_bytes(resp: requests.Response) -> bytes:
    """Read a response with a hard upper bound, supporting test doubles."""
    iterator = getattr(resp, "iter_content", None)
    if callable(iterator):
        chunks = bytearray()
        for chunk in iterator(chunk_size=_RESPONSE_CHUNK_SIZE):
            if not chunk:
                continue
            chunks.extend(chunk)
            if len(chunks) > _MAX_RESPONSE_BYTES:
                raise _ResponseTooLargeError
        return bytes(chunks)

    content = getattr(resp, "content", None)
    if isinstance(content, bytes):
        if len(content) > _MAX_RESPONSE_BYTES:
            raise _ResponseTooLargeError
        return content

    text = getattr(resp, "text", "")
    encoded = str(text).encode("utf-8")
    if len(encoded) > _MAX_RESPONSE_BYTES:
        raise _ResponseTooLargeError
    return encoded


# --- Shared metadata and text helpers ---


def _clip_metadata(value: str | None) -> str | None:
    if not value:
        return None
    return value.strip()[:_MAX_METADATA_CHARS] or None


def _normalize_date(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    match = re.search(r"\d{4}-\d{2}-\d{2}", value)
    return match.group(0) if match else None


def _json_ld_objects(soup: BeautifulSoup) -> list[dict]:
    objects: list[dict] = []
    for script in soup.find_all("script", attrs={"type": "application/ld+json"}):
        raw = script.string or script.get_text()
        if not raw or not raw.strip():
            continue
        if len(raw.encode("utf-8", errors="ignore")) > _MAX_JSON_LD_BYTES:
            continue
        try:
            value = json.loads(raw)
        except (TypeError, ValueError, RecursionError):
            continue
        values = value if isinstance(value, list) else [value]
        for item in values:
            if not isinstance(item, dict):
                continue
            graph = item.get("@graph")
            if isinstance(graph, list):
                objects.extend(node for node in graph if isinstance(node, dict))
            else:
                objects.append(item)
    return objects


def _extract_metadata(
    soup: BeautifulSoup,
) -> tuple[str | None, str | None, str | None, str | None]:
    json_ld = _json_ld_objects(soup)

    title = None
    og_title = soup.find("meta", attrs={"property": "og:title"})
    if og_title and isinstance(og_title.get("content"), str):
        title = og_title["content"].strip()
    if not title:
        for item in json_ld:
            headline = item.get("headline")
            if isinstance(headline, str) and headline.strip():
                title = headline.strip()
                break
    if not title and soup.title:
        title = soup.title.get_text(" ", strip=True) or None

    publish_date = None
    published = soup.find("meta", attrs={"property": "article:published_time"})
    if published:
        publish_date = _normalize_date(published.get("content"))
    if not publish_date:
        for item in json_ld:
            publish_date = _normalize_date(item.get("datePublished"))
            if publish_date:
                break

    author = None
    for item in json_ld:
        raw_author = item.get("author")
        if isinstance(raw_author, dict):
            raw_author = raw_author.get("name")
        elif isinstance(raw_author, list) and raw_author:
            first = raw_author[0]
            raw_author = first.get("name") if isinstance(first, dict) else first
        if isinstance(raw_author, str) and raw_author.strip():
            author = raw_author.strip()
            break
    if not author:
        author_meta = soup.find("meta", attrs={"name": "author"})
        if author_meta and isinstance(author_meta.get("content"), str):
            author = author_meta["content"].strip() or None

    canonical_url = None
    canonical = soup.find("link", rel=lambda value: value and "canonical" in value)
    if canonical and isinstance(canonical.get("href"), str):
        candidate = canonical["href"].strip()
        if urlparse(candidate).scheme in ("http", "https"):
            canonical_url = candidate

    return _clip_metadata(title), publish_date, _clip_metadata(author), canonical_url


def _normalize_body(text: str) -> str:
    lines: list[str] = []
    for line in text.splitlines():
        normalized = re.sub(r"\s+", " ", line).strip()
        if normalized and (not lines or normalized != lines[-1]):
            lines.append(normalized)
    return "\n".join(lines)


def _candidate_text(node: Tag) -> tuple[str, int, float]:
    clone = BeautifulSoup(str(node), "html.parser")
    for noise in clone.select(", ".join(_NOISE_SELECTORS)):
        noise.decompose()
    text = _normalize_body(clone.get_text("\n", strip=True))
    paragraphs = [p.get_text(" ", strip=True) for p in clone.select("p")]
    paragraph_count = sum(bool(p) for p in paragraphs)
    link_chars = sum(len(a.get_text(" ", strip=True)) for a in clone.select("a"))
    link_ratio = link_chars / max(len(text), 1)
    return text, paragraph_count, link_ratio


def _collect_candidates(soup: BeautifulSoup, selectors: tuple[str, ...]) -> list[Tag]:
    candidates: list[Tag] = []
    seen: set[int] = set()
    for selector in selectors:
        for node in soup.select(selector):
            marker = id(node)
            if marker not in seen:
                seen.add(marker)
                candidates.append(node)
    return candidates


def _has_credible_candidate(soup: BeautifulSoup) -> bool:
    for candidate in _collect_candidates(soup, _GENERIC_SELECTORS):
        text, paragraphs, link_ratio = _candidate_text(candidate)
        if link_ratio <= 0.6 and (len(text) >= 80 or (paragraphs >= 2 and len(text) >= 40)):
            return True
    return False


def _looks_blocked(soup: BeautifulSoup) -> bool:
    text = _normalize_body(soup.get_text("\n", strip=True))
    if len(text) >= 500 or _has_credible_candidate(soup):
        return False
    if _collect_candidates(soup, _GENERIC_SELECTORS):
        return False
    lowered = text.lower()
    return any(marker in lowered for marker in _BLOCK_MARKERS)


def _looks_like_js_shell(html: str, soup: BeautifulSoup) -> bool:
    if _has_credible_candidate(soup):
        return False
    raw = html.lower()
    has_shell_marker = any(
        marker in raw
        for marker in ("__next_data__", 'id="app"', "id='app'", "/bundle.js", "webpack")
    )
    if not has_shell_marker:
        return False
    noscript_body = _noscript_body(soup)
    if len(noscript_body) >= 40:
        return True
    visible = _normalize_body(soup.get_text("\n", strip=True))
    return len(visible) < 80


def _noscript_body(soup: BeautifulSoup) -> str:
    texts = [_normalize_body(node.get_text("\n", strip=True)) for node in soup.find_all("noscript")]
    return max(texts, key=len, default="")


def _decode_response(
    resp: requests.Response,
    content: bytes | None = None,
    fallback_encoding: str | None = None,
) -> str:
    if content is None:
        content = getattr(resp, "content", None)
    if not isinstance(content, bytes):
        return resp.text

    content_type = str(getattr(resp, "headers", {}).get("Content-Type", ""))
    charset_match = re.search(r"charset\s*=\s*['\"]?([^;'\"\s]+)", content_type, re.I)
    if charset_match:
        try:
            return content.decode(charset_match.group(1))
        except (LookupError, UnicodeDecodeError):
            pass

    if content.startswith(b"\xef\xbb\xbf"):
        return content.decode("utf-8-sig")
    try:
        return content.decode("utf-8")
    except UnicodeDecodeError:
        pass

    if fallback_encoding:
        try:
            return content.decode(fallback_encoding)
        except (LookupError, UnicodeDecodeError):
            pass

    # ``apparent_encoding`` may consume a streamed Response body, so only
    # consult it for non-streaming test doubles/legacy responses.
    if not callable(getattr(resp, "iter_content", None)):
        apparent = getattr(resp, "apparent_encoding", None)
        if isinstance(apparent, str) and apparent:
            try:
                return content.decode(apparent)
            except (LookupError, UnicodeDecodeError):
                pass
    return content.decode("utf-8", errors="replace")


def _finalize_result(
    result: NewsContent,
    *,
    response_url: str | None = None,
    canonical_url: str | None = None,
    http_status: int | None = None,
) -> NewsContent:
    final_url = response_url or result.url
    resolved_canonical = canonical_url or result.canonical_url or response_url
    return replace(
        result,
        source_domain=source_domain_from_url(final_url),
        canonical_url=resolved_canonical,
        http_status=http_status if http_status is not None else result.http_status,
    )


def _call_handler(handler: Callable[..., NewsContent], url: str, html: str) -> NewsContent:
    """Invoke current two-argument handlers without masking internal TypeErrors."""
    try:
        signature = inspect.signature(handler)
    except (TypeError, ValueError):
        return handler(url, html)

    try:
        signature.bind(url, html)
    except TypeError:
        signature.bind(url)
        return handler(url)
    return handler(url, html)


# --- Handler registry ---


class NewsContentExtractor:
    """URL -> NewsContent. Public entry point: ``extract(url)``."""

    _domain_handlers: dict[str, Callable[..., NewsContent]] = {}

    @classmethod
    def register_domain_handler(cls, domain: str, handler: Callable[..., NewsContent]) -> None:
        cls._domain_handlers[domain.lower().removeprefix("www.")] = handler

    @classmethod
    def unregister_domain_handler(cls, domain: str) -> None:
        cls._domain_handlers.pop(domain.lower().removeprefix("www."), None)

    @classmethod
    def _build(
        cls,
        url: str,
        title: str | None = None,
        body: str = "",
        publish_date: str | None = None,
        author: str | None = None,
        source_domain: str = "",
        extractor: str = "default",
        content_status: ContentStatus = "ok",
        reason: str | None = None,
        canonical_url: str | None = None,
        http_status: int | None = None,
    ) -> NewsContent:
        """Convenience alias for :meth:`NewsContent._build`."""
        return NewsContent._build(
            url=url,
            title=title,
            body=body,
            publish_date=publish_date,
            author=author,
            source_domain=source_domain,
            extractor=extractor,
            content_status=content_status,
            reason=reason,
            canonical_url=canonical_url,
            http_status=http_status,
        )

    @classmethod
    def extract(cls, url: str, *, html: str | None = None) -> NewsContent:
        """Fetch and extract news content.

        URL validation and redirect-to-private checks raise ``ValueError``.
        Ordinary fetch and parse failures return a structured result.
        """
        host = _validate_url(url)
        domain = host.removeprefix("www.")
        response_url: str | None = None
        http_status: int | None = None

        if html is None:
            try:
                resp = requests.get(
                    url,
                    headers={"User-Agent": random_ua()},
                    timeout=15,
                    allow_redirects=True,
                    stream=True,
                )
            except (requests.RequestException, UnicodeError, OSError):
                return cls._build(
                    url=url,
                    extractor="none",
                    content_status="fetch_error",
                    reason="upstream request failed",
                )

            final_host = urlparse(resp.url).hostname
            if final_host and _is_private_ip(final_host):
                close = getattr(resp, "close", None)
                if callable(close):
                    close()
                raise ValueError("redirected to internal network")
            if final_host:
                domain = final_host.lower().removeprefix("www.")

            response_url = resp.url
            http_status = resp.status_code
            if http_status in (403, 429):
                close = getattr(resp, "close", None)
                if callable(close):
                    close()
                return cls._build(
                    url=url,
                    source_domain=source_domain_from_url(response_url),
                    extractor="none",
                    content_status="blocked",
                    reason=f"upstream HTTP {http_status}",
                    canonical_url=response_url,
                    http_status=http_status,
                )
            if http_status >= 400:
                close = getattr(resp, "close", None)
                if callable(close):
                    close()
                return cls._build(
                    url=url,
                    source_domain=source_domain_from_url(response_url),
                    extractor="none",
                    content_status="fetch_error",
                    reason=f"upstream HTTP {http_status}",
                    canonical_url=response_url,
                    http_status=http_status,
                )
            try:
                raw_content = _read_response_bytes(resp)
            except _ResponseTooLargeError:
                return cls._build(
                    url=url,
                    source_domain=source_domain_from_url(response_url),
                    extractor="none",
                    content_status="fetch_error",
                    reason="upstream response exceeds the 5 MiB limit",
                    canonical_url=response_url,
                    http_status=http_status,
                )
            finally:
                close = getattr(resp, "close", None)
                if callable(close):
                    close()

            try:
                fallback_encoding = "gb18030" if domain.endswith("10jqka.com.cn") else None
                html = _decode_response(resp, raw_content, fallback_encoding)
            except (UnicodeError, LookupError):
                return cls._build(
                    url=url,
                    source_domain=source_domain_from_url(response_url),
                    extractor="none",
                    content_status="fetch_error",
                    reason="response decoding failed",
                    canonical_url=response_url,
                    http_status=http_status,
                )

        handler = cls._domain_handlers.get(domain)
        if handler is None:
            result = _default_handler(url, html)
        else:
            result = _call_handler(handler, url, html)

        return _finalize_result(
            result,
            response_url=response_url,
            http_status=http_status,
        )


# --- Default handler (generic) ---


def _default_handler(url: str, html: str) -> NewsContent:
    soup = BeautifulSoup(html, "html.parser")
    title, publish_date, author, canonical_url = _extract_metadata(soup)

    if _looks_blocked(soup):
        return NewsContent._build(
            url=url,
            title=title,
            publish_date=publish_date,
            author=author,
            extractor="generic",
            content_status="blocked",
            reason="page contains an access challenge",
            canonical_url=canonical_url,
        )

    if _looks_like_js_shell(html, soup):
        noscript_body = _noscript_body(soup)
        if len(noscript_body) >= 40:
            return NewsContent._build(
                url=url,
                title=title,
                body=noscript_body,
                publish_date=publish_date,
                author=author,
                extractor="generic_noscript",
                canonical_url=canonical_url,
            )
        return NewsContent._build(
            url=url,
            title=title,
            publish_date=publish_date,
            author=author,
            extractor="generic",
            content_status="javascript_required",
            reason="page requires client-side rendering",
            canonical_url=canonical_url,
        )

    candidates: list[tuple[Tag, str, int, float]] = []
    for node in _collect_candidates(soup, _GENERIC_SELECTORS):
        text, paragraphs, link_ratio = _candidate_text(node)
        if text and link_ratio <= 0.6:
            candidates.append((node, text, paragraphs, link_ratio))

    if not candidates:
        return NewsContent._build(
            url=url,
            title=title,
            publish_date=publish_date,
            author=author,
            extractor="generic",
            content_status="unsupported",
            reason="no supported article container",
            canonical_url=canonical_url,
        )

    node, body, paragraph_count, _link_ratio = max(candidates, key=lambda item: len(item[1]))
    if len(body) < 80 and (paragraph_count < 2 or len(body) < 40):
        return NewsContent._build(
            url=url,
            title=title,
            publish_date=publish_date,
            author=author,
            extractor="generic",
            content_status="empty",
            reason="cleaned body is below the generic length threshold",
            canonical_url=canonical_url,
        )

    if node.name == "article":
        extractor = "generic_article"
    elif node.name == "main":
        extractor = "generic_main"
    else:
        extractor = "generic_content"

    return NewsContent._build(
        url=url,
        title=title,
        body=body,
        publish_date=publish_date,
        author=author,
        extractor=extractor,
        canonical_url=canonical_url,
    )


_THS_BODY_SELECTORS = (
    ".article-detail",
    ".article-content",
    ".news-content",
    ".txt",
    "article",
    "main",
)


def _ths_news_handler(url: str, html: str) -> NewsContent:
    """Extract THS news pages from their article-detail style containers."""
    soup = BeautifulSoup(html, "html.parser")
    title, publish_date, author, canonical_url = _extract_metadata(soup)

    if _looks_blocked(soup):
        return NewsContent._build(
            url=url,
            title=title,
            publish_date=publish_date,
            author=author,
            extractor="ths_news_v1",
            content_status="blocked",
            reason="page contains an access challenge",
            canonical_url=canonical_url,
        )

    if _looks_like_js_shell(html, soup):
        noscript_body = _noscript_body(soup)
        if len(noscript_body) >= 40:
            return NewsContent._build(
                url=url,
                title=title,
                body=noscript_body,
                publish_date=publish_date,
                author=author,
                extractor="ths_news_v1_noscript",
                canonical_url=canonical_url,
            )
        return NewsContent._build(
            url=url,
            title=title,
            publish_date=publish_date,
            author=author,
            extractor="ths_news_v1",
            content_status="javascript_required",
            reason="page requires client-side rendering",
            canonical_url=canonical_url,
        )

    selected_body = ""
    for selector in _THS_BODY_SELECTORS:
        for node in soup.select(selector):
            text, _paragraphs, link_ratio = _candidate_text(node)
            if text and link_ratio <= 0.6:
                selected_body = text
                break
        if selected_body:
            break

    if not selected_body:
        return NewsContent._build(
            url=url,
            title=title,
            publish_date=publish_date,
            author=author,
            extractor="ths_news_v1",
            content_status="unsupported",
            reason="no supported THS article container",
            canonical_url=canonical_url,
        )

    if len(selected_body) < 20:
        return NewsContent._build(
            url=url,
            title=title,
            publish_date=publish_date,
            author=author,
            extractor="ths_news_v1",
            content_status="empty",
            reason="cleaned THS body is too short",
            canonical_url=canonical_url,
        )

    return NewsContent._build(
        url=url,
        title=title,
        body=selected_body,
        publish_date=publish_date,
        author=author,
        extractor="ths_news_v1",
        canonical_url=canonical_url,
    )


# --- EastMoney domain handler ---


def _eastmoney_handler(url: str, html: str) -> NewsContent:
    """finance.eastmoney.com / stock.eastmoney.com article handler."""
    soup = BeautifulSoup(html, "html.parser")
    meta_title, meta_date, meta_author, canonical_url = _extract_metadata(soup)

    topbox = soup.select_one("div.topbox")
    title = meta_title
    publish_date = meta_date
    author = meta_author
    if topbox:
        lines = [ln.strip() for ln in topbox.get_text("\n").split("\n") if ln.strip()]
        if lines:
            title = lines[0]
        for line in lines[1:]:
            match = re.match(
                r"(\d{4})年(\d{1,2})月(\d{1,2})日\s+(\d{1,2}:\d{2})\s*来源[:：]\s*(.*)",
                line,
            )
            if match:
                year, month, day, _hm, source = match.groups()
                publish_date = f"{year}-{int(month):02d}-{int(day):02d}"
                author = source.strip() or None
                break

    body_paras: list[str] = []
    contentbox = soup.select_one("div.contentbox")
    if contentbox:
        for paragraph in contentbox.select("p"):
            text = paragraph.get_text().strip()
            if not text:
                continue
            if any(keyword in text for keyword in _EM_AD_KEYWORDS):
                continue
            if any(keyword in text for keyword in _EM_BODY_STOP_KEYWORDS):
                break
            body_paras.append(text)

    body = "\n\n".join(body_paras)
    if not body:
        fallback_selectors = ("article", ".article-content", ".article-body", "#ContentBody")
        fallback_candidates = []
        for node in _collect_candidates(soup, fallback_selectors):
            text, _paragraphs, link_ratio = _candidate_text(node)
            if text and link_ratio <= 0.6:
                fallback_candidates.append(text)
        body = max(fallback_candidates, key=len, default="")

    if len(body.encode("utf-8")) < 100:
        return NewsContent._build(
            url=url,
            title=title,
            publish_date=publish_date,
            author=author,
            extractor="eastmoney_v1",
            content_status="empty",
            reason="cleaned body is below the EastMoney length threshold",
            canonical_url=canonical_url,
        )

    return NewsContent._build(
        url=url,
        title=title,
        body=body,
        publish_date=publish_date,
        author=author,
        extractor="eastmoney_v1",
        canonical_url=canonical_url,
    )


def _eastmoney_notice_handler(url: str, html: str) -> NewsContent:
    """Use generic extraction for notice pages while preserving source identity."""
    result = _default_handler(url, html)
    return replace(result, extractor="eastmoney_notice")


NewsContentExtractor.register_domain_handler("finance.eastmoney.com", _eastmoney_handler)
NewsContentExtractor.register_domain_handler("stock.eastmoney.com", _eastmoney_handler)
NewsContentExtractor.register_domain_handler("data.eastmoney.com", _eastmoney_notice_handler)
NewsContentExtractor.register_domain_handler("news.10jqka.com.cn", _ths_news_handler)
