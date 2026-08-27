# `source` field tracking — coverage matrix

Read this when adding an endpoint that must report which fetcher served it,
or when auditing why a response's `source` is `""` / `null` / `"persistence"`.
Extracted from CLAUDE.md 2026-08-27; the resident spec keeps the three-value
summary and points here for the per-endpoint matrix.

所有响应都包含 `source: str` 字段, 取值:
- **fetcher 名** (e.g. `tushare`, `akshare`, `eastmoney`): 实时从上游拉取
- **fetcher 名**: API TTLCache 命中时, 保留写入时的 fetcher (Pydantic 字段自然带过去, 无需额外代码)
- **`"persistence"`**: 从 SQLite 持久化层读取 (历史数据 / 板块列表 / 交易日历等)

`source` 为可选字段, `default=""`. 旧 client 可忽略.

## 覆盖矩阵

| Endpoint 类型 | 实时拉取 / 缓存命中 | SQLite persistence |
|---|---|---|
| K线 / 分时 / 实时行情 / 指数 | fetcher 名 (e.g. `tushare`, `akshare`) | n/a |
| 龙虎榜 / 融资融券 / 大宗交易 / 资金流 / 研报 / 公告 等 | fetcher 名 (e.g. `eastmoney`, `cninfo`, `ths`) | n/a (每次 fetch) |
| 板块清单 | 用户传入 `source`; fetcher 名 (fetch 时) | `"persistence"` (缓存命中) |
| 板块成分股 | 用户传入 `source`; fetcher 名 (fetch 时) | `"persistence"` (缓存命中) |
| 涨跌停 / 股票列表 / 交易日历 | fetcher 名 (refresh 时) | `"persistence"` (缓存命中) |
| `/agent/correlation/matrix` | 不跟踪 serving fetcher — stock label 恒为 `source: null`;board label 记录*请求的* source (`ths`/`eastmoney`, spec §2.3),非实际服务的 fetcher | n/a (compute-only — no top-level `source` field on `CorrelationMatrixResponse` because the response is a composite of multiple fetchers) |

> `/stocks` 暴露 `source` 字段 (post-2026-07-29): 每个 list entry 的 source 是 metadata origin (akshare/zzshare/persistence) 或 quote fetcher (当 `?include_quote=true`)。`/calendar` 仍然不暴露 source (response model 无该字段)。

## Composite-response exception

Aggregation endpoints whose response is stitched from several fetchers
(`/agent/correlation/matrix`, `/agent/*/batch-profile`, `/agent/market-context`)
carry **no top-level `source`** — there is no single serving fetcher to name.
Per-item provenance, where it exists, lives on the item.
