# 公告 — 端点明细

> 主文件已列端点路径与 capability；本文给出字段、单位、入参约束与示例。

---

## `GET /api/v1/stocks/{stock_code}/announcements`

### 功能

获取个股公司公告列表。覆盖年报、季报、重大事项等全部公开披露文件。`type` 字段由上游解析，常见值包括"年报"、"季报"、"重大事项"、"权益分派"等。

### 入参

| 参数名 | 类型 | 必填 | 默认值 | 约束 |
|---|---|---|---|---|
| `stock_code`（路径） | string | ✅ | — | 6 位 A 股代码（如 `600519`） |
| `page_size`（query） | int | ❌ | `30` | 返回条数（`1 ≤ page_size ≤ 100`） |

### 返回参数

顶层 `{code, name, total, announcements[], source}`。`announcements[]` 每条：

| 字段 | 类型 | 单位 | 说明 |
|---|---|---|---|
| `title` | string | — | 公告标题 |
| `type` | string | — | 公告类型（如"年报"、"季报"、"重大事项"） |
| `date` | string | — | 公告日期 `YYYY-MM-DD` |
| `url` | string | — | 详情页 URL（cninfo / eastmoney / 10jqka 等域名） |
| `raw_url` | string | — | **巨潮原文 PDF 直链**（仅 ThsFetcher 携带；其他 fetcher 此字段为空字符串） |

### 示例

```bash
# 默认 30 条
curl 'http://localhost:8888/api/v1/stocks/600519/announcements'

# 自定义条数
curl 'http://localhost:8888/api/v1/stocks/600519/announcements?page_size=50'
```
