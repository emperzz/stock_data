# 03 涨跌股池

> 抓取时间：2026-06-10
> 源站点：<https://www.zhituapi.com/hsstockapi.html>

## 涨停股池

**API 地址**：

```
https://api.zhituapi.com/hs/pool/ztgc/2024-01-10?token=token证书
```

**描述**：根据日期（格式yyyy-MM-dd，从2019-11-28开始到现在的每个交易日）作为参数，得到每天的涨停股票列表，根据封板时间升序。

**更新频率**：交易时间段每10分钟

**请求频率限制**：包量版1分钟300次 |体验版、包月版1分钟1000次 | 包年版1分钟3千次 | 至尊版1分钟6千次

**字段说明**：

| 字段名称 | 数据类型 | 字段说明 |
| --- | --- | --- |
| dm | string | 代码 |
| mc | string | 名称 |
| p | number | 价格（元） |
| zf | number | 涨幅（%） |
| cje | number | 成交额（元） |
| lt | number | 流通市值（元） |
| zsz | number | 总市值（元） |
| hs | number | 换手率（%） |
| lbc | number | 连板数 |
| fbt | string | 首次封板时间（HH:mm:ss） |
| lbt | string | 最后封板时间（HH:mm:ss） |
| zj | number | 封板资金（元） |
| zbc | number | 炸板次数 |
| tj | string | 涨停统计（x天/y板） |

**返回示例**：

```json
[{"dm":"sz000657","mc":"中钨高新","p":9.33,"zf":10.02,"cje":436073568.0,"lt":11568521214.51,"zsz":13037537784.96,"hs":3.77,"lbc":1,"fbt":"09:25:00","lbt":"09:34:33","zj":98243407,"zbc":3,"tj":"1/1"},{"dm":"sz000715","mc":"中兴商业","p":10.13,"zf":9.99,"cje":608770896.0,"lt":4204552674.22,"zsz":4211232902.72,"hs":14.49,"lbc":3,"fbt":"09:25:00","lbt":"10:12:15","zj":170175926,"zbc":1,"tj":"3/3"},{"dm":"sz002403","mc":"爱仕达","p":12.93,"zf":10.04,"cje":362526448.0,"lt":3955758350.22,"zsz":4404456787.68,"hs":9.16,"lbc":4,"fbt":"09:25:00","lbt":"09:25:00","zj":7605154,"zbc":0,"tj":"4/4"},{"dm":"sz000017","mc":"深中华A","p":5.41,"zf":9.96,"cje":83346703.0,"lt":1639148660.65,"zsz":3728490460.48,"hs":5.14,"lbc":2,"fbt":"09:30:06","lbt":"09:30:06","zj":86225164,"zbc":0,"tj":"2/2"},{"dm":"sh603099","mc":"长白山","p":29.18,"zf":9.99,"cje":1462451424.0,"lt":7781430600.0,"zsz":7781430600.0,"hs":19.22,"lbc":7,"fbt":"09:31:27","lbt":"13:03:12","zj":56022361,"zbc":3,"tj":"7/7"}]
```

**Python 接入示例**：

```python
import requests
url = "https://api.zhituapi.com/hs/pool/ztgc/交易日期?token=token证书"
response = requests.get(url)
data = response.json()
print(data)
```

## 跌停股池

**API 地址**：

```
https://api.zhituapi.com/hs/pool/dtgc/2024-01-10?token=token证书
```

**描述**：根据日期（格式yyyy-MM-dd，从2019-11-28开始到现在的每个交易日）作为参数，得到每天的跌停股票列表，根据封单资金升序。

**更新频率**：交易时间段每10分钟

**请求频率限制**：包量版1分钟300次 |体验版、包月版1分钟1000次 | 包年版1分钟3千次 | 至尊版1分钟6千次

**字段说明**：

| 字段名称 | 数据类型 | 字段说明 |
| --- | --- | --- |
| dm | string | 代码 |
| mc | string | 名称 |
| p | number | 价格（元） |
| zf | number | 跌幅（%） |
| cje | number | 成交额（元） |
| lt | number | 流通市值（元） |
| zsz | number | 总市值（元） |
| pe | number | 动态市盈率 |
| hs | number | 换手率（%） |
| lbc | number | 连续跌停次数 |
| lbt | string | 最后封板时间（HH:mm:ss） |
| zj | number | 封单资金（元） |
| fba | number | 板上成交额（元） |
| zbc | number | 开板次数 |

**返回示例**：

```json
[{"dm":"sz002888","mc":"惠威科技","p":21.42,"zf":-10.0,"cje":541754256.0,"lt":1619363266.92,"zsz":3204682185.6,"pe":2001.86,"hs":31.96,"lbc":1,"lbt":"15:00:00","zj":1939795,"fba":32045816.0,"zbc":2},{"dm":"sz000595","mc":"宝塔实业","p":5.4,"zf":-10.0,"cje":476276416.0,"lt":6146375407.2,"zsz":6148744387.2,"pe":-91.26,"hs":7.45,"lbc":1,"lbt":"14:56:42","zj":2446200,"fba":24075359.0,"zbc":1},{"dm":"sh600329","mc":"达仁堂","p":31.63,"zf":-9.99,"cje":708590896.0,"lt":17898407243.88,"zsz":24360106143.36,"pe":21.29,"hs":3.88,"lbc":1,"lbt":"14:25:54","zj":6901666,"fba":172764313.0,"zbc":24}]
```

**Python 接入示例**：

```python
import requests
url = "https://api.zhituapi.com/hs/pool/dtgc/交易日期?token=token证书"
response = requests.get(url)
data = response.json()
print(data)
```

## 强势股池

**API 地址**：

```
https://api.zhituapi.com/hs/pool/qsgc/2024-01-10?token=token证书
```

**描述**：根据日期（格式yyyy-MM-dd，从2019-11-28开始到现在的每个交易日）作为参数，得到每天的强势股票列表，根据涨幅倒序。

**更新频率**：交易时间段每10分钟

**请求频率限制**：包量版1分钟300次 |体验版、包月版1分钟1000次 | 包年版1分钟3千次 | 至尊版1分钟6千次

**字段说明**：

| 字段名称 | 数据类型 | 字段说明 |
| --- | --- | --- |
| dm | string | 代码 |
| mc | string | 名称 |
| p | number | 价格（元） |
| ztp | number | 涨停价（元） |
| zf | number | 涨幅（%） |
| cje | number | 成交额（元） |
| lt | number | 流通市值（元） |
| zsz | number | 总市值（元） |
| zs | number | 涨速（%） |
| nh | number | 是否新高（0：否，1：是） |
| lb | number | 量比 |
| hs | number | 换手率（%） |
| tj | string | 涨停统计（x天/y板） |

**返回示例**：

```json
[{"dm":"sh603333","mc":"尚纬股份","p":6.67,"ztp":6.67,"zf":10.07,"cje":790927376.0,"lt":4145588998.62,"zsz":4145588985.28,"zs":0.0,"nh":0,"lb":1.22,"hs":20.47,"tj":"9/6"},{"dm":"sz002641","mc":"公元股份","p":5.91,"ztp":5.91,"zf":10.06,"cje":349813616.0,"lt":6704161267.59,"zsz":7263944783.52,"zs":0.0,"nh":1,"lb":4.19,"hs":5.43,"tj":"2/2"},{"dm":"sz002403","mc":"爱仕达","p":12.93,"ztp":12.93,"zf":10.04,"cje":362526448.0,"lt":3955758350.22,"zsz":4404456787.68,"zs":0.0,"nh":1,"lb":1.52,"hs":9.16,"tj":"4/4"},{"dm":"sz000532","mc":"华金资本","p":13.6,"ztp":13.6,"zf":10.03,"cje":670297024.0,"lt":4672276545.6,"zsz":4688033369.6,"zs":0.0,"nh":1,"lb":1.55,"hs":14.68,"tj":"1/1"}]
```

**Python 接入示例**：

```python
import requests
url = "https://api.zhituapi.com/hs/pool/qsgc/交易日期?token=token证书"
response = requests.get(url)
data = response.json()
print(data)
```

## 次新股池

**API 地址**：

```
https://api.zhituapi.com/hs/pool/cxgc/2024-01-10?token=token证书
```

**描述**：根据日期（格式yyyy-MM-dd，从2019-11-28开始到现在的每个交易日）作为参数，得到每天的次新股票列表，根据开板几日升序。

**更新频率**：交易时间段每10分钟

**请求频率限制**：包量版1分钟300次 |体验版、包月版1分钟1000次 | 包年版1分钟3千次 | 至尊版1分钟6千次

**字段说明**：

| 字段名称 | 数据类型 | 字段说明 |
| --- | --- | --- |
| dm | string | 代码 |
| mc | string | 名称 |
| p | number | 价格（元） |
| ztp | number | 涨停价（元，无涨停价为null） |
| zf | number | 涨跌幅（%） |
| cje | number | 成交额（元） |
| lt | number | 流通市值（元） |
| zsz | number | 总市值（元） |
| nh | number | 是否新高（0：否，1：是） |
| hs | number | 转手率（%） |
| tj | string | 涨停统计（x天/y板） |
| kb | number | 开板几日 |
| od | string | 开板日期（yyyyMMdd） |
| ipod | string | 上市日期（yyyyMMdd） |

**返回示例**：

```json
[{"dm":"sh603325","mc":"N博隆","p":84.93,"ztp":null,"zf":17.21,"cje":930814816.0,"lt":1387300295.76,"zsz":5662283100.0,"nh":0,"hs":64.67,"tj":"0/0","kb":1,"od":"20240110","ipod":"20240110"},{"dm":"sh688717","mc":"艾罗能源","p":101.44,"ztp":104.28,"zf":16.73,"cje":882973520.0,"lt":1882666448.96,"zsz":16230400000.0,"nh":0,"hs":49.12,"tj":"0/0","kb":6,"od":"20240103","ipod":"20240103"},{"dm":"sz301566","mc":"达利凯普","p":23.5,"ztp":28.22,"zf":-0.09,"cje":308266928.0,"lt":1074558979.0,"zsz":9400235000.0,"nh":0,"hs":28.39,"tj":"0/0","kb":8,"od":"20231229","ipod":"20231229"}]
```

**Python 接入示例**：

```python
import requests
url = "https://api.zhituapi.com/hs/pool/cxgc/交易日期?token=token证书"
response = requests.get(url)
data = response.json()
print(data)
```

## 炸板股池

**API 地址**：

```
https://api.zhituapi.com/hs/pool/zbgc/2024-01-10?token=token证书
```

**描述**：根据日期（格式yyyy-MM-dd，从2019-11-28开始到现在的每个交易日）作为参数，得到每天的炸板股票列表，根据首次封板时间升序。

**更新频率**：交易时间段每10分钟

**请求频率限制**：包量版1分钟300次 |体验版、包月版1分钟1000次 | 包年版1分钟3千次 | 至尊版1分钟6千次

**字段说明**：

| 字段名称 | 数据类型 | 字段说明 |
| --- | --- | --- |
| dm | string | 代码 |
| mc | string | 名称 |
| p | number | 价格（元） |
| ztp | number | 涨停价（元） |
| zf | number | 振幅（%） |
| cje | number | 成交额（元） |
| lt | number | 流通市值（元） |
| zsz | number | 总市值（元） |
| zs | number | 涨速（%） |
| hs | number | 转手率（%） |
| tj | string | 涨停统计（x天/y板） |
| fbt | string | 首次封板时间（HH:mm:ss） |
| zbc | number | 炸板次数 |
| zdf | number | 涨跌幅 |

**返回示例**：

```json
[{"dm":"sz002611","mc":"东方精工","p":5.14,"ztp":5.79,"zf":-2.28,"cje":955617568.0,"lt":5201681387.8,"zsz":6376778576.0,"hs":17.33,"zs":-0.58,"tj":"2/1","fbt":"09:25:00","zbc":1},{"dm":"sh605080","mc":"浙江自然","p":25.72,"ztp":28.3,"zf":-0.04,"cje":548066192.0,"lt":1210718588.8,"zsz":3641258588.8,"hs":41.77,"zs":-0.04,"tj":"2/1","fbt":"09:30:04","zbc":4},{"dm":"sz003025","mc":"思进智能","p":18.59,"ztp":21.29,"zf":-3.93,"cje":1526952944.0,"lt":4398913869.35,"zsz":4398913869.35,"hs":31.04,"zs":-0.48,"tj":"8/5","fbt":"09:30:15","zbc":6}]
```

**Python 接入示例**：

```python
import requests
url = "https://api.zhituapi.com/hs/pool/zbgc/交易日期?token=token证书"
response = requests.get(url)
data = response.json()
print(data)
```
