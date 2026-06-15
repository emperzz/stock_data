# AKShare 债券 数据字典

共 **43** 个接口。

## 接口索引

- [`bond_info_cm`](./bond/bond_info_cm.md): 中国外汇交易中心暨全国银行间同业拆借中心-数据-债券信息-信息查询
- [`bond_info_detail_cm`](./bond/bond_info_detail_cm.md): 中国外汇交易中心暨全国银行间同业拆借中心-数据-债券信息-信息查询-债券详情
- [`bond_cash_summary_sse`](./bond/bond_cash_summary_sse.md): 上登债券信息网-市场数据-市场统计-市场概览-债券现券市场概览
- [`bond_deal_summary_sse`](./bond/bond_deal_summary_sse.md): 上登债券信息网-市场数据-市场统计-市场概览-债券成交概览
- [`bond_debt_nafmii`](./bond/bond_debt_nafmii.md): 中国银行间市场交易商协会-非金融企业债务融资工具注册信息系统
- [`bond_spot_quote`](./bond/bond_spot_quote.md): 中国外汇交易中心暨全国银行间同业拆借中心-市场数据-市场行情-债券市场行情-现券市场做市报价
- [`bond_spot_deal`](./bond/bond_spot_deal.md): 中国外汇交易中心暨全国银行间同业拆借中心-市场数据-市场行情-债券市场行情-现券市场成交行情
- [`bond_china_yield`](./bond/bond_china_yield.md): 中国债券信息网-国债及其他债券收益率曲线
- [`bond_zh_hs_spot`](./bond/bond_zh_hs_spot.md): 新浪财经-债券-沪深债券-实时行情数据
- [`bond_zh_hs_daily`](./bond/bond_zh_hs_daily.md): 新浪财经-债券-沪深债券-历史行情数据, 历史数据按日频率更新
- [`bond_cb_profile_sina`](./bond/bond_cb_profile_sina.md): 新浪财经-债券-可转债-详情资料
- [`bond_cb_summary_sina`](./bond/bond_cb_summary_sina.md): 新浪财经-债券-可转债-债券概况
- [`bond_zh_hs_cov_spot`](./bond/bond_zh_hs_cov_spot.md): 新浪财经-沪深可转债数据
- [`bond_zh_hs_cov_daily`](./bond/bond_zh_hs_cov_daily.md): 新浪财经-历史行情数据，日频率更新, 新上的标的需要次日更新数据
- [`bond_zh_hs_cov_min`](./bond/bond_zh_hs_cov_min.md): 东方财富网-可转债-分时行情
- [`bond_zh_hs_cov_pre_min`](./bond/bond_zh_hs_cov_pre_min.md): 东方财富网-可转债-分时行情-盘前分时
- [`bond_zh_cov`](./bond/bond_zh_cov.md): 东方财富网-数据中心-新股数据-可转债数据一览表
- [`bond_zh_cov_info`](./bond/bond_zh_cov_info.md): 东方财富网-数据中心-新股数据-可转债详情
- [`bond_zh_cov_info_ths`](./bond/bond_zh_cov_info_ths.md): 同花顺-数据中心-可转债
- [`bond_cov_comparison`](./bond/bond_cov_comparison.md): 东方财富网-行情中心-债券市场-可转债比价表
- [`bond_zh_cov_value_analysis`](./bond/bond_zh_cov_value_analysis.md): 东方财富网-行情中心-新股数据-可转债数据-可转债价值分析
- [`bond_zh_cov_value_analysis`](./bond/bond_zh_cov_value_analysis.md): 东方财富网-行情中心-新股数据-可转债数据-可转债溢价率分析
- [`bond_sh_buy_back_em`](./bond/bond_sh_buy_back_em.md): 东方财富网-行情中心-债券市场-上证质押式回购
- [`bond_sz_buy_back_em`](./bond/bond_sz_buy_back_em.md): 东方财富网-行情中心-债券市场-深证质押式回购
- [`bond_buy_back_hist_em`](./bond/bond_buy_back_hist_em.md): 东方财富网-行情中心-债券市场-质押式回购-历史数据
- [`bond_cb_jsl`](./bond/bond_cb_jsl.md): 集思录可转债实时数据，包含行情数据（涨跌幅，成交量和换手率等）及可转债基本信息（转股价，溢价率和到期收益率等）
- [`bond_cb_redeem_jsl`](./bond/bond_cb_redeem_jsl.md): 集思录可转债-强赎
- [`bond_cb_index_jsl`](./bond/bond_cb_index_jsl.md): 可转债-集思录可转债等权指数
- [`bond_cb_adj_logs_jsl`](./bond/bond_cb_adj_logs_jsl.md): 集思录-单个可转债的转股价格-调整记录
- [`bond_china_close_return`](./bond/bond_china_close_return.md): 收盘收益率曲线历史数据, 该接口只能获取近 3 个月的数据，且每次获取的数据不超过 1 个月
- [`bond_zh_us_rate`](./bond/bond_zh_us_rate.md): 东方财富网-数据中心-经济数据-中美国债收益率历史数据
- [`bond_gb_zh_sina`](./bond/bond_gb_zh_sina.md): 新浪财经-债券-中国国债收益率行情数据
- [`bond_gb_us_sina`](./bond/bond_gb_us_sina.md): 新浪财经-债券-美国国债收益率行情数据
- [`bond_treasure_issue_cninfo`](./bond/bond_treasure_issue_cninfo.md): 巨潮资讯-数据中心-专题统计-债券报表-债券发行-国债发行
- [`bond_local_government_issue_cninfo`](./bond/bond_local_government_issue_cninfo.md): 巨潮资讯-数据中心-专题统计-债券报表-债券发行-地方债发行
- [`bond_corporate_issue_cninfo`](./bond/bond_corporate_issue_cninfo.md): 巨潮资讯-数据中心-专题统计-债券报表-债券发行-企业债发行
- [`bond_cov_issue_cninfo`](./bond/bond_cov_issue_cninfo.md): 巨潮资讯-数据中心-专题统计-债券报表-债券发行-可转债发行
- [`bond_cov_stock_issue_cninfo`](./bond/bond_cov_stock_issue_cninfo.md): 巨潮资讯-数据中心-专题统计-债券报表-债券发行-可转债转股
- [`bond_new_composite_index_cbond`](./bond/bond_new_composite_index_cbond.md) — 综合类指数 / 新综合指数: 中国债券信息网-中债指数-中债指数族系-总指数-综合类指数-中债-新综合指数
- [`bond_composite_index_cbond`](./bond/bond_composite_index_cbond.md): 中国债券信息网-中债指数-中债指数族系-分类指数-按待偿期限
- [`bond_treasury_index_cbond`](./bond/bond_treasury_index_cbond.md): 中国债券信息网-中债指数-中债指数族系-总指数-综合类指数-中债-国债指数
- [`bond_available_index_cbond`](./bond/bond_available_index_cbond.md): 中国债券信息网-中债指数-中债指数族系当中, 非指定期限部分的可选指数
- [`bond_index_general_cbond`](./bond/bond_index_general_cbond.md): 中国债券信息网-中债指数-中债指数族系
