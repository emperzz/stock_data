"""
News content extractor: given a URL, fetch and extract the article body.

The default handler is a generic HTML scraper (find <article>, <div class=content>,
<main>). Source-specific handlers can be registered per domain via
register_domain_handler() — see _EM_HANDLER for the finance.eastmoney.com case
verified during spec validation.
"""
import ipaddress
import logging
import re
import socket
from dataclasses import dataclass
from typing import Callable
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

_EM_BODY_STOP_KEYWORDS = ("文章来源", "责任编辑", "郑重声明", "网友评论")
_EM_AD_KEYWORDS = ("看资讯行情", "选东方财富证券")
_EM_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)


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
    ) -> "NewsContent":
        return cls(
            url=url,
            title=title,
            body=body,
            publish_date=publish_date,
            author=author,
            source_domain=source_domain or urlparse(url).netloc,
            extractor=extractor,
            byte_size=len(body.encode("utf-8")),
        )


# --- SSRF protection ---

_PRIVATE_IP_RANGES = [
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("0.0.0.0/8"),
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("fc00::/7"),
]


def _is_private_ip(host: str) -> bool:
    """Resolve host to IP and check if it's a private/loopback address."""
    try:
        # If `host` is already an IP, ip_address() parses it directly
        try:
            ip = ipaddress.ip_address(host)
        except ValueError:
            ip = ipaddress.ip_address(socket.gethostbyname(host))
        return any(ip in net for net in _PRIVATE_IP_RANGES)
    except (socket.gaierror, ValueError):
        # If DNS fails, fail closed: treat as private (reject)
        return True


def _validate_url(url: str) -> str:
    """Validate URL is http(s) and points to a non-private host.

    Returns the netloc (host) on success; raises ValueError on rejection.
    """
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise ValueError(f"url must be http or https (got {parsed.scheme!r})")
    host = parsed.hostname  # already strips port + lowercases
    if not host:
        raise ValueError("url has no host")
    if host.lower() in ("localhost",):
        raise ValueError("url points to internal network (localhost)")
    if _is_private_ip(host):
        raise ValueError("url points to internal network (private IP)")
    return host


# --- Handler registry ---

class NewsContentExtractor:
    """URL -> NewsContent. Public entry point: ``extract(url)``."""

    _domain_handlers: dict[str, Callable[[str], NewsContent]] = {}

    @classmethod
    def register_domain_handler(
        cls, domain: str, handler: Callable[[str], NewsContent]
    ) -> None:
        cls._domain_handlers[domain] = handler

    @classmethod
    def unregister_domain_handler(cls, domain: str) -> None:
        cls._domain_handlers.pop(domain, None)

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
    ) -> "NewsContent":
        """Convenience alias for :meth:`NewsContent._build`."""
        return NewsContent._build(
            url=url,
            title=title,
            body=body,
            publish_date=publish_date,
            author=author,
            source_domain=source_domain,
            extractor=extractor,
        )

    @classmethod
    def extract(cls, url: str, *, html: str | None = None) -> NewsContent:
        """Fetch and extract news content. If ``html`` is given, skip fetching.

        Raises ValueError on SSRF, protocol errors, or content extraction failure.
        """
        host = _validate_url(url)
        domain = host.lstrip("www.")

        if html is None:
            try:
                resp = requests.get(
                    url,
                    headers={"User-Agent": _EM_USER_AGENT},
                    timeout=15,
                    allow_redirects=True,
                )
            except requests.RequestException as e:
                raise ValueError(f"fetch timeout or network error for {url}: {e}") from e
            # Re-validate after redirects (DNS rebinding defense)
            final_host = urlparse(resp.url).hostname
            if final_host and _is_private_ip(final_host):
                raise ValueError("redirected to internal network")
            html = resp.text

        handler = cls._domain_handlers.get(domain) or cls._domain_handlers.get(
            "www." + domain
        )
        if handler is None:
            return _default_handler(url, html)
        # Support both (url, html) and (url,) handler signatures.
        try:
            return handler(url, html)
        except TypeError:
            return handler(url)


# --- Default handler (generic) ---


def _default_handler(url: str, html: str) -> NewsContent:
    soup = BeautifulSoup(html, "html.parser")

    # Strip noise
    for tag in soup(["script", "style", "nav", "aside", "header", "footer", "iframe"]):
        tag.decompose()

    # Pick main container in priority order
    main = (
        soup.find("article")
        or soup.select_one("div.content, div#content, div.article-content, div.article-body")
        or soup.find("main")
    )

    if main is None:
        # Last resort: use body, but mark as loose
        main = soup.body or soup

    body = main.get_text(separator="\n", strip=True)

    if len(body.encode("utf-8")) < 10:
        raise ValueError("could not extract main content (body too short)")

    # Title: og:title > <title>
    title = None
    og = soup.find("meta", attrs={"property": "og:title"})
    if og and og.get("content"):
        title = og["content"].strip()
    elif soup.title:
        title = soup.title.get_text().strip()

    # Publish date: og:article:published_time > guess
    pub = None
    pub_meta = soup.find("meta", attrs={"property": "article:published_time"})
    if pub_meta and pub_meta.get("content"):
        pub = pub_meta["content"][:10]

    return NewsContent._build(
        url=url,
        title=title,
        body=body,
        publish_date=pub,
        extractor="default",
    )


# --- Eastmoney domain handler ---

def _eastmoney_handler(url: str, html: str) -> NewsContent:
    """finance.eastmoney.com / stock.eastmoney.com: .topbox + .contentbox structure."""
    soup = BeautifulSoup(html, "html.parser")

    # Title + publish date + author from .topbox
    topbox = soup.select_one("div.topbox")
    title = None
    publish_date = None
    author = None
    if topbox:
        lines = [ln.strip() for ln in topbox.get_text("\n").split("\n") if ln.strip()]
        if lines:
            title = lines[0]
        for line in lines[1:]:
            m = re.match(
                r"(\d{4})年(\d{1,2})月(\d{1,2})日\s+(\d{1,2}:\d{2})\s*来源[:：]\s*(.*)",
                line,
            )
            if m:
                y, mo, d, _hm, src = m.groups()
                publish_date = f"{y}-{int(mo):02d}-{int(d):02d}"
                author = src.strip() or None
                break

    # Body from .contentbox paragraphs
    body_paras: list[str] = []
    contentbox = soup.select_one("div.contentbox")
    if contentbox:
        for p in contentbox.select("p"):
            text = p.get_text().strip()
            if not text:
                continue
            # Skip promotional first paragraph
            if any(kw in text for kw in _EM_AD_KEYWORDS):
                continue
            # Stop at meta/footer markers
            if any(kw in text for kw in _EM_BODY_STOP_KEYWORDS):
                break
            body_paras.append(text)

    body = "\n\n".join(body_paras)

    if len(body.encode("utf-8")) < 100:
        raise ValueError("could not extract main content (body too short)")

    return NewsContent._build(
        url=url,
        title=title,
        body=body,
        publish_date=publish_date,
        author=author,
        extractor="eastmoney_v1",
    )


# Register eastmoney domains on import
NewsContentExtractor.register_domain_handler("finance.eastmoney.com", _eastmoney_handler)
NewsContentExtractor.register_domain_handler("stock.eastmoney.com", _eastmoney_handler)
