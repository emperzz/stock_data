# 07 交易函数（下单 / 撤单 / 调仓 / 查询 / 持仓 / 标的池）

> 来源：
> - `docs2/sdk/python/API介绍/交易函数.html`
> - `docs2/sdk/python/API介绍/交易查询函数.html`
> - `docs2/sdk/python/API介绍/交易事件.html`
> - `docs2/sdk/python/API介绍/标的池.html`
>
> **免费 / 付费**：函数本身免费；实际下单/查询需有效的交易账户与券商通道权限。

---

## 下单 — 按指定量

```
order_volume(symbol, volume, side, order_type, position_effect,
             price=0, trigger_type=0, stop_price=0,
             order_duration=OrderDuration_Unknown,
             order_qualifier=OrderQualifier_Unknown, account='')
```

| 参数 | 类型 | 说明 |
|---|---|---|
| `symbol` | str | 标的 |
| `volume` | int | 下单量（股） |
| `side` | int | `OrderSide_Buy` / `OrderSide_Sell` |
| `order_type` | int | `OrderType_Market` / `OrderType_Limit` / `OrderType_Stop` |
| `position_effect` | int | `PositionEffect_Open`（开仓）/ `PositionEffect_Close`（平仓）等 |
| `price` | float | 限价价格（限价单必填） |
| `trigger_type` | int | 触发条件 |
| `stop_price` | float | 止损价 |
| `order_duration` | int | 委托有效期 |
| `order_qualifier` | int | 委托修饰 |
| `account` | str | 账户 ID，默认主账户 |

```python
order_volume(symbol='SHSE.600000', volume=10000,
             side=OrderSide_Buy, order_type=OrderType_Limit,
             position_effect=PositionEffect_Open, price=11)
```

---

## 下单 — 按指定价值

```
order_value(symbol, value, side, order_type, position_effect, price=0,
            order_duration=OrderDuration_Unknown,
            order_qualifier=OrderQualifier_Unknown, account='')
```

下 ¥`value` 金额的标的。

---

## 下单 — 按总资产百分比

```
order_percent(symbol, percent, side, order_type, position_effect, price=0,
              order_duration=OrderDuration_Unknown,
              order_qualifier=OrderQualifier_Unknown, account='')
```

`percent` 是 0-1 之间的比例（如 `0.1` = 总资产的 10%）。

---

## 调仓 — 到目标量

```
order_target_volume(symbol, volume, position_side, order_type, price=0,
                    order_duration=OrderDuration_Unknown,
                    order_qualifier=OrderQualifier_Unknown, account='')
```

```python
order_target_volume(symbol='SHSE.600000', volume=10000,
                    position_side=PositionSide_Long,
                    order_type=OrderType_Limit, price=13)
```

---

## 调仓 — 到目标价值

```
order_target_value(symbol, value, position_side, order_type, price=0,
                   order_duration=OrderDuration_Unknown,
                   order_qualifier=OrderQualifier_Unknown, account='')
```

---

## 调仓 — 到目标百分比（总资产的比例）

```
order_target_percent(symbol, percent, position_side, order_type, price=0,
                     order_duration=OrderDuration_Unknown,
                     order_qualifier=OrderQualifier_Unknown, account='')
```

---

## 批量委托

```
order_batch(orders, combine=False, account='')
```

`orders` 是订单 dict 的列表；`combine=True` 会尝试合并对冲单。

---

## 撤单

```
order_cancel(wait_cancel_orders)   # 撤销指定委托
order_cancel_all()                  # 撤销所有未结
order_close_all()                   # 平当前所有可平持仓
```

---

## 委托/回报查询

```
get_unfinished_orders()    # 日内全部未结委托
get_orders()                # 日内全部委托
get_execution_reports()     # 日内全部执行回报
```

> 三个查询都是只取「**当日**」数据。

---

## 资金/持仓查询

```
get_cash(account_id=None)       # 资金（dict）
get_position(account_id=None)   # 全部持仓（list[dict]）
```

策略上下文里的便捷写法（实时只读）：

```python
context.account().cash                       # 当前账户资金
context.account().positions()                # 当前账户全部持仓
context.account().position(symbol, side)     # 指定持仓
```

---

## 交易事件回调

| 事件 | 签名 | 触发时机 |
|---|---|---|
| `on_order_status` | `(context, order)` | 委托状态更新（已报/部成/全成/已撤/已拒等） |
| `on_execution_report` | `(context, execution)` | 成交回报 |
| `on_account_status` | `(context, account_status)` | 交易账户状态更新 |

---

## 标的池（Universe）

```
universe_set(universe_name, universe_symbols=None)
universe_get_symbols(universe_name)
universe_get_names()
universe_delete(universe_name)
```

标的池是**持久化**的命名集合，跨策略可见。

```python
universe_set(universe_name='妖股', universe_symbols=['SZSE.002137', 'SHSE.603421'])
universe_get_symbols(universe_name='持仓标的')
universe_get_names()
universe_delete(universe_name='龙头1')
```

`universe_set` 不传 `universe_symbols` 时表示**置空该池**。
