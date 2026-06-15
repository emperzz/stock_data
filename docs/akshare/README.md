# AKShare 数据字典

本目录收录 AKShare 官方数据字典(原始文档: <https://akshare.akfamily.xyz/data/index.html>)。

**总计 22 个分类, 1006 个接口。**

## 分类索引

- **股票** ([`stock.md`](./stock.md), [`stock/`](./stock/)): 共 372 个接口
- **指数** ([`index.md`](./index.md), [`index/`](./index/)): 共 87 个接口
- **期货** ([`futures.md`](./futures.md), [`futures/`](./futures/)): 共 54 个接口
- **债券** ([`bond.md`](./bond.md), [`bond/`](./bond/)): 共 43 个接口
- **期权** ([`option.md`](./option.md), [`option/`](./option/)): 共 42 个接口
- **外汇** ([`fx.md`](./fx.md), [`fx/`](./fx/)): 共 11 个接口
- **货币** ([`currency.md`](./currency.md), [`currency/`](./currency/)): 共 5 个接口
- **现货** ([`spot.md`](./spot.md), [`spot/`](./spot/)): 共 13 个接口
- **利率** ([`interest_rate.md`](./interest_rate.md), [`interest_rate/`](./interest_rate/)): 共 14 个接口
- **私募基金** ([`fund_private.md`](./fund_private.md), [`fund_private/`](./fund_private/)): 共 14 个接口
- **公募基金** ([`fund_public.md`](./fund_public.md), [`fund_public/`](./fund_public/)): 共 76 个接口
- **宏观** ([`macro.md`](./macro.md), [`macro/`](./macro/)): 共 215 个接口
- **加密货币** ([`dc.md`](./dc.md), [`dc/`](./dc/)): 共 3 个接口
- **银行** ([`bank.md`](./bank.md), [`bank/`](./bank/)): 共 1 个接口
- **波动率** ([`article.md`](./article.md), [`article/`](./article/)): 共 4 个接口
- **能源** ([`energy.md`](./energy.md), [`energy/`](./energy/)): 共 8 个接口
- **迁徙** ([`event.md`](./event.md), [`event/`](./event/)): 共 2 个接口
- **高频** ([`hf.md`](./hf.md), [`hf/`](./hf/)): 共 1 个接口
- **自然语言处理** ([`nlp.md`](./nlp.md), [`nlp/`](./nlp/)): 共 2 个接口
- **QDII** ([`qdii.md`](./qdii.md), [`qdii/`](./qdii/)): 共 3 个接口
- **另类** ([`others.md`](./others.md), [`others/`](./others/)): 共 35 个接口
- **工具箱** ([`tool.md`](./tool.md), [`tool/`](./tool/)): 共 1 个接口
- **奇货首页** ([`qhkc_index.md`](./qhkc_index.md), [`qhkc_index/`](./qhkc_index/)): 共 0 个接口
- **奇货商品** ([`qhkc_commodity.md`](./qhkc_commodity.md), [`qhkc_commodity/`](./qhkc_commodity/)): 共 0 个接口
- **奇货席位** ([`qhkc_broker.md`](./qhkc_broker.md), [`qhkc_broker/`](./qhkc_broker/)): 共 0 个接口
- **奇货指数** ([`qhkc_index_data.md`](./qhkc_index_data.md), [`qhkc_index_data/`](./qhkc_index_data/)): 共 0 个接口
- **奇货基本面** ([`qhkc_fundamental.md`](./qhkc_fundamental.md), [`qhkc_fundamental/`](./qhkc_fundamental/)): 共 0 个接口
- **奇货工具** ([`qhkc_tools.md`](./qhkc_tools.md), [`qhkc_tools/`](./qhkc_tools/)): 共 0 个接口
- **奇货资金** ([`qhkc_fund.md`](./qhkc_fund.md), [`qhkc_fund/`](./qhkc_fund/)): 共 0 个接口

## 目录结构

```
docs/akshare/
├── README.md           # 本文件

├── stock.md          # 股票分类总览

└── stock/            # 每接口一个 md

├── index.md          # 指数分类总览

└── index/            # 每接口一个 md

├── futures.md          # 期货分类总览

└── futures/            # 每接口一个 md

├── bond.md          # 债券分类总览

└── bond/            # 每接口一个 md

├── option.md          # 期权分类总览

└── option/            # 每接口一个 md

├── fx.md          # 外汇分类总览

└── fx/            # 每接口一个 md

├── currency.md          # 货币分类总览

└── currency/            # 每接口一个 md

├── spot.md          # 现货分类总览

└── spot/            # 每接口一个 md

├── interest_rate.md          # 利率分类总览

└── interest_rate/            # 每接口一个 md

├── fund_private.md          # 私募基金分类总览

└── fund_private/            # 每接口一个 md

├── fund_public.md          # 公募基金分类总览

└── fund_public/            # 每接口一个 md

├── macro.md          # 宏观分类总览

└── macro/            # 每接口一个 md

├── dc.md          # 加密货币分类总览

└── dc/            # 每接口一个 md

├── bank.md          # 银行分类总览

└── bank/            # 每接口一个 md

├── article.md          # 波动率分类总览

└── article/            # 每接口一个 md

├── energy.md          # 能源分类总览

└── energy/            # 每接口一个 md

├── event.md          # 迁徙分类总览

└── event/            # 每接口一个 md

├── hf.md          # 高频分类总览

└── hf/            # 每接口一个 md

├── nlp.md          # 自然语言处理分类总览

└── nlp/            # 每接口一个 md

├── qdii.md          # QDII分类总览

└── qdii/            # 每接口一个 md

├── others.md          # 另类分类总览

└── others/            # 每接口一个 md

├── tool.md          # 工具箱分类总览

└── tool/            # 每接口一个 md

├── qhkc_index.md          # 奇货首页分类总览

└── qhkc_index/            # 每接口一个 md

├── qhkc_commodity.md          # 奇货商品分类总览

└── qhkc_commodity/            # 每接口一个 md

├── qhkc_broker.md          # 奇货席位分类总览

└── qhkc_broker/            # 每接口一个 md

├── qhkc_index_data.md          # 奇货指数分类总览

└── qhkc_index_data/            # 每接口一个 md

├── qhkc_fundamental.md          # 奇货基本面分类总览

└── qhkc_fundamental/            # 每接口一个 md

├── qhkc_tools.md          # 奇货工具分类总览

└── qhkc_tools/            # 每接口一个 md

├── qhkc_fund.md          # 奇货资金分类总览

└── qhkc_fund/            # 每接口一个 md

├── raw/                # urllib 抓取的 innerText (供 reparse)

└── scripts/            # 解析脚本

```

## 重新生成

```bash
# 1. 抓 raw (urllib 批量, 不经 LLM 上下文)
python docs/akshare/scripts/fetch_categories.py

# 2. 跑解析脚本
python docs/akshare/scripts/parse_akshare.py
```
