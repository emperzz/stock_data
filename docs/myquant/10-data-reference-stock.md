# 10 数据文档 — 股票数据参考

> 来源：`docs2/docs/`（数据文档 → 股票）
>
> 这份文档主要给出**字段表**和**支持的 API 列表**；与上面 SDK 章节是「数据契约 ↔ 函数实现」的关系。

## 0. 数据日清洗

| 数据 | 更新规则 |
|---|---|
| K 线日数据 | 盘后 18:00 清洗入库（取当日数据需 18:00 后） |
| 财报 | 每季度财报公布日当日 19:00 |
| 龙虎榜、沪深港通 | 交易日约 20:00 更新 |

---

## 1. 基础数据（免费）

支持市场：上交所 SHSE、深交所 SZSE。
交易日历范围：从 1991-01-01 至今。

### Python 数据接口
- `get_symbol_infos` — 查询标的基本信息
- `get_symbols` — 查询指定交易日多标的交易信息
- `get_history_symbol` — 查询指定标的多日交易信息
- `get_trading_dates_by_year` — 查询年度交易日历
- `get_trading_session` — 查询交易时段

详细签名见 [04-common-data-free.md](04-common-data-free.md)。

---

## 2. 行情数据（免费）

### 实时行情：Tick / Bar
支持 60s / 300s / 900s / 1800s / 3600s 五档频率（不含 1s/30s）。

### 历史行情：Tick / Bar
- Tick 历史最早 2022-08-10（不同版本权限不同；体验版/专业版/券商版/机构版有差异）
- Bar 日线（1d）：上市以来
- Bar 分钟线：具体范围按终端「数据管理」下载权限

### Tick 字段（实时+历史一致）

| 字段 | 类型 | 说明 |
|---|---|---|
| `symbol` | str | 标的代码 |
| `open` | float | 开盘价 |
| `high` | float | 最高价 |
| `low` | float | 最低价 |
| `price` | float | 最新价 |
| `cum_volume` | int | 成交总量（累计） |
| `cum_amount` | float | 成交总额（累计） |
| `trade_type` | int | 1 双开 / 2 双平 / 3 多开 / 4 空开 / 5 空平 / 6 多平 / 7 多换 / 8 空换 |
| `last_volume` | int | 瞬时成交量 |
| `last_amount` | float | 瞬时成交额（郑商所为 0） |
| `cum_position` | int | 持仓量（期），股票为 0 |
| `created_at` | datetime | 创建时间 |
| `quotes` | list[quote] | 买卖 1–5 档 |
| `iopv` | float | 基金参考净值（仅基金） |

### Quote（报价子结构）
| `bid_p` | float | 买价 |
| `bid_v` | int | 买量 |
| `ask_p` | float | 卖价 |
| `ask_v` | int | 卖量 |

### Bar 字段

| 字段 | 类型 | 说明 |
|---|---|---|
| `symbol` | str | 标的 |
| `frequency` | str | 频率 |
| `open` / `close` / `high` / `low` | float | OHLC |
| `amount` | float | 成交额 |
| `volume` | int | 成交量 |
| `bob` | datetime | bar 开始时间 |
| `eob` | datetime | bar 结束时间 |

---

## 3. 财务数据（免费）

### 数据接口
- `stk_get_fundamentals_balance` / `_pt` — 资产负债表
- `stk_get_fundamentals_cashflow` / `_pt` — 现金流量表
- `stk_get_fundamentals_income` / `_pt` — 利润表
- `stk_get_finance_prime` / `_pt` — 财务主要指标
- `stk_get_finance_deriv` / `_pt` — 财务衍生指标

### 维护时间范围
- 资产负债表：1989-12-31 至今
- 现金流量表：1996-12-31 至今
- 利润表：1989-12-31 至今
- 更新：每季度财报公布日当日 19:00

### 资产负债表字段（节选）

每个字段都标明「适用行业」：通用 / 银行 / 证券 / 保险。

#### 流动资产
| 字段 | 中文名 | 单位 | 行业限制 |
|---|---|---|---|
| `cash_bal_cb` | 现金及存放中央银行款项 | 元 | 银行 |
| `dpst_ob` | 存放同业款项 | 元 | 银行 |
| `mny_cptl` | 货币资金 | 元 | 通用 |
| `cust_cred_dpst` | 客户信用资金存款 | 元 | 证券 |
| `cust_dpst` | 客户资金存款 | 元 | 证券 |
| `pm` | 贵金属 | 元 | 银行 |
| `bal_clr` | 结算备付金 | 元 | 通用 |
| `cust_rsv` | 客户备付金 | 元 | 证券 |
| `ln_to_ob` | 拆出资金 | 元 | 通用 |
| `fair_val_fin_ast` | 以公允价值计量且其变动计入当期损益的金融资产 | 元 | 通用 |
| `ppay` | 预付款项 | 元 | 通用 |
| `fin_out` | 融出资金 | 元 | 通用 |
| `trd_fin_ast` | 交易性金融资产 | 元 | 通用 |
| `deriv_fin_ast` | 衍生金融资产 | 元 | 通用 |
| `note_acct_rcv` | 应收票据及应收账款 | 元 | 通用 |
| `note_rcv` | 应收票据 | 元 | 通用 |
| `acct_rcv` | 应收账款 | 元 | 通用 |
| `acct_rcv_fin` | 应收款项融资 | 元 | 通用 |
| `int_rcv` | 应收利息 | 元 | 通用 |
| `dvd_rcv` | 应收股利 | 元 | 通用 |
| `oth_rcv` | 其他应收款 | 元 | 通用 |
| `in_prem_rcv` | 应收保费 | 元 | 通用 |
| `rin_acct_rcv` | 应收分保账款 | 元 | 通用 |
| `rin_rsv_rcv` | 应收分保合同准备金 | 元 | 保险 |
| `rfd_dpst` | 存出保证金 | 元 | 证券、保险 |
| `term_dpst` | 定期存款 | 元 | 保险 |
| `pur_resell_fin` | 买入返售金融资产 | 元 | 通用 |
| `aval_sale_fin` | 可供出售金融资产 | 元 | 通用 |
| `htm_inv` | 持有至到期投资 | 元 | 通用 |
| `hold_for_sale` | 持有待售资产 | 元 | 通用 |
| `acct_rcv_inv` | 应收款项类投资 | 元 | 保险 |
| `invt` | 存货 | 元 | 通用 |
| `contr_ast` | 合同资产 | 元 | 通用 |
| `ncur_ast_one_y` | 一年内到期的非流动资产 | 元 | 通用 |
| `oth_cur_ast` | 其他流动资产 | 元 | 通用 |
| `ttl_cur_ast` | 流动资产合计 | 元 | 通用 |

#### 非流动资产
| 字段 | 中文名 |
|---|---|
| `loan_adv` | 发放委托贷款及垫款 |
| `cred_inv` | 债权投资 |
| `oth_cred_inv` | 其他债权投资 |
| `lt_rcv` | 长期应收款 |
| `lt_eqy_inv` | 长期股权投资 |
| `oth_eqy_inv` | 其他权益工具投资 |
| `rfd_cap_guar_dpst` | 存出资本保证金（保险） |
| `oth_ncur_fin_ast` | 其他非流动金融资产 |
| `amor_cos_fin_ast_ncur` | 以摊余成本计量的金融资产（非流动） |
| `fair_val_oth_inc_ncur` | 以公允价值计量且其变动计入其他综合收益的金融资产（非流动） |
| `inv_prop` | 投资性房地产 |
| `fix_ast` | 固定资产 |
| `const_prog` | 在建工程 |
| `const_matl` | 工程物资 |
| `fix_ast_dlpl` | 固定资产清理 |
| `cptl_bio_ast` | 生产性生物资产 |
| `oil_gas_ast` | 油气资产 |
| `rig_ast` | 使用权资产 |
| `intg_ast` | 无形资产 |
| `trd_seat_fee` | 交易席位费（证券） |
| `dev_exp` | 开发支出 |
| `gw` | 商誉 |
| `lt_ppay_exp` | 长期待摊费用 |
| `dfr_tax_ast` | 递延所得税资产 |
| `oth_ncur_ast` | 其他非流动资产 |
| `ttl_ncur_ast` | 非流动资产合计 |
| `ttl_ast` | 资产总计 |

#### 流动负债 / 非流动负债 / 所有者权益
完整字段超过 100 个；常用：
- `sht_ln`（短期借款）、`note_acct_pay`（应付票据及应付账款）、`emp_comp_pay`（应付职工薪酬）、`tax_pay`（应交税费）、`ttl_cur_liab`（流动负债合计）
- `lt_ln`（长期借款）、`bnd_pay`（应付债券）、`bnd_pay_pbd`（永续债）、`bnd_pay_pfd`（优先股）、`leas_liab`（租赁负债）、`dfr_tax_liab`（递延所得税负债）、`ttl_ncur_liab`（非流动负债合计）、`ttl_liab`（负债合计）
- `paid_in_cptl`（实收资本/股本）、`oth_eqy`（其他权益工具）、`cptl_rsv`（资本公积）、`treas_shr`（库存股）、`sur_rsv`（盈余公积）、`ret_prof`（未分配利润）、`min_sheqy`（少数股东权益）、`ttl_eqy_pcom`（归母权益）、`ttl_eqy`（股东权益合计）、`ttl_liab_eqy`（负债+权益合计）

### 现金流量表字段（节选）

#### 一、经营活动现金流
| 字段 | 中文名 |
|---|---|
| `cash_rcv_sale` | 销售商品、提供劳务收到的现金 |
| `tax_rbt_rcv` | 收到的税费返还 |
| `cash_rcv_oth_oper` | 收到其他与经营活动有关的现金 |
| `cf_in_oper` | 经营活动现金流入小计 |
| `cash_pur_gds_svc` | 购买商品、接受劳务支付的现金 |
| `cash_pay_emp` | 支付给职工以及为职工支付的现金 |
| `cash_pay_tax` | 支付的各项税费 |
| `cash_pay_oth_oper` | 支付其他与经营活动有关的现金 |
| `cf_out_oper` | 经营活动现金流出小计 |
| `net_cf_oper` | **经营活动产生的现金流量净额** |

#### 二、投资活动现金流
| 字段 | 中文名 |
|---|---|
| `cash_rcv_sale_inv` | 收回投资收到的现金 |
| `inv_inc_rcv` | 取得投资收益收到的现金 |
| `cash_rcv_dspl_ast` | 处置固定/无形资产收回的现金净额 |
| `cf_in_inv` | 投资活动现金流入小计 |
| `pur_fix_intg_ast` | 购建固定/无形/长期资产支付的现金 |
| `cash_pay_inv` | 投资支付的现金 |
| `cf_out_inv` | 投资活动现金流出小计 |
| `net_cf_inv` | **投资活动产生的现金流量净额** |

#### 三、筹资活动现金流
| 字段 | 中文名 |
|---|---|
| `cash_rcv_cptl` | 吸收投资收到的现金 |
| `brw_rcv` | 取得借款收到的现金 |
| `cash_rcv_bnd_iss` | 发行债券收到的现金 |
| `cf_in_fin` | 筹资活动现金流入小计 |
| `cash_rpay_brw` | 偿还债务支付的现金 |
| `cash_pay_dvd_int` | 分配股利、利润或偿付利息支付的现金 |
| `cf_out_fin` | 筹资活动现金流出小计 |
| `net_cf_fin` | **筹资活动产生的现金流量净额** |

#### 四 / 五 / 六
- `efct_er_chg_cash` — 汇率变动对现金及现金等价物的影响
- `net_incr_cash_eq` — 现金及现金等价物净增加额
- `cash_cash_eq_bgn` — 期初余额
- `cash_cash_eq_end` — 期末余额

### 利润表字段（节选）

| 字段 | 中文名 |
|---|---|
| `ttl_inc_oper` | 营业总收入 |
| `inc_oper` | 营业收入 |
| `net_inc_int` | 利息净收入（金融行业） |
| `inc_fee_comm` | 手续费及佣金收入 |
| `in_prem_earn` | 已赚保费 |
| `ttl_cost_oper` | 营业总成本 |
| `cost_oper` | 营业成本 |
| `biz_tax_sur` | 营业税金及附加 |
| `exp_sell` | 销售费用 |
| `exp_adm` | 管理费用 |
| `exp_rd` | 研发费用 |
| `exp_fin` | 财务费用 |
| `inc_inv` | 投资收益 |
| `inc_ast_dspl` | 资产处置收益 |
| `ast_impr_loss` | 资产减值损失 |
| `cred_impr_loss` | 信用减值损失 |
| `inc_fv_chg` | 公允价值变动收益 |
| `inc_other` | 其他收益 |
| `oper_prof` | 营业利润 |
| `inc_noper` | 营业外收入 |
| `exp_noper` | 营业外支出 |
| `ttl_prof` | 利润总额 |
| `inc_tax` | 所得税费用 |
| `net_prof` | 净利润 |
| `net_prof_pcom` | 归属于母公司股东的净利润 |
| `min_int_inc` | 少数股东损益 |
| `eps_base` | 基本每股收益 |
| `eps_dil` | 稀释每股收益 |
| `ttl_comp_inc` | 综合收益总额 |
| `ttl_comp_inc_pcom` | 归属于母公司所有者的综合收益总额 |

---

## 4. 行业数据（**付费**）

### 数据接口
- `stk_get_industry_category` — 查询行业分类
- `stk_get_industry_constituents` — 查询行业成分股
- `stk_get_symbol_industry` — 查询股票所属行业

### 行业分类源
- **证监会行业分类(2012)**：一级行业 A–S（19 个），二级行业 1–90
- **申万行业分类(2021)**：三级结构。一级如 110000 农林牧渔 / 220000 基础化工 / 270000 电子 / 280000 汽车 / 480000 银行 / 490000 非银金融 等

### 证监会一级行业（节选）
| 代码 | 一级行业 |
|---|---|
| A | 农、林、牧、渔业 |
| B | 采矿业 |
| C | 制造业 |
| D | 电力、热力、燃气及水生产和供应业 |
| E | 建筑业 |
| F | 批发和零售业 |
| G | 交通运输、仓储和邮政业 |
| H | 住宿和餐饮业 |
| I | 信息传输、软件和信息技术服务业 |
| J | 金融业 |
| K | 房地产业 |
| L | 租赁和商务服务业 |
| M | 科学研究和技术服务业 |
| N | 水利、环境和公共设施管理业 |
| O | 居民服务、修理和其他服务业 |
| P | 教育 |
| Q | 卫生和社会工作 |
| R | 文化、体育和娱乐业 |
| S | 综合 |

### 申万 2021 一级行业（21 个）
110000 农林牧渔 / 220000 基础化工 / 230000 钢铁 / 240000 有色金属 / 270000 电子 / 280000 汽车 / 330000 家用电器 / 340000 食品饮料 / 350000 纺织服饰 / 360000 轻工制造 / 370000 医药生物 / 410000 公用事业 / 420000 交通运输 / 430000 房地产 / 450000 商贸零售 / 460000 社会服务 / 480000 银行 / 490000 非银金融 / 510000 综合 / 610000 建筑材料 / 620000 建筑装饰 / 630000 电力设备 / 640000 机械设备 / 650000 国防军工 / 710000 计算机 / 720000 传媒 / 730000 通信 / 740000 煤炭 / 750000 石油石化 / 760000 环保 / 770000 美容护理。

---

## 5. 板块数据（**付费**）

### 数据接口
- `stk_get_sector_category(sector_type)` — 查询板块分类
- `stk_get_sector_constituents(sector_code)` — 查询板块成分股
- `stk_get_symbol_sector(symbols, sector_type)` — 查询股票所属板块

### 三种板块（`sector_type`）
| `sector_type` | 含义 | 示例 |
|---|---|---|
| `1001` | 市场板块 | `1001` 沪深 AB 股, `1057` 科创板, `1067` 注册制创业板, `1071` 全部 A 股, `1045` 融资融券标的(含 ETF) |
| `1002` | 地域板块 | 6 位编码，按地市划分（如 `6003006001` 上海市，`6006001015` 深圳市） |
| `1003` | 概念板块 | 6 位编码 007xxx，如 `007009` HS300、`007195` 人工智能、`007296` 白酒、`007488` ChatGPT 概念 |

### 市场板块（节选）
| 代码 | 名称 |
|---|---|
| 1001 | 沪深 AB 股 |
| 1004 | 沪深 A 股 |
| 1010 | 全部创业板 |
| 1017 | ST |
| 1018 | *ST |
| 1023 | 风险警示股票 |
| 1038 | 沪股通 |
| 1041 | 深股通 |
| 1045 | 融资融券标的(含 ETF) |
| 1047 | 沪深股通 |
| 1057 | 科创板 |
| 1065 | 沪深 A 股（除科创板、创业板） |
| 1067 | 注册制创业板 |
| 1069 | 可转债标的 |
| 1070 | 北证 A 股 |
| 1071 | 全部 A 股 |
| 1075 | 当日融资融券标的(含 ETF) |

> 完整板块清单（截至 2023-03-21）共 50+ 个市场板块，~340 个地域板块，~470 个概念板块。

---

## 6. 分红派息（**付费**）

- `stk_get_dividend(symbol, start_date, end_date)` — 查询股票分红送股信息
- `stk_get_ration(symbol, start_date, end_date)` — 查询股票配股信息

### `stk_get_dividend` 返回字段
| 字段 | 说明 |
|---|---|
| `symbol` | 标的代码 |
| `scheme_type` | 方案类型，如 `'现金分红'` |
| `pub_date` | 公告日期 |
| `equity_reg_date` | 股权登记日 |
| `ex_date` | 除权除息日 |
| `cash_pay_date` | 现金派发日 |
| `share_acct_date` | 送股入账日 |
| `share_lst_date` | 送股上市流通日 |
| `cash_af_tax` | 税后派现（每 10 股） |
| `cash_bf_tax` | 税前派现（每 10 股） |
| `bonus_ratio` | 送股比例 |
| `convert_ratio` | 转股比例 |
| `base_date` | 基准日期 |
| `base_share` | 基准股本 |

支持的时间范围：上市以来。

---

## 7. 股本股东（**付费**）

- `stk_get_shareholder_num` — 股东户数（A 股、B 股、H 股总数）
- `stk_get_top_shareholder` — 十大股东（持股数、所持股份性质）
- `stk_get_share_change` — 股本变动公告

---

## 8. 龙虎榜（**付费**）

更新：日频，交易日约 20:00 更新当日数据。
起始日期：2004-06-25。

- `stk_abnor_change_stocks(symbols=None, change_types=None, trade_date=None, fields=None, df=False)` — 查询龙虎榜股票
- `stk_abnor_change_detail(symbols=None, change_types=None, trade_date=None, fields=None, df=False)` — 查询龙虎榜营业部

### 异动类型 `change_types`（节选，完整 101–172）

| 代码 | 异动原因 |
|---|---|
| 101 | 龙虎榜（总类） |
| 102 | 有涨跌幅限制的异动证券 |
| 103 | 当日价格振幅达到 15% 的证券 |
| 104 | 涨跌幅偏离值异常 |
| 105 | 涨幅偏离值异常 |
| 106 | 当日涨幅偏离值达 7% 的证券 |
| 107 | 连续三个交易日内收盘价格涨幅偏离值累计 20% |
| 108-110 | S/ST/*ST 三日涨幅偏离值 12%/12%/15% |
| 111 | 跌幅偏离值异常 |
| 112 | 当日跌幅偏离值达 7% 的证券 |
| 113 | 连续三个交易日内收盘价跌幅偏离值累计 20% |
| 117 | 连续多个交易日触及或达到涨跌幅限制 |
| 128 | 换手率 |
| 129 | 当日换手率达到 20% 的证券 |
| 130 | 日均换手率/前 5 日均换手率比值达 30 倍 + 累计 20% |
| 131 | 无价格涨跌幅限制的证券 |
| 132 | 无价格涨跌幅限制的股票 |
| 133-136 | 无涨跌幅限制股票当日盘中涨/跌 30%/50%/100% |
| 138 | 单只标的证券的当日融资买卖数量 |
| 139 | 当日融资买入数量占该证券总交易量 50% 以上 |
| 140 | 当日融券卖出数量占总交易量 50% 以上 |
| 144 | 同一营业部连续 2 个交易日涨停 + 净买入占比 30% + 无重大事项 |
| 146 | 风险警示股票盘中换手率 ≥ 30% |
| 147 | 退市整理的证券 |
| 148 | 风险警示期交易 |
| 149-152 | 日涨幅 15% / 日跌幅 15% / 振幅 30% / 换手率 30% 前 5 只 |
| 153-160 | 涨/跌幅 3 日 30% / 同向异动 / 10 日 100%(-50%) / 30 日 200%(-70%) |
| 161 | 新股首日交易信息 |
| 168-169 | 当日收盘价涨/跌幅 20% 前 5 只股票 |
| 170 | 北交所股票最近 3 个有成交日内涨跌幅偏离值累计 +40%(-40%) |
| 171-172 | 严重异常期间 4 次正/负向异常波动 |

---

## 9. 北向资金 / 沪深港通（**付费**）

更新：日频，交易日约 20:00 更新当日数据。

- `stk_quota_shszhk_infos(types=None, start_date=None, end_date=None, count=None, df=False)` — 沪深港通额度（起始：2016-12-05）
- `stk_hk_inst_holding_detail_info(symbols=None, trade_date=None, df=False)` — 沪深港通标的港股机构持股**明细**（起始：2024-01-23）
- `stk_hk_inst_holding_info(symbols=None, trade_date=None, df=False)` — 沪深港通标的港股机构持股汇总（起始：2024-01-23）
- `stk_active_stock_top10_shszhk_info(types=None, trade_date=None, df=False)` — 沪深港通**十大活跃成交股**（起始：2014-11-17）

### `types` 取值
| 值 | 含义 |
|---|---|
| `SHHK` | 沪股通（北向，沪市→香港买卖香港） |
| `SZHK` | 深股通（北向，深市→香港） |
| `HKSH` | 港股通（南向，香港→沪市） |
| `HKSZ` | 港股通（南向，香港→深市） |

---

## 10. 其他增值数据（**付费**）

- `stk_get_adj_factor(symbol, start_date='', end_date='', base_date='')` — 复权因子
- `stk_get_money_flow(symbols, trade_date=None)` — 个股资金流向
- `stk_get_finance_audit(symbols, date=None, rpt_date=None, df=False)` — 财务审计意见
- `stk_get_finance_forecast(symbols, rpt_type=None, date=None, df=False)` — 业绩预告
- `get_open_call_auction(symbols, trade_date=None)` — 集合竞价开盘成交

详细签名见 [06-stock-valueadd-paid.md](06-stock-valueadd-paid.md)。
