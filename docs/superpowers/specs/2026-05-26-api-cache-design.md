# API TTL Cache 增强设计

## 目标

为 `routes.py` 中目前无缓存的 13 个 API 端点增加内存 TTLCache 缓存功能，减少重复上游 API 调用，提升响应速度。

## 缓存架构

在 `stock_data/api/cache.py` 中新增 11 个 TTLCache 实例（`/stocks` 列表和 `/calendar` 因已有 SQLite 持久化不做缓存）：

| 缓存实例 | TTL 环境变量 | 默认值 | 适用场景 |
|---------|------------|-------|---------|
| `_dragontiger_cache` | `CACHE_TTL_DRAGON_TIGER` | 300s | 龙虎榜（盘中更新） |
| `_margin_cache` | `CACHE_TTL_MARGIN` | 300s | 融资融券 |
| `_block_trade_cache` | `CACHE_TTL_BLOCK_TRADE` | 300s | 大宗交易 |
| `_holder_num_cache` | `CACHE_TTL_HOLDER_NUM` | 300s | 股东户数 |
| `_dividend_cache` | `CACHE_TTL_DIVIDEND` | 300s | 分红送转 |
| `_fund_flow_cache` | `CACHE_TTL_FUND_FLOW` | 60s | 资金流（分钟级） |
| `_hot_topics_cache` | `CACHE_TTL_HOT_TOPICS` | 60s | 热点题材 |
| `_north_flow_cache` | `CACHE_TTL_NORTH_FLOW` | 60s | 北向资金 |
| `_reports_cache` | `CACHE_TTL_REPORTS` | 1800s | 研报（内容稳定） |
| `_announcements_cache` | `CACHE_TTL_ANNOUNCEMENTS` | 1800s | 公告 |
| `_pools_cache` | `CACHE_TTL_POOLS` | 60s | 涨跌停池 |

## 缓存 Key 设计

| API Endpoint | Cache Key 格式 |
|-------------|---------------|
| `GET /stocks/{code}/dragon-tiger` | `f"dt:{code}:{trade_date}:{look_back}"` |
| `GET /dragon-tiger/daily` | `f"dtdaily:{trade_date}:{min_net_buy}"` |
| `GET /stocks/{code}/margin` | `f"margin:{code}:{page_size}"` |
| `GET /stocks/{code}/block-trade` | `f"block:{code}:{page_size}"` |
| `GET /stocks/{code}/holder-num` | `f"holder:{code}:{page_size}"` |
| `GET /stocks/{code}/dividend` | `f"div:{code}:{page_size}"` |
| `GET /stocks/{code}/fund-flow` | `f"ff:{code}"` |
| `GET /stocks/{code}/fund-flow/daily` | `f"ffd:{code}"` |
| `GET /hot/topics` | `f"hot:{date}"` |
| `GET /north-flow/realtime` | `"north:realtime"` |
| `GET /stocks/{code}/reports` | `f"rpt:{code}:{max_pages}"` |
| `GET /stocks/{code}/announcements` | `f"ann:{code}:{page_size}"` |
| `GET /pools` | `f"pool:{type}:{date}"` |

## 不加缓存的端点

以下端点因已有 SQLite 持久化，无需再加 TTLCache：
- `GET /stocks` — 数据量大，已通过 `stock_cache.get_stock_list()` 走 SQLite
- `GET /calendar` — 已通过 `get_cached_calendar()` 走 SQLite

## 修改文件

1. **`stock_data/api/cache.py`**
   - 新增 11 个 TTLCache 实例
   - 新增 11 个 `get_xxx_cache()` 访问器函数
   - 新增 13 个 `make_xxx_cache_key()` 函数

2. **`stock_data/api/routes.py`**
   - 在 13 个无缓存端点中增加缓存逻辑：
     - 检查 `is_cache_enabled()`
     - 构建 cache key 并检查命中
     - 正常处理后写入缓存

## 缓存命中日志

每个端点命中时输出：
```python
logger.info(f"[APICache] {cache_name} hit: {key}")
```

## 测试要点

- 验证各端点缓存未命中时正常获取数据
- 验证各端点缓存命中时直接返回
- 验证 TTL 过期后重新获取数据
- 验证 `ENABLE_API_CACHE=false` 时跳过缓存