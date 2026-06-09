# 02 数据订阅 & 事件

> 来源：`docs2/sdk/python/API介绍/数据订阅.html`、`数据事件.html`
>
> **免费 / 付费**：订阅函数本身免费；逐笔类（`on_l2transaction` / `on_l2order`）需要券商版/L2 权限。

---

## `subscribe(symbols, frequency='1d', count=1, unsubscribe_previous=False)`

订阅行情。被订阅的 symbol/频率组合，会在到达新数据时通过事件（`on_tick` / `on_bar`）推送给你，也可以通过 `context.data(...)` 取滑窗。

| 参数 | 类型 | 说明 |
|---|---|---|
| `symbols` | str / list | 标的代码 |
| `frequency` | str | `'tick'`、`'1d'`、`'60s'`、`'300s'`、`'900s'`、`'1800s'`、`'3600s'` |
| `count` | int | 缓存滑窗大小（`context.data` 可取的最大长度） |
| `unsubscribe_previous` | bool | 是否先取消之前所有订阅 |

> 扩展参数（在 `context.data` 与 `subscribe` 高级用法中可见，但在订阅 API 主签名中未列出）：
> - `fields` — 指定字段过滤
> - `format` — `'df'`（默认）/ `'row'`（list[dict]）/ `'col'`（每字段独立列表）

```python
subscribe(symbols='SHSE.600519', frequency='60s', count=50,
          fields='symbol, close, eob', format='df')
```

---

## `unsubscribe(symbols='*', frequency='60s')`

取消订阅。`symbols='*'` 表示取消该频率的所有订阅。

```python
unsubscribe(symbols='SHSE.600000,SHSE.600004', frequency='60s')
unsubscribe(symbols='*', frequency='60s')
```

---

## 行情事件

事件函数签名固定，框架会在到达数据时自动调用：

### `on_tick(context, tick)`
tick 数据推送。`tick` 是 dict（字段见 `tick` 对象）。

### `on_bar(context, bars)`
bar 数据推送。**注意**：`bars` 是 `list[bar]`，不是单个 bar——同一时刻可能多个 symbol 的 bar 同时到达。

```python
def on_bar(context, bars):
    for b in bars:
        print(b['symbol'], b['close'])
```

### `on_l2transaction(context, transaction)` ⚠️ 仅 L2 权限
逐笔成交事件。

```python
def on_l2transaction(context, transaction):
    print(transaction)
```

### `on_l2order(context, l2order)` ⚠️ 仅 L2 权限，仅深市
逐笔委托事件。

```python
def on_l2order(context, l2order):
    print(l2order)
```

---

## tick 对象字段（实时 + 历史一致）

| 字段 | 类型 | 说明 |
|---|---|---|
| `symbol` | str | 标的代码 |
| `open` / `high` / `low` | float | 开盘 / 最高 / 最低 |
| `price` | float | 最新价 |
| `cum_volume` | int | 成交总量（累计） |
| `cum_amount` | float | 成交总额（累计） |
| `last_volume` | int | 瞬时成交量 |
| `last_amount` | float | 瞬时成交额（郑商所为 0） |
| `cum_position` | int | 持仓量（期），股票为 0 |
| `trade_type` | int | 1 双开 / 2 双平 / 3 多开 / 4 空开 / 5 空平 / 6 多平 / 7 多换 / 8 空换 |
| `created_at` | datetime | 创建时间 |
| `quotes` | list[quote] | 买卖 1–5 档；跌停时无买、涨停时无卖 |
| `iopv` | float | 基金份额参考净值（仅基金） |

### `quote` 子结构

| 字段 | 类型 | 说明 |
|---|---|---|
| `bid_p` | float | 买价 |
| `bid_v` | int | 买量 |
| `ask_p` | float | 卖价 |
| `ask_v` | int | 卖量 |

---

## bar 对象字段

| 字段 | 类型 | 说明 |
|---|---|---|
| `symbol` | str | 标的 |
| `frequency` | str | 频率 |
| `open` / `close` / `high` / `low` | float | OHLC |
| `amount` | float | 成交额 |
| `volume` | int | 成交量 |
| `bob` | datetime | bar 开始时间 (begin of bar) |
| `eob` | datetime | bar 结束时间 (end of bar) |

---

## 实时行情支持频率（股票）

| 交易所 | 频率 |
|---|---|
| 上交所 SHSE | 60s, 300s, 900s, 1800s, 3600s |
| 深交所 SZSE | 60s, 300s, 900s, 1800s, 3600s |

> 注：`s` 表示「秒」。

## 历史行情支持范围（股票）

| 交易所 | 频率与范围 |
|---|---|
| 上交所 SHSE | 60s / 300s / 900s / 1800s / 3600s（具体范围见终端「数据管理」下载权限）；1d 上市以来 |
| 深交所 SZSE | 同上 |
