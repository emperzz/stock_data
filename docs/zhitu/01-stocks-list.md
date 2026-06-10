# 01 股票列表

> 抓取时间：2026-06-10
> 源站点：<https://www.zhituapi.com/hsstockapi.html>

## 股票列表

**API 地址**：

```
https://api.zhituapi.com/hs/list/all?token=token证书
```

**描述**：获取基础的股票代码和名称，用于后续接口的参数传入。

**更新频率**：每日16:20

**请求频率限制**：包量版1分钟300次 |体验版、包月版1分钟1000次 | 包年版1分钟3千次 | 至尊版1分钟6千次

**字段说明**：

| 字段名称 | 数据类型 | 字段说明 |
| --- | --- | --- |
| dm | string | 股票代码，如：000001 |
| mc | string | 股票名称，如：平安银行 |
| jys | string | 交易所，"sh"表示上证，"sz"表示深证 |

**返回示例**：

```json
[
    {
        "dm": "688411",
        "mc": "N海博",
        "jys": "sh"
    },
    {
        "dm": "001395",
        "mc": "N亚联",
        "jys": "sz"
    },
    {
        "dm": "300766",
        "mc": "每日互动",
        "jys": "sz"
    },
    {
        "dm": "301248",
        "mc": "杰创智能",
        "jys": "sz"
    },
    {
        "dm": "301299",
        "mc": "卓创资讯",
        "jys": "sz"
    },
    {
        "dm": "300229",
        "mc": "拓尔思",
        "jys": "sz"
    },
    {
        "dm": "300996",
        "mc": "普联软件",
        "jys": "sz"
    },
    {
        "dm": "300697",
        "mc": "电工合金",
        "jys": "sz"
    }    
]
```

**Python 接入示例**：

```python
import requests
url = "https://api.zhituapi.com/hs/list/all?token=token证书"
response = requests.get(url)
data = response.json()
print(data)
```

## 新股日历

**API 地址**：

```
https://api.zhituapi.com/hs/list/new?token=token证书
```

**描述**：新股日历，按申购日期倒序。

**更新频率**：每日17:00

**请求频率限制**：包量版1分钟300次 |体验版、包月版1分钟1000次 | 包年版1分钟3千次 | 至尊版1分钟6千次

**字段说明**：

| 字段名称 | 数据类型 | 字段说明 |
| --- | --- | --- |
| zqdm | string | 股票代码 |
| zqjc | string | 股票简称 |
| sgdm | string | 申购代码 |
| fxsl | number | 发行总数（股） |
| swfxsl | number | 网上发行（股） |
| sgsx | number | 申购上限（股） |
| dgsz | number | 顶格申购需配市值(元) |
| sgrq | string | 申购日期 |
| fxjg | number | 发行价格（元），null为"未知" |
| zxj | number | 最新价（元），null为"未知" |
| srspj | number | 首日收盘价（元），null为"未知" |
| zqgbrq | string | 中签号公布日，null为未知 |
| zqjkrq | string | 中签缴款日，null为未知 |
| ssrq | string | 上市日期，null为未知 |
| syl | number | 发行市盈率，null为"未知" |
| hysyl | number | 行业市盈率 |
| wszql | number | 中签率（%），null为"未知" |
| yzbsl | number | 连续一字板数量，null为"未知" |
| zf | number | 涨幅（%），null为"未知" |
| yqhl | number | 每中一签获利（元），null为"未知" |
| zyyw | string | 主营业务 |

**返回示例**：

```json
[
    {
        "zqdm": "920108",
        "zqjc": "宏海科技",
        "sgdm": "920108",
        "fxsl": 20000000,
        "swfxsl": 19000000,
        "sgsx": 950000,
        "dgsz": 9500000,
        "fxjg": 5.57,
        "zxj": 0,
        "srspj": null,
        "sgrq": "2025-01-17",
        "zqgbrq": null,
        "zqjkrq": null,
        "ssrq": "2025-02-06",
        "syl": 14.99,
        "hysyl": 18.54,
        "wszql": null,
        "yzbsl": null,
        "zf": null,
        "yqhl": null,
        "zyyw": "空调结构件、热交换器、显示类结构件等家用电器配件产品的研发、设计、制造和销售"
    },
    {
        "zqdm": "688411",
        "zqjc": "海博思创",
        "sgdm": "787411",
        "fxsl": 44432537.0,
        "swfxsl": 15126000,
        "sgsx": 11000,
        "dgsz": 110000,
        "fxjg": 19.38,
        "zxj": 0,
        "srspj": null,
        "sgrq": "2025-01-16",
        "zqgbrq": "2025-01-20",
        "zqjkrq": "2025-01-20",
        "ssrq": "2025-01-27",
        "syl": 6.14,
        "hysyl": 18.54,
        "wszql": 0.0329001,
        "yzbsl": 0,
        "zf": null,
        "yqhl": null,
        "zyyw": "电化学储能系统的研发、生产及销售,为传统发电、新能源发电、智能电网、终端电力用户等"源-网-荷"全链条行业客户提供全系列储能系统产品,提供储能系统一站式整体解决方案"
    }
]
```

**Python 接入示例**：

```python
import requests
url = "https://api.zhituapi.com/hs/list/new?token=token证书"
response = requests.get(url)
data = response.json()
print(data)
```

## 风险警示股票列表

**API 地址**：

```
https://api.zhituapi.com/hs/list/fx?token=token证书
```

**描述**：获取风险警示（ST）股票的代码和名称。

**更新频率**：每日16:20

**请求频率限制**：包量版1分钟300次 |体验版、包月版1分钟1000次 | 包年版1分钟3千次 | 至尊版1分钟6千次

**字段说明**：

| 字段名称 | 数据类型 | 字段说明 |
| --- | --- | --- |
| dm | string | 股票代码，如：000001 |
| mc | string | 股票名称，如：平安银行 |
| jys | string | 交易所，"sh"表示上证，"sz"表示深证 |

**返回示例**：

```json
[
    {
        "dm": "300268",
        "mc": "ST佳沃",
        "jys": "sz"
    },
    {
        "dm": "002259",
        "mc": "ST升达",
        "jys": "sz"
    },
    {
        "dm": "600360",
        "mc": "ST华微",
        "jys": "sh"
    },
    {
        "dm": "600234",
        "mc": "*ST科新",
        "jys": "sh"
    },
    {
        "dm": "002005",
        "mc": "ST德豪",
        "jys": "sz"
    },
    {
        "dm": "600289",
        "mc": "*ST信通",
        "jys": "sh"
    },
    {
        "dm": "603557",
        "mc": "ST起步",
        "jys": "sh"
    },
    {
        "dm": "000711",
        "mc": "*ST京蓝",
        "jys": "sz"
    }
]
```

**Python 接入示例**：

```python
import requests
url = "https://api.zhituapi.com/hs/list/fx?token=token证书"
response = requests.get(url)
data = response.json()
print(data)
```

## 概念指数列表（券商数据）

**API 地址**：

```
https://api.zhituapi.com/hs/list/sectors?token=token证书
```

**描述**：获取基础的概念指数代码和名称，用于后续接口的参数传入。

**更新频率**：每日16:20

**请求频率限制**：包量版1分钟300次 |体验版、包月版1分钟1000次 | 包年版1分钟3千次 | 至尊版1分钟6千次

**字段说明**：

| 字段名称 | 数据类型 | 字段说明 |
| --- | --- | --- |
| dm | string | 概念指数代码，如：101076.BKZS |
| mc | string | 概念指数名称，如：GN玻璃 |
| jys | string | 交易所 |

**返回示例**：

```json
[
     {
        "dm": "101075.BKZS",
        "mc": "GNPM2.5",
        "jys": "BK"
    },
    {
        "dm": "101076.BKZS",
        "mc": "GN玻璃",
        "jys": "BK"
    },
    {
        "dm": "101077.BKZS",
        "mc": "GNC2M",
        "jys": "BK"
    }
]
```

**Python 接入示例**：

```python
import requests
url = "https://api.zhituapi.com/hs/list/sectors?token=token证书"
response = requests.get(url)
data = response.json()
print(data)
```

## 一级市场板块列表（券商数据）

**API 地址**：

```
https://api.zhituapi.com/hs/list/primary?token=token证书
```

**描述**：获取基础的一级市场板块名称，用于后续接口的参数传入。

**更新频率**：每日16:20

**请求频率限制**：包量版1分钟300次 |体验版、包月版1分钟1000次 | 包年版1分钟3千次 | 至尊版1分钟6千次

**字段说明**：

| 字段名称 | 数据类型 | 字段说明 |
| --- | --- | --- |
| mc | string | 一级市场名称，如：1000SW1基础化工 |

**返回示例**：

```json
[
    {
        "dm": "688411",
        "mc": "N海博",
        "jys": "sh"
    },
    {
        "dm": "001395",
        "mc": "N亚联",
        "jys": "sz"
    },
    {
        "dm": "300766",
        "mc": "每日互动",
        "jys": "sz"
    },
    {
        "dm": "301248",
        "mc": "杰创智能",
        "jys": "sz"
    },
    {
        "dm": "301299",
        "mc": "卓创资讯",
        "jys": "sz"
    },
    {
        "dm": "300229",
        "mc": "拓尔思",
        "jys": "sz"
    },
    {
        "dm": "300996",
        "mc": "普联软件",
        "jys": "sz"
    },
    {
        "dm": "300697",
        "mc": "电工合金",
        "jys": "sz"
    }    
]
```

**Python 接入示例**：

```python
import requests
url = "https://api.zhituapi.com/hs/list/primary?token=token证书"
response = requests.get(url)
data = response.json()
print(data)
```

## 板块明细列表（券商数据）

**API 地址**：

```
https://api.zhituapi.com/hs/sectors/板块指数名称（例如：概念指数）?token=Token证书
```

**描述**：依据《一级市场板块列表》获取的一级市场板块名称，获取对应的板块列表。

**更新频率**：每日16:20

**请求频率限制**：包量版1分钟300次 |体验版、包月版1分钟1000次 | 包年版1分钟3千次 | 至尊版1分钟6千次

**字段说明**：

| 字段名称 | 数据类型 | 字段说明 |
| --- | --- | --- |
| dm | string | 板块代码，如：101076.BKZS |
| mc | string | 板块名称，如：GN玻璃 |
| jys | string | 交易所 |

**返回示例**：

```json
[
    {
        "dm": "688411",
        "mc": "N海博",
        "jys": "sh"
    },
    {
        "dm": "001395",
        "mc": "N亚联",
        "jys": "sz"
    },
    {
        "dm": "300766",
        "mc": "每日互动",
        "jys": "sz"
    },
    {
        "dm": "301248",
        "mc": "杰创智能",
        "jys": "sz"
    },
    {
        "dm": "301299",
        "mc": "卓创资讯",
        "jys": "sz"
    },
    {
        "dm": "300229",
        "mc": "拓尔思",
        "jys": "sz"
    },
    {
        "dm": "300996",
        "mc": "普联软件",
        "jys": "sz"
    },
    {
        "dm": "300697",
        "mc": "电工合金",
        "jys": "sz"
    }    
]
```

**Python 接入示例**：

```python
import requests
url = "https://api.zhituapi.com/hs/sectors/板块指数名称（例如：概念指数）?token=Token证书"
response = requests.get(url)
data = response.json()
print(data)
```
