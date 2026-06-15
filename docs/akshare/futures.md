# AKShare 期货 数据字典

共 **54** 个接口。

## 接口索引

- [`futures_fees_info`](./futures/futures_fees_info.md): openctp 期货交易费用参照表
- [`futures_comm_info`](./futures/futures_comm_info.md): 九期网-期货手续费数据
- [`futures_comm_js`](./futures/futures_comm_js.md): 金十财经-期货手续费数据
- [`futures_rule`](./futures/futures_rule.md): 国泰君安期货-交易日历数据表
- [`futures_inventory_99`](./futures/futures_inventory_99.md): 99 期货网-大宗商品库存数据
- [`futures_inventory_em`](./futures/futures_inventory_em.md): 东方财富网-期货数据-库存数据; 近 60 个交易日的期货库存日频率数据
- [`futures_dce_position_rank`](./futures/futures_dce_position_rank.md): 大连商品交易所指定交易日的具体合约的持仓排名
- [`futures_gfex_position_rank`](./futures/futures_gfex_position_rank.md): 广州期货交易所-日成交持仓排名
- [`futures_warehouse_receipt_czce`](./futures/futures_warehouse_receipt_czce.md): 郑州商品交易所-交易数据-仓单日报
- [`futures_warehouse_receipt_dce`](./futures/futures_warehouse_receipt_dce.md): 大连商品交易所-行情数据-统计数据-日统计-仓单日报
- [`futures_shfe_warehouse_receipt`](./futures/futures_shfe_warehouse_receipt.md): 提供上海期货交易所指定交割仓库期货仓单日报
- [`futures_gfex_warehouse_receipt`](./futures/futures_gfex_warehouse_receipt.md): 广州期货交易所-行情数据-仓单日报
- [`futures_to_spot_dce`](./futures/futures_to_spot_dce.md): 大连商品交易所-期转现统计数据
- [`futures_to_spot_czce`](./futures/futures_to_spot_czce.md): 郑州商品交易所-期转现统计数据
- [`futures_to_spot_shfe`](./futures/futures_to_spot_shfe.md): 上海期货交易所-期转现数据
- [`futures_delivery_dce`](./futures/futures_delivery_dce.md): 大连商品交易所-交割统计
- [`futures_delivery_czce`](./futures/futures_delivery_czce.md): 郑州商品交易所-交割统计
- [`futures_delivery_shfe`](./futures/futures_delivery_shfe.md): 上海期货交易所-交割统计
- [`futures_delivery_match_dce`](./futures/futures_delivery_match_dce.md): 大连商品交易所-交割配对
- [`futures_delivery_match_czce`](./futures/futures_delivery_match_czce.md): 郑州商品交易所-交割配对
- [`futures_stock_shfe_js`](./futures/futures_stock_shfe_js.md): 金十财经-上海期货交易所指定交割仓库库存周报
- [`futures_hold_pos_sina`](./futures/futures_hold_pos_sina.md): 新浪财经-期货-成交持仓
- [`futures_spot_sys`](./futures/futures_spot_sys.md): 生意社-商品与期货-现期图
- [`futures_contract_info_shfe`](./futures/futures_contract_info_shfe.md): 上海期货交易所-交易所服务-业务数据-交易参数汇总查询
- [`futures_contract_info_ine`](./futures/futures_contract_info_ine.md): 上海国际能源交易中心-业务指南-交易参数汇总(期货)
- [`futures_contract_info_dce`](./futures/futures_contract_info_dce.md): 大连商品交易所-数据中心-业务数据-交易参数-合约信息
- [`futures_contract_info_czce`](./futures/futures_contract_info_czce.md): 郑州商品交易所-交易数据-参考数据
- [`futures_contract_info_gfex`](./futures/futures_contract_info_gfex.md): 广州期货交易所-业务/服务-合约信息
- [`futures_contract_info_cffex`](./futures/futures_contract_info_cffex.md): 中国金融期货交易所-数据-交易参数
- [`futures_zh_spot`](./futures/futures_zh_spot.md): 新浪财经-期货页面的实时行情数据
- [`futures_zh_realtime`](./futures/futures_zh_realtime.md): 新浪财经-期货实时行情数据
- [`futures_zh_minute_sina`](./futures/futures_zh_minute_sina.md): 新浪财经-期货-分时数据
- [`futures_hist_em`](./futures/futures_hist_em.md): 东方财富网-期货行情-行情数据；其中 weekly, monthly 获取的成交额和持仓量未经验证
- [`futures_zh_daily_sina`](./futures/futures_zh_daily_sina.md): 新浪财经-期货-日频数据
- [`get_futures_daily`](./futures/get_futures_daily.md): 提供各交易所各品种的网站的历史行情数据, 其中 20040625, 20070604, 20081226, 200901…
- [`futures_settle`](./futures/futures_settle.md): 提供各交易所的结算参数数据，包括保证金、手续费、涨跌停板等参数
- [`futures_hq_subscribe_exchange_symbol`](./futures/futures_hq_subscribe_exchange_symbol.md): 新浪财经-外盘商品期货品种代码表数据
- [`futures_foreign_commodity_realtime`](./futures/futures_foreign_commodity_realtime.md): 新浪财经-外盘商品期货数据
- [`futures_global_spot_em`](./futures/futures_global_spot_em.md): 东方财富网-行情中心-期货市场-国际期货-实时行情数据
- [`futures_global_hist_em`](./futures/futures_global_hist_em.md): 东方财富网-行情中心-期货市场-国际期货-历史行情数据
- [`futures_foreign_hist`](./futures/futures_foreign_hist.md): 新浪财经-期货外盘历史行情数据
- [`futures_foreign_detail`](./futures/futures_foreign_detail.md): 新浪财经-期货外盘期货合约详情
- [`futures_settlement_price_sgx`](./futures/futures_settlement_price_sgx.md): 新加坡交易所-衍生品-历史数据-历史结算价格; 数据于下个工作日新加坡时间下午 2 点起提供
- [`futures_main_sina`](./futures/futures_main_sina.md): 新浪财经-期货-主力连续合约历史数据
- [`futures_contract_detail`](./futures/futures_contract_detail.md): 新浪财经-期货-期货合约详情数据
- [`futures_contract_detail_em`](./futures/futures_contract_detail_em.md): 东方财富-期货-期货合约详情数据
- [`futures_index_ccidx`](./futures/futures_index_ccidx.md): 中证商品指数
- [`futures_spot_stock`](./futures/futures_spot_stock.md): 东方财富网-数据中心-现货与股票
- [`futures_comex_inventory`](./futures/futures_comex_inventory.md): 东方财富网-数据中心-期货期权-COMEX 库存数据
- [`futures_hog_core`](./futures/futures_hog_core.md): 玄田数据-核心数据
- [`futures_hog_cost`](./futures/futures_hog_cost.md): 玄田数据-成本维度
- [`futures_hog_supply`](./futures/futures_hog_supply.md): 玄田数据-供应维度
- [`index_hog_spot_price`](./futures/index_hog_spot_price.md): 行情宝-生猪市场价格指数
- [`futures_news_shmet`](./futures/futures_news_shmet.md): 上海金属网-快讯
