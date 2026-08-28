# 基础数据 — 端点明细

> 主文件已列端点路径与 capability；本文给出字段、单位、入参约束与示例。

---

## `GET /api/v1/stocks/{stock_code}/dividend`

### 功能

获取个股分红送转记录。返回该股历史上所有分红 / 送股 / 转增记录，含除权除息日、每股派息、每 10 股送 / 转股数、方案进度。

### 入参

| 参数名 | 类型 | 必填 | 默认值 | 约束 |
|---|---|---|---|---|
| `stock_code`（路径） | string | ✅ | — | 6 位 A 股代码（如 `600519`） |
| `page_size`（query） | int | ❌ | `20` | 返回条数（`1 ≤ page_size ≤ 100`） |

### 返回参数

顶层 `{code, name, records[], source}`（完整 Pydantic schema 见 `stock_data/api/schemas.py`）。`records[]` 每条：

| 字段 | 类型 | 单位 | 说明 |
|---|---|---|---|
| `date` | string | — | 除权除息日 `YYYY-MM-DD` |
| `bonus_rmb` | number | 元 | **每股派息（税前）** |
| `transfer_ratio` | number | 股 | 每 10 股转增股数（如 `5` 表示 10 转 5） |
| `bonus_ratio` | number | 股 | 每 10 股送股数 |
| `plan` | string | — | 进度描述（如 `"实施完成"`、`"股东大会通过"`） |

### 示例

```bash
curl 'http://localhost:8888/api/v1/stocks/600519/dividend'
```
