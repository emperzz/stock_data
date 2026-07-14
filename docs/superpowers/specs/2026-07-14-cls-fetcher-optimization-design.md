# CLS Fetcher Optimization — 头部封面图过滤 + 路径重命名

**Date:** 2026-07-14
**Status:** Approved (user-confirmed during brainstorming)
**Scope:** 3 个独立优化，6 个文件变更，零 schema 破坏（仅 URL 路径破坏性变更）
**Supersedes:** N/A（与现有 2026-07-14-cls-fetcher-design.md 并行 — 本 spec 描述该 spec 落地后的第二轮优化）

---

## 1. Goal

3 个独立优化（用户 2026-07-14 提出）：

1. **过滤 CLS 早报/复盘响应中的"头部封面图"** — 用户描述："logo图片无实际意义，看起来像是第一张图片"
2. **API 路径重命名** — 从 `/api/v1/cls/*` 改为 `/api/v1/news/*`，与已有 `/api/v1/news/flash` 等命名空间统一
3. **20 天窗口扩展** — 探查后决定**不扩展**（list 端点硬编码 20 篇，无分页 API；用户接受现状）

---

## 2. 调查结果（playwright 2026-07-14 实测）

### 2.1 头部封面图位置

CLS 文章 `__NEXT_DATA__.props.pageProps.articleDetail` 结构：
- `images` 字段：列表页/分享用的缩略图（1 张）
- `content` 字段：HTML 字符串，正文（含 `<p>` 和 `<img>`）

| 文章 | `images[]` | `content` 内 `<img>` | 第 1 张位置 |
|---|---|---|---|
| 早报 2026-07-13 (id=2423960) | 1 张 (列表页缩略图) | 1 张: `u7JbjM58m8_1062x264.png` | body 第 1 个 `<p>` |
| 复盘 2026-07-13 (id=2424673) | 1 张 (列表页缩略图) | 4 张: 851vvXi7Rd, Guk5GFb634, 322277Mizw, s2z3UM8eJC | lead 段后、`<p><strong>人气及连板股分析</strong></p>` 之前 |
| 复盘 2026-07-14 (id=2425998) | `Ll73DEck7i_780x506.png` (列表页缩略图) | 4 张: 4HXJK0Ewx6, ekjF2FijKj, 42SY0RElB6, S45rlqZ3XE | 同上 |

**结论**：`content` 里**第一个 `<img>` 总是头部封面图**（位于 lead 段后、第一个 section header 前）。早报通常只 1 张（且就是 header），复盘 3-4 张（header + 涨停分析图等）。

### 2.2 20 天窗口扩展

| 探查 | 结论 |
|---|---|
| `/subject/{id}` list 端点 | 硬编码返 20 篇，无 cursor/page 参数 |
| `/detail/{id}.json` 详情端点 | 任意有效 article_id 都能返（试了 2024/2025/2026 老 ID 都行）|
| 详情页 JSON "上一篇/下一篇" 字段 | 不存在（associatedFastFact / assocArticleUrl 均为空）|
| 搜索接口 `/searchPage` | WAF 反爬（"Please Enable JavaScript and Cookie"）|
| Sitemap / RSS | 不存在（sitemap.xml / robots.txt 都是 HTML）|

**结论**：扩展不可行。详情 API 接受任意 article_id 但没有"由日期反查 ID"的机制。用户接受 20 天限制。

---

## 3. 设计方案

### 3.1 头部封面图过滤（用户已确认范围）

**唯一保留**：正文 (`content`) 内嵌图，**跳过第一个**。
**丢弃**：
- `articleDetail.images[]`（列表页缩略图）— 与正文无关
- `content` 内第一个 `<img>`（头部封面/logo）— 用户描述："logo图片无实际意义，看起来像是第一张图片"

**用户明确**：需要的是"正文里的images"，其他图片（列表页缩略图 + 头部封面）都不需要。

**实现** (`stock_data/data_provider/fetchers/cls_fetcher.py::_dedup_images`)：

```python
@staticmethod
def _dedup_images(article_detail: dict, soup=None) -> list[str]:
    """从 `content` 内 <img src> 抽取正文图，去重保序。

    跳过 content 里的**第一个** <img> — 那是文章头部封面图（紧跟 lead 段、
    第一个 section header 之前），用户/agent 场景下没有信息量（可视为 logo）。

    **不**合并 `article_detail["images"]` 列表页缩略图 — 那是文章在列表/分享时
    用的封面，与正文无关。仅保留正文 (`content`) 内嵌图。
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
            continue  # 跳过第一张 (头部封面图)
        src = img.get("src")
        if src and src not in seen:
            seen.add(src)
            out.append(str(src))
    return out
```

**行为变化**（按文章类型）：

| 类型 | 过滤前 images | 过滤后 images |
|---|---|---|
| 早报 (0-1 张正文图 + 1 张 `images[]`) | 1-2 张 | 0 张 |
| 复盘 (3-4 张正文图 + 1 张 `images[]`) | 4-5 张 | 2-3 张（去掉 header 保留 涨停分析图 等） |

`body_text` 不受影响（BS4 `get_text` 不输出 `<img>` 的 src/alt 属性）。

### 3.2 API 路径重命名

| Before | After |
|---|---|
| `GET /api/v1/cls/morning-briefing` | `GET /api/v1/news/morning-briefing` |
| `GET /api/v1/cls/market-review` | `GET /api/v1/news/market-recap` |

- **破坏性变更** — 旧 `/api/v1/cls/*` 路径不再有效。这是 server 内部 API 命名空间调整，CLAUDE.md "explorer 是 source of truth" 约定。
- `subject` 响应字段**不变**（仍为 `"morning_briefing"` / `"market_review"`，作为 cache namespace）
- Response schema 不变
- `@endpoint_meta` 装饰器 `tags=["cls"]` → `tags=["news"]`

### 3.3 Explorer section 合并

**`stock_data/explorer/tags.py`** 改动：
- 删除 `TAG_TO_TITLE["cls"] = "财联社"`（不再有独立 section）
- `CAPABILITY_LABELS["MORNING_BRIEFING"]`: `"财联社早报"` → `"早报"`
- `CAPABILITY_LABELS["MARKET_RECAP"]`: `"财联社复盘"` → `"市场复盘"`

**视觉影响**：`/explorer/` 的"新闻" section 现在含 5 个 endpoint（flash / search / stock / morning-briefing / market-recap）；原"财联社" section 消失。

---

## 4. 文件变更

| 路径 | 改动类型 | 说明 |
|---|---|---|
| `stock_data/data_provider/fetchers/cls_fetcher.py` | 修改 | `_dedup_images` 改写（约 -15 行 / +20 行），跳过第一个 content img + 不再合并 images[] |
| `stock_data/api/routes/cls.py` | 修改 | path 改 `/cls/*` → `/news/*`, `/market-review` → `/market-recap`, `tags=["cls"]` → `tags=["news"]` |
| `stock_data/api/schemas.py` | 修改 | docstring 改路径 |
| `stock_data/explorer/tags.py` | 修改 | 删 `cls` tag entry, 改 2 个 capability labels |
| `tests/test_cls_fetcher.py` | 修改 | 改 `test_dedup_images` 期望; 加 3 个新测试 (no_content, only_one_skipped, empty_content) |
| `tests/test_cls_endpoints.py` | 修改 | 改所有 URL 路径 (`/cls/*` → `/news/*`) |

**未变更**（明确不做）：
- `CLAUDE.md` — 不增加历史窗口备注（用户已确认不加）
- `manager.py` / `base.py` — capability flag / 方法名不变
- `cache.py` — cache key 仍按 `subject` namespace
- `server.py` — `app.include_router(cls_router, prefix="/api/v1")` 不变
- `_get_subject_article` 流程不变

---

## 5. 测试策略（TDD-first）

### 5.1 `tests/test_cls_fetcher.py`

| 测试 | 验证 |
|---|---|
| `test_dedup_images` (改) | 只返 `content` 中跳过第一张后的图; `images[]` 字段丢弃 |
| `test_dedup_images_no_content_images` (新) | content 0 张图 → `[]`; 仍丢弃 images[] |
| `test_dedup_images_only_one_content_image_skipped` (新) | content 1 张图（是 header）→ `[]` |
| `test_dedup_images_empty_content` (新) | content 缺失/空 → `[]` |

### 5.2 `tests/test_cls_endpoints.py`

8 个测试全部改 URL：`/api/v1/cls/morning-briefing` → `/api/v1/news/morning-briefing`，`/api/v1/cls/market-review` → `/api/v1/news/market-recap`。

### 5.3 不动的测试

- `tests/test_capability_method_map.py` — 自动覆盖 2 个 capability + CAPABILITY_LABELS（已 PASS）
- `tests/test_explorer_manifest_endpoint.py` — manifest builder 反映 tags 改动（已 PASS）
- `tests/test_cls_live.py` — live_network 标记，dev loop 跳过；CI 全跑时验证 `body_text` 仍正确

---

## 6. 风险与缓解

| 风险 | 缓解 |
|---|---|
| 旧 client 调 `/api/v1/cls/*` → 404 | **接受** — server 内部 API 命名空间, CLAUDE.md 约定 explorer 是 source of truth |
| 早报偶尔只有 1 张图（且是 header）→ 过滤后 `images: []` | 用户确认"无实际意义" → 接受空数组 |
| 未来 CLS 改 HTML 结构（无 `<p>` 包裹图） | `_dedup_images` 已用 `soup.find_all("img")` 不依赖 `<p>`; 索引逻辑与包裹无关 |
| 用户对 `images[]` 字段语义理解变化 | 用户已明确: "需要的是正文里的images" — 响应中 `images` 字段 = 正文中除第一张外的所有图 |

---

## 7. 不做

- ❌ 不实现 article_id 反查 / 旧数据访问扩展
- ❌ 不改 response schema (字段名 / 类型 / 默认值)
- ❌ 不动 fetcher 优先级 / capability flag 名 / manager 方法名
- ❌ 不动 `body_text` 抽取逻辑
- ❌ 不加 `is_header_image` 标记字段（直接过滤最简单）
- ❌ 不在 CLAUDE.md 增加历史窗口备注

---

## 8. 验证

```bash
# 单元 + 集成（必跑）
.venv/Scripts/python.exe -m pytest tests/test_cls_fetcher.py tests/test_cls_endpoints.py -v
# 32 + 8 = 40 tests passed

# 副作用检查
.venv/Scripts/python.exe -m pytest tests/test_capability_method_map.py tests/test_explorer_manifest_endpoint.py
# 64 tests passed (capability map + explorer manifest)

# CI 完整套（含 live_network）
.venv/Scripts/python.exe -m pytest -m ""
```

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
