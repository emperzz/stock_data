# 09 财务报表

> 抓取时间：2026-10-08
> 源站点：<https://www.zhituapi.com/hsstockapi.html>

## 资产负债表

**API 地址**：

```
https://api.zhituapi.com/hs/fin/balance/股票代码（如000001.SZ）?token=token证书&st=开始时间&et=结束时间
```

**描述**：根据《股票列表》得到的股票代码获取资产负债表，开始时间以及结束时间的格式均为 YYYYMMDD，例如：'20240101'。不设置开始时间和结束时间则为全部数据。

**更新频率**：每日0点

**请求频率限制**：包量版1分钟300次 |体验版、包月版1分钟1000次 | 包年版1分钟3千次 | 至尊版1分钟6千次

**字段说明**：

| 字段名称 | 数据类型 | 字段说明 |
| --- | --- | --- |
| jzrq | string | 截止日期 |
| plrq | string | 披露日期 |
| nbysk | float | 内部应收款 |
| gdzcql | float | 固定资产清理 |
| yffbzk | float | 应付分保账款 |
| jsbfj | float | 结算备付金 |
| ysbf | float | 应收保费 |
| ysfbzk | float | 应收分保账款 |
| ysfbhtzbj | float | 应收分保合同准备金 |
| ysgl | float | 应收股利 |
| ysckts | float | 应收出口退税 |
| ysbtk | float | 应收补贴款 |
| ysbzj | float | 应收保证金 |
| dfy | float | 待摊费用 |
| dclldzcsy | float | 待处理流动资产损益 |
| ynndqdfldzc | float | 一年内到期的非流动资产 |
| cqysk | float | 长期应收款 |
| qtcqtz | float | 其他长期投资 |
| gdzcyz | float | 固定资产原值 |
| gdzcjz | float | 固定资产净值 |
| gdzcjzzbj | float | 固定资产减值准备 |
| scxswzc | float | 生产性生物资产 |
| gyxswzc | float | 公益性生物资产 |
| yqzc | float | 油气资产 |
| kfzc | float | 开发支出 |
| gqfzltq | float | 股权分置流通权 |
| qtfldzc | float | 其他非流动资产 |
| yfsxfyj | float | 应付手续费及佣金 |
| qtjyk | float | 其他应交款 |
| yfbzj | float | 应付保证金 |
| nbyfk | float | 内部应付款 |
| ytfy | float | 预提费用 |
| bxhtzbj | float | 保险合同准备金 |
| dlmmzqk | float | 代理买卖证券款 |
| dlcxzqk | float | 代理承销证券款 |
| gjpjjs | float | 国际票证结算 |
| gnpjjs | float | 国内票证结算 |
| dysr | float | 递延收益 |
| yfdqzq | float | 应付短期债券 |
| cqdysr | float | 长期递延收益 |
| wqddtzss | float | 未确定的投资损失 |
| nfpxjgl | float | 拟分配现金股利 |
| yjfz | float | 预计负债 |
| xsckjtycf | float | 吸收存款及同业存放 |
| yjldfz | float | 预计流动负债 |
| j_kcg | float | 减:库存股 |
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
| ffdkjjd | float | 发放贷款及垫款 |
| kkgsjrzc | float | 可供出售金融资产 |
| cyzdqtz | float | 持有至到期投资 |
| cqgqtz | float | 长期股权投资 |
| tzxfd | float | 投资性房地产 |
| ljzj | float | 累计折旧 |
| gdzc | float | 固定资产 |
| zjgc | float | 在建工程 |
| gcwz | float | 工程物资 |
| cqfz | float | 长期负债 |
| wxzc | float | 无形资产 |
| sy | float | 商誉 |
| cqdtfy | float | 长期待摊费用 |
| dysdszc | float | 递延所得税资产 |
| fldzchj | float | 非流动资产合计 |
| zczj | float | 资产总计 |
| dqjk | float | 短期借款 |
| xzyhyhk | float | 向中央银行借款 |
| crzj | float | 拆入资金 |
| jyxjrfz | float | 交易性金融负债 |
| ysjrfz | float | 衍生金融负债 |
| yfpj | float | 应付票据 |
| yfzk | float | 应付账款 |
| ysk | float | 预收账款 |
| mchgjrzck | float | 卖出回购金融资产款 |
| yfgzxc | float | 应付职工薪酬 |
| yjsf | float | 应交税费 |
| yflx | float | 应付利息 |
| yfgl | float | 应付股利 |
| qtfzk | float | 其他应付款 |
| ynndqdfldfz | float | 一年内到期的非流动负债 |
| qtldfz | float | 其他流动负债 |
| ldfzhj | float | 流动负债合计 |
| cqjk | float | 长期借款 |
| yfzq | float | 应付债券 |
| cqyfk | float | 长期应付款 |
| zxyfk | float | 专项应付款 |
| dysdsfz | float | 递延所得税负债 |
| qtfldfz | float | 其他非流动负债 |
| fldfzhj | float | 非流动负债合计 |
| fzhj | float | 负债合计 |
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

**返回示例**：

```json
"[
```

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
| yysr | float | 营业收入 |
| yzbf | float | 已赚保费 |
| fdczssr | float | 房地产销售收入 |
| yyzcb | float | 营业总成本 |
| fdczscb | float | 房地产销售成本 |
| yffy | float | 研发费用 |
| tbj | float | 退保金 |
| pczjje | float | 赔付支出净额 |
| tqbxhtzbjje | float | 提取保险合同准备金净额 |
| bdhlzc | float | 保单红利支出 |
| fbfy | float | 分保费用 |
| gyjzbdsy | float | 公允价值变动收益 |
| qhsy | float | 期货损益 |
| tgsy | float | 托管收益 |
| btsr | float | 补贴收入 |
| qtywlr | float | 其他业务利润 |
| bhbfzhbqsljlr | float | 被合并方在合并前实现净利润 |
| lxsr | float | 利息收入 |
| sxfjyjsr | float | 手续费及佣金收入 |
| sxfjyjzc | float | 手续费及佣金支出 |
| qtywcb | float | 其他业务成本 |
| hdsy | float | 汇兑收益 |
| fldzcczsy | float | 非流动资产处置收益 |
| sdsfy | float | 所得税费用 |
| wqrtzss | float | 未确认投资损失 |
| gsmgsyzzdjlr | float | 归属于母公司所有者的净利润 |
| lxzc | float | 利息支出 |
| qtywsr | float | 其他业务收入 |
| yyzsr | float | 营业总收入 |
| yycb | float | 营业成本 |
| yysjjfj | float | 营业税金及附加 |
| xsfy | float | 销售费用 |
| glfy | float | 管理费用 |
| cwfy | float | 财务费用 |
| zcjzss | float | 资产减值损失 |
| tzsy | float | 投资收益 |
| lyqyhhhqydtzsy | float | 联营企业和合营企业的投资收益 |
| yylr | float | 营业利润 |
| ywsr | float | 营业外收入 |
| ywzc | float | 营业外支出 |
| lrze | float | 利润总额 |
| jlr | float | 净利润 |
| jlrhfcjcx | float | 净利润(扣除非经常性损益后) |
| ssgdsy | float | 少数股东损益 |
| jbmgsy | float | 基本每股收益 |
| xsmgsy | float | 稀释每股收益 |
| zhsyz | float | 综合收益总额 |
| gsssgdzhsyz | float | 归属于少数股东的综合收益总额 |
| qtsy | float | 其他收益 |

**返回示例**：

```json
"[
```

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

**字段说明**：

| 字段名称 | 数据类型 | 字段说明 |
| --- | --- | --- |
| jzrq | string | 截止日期 |
| plrq | string | 披露日期 |
| sdydbxbfqdxj | float | 收到原保险合同保费取得的现金 |
| sdzbxywxjjje | float | 收到再保险业务现金净额 |
| bhcjjtkkjzje | float | 保户储金及投资款净增加额 |
| czjyxjrzcjzje | float | 处置交易性金融资产净增加额 |
| sqlxsxfjyjdxj | float | 收取利息、手续费及佣金的现金 |
| hgywzjjzje | float | 回购业务资金净增加额 |
| zfybxhtpfkxdj | float | 支付原保险合同赔付款项的现金 |
| zfbdhldxj | float | 支付保单红利的现金 |
| czfzgsjqtsddxj | float | 处置子公司及其他收到的现金 |
| jszyhdqckssddxj | float | 减少质押和定期存款所收到的现金 |
| tzszfdxj | float | 投资所支付的现金 |
| zydkjzje | float | 质押贷款净增加额 |
| qdfzgsjqtywdwzfdxjje | float | 取得子公司及其他营业单位支付的现金净额 |
| zjzyhdqckszfdxj | float | 增加质押和定期存款所支付的现金 |
| qzfzgsxrxj | float | 其中子公司吸收现金 |
| qz:fzgszfgsssgdglr | float | 其中:子公司支付给少数股东的股利、利润 |
| ssgdsy | float | 少数股东损益 |
| wqrdtzss | float | 未确认的投资损失 |
| dysyzj(j:js) | float | 递延收益增加(减:减少) |
| yjfz | float | 预计负债 |
| jxyyfxmdzj | float | 经营性应付项目的增加 |
| ywgwswjskdjs(j:zj) | float | 已完工尚未结算款的减少(减:增加) |
| yjswgwgdjz(j:js) | float | 已结算尚未完工款的增加(减:减少) |
| xssptglwsddxj | float | 销售商品、提供劳务收到的现金 |
| khckhtyckxkjzje | float | 客户存款和同业存放款项净增加额 |
| xzyhyhkjzje | float | 向中央银行借款净增加额(万元) |
| xtjrgjqjcrzjjzje | float | 向其他金融机构拆入资金净增加额 |
| sddsfyfh | float | 收到的税费与返还 |
| tzzfdxj | float | 投资支付的现金 |
| sdqtyjyghdxj | float | 收到的其他与经营活动有关的现金 |
| jyhdxjlrxj | float | 经营活动现金流入小计 |
| gmspjslwzfdxj | float | 购买商品、接受劳务支付的现金 |
| khdkjdknzje | float | 客户贷款及垫款净增加额 |
| cfzyxhytckxkjzje | float | 存放中央银行和同业款项净增加额 |
| zflxsxfjyjdxj | float | 支付利息、手续费及佣金的现金 |
| zfgzyjwzgzfdxj | float | 支付给职工以及为职工支付的现金 |
| zfdgxsf | float | 支付的各项税费 |
| zfqtyjyghdxj | float | 支付其他与经营活动有关的现金 |
| jyhdxjlcxj | float | 经营活动现金流出小计 |
| jyhdcsdxjlje | float | 经营活动产生的现金流量净额 |
| shtzssddxj | float | 收回投资所收到的现金 |
| qdtzsysddxj | float | 取得投资收益所收到的现金 |
| czgdzcwxzhqtqctzssddxj | float | 处置固定资产、无形资产和其他长期投资收到的现金 |
| sdqtytzghdxj | float | 收到的其他与投资活动有关的现金 |
| tzhdxjlrxj | float | 投资活动现金流入小计 |
| gjgdzcwxzhqtqctzzfdxj | float | 购建固定资产、无形资产和其他长期投资支付的现金 |
| tzhdxjlcxj | float | 投资活动现金流出小计 |
| tzhdcsdxjlxj | float | 投资活动产生的现金流量净额 |
| xstzsdj | float | 吸收投资收到的现金 |
| qdjkjddxj | float | 取得借款收到的现金 |
| fxzjsddxj | float | 发行债券收到的现金 |
| sdqtczghdxj | float | 收到其他与筹资活动有关的现金 |
| czhdxjlrxj | float | 筹资活动现金流入小计 |
| chzwzfxj | float | 偿还债务支付现金 |
| fpglrlhcllxzfdxj | float | 分配股利、利润或偿付利息支付的现金 |
| zfqtczdxj | float | 支付其他与筹资的现金 |
| czhdxjlcxj | float | 筹资活动现金流出小计 |
| czhdcsdxjlxj | float | 筹资活动产生的现金流量净额 |
| hlbddxjdxy | float | 汇率变动对现金的影响 |
| xjxjdhwjzje | float | 现金及现金等价物净增加额 |
| qcxjjxjdhwye | float | 期初现金及现金等价物余额 |
| qmxjjxjdhwye | float | 期末现金及现金等价物余额 |
| jlr | float | 净利润 |
| zcjzzb | float | 资产减值准备 |
| gdzczjyqzcshscxwzczj | float | 固定资产折旧、油气资产折耗、生产性物资折旧 |
| wxzctx | float | 无形资产摊销 |
| cqdtfytx | float | 长期待摊费用摊销 |
| dtfydjs | float | 待摊费用的减少 |
| ytfydzj | float | 预提费用的增加 |
| czgdzcwxzhqtqctzss | float | 处置固定资产、无形资产和其他长期资产的损失 |
| gdzcgbss | float | 固定资产报废损失 |
| gyjzbds | float | 公允价值变动损失 |
| cwfy | float | 财务费用 |
| tzss | float | 投资损失 |
| dysdszcjs | float | 递延所得税资产减少 |
| dysdsfzzj | float | 递延所得税负债增加 |
| chdjs | float | 存货的减少 |
| jxyysxmdjs | float | 经营性应收项目的减少 |
| qt | float | 其他 |
| jyhdcsdxjlxj | float | 经营活动产生现金流量净额 |
| zwzwzb | float | 债务转为资本 |
| ynndqdkzhgzq | float | 一年内到期的可转换公司债券 |
| rzrgdzc | float | 融资租入固定资产 |
| xjdqmye | float | 现金的期末余额 |
| xjdqcye | float | 现金的期初余额 |
| xjdhwdqmye | float | 现金等价物的期末余额 |
| xjdhwdqcye | float | 现金等价物的期初余额 |
| xjxjdhwdjzje | float | 现金及现金等价物的净增加额 |

**返回示例**：

```json
"[
```

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
| mgzbgjj | float | 每股资本公积金 |
| kfmgsy | float | 扣非每股收益 |
| jzcsyl | float | 净资产收益率 |
| xsmlv | float | 销售毛利率 |
| zyyrsrzz | float | 主营收入同比增长 |
| jlrzz | float | 净利润同比增长 |
| gsmgsyzzdjlrzz | float | 归属于母公司所有者的净利润同比增长 |
| kfjlrzz | float | 扣非净利润同比增长 |
| yyzsrgdhbzz | float | 营业总收入滚动环比增长 |
| sljlrjqhbzz | float | 归属净利润滚动环比增长 |
| kfjlrgdhbzz | float | 扣非净利润滚动环比增长 |
| jqjzcsyl | float | 加权净资产收益率 |
| tbjzcsyl | float | 摊薄净资产收益率 |
| tbzzcsyl | float | 摊薄总资产收益率 |
| mlv | float | 毛利率 |
| jlv | float | 净利率 |
| sjslv | float | 实际税率 |
| yskyysr | float | 预收款营业收入 |
| xsxjlyysr | float | 销售现金流营业收入 |
| zcfzl | float | 资产负债比率 |
| chzzl | float | 存货周转率 |
| jzrq | string | 截止日期 |
| plrq | string | 披露日期 |
| mgjyhdxjl | float | 每股经营活动现金流量 |
| mgjzc | float | 每股净资产 |
| jbmgsy | float | 基本每股收益 |
| xsmgsy | float | 稀释每股收益 |
| mgwfplr | float | 每股未分配利润 |

**返回示例**：

```json
"[
```

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

**返回示例**：

```json
"[
```

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

**返回示例**：

```json
"[
```

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

**返回示例**：

```json
"[
```

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

**返回示例**：

```json
"[
```

**Python 接入示例**：

```python
import requests
url = "https://api.zhituapi.com/hs/fin/hm/股票代码（如000001.SZ）?token=token证书&st=开始时间&et=结束时间"
response = requests.get(url)
data = response.json()
print(data)
```

