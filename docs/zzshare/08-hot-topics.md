# zzshare · 同花顺热度

> 涵盖 `ths_hot_top` / `stock_ths_hot` 两个接口

## 1. `ths_hot_top` — 同花顺热搜榜 Top N

### 接口

- **HTTP**: `GET /open/sentiment/media/ths2/top`
- **SDK**: `DataApi.ths_hot_top(...)`

### 参数

| 参数 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `date1` | `str` | ✅ | `YYYYMMDD` |
| `top_n` | `int` | 否 | 默认 100 |

### 返回字段（实测）

`list[dict]`，每只股票一条记录：

| 字段 | 类型 | 说明 |
|---|---|---|
| `rank` | int | 排名（1=榜首） |
| `rank_diff` | int | 排名变化（正数=上升，负数=下降） |
| `symbol_code` | str | **6 位裸码**（如 `002342`） |
| `symbol_name` | str | 中文名 |
| `last_price` | float | 最新价 |
| `last_pct` | float | 最新涨跌幅（%） |
| `circulation_value` | float | 流通市值（亿元） |
| `collect_date` | str | `YYYY-MM-DD` |
| `update_time` | str | `YYYY-MM-DD HH:MM:SS` |
| `id` | int | 内部 ID |

### 行为细节

- `symbol_code` 不带市场后缀，需要按 `client.py` 的 `_to_tushare_ts_code` 风格补 `.SH` / `.SZ`。

### 示例

```python
top = api.ths_hot_top(date1='20260520', top_n=5)
# top[0] → {'rank': 1, 'rank_diff': 1, 'symbol_code': '002342', 'symbol_name': '...', ...}
```

---

## 2. `stock_ths_hot` — 个股同花顺热度趋势

### 接口

- **HTTP**: `GET /v2/api/sentiment/media/ths/symbol/{code}`
- **SDK**: `DataApi.stock_ths_hot(...)`

### 参数

| 参数 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `code` | `str` | ✅ | 6 位裸码 |
| `date1` | `str` | ✅ | `YYYYMMDD` |

### 返回

`dict` / `list[dict]`——含个股当日及近期热度时间序列。

### 示例

```python
trend = api.stock_ths_hot(code='002342', date1='20260520')
```