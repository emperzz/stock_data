# zzshare · 实时行情（`rt_k`）

> 唯一支持的实时快照接口；其他 fetcher 多走 `push2.eastmoney.com` 风格，zzshare 是直连自家网关。

## `rt_k` — 实时日线快照

### 接口

- **HTTP**: `GET /v3/market/kline/realtime`
- **SDK**: `DataApi.rt_k(...)`

### 参数

| 参数 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `ts_code` | `str` | 否 | 单只 / 多只 / 通配符；为空时返回全市场 |
| `fields` | `str` | 否 | `'all'` 时返回 26 字段增强模式 |

### `ts_code` 通配符

| 写法 | 含义 |
|---|---|
| `600000.SH` | 单只 |
| `600000.SH,000001.SZ` | 多只（逗号分隔，并发） |
| `60*.SH` | 沪市主板 |
| `68*.SH` | 科创板 |
| `0*.SZ` | 深市主板 |
| `3*.SZ` | 创业板 |
| `9*.BJ` | 北交所 |
| `3*.SZ,0*.SZ,6*.SH,9*.BJ` | 全市场（不推荐一次取完） |

### 返回字段

**默认 14 字段**（强兼容模式）：

| 字段 | 类型 | 说明 |
|---|---|---|
| `ts_code` | str | tushare 风格代码 |
| `name` | str | 股票名称 |
| `pre_close` | float | 昨收 |
| `open` / `high` / `low` / `close` | float | OHLC（盘中为截至当前） |
| `vol` | float | 成交量（股） |
| `amount` | float | 成交额（元） |
| `num` | int | 成交笔数（若源不支持为 0） |
| `ask_price1` / `ask_volume1` | float / int | 卖一价 / 量 |
| `bid_price1` / `bid_volume1` | float / int | 买一价 / 量 |

**`fields='all'` 追加 12 个增强字段**：

| 字段 | 类型 | 说明 |
|---|---|---|
| `quote_rate` | float | 涨跌幅（%） |
| `turnover_rate` | float | 换手率 |
| `min5_chgpct` | float | 5 分钟涨跌幅 |
| `high_limit` / `low_limit` | float | 涨停价 / 跌停价 |
| `market_value` / `circulation_value` | float | 总市值 / 流通市值（元） |
| `auction_px` / `auction_vol` / `auction_val` | float | 集合竞价成交价 / 量 / 额 |
| `bid_grp` / `offer_grp` | list | 多档买盘 / 卖盘 |
| `ttm_pe_rate` | float | 滚动市盈率 |
| `eps_ttm` | float | 滚动每股收益 |

### 频率限制

- README 明示需 Token，**20 次/分钟**。
- 实测单只股票匿名可通（返回 1 行）；批量匿名将被 429。

### 行为细节

- 单接口一次只能取**一种粒度**——批量覆盖多市场建议拆成多次调用再 concat，避免触发 429。
- 默认 14 列与 `fields='all'` 26 列之间字段集不同，调用方需要在客户端归一化。
- `market_value` 单位为元。

### 示例

```python
# 单股
df = api.rt_k(ts_code='600000.SH')

# 多股
df = api.rt_k(ts_code='600000.SH,000001.SZ')

# 全沪市主板
df = api.rt_k(ts_code='60*.SH')

# 增强字段
df = api.rt_k(ts_code='000001.SZ', fields='all')
```