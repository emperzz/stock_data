# 01 策略生命周期 — 基本函数

> 来源：`docs2/sdk/python/API介绍/基本函数.html`
>
> **免费 / 付费**：均为免费（属于 SDK 策略框架，不涉及数据费用）。

策略主线只有 6 个函数：

```
run() → init(context) → [事件循环] → stop()
                            ↑
                            └─ schedule / timer 触发的定时器
```

---

## `init(context)`
策略启动时**自动执行一次**，用于初始化配置、订阅行情、初始化 context 自定义属性。

```python
def init(context):
    subscribe(symbols='SHSE.600000,SHSE.600004', frequency='30s', count=5)
    context.percentage_stock = 0.8
```

**注意**：
1. **回测模式下 `init` 里不支持交易操作**（仿真、实盘可下单）。
2. `init` 只在启动时跑一次；如果不重启策略而每天都要刷新数据，请配合 `schedule` 设置每日任务。

---

## `schedule(schedule_func, date_rule, time_rule)`
在指定时间自动执行某个函数，**通常用于选股类策略**。

| 参数 | 类型 | 说明 |
|---|---|---|
| `schedule_func` | function | 要被调用的策略函数 `f(context)` |
| `date_rule` | str | 日期规则。`'1d'` 每天 / `'1w'` 每周 / `'1m'` 每月 |
| `time_rule` | str | 执行时间 `%H:%M:%S` |

返回 `None`。

```python
def init(context):
    schedule(schedule_func=algo_1, date_rule='1d', time_rule='19:06:20')
    schedule(schedule_func=algo_2, date_rule='1m', time_rule='9:40:00')

def algo_1(context):
    print(context.symbols)

def algo_2(context):
    order_volume(symbol='SHSE.600000', volume=200, side=OrderSide_Buy,
                 order_type=OrderType_Market, position_effect=PositionEffect_Open)
```

**注意**：
1. `time_rule` 的时/分/秒**不可只输入个位数**（如 `'9:40:0'` 不行）。
2. 目前仅支持 `1d`、`1w`、`1m`；其中 `1w` 和 `1m` **仅用于回测**。

---

## `run(...)` — 启动策略

```python
run(strategy_id='', filename='', mode=MODE_UNKNOWN, token='',
    backtest_start_time='', backtest_end_time='',
    backtest_initial_cash=1000000,
    backtest_transaction_ratio=1, backtest_commission_ratio=0,
    backtest_slippage_ratio=0, backtest_adjust=ADJUST_NONE,
    backtest_check_cache=1, serv_addr='',
    backtest_match_mode=0, backtest_intraday=0)
```

| 参数 | 类型 | 说明 |
|---|---|---|
| `strategy_id` | str | 策略 ID |
| `filename` | str | 策略 py 文件名，如 `'Strategy.py'` |
| `mode` | int | `MODE_LIVE=1`（实盘/仿真）/ `MODE_BACKTEST=2`（回测） |
| `token` | str | 用户标识 |
| `backtest_start_time` / `backtest_end_time` | str | `%Y-%m-%d %H:%M:%S` |
| `backtest_initial_cash` | float | 回测初始资金，默认 1,000,000 |
| `backtest_transaction_ratio` | float | 回测成交比例，默认 1.0（下单 100% 成交） |
| `backtest_commission_ratio` | float | 回测佣金比例，默认 0 |
| `backtest_slippage_ratio` | float | 回测滑点比例，默认 0 |
| `backtest_adjust` | int | `ADJUST_NONE=0` / `ADJUST_PREV=1` / `ADJUST_POST=2` |
| `backtest_check_cache` | int | 1 用缓存 / 0 不用，默认 1 |
| `serv_addr` | str | 终端服务地址，默认本地；如 `"127.0.0.1:7001"` |
| `backtest_match_mode` | int | **回测市价撮合模式**。`1`=当前 bar 收盘价/当前 tick 撮合；`0`=下个 bar 开盘价/下个 tick 撮合（默认） |
| `backtest_intraday` | int | **回测不订阅行情时**，`current` / `current_price` 返回的日线价格类型：`0`=回测当前时刻的历史最新日线收盘价（T 日盘中为 T-1 收盘价）；`1`=回测当前交易日收盘价（T 日盘中和盘后均为 T 日收盘价），默认 `0` |

```python
run(strategy_id='strategy_1', filename='main.py', mode=MODE_BACKTEST,
    token='token_id',
    backtest_start_time='2016-06-17 13:00:00',
    backtest_end_time='2017-08-21 15:00:00')
```

**注意**：
1. `mode=1` 等价于 `mode=MODE_LIVE`，`backtest_adjust` 同理。
2. **前复权/后复权回测模式不会处理分红、送股、拆分事件**（已通过复权因子反映在价格上）；不复权模式会自动处理分红送转。
3. `filename` 指要运行的 py 文件名。

---

## `stop()` — 停止策略

```python
if not context.symbols:
    stop()
```

返回 `None`。

---

## `timer(timer_func, period, start_delay)` — 设置定时器（仿真/实盘）

> ⚠️ **回测模式下不生效**

| 参数 | 类型 | 说明 |
|---|---|---|
| `timer_func` | function | 触发时调用 |
| `period` | int | **毫秒**，范围 `[1, 43200000]`（即 1 ms ~ 12 小时） |
| `start_delay` | int | 启动延迟毫秒数，范围 `[0, 43200000]` |

返回 `dict`：
- `timer_status` — 设置是否成功（0=成功）
- `timer_id` — 定时器 ID

```python
def init(context):
    context.timerid_1 = timer(timer_func=ontimer_1, period=60000, start_delay=0)
    context.timerid_2 = timer(timer_func=ontimer_2, period=300000, start_delay=0)
```

**注意**：
1. **回测不生效**，仅仿真/实盘。
2. `period` 从前一次事件函数**开始执行**时点起算；若上一个还没跑完，会等它跑完再触发下一个。

---

## `timer_stop(timer_id)` — 停止定时器

| 参数 | 类型 | 说明 |
|---|---|---|
| `timer_id` | int | 要停止的定时器 ID |

返回 `{'is_stop': bool}`。

```python
ret = timer_stop(context.timerid_1['timer_id'])
```
