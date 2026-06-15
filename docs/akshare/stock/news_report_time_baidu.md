# `news_report_time_baidu`

**描述**: 百度股市通-财报发行

**目标地址**: <https://gushitong.baidu.com/calendar>

**限量**: 单次获取指定 date 的财报发行, 提供港股的财报发行数据


## 输入参数

| 名称 | 类型 | 描述 |
| --- | --- | --- |
| date | str | date="20241107" |

## 输出参数

| 名称 | 类型 | 描述 |
| --- | --- | --- |
| 股票代码 | object |  |
| 交易所 | object |  |
| 股票简称 | object |  |
| 财报期 | object |  |

## 接口示例

```python
import akshare as ak
news_report_time_baidu_df = ak.news_report_time_baidu(date="20241107")
print(news_report_time_baidu_df)
```

## 数据示例

```text
 股票代码 交易所 股票简称 财报期
0 00945 HK 宏利金融-S 2024年三季报
1 00981 HK 中芯国际 2024年三季报
2 01347 HK 华虹半导体 2024年三季报
3 01665 HK 槟杰科达 2024年三季报
4 08476 HK 大洋环球控股 2024年中报
.. ... .. ... ...
95 XRAY US 登士柏西诺德 美东时间发布2024年三季报
96 UPST US Upstart Holdings, Inc. 美东时间盘后发布2024年三季报
97 MUR US 墨菲石油 美东时间发布2024年三季报
98 SG US Sweetgreen, Inc. Class A 美东时间发布2024年三季报
99 STEP US StepStone Group, Inc. Class A 美东时间发布24/25年二季报
[100 rows x 4 columns]
新股数据
打新收益率
```
