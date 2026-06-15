# Zhitu 股票列表接入 + Exchange 持久化 设计文档

> 日期：2026-06-15
> 状态：待审
> 范围：ZhituFetcher 加 `get_all_stocks` + `STOCK_LIST` capability；persistence 层加可空 `exchange` 列并对多源格式归一化

## 1. 目标与范围

让 Zhitu 接入 `STOCK_LIST` capability，作为 A 股股票列表的 last-resort 备份（紧跟在 Baostock / Akshare / Myquant 之后）；同时把各 fetcher 报告的"交易所"信息（Zhitu `jys`、Myquant `exchange`）以**归一化后**的可空 `exchange` 列持久化下来。

**只做这一次**。不包含：
- `/stocks` 响应模型加 `exchange` 字段（响应契约不变，避免客户端兼容负担）
- 历史数据迁移（按 2026-06-15 决定：不写 ALTER TABLE；现有 DB 用 `STOCK_DB_INIT=true` 全量重置，新数据天然带 exchange）
- HK / US 股票列表（Zhitu 不支持；与 `MyquantFetcher.get_all_stocks` 一致返回 `[]`）

## 2. 使用的上游 API

### Zhitu `https://api.zhituapi.com/hs/list/all?token={token}`

- 鉴权：`ZHITU_TOKEN` 环境变量
- 频率：每日 16:20 更新；限频 "1分钟300次"（包量版）
- 文档：`stock_data/docs/zhitu/01-stocks-list.md`
- 单次返回**完整 A 股列表**（一次 HTTP 调用拿所有 ~5000+ 票）

**返回字段**：

| Zhitu 字段 | 类型 | 说明 |
|---|---|---|
| `dm` | string | 股票代码，如 `000001` |
| `mc` | string | 股票名称，如 `平安银行` |
| `jys` | string | 交易所 `"sh"` / `"sz"` |

## 3. 设计要点

### 3.1 ZhituFetcher 改动

**新 capability**：
```python
supported_data_types = (
    DataCapability.REALTIME_QUOTE
    | DataCapability.STOCK_ZT_POOL
    | DataCapability.STOCK_INFO
    | DataCapability.HISTORICAL_MIN
    | DataCapability.STOCK_LIST      # NEW
)
```

**新方法** `get_all_stocks(market="csi") -> list[dict]`：

- 非 `csi` 市场（hk/us）→ 返回 `[]`（与 Myquant 一致）
- 调用 `/hs/list/all`，超时 / 4xx / 5xx / 解析失败 → 返回 `[]`（容错优先，避免阻塞 failover）
- 输出 dict 形如 `{"code": "688411", "name": "N海博", "exchange": "sh"}`
  - `exchange` **原值透传**（不做归一化），归一化在 persistence 层做
  - 这是为了让 fetcher contract 简单；Myquant 现有代码也是这么做的

**Failover 位置**：自动按 priority 4 排在链尾（Baostock 1 → Akshare 2 → Myquant 3 → Zhitu 4）。无需额外配置。

### 3.2 Persistence 改动

**Schema 新增列**：
```sql
CREATE TABLE IF NOT EXISTS stock_list (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    market TEXT NOT NULL,
    code TEXT NOT NULL,
    name TEXT NOT NULL,
    exchange TEXT,                     -- NEW, nullable
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(market, code)
);
```

**不做 ALTER TABLE 迁移**（按 2026-06-15 决定）。新装 / `STOCK_DB_INIT=true` 重置后自动包含该列；现有 DB 如果保留旧 schema，exchange 永远 NULL，新拉一次数据后才有。

**Exchange 归一化**（在 `update_cached_stocks` 写入前应用）：

| 输入 | 输出 |
|---|---|
| `None` / `""` | `None` |
| `"sh"` / `"SH"` / `"SHSE"` / `"SSE"` | `"SH"` |
| `"sz"` / `"SZ"` / `"SZSE"` | `"SZ"` |
| `"bj"` / `"BJ"` / `"BSE"` | `"BJ"` |
| 其它 | 大写化后保留原样（如 `"tw"` → `"TW"`） |

实现：模块级 helper `_normalize_exchange(value: str | None) -> str | None`：
```python
def _normalize_exchange(value: str | None) -> str | None:
    if not value:
        return None
    v = value.strip().upper()
    if v in ("SH", "SHSE", "SSE"):
        return "SH"
    if v in ("SZ", "SZSE"):
        return "SZ"
    if v in ("BJ", "BSE"):
        return "BJ"
    return v  # 未知值：保留归一化后的大写形式
```
在 `update_cached_stocks` 内对每条 stock 调用一次。

**读路径**（`_read_from_db`、`get_cached_stocks`）：
```python
"SELECT code, name, exchange, updated_at FROM stock_list WHERE market = ? ORDER BY code"
```
返回 dict 多一个 `exchange` 键（DB 中为 NULL → Python `None`）。

### 3.3 不改的东西

- `/stocks` 响应模型（`StockInfo`）— 暂不加 `exchange`，避免 API 契约变化
- `routes.py` — 现有 `list_stocks` 已经从 persistence 读，再多一个字段不影响响应
- MyquantFetcher — 不动它的输出格式；归一化在 persistence 层兜底
- Baostock / Akshare — 两者不返回 exchange，自然落到 NULL，不需改动

## 4. 测试策略

### 单元测试（`tests/test_zhitu_fetcher.py`）

1. `test_get_all_stocks_csi_success` — mock `requests.get` 返回标准 Zhitu 列表，验证输出 dict 形状（含 `code`/`name`/`exchange`）
2. `test_get_all_stocks_csi_empty_response` — mock 返回 `[]`，验证返回 `[]`
3. `test_get_all_stocks_csi_error_dict` — mock 返回 `{"detail": "..."}`，验证返回 `[]`
4. `test_get_all_stocks_hk_returns_empty` — 验证非 csi 直接返回 `[]`
5. `test_get_all_stocks_unavailable_token` — 无 token 时返回 `[]`
6. `test_get_all_stocks_http_failure` — mock 抛 `RequestException`，验证返回 `[]`
7. `test_supported_data_types_includes_stock_list` — 验证 `STOCK_LIST` 在 `supported_data_types`

### 集成测试（`tests/test_capability_method_map.py`）

- 验证 `STOCK_LIST` capability 的 failover chain 包含 `ZhituFetcher`
- 验证 Zhitu 的 `get_all_stocks` 方法签名能被 manifest 反射到

### Persistence 测试（`tests/test_persistence_origin.py` 或新建 `test_stock_list_exchange.py`）

- `_normalize_exchange` 各分支覆盖（sh/SH/SHSE/SSE、sz/SZ/SZSE、bj/BJ/BSE、None、空字符串、未知值）
- `update_cached_stocks` 写入后 round-trip 读出，验证 exchange 值正确归一化
- 缺失 exchange 的输入 dict（Baostock/Akshare 风格）写入后读出为 `None`

## 5. 文档更新（CLAUDE.md）

1. **ZhituFetcher 行**（capability 表）：
   `ZhituFetcher | REALTIME_QUOTE \| STOCK_ZT_POOL \| STOCK_INFO \| HISTORICAL_MIN \| STOCK_LIST`
2. **ZhituFetcher 章节**：加一行描述 `/hs/list/all` 端点、限频、字段映射、归一化约定
3. **`STOCK_LIST` failover chain 表**：在"Source Tracking 覆盖矩阵"附近补一句 Zhitu 作为 last-resort backup

## 6. 风险与缓解

| 风险 | 缓解 |
|---|---|
| 现有 DB schema 不含 `exchange` 列 | 按用户决定，不写 ALTER TABLE；新装 / `STOCK_DB_INIT=true` 重置后 OK |
| Zhitu / Myquant 格式不一致 | persistence 层归一化；fetcher contract 不动 |
| Zhitu 返回 ~5000 条，无分页 | 单次 HTTP 调用完成；不加循环 |
| Token 失效 | 已存在 `is_available()` 守卫；`unavailable_reason()` 也已实现 |
| 与现有 Baostock / Akshare 数据冲突（已有 DB 行 exchange=NULL） | `INSERT OR REPLACE` 按 (market, code) 唯一键 upsert；新 fetch 后所有 Zhitu 行 exchange 自动填充 |
