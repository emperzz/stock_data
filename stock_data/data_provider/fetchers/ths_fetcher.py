"""
同花顺 HTTP API fetcher for signal layer data.

Provides: 热点题材(hot-topics), 北向资金(north-flow), 全球财经快讯(news-flash),
          新闻搜索(news-search), 板块 K 线(board-history),
          个股新闻(stock-news), 个股公告(announcements)

APIs:
- 热点: zx.10jqka.com.cn/event/api/getharden/
- 北向: data.hexin.cn/market/hsgtApi/method/dayChart/
- 快讯: news.10jqka.com.cn/tapp/news/push/stock  (pageSize 硬编码 20/页, 内部翻页)
- 搜索: www.iwencai.com/gateway/mobilesearch/comprehensive/search  (问财聚合搜索)
- 板块 K 线:
    - 概念(CID → platecode): q.10jqka.com.cn/gn/detail/code/{cid}/  →  platecode
    - 行业(直查):            q.10jqka.com.cn/thshy/detail/code/{platecode}/  →
                              platecode 与 URL slug 相同 (881xxx)
    - 通用 K 线: d.10jqka.com.cn/v4/line/bk_{platecode}/{freq_segment}/{year}.js

Naming note (post-2026-07-14 cleanup): the upstream HTML element
``<input id="clid">`` on the concept detail page returns a 6-digit
**platecode** (e.g. ``"886042"``), NOT a T-prefixed clid. The HTML
attribute name is a historical artifact that we preserve verbatim but
**the variable / function naming in this module treats the value as a
platecode**. Historical references to "T000267467"-style clids in older
docs/comments were placeholders for that era's naming and are no longer
accurate — they should not appear in new code.

板块 K 线支持的频率(`_THS_BOARD_FREQ_MAP`,按 upstream 实测 2026-07-14):
  d   → seg=01  日线     (YYYYMMDD 日期)
  w   → seg=02  周线     (YYYYMMDD 日期,周五锚定)
  m   → seg=10  月线     (YYYYMMDD 日期)
  5m  → seg=30  5分钟    (YYYYMMDDHHMM 日期)
  15m → seg=50  15分钟   (YYYYMMDDHHMM 日期)
  30m → seg=60  30分钟   (YYYYMMDDHHMM 日期)
  60m → seg=70  60分钟   (YYYYMMDDHHMM 日期,15:00 收盘时点)

akshare 仅硬编码 seg=01(日线),所以 THS 周线/月线/分钟线从未被公开 — 但
upstream 真实支持所有 7 种频率,本 fetcher 现已覆盖。

注意: 新闻搜索走的是同花顺问财 iWenCai (www.iwencai.com), 不是 10jqka 域名。
10jqka 财经页的站内搜索框本身就是跳转到 iWenCai 的。详见 search_news 文档。
"""

import logging
import math
import os
import random
import re
import time
from datetime import date as _date
from datetime import datetime, timedelta, timezone
from importlib import resources, util
from typing import Any

from tenacity import (
    before_sleep_log,
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

import requests

from ..base import BaseFetcher, DataCapability, DataFetchError
from ..core.types import safe_float
from ..persistence.board import THS_CONCEPT_SUBTYPE, THS_INDUSTRY_SUBTYPE
from ..utils.http import json_get, json_post, random_ua
from ..utils.normalize import normalize_stock_code
from ..utils.text import strip_em_tags
from ..utils.url_helpers import source_domain as source_domain_from_url

logger = logging.getLogger(__name__)


class ThsBoundarySignalError(DataFetchError):
    """Internal signal: 401/403 on a THS page AFTER data was received.

    Used by ``get_board_stocks``'s pagination loop to distinguish THS
    upstream's "no more data" boundary signal from a real upstream
    failure. Subclassing ``DataFetchError`` keeps the public exception
    surface unchanged — other callers that catch ``DataFetchError`` still
    see these raises; only the pagination loop looks for this specific
    subtype.

    ``status_code`` is the HTTP status (401 or 403) that triggered the
    raise, preserved for observability and tests.
    """

    def __init__(self, message: str, *, status_code: int) -> None:
        super().__init__(message)
        self.status_code = status_code


_BOUNDARY_TOLERATED_STATUSES: frozenset[int] = frozenset({401, 403})


def _parse_free_float(s: str | None) -> int | None:
    """Parse THS upstream large-value column → int (shares or 元).

    THS 上游对 流通股 / 流通市值 / 成交额 等大数字用 'N.NN亿' 中文单位,
    但也保留旧版 raw-integer 的 fallthrough (测试 fixture / 早期版本兼容).

    Accepted formats:
      - ``'4.73亿'``  →  ``473_000_000``  (× 1e8)
      - ``'27.16亿'`` →  ``2_716_000_000`` (× 1e8)
      - ``'100000000'`` →  ``100_000_000``  (raw integer fallthrough)

    Returns:
        int | None — None on ``'--'`` / ``'-'`` / 空字符串 / ``None`` /
        未识别格式 (上游格式变化时安全降级而非抛错). 调用方靠 schema
        Optional 接受 None.

    2026-07-13 实测上游格式稳定; regex 严格匹配 + raw fallthrough,
    未来微调时降级到 None 而不是抛 ValueError.
    """
    s = (s or "").strip().replace(",", "").replace("\xa0", "").replace("．", ".")
    if not s or s in ("--", "-"):
        return None
    m = re.match(r"^([0-9]+(?:\.[0-9]+)?)亿$", s)
    if m:
        return int(round(float(m.group(1)) * 1e8))
    # Strict integer-only fallthrough (compat with raw-integer fixture).
    if re.match(r"^\d+$", s):
        return int(s)
    return None


# ---------------------------------------------------------------------------
# v-token cache (F2 from PR2 review)
# ---------------------------------------------------------------------------
#
# THS upstream authenticates board K-line requests with a `v=` cookie
# minted by a JavaScript obfuscator bundled as `ths.js` (~40KB, 989 lines).
# We tokenize the JS once at process start (keep the V8 VM warm to avoid
# 200ms cold starts per call), then cache the produced cookie string and
# TTL-rotate it. The cache also retries on transient mint failures
# instead of caching the exception (the lru_cache(maxsize=1) trick this
# replaced pinned a single transient failure for the process lifetime).
#
# Note we DO NOT lru_cache anything — lru_cache caches exceptions too,
# turning a one-shot failure into a perma-broken fetcher.
#
# Retry uses the project-standard ``tenacity`` decorator
# (``yfinance_fetcher._fetch_raw_data`` and
# ``eastmoney._boards_mixin._fetch_one_clist_page`` follow the same
# pattern). The previous manual loop only caught ``DataFetchError``;
# tenacity's ``retry_if_exception_type(Exception)`` is broader so a
# JSError / RuntimeError from ``py_mini_racer`` is also retried (which
# is the most common transient class — see review finding #4).

_THS_V_TOKEN_MAX_RETRIES = 3
_THS_V_TOKEN_TTL_SECONDS = 1800.0  # 30 min; THS rotates rarely upstream

_ths_v_token_cache: dict[str, float | str | None] = {
    "value": None,
    "expires_at": 0.0,
}
_ths_js_vm = None  # lazily-initialized py_mini_racer.MiniRacer with ths.js loaded

# HXKline (quota-h.10jqka.com.cn) JWT cache. Discovered 2026-07-21: the JWT
# is hardcoded in the HXKline Next.js webpack chunk (currently 82-*.js). It
# rotates only when the JS bundle is rebuilt (rare). We cache for 1 day by
# default; the env override THS_HXLINE_JWT skips the cache + fetch entirely
# so operators can pin a known-good token after a chunk-hash rotation.
_ths_hxkline_jwt_cache: dict[str, Any] = {
    "value": None,
    "expires_at": 0.0,
}
_THS_HXKLINE_JWT_TTL_SECONDS = 24 * 3600
_THS_HXKLINE_JS_CHUNK_URL = (
    "https://s.thsi.cn/cd/news-p-fe-app-news-flow-home/market/"
    "_next/static/chunks/82-2aa7e9259b5193a4.js"
)
_THS_HXKLINE_HEADERS_BASE: dict[str, str] = {
    "x-auth-progid": "7047",
    "x-auth-type": "ths",
    "x-auth-version": "1.0",
    "x-auth-appname": "AINVEST",
    "source-id": "hxkline-NEWS_appNewsFlowHome_Page",
    "platform": "hxkline",
    "Referer": "https://stockpage.10jqka.com.cn/",
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/151.0.0.0 Safari/537.36"
    ),
    "content-type": "application/json",
}
_THS_HXKLINE_KLINE_URL = (
    "https://quota-h.10jqka.com.cn/fuyao/common_hq_aggr/quote/v1/single_kline"
)
# time_period enum. Verified 2026-07-21 against the stockpage network panel
# for d / w / m / min_1 / min_5 / min_15 / min_30 / min_60.
_THS_HXKLINE_PERIOD_MAP: dict[str, str] = {
    "d": "day_1",
    "w": "week_1",
    "m": "month_1",
    "1m": "min_1",   # upstream: begin_time=-N returns N bars (capped at 800)
    "5m": "min_5",
    "15m": "min_15",
    "30m": "min_30",
    "60m": "min_60",
}
# Position-to-key map for `data_fields` in the response. Stable across
# upstream variants (verified 2026-07-21 across 18 probes).
_THS_HXKLINE_FIELD_TO_KEY = {
    "1": "ts_ms",
    "7": "open",
    "8": "high",
    "9": "low",
    "11": "close",
    "13": "volume",
    "19": "amount",
}


def _load_ths_js() -> str:
    """Return the contents of the vendored ``ths.js`` blob.

    The blob lives in this fetcher's own package — see
    ``stock_data/data_provider/fetchers/ths_assets/ths.js``. We intentionally
    don't read it from akshare's package data: vendor'ing keeps the
    dependency direction between fetchers one-way (peer fetchers don't
    reach into each other's packages, see CLAUDE.md anti-patterns).
    """
    js_path = resources.files("stock_data.data_provider.fetchers.ths_assets").joinpath("ths.js")
    if not js_path.is_file():
        raise DataFetchError(
            "[ThsFetcher] ths.js not shipped in ths_assets/ — "
            "`python tools/vendor_ths_js.py` to refresh it"
        )
    return js_path.read_text(encoding="utf-8")


def _get_ths_js_vm():
    """Singleton MiniRacer VM with ths.js loaded; raises DataFetchError."""
    global _ths_js_vm
    if _ths_js_vm is not None:
        return _ths_js_vm
    try:
        import py_mini_racer
    except ImportError as e:
        raise DataFetchError(f"[ThsFetcher] board history requires py_mini_racer: {e}") from e
    vm = py_mini_racer.MiniRacer()
    vm.eval(_load_ths_js())
    _ths_js_vm = vm
    return vm


@retry(
    retry=retry_if_exception_type(Exception),  # broader than yfinance; matches eastmoney mixin
    stop=stop_after_attempt(_THS_V_TOKEN_MAX_RETRIES),
    wait=wait_exponential(multiplier=0.2, min=0.2, max=2),
    reraise=False,  # we re-raise as DataFetchError ourselves for a clear final message
    before_sleep=before_sleep_log(logger, logging.WARNING),
)
def _mint_ths_v_token_uncached() -> str:
    """Single mint attempt: load the singleton V8 VM, evaluate ``v()``.

    No caching here — the TTL is managed by ``_get_ths_v_token`` via
    ``_ths_v_token_cache``. Each call to this function pays the full
    V8 cold-start cost; the TTL ensures this only happens at most once
    every 30 min in steady state. The ``@retry`` decorator handles
    transient failures (py_mini_racer import races, JS errors) with
    exponential backoff up to ``_THS_V_TOKEN_MAX_RETRIES`` attempts.
    """
    vm = _get_ths_js_vm()
    return vm.call("v")


def _get_ths_v_token() -> str:
    """Cached v-token with TTL refresh + bounded retry on transient failure.

    Proactive 30 min TTL means a forgotten stale token recovers on its
    own at the next refresh instead of waiting for the next caller to
    hit a 403 and re-mint. Bounded retry (via ``tenacity``) handles
    transient mint errors (py_mini_racer startup races, JS errors) without
    pinning the fetcher dead.
    """
    now = time.monotonic()
    cached = _ths_v_token_cache["value"]
    # `is not None` — not truthiness. `v()` could legitimately return ""
    # upstream; truthiness would re-mint on every call (potential infinite
    # loop) and 5xx users with no v-cookie. None means "never minted".
    if cached is not None and _ths_v_token_cache["expires_at"] > now:
        return cached

    try:
        token = _mint_ths_v_token_uncached()
    except Exception as e:
        raise DataFetchError(
            f"[ThsFetcher] v-token mint failed after {_THS_V_TOKEN_MAX_RETRIES} attempts: {e}"
        ) from e
    _ths_v_token_cache["value"] = token
    _ths_v_token_cache["expires_at"] = now + _THS_V_TOKEN_TTL_SECONDS
    return token


# ---------------------------------------------------------------------------
# HXKline (quota-h.10jqka.com.cn) JWT bootstrap (post-2026-07-21)
# ---------------------------------------------------------------------------


def _mint_ths_hxkline_jwt_uncached() -> str:
    """Fetch the HXKline JS bundle and extract the embedded x-fuyao-auth JWT.

    The token is shipped as a static string in the Next.js webpack chunk so
    there's no auth handshake — but the chunk hash changes when JS is
    rebuilt, in which case this function raises ``DataFetchError`` and the
    operator must either wait for the new hash to land or pin
    ``THS_HXKLINE_JWT`` to a known-good value (see ``_get_ths_hxkline_jwt``).
    """
    resp = requests.get(_THS_HXKLINE_JS_CHUNK_URL, timeout=15)
    resp.raise_for_status()
    m = re.search(
        r'token:\s*"(eyJ[A-Za-z0-9_\-]+\.eyJ[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+)"',
        resp.text,
    )
    if not m:
        raise DataFetchError(
            f"x-fuyao-auth JWT not found in HXKline JS chunk "
            f"{_THS_HXKLINE_JS_CHUNK_URL}; the chunk hash may have rotated. "
            f"Pin THS_HXKLINE_JWT env var to a known-good value."
        )
    return m.group(1)


def _get_ths_hxkline_jwt() -> str:
    """Return a cached x-fuyao-auth JWT, refreshing on TTL expiry.

    TTL: ``_THS_HXKLINE_JWT_TTL_SECONDS`` (1 day). The token rarely rotates
    (only when the JS bundle is rebuilt); 1 day is a defensive upper bound
    that also lets a chunk-hash rotation recover within a day of occurrence.

    Override: setting ``THS_HXKLINE_JWT`` in the environment bypasses both
    the cache and the JS-bundle fetch. Use this to pin a token after the
    chunk hash rotates before the cache TTL elapses.
    """
    env_jwt = os.environ.get("THS_HXKLINE_JWT")
    if env_jwt:
        return env_jwt
    cached = _ths_hxkline_jwt_cache["value"]
    if cached is not None and _ths_hxkline_jwt_cache["expires_at"] > time.time():
        return cached
    token = _mint_ths_hxkline_jwt_uncached()
    _ths_hxkline_jwt_cache["value"] = token
    _ths_hxkline_jwt_cache["expires_at"] = time.time() + _THS_HXKLINE_JWT_TTL_SECONDS
    return token


def _compute_time_window(
    *, start_d: _date | None, end_d: _date | None, days: int,
    freq_key: str,
) -> tuple[int, int]:
    """Translate **resolved** ``(start_d, end_d)`` to upstream offsets.

    The single_kline endpoint uses negative-day offsets relative to today
    (verified against the stockpage network panel): ``-N`` means "N days
    before today"; ``0`` means "now". Upstream does NOT accept date
    strings, only these offsets.

    For minute-level frequencies, ``begin_time`` is bar count, not
    calendar days (upstream: begin_time=-N returns N bars, hard-capped
    at 800 per request). The span check
    (``(end_d - start_d).days ≤ max_span``) catches most over-cap cases,
    but misses requests where ``end_d < today`` (e.g. ``days=800,
    end_date=yesterday`` → span_days=800 OK, but begin_time = -801,
    which upstream silently returns empty for). We detect that here and
    raise so the route layer's @map_errors can turn it into a 400.

    Caller MUST have already run ``_resolve_ths_date_range`` (which applies
    the days-is-width + start_date-is-lower-bound contract). This helper is
    a pure translation step — feeding raw ``start_date`` here was the
    bug behind "5m with ``start_date=today`` returns 1 bar" (the resolver
    expanded the window to 30 days but this helper still pinned
    ``begin_time`` to ``-1``).

    Anchor is Beijing today — UTC servers risk off-by-one in the
    16:00–24:00 UTC window.
    """
    today = datetime.now(_THS_TZ).date()
    if end_d is None:
        end_d = today
    if start_d is None:
        start_d = end_d - timedelta(days=days)
    end_offset = (today - end_d).days
    end_time = -end_offset if end_offset > 0 else 0
    computed_begin_offset = max((today - start_d).days, 1)
    if freq_key in _MINUTE_FREQS and computed_begin_offset > 800:
        raise ValueError(
            f"[ThsFetcher] get_board_history: minute-level window "
            f"(begin_time=-{computed_begin_offset}) exceeds upstream's "
            f"800-bar cap for frequency={freq_key!r}. Narrow "
            f"start_date/end_date or reduce days."
        )
    begin_time = -computed_begin_offset
    return begin_time, end_time


def _fetch_ths_single_kline(
    board_code: str,
    *,
    freq_key: str,
    start_d: _date | None = None,
    end_d: _date | None = None,
    days: int = 30,
) -> list[dict]:
    """POST to ``single_kline`` and return parsed K-line rows.

    ``start_d`` / ``end_d`` are the **already-resolved** date objects from
    ``_resolve_ths_date_range`` — do not pass raw ``start_date`` / ``end_date``
    strings (the lower-bound semantics live in the resolver, not here).

    Single request — no year loop, no JS-body parsing. Returns [] on empty
    upstream payload (legit no-data); raises ``DataFetchError`` on HTTP
    errors, non-zero status_code, or 401/403 after one JWT refresh + retry
    (skipped when ``THS_HXKLINE_JWT`` env var is pinned).

    The 401/403 retry is the only failure-recovery this helper does:
    upstream JWT rotations coincide with JS-bundle chunk-hash changes, and
    we already cache the new JWT for 24h on a successful re-fetch (see
    ``_get_ths_hxkline_jwt``). After one retry we let the error propagate.
    """
    if freq_key not in _THS_HXKLINE_PERIOD_MAP:
        raise DataFetchError(
            f"[ThsFetcher] _fetch_ths_single_kline: unsupported freq_key "
            f"{freq_key!r}; supported: {sorted(_THS_HXKLINE_PERIOD_MAP)}"
        )
    time_period = _THS_HXKLINE_PERIOD_MAP[freq_key]
    headers = {**_THS_HXKLINE_HEADERS_BASE, "x-fuyao-auth": _get_ths_hxkline_jwt()}
    begin_time, end_time = _compute_time_window(
        start_d=start_d, end_d=end_d, days=days, freq_key=freq_key,
    )
    body = {
        "code_list": [{"codes": [board_code], "market": "48"}],
        "trade_class": "intraday",
        "time_period": time_period,
        "trade_date": -1,
        # Negative offsets mean "N days back" (verified against stockpage
        # network panel). Upstream doesn't accept date strings; it accepts
        # ms epoch or these negative-day offsets.
        "begin_time": begin_time,
        "end_time": end_time,  # 0 = "now"
        "adjust_type": "forward",
        "gpid": 1,
    }
    for attempt in (1, 2):
        try:
            resp = requests.post(
                _THS_HXKLINE_KLINE_URL, headers=headers, json=body, timeout=20,
            )
        except Exception as e:
            raise DataFetchError(
                f"[ThsFetcher] single_kline({board_code}, freq={freq_key}) "
                f"network failed: {e}"
            ) from e
        if resp.status_code in (401, 403):
            # When THS_HXKLINE_JWT is env-pinned, _get_ths_hxkline_jwt() returns
            # the env value without touching the cache — retrying with the
            # same stale token is a no-op. Surface a clear "your pin is
            # stale" error instead of silently looping.
            if os.environ.get("THS_HXKLINE_JWT"):
                raise DataFetchError(
                    f"[ThsFetcher] single_kline({board_code}, freq={freq_key}) "
                    f"HTTP {resp.status_code}; THS_HXKLINE_JWT env var is "
                    f"stale — refresh it to a known-good token."
                )
            if attempt == 1:
                # JWT may have rotated; invalidate cache and retry once with
                # a fresh token. The next _get_ths_hxkline_jwt() call will
                # re-mint from the JS bundle.
                _ths_hxkline_jwt_cache["value"] = None
                _ths_hxkline_jwt_cache["expires_at"] = 0.0
                headers["x-fuyao-auth"] = _get_ths_hxkline_jwt()
                logger.warning(
                    f"[ThsFetcher] single_kline {board_code} freq={freq_key} "
                    f"got HTTP {resp.status_code}; refreshing JWT and retrying once"
                )
                continue
            raise DataFetchError(
                f"[ThsFetcher] single_kline({board_code}, freq={freq_key}) "
                f"HTTP {resp.status_code} after JWT refresh — likely chunk-hash "
                f"rotation. Set THS_HXKLINE_JWT to a known-good token."
            )
        if not (200 <= resp.status_code < 300):
            raise DataFetchError(
                f"[ThsFetcher] single_kline({board_code}, freq={freq_key}) "
                f"HTTP {resp.status_code} ({len(resp.content)}B body)"
            )
        try:
            resp_body = resp.json()
        except Exception as e:
            raise DataFetchError(
                f"[ThsFetcher] single_kline({board_code}, freq={freq_key}) "
                f"response not JSON: {e}"
            ) from e
        return _parse_ths_single_kline_response(resp_body, freq_key=freq_key)
    # unreachable
    raise DataFetchError(f"[ThsFetcher] single_kline({board_code}) retry loop exited unexpectedly")


THS_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/117.0.0.0 Safari/537.36"

HSGT_HEADERS = {
    "User-Agent": THS_UA,
    "Host": "data.hexin.cn",
    "Referer": "https://data.hexin.cn/",
}


_CONCEPT_DETAIL_URL = "https://q.10jqka.com.cn/gn/detail/code/{slug}/"

# q.10jqka.com.cn AJAX board-stocks endpoint (同花顺概念/行业成分股).
# THS upstream URL: /field/<code>/order/<dir>/page/N/ajax/1/
# field/<code> 决定排序键 (199112=涨跌幅); order/<dir> 决定方向;
# 每页 10 只; ajax/1/ 强制 AJAX HTML 片段 (避免完整页面).
_BOARD_STOCKS_URL_TEMPLATE = (
    "https://q.10jqka.com.cn/gn/detail/code/{concept_id}"
    "/field/{field_code}/order/{order}/page/{page}/ajax/1/"
)
# THS 上游列代码 (从 <th a field="..."> 实测) → python attr name.
# 2026-07-13 playwright probe. 新加任何 key 需 route Literal 同步开放.
_THS_BOARD_STOCKS_SORT_FIELD_MAP: dict[str, str] = {
    "change_pct": "199112",  # 涨跌幅(%)
    "price": "10",  # 现价
    "turnover_rate": "1968584",  # 换手(%)
    "volume_ratio": "1771976",  # 量比
    "amplitude": "526792",  # 振幅(%)
    "change_amount": "264648",  # 涨跌(元)
    "change_speed": "48",  # 涨速(%)
    "amount": "19",  # 成交额(元)
    "pe_ratio": "2034120",  # 市盈率
    "float_market_cap": "3475914",  # 流通市值(元)
    "free_float_shares": "407",  # 流通股(股)
}

_STOCK_CONCEPT_LIST_URL = (
    "https://basic.10jqka.com.cn/fuyao/f10_stock_index/concept/v1/stock_concept_list"
)
# THS market_id: 17=沪市, 33=深市. BJ (4/8 prefix) 暂不映射 (上游 stock_concept_list
# 端点可能不支持北交所; 留待后续任务). 注意代码首位即可区分:
#   6/9 → 沪市;  0/3 → 深市;  4/8 → 北交所 (未映射)
_THS_MARKET_ID_MAP: dict[str, str] = {
    "6": "17",  # 沪市主板 + 科创板
    "9": "17",  # 沪市 B 股
    "0": "33",  # 深市主板 + 中小板
    "3": "33",  # 深市创业板
}

# 板块新闻 timeline — news.10jqka.com.cn/timeline_web/... (probed 2026-07-21).
# Unauthenticated JSON, cursor-paginated (offset=last publishTime), marketId=48
# for THS blocks (concept + industry both verified). Replaces the old F10-page
# scrape that hard-capped at 14 items with no summary.
_THS_TIMELINE_NEWS_URL = "https://news.10jqka.com.cn/timeline_web/web/v1/news/list"
_THS_BOARD_MARKET_ID = "48"
# THS publishTime is a UTC-epoch ms; articles are published in Beijing time.
# Parse in CST so publish_date/time don't shift a day on non-Asia/Shanghai
# servers (same fix as ClsFetcher._CLS_TZ).
_THS_TZ = timezone(timedelta(hours=8))

# 个股新闻 / 个股公告 — basic.10jqka.com.cn/fuyao/info/company/v1/...
_THS_NEWS_URL = "https://basic.10jqka.com.cn/fuyao/info/company/v1/news"
_THS_NOTICE_URL = "https://basic.10jqka.com.cn/basicapi/notice/pub"
_THS_BASIC_HEADERS = {
    "User-Agent": THS_UA,
    "Referer": "https://basic.10jqka.com.cn/astockpc/astockmain/index.html",
}



# THS F10 板块基本资料页 — server-render 一次性给"成分股全表 + 板块新闻 + 炒作周期"
# 三段(详见 spec 2026-07-20 §3.2.1)。Marketid 直写 /48/ 对应 concept 板;
# industry F10 (/47/) 未实测,违背 upstream-probe-success-case,留到 probe 后再加。
# Keyed by `board_code` (the public THS platecode) — same identifier that
# /boards/{board_code}/stocks accepts.
_THS_F10_BOARD_URL = "https://basic.10jqka.com.cn/48/{board_code}/"

# Module-level short TTL HTML cache for the F10 page. Three sections
# (stocks / news / surges) all read the same URL; caching the HTML
# prevents the route layer from triggering 3 separate upstream GETs
# when a client hits all three endpoints in one window. The route-layer
# @cache_endpoint (30min TTL) and the persistence layer's staleness
# logic are unchanged — this cache is purely a same-process de-duper.
_F10_HTML_TTL_SECONDS: float = 45.0
_f10_html_cache: dict[str, tuple[str, float]] = {}

# Public: maps user-facing frequency string to internal upstream segment.
# Values are read by ``_fetch_ths_board_year`` which interpolates them
# into the URL template; callers should NOT use the integer values
# directly. The string keys (``d`` / ``w`` / ``m`` / ``5m`` / ``15m`` /
# ``30m`` / ``60m``) are the contract with the API layer.
#
# akshare 硬编码 seg=01,从未公开过其他频率 — 但 upstream 真实支持全部 7 种
# (verified 2026-07-14, see _ThsFreqSegment docstring).

# Canonical human-readable label for each frequency. Used in error
# messages and the explorer's manifest; NOT serialized into the API
# response (the user-facing ``period`` field on the response is the
# request's frequency string, e.g. ``"w"`` not ``"weekly"`` — keeps
# the response terse and round-trippable).

# Frequencies whose bars carry a "HH:MM" time suffix in their
# normalized date string. Daily/weekly/monthly emit "YYYY-MM-DD";
# minute-level emit "YYYY-MM-DD HH:MM". Used in
# :meth:`get_board_history` to construct the inclusive end-date bound
# — minute-level needs the " 23:59" tail or the last bar of the day
# would be cut off; daily/weekly/monthly don't need it. Explicit
# set (NOT a substring check) so monthly (key "m", which also ends
# in "m") is not silently over-applied.
# Per-frequency max history span (days) for the single_kline endpoint.
# Daily/weekly/monthly keep the 10-year ceiling (single request returns
# up to ~10 years of bars). Minute-level frequencies are bounded by
# upstream's per-request bar-count cap.
#
# Upstream semantics for ALL minute-level: ``begin_time=-N`` returns
# exactly N bars (capped at 800 total per request — verified 2026-07-22
# against the stockpage network panel for min_1/min_5/min_15/min_30/
# min_60; requests with begin_time < -800 return ``quote_data: []``).
# So ``days`` for any minute frequency is effectively "bar count up to
# 800", not calendar days. All minute-level caps below are 800 to match
# upstream; the legacy per-frequency day caps (5m=30, 15m=60, 30m=90,
# 60m=180) were under-tight (rejected valid requests, e.g. 5m days=50
# was 400 even though upstream would happily return 50 bars) and are
# unified here.
_THS_HXKLINE_MAX_SPAN_DAYS: dict[str, int] = {
    "d": 365 * 10,
    "w": 365 * 10,
    "m": 365 * 10,
    "1m": 800,
    "5m": 800,
    "15m": 800,
    "30m": 800,
    "60m": 800,
}


def _resolve_ths_date_range(
    start_date: str | None,
    end_date: str | None,
    days: int,
) -> tuple[_date, _date]:
    """Resolve and validate ``(start_date, end_date, days)`` to a date range.

    ``days`` is the **default** window width. ``start_date`` only extends
    the window further back — when given, the window becomes
    ``[min(start_date, end_d - days), end_d]``. This way ``start_date=today``
    is effectively a no-op (caller probably meant "give me the default
    days-back window") rather than collapsing the window to 1 day, while
    ``start_date=2020-01-01`` still honors the longer history request.

    If the resolved window exceeds the per-frequency max span, the
    fetcher's own ``_THS_HXKLINE_MAX_SPAN_DAYS`` check raises a
    ``ValueError`` → 400 with a clear message.

    ``end_date`` is the upper bound; defaults to Beijing today. Both bounds
    are stripped before parsing so user-supplied whitespace
    (e.g. ``" 2026-01-01 "``) is accepted, matching EastMoney's behavior.

    Raises:
        ValueError: a non-empty bound fails YYYY-MM-DD parsing, or
            ``start_d > end_d`` (caller passed ``start_date > end_date``).
            The route layer's ``@map_errors`` maps ``ValueError → 400``.
    """
    try:
        end_d = (
            datetime.strptime((end_date or "").strip(), "%Y-%m-%d").date()
            if end_date
            else datetime.now(_THS_TZ).date()
        )
    except (TypeError, ValueError) as exc:
        raise ValueError(
            f"[ThsFetcher] get_board_history: end_date={end_date!r} not YYYY-MM-DD"
        ) from exc
    start_d_default = end_d - timedelta(days=days)
    start_hint: _date | None = None
    if start_date:
        try:
            start_hint = datetime.strptime(start_date.strip(), "%Y-%m-%d").date()
        except (TypeError, ValueError) as exc:
            raise ValueError(
                f"[ThsFetcher] get_board_history: start_date={start_date!r} not YYYY-MM-DD"
            ) from exc
        # Earliest of (hint, days-based default): if hint is older than the
        # default, honor it; if hint is more recent (e.g. user passed
        # ``start_date=today``), use the default so `days` doesn't get
        # silently overridden.
        start_d = min(start_hint, start_d_default)
    else:
        start_d = start_d_default
    # Reversed-bounds guard: when the user gave an explicit `start_date`,
    # compare the hint (not the clamped start_d) so a contradictory
    # `start_date > end_date` is still surfaced as a 400 instead of being
    # silently widened by the min() above. Without `start_date`, the
    # default `start_d = end_d - days` is always ≤ end_d (route enforces
    # `days >= 1`), so no second guard is needed.
    if start_hint is not None and start_hint > end_d:
        raise ValueError(
            f"[ThsFetcher] get_board_history: start_date {start_date!r} > end_date {end_date!r}"
        )
    return start_d, end_d


# Frequencies whose bars carry a "HH:MM" suffix in their normalized date string.
# Mirrors the same set in the legacy implementation; kept as a module-level
# constant so the parser and the date-range filter agree.
_MINUTE_FREQS: frozenset[str] = frozenset({"1m", "5m", "15m", "30m", "60m"})


def _parse_ths_single_kline_response(body: dict, freq_key: str) -> list[dict]:
    """Parse a `quota-h.10jqka.com.cn/.../single_kline` JSON response.

    Response shape (verified 2026-07-21, 21 probes):
        {"status_code": 0,
         "data": {"quote_data": [{
             "market": "48", "code": "<board_code>",
             "data_fields": ["1","7","8","9","11","13","19"],
             "value": [[ts_ms, open, high, low, close, volume, amount], ...]
         }], "fail_params": None},
         "status_msg": "ok"}

    Returns canonical row dicts: date, open, high, low, close, volume, amount, frequency.
    Date normalization matches the legacy implementation so the route-layer
    date filter is identical:
        daily / weekly / monthly  → "YYYY-MM-DD"
        minute-level (1m/5m/15m/30m/60m) → "YYYY-MM-DD HH:MM"

    Raises ``DataFetchError`` when ``status_code != 0`` (upstream auth
    failure or unknown time_period enum — see Task 3 for 401/403 retry).
    Returns ``[]`` when ``quote_data`` is empty (legit no-data, distinct
    from the legacy "all years empty" gate which surfaced 503).
    """
    status = body.get("status_code")
    if status != 0:
        raise DataFetchError(
            f"[ThsFetcher] single_kline returned status_code={status} "
            f"msg={body.get('status_msg')!r}; the JWT may have rotated or "
            f"the time_period enum may be wrong"
        )
    quote_data = (body.get("data") or {}).get("quote_data") or []
    if not quote_data:
        return []
    row0 = quote_data[0]
    values = row0.get("value") or []
    # Verify data_fields shape (defensive — if upstream adds/reorders fields,
    # we'd silently misalign. Probe 21 cases all returned the same 7 fields).
    fields = row0.get("data_fields") or []
    expected = list(_THS_HXKLINE_FIELD_TO_KEY.keys())
    if fields != expected:
        raise DataFetchError(
            f"[ThsFetcher] single_kline data_fields={fields!r} != expected {expected!r}; "
            f"upstream schema may have changed"
        )
    use_hhmm = freq_key in _MINUTE_FREQS
    out: list[dict] = []
    for row in values:
        try:
            ts_ms = int(row[0])
            # Beijing time (matches legacy implementation's `_THS_TZ`).
            dt = datetime.fromtimestamp(ts_ms / 1000, _THS_TZ)
            date_str = dt.strftime("%Y-%m-%d %H:%M") if use_hhmm else dt.strftime("%Y-%m-%d")
            out.append({
                "date": date_str,
                "open": float(row[1]),
                "high": float(row[2]),
                "low": float(row[3]),
                "close": float(row[4]),
                "volume": int(float(row[5])),
                "amount": float(row[6]),
                "frequency": freq_key,
            })
        except (TypeError, ValueError, IndexError):
            continue
    return out


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
        | DataCapability.STOCK_NEWS  # 新: 个股新闻 basic.10jqka.com.cn
        | DataCapability.ANNOUNCEMENT  # 新: 个股公告 basic.10jqka.com.cn
        # 新 (2026-07-20 spec): F10 page sections
        | DataCapability.BOARD_NEWS     # 板块热点新闻
        | DataCapability.BOARD_SURGES   # 板块炒作周期
    )

    @staticmethod
    def _check_ths_deps() -> tuple[bool, str | None]:
        """Single source of truth for THS board-K-line dependency status.

        Returns ``(is_available, reason_if_not)``. Used by both
        :meth:`is_available` and :meth:`unavailable_reason` so the two
        methods cannot drift. Mirrors the pattern in ``yfinance_fetcher``
        / ``eastmoney._boards_mixin`` where availability is a single
        tuple-returning helper.

        Probes:
        - ``py_mini_racer`` (V8 isolate for ``ths.js`` evaluation)
        - ``bs4`` (BeautifulSoup for HTML page parsing — board index /
          F10 / news pages)
        - ``ths_assets/ths.js`` (vendored JS blob)

        Hot-topics / north-flow / flash-news / news-search don't need
        any of these (pure HTTP), but by project convention
        (``data_provider/manager.py:1002``) an unavailable fetcher is
        dropped from the manager's table — meaning a missing dep costs
        all four pure-HTTP endpoints too. This is a deliberate
        trade-off; see :meth:`is_available` docstring.
        """
        missing: list[str] = []
        for mod in ("py_mini_racer", "bs4"):
            if util.find_spec(mod) is None:
                missing.append(mod)
        if missing:
            return False, (
                f"{ThsFetcher.name}.board_history unavailable: "
                f"missing deps {sorted(missing)} "
                f"(pip install py-mini-racer beautifulsoup4)"
            )
        try:
            js_path = resources.files("stock_data.data_provider.fetchers.ths_assets").joinpath(
                "ths.js"
            )
            if not js_path.is_file():
                return False, (
                    f"{ThsFetcher.name}.board_history unavailable: "
                    f"ths.js missing from ths_assets/ "
                    f"(run tools/vendor_ths_js.py)"
                )
        except (FileNotFoundError, ModuleNotFoundError):
            return False, (
                f"{ThsFetcher.name}.board_history unavailable: "
                f"ths.js missing or ths_assets/ unreadable "
                f"(run tools/vendor_ths_js.py)"
            )
        return True, None

    def is_available(self) -> bool:
        """True only when board-K-line deps are present.

        Returns ``self._check_ths_deps()[0]``. Six pure-HTTP THS
        endpoints (hot-topics / north-flow / flash-news / news-search
        / stock-news / announcements) don't need ``py_mini_racer`` /
        ``bs4`` or the vendored ``ths.js``, but by
        project convention (``data_provider/manager.py:1002``) an
        unavailable fetcher is dropped from the manager's table —
        a missing dep costs all six pure-HTTP endpoints too.

        **Accepted trade-off:** one ``ths.js`` / V8 / bs4 outage
        takes down the entire fetcher (not just the K-line endpoint).
        In our threat model — a single deps env per server, not a
        multi-tenant fleet — this is acceptable. Per-capability
        availability gating would require a ``(capability -> deps)``
        map in :meth:`_check_ths_deps` plus a manager-side
        ``is_available_for(capability)`` lookup; tracked as tech
        debt, deferred.
        """
        return self._check_ths_deps()[0]

    def unavailable_reason(self) -> str | None:
        """Specific reason string when board K-line path is unavailable."""
        available, reason = self._check_ths_deps()
        if available:
            return None
        return reason

    def _normalize_data(self, df, stock_code):
        raise DataFetchError("ThsFetcher does not support historical K-line data")

    # ------------------------------------------------------------------
    # v-token (cookie auth for board K-line; same mechanism as akshare uses)
    # ------------------------------------------------------------------

    def _v_token(self) -> str:
        """Instance accessor for the cached v token (for class-method ergonomics)."""
        return _get_ths_v_token()

    @staticmethod
    def _http_get(url: str, *, headers: dict | None = None, timeout: int = 10):
        """Raw HTTP GET returning the response object (not parsed).

        Uses requests (not curl_cffi) — d.10jqka.com.cn / q.10jqka.com.cn don't
        fingerprint-block. Reuses the project's requests default (no proxy).

        UA rotation (P2-4 of ``docs/optimization-plan-2026-07-16.md``):
        when the caller doesn't supply its own ``User-Agent``, we pick one
        at random from the project's shared UA pool (``utils.http._UA_POOL``)
        instead of the single static ``THS_UA``. Personal single-IP use is
        especially vulnerable to per-UA throttling on q.10jqka.com.cn, so
        the rotation is the cheapest defense. Callers that pass a custom
        UA (Cninfo POST, Baidu Bearer) keep theirs unchanged.

        **Scope caveat (M11 partial fix):** the rotation only applies to
        request sites that go through ``_http_get``. The other ~9 THS
        request sites (industry summary, hot topics, north flow, news
        flash, news search, board history, etc.) still use the static
        ``THS_UA`` constant directly. Extending the swap to those
        callsites is left as a follow-up — see audit §M11 for the full
        list. The audit's intent is met for the two paged cold-path
        fetches (``get_board_stocks`` and the industry summary loop in
        ``get_all_boards``), which are the highest-frequency request
        patterns.
        """
        import requests

        if headers is None or "User-Agent" not in headers:
            base = {"User-Agent": random_ua()}
            if headers:
                base.update(headers)
            headers = base
        return requests.get(url, headers=headers, timeout=timeout)
    def get_board_history(
        self,
        board_code: str,
        frequency: str = "d",
        days: int = 365,
        *,
        start_date: str | None = None,
        end_date: str | None = None,
        source: str | None = None,
        board_type: str | None = None,
        **kwargs,
    ) -> list[dict]:
        """THS concept/industry board K-line via quota-h.10jqka.com.cn (single_kline).

        Post-2026-07-21: replaced the legacy d.10jqka.com.cn year-loop with a
        single POST to ``single_kline``. The new endpoint returns clean JSON,
        takes all 8 frequencies via a single ``time_period`` enum, and uses a
        static JWT token (no rotation). It accepts THS platecode directly
        (885xxx for concept, 881xxx for industry) — CID resolution was dropped
        since the route defaults to platecode anyway.

        Args:
            board_code: THS platecode (concept: 885xxx; industry: 881xxx).
            frequency: One of ``d | w | m | 1m | 5m | 15m | 30m | 60m``.
            days: Default window width (always honored as the lower bound).
                Per-frequency max span: d/w/m=3650 (10y), 1m=2, 5m=30,
                15m=60, 30m=90, 60m=180.
            start_date: YYYY-MM-DD; only extends the window further back
                (``start_d = min(start_hint, end_d - days)``). Passing
                ``start_date=today`` is effectively a no-op — you still
                get the default ``days``-wide window. ``start_date`` set
                AFTER ``end_date`` raises ``ValueError`` → 400.
            end_date: YYYY-MM-DD upper bound; defaults to Beijing today.
            board_type: ``"concept"`` or ``"industry"``; auto-detected from
                the ``stock_board`` cache when omitted.

        Returns:
            list[dict] — sorted oldest → newest. Keys: date, open, high, low,
            close, volume, amount, frequency. ``date`` is normalized to
            ``"YYYY-MM-DD"`` (daily/weekly/monthly) or ``"YYYY-MM-DD HH:MM"``
            (minute bars).

        Raises:
            DataFetchError: JWT missing / chunk-hash rotation; non-zero
                upstream status_code after retry; unsupported frequency.
            ValueError: date span exceeds per-frequency max span; date bound
                malformed; ``end_date < start_date``.
        """
        # Auto-detect board_type from the stock_board cache when not provided.
        # Industry and concept both go through single_kline with the same
        # market="48"; the board_type only affects cache lookup and downstream
        # callers (which use it for member-list formatting etc.).
        if not board_type:
            from ..persistence.board import get_board_metadata

            meta = get_board_metadata(board_code, "ths")
            if meta and meta.get("type"):
                board_type = meta["type"]
            else:
                board_type = "concept"  # default; matches legacy behavior
        elif board_type not in ("concept", "industry"):
            raise DataFetchError(
                f"[ThsFetcher] get_board_history: board_type must be "
                f"'concept' or 'industry' (got {board_type!r})"
            )

        freq_key = (frequency or "d").lower()
        if freq_key not in _THS_HXKLINE_PERIOD_MAP:
            raise DataFetchError(
                f"[ThsFetcher] get_board_history: unsupported frequency "
                f"{frequency!r}; supported: {sorted(_THS_HXKLINE_PERIOD_MAP)}"
            )

        # Date range resolution + per-frequency max-span cap (reused from legacy).
        start_d, end_d = _resolve_ths_date_range(start_date, end_date, days)
        max_span_days = _THS_HXKLINE_MAX_SPAN_DAYS[freq_key]
        # `days` is the window width, not inclusive calendar days. E.g.
        # `days=30` means "30 bars" not "30+1 calendar days" — without
        # this fix, a `days=30` request with default end_d=today fails
        # the 5m (30d) cap by 1 (the +1 was a legacy off-by-one that
        # only mattered when `start_date` widened the window).
        span_days = (end_d - start_d).days
        if span_days > max_span_days:
            raise ValueError(
                f"[ThsFetcher] get_board_history: date span ({span_days}d) "
                f"exceeds frequency={freq_key!r} max ({max_span_days}d). "
                f"Narrow start_date/end_date."
            )

        rows = _fetch_ths_single_kline(
            board_code,
            freq_key=freq_key,
            start_d=start_d,
            end_d=end_d,
            days=days,
        )

        # Date range filter (canonical format comparison, same logic as legacy).
        start_str = start_d.strftime("%Y-%m-%d")
        # For minute-level, upstream maps begin_time=-N to N bars (not
        # N days of history). The resolver's ``min(start_hint, end_d -
        # days)`` therefore silently widens the fetch window past the
        # user's start_date when days is large (1m default = 800).
        # Override start_str with the user's start_date so the post-filter
        # actually honors it. Daily/weekly/monthly are unaffected because
        # their days == calendar days == bar count, so the resolver's
        # min() clamp is semantically correct.
        if freq_key in _MINUTE_FREQS and start_date:
            try:
                user_start_d = datetime.strptime(
                    start_date.strip(), "%Y-%m-%d"
                ).date()
                start_str = user_start_d.strftime("%Y-%m-%d")
            except ValueError:
                pass  # invalid start_date already raised in resolver
        end_str = (
            f"{end_d.strftime('%Y-%m-%d')} 23:59"
            if freq_key in _MINUTE_FREQS
            else end_d.strftime("%Y-%m-%d")
        )
        filtered = [r for r in rows if start_str <= r["date"] <= end_str]
        filtered.sort(key=lambda r: r["date"])
        logger.debug(
            f"[ThsFetcher] get_board_history board_code={board_code!r} "
            f"freq={freq_key} date_range=[{start_str},{end_str}] "
            f"upstream_rows={len(rows)} filtered_rows={len(filtered)}"
        )
        return filtered

    # ------------------------------------------------------------------
    # 板块成分股 (Board Stocks) — q.10jqka.com.cn AJAX endpoint
    # ------------------------------------------------------------------

    def _fetch_ths_board_stocks_page(
        self,
        concept_id: str,
        page: int,
        *,
        field_code: str = "199112",
        order: str = "desc",
    ) -> list[dict]:
        """Fetch one page of THS board stocks (10 rows per page).

        ``field_code`` selects the sort column (199112=change_pct, the
        default preserved for callers that don't care about ordering)
        and ``order`` picks direction ("desc"/"asc"); both map to the
        URL template placeholders consumed by ``_BOARD_STOCKS_URL_TEMPLATE``.

        Returns ``[]`` when the page is empty (caller treats as the
        end-of-pagination signal). HTTP non-2xx raises ``DataFetchError``
        so the upstream failure surfaces as 503 at the route layer
        rather than silently returning zero rows.

        GBK decoding: the upstream serves ``text/html; charset=gbk``,
        so we must set ``r.encoding = "gbk"`` BEFORE reading ``r.text``.
        Without this, requests defaults to ISO-8859-1 and the Chinese
        stock names decode to garbage.
        """
        url = _BOARD_STOCKS_URL_TEMPLATE.format(
            concept_id=concept_id,
            field_code=field_code,
            order=order,
            page=page,
        )
        headers = {
            "Referer": _CONCEPT_DETAIL_URL.format(slug=concept_id),
            "X-Requested-With": "XMLHttpRequest",
            "Cookie": f"v={self._v_token()}",
        }
        try:
            r = self._http_get(url, headers=headers, timeout=15)
        except Exception as e:
            raise DataFetchError(
                f"[ThsFetcher] board_stocks({concept_id}, page={page}) network failed: {e}"
            ) from e
        if not (200 <= r.status_code < 300):
            # 401/403 → raise a *subclass* of DataFetchError that the
            # pagination loop recognises as THS's "no more data"
            # boundary signal. Other statuses raise the base
            # DataFetchError so a real upstream failure still surfaces
            # as 5xx at the route layer and trips the circuit breaker.
            msg = (
                f"[ThsFetcher] board_stocks({concept_id}, page={page}) "
                f"HTTP {r.status_code} ({len(r.content)}B body)"
            )
            if r.status_code in _BOUNDARY_TOLERATED_STATUSES:
                raise ThsBoundarySignalError(msg, status_code=r.status_code)
            raise DataFetchError(msg)
        # Force GBK decoding BEFORE reading .text. requests defaults to
        # ISO-8859-1 when Content-Type has charset (gbk) but the body is
        # actually gbk-encoded — a documented requests behavior.
        r.encoding = "gbk"
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(r.text or "", features="lxml")
        rows_out: list[dict] = []
        for tr in soup.select("tbody tr"):
            tds = tr.find_all("td")
            if not tds:
                continue
            try:
                parsed = self._parse_ths_board_stocks_row(tds)
            except Exception as e:
                logger.warning(
                    f"[ThsFetcher] board_stocks({concept_id}, page={page}) "
                    f"skipping malformed row: {e}"
                )
                continue
            if parsed is not None:
                rows_out.append(parsed)
        return rows_out

    def get_board_stocks(
        self,
        board_code: str,
        *,
        source: str | None = None,
        include_quote: bool = False,
        board_type: str | None = None,
        top_n: int = 50,
        sort_by: str | None = None,
        sort_order: str = "desc",
        **kwargs,
    ) -> list[dict]:
        """THS board constituent stocks via q.10jqka.com.cn AJAX endpoint.

        Args:
            board_code: THS concept slug (e.g. ``"308709"``) — the path
                segment used by ``q.10jqka.com.cn/gn/detail/code/{slug}/``.
                THS concept/industry boards use 6-digit decimal slugs.
                This fetcher always treats the code as a ``concept_id``
                (THS does not expose a parallel industry endpoint that
                we have observed). If industry support is added later,
                branch on ``board_type``.
            source: Accepted for interface parity (manager passes it).
                Always effectively ``"ths"`` for this fetcher.
            include_quote: Accepted for interface parity. THS upstream
                already returns quote fields, so this flag is ignored.
            board_type: Accepted for interface parity. Currently unused.

        New kwargs (2026-07-13):
            sort_by: One of 11 keys in _THS_BOARD_STOCKS_SORT_FIELD_MAP.
                Default "change_pct".
            sort_order: "asc" or "desc". Default "desc".
            top_n: Max number of stocks to fetch. Default 50 (THS hard cap).

        Returns:
            ``list[dict]`` — one row per constituent stock. Each row has:
            - ``stock_code`` (e.g. ``"300740"``)
            - ``stock_name`` (Chinese name)
            - ``exchange`` (``"sh"`` / ``"sz"`` / ``""`` for unknown prefix)
            - ``price``, ``change_pct``, ``change_amount``, ``turnover_rate``,
              ``volume``, ``amount`` — None when upstream emits ``--``

            Empty list on no-data or upstream empty. Multiple pages are
            fanned out internally (10 rows per page, terminated by empty
            page or ``max_pages = ceil(top_n/10) + 1`` cap).

        Raises:
            DataFetchError: v-token mint failed, HTTP non-2xx on any page,
                or network failure on any page.
        """
        sort_by = sort_by or "change_pct"
        if sort_by not in _THS_BOARD_STOCKS_SORT_FIELD_MAP:
            raise DataFetchError(
                f"[ThsFetcher] get_board_stocks: sort_by={sort_by!r} not in "
                f"supported set {sorted(_THS_BOARD_STOCKS_SORT_FIELD_MAP.keys())}"
            )
        if sort_order not in ("asc", "desc"):
            raise DataFetchError(
                f"[ThsFetcher] get_board_stocks: sort_order={sort_order!r} must be 'asc' or 'desc'"
            )
        # Defensive clamp: THS upstream hard cap is 50 (=5 pages * 10).
        top_n = max(1, min(top_n, 50))
        field_code = _THS_BOARD_STOCKS_SORT_FIELD_MAP[sort_by]
        max_pages = (top_n + 9) // 10 + 1  # ceil(top_n/10) + 1 buffer

        all_rows: list[dict] = []
        for page in range(1, max_pages + 1):
            # P2-4: jitter between paged fetches. THS personal single-IP
            # use is easy to fingerprint at 10-row/page cadence; a uniform
            # 1.5-3.0s sleep evens out the request pattern. Skip the sleep
            # before the first page so the cold-path latency is unaffected.
            if page > 1:
                time.sleep(random.uniform(*self._THS_PAGING_JITTER_S))
            try:
                rows = self._fetch_ths_board_stocks_page(
                    board_code,
                    page,
                    field_code=field_code,
                    order=sort_order,
                )
            except ThsBoundarySignalError as e:
                if not all_rows:
                    raise
                logger.info(
                    f"[ThsFetcher] board_stocks({board_code}, page={page}, "
                    f"sort_by={sort_by}, sort_order={sort_order}) "
                    f"HTTP {e.status_code} on beyond-data page; treating as "
                    f"end of pagination ({len(all_rows)} rows collected so far)"
                )
                break
            if not rows:
                break
            all_rows.extend(rows)
            if len(all_rows) >= top_n:
                break
        return all_rows[:top_n]

    # ------------------------------------------------------------------
    # 板块实时行情 (Board Realtime Quote) — q.10jqka.com.cn 概念详情页 .heading
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_board_realtime(soup) -> dict:
        """Parse the .heading block of /gn/detail/code/{cid}/ into a quote dict.

        Units are kept as upstream (NOT converted): volume=万手 (safe_int),
        amount=亿元, net_inflow=亿元 — matches the existing industry-rank
        parser and BoardInfo's live convention. Prices/change are 指数点.

        Sign: displayed text is magnitude; direction comes from CSS classes
        (arr-rise/arr-fall on .board-xj for change; c-rise/c-fall on the
        资金净流入 dd for net inflow).

        Raises:
            DataFetchError: .heading block absent (page shape changed /
                board not found).
        """
        from ..core.types import safe_float, safe_int

        heading = soup.select_one(".heading")
        if heading is None:
            raise DataFetchError("[ThsFetcher] board realtime: .heading block not found")

        hq = heading.select_one(".board-hq")
        h3 = hq.select_one("h3") if hq else None
        code_span = h3.select_one("span") if h3 else None
        board_code = code_span.get_text(strip=True) if code_span else ""
        # name = h3 text minus the code span
        if code_span:
            code_span.extract()
        board_name = h3.get_text(strip=True) if h3 else ""

        xj = hq.select_one(".board-xj") if hq else None
        price = safe_float(xj.get_text(strip=True)) if xj else None
        change_is_fall = bool(xj and "arr-fall" in (xj.get("class") or []))

        zdf = hq.select_one(".board-zdf") if hq else None
        change_amount = change_pct = None
        if zdf:
            parts = zdf.get_text().split()  # str.split() also splits \xa0 (nbsp)
            if len(parts) >= 1:
                change_amount = safe_float(parts[0])
            if len(parts) >= 2:
                change_pct = safe_float(parts[1].rstrip("%"))

        def _signed(v, is_fall):
            return (-abs(v) if is_fall else v) if v is not None else None

        change_amount = _signed(change_amount, change_is_fall)
        change_pct = _signed(change_pct, change_is_fall)

        out: dict = {
            "board_code": board_code,
            "board_name": board_name,
            "price": price,
            "change_amount": change_amount,
            "change_pct": change_pct,
            "open": None,
            "prev_close": None,
            "high": None,
            "low": None,
            "volume": None,
            "amount": None,
            "up_count": None,
            "down_count": None,
            "net_inflow": None,
            "rank": None,
        }

        for dl in heading.select(".board-infos dl"):
            dt = dl.select_one("dt")
            dd = dl.select_one("dd")
            if not dt or not dd:
                continue
            label = dt.get_text(strip=True)
            if label == "今开":
                out["open"] = safe_float(dd.get_text(strip=True))
            elif label == "昨收":
                out["prev_close"] = safe_float(dd.get_text(strip=True))
            elif label == "最低":
                out["low"] = safe_float(dd.get_text(strip=True))
            elif label == "最高":
                out["high"] = safe_float(dd.get_text(strip=True))
            elif label.startswith("成交量"):
                out["volume"] = safe_int(dd.get_text(strip=True))  # 万手
            elif label == "涨幅排名":
                out["rank"] = dd.get_text(strip=True) or None
            elif label == "涨跌家数":
                spans = dd.select("span")
                if len(spans) >= 2:
                    out["up_count"] = safe_int(spans[0].get_text(strip=True))
                    out["down_count"] = safe_int(spans[1].get_text(strip=True))
            elif label.startswith("资金净流入"):
                v = safe_float(dd.get_text(strip=True))  # 亿元
                is_fall = "c-fall" in (dd.get("class") or [])
                out["net_inflow"] = _signed(v, is_fall)
            elif label.startswith("成交额"):
                out["amount"] = safe_float(dd.get_text(strip=True))  # 亿元
        return out

    def get_board_realtime(
        self,
        board_code: str,
        *,
        board_type: str | None = None,
        **kwargs,
    ) -> dict:
        """THS board-level realtime quote via q.10jqka.com.cn concept detail page.

        Args:
            board_code: THS platecode (e.g. ``"885595"`` for concept,
                ``"881270"`` for industry).
            board_type: Board classification (``"concept"`` / ``"industry"``).
                Source of truth: the ``stock_board`` cache (column
                ``board_type``). The route layer is expected to look this up
                and pass it explicitly. If omitted, the fetcher does a
                one-shot cache fallback (``get_board_metadata``) — this is
                a safety net, not the primary path. The legacy
                ``board_code.startswith("881")`` magic-string check has
                been removed; ``board_type`` is now the only discriminator.

                For ``board_type="industry"``: platecode IS the URL cid
                (per THS naming, e.g. 881272 → /gn/detail/code/881272/).
                For ``board_type="concept"`` (or any non-industry): the cid
                is resolved via the stock_board cache's platecode→cid
                mapping. If the cid can't be resolved, the upstream page
                would be empty, so we raise ``DataFetchError`` early
                instead of spending the HTTP round-trip on a known-empty
                page.

        Returns:
            dict with keys: board_code (platecode), board_name, price,
            change_amount, change_pct, open, prev_close, high, low, volume
            (万手), amount (亿元), up_count, down_count, net_inflow (亿元), rank,
            cid.

        Raises:
            DataFetchError: ``board_type`` cannot be determined (caller
                did not pass it AND the stock_board cache has no row)
                / cid unresolved for a non-industry platecode / upstream
                non-2xx / network failure / .heading absent.
        """
        # Resolve board_type: caller-provided takes precedence; otherwise
        # try the public cache helper. The legacy "881 prefix" magic
        # string has been removed (post-2026-07-10 review); the cache is
        # now the single source of truth for "industry vs concept".
        if board_type is None:
            from ..persistence.board import get_board_metadata

            meta = get_board_metadata(board_code, "ths")
            if meta and meta.get("type"):
                board_type = meta["type"]
            else:
                raise DataFetchError(
                    f"[ThsFetcher] board_realtime: cannot determine board_type "
                    f"for platecode={board_code!r}. The caller did not pass "
                    f"``board_type`` and the stock_board cache has no row for "
                    f"this code. (Concept/industry classification is required "
                    f"to build the upstream URL — pass it explicitly or "
                    f"ensure the board is in the stock_board cache.)"
                )

        # Resolve the URL cid from board_type. Industry boards use their
        # platecode directly; concept boards (and other non-industry
        # types) require a platecode→cid translation that's stored in
        # stock_board.
        from ..persistence.board import _resolve_ths_cid_from_platecode

        if board_type == "industry":
            cid = board_code
        else:
            cid = _resolve_ths_cid_from_platecode(board_code)
            if not cid:
                raise DataFetchError(
                    f"[ThsFetcher] board_realtime: no THS cid resolved for "
                    f"platecode={board_code!r} (board_type={board_type!r}). "
                    f"Concept boards require platecode→cid via stock_board cache."
                )
        url = _CONCEPT_DETAIL_URL.format(slug=cid)
        headers = {
            "Referer": _CONCEPT_DETAIL_URL.format(slug=cid),
            "Cookie": f"v={self._v_token()}",
        }
        try:
            r = self._http_get(url, headers=headers, timeout=15)
        except Exception as e:
            raise DataFetchError(
                f"[ThsFetcher] board_realtime({board_code}) network failed: {e}"
            ) from e
        if not (200 <= r.status_code < 300):
            raise DataFetchError(f"[ThsFetcher] board_realtime({board_code}) HTTP {r.status_code}")
        r.encoding = "gbk"
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(r.text or "", features="lxml")
        out = self._parse_board_realtime(soup)
        out["cid"] = cid
        # Prefer the platecode the client passed if the page didn't echo one.
        if not out.get("board_code"):
            out["board_code"] = board_code
        return out

    # ------------------------------------------------------------------
    # 股票所属概念 (stock_concept_list — basic.10jqka.com.cn)
    # ------------------------------------------------------------------

    def get_stock_news(self, stock_code: str, limit: int = 20) -> list[dict]:
        """THS 个股新闻 via basic.10jqka.com.cn/fuyao/info/company/v1/news.

        返回 dict shape 严格对齐 EastMoneyFetcher.get_stock_news:
          {title, url, source_domain, publish_date, media_name}.

        Soft failures (no market_id, upstream status_code != 0) → return [].
        Hard failures (network / JSON parse) → raise DataFetchError for
        manager.failover fallback to next fetcher.

        Returns:
            list of normalized news items; possibly empty.
        """
        code = normalize_stock_code(stock_code)
        market_id = _THS_MARKET_ID_MAP.get(code[:1])
        if not market_id:
            logger.warning(f"[ThsFetcher] get_stock_news: no market_id for {code!r}")
            return []
        try:
            n = max(1, min(int(limit), 100))
        except (TypeError, ValueError):
            n = 20
        payload = json_get(
            _THS_NEWS_URL,
            params={
                "type": "stock",
                "code": code,
                "market": market_id,
                "current": 1,
                "limit": n,
            },
            headers=_THS_BASIC_HEADERS,
            timeout=10,
        )
        if not isinstance(payload, dict) or payload.get("status_code") != 0:
            logger.warning(
                f"[ThsFetcher] get_stock_news({code}) upstream "
                f"status_code={payload.get('status_code') if isinstance(payload, dict) else 'N/A'}"
            )
            return []
        rows = (payload.get("data") or {}).get("data") or []
        out: list[dict] = []
        for r in rows:
            url = r.get("pc_url") or r.get("client_url") or r.get("mobile_url") or ""
            source_domain = source_domain_from_url(url)
            out.append(
                {
                    "title": str(r.get("title", "")),
                    "url": url,
                    "source_domain": source_domain,
                    "publish_date": str(r.get("date", "")),
                    "media_name": "",
                }
            )
        return out

    def get_announcements(self, code: str, page_size: int = 30) -> list[dict]:
        """THS 个股公告 via basic.10jqka.com.cn/basicapi/notice/pub.

        Returns dict shape compatible with CninfoFetcher.get_announcements:
          {title, type, date, url}; bonus field `raw_url` (cninfo PDF 直链).

        The upstream `data.type` field is the static classification list
        (业绩/重大事项/...); it's not per-record announcement type. Left as
        "" to match the existing schema's "type" semantics used by
        /stocks/{code}/announcements.

        Soft failures (no market_id, upstream status_code != 0) → return [].
        Hard failures (network / JSON parse) → raise DataFetchError.
        """
        code = normalize_stock_code(code)
        market_id = _THS_MARKET_ID_MAP.get(code[:1])
        if not market_id:
            logger.warning(f"[ThsFetcher] get_announcements: no market_id for {code!r}")
            return []
        try:
            n = max(1, min(int(page_size), 100))
        except (TypeError, ValueError):
            n = 30
        payload = json_get(
            _THS_NOTICE_URL,
            params={
                "type": "stock",
                "code": code,
                "market": market_id,
                "classify": "all",
                "page": 1,
                "limit": n,
            },
            headers=_THS_BASIC_HEADERS,
            timeout=10,
        )
        if not isinstance(payload, dict) or payload.get("status_code") != 0:
            logger.warning(
                f"[ThsFetcher] get_announcements({code}) upstream "
                f"status_code={payload.get('status_code') if isinstance(payload, dict) else 'N/A'}"
            )
            return []
        rows = payload.get("data") or {}
        items = rows.get("data") or [] if isinstance(rows, dict) else []
        out: list[dict] = []
        for r in items:
            url = r.get("pc_url") or r.get("mobile_url") or ""
            out.append(
                {
                    "title": str(r.get("title", "")),
                    "type": "",
                    "date": str(r.get("date", "")),
                    "url": url,
                    "raw_url": r.get("raw_url") or "",
                }
            )
        return out

    def get_stock_boards(self, stock_code: str, **kwargs) -> list[dict]:
        """THS concept membership via basic.10jqka.com.cn stock_concept_list.

        Returns list[{code, name, type, subtype}] or [] on upstream empty /
        no market_id mapping (北交所暂不支持).

        - code = quote_code (885xxx) — matches zzshare board-list code
          system, so forward board-list cache and reverse cold-fill rows
          join cleanly via (board_code, source).
        - type = 'concept' (硬编码 — endpoint is stock_concept_list).
        - subtype = THS_CONCEPT_SUBTYPE — matches
          VALID_SUBTYPES_BY_SOURCE["ths"]["concept"] (single source of truth
          via stock_data.data_provider.persistence.board).

        Raises:
            DataFetchError: HTTP fetch failed.
        """
        code = normalize_stock_code(stock_code)
        market_id = _THS_MARKET_ID_MAP.get(code[:1])
        if not market_id:
            logger.warning(
                f"[ThsFetcher] get_stock_boards: no market_id mapping "
                f"for code={code!r} (北交所暂不支持)"
            )
            return []
        try:
            payload = json_get(
                _STOCK_CONCEPT_LIST_URL,
                params={"code": code, "market_id": market_id, "simple": 1},
                headers={
                    "Referer": "https://basic.10jqka.com.cn/astockpc/astockmain/index.html",
                    "User-Agent": THS_UA,
                },
                timeout=10,
            )
        except Exception as e:
            raise DataFetchError(f"[ThsFetcher] stock_concept_list({code}) failed: {e}") from e
        # Mirror search_news: business-level upstream errors (status_code != 0)
        # surface as DataFetchError so cold-fill callers can see the failure in
        # `cold_sources` instead of silently receiving [].
        if payload.get("status_code") != 0:
            raise DataFetchError(
                f"[ThsFetcher] stock_concept_list({code}) upstream status_code="
                f"{payload.get('status_code')} msg={payload.get('status_msg')}"
            )
        rows = payload.get("data") or []
        return [
            {
                "code": normalize_stock_code(str(r.get("quote_code", "")).strip()),
                "name": str(r.get("name", "")).strip(),
                "type": "concept",
                "subtype": THS_CONCEPT_SUBTYPE,
            }
            for r in rows
            if r.get("quote_code")
        ]

    # ------------------------------------------------------------------
    # 板块清单 (All Boards) — concept + industry
    # ------------------------------------------------------------------
    #
    # Strategy (designed 2026-07-08, mirrors the upstream-rendered DOM rather
    # than akshare's paginated ajax/1/ path):
    #
    #   - Concept: single GET /gn/  → two data blobs coexist on the page:
    #       (a) `<input id="gnSection" value="{...}">` hidden input — 295
    #           boards, carries platecode + cid + platename + change_pct +
    #           net_inflow. The "今日热门" subset (boards with today's
    #           trade data), not a full list.
    #       (b) `.cate_items a[href*="/gn/detail/code/"]` sidebar — 351
    #           boards (full A–Z + 数字 index), only cid + name, no
    #           platecode. Covers 88 boards that gnSection misses.
    #     Merge by cid: gnSection rows are primary (carry platecode +
    #     real-time fields), sidebar fills missing names. ~383 unique.
    #
    #   - Industry: single GET /thshy/ → `.cate_items a[href*="/thshy/detail/code/"]`
    #     sidebar. No equivalent gnSection on the industry page; code IS
    #     the platecode (881xxx), no separate cid. ~80–90 industries.
    #
    # For industry the upstream returns fewer fields (no change_pct /
    # net_inflow on the sidebar). If callers need quote data, use
    # the existing /boards/{code}/stocks + get_board_history path; the
    # board-list endpoint stays metadata-only (consistent with the
    # persistence layer's "realtime quotes never go in SQLite" rule —
    # see stock_data.data_provider.persistence.board CLAUDE.md).
    #
    # Network auth: both endpoints sit behind the same `v=` cookie the
    # board-K-line path uses; reuse `_get_ths_v_token` so the V8 VM
    # stays warm across the call.

    _THS_CONCEPT_INDEX_URL = "https://q.10jqka.com.cn/gn/"
    _THS_INDUSTRY_INDEX_URL = "https://q.10jqka.com.cn/thshy/"
    _THS_BOARD_LIST_TIMEOUT = 15

    # P2-4 board-paging jitter (docs/optimization-plan-2026-07-16.md).
    # THS personal single-IP users are easy to flag — q.10jqka.com.cn sees
    # the IP and UA but not enough cookie churn. A randomized sleep between
    # paged board fetches matches the 1.5-3.0s range the project's CLAUDE.md
    # aspirationally promises (today: only EastMoney uses it; THS was the
    # weakest link per audit §M11).
    _THS_PAGING_JITTER_S = (1.5, 3.0)

    # Realtime fields the /boards response shape promises for every row.
    # The list is intentionally verbose so the backfill loop in
    # ``get_all_boards`` can guarantee uniform shape across concept +
    # industry + sidebar-only + gnSection-only rows. Sidebar-only
    # concept rows and (default) industry rows get None for each
    # entry. ``include_quote=True`` on industry populates the bulk
    # of these from the rank table.
    _REALTIME_BOARD_FIELDS: tuple[str, ...] = (
        "change_pct",
        "volume",
        "amount",
        "net_inflow",
        "up_count",
        "down_count",
        "avg_price",
        "leading_stock",
        "leading_stock_price",
        "leading_stock_pct",
    )

    def get_all_boards(
        self,
        board_type: str | None = None,
        subtype: str | None = None,
        include_quote: bool = False,  # accepted for interface parity; ignored
        source: str = "ths",  # accepted for Manager interface parity
        **kwargs,
    ) -> list[dict]:
        """THS concept + industry board list via q.10jqka.com.cn index pages.

        Returns unified rows shaped like other fetchers' get_all_boards:
            ``{code, name, type, subtype, source, platecode, change_pct?, net_inflow?}``

        - For **concept**: ``code`` = THS concept id (cid, 300xxx);
          ``platecode`` = 885xxx used by d.10jqka.com.cn/v4/line/bk_*/
          (i.e. the same ``<input id="clid">`` value that
          ``get_board_history`` resolves for concept K-line).
        - For **industry**: ``code`` = platecode (881xxx) — they are the
          same thing for industries, since THS doesn't expose a
          separate cid for industry boards (verified 2026-07-08: the
          ``/thshy/detail/code/881272/`` detail page's ``<input id=clid>``
          returns 881272, identical to the URL slug).
        - ``platecode`` may be ``None`` for concept rows that appear
          only in the sidebar (88 of ~383 on a typical snapshot) — the
          sidebar doesn't carry platecode. Reverse-filling them by
          fetching ``/gn/detail/code/{cid}/`` would cost 88 extra
          requests on every refresh; out of scope. Clients that need
          the platecode for K-line can resolve on demand via
          ``get_board_history`` (which already does the clid lookup).

        Args:
            board_type: ``"concept"`` / ``"industry"`` / ``None`` (both).
                ``None`` fans out to both and concatenates the results.
            subtype: optional ``THS_CONCEPT_SUBTYPE`` / ``THS_INDUSTRY_SUBTYPE``
                filter. ``None`` returns every subtype the type exposes.
            include_quote: when True, industry boards are enriched with
                change_pct + net_inflow from the rank table at
                ``/thshy/index/field/199112/.../ajax/1/`` (2 pages).
                Concept boards always carry these fields when gnSection
                has them (the rank table is not used for concept — it
                only lists industries). For rows that lack a real-time
                value the field is set to ``None`` rather than omitted,
                so the response shape is uniform across all rows.

        Returns:
            ``list[dict]`` — every row carries ``change_pct`` and
            ``net_inflow`` keys (None when unavailable). Empty list on
            upstream failure (no board list available); the persistence
            layer treats empty + non-"persistence" origin as a partial
            failure and logs a WARNING.

        Raises:
            DataFetchError: v-token mint failed, HTTP non-2xx on either
                index page, or HTML parse error (gnSection JSON
                malformed).
        """
        _ = source  # accepted for Manager interface; ThsFetcher has no per-call source override
        types_to_fetch: list[str]
        if board_type is None:
            types_to_fetch = ["concept", "industry"]
        elif board_type in ("concept", "industry"):
            types_to_fetch = [board_type]
        else:
            raise DataFetchError(
                f"[ThsFetcher] get_all_boards: board_type must be "
                f"'concept' / 'industry' / None (got {board_type!r})"
            )

        out: list[dict] = []
        for bt in types_to_fetch:
            if bt == "concept":
                rows = self._fetch_ths_concept_boards()
            else:
                rows = self._fetch_ths_industry_boards(include_quote=include_quote)
            # Tag + subtype the per-type rows. The per-row enrichment
            # helpers above already set realtime fields where the
            # upstream supplied them; here we tag the row and backfill
            # missing keys with None so every row has a uniform shape
            # (no "key present or absent" branching for the caller).
            for r in rows:
                r["type"] = bt
                r["subtype"] = THS_CONCEPT_SUBTYPE if bt == "concept" else THS_INDUSTRY_SUBTYPE
                # Uniform shape: every row carries the full set of
                # realtime fields. Concept rows from gnSection get
                # change_pct + net_inflow; sidebar-only concept rows
                # and (by default) industry rows get None for
                # everything. The downstream consumer can rely on key
                # presence — no ``if "change_pct" in r`` branching.
                for k in ThsFetcher._REALTIME_BOARD_FIELDS:
                    r.setdefault(k, None)
            if subtype is not None:
                rows = [r for r in rows if r.get("subtype") == subtype]
            out.extend(rows)
        return out

    # -- concept: /gn/ -------------------------------------------------

    def _fetch_ths_concept_boards(self) -> list[dict]:
        """Single GET /gn/ → merge gnSection + sidebar.

        Returns rows keyed by cid. gnSection rows are primary (carry
        platecode + real-time fields). Sidebar rows fill in any
        boards gnSection misses (~88, all without platecode).

        Deduplicates by cid; if both sources carry the same cid, the
        gnSection row wins (it has the richer payload). Sidebar rows
        with no cid are dropped (malformed).

        Returns ``[]`` on hard failure (HTML parse / network). The
        per-row exceptions on individual sidebar links are swallowed
        so a single bad link doesn't fail the whole list.
        """
        html = self._http_get_ths_board_index(self._THS_CONCEPT_INDEX_URL)
        gn_section = self._parse_gn_section(html)
        sidebar = self._parse_ths_gn_sidebar(html)
        return self._merge_concept_sources(gn_section, sidebar)

    @staticmethod
    def _parse_gn_section(html: str) -> list[dict]:
        """Extract boards from ``<input id="gnSection" value="{json}">``.

        The value is HTML-encoded JSON: &quot; → ", &amp; → &. The
        decoded payload is a dict keyed by a numeric rank, each value
        carrying platecode / platename / cid / zjjlr / zfl + an
        anonymous date-key field (e.g. "199112") whose value is the
        board's intraday change_pct (%). The "zfl" key is a private
        THS field whose meaning is not publicly documented (verified
        2026-07-08: does NOT match stock count, rank, or any rendered
        label on the detail page) — we drop it on the way out.

        Malformed rows (missing cid or platecode) are skipped at
        DEBUG level (~15 rows/snapshot from gnSection lack a cid; not
        a fetcher bug — see inline comment). Bad JSON raises
        DataFetchError (a 200 OK with broken JSON is an upstream
        change, not a transient fault).
        """
        import json as _json

        from bs4 import BeautifulSoup

        soup = BeautifulSoup(html or "", features="lxml")
        node = soup.find("input", attrs={"id": "gnSection"})
        if node is None:
            return []
        raw = node.get("value") or ""
        if not raw:
            return []
        decoded = raw.replace("&quot;", '"').replace("&amp;", "&")
        try:
            payload = _json.loads(decoded)
        except Exception as e:
            raise DataFetchError(
                f"[ThsFetcher] get_all_boards: malformed gnSection JSON: {e}"
            ) from e
        out: list[dict] = []
        for entry in payload.values():
            if not isinstance(entry, dict):
                continue
            cid = str(entry.get("cid", "")).strip()
            platecode = str(entry.get("platecode", "")).strip()
            name = str(entry.get("platename", "")).strip()
            if not cid or not platecode or not name:
                # Brand-new boards sometimes appear in gnSection before
                # upstream assigns a cid (verified 2026-07-08: ~15 rows in
                # a typical snapshot, platecode populated but cid empty).
                # The sidebar will fill in any rows that already have a
                # cid; the rest we drop. Not a fetcher bug — log at DEBUG
                # so the count is visible without spamming WARNING.
                logger.debug(
                    f"[ThsFetcher] gnSection row missing required field: "
                    f"cid={cid!r} platecode={platecode!r} name={name!r}"
                )
                continue
            row: dict = {
                "code": cid,
                "name": name,
                "platecode": platecode,
                "source": "ths",
            }
            # Real-time fields from gnSection. The numeric key (e.g.
            # "199112") is a date-style label whose value is the
            # intraday change_pct (%). We probe for it without baking
            # the magic number into the fetcher so an upstream rename
            # is a one-line change.
            for k, v in entry.items():
                if k in ("cid", "platecode", "platename", "zjjlr", "zfl"):
                    continue
                if isinstance(v, (int, float)) and not isinstance(v, bool):
                    # First non-meta numeric field is the change_pct
                    # carrier. The break guarantees a single assignment.
                    row["change_pct"] = float(v)
                    break
            zjjlr = entry.get("zjjlr")
            if isinstance(zjjlr, (int, float)) and not isinstance(zjjlr, bool):
                row["net_inflow"] = float(zjjlr)  # 单位: 亿元
            out.append(row)
        return out

    @staticmethod
    def _parse_ths_gn_sidebar(html: str) -> list[dict]:
        """Extract (cid, name) pairs from the /gn/ index sidebar.

        Mirrors the parsing akshare does in ``_get_stock_board_concept_name_ths``
        but returns a list of dicts (akshare returns a {name: code} dict,
        which loses order). We only need the slug from the URL — name
        comes from the anchor text.

        Robust to a single bad <a>: it logs and skips rather than
        aborting the whole board list.
        """
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(html or "", features="lxml")
        out: list[dict] = []
        # Scope to .cate_items so we don't accidentally pick up
        # detail-page links from any other sidebar block on /gn/.
        for items_div in soup.select(".cate_items"):
            for a in items_div.select("a"):
                href = a.get("href") or ""
                if "/gn/detail/code/" not in href:
                    continue
                parts = [p for p in href.split("/") if p]
                slug = parts[-1] if parts else ""
                name = a.get_text(strip=True)
                if not slug or not name:
                    logger.debug(f"[ThsFetcher] sidebar anchor missing slug or name: href={href!r}")
                    continue
                out.append({"code": slug, "name": name, "source": "ths"})
        return out

    @staticmethod
    def _merge_concept_sources(gn_section: list[dict], sidebar: list[dict]) -> list[dict]:
        """Merge gnSection (primary) + sidebar (fallback for missing names).

        - gnSection rows always win (they carry platecode + real-time).
        - Sidebar-only rows are appended; their ``platecode`` is set
          to ``None`` so callers can detect "no K-line via platecode"
          and fall back to ``get_board_history``'s clid lookup.
        - Duplicates within either source (e.g. gnSection repeating
          the same cid twice in a single snapshot) are de-duped by cid.
        """
        by_cid: dict[str, dict] = {}
        for r in gn_section:
            by_cid[r["code"]] = r
        for r in sidebar:
            cid = r["code"]
            if cid in by_cid:
                # Fill missing name (gnSection should already have it,
                # but a malformed upstream that left name empty benefits).
                if not by_cid[cid].get("name") and r.get("name"):
                    by_cid[cid]["name"] = r["name"]
                continue
            # Sidebar-only: no platecode available, leave None.
            by_cid[cid] = {**r, "platecode": None}
        return list(by_cid.values())

    # -- industry: /thshy/ ---------------------------------------------

    def _fetch_ths_industry_boards(self, *, include_quote: bool = False) -> list[dict]:
        """Single GET /thshy/ → sidebar (881xxx platecodes), optionally enriched.

        Industries don't have a hidden-input data blob like /gn/ does.
        The sidebar ``.cate_items a[href*="/thshy/detail/code/"]`` is
        the primary source.

        Real-time fields are absent from the sidebar — those live in
        the rank table on ``/thshy/index/field/199112/.../ajax/1/``.
        When ``include_quote=True`` we also fetch that paginated rank
        table (2 pages, 90 industries total — the rank table is a
        complete list as of 2026-07-08) and merge by name.

        The merge is a NAME lookup because the rank table only
        carries board names (no platecode column). Names in both
        sources are upstream-curated so collisions are rare; the
        merge still tolerates them by last-write-wins. Every
        realtime field is overridden in-place — there is no field
        we keep from the sidebar row, since the sidebar has none.

        For industry, ``code`` IS the platecode (881xxx). We still
        emit ``platecode`` redundantly in the response so the
        ``/boards`` response shape is uniform across concept/industry.
        """
        html = self._http_get_ths_board_index(self._THS_INDUSTRY_INDEX_URL)
        rows = self._parse_ths_thshy_sidebar(html)
        for r in rows:
            r["platecode"] = r["code"]  # industry code == platecode
        if include_quote:
            quotes_by_name = self._fetch_ths_industry_summary()
            for r in rows:
                q = quotes_by_name.get(r["name"]) or {}
                # Apply every realtime field the rank table carries
                # (None when upstream didn't supply). Non-quote fields
                # (code / name / source) are preserved from the sidebar.
                for k, v in q.items():
                    r[k] = v
        return rows

    @staticmethod
    def _parse_ths_thshy_sidebar(html: str) -> list[dict]:
        """Extract (platecode, name) pairs from the /thshy/ index sidebar.

        Industry slugs are 6-digit decimal but the leading 3 digits are
        always 881 (e.g. 881121 半导体, 881273 白酒). The slug is the
        ``code`` and the platecode — no separate cid exists for
        industry boards.

        No gnSection-style hidden input exists on /thshy/, so this
        single source is the full list.
        """
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(html or "", features="lxml")
        out: list[dict] = []
        for items_div in soup.select(".cate_items"):
            for a in items_div.select("a"):
                href = a.get("href") or ""
                if "/thshy/detail/code/" not in href:
                    continue
                parts = [p for p in href.split("/") if p]
                slug = parts[-1] if parts else ""
                name = a.get_text(strip=True)
                if not slug or not name:
                    continue
                out.append({"code": slug, "name": name, "source": "ths"})
        return out

    # Industry rank/summary endpoint — paginated, carries change_pct and
    # net_inflow. 2 pages, 50 + 40 = 90 industries (verified 2026-07-08:
    # the rank table is the COMPLETE industry set, not a top-N subset).
    _THS_INDUSTRY_SUMMARY_URL = (
        "http://q.10jqka.com.cn/thshy/index/field/199112/order/desc/page/{page}/ajax/1/"
    )
    _THS_INDUSTRY_SUMMARY_MAX_PAGES = 5  # safety cap; observed: 2

    def _fetch_ths_industry_summary(self) -> dict[str, dict]:
        """Fetch the industry rank table; return ``{name: <all realtime fields>}``.

        The value dict mirrors the per-row shape produced by
        :meth:`_parse_ths_industry_summary_page` (every realtime
        column the rank table carries — change_pct / volume / amount /
        net_inflow / up_count / down_count / avg_price / leading_stock
        / leading_stock_price / leading_stock_pct). Callers merge by
        name into the sidebar rows.

        Returns an empty dict on hard failure (network / parse); callers
        then leave every realtime field as None rather than failing
        the whole board-list request. The rank table is a "today's
        performance leaderboard" ordered by 涨跌幅; an empty page is
        the end-of-pagination signal.
        """

        out: dict[str, dict] = {}
        for page in range(1, self._THS_INDUSTRY_SUMMARY_MAX_PAGES + 1):
            # P2-4: jitter between paged fetches — same rationale as
            # ``get_board_stocks``. Industry-summary backfill can fan out
            # up to _THS_INDUSTRY_SUMMARY_MAX_PAGES (5) requests in tight
            # succession, which is the request pattern most likely to
            # trigger THS anti-bot heuristics.
            if page > 1:
                time.sleep(random.uniform(*self._THS_PAGING_JITTER_S))
            url = self._THS_INDUSTRY_SUMMARY_URL.format(page=page)
            headers = {
                "Referer": self._THS_INDUSTRY_INDEX_URL,
                "X-Requested-With": "XMLHttpRequest",
                "Cookie": f"v={self._v_token()}",
            }
            try:
                r = self._http_get(url, headers=headers, timeout=self._THS_BOARD_LIST_TIMEOUT)
                if not (200 <= r.status_code < 300):
                    logger.warning(
                        f"[ThsFetcher] industry summary page={page} HTTP {r.status_code}"
                    )
                    break
                # Industry rank table is GBK-encoded (verified 2026-07-08);
                # requests will auto-pick GBK from Content-Type but we set
                # it explicitly to defend against a charset-less response.
                r.encoding = "gbk"
                rows = self._parse_ths_industry_summary_page(r.text or "")
            except Exception as e:
                logger.warning(f"[ThsFetcher] industry summary page={page} failed: {e}")
                break
            if not rows:
                break
            for row in rows:
                name = row.pop("name")
                out[name] = row
        return out

    @staticmethod
    def _parse_ths_industry_summary_page(html: str) -> list[dict]:
        """Parse one industry rank table page → list of {name, ...realtime fields}.

        Table columns (verified 2026-07-08):
            0:  序号                 (ignored)
            1:  板块                 (name)
            2:  涨跌幅(%)            (change_pct, %)
            3:  总成交量(万手)        (volume, 万手)
            4:  总成交额(亿元)        (amount, 亿元)
            5:  净流入(亿元)          (net_inflow, 亿元)
            6:  上涨家数              (up_count)
            7:  下跌家数              (down_count)
            8:  均价                 (avg_price, 元/股)
            9:  领涨股                (leading_stock)
            10: 领涨股-最新价         (leading_stock_price, 元)
            11: 领涨股-涨跌幅(%)     (leading_stock_pct, %)

        We extract every realtime column so the response shape is
        uniform across rows (None when the source has no value).
        Returns ``[]`` for empty / non-table pages so the caller's
        page-loop terminates on the first empty page.
        """
        from bs4 import BeautifulSoup

        from ..core.types import safe_float, safe_int

        soup = BeautifulSoup(html or "", features="lxml")
        out: list[dict] = []
        for tr in soup.select("tbody tr"):
            tds = tr.find_all("td")
            if len(tds) < 6:
                continue
            name = tds[1].get_text(strip=True)
            if not name:
                continue
            out.append(
                {
                    "name": name,
                    "change_pct": safe_float(tds[2].get_text(strip=True)) if len(tds) > 2 else None,
                    "volume": safe_int(tds[3].get_text(strip=True)) if len(tds) > 3 else None,
                    "amount": safe_float(tds[4].get_text(strip=True)) if len(tds) > 4 else None,
                    "net_inflow": safe_float(tds[5].get_text(strip=True)) if len(tds) > 5 else None,
                    "up_count": safe_int(tds[6].get_text(strip=True)) if len(tds) > 6 else None,
                    "down_count": safe_int(tds[7].get_text(strip=True)) if len(tds) > 7 else None,
                    "avg_price": safe_float(tds[8].get_text(strip=True)) if len(tds) > 8 else None,
                    "leading_stock": tds[9].get_text(strip=True) if len(tds) > 9 else None,
                    "leading_stock_price": safe_float(tds[10].get_text(strip=True))
                    if len(tds) > 10
                    else None,
                    "leading_stock_pct": safe_float(tds[11].get_text(strip=True))
                    if len(tds) > 11
                    else None,
                }
            )
        return out

    # -- shared HTTP ----------------------------------------------------

    def _http_get_ths_board_index(self, url: str) -> str:
        """GET a THS index page with the v-token cookie.

        Distinct from the per-year board-K-line HTTP helper because:
        - No ``Referer`` / ``Host`` overrides needed (we're not
          hitting d.10jqka.com.cn).
        - GBK-decoding NOT needed (the index pages are UTF-8).
        - Timeout can be shorter (single page, not part of a year loop).

        Returns body on 2xx. Raises DataFetchError on non-2xx so the
        upstream failure surfaces in the response / 503 path.
        """
        headers = {"Cookie": f"v={self._v_token()}"}
        try:
            r = self._http_get(url, headers=headers, timeout=self._THS_BOARD_LIST_TIMEOUT)
        except Exception as e:
            raise DataFetchError(f"[ThsFetcher] get_all_boards: GET {url} failed: {e}") from e
        if not (200 <= r.status_code < 300):
            raise DataFetchError(
                f"[ThsFetcher] get_all_boards: GET {url} HTTP {r.status_code} "
                f"({len(r.content)}B body)"
            )
        return r.text or ""

    # ------------------------------------------------------------------
    # 热点题材 (Hot Topics)
    # ------------------------------------------------------------------

    # ------------------------------------------------------------------
    # 板块 F10 页面（basic.10jqka.com.cn/48/{code}/）：成分股全表 + 板块新闻 + 炒作周期
    # (added 2026-07-20 per spec §3.2; HTML cache via _THS_F10_BOARD_URL)
    # ------------------------------------------------------------------

    @staticmethod
    def _throttle_f10_cache_key(board_code: str) -> str:
        """Stable cache key for the F10 HTML cache. Stored as-is in
        :data:`_f10_html_cache`. The route layer wraps each public method
        call in its own `@cache_endpoint` (30min TTL), so this cache only
        covers intra-window multiple-section reads (stocks + news + surges
        on the same process hit)."""
        return f"ths-f10-html::{board_code}"

    def get_board_f10_page(self, board_code: str, *, board_type: str | None = None) -> str:
        """Fetch the THS F10 HTML page for a board, with a short TTL HTML cache.

        Three downstream methods (``get_board_stocks_full``,
        ``get_board_news``, ``get_board_surges``) all read this same page
        and parse their respective sections. The 45-second module-level
        cache lets a single request window issue one upstream GET even
        when all three are called in succession.

        Args:
            board_code: THS public platecode (e.g. ``"885914"``).
            board_type: Optional hint. ``"industry"`` short-circuits with
                empty string (industry F10 path not probed yet — see
                spec §3.2 stub note); ``"concept"`` / ``None`` fetches.

        Returns:
            The HTML body as GBK-decoded text, or ``""`` on:
              - HTTP 401/403 (boundary signal — same handling as
                ``get_board_stocks``)
              - ``board_type="industry"`` (v1 stub — see spec §3.2)

        Raises:
            DataFetchError: 5xx / network failure (not 401/403 — those
                are surfaced as empty string so callers can transparently
                fall back to the existing ZZSHARE+THS chain).
        """
        if board_type == "industry":
            # v1 doesn't support industry F10 — return empty so the
            # caller's `if html == "": return []` logic kicks in.
            logger.info(
                f"[ThsFetcher] get_board_f10_page: industry F10 page "
                f"not implemented in v1 (board_code={board_code!r}); "
                f"caller should fall back to the canonical path."
            )
            return ""

        cache_key = self._throttle_f10_cache_key(board_code)
        now = time.monotonic()
        cached = _f10_html_cache.get(cache_key)
        if cached is not None:
            html, ts = cached
            if (now - ts) < _F10_HTML_TTL_SECONDS:
                return html
            # TTL expired — drop and refetch.
            _f10_html_cache.pop(cache_key, None)

        url = _THS_F10_BOARD_URL.format(board_code=board_code)
        headers = {"Cookie": f"v={self._v_token()}"}
        try:
            r = self._http_get(url, headers=headers, timeout=10)
        except Exception as e:
            raise DataFetchError(
                f"[ThsFetcher] get_board_f10_page({board_code!r}): GET {url} failed: {e}"
            ) from e

        status = getattr(r, "status_code", 0)
        if status in _BOUNDARY_TOLERATED_STATUSES:
            # 401 / 403 — THS upstream's no-auth signal. Don't cache;
            # caller's downstream parser returns []. Mirrors
            # get_board_stocks' boundary-signal handling.
            logger.warning(
                f"[ThsFetcher] get_board_f10_page({board_code!r}): "
                f"HTTP {status}; returning empty."
            )
            return ""
        if not (200 <= status < 300):
            raise DataFetchError(
                f"[ThsFetcher] get_board_f10_page({board_code!r}): "
                f"HTTP {status} ({len(r.content)}B body)"
            )

        # The page declares its encoding as GBK in the meta charset; match
        # what the existing fetcher does for THS HTML so BeautifulSoup
        # gets unicode strings.
        r.encoding = "gbk"
        html = r.text or ""
        if html:
            _f10_html_cache[cache_key] = (html, now)
        return html

    def get_board_stocks_full(
        self,
        board_code: str,
        *,
        board_type: str | None = None,
        **kwargs,
    ) -> list[dict]:
        """THS F10 concept page's full membership — 90+ / 800+ concept stocks.

        Distinct from ``get_board_stocks`` (q.10jqka AJAX, hard cap 50
        with realtime sort keys). F10 has no realtime quote — all
        quote-shaped fields are ``None``.

        Data source on the page: ``<div id="concept_data" style="display:none;">
        {JSON}</div>``. THS's client JS at ``s.thsi.cn/js/basic/exponent/index.js``
        ``eval()``s it and renders into ``#c_table``. We parse the inline JSON
        directly because our fetcher doesn't run JS — the raw HTML has the
        c_table shell but no rows. Probed 2026-07-21: 885914 → 90 rows,
        885756 → 905 rows (vs q.10jqka's 50-cap).

        Args:
            board_code: THS public platecode (e.g. ``"885914"``).
            board_type: Optional hint. ``"industry"`` returns ``[]``
                (v1 stub — see :meth:`get_board_f10_page`).
            **kwargs: Absorbed silently so callers can pass arbitrary
                kwargs through ``_with_source`` without crashing.

        Returns:
            list of dicts with shape matching ``get_board_stocks``'s
            BoardStockInfo fields, with all quote-shaped values ``None``
            (F10 doesn't provide them). Empty list on industry,
            401/403, no rows in HTML.
        """
        from bs4 import BeautifulSoup
        from ..core.types import safe_float, safe_int
        import json as _json
        import re as _re

        html = self.get_board_f10_page(board_code, board_type=board_type)
        if not html:
            return []

        soup = BeautifulSoup(html, features="lxml")

        # Primary path: parse the inline #concept_data JSON. Each entry:
        #   [stock_code, stock_name, exchange, rank, ?, ?, 涨停次数, summary, ...]
        # Index 0=code, 1=name, 2=exchange ("深交所"/"上交所"/"北交所"),
        # 3=涨停次数 (rank in some boards). Probed 2026-07-21 on
        # 885914 / 885756.
        rows: list[dict] = []
        concept_data = soup.find(id="concept_data")
        if concept_data is not None:
            txt = concept_data.get_text() or ""
            try:
                payload = _json.loads(txt)
                ld = (payload.get("result") or {}).get("listdata") or {}
                # listdata keyed by date; take the only (or latest) entry.
                for _date, entries in ld.items():
                    for entry in entries or []:
                        if not (isinstance(entry, (list, tuple)) and len(entry) >= 3):
                            continue
                        stock_code = str(entry[0] or "").strip()
                        if not stock_code:
                            continue
                        exch_map = {"上交所": "sh", "深交所": "sz", "北交所": "bj"}
                        exchange = exch_map.get(str(entry[2] or "").strip(), "")
                        rows.append(
                            {
                                "stock_code": stock_code,
                                "stock_name": str(entry[1] or "").strip(),
                                "exchange": exchange,
                                "price": None,
                                "change_pct": None,
                                "change_amount": None,
                                "volume": None,
                                "amount": None,
                                "turnover_rate": None,
                                "amplitude": None,
                                "high": None,
                                "low": None,
                                "open": None,
                                "prev_close": None,
                                "speed_open": None,
                                "speed_current": None,
                                "speed_change_pct": None,
                                "speed_change_amount": None,
                                "speed_volume": None,
                                "speed_turnover_rate": None,
                                "rise_speed": None,
                                "ls_based_ratio": None,
                                "rise_count": None,
                                "fall_count": None,
                                "leading_stock": None,
                                "leading_stock_pct": None,
                                "board_pct": None,
                                "rank": safe_int(entry[3]) if len(entry) > 3 else None,
                                "eps": None,
                                "float_share_yi": None,
                                "float_mv_yi": None,
                                "limit_up_count_year": None,
                                "analysis": None,
                                "pop_info": None,
                            }
                        )
                    break  # only consume the first/latest date entry
            except (ValueError, KeyError, TypeError) as e:
                logger.warning(
                    f"[ThsFetcher] get_board_stocks_full({board_code!r}): "
                    f"#concept_data JSON parse failed ({type(e).__name__}: {e}); "
                    f"falling back to #c_table rows."
                )

        # Fallback: render-side rows (legacy spec path; works only if upstream
        # ships server-rendered rows, which it doesn't today).
        if not rows:
            c_table = soup.find(id="c_table")
            if c_table is None:
                return []  # concept_data missing AND c_table missing — empty board
            for tr in c_table.select("tr"):
                a = tr.select_one("a.jumpto[code]")
                if a is None:
                    continue
                stock_code = a["code"].strip() if a.get("code") else ""
                raw_name = a.get_text(strip=True)
                stock_name = strip_em_tags(raw_name)
                exchange = ""
                td = tr.find_all("td")
                if len(td) >= 3:
                    exch_map = {"上交所": "sh", "深交所": "sz", "北交所": "bj"}
                    exchange = exch_map.get(td[2].get_text(strip=True), "")
                if not stock_code:
                    continue
                rows.append(
                    {
                        "stock_code": stock_code,
                        "stock_name": stock_name,
                        "exchange": exchange,
                        "price": None, "change_pct": None, "change_amount": None,
                        "volume": None, "amount": None, "turnover_rate": None,
                        "amplitude": None, "high": None, "low": None,
                        "open": None, "prev_close": None,
                        "speed_open": None, "speed_current": None,
                        "speed_change_pct": None, "speed_change_amount": None,
                        "speed_volume": None, "speed_turnover_rate": None,
                        "rise_speed": None, "ls_based_ratio": None,
                        "rise_count": None, "fall_count": None,
                        "leading_stock": None, "leading_stock_pct": None,
                        "board_pct": None, "rank": None,
                        "eps": None, "float_share_yi": None,
                        "float_mv_yi": None, "limit_up_count_year": None,
                        "analysis": None, "pop_info": None,
                    }
                )

        return rows

    def get_board_news(
        self,
        board_code: str,
        *,
        limit: int = 20,
        board_type: str | None = None,
        **kwargs,
    ) -> list[dict]:
        """THS 板块新闻 via news.10jqka.com.cn timeline API.

        Replaces the old F10-page (`basic.10jqka.com.cn/48/{code}/`) scrape,
        which hard-capped at 14 items (two 7-item ``<ul>`` blocks) and never
        carried a summary. The timeline endpoint is unauthenticated JSON,
        cursor-paginated, and returns publisher + summary per item (probed
        2026-07-21 on 885756 / 881165 / 884001, marketId=48 covers concept
        and industry boards alike).

        Args:
            board_code: THS public platecode (e.g. ``"885756"``).
            limit: Max items to return (1-50). Single upstream page; the API
                honors ``size`` directly so no offset loop is needed here.
            board_type: Ignored (kept for manager call-site compatibility).
            **kwargs: Absorbed silently.

        Returns:
            list of dicts: {title, url, publish_date, publish_time,
                            summary, source_domain}.
        """
        n = max(1, min(int(limit), 50))
        payload = json_get(
            _THS_TIMELINE_NEWS_URL,
            params={"marketId": _THS_BOARD_MARKET_ID, "code": board_code, "size": n},
            headers={"User-Agent": THS_UA, "Referer": "https://stockpage.10jqka.com.cn/"},
            timeout=10,
        )
        if not isinstance(payload, dict) or payload.get("status_code") != 0:
            logger.warning(
                f"[ThsFetcher] get_board_news({board_code}) upstream "
                f"status_code={payload.get('status_code') if isinstance(payload, dict) else 'N/A'}"
            )
            return []

        rows = (payload.get("data") or {}).get("newsList") or []
        out: list[dict] = []
        for r in rows:
            url = str(r.get("jumpUrl") or "").strip()
            title = str(r.get("title") or "").strip()
            if not title or not url:
                continue
            publish_date = publish_time = ""
            pt = r.get("publishTime")
            if isinstance(pt, (int, float)) and pt > 0:
                dt = datetime.fromtimestamp(pt / 1000, _THS_TZ)
                publish_date = dt.strftime("%Y-%m-%d")
                publish_time = dt.strftime("%H:%M")
            out.append(
                {
                    "title": title,
                    "url": url,
                    "publish_date": publish_date,
                    "publish_time": publish_time,
                    "summary": str(r.get("summary") or "").strip(),
                    "source_domain": source_domain_from_url(url),
                }
            )
            if len(out) >= n:
                break
        return out


    def get_board_surges(
        self,
        board_code: str,
        *,
        limit: int = 5,
        board_type: str | None = None,
        **kwargs,
    ) -> list[dict]:
        """THS F10 板块炒作周期 — section ``<div class="m_box" id="period">``.

        Each ``<div class="timeline">`` represents one peak 炒作 cycle.
        The涨停 stock list for the cycle is in the SECOND
        ``<p class="flexcont" style="display:none;">`` block (full list —
        the 1st block truncates to 5 visible). We parse the 2nd block for
        the full list.

        Args:
            board_code: THS public platecode.
            limit: Max items (1-12).
            board_type: Optional hint. ``"industry"`` returns ``[]``.
            **kwargs: Absorbed silently.

        Returns:
            list of dicts: {date, board_change_pct, sh_change_pct,
                             limit_up_count, limit_up_stocks, up_count, down_count}.
        """
        from bs4 import BeautifulSoup
        import re as _re

        html = self.get_board_f10_page(board_code, board_type=board_type)
        if not html:
            return []

        # html.parser (not lxml): see get_board_news comment — same mojibake
        # in HTML comments breaks lxml element matching for some boards.
        soup = BeautifulSoup(html, features="html.parser")
        period_box = soup.select_one("#period div.history.clearfix")
        if period_box is None:
            return []

        n = max(1, min(int(limit), 12))
        out: list[dict] = []
        for tl in period_box.select("div.timeline"):
            if len(out) >= n:
                break

            date_span = tl.select_one("span.time")
            date_str = date_span.get_text(strip=True) if date_span else ""

            thead_tr = tl.select_one("thead tr.f14")
            if thead_tr is None:
                continue
            pct_cells = thead_tr.find_all("th")
            board_pct = None
            sh_pct = None
            limit_up_count = None
            if len(pct_cells) >= 3:
                def _pct(cell) -> float | None:
                    # THS F10 markup uses `.upcolor` for positive pct
                    # and `.downcolor` for negative pct (`tests/fixtures/
                    # ths_basic_board_885914_surges.html:68` shows
                    # `<span class="downcolor">-0.27%</span>` — note
                    # `.fallcolor` does NOT exist on this surface).
                    el = cell.select_one(".upcolor, .downcolor")
                    return safe_float(el.get_text(strip=True).rstrip("%")) if el else None

                board_pct = _pct(pct_cells[0])
                sh_pct = _pct(pct_cells[1])

                tip_el = pct_cells[2].select_one(".tip")
                if tip_el:
                    txt = tip_el.get_text(strip=True)
                    num_m = _re.search(r"(\d+)", txt)
                    if num_m:
                        try:
                            limit_up_count = int(num_m.group(1))
                        except (TypeError, ValueError):
                            limit_up_count = None

            # 2nd .flexcont is the full list; fall back to 1st only on
            # structural change.
            flexcont_paras = tl.select("p.flexcont")
            full_para = (
                flexcont_paras[1]
                if len(flexcont_paras) >= 2
                else (flexcont_paras[0] if flexcont_paras else None)
            )
            limit_up_stocks: list[str] = []
            if full_para is not None:
                seen: set[str] = set()
                for a in full_para.select("a.jumpto[code]"):
                    c = (a.get("code") or "").strip()
                    if c and c not in seen:
                        seen.add(c)
                        limit_up_stocks.append(c)

            out.append(
                {
                    "date": date_str,
                    "board_change_pct": board_pct,
                    "sh_change_pct": sh_pct,
                    "limit_up_count": limit_up_count if limit_up_count is not None else 0,
                    "limit_up_stocks": limit_up_stocks,
                    "up_count": None,
                    "down_count": None,
                }
            )

        return out

    # ------------------------------------------------------------------
    # 热点题材 / 北向资金
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
                rows.append(
                    {
                        "time": times[i],
                        "hgt_yi": hgt_val,
                        "sgt_yi": sgt_val,
                    }
                )
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
                publish_time = datetime.fromtimestamp(int(rtime_raw)).strftime("%Y-%m-%d %H:%M:%S")
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
                logger.warning(f"[ThsFetcher] fetch_flash_news: skipping malformed record: {e}")
                continue
        return out

    # ------------------------------------------------------------------
    # 新闻搜索 (News Search) — 同花顺问财 iWenCai 聚合搜索
    # ------------------------------------------------------------------

    # 问财 PC 聚合搜索接口。注意是 www.iwencai.com 域名(同花顺问财),不是
    # 10jqka —— 10jqka 财经页的站内搜索框 (#search_input) 本身就跳转到这里。
    _NEWS_SEARCH_URL = "https://www.iwencai.com/gateway/mobilesearch/comprehensive/search"
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
        title = strip_em_tags(rec["title"])
        extra = rec.get("extra") or {}
        # publish_date 形如 "2026-06-30 18:28:21"; 截到日。
        publish_date = (rec.get("publish_date") or "")[:10]
        snippet = strip_em_tags(rec.get("summary") or "").replace("　", "").strip()
        source_domain = extra.get("host_name") or source_domain_from_url(url)
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
            raise DataFetchError(f"[ThsFetcher] search_news: invalid q (len={len(q) if q else 0})")
        try:
            limit = int(limit)
        except (TypeError, ValueError) as e:
            raise DataFetchError(
                f"[ThsFetcher] search_news: limit must be an integer 1..100 (got {limit!r})"
            ) from e
        if not (1 <= limit <= 100):
            raise DataFetchError(f"[ThsFetcher] search_news: limit must be 1..100 (got {limit})")

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


# ---------------------------------------------------------------------------
# Module-level parse helper for ``ThsFetcher._parse_ths_board_stocks_row``.
#
# Defined at module scope (not as a class static method) so that unit tests
# can import it directly without instantiating the fetcher. The function
# only depends on module-level ``safe_float`` and ``_parse_free_float`` —
# no instance state — so promoting it to module scope is safe and makes
# the contract testable in isolation. Re-attached to the class below as
# a static method so internal callers continue to use ``self._parse_ths_...``.
# ---------------------------------------------------------------------------


def _parse_ths_board_stocks_row(tds: list) -> dict | None:
    """Parse one <tr> from q.10jqka.com.cn board-stocks HTML into a dict.

    14 columns (固定):
    idx 0:  序号 (string, ignored)
    idx 1:  代码 (string)
    idx 2:  名称 (string)
    idx 3:  现价 (float | None)
    idx 4:  涨跌幅 (float | None, %)
    idx 5:  涨跌 (float | None, 元)
    idx 6:  涨速 (float | None, %)
    idx 7:  换手 (float | None, %)
    idx 8:  量比 (float | None)
    idx 9:  振幅 (float | None, %)
    idx 10: 成交额 (int | None, 元)
    idx 11: 流通股 (int | None, 股)
    idx 12: 流通市值 (float | None, 元)
    idx 13: 市盈率 (float | None)

    Returns None when ``td[1]`` (code) is missing — that row is
    malformed and gets skipped silently.

    ``--`` (em-dash) maps to None via ``safe_float`` in core.types.
    """
    if len(tds) < 3:
        return None
    stock_code = tds[1].get_text(strip=True)
    if not stock_code:
        return None
    stock_name = tds[2].get_text(strip=True)
    # Exchange inferred from the code prefix (matches zzshare/eastmoney
    # convention: 'sh' for 沪, 'sz' for 深, '' for 北交所/未知).
    code_prefix = stock_code[:1]
    exchange = (
        "sh" if code_prefix in ("6", "9") else ("sz" if code_prefix in ("0", "3") else "")
    )
    return {
        "stock_code": stock_code,
        "stock_name": stock_name,
        "exchange": exchange,
        "price": safe_float(tds[3].get_text(strip=True)) if len(tds) > 3 else None,
        "change_pct": safe_float(tds[4].get_text(strip=True)) if len(tds) > 4 else None,
        "change_amount": safe_float(tds[5].get_text(strip=True)) if len(tds) > 5 else None,
        "change_speed": safe_float(tds[6].get_text(strip=True)) if len(tds) > 6 else None,
        "turnover_rate": safe_float(tds[7].get_text(strip=True)) if len(tds) > 7 else None,
        "volume_ratio": safe_float(tds[8].get_text(strip=True)) if len(tds) > 8 else None,
        "amplitude": safe_float(tds[9].get_text(strip=True)) if len(tds) > 9 else None,
        "amount": _parse_free_float(tds[10].get_text(strip=True))
        if len(tds) > 10
        else None,
        "free_float_shares": _parse_free_float(tds[11].get_text(strip=True))
        if len(tds) > 11
        else None,
        "float_market_cap": _parse_free_float(tds[12].get_text(strip=True))
        if len(tds) > 12
        else None,
        "pe_ratio": safe_float(tds[13].get_text(strip=True)) if len(tds) > 13 else None,
        # THS field/199112 上游只有 14 列,没有 成交量(手) 字段 — 现有
        # 14 列中 idx 10 是 成交额(元),不是 成交量(股). 因为 BoardStockInfo
        # schema 的 volume 字段语义是 成交量(股),我们必须把 volume 留 None
        # 而不是塞成交额进去 (错把元当成股,会误导调用方).
        "volume": None,
    }


ThsFetcher._parse_ths_board_stocks_row = staticmethod(_parse_ths_board_stocks_row)
