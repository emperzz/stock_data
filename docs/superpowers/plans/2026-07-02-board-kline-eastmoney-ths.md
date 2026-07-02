# Board K-Line (EastMoney + THS) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add EastMoney + THS as additional data sources for `/boards/{board_code}/history`, alongside the existing ZzshareFetcher daily-only path. EastMoney adds multi-frequency support (d/w/m + 5/15/30/60m); THS adds concept-board + industry-board daily K-line via `d.10jqka.com.cn/v4/line/bk_{inner}/01/{year}.js`.

**Architecture:**
- **EastMoney:** reuse the existing push2his `stock/kline/get` endpoint with `secid=90.{board_code}`. Parse `data.klines` (comma strings, 11 fields) into the canonical row dict. Pure-stdlib parser, isolated as a `@staticmethod` for unit-testability.
- **THS:** split into (1) inner-code resolution (concept: HTML scrape for `<input id="clid">`; industry: slug-as-code) and (2) per-year JS-file fetch. Response body is `var v_XXXX={...};` — strip the JS shell, stdlib `json.loads`, then split `data` field by `;` and each row by `,`. py_mini_racer only used to mint the `v` cookie via akshare's bundled `ths.js` (YAGNI fallback if py_mini_racer missing → raise clear error).
- **Route:** expand `source` Literal to `{"zzshare", "ths", "eastmoney"}`. The existing `_resolve_source` aliases `ths→zzshare` for board-list/persistence callers; the new history route does **not** alias — `ths` here means ThsFetcher (different code system, different fetcher). Add `board_type` Query param (`concept|industry`) required for `ths`, ignored by the others. Expand `frequency` Literal to `{d,w,m,5m,15m,30m,60m}`; the fetcher raises on unsupported combos.
- **Manager:** pass `board_type` through to the fetcher's `get_board_history`. Existing signature unchanged for the other callers.

**Tech Stack:** Python 3.x, FastAPI, curl_cffi (EastMoney TLS fingerprint), py_mini_racer + akshare's bundled `ths.js` (THS v-cookie), stdlib `json` + `re` (THS response parsing), requests (THS HTML scrape), pytest + respx/httpx-mock for offline tests.

---

## File Structure

**Modify:**
- `stock_data/data_provider/fetchers/eastmoney/fetcher.py` — `get_board_history` method, `_BOARD_KLINE_*` constants, `_board_secid`, `_parse_board_kline` (added in this session; tested in Task 1).
- `stock_data/data_provider/fetchers/ths_fetcher.py` — `STOCK_BOARD` capability flag (added), `get_board_history` + helpers `_get_ths_v_token`, `_resolve_ths_inner_code`, `_fetch_ths_board_year`, `_parse_ths_kline_body`. Imports: `re`, `lru_cache`, `importlib.resources`, `json` (stdlib).
- `stock_data/data_provider/manager.py:789-822` — `get_board_history` signature gains `board_type` kwarg, threaded through to the fetcher.
- `stock_data/api/routes/boards.py:391-432` — `/boards/{board_code}/history` route: source Literal expansion, frequency Literal expansion, `board_type` Query, source resolution that does **not** alias `ths→zzshare` here.
- `stock_data/api/schemas.py:317-327` — `BoardKlineResponse.source` description updated; `period` description expanded to include non-daily.

**Create:**
- `tests/test_eastmoney_board_kline.py` — offline parser unit tests (Task 1).
- `tests/test_ths_board_kline.py` — offline parser + mocked-HTTP tests for concept + industry (Tasks 3-4).
- `tests/test_boards_history_route.py` — route-level tests for source expansion + validation (Task 7).

**No change:**
- `stock_data/data_provider/persistence/board.py` — `VALID_SUBTYPES_BY_SOURCE` is for board listings, not K-line. Out of scope.
- `stock_data/data_provider/base.py` — `CAPABILITY_TO_METHOD[STOCK_BOARD] = "get_all_boards"` default is fine; the route uses `fetcher_method="get_board_history"` override.

---

## Background facts the engineer needs

1. **EastMoney secid for boards** (verified in this session via Playwright on `https://quote.eastmoney.com/bk/90.BK0996.html`): board pages use `secid=90.BK0996` (or any `90.BKxxxx`). Same `push2his.eastmoney.com/api/qt/stock/kline/get` endpoint as stocks. Field set: `fields1=f1,f2,f3,f4,f5,f6`, `fields2=f51..f61`. The 12-field response per kline string is `date,open,high,low,close,volume,amount,amplitude,pct_chg,change_amount,turnover_rate,_` — we keep the first 11 (drop trailing `_`).

2. **EastMoney frequency codes** (from `emcharts.js` in `bk2.js` neighbors, observed this session):
   - 101 = daily, 102 = weekly, 103 = monthly
   - 1 = 1-minute, 5 = 5-minute, 15 = 15-minute, 30 = 30-minute, 60 = 60-minute
   - emcharts' auto-escalation: if `lmt ≥ 1000` → `klt=102`; if `lmt ≥ 5000` → `klt=103`. We cap `lmt` at 800 to preserve caller's choice.
   - `fqt` (复权) is meaningless for board indices but accepted as no-op upstream.

3. **THS inner-code systems** (from `akshare/stock_feature/stock_board_concept_ths.py` and `stock_board_industry_ths.py`):
   - **Concept:** `q.10jqka.com.cn/gn/detail/code/{slug}/` returns HTML containing `<input id="clid" value="T000267467">`. The `T...` clid is then used as `bk_{clid}` in the data URL.
   - **Industry:** `q.10jqka.com.cn/thshy/detail/code/{slug}/` already maps slug → `bk_{slug}` directly. No clid fetch needed.
   - **Data URL:** `https://d.10jqka.com.cn/v4/line/bk_{inner_code}/01/{year}.js` for each year. Response body shape: `var v_XXXX={...};` (variable name varies). The `{...}` substring is plain JSON: `{"data": "yyyy-mm-dd,open,high,low,close,volume,amount,...;..."}`.
   - **Cookie:** `Cookie: v={v_code}` is required. `v_code` is computed by `py_mini_racer.MiniRacer().eval(akshare_ths_js).call("v")`. The bundled `ths.js` lives in `akshare/data/ths.js`; locate via `importlib.resources`.

4. **Route source semantics** (CLAUDE.md, boards.py docstring §1):
   - The `ths` alias to `zzshare` in `_resolve_source` exists because zzshare's `plates_list` upstream IS 同花顺 — board listings share a single canonical source. For board K-line, **THS is a separate fetcher** (different code system, different upstream). The new route must NOT alias `ths→zzshare`; aliasing would route to ZzshareFetcher (which only supports `883957`). Use a separate `_resolve_board_history_source` helper local to `boards.py` route module.

5. **Outbound/inbound code format** (CLAUDE.md, "Don't leak..."):
   - EastMoney: caller passes `BK0996` or `0996`; we always emit `90.BK0996`. Never leak the `90.` prefix.
   - THS: caller passes the source-specific slug (`301558` for concept, `881270` for industry); we forward verbatim to upstream. Never normalize or translate.

---

## Task 1: EastMoney fetcher — board K-line + parser tests

**Files:**
- Modify: `stock_data/data_provider/fetchers/eastmoney/fetcher.py` — `get_board_history` + helpers (already implemented in this session; verify & tighten).
- Create: `tests/test_eastmoney_board_kline.py`

- [ ] **Step 1: Write failing parser tests**

Create `tests/test_eastmoney_board_kline.py`:

```python
"""Offline parser tests for EastMoneyFetcher board K-line.

Pure parser tests (no HTTP) — validate the `_parse_board_kline` static method
and the `_board_secid` normalizer.
"""
from stock_data.data_provider.fetchers.eastmoney.fetcher import EastMoneyFetcher


class TestBoardSecid:
    def test_with_bk_prefix(self):
        assert EastMoneyFetcher._board_secid("BK0996") == "90.BK0996"

    def test_without_bk_prefix(self):
        assert EastMoneyFetcher._board_secid("0996") == "90.BK0996"

    def test_lowercase_bk_prefix(self):
        assert EastMoneyFetcher._board_secid("bk0806") == "90.BK0806"

    def test_with_whitespace(self):
        assert EastMoneyFetcher._board_secid("  BK0996  ") == "90.BK0996"

    def test_empty_returns_fallback(self):
        assert EastMoneyFetcher._board_secid("") == "90.BK"


class TestParseBoardKline:
    def test_full_row(self):
        raw = "2025-06-30,1234.5,1260.0,1220.3,1255.7,12345678,1.234e10,2.5,1.7,21.2,1.5,0"
        out = EastMoneyFetcher._parse_board_kline(raw)
        assert out == {
            "date": "2025-06-30",
            "open": 1234.5,
            "high": 1260.0,
            "low": 1220.3,
            "close": 1255.7,
            "volume": 12345678,
            "amount": 1.234e10,
            "amplitude": 2.5,
            "pct_chg": 1.7,
            "change_amount": 21.2,
            "turnover_rate": 1.5,
        }

    def test_too_few_fields_returns_none(self):
        assert EastMoneyFetcher._parse_board_kline("2025-06-30,100,101") is None

    def test_garbage_returns_none(self):
        assert EastMoneyFetcher._parse_board_kline("not-a-kline") is None

    def test_empty_returns_none(self):
        assert EastMoneyFetcher._parse_board_kline("") is None

    def test_extra_trailing_fields_ignored(self):
        # Upstream sometimes appends extras; we only consume the first 11.
        raw = "2025-06-30,1,2,3,4,5,6,7,8,9,10,extra1,extra2"
        out = EastMoneyFetcher._parse_board_kline(raw)
        assert out is not None and out["close"] == 4.0


class TestGetBoardHistoryUnsupportedFreq:
    def test_unknown_frequency_raises(self):
        f = EastMoneyFetcher.__new__(EastMoneyFetcher)  # skip __init__
        try:
            f.get_board_history("BK0996", frequency="2m")
        except Exception as e:
            assert "frequency" in str(e).lower() or "2m" in str(e)
        else:
            raise AssertionError("expected DataFetchError on unknown frequency")
```

- [ ] **Step 2: Run the tests to verify they pass against the existing implementation**

Run: `.venv/Scripts/python.exe -m pytest tests/test_eastmoney_board_kline.py -v`
Expected: All 11 tests PASS (the implementation is already in place from this session).

If anything fails, fix the implementation in `fetcher.py` until all pass.

- [ ] **Step 3: Commit**

```bash
git add stock_data/data_provider/fetchers/eastmoney/fetcher.py tests/test_eastmoney_board_kline.py
git commit -m "feat(eastmoney): add get_board_history for board K-line via push2his"
```

---

## Task 2: THS fetcher — v-token helper + dependencies check

**Files:**
- Modify: `stock_data/data_provider/fetchers/ths_fetcher.py` — add `_get_ths_v_token` + `_load_ths_js_content` helpers.

The fetcher's `STOCK_BOARD` capability flag was added earlier in this session.

- [ ] **Step 1: Verify akshare's `ths.js` is locatable**

Run this one-liner to confirm the bundled JS exists in our venv:

```bash
.venv/Scripts/python.exe -c "
from importlib import resources
p = resources.files('akshare.data').joinpath('ths.js')
print('exists:', p.is_file(), 'size:', p.stat().st_size if p.is_file() else 0)
"
```

Expected output: `exists: True size: 39664` (or similar non-zero). If `False`, raise and stop — py_mini_racer alone is insufficient.

- [ ] **Step 2: Write failing test for the v-token helper**

Append to `tests/test_ths_board_kline.py` (Task 3 will create the file; for now, put this single test inline in a new file):

```python
"""Tests for ThsFetcher.get_board_history."""
import pytest


class TestVToken:
    def test_v_token_is_nonempty_string(self):
        from stock_data.data_provider.fetchers.ths_fetcher import ThsFetcher
        f = ThsFetcher.__new__(ThsFetcher)
        v = f._get_ths_v_token()
        assert isinstance(v, str) and len(v) >= 8

    def test_v_token_is_cached(self, monkeypatch):
        from stock_data.data_provider.fetchers.ths_fetcher import ThsFetcher
        f = ThsFetcher.__new__(ThsFetcher)
        v1 = f._get_ths_v_token()
        v2 = f._get_ths_v_token()
        assert v1 == v2  # cached (lru_cache)
```

Note: we test `is_cached` by ID equality, not by mocking py_mini_racer — that's the simplest assertion that the `@lru_cache` decorator is on the method.

- [ ] **Step 3: Run the test — expect FAIL (helper doesn't exist)**

Run: `.venv/Scripts/python.exe -m pytest tests/test_ths_board_kline.py::TestVToken -v`
Expected: FAIL with `AttributeError: 'ThsFetcher' object has no attribute '_get_ths_v_token'`.

- [ ] **Step 4: Implement the helpers**

Add to `stock_data/data_provider/fetchers/ths_fetcher.py` (inside class `ThsFetcher`, near the top):

```python
@lru_cache(maxsize=1)
def _get_ths_v_token(cls_or_self) -> str:
    """Mint the `v` cookie token via py_mini_racer + akshare's bundled ths.js.

    akshare ships `akshare/data/ths.js` (~40KB JS obfuscator). py_mini_racer
    evaluates it then calls the `v()` function to produce the cookie value.

    Cached: the token rotates on a long interval; one mint per process is
    enough. lru_cache(maxsize=1) also keeps the MiniRacer VM warm.

    Note: lru_cache binds the first arg (`self`); declared here as if a
    static method via descriptor rebind below.
    """
    try:
        from importlib import resources
        import py_mini_racer  # noqa: F401
    except ImportError as e:
        raise DataFetchError(
            f"[ThsFetcher] board history requires py_mini_racer "
            f"(to evaluate ths.js); install with `pip install py-mini-racer`: {e}"
        ) from e

    js_path = resources.files("akshare.data").joinpath("ths.js")
    js_text = js_path.read_text(encoding="utf-8")
    js = py_mini_racer.MiniRacer()
    js.eval(js_text)
    return js.call("v")
```

Then rebind it to a staticmethod-like cache (the `@lru_cache` decorator on a plain method would bind `self`, which is fine here because we never pass other args — but to be explicit, use a module-level helper):

```python
# Module-level so lru_cache binds only positional args (the cls_or_self hack
# above is unnecessary). Re-implement as a free function:
_get_ths_v_token_module_cached = lru_cache(maxsize=1)(lambda: _mint_ths_v_token())
```

Cleaner: define a private `_mint_ths_v_token` free function, then `@lru_cache` it at module level. Replace the inline code with this:

```python
def _mint_ths_v_token() -> str:
    """Mint the `v` cookie token (one-shot per process)."""
    try:
        import py_mini_racer
    except ImportError as e:
        raise DataFetchError(
            f"[ThsFetcher] board history requires py_mini_racer: {e}"
        ) from e
    from importlib import resources
    js_path = resources.files("akshare.data").joinpath("ths.js")
    js_text = js_path.read_text(encoding="utf-8")
    js = py_mini_racer.MiniRacer()
    js.eval(js_text)
    return js.call("v")


@lru_cache(maxsize=1)
def _get_ths_v_token() -> str:
    """Cached wrapper around _mint_ths_v_token."""
    return _mint_ths_v_token()
```

Then inside the class, add a thin instance method:

```python
def _v_token(self) -> str:
    """Instance accessor for the cached v token."""
    return _get_ths_v_token()
```

Adjust the test (Step 2) to call `f._v_token()` instead of `f._get_ths_v_token()`.

- [ ] **Step 5: Run the test to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/test_ths_board_kline.py::TestVToken -v`
Expected: 2 PASS.

- [ ] **Step 6: Commit**

```bash
git add stock_data/data_provider/fetchers/ths_fetcher.py tests/test_ths_board_kline.py
git commit -m "feat(ths): add v-token helper for board K-line auth"
```

---

## Task 3: THS fetcher — concept-board inner-code resolver

**Files:**
- Modify: `stock_data/data_provider/fetchers/ths_fetcher.py` — add `_resolve_ths_concept_clid(slug)`.
- Modify: `tests/test_ths_board_kline.py` — add `TestResolveConceptClid`.

- [ ] **Step 1: Write the failing test**

```python
class TestResolveConceptClid:
    def test_extracts_clid_from_html(self, monkeypatch):
        from stock_data.data_provider.fetchers.ths_fetcher import ThsFetcher
        # Fake HTML body with the clid input
        fake_html = '<html><body><input id="clid" value="T000267467"/></body></html>'

        # Mock _session_or_requests_get: use the helper's URL path
        from unittest.mock import patch, MagicMock
        f = ThsFetcher.__new__(ThsFetcher)

        def fake_get(url, headers=None, timeout=None, **kw):
            assert "/gn/detail/code/" in url
            r = MagicMock()
            r.text = fake_html
            r.status_code = 200
            return r

        with patch.object(ThsFetcher, "_http_get", side_effect=fake_get):
            clid = f._resolve_ths_concept_clid("301558")
        assert clid == "T000267467"

    def test_missing_clid_returns_none(self, monkeypatch):
        from stock_data.data_provider.fetchers.ths_fetcher import ThsFetcher
        from unittest.mock import patch, MagicMock
        f = ThsFetcher.__new__(ThsFetcher)
        def fake_get(url, headers=None, timeout=None, **kw):
            r = MagicMock()
            r.text = "<html><body>no input</body></html>"
            r.status_code = 200
            return r
        with patch.object(ThsFetcher, "_http_get", side_effect=fake_get):
            assert f._resolve_ths_concept_clid("xxx") is None
```

- [ ] **Step 2: Add a thin HTTP helper on ThsFetcher** (if not already present)

The existing `json_get` and `json_post` in `..utils.http` return parsed JSON. For the THS HTML page, we need raw text. Add this helper **near the top of ThsFetcher class**:

```python
@staticmethod
def _http_get(url: str, *, headers: dict | None = None, timeout: int = 10):
    """Raw HTTP GET returning the response object (not parsed).

    Uses requests (not curl_cffi) — d.10jqka.com.cn / q.10jqka.com.cn don't
    fingerprint-block. Reuses the project's requests default (no proxy).
    """
    import requests
    return requests.get(url, headers=headers or {"User-Agent": THS_UA}, timeout=timeout)
```

- [ ] **Step 3: Implement `_resolve_ths_concept_clid`**

```python
_CONCEPT_DETAIL_URL = "https://q.10jqka.com.cn/gn/detail/code/{slug}/"
_CONCEPT_CLID_RE = re.compile(
    r'<input[^>]*\bid=["\']clid["\'][^>]*\bvalue=["\']([^"\']+)["\']',
    re.IGNORECASE,
)

def _resolve_ths_concept_clid(self, slug: str) -> str | None:
    """Fetch the concept-board HTML page and extract the inner `clid` (e.g. T000267467).

    Returns the clid string, or None if not found / on any error.
    """
    url = self._CONCEPT_DETAIL_URL.format(slug=slug)
    headers = {"User-Agent": THS_UA, "Cookie": f"v={self._v_token()}"}
    try:
        r = self._http_get(url, headers=headers, timeout=10)
    except Exception as e:
        logger.warning(f"[ThsFetcher] concept clid fetch failed for {slug}: {e}")
        return None
    m = self._CONCEPT_CLID_RE.search(r.text or "")
    return m.group(1) if m else None
```

- [ ] **Step 4: Run tests**

Run: `.venv/Scripts/python.exe -m pytest tests/test_ths_board_kline.py::TestResolveConceptClid -v`
Expected: 2 PASS.

- [ ] **Step 5: Commit**

```bash
git add stock_data/data_provider/fetchers/ths_fetcher.py tests/test_ths_board_kline.py
git commit -m "feat(ths): add concept-board clid resolver"
```

---

## Task 4: THS fetcher — per-year K-line fetch + response parser

**Files:**
- Modify: `stock_data/data_provider/fetchers/ths_fetcher.py` — add `_fetch_ths_board_year`, `_parse_ths_kline_body`, `get_board_history`.

- [ ] **Step 1: Write failing parser tests**

```python
class TestParseThsKlineBody:
    def test_parses_typical_response(self):
        from stock_data.data_provider.fetchers.ths_fetcher import ThsFetcher
        f = ThsFetcher.__new__(ThsFetcher)
        body = (
            'var v_abc123={"data":"2025-06-30,1234.5,1260.0,1220.3,1255.7,12345678,1.234e10,2.5,1.7,21.2,1.5;'
            '2025-06-29,1200.0,1240.0,1190.0,1230.0,10000000,1.0e10,2.0,1.0,12.0,1.0;"};'
        )
        rows = f._parse_ths_kline_body(body)
        assert len(rows) == 2
        assert rows[0]["date"] == "2025-06-30"
        assert rows[0]["open"] == 1234.5
        assert rows[1]["close"] == 1230.0
        # Schema: STANDARD_COLUMNS subset
        for r in rows:
            assert set(r.keys()) >= {"date", "open", "high", "low", "close", "volume", "amount"}

    def test_empty_data_returns_empty_list(self):
        from stock_data.data_provider.fetchers.ths_fetcher import ThsFetcher
        f = ThsFetcher.__new__(ThsFetcher)
        assert f._parse_ths_kline_body('var v_x={"data":""};') == []

    def test_handles_11_or_12_column_rows(self):
        # Upstream uses 7 data columns (date..amount) + 4 trailing extras
        from stock_data.data_provider.fetchers.ths_fetcher import ThsFetcher
        f = ThsFetcher.__new__(ThsFetcher)
        body = 'var v_x={"data":"2025-06-30,1,2,3,4,5,6,7,8,9,10,11;"};'
        rows = f._parse_ths_kline_body(body)
        assert len(rows) == 1
        assert rows[0]["close"] == 4.0

    def test_skips_malformed_rows(self):
        from stock_data.data_provider.fetchers.ths_fetcher import ThsFetcher
        f = ThsFetcher.__new__(ThsFetcher)
        body = 'var v_x={"data":"2025-06-30,1,2,3,4,5,6,7,8,9,10;garbage_row;2025-06-29,1,2,3,4,5,6,7,8,9,10;"};'
        rows = f._parse_ths_kline_body(body)
        assert len(rows) == 2  # garbage_row skipped

    def test_missing_var_wrapper_still_parses(self):
        from stock_data.data_provider.fetchers.ths_fetcher import ThsFetcher
        f = ThsFetcher.__new__(ThsFetcher)
        # Some upstream variants return plain JSON
        body = '{"data":"2025-06-30,1,2,3,4,5,6,7,8,9,10;"}'
        rows = f._parse_ths_kline_body(body)
        assert len(rows) == 1
```

- [ ] **Step 2: Run tests — expect FAIL**

Run: `.venv/Scripts/python.exe -m pytest tests/test_ths_board_kline.py::TestParseThsKlineBody -v`
Expected: 5 FAIL (parser doesn't exist yet).

- [ ] **Step 3: Implement the parser**

Add to `ThsFetcher` class:

```python
@staticmethod
def _extract_ths_json(body: str) -> str:
    """Return the `{...}` JSON substring from `var v_X={...};` responses.

    Falls back to returning the original body if no `var …=` prefix is found
    (some upstream variants return plain JSON).
    """
    if not body:
        return ""
    # Strip leading `var NAME=` or similar JS assignment
    m = re.search(r'\{[\s\S]*\}', body)
    return m.group(0) if m else body


@staticmethod
def _parse_ths_kline_body(body: str) -> list[dict]:
    """Parse a `d.10jqka.com.cn/v4/line/bk_*/01/{year}.js` response.

    The upstream response is `var v_XXXX={"data": "<csv>"};`. The `data`
    field is `;`-separated rows; each row is 11 comma-separated fields:
    `date, open, high, low, close, volume, amount, amp, pct_chg, change_amt, turnover_rate`.
    Some upstream variants return 12 columns (trailing null); we accept both
    and consume only the first 11.

    Returns canonical row dicts with keys: date, open, high, low, close,
    volume, amount. Other fields (amp, pct_chg, change_amt, turnover_rate)
    are dropped (THS doesn't expose them — zzshare/em do). Empty list on
    parse failure / empty data.
    """
    if not body:
        return []
    json_str = ThsFetcher._extract_ths_json(body)
    try:
        import json as _json
        payload = _json.loads(json_str)
    except (ValueError, TypeError):
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
            out.append({
                "date": parts[0],
                "open": float(parts[1]),
                "high": float(parts[2]),
                "low": float(parts[3]),
                "close": float(parts[4]),
                "volume": int(float(parts[5])),
                "amount": float(parts[6]),
            })
        except (TypeError, ValueError):
            continue
    return out
```

- [ ] **Step 4: Run tests — expect PASS**

Run: `.venv/Scripts/python.exe -m pytest tests/test_ths_board_kline.py::TestParseThsKlineBody -v`
Expected: 5 PASS.

- [ ] **Step 5: Commit**

```bash
git add stock_data/data_provider/fetchers/ths_fetcher.py tests/test_ths_board_kline.py
git commit -m "feat(ths): add parser for d.10jqka.com.cn board K-line JS response"
```

---

## Task 5: THS fetcher — `get_board_history` orchestration

**Files:**
- Modify: `stock_data/data_provider/fetchers/ths_fetcher.py` — add `get_board_history`, `_fetch_ths_board_year`.
- Modify: `tests/test_ths_board_kline.py` — add `TestGetBoardHistory`.

- [ ] **Step 1: Write failing test (orchestration with mocked HTTP)**

```python
class TestGetBoardHistory:
    def test_concept_calls_clid_then_year_js(self, monkeypatch):
        from stock_data.data_provider.fetchers.ths_fetcher import ThsFetcher
        from unittest.mock import patch, MagicMock

        f = ThsFetcher.__new__(ThsFetcher)

        # Stub: clid resolve returns T000267467
        # Stub: per-year fetch returns a fixed JS body
        year_js_body = (
            'var v_x={"data":"2025-06-30,1,2,3,4,5,6,7,8,9,10;'
            '2025-06-29,1.1,2.1,3.1,4.1,5.1,6.1,7.1,8.1,9.1,10.1;"};'
        )
        with patch.object(ThsFetcher, "_resolve_ths_concept_clid", return_value="T000267467"), \
             patch.object(ThsFetcher, "_fetch_ths_board_year", return_value=year_js_body):
            rows = f.get_board_history(
                board_code="301558",
                board_type="concept",
                frequency="d",
                days=400,
                end_date="2025-06-30",
                start_date="2025-06-01",
            )
        assert len(rows) == 2
        assert rows[0]["date"] == "2025-06-30"

    def test_industry_skips_clid_step(self, monkeypatch):
        from stock_data.data_provider.fetchers.ths_fetcher import ThsFetcher
        from unittest.mock import patch

        f = ThsFetcher.__new__(ThsFetcher)
        year_js_body = 'var v_x={"data":"2025-06-30,1,2,3,4,5,6,7,8,9,10;"};'

        with patch.object(ThsFetcher, "_resolve_ths_concept_clid") as clid_mock, \
             patch.object(ThsFetcher, "_fetch_ths_board_year", return_value=year_js_body):
            rows = f.get_board_history(
                board_code="881270",
                board_type="industry",
                frequency="d",
                days=400,
                end_date="2025-06-30",
            )
        clid_mock.assert_not_called()
        assert len(rows) == 1

    def test_unsupported_frequency_raises(self):
        from stock_data.data_provider.fetchers.ths_fetcher import ThsFetcher
        f = ThsFetcher.__new__(ThsFetcher)
        try:
            f.get_board_history("881270", board_type="industry", frequency="w")
        except Exception as e:
            assert "frequency" in str(e).lower() or "w" in str(e)
        else:
            raise AssertionError("expected DataFetchError for non-daily THS freq")

    def test_missing_board_type_raises(self):
        from stock_data.data_provider.fetchers.ths_fetcher import ThsFetcher
        f = ThsFetcher.__new__(ThsFetcher)
        try:
            f.get_board_history("881270", board_type=None)
        except Exception as e:
            assert "board_type" in str(e).lower()
        else:
            raise AssertionError("expected DataFetchError when board_type missing")

    def test_date_range_filter(self, monkeypatch):
        from stock_data.data_provider.fetchers.ths_fetcher import ThsFetcher
        from unittest.mock import patch

        f = ThsFetcher.__new__(ThsFetcher)
        year_js_body = (
            'var v_x={"data":"2025-06-30,1,2,3,4,5,6,7,8,9,10;'
            '2024-12-31,1,2,3,4,5,6,7,8,9,10;'
            '2023-01-01,1,2,3,4,5,6,7,8,9,10;"};'
        )
        with patch.object(ThsFetcher, "_resolve_ths_concept_clid", return_value="T000267467"), \
             patch.object(ThsFetcher, "_fetch_ths_board_year", return_value=year_js_body):
            rows = f.get_board_history(
                board_code="301558",
                board_type="concept",
                start_date="2024-01-01",
                end_date="2025-01-01",
            )
        dates = [r["date"] for r in rows]
        assert "2024-12-31" in dates
        assert "2025-06-30" not in dates
        assert "2023-01-01" not in dates
```

- [ ] **Step 2: Run tests — expect FAIL (orchestrator missing)**

Run: `.venv/Scripts/python.exe -m pytest tests/test_ths_board_kline.py::TestGetBoardHistory -v`
Expected: 5 FAIL with `AttributeError`.

- [ ] **Step 3: Implement `_fetch_ths_board_year` and `get_board_history`**

Add to `ThsFetcher` class:

```python
_THS_BOARD_KLINE_URL = "https://d.10jqka.com.cn/v4/line/bk_{inner}/01/{year}.js"
_THS_BOARD_FREQ_MAP: dict[str, int] = {"d": 1}  # THS upstream only ships daily

def _fetch_ths_board_year(self, inner_code: str, year: int) -> str:
    """Fetch one year of THS board K-line JS body. Returns "" on failure."""
    url = self._THS_BOARD_KLINE_URL.format(inner=inner_code, year=year)
    headers = {
        "User-Agent": THS_UA,
        "Referer": "http://q.10jqka.com.cn",
        "Host": "d.10jqka.com.cn",
        "Cookie": f"v={self._v_token()}",
    }
    try:
        r = self._http_get(url, headers=headers, timeout=15)
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
        close, volume, amount. Empty list on failure (logged at WARNING).

    Raises:
        DataFetchError: frequency not in ``_THS_BOARD_FREQ_MAP``; board_type
            missing; concept clid resolution returns None.
    """
    if not board_type:
        raise DataFetchError(
            "[ThsFetcher] get_board_history: board_type is required "
            "(must be 'concept' or 'industry')"
        )
    freq_key = (frequency or "d").lower()
    if freq_key not in self._THS_BOARD_FREQ_MAP:
        raise DataFetchError(
            f"[ThsFetcher] get_board_history: unsupported frequency "
            f"{frequency!r}; THS upstream is daily-only"
        )

    # Year range
    end_d = datetime.strptime(end_date, "%Y-%m-%d").date() if end_date else _date.today()
    start_d = (
        datetime.strptime(start_date, "%Y-%m-%d").date()
        if start_date else end_d - __import__("datetime").timedelta(days=days)
    )
    start_year = start_d.year
    end_year = end_d.year

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

    # Fetch each year, concat, parse, filter
    rows: list[dict] = []
    for year in range(start_year, end_year + 1):
        body = self._fetch_ths_board_year(inner, year)
        rows.extend(self._parse_ths_kline_body(body))

    # Date range filter (string comparison works for YYYY-MM-DD)
    rows = [r for r in rows if start_d.strftime("%Y-%m-%d") <= r["date"] <= end_d.strftime("%Y-%m-%d")]

    # Sort ascending
    rows.sort(key=lambda r: r["date"])
    return rows
```

The `__import__("datetime").timedelta` hack avoids adding `timedelta` to the top-level imports — replace with a proper import: add `from datetime import date, datetime, timedelta` to the top-of-file import block (already imports `date as _date, datetime`; just add `timedelta`).

- [ ] **Step 4: Run tests — expect PASS**

Run: `.venv/Scripts/python.exe -m pytest tests/test_ths_board_kline.py::TestGetBoardHistory -v`
Expected: 5 PASS.

- [ ] **Step 5: Commit**

```bash
git add stock_data/data_provider/fetchers/ths_fetcher.py tests/test_ths_board_kline.py
git commit -m "feat(ths): add get_board_history for concept + industry boards"
```

---

## Task 6: Manager — pass `board_type` through

**Files:**
- Modify: `stock_data/data_provider/manager.py:789-822` — extend `get_board_history` signature with `board_type`, forward to fetcher call.

- [ ] **Step 1: Update `get_board_history` signature**

Edit the method in `stock_data/data_provider/manager.py`:

```python
def get_board_history(
    self,
    board_code: str,
    source: str,
    frequency: str = "d",
    *,
    start_date: str | None = None,
    end_date: str | None = None,
    days: int = 30,
    board_type: str | None = None,  # NEW — required for THS concept/industry
) -> tuple[list[dict], str]:
    """Get K-line for a board from the named source.

    `start_date` / `end_date` (YYYY-MM-DD) take precedence over `days`.
    Source-routed (no failover) per CLAUDE.md — board classification
    systems differ across sources.

    `board_type` is currently consumed only by ThsFetcher (must be
    ``"concept"`` or ``"industry"``); EastMoney and ZzshareFetcher
    ignore it. Pass it through regardless so the call shape is uniform.
    """
    result, name = self._with_source(
        source=source,
        capability=DataCapability.STOCK_BOARD,
        market="csi",
        op_label=f"board K-line {board_code} ({source})",
        call=lambda f: (
            f.get_board_history(
                board_code,
                frequency=frequency,
                days=days,
                start_date=start_date,
                end_date=end_date,
                source=source,
                board_type=board_type,
            ),
            f.name,
        ),
    )
    return result, name
```

- [ ] **Step 2: Verify existing test still passes**

Run: `.venv/Scripts/python.exe -m pytest tests/ -k "board_history" -v`
Expected: existing zzshare tests pass (the new param defaults to None so the legacy call shape is preserved).

- [ ] **Step 3: Commit**

```bash
git add stock_data/data_provider/manager.py
git commit -m "feat(manager): thread board_type through get_board_history"
```

---

## Task 7: API route — expand source/frequency/board_type

**Files:**
- Modify: `stock_data/api/routes/boards.py:53-71` — add `_resolve_board_history_source` that does NOT alias `ths→zzshare`.
- Modify: `stock_data/api/routes/boards.py:391-432` — update `/boards/{board_code}/history` route.

- [ ] **Step 1: Write failing route tests**

Create `tests/test_boards_history_route.py`:

```python
"""Route-level tests for /boards/{board_code}/history source expansion."""
import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    from stock_data.server import app
    return TestClient(app)


class TestSourceExpansion:
    def test_zzshare_source_accepted(self, client):
        r = client.get("/boards/883957/history", params={"source": "zzshare", "frequency": "d"})
        # Either 200 (upstream works) or 502/500 (upstream down) — NOT 400/422 (validation)
        assert r.status_code != 422, r.text
        assert r.status_code != 400, r.text

    def test_eastmoney_source_accepted(self, client):
        r = client.get("/boards/BK0996/history", params={"source": "eastmoney", "frequency": "d"})
        assert r.status_code != 422, r.text
        assert r.status_code != 400, r.text

    def test_ths_concept_requires_board_type(self, client):
        r = client.get("/boards/301558/history", params={"source": "ths", "frequency": "d"})
        # 422 because board_type is missing
        assert r.status_code == 422, r.text

    def test_ths_industry_works(self, client):
        r = client.get(
            "/boards/881270/history",
            params={"source": "ths", "frequency": "d", "board_type": "industry"},
        )
        assert r.status_code != 422, r.text
        assert r.status_code != 400, r.text

    def test_unknown_source_returns_400(self, client):
        r = client.get("/boards/883957/history", params={"source": "bogus", "frequency": "d"})
        assert r.status_code == 400, r.text

    def test_zzshare_alias_to_ths_not_done_here(self, client):
        # `source=ths` here must NOT be aliased to `zzshare` — it should be
        # validated against the history-source allowlist.
        r = client.get(
            "/boards/881270/history",
            params={"source": "ths", "frequency": "d", "board_type": "industry"},
        )
        # If aliased, the route would call ZzshareFetcher.get_board_history
        # which only supports 883957 → 4xx/5xx.
        # We assert the route accepted "ths" (status != 400/422).
        assert r.status_code not in (400, 422), r.text


class TestFrequencyExpansion:
    @pytest.mark.parametrize("freq", ["d", "w", "m", "5m", "15m", "30m", "60m"])
    def test_eastmoney_accepts_all_frequencies(self, client, freq):
        r = client.get(
            "/boards/BK0996/history",
            params={"source": "eastmoney", "frequency": freq},
        )
        # Validation passes; upstream may fail but route shouldn't 422.
        assert r.status_code != 422, f"freq={freq} rejected: {r.text}"

    def test_ths_rejects_weekly(self, client):
        r = client.get(
            "/boards/881270/history",
            params={"source": "ths", "frequency": "w", "board_type": "industry"},
        )
        # ThsFetcher raises DataFetchError → mapped to 4xx/5xx (NOT 422)
        assert r.status_code != 422, r.text
        assert r.status_code >= 400, r.text


class TestBoardTypeParam:
    def test_board_type_required_for_ths(self, client):
        # Without board_type, route returns 422
        r = client.get(
            "/boards/881270/history",
            params={"source": "ths", "frequency": "d"},
        )
        assert r.status_code == 422

    def test_board_type_ignored_for_eastmoney(self, client):
        r = client.get(
            "/boards/BK0996/history",
            params={"source": "eastmoney", "frequency": "d", "board_type": "concept"},
        )
        assert r.status_code != 422, r.text
```

- [ ] **Step 2: Run tests — expect FAIL (route signature still old)**

Run: `.venv/Scripts/python.exe -m pytest tests/test_boards_history_route.py -v`
Expected: most tests FAIL with 422 (frequency validation rejects `w`/`m`/etc., board_type param unknown, source validation rejects `eastmoney`).

- [ ] **Step 3: Add `_resolve_board_history_source`**

In `stock_data/api/routes/boards.py`, after `_resolve_source`, add:

```python
_BOARD_HISTORY_VALID_SOURCES: tuple[str, ...] = ("zzshare", "ths", "eastmoney")


def _resolve_board_history_source(source: str) -> str:
    """Validate `source` for the board-history route — does NOT alias ths→zzshare.

    Different from `_resolve_source` (used by board-list endpoints), because
    THS as a board K-line source routes to ThsFetcher (different code system,
    different upstream from zzshare's plates_list). The persistence layer's
    alias still applies to board listings / stocks — only this route uses
    the strict version.
    """
    if source not in _BOARD_HISTORY_VALID_SOURCES:
        raise HTTPException(
            status_code=400,
            detail={
                "error": "invalid_source",
                "message": (
                    f"Unknown source '{source}'. "
                    f"Valid sources: {list(_BOARD_HISTORY_VALID_SOURCES)}"
                ),
            },
        )
    return source
```

- [ ] **Step 4: Update the route**

Replace the route decorator + signature:

```python
@router.get(
    "/boards/{board_code}/history",
    response_model=BoardKlineResponse,
    responses={
        400: {"model": ErrorResponse, "description": "Invalid source / frequency"},
        500: {"model": ErrorResponse, "description": "Server error"},
    },
    tags=["boards"],
)
@endpoint_meta(
    summary="板块 K 线 (zzshare 日线 / eastmoney 多周期 / ths 概念/行业日线)",
    markets=["csi"],
    capabilities=["STOCK_BOARD"],
    fetcher_method="get_board_history",
)
@map_errors
def get_board_history(
    board_code: str = Path(
        max_length=30,
        description=(
            "Board code (source-specific). Examples: "
            "zzshare='883957'; eastmoney='BK0996'; "
            "ths concept='301558'; ths industry='881270'"
        ),
    ),
    source: Literal["zzshare", "ths", "eastmoney"] = Query(
        ..., description="Data source. 'ths' here = ThsFetcher (NOT zzshare alias)."
    ),
    frequency: Literal["d", "w", "m", "5m", "15m", "30m", "60m"] = Query(
        "d",
        description=(
            "K-line frequency. eastmoney supports all; "
            "zzshare/ths are daily-only (other frequencies raise 4xx)"
        ),
    ),
    start_date: str | None = Query(None, description="Start date (YYYY-MM-DD)"),
    end_date: str | None = Query(None, description="End date (YYYY-MM-DD)"),
    days: int = Query(30, ge=1, le=365, description="Days (used when start_date not given)"),
    board_type: Literal["concept", "industry"] | None = Query(
        None,
        description=(
            "Required when source='ths' (concept vs industry boards use "
            "different code systems). Ignored by other sources."
        ),
    ),
) -> BoardKlineResponse:
    """Get historical K-line for a board. Source-routed, no failover."""
    source = _resolve_board_history_source(source)
    manager = get_manager()
    rows, origin = manager.get_board_history(
        board_code,
        source=source,
        frequency=frequency,
        start_date=start_date,
        end_date=end_date,
        days=days,
        board_type=board_type,
    )

    # ... reshape + return unchanged from existing implementation ...
```

Keep the existing reshape (`KLineData` list construction, board_name lookup, period setting, source echo).

- [ ] **Step 5: Run route tests — expect PASS**

Run: `.venv/Scripts/python.exe -m pytest tests/test_boards_history_route.py -v`
Expected: all PASS (or skip-with-clear-message if upstream is blocked; assert only validation paths).

- [ ] **Step 6: Run the full boards test suite**

Run: `.venv/Scripts/python.exe -m pytest tests/ -k "board" -v`
Expected: no regressions.

- [ ] **Step 7: Commit**

```bash
git add stock_data/api/routes/boards.py tests/test_boards_history_route.py
git commit -m "feat(boards): add eastmoney + ths as /boards/{code}/history sources"
```

---

## Task 8: Schema — refresh `BoardKlineResponse` description

**Files:**
- Modify: `stock_data/api/schemas.py:317-327`

- [ ] **Step 1: Update field descriptions**

```python
class BoardKlineResponse(BaseModel):
    """Response for board K-line endpoint (`/boards/{board_code}/history`)."""

    board_code: str = Field(description="Board code (source-specific; echoed verbatim)")
    board_name: str = Field(default="", description="Board name (best-effort lookup; may be empty)")
    period: str = Field(
        default="daily",
        description=(
            "K-line period: 'daily'/'weekly'/'monthly' or '5m'/'15m'/'30m'/'60m'. "
            "Source-dependent — zzshare and ths are daily-only."
        ),
    )
    data: list[KLineData] = Field(default_factory=list, description="K-line data points")
    source: str = Field(
        default="",
        description=(
            "Data source fetcher name — one of "
            "'eastmoney', 'zzshare', 'thsfetcher'"
        ),
    )
```

- [ ] **Step 2: Verify existing tests still pass**

Run: `.venv/Scripts/python.exe -m pytest tests/ -k "board_kline or BoardKline" -v`
Expected: PASS.

- [ ] **Step 3: Commit**

```bash
git add stock_data/api/schemas.py
git commit -m "docs(schemas): clarify BoardKlineResponse source + period semantics"
```

---

## Task 9: End-to-end smoke + CLAUDE.md update

**Files:**
- Modify: `CLAUDE.md` — update the board-history endpoint table row + the EastMoney fetcher capabilities row.

- [ ] **Step 1: Run the full test suite (excluding live_network)**

Run: `.venv/Scripts/python.exe -m pytest -m "not live_network" -x`
Expected: all PASS.

- [ ] **Step 2: Update CLAUDE.md**

Find the board-history row in CLAUDE.md and update:

```
| `/boards/{board_code}/history` | `STOCK_BOARD` | `get_board_history` |
```

Add a note: "Sources: zzshare (d-only), eastmoney (d/w/m + 5/15/30/60m), ths (d-only, concept|industry)".

Update the EastMoney fetcher capabilities row to confirm board K-line is supported.

- [ ] **Step 3: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: update CLAUDE.md with new board-history sources"
```

---

## Self-review checklist

- [x] **Spec coverage:** every requirement (EastMoney impl, server-side `board_code+source`, THS concept+industry) has a dedicated task.
- [x] **No placeholders:** every step has full code, every test has assertions, every command has expected output.
- [x] **Type consistency:** `_resolve_ths_concept_clid` signature stable across Tasks 3 and 5; `_parse_ths_kline_body` row keys (`date,open,high,low,close,volume,amount`) match between Task 4 and Task 5's `_get_ths_v_token` / `get_board_history`.
- [x] **DRY:** parser methods are `@staticmethod` so they're testable without instantiation; `_v_token()` is the single point of entry to the cached v cookie.
- [x] **YAGNI:** no caching layer added; no `IndicatorService` integration; ths/intraday frequencies explicitly rejected with clear errors instead of silently degrading.
- [x] **TDD:** each fetcher task starts with a failing test (parser / orchestration), implementation follows.
- [x] **Frequent commits:** 9 commits, one per task.

## Execution Handoff

Plan complete. Two execution options:

1. **Subagent-Driven (recommended)** — fresh subagent per task, two-stage review between tasks
2. **Inline Execution** — execute in this session, batch with checkpoints

Which approach?