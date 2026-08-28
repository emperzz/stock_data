# 公告 — 端点明细

> 本文件是 `market-data-obtain` 主文件 [§7 公告](../market-data-obtain.md) 的端点明细。  
> 主文件只列端点路径 + capability + 一句话用途；**字段、单位、调用约束、示例见本文**。

---

## `GET /api/v1/stocks/{stock_code}/announcements`

### 功能

获取个股公司公告列表。覆盖年报、季报、重大事项等全部公开披露文件。返回分页结果，每页条数由 `?page_size` 控制。

- 主要 fetcher: EastMoney → Cninfo → Ths（Manager 自动 failover）
- `type` 字段由上游解析，常见值包括"年报"、"季报"、"重大事项"、"权益分派"等

### 入参

| 参数名 | 类型 | 必填 | 默认值 | 约束 |
|---|---|---|---|---|
| `stock_code`（路径） | string | ✅ | — | 6 位 A 股代码（如 `600519`） |
| `page`（query） | int | ❌ | `1` | 页码，从 1 开始 |
| `page_size`（query） | int | ❌ | `20` | 单页条数 |

### 返回参数

顶层结构含 `announcements[]`（完整 Pydantic schema 见 `stock_data/api/schemas.py`）。`announcements[]` 每条：

| 字段 | 类型 | 单位 | 说明 |
|---|---|---|---|
| `title` | string | — | 公告标题 |
| `type` | string | — | 公告类型（如"年报"、"季报"、"重大事项"） |
| `date` | string | — | 公告日期 `YYYY-MM-DD` |
| `url` | string | — | 详情页 URL（cninfo / eastmoney 域名） |

### 示例

```bash
# 默认第一页
curl 'http://localhost:8888/api/v1/stocks/600519/announcements'

# 自定义分页
curl 'http://localhost:8888/api/v1/stocks/600519/announcements?page=2&page_size=50'
```
