# 14 沪深数据 API（四）：可转债

> 抓取时间：2026-10-08
> 源站点：<https://www.zhituapi.com/hsdataapi.html>
> 上游分类「可转债」。

## 可转债

### 可转债一览

**API 地址**：

```
https://api.zhituapi.com/kzz/list?token=您的token
```

**描述**：可转债一览：含转债代码/名称、正股信息、转股价/溢价率、发行与评级等基础档案。

**更新频率**：每个交易日盘后（采集任务调度）

**请求频率限制**：包量版1分钟300次 | 包月版、体验版1分钟1千次| 包年版1分钟3千次 | 至尊版1分钟6千次

**字段说明**：

| 字段名称 | 数据类型 | 字段说明 |
| --- | --- | --- |
| dm | string | 可转债代码 |
| mc | string | 可转债简称 |
| sg_t | string | 申购日期 |
| sgdm | string | 申购代码 |
| sgsx | number | 申购上限（万元） |
| zgdm | string | 正股代码 |
| zgmc | string | 正股简称 |
| zgsj | number | 正股价格 |
| zgjg | number | 转股价格 |
| zgjz | number | 转股价值 |
| zxj | number | 转债现价 |
| yjl | number | 转股溢价率% |
| gqdjr | string | 原股东配售股权登记日 |
| mgpse | string | 每股配售额 |
| fxgm | number | 发行规模（亿元） |
| zqh | string | 中签号发布日 |
| zql | number | 中签率% |
| sssj | string | 上市时间 |
| pj | string | 信用评级 |

**返回示例**：

```json
[{"dm":"123281","mc":"中仑转债","sg_t":"2026-08-06 00:00:00","sgdm":"371565","sgsx":null,"zgdm":"301565","zgmc":"中仑发债","zgsj":19.8,"zgjg":20.28,"zgjz":97.6331,"zxj":null,"yjl":2.42,"gqdjr":null,"mgpse":100,"fxgm":10.68,"zqh":"2026-08-10 00:00:00","zql":null,"sssj":null,"pj":"AA-"},{"dm":"111026","mc":"派克转债","sg_t":"2026-08-06 00:00:00","sgdm":"713123","sgsx":null,"zgdm":"605123","zgmc":"派克发债","zgsj":78.17,"zgjg":81.8,"zgjz":95.5623,"zxj":null,"yjl":4.64,"gqdjr":null,"mgpse":100,"fxgm":15.8,"zqh":"2026-08-10 00:00:00","zql":null,"sssj":null,"pj":"AA"}]
```

**Python 接入示例**：

```python
import requests
url = "https://api.zhituapi.com/kzz/list?token=您的token"
response = requests.get(url)
data = response.json()
print(data)
```

### 可转债比价表

**API 地址**：

```
https://api.zhituapi.com/kzz/comparison?token=您的token
```

**描述**：可转债比价表：转债与正股行情对比，含溢价率、纯债价值、回售/强赎触发价等。

**更新频率**：每个交易日盘后（采集任务调度）

**请求频率限制**：包量版1分钟300次 | 包月版、体验版1分钟1千次| 包年版1分钟3千次 | 至尊版1分钟6千次

**字段说明**：

| 字段名称 | 数据类型 | 字段说明 |
| --- | --- | --- |
| xh | number | 序号 |
| dm | string | 转债代码 |
| mc | string | 转债名称 |
| zxj | number | 转债最新价 |
| zdf | number | 转债涨跌幅% |
| zgdm | string | 正股代码 |
| zgmc | string | 正股名称 |
| zgzxj | number | 正股最新价 |
| zgzdf | number | 正股涨跌幅% |
| zgjg | number | 转股价 |
| zgjz | number | 转股价值 |
| yjl | number | 转股溢价率% |
| czyjl | number | 纯债溢价率% |
| hscfj | number | 回售触发价 |
| qscfj | number | 强赎触发价 |
| dqshj | number | 到期赎回价 |
| czjz | number | 纯债价值 |
| kszgr | string | 开始转股日 |
| ssrq | string | 上市日期 |
| sgrq | string | 申购日期 |

**返回示例**：

```json
[{"xh":1,"dm":"123281","mc":"中仑转债","zxj":null,"zdf":null,"zgdm":"301565","zgmc":"中仑新材","zgzxj":19.8,"zgzdf":-5.22,"zgjg":20.28,"zgjz":97.6331,"yjl":2.42,"czyjl":0.0,"hscfj":14.2,"qscfj":26.36,"dqshj":110.0,"czjz":null,"kszgr":"2027-02-12","ssrq":"2026-08-06","sgrq":null},{"xh":2,"dm":"118076","mc":"先锋转债","zxj":null,"zdf":null,"zgdm":"688605","zgmc":"先锋精科","zgzxj":72.98,"zgzdf":0.9,"zgjg":86.4,"zgjz":84.4676,"yjl":18.39,"czyjl":0.0,"hscfj":60.48,"qscfj":112.32,"dqshj":110.0,"czjz":null,"kszgr":"2027-02-12","ssrq":"2026-08-06","sgrq":null}]
```

**Python 接入示例**：

```python
import requests
url = "https://api.zhituapi.com/kzz/comparison?token=您的token"
response = requests.get(url)
data = response.json()
print(data)
```

### 可转债实时行情

**API 地址**：

```
https://api.zhituapi.com/kzz/spot?token=您的token
```

**描述**：可转债实时行情：最新价、涨跌幅、买卖盘、开高低、成交量额等。

**更新频率**：每个交易日盘后（采集任务调度）

**请求频率限制**：包量版1分钟300次 | 包月版、体验版1分钟1千次| 包年版1分钟3千次 | 至尊版1分钟6千次

**字段说明**：

| 字段名称 | 数据类型 | 字段说明 |
| --- | --- | --- |
| symbol | string | 带市场前缀代码，如 sh113052 |
| code | string | 纯数字代码 |
| name | string | 名称 |
| trade | number | 最新价 |
| pricechange | number | 涨跌额 |
| changepercent | number | 涨跌幅% |
| buy | number | 买一价 |
| sell | number | 卖一价 |
| settlement | number | 昨收 |
| open | number | 开盘 |
| high | number | 最高 |
| low | number | 最低 |
| volume | number | 成交量 |
| amount | number | 成交额 |
| ticktime | string | 行情时间 HH:MM:SS |

**返回示例**：

```json
[{"symbol":"sh113708","code":"113708","name":"N曙26转","trade":130.0,"pricechange":30.0,"changepercent":30.0,"buy":4.0,"sell":10400000000.0,"settlement":100.0,"open":130.0,"high":130.0,"low":130.0,"volume":123963.0,"amount":161151900.0,"ticktime":"-"},{"symbol":"sh110102","code":"110102","name":"江农转债","trade":177.425,"pricechange":20.125,"changepercent":12.79,"buy":4.0,"sell":2102486250.0,"settlement":157.3,"open":170.0,"high":179.195,"low":166.6,"volume":2087019.0,"amount":3640163760.0,"ticktime":"08:00:50"}]
```

**Python 接入示例**：

```python
import requests
url = "https://api.zhituapi.com/kzz/spot?token=您的token"
response = requests.get(url)
data = response.json()
print(data)
```

