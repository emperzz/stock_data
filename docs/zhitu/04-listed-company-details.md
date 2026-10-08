# 04 上市公司详情

> 抓取时间：2026-10-08
> 源站点：<https://www.zhituapi.com/hsstockapi.html>

## 公司简介

**API 地址**：

```
https://api.zhituapi.com/hs/gs/gsjj/股票代码?token=token证书
```

**描述**：根据《股票列表》得到的股票代码获取上市公司的简介。包括公司基本信息，概念以及发行信息等。

**更新频率**：每日03:30

**请求频率限制**：包量版1分钟300次 |体验版、包月版1分钟1000次 | 包年版1分钟3千次 | 至尊版1分钟6千次

**字段说明**：

| 字段名称 | 数据类型 | 字段说明 |
| --- | --- | --- |
| name | string | 公司名称 |
| ename | string | 公司英文名称 |
| market | string | 上市市场 |
| idea | string | 概念及板块，多个概念由英文逗号分隔 |
| ldate | string | 上市日期，格式yyyy-MM-dd |
| sprice | string | 发行价格（元） |
| principal | string | 主承销商 |
| rdate | string | 成立日期 |
| rprice | string | 注册资本 |
| instype | string | 机构类型 |
| organ | string | 组织形式 |
| secre | string | 董事会秘书 |
| phone | string | 公司电话 |
| sphone | string | 董秘电话 |
| fax | string | 公司传真 |
| sfax | string | 董秘传真 |
| email | string | 公司电子邮箱 |
| semail | string | 董秘电子邮箱 |
| site | string | 公司网站 |
| post | string | 邮政编码 |
| infosite | string | 信息披露网址 |
| oname | string | 证券简称更名历史 |
| addr | string | 注册地址 |
| oaddr | string | 办公地址 |
| desc | string | 公司简介 |
| bscope | string | 经营范围 |
| printype | string | 承销方式 |
| referrer | string | 上市推荐人 |
| putype | string | 发行方式 |
| pe | string | 发行市盈率（按发行后总股本） |
| firgu | string | 首发前总股本（万股） |
| lastgu | string | 首发后总股本（万股） |
| realgu | string | 实际发行量（万股） |
| planm | string | 预计募集资金（万元） |
| realm | string | 实际募集资金合计（万元） |
| pubfee | string | 发行费用总额（万元） |
| collect | string | 募集资金净额（万元） |
| signfee | string | 承销费用（万元） |
| pdate | string | 招股公告日 |

**返回示例**：

```json
{"name":"平安银行股份有限公司","ename":"Ping An Bank Co.,Ltd.","market":"深圳证券交易所","ldate":"1991-04-03","sprice":"40.00","principal":"","rdate":"1987-12-22","rprice":"1940590万元(CNY)","instype":"股份制商业银行","organ":"民营企业","secre":"周强","phone":"0755-82080387","sphone":"0755-82080387","fax":"0755-82080386","sfax":"0755-82080386","email":"PAB_db@pingan.com.cn","semail":"PAB_db@pingan.com.cn","site":"http://www.bank.pingan.com","post":"518001,518033","infosite":"","oname":"S深发展A 深发展A 平安银行","addr":"广东省深圳市罗湖区深南东路5047号","oaddr":"广东省深圳市罗湖区深南东路5047号,中国广东省深圳市福田区益田路5023号平安金融中心B座","desc":"本行系在对深圳经济特区原六家信用社改组的同时经中国人民银行深圳经济特区分行[87]深人融管字第93号文批准向社会公众发行股票,并经中国人民银行银复[1987]365号文批准设立的股份有限公司。本行在深圳市工商行政管理局注册登记,取得营业执照,营业执照注册号为:440301103098545。本行于1987年5月9日经中国人民银行深圳经济特区分行批准,首次向境内社会公众发行人民币普通股39.7万股。于1988年4月在深圳经济特区证券公司挂牌柜台交易。并于1991年4月3日在深圳证券交易所上市。 自2012年7月27日起,公司名称由\"深圳发展银行股份有限公司\"变更为\"平安银行股份有限公司\",英文名称由\"Shenzhen Development Bank Co.,Ltd.\"变更为\"Ping An Bank Co.,Ltd.\"。","bscope":"人民币、外币存贷款;国际、国内结算;票据贴现;外汇买卖;提供担保及信用证服务;提供保管箱服务等。","idea":"本月解禁,外资背景,证金汇金,区块链,融资融券,券商重仓,保险重仓,深圳本地,大盘,MSCI中国,基金重仓,社保重仓","printype":"代销","referrer":"--","putype":"其他","pe":"--","firgu":"--","lastgu":"--","realgu":"67.50","planm":"--","realm":"--","pubfee":"--","collect":"--","signfee":"--","pdate":"1989-03-10"}]
```

**Python 接入示例**：

```python
import requests
url = "https://api.zhituapi.com/hs/gs/gsjj/股票代码?token=token证书"
response = requests.get(url)
data = response.json()
print(data)
```

## 所属指数

**API 地址**：

```
https://api.zhituapi.com/hs/gs/sszs/股票代码?token=token证书
```

**描述**：根据《股票列表》得到的股票代码获取上市公司的所属指数。

**更新频率**：每日03:30

**请求频率限制**：包量版1分钟300次 |体验版、包月版1分钟1000次 | 包年版1分钟3千次 | 至尊版1分钟6千次

**字段说明**：

| 字段名称 | 数据类型 | 字段说明 |
| --- | --- | --- |
| mc | string | 指数名称 |
| dm | string | 指数代码 |
| ind | string | 进入日期yyyy-MM-dd |
| outd | string | 退出日期yyyy-MM-dd |

**返回示例**：

```json
[{"mc":"金融业","dm":"825500","ind":"","outd":""},{"mc":"中信大盘","dm":"816100","ind":"","outd":""},{"mc":"大盘成长","dm":"816120","ind":"","outd":""},{"mc":"中标300","dm":"816000","ind":"2004-01-02","outd":""},{"mc":"深证综指","dm":"399106","ind":"1991-04-03","outd":""},{"mc":"深证A指","dm":"399107","ind":"1992-10-04","outd":""},{"mc":"成份A指","dm":"399002","ind":"1995-01-23","outd":""},{"mc":"金融指数","dm":"399190","ind":"2001-07-02","outd":""},{"mc":"巨潮100","dm":"399313","ind":"2004-11-01","outd":""},{"mc":"沪深300","dm":"399300","ind":"2005-04-08","outd":""},{"mc":"道中指数","dm":"DWJ001","ind":"2005-04-01","outd":""},{"mc":"道中88","dm":"DWJ004","ind":"2005-04-01","outd":""},{"mc":"道深指数","dm":"DWJ003","ind":"2005-04-01","outd":""},{"mc":"道财600","dm":"DWJ005","ind":"2005-04-01","outd":""},{"mc":"道财金融","dm":"DWJ010","ind":"2005-09-08","outd":""},{"mc":"中证100","dm":"000903","ind":"2006-05-29","outd":"2022-06-13"},{"mc":"中证100","dm":"399903","ind":"2006-05-29","outd":"2022-06-13"},{"mc":"巨潮40","dm":"399310","ind":"","outd":"2021-06-15"},{"mc":"巨潮300","dm":"399312","ind":"","outd":"2021-06-15"},{"mc":"巨潮大盘","dm":"399314","ind":"","outd":""},{"mc":"巨潮A指","dm":"399317","ind":"1900-01-01","outd":""},{"mc":"巨潮1000","dm":"399311","ind":"","outd":""},{"mc":"深报指数","dm":"399351","ind":"","outd":""},{"mc":"深报综指","dm":"399352","ind":"","outd":""},{"mc":"深证成长","dm":"399325","ind":"1900-01-01","outd":"2011-01-04"},{"mc":"沪深300全收益","dm":"QSY301","ind":"2005-04-21","outd":""},{"mc":"中证800","dm":"000906","ind":"2005-01-04","outd":""},{"mc":"中证800","dm":"399906","ind":"2005-01-04","outd":""},{"mc":"中证100全收益","dm":"QSY913","ind":"2006-05-29","outd":"2022-06-13"},{"mc":"中证800全收益","dm":"QSY916","ind":"2007-01-15","outd":""},{"mc":"300金融","dm":"000914","ind":"2002-01-04","outd":""},{"mc":"300金融","dm":"399914","ind":"2002-01-04","outd":""},{"mc":"新指数","dm":"399100","ind":"2007-06-20","outd":""},{"mc":"CBN珠三角40","dm":"399356","ind":"2007-07-02","outd":""},{"mc":"巨潮治理","dm":"399322","ind":"2008-01-02","outd":"2020-08-31"},{"mc":"深证治理","dm":"399327","ind":"2008-01-02","outd":""},{"mc":"300成长","dm":"000918","ind":"2008-01-02","outd":"2018-06-11"},{"mc":"300成长","dm":"399918","ind":"2008-01-02","outd":"2018-06-11"},{"mc":"300价值","dm":"000919","ind":"2008-01-02","outd":"2020-06-15"},{"mc":"300价值","dm":"399919","ind":"2008-01-02","outd":""},{"mc":"300R成长","dm":"000920","ind":"2008-01-02","outd":"2018-06-11"},{"mc":"300R成长","dm":"399920","ind":"2008-01-02","outd":""},{"mc":"300R价值","dm":"000921","ind":"2008-01-02","outd":""},{"mc":"300R价值","dm":"399921","ind":"2008-01-02","outd":""},{"mc":"申万300","dm":"801300","ind":"2000-01-04","outd":""},{"mc":"沪深300","dm":"000300","ind":"2005-04-08","outd":""},{"mc":"申万50","dm":"801001","ind":"2008-01-02","outd":"2016-07-01"},{"mc":"申万Ａ指","dm":"801003","ind":"1991-04-03","outd":""},{"mc":"大盘指数","dm":"801811","ind":"2008-01-02","outd":""},{"mc":"低市盈率指数","dm":"801823","ind":"2008-05-05","outd":"2009-05-04"},{"mc":"高价股指数","dm":"801841","ind":"2008-04-01","outd":"2009-01-05"},{"mc":"绩优股指数","dm":"801853","ind":"2008-05-05","outd":"2009-05-04"},{"mc":"基金重仓","dm":"801901","ind":"2008-05-05","outd":""}]
```

**Python 接入示例**：

```python
import requests
url = "https://api.zhituapi.com/hs/gs/sszs/股票代码?token=token证书"
response = requests.get(url)
data = response.json()
print(data)
```

## 历届高管成员

**API 地址**：

```
https://api.zhituapi.com/hs/gs/ljgg/股票代码?token=token证书
```

**描述**：根据《股票列表》得到的股票代码获取上市公司的历届高管成员名单。

**更新频率**：每日03:30

**请求频率限制**：包量版1分钟300次 |体验版、包月版1分钟1000次 | 包年版1分钟3千次 | 至尊版1分钟6千次

**字段说明**：

| 字段名称 | 数据类型 | 字段说明 |
| --- | --- | --- |
| name | string | 姓名 |
| title | string | 职务 |
| sdate | string | 起始日期yyyy-MM-dd |
| edate | string | 终止日期yyyy-MM-dd |

**返回示例**：

```json
[{"name":"杨志群","title":"副行长","sdate":"2019-04-20","edate":"--"},{"name":"项有志","title":"首席财务官","sdate":"2018-01-29","edate":"--"},{"name":"项有志","title":"副行长","sdate":"2020-06-05","edate":"--"},{"name":"周强","title":"董事会秘书","sdate":"2014-10-21","edate":"--"},{"name":"邱伟","title":"纪委书记","sdate":"2015-12-31","edate":"--"},{"name":"邱伟","title":"党委副书记","sdate":"2015-12-31","edate":"--"},{"name":"吴雷鸣","title":"首席风险官","sdate":"2024-04-03","edate":"--"},{"name":"吴雷鸣","title":"行长助理","sdate":"2024-04-03","edate":"--"}]
```

**Python 接入示例**：

```python
import requests
url = "https://api.zhituapi.com/hs/gs/ljgg/股票代码?token=token证书"
response = requests.get(url)
data = response.json()
print(data)
```

## 历届董事会成员

**API 地址**：

```
https://api.zhituapi.com/hs/gs/ljds/股票代码?token=token证书
```

**描述**：根据《股票列表》得到的股票代码获取上市公司的历届董事会成员名单。

**更新频率**：每日03:30

**请求频率限制**：包量版1分钟300次 |体验版、包月版1分钟1000次 | 包年版1分钟3千次 | 至尊版1分钟6千次

**字段说明**：

| 字段名称 | 数据类型 | 字段说明 |
| --- | --- | --- |
| name | string | 姓名 |
| title | string | 职务 |
| sdate | string | 起始日期yyyy-MM-dd |
| edate | string | 终止日期yyyy-MM-dd |

**返回示例**：

```json
[{"name":"谢永林","title":"董事长","sdate":"2022-11-10","edate":"2025-11-09"},{"name":"谢永林","title":"非执行董事","sdate":"2022-11-10","edate":"2025-11-09"},{"name":"陈心颖","title":"非执行董事","sdate":"2022-11-10","edate":"2024-10-08"},{"name":"蔡方方","title":"非执行董事","sdate":"2022-11-10","edate":"2025-11-09"},{"name":"付欣","title":"非执行董事","sdate":"2024-03-06","edate":"2025-11-09"},{"name":"郭建","title":"非执行董事","sdate":"2022-11-10","edate":"2025-11-09"},{"name":"郭晓涛","title":"非执行董事","sdate":"2024-10-08","edate":"2025-11-09"},{"name":"胡跃飞","title":"执行董事","sdate":"2022-11-10","edate":"2023-06-07"},{"name":"杨志群","title":"执行董事","sdate":"2022-11-10","edate":"2025-11-09"},{"name":"郭世邦","title":"执行董事","sdate":"2022-11-10","edate":"2023-12-21"},{"name":"项有志","title":"执行董事","sdate":"2022-11-10","edate":"2025-11-09"},{"name":"冀光恒","title":"执行董事","sdate":"2023-11-10","edate":"2025-11-09"},{"name":"杨军","title":"独立董事","sdate":"2022-11-10","edate":"2025-11-09"},{"name":"艾春荣","title":"独立董事","sdate":"2022-11-10","edate":"2025-11-09"},{"name":"吴志攀","title":"独立董事","sdate":"2023-05-11","edate":"2025-11-09"}]
```

**Python 接入示例**：

```python
import requests
url = "https://api.zhituapi.com/hs/gs/ljds/股票代码?token=token证书"
response = requests.get(url)
data = response.json()
print(data)
```

## 历届监事会成员

**API 地址**：

```
https://api.zhituapi.com/hs/gs/ljjs/股票代码?token=token证书
```

**描述**：根据《股票列表》得到的股票代码获取上市公司的历届监事会成员名单。

**更新频率**：每日03:30

**请求频率限制**：包量版1分钟300次 |体验版、包月版1分钟1000次 | 包年版1分钟3千次 | 至尊版1分钟6千次

**字段说明**：

| 字段名称 | 数据类型 | 字段说明 |
| --- | --- | --- |
| name | string | 姓名 |
| title | string | 职务 |
| sdate | string | 起始日期yyyy-MM-dd |
| edate | string | 终止日期yyyy-MM-dd |

**返回示例**：

```json
[{"name":"叶望春","title":"监事长","sdate":"2022-12-30","edate":"2025-11-09"},{"name":"邱伟","title":"职工监事","sdate":"2022-11-10","edate":"2022-12-23"},{"name":"邱伟","title":"监事长","sdate":"2022-11-10","edate":"2022-12-23"},{"name":"叶望春","title":"职工监事","sdate":"2022-12-23","edate":"2025-11-09"},{"name":"孙永桢","title":"职工监事","sdate":"2022-11-10","edate":"2025-11-09"},{"name":"邓红","title":"职工监事","sdate":"2022-11-10","edate":"2025-11-09"},{"name":"王春汉","title":"外部监事","sdate":"2022-11-10","edate":"2025-11-09"},{"name":"王松奇","title":"外部监事","sdate":"2022-11-10","edate":"2024-07-18"},{"name":"韩小京","title":"外部监事","sdate":"2022-11-10","edate":"2025-11-09"},{"name":"车国宝","title":"股东监事","sdate":"2022-11-10","edate":"2025-11-09"},{"name":"邱伟","title":"监事长","sdate":"2020-05-15","edate":"2022-11-09"},{"name":"邱伟","title":"职工监事","sdate":"2020-05-14","edate":"2022-11-09"},{"name":"孙永桢","title":"职工监事","sdate":"2020-05-14","edate":"2022-11-09"},{"name":"王群","title":"职工监事","sdate":"2020-05-14","edate":"2022-11-09"},{"name":"王春汉","title":"外部监事","sdate":"2020-09-16","edate":"2022-11-09"},{"name":"王松奇","title":"外部监事","sdate":"2020-09-06","edate":"2022-11-09"}]
```

**Python 接入示例**：

```python
import requests
url = "https://api.zhituapi.com/hs/gs/ljjs/股票代码?token=token证书"
response = requests.get(url)
data = response.json()
print(data)
```

## 近年分红

**API 地址**：

```
https://api.zhituapi.com/hs/gs/jnff/股票代码?token=token证书
```

**描述**：根据《股票列表》得到的股票代码获取上市公司的近年来的分红实施结果。按公告日期倒序。

**更新频率**：每日03:30

**请求频率限制**：包量版1分钟300次 |体验版、包月版1分钟1000次 | 包年版1分钟3千次 | 至尊版1分钟6千次

**字段说明**：

| 字段名称 | 数据类型 | 字段说明 |
| --- | --- | --- |
| sdate | string | 公告日期yyyy-MM-dd |
| give | string | 每10股送股(单位：股) |
| change | string | 每10股转增(单位：股) |
| send | string | 每10股派息(税前，单位：元) |
| line | string | 进度 |
| cdate | string | 除权除息日yyyy-MM-dd |
| edate | string | 股权登记日yyyy-MM-dd |
| hdate | string | 红股上市日yyyy-MM-dd |

**返回示例**：

```json
[{"sdate":"2024-09-26","give":"0","change":"0","send":"2.46","line":"实施","cdate":"2024-10-10","edate":"2024-10-09","hdate":"--"},{"sdate":"2024-06-06","give":"0","change":"0","send":"7.19","line":"实施","cdate":"2024-06-14","edate":"2024-06-13","hdate":"--"},{"sdate":"2023-06-07","give":"0","change":"0","send":"2.85","line":"实施","cdate":"2023-06-14","edate":"2023-06-13","hdate":"--"},{"sdate":"2022-07-15","give":"0","change":"0","send":"2.28","line":"实施","cdate":"2022-07-22","edate":"2022-07-21","hdate":"--"},{"sdate":"2021-05-07","give":"0","change":"0","send":"1.8","line":"实施","cdate":"2021-05-14","edate":"2021-05-13","hdate":"--"},{"sdate":"2020-05-22","give":"0","change":"0","send":"2.18","line":"实施","cdate":"2020-05-28","edate":"2020-05-27","hdate":"--"},{"sdate":"2019-06-20","give":"0","change":"0","send":"1.45","line":"实施","cdate":"2019-06-26","edate":"2019-06-25","hdate":"--"},{"sdate":"2018-07-06","give":"0","change":"0","send":"1.36","line":"实施","cdate":"2018-07-12","edate":"2018-07-11","hdate":"--"},{"sdate":"2017-07-17","give":"0","change":"0","send":"1.58","line":"实施","cdate":"2017-07-21","edate":"2017-07-20","hdate":"--"},{"sdate":"2016-06-08","give":"0","change":"2","send":"1.53","line":"实施","cdate":"2016-06-16","edate":"2016-06-15","hdate":"--"},{"sdate":"2015-04-07","give":"0","change":"2","send":"1.74","line":"实施","cdate":"2015-04-13","edate":"2015-04-10","hdate":"--"},{"sdate":"2014-06-06","give":"0","change":"2","send":"1.6","line":"实施","cdate":"2014-06-12","edate":"2014-06-11","hdate":"--"},{"sdate":"2013-06-14","give":"6","change":"0","send":"1.7","line":"实施","cdate":"2013-06-20","edate":"2013-06-19","hdate":"--"},{"sdate":"2012-10-12","give":"0","change":"0","send":"1","line":"实施","cdate":"2012-10-19","edate":"2012-10-18","hdate":"--"},{"sdate":"2012-03-09","give":"0","change":"0","send":"0","line":"不分配","cdate":"--","edate":"--","hdate":"--"},{"sdate":"2011-02-25","give":"0","change":"0","send":"0","line":"不分配","cdate":"--","edate":"--","hdate":"--"},{"sdate":"2010-03-12","give":"0","change":"0","send":"0","line":"不分配","cdate":"--","edate":"--","hdate":"--"},{"sdate":"2009-03-20","give":"0","change":"0","send":"0","line":"不分配","cdate":"--","edate":"--","hdate":"--"},{"sdate":"2008-10-24","give":"3","change":"0","send":"0.335","line":"实施","cdate":"2008-10-31","edate":"2008-10-30","hdate":"--"},{"sdate":"2008-03-20","give":"0","change":"0","send":"0","line":"不分配","cdate":"--","edate":"--","hdate":"--"},{"sdate":"2007-06-14","give":"1","change":"0","send":"0.09","line":"实施","cdate":"2007-06-18","edate":"2007-06-15","hdate":"2007-06-20"},{"sdate":"2007-03-22","give":"0","change":"0","send":"0","line":"不分配","cdate":"--","edate":"--","hdate":"--"},{"sdate":"2006-04-01","give":"0","change":"0","send":"0","line":"不分配","cdate":"--","edate":"--","hdate":"--"},{"sdate":"2005-06-18","give":"0","change":"0","send":"0","line":"不分配","cdate":"--","edate":"--","hdate":"--"},{"sdate":"2003-09-23","give":"0","change":"0","send":"1.5","line":"实施","cdate":"2003-09-29","edate":"2003-09-26","hdate":"--"},{"sdate":"2002-07-17","give":"0","change":"0","send":"1.5","line":"实施","cdate":"2002-07-23","edate":"2002-07-22","hdate":"--"},{"sdate":"1999-10-16","give":"0","change":"0","send":"6","line":"实施","cdate":"1999-10-18","edate":"1999-10-15","hdate":"--"},{"sdate":"1997-08-19","give":"5","change":"0","send":"2","line":"实施","cdate":"1997-08-25","edate":"1997-08-22","hdate":"--"},{"sdate":"1996-05-23","give":"5","change":"5","send":"0","line":"实施","cdate":"1996-05-27","edate":"1996-05-24","hdate":"1996-05-29"},{"sdate":"1995-09-15","give":"2","change":"0","send":"3","line":"实施","cdate":"1995-09-25","edate":"1995-09-22","hdate":"--"},{"sdate":"1994-07-02","give":"3","change":"2","send":"5","line":"实施","cdate":"1994-07-11","edate":"1994-07-08","hdate":"--"},{"sdate":"1993-05-09","give":"3.5","change":"5","send":"3","line":"实施","cdate":"1993-05-24","edate":"1993-05-21","hdate":"--"},{"sdate":"1991-03-03","give":"4","change":"0","send":"3","line":"实施","cdate":"1991-04-03","edate":"1991-03-12","hdate":"--"},{"sdate":"1900-01-01","give":"3","change":"0","send":"0","line":"实施","cdate":"1991-08-17","edate":"--","hdate":"--"}]
```

**Python 接入示例**：

```python
import requests
url = "https://api.zhituapi.com/hs/gs/jnff/股票代码?token=token证书"
response = requests.get(url)
data = response.json()
print(data)
```

## 近年增发

**API 地址**：

```
https://api.zhituapi.com/hs/gs/jnzf/股票代码?token=token证书
```

**描述**：根据《股票列表》得到的股票代码获取上市公司的近年来的增发情况。按公告日期倒序。

**更新频率**：每日03:30

**请求频率限制**：包量版1分钟300次 |体验版、包月版1分钟1000次 | 包年版1分钟3千次 | 至尊版1分钟6千次

**字段说明**：

| 字段名称 | 数据类型 | 字段说明 |
| --- | --- | --- |
| sdate | string | 公告日期yyyy-MM-dd |
| type | string | 发行方式 |
| price | string | 发行价格 |
| tprice | string | 实际公司募集资金总额 |
| fprice | string | 发行费用总额 |
| amount | string | 实际发行数量 |

**返回示例**：

```json
[{"sdate":"2015-05-20","type":"定向配售、网下询价配售","price":"16.70元","tprice":"1,000,000.00万元","fprice":"6,000.00万元","amount":"59880.2395万股"},{"sdate":"2014-01-08","type":"定向配售","price":"11.17元","tprice":"1,478,221.03万元","fprice":"4,850.00万元","amount":"132338.4991万股"},{"sdate":"2011-07-29","type":"定向配售","price":"17.75元","tprice":"269,005.23万元","fprice":"0.00元","amount":"163833.6654万股"},{"sdate":"2010-09-16","type":"定向配售","price":"18.26元","tprice":"693,113.08万元","fprice":"2,386.23万元","amount":"37958万股"}]
```

**Python 接入示例**：

```python
import requests
url = "https://api.zhituapi.com/hs/gs/jnzf/股票代码?token=token证书"
response = requests.get(url)
data = response.json()
print(data)
```

## 解禁限售

**API 地址**：

```
https://api.zhituapi.com/hs/gs/jjxs/股票代码?token=token证书
```

**描述**：根据《股票列表》得到的股票代码获取上市公司的解禁限售情况。按解禁日期倒序。

**更新频率**：每日03:30

**请求频率限制**：包量版1分钟300次 |体验版、包月版1分钟1000次 | 包年版1分钟3千次 | 至尊版1分钟6千次

**字段说明**：

| 字段名称 | 数据类型 | 字段说明 |
| --- | --- | --- |
| rdate | string | 解禁日期yyyy-MM-dd |
| ramount | number | 解禁数量(万股) |
| rprice | number | 解禁股流通市值(亿元) |
| batch | number | 上市批次 |
| pdate | string | 公告日期yyyy-MM-dd |

**返回示例**：

```json
[{"rdate":"2018-05-21","ramount":25224.8,"rprice":27.2932,"batch":15,"pdate":"2015-05-20"},{"rdate":"2017-01-09","ramount":228680.93,"rprice":209.7004,"batch":14,"pdate":"2014-01-08"},{"rdate":"2014-09-01","ramount":314560.64,"rprice":319.279,"batch":12,"pdate":"2011-07-29"},{"rdate":"2013-11-12","ramount":60732.8,"rprice":80.9568,"batch":11,"pdate":"2010-09-16"},{"rdate":"2010-06-28","ramount":18125.57,"rprice":33.5867,"batch":10,"pdate":"2008-03-20"},{"rdate":"2009-10-15","ramount":35.74,"rprice":0.0808,"batch":8,"pdate":"2009-10-14"},{"rdate":"2009-06-22","ramount":13908.07,"rprice":31.4322,"batch":7,"pdate":"2008-03-20"},{"rdate":"2008-06-26","ramount":28972.91,"rprice":65.4788,"batch":4,"pdate":"2008-06-25"}]
```

**Python 接入示例**：

```python
import requests
url = "https://api.zhituapi.com/hs/gs/jjxs/股票代码?token=token证书"
response = requests.get(url)
data = response.json()
print(data)
```

## 近一年各季度利润

**API 地址**：

```
https://api.zhituapi.com/hs/gs/jdlr/股票代码?token=token证书
```

**描述**：根据《股票列表》得到的股票代码获取上市公司近一年各个季度的利润。按截止日期倒序。

**更新频率**：每日03:30

**请求频率限制**：包量版1分钟300次 |体验版、包月版1分钟1000次 | 包年版1分钟3千次 | 至尊版1分钟6千次

**字段说明**：

| 字段名称 | 数据类型 | 字段说明 |
| --- | --- | --- |
| date | string | 截止日期yyyy-MM-dd |
| income | string | 营业收入（万元） |
| expend | string | 营业支出（万元） |
| profit | string | 营业利润（万元） |
| totalp | string | 利润总额（万元） |
| reprofit | string | 净利润（万元） |
| basege | string | 基本每股收益(元/股) |
| ettege | string | 稀释每股收益(元/股) |
| otherp | string | 其他综合收益（万元） |
| totalcp | string | 综合收益总额（万元） |

**返回示例**：

```json
[{"date":"2024-09-30","income":"11,158,200.00","expend":"3,169,900.00","profit":"4,786,900.00","totalp":"4,774,400.00","reprofit":"3,972,900.00","basege":"1.9400","ettege":"1.9400","otherp":"-78,600.00","totalcp":"3,894,300.00"},{"date":"2024-06-30","income":"7,713,200.00","expend":"2,189,200.00","profit":"3,208,700.00","totalp":"3,197,700.00","reprofit":"2,587,900.00","basege":"1.2300","ettege":"1.2300","otherp":"-35,600.00","totalcp":"2,552,300.00"},{"date":"2024-03-31","income":"3,877,000.00","expend":"1,082,000.00","profit":"1,855,400.00","totalp":"1,852,500.00","reprofit":"1,493,200.00","basege":"0.6600","ettege":"0.6600","otherp":"34,500.00","totalcp":"1,527,700.00"},{"date":"2023-12-31","income":"16,469,900.00","expend":"4,767,700.00","profit":"5,792,800.00","totalp":"5,771,800.00","reprofit":"4,645,500.00","basege":"2.2500","ettege":"2.2500","otherp":"-37,200.00","totalcp":"4,608,300.00"},{"date":"2023-09-30","income":"12,763,400.00","expend":"3,517,300.00","profit":"4,904,700.00","totalp":"4,899,300.00","reprofit":"3,963,500.00","basege":"1.9400","ettege":"1.9400","otherp":"-83,800.00","totalcp":"3,879,700.00"}]
```

**Python 接入示例**：

```python
import requests
url = "https://api.zhituapi.com/hs/gs/jdlr/股票代码?token=token证书"
response = requests.get(url)
data = response.json()
print(data)
```

## 近一年各季度现金流

**API 地址**：

```
https://api.zhituapi.com/hs/gs/jdxj/股票代码?token=token证书
```

**描述**：根据《股票列表》得到的股票代码获取上市公司近一年各个季度的现金流。按截止日期倒序。

**更新频率**：每日03:30

**请求频率限制**：包量版1分钟300次 |体验版、包月版1分钟1000次 | 包年版1分钟3千次 | 至尊版1分钟6千次

**字段说明**：

| 字段名称 | 数据类型 | 字段说明 |
| --- | --- | --- |
| date | string | 截止日期yyyy-MM-dd |
| jyin | string | 经营活动现金流入小计（万元） |
| jyout | string | 经营活动现金流出小计（万元） |
| jyfinal | string | 经营活动产生的现金流量净额（万元） |
| tzin | string | 投资活动现金流入小计（万元） |
| tzout | string | 投资活动现金流出小计（万元） |
| tzfinal | string | 投资活动产生的现金流量净额（万元） |
| czin | string | 筹资活动现金流入小计（万元） |
| czout | string | 筹资活动现金流出小计（万元） |
| czfinal | string | 筹资活动产生的现金流量净额（万元） |
| hl | string | 汇率变动对现金及现金等价物的影响（万元） |
| cashinc | string | 现金及现金等价物净增加额（万元） |
| cashs | string | 期初现金及现金等价物余额（万元） |
| cashe | string | 期末现金及现金等价物余额（万元） |

**返回示例**：

```json
[{"date":"2024-09-30","jyin":"53,854,700.00","jyout":"40,138,900.00","jyfinal":"13,715,800.00","tzin":"46,389,500.00","tzout":"47,443,400.00","tzfinal":"-1,053,900.00","czin":"51,304,000.00","czout":"65,857,200.00","czfinal":"-14,553,200.00","hl":"-59,400.00","cashinc":"-1,950,700.00","cashs":"29,821,900.00","cashe":"27,871,200.00"},{"date":"2024-06-30","jyin":"50,878,400.00","jyout":"39,506,200.00","jyfinal":"11,372,200.00","tzin":"29,409,700.00","tzout":"26,600,400.00","tzfinal":"2,809,300.00","czin":"45,294,400.00","czout":"59,982,500.00","czfinal":"-14,688,100.00","hl":"103,200.00","cashinc":"-403,400.00","cashs":"29,821,900.00","cashe":"29,418,500.00"},{"date":"2024-03-31","jyin":"22,175,200.00","jyout":"24,313,400.00","jyfinal":"-2,138,200.00","tzin":"12,364,300.00","tzout":"11,533,200.00","tzfinal":"831,100.00","czin":"29,476,400.00","czout":"27,196,300.00","czfinal":"2,280,100.00","hl":"92,300.00","cashinc":"1,065,300.00","cashs":"29,821,900.00","cashe":"30,887,200.00"},{"date":"2023-12-31","jyin":"52,903,500.00","jyout":"43,657,400.00","jyfinal":"9,246,100.00","tzin":"44,072,500.00","tzout":"46,686,700.00","tzfinal":"-2,614,200.00","czin":"93,341,600.00","czout":"92,532,700.00","czfinal":"808,900.00","hl":"148,500.00","cashinc":"7,589,300.00","cashs":"22,232,600.00","cashe":"29,821,900.00"},{"date":"2023-09-30","jyin":"43,959,000.00","jyout":"32,366,000.00","jyfinal":"11,593,000.00","tzin":"34,152,800.00","tzout":"29,149,900.00","tzfinal":"5,002,900.00","czin":"64,898,900.00","czout":"74,001,200.00","czfinal":"-9,102,300.00","hl":"345,300.00","cashinc":"7,838,900.00","cashs":"22,232,600.00","cashe":"30,071,500.00"}]
```

**Python 接入示例**：

```python
import requests
url = "https://api.zhituapi.com/hs/gs/jdxj/股票代码?token=token证书"
response = requests.get(url)
data = response.json()
print(data)
```

## 近年业绩预告

**API 地址**：

```
https://api.zhituapi.com/hs/gs/yjyg/股票代码?token=token证书
```

**描述**：根据《股票列表》得到的股票代码获取上市公司近年来的业绩预告。按公告日期倒序。

**更新频率**：每日03:30

**请求频率限制**：包量版1分钟300次 |体验版、包月版1分钟1000次 | 包年版1分钟3千次 | 至尊版1分钟6千次

**字段说明**：

| 字段名称 | 数据类型 | 字段说明 |
| --- | --- | --- |
| pdate | string | 公告日期yyyy-MM-dd |
| rdate | string | 报告期yyyy-MM-dd |
| type | string | 类型 |
| abs | string | 业绩预告摘要 |
| old | string | 上年同期每股收益(元) |

**返回示例**：

```json
[{"pdate":"2023-01-17","rdate":"2022-12-31","type":"预升","abs":"预计2022年1-12月归属于上市公司股东的净利润为：45516百万，与上年同期相比变动幅度：25.3%。","old":"1.7300"},{"pdate":"2022-01-14","rdate":"2021-12-31","type":"预升","abs":"预计2021年1-12月归属于上市公司股东的净利润为：36336百万，与上年同期相比变动幅度：25.6%。","old":"1.4000"},{"pdate":"2020-01-14","rdate":"2019-12-31","type":"预升","abs":"预计2019年1-12月归属于上市公司股东的净利润为：28195百万，与上年同期相比变动幅度：13.6%。","old":"1.3900"},{"pdate":"2019-01-04","rdate":"2018-12-31","type":"预升","abs":"预计2018年1-12月归属于上市公司股东的净利润为：24818百万，与上年同期相比变动幅度：7%。","old":"1.3000"},{"pdate":"2016-01-21","rdate":"2015-12-31","type":"预升","abs":"预计2015年1-12月归属于上市公司股东的净利润：2,079,206万元-2,277,225万元，与上年同期相比增长：5%-15%。","old":"1.7300"},{"pdate":"2012-01-30","rdate":"2011-12-31","type":"预增","abs":"预计2011年1月1日至2011年12月31日归属于上市公司股东的净利润为：盈利999,446 万元 – 1,061,912 万元，比上年同期增长：60% – 70% 。","old":"1.9100"},{"pdate":"2011-10-15","rdate":"2011-09-30","type":"预增","abs":"预计2011年1月1日 – 2011年9月30日，归属于上市公司股东的净利润：比上年同期增长：60% – 70%，盈利：754,914万元 – 802,096万元。","old":"1.4600"},{"pdate":"2011-10-15","rdate":"2011--","type":"预增","abs":"预计2011年7月1日-9月30日，归属于上市公司股东的净利润：比上年同期增长：70% – 80%，盈利：288,893万元 – 305,887万元。","old":""}]
```

**Python 接入示例**：

```python
import requests
url = "https://api.zhituapi.com/hs/gs/yjyg/股票代码?token=token证书"
response = requests.get(url)
data = response.json()
print(data)
```

## 财务指标

**API 地址**：

```
https://api.zhituapi.com/hs/gs/cwzb/股票代码?token=token证书
```

**描述**：根据《股票列表》得到的股票代码获取上市公司近四个季度的主要财务指标。按报告日期倒序。

**更新频率**：每日03:30

**请求频率限制**：包量版1分钟300次 |体验版、包月版1分钟1000次 | 包年版1分钟3千次 | 至尊版1分钟6千次

**字段说明**：

| 字段名称 | 数据类型 | 字段说明 |
| --- | --- | --- |
| date | string | 报告日期yyyy-MM-dd |
| tbmg | string | 摊薄每股收益(元)d |
| jqmg | string | 加权每股收益(元)型 |
| mgsy | string | 每股收益_调整后(元) |
| kfmg | string | 扣除非经常性损益后的每股收益(元) |
| mgjz | string | 每股净资产_调整前(元) |
| mgjzad | string | 每股净资产_调整后(元) |
| mgjy | string | 每股经营性现金流(元) |
| mggjj | string | 每股资本公积金(元) |
| mgwly | string | 每股未分配利润(元) |
| zclr | string | 总资产利润率(%) |
| zylr | string | 主营业务利润率(%) |
| zzlr | string | 总资产净利润率(%) |
| cblr | string | 成本费用利润率(%) |
| yylr | string | 营业利润率(%) |
| zycb | string | 主营业务成本率(%) |
| xsjl | string | 销售净利率(%) |
| gbbc | string | 股本报酬率(%) |
| jzbc | string | 净资产报酬率(%) |
| zcbc | string | 资产报酬率(%) |
| xsml | string | 销售毛利率(%) |
| xxbz | string | 三项费用比重 |
| fzy | string | 非主营比重 |
| zybz | string | 主营利润比重 |
| gxff | string | 股息发放率(%) |
| tzsy | string | 投资收益率(%) |
| zyyw | string | 主营业务利润(元) |
| jzsy | string | 净资产收益率(%) |
| jqjz | string | 加权净资产收益率(%) |
| kflr | string | 扣除非经常性损益后的净利润(元) |
| zysr | string | 主营业务收入增长率(%) |
| jlzz | string | 净利润增长率(%) |
| jzzz | string | 净资产增长率(%) |
| zzzz | string | 总资产增长率(%) |
| yszz | string | 应收账款周转率(次) |
| yszzt | string | 应收账款周转天数(天) |
| chzz | string | 存货周转天数(天) |
| chzzl | string | 存货周转率(次) |
| gzzz | string | 固定资产周转率(次) |
| zzzzl | string | 总资产周转率(次) |
| zzzzt | string | 总资产周转天数(天) |
| ldzz | string | 流动资产周转率(次) |
| ldzzt | string | 流动资产周转天数(天) |
| gdzz | string | 股东权益周转率(次) |
| ldbl | string | 流动比率 |
| sdbl | string | 速动比率 |
| xjbl | string | 现金比率(%) |
| lxzf | string | 利息支付倍数 |
| zjbl | string | 长期债务与营运资金比率(%) |
| gdqy | string | 股东权益比率(%) |
| cqfz | string | 长期负债比率(%) |
| gdgd | string | 股东权益与固定资产比率(%) |
| fzqy | string | 负债与所有者权益比率(%) |
| zczjbl | string | 长期资产与长期资金比率(%) |
| zblv | string | 资本化比率(%) |
| gdzcjz | string | 固定资产净值率(%) |
| zbgdh | string | 资本固定化比率(%) |
| cqbl | string | 产权比率(%) |
| qxjzb | string | 清算价值比率(%) |
| gdzcbz | string | 固定资产比重(%) |
| zcfzl | string | 资产负债率(%) |
| zzc | string | 总资产(元) |
| jyxj | string | 经营现金净流量对销售收入比率(%) |
| zcjyxj | string | 资产的经营现金流量回报率(%) |
| jylrb | string | 经营现金净流量与净利润的比率(%) |
| jyfzl | string | 经营现金净流量对负债比率(%) |
| xjlbl | string | 现金流量比率(%) |
| dqgptz | string | 短期股票投资(元) |
| dqzctz | string | 短期债券投资(元) |
| dqjytz | string | 短期其它经营性投资(元) |
| qcgptz | string | 长期股票投资(元) |
| cqzqtz | string | 长期债券投资(元) |
| cqjyxtz | string | 长期其它经营性投资(元) |
| yszk1 | string | 1年以内应收帐款(元) |
| yszk12 | string | 1-2年以内应收帐款(元) |
| yszk23 | string | 2-3年以内应收帐款(元) |
| yszk3 | string | 3年以内应收帐款(元) |
| yfhk1 | string | 1年以内预付货款(元) |
| yfhk12 | string | 1-2年以内预付货款(元) |
| yfhk23 | string | 2-3年以内预付货款(元) |
| yfhk3 | string | 3年以内预付货款(元) |
| ysk1 | string | 1年以内其它应收款(元) |
| ysk12 | string | 1-2年以内其它应收款(元) |
| ysk23 | string | 2-3年以内其它应收款(元) |
| ysk3 | string | 3年以内其它应收款(元) |

**返回示例**：

```json
[{"date":"2024-09-30","tbmg":"2.0473","jqmg":"1.94","mgsy":"1.94","kfmg":"1.94","mgjz":"25.2742","mgjzad":"21.67","mgjy":"7.0678","mggjj":"4.1593","mgwly":"12.3622","zclr":"0.6914","zylr":"--","zzlr":"0.7011","cblr":"150.6167","yylr":"--","zycb":"--","xsjl":"--","gbbc":"204.7262","jzbc":"8.1002","zcbc":"0.6914","xsml":"--","xxbz":"--","fzy":"38.2184","zybz":"-2.3521","gxff":"--","tzsy":"--","zyyw":"-1123000000","jzsy":"8.1","jqjz":"9.1","kflr":"39748000000","zysr":"--","jlzz":"0.2372","jzzz":"5.2825","zzzz":"4.1621","yszz":"--","yszzt":"--","chzz":"--","chzzl":"--","gzzz":"--","zzzzl":"--","zzzzt":"--","ldzz":"--","ldzzt":"--","gdzz":"--","ldbl":"--","sdbl":"--","xjbl":"--","lxzf":"--","zjbl":"--","gdqy":"8.5359","cqfz":"--","gdgd":"--","fzqy":"1071.5293","zczjbl":"--","zblv":"--","gdzcjz":"--","zbgdh":"1171.5293","cqbl":"0","qxjzb":"--","gdzcbz":"--","zcfzl":"91.4641","zzc":"5745988000000","jyxj":"--","zcjyxj":"0.0239","jylrb":"3.4523","jyfzl":"0.0261","xjlbl":"--","dqgptz":null,"dqzctz":"--","dqjytz":"--","qcgptz":null,"cqzqtz":"777403000000","cqjyxtz":"--","yszk1":"--","yszk12":"--","yszk23":"--","yszk3":"--","yfhk1":"--","yfhk12":"--","yfhk23":"--","yfhk3":"--","ysk1":"--","ysk12":"--","ysk23":"--","ysk3":"--"}]
```

**Python 接入示例**：

```python
import requests
url = "https://api.zhituapi.com/hs/gs/cwzb/股票代码?token=token证书"
response = requests.get(url)
data = response.json()
print(data)
```

## 十大股东

**API 地址**：

```
https://api.zhituapi.com/hs/gs/sdgd/股票代码?token=token证书
```

**描述**：根据《股票列表》得到的股票代码获取上市公司的十大股东数据。按截止日期倒序。

**更新频率**：每日03:30

**请求频率限制**：包量版1分钟300次 |体验版、包月版1分钟1000次 | 包年版1分钟3千次 | 至尊版1分钟6千次

**字段说明**：

| 字段名称 | 数据类型 | 字段说明 |
| --- | --- | --- |
| jzrq | string | 截止日期yyyy-MM-dd |
| ggrq | string | 公告日期yyyy-MM-dd |
| gdsm | string | 股东说明 |
| gdzs | number | 股东总数 |
| pjcg | number | 平均持股(单位：股，按总股本计算) |
| sdgd | array<ZygdSdgd> | 十大股东，其中ZygdSdgd对象见下方说明 |

**返回示例**：

```json
[{"jzrq":"2024-09-30","ggrq":"2024-10-19","gdsm":"","gdzs":517695,"pjcg":37489,"sdgd":[{"pm":1,"gdmc":"中国平安保险(集团)股份有限公司－集团本级－自有资金","cgsl":9618540236,"cgbl":49.56,"gbxz":"流通A股"},{"pm":2,"gdmc":"中国平安人寿保险股份有限公司－自有资金","cgsl":1186100488,"cgbl":6.11,"gbxz":"流通A股"},{"pm":3,"gdmc":"香港中央结算有限公司","cgsl":851414551,"cgbl":4.39,"gbxz":"流通A股"},{"pm":4,"gdmc":"中国平安人寿保险股份有限公司－传统－普通保险产品","cgsl":440478714,"cgbl":2.27,"gbxz":"流通A股"},{"pm":5,"gdmc":"中国证券金融股份有限公司","cgsl":429232688,"cgbl":2.21,"gbxz":"流通A股"},{"pm":6,"gdmc":"中国工商银行股份有限公司－华泰柏瑞沪深300交易型开放式指数证券投资基金","cgsl":185360838,"cgbl":0.96,"gbxz":"流通A股"},{"pm":7,"gdmc":"中国建设银行股份有限公司－易方达沪深300交易型开放式指数发起式证券投资基金","cgsl":123146496,"cgbl":0.63,"gbxz":"流通A股"},{"pm":8,"gdmc":"中国工商银行股份有限公司－华夏沪深300交易型开放式指数证券投资基金","cgsl":78266877,"cgbl":0.4,"gbxz":"流通A股"},{"pm":9,"gdmc":"中国银行股份有限公司－嘉实沪深300交易型开放式指数证券投资基金","cgsl":76478723,"cgbl":0.39,"gbxz":"流通A股"},{"pm":10,"gdmc":"深圳中电投资有限公司","cgsl":62523366,"cgbl":0.32,"gbxz":"流通A股"}]},{"jzrq":"2024-06-30","ggrq":"2024-08-16","gdsm":"","gdzs":546413,"pjcg":35519,"sdgd":[{"pm":1,"gdmc":"中国平安保险(集团)股份有限公司－集团本级－自有资金","cgsl":9618540236,"cgbl":49.56,"gbxz":"流通A股"},{"pm":2,"gdmc":"中国平安人寿保险股份有限公司－自有资金","cgsl":1186100488,"cgbl":6.11,"gbxz":"流通A股"},{"pm":3,"gdmc":"香港中央结算有限公司","cgsl":698756824,"cgbl":3.6,"gbxz":"流通A股"},{"pm":4,"gdmc":"中国平安人寿保险股份有限公司－传统－普通保险产品","cgsl":440478714,"cgbl":2.27,"gbxz":"流通A股"},{"pm":5,"gdmc":"中国证券金融股份有限公司","cgsl":429232688,"cgbl":2.21,"gbxz":"流通A股"},{"pm":6,"gdmc":"中国工商银行股份有限公司－华泰柏瑞沪深300交易型开放式指数证券投资基金","cgsl":114458038,"cgbl":0.59,"gbxz":"流通A股"},{"pm":7,"gdmc":"中国建设银行股份有限公司－易方达沪深300交易型开放式指数发起式证券投资基金","cgsl":76260746,"cgbl":0.39,"gbxz":"流通A股"},{"pm":8,"gdmc":"深圳中电投资有限公司","cgsl":62523366,"cgbl":0.32,"gbxz":"流通A股"},{"pm":9,"gdmc":"和谐健康保险股份有限公司－万能产品","cgsl":58894176,"cgbl":0.3,"gbxz":"流通A股"}]
```

**Python 接入示例**：

```python
import requests
url = "https://api.zhituapi.com/hs/gs/sdgd/股票代码?token=token证书"
response = requests.get(url)
data = response.json()
print(data)
```

## 十大流通股东

**API 地址**：

```
https://api.zhituapi.com/hs/gs/ltgd/股票代码?token=token证书
```

**描述**：根据《股票列表》得到的股票代码获取上市公司的十大流通股东数据。按公告日期倒序。

**更新频率**：每日03:30

**请求频率限制**：包量版1分钟300次 |体验版、包月版1分钟1000次 | 包年版1分钟3千次 | 至尊版1分钟6千次

**字段说明**：

| 字段名称 | 数据类型 | 字段说明 |
| --- | --- | --- |
| jzrq | string | 截止日期yyyy-MM-dd |
| ggrq | string | 公告日期yyyy-MM-dd |
| sdgd | array<ZygdSdgd> | 十大流通股东，其中ZygdSdgd对象见下方说明 |

**返回示例**：

```json
[{"jzrq":"2024-09-30","ggrq":"2024-10-19","sdgd":[{"pm":1,"gdmc":"中国平安保险(集团)股份有限公司－集团本级－自有资金","cgsl":9618540236,"cgbl":49.566,"gbxz":"境内法人股"},{"pm":2,"gdmc":"中国平安人寿保险股份有限公司－自有资金","cgsl":1186100488,"cgbl":6.112,"gbxz":"境内法人股"},{"pm":3,"gdmc":"香港中央结算有限公司","cgsl":851414551,"cgbl":4.387,"gbxz":"境外法人股"},{"pm":4,"gdmc":"中国平安人寿保险股份有限公司－传统－普通保险产品","cgsl":440478714,"cgbl":2.27,"gbxz":"境内法人股"},{"pm":5,"gdmc":"中国证券金融股份有限公司","cgsl":429232688,"cgbl":2.212,"gbxz":"国有股"},{"pm":6,"gdmc":"中国工商银行股份有限公司－华泰柏瑞沪深300交易型开放式指数证券投资基金","cgsl":185360838,"cgbl":0.955,"gbxz":"境内法人股"},{"pm":7,"gdmc":"中国建设银行股份有限公司－易方达沪深300交易型开放式指数发起式证券投资基金","cgsl":123146496,"cgbl":0.635,"gbxz":"境内法人股"},{"pm":8,"gdmc":"中国工商银行股份有限公司－华夏沪深300交易型开放式指数证券投资基金","cgsl":78266877,"cgbl":0.403,"gbxz":"境内法人股"},{"pm":9,"gdmc":"中国银行股份有限公司－嘉实沪深300交易型开放式指数证券投资基金","cgsl":76478723,"cgbl":0.394,"gbxz":"境内法人股"},{"pm":10,"gdmc":"深圳中电投资有限公司","cgsl":62523366,"cgbl":0.322,"gbxz":"国有股"}]},{"jzrq":"2024-06-30","ggrq":"2024-08-16","sdgd":[{"pm":1,"gdmc":"中国平安保险(集团)股份有限公司－集团本级－自有资金","cgsl":9618540236,"cgbl":49.566,"gbxz":"境内法人股"},{"pm":2,"gdmc":"中国平安人寿保险股份有限公司－自有资金","cgsl":1186100488,"cgbl":6.112,"gbxz":"境内法人股"},{"pm":3,"gdmc":"香港中央结算有限公司","cgsl":698756824,"cgbl":3.601,"gbxz":"境外法人股"},{"pm":4,"gdmc":"中国平安人寿保险股份有限公司－传统－普通保险产品","cgsl":440478714,"cgbl":2.27,"gbxz":"境内法人股"},{"pm":5,"gdmc":"中国证券金融股份有限公司","cgsl":429232688,"cgbl":2.212,"gbxz":"国有股"},{"pm":6,"gdmc":"中国工商银行股份有限公司－华泰柏瑞沪深300交易型开放式指数证券投资基金","cgsl":114458038,"cgbl":0.59,"gbxz":"境内法人股"},{"pm":7,"gdmc":"中国建设银行股份有限公司－易方达沪深300交易型开放式指数发起式证券投资基金","cgsl":76260746,"cgbl":0.393,"gbxz":"境内法人股"},{"pm":8,"gdmc":"深圳中电投资有限公司","cgsl":62523366,"cgbl":0.322,"gbxz":"国有股"},{"pm":9,"gdmc":"和谐健康保险股份有限公司－万能产品","cgsl":58894176,"cgbl":0.303,"gbxz":"境内法人股"}]
```

**Python 接入示例**：

```python
import requests
url = "https://api.zhituapi.com/hs/gs/ltgd/股票代码?token=token证书"
response = requests.get(url)
data = response.json()
print(data)
```

## 股东变化趋势

**API 地址**：

```
https://api.zhituapi.com/hs/gs/gdbh/股票代码?token=token证书
```

**描述**：根据《股票列表》得到的股票代码获取上市公司的股东变化趋势数据。按截止日期倒序。

**更新频率**：每日03:30

**请求频率限制**：包量版1分钟300次 |体验版、包月版1分钟1000次 | 包年版1分钟3千次 | 至尊版1分钟6千次

**字段说明**：

| 字段名称 | 数据类型 | 字段说明 |
| --- | --- | --- |
| jzrq | string | 截止日期yyyy-MM-dd |
| gdhs | string | 股东户数 |
| bh | string | 比上期变化情况 |

**返回示例**：

```json
[{"jzrq":"2024-09-30","gdhs":"517695","bh":"减少28718"},{"jzrq":"2024-06-30","gdhs":"546413","bh":"减少21489"},{"jzrq":"2024-03-31","gdhs":"567902","bh":"新增1702"},{"jzrq":"2024-03-29","gdhs":"566200","bh":"不变"},{"jzrq":"2024-03-22","gdhs":"566200","bh":"不变"},{"jzrq":"2024-02-29","gdhs":"566200","bh":"不变"},{"jzrq":"2024-02-28","gdhs":"566200","bh":"减少7082"},{"jzrq":"2023-12-31","gdhs":"573282","bh":"新增43053"},{"jzrq":"2023-09-30","gdhs":"530229","bh":"减少6472"},{"jzrq":"2023-06-30","gdhs":"536701","bh":"新增29834"},{"jzrq":"2023-03-31","gdhs":"506867","bh":"新增29563"},{"jzrq":"2023-02-28","gdhs":"477304","bh":"减少9896"},{"jzrq":"2022-12-31","gdhs":"487200","bh":"减少60535"},{"jzrq":"2022-09-30","gdhs":"547735","bh":"新增54706"},{"jzrq":"2022-06-30","gdhs":"493029","bh":"减少15650"},{"jzrq":"2022-03-31","gdhs":"508679","bh":"新增1945"},{"jzrq":"2022-02-28","gdhs":"506734","bh":"新增4018"},{"jzrq":"2021-12-31","gdhs":"502716","bh":"新增112226"},{"jzrq":"2021-09-30","gdhs":"390490","bh":"新增93662"},{"jzrq":"2021-06-30","gdhs":"296828","bh":"减少35001"},{"jzrq":"2021-03-31","gdhs":"331829","bh":"新增41079"},{"jzrq":"2021-01-31","gdhs":"290750","bh":"减少17974"}]
```

**Python 接入示例**：

```python
import requests
url = "https://api.zhituapi.com/hs/gs/gdbh/股票代码?token=token证书"
response = requests.get(url)
data = response.json()
print(data)
```

## 基金持股

**API 地址**：

```
https://api.zhituapi.com/hs/gs/jjcg/股票代码?token=token证书
```

**描述**：根据《股票列表》得到的股票代码获取该股票最近500家左右的基金持股情况。按截止日期倒序。

**更新频率**：每周六18:00

**请求频率限制**：包量版1分钟300次 |体验版、包月版1分钟1000次 | 包年版1分钟3千次 | 至尊版1分钟6千次

**字段说明**：

| 字段名称 | 数据类型 | 字段说明 |
| --- | --- | --- |
| jzrq | string | 截止日期yyyy-MM-dd |
| jjmc | string | 基金名称 |
| jjdm | string | 基金代码 |
| ccsl | number | 持仓数量(股) |
| ltbl | number | 占流通股比例(%) |
| cgsz | number | 持股市值（元） |
| jzbl | number | 占净值比例（%） |

**返回示例**：

```json
[{"jzrq":"2024-12-31","jjmc":"易方达上证50增强A","jjdm":"110003","ccsl":50383468,"ltbl":0.2596,"cgsz":589487000,"jzbl":2.95},{"jzrq":"2024-12-31","jjmc":"易方达上证50增强Y","jjdm":"022933","ccsl":50383468,"ltbl":0.2596,"cgsz":589487000,"jzbl":2.95},{"jzrq":"2024-12-31","jjmc":"易方达上证50增强C","jjdm":"004746","ccsl":50383468,"ltbl":0.2596,"cgsz":589487000,"jzbl":2.95},{"jzrq":"2024-12-31","jjmc":"华宝中证银行ETF","jjdm":"512800","ccsl":24396546,"ltbl":0.1257,"cgsz":285440000,"jzbl":3.81},{"jzrq":"2024-12-31","jjmc":"深红利ETF","jjdm":"159905","ccsl":13652000,"ltbl":0.0704,"cgsz":159728000,"jzbl":4.66},{"jzrq":"2024-12-31","jjmc":"天弘中证银行ETF","jjdm":"515290","ccsl":12854700,"ltbl":0.0662,"cgsz":150400000,"jzbl":3.84},{"jzrq":"2024-12-31","jjmc":"易方达沪深300精选增强Y","jjdm":"022914","ccsl":8000000,"ltbl":0.0412,"cgsz":93600000,"jzbl":2.77},{"jzrq":"2024-12-31","jjmc":"易方达沪深300精选增强C","jjdm":"010737","ccsl":8000000,"ltbl":0.0412,"cgsz":93600000,"jzbl":2.77},{"jzrq":"2024-12-31","jjmc":"易方达沪深300精选增强A","jjdm":"010736","ccsl":8000000,"ltbl":0.0412,"cgsz":93600000,"jzbl":2.77},{"jzrq":"2024-12-31","jjmc":"中证银行ETF","jjdm":"512820","ccsl":7034100,"ltbl":0.0362,"cgsz":82299000,"jzbl":3.84},{"jzrq":"2024-12-31","jjmc":"易方达增强回报债券B","jjdm":"110018","ccsl":6797211,"ltbl":0.035,"cgsz":79527400,"jzbl":0.29},{"jzrq":"2024-12-31","jjmc":"易方达增强回报债券A","jjdm":"110017","ccsl":6797211,"ltbl":0.035,"cgsz":79527400,"jzbl":0.29},{"jzrq":"2024-12-31","jjmc":"南方中证银行ETF","jjdm":"512700","ccsl":5134300,"ltbl":0.0265,"cgsz":60071300,"jzbl":3.84},{"jzrq":"2024-12-31","jjmc":"长信内需成长混合A","jjdm":"519979","ccsl":3900000,"ltbl":0.0201,"cgsz":45630000,"jzbl":6.72},{"jzrq":"2024-12-31","jjmc":"长信内需成长混合C","jjdm":"015768","ccsl":3900000,"ltbl":0.0201,"cgsz":45630000,"jzbl":6.72},{"jzrq":"2024-12-31","jjmc":"长信内需成长混合E","jjdm":"006397","ccsl":3900000,"ltbl":0.0201,"cgsz":45630000,"jzbl":6.72},{"jzrq":"2024-12-31","jjmc":"易方达金融行业股票C","jjdm":"019026","ccsl":3897300,"ltbl":0.0201,"cgsz":45598400,"jzbl":6.92}]
```

**Python 接入示例**：

```python
import requests
url = "https://api.zhituapi.com/hs/gs/jjcg/股票代码?token=token证书"
response = requests.get(url)
data = response.json()
print(data)
```

## 经营范围

**API 地址**：

```
https://api.zhituapi.com/hs/gs/jyfw/股票代码?token=token证书
```

**描述**：根据《股票列表》得到的股票代码作为参数，获取该股票的经营范围。

**更新频率**：每日21:00

**请求频率限制**：包量版1分钟300次 |体验版、包月版1分钟1000次 | 包年版1分钟3千次 | 至尊版1分钟6千次

**字段说明**：

| 字段名称 | 数据类型 | 字段说明 |
| --- | --- | --- |
| keyword | string | 关键字 |
| content | string | 内容 |

**返回示例**：

```json
[{"keyword":"经营范围","content":"办理人民币存、贷、结算、汇兑业务;人民币票据承兑和贴现;各项信托业务;经监管机构批准发行或买卖人民币有价证券;发行金融债券;代理发行、代理兑付、承销政府债券;买卖政府债券;外汇存款、汇款;境内境外借款;从事同业拆借;外汇借款;外汇担保;在境内境外发行或代理发行外币有价证券;买卖或代客买卖外汇及外币有价证券、自营外汇买卖;贸易、非贸易结算;办理国内结算;国际结算;外币票据的承兑和贴现;外汇贷款;资信调查、咨询、见证业务;保险兼业代理业务;代理收付款项;黄金进口业务;提供信用证服务及担保;提供保管箱服务;外币兑换;结汇、售汇;信用卡业务;经有关监管机构批准或允许的其他业务。"}]
```

**Python 接入示例**：

```python
import requests
url = "https://api.zhituapi.com/hs/gs/jyfw/股票代码?token=token证书"
response = requests.get(url)
data = response.json()
print(data)
```

