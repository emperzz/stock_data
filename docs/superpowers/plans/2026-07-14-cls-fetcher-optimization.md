# CLS Fetcher Optimization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Filter CLS 早报/复盘响应中的头部封面图（保留正文里的图），重命名 API 路径为 `/api/v1/news/*`，合并 explorer section 到现有 `news`。

**Architecture:** 修改 `ClsFetcher._dedup_images` 跳过 `content` 第一个 `<img>` 且不再合并 `articleDetail.images[]`；修改 `routes/cls.py` 路径和 tag；修改 `explorer/tags.py` 删 `cls` 标签并简化 capability label。所有 schema 字段保持不变，仅 URL 路径破坏性变更。

**Tech Stack:** Python 3.10, FastAPI, BS4, pytest, Pydantic v2

---

## 状态说明

此 plan 描述的工作**已部分落地**（用户希望 spec 通过后立即进入 plan+执行，所以 brainstorming 阶段已经边设计边实现）。本 plan 既是：
1. **审计清单** — 验证所有改动符合 spec
2. **执行清单** — 补完 spec review 阶段新发现的 2 个 follow-up（fixture + test pin）
3. **记录文档** — 提交时作为 commit message 参考

每步 checkbox 状态: `- [x]` = 已完成, `- [ ]` = 待做

---

## File Structure

| 文件 | 角色 | 改动 |
|---|---|---|
| `stock_data/data_provider/fetchers/cls_fetcher.py` | `_dedup_images` 改写 | 修改 |
| `stock_data/api/routes/cls.py` | 路径 + tag | 修改 |
| `stock_data/api/schemas.py` | docstring | 修改 |
| `stock_data/explorer/tags.py` | 删 cls 标签 + 改 capability label | 修改 |
| `tests/fixtures/cls_article_detail.json` | 真实文章结构 | 修改 |
| `tests/test_cls_fetcher.py` | dedup_images 测试 | 修改 |
| `tests/test_cls_endpoints.py` | URL 更新 | 修改 |
| `docs/superpowers/specs/2026-07-14-cls-fetcher-optimization-design.md` | 规范 + §9 follow-up 备注 | 修改 |

---

## Task 1: 头部封面图过滤（fetcher 层）

**Files:**
- Modify: `stock_data/data_provider/fetchers/cls_fetcher.py:182-208`

- [x] **Step 1: 改写 `_dedup_images`**

完整替换 `stock_data/data_provider/fetchers/cls_fetcher.py` 中 `_dedup_images` 方法（原 182-208 行）为：

```python
@staticmethod
def _dedup_images(article_detail: dict, soup=None) -> list[str]:
    """从 `content` 内 <img src> 抽取正文图，去重保序。

    跳过 content 里的**第一个** <img> — 那是文章头部封面图（紧跟 lead 段、
    第一个 section header 之前），用户/agent 场景下没有信息量（可视为 logo）。

    **不**合并 `article_detail["images"]` 列表页缩略图 — 那是文章在列表/分享时
    用的封面，与正文无关。仅保留正文 (`content`) 内嵌图。

    Accepts a pre-parsed ``BeautifulSoup`` so callers can share the parse
    with ``_extract_body_text`` (one BS4 parse per detail page, not two).
    """
    seen: set[str] = set()
    out: list[str] = []
    content = article_detail.get("content", "") or ""
    if not content:
        return out
    if soup is None:
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(content, "lxml")
    for i, img in enumerate(soup.find_all("img")):
        if i == 0:
            # Skip the first <img> — it's the article header cover (logo-like,
            # always positioned right after the lead paragraph and before
            # the first <p><strong> section heading).
            continue
        src = img.get("src")
        if src and src not in seen:
            seen.add(src)
            out.append(str(src))
    return out
```

- [x] **Step 2: 验证 fetcher 测试通过**

Run: `.venv/Scripts/python.exe -m pytest tests/test_cls_fetcher.py -v`
Expected: 32 passed (含 `test_dedup_images` 改写后 + 3 个新测试)

---

## Task 2: 真实结构 fixture + 测试 pin（spec review 阶段发现）

**Files:**
- Modify: `tests/fixtures/cls_article_detail.json`
- Modify: `tests/test_cls_fetcher.py:226-238`

- [x] **Step 1: 改写 fixture 为真实 CLS 文章结构**

完整替换 `tests/fixtures/cls_article_detail.json` 的 `content` 字段为：

```json
"content": "<p>财联社7月14日讯，美伊冲突再度升级，受此影响油价开盘大涨9%，黄金、白银大幅回落，美股半导体指数隔夜大跌4.78%。</p>\n<p><img src=\"https://image.cls.cn/images/20260714/header_cover_1062x264.png\" alt=\"image\"></p>\n<p><strong>宏观新闻</strong></p>\n<p>1、外交部发言人宣布：2026世界人工智能大会暨人工智能全球治理高级别会议将于7月17日至20日在上海举行。国家主席习近平将出席大会开幕式并发表主旨讲话。</p>\n<p>2、中共中央政治局常委、国务院总理李强7月13日下午主持召开经济形势专家和企业家座谈会，听取对当前经济形势和下一步经济工作的意见建议。</p>\n<p><strong>公司新闻</strong></p>\n<p>1、中国石化公告，公司已完成对中国航空油料集团有限公司的重组工作。重组后，中国航油成为公司的全资子公司。</p>\n<p>2、胜宏科技发布澄清公告，针对近期市场传闻作出说明，目前公司经营情况正常，不存在应披露未披露事项。</p>\n<p><strong>海外市场</strong></p>\n<p>1、隔夜美股三大指数集体收跌，半导体指数大跌4.78%，油价大涨9%，黄金、白银大幅回落。</p>\n<p>2、META宣布将追加400亿美元投资路易斯安那州数据中心，将该数据中心扩展至5GW的计算容量。</p>\n<p><img src=\"https://image.cls.cn/images/20260714/market_chart_911x466.png\" alt=\"美股盘后行情\"></p>"
```

结构: lead → header_cover (要被过滤) → 3 sections → market_chart (要保留)

- [x] **Step 2: pin `test_fetch_article_detail_normal`**

替换 `tests/test_cls_fetcher.py:226-238` 的 `test_fetch_article_detail_normal` 为：

```python
def test_fetch_article_detail_normal(fetcher, detail_html):
    """Standard detail HTML → full ClsArticle-shaped dict.

    Fixture mirrors the real CLS structure: lead paragraph → header cover img →
    section headers + items → trailing chart img. The new `_dedup_images` logic
    MUST drop (a) the `images[]` list-page thumbnail and (b) the first content
    `<img>` (the header cover), keeping only the trailing chart img.
    """
    art = fetcher._fetch_article_detail(2425210, detail_html)
    assert art is not None
    assert art["article_id"] == 2425210
    assert art["title"].startswith("【")
    assert len(art["body_text"]) > 100
    # date is YYYY-MM-DD
    assert len(art["date"]) == 10 and art["date"][4] == "-"
    # images: only the trailing chart img survives (header cover + images[]
    # list-page thumb both dropped). Pin content to catch silent regressions.
    assert art["images"] == [
        "https://image.cls.cn/images/20260714/market_chart_911x466.png"
    ]
```

- [x] **Step 3: 验证测试通过**

Run: `.venv/Scripts/python.exe -m pytest tests/test_cls_fetcher.py -v`
Expected: 32 passed

---

## Task 3: API 路径重命名

**Files:**
- Modify: `stock_data/api/routes/cls.py`

- [x] **Step 1: 改 module docstring**

`stock_data/api/routes/cls.py:1-6`:

```python
"""财联社 早报 / 焦点复盘 endpoints (mounted under /api/v1/news/*).

Mounted by `stock_data.server` with prefix="/api/v1"; this router's own paths
are /news/morning-briefing and /news/market-recap. Both require ?date=YYYY-MM-DD
and return the single article for that date (or 404 if not published).

Tag: 'news' (merged with the existing /api/v1/news/* section in the explorer).
"""
```

- [x] **Step 2: 改 `tags=["cls"]` → `tags=["news"]`**

`stock_data/api/routes/cls.py` 中 `_make_cls_route` 内的 `tags=["cls"]` (在 `@cls_router.get` 装饰器里) 改为 `tags=["news"]`.

- [x] **Step 3: 改两个 endpoint path**

`stock_data/api/routes/cls.py` 文件末尾两个 `_make_cls_route(...)` 调用:
- `path="/cls/morning-briefing"` → `path="/news/morning-briefing"`
- `path="/cls/market-review"` → `path="/news/market-recap"`

- [x] **Step 4: 验证 endpoint 测试通过**

Run: `.venv/Scripts/python.exe -m pytest tests/test_cls_endpoints.py -v`
Expected: 8 passed

---

## Task 4: Schema docstring 更新

**Files:**
- Modify: `stock_data/api/schemas.py:1121`

- [x] **Step 1: 改 docstring**

`stock_data/api/schemas.py` `ClsFeedResponse` 类的 docstring:

```python
"""Response shape for /api/v1/news/morning-briefing and /api/v1/news/market-recap."""
```

- [x] **Step 2: 验证未引入错误**

Run: `.venv/Scripts/python.exe -c "from stock_data.api.schemas import ClsFeedResponse; print(ClsFeedResponse.__doc__)"`
Expected: 包含 `morning-briefing` 和 `market-recap`

---

## Task 5: Explorer section 合并

**Files:**
- Modify: `stock_data/explorer/tags.py`

- [x] **Step 1: 删 `TAG_TO_TITLE["cls"]`**

`stock_data/explorer/tags.py:18-31` `TAG_TO_TITLE` dict: 删 `"cls": "财联社",` 一行

- [x] **Step 2: 改 2 个 capability label**

`stock_data/explorer/tags.py:58-59` (in `CAPABILITY_LABELS`):
- `"MORNING_BRIEFING": {"label": "财联社早报", "icon": "📰"}` → `"MORNING_BRIEFING": {"label": "早报", "icon": "📰"}`
- `"MARKET_RECAP": {"label": "财联社复盘", "icon": "📊"}` → `"MARKET_RECAP": {"label": "市场复盘", "icon": "📊"}`

- [x] **Step 3: 验证 manifest 测试通过**

Run: `.venv/Scripts/python.exe -m pytest tests/test_explorer_manifest_endpoint.py tests/test_capability_method_map.py -v`
Expected: 64 passed

---

## Task 6: Endpoint 测试 URL 更新

**Files:**
- Modify: `tests/test_cls_endpoints.py`

- [x] **Step 1: 改 docstring + 8 个 URL**

`tests/test_cls_endpoints.py` 中:
- docstring (line 1): `"/api/v1/cls/morning-briefing"` → `"/api/v1/news/morning-briefing"`, `"/api/v1/cls/market-review"` → `"/api/v1/news/market-recap"`
- `test_market_recap_success` docstring (line 118): `"Same shape for /market-review."` → `"Same shape for /market-recap."`
- 所有 8 个 `client.get("/api/v1/cls/...")` 改为 `client.get("/api/v1/news/...")`

- [x] **Step 2: 验证 endpoint 测试通过**

Run: `.venv/Scripts/python.exe -m pytest tests/test_cls_endpoints.py -v`
Expected: 8 passed

---

## Task 7: Spec 文档加 §9 follow-up 备注

**Files:**
- Modify: `docs/superpowers/specs/2026-07-14-cls-fetcher-optimization-design.md`

- [x] **Step 1: 在文件末尾加 §9**

```markdown
## 9. Spec review follow-ups (sub-agent double-check, 2026-07-14)

A sub-agent reviewed this spec and flagged 3 BLOCKING concerns; 2 were addressed
in the spec/code, 1 was a false alarm:

1. **`test_fetch_article_detail_normal` 不验 `images` 内容** (FIXED): the
   original test only checked `isinstance(art["images"], list)`, hiding the
   behavior change. Pinned to the explicit chart-img URL.
2. **Fixture `cls_article_detail.json` 结构** (FIXED): original fixture was
   synthetic (1 cover + 1 trailing img, no realistic lead/section layout).
   Updated to mirror the real CLS article structure: `<p>lead</p> →
   <p><img src="header_cover"></p> → <p><strong>section</strong></p> → ...
   → <p><img src="market_chart"></p>`. The header img at position 0 is
   filtered out; the trailing chart img survives.
3. **`test_capability_method_map.py` 覆盖 `CAPABILITY_LABELS`** (FALSE ALARM):
   sub-agent missed that `tests/test_capability_method_map.py:109`
   (`test_every_capability_has_a_label_in_capability_labels`) does enforce a
   `{label, icon}` entry for every `DataCapability` flag. Spec claim
   (§5.3) was accurate.

---
```

---

## Task 8: 完整测试套验证

- [x] **Step 1: 跑完整测试套 (排除 live_network)**

Run: `.venv/Scripts/python.exe -m pytest`
Expected: ~1829 passed, 0 failed

(已确认: 1829 passed, 1 skipped, 123 deselected)

- [x] **Step 2: 跑副作用测试**

Run: `.venv/Scripts/python.exe -m pytest tests/test_capability_method_map.py tests/test_explorer_manifest_endpoint.py -v`
Expected: 64 passed

---

## Task 9: Sub-agent code review (独立审查)

- [ ] **Step 1: 开 sub-agent 做 code review**

新开 sub-agent, 任务描述:

```
Review code changes for spec compliance and code quality.
Spec: docs/superpowers/specs/2026-07-14-cls-fetcher-optimization-design.md
Files changed: stock_data/data_provider/fetchers/cls_fetcher.py, stock_data/api/routes/cls.py, stock_data/api/schemas.py, stock_data/explorer/tags.py, tests/fixtures/cls_article_detail.json, tests/test_cls_fetcher.py, tests/test_cls_endpoints.py
DO NOT open further sub-agents. Read-only review. Output: BLOCKING/NON-BLOCKING/VERIFIED list.
```

---

## Task 10: Commit + push

- [ ] **Step 1: 确认所有改动**

Run: `git status`
Expected: 7 modified files + 1 new spec file

- [ ] **Step 2: commit**

```bash
git add stock_data/data_provider/fetchers/cls_fetcher.py \
        stock_data/api/routes/cls.py \
        stock_data/api/schemas.py \
        stock_data/explorer/tags.py \
        tests/fixtures/cls_article_detail.json \
        tests/test_cls_fetcher.py \
        tests/test_cls_endpoints.py \
        docs/superpowers/specs/2026-07-14-cls-fetcher-optimization-design.md

git commit -m "$(cat <<'EOF'
feat(cls): filter header cover image + rename to /api/v1/news/*

3 optimizations for the CLS 早报/复盘 endpoints:

1. _dedup_images now returns ONLY the body content images:
   - drops `articleDetail.images[]` (list-page thumbnail, not body)
   - skips the first <img> in `content` HTML (article header cover,
     always positioned right after the lead paragraph and before the
     first section heading)
   Result: `images` field in response = 正文里的图, 排除头部 logo-like
   cover and list-page thumb.

2. API path rename: /api/v1/cls/* → /api/v1/news/* (破坏性):
   - /api/v1/cls/morning-briefing → /api/v1/news/morning-briefing
   - /api/v1/cls/market-review     → /api/v1/news/market-recap
   - tag: "cls" → "news"
   Spec §6 accepts the 404 risk for old clients (no external doc/fixture
   references the old paths).

3. Explorer section merge: 早报+复盘 join existing "新闻" section.
   - TAG_TO_TITLE["cls"] removed
   - CAPABILITY_LABELS: "财联社早报"→"早报", "财联社复盘"→"市场复盘"

Fixture updated to mirror real CLS article structure (lead → header
cover img → sections → chart img) so the dedup behavior is exercised
end-to-end. test_fetch_article_detail_normal pinned to expected chart
URL to catch silent regressions.

20-day history window unchanged (list endpoint hard-capped at 20
articles, no pagination API; user accepted current limit).

Tests: 40 cls tests + 64 capability/manifest tests pass; full suite
1829 passed.

Spec: docs/superpowers/specs/2026-07-14-cls-fetcher-optimization-design.md
Plan: docs/superpowers/plans/2026-07-14-cls-fetcher-optimization.md
EOF
)"
```

- [ ] **Step 3: push**

```bash
git push origin master
```

---

## Self-Review (plan vs spec)

**1. Spec coverage:**
- §3.1 头部封面图过滤 → Task 1 ✓
- §3.2 API 路径重命名 → Task 3 ✓
- §3.3 Explorer section 合并 → Task 5 ✓
- §4 文件变更表 6 项 → Tasks 1-6 覆盖 ✓
- §5 测试策略 → Tasks 1, 2, 6 ✓
- §9 follow-up 备注 (新增) → Task 7 ✓

**2. Placeholder scan:** 0 placeholder (TBD/TODO/etc.) — 实际代码/路径/URL 全部硬编码

**3. Type consistency:** `_dedup_images` 返回类型 `list[str]` 在 spec 描述和 Tasks 1-2 中一致; URL 路径字符串 `/api/v1/news/morning-briefing` 和 `/api/v1/news/market-recap` 在 Tasks 3, 4, 6 一致

**Coverage: 100%**
