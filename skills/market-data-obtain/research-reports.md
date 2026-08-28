# 研报 — 端点明细

> 主文件已列端点路径与 capability；本文给出字段、单位、入参约束与示例。

---

## `GET /api/v1/stocks/{stock_code}/reports`

### 功能

获取个股券商研报列表，含机构名、评级、当年/次年/后年 EPS 预测。`info_code` 是研报的唯一 ID，**用于下一步 `/reports/{report_id}/pdf` 下载 PDF**。

### 入参

| 参数名 | 类型 | 必填 | 默认值 | 约束 |
|---|---|---|---|---|
| `stock_code`（路径） | string | ✅ | — | 6 位 A 股代码（如 `600519`） |
| `max_pages`（query） | int | ❌ | `3` | 最多抓取的页数（`1 ≤ max_pages ≤ 10`） |

### 返回参数

顶层 `{code, name, total, reports[], source}`。`reports[]` 每条：

| 字段 | 类型 | 单位 | 说明 |
|---|---|---|---|
| `title` | string | — | 研报标题 |
| `publish_date` | string | — | 发布日期 `YYYY-MM-DD` |
| `org` | string | — | 机构名（中信证券、华泰证券等） |
| `info_code` | string | — | 报告 ID，**下载 PDF 时作为 `report_id` 路径参数** |
| `rating` | string | — | 评级（`"买入"` / `"增持"` / `"中性"` / `"减持"` / `"卖出"`） |
| `predict_eps_this` | number | 元 | 当年 EPS 预测 |
| `predict_eps_next` | number | 元 | 次年 EPS 预测 |
| `predict_eps_next2` | number | 元 | 后年 EPS 预测 |

### 示例

```bash
curl 'http://localhost:8888/api/v1/stocks/600519/reports'
```

---

## `GET /api/v1/stocks/{stock_code}/reports/{report_id}/pdf`

### 功能

下载指定研报的 PDF 文件。**返回的是本地路径**（服务器把上游 PDF 缓存到磁盘），不是直接的文件流——agent 需要再次 `Read` 该路径才能拿到 PDF 字节。

上游 URL 在响应 `url` 字段，便于溯源。

### 入参

| 参数名 | 类型 | 必填 | 默认值 | 约束 |
|---|---|---|---|---|
| `stock_code`（路径） | string | ✅ | — | 6 位 A 股代码 |
| `report_id`（路径） | string | ✅ | — | 来自 `/reports` 响应的 `info_code` 字段 |

### 返回参数

| 字段 | 类型 | 单位 | 说明 |
|---|---|---|---|
| `report_id` | string | — | 入参回显 |
| `download_path` | string | — | 本地缓存路径（agent `Read` 此路径拿 PDF 字节） |
| `url` | string | — | 原始上游 URL（便于溯源） |

### 示例

```bash
# 先取 report_id
curl 'http://localhost:8888/api/v1/stocks/600519/reports' | jq '.[0].info_code'
# 假设返回 "abc123"

# 下载 PDF
curl 'http://localhost:8888/api/v1/stocks/600519/reports/abc123/pdf'
```
