# 其他 — 端点明细

> 主文件 [§11 其他](../market-data-obtain.md) 的端点明细；字段、单位、调用约束、示例见本文。

---

## `GET /healthz`

### 功能

服务器健康检查 + 每个 fetcher 断路器状态快照。`status` 字段在所有 fetcher 都可用时为 `ok`，部分不可用时为 `degraded`，全部不可用为 `unhealthy`。

- 本地端点，不消耗任何 fetcher 配额
- 任意场景启动 / 出错时都建议先查一次

### 入参

| 参数名 | 类型 | 必填 | 默认值 | 约束 |
|---|---|---|---|---|
| `details`（query） | bool | ❌ | `false` | `true` 时响应额外带 `sources[]` 列出每个 fetcher 状态 |

### 返回参数

| 字段 | 类型 | 单位 | 说明 |
|---|---|---|---|
| `status` | string | — | `ok` / `degraded` / `unhealthy`（整体） |
| `version` | string | — | 服务端版本号（默认 `"0.1.0"`） |
| `sources[]`（仅 `?details=true`） | array | — | 每个 fetcher 的断路器状态 |
| `sources[].name` | string | — | fetcher 名（`tushare` / `akshare` / `zzshare` / ...） |
| `sources[].state` | string | — | `closed` / `open` / `half_open`（断路器状态） |
| `sources[].available` | bool | — | 当前是否可用（无 token / 配置缺失 = `false`） |
| `sources[].last_success_time` | float | epoch 秒 | 最近一次成功时间；缺数据为 `null` |
| `sources[].last_failure_time` | float | epoch 秒 | 最近一次失败时间；缺数据为 `null` |
| `sources[].failure_count` | int | — | 累计失败次数 |
| `sources[].unavailable_reason` | string | — | 不可用原因（仅 `available=false` 时填充） |

### 示例

```bash
# 仅查整体健康
curl 'http://localhost:8888/healthz'

# 含每个 fetcher 详情
curl 'http://localhost:8888/healthz?details=true'
```

---

## `GET /api/v1/indicators`

### 功能

返回本服务支持的所有技术指标目录。K 线请求里通过 `?indicators=ma,macd,kdj` 一次计算多个指标。

- 纯本地计算，零网络开销
- 建议先查本端点确认指标 key，再在 `/stocks/{code}/kline` 或 `/indices/{code}/kline` 里指定

### 入参

无。

### 返回参数

| 字段 | 类型 | 单位 | 说明 |
|---|---|---|---|
| `indicators[]` | array | — | 所有支持的指标 |
| `indicators[].key` | string | — | 指标标识符（`ma` / `macd` / `kdj` / `boll` / ...） |
| `indicators[].input_shape` | string | — | 输入需求：`"closes"`（仅收盘价）或 `"ohlcv"`（OHLCV 全量） |
| `indicators[].default_options` | object | — | 默认参数（如 `ma: {periods: [5,10,20,30,60], type: "sma"}`） |
| `indicators[].output_columns[]` | array | — | 输出列名（如 `["ma5","ma10",...]`） |
| `indicators[].default_lookback` | int | — | 预热所需最少 K 线根数（路由层自动 `max(days, lookback)` 拉更多再截断） |

### 示例

```bash
curl 'http://localhost:8888/api/v1/indicators'
```

然后 K 线请求里：

```bash
curl 'http://localhost:8888/api/v1/stocks/600519/kline?period=daily&days=60&indicators=ma,macd,kdj'
```