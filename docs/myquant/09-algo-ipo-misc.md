# 09 算法交易 / 新股新债 / 其他工具

> 来源：
> - `docs2/sdk/python/API介绍/算法交易函数.html`
> - `docs2/sdk/python/API介绍/新股新债交易函数.html`
> - `docs2/sdk/python/API介绍/其他函数.html`
>
> **免费 / 付费**：函数本身免费；算法策略实际可用与否取决于券商通道。

---

## 一、算法交易

掘金把 TWAP / VWAP / Iceberg 等算法策略包装成「母单 + 自动拆单」模式。下母单后由 SDK 自动按 `algo_name` 和 `algo_param` 拆出子单。

### `algo_order` — 算法委托

```
algo_order(symbol, volume, side, order_type, position_effect,
           price, algo_name, algo_param)
```

| 参数 | 类型 | 说明 |
|---|---|---|
| `algo_name` | str | 算法名：`'TWAP'` / `'VWAP'` / `'ICEBERG'` 等 |
| `algo_param` | dict | 算法参数 dict（如 `{'start_time': ..., 'end_time': ..., 'part_rate': 0.1}`） |
| 其余 | — | 与 `order_volume` 相同 |

### `algo_order_cancel(wait_cancel_orders)` — 撤销算法委托
也可传 `account` 撤销该账户全部算法委托。

### `algo_order_pause(alorders)` — 暂停/重启/撤销算法委托

### `get_algo_orders(account='')` — 查询算法委托

### `get_algo_child_orders(cl_ord_id, account='')` — 查询算法委托的所有子单

### `algo_order_batch(algo_orders, algo_name, algo_param, account='')` — 批量算法委托

### `on_algo_order_status(context, algo_order)` — 算法单状态事件

---

## 二、新股新债申购（IPO）

### `ipo_buy(symbol, volume, price, account_id='')`
申购。

### `ipo_get_quota(account_id='')`
查询新股新债申购额度。

### `ipo_get_instruments(sec_type, account_id='', df=False)`
查询**当日**新股新债清单。

| `sec_type` | 含义 |
|---|---|
| 1010 | 新股 |
| 1030 | 新债（可转债） |

### `ipo_get_match_number(start_time, end_time, account_id='', df=False)`
查询配号。

### `ipo_get_lot_info(start_time, end_time, account_id='', df=False)`
中签查询。

---

## 三、其他工具函数

### `set_token(token)` — 设置 token

仅在「**策略外**」（如 jupyter notebook 调数据）需要主动设置；策略内 `run(token=...)` 已设置。

```python
set_token('your token')
history_data = history(symbol='SHSE.000300', frequency='1d',
                       start_time='2010-07-28', end_time='2017-07-30', df=True)
```

### `set_option(max_wait_time=3600000, backtest_thread_num=1, ctp_md_info={})` — 系统设置

| 参数 | 说明 |
|---|---|
| `max_wait_time` | 回测/仿真最大等待时间（毫秒） |
| `backtest_thread_num` | 回测线程数 |
| `ctp_md_info` | 期货 CTP 行情参数 |

### `log(level, msg, source)` — 日志

```python
log(level='info', msg='平安银行信号触发', source='strategy')
```

`level` 取值：`'info'`、`'warning'`、`'error'`、`'debug'`。

### `get_strerror(error_code)` — 查询错误码描述

### `get_version()` — 查询 SDK 版本
