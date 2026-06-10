# 07 基础信息

> 抓取时间：2026-06-10
> 源站点：<https://www.zhituapi.com/hsstockapi.html>

## 股票基础信息

**API 地址**：

```
https://api.zhituapi.com/hs/instrument/股票代码（如000001.SZ）?token=token证书
```

**描述**：依据《股票列表》中的股票代码获取股票的基础信息。

**更新频率**：每日1点

**请求频率限制**：包量版1分钟300次 |体验版、包月版1分钟1000次 | 包年版1分钟3千次 | 至尊版1分钟6千次

**字段说明**：

| 字段名称 | 数据类型 | 字段说明 |
| --- | --- | --- |
| ei | string | 市场代码 |
| ii | string | 股票代码 |
| name | string | 股票名称 |
| od | string | 上市日期(股票IPO日期) |
| pc | float | 前收盘价格 |
| up | float | 当日涨停价 |
| dp | float | 当日跌停价 |
| fv | float | 流通股本 |
| tv | float | 总股本 |
| pk | float | 最小价格变动单位 |
| is | int | 股票停牌状态(<=0:正常交易（-1:复牌）;>=1停牌天数;) |

**Python 接入示例**：

```python
import requests
url = "https://api.zhituapi.com/hs/instrument/股票代码（如000001.SZ）?token=token证书"
response = requests.get(url)
data = response.json()
print(data)
```
