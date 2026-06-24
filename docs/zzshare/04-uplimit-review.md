# zzshare · 涨停复盘

> 涵盖 `uplimit_hot` / `uplimit_stocks` / `stock_uplimit_reason` / `review_uplimit_reason` / `review_uplimit_hot_step` / `review_uplimit_reason_open` / `stock_uplimit_reason_history` / `uplimit_market_value` 共 8 个接口

## 1. `uplimit_hot` — 涨停热门板块及连板梯队

### 接口

- **HTTP**: `GET /open/review/uplimit/hot`
- **SDK**: `DataApi.uplimit_hot(...)`

### 参数

| 参数 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `date1` | `str` | ✅ | 涨停日 `YYYYMMDD` |
| `board` | `str` | 否 | 板块过滤（SDK 未公开枚举） |

### 返回

```python
{
    "ban_info": {
        "1": {"count": 46},   # 一板 46 只
        "2": {"count": 5},    # 二板 5 只
        ...
        "8": {"count": 1},
    },
    "max_count": 8,
    "plate": [
        ["芯片", "801001", 21973],
        ["机器人概念", "801159", 6292],
        ...
    ]
}
```

- `plate[i][0]`：板块名
- `plate[i][1]`：板块代码（同花顺风格，如 `801001`）
- `plate[i][2]`：板块热度分

### 示例

```python
hot = api.uplimit_hot(date1='20260520')
print(hot['ban_info'])   # {1: count=46, 2: count=5, ...}
print(hot['plate'][:3])  # 排名前三的板块
```

---

## 2. `uplimit_stocks` — 指定日期所有涨停股票

### 接口

- **HTTP**: `GET /open/review/uplimit/stocks/{date1}`
- **SDK**: `DataApi.uplimit_stocks(...)`

### 参数

| 参数 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `date1` | `str` | ✅ | 涨停日 `YYYYMMDD`（路径参数） |

### 返回

`list[dict]`，每只涨停股一条记录。**字段 schema 由后端决定**，README 未公开——实测匿名调用返回 `[]`，**需要 Token**。

### 示例

```python
stocks = api.uplimit_stocks(date1='20260520')
```

---

## 3. `stock_uplimit_reason` — 个股涨停原因

### 接口

- **HTTP**: `GET /v3/open/stock/uplimit/reason/{stock_code}`
- **SDK**: `DataApi.stock_uplimit_reason(...)`

### 参数

| 参数 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `stock_code` | `str` | ✅ | 6 位裸码（路径参数） |
| `date` | `str` | 否 | 涨停日 `YYYYMMDD` |

### 返回

`dict` / `list[dict]`（含涨停原因文本）。

### 示例

```python
reason = api.stock_uplimit_reason(stock_code='000001', date='20260520')
```

---

## 4. `stock_uplimit_reason_history` — 个股涨停历史

### 接口

- **HTTP**: `GET /v3/open/stock/uplimit/reason/history/{stock_code}`
- **SDK**: `DataApi.stock_uplimit_reason_history(...)`

### 参数

| 参数 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `stock_code` | `str` | ✅ | 6 位裸码 |
| `page` | `int` | 否 | 默认 1 |
| `pageSize` | `int` | 否 | 默认 10 |

### 返回

`list[dict]`，每条记录对应一次历史涨停（含日期 / 原因 / 连板数 等字段）。

### 示例

```python
history = api.stock_uplimit_reason_history(stock_code='000001', page=1, pageSize=10)
```

---

## 5. `review_uplimit_reason` — 全市场涨停原因汇总

### 接口

- **HTTP**: `GET /v3/api/review/uplimit/reason`
- **SDK**: `DataApi.review_uplimit_reason(...)`

### 参数

| 参数 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `date1` | `str` | 否 | `YYYYMMDD` |
| `group` | `int` | 否 | 分组（默认 1） |
| `page` | `int` | 否 | 分页 |
| `page_size` | `int` | 否 | 每页条数 |

### 返回

`list[dict]`，每条含个股代码 / 涨停时间 / 涨停原因。

---

## 6. `review_uplimit_hot_step` — 指定板块涨停梯队

### 接口

- **HTTP**: `GET /v3/open/review/uplimit/hot`
- **SDK**: `DataApi.review_uplimit_hot_step(...)`

### 参数

| 参数 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `date1` | `str` | 否 | `YYYYMMDD` |
| `board` | `str` | 否 | 板块代码 |
| `limit` | `int` | 否 | 返回条数 |

---

## 7. `review_uplimit_reason_open` — 全市场涨停原因（简化版）

### 接口

- **HTTP**: `GET /v3/open/review/uplimit/reason`
- **SDK**: `DataApi.review_uplimit_reason_open(...)`

### 参数

| 参数 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `date1` | `str` | 否 | `YYYYMMDD` |

---

## 8. `uplimit_market_value` — 涨停市值统计

### 接口

- **HTTP**: `GET /v2/api/uplimit/market/value`
- **SDK**: `DataApi.uplimit_market_value(...)`

### 参数

| 参数 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `date1` | `str` | ✅ | 起始日期 `YYYYMMDD` |
| `date2` | `str` | 否 | 截止日期 `YYYYMMDD` |

### 返回

基于市值的涨停板个股分布统计（按市值区间统计涨停家数 / 资金流入 等）。

### 示例

```python
data = api.uplimit_market_value(date1='20260501', date2='20260520')
```