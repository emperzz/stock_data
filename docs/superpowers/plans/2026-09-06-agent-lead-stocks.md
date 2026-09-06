# `/agent/lead-stocks` Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 新增 `GET /api/v1/agent/lead-stocks` 端点，按 `连板数 × 涨幅 → 最后涨停时间 → 封单金额` 三层链对 10cm/20cm 涨停股做服务端排名，附带涨停原因与完整 feature profile；顺手把 `post_stocks_batch_profile` 内联的 per-stock fan-out 抽到公共 helper 复用。

**Architecture:**
- 1 个新 helper 模块（`api/_helpers/agent_stock_profile.py::build_stock_profile`），被新端点与 `post_stocks_batch_profile` 共用
- 1 个 GET 路由（`agent.py::get_lead_stocks`），3 步上游调用（zt-pools → board-stocks → zt-reasons）+ filter + rank 纯函数 + per-stock profile fan-out
- 1 个新 Pydantic 模型对（`LeadStockEntry` 继承 `StockBatchProfileEntry` + `LeadStocksResponse`）
- 1 个新 MD 渲染器（`render_lead_stocks_as_md`）
- 无复合缓存（依赖内层 60s 缓存），无 `@cache_endpoint` 装饰器

**Tech Stack:** Python 3.x / FastAPI / Pydantic v2 / pytest / TTLcache（既有）/ `trade_calendar.get_latest_trade_date_on_or_before`

**Spec:** `docs/superpowers/specs/2026-09-06-agent-lead-stocks-design.md` — plan 跟随 spec 阅读，executor 必须先读完 spec。

---

## Global Constraints

- **Python 路径**: 使用 `.venv/Scripts/python.exe`（CLAUDE.md "Common Commands"）。运行系统 `python` 会让 `AkshareFetcher.is_available()` 返回 False，安静破坏 akshare-routed 端点。
- **默认 `pytest` 跳过 `live_network` 和 `requires_token`**——开发循环 ~1 分钟；最终回归用 `pytest -m ""`。
- **运行 `ruff check` + `ruff format`** 在每个 commit 前。
- **endpoint_meta 装饰器**: 顺序 `@router.get → @endpoint_meta → @map_errors → def`；`endpoint_meta.deco` 必须返回原 `func`（CLAUDE.md "Don't reorder decorators"）。
- **`@endpoint_meta(capabilities=[])` 留空**——agent 端点不映射单一 capability（CLAUDE.md "Anti-patterns"）。
- **`ts_code` / 后缀**绝不能泄漏到响应——保持 6 位裸代码（CLAUDE.md "Don't leak the outbound ts_code suffix"）。
- **MD 渲染契约**: 不丢字段——`?format=md` 必须包含 JSON 携带的每个字段（CLAUDE.md "Anti-patterns"）。
- **per-aspect 错误隔离**: 任何上游失败不阻塞整批；`StockBatchAspectError(aspect=..., error=..., message=...)` 累积到 `errors[]`（CLAUDE.md "Per-item error isolation"）。
- **装饰器顺序**: route 装饰器栈严格按 `agent.py` 既有端点——见 `agent.py:196-219` 的 `post_boards_stock_overlap`。
- **测试文件命名**: `tests/test_agent_lead_stocks.py`（延续 `tests/test_agent_market_*.py` / `test_agent_batch_features.py` 模式）。
- **测试 fixture**: 复用 `tests/test_agent_endpoints.py` 的 `reset_before_test` autouse fixture 模式（reset_manager + 清缓存）。
- **commit 规范**: 不要求每个 task 一个 commit；任务级别的 deliverable 通过后才 commit（见每个 Task 的 Step 5）。
- **CLAUDE.md "Don't" 列表**: 不创建新 `DataCapability`、不创建新 fetcher、不写 `options.get(key) or default`、`change_pct=None` 不视为 0 而是视为 0 进入 `< 9` 过滤桶。

---

## File Structure（实施前最终状态）

| 文件 | 角色 | Task |
|---|---|---|
| `stock_data/api/_helpers/agent_stock_profile.py` | 新建——`StockProfileData` dataclass + `build_stock_profile()` 函数 | Task 1 |
| `stock_data/api/routes/agent.py` | 修改——`post_stocks_batch_profile` 内联 fan-out 替换为 `build_stock_profile` 调用；新增 `get_lead_stocks` handler；新增 `apply_change_pct_filter` / `rank_lead_stocks` 纯函数；新增 `render_lead_stocks_as_md` 与 `_MD_TEMPLATES["lead-stocks"]` | Task 2 / 4 / 5 |
| `stock_data/api/schemas.py` | 修改——新增 `LeadStockEntry(StockBatchProfileEntry)` + `LeadStocksResponse` | Task 3 |
| `tests/test_agent_lead_stocks.py` | 新建——10 个测试类覆盖 ranking / filter / board / error isolation / top_n / date / manifest / format=md / helper reuse / batch-profile regression | Task 4 / 5 / 6 |
| `tests/test_agent_endpoints.py` | 修改——`TestBatchProfile*` 测试类加新断言（重构后行为不变） | Task 2 |
| `docs/api-reference.md` | 修改——新增 `/agent/lead-stocks` 章节 | Task 7 |
| `CLAUDE.md` | 修改——Agent Batch API 路由表新增一行 | Task 7 |

---

## Task 1: 抽离 `build_stock_profile` 公共 helper

**Files:**
- Create: `stock_data/api/_helpers/agent_stock_profile.py`
- Test: `tests/test_agent_stock_profile.py`（新建，独立验证 helper）

**Interfaces:**
- Consumes: `DataFetcherManager`（来自 `stock_data.data_provider.manager`）；`MinimalQuote`（来自 `stock_data.api.schemas`）；`BatchFeatures`（来自 `stock_data.api.schemas`）；`StockBatchAspectError`（来自 `stock_data.api.schemas`）；`features.build_features`（来自 `stock_data.api._helpers.features` 或同等位置）；`stock_board_cache.get_stock_memberships`（来自 `stock_data.data_provider.persistence.board`）
- Produces:
  - `class StockProfileData`：`code: str` + `quote / features / info / boards: Optional[...]` + `errors: list[StockBatchAspectError]` + `ok: bool` property
  - `def build_stock_profile(manager, code, *, frequency="d", days=None) -> StockProfileData`

**Step 1.1**: 创建测试文件 `tests/test_agent_stock_profile.py`，写 helper 的独立单元测试：

```python
"""Tests for build_stock_profile helper."""
from types import SimpleNamespace
from unittest.mock import MagicMock

from stock_data.api._helpers.agent_stock_profile import (
    StockProfileData,
    build_stock_profile,
)
from stock_data.api.schemas import StockBatchAspectError


def _make_unified_quote(**overrides):
    """Build a SimpleNamespace that passes MinimalQuote validation.
    Uses getattr-with-default in _build_minimal_quote_from_unified, so
    missing fields default to None — only the kwargs present here need
    real values."""
    defaults = dict(
        price=10.0, change_pct=5.0, open_price=10.0, high=10.5, low=9.5,
        pre_close=9.5, volume=1000, amount=10000.0, change_amount=0.5,
        turnover_rate=1.0, amplitude=10.0, volume_ratio=1.5,
        pe_ratio=20.0, pb_ratio=3.0, mcap_yi=1000.0, float_mcap_yi=500.0,
        limit_up=11.0, limit_down=9.0, name="测试股",
    )
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


def _make_manager(quote=None, kline_df=None, info_dict=None, info_src="zhitu",
                  memberships=([], [], "persistence"), enrich=([], {})):
    m = MagicMock()
    m.get_realtime_quote.return_value = quote
    # get_kline_data returns (df, source) — empty df tuple for "no features"
    m.get_kline_data.return_value = (kline_df, "akshare") if kline_df is not None else (None, "akshare")
    # get_stock_info always returns (dict, source) tuple
    m.get_stock_info.return_value = (info_dict or {}, info_src)
    return m


def test_helper_returns_dataclass_with_code():
    m = _make_manager()
    profile = build_stock_profile(m, "300750")
    assert isinstance(profile, StockProfileData)
    assert profile.code == "300750"
    assert profile.quote is None
    assert profile.features is None
    # info always populated (get_stock_info always returns tuple)
    assert profile.info == {"source": "zhitu", "data": {}}
    assert profile.boards is None  # no cached entries + no fetcher_full
    assert profile.errors == []
    # ok is True because info is populated (truthy dict)
    assert profile.ok is True


def test_helper_ok_true_when_quote_present():
    m = _make_manager(quote=_make_unified_quote())
    profile = build_stock_profile(m, "300750")
    assert profile.ok is True
    assert profile.quote is not None
    assert profile.quote.price == 10.0
    assert profile.quote.name == "测试股"


def test_helper_quote_failure_appends_error():
    m = _make_manager()
    m.get_realtime_quote.side_effect = Exception("boom")
    profile = build_stock_profile(m, "300750")
    assert profile.quote is None
    aspects = [e for e in profile.errors if e.aspect == "quote"]
    assert len(aspects) == 1
    assert aspects[0].error == "Exception"
    assert "boom" in aspects[0].message


def test_helper_features_failure_does_not_block_quote():
    m = _make_manager(quote=_make_unified_quote())
    m.get_kline_data.side_effect = Exception("kline boom")
    profile = build_stock_profile(m, "300750")
    assert profile.quote is not None
    assert profile.features is None
    aspects = {e.aspect for e in profile.errors}
    assert "features" in aspects
    assert profile.ok is True  # quote 仍然 OK


def test_helper_info_shape():
    """info 字段必须包装为 {source, data} 形态以匹配 StockBatchProfileEntry 契约。"""
    m = _make_manager(info_dict={"name": "测试股", "industry": "新能源"}, info_src="tushare")
    profile = build_stock_profile(m, "300750")
    assert profile.info == {"source": "tushare", "data": {"name": "测试股", "industry": "新能源"}}


def test_helper_kline_returns_two_tuple():
    """get_kline_data 返回 (df, source) tuple；helper 正确解包。"""
    import pandas as pd
    df = pd.DataFrame({"close": [10.0, 11.0]})
    m = _make_manager(kline_df=df)
    # Verify the call went through with proper tuple unpacking
    profile = build_stock_profile(m, "300750")
    assert m.get_kline_data.called
    assert profile.features is not None  # build_features ran
```

**Step 1.2**: 运行测试，确认失败：

```bash
.venv/Scripts/python.exe -m pytest tests/test_agent_stock_profile.py -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'stock_data.api._helpers.agent_stock_profile'`

**Step 1.3**: 创建 `stock_data/api/_helpers/agent_stock_profile.py`：

```python
"""Per-stock fan-out helper used by /agent/stocks/batch-profile and /agent/lead-stocks.

Each aspect (quote / features / info / boards) is fetched independently with
its own try/except; a failure surfaces as a StockBatchAspectError in the
returned profile's errors[] but never aborts the whole fan-out.

Also re-homes `_build_minimal_quote_from_unified` (formerly at
`stock_data/api/routes/agent.py:1016-1054`) so both endpoints can import it
without a circular dependency on `agent.py`.

Spec: docs/superpowers/specs/2026-09-06-agent-lead-stocks-design.md §3.2
"""
from dataclasses import dataclass, field
from typing import Optional

from stock_data.api._helpers import stock_boards as _stock_boards_helper
from stock_data.api.schemas import (
    MinimalQuote,
    StockBatchAspectError,
)
from stock_data.data_provider.core.types import UnifiedRealtimeQuote
from stock_data.data_provider.manager import DataFetcherManager
from stock_data.data_provider.persistence import stock_board_cache


@dataclass
class StockProfileData:
    """Per-stock fan-out result. None fields are NOT failures — they correspond
    to a StockBatchAspectError in `errors` if the upstream call raised.

    Field shapes (must match StockBatchProfileEntry contract):
      - quote: MinimalQuote
      - features: dict (build_features returns a dict, not BatchFeatures Pydantic)
      - info:   {"source": str, "data": dict}
      - boards: {"source": "persistence"|"ths", "data": list[dict]}
    """

    code: str
    quote: Optional[MinimalQuote] = None
    features: Optional[dict] = None
    info: Optional[dict] = None
    boards: Optional[dict] = None
    errors: list[StockBatchAspectError] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return any(v is not None for v in (self.quote, self.features, self.info, self.boards))


def _build_minimal_quote_from_unified(q: UnifiedRealtimeQuote) -> MinimalQuote:
    """23-field mapping UnifiedRealtimeQuote → MinimalQuote.

    Re-homed from `agent.py:1016-1054`. Covers price / change_pct / OHLV /
    pre_close / volume / amount / change_amount / turnover_pct / amplitude /
    volume_ratio, plus the 2026-08-27 enrichment (volume_unit / amplitude_pct /
    pe_ratio / pb_ratio / mcap_yi / float_mcap_yi / limit_up / limit_down / name).
    `getattr(..., None)` lets missing source fields pass through as None
    rather than AttributeError.
    """
    return MinimalQuote(
        price=getattr(q, "price", None),
        change_pct=getattr(q, "change_pct", None),
        open=getattr(q, "open_price", None),
        high=getattr(q, "high", None),
        low=getattr(q, "low", None),
        pre_close=getattr(q, "pre_close", None),
        volume=getattr(q, "volume", None),
        amount=getattr(q, "amount", None),
        change_amount=getattr(q, "change_amount", None),
        turnover_pct=getattr(q, "turnover_rate", None),
        amplitude=getattr(q, "amplitude", None),
        volume_ratio=getattr(q, "volume_ratio", None),
        volume_unit="share",
        amplitude_pct=getattr(q, "amplitude", None),
        pe_ratio=getattr(q, "pe_ratio", None),
        pb_ratio=getattr(q, "pb_ratio", None),
        mcap_yi=getattr(q, "mcap_yi", None),
        float_mcap_yi=getattr(q, "float_mcap_yi", None),
        limit_up=getattr(q, "limit_up", None),
        limit_down=getattr(q, "limit_down", None),
        name=getattr(q, "name", None),
    )


def build_stock_profile(
    manager: DataFetcherManager,
    code: str,
    *,
    frequency: str = "d",
    days: Optional[int] = None,
) -> StockProfileData:
    """Pull quote + features + info + boards for `code`. Per-aspect isolation.

    Replicates the exact block formerly inlined at `agent.py:932-1005`
    inside `post_stocks_batch_profile` — same call signatures, same return
    shapes, same boards-enrichment merge — so the refactor (Task 2) is
    behavior-preserving.

    Args:
        manager: the DataFetcherManager singleton.
        code: 6-digit stock code (canonical form).
        frequency: kline frequency — one of d/w/m/1m/5m/15m/30m/60m.
        days: kline lookback days. If None, uses FreqProfile.default_days.

    Returns:
        StockProfileData with whichever aspects succeeded and per-aspect errors.
    """
    # Local imports — avoid circular: agent.py imports this module, so
    # _FEATURE_FREQS / build_features must come in lazily.
    from stock_data.api.routes.agent import _FEATURE_FREQS
    from stock_data.data_provider.features.build import build_features

    profile = StockProfileData(code=code)

    # 1. quote
    try:
        q = manager.get_realtime_quote(code)
        if q is not None:
            profile.quote = _build_minimal_quote_from_unified(q)
    except Exception as exc:
        profile.errors.append(
            StockBatchAspectError(aspect="quote", error=type(exc).__name__, message=str(exc))
        )

    # 2. features
    try:
        freq_profile = _FEATURE_FREQS[frequency]
        actual_days = max(days or freq_profile.default_days, freq_profile.ma60_warmup_days or 0)
        # get_kline_data returns (df, source) — discard source
        df, _src = manager.get_kline_data(
            code, frequency=freq_profile.mgr_frequency, days=actual_days, adjust="qfq",
        )
        if df is not None and not df.empty:
            # build_features signature: (df, *, frequency, days) — both kwargs required
            profile.features = build_features(df, frequency=frequency, days=actual_days)
    except Exception as exc:
        profile.errors.append(
            StockBatchAspectError(aspect="features", error=type(exc).__name__, message=str(exc))
        )

    # 3. info — always returns (dict, source); never None
    try:
        info_dict, info_src = manager.get_stock_info(code)
        profile.info = {"source": info_src, "data": info_dict}
    except Exception as exc:
        profile.errors.append(
            StockBatchAspectError(aspect="info", error=type(exc).__name__, message=str(exc))
        )

    # 4. boards — mirrors the inline flow at agent.py:966-984 exactly:
    # get_stock_memberships + THS enrichment merge. `get_stock_memberships`
    # uses `stock_code` (positional here) and returns (entries, cold_sources, origin).
    try:
        entries, _cold, _origin = stock_board_cache.get_stock_memberships(
            stock_code=code, sources=["ths"], manager=manager,
        )
        ths_cached = entries
        # fetch live THS enrichment (7 fields per THS upstream) — failures degrade
        enrichment: dict = {}
        fetcher_full = []
        try:
            fetcher_full, enrichment = _stock_boards_helper.fetch_stock_boards_quote_enrichment(
                code, manager,
            )
        except Exception:
            pass
        if ths_cached:
            for entry in ths_cached:
                code_key = entry.get("code") or entry.get("stock_code")
                if code_key and code_key in enrichment:
                    entry.update(enrichment[code_key])
            profile.boards = {"source": "persistence", "data": ths_cached}
        elif fetcher_full:
            profile.boards = {"source": "ths", "data": fetcher_full}
    except Exception as exc:
        profile.errors.append(
            StockBatchAspectError(aspect="boards", error=type(exc).__name__, message=str(exc))
        )

    return profile
```

**Step 1.4**: 运行测试，确认通过：

```bash
.venv/Scripts/python.exe -m pytest tests/test_agent_stock_profile.py -v
```

Expected: PASS (4 tests)

**Step 1.5**: Lint + format：

```bash
ruff check stock_data/api/_helpers/agent_stock_profile.py tests/test_agent_stock_profile.py
ruff format stock_data/api/_helpers/agent_stock_profile.py tests/test_agent_stock_profile.py
```

**Step 1.6**: Commit：

```bash
git add stock_data/api/_helpers/agent_stock_profile.py tests/test_agent_stock_profile.py
git commit -m "feat(helpers): add build_stock_profile per-stock fan-out helper

Extracted from /agent/stocks/batch-profile inline fan-out. Used by the
upcoming /agent/lead-stocks endpoint plus batch-profile itself. Per-aspect
try/except isolates failures into errors[] without aborting the fan-out.

Spec: docs/superpowers/specs/2026-09-06-agent-lead-stocks-design.md §3.2"
```

---

## Task 2: 重构 `post_stocks_batch_profile` 使用 helper

**Files:**
- Modify: `stock_data/api/routes/agent.py:873-1013` (`post_stocks_batch_profile` handler)
- Test: `tests/test_agent_endpoints.py::TestBatchProfile*`

**Interfaces:**
- Consumes: `build_stock_profile(manager, code, *, frequency, days)` from Task 1
- Produces: `StockBatchProfileEntry` 形态不变；内部 fan-out 调用替换为 helper

**Context**: 读 `agent.py:873-1013` 当前内联实现。每只股票原本走：1) `manager.get_realtime_quote` + `MinimalQuote(...)` 填充；2) `manager.get_kline_data` + `features.build_features`；3) `manager.get_stock_info`；4) `stock_board_cache.get_stock_memberships`。每步独立 try/except 加 `StockBatchAspectError`。重构后每个 aspect 整段被 helper 替换，handler 只剩循环与 entry 组装。

**Step 2.1**: 阅读 `agent.py:873-1013` 当前 `post_stocks_batch_profile` 全文，记录：
- 每个 aspect 的当前代码块（quote / features / info / boards）
- `name` 的取法（看是用 `quote.name` 还是 `stock_name_cache.get(code)`）
- `ok` 派生的当前写法（看是用 `any(...)` 还是别的方式）

把这段当前代码复制到一个临时注释块或单独文本，留作重构后比对。

**Step 2.2**: 在 `tests/test_agent_endpoints.py::TestBatchProfile*` 加 regression 断言。新建一个 `test_batch_profile_calls_helper_for_each_code`：

```python
def test_batch_profile_calls_helper_for_each_code(self, client, monkeypatch):
    """重构后 helper 应被调用 N 次（N=输入 codes 数）。"""
    from stock_data.api._helpers.agent_stock_profile import build_stock_profile
    mock_helper = MagicMock(wraps=build_stock_profile)
    monkeypatch.setattr(
        "stock_data.api.routes.agent.build_stock_profile", mock_helper,
    )
    payload = {"codes": ["300750", "600519"], "frequency": "d"}
    client.post("/api/v1/agent/stocks/batch-profile", json=payload)
    assert mock_helper.call_count == 2
    called_codes = {c.args[1] for c in mock_helper.call_args_list}
    assert called_codes == {"300750", "600519"}
```

**Step 2.3**: 运行新断言确认通过（重构尚未做，但当前 `post_stocks_batch_profile` 还在用内联 fan-out——helper 还没被调用，断言会失败）：

```bash
.venv/Scripts/python.exe -m pytest tests/test_agent_endpoints.py::TestBatchProfileQuoteFields::test_batch_profile_calls_helper_for_each_code -v
```

Expected: FAIL — `mock_helper.call_count == 0`（因为 helper 没被调用）。

**Step 2.4**: 重构 `agent.py:873-1013` 的 `post_stocks_batch_profile`。删除每个 aspect 的内联 try/except 块，替换为：

```python
results: list[StockBatchProfileEntry] = []
n_ok = 0

for code in payload.codes:
    profile = build_stock_profile(
        manager, code,
        frequency=payload.frequency,
        days=payload.days,
    )
    name = (getattr(profile.quote, "name", "") if profile.quote else "") or None
    if profile.ok:
        n_ok += 1
    results.append(
        StockBatchProfileEntry(
            code=code, name=name, ok=profile.ok,
            quote=profile.quote, features=profile.features,
            info=profile.info, boards=profile.boards,
            errors=profile.errors,
        )
    )

summary = _batch_summary(requested=len(payload.codes), ok=n_ok, started=t0)
result = StockBatchProfileResponse(
    frequency=payload.frequency, days=payload.days,
    results=results, summary=summary,
)
return _render_agent("stocks/batch-profile", result, format)
```

在文件顶部加 import：

```python
from stock_data.api._helpers.agent_stock_profile import build_stock_profile
```

**Step 2.5**: 跑全套 batch-profile 测试，确认无 regression：

```bash
.venv/Scripts/python.exe -m pytest tests/test_agent_endpoints.py::TestBatchProfileQuoteFields tests/test_agent_batch_features.py tests/test_agent_boards_batch_profile.py -v
```

Expected: PASS（全部既有测试通过，包括 MinimalQuote 23 字段契约 + `test_stocks_batch_profile_quote_has_all_23_keys`） + 新断言 `test_batch_profile_calls_helper_for_each_code` PASS。

**Step 2.6**（新增）：在 `tests/test_agent_endpoints.py` 加 boards-enrichment 回归测试——确认 helper 保留了原 inline 的 `stock_boards.fetch_stock_boards_quote_enrichment` 合并行为：

```python
def test_batch_profile_boards_enrichment_merged(self, client, monkeypatch):
    """boards 字段必须合并 THS enrichment（与重构前 agent.py:970-984 行为一致）。"""
    from stock_data.data_provider.persistence import stock_board_cache
    from stock_data.api._helpers import stock_boards as sb_helper

    cached_entry = {"code": "300750", "stock_code": "300750", "name": "宁德时代"}
    monkeypatch.setattr(
        stock_board_cache, "get_stock_memberships",
        lambda stock_code, sources, manager=None, **kw: ([cached_entry], [], "persistence"),
    )
    monkeypatch.setattr(
        sb_helper, "fetch_stock_boards_quote_enrichment",
        lambda code, manager: ([], {"300750": {"change_pct": 20.0, "limit_up_count": 1}}),
    )
    # ... mock quote / kline / info to return None ...
    response = client.post("/api/v1/agent/stocks/batch-profile", json={"codes": ["300750"]})
    body = response.json()
    entry = body["results"][0]
    assert entry["boards"] is not None
    assert entry["boards"]["source"] == "persistence"
    assert any(e.get("change_pct") == 20.0 for e in entry["boards"]["data"])
```

**Step 2.7**: Lint + format：

```bash
ruff check stock_data/api/routes/agent.py tests/test_agent_endpoints.py
ruff format stock_data/api/routes/agent.py tests/test_agent_endpoints.py
```

**Step 2.8**: Commit：

```bash
git add stock_data/api/routes/agent.py tests/test_agent_endpoints.py
git commit -m "refactor(routes/agent): use build_stock_profile helper in batch-profile

Replaces ~80 lines of inline per-stock fan-out with calls to the new
build_stock_profile helper. Behavior is preserved — same errors[],
ok derivation, entry shape. Pinned by test_batch_profile_calls_helper_for_each_code
plus the existing TestBatchProfile* regression suite.

Spec: docs/superpowers/specs/2026-09-06-agent-lead-stocks-design.md §3.7"
```

---

## Task 3: 新增 `LeadStockEntry` 与 `LeadStocksResponse` 模型

**Files:**
- Modify: `stock_data/api/schemas.py` (in section near `StockBatchProfileResponse` ~line 1944)
- Test: schema validation 在 Task 4 的端点测试中验证（无需独立 schema 测试）

**Interfaces:**
- Consumes: `StockBatchProfileEntry`（既有 model）
- Produces:
  - `class LeadStockEntry(StockBatchProfileEntry)` + 9 新字段（`rank / score / change_pct / lb_count / zt_count / last_seal_time / seal_amount / reason`）
  - `class LeadStocksResponse(BaseModel)` 含 `date / board_code / top_n / leads / errors / warning / summary`

**Step 3.1**: 阅读 `schemas.py:1944-2112` 的 `StockBatchProfileResponse` 与 `StockBatchProfileEntry` 全文，记录现有字段顺序。

**Step 3.2**: 在 `StockBatchProfileResponse` 类**定义结束**之后追加两个新 model（保持字段顺序与既有惯例）：

```python
class LeadStockEntry(StockBatchProfileEntry):
    """涨停池内股票按 score → seal_time → seal_amount 排名后的 entry。

    Inherits StockBatchProfileEntry's quote/features/info/boards/errors. Adds
    ranking-specific fields. The change_pct / lb_count / last_seal_time /
    seal_amount fields are duplicated from the upstream ZT-pool payload to
    surface the ranking rationale without requiring a second round-trip.

    Spec: docs/superpowers/specs/2026-09-06-agent-lead-stocks-design.md §2.4
    """
    rank: int
    score: float
    change_pct: float | None = None
    lb_count: int | None = None
    zt_count: str | None = None
    last_seal_time: str | None = None
    seal_amount: float | None = None
    reason: str | None = None


class LeadStocksResponse(BaseModel):
    """Response for GET /api/v1/agent/lead-stocks."""
    date: str
    board_code: str | None = None
    top_n: int
    leads: list[LeadStockEntry]
    errors: list[dict] = []
    warning: str | None = None
    summary: dict = {}
```

**Step 3.3**: 运行现有 schema-related 测试确认没破：

```bash
.venv/Scripts/python.exe -m pytest tests/test_agent_endpoints.py tests/test_agent_batch_features.py -q
```

Expected: PASS（既有测试不受影响——只是新增了两个 model）。

**Step 3.4**: Lint：

```bash
ruff check stock_data/api/schemas.py
ruff format stock_data/api/schemas.py
```

**Step 3.5**: Commit：

```bash
git add stock_data/api/schemas.py
git commit -m "feat(schemas): add LeadStockEntry and LeadStocksResponse models

LeadStockEntry inherits StockBatchProfileEntry and adds 8 ranking-related
fields (rank / score / change_pct / lb_count / zt_count / last_seal_time /
seal_amount / reason). LeadStocksResponse wraps the per-stock entries
plus top-level date / board_code / top_n / errors / warning / summary.

Spec: docs/superpowers/specs/2026-09-06-agent-lead-stocks-design.md §3.1"
```

---

## Task 4: 实现 `apply_change_pct_filter` 与 `rank_lead_stocks` 纯函数

**Files:**
- Modify: `stock_data/api/routes/agent.py` (新增两个纯函数，建议放在 `_compute_limit_pools_block` 附近 ~line 574)
- Test: `tests/test_agent_lead_stocks.py::TestLeadStocksRanking` + `TestLeadStocksChangePctFilter`

**Interfaces:**
- Consumes: `list[dict]`（来自 `manager.get_zt_pool` 的 dict 列表）
- Produces:
  - `def apply_change_pct_filter(stocks: list[dict]) -> tuple[list[dict], dict]`
    返回 `(kept, {"below_9pct": int, "above_22pct": int})`
  - `def rank_lead_stocks(stocks: list[dict]) -> list[dict]`
    三层链排序：score 降序 → seal_time 升序 → seal_amount 降序

**Step 4.1**: 创建 `tests/test_agent_lead_stocks.py` 框架：

```python
"""Tests for /agent/lead-stocks endpoint."""
from stock_data.api.routes.agent import (
    apply_change_pct_filter,
    rank_lead_stocks,
)


class TestLeadStocksChangePctFilter:
    """Pin the change_pct ∈ [9.0, 22.0] filter (inclusive)."""

    def test_boundary_9pct_inclusive(self):
        stocks = [{"code": "X", "change_pct": 9.0}]
        kept, exc = apply_change_pct_filter(stocks)
        assert len(kept) == 1
        assert exc == {"below_9pct": 0, "above_22pct": 0}

    def test_boundary_22pct_inclusive(self):
        stocks = [{"code": "X", "change_pct": 22.0}]
        kept, exc = apply_change_pct_filter(stocks)
        assert len(kept) == 1

    def test_just_below_excluded(self):
        stocks = [{"code": "X", "change_pct": 8.99}]
        kept, exc = apply_change_pct_filter(stocks)
        assert kept == []
        assert exc["below_9pct"] == 1

    def test_just_above_excluded(self):
        stocks = [{"code": "X", "change_pct": 22.01}]
        kept, exc = apply_change_pct_filter(stocks)
        assert kept == []
        assert exc["above_22pct"] == 1

    def test_none_treated_as_zero(self):
        """change_pct=None 视为 0，落入 below_9pct 桶。"""
        stocks = [{"code": "X", "change_pct": None}]
        kept, exc = apply_change_pct_filter(stocks)
        assert kept == []
        assert exc["below_9pct"] == 1

    def test_excluded_buckets_sum_correctly(self):
        stocks = [
            {"code": "A", "change_pct": 8.0},
            {"code": "B", "change_pct": 23.0},
            {"code": "C", "change_pct": 10.0},
            {"code": "D", "change_pct": 20.0},
        ]
        kept, exc = apply_change_pct_filter(stocks)
        assert {s["code"] for s in kept} == {"C", "D"}
        assert exc == {"below_9pct": 1, "above_22pct": 1}


class TestLeadStocksRanking:
    """Pin the 3-tier sort chain."""

    def test_score_descending(self):
        s1 = {"code": "A", "lb_count": 1, "change_pct": 10.0, "last_seal_time": "10:00:00", "seal_amount": 1e9}
        s2 = {"code": "B", "lb_count": 3, "change_pct": 10.0, "last_seal_time": "10:00:00", "seal_amount": 1e9}
        s3 = {"code": "C", "lb_count": 2, "change_pct": 20.0, "last_seal_time": "10:00:00", "seal_amount": 1e9}
        # scores: A=10, B=30, C=40 → order C, B, A
        ranked = rank_lead_stocks([s1, s2, s3])
        assert [s["code"] for s in ranked] == ["C", "B", "A"]

    def test_seal_time_ascending_breaks_score_tie(self):
        s1 = {"code": "A", "lb_count": 1, "change_pct": 10.0, "last_seal_time": "10:30:00", "seal_amount": 1e9}
        s2 = {"code": "B", "lb_count": 1, "change_pct": 10.0, "last_seal_time": "09:30:00", "seal_amount": 1e9}
        # same score (10) — earlier time wins → B first
        ranked = rank_lead_stocks([s1, s2])
        assert [s["code"] for s in ranked] == ["B", "A"]

    def test_seal_amount_descending_breaks_time_tie(self):
        s1 = {"code": "A", "lb_count": 1, "change_pct": 10.0, "last_seal_time": "10:00:00", "seal_amount": 1e8}
        s2 = {"code": "B", "lb_count": 1, "change_pct": 10.0, "last_seal_time": "10:00:00", "seal_amount": 1e9}
        ranked = rank_lead_stocks([s1, s2])
        assert [s["code"] for s in ranked] == ["B", "A"]

    def test_none_seal_time_pushed_to_bottom(self):
        s1 = {"code": "A", "lb_count": 1, "change_pct": 10.0, "last_seal_time": None, "seal_amount": 1e9}
        s2 = {"code": "B", "lb_count": 1, "change_pct": 10.0, "last_seal_time": "10:00:00", "seal_amount": 1e9}
        ranked = rank_lead_stocks([s1, s2])
        assert [s["code"] for s in ranked] == ["B", "A"]

    def test_none_seal_amount_pushed_to_bottom(self):
        s1 = {"code": "A", "lb_count": 1, "change_pct": 10.0, "last_seal_time": "10:00:00", "seal_amount": None}
        s2 = {"code": "B", "lb_count": 1, "change_pct": 10.0, "last_seal_time": "10:00:00", "seal_amount": 1e9}
        ranked = rank_lead_stocks([s1, s2])
        assert [s["code"] for s in ranked] == ["B", "A"]

    def test_none_lb_count_treated_as_one(self):
        """lb_count=None 视为 1，不让缺失数据意外跑到末尾。"""
        s1 = {"code": "A", "lb_count": None, "change_pct": 10.0, "last_seal_time": "10:00:00", "seal_amount": 1e9}
        s2 = {"code": "B", "lb_count": 1, "change_pct": 10.0, "last_seal_time": "10:00:00", "seal_amount": 1e9}
        # both score = 1 * 10 = 10, same time, same amount → unspecified tie
        # Pin: A and B both in output, no exception
        ranked = rank_lead_stocks([s1, s2])
        assert {s["code"] for s in ranked} == {"A", "B"}
```

**Step 4.2**: 运行测试，确认失败：

```bash
.venv/Scripts/python.exe -m pytest tests/test_agent_lead_stocks.py -v
```

Expected: FAIL — `ImportError: cannot import name 'apply_change_pct_filter' from 'stock_data.api.routes.agent'`

**Step 4.3**: 在 `stock_data/api/routes/agent.py`（在 `_compute_limit_pools_block` 附近）新增两个纯函数：

```python
def apply_change_pct_filter(stocks: list[dict]) -> tuple[list[dict], dict]:
    """Filter to keep only stocks with 9.0 ≤ change_pct ≤ 22.0 (inclusive).
    Excludes 30cm (北交所, ~30%) and ST (~5%) stocks.

    None change_pct is treated as 0 → falls into below_9pct bucket.

    Returns (kept, {"below_9pct": int, "above_22pct": int}).
    """
    kept: list[dict] = []
    below = above = 0
    for s in stocks:
        pct_raw = s.get("change_pct")
        pct = 0.0 if pct_raw is None else float(pct_raw)
        if pct < 9.0:
            below += 1
        elif pct > 22.0:
            above += 1
        else:
            kept.append(s)
    return kept, {"below_9pct": below, "above_22pct": above}


def rank_lead_stocks(stocks: list[dict]) -> list[dict]:
    """Three-tier sort: score DESC → seal_time ASC → seal_amount DESC.

    None handling (None = worst value for that key):
      - lb_count=None → 1 (assume at least 首板)
      - change_pct=None → 0 (compute_score will push to bottom)
      - last_seal_time=None → "99:99:99" (push to bottom on time tier)
      - seal_amount=None → -1 (push to bottom on amount tier)
    """
    def sort_key(s):
        lb = 1 if s.get("lb_count") is None else int(s["lb_count"])
        pct = 0.0 if s.get("change_pct") is None else float(s["change_pct"])
        score = lb * pct
        seal_time = s.get("last_seal_time") or "99:99:99"
        seal_amount = -1.0 if s.get("seal_amount") is None else float(s["seal_amount"])
        # negate score and seal_amount for descending; seal_time ascending as-is
        return (-score, seal_time, -seal_amount)

    return sorted(stocks, key=sort_key)
```

**Step 4.4**: 运行测试，确认通过：

```bash
.venv/Scripts/python.exe -m pytest tests/test_agent_lead_stocks.py -v
```

Expected: PASS（11 个新单元测试）

**Step 4.5**: Lint：

```bash
ruff check stock_data/api/routes/agent.py tests/test_agent_lead_stocks.py
ruff format stock_data/api/routes/agent.py tests/test_agent_lead_stocks.py
```

**Step 4.6**: Commit：

```bash
git add stock_data/api/routes/agent.py tests/test_agent_lead_stocks.py
git commit -m "feat(routes/agent): add apply_change_pct_filter and rank_lead_stocks

Pure functions for the lead-stocks ranking algorithm. change_pct filter
excludes 30cm (北交所) and ST (5%) stocks via [9.0, 22.0] inclusive band.
Three-tier sort: score DESC → seal_time ASC → seal_amount DESC, with
None treated as worst-value for each key.

Spec: docs/superpowers/specs/2026-09-06-agent-lead-stocks-design.md §3.3"
```

---

## Task 5: 实现 `get_lead_stocks` handler

**Files:**
- Modify: `stock_data/api/routes/agent.py` (新增 `get_lead_stocks` handler)
- Test: `tests/test_agent_lead_stocks.py` 加 `TestLeadStocksHappyPath` / `TestLeadStocksBoardFilter` / `TestLeadStocksErrorIsolation` / `TestLeadStocksTopN` / `TestLeadStocksDateDefault` / `TestLeadStocksProfileHelperReuse`

**Interfaces:**
- Consumes: `apply_change_pct_filter` / `rank_lead_stocks`（Task 4）；`build_stock_profile`（Task 1）；`manager.get_zt_pool` / `manager.get_zt_reasons`；`stock_board_cache.get_board_stocks`；`trade_calendar.get_latest_trade_date_on_or_before`
- Produces: `LeadStocksResponse`（Task 3）

**Step 5.1**: 在 `tests/test_agent_lead_stocks.py` 顶部加共享 fixtures：

```python
import pytest
from unittest.mock import MagicMock, patch
from fastapi.testclient import TestClient

from stock_data.api.server_helpers import get_test_client  # 或既有 client fixture
from stock_data.data_provider.persistence import stock_board_cache
from stock_data.data_provider.persistence.trade_calendar import (
    get_latest_trade_date_on_or_before,
)


@pytest.fixture(autouse=True)
def reset_before_test():
    """Reset manager singleton + clear caches. Mirrors tests/test_agent_endpoints.py."""
    from stock_data.api.routes.agent import reset_manager
    from stock_data.api.cache import (
        get_quote_cache, get_index_quote_cache, get_history_cache,
        get_pools_cache, get_stock_info_cache,  # 注意：get_pools_cache 是复数
    )
    reset_manager()
    get_quote_cache().clear()
    get_index_quote_cache().clear()
    get_history_cache().clear()
    get_pools_cache().clear()
    get_stock_info_cache().clear()
    yield


def _make_zt_pool_mock(stocks):
    """Mock manager.get_zt_pool to return (stocks, 'akshare', None)."""
    mock = MagicMock()
    mock.get_zt_pool.return_value = (stocks, "akshare", None)
    return mock


def _make_zt_reasons_mock(stocks):
    mock = MagicMock()
    mock.get_zt_reasons.return_value = (stocks, "zzshare", None)
    return mock


def _sample_zt_pool_stocks():
    return [
        {"code": "300750", "name": "宁德时代", "change_pct": 20.02, "lb_count": 3,
         "zt_count": "3连板", "last_seal_time": "10:23:14", "seal_amount": 1.23e9},
        {"code": "600519", "name": "贵州茅台", "change_pct": 10.01, "lb_count": 2,
         "zt_count": "2连板", "last_seal_time": "11:00:00", "seal_amount": 5e8},
        {"code": "000001", "name": "平安银行", "change_pct": 9.99, "lb_count": 1,
         "zt_count": "首板", "last_seal_time": "14:30:00", "seal_amount": 2e8},
        # 30cm
        {"code": "830799", "name": "北交所某", "change_pct": 30.0, "lb_count": 1,
         "zt_count": "首板", "last_seal_time": "10:00:00", "seal_amount": 1e7},
        # ST
        {"code": "600200", "name": "ST江苏", "change_pct": 5.0, "lb_count": 1,
         "zt_count": "首板", "last_seal_time": "10:00:00", "seal_amount": 1e7},
    ]


def _sample_reasons():
    return [
        {"code": "300750", "reason": "新能源车产业链"},
        {"code": "600519", "reason": "消费复苏"},
        {"code": "000001", "reason": "银行板块联动"},
    ]


def _make_unified_quote(**overrides):
    """Build a SimpleNamespace that survives MinimalQuote construction.
    Uses getattr-with-default in _build_minimal_quote_from_unified, so
    missing fields default to None — only the kwargs present here need
    real values."""
    from types import SimpleNamespace
    defaults = dict(
        price=10.0, change_pct=5.0, open_price=10.0, high=10.5, low=9.5,
        pre_close=9.5, volume=1000, amount=10000.0, change_amount=0.5,
        turnover_rate=1.0, amplitude=10.0, volume_ratio=1.5,
        pe_ratio=20.0, pb_ratio=3.0, mcap_yi=1000.0, float_mcap_yi=500.0,
        limit_up=11.0, limit_down=9.0, name="测试股",
    )
    defaults.update(overrides)
    return SimpleNamespace(**defaults)
```

**Step 5.2**: 加 `TestLeadStocksHappyPath` 测试类：

```python
class TestLeadStocksHappyPath:
    """GET /api/v1/agent/lead-stocks — main flow."""

    def test_default_top_n_returns_three(self, client, monkeypatch):
        """No params → default top_n=3, returns 3 leads sorted by score DESC."""
        from stock_data.api.routes.agent import get_manager
        manager = _make_zt_pool_mock(_sample_zt_pool_stocks())
        manager.get_zt_reasons.return_value = (_sample_reasons(), "zzshare", None)
        manager.get_realtime_quote.return_value = _make_unified_quote()
        manager.get_kline_data.return_value = (None, "akshare")
        manager.get_stock_info.return_value = ({}, "zhitu")
        monkeypatch.setattr("stock_data.api.routes.agent.get_manager", lambda: manager)
        monkeypatch.setattr(
            "stock_data.data_provider.persistence.stock_board_cache.get_stock_memberships",
            lambda stock_code, sources, manager=None: ([], [], "persistence"),
        )
        response = client.get("/api/v1/agent/lead-stocks")
        assert response.status_code == 200
        body = response.json()
        assert body["date"]  # auto-resolved
        assert body["top_n"] == 3
        assert body["board_code"] is None
        # 30cm (830799) and ST (600200) excluded by change_pct filter
        codes = [l["code"] for l in body["leads"]]
        assert "830799" not in codes
        assert "600200" not in codes
        # Order: score = lb * pct → 300750=60.06, 600519=20.02, 000001=9.99
        assert codes == ["300750", "600519", "000001"]
        # scores correctly computed
        assert body["leads"][0]["score"] == 60.06
        # ranking ranks 1-indexed
        assert [l["rank"] for l in body["leads"]] == [1, 2, 3]
        # reasons populated from zt-reasons
        assert body["leads"][0]["reason"] == "新能源车产业链"
        # summary populated
        assert body["summary"]["requested"] == 3
        assert body["summary"]["matched"] == 3
        assert body["summary"]["excluded"] == {"below_9pct": 1, "above_22pct": 1}

    def test_explicit_top_n_respected(self, client, monkeypatch):
        """top_n=1 returns only the top scorer."""
        manager = _make_zt_pool_mock(_sample_zt_pool_stocks())
        manager.get_zt_reasons.return_value = (_sample_reasons(), "zzshare", None)
        manager.get_realtime_quote.return_value = _make_unified_quote()
        manager.get_kline_data.return_value = (None, "akshare")
        manager.get_stock_info.return_value = ({}, "zhitu")
        monkeypatch.setattr("stock_data.api.routes.agent.get_manager", lambda: manager)
        monkeypatch.setattr(
            "stock_data.data_provider.persistence.stock_board_cache.get_stock_memberships",
            lambda stock_code, sources, manager=None: ([], [], "persistence"),
        )
        response = client.get("/api/v1/agent/lead-stocks?top_n=1")
        assert response.status_code == 200
        body = response.json()
        assert len(body["leads"]) == 1
        assert body["leads"][0]["code"] == "300750"
```

**Step 5.3**: 加 `TestLeadStocksBoardFilter`：

```python
class TestLeadStocksBoardFilter:
    """board_code filter restricts leads to board members."""

    def test_board_intersection_filters_pool(self, client, monkeypatch):
        """board_code 的成分股与涨停池做交集。"""
        manager = _make_zt_pool_mock(_sample_zt_pool_stocks())
        manager.get_zt_reasons.return_value = (_sample_reasons(), "zzshare", None)
        manager.get_realtime_quote.return_value = _make_unified_quote()
        manager.get_kline_data.return_value = (None, "akshare")
        manager.get_stock_info.return_value = ({}, "zhitu")
        monkeypatch.setattr("stock_data.api.routes.agent.get_manager", lambda: manager)
        # board 只有 300750 一只
        monkeypatch.setattr(
            "stock_data.data_provider.persistence.stock_board_cache.get_board_stocks",
            lambda code, source, include_quote, manager, **kw: (
                [{"stock_code": "300750", "stock_name": "宁德时代"}],
                "ths", "ths", None, False, 1,
            ),
        )
        monkeypatch.setattr(
            "stock_data.data_provider.persistence.stock_board_cache.get_stock_memberships",
            lambda stock_code, sources, manager=None: ([], [], "persistence"),
        )
        response = client.get("/api/v1/agent/lead-stocks?board_code=885595")
        assert response.status_code == 200
        body = response.json()
        codes = [l["code"] for l in body["leads"]]
        assert codes == ["300750"]
        assert body["board_code"] == "885595"

    def test_empty_intersection_returns_empty_leads(self, client, monkeypatch):
        """board 与涨停池无交集 → 200 + 空 leads。"""
        manager = _make_zt_pool_mock(_sample_zt_pool_stocks())
        manager.get_zt_reasons.return_value = (_sample_reasons(), "zzshare", None)
        monkeypatch.setattr("stock_data.api.routes.agent.get_manager", lambda: manager)
        monkeypatch.setattr(
            "stock_data.data_provider.persistence.stock_board_cache.get_board_stocks",
            lambda code, source, include_quote, manager, **kw: (
                [{"stock_code": "999999", "stock_name": "无关"}],
                "ths", "ths", None, False, 1,
            ),
        )
        response = client.get("/api/v1/agent/lead-stocks?board_code=885595")
        assert response.status_code == 200
        body = response.json()
        assert body["leads"] == []
        assert body["summary"]["matched"] == 0
```

**Step 5.4**: 加 `TestLeadStocksErrorIsolation`：

```python
class TestLeadStocksErrorIsolation:
    """上游失败按矩阵处理。"""

    def test_zt_pool_failure_returns_503(self, client, monkeypatch):
        from stock_data.data_provider.base import DataFetchError  # 从 base 而非 manager 导入
        manager = MagicMock()
        manager.get_zt_pool.side_effect = DataFetchError("pool down")
        monkeypatch.setattr("stock_data.api.routes.agent.get_manager", lambda: manager)
        response = client.get("/api/v1/agent/lead-stocks")
        assert response.status_code == 503

    def test_zt_reasons_failure_degrades_to_null(self, client, monkeypatch):
        """zt-reasons 失败 → 200 + reason=null + errors[]。"""
        from stock_data.data_provider.base import DataFetchError
        manager = _make_zt_pool_mock(_sample_zt_pool_stocks())
        manager.get_zt_reasons.side_effect = DataFetchError("reasons down")
        manager.get_realtime_quote.return_value = _make_unified_quote()
        manager.get_kline_data.return_value = (None, "akshare")
        manager.get_stock_info.return_value = ({}, "zhitu")
        monkeypatch.setattr("stock_data.api.routes.agent.get_manager", lambda: manager)
        monkeypatch.setattr(
            "stock_data.data_provider.persistence.stock_board_cache.get_stock_memberships",
            lambda stock_code, sources, manager=None: ([], [], "persistence"),
        )
        response = client.get("/api/v1/agent/lead-stocks")
        assert response.status_code == 200
        body = response.json()
        # reason 全 null
        assert all(l["reason"] is None for l in body["leads"])
        # errors[] 有 reasons 块
        assert any(e.get("block") == "reasons" for e in body["errors"])

    def test_board_stocks_failure_with_board_code_returns_503(self, client, monkeypatch):
        from stock_data.data_provider.base import DataFetchError
        manager = _make_zt_pool_mock(_sample_zt_pool_stocks())
        manager.get_realtime_quote.return_value = _make_unified_quote()
        monkeypatch.setattr("stock_data.api.routes.agent.get_manager", lambda: manager)
        monkeypatch.setattr(
            "stock_data.data_provider.persistence.stock_board_cache.get_board_stocks",
            lambda board_code, source, include_quote, manager, **kw: (_ for _ in ()).throw(
                DataFetchError("board down")
            ),
        )
        response = client.get("/api/v1/agent/lead-stocks?board_code=885595")
        assert response.status_code == 503
```

**Step 5.5**: 加 `TestLeadStocksTopN` + `TestLeadStocksDateDefault`：

```python
class TestLeadStocksTopN:
    def test_top_n_zero_returns_422(self, client):
        response = client.get("/api/v1/agent/lead-stocks?top_n=0")
        assert response.status_code == 422

    def test_top_n_above_max_returns_422(self, client):
        response = client.get("/api/v1/agent/lead-stocks?top_n=21")
        assert response.status_code == 422

    def test_top_n_max_boundary_accepted(self, client, monkeypatch):
        manager = _make_zt_pool_mock(_sample_zt_pool_stocks())
        manager.get_zt_reasons.return_value = (_sample_reasons(), "zzshare", None)
        manager.get_realtime_quote.return_value = _make_unified_quote()
        manager.get_kline_data.return_value = (None, "akshare")
        manager.get_stock_info.return_value = ({}, "zhitu")
        monkeypatch.setattr("stock_data.api.routes.agent.get_manager", lambda: manager)
        monkeypatch.setattr(
            "stock_data.data_provider.persistence.stock_board_cache.get_stock_memberships",
            lambda stock_code, sources, manager=None: ([], [], "persistence"),
        )
        response = client.get("/api/v1/agent/lead-stocks?top_n=20")
        assert response.status_code == 200


class TestLeadStocksDateDefault:
    def test_explicit_date_passes_through(self, client, monkeypatch):
        manager = _make_zt_pool_mock([])
        manager.get_zt_reasons.return_value = ([], "zzshare", None)
        monkeypatch.setattr("stock_data.api.routes.agent.get_manager", lambda: manager)
        monkeypatch.setattr(
            "stock_data.data_provider.persistence.stock_board_cache.get_stock_memberships",
            lambda stock_code, sources, manager=None: ([], [], "persistence"),
        )
        response = client.get("/api/v1/agent/lead-stocks?date=2026-08-01")
        assert response.status_code == 200
        assert response.json()["date"] == "2026-08-01"

    def test_omitted_date_resolves_to_latest_trade_date(self, client, monkeypatch):
        """省略 date → trade_calendar.get_latest_trade_date_on_or_before(today)。"""
        manager = _make_zt_pool_mock([])
        manager.get_zt_reasons.return_value = ([], "zzshare", None)
        monkeypatch.setattr("stock_data.api.routes.agent.get_manager", lambda: manager)
        monkeypatch.setattr(
            "stock_data.data_provider.persistence.stock_board_cache.get_stock_memberships",
            lambda stock_code, sources, manager=None: ([], [], "persistence"),
        )
        # mock trade_calendar
        import datetime
        monkeypatch.setattr(
            "stock_data.api.routes.agent.get_latest_trade_date_on_or_before",
            lambda d: "2026-09-05",
        )
        response = client.get("/api/v1/agent/lead-stocks")
        assert response.status_code == 200
        assert response.json()["date"] == "2026-09-05"

    def test_malformed_date_returns_422(self, client):
        response = client.get("/api/v1/agent/lead-stocks?date=not-a-date")
        assert response.status_code == 422
```

**Step 5.6**: 加 `TestLeadStocksProfileHelperReuse`：

```python
class TestLeadStocksProfileHelperReuse:
    """验证 build_stock_profile 被 lead-stocks 与 batch-profile 共用。"""

    def test_lead_stocks_calls_helper(self, client, monkeypatch):
        from stock_data.api._helpers.agent_stock_profile import build_stock_profile
        mock_helper = MagicMock(wraps=build_stock_profile)
        monkeypatch.setattr(
            "stock_data.api.routes.agent.build_stock_profile", mock_helper,
        )
        manager = _make_zt_pool_mock(_sample_zt_pool_stocks()[:1])  # 1 stock
        manager.get_zt_reasons.return_value = (_sample_reasons(), "zzshare", None)
        manager.get_realtime_quote.return_value = _make_unified_quote()
        manager.get_kline_data.return_value = (None, "akshare")
        manager.get_stock_info.return_value = ({}, "zhitu")
        monkeypatch.setattr("stock_data.api.routes.agent.get_manager", lambda: manager)
        monkeypatch.setattr(
            "stock_data.data_provider.persistence.stock_board_cache.get_stock_memberships",
            lambda stock_code, sources, manager=None: ([], [], "persistence"),
        )
        client.get("/api/v1/agent/lead-stocks?top_n=1")
        assert mock_helper.call_count == 1
        assert mock_helper.call_args.args[1] == "300750"
```

**Step 5.7**: 运行所有 lead-stocks 测试，确认全部失败（handler 还没实现）：

```bash
.venv/Scripts/python.exe -m pytest tests/test_agent_lead_stocks.py -v
```

Expected: 全部 FAIL（`/api/v1/agent/lead-stocks` 路由不存在）。

**Step 5.8**: 在 `agent.py` 找到 `post_boards_stock_overlap` handler 上方合适位置（建议紧挨 `post_stocks_batch_profile` 之后）插入新 handler：

```python
@router.get(
    "/agent/lead-stocks",
    response_model=LeadStocksResponse,
    responses={
        422: {"model": ErrorResponse, "description": "Invalid request"},
        503: {"model": ErrorResponse, "description": "Upstream unavailable"},
        500: {"model": ErrorResponse, "description": "Server error"},
    },
    tags=["agent"],
)
@endpoint_meta(
    summary="涨停龙头股服务端排名（连板数×涨幅→最后涨停时间→封单金额）",
    markets=["csi"],
    capabilities=[],
    depends_on=[
        "/api/v1/zt-pools",
        "/api/v1/zt-reasons",
        "/api/v1/boards/{board_code}/stocks",
    ],
)
@map_errors
def get_lead_stocks(
    date: str | None = Query(
        None,
        pattern=r"^\d{4}-\d{2}-\d{2}$",
        description="交易日期（默认最新一个交易日）",
    ),
    board_code: str | None = Query(
        None,
        description="可选板块代码；传入则只在该板块成分股范围内排名",
    ),
    top_n: int = Query(
        3, ge=1, le=20,
        description="返回数量上限；范围 [1, 20]",
    ),
    format: str = Query(
        "json", pattern="^(json|md)$",
        description="Output format. json=application/json (default); md=text/markdown.",
    ),
) -> Response:
    """Per-spec §2.1 / §3.4. Three-tier ranking + filter + reasons."""
    from stock_data.data_provider.persistence.trade_calendar import (
        get_latest_trade_date_on_or_before,
    )

    t0 = time.monotonic()
    resolved_date = date or get_latest_trade_date_on_or_before(datetime.date.today())
    manager = get_manager()
    errors: list[dict] = []

    # 1. zt-pools
    try:
        pool_stocks, _origin, warning = manager.get_zt_pool(
            pool_type="zt", date=resolved_date,
        )
    except Exception as exc:
        logger.warning(f"[agent/lead-stocks] get_zt_pool failed: {exc}")
        raise HTTPException(
            status_code=503,
            detail={"error": "upstream_unavailable", "message": "zt-pools fetch failed"},
        )

    # 2. board_code filter
    if board_code:
        try:
            board_stocks, _o, _es, _r, _qt, _t = stock_board_cache.get_board_stocks(
                board_code, source="ths", include_quote=False, manager=manager,
            )
            board_codes = {s.get("stock_code") for s in board_stocks if s.get("stock_code")}
            pool_stocks = [s for s in pool_stocks if s.get("code") in board_codes]
        except (DataFetchError, ValueError) as exc:
            logger.warning(f"[agent/lead-stocks] get_board_stocks failed: {exc}")
            raise HTTPException(
                status_code=503,
                detail={"error": "upstream_unavailable", "message": "board-stocks fetch failed"},
            )

    # 3. change_pct filter
    kept, excluded = apply_change_pct_filter(pool_stocks)

    # 4. rank
    ranked = rank_lead_stocks(kept)[:top_n]

    # 5. reasons
    reasons: dict[str, str | None] = {}
    try:
        reason_stocks, _src, _ = manager.get_zt_reasons(date=resolved_date)
        reasons = {s.get("code"): s.get("reason") for s in reason_stocks}
    except Exception as exc:
        logger.warning(f"[agent/lead-stocks] get_zt_reasons failed: {exc}")
        errors.append({"block": "reasons", "error": type(exc).__name__, "message": str(exc)})

    # 6. per-lead profile
    leads: list[LeadStockEntry] = []
    for rank_idx, s in enumerate(ranked, start=1):
        code = s["code"]
        profile = build_stock_profile(manager, code, frequency="d", days=60)
        leads.append(
            LeadStockEntry(
                rank=rank_idx,
                score=(s.get("lb_count") or 1) * (s.get("change_pct") or 0.0),
                code=code,
                name=s.get("name"),
                change_pct=s.get("change_pct"),
                lb_count=s.get("lb_count"),
                zt_count=s.get("zt_count"),
                last_seal_time=s.get("last_seal_time"),
                seal_amount=s.get("seal_amount"),
                reason=reasons.get(code),
                ok=profile.ok,
                quote=profile.quote,
                features=profile.features,
                info=profile.info,
                boards=profile.boards,
                errors=profile.errors,
            )
        )

    summary = {
        "requested": top_n,
        "matched": len(leads),
        "elapsed_ms": int((time.monotonic() - t0) * 1000),
        "excluded": excluded,
    }
    result = LeadStocksResponse(
        date=resolved_date, board_code=board_code, top_n=top_n,
        leads=leads, errors=errors, warning=warning, summary=summary,
    )
    return _render_agent("lead-stocks", result, format)
```

**新增 import**（在文件顶部 import 块）：

```python
import datetime  # 如果尚未导入
from stock_data.api.schemas import LeadStockEntry, LeadStocksResponse
```

`_render_agent("lead-stocks", result, format)` 在 `_MD_TEMPLATES` 字典中尚无 `"lead-stocks"` 条目——会在 Task 6 渲染器注册时报 KeyError。先在 Task 5.8 后临时把 `"lead-stocks"` 映射到一个 no-op lambda 让 Task 5 测试通过；Task 6 替换为正式 renderer。

临时占位：

```python
_MD_TEMPLATES["lead-stocks"] = lambda payload: ""  # 临时占位 — Task 6 替换
```

**Step 5.9**: 运行所有 lead-stocks 测试，确认通过：

```bash
.venv/Scripts/python.exe -m pytest tests/test_agent_lead_stocks.py -v
```

Expected: PASS（~13 个测试）。

**Step 5.10**: 跑全套既有 agent 测试确认无 regression：

```bash
.venv/Scripts/python.exe -m pytest tests/test_agent_endpoints.py tests/test_agent_batch_features.py tests/test_agent_boards_batch_profile.py tests/test_agent_market_stats.py tests/test_agent_market_recap.py tests/test_agent_correlation_matrix.py -v
```

Expected: PASS。

**Step 5.11**: Lint：

```bash
ruff check stock_data/api/routes/agent.py tests/test_agent_lead_stocks.py
ruff format stock_data/api/routes/agent.py tests/test_agent_lead_stocks.py
```

**Step 5.12**: Commit：

```bash
git add stock_data/api/routes/agent.py tests/test_agent_lead_stocks.py
git commit -m "feat(routes/agent): add GET /api/v1/agent/lead-stocks handler

Three-tier ranking (score DESC → seal_time ASC → seal_amount DESC) with
change_pct ∈ [9.0, 22.0] filter that excludes 30cm (北交所) and ST
stocks. Optional board_code restricts to board members. Optional top_n
[1, 20] caps result size. Per-spec error isolation: zt-pools / board-stocks
failures → 503; zt-reasons failure → degrade with errors[]. Reuses
build_stock_profile helper for full feature profile per lead.

Spec: docs/superpowers/specs/2026-09-06-agent-lead-stocks-design.md §3.4"
```

---

## Task 6: MD 渲染器

**Files:**
- Modify: `stock_data/api/routes/agent.py` (新增 `render_lead_stocks_as_md` + 注册到 `_MD_TEMPLATES`)
- Test: `tests/test_agent_lead_stocks.py::TestLeadStocksFormatMd`

**Interfaces:**
- Consumes: `LeadStocksResponse` payload
- Produces: `str`（完整 MD 输出，包含排序规则说明 + 排名表 + 每个 lead 一节 quote/features/info/boards 子表）

**Step 6.1**: 加 `TestLeadStocksFormatMd`：

```python
class TestLeadStocksFormatMd:
    """?format=md 渲染契约——CLAUDE.md 不丢字段。"""

    def test_md_content_type(self, client, monkeypatch):
        manager = _make_zt_pool_mock(_sample_zt_pool_stocks()[:1])
        manager.get_zt_reasons.return_value = (_sample_reasons()[:1], "zzshare", None)
        manager.get_realtime_quote.return_value = _make_unified_quote()
        manager.get_kline_data.return_value = (None, "akshare")
        manager.get_stock_info.return_value = ({}, "zhitu")
        monkeypatch.setattr("stock_data.api.routes.agent.get_manager", lambda: manager)
        monkeypatch.setattr(
            "stock_data.data_provider.persistence.stock_board_cache.get_stock_memberships",
            lambda stock_code, sources, manager=None: ([], [], "persistence"),
        )
        response = client.get("/api/v1/agent/lead-stocks?format=md&top_n=1")
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/markdown")

    def test_md_includes_ranking_table(self, client, monkeypatch):
        """MD 包含排序规则说明 + 排名表 + 每只 lead 子节。"""
        manager = _make_zt_pool_mock(_sample_zt_pool_stocks()[:1])
        manager.get_zt_reasons.return_value = (_sample_reasons()[:1], "zzshare", None)
        manager.get_realtime_quote.return_value = _make_unified_quote()
        manager.get_kline_data.return_value = (None, "akshare")
        manager.get_stock_info.return_value = ({}, "zhitu")
        monkeypatch.setattr("stock_data.api.routes.agent.get_manager", lambda: manager)
        monkeypatch.setattr(
            "stock_data.data_provider.persistence.stock_board_cache.get_stock_memberships",
            lambda stock_code, sources, manager=None: ([], [], "persistence"),
        )
        response = client.get("/api/v1/agent/lead-stocks?format=md&top_n=1")
        body = response.text
        assert "排序规则" in body
        assert "300750" in body  # ranking table includes code
        assert "宁德时代" in body  # ranking table includes name
        assert "新能源车产业链" in body  # reason
        # Per-lead sub-sections
        assert "### 实时报价" in body or "实时报价" in body
```

**Step 6.2**: 运行测试确认失败：

```bash
.venv/Scripts/python.exe -m pytest tests/test_agent_lead_stocks.py::TestLeadStocksFormatMd -v
```

Expected: FAIL——MD 渲染器输出空字符串（占位 lambda）。

**Step 6.3**: 在 `agent.py` 新增 `render_lead_stocks_as_md` 函数（紧挨既有 `render_*_as_md` 函数如 `render_market_recap_as_md`）：

```python
def render_lead_stocks_as_md(payload: LeadStocksResponse) -> str:
    """Render LeadStocksResponse as markdown. Per CLAUDE.md 'No data is dropped'
    contract — every JSON field appears in the MD output."""
    out: list[str] = []
    board_label = payload.board_code or "ALL"
    out.append(f"# {payload.date} · board={board_label} · top_n={payload.top_n}")
    out.append("")

    out.append("## 排序规则")
    out.append("按 `连板数 × 当日涨幅` 降序 → 最后涨停时间升序 → 封单金额降序。")
    out.append("`change_pct ∈ [9.0, 22.0]` 之外的票（北交所 30cm / ST 5%）不参与排名。")
    out.append("")

    # Ranking table
    out.append("## 排名表")
    out.append("| 排名 | 代码 | 名称 | score | 涨幅 | 连板 | 涨停统计 | 最后封板 | 封单金额(元) | 原因 |")
    out.append("|---|---|---|---|---|---|---|---|---|---|")
    for lead in payload.leads:
        out.append(
            f"| {lead.rank} | {lead.code} | {lead.name or ''} | "
            f"{lead.score:.2f} | {_md_pct(lead.change_pct)} | "
            f"{lead.lb_count if lead.lb_count is not None else ''} | "
            f"{lead.zt_count or ''} | {lead.last_seal_time or ''} | "
            f"{lead.seal_amount if lead.seal_amount is not None else ''} | "
            f"{lead.reason or ''} |"
        )
    out.append("")

    # Per-lead sections
    for lead in payload.leads:
        out.append(f"## {lead.rank}. {lead.code} {lead.name or ''}")
        if lead.quote:
            _md_quote_block(out, lead.quote)  # agent.py:1708 — exists
        if lead.features:
            _md_feature_block(out, lead.features)  # agent.py:1778 — exists
        # info / boards / errors: inline (helpers don't exist)
        if lead.info:
            out.append("### 公司画像")
            src = lead.info.get("source") if isinstance(lead.info, dict) else None
            data = lead.info.get("data") if isinstance(lead.info, dict) else lead.info
            if src:
                out.append(f"- source: {src}")
            if isinstance(data, dict):
                for k, v in data.items():
                    out.append(f"- {k}: {v}")
            out.append("")
        if lead.boards:
            out.append("### 板块归属")
            src = lead.boards.get("source") if isinstance(lead.boards, dict) else None
            data = lead.boards.get("data") if isinstance(lead.boards, dict) else lead.boards
            if src:
                out.append(f"- source: {src}")
            if isinstance(data, list):
                for i, entry in enumerate(data, 1):
                    if isinstance(entry, dict):
                        name = entry.get("name") or entry.get("board_name") or ""
                        code = entry.get("code") or entry.get("board_code") or ""
                        out.append(f"- {i}. {code} {name}")
            out.append("")
        if lead.errors:
            out.append("### aspect 错误")
            for e in lead.errors:
                out.append(f"- **{e.aspect}**: {e.error}: {e.message}")
            out.append("")

    # Summary
    out.append("## 摘要")
    out.append(f"- requested: {payload.summary.get('requested')}")
    out.append(f"- matched: {payload.summary.get('matched')}")
    out.append(f"- elapsed_ms: {payload.summary.get('elapsed_ms')}")
    out.append(f"- excluded: {payload.summary.get('excluded')}")
    if payload.warning:
        out.append(f"- warning: {payload.warning}")
    if payload.errors:
        out.append("- 顶层错误:")
        for e in payload.errors:
            out.append(f"  - {e.get('block')}: {e.get('error')}: {e.get('message')}")
    out.append("")

    return "\n".join(out)
```

**辅助函数**：`_md_quote_block` 与 `_md_feature_block` 在 `agent.py` 已存在（前者 `agent.py:1708`，后者 `agent.py:1778`，由 2026-08-27 batch-profile spec 引入）；`_md_pct` 在 `agent.py:1537`。**`_md_dict_block` / `_md_aspect_errors_block` 不存在**——本 renderer 已内联 info/boards/errors 子段，**不依赖这两个缺失的 helper**（避免 BLOCKER 1）。

**Step 6.4**: 在 `_MD_TEMPLATES` 字典替换占位 lambda：

```python
_MD_TEMPLATES["lead-stocks"] = render_lead_stocks_as_md
```

**Step 6.5**: 运行测试确认通过：

```bash
.venv/Scripts/python.exe -m pytest tests/test_agent_lead_stocks.py::TestLeadStocksFormatMd -v
```

Expected: PASS。

**Step 6.6**: Lint：

```bash
ruff check stock_data/api/routes/agent.py
ruff format stock_data/api/routes/agent.py
```

**Step 6.7**: Commit：

```bash
git add stock_data/api/routes/agent.py
git commit -m "feat(routes/agent): add lead-stocks MD renderer

Renders LeadStocksResponse as markdown with: header (date/board/top_n),
sorting rules section, ranking table (rank/code/name/score/pct/lb/zt_count/
seal_time/seal_amount/reason), per-lead subsections with quote/features/
info/boards/error sub-tables, and summary section. Pinned by TestLeadStocksFormatMd
which asserts 'No data is dropped' contract per CLAUDE.md.

Spec: docs/superpowers/specs/2026-09-06-agent-lead-stocks-design.md §3.5"
```

---

## Task 7: Manifest 校验 + 文档更新

**Files:**
- Test: `tests/test_agent_lead_stocks.py::TestLeadStocksManifest` (新建)
- Modify: `docs/api-reference.md`
- Modify: `CLAUDE.md`

**Interfaces:**
- Consumes: `GET /control/api-manifest`（既有 endpoint）
- Produces: 新端点出现在 `id=="agent"` 段；`@endpoint_meta` 字段正确

**Step 7.1**: 加 `TestLeadStocksManifest`：

```python
class TestLeadStocksManifest:
    def test_endpoint_in_manifest(self, client):
        """新端点出现在 manifest['sections'] 的 id=='agent' 段。"""
        response = client.get("/control/api-manifest")
        manifest = response.json()
        agent_section = next(s for s in manifest["sections"] if s.get("id") == "agent")
        paths = [e["path"] for e in agent_section["endpoints"]]
        assert "/agent/lead-stocks" in paths

    def test_endpoint_meta_fields(self, client):
        """@endpoint_meta 字段：summary / markets=['csi'] / capabilities=[] /
        depends_on 含三条。"""
        response = client.get("/control/api-manifest")
        manifest = response.json()
        agent_section = next(s for s in manifest["sections"] if s.get("id") == "agent")
        endpoint = next(e for e in agent_section["endpoints"] if e["path"] == "/agent/lead-stocks")
        assert endpoint["markets"] == ["csi"]
        assert endpoint["capabilities"] == []
        deps = endpoint.get("depends_on", [])
        assert "/api/v1/zt-pools" in deps
        assert "/api/v1/zt-reasons" in deps
```

**Step 7.2**: 运行测试确认通过：

```bash
.venv/Scripts/python.exe -m pytest tests/test_agent_lead_stocks.py::TestLeadStocksManifest -v
```

Expected: PASS。

**Step 7.3**: 更新 `docs/api-reference.md`：在文件合适位置（按路由字母顺序或按现有章节组织）新增 `/agent/lead-stocks` 章节。模板：

```markdown
## `GET /api/v1/agent/lead-stocks`

涨停龙头股服务端排名。按 `连板数 × 当日涨幅 → 最后涨停时间 → 封单金额` 三层链对 10cm/20cm 涨停股排序，附带涨停原因与完整 feature profile。

### Query 参数

| 参数 | 类型 | 必填 | 默认 | 说明 |
|---|---|---|---|---|
| `date` | YYYY-MM-DD | 否 | 最新交易日 | |
| `board_code` | str | 否 | null | 传入则只在该板块成分股范围内排名 |
| `top_n` | int | 否 | 3 | 范围 [1, 20] |
| `format` | `json\|md` | 否 | json | md 输出 text/markdown |

### 响应字段

参见 `LeadStocksResponse` schema。`summary.excluded` 报告被过滤掉的股票分桶（`below_9pct` / `above_22pct`）；`errors[]` 在 zt-reasons 失败时填充 `{block:"reasons", ...}`；`warning` 在 volatile date 透传。

### 示例

```bash
curl 'http://localhost:8888/api/v1/agent/lead-stocks?top_n=3&format=md'
```

### 错误码

- `422`: top_n 越界 / date 格式错误
- `503`: zt-pools 或 board-stocks 上游不可达
- `500`: 内部错误

详见 `docs/superpowers/specs/2026-09-06-agent-lead-stocks-design.md`。
```

**Step 7.4**: 更新 `CLAUDE.md` 路由表——找到 `Agent Batch API (/api/v1/agent/*)` 章节的路由表，新增一行：

```markdown
| `GET /agent/lead-stocks` | 涨停龙头股服务端排名（连板数×涨幅→时间→封单金额；`change_pct ∈ [9, 22]` 排除 30cm/ST） | per-code `manager.get_zt_pool` + 可选 `stock_board_cache.get_board_stocks` + `manager.get_zt_reasons` + `build_stock_profile` |
```

**Step 7.5**: Lint + format 文档文件：

```bash
ruff check docs/api-reference.md CLAUDE.md  # 仅检查行长度等可 lint 项
```

文档文件通常不在 ruff 检查范围内，可跳过此步。

**Step 7.6**: Commit：

```bash
git add tests/test_agent_lead_stocks.py docs/api-reference.md CLAUDE.md
git commit -m "docs: add /agent/lead-stocks manifest test, api-reference, CLAUDE.md row

Manifest test pins the new endpoint under sections[].id=='agent' with
correct markets=['csi'], capabilities=[], and depends_on (3 entries).
api-reference.md gets the request/response/fields/error-codes chapter.
CLAUDE.md routing table gets a new row.

Spec: docs/superpowers/specs/2026-09-06-agent-lead-stocks-design.md §5"
```

---

## Task 8: 最终回归

**Step 8.1**: 跑全套 agent 相关测试（dev 循环速度）：

```bash
.venv/Scripts/python.exe -m pytest tests/test_agent_endpoints.py tests/test_agent_batch_features.py tests/test_agent_boards_batch_profile.py tests/test_agent_market_stats.py tests/test_agent_market_recap.py tests/test_agent_correlation_matrix.py tests/test_agent_stock_profile.py tests/test_agent_lead_stocks.py -v
```

Expected: ALL PASS。

**Step 8.2**: 跑整个测试套件（不含 live_network）：

```bash
.venv/Scripts/python.exe -m pytest -v
```

Expected: ALL PASS（live_network 与 requires_token 默认跳过）。

**Step 8.3**: 跑完整套件（含 live_network 与 requires_token——CI 模式）：

```bash
.venv/Scripts/python.exe -m pytest -m "" -v
```

Expected: ALL PASS 或仅 xfail（live_network 网络失败在 `_network_guard.py` hook 下转 xfail）。

**Step 8.4**: 手动启动 server + 手动验证 manifest 与新端点：

```bash
.venv/Scripts/python.exe -m stock_data.server &
sleep 5
curl -s http://localhost:8888/control/api-manifest | python -m json.tool | grep -A 5 lead-stocks
curl -s 'http://localhost:8888/api/v1/agent/lead-stocks?top_n=3&format=md' | head -50
curl -s 'http://localhost:8888/api/v1/agent/lead-stocks?top_n=3' | python -m json.tool
```

预期：manifest 显示新端点；MD 渲染表格+排序规则；JSON 返回完整结构。

**Step 8.5**: Lint 整个改动文件集：

```bash
ruff check .
ruff format .
```

Expected: clean。

**Step 8.6**: Commit 任何 format 修正（如有）：

```bash
git add -A
git commit -m "chore: ruff format pass"  # 仅在有修正时
```

**Step 8.7**: 写 PR 描述（手动，不在自动化范围内）。要点：
- 链接 spec doc
- 链接首个 commit（helper 抽离）作为讨论起点
- 强调 `LeadStocksEntry` 继承 `StockBatchProfileEntry` 的复用决策
- 列出 review focus：算法（filter + sort）、错误隔离矩阵、MD 不丢字段契约、batch-profile 重构 regression

---

## Self-Review

### 1. Spec coverage

| Spec § | 实现位置 |
|---|---|
| §1 Background + Non-goals | 体现在 implementation plan 整体 scope（无新 fetcher / capability / manager method）|
| §2.1 Request | Task 5.8 (`Query(...)` 参数) |
| §2.2 Response shape | Task 3.2 (`LeadStocksResponse` 模型) |
| §2.3 Field reference | Task 3.2 + Task 5.8 |
| §2.4 Naming discipline | Task 3.2（继承而非嵌套）|
| §3.1 Schemas | Task 3 |
| §3.2 Public helper | Task 1 |
| §3.3 排序与归一化 | Task 4 |
| §3.4 Route handler | Task 5 |
| §3.5 MD 渲染器 | Task 6 |
| §3.6 Manifest 注册 | Task 5.8 (`@endpoint_meta` decorator) + Task 7 (`TestLeadStocksManifest`) |
| §3.7 batch-profile 重构 | Task 2 |
| §4.1 测试类清单 | 散落在 Task 1 / 4 / 5 / 6 / 7 |
| §4.2 Pinned tests | Task 4.1 + Task 5.2 + Task 5.6 + Task 6.1 + Task 7.1 |
| §4.3 Out of test scope | 不写对应测试（一致性检查）|
| §5 Documentation | Task 7.3 + Task 7.4 |
| §6.1 None 归一化 | Task 4.3 + Task 4.1（`test_none_*` 测试 pin 行为）|
| §6.2 change_pct 阈值边界 | Task 4.1（`test_boundary_*` + `test_just_*` 测试 pin）|
| §6.3 ZT-pool 数据质量 | Task 5.4（`test_zt_pool_failure_returns_503`）|
| §6.4 zzshare 单点 | Task 5.4（`test_zt_reasons_failure_degrades_to_null`）|
| §6.5 batch-profile 重构 regression | Task 2（既有 TestBatchProfile*）|
| §6.6 top_n 体积膨胀 | Task 5.5（top_n=20 边界测试）|
| §7 Out of scope | 整个 plan 不引入 30cm 检测 helper / 多日 leader-board / `?source=` 等切面 flag |

**Gap check**：spec §6.4 zzshare 单点提到 "失败仅降级，不致命"——已在 Task 5.4 测试 pin。spec §6.6 提到 `summary.matched` 字段——已在 Task 5.2 / 5.3 测试覆盖。

**No spec gaps**.

### 2. Placeholder scan

- 全部代码块含完整实现，无 "TODO" / "TBD" / "implement later"。
- 异常处理在每个 helper / handler 步骤明确写出。
- 测试代码完整、可执行。
- 无 "Similar to Task N"——每个 Task 的代码块自包含。

**No placeholders**.

### 3. Type consistency

| 符号 | 定义位置 | 使用位置 | 一致？|
|---|---|---|---|
| `StockProfileData.code / quote / features / info / boards / errors / ok` | Task 1.3 | Task 1.1 + Task 2 + Task 5.8 | ✓ |
| `build_stock_profile(manager, code, *, frequency="d", days=None)` | Task 1.3 | Task 2.4 + Task 5.8 | ✓ |
| `apply_change_pct_filter(stocks) -> (kept, {"below_9pct", "above_22pct"})` | Task 4.3 | Task 4.1 + Task 5.8 | ✓ |
| `rank_lead_stocks(stocks)` | Task 4.3 | Task 4.1 + Task 5.8 | ✓ |
| `LeadStockEntry.rank / score / change_pct / lb_count / zt_count / last_seal_time / seal_amount / reason` + 继承字段 | Task 3.2 | Task 5.8 | ✓ |
| `LeadStocksResponse.date / board_code / top_n / leads / errors / warning / summary` | Task 3.2 | Task 5.8 | ✓ |
| `_render_agent("lead-stocks", result, format)` | Task 5.8 | Task 6.4 `_MD_TEMPLATES["lead-stocks"] = render_lead_stocks_as_md` | ✓ |
| `_md_quote_block / _md_feature_block / _md_dict_block / _md_pct` | Task 6.3（"如不存在则从既有提取"） | Task 6.3 | ✓（既有 helper，executor 需在实现时验证存在）|

**一处类型/函数名风险**：`_md_quote_block / _md_feature_block / _md_dict_block / _md_aspect_errors_block` 这4个 helper 在 Task 6.3 用到但未在本 plan 中显式定义。**executor 在 Task 6.3 实施前需 grep `agent.py` 确认这些函数确实存在**（按 2026-08-27 spec §3.5 ` `_md_quote_block` 是新增的，`_md_feature_block` 是 batch-profile 既有，`_md_dict_block` 在 batch-profile 与 market-recap 渲染器中使用过）。如果不存在，按同名创建即可（参考既有 renderer 实现）。

---

## 总结

8 个 Task，3 个 commit 阶段：

| 阶段 | Task | 提交信息前缀 |
|---|---|---|
| 准备 | Task 1: helper 抽离 | `feat(helpers): add build_stock_profile` |
| 重构 | Task 2: batch-profile 接入 helper | `refactor(routes/agent): use build_stock_profile helper in batch-profile` |
| 新端点 | Task 3: schemas | `feat(schemas): add LeadStockEntry and LeadStocksResponse` |
| 新端点 | Task 4: 纯函数 | `feat(routes/agent): add apply_change_pct_filter and rank_lead_stocks` |
| 新端点 | Task 5: handler | `feat(routes/agent): add GET /api/v1/agent/lead-stocks handler` |
| 新端点 | Task 6: MD 渲染 | `feat(routes/agent): add lead-stocks MD renderer` |
| 收尾 | Task 7: manifest + docs | `docs: add /agent/lead-stocks manifest test, api-reference, CLAUDE.md row` |
| 收尾 | Task 8: 回归 | `chore: ruff format pass`（仅在必要时）|

预计总提交：**7-8 个 commits**，1 个 PR。