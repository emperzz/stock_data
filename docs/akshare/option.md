# AKShare 期权 数据字典

共 **42** 个接口。

## 接口索引

- [`option_contract_info_ctp`](./option/option_contract_info_ctp.md): openctp 期权合约信息
- [`option_finance_board`](./option/option_finance_board.md)
- [`option_risk_indicator_sse`](./option/option_risk_indicator_sse.md): 上海证券交易所-产品-股票期权-期权风险指标数据
- [`option_current_day_sse`](./option/option_current_day_sse.md): 上海证券交易所-产品-股票期权-信息披露-当日合约
- [`option_current_day_szse`](./option/option_current_day_szse.md): 深圳证券交易所-期权子网-行情数据-当日合约
- [`option_daily_stats_sse`](./option/option_daily_stats_sse.md): 上海证券交易所-产品-股票期权-每日统计
- [`option_daily_stats_szse`](./option/option_daily_stats_szse.md): 深圳证券交易所-市场数据-期权数据-日度概况
- [`option_cffex_sz50_list_sina`](./option/option_cffex_sz50_list_sina.md): 中金所-上证50指数-所有合约, 返回的第一个合约为主力合约
- [`option_cffex_hs300_list_sina`](./option/option_cffex_hs300_list_sina.md): 中金所-沪深300指数-所有合约, 返回的第一个合约为主力合约
- [`option_cffex_zz1000_list_sina`](./option/option_cffex_zz1000_list_sina.md): 中金所-中证1000指数-所有合约, 返回的第一个合约为主力合约
- [`option_cffex_sz50_spot_sina`](./option/option_cffex_sz50_spot_sina.md): 新浪财经-中金所-上证50指数-指定合约-实时行情
- [`option_cffex_hs300_spot_sina`](./option/option_cffex_hs300_spot_sina.md): 新浪财经-中金所-沪深300指数-指定合约-实时行情
- [`option_cffex_zz1000_spot_sina`](./option/option_cffex_zz1000_spot_sina.md): 新浪财经-中金所-中证1000指数-指定合约-实时行情
- [`option_cffex_sz50_daily_sina`](./option/option_cffex_sz50_daily_sina.md): 中金所-上证50指数-指定合约-日频行情
- [`option_cffex_hs300_daily_sina`](./option/option_cffex_hs300_daily_sina.md): 中金所-沪深300指数-指定合约-日频行情
- [`option_cffex_zz1000_daily_sina`](./option/option_cffex_zz1000_daily_sina.md): 中金所-中证1000指数-指定合约-日频行情
- [`option_sse_list_sina`](./option/option_sse_list_sina.md): 获取期权-上交所-50ETF-合约到期月份列表
- [`option_sse_expire_day_sina`](./option/option_sse_expire_day_sina.md): 获取指定到期月份指定品种的剩余到期时间
- [`option_sse_codes_sina`](./option/option_sse_codes_sina.md): 新浪期权-看涨看跌合约合约的代码
- [`option_sse_spot_price_sina`](./option/option_sse_spot_price_sina.md): 期权实时数据
- [`option_sse_underlying_spot_price_sina`](./option/option_sse_underlying_spot_price_sina.md): 获取期权标的物的实时数据
- [`option_sse_greeks_sina`](./option/option_sse_greeks_sina.md): 新浪财经-期权希腊字母信息表
- [`option_sse_minute_sina`](./option/option_sse_minute_sina.md): 期权行情分钟数据, 只能返还当天的分钟数据
- [`option_sse_daily_sina`](./option/option_sse_daily_sina.md): 期权行情日数据
- [`option_finance_minute_sina`](./option/option_finance_minute_sina.md): 新浪财经-金融期权-股票期权分时行情数据
- [`option_minute_em`](./option/option_minute_em.md): 东方财富网-行情中心-期权市场-分时行情
- [`option_current_em`](./option/option_current_em.md): 东方财富网-行情中心-期权市场
- [`option_lhb_em`](./option/option_lhb_em.md): 东方财富网-数据中心-期货期权-期权龙虎榜单-金融期权
- [`option_value_analysis_em`](./option/option_value_analysis_em.md): 东方财富网-数据中心-特色数据-期权价值分析
- [`option_risk_analysis_em`](./option/option_risk_analysis_em.md): 东方财富网-数据中心-特色数据-期权风险分析
- [`option_premium_analysis_em`](./option/option_premium_analysis_em.md): 东方财富网-数据中心-特色数据-期权折溢价
- [`option_commodity_contract_sina`](./option/option_commodity_contract_sina.md): 新浪财经-商品期权当前在交易的合约
- [`option_commodity_contract_table_sina`](./option/option_commodity_contract_table_sina.md): 新浪财经-商品期权的 T 型报价表
- [`option_commodity_hist_sina`](./option/option_commodity_hist_sina.md): 新浪财经-商品期权的历史行情数据-日频率
- [`option_comm_info`](./option/option_comm_info.md): 九期网-商品期权手续费数据
- [`option_margin`](./option/option_margin.md): 唯爱期货-期权保证金
- [`option_hist_shfe`](./option/option_hist_shfe.md): 上海期货交易所-商品期权数据
- [`option_hist_dce`](./option/option_hist_dce.md): 大连商品交易所-商品期权数据
- [`option_hist_czce`](./option/option_hist_czce.md): 郑州商品交易所-商品期权数据
- [`option_hist_gfex`](./option/option_hist_gfex.md): 广州期货交易所-商品期权数据
- [`option_vol_gfex`](./option/option_vol_gfex.md): 广州期货交易所-商品期权数据-隐含波动参考值
- [`option_czce_hist`](./option/option_czce_hist.md): 郑州商品交易所的商品期权历史行情数据
