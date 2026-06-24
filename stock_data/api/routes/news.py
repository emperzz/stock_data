"""News endpoints (search / flash / content extraction).

Mounted by ``server.py`` with ``prefix="/api/v1"``; this router's own paths
start with ``/news/...`` so the final URLs are ``/api/v1/news/...``.
"""

from fastapi import APIRouter, HTTPException, Query

from ..cache import (
    cache_endpoint,
    get_news_content_cache,
    get_news_flash_cache,
    get_news_search_cache,
    make_news_content_cache_key,
    make_news_flash_cache_key,
    make_news_search_cache_key,
)
from ..endpoint_meta import endpoint_meta
from ..schemas import (
    ErrorResponse,
    FlashNewsItem,
    FlashNewsResponse,
    NewsContentResponse,
    NewsItem,
    NewsSearchResponse,
)
from .errors import map_errors
from .helpers import get_manager

news_router = APIRouter()


@news_router.get(
    "/news/search",
    response_model=NewsSearchResponse,
    responses={
        400: {"model": ErrorResponse, "description": "Invalid request"},
        502: {"model": ErrorResponse, "description": "All fetchers failed"},
    },
    tags=["news"],
)
@endpoint_meta(
    summary="新闻搜索（关键词 / 股票代码 / 主题）",
    markets=["csi"],
    capabilities=["NEWS_SEARCH"],
)
@map_errors
@cache_endpoint(
    cache_fn=lambda *args, **kwargs: get_news_search_cache(),
    key_builder=lambda q, from_, to, limit: make_news_search_cache_key(q, from_, to, limit),
    hit_label="news_search",
)
def search_news(
    q: str = Query(min_length=1, max_length=200, description="搜索词"),
    from_: str | None = Query(default=None, alias="from", description="起始日期 YYYY-MM-DD"),
    to: str | None = Query(default=None, description="结束日期 YYYY-MM-DD"),
    limit: int = Query(default=20, ge=1, le=100, description="结果数上限 1-100"),
) -> NewsSearchResponse:
    """Search news via NEWS_SEARCH-capable fetchers."""
    if from_ and to and from_ > to:
        raise HTTPException(status_code=400, detail="from must be <= to")

    manager = get_manager()
    items, source = manager.search_news(q=q, from_date=from_, to_date=to, limit=limit)

    return NewsSearchResponse(
        data=[NewsItem(**it) for it in items],
        total=len(items),
        limit=limit,
        query=q,
        source=source,
    )


@news_router.get(
    "/news/flash",
    response_model=FlashNewsResponse,
    responses={
        400: {"model": ErrorResponse, "description": "Invalid limit"},
        502: {"model": ErrorResponse, "description": "All fetchers failed"},
    },
    tags=["news"],
)
@endpoint_meta(
    summary="全球财经快讯（7×24 实时推送）",
    markets=["csi"],
    capabilities=["NEWS_FLASH"],
)
@map_errors
@cache_endpoint(
    cache_fn=lambda *args, **kwargs: get_news_flash_cache(),
    key_builder=lambda limit: make_news_flash_cache_key(limit),
    hit_label="news_flash",
)
def get_flash_news(
    limit: int = Query(default=50, ge=1, le=200, description="条数 1-200, 默认 50"),
) -> FlashNewsResponse:
    """全球财经快讯（东财 7x24 实时流，60s 缓存）。"""
    manager = get_manager()
    items, source = manager.get_flash_news(limit=limit)

    return FlashNewsResponse(
        data=[FlashNewsItem(**it) for it in items],
        total=len(items),
        limit=limit,
        source=source,
    )


@news_router.get(
    "/news/content",
    response_model=NewsContentResponse,
    responses={
        400: {"model": ErrorResponse, "description": "Invalid URL or SSRF rejection"},
        502: {"model": ErrorResponse, "description": "Extraction failed"},
    },
    tags=["news"],
)
@endpoint_meta(
    summary="新闻正文提取（给定 URL 抓取详情页）",
    # URL 提取器本身不限市场;声明三个真实市场而非 "global",
    # 否则 UI 的 market 过滤(默认 ["csi","hk","us"])会把它隐藏掉
    markets=["csi", "hk", "us"],
    capabilities=[],
)
@map_errors
@cache_endpoint(
    cache_fn=lambda *args, **kwargs: get_news_content_cache(),
    key_builder=lambda url: make_news_content_cache_key(url),
    hit_label="news_content",
)
def get_news_content(
    url: str = Query(min_length=1, description="新闻详情页 URL"),
) -> NewsContentResponse:
    """Fetch and extract news content from a URL."""
    from stock_data.data_provider.utils.news_extractor import (
        NewsContent,
        NewsContentExtractor,
    )

    result = NewsContentExtractor.extract(url)

    # The extractor returns a NewsContent dataclass in production; tests may
    # mock it with a plain dict. Coerce dicts to the dataclass so the rest of
    # the handler can use attribute access uniformly.
    if isinstance(result, dict):
        result = NewsContent(
            url=result.get("url", url),
            title=result.get("title"),
            body=result.get("body", ""),
            publish_date=result.get("publish_date"),
            author=result.get("author"),
            source_domain=result.get("source_domain", ""),
            extractor=result.get("extractor", "default"),
            byte_size=result.get("byte_size", 0),
        )

    return NewsContentResponse(
        url=result.url,
        title=result.title,
        body=result.body,
        publish_date=result.publish_date,
        author=result.author,
        source_domain=result.source_domain,
        extractor=result.extractor,
        byte_size=result.byte_size,
    )
