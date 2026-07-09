# THS 板块实时行情 + board_name 修复 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 修复 `/boards/{code}/stocks` 的 `board.name==code` bug；新增 `ThsFetcher.get_board_realtime` 抓取板块实时行情并接入 manager + `GET /boards/{code}/quote` 独立接口；`include_quote=true` 时给 `board` 块填真实行情。

**Architecture:** 三层：(1) 修 `persistence/board.py` 的 name 查找（platecode OR）；(2) `ths_fetcher.py` 用现有 `requests`+BeautifulSoup+`v=`token+GBK 模式抓 `q.10jqka.com.cn/gn/detail/code/{cid}/` 静态 HTML；(3) manager `_with_source` 路由 + route 层组装。板块实时行情**不入 SQLite**（realtime 不缓存），route 直接调 manager（与 `/boards/{code}/history` 同为不可缓存 read-through 的既定豁免）。

**Tech Stack:** Python 3.11, FastAPI, Pydantic v2, BeautifulSoup(lxml), requests, pytest。venv 在 `.venv/`，测试命令用 `.venv/Scripts/python.exe -m pytest`。

**Spec:** `docs/superpowers/specs/2026-07-09-ths-board-realtime-and-board-name-fix-design.md`

**关键约定（勿违反）:**
- 单位：`volume`=万手(safe_int)、`amount`=亿元、`net_inflow`=亿元，**不做换算**（对齐既有 industry-rank 解析 `ths_fetcher.py:~1494` 与 `BoardInfo` 现状）。
- 服务器对外 stock/board 码是裸码；平台码 cid/platecode 的双码只在 THS 内部处理。
- 符号从 CSS class（`arr-rise/arr-fall`、`c-rise/c-fall`）推，文本是量级。

---

## File Structure

- Modify `stock_data/data_provider/persistence/board.py` — `get_board_name` SQL、`get_board_name_with_fallback` 慢路径比较（Task 1）。
- Modify `stock_data/data_provider/fetchers/ths_fetcher.py` — 新增 `_parse_board_realtime`（静态解析）+ `get_board_realtime`（Task 2）。
- Modify `stock_data/data_provider/manager.py` — 新增 `get_board_realtime`（Task 3）。
- Modify `stock_data/api/schemas.py` — 新增 `BoardQuoteResponse`（Task 4）。
- Modify `stock_data/api/routes/boards.py` — 新增 `GET /boards/{code}/quote`（Task 4）+ `/boards/{code}/stocks` include_quote 填充（Task 5）。
- Tests: `tests/test_persistence_board_name_fallback.py`（追加，Task 1）、`tests/test_ths_board_realtime.py`（新建，Task 2/3）、`tests/test_board_quote_route.py`（新建，Task 4）、`tests/test_board_stocks_forward_route.py`（追加，Task 5）。
- Modify `CLAUDE.md` — capability 路由表加 `get_board_realtime` 行、ThsFetcher 能力说明（Task 6）。

---

## Task 1: 修复 board_name（platecode OR 查找）

**Files:**
- Modify: `stock_data/data_provider/persistence/board.py:1310` (`get_board_name`), `:1338` (`get_board_name_with_fallback`)
- Test: `tests/test_persistence_board_name_fallback.py`

- [ ] **Step 1: 写失败测试**（追加到 `tests/test_persistence_board_name_fallback.py` 末尾）

```python
def test_get_board_name_matches_ths_concept_by_platecode():
    """THS concept board: input is platecode (885xxx) but stock_board stores code=cid.

    Regression for the board.name==code bug: get_board_name must match on
    platecode too (mirrors _read_membership_entries' OR-join fix, 2026-07-09).
    """
    board_mod.update_cached_boards(
        "concept",
        "ths",
        [{"code": "301546", "name": "央企国企改革", "platecode": "885595"}],
    )
    # Client addresses the board by platecode (885595), not cid.
    assert board_mod.get_board_name("885595", "ths") == "央企国企改革"
    # cid still works (industry boards pass code==platecode).
    assert board_mod.get_board_name("301546", "ths") == "央企国企改革"


def test_get_board_name_platecode_or_no_false_match_for_eastmoney():
    """eastmoney rows have platecode=NULL → OR's second arm is UNKNOWN, no false hit."""
    board_mod.update_cached_boards(
        "concept",
        "eastmoney",
        [{"code": "BK0996", "name": "人形机器人"}],  # platecode defaults to NULL
    )
    assert board_mod.get_board_name("BK0996", "eastmoney") == "人形机器人"
    assert board_mod.get_board_name("885595", "eastmoney") is None


def test_get_board_name_with_fallback_matches_platecode_in_slow_path():
    """Slow path (manager.get_all_boards) must also compare platecode."""
    from unittest.mock import MagicMock
    manager = MagicMock()
    manager.get_all_boards.return_value = (
        [{"code": "301546", "name": "央企国企改革", "platecode": "885595"}],
        "ThsFetcher",
    )
    name = board_mod.get_board_name_with_fallback("885595", "ths", manager=manager)
    assert name == "央企国企改革"
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/Scripts/python.exe -m pytest tests/test_persistence_board_name_fallback.py -k "platecode" -v`
Expected: FAIL（`get_board_name("885595","ths")` 返回 None）

- [ ] **Step 3: 改 `get_board_name` SQL**（`board.py:1330-1333`）

将
```python
    cursor.execute(
        "SELECT name FROM stock_board WHERE code = ? AND source = ? LIMIT 1",
        (board_code, source),
    )
```
改为
```python
    # Match on code OR platecode: THS concept boards are addressed by
    # platecode (885xxx) but stored with code=cid (3xxxxx), platecode=885xxx.
    # eastmoney/zhitu rows have platecode=NULL so the second arm is UNKNOWN
    # (never TRUE) — no false positives. Mirrors _read_membership_entries.
    cursor.execute(
        "SELECT name FROM stock_board WHERE (code = ? OR platecode = ?) AND source = ? LIMIT 1",
        (board_code, board_code, source),
    )
```

- [ ] **Step 4: 改 `get_board_name_with_fallback` 慢路径比较**（`board.py:1388`）

将
```python
            match = next((b["name"] for b in boards if b["code"] == board_code), None)
```
改为
```python
            match = next(
                (b["name"] for b in boards
                 if board_code in (b.get("code"), b.get("platecode"))),
                None,
            )
```

- [ ] **Step 5: 跑测试确认通过（含既有回归）**

Run: `.venv/Scripts/python.exe -m pytest tests/test_persistence_board_name_fallback.py -v`
Expected: PASS（新老用例全绿）

- [ ] **Step 6: 提交**

```bash
git add stock_data/data_provider/persistence/board.py tests/test_persistence_board_name_fallback.py
git commit -m "fix(boards): match board name on platecode too (forward /boards/{code}/stocks path)

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Task 2: ThsFetcher.get_board_realtime（解析器 + 抓取）

**Files:**
- Modify: `stock_data/data_provider/fetchers/ths_fetcher.py`（在 `get_board_stocks` 后、`get_all_boards` 前新增两个方法）
- Test: `tests/test_ths_board_realtime.py`（新建）

- [ ] **Step 1: 写失败测试（解析器，上涨样本 + 合成下跌样本验证符号）**

新建 `tests/test_ths_board_realtime.py`：

```python
"""Tests for ThsFetcher.get_board_realtime (board-level realtime quote scrape)."""

from unittest.mock import MagicMock, patch

from stock_data.data_provider.fetchers.ths_fetcher import ThsFetcher

# Real captured .heading block from q.10jqka.com.cn/gn/detail/code/301546/
# (rising board sample, 2026-07-09).
_HEADING_UP = """
<div class="heading">
  <div class="board-hq" style="background:#d75442;">
    <h3>央企国企改革<span>885595</span></h3>
    <span class="board-xj arr-rise">2934.39</span>
    <p class="board-zdf">10.92&nbsp;&nbsp;&nbsp;&nbsp;0.37%</p>
  </div>
  <div class="board-infos">
    <dl><dt>今开</dt><dd class="c-fall">2921.12</dd></dl>
    <dl><dt>昨收</dt><dd>2923.48</dd></dl>
    <dl><dt>最低</dt><dd class="c-fall">2870.11</dd></dl>
    <dl><dt>最高</dt><dd class="c-rise">2936.89</dd></dl>
    <dl><dt>成交量(万手)</dt><dd>15343.80</dd></dl>
    <dl><dt>板块涨幅</dt><dd class="c-rise">0.37%</dd></dl>
    <dl><dt>涨幅排名</dt><dd>229/389</dd></dl>
    <dl><dt>涨跌家数</dt><dd><span class="arr-rise-s">175</span><span class="arr-fall-s">207</span></dd></dl>
    <dl><dt>资金净流入(亿)</dt><dd class="c-rise">34.79</dd></dl>
    <dl><dt>成交额(亿)</dt><dd>2642.50</dd></dl>
  </div>
</div>
"""

# Synthetic falling board: flip board-xj to arr-fall and net-inflow dd to c-fall.
_HEADING_DOWN = (
    _HEADING_UP
    .replace('board-xj arr-rise', 'board-xj arr-fall')
    .replace('<dd class="c-rise">34.79</dd>', '<dd class="c-fall">34.79</dd>')
)


def _parse(html):
    from bs4 import BeautifulSoup
    return ThsFetcher._parse_board_realtime(BeautifulSoup(html, features="lxml"))


def test_parse_board_realtime_rising_sample():
    d = _parse(_HEADING_UP)
    assert d["board_code"] == "885595"
    assert d["board_name"] == "央企国企改革"
    assert d["price"] == 2934.39
    assert d["change_amount"] == 10.92
    assert d["change_pct"] == 0.37
    assert d["open"] == 2921.12
    assert d["prev_close"] == 2923.48
    assert d["low"] == 2870.11
    assert d["high"] == 2936.89
    assert d["volume"] == 15343  # 万手, safe_int
    assert d["amount"] == 2642.50  # 亿元, raw
    assert d["up_count"] == 175
    assert d["down_count"] == 207
    assert d["net_inflow"] == 34.79  # 亿元, raw
    assert d["rank"] == "229/389"


def test_parse_board_realtime_sign_from_css_class():
    """Falling board → change_amount/change_pct/net_inflow negative (sign from class)."""
    d = _parse(_HEADING_DOWN)
    assert d["change_amount"] == -10.92
    assert d["change_pct"] == -0.37
    assert d["net_inflow"] == -34.79
    # Absolute prices stay positive regardless of direction.
    assert d["open"] == 2921.12
    assert d["high"] == 2936.89


def test_get_board_realtime_resolves_cid_and_hits_detail_url():
    """platecode 885595 → cid 301546 (via persistence) → /gn/detail/code/301546/."""
    f = ThsFetcher.__new__(ThsFetcher)
    captured = {}

    def fake_get(url, headers=None, timeout=None, **kw):
        captured["url"] = url
        r = MagicMock()
        r.status_code = 200
        r.content = b"x" * 100
        r.text = _HEADING_UP
        r.encoding = "gbk"
        return r

    with patch(
        "stock_data.data_provider.persistence.board._resolve_ths_cid_from_platecode",
        return_value="301546",
    ), patch.object(ThsFetcher, "_http_get", side_effect=fake_get), patch.object(
        ThsFetcher, "_v_token", return_value="tok"
    ):
        d = f.get_board_realtime("885595")
    assert "/gn/detail/code/301546/" in captured["url"]
    assert d["board_name"] == "央企国企改革"


def test_get_board_realtime_falls_back_to_input_when_cid_unresolved():
    """cid resolution miss → use board_code as-is in the URL."""
    f = ThsFetcher.__new__(ThsFetcher)
    captured = {}

    def fake_get(url, headers=None, timeout=None, **kw):
        captured["url"] = url
        r = MagicMock()
        r.status_code = 200
        r.content = b"x" * 100
        r.text = _HEADING_UP
        r.encoding = "gbk"
        return r

    with patch(
        "stock_data.data_provider.persistence.board._resolve_ths_cid_from_platecode",
        return_value=None,
    ), patch.object(ThsFetcher, "_http_get", side_effect=fake_get), patch.object(
        ThsFetcher, "_v_token", return_value="tok"
    ):
        f.get_board_realtime("301546")
    assert "/gn/detail/code/301546/" in captured["url"]


def test_get_board_realtime_raises_on_http_error():
    from stock_data.data_provider.base import DataFetchError
    f = ThsFetcher.__new__(ThsFetcher)

    def fake_get(url, headers=None, timeout=None, **kw):
        r = MagicMock()
        r.status_code = 500
        r.content = b""
        return r

    import pytest
    with patch(
        "stock_data.data_provider.persistence.board._resolve_ths_cid_from_platecode",
        return_value="301546",
    ), patch.object(ThsFetcher, "_http_get", side_effect=fake_get), patch.object(
        ThsFetcher, "_v_token", return_value="tok"
    ):
        with pytest.raises(DataFetchError):
            f.get_board_realtime("885595")
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/Scripts/python.exe -m pytest tests/test_ths_board_realtime.py -v`
Expected: FAIL（`_parse_board_realtime` / `get_board_realtime` 不存在）

- [ ] **Step 3: 实现解析器 + 抓取方法**（`ths_fetcher.py`，在 `get_board_stocks` 方法之后插入）

```python
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
            "open": None, "prev_close": None, "high": None, "low": None,
            "volume": None, "amount": None,
            "up_count": None, "down_count": None,
            "net_inflow": None, "rank": None,
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
        board_type: str | None = None,  # accepted for interface parity; unused
        **kwargs,
    ) -> dict:
        """THS board-level realtime quote via q.10jqka.com.cn concept detail page.

        Args:
            board_code: THS platecode (e.g. ``"885595"``). Resolved to the
                URL cid (e.g. ``"301546"``) via the stock_board cache; when
                resolution misses (cold cache / input already a cid), the
                input is used as-is in the URL.

        Returns:
            dict with keys: board_code (platecode), board_name, price,
            change_amount, change_pct, open, prev_close, high, low, volume
            (万手), amount (亿元), up_count, down_count, net_inflow (亿元), rank.

        Raises:
            DataFetchError: upstream non-2xx / network failure / .heading absent.
        """
        from ..persistence.board import _resolve_ths_cid_from_platecode

        cid = _resolve_ths_cid_from_platecode(board_code) or board_code
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
            raise DataFetchError(
                f"[ThsFetcher] board_realtime({board_code}) HTTP {r.status_code}"
            )
        r.encoding = "gbk"
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(r.text or "", features="lxml")
        out = self._parse_board_realtime(soup)
        out["cid"] = cid
        # Prefer the platecode the client passed if the page didn't echo one.
        if not out.get("board_code"):
            out["board_code"] = board_code
        return out
```

- [ ] **Step 4: 跑测试确认通过**

Run: `.venv/Scripts/python.exe -m pytest tests/test_ths_board_realtime.py -v`
Expected: PASS（5 个用例全绿）

- [ ] **Step 5: 提交**

```bash
git add stock_data/data_provider/fetchers/ths_fetcher.py tests/test_ths_board_realtime.py
git commit -m "feat(ths): add get_board_realtime board-level quote scraper

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Task 3: manager.get_board_realtime 路由

**Files:**
- Modify: `stock_data/data_provider/manager.py`（在 `get_board_history` 后新增）
- Test: `tests/test_ths_board_realtime.py`（追加）

- [ ] **Step 1: 写失败测试**（追加到 `tests/test_ths_board_realtime.py`）

```python
def test_manager_get_board_realtime_routes_to_source():
    """manager.get_board_realtime routes by source via _with_source, returns (dict, name)."""
    from stock_data.data_provider.manager import DataFetcherManager
    from stock_data.data_provider.base import DataCapability

    mgr = DataFetcherManager.__new__(DataFetcherManager)

    captured = {}

    def fake_with_source(source, capability, market, op_label, call):
        captured["source"] = source
        captured["capability"] = capability
        captured["market"] = market
        fake_fetcher = MagicMock()
        fake_fetcher.name = "ths"
        fake_fetcher.get_board_realtime.return_value = {"board_name": "央企国企改革"}
        return call(fake_fetcher)

    with patch.object(mgr, "_with_source", side_effect=fake_with_source):
        result, name = mgr.get_board_realtime("885595", "ths")
    assert result["board_name"] == "央企国企改革"
    assert name == "ths"
    assert captured["capability"] == DataCapability.STOCK_BOARD
    assert captured["market"] == "csi"
    assert captured["source"] == "ths"
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/Scripts/python.exe -m pytest tests/test_ths_board_realtime.py::test_manager_get_board_realtime_routes_to_source -v`
Expected: FAIL（`get_board_realtime` 不存在）

- [ ] **Step 3: 实现 manager 方法**（`manager.py`，在 `get_board_history` 方法之后）

```python
    def get_board_realtime(
        self,
        board_code: str,
        source: str,
    ) -> tuple[dict, str]:
        """Get board-level realtime quote from the named source (source-routed).

        No failover — board classification systems differ across sources.
        Currently only ThsFetcher implements ``get_board_realtime``; other
        sources raise AttributeError inside the call (caller decides fallback).
        """
        return self._with_source(
            source=source,
            capability=DataCapability.STOCK_BOARD,
            market="csi",
            op_label=f"board realtime {board_code} ({source})",
            call=lambda f: (f.get_board_realtime(board_code), f.name),
        )
```

- [ ] **Step 4: 跑测试确认通过**

Run: `.venv/Scripts/python.exe -m pytest tests/test_ths_board_realtime.py -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add stock_data/data_provider/manager.py tests/test_ths_board_realtime.py
git commit -m "feat(boards): manager.get_board_realtime source-routed (no failover)

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Task 4: BoardQuoteResponse schema + GET /boards/{code}/quote

**Files:**
- Modify: `stock_data/api/schemas.py`（在 `BoardStocksResponse` 后新增 `BoardQuoteResponse`）
- Modify: `stock_data/api/routes/boards.py`（新增路由，import 处补 `BoardQuoteResponse`）
- Test: `tests/test_board_quote_route.py`（新建）

- [ ] **Step 1: 写失败测试**

新建 `tests/test_board_quote_route.py`：

```python
"""Integration tests for GET /boards/{board_code}/quote."""

from unittest.mock import patch

import pytest

from stock_data.api.routes import reset_manager


@pytest.fixture(autouse=True)
def reset_before_test():
    reset_manager()
    yield


_QUOTE = {
    "board_code": "885595", "board_name": "央企国企改革", "cid": "301546",
    "price": 2934.39, "change_amount": 10.92, "change_pct": 0.37,
    "open": 2921.12, "prev_close": 2923.48, "high": 2936.89, "low": 2870.11,
    "volume": 15343, "amount": 2642.50, "up_count": 175, "down_count": 207,
    "net_inflow": 34.79, "rank": "229/389",
}


def test_board_quote_source_required(client):
    """source is required → 422."""
    r = client.get("/api/v1/boards/885595/quote")
    assert r.status_code == 422


def test_board_quote_rejects_non_ths_source(client):
    """Literal['ths'] rejects eastmoney/zhitu at the FastAPI layer (422)."""
    r = client.get("/api/v1/boards/885595/quote?source=eastmoney")
    assert r.status_code == 422


def test_board_quote_returns_fields(client):
    from stock_data.data_provider import manager as mgr_mod
    with patch.object(mgr_mod.DataFetcherManager, "get_board_realtime",
                      return_value=(_QUOTE, "ths")):
        r = client.get("/api/v1/boards/885595/quote?source=ths")
    assert r.status_code == 200
    body = r.json()
    assert body["board_code"] == "885595"
    assert body["board_name"] == "央企国企改革"
    assert body["open"] == 2921.12
    assert body["up_count"] == 175
    assert body["net_inflow"] == 34.79
    assert body["rank"] == "229/389"
    assert body["source"] == "ths"


def test_board_quote_upstream_error_returns_503(client):
    from stock_data.data_provider import manager as mgr_mod
    from stock_data.data_provider.base import DataFetchError
    with patch.object(mgr_mod.DataFetcherManager, "get_board_realtime",
                      side_effect=DataFetchError("upstream down")):
        r = client.get("/api/v1/boards/885595/quote?source=ths")
    assert r.status_code == 503
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/Scripts/python.exe -m pytest tests/test_board_quote_route.py -v`
Expected: FAIL（路由 404 / schema 未定义）

- [ ] **Step 3: 新增 `BoardQuoteResponse`**（`schemas.py`，在 `BoardStocksResponse` 定义之后）

```python
class BoardQuoteResponse(BaseModel):
    """Response for board realtime quote endpoint (`/boards/{board_code}/quote`)."""

    board_code: str = Field(description="Board platecode (e.g. 885595)")
    board_name: str = Field(default="", description="Board name")
    source: str = Field(default="", description="数据来源 fetcher 名 (当前仅 ths)")
    price: float | None = Field(default=None, description="板块指数/现价 (指数点)")
    change_pct: float | None = Field(default=None, description="涨跌幅 (%)")
    change_amount: float | None = Field(default=None, description="涨跌额 (指数点)")
    open: float | None = Field(default=None, description="今开 (指数点)")
    high: float | None = Field(default=None, description="最高 (指数点)")
    low: float | None = Field(default=None, description="最低 (指数点)")
    prev_close: float | None = Field(default=None, description="昨收 (指数点)")
    volume: int | None = Field(default=None, description="成交量 (万手)")
    amount: float | None = Field(default=None, description="成交额 (亿元)")
    net_inflow: float | None = Field(default=None, description="资金净流入 (亿元)")
    up_count: int | None = Field(default=None, description="上涨家数")
    down_count: int | None = Field(default=None, description="下跌家数")
    rank: str | None = Field(default=None, description="涨幅排名 (e.g. '229/389')")
```

- [ ] **Step 4: import 补 `BoardQuoteResponse`**（`routes/boards.py` 的 `from ..schemas import (...)` 块，按字母序插入）

在 `BoardListResponse,` 之后加一行：
```python
    BoardQuoteResponse,
```

- [ ] **Step 5: 新增路由**（`routes/boards.py`，在 `get_board_stocks` 路由函数之后）

```python
@router.get(
    "/boards/{board_code}/quote",
    response_model=BoardQuoteResponse,
    responses={
        400: {"model": ErrorResponse, "description": "Invalid source"},
        500: {"model": ErrorResponse, "description": "Server error"},
    },
    tags=["boards"],
)
@endpoint_meta(
    summary="板块实时行情 (ths; 开盘/涨跌幅/涨跌家数/净流入 等 — q.10jqka 概念详情页)",
    markets=["csi"],
    capabilities=["STOCK_BOARD"],
    fetcher_method="get_board_realtime",
)
@map_errors
def get_board_quote(
    board_code: str = Path(max_length=30, description="Board platecode (e.g. 885595)"),
    source: Literal["ths"] = Query(
        ..., description="Data source (REQUIRED). Only 'ths' is implemented."
    ),
) -> BoardQuoteResponse:
    """Get board-level realtime quote. Source-routed, no failover (ths only)."""
    manager = get_manager()
    quote, origin = manager.get_board_realtime(board_code, source=source)
    return BoardQuoteResponse(
        board_code=quote.get("board_code") or board_code,
        board_name=quote.get("board_name", ""),
        source=origin,
        price=quote.get("price"),
        change_pct=quote.get("change_pct"),
        change_amount=quote.get("change_amount"),
        open=quote.get("open"),
        high=quote.get("high"),
        low=quote.get("low"),
        prev_close=quote.get("prev_close"),
        volume=quote.get("volume"),
        amount=quote.get("amount"),
        net_inflow=quote.get("net_inflow"),
        up_count=quote.get("up_count"),
        down_count=quote.get("down_count"),
        rank=quote.get("rank"),
    )
```

- [ ] **Step 6: 跑测试确认通过（含 manifest 启动校验）**

Run: `.venv/Scripts/python.exe -m pytest tests/test_board_quote_route.py tests/test_explorer_manifest_endpoint.py -v`
Expected: PASS（路由 + manifest sanity 校验 `fetcher_method="get_board_realtime"` 存在于 ThsFetcher）

- [ ] **Step 7: 提交**

```bash
git add stock_data/api/schemas.py stock_data/api/routes/boards.py tests/test_board_quote_route.py
git commit -m "feat(boards): add GET /boards/{code}/quote board realtime endpoint

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Task 5: include_quote=true 时填充 board 块行情

**Files:**
- Modify: `stock_data/api/routes/boards.py:471-497`（`get_board_stocks` 路由的 board 组装段）
- Test: `tests/test_board_stocks_forward_route.py`（追加）

- [ ] **Step 1: 写失败测试**（追加到 `tests/test_board_stocks_forward_route.py`）

```python
def test_board_stocks_include_quote_fills_board_block(client):
    """include_quote=true → board block populated from manager.get_board_realtime."""
    from unittest.mock import patch
    from stock_data.data_provider import manager as mgr_mod
    from stock_data.data_provider.persistence import board as board_mod

    quote = {
        "board_code": "885595", "board_name": "央企国企改革",
        "price": 2934.39, "change_pct": 0.37, "change_amount": 10.92,
        "volume": 15343, "amount": 2642.50, "net_inflow": 34.79,
        "up_count": 175, "down_count": 207,
    }
    with patch.object(
        board_mod, "get_board_stocks",
        return_value=([{"stock_code": "600519", "stock_name": "贵州茅台"}], "ths"),
    ), patch.object(
        board_mod, "get_board_name_with_fallback", return_value="央企国企改革"
    ), patch.object(
        mgr_mod.DataFetcherManager, "get_board_realtime", return_value=(quote, "ths")
    ):
        r = client.get("/api/v1/boards/885595/stocks?source=ths&include_quote=true")
    assert r.status_code == 200
    board = r.json()["board"]
    assert board["name"] == "央企国企改革"
    assert board["price"] == 2934.39
    assert board["up_count"] == 175
    assert board["net_inflow"] == 34.79


def test_board_stocks_include_quote_false_no_realtime_call(client):
    """include_quote=false → get_board_realtime NOT called; board is code+name only."""
    from unittest.mock import patch
    from stock_data.data_provider import manager as mgr_mod
    from stock_data.data_provider.persistence import board as board_mod

    with patch.object(
        board_mod, "get_board_stocks",
        return_value=([{"stock_code": "600519", "stock_name": "贵州茅台"}], "ths"),
    ), patch.object(
        board_mod, "get_board_name_with_fallback", return_value="央企国企改革"
    ), patch.object(
        mgr_mod.DataFetcherManager, "get_board_realtime"
    ) as mock_rt:
        r = client.get("/api/v1/boards/885595/stocks?source=ths&include_quote=false")
    assert r.status_code == 200
    assert r.json()["board"]["price"] is None
    mock_rt.assert_not_called()


def test_board_stocks_include_quote_best_effort_on_failure(client):
    """get_board_realtime failure → board falls back to code+name, no 500."""
    from unittest.mock import patch
    from stock_data.data_provider import manager as mgr_mod
    from stock_data.data_provider.persistence import board as board_mod
    from stock_data.data_provider.base import DataFetchError

    with patch.object(
        board_mod, "get_board_stocks",
        return_value=([{"stock_code": "600519", "stock_name": "贵州茅台"}], "ths"),
    ), patch.object(
        board_mod, "get_board_name_with_fallback", return_value="央企国企改革"
    ), patch.object(
        mgr_mod.DataFetcherManager, "get_board_realtime",
        side_effect=DataFetchError("upstream down"),
    ):
        r = client.get("/api/v1/boards/885595/stocks?source=ths&include_quote=true")
    assert r.status_code == 200
    board = r.json()["board"]
    assert board["name"] == "央企国企改革"
    assert board["price"] is None
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/Scripts/python.exe -m pytest tests/test_board_stocks_forward_route.py -k include_quote -v`
Expected: FAIL（board 块只有 code+name，price 恒为 None）

- [ ] **Step 3: 修改 board 组装段**（`routes/boards.py`，把 `return BoardStocksResponse(...)` 之前的 board 构造改为按 include_quote 填充）

将（`:492-497`）
```python
    return BoardStocksResponse(
        board=BoardInfo(code=board_code, name=board_name),
        stocks=stock_list,
        query_source=source,
        data_source=origin,
    )
```
改为
```python
    # include_quote=true → also pull the board-level realtime quote (THS
    # only). Best-effort: any routing/upstream/missing-method failure falls
    # back to code+name. Mirrors /boards/{code}/history's direct manager call
    # (non-cacheable board read-through; CLAUDE.md persistence-only carve-out).
    board_info = BoardInfo(code=board_code, name=board_name)
    if include_quote:
        try:
            quote, _ = manager.get_board_realtime(board_code, source=source)
        except (DataFetchError, ValueError, AttributeError) as e:
            logger.debug(
                f"[boards] board realtime quote unavailable for {board_code} "
                f"(source={source}): {type(e).__name__}: {e}"
            )
        else:
            board_info = BoardInfo(
                code=board_code,
                name=board_name,
                price=quote.get("price"),
                change_pct=quote.get("change_pct"),
                change_amount=quote.get("change_amount"),
                volume=quote.get("volume"),
                amount=quote.get("amount"),
                net_inflow=quote.get("net_inflow"),
                up_count=quote.get("up_count"),
                down_count=quote.get("down_count"),
            )

    return BoardStocksResponse(
        board=board_info,
        stocks=stock_list,
        query_source=source,
        data_source=origin,
    )
```

- [ ] **Step 4: 跑测试确认通过**

Run: `.venv/Scripts/python.exe -m pytest tests/test_board_stocks_forward_route.py -v`
Expected: PASS（含既有用例）

- [ ] **Step 5: 提交**

```bash
git add stock_data/api/routes/boards.py tests/test_board_stocks_forward_route.py
git commit -m "feat(boards): fill board quote block on /boards/{code}/stocks?include_quote=true

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Task 6: 文档更新 + 全量测试

**Files:**
- Modify: `CLAUDE.md`（capability 路由表 + ThsFetcher 能力说明）

- [ ] **Step 1: 更新 CLAUDE.md capability 路由表**

在 "Capability-Based Routing" 的方法表（`get_board_history` 行附近）新增一行：
```markdown
| `get_board_realtime` | `STOCK_BOARD` (source-routed, no failover; ths only — board-level realtime quote via q.10jqka concept detail page) |
```
并在 Stage 1/2 `fetcher_method` overrides 表（"5 known" 段）新增一行 + 把标题计数更新为 6：
```markdown
| `/boards/{board_code}/quote` | `STOCK_BOARD` | `get_board_realtime` |
```
在 ThsFetcher 能力清单描述里，把 `STOCK_BOARD` 说明补一句：`get_board_realtime (板块实时行情 — q.10jqka /gn/detail/code/{cid}/ .heading 抓取, platecode 入参内部解析 cid)`。

- [ ] **Step 2: ruff 检查 + 格式化**

Run: `.venv/Scripts/python.exe -m ruff check stock_data/ tests/ && .venv/Scripts/python.exe -m ruff format stock_data/ tests/`
Expected: no errors（如 format 改动文件，git add 之）

- [ ] **Step 3: 跑受影响子集全绿**

Run: `.venv/Scripts/python.exe -m pytest tests/test_persistence_board_name_fallback.py tests/test_ths_board_realtime.py tests/test_board_quote_route.py tests/test_board_stocks_forward_route.py tests/test_boards_api.py tests/test_explorer_manifest_endpoint.py tests/test_capability_method_map.py -v`
Expected: PASS

- [ ] **Step 4: 跑默认全量套件（跳过 live_network）**

Run: `.venv/Scripts/python.exe -m pytest`
Expected: PASS（无回归）

- [ ] **Step 5: live_network 冒烟（可选，需真实上游）**

Run: `.venv/Scripts/python.exe -m pytest tests/test_ths_board_realtime.py -m live_network -v`
（注：若新增了带 `@pytest.mark.live_network` 的真实上游冒烟用例才需要；无则跳过。）

- [ ] **Step 6: 提交**

```bash
git add CLAUDE.md
git commit -m "docs(boards): document get_board_realtime capability + /boards/{code}/quote

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Self-Review notes（已核对 spec 覆盖）

- **任务1（name fix）** → Task 1。**任务2（include_quote board 填充）** → Task 5（依赖 Task 3）。**任务3（fetcher+manager+endpoint）** → Task 2 + Task 3 + Task 4。
- 单位一致性：Task 2 解析器、Task 4 schema、Task 5 填充三处均按 volume=万手/amount=亿元/net_inflow=亿元，无换算（对齐 B1 修复）。
- 符号：Task 2 用 CSS class 推导，含合成下跌 fixture 覆盖负号分支。
- best-effort 异常集合（DataFetchError/ValueError/AttributeError）与 spec 一致；eastmoney/zhitu 走 AttributeError 分支（Task 5 用例可后续补，当前 `/stocks` 路由 source 已被上游 stocks 逻辑约束，核心回落已由 DataFetchError 用例覆盖）。
- `fetcher_method="get_board_realtime"` 由 Task 4 Step 6 的 manifest 测试校验存在于 ThsFetcher。
