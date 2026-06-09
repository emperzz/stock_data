# 05 股票财务 & 基础数据函数（免费）

> 来源：`docs2/sdk/python/API介绍/股票财务数据及基础数据函数（免费）.html`
>
> **免费 / 付费**：所有函数均标注「掘金公版（体验版/专业版/机构版）函数，券商版以升级提示为准」——**免费**可用。
>
> 要求 `gm SDK >= 3.0.148`。

## 函数全清单（17 个）

| 函数 | 说明 |
|---|---|
| `stk_get_index_constituents` | 查询指数成分股（含权重） |
| **`_pt` 截面变体（多标的，单日 point-in-time）** | |
| `stk_get_fundamentals_balance_pt` | 资产负债表 截面 |
| `stk_get_fundamentals_cashflow_pt` | 现金流量表 截面 |
| `stk_get_fundamentals_income_pt` | 利润表 截面 |
| `stk_get_finance_prime_pt` | 财务主要指标 截面 |
| `stk_get_finance_deriv_pt` | 财务衍生指标 截面 |
| `stk_get_daily_valuation_pt` | 估值指标 单日截面 |
| `stk_get_daily_mktvalue_pt` | 市值指标 单日截面 |
| `stk_get_daily_basic_pt` | 股本等基础指标 单日截面 |
| **时间序列变体（单标的，多日）** | |
| `stk_get_fundamentals_balance` | 资产负债表 |
| `stk_get_fundamentals_cashflow` | 现金流量表 |
| `stk_get_fundamentals_income` | 利润表 |
| `stk_get_finance_prime` | 财务主要指标 |
| `stk_get_finance_deriv` | 财务衍生指标 |
| `stk_get_daily_valuation` | 估值指标 每日 |
| `stk_get_daily_mktvalue` | 市值指标 每日 |
| `stk_get_daily_basic` | 股本等基础指标 每日 |

---

## 1. `stk_get_index_constituents(index, trade_date=None)`

| 参数 | 类型 | 必填 | 默认 | 说明 |
|---|---|---|---|---|
| `index` | str | Y | — | 单个指数，如 `'SHSE.000905'`、`'SHSE.000300'` |
| `trade_date` | str | N | None | `%Y-%m-%d`；默认最新交易日 |

返回 **DataFrame**：

| 字段 | 类型 | 说明 |
|---|---|---|
| `index` | str | 指数代码 |
| `symbol` | str | 成分股代码 |
| `weight` | float | 权重（**中证系列指数因版权限制 weight=0**） |
| `trade_date` | str | 交易日 |
| `market_value_total` | float | 总市值（亿元） |
| `market_value_circ` | float | 流通市值（亿元） |

注意：
1. 在交易日约 20:00 更新当日数据；若调用时当日未更新，不指定 `trade_date` 会返回前一交易日数据，指定为当日会返回空。
2. `trade_date` 非交易日返回空 DataFrame；日期格式错误会报错。

---

## 2. 财务报表截面（`_pt` 系列）

以 `stk_get_fundamentals_balance_pt` 为模板，三张报表的截面 API 参数一致：

```
stk_get_fundamentals_balance_pt(symbols, rpt_type=None, data_type=None,
                                 date=None, fields, df=False)
stk_get_fundamentals_cashflow_pt(symbols, rpt_type=None, data_type=None,
                                  date=None, fields, df=False)
stk_get_fundamentals_income_pt(symbols, rpt_type=None, data_type=None,
                                date=None, fields, df=False)
```

| 参数 | 类型 | 必填 | 默认 | 说明 |
|---|---|---|---|---|
| `symbols` | str / list | Y | — | 单/多标的；str 用英文逗号分隔 |
| `fields` | str | Y | — | 财务字段名，多个用逗号；**不能超过 20 个字段** |
| `rpt_type` | int | N | None | 报表类型：`1`=一季报，`6`=中报，`9`=三季报，`12`=年报；默认不限 |
| `data_type` | int | N | None | `100`=合并最初，`101`=合并原始，`102`=合并调整，`200`=母公司最初，`201`=母公司原始，`202`=母公司调整；默认返回当期合并调整→合并原始→合并最初 |
| `date` | str | N | None | 查询日期（按发布日期 `pub_date`），`%Y-%m-%d`；默认最新 |
| `df` | bool | N | False | True 返回 DataFrame |

返回字段：`symbol` / `pub_date` / `rpt_date` / `rpt_type` / `data_type` / 你请求的 `fields`。

```python
stk_get_fundamentals_balance_pt(
    symbols='SHSE.600000, SZSE.000001',
    date='2022-10-01', fields='fix_ast', df=True
)
```

```
        symbol    pub_date    rpt_date        fix_ast  data_type  rpt_type
0  SZSE.000001  2022-10-25  2022-09-30 10975000000.00        102         9
1  SHSE.600000  2022-10-29  2022-09-30 42563000000.00        102         9
```

---

## 3. 财务报表时间序列（非 `_pt`）

```
stk_get_fundamentals_balance(symbol, rpt_type, data_type, start_date, end_date, fields, df=False)
stk_get_fundamentals_cashflow(symbol, ...)
stk_get_fundamentals_income(symbol, ...)
```

单标的、时间段查询。参数与 `_pt` 类似，但用 `start_date` / `end_date` 取代 `date`。

---

## 4. 财务主要 / 衍生指标

```
stk_get_finance_prime(symbol, fields, rpt_type=None, data_type=None, start_date=None, end_date=None, df=True)
stk_get_finance_deriv(symbol, fields, rpt_type=None, data_type=None, start_date=None, end_date=None, df=True)
```

主要指标 = 来自财报的关键指标（如 `eps_basic`、`eps_dil`、`roe`、`gross_margin` 等）；衍生指标 = 派生计算指标。

```python
stk_get_finance_prime(symbol='SHSE.600000', fields='eps_basic,eps_dil',
                      rpt_type=None, data_type=None,
                      start_date=None, end_date=None, df=True)
```

```
        symbol    pub_date    rpt_date  rpt_type  data_type  eps_basic  eps_dil
0  SHSE.600000  2017-04-27  2016-03-31         1        102       0.63     0.63
1  SHSE.600000  2017-08-30  2016-06-30         6        102       0.95     0.95
...
```

---

## 5. 估值 / 市值 / 基础指标日数据

```
stk_get_daily_valuation(symbol, fields, start_date, end_date, df=False)
stk_get_daily_mktvalue(symbol, fields, start_date, end_date, df=False)
stk_get_daily_basic(symbol, fields, start_date, end_date, df=False)
```

每日截面 + 单标的时间序列：
- **valuation**：PE / PB / PS / dividend_yield 等估值指标
- **mktvalue**：总市值 / 流通市值 / 自由流通市值
- **basic**：股本结构（总股本 / 流通股本 / 限售股本 等）

每个函数都有 `_pt` 版本，支持多标的单日截面：
```
stk_get_daily_valuation_pt(symbols, date, fields, df=False)
stk_get_daily_mktvalue_pt(symbols, date, fields, df=False)
stk_get_daily_basic_pt(symbols, date, fields, df=False)
```

---

## 字段大全

三张报表的完整字段表见 [10-data-reference-stock.md](10-data-reference-stock.md)。
要点：每个字段都有「适用行业」标注（银行/证券/保险/通用）。

> ⚠️ 调用财报 API 时，`fields` 不能超过 20 个字段；超出或拼写错误会报「填写的 fields 不正确」。
