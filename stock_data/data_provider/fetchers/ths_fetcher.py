"""
同花顺 HTTP API fetcher for signal layer data.

Provides: 热点题材(hot-topics), 北向资金(north-flow), 全球财经快讯(news-flash),
          新闻搜索(news-search), 板块 K 线(board-history)

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
import time
from datetime import date as _date
from datetime import datetime, timedelta
from importlib import resources, util
from urllib.parse import urlparse

from tenacity import (
    before_sleep_log,
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from ..base import BaseFetcher, DataCapability, DataFetchError
from ..utils.http import json_get, json_post
from ..utils.text import strip_em_tags

logger = logging.getLogger(__name__)


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

        Hot-topics / north-flow / flash-news / news-search don't need
        ``py_mini_racer`` / ``bs4`` / ``demjson3`` or the vendored
        ``ths.js`` — they're pure HTTP. But by project convention (see
        ``ZhituFetcher`` and the ``data_provider/manager.py:1002``
        registration loop), an unavailable fetcher is dropped from the
        manager's table — meaning when is_available() returns False,
        the four pure-HTTP THS endpoints lose their backend too.
        Trade-off: one board-K-line dep outage costs four endpoints; in
        our threat model (single akshare+py_mini_racer env per server)
        that's acceptable. If you need fine-grained gating per
        capability, the manager would need a per-capability
        is_available variant — larger refactor, deferred.

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
        source_domain = extra.get("host_name") or urlparse(url).netloc
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
