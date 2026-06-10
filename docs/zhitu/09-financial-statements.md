# 09 财务报表

> 抓取时间：2026-06-10
> 源站点：<https://www.zhituapi.com/hsstockapi.html>

## 资产负债表

**API 地址**：

```
https://api.zhituapi.com/hs/fin/balance/股票代码（如000001.SZ）?token=token证书&st=开始时间&et=结束时间
```

**描述**：根据《股票列表》得到的股票代码获取资产负债表，开始时间以及结束时间的格式均为 YYYYMMDD，例如：'20240101'。不设置开始时间和结束时间则为全部数据。

**更新频率**：每日0点

**请求频率限制**：包量版1分钟300次 |体验版、包月版1分钟1000次 | 包年版1分钟3千次 | 至尊版1分钟6千次

**字段说明**（按类别分组）：

**基础字段**：

| 字段名称 | 数据类型 | 字段说明 |
| --- | --- | --- |
| jzrq | string | 截止日期 |
| plrq | string | 披露日期 |

**流动资产**：

| 字段名称 | 数据类型 | 字段说明 |
| --- | --- | --- |
| hbzj | float | 货币资金 |
| cczj | float | 拆出资金 |
| jyxjrzc | float | 交易性金融资产 |
| ysjrzc | float | 衍生金融资产 |
| yspj | float | 应收票据 |
| yszk | float | 应收账款 |
| yfkx | float | 预付款项 |
| yslx | float | 应收利息 |
| qtysk | float | 其他应收款 |
| mrfsjrzck | float | 买入返售金融资产款 |
| gyjzjzbdqjsrdq | float | 以公允价值计量且其变动计入当期损益的金融资产 |
| ch | float | 存货 |
| qtldzc | float | 其他流动资产 |
| ldzchj | float | 流动资产合计 |

**非流动资产**：

| 字段名称 | 数据类型 | 字段说明 |
| --- | --- | --- |
| ffdkjjd | float | 发放贷款及垫款 |
| kkgsjrzc | float | 可供出售金融资产 |
| cyzdqtz | float | 持有至到期投资 |
| cqgqtz | float | 长期股权投资 |
| tzxfd | float | 投资性房地产 |
| gdzc | float | 固定资产 |
| zjgc | float | 在建工程 |
| gcwz | float | 工程物资 |
| wxzc | float | 无形资产 |
| sy | float | 商誉 |
| cqdtfy | float | 长期待摊费用 |
| dysdszc | float | 递延所得税资产 |
| fldzchj | float | 非流动资产合计 |
| zczj | float | 资产总计 |

**流动负债**：

| 字段名称 | 数据类型 | 字段说明 |
| --- | --- | --- |
| dqjk | float | 短期借款 |
| yfpj | float | 应付票据 |
| yfzk | float | 应付账款 |
| ysk | float | 预收账款 |
| yfgzxc | float | 应付职工薪酬 |
| yjsf | float | 应交税费 |
| yflx | float | 应付利息 |
| yfgl | float | 应付股利 |
| qtfzk | float | 其他应付款 |
| ynndqdfldfz | float | 一年内到期的非流动负债 |
| qtldfz | float | 其他流动负债 |
| ldfzhj | float | 流动负债合计 |

**非流动负债**：

| 字段名称 | 数据类型 | 字段说明 |
| --- | --- | --- |
| cqjk | float | 长期借款 |
| yfzq | float | 应付债券 |
| cqyfk | float | 长期应付款 |
| zxyfk | float | 专项应付款 |
| dysdsfz | float | 递延所得税负债 |
| qtfldfz | float | 其他非流动负债 |
| fldfzhj | float | 非流动负债合计 |
| fzhj | float | 负债合计 |

**所有者权益**：

| 字段名称 | 数据类型 | 字段说明 |
| --- | --- | --- |
| sszb | float | 实收资本(或股本) |
| zbgj | float | 资本公积 |
| zxzb | float | 专项储备 |
| ylgj | float | 盈余公积 |
| ybfxzb | float | 一般风险准备 |
| wfplr | float | 未分配利润 |
| wbbzbzhc | float | 外币报表折算差额 |
| gsmgdqsyhj | float | 归属于母公司股东权益合计 |
| ssgdqy | float | 少数股东权益 |
| syzqyhj | float | 所有者权益合计 |
| fzhgdqyzj | float | 负债和股东权益总计 |

> 注：还有更多业务专用字段（如应收保费、应付分保账款等保险业专用字段、内部应收款、内部应付款等），详见源站点。

**Python 接入示例**：

```python
import requests
url = "https://api.zhituapi.com/hs/fin/balance/股票代码（如000001.SZ）?token=token证书&st=开始时间&et=结束时间"
response = requests.get(url)
data = response.json()
print(data)
```

## 利润表

**API 地址**：

```
https://api.zhituapi.com/hs/fin/income/股票代码（如000001.SZ）?token=token证书&st=开始时间&et=结束时间
```

**描述**：根据《股票列表》得到的股票代码获取利润表，开始时间以及结束时间的格式均为 YYYYMMDD，例如：'20240101'。不设置开始时间和结束时间则为全部数据。

**更新频率**：每日0点

**请求频率限制**：包量版1分钟300次 |体验版、包月版1分钟1000次 | 包年版1分钟3千次 | 至尊版1分钟6千次

**字段说明**：

| 字段名称 | 数据类型 | 字段说明 |
| --- | --- | --- |
| jzrq | string | 截止日期 |
| plrq | string | 披露日期 |
| yyzsr | float | 营业总收入 |
| yysr | float | 营业收入 |
| yycb | float | 营业成本 |
| yysjjfj | float | 营业税金及附加 |
| xsfy | float | 销售费用 |
| glfy | float | 管理费用 |
| yffy | float | 研发费用 |
| cwfy | float | 财务费用 |
| zcjzss | float | 资产减值损失 |
| tzsy | float | 投资收益 |
| lyqyhhhqydtzsy | float | 联营企业和合营企业的投资收益 |
| gyjzbdsy | float | 公允价值变动收益 |
| qhsy | float | 期货损益 |
| tgsy | float | 托管收益 |
| btsr | float | 补贴收入 |
| qtywsr | float | 其他业务收入 |
| yylr | float | 营业利润 |
| ywsr | float | 营业外收入 |
| ywzc | float | 营业外支出 |
| lrze | float | 利润总额 |
| sdsfy | float | 所得税费用 |
| jlr | float | 净利润 |
| jlrhfcjcx | float | 净利润(扣除非经常性损益后) |
| gsmgsyzzdjlr | float | 归属于母公司所有者的净利润 |
| ssgdsy | float | 少数股东损益 |
| jbmgsy | float | 基本每股收益 |
| xsmgsy | float | 稀释每股收益 |
| zhsyz | float | 综合收益总额 |
| gsssgdzhsyz | float | 归属于少数股东的综合收益总额 |
| qtsy | float | 其他收益 |
| ... | ... | 保险/房地产行业专用字段（详见源站点） |

**Python 接入示例**：

```python
import requests
url = "https://api.zhituapi.com/hs/fin/income/股票代码（如000001.SZ）?token=token证书&st=开始时间&et=结束时间"
response = requests.get(url)
data = response.json()
print(data)
```

## 现金流量表

**API 地址**：

```
https://api.zhituapi.com/hs/fin/cashflow/股票代码（如000001.SZ）?token=token证书&st=开始时间&et=结束时间
```

**描述**：根据《股票列表》得到的股票代码获取现金流量表，开始时间以及结束时间的格式均为 YYYYMMDD，例如：'20240101'。不设置开始时间和结束时间则为全部数据。

**更新频率**：每日0点

**请求频率限制**：包量版1分钟300次 |体验版、包月版1分钟1000次 | 包年版1分钟3千次 | 至尊版1分钟6千次

**字段说明**（主要字段）：

| 字段名称 | 数据类型 | 字段说明 |
| --- | --- | --- |
| jzrq | string | 截止日期 |
| plrq | string | 披露日期 |
| jlr | float | 净利润 |
| zcjzzb | float | 资产减值准备 |
| gdzczjyqzcshscxwzczj | float | 固定资产折旧、油气资产折耗、生产性物资折旧 |
| wxzctx | float | 无形资产摊销 |
| cqdtfytx | float | 长期待摊费用摊销 |
| cwfy | float | 财务费用 |
| tzss | float | 投资损失 |
| chdjs | float | 存货的减少 |
| jxyysxmdjs | float | 经营性应收项目的减少 |
| jyhdcsdxjlxj | float | 经营活动产生现金流量净额 |
| xssptglwsddxj | float | 销售商品、提供劳务收到的现金 |
| sddgxsf | float | 收到的各项税费 |
| jyhdxjlrxj | float | 经营活动现金流入小计 |
| gmspjslwzfdxj | float | 购买商品、接受劳务支付的现金 |
| zfgzyjwzgzfdxj | float | 支付给职工以及为职工支付的现金 |
| zfdgxsf | float | 支付的各项税费 |
| jyhdxjlcxj | float | 经营活动现金流出小计 |
| shtzssddxj | float | 收回投资所收到的现金 |
| qdtzsysddxj | float | 取得投资收益所收到的现金 |
| tzhdxjlrxj | float | 投资活动现金流入小计 |
| gjgdzcwxzhqtqctzzfdxj | float | 购建固定资产、无形资产和其他长期投资支付的现金 |
| tzhdxjlcxj | float | 投资活动现金流出小计 |
| tzhdcsdxjlxj | float | 投资活动产生的现金流量净额 |
| xstzsdj | float | 吸收投资收到的现金 |
| qdjkjddxj | float | 取得借款收到的现金 |
| fxzjsddxj | float | 发行债券收到的现金 |
| czhdxjlrxj | float | 筹资活动现金流入小计 |
| chzwzfxj | float | 偿还债务支付现金 |
| fpglrlhcllxzfdxj | float | 分配股利、利润或偿付利息支付的现金 |
| czhdxjlcxj | float | 筹资活动现金流出小计 |
| czhdcsdxjlxj | float | 筹资活动产生的现金流量净额 |
| hlbddxjdxy | float | 汇率变动对现金的影响 |
| xjxjdhwjzje | float | 现金及现金等价物净增加额 |
| qcxjjxjdhwye | float | 期初现金及现金等价物余额 |
| qmxjjxjdhwye | float | 期末现金及现金等价物余额 |
| ... | ... | 保险/银行业专用字段（详见源站点） |

**Python 接入示例**：

```python
import requests
url = "https://api.zhituapi.com/hs/fin/cashflow/股票代码（如000001.SZ）?token=token证书&st=开始时间&et=结束时间"
response = requests.get(url)
data = response.json()
print(data)
```

## 财务主要指标

**API 地址**：

```
https://api.zhituapi.com/hs/fin/ratios/股票代码（如000001.SZ）?token=token证书&st=开始时间&et=结束时间
```

**描述**：根据《股票列表》得到的股票代码获取财务主要指标，开始时间以及结束时间的格式均为 YYYYMMDD，例如：'20240101'。不设置开始时间和结束时间则为全部数据。

**更新频率**：每日0点

**请求频率限制**：包量版1分钟300次 |体验版、包月版1分钟1000次 | 包年版1分钟3千次 | 至尊版1分钟6千次

**字段说明**：

| 字段名称 | 数据类型 | 字段说明 |
| --- | --- | --- |
| jzrq | string | 截止日期 |
| plrq | string | 披露日期 |
| jbmgsy | float | 基本每股收益 |
| xsmgsy | float | 稀释每股收益 |
| kfmgsy | float | 扣非每股收益 |
| mgjzc | float | 每股净资产 |
| mgzbgjj | float | 每股资本公积金 |
| mgwfplr | float | 每股未分配利润 |
| mgjyhdxjl | float | 每股经营活动现金流量 |
| jzcsyl | float | 净资产收益率 |
| jqjzcsyl | float | 加权净资产收益率 |
| tbjzcsyl | float | 摊薄净资产收益率 |
| tbzzcsyl | float | 摊薄总资产收益率 |
| xsmlv | float | 销售毛利率 |
| mlv | float | 毛利率 |
| jlv | float | 净利率 |
| sjslv | float | 实际税率 |
| zcfzl | float | 资产负债比率 |
| chzzl | float | 存货周转率 |
| yskyysr | float | 预收款营业收入 |
| xsxjlyysr | float | 销售现金流营业收入 |
| zyyrsrzz | float | 主营收入同比增长 |
| jlrzz | float | 净利润同比增长 |
| gsmgsyzzdjlrzz | float | 归属于母公司所有者的净利润同比增长 |
| kfjlrzz | float | 扣非净利润同比增长 |
| yyzsrgdhbzz | float | 营业总收入滚动环比增长 |
| sljlrjqhbzz | float | 归属净利润滚动环比增长 |
| kfjlrgdhbzz | float | 扣非净利润滚动环比增长 |

**Python 接入示例**：

```python
import requests
url = "https://api.zhituapi.com/hs/fin/ratios/股票代码（如000001.SZ）?token=token证书&st=开始时间&et=结束时间"
response = requests.get(url)
data = response.json()
print(data)
```

## 公司股本表

**API 地址**：

```
https://api.zhituapi.com/hs/fin/capital/股票代码（如000001.SZ）?token=token证书&st=开始时间&et=结束时间
```

**描述**：根据《股票列表》得到的股票代码获取公司股本表，开始时间以及结束时间的格式均为 YYYYMMDD，例如：'20240101'。不设置开始时间和结束时间则为全部数据。

**更新频率**：每日0点

**请求频率限制**：包量版1分钟300次 |体验版、包月版1分钟1000次 | 包年版1分钟3千次 | 至尊版1分钟6千次

**字段说明**：

| 字段名称 | 数据类型 | 字段说明 |
| --- | --- | --- |
| zgb | float | 总股本 |
| ysltag | float | 已上市流通A股 |
| xsltgf | float | 限售流通股份 |
| bdrq | string | 变动日期 |
| ggr | string | 公告日 |

**Python 接入示例**：

```python
import requests
url = "https://api.zhituapi.com/hs/fin/capital/股票代码（如000001.SZ）?token=token证书&st=开始时间&et=结束时间"
response = requests.get(url)
data = response.json()
print(data)
```

## 公司十大股东

**API 地址**：

```
https://api.zhituapi.com/hs/fin/topholder/股票代码（如000001.SZ）?token=token证书&st=开始时间&et=结束时间
```

**描述**：根据《股票列表》得到的股票代码获取公司十大股东，开始时间以及结束时间的格式均为 YYYYMMDD，例如：'20240101'。不设置开始时间和结束时间则为全部数据。

**更新频率**：每日0点

**请求频率限制**：包量版1分钟300次 |体验版、包月版1分钟1000次 | 包年版1分钟3千次 | 至尊版1分钟6千次

**字段说明**：

| 字段名称 | 数据类型 | 字段说明 |
| --- | --- | --- |
| ggrq | string | 公告日期 |
| jzrq | string | 截止日期 |
| gdmc | string | 股东名称 |
| gdlx | string | 股东类型 |
| cgsl | string | 持股数量 |
| bdyy | string | 变动原因 |
| cgbl | string | 持股比例 |
| gfxz | string | 股份性质 |
| cgpm | string | 持股排名 |

**Python 接入示例**：

```python
import requests
url = "https://api.zhituapi.com/hs/fin/topholder/股票代码（如000001.SZ）?token=token证书&st=开始时间&et=结束时间"
response = requests.get(url)
data = response.json()
print(data)
```

## 公司十大流通股东

**API 地址**：

```
https://api.zhituapi.com/hs/fin/flowholder/股票代码（如000001.SZ）?token=token证书&st=开始时间&et=结束时间
```

**描述**：根据《股票列表》得到的股票代码获取公司十大流通股东，开始时间以及结束时间的格式均为 YYYYMMDD，例如：'20240101'。不设置开始时间和结束时间则为全部数据。

**更新频率**：每日0点

**请求频率限制**：包量版1分钟300次 |体验版、包月版1分钟1000次 | 包年版1分钟3千次 | 至尊版1分钟6千次

**字段说明**：

| 字段名称 | 数据类型 | 字段说明 |
| --- | --- | --- |
| ggrq | string | 公告日期 |
| jzrq | string | 截止日期 |
| gdmc | string | 股东名称 |
| gdlx | string | 股东类型 |
| cgsl | string | 持股数量 |
| bdyy | string | 变动原因 |
| cgbl | string | 持股比例 |
| gfxz | string | 股份性质 |
| cgpm | string | 持股排名 |

**Python 接入示例**：

```python
import requests
url = "https://api.zhituapi.com/hs/fin/flowholder/股票代码（如000001.SZ）?token=token证书&st=开始时间&et=结束时间"
response = requests.get(url)
data = response.json()
print(data)
```

## 公司股东数

**API 地址**：

```
https://api.zhituapi.com/hs/fin/hm/股票代码（如000001.SZ）?token=token证书&st=开始时间&et=结束时间
```

**描述**：根据《股票列表》得到的股票代码获取公司股东数，开始时间以及结束时间的格式均为 YYYYMMDD，例如：'20240101'。不设置开始时间和结束时间则为全部数据。

**更新频率**：每日0点

**请求频率限制**：包量版1分钟300次 |体验版、包月版1分钟1000次 | 包年版1分钟3千次 | 至尊版1分钟6千次

**字段说明**：

| 字段名称 | 数据类型 | 字段说明 |
| --- | --- | --- |
| jzrq | string | 截止日期 |
| gdzs | string | 股东总数 |
| agdhs | string | A股东户数 |
| bgdhs | string | B股东户数 |
| hgdhs | string | H股东户数 |
| yltgdhs | string | 已流通股东户数 |
| wltgdhs | string | 未流通股东户数 |

**Python 接入示例**：

```python
import requests
url = "https://api.zhituapi.com/hs/fin/hm/股票代码（如000001.SZ）?token=token证书&st=开始时间&et=结束时间"
response = requests.get(url)
data = response.json()
print(data)
```
