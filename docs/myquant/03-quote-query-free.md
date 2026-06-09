# 行情数据查询函数（免费） — 原始文档

> 抓自 `https://www.myquant.cn/docs2/sdk/python/API介绍/行情数据查询函数（免费）.html`
>
> **重要提示**：本页页头标记「（免费）」，但页内 5 个 L2 相关函数（get_history_l2ticks / get_history_l2bars / get_history_l2transactions / get_history_l2orders / get_history_l2orders_queue）单独注明「仅特定券商付费提供」，本质属于券商版/机构版增值数据。

## # 行情数据查询函数（免费）

## # last_tick - 查询已订阅的最新 Tick （多标的）
查询已订阅的最新 Tick
函数原型：
```
last_tick(symbols, fields="", include_call_auction = False)
```
参数：
| 参数名 | 类型 | 说明 |
|---|---|---|
| symbols | str or list | 查询代码，如有多个代码, 中间用 , (英文逗号) 隔开, 也支持 ['symbol1', 'symbol2'] 这种列表格式 |
| fields | str | 查询字段, 默认所有字段, 具体字段见 tick 对象 |
| include_call_auction | bool | 是否支持集合竞价(9:15-9:25)取数，True为支持，False为不支持，默认 False |

返回值：list[dict]

注意：
1. 输入的 symbols 必须先订阅 tick，如果 last_tick 查询的标的代码不在 tick 行情订阅范围内，则返回该代码的 tick 字典除 symbol 外其他字段均为空字符串/0
2. 实时模式获取集合竞价的 tick 数据，需要指定 include_call_auction=True，注意集合竞价阶段没有成交，有效字段只有报价 quotes
3. 回测模式，先订阅标的行情 frequency='tick' 再调用 last_tick，会返回回测当前时刻最新的 tick.price，如果超出历史行情权限会报错中止回测

---

## # current_price - 查询当前最新价
查询指定标的当前时点最新价
函数原型：
```
current_price(symbols)
```
参数：
| 参数名 | 类型 | 说明 |
|---|---|---|
| symbols | str or list | 查询代码 |

返回值：list[dict]
| 字段名 | 类型 | 中文名称 | 说明 |
|---|---|---|---|
| symbol | str | 标的代码 | 格式 exchange.sec_id（SHSE.600000, SZSE.000001） |
| price | float | 最新价 | 实时模式：当前时点最新tick.price；回测模式行为见原文 |
| created_at | datetime.datetime | 创建时间 | 实时/回测行为见原文 |

注意：
- 回测模式订阅 'tick' / '60s' / '1d' 行为差异；不订阅时由 run() 的 backtest_intraday 控制（0=历史最新日线收盘价；1=回测当前交易日收盘价）

---

## # history - 查询历史行情
查询标的在指定时间段的历史行情数据
函数原型：
```
history(symbol, frequency, start_time, end_time, fields=None, skip_suspended=True,
        fill_missing=None, adjust=ADJUST_NONE, adjust_end_time='', df=False)
```
参数：
| 参数名 | 类型 | 说明 |
|---|---|---|
| symbol | str or list | 标的代码, 多个用逗号或 list |
| frequency | str | 频率, 支持 'tick', '1d', '60s' 等, 默认 '1d' |
| start_time | str or datetime.datetime | 开始时间 |
| end_time | str or datetime.datetime | 结束时间 |
| fields | str | 指定返回对象字段 |
| adjust | int | ADJUST_NONE=0 不复权 / ADJUST_PREV=1 前复权 / ADJUST_POST=2 后复权 |
| adjust_end_time | str | 复权基点时间, 默认当前时间 |
| df | bool | True=DataFrame, False=list[dict]，默认 False |

注意：
1. 前开后闭区间，按 eob 升序排序
2. **skip_suspended、fill_missing 暂不支持**
3. 日内数据单次返回最大 33000 条，超出部分不返回
4. **盘后 18 点清洗入库更新当天数据**，需要盘后取数据请在 18 点后取

---

## # history_n - 查询历史行情最新 n 条
查询标的最新 n 条的历史行情数据
函数原型：
```
history_n(symbol, frequency, count, end_time=None, fields=None, skip_suspended=True,
          fill_missing=None, adjust=ADJUST_NONE, adjust_end_time='', df=False)
```
参数：
| 参数名 | 类型 | 说明 |
|---|---|---|
| symbol | str | 单个标的代码（不支持多标的） |
| frequency | str | 频率 |
| count | int | 数量(正整数) |
| end_time | str or datetime | 结束时间，默认 None 即实际当前时间（非回测当前时间） |
| 其余 | 同 history | |

注意：
1. 单次返回最大 33000 条
2. 盘后 18 点清洗入库

---

## # context.data - 查询订阅数据
从订阅缓冲区取滑窗数据
函数原型：
```
context.data(symbol, frequency, count, fields)
```
返回类型由 `subscribe` 的 `format` 决定：
- `format='df'`（默认） → dataframe
- `format='row'` → list[dict]
- `format='col'` → dict（每字段为列表）

注意：
1. 必须先订阅
2. symbol 只支持一个
3. count 必须 ≤ subscribe 时的 count
4. fields 必须在 subscribe 的 fields 范围内
5. 效率：row > col > df
6. col 模式下，tick.quotes 只返回买卖一档：bid_p/bid_v/ask_p/ask_v

---

## # get_history_l2ticks - 查询历史 L2 Tick 行情 ⚠️ 仅特定券商付费
函数原型：
```
get_history_l2ticks(symbols, start_time, end_time, fields=None, skip_suspended=True,
                    fill_missing=None, adjust=ADJUST_NONE, adjust_end_time='', df=False)
```
- 每次只能提取一天的数据，超过一天则只返回结束时间最近一个交易日数据
- 超过一个自然月（31 天）则获取不到数据

## # get_history_l2bars - 查询历史 L2 Bar 行情 ⚠️ 仅特定券商付费
函数原型：
```
get_history_l2bars(symbols, frequency, start_time, end_time, fields=None, skip_suspended=True,
                   fill_missing=None, adjust=ADJUST_NONE, adjust_end_time='', df=False)
```
- 每次最多提取 1 个自然月（31）天

## # get_history_l2transactions - 查询历史 L2 逐笔成交 ⚠️ 仅特定券商付费
函数原型：
```
get_history_l2transactions(symbols, start_time, end_time, fields=None, df=False)
```
- 每次只能提取一天

## # get_history_l2orders - 查询历史 L2 逐笔委托 ⚠️ 仅特定券商付费
仅深市标的可用
函数原型：
```
get_history_l2orders(symbols, start_time, end_time, fields=None, df=False)
```
- 每次只能提取一天

## # get_history_l2orders_queue - 查询历史 L2 委托队列 ⚠️ 仅特定券商付费
函数原型：
```
get_history_l2orders_queue(symbols, start_time, end_time, fields=None, df=False)
```
- 每次只能提取一天
