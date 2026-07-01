"""
Unified HTTP utility layer for fetchers.

Centralises the boilerplate that was previously copy-pasted across
ZhituFetcher, ThsFetcher, BaiduFetcher, and CninfoFetcher:

  try:
      resp = requests.get(url, params=params, headers=headers, timeout=timeout)
      resp.raise_for_status()
      data = resp.json()
  except requests.exceptions.Timeout as e:
      logger.warning(...)
  except requests.exceptions.RequestException as e:
      logger.warning(...)
  except ValueError as e:
      logger.warning(...)

The unified helper does the same work in one line at the call site and
maps network/HTTP/parse errors onto ``DataFetchError`` so the manager's
failover loop can continue.

Design notes:

- UA rotation: a small pool of desktop Chrome UAs that anti-bot
  heuristics won't flag. Picked once per request (cheap; the pool has 4
  entries). Fetchers that need a *fixed* UA (Cninfo's POST requires a
  desktop UA for CSRF, Baidu uses Bearer auth header not browser UA)
  can override via the ``headers`` parameter.
- EastMoneyFetcher is **not** migrated — it uses ``curl_cffi`` for TLS
  fingerprinting and cannot be replaced by ``requests``. The Zhitu
  fetcher's 8 raw ``requests.get`` calls are the primary beneficiary.
- ``urllib.request`` callers (TencentFetcher, YfinanceFetcher) are NOT
  migrated — Tencent decodes GBK manually and Yfinance's URL opener is
  called by the yfinance SDK itself, both out of scope.
- Test patchability: ``json_get`` defaults to the bare ``requests.get``
  function so tests can monkeypatch
  ``stock_data.data_provider.utils.http.requests.get`` directly.
  Pass an explicit ``session=`` to opt into connection pooling.
"""

from __future__ import annotations

import logging
import random
from typing import Any

import requests

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# UA pool — desktop Chrome strings; rotated per request to avoid
# fingerprint-based throttling on Chinese financial endpoints.
# ---------------------------------------------------------------------------
_UA_POOL: tuple[str, ...] = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/118.0.0.0 Safari/537.36",
)


def random_ua() -> str:
    """Return a random UA from the pool. Cheap (random.choice on 4 entries)."""
    return random.choice(_UA_POOL)


# ---------------------------------------------------------------------------
# Unified JSON GET — primary entry point for fetchers.
# ---------------------------------------------------------------------------
def json_get(
    url: str,
    params: dict | None = None,
    *,
    timeout: int = 10,
    headers: dict | None = None,
    session: requests.Session | None = None,
) -> Any:
    """GET ``url`` and return the parsed JSON body.

    Centralises the timeout / HTTP / parse error handling that was
    previously written out 8+ times in ZhituFetcher and twice each in
    Ths/Baidu/Cninfo. Errors are wrapped in ``DataFetchError`` so the
    manager's failover loop can transparently move on to the next
    fetcher.

    Args:
        url: Full URL to fetch.
        params: Optional query-string parameters.
        timeout: Per-request timeout in seconds (default 10s).
        headers: Extra headers; a random UA from the pool is always
            injected unless ``headers`` already has its own ``User-Agent``.
        session: Optional pre-configured ``requests.Session``. Defaults
            to ``None``, in which case ``json_get`` uses the bare
            ``requests.get`` function so that tests can monkeypatch
            ``stock_data.data_provider.utils.http.requests.get`` and
            intercept the call. Pass an explicit session to opt into
            keep-alive connection pooling.

    Returns:
        Parsed JSON body (``dict`` / ``list`` / scalar), or ``None`` when
        the caller wants to distinguish "no data" from "exception".

    Raises:
        DataFetchError: on network timeout, HTTP error status, JSON
            parse failure, or any other ``requests.RequestException``.
    """
    # Local import — avoids circular dependency at module load time.
    from ..base import DataFetchError

    hdrs: dict = {"User-Agent": random_ua()}
    if headers:
        hdrs.update(headers)

    try:
        if session is not None:
            resp = session.get(url, params=params, headers=hdrs, timeout=timeout)
        else:
            # Direct module-level requests.get — patchable by tests at
            # ``stock_data.data_provider.utils.http.requests.get``.
            resp = requests.get(url, params=params, headers=hdrs, timeout=timeout)
        resp.raise_for_status()
        return resp.json()
    except requests.exceptions.Timeout as e:
        raise DataFetchError(f"Timeout fetching {url}: {e}") from e
    except requests.exceptions.HTTPError as e:
        status = getattr(resp, "status_code", "?")
        raise DataFetchError(f"HTTP {status} from {url}: {e}") from e
    except requests.exceptions.RequestException as e:
        raise DataFetchError(f"Request failed for {url}: {e}") from e
    except (ValueError, TypeError) as e:
        raise DataFetchError(f"Invalid JSON from {url}: {e}") from e


# ---------------------------------------------------------------------------
# Unified JSON POST — companion to json_get for POST endpoints.
# ---------------------------------------------------------------------------
def json_post(
    url: str,
    json_body: Any,
    *,
    timeout: int = 10,
    headers: dict | None = None,
    session: requests.Session | None = None,
) -> Any:
    """POST ``url`` with a JSON body and return the parsed JSON response.

    Mirror of :func:`json_get` for POST endpoints (e.g. ThsFetcher's
    iWenCai search, CninfoFetcher announcements). Errors are wrapped in
    ``DataFetchError`` so the manager's failover loop can continue.

    Args:
        url: Full URL to POST.
        json_body: JSON-serialisable body (passed as ``json=`` to requests).
        timeout: Per-request timeout in seconds (default 10s).
        headers: Extra headers; a random UA from the pool is always
            injected unless ``headers`` already has its own ``User-Agent``.
        session: Optional pre-configured ``requests.Session``. Defaults
            to ``None`` (bare ``requests.post``; patchable by tests at
            ``stock_data.data_provider.utils.http.requests.post``).

    Returns:
        Parsed JSON body (``dict`` / ``list`` / scalar).

    Raises:
        DataFetchError: on network timeout, HTTP error status, JSON
            parse failure, or any other ``requests.RequestException``.
    """
    from ..base import DataFetchError

    hdrs: dict = {"User-Agent": random_ua()}
    if headers:
        hdrs.update(headers)

    try:
        if session is not None:
            resp = session.post(url, json=json_body, headers=hdrs, timeout=timeout)
        else:
            resp = requests.post(url, json=json_body, headers=hdrs, timeout=timeout)
        resp.raise_for_status()
        return resp.json()
    except requests.exceptions.Timeout as e:
        raise DataFetchError(f"Timeout posting to {url}: {e}") from e
    except requests.exceptions.HTTPError as e:
        status = getattr(resp, "status_code", "?")
        raise DataFetchError(f"HTTP {status} from {url}: {e}") from e
    except requests.exceptions.RequestException as e:
        raise DataFetchError(f"Request failed for {url}: {e}") from e
    except (ValueError, TypeError) as e:
        raise DataFetchError(f"Invalid JSON from {url}: {e}") from e


__all__ = ["json_get", "json_post", "random_ua"]
