# `futures_main_sina`

**描述**: 新浪财经-期货-主力连续合约历史数据

**目标地址**: <https://vip.stock.finance.sina.com.cn/quotes_service/view/qihuohangqing.html#titlePos_0>

**限量**: 单次返回单个期货品种的主力连续合约的日频历史数据


## 输入参数

| 名称 | 类型 | 描述 |
| --- | --- | --- |
| symbol | str | symbol="IF0"; 请参考 新浪连续合约品种一览表, 也可通过 ak.futures_display_main_sina() 获取 |
| start_date | str | start_date="19900101"; |
| end_date | str | end_date="22220101"; |

## 输出参数

| 名称 | 类型 | 描述 |
| --- | --- | --- |
| 日期 | object | - |
| 开盘价 | int64 | - |
| 最高价 | int64 | - |
| 最低价 | int64 | - |
| 收盘价 | int64 | - |
| 成交量 | int64 | 注意单位 |
| 持仓量 | int64 | 注意单位 |
| 动态结算价 | int64 | - |

## 接口示例

```python
import akshare as ak
futures_main_sina_hist = ak.futures_main_sina(symbol="V0", start_date="20200101", end_date="20220101")
print(futures_main_sina_hist)
```

## 数据示例

```text
 日期 开盘价 最高价 最低价 收盘价 成交量 持仓量 动态结算价
0 2020-01-02 6520 6530 6485 6500 54491 230632 6500
1 2020-01-03 6500 6510 6480 6495 72391 229655 6495
2 2020-01-06 6495 6590 6480 6545 174761 237376 6535
3 2020-01-07 6540 6545 6495 6510 86013 230968 6515
4 2020-01-08 6515 6570 6510 6565 115493 235940 6550
.. ... ... ... ... ... ... ... ...
481 2021-12-27 8500 8605 8233 8239 1162292 322968 8413
482 2021-12-28 8239 8510 8224 8483 930875 342271 8362
483 2021-12-29 8500 8520 8413 8484 797016 348914 8468
484 2021-12-30 8480 8503 8372 8478 924423 351493 0
485 2021-12-31 8492 8530 8276 8321 987714 320158 8384
接口示例-新浪主力连续合约品种一览表接口
import akshare as ak
futures_display_main_sina_df = ak.futures_display_main_sina()
print(futures_display_main_sina_df)
数据示例-新浪主力连续合约品种一览表接口
 symbol exchange name
0 V0 dce PVC连续
1 P0 dce 棕榈油连续
2 B0 dce 豆二连续
3 M0 dce 豆粕连续
4 I0 dce 铁矿石连续
.. ... ... ...
58 IF0 cffex 沪深300指数期货连续
59 TF0 cffex 5年期国债期货连续
60 IH0 cffex 上证50指数期货连续
61 IC0 cffex 中证500指数期货连续
62 TS0 cffex 2年期国债期货连续
期货合约详情-新浪
```
