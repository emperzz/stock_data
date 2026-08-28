# 新闻 / 消息 — 端点明细

> 本文件是 `market-data-obtain` 主文件 [§10 新闻 / 消息](../market-data-obtain.md) 的端点明细。  
> 主文件只列端点路径 + capability + 一句话用途；**字段、单位、调用约束、示例见本文**。  
> **本节是 fallback 策略的高频触发区**——"为什么涨/跌"等外部事件型原因主要走本节端点。失败 / 28 天窗口外时按主文件 §3 Fallback 策略切换到 agent 自带的网络搜索 / 抓取工具。

---

## `GET /api/v1/news/search`

### 功能

按关键词 / 股票代码 / 主题搜索财经新闻。返回标题、URL、发布日期、来源子域、摘要。

- 主要 fetcher: EastMoney → Ths → Baidu（Manager 自动 failover）
- `source_domain` 限定白名单：`finance.eastmoney.com` / `www.cls.cn` / `news.10jqka.com.cn`（canonical 子域）
- `summary` 部分上游不提供，可能为空字符串

### 入参

| 参数名 | 类型 | 必填 | 默认值 | 约束 |
|---|---|---|---|---|
| `q`（query） | string | ✅ | — | 搜索关键词（股票代码 / 主题词） |
| `limit`（query） | int | ❌ | `20` | 返回条数 |
| `offset`（query） | int | ❌ | `0` | 跳过条数（分页） |

### 返回参数

顶层结构含 `data[]`（完整 Pydantic schema 见 `stock_data/api/schemas.py`）。`data[]` 每条：

| 字段 | 类型 | 单位 | 说明 |
|---|---|---|---|
| `title` | string | — | 新闻标题 |
| `url` | string | — | 详情页 URL |
| `publish_date` | string | — | 发布日期 `YYYY-MM-DD` |
| `source_domain` | string | — | 来源子域（白名单内） |
| `summary` | string | — | 摘要；可能为空字符串 |

### 示例

```bash
# 搜股票相关
curl 'http://localhost:8888/api/v1/news/search?q=600519&limit=10'

# 搜主题
curl 'http://localhost:8888/api/v1/news/search?q=人形机器人&limit=20'
```

---

## `GET /api/v1/news/flash`

### 功能

全球财经快讯流（7×24 实时）。常用于"为什么今天涨/跌"分析的第 1 步（看当日大事）。

- 主要 fetcher: EastMoney → Ths
- **`code` 字段是文章 ID，不是股票代码**（⚠️ 易踩坑——不能误用 `code` 字段去查股票行情）

### 入参

| 参数名 | 类型 | 必填 | 默认值 | 约束 |
|---|---|---|---|---|
| `limit`（query） | int | ❌ | `50` | 返回条数 |
| `start_time`（query） | string | ❌ | — | 起始时间 `YYYY-MM-DD HH:MM:SS` |
| `end_time`（query） | string | ❌ | — | 结束时间 `YYYY-MM-DD HH:MM:SS` |

### 返回参数

顶层结构含 `data[]`。`data[]` 每条：

| 字段 | 类型 | 单位 | 说明 |
|---|---|---|---|
| `title` | string | — | 快讯标题 |
| `publish_time` | string | — | 发布时间 `YYYY-MM-DD HH:MM:SS` |
| `url` | string | — | 详情页 URL（无则为空） |
| `code` | string | — | **文章 ID**（不是股票代码） |
| `source_domain` | string | — | 来源子域 |

### 示例

```bash
# 最近 20 条
curl 'http://localhost:8888/api/v1/news/flash?limit=20'

# 限定时间窗
curl 'http://localhost:8888/api/v1/news/flash?start_time=2026-05-20%2009:00:00&end_time=2026-05-20%2015:00:00'
```

---

## `GET /api/v1/news/content`

### 功能

给定 URL 抓取新闻详情页正文。本地解析器，**入口有 SSRF 防护**（`127.0.0.1` / `10.0.0.0/8` 等内网 URL 会被 400 拒绝）。

- 纯本地解析，不消耗 fetcher 配额
- `extractor` 字段标识使用的解析器（`"default"` 等）

### 入参

| 参数名 | 类型 | 必填 | 默认值 | 约束 |
|---|---|---|---|---|
| `url`（query） | string | ✅ | — | 详情页完整 URL；**禁止内网地址**（SSRF 防护） |

### 返回参数

| 字段 | 类型 | 单位 | 说明 |
|---|---|---|---|
| `url` | string | — | 入参 URL（echo） |
| `title` | string | — | 文章标题 |
| `body` | string | — | 提取的正文纯文本（保留段落换行） |
| `publish_date` | string | — | 发布日期 `YYYY-MM-DD`（若解析到） |
| `author` | string | — | 作者（若解析到） |
| `source_domain` | string | — | 来源子域 |
| `extractor` | string | — | 解析器名（`"default"` 等） |
| `byte_size` | number | 字节 | body 长度 |
| `content_status` | string | — | `ok` / `failed` |
| `reason` | string | — | 失败原因（仅 `content_status="failed"` 时非空） |
| `canonical_url` | string | — | URL 跳转后的最终地址（抓取诊断） |
| `http_status` | number | — | HTTP 状态码（抓取诊断） |

### 示例

```bash
curl 'http://localhost:8888/api/v1/news/content?url=https://finance.eastmoney.com/news/1234.html'
```

---

## `GET /api/v1/stocks/{stock_code}/news`

### 功能

个股相关新闻列表。结构比 `/news/search` 简（无 `summary` 字段）。

- 主要 fetcher: EastMoney → Ths
- 适用于"看某只股票最近有什么消息"场景

### 入参

| 参数名 | 类型 | 必填 | 默认值 | 约束 |
|---|---|---|---|---|
| `stock_code`（路径） | string | ✅ | — | 6 位 A 股代码 |
| `limit`（query） | int | ❌ | `20` | 返回条数 |

### 返回参数

顶层结构含 `data[]`。`data[]` 每条：

| 字段 | 类型 | 单位 | 说明 |
|---|---|---|---|
| `title` | string | — | 新闻标题 |
| `url` | string | — | 详情页 URL |
| `publish_time` | string | — | 发布时间 `YYYY-MM-DD HH:MM:SS` |
| `source_domain` | string | — | 来源子域 |

### 示例

```bash
curl 'http://localhost:8888/api/v1/stocks/600519/news?limit=20'
```

---

## `GET /api/v1/news/morning-briefing`

### 功能

财联社早报。**仅最近 28 天窗口**——超出窗口 → 400，窗口内但当日未发 → 404。

- 主要 fetcher: ClsFetcher（财联社）
- `body_text` 字段是 BS4 提取的完整正文（`get_text("\n", strip=True)`，3+ 空行折叠为 2 空行）——这是 agent 拿全文做总结的主字段
- `subject_id` 固定 `1151`（CLS 上游枚举；如 CLS 改枚举，service 会通过 `subject_id mismatch` 告警）

### 入参

| 参数名 | 类型 | 必填 | 默认值 | 约束 |
|---|---|---|---|---|
| `date`（query） | string | ❌ | 最新一日 | `YYYY-MM-DD`；**必须 ≤ 今日 - 28 天窗口**（超出 → 400）；格式错也 → 400 |

### 返回参数

| 字段 | 类型 | 单位 | 说明 |
|---|---|---|---|
| `subject` | string | — | 固定 `"morning_briefing"` |
| `subject_id` | string | — | 固定 `"1151"` |
| `date` | string | — | 入参回显 `YYYY-MM-DD` |
| `article` | object | — | 文章对象（见下） |
| `article.article_id` | string | — | 文章 ID |
| `article.title` | string | — | 标题 |
| `article.brief` | string | — | 简介 |
| `article.author` | string | — | 作者 |
| `article.date` | string | — | 发布日期 `YYYY-MM-DD` |
| `article.ctime` | number | epoch 秒 | 发布时间 |
| `article.read_num` | number | — | 阅读数 |
| `article.comments_num` | number | — | 评论数 |
| `article.share_num` | number | — | 分享数 |
| `article.images[]` | array | — | 图片 URL 列表 |
| `article.body_text` | string | — | **完整正文（纯文本）**——agent 总结的主字段 |
| `source` | string | — | 数据来源 fetcher 名（固定 `"cls"`） |

### 示例

```bash
# 默认最新一日
curl 'http://localhost:8888/api/v1/news/morning-briefing'

# 指定日期
curl 'http://localhost:8888/api/v1/news/morning-briefing?date=2026-05-20'
```

---

## `GET /api/v1/news/market-recap`

### 功能

财联社焦点复盘。**与早报相同的 28 天窗口限制**。

- 主要 fetcher: ClsFetcher
- `subject_id` 固定 `1135`（CLS 上游枚举；如 CLS 改枚举，service 会通过 `subject_id mismatch` 告警）
- 字段结构与 `/news/morning-briefing` 完全一致，**仅 `subject` 字段值不同**（`"market_recap"` vs `"morning_briefing"`）

### 入参

| 参数名 | 类型 | 必填 | 默认值 | 约束 |
|---|---|---|---|---|
| `date`（query） | string | ❌ | 最新一日 | `YYYY-MM-DD`；**必须 ≤ 今日 - 28 天窗口**（超出 → 400） |

### 返回参数

与 `/news/morning-briefing` 完全相同（字段集、类型、单位），仅：

- `subject` 固定 `"market_recap"`
- `subject_id` 固定 `"1135"`

### 示例

```bash
curl 'http://localhost:8888/api/v1/news/market-recap?date=2026-05-20'
```
