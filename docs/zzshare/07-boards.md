# zzshare · 板块数据

> 涵盖 `plates_list` / `plates_rank` / `plates_stocks` / `plates_trend` / `plates_rank_days` / `plates_rank_days_new` / `market_plate_stocks` / `market_plate_popular_reason` 共 8 个接口

## `plate_type` 取值约定

zzshare 的板块体系是**统一维度**，通过 `plate_type` 区分：

| `plate_type` | 含义 | 示例代码 |
|---|---|---|
| `14` | 行业板块（同花顺） | `881121`（半导体） |
| `15` | 概念板块（同花顺） | |
| `17` | 题材板块（同花顺） | `801001`（芯片）、`801660`（通信） |

---

## 1. `plates_list` — 板块列表

### 接口

- **HTTP**: `GET /market/plates/{plate_type}`
- **SDK**: `DataApi.plates_list(...)`

### 参数

| 参数 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `plate_type` | `int` | ✅ | `14` / `15` / `17` |

### 返回

`list[dict]`，每个板块一条记录（含 `plate_code` / `plate_name` / 热度 / 涨跌幅 等字段）。

> README 建议改用 `plates_rank`——`plates_list` 返回的是**全量历史板块列表**（包含已下线的板块），实战中应当用 `plates_rank(date1=today)` 替代。

### 示例

```python
plates = api.plates_list(plate_type=17)
```

---

## 2. `plates_rank` — 板块热度排名

### 接口

- **HTTP**: `GET /v3/market/plates/{plate_type}/rank`
- **SDK**: `DataApi.plates_rank(...)`

### 参数

| 参数 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `plate_type` | `int` | ✅ | `14` / `15` / `17` |
| `date1` | `str` | ✅ | `YYYY-MM-DD` 或 `YYYYMMDD`（README 与 SDK 实测均支持） |
| `limit` | `int` | 否 | 默认 10 |

### 返回字段（实测）

| 字段 | 类型 | 说明 |
|---|---|---|
| `plate_code` | str | 同花顺板块代码 |
| `plate_name` | str | 板块名 |
| `plate_type` | int | 14/15/17 |
| `rate` | float | 涨跌幅（%） |
| `speed` | float | 涨速 |
| `score` | int | 热度分 |
| `money_leader` | float | 领涨股资金净额 |
| `money_leader_buy` / `money_leader_sell` | float | 领涨股买入 / 卖出净额 |
| `trade_money` | float | 板块成交额 |
| `volume_ration` | float | 量比 |
| `market_cap_cir` | float | 流通市值 |
| `date1` | str | `YYYY-MM-DD` |
| `time` | str | 数据时间戳 `YYYY-MM-DD HH:MM:SS` |

### 示例

```python
rank = api.plates_rank(plate_type=14, date1='20260520', limit=20)
```

---

## 3. `plates_stocks` — 板块成分股

### 接口

- **HTTP**: `GET /market/plates/{plate_type}/{plate_code}/stocks`
- **SDK**: `DataApi.plates_stocks(...)`

### 参数

| 参数 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `plate_type` | `int` | ✅ | `14` / `15` / `17` |
| `plate_code` | `str` | ✅ | 板块代码 |
| `date` | `str` | 否 | `YYYYMMDD` |

### 返回

`list[dict]`（板块内所有成分股详情）。

### 示例

```python
stocks = api.plates_stocks(plate_type=17, plate_code='801001', date='20260520')
```

---

## 4. `market_plate_stocks` — 板块成分股（按人气排名）

### 接口

- **HTTP**: `GET /v3/market/plates/{plate_type}/{plate_code}/stocks/rank`
- **SDK**: `DataApi.market_plate_stocks(...)`

### 参数

| 参数 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `plate_type` | `int` | ✅ | `14` / `15` / `17` |
| `plate_code` | `str` | ✅ | 板块代码 |
| `date1` | `str` | ✅ | `YYYYMMDD` |
| `is_real` | `int` | 否 | 1=实时 / 0=收盘后，默认 1 |
| `limit` | `int` | 否 | 默认 50 |

### 与 `plates_stocks` 的区别

`plates_stocks` 返回板块全部成分股；`market_plate_stocks` **按人气排名**返回 TopN。

### 示例

```python
top = api.market_plate_stocks(plate_type=17, plate_code='801001',
                              date1='20260520', is_real=1, limit=5)
```

---

## 5. `market_plate_popular_reason` — 板块爆点 / 原因

### 接口

- **HTTP**: `GET /v3/market/plate/popular/reason`
- **SDK**: `DataApi.market_plate_popular_reason(...)`

### 参数

| 参数 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `plate_code` | `str` | ✅ | 板块代码 |
| `date2` | `str` | 否 | 截止日期 `YYYYMMDD` |

### 返回

`dict` / `list[dict]`——板块题材的爆点 / 原因列表。

### 示例

```python
reason = api.market_plate_popular_reason(plate_code='801660', date2='20260520')
```

---

## 6. `plates_trend` — 板块分时数据

### 接口

- **HTTP**: `GET /market/plates/{plate_type}/trend`
- **SDK**: `DataApi.plates_trend(...)`

### 参数

| 参数 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `plate_type` | `int` | ✅ | `14` / `15` / `17` |
| `plate_code` | `str` | ✅ | 板块代码 |
| `day_start` | `str` | ✅ | `YYYYMMDD` |
| `day_end` | `str` | ✅ | `YYYYMMDD` |

---

## 7. `plates_rank_days` — 板块区间排名

### 接口

- **HTTP**: `GET /v3/market/plates/{plate_type}/rank/days`
- **SDK**: `DataApi.plates_rank_days(...)`

### 参数

| 参数 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `plate_type` | `int` | ✅ | `14` / `15` / `17` |
| `date2` | `str` | ✅ | 截止日期 `YYYYMMDD` |
| `n_days` | `int` | 否 | 累计天数，默认 5 |
| `n_type` | `int` | 否 | 排序类型：`1`=涨幅 / `3`=净额 / `9`=强度，默认 3 |
| `limit` | `int` | 否 | 默认 10 |

### 返回

近 N 日板块累计排名数据（按涨幅 / 资金净额 / 强度等不同维度）。

---

## 8. `plates_rank_days_new` — 区间排名 + 新进标记

### 接口

- **HTTP**: `GET /v3/market/plates/{plate_type}/rank/days/new`
- **SDK**: `DataApi.plates_rank_days_new(...)`

### 参数

| 参数 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `plate_type` | `int` | ✅ | `14` / `15` / `17` |
| `date2` | `str` | ✅ | 截止日期 `YYYYMMDD` |
| `n_days` | `int` | 否 | 默认 5 |
| `n_type` | `int` | 否 | 默认 3 |
| `limit` | `int` | 否 | 默认 20 |
| `prev_days` | `int` | 否 | 往前追溯天数，默认 3 |

### 返回

与 `plates_rank_days` 类似，但额外标记 `is_new` 字段（是否是 `prev_days` 内新进的板块）。