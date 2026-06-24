# zzshare · 题材库 / AI 报告 / 异动监控

> 涵盖 `topic_table_*` / `ai_report_*` / `movement_alerts` / `zdjk_get` / `stock_moneyflow` / `market_mf` 共 8 个接口

## 一、题材库（`topic_table_*`）

zzshare 提供了一套**自有的题材库**——区别于同花顺 17 类题材，是「结构化的题材表格 + 个股归类 + 合成指数 K 线」三件套。

### 1. `topic_table_list` — 题材库表格列表

#### 接口

- **HTTP**: `GET /v3/topic/tables`
- **SDK**: `DataApi.topic_table_list(...)`

#### 参数

| 参数 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `page` | `int` | 否 | 默认 1 |
| `limit` | `int` | 否 | 默认 20 |
| `brief` | `int` | 否 | `1`=返回概要（默认），`0`=返回全部字段 |

#### 返回

`list[dict]`，每个题材一条记录（含 `tid` / 题材名 / 描述 / 关联个股数 等）。

---

### 2. `topic_table_detail` — 题材库表格详情

#### 接口

- **HTTP**: `GET /v3/topic/table/{tid}`
- **SDK**: `DataApi.topic_table_detail(...)`

#### 参数

| 参数 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `tid` | `int` | ✅ | 题材库表格 ID |

#### 返回

`dict`——题材的元数据 + 描述 + 关联板块等。

---

### 3. `topic_table_stocks` — 题材下个股列表

#### 接口

- **HTTP**: `GET /v3/topic/table/{tid}/stocks`
- **SDK**: `DataApi.topic_table_stocks(...)`

#### 参数

| 参数 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `tid` | `int` | ✅ | 题材库表格 ID |

#### 返回

`list[dict]`——题材下归类的所有个股。

---

### 4. `topic_kline` — 题材合成指数 K 线

> 与 `01-kline.md` 中的 `topic_kline` 同接口（`/v3/topic/table/{tid}/kline`），此处仅列出，不重复参数。

---

## 二、AI 每日报告（`ai_report_*`）

> AI 生成的收盘 / 盘前报告（**非第三方券商研报**）。

### 1. `ai_report_list` — AI 报告列表

#### 接口

- **HTTP**: `GET /v3/ai-report/list`
- **SDK**: `DataApi.ai_report_list(...)`

#### 参数

| 参数 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `type` | `str` | 否 | 报告类型（SDK 未公开枚举） |
| `page` | `int` | 否 | 默认 1 |
| `page_size` | `int` | 否 | 默认 20 |

#### 返回

`list[dict]`——报告标题、发布时间、摘要等。

---

### 2. `ai_report_detail` — AI 报告详情

#### 接口

- **HTTP**: `GET /v3/ai-report/detail/{post_id}`
- **SDK**: `DataApi.ai_report_detail(...)`

#### 参数

| 参数 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `post_id` | `int` | ✅ | 报告 ID |

#### 返回

`dict`——报告全文（Markdown / HTML）。

---

## 三、异动 / 监控（`movement_alerts` / `zdjk_get`）

### 1. `movement_alerts` — 异动数据

#### 接口

- **HTTP**: `GET /market/movement/alerts`
- **SDK**: `DataApi.movement_alerts(...)`

#### 参数

| 参数 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `date1` | `str` | ✅ | `YYYYMMDD` |
| `type` | `int` | 否 | 异动类型，默认 0 |
| `limit` | `int` | 否 | 默认 200 |
| `is_real` | `int` | 否 | 默认 1 |

#### 返回

沪深涨幅触发监管以及距离触发的空间。

---

### 2. `zdjk_get` — 监管监控

#### 接口

- **HTTP**: `GET /open/zdjk/get`
- **SDK**: `DataApi.zdjk_get(...)`

#### 参数

| 参数 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `date1` | `str` | ✅ | `YYYYMMDD` |
| `date2` | `str` | 否 | `YYYYMMDD` |

#### 返回

`list[dict]`——已经触发监管的股票列表。

---

## 四、资金流向（`stock_moneyflow` / `market_mf`——SDK 已注释）

> 以下两个接口在 `client.py` 的 `SHORTCUTS` 表中已被**注释掉**（不再作为快捷方法注册），但 `client.pyi` 中保留了类型提示；可通过 `api.query(...)` 绕过注册直接调用。

### 1. `stock_moneyflow` — 个股实时资金流向

#### 接口

- **HTTP**: `GET /open/stock/{stock_id}/moneyflow`
- **SDK 类型提示**: `DataApi.stock_moneyflow(...)`（未注册）
- **实际调用**: `api.query("open/stock/{stock_id}/moneyflow", params=...)`

#### 参数

| 参数 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `stock_id` | `str` | ✅ | 6 位裸码（路径参数） |
| `m_type` | `str` | 否 | 资金类型 |

#### 返回

`dict`——个股实时主力资金流向（超大单 / 大单 等）。

---

### 2. `market_mf` — 全市场资金流分布概览

#### 接口

- **HTTP**: `GET /open/market/mf`
- **SDK 类型提示**: `DataApi.market_mf(...)`（未注册）
- **实际调用**: `api.query("open/market/mf", params=...)`

#### 参数

| 参数 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `stock` | `str` | ✅ | 股票 / 板块代码 |
| `date` | `str` | ✅ | `YYYYMMDD` |
| `wm` | `int` | 否 | 默认 0 |
| `default_v` | `int` | 否 | 默认 0 |

#### 返回

`dict`——全市场资金流分布概览。