# zzshare · 龙虎榜

> 涵盖 `lhb_list` / `lhb_detail` / `lhb_stock_history` / `lhb_trader_history` 四个接口

## 1. `lhb_list` — 龙虎榜每日上榜概览

### 接口

- **HTTP**: `GET /market/lhb/list`
- **SDK**: `DataApi.lhb_list(...)`

### 参数

| 参数 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `date1` | `str` | ✅ | 上榜日 `YYYYMMDD` |

### 返回字段（实测）

`list[dict]`，每只上榜股一条记录：

| 字段 | 类型 | 说明 |
|---|---|---|
| `stock_code` | str | **6 位裸码**（不带 `.SH` / `.SZ`） |
| `stock_name` | str | 中文名 |
| `concepts` | str | 涉及的概念板块，逗号分隔（`801723:中药,801369:...`） |
| `amplitude` | float | 振幅（%） |
| `quote_change` | float | 涨跌幅（%） |
| `turnover` | float | 成交额（元） |
| `turnover_ratio` | float | 换手率（%） |
| `capitalization` | float | 总股本 |
| `circ_price` | float | 流通市值 |
| `buy_in` | float | 龙虎榜净买入额 |
| `join_num` | int | 上榜席位数量 |
| `up_reason` | str | 上榜原因文本 |
| `t_type` | int | 上榜类型（0=日涨幅/跌幅异常 等） |
| `d3` | float | 3 日涨跌幅 |

### 行为细节

- `stock_code` 不带市场后缀，需要根据代码前缀（`60/68 → SH`, `0/3 → SZ`, `8/4/2/9 → BJ`）自动补。
- `concepts` 是字符串（`"801723:中药,..."`），需要 split + map。

### 示例

```python
lhb = api.lhb_list(date1='20260520')
print(lhb[0]['stock_code'], lhb[0]['stock_name'], lhb[0]['buy_in'])
```

---

## 2. `lhb_detail` — 个股龙虎榜席位详情

### 接口

- **HTTP**: `GET /market/lhb/detail`
- **SDK**: `DataApi.lhb_detail(...)`

### 参数

| 参数 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `date1` | `str` | ✅ | `YYYYMMDD` |
| `stock_code` | `str` | ✅ | 6 位裸码 |

### 返回

`list[dict]` / `dict`——每条记录对应一个席位，含营业部名称 / 买入额 / 卖出额 / 净额。

### 示例

```python
detail = api.lhb_detail(date1='20260520', stock_code='000001')
```

---

## 3. `lhb_stock_history` — 个股龙虎榜历史

### 接口

- **HTTP**: `GET /market/lhb/stock/history`
- **SDK**: `DataApi.lhb_stock_history(...)`

### 参数

| 参数 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `stock_code` | `str` | 否 | 6 位裸码 |
| `trader_name` | `str` | 否 | 营业部名称 |

### 返回

`dict` / `list[dict]`——给定股票返回历史所有上榜记录（日期 + 席位 + 净买入），或给定营业部返回该营业部的所有上榜记录（不需要 `stock_code`）。

### 示例

```python
# 按个股
history = api.lhb_stock_history(stock_code='000001')
# 按营业部
history = api.lhb_stock_history(trader_name='东方证券绍兴解放南路营业部')
```

---

## 4. `lhb_trader_history` — 席位交易历史

### 接口

- **HTTP**: `GET /market/lhb/trader/history`
- **SDK**: `DataApi.lhb_trader_history(...)`

### 参数

| 参数 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `trader_name` | `str` | 否 | 营业部名称 |
| `trader_id` | `str` | 否 | 营业部 ID |
| `stock_code` | `str` | 否 | 6 位裸码 |
| `page` | `int` | 否 | 默认 1 |
| `per_page` | `int` | 否 | 默认 20 |

### 返回

`dict` / `list[dict]`——知名游资 / 席位的跨股票交易历史。

### 示例

```python
history = api.lhb_trader_history(trader_name='东方证券绍兴解放南路营业部', page=1, per_page=20)
```