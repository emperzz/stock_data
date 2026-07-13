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
import time
from datetime import date as _date
from datetime import datetime, timedelta
from importlib import resources, util

from tenacity import (
    before_sleep_log,
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from ..base import BaseFetcher, DataCapability, DataFetchError
from ..core.types import safe_float
from ..persistence.board import THS_CONCEPT_SUBTYPE, THS_INDUSTRY_SUBTYPE
from ..utils.http import json_get, json_post
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

# 个股新闻 / 个股公告 — basic.10jqka.com.cn/fuyao/info/company/v1/...
_THS_NEWS_URL = "https://basic.10jqka.com.cn/fuyao/info/company/v1/news"
_THS_NOTICE_URL = "https://basic.10jqka.com.cn/basicapi/notice/pub"
_THS_BASIC_HEADERS = {
    "User-Agent": THS_UA,
    "Referer": "https://basic.10jqka.com.cn/astockpc/astockmain/index.html",
}

_THS_BOARD_KLINE_URL = "https://d.10jqka.com.cn/v4/line/bk_{inner}/01/{year}.js"
_THS_BOARD_FREQ_MAP: dict[str, int] = {"d": 1}  # THS upstream only ships daily
# Year-loop cap (A6 from PR2 review).  Each year carries a 15s timeout
# worst case; 17-year queries at 250s+ are a stability risk and a DoS
# surface for callers (the route layer has no start/end span limit). The
# fetcher is sequential on purpose — concurrent year-fetch triggers
# push2-style rate limits on this endpoint.
_MAX_YEAR_SPAN = 10


def _resolve_ths_date_range(
    start_date: str | None,
    end_date: str | None,
    days: int,
) -> tuple[_date, _date]:
    """Resolve and validate ``(start_date, end_date)`` for the year loop.

    Mirrors ``EastMoneyFetcher._board_history_range_days`` semantics so
    f-string path messages look the same; returns ``(start_d, end_d)``
    both as ``date`` objects. Both bounds are stripped before parsing
    so user-supplied whitespace (e.g. ``" 2026-01-01 "``) is accepted,
    matching EastMoney's behavior.

    Raises:
        ValueError: a non-empty bound fails YYYY-MM-DD parsing, or
            ``end_date`` is strictly before ``start_date``. The route
            layer's ``@map_errors`` maps ``ValueError → 400`` (bad
            request), matching EastMoney's contract. ``DataFetchError``
            is reserved for upstream failures (year-span cap, all-empty
            gate, clid resolution, etc.).
    """
    try:
        end_d = (
            datetime.strptime((end_date or "").strip(), "%Y-%m-%d").date()
            if end_date
            else _date.today()
        )
    except (TypeError, ValueError) as exc:
        raise ValueError(
            f"[ThsFetcher] get_board_history: end_date={end_date!r} not YYYY-MM-DD"
        ) from exc
    if start_date:
        try:
            start_d = datetime.strptime(start_date.strip(), "%Y-%m-%d").date()
        except (TypeError, ValueError) as exc:
            raise ValueError(
                f"[ThsFetcher] get_board_history: start_date={start_date!r} not YYYY-MM-DD"
            ) from exc
    else:
        start_d = end_d - timedelta(days=days)
    if start_d > end_d:
        raise ValueError(
            f"[ThsFetcher] get_board_history: start_date {start_date!r} > end_date {end_date!r}"
        )
    return start_d, end_d


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
        - ``bs4`` (BeautifulSoup for concept-board clid resolution)
        - ``demjson3`` (lenient JSON parser for upstream JS-style bodies)
        - ``ths_assets/ths.js`` (vendored JS blob)

        Hot-topics / north-flow / flash-news / news-search don't need
        any of these (pure HTTP), but by project convention
        (``data_provider/manager.py:1002``) an unavailable fetcher is
        dropped from the manager's table — meaning a missing dep costs
        all four pure-HTTP endpoints too. This is a deliberate
        trade-off; see :meth:`is_available` docstring.
        """
        missing: list[str] = []
        for mod in ("py_mini_racer", "bs4", "demjson3"):
            if util.find_spec(mod) is None:
                missing.append(mod)
        if missing:
            return False, (
                f"{ThsFetcher.name}.board_history unavailable: "
                f"missing deps {sorted(missing)} "
                f"(pip install py-mini-racer beautifulsoup4 demjson3)"
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

        Six pure-HTTP THS endpoints (hot-topics / north-flow / flash-news
        / news-search / stock-news / announcements) don't need
        ``py_mini_racer`` / ``bs4`` / ``demjson3`` or the vendored
        ``ths.js``. But by project convention (see ``ZhituFetcher`` and
        the ``data_provider/manager.py:1002`` registration loop), an
        unavailable fetcher is dropped from the manager's table —
        meaning when is_available() returns False, the six pure-HTTP
        THS endpoints lose their backend too. Trade-off: one
        board-K-line dep outage costs six endpoints; in our threat
        model (single akshare+py_mini_racer env per server) that's
        acceptable. If you need fine-grained gating per capability,
        the manager would need a per-capability is_available variant —
        larger refactor, deferred.

        The reverse is also worth catching: a process where someone
        deleted ``ths_assets/ths.js`` shouldn't silently drop a
        fetcher capability that does work.
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
        """
        import requests

        return requests.get(url, headers=headers or {"User-Agent": THS_UA}, timeout=timeout)

    def _resolve_ths_concept_clid(self, slug: str) -> str | None:
        """Fetch the concept-board HTML page and extract the inner `clid` (e.g. T000267467).

        Uses BeautifulSoup's attribute dict lookup rather than a regex so a
        different attribute order on the upstream HTML (e.g. ``value="..."``
        before ``id="clid"``) doesn't silently break clid extraction.

        Returns the clid string, or None if not found / on any error.
        Logs at WARNING on network failure or HTML parse error.
        """
        url = _CONCEPT_DETAIL_URL.format(slug=slug)
        headers = {"User-Agent": THS_UA, "Cookie": f"v={self._v_token()}"}
        try:
            r = self._http_get(url, headers=headers, timeout=10)
        except Exception as e:
            logger.warning(f"[ThsFetcher] concept clid fetch failed for {slug}: {e}")
            return None
        try:
            from bs4 import BeautifulSoup

            soup = BeautifulSoup(r.text or "", features="lxml")
            node = soup.find("input", attrs={"id": "clid"})
        except Exception as e:
            logger.warning(f"[ThsFetcher] soup parse failed for {slug}: {e}")
            return None
        if node is None:
            return None
        # node.get() returns None when the attribute is absent — different
        # from `node["value"]` which would KeyError. Defensive — the upstream
        # form does carry the value, but an HTML reshuffle that drops it
        # shouldn't 500 the fetcher.
        return node.get("value")

    @staticmethod
    def _parse_ths_kline_body(body: str) -> list[dict]:
        """Parse a `d.10jqka.com.cn/v4/line/bk_*/01/{year}.js` response.

        The upstream response is `var v_XXXX={"data": "<csv>"};`. The `data`
        field is `;`-separated rows; each row is 11 comma-separated fields:
        `date, open, high, low, close, volume, amount, amp, pct_chg, change_amt, turnover_rate`.
        Some upstream variants return 12 columns (trailing null); we accept
        both and consume only the first 7 (canonical K-line subset).

        JSON extraction is positional (find first ``{`` + strip trailing
        ``;``) instead of a greedy regex, so multi-var upstream variants
        parse correctly. ``demjson3`` (Python 3 port — the original ``demjson``
        doesn't install on 3.10+) is more lenient than ``json`` on JS-style
        literals (e.g. unquoted keys are still rare but possible upstream).

        Returns canonical row dicts with keys: date, open, high, low, close,
        volume, amount. Other fields (amp, pct_chg, change_amt, turnover_rate)
        are dropped — THS upstream's last 4 fields aren't standardized. Empty
        list on parse failure / empty data.
        """
        if not body:
            return []
        # Locate the FIRST complete JSON object anywhere in ``body``.
        # ``json.JSONDecoder().raw_decode(s, idx)`` is the only
        # strictly-positional extractor that respects nested braces — it
        # walks the string from ``idx`` and returns ``(obj, end_pos)`` of
        # the first well-formed JSON object. Replaces both the old greedy
        # ``re.search(r"\{[\s\S]*\}", body)`` AND the
        # slightly-buggy ``body.find("}", start+1)`` we tried first.
        idx = body.find("{")
        if idx == -1:
            return []
        try:
            import json as _json

            decoder = _json.JSONDecoder()
            payload, _ = decoder.raw_decode(body, idx)
        except (_json.JSONDecodeError, ValueError):
            # demjson3 is more lenient than stdlib on JS-style literals
            # (unquoted keys, trailing commas). Fall back to a manual
            # brace-balance scan + demjson3 decode for those variants.
            try:
                import demjson3 as demjson_lib

                start = idx
                depth = 0
                end = -1
                for i, ch in enumerate(body[start:], start=start):
                    if ch == "{":
                        depth += 1
                    elif ch == "}":
                        depth -= 1
                        if depth == 0:
                            end = i
                            break
                if end == -1:
                    return []
                payload = demjson_lib.decode(body[start : end + 1])
            except Exception:
                return []
        data = payload.get("data") or ""
        if not data:
            return []
        out: list[dict] = []
        for row in data.split(";"):
            row = row.strip()
            if not row:
                continue
            parts = row.split(",")
            if len(parts) < 7:
                continue
            try:
                out.append(
                    {
                        "date": parts[0],
                        "open": float(parts[1]),
                        "high": float(parts[2]),
                        "low": float(parts[3]),
                        "close": float(parts[4]),
                        "volume": int(float(parts[5])),
                        "amount": float(parts[6]),
                    }
                )
            except (TypeError, ValueError):
                continue
        return out

    # ------------------------------------------------------------------
    # 板块 K 线 (Board K-Line) — concept + industry
    # ------------------------------------------------------------------

    def _fetch_ths_board_year(self, inner_code: str, year: int) -> str:
        """Fetch one year of THS board K-line JS body. Returns "" on failure.

        A non-2xx response (typically 403 when the v-token has been rotated
        upstream, or 5xx during upstream incidents) is treated as failure:
        we log and return ``""`` so the all-empty gate in
        :meth:`get_board_history` can surface the upstream issue as 503.
        Without this check, a 403 HTML body would be passed to the JSON
        parser and silently return zero rows (no error, no signal) — the
        exact bug the all-empty gate was supposed to catch.

        Per-year 4xx/5xx does not abort the full request — other years may
        still succeed. Only the all-empty case is fatal. This matches
        cninfo_fetcher's "be forgiving on partial failure" pattern.
        """
        url = _THS_BOARD_KLINE_URL.format(inner=inner_code, year=year)
        headers = {
            "User-Agent": THS_UA,
            "Referer": "http://q.10jqka.com.cn",
            "Host": "d.10jqka.com.cn",
            "Cookie": f"v={self._v_token()}",
        }
        try:
            r = self._http_get(url, headers=headers, timeout=15)
            if not (200 <= r.status_code < 300):
                logger.warning(
                    f"[ThsFetcher] board kline year={year} ({inner_code}) "
                    f"HTTP {r.status_code} ({len(r.content)}B body)"
                )
                return ""
            return r.text or ""
        except Exception as e:
            logger.warning(f"[ThsFetcher] board kline year={year} ({inner_code}) failed: {e}")
            return ""

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
        """THS concept/industry board K-line via d.10jqka.com.cn.

        Args:
            board_code: THS board slug (concept: e.g. ``301558``; industry: e.g.
                ``881270``). NOT the inner `clid` — that's resolved internally
                for concept boards via the q.10jqka.com.cn HTML scrape.
            frequency: Only ``"d"`` is supported. THS upstream returns daily only.
            board_type: ``"concept"`` or ``"industry"`` — required. Concept slugs
                are remapped to inner clid; industry slugs map directly.
            days: Used when ``start_date`` not given; the year range is
                ``[today - days, today]`` capped at the full available history.
            start_date / end_date: ``YYYY-MM-DD`` — wins over ``days``.

        Returns:
            list[dict] — sorted oldest → newest. Keys: date, open, high, low,
            close, volume, amount. Empty list if individual year fetches
            return empty bodies (e.g. a brand-new board with no history yet);
            a Hard error is raised when every requested year fails (e.g.
            cached v-token expired) — see Raises.

        Raises:
            DataFetchError: frequency not in ``_THS_BOARD_FREQ_MAP``;
                board_type missing or invalid; concept clid resolution
                returns None; every requested year fetch failed
                (likely upstream auth problem — investigate the v-token
                / d.10jqka.com.cn).
            ValueError: year span exceeds ``_MAX_YEAR_SPAN``;
                date bound malformed or whitespace-padded past parse;
                ``end_date < start_date``. These are caller-input
                errors — the route layer's ``@map_errors`` maps
                ``ValueError → 400``. Aligns with EastMoney's contract
                so the same bad input gets the same status code
                regardless of which source serves the request.
        """
        if not board_type:
            raise DataFetchError(
                "[ThsFetcher] get_board_history: board_type is required "
                "(must be 'concept' or 'industry')"
            )
        freq_key = (frequency or "d").lower()
        if freq_key not in _THS_BOARD_FREQ_MAP:
            raise DataFetchError(
                f"[ThsFetcher] get_board_history: unsupported frequency "
                f"{frequency!r}; THS upstream is daily-only"
            )

        # Year range — fail fast on bad bounds (reversed dates, malformed,
        # past-the-end dates) so the year loop doesn't silently loop weird
        # windows. Mirrors the validation in EastMoneyFetcher.
        # Tuple returned from _resolve_ths_date_range is (start_d, end_d).
        start_d, end_d = _resolve_ths_date_range(start_date, end_date, days)
        start_year = start_d.year
        end_year = end_d.year
        n_years = end_year - start_year + 1
        if n_years > _MAX_YEAR_SPAN:
            raise ValueError(
                f"[ThsFetcher] get_board_history year span "
                f"({n_years}y) > {_MAX_YEAR_SPAN}; "
                f"narrow start_date/end_date or call repeatedly."
            )

        # Resolve inner code
        if board_type == "concept":
            clid = self._resolve_ths_concept_clid(board_code)
            if not clid:
                raise DataFetchError(
                    f"[ThsFetcher] could not resolve concept clid for slug={board_code!r}"
                )
            inner = clid
        elif board_type == "industry":
            inner = board_code
        else:
            raise DataFetchError(
                f"[ThsFetcher] get_board_history: board_type must be "
                f"'concept' or 'industry' (got {board_type!r})"
            )

        # Fetch each year sequentially (concurrent year-fetch triggers
        # push2-style rate limits on this endpoint — keep it serial).
        # Track success vs failure so we can distinguish "no history yet"
        # (board is brand-new) from "everything is broken" (auth failure).
        rows: list[dict] = []
        bodies: dict[int, str] = {}
        for year in range(start_year, end_year + 1):
            body = self._fetch_ths_board_year(inner, year)
            bodies[year] = body
        # All-empty is a real failure surface: callers can't tell from an
        # empty list whether the board has no history (legit) or every
        # request 4xx'd (ops bug). Surface it.
        if all(b == "" for b in bodies.values()):
            raise DataFetchError(
                f"[ThsFetcher] get_board_history: all {n_years} year-fetches "
                f"returned empty for inner={inner!r}; check v-token, "
                f"d.10jqka.com.cn reachability, and that the board slug "
                f"({board_code!r}) is correct. See WARNING logs above."
            )
        for body in bodies.values():
            if not body:
                continue
            rows.extend(self._parse_ths_kline_body(body))

        # Date range filter (string comparison works for YYYY-MM-DD)
        start_str = start_d.strftime("%Y-%m-%d")
        end_str = end_d.strftime("%Y-%m-%d")
        rows = [r for r in rows if start_str <= r["date"] <= end_str]

        # Sort ascending
        rows.sort(key=lambda r: r["date"])
        return rows

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
            "User-Agent": THS_UA,
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
            "User-Agent": THS_UA,
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
                "code": str(r.get("quote_code", "")).strip(),
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
            url = self._THS_INDUSTRY_SUMMARY_URL.format(page=page)
            headers = {
                "User-Agent": THS_UA,
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
        headers = {"User-Agent": THS_UA, "Cookie": f"v={self._v_token()}"}
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
