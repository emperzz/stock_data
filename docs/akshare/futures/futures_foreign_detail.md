# `futures_foreign_detail`

**描述**: 新浪财经-期货外盘期货合约详情

**目标地址**: <https://finance.sina.com.cn/futuremarket/>

**限量**: 单次返回指定品种的合约详情数据


## 输入参数

| 名称 | 类型 | 描述 |
| --- | --- | --- |
| symbol | str | symbol="ZSD"; 外盘期货的 symbol 可以通过 hf_subscribe_exchange_symbol 获取 |

## 输出参数

| 名称 | 类型 | 描述 |
| --- | --- | --- |
| 交易品种 | str | - |
| 最小变动价位 | str | - |
| 交易时间 | str | - |
| 交易代码 | str | - |
| 交易单位 | str | - |
| 涨跌停板幅度 | str | - |
| 交割品级 | str | - |
| 上市交易所 | str | - |
| 报价单位 | str | - |
| 合约交割月份 | str | - |
| 交割地点 | str | - |
| 附加信息 | str | - |

## 接口示例

```python
import akshare as ak
futures_foreign_detail_df = ak.futures_foreign_detail(symbol="ZSD")
print(futures_foreign_detail_df)
```

## 数据示例

```text
 0 1 ... 4 5
0 交易品种 伦敦锌(CFD差价合约并非期货) ... 报价单位 美元/吨
1 最小变动价位 电话交易：0.5美元/吨 电子盘：0.25美元/吨 ... 合约交割月份 LME三个月期货合约是连续合约，每日都有交割
2 交易时间 LME Select北京时间（夏令时）08:00-02:00 ... 交割地点 NaN
3 交易代码 ZSD ... 附加信息 NaN
新加坡交易所期货
```
