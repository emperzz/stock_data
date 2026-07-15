"""Regression: every JSON response advertises ``charset=utf-8``.

Background (2026-07-15): the default ``JSONResponse`` ships
``Content-Type: application/json`` with no charset. RFC 8259 says JSON *is*
UTF-8, but HTTP/1.1 §3.7.1 still defaults ``text/*`` to ISO-8859-1 when the
charset is missing, and many browsers/curl on Windows apply the same default
to ``application/json``. The user saw the classic UTF-8→Latin-1 mojibake
("ãç¦ç¹...") when curling ``/api/v1/news/morning-briefing`` and other
Chinese-text endpoints.

The fix: ``stock_data.server._UTF8JSONResponse`` is set as the app's
``default_response_class``, so every response that doesn't pick a different
class explicitly gets ``application/json; charset=utf-8``. The actual
response bytes were correct UTF-8 the whole time — the fetcher never had
a bug; this is purely a client-side hint.

This test pins the Content-Type contract for the most likely mojibake
hot-spots: a 422 validation error (always returned without upstream call —
the contract is universal) and a K-line success path (uses the same
default-response-class machinery, so if charset leaks out of K-line it
will leak out of CLS too).
"""

from fastapi.testclient import TestClient


def test_validation_error_422_serves_utf8_charset():
    """A missing required query param triggers 422 — exercises the default
    response class with zero upstream dependency."""
    from stock_data.server import app

    client = TestClient(app)
    # No ?date= → 422 Validation Error
    r = client.get("/api/v1/news/morning-briefing")
    assert r.status_code == 422, r.text
    ct = r.headers.get("content-type", "")
    assert "charset=utf-8" in ct.lower(), (
        f"missing charset=utf-8 in Content-Type: {ct!r} — clients defaulting "
        f"to ISO-8859-1 will see UTF-8 mojibake for Chinese payloads"
    )
    assert "application/json" in ct.lower()


def test_kline_serves_utf8_charset():
    """K-line has no Chinese, but the framework default still applies.

    If the default-response-class wiring ever regresses, this catches it
    without needing CLS network access."""
    from stock_data.server import app

    client = TestClient(app)
    r = client.get("/api/v1/stocks/600519/kline?days=5&frequency=d")
    assert r.status_code == 200, r.text
    ct = r.headers.get("content-type", "")
    assert "charset=utf-8" in ct.lower(), (
        f"missing charset=utf-8 in Content-Type: {ct!r}"
    )
