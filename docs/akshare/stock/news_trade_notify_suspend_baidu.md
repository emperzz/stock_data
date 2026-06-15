# `news_trade_notify_suspend_baidu`

**描述**: 百度股市通-交易提醒-停复牌

**目标地址**: <https://gushitong.baidu.com/calendar>

**限量**: 单次获取指定 date 的停复牌数据, 提供港股的停复牌数据


## 输入参数

| 名称 | 类型 | 描述 |
| --- | --- | --- |
| date | str | date="20241107" |

## 输出参数

| 名称 | 类型 | 描述 |
| --- | --- | --- |
| 股票代码 | object |  |
| 股票简称 | object |  |
| 交易所 | object |  |
| 停牌时间 | object |  |
| 复牌时间 | object |  |
| 停牌事项说明 | object |  |

## 接口示例

```python
import akshare as ak
news_trade_notify_suspend_baidu_df = ak.news_trade_notify_suspend_baidu(date="20241107")
print(news_trade_notify_suspend_baidu_df)
```

## 数据示例

```text
 股票代码 股票简称 ... 复牌时间 停牌事项说明
0 002602 世纪华通 ... 2024-11-08 实行其他风险警示
1 300473 德尔股份 ... NaT 重大事项
2 833534 神玥软件 ... NaT 全国股转公司认定的其他重大事项，具体内容为：公司股价出现较大波动，停牌核查。
3 836226 卡友信息 ... NaT 做市商不足两家。
4 870215 ST未来能 ... NaT 主办券商单方解除持续督导且公司无其他主办券商承接持续督导工作。
5 872577 浏经水务 ... NaT 向全国股转公司主动申请终止挂牌。
6 02288 宏基资本 ... NaT 将于今天（7/11/2024）上午九时正起短暂停止买卖。
[7 rows x 6 columns]
分红派息
```
