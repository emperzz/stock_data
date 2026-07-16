# 项目架构审查报告

> 审查日期：2026-07-16
> 审查方式：5 路并行只读分析（核心编排 / 持久层 / 大型 fetcher / 剩余 fetcher+utils / API+测试）
> 规模：~27k LOC，~90 源文件，~110 测试文件，13 个数据源适配器

## 总体评价

这是一个**成熟度较高的项目**。四层架构（FastAPI → 纯计算指标层 → DataFetcherManager → Source Adapters）清晰，CLAUDE.md 文档与代码的契合度在同类项目中属上乘，测试矩阵对关键契约（capability 路由、manifest、effective_source、SSRF、装饰器）有针对性覆盖，xfail 自动降级 hook 设计优雅。

但也存在若干**真实可触发的缺陷**，其中 2 个为 critical（一个安全、一个数据完整性），需要在生产化前修复。报告按严重度排序。

---

## 一、Critical（生产化前必修）

### C1. SSRF 云元数据 IP 未拦截 — 可远程窃取实例凭据
- **位置**：`data_provider/utils/news_extractor.py:136-144`（`_PRIVATE_IP_RANGES` 缺 `169.254.0.0/16`）；暴露面 `api/routes/news.py:141` `GET /api/v1/news/content?url=...`
- **场景**：`/news/content` 接受任意用户 URL 服务端抓取。攻击者发 `?url=http://169.254.169.254/latest/meta-data/iam/security-credentials/<role>`，IMDSv1 直接返回 JSON，extractor 会解析并回吐 AWS/GCP/Azure 实例凭据。同样未拦：`100.64.0.0/10`(CGNAT)、`198.18.0.0/15`、IPv6 `fe80::/10`。
- **修复**：补 `169.254.0.0/16`、`100.64.0.0/10`、`198.18.0.0/15`、`fe80::/10` 到 `_PRIVATE_IP_RANGES`，并补对应回归测试。现有 `test_news_content_ssrf.py` 与代码共享同一盲点。

### C2. SQLite 共享单例连接在 FastAPI 线程池下非线程安全 — 并发写损坏数据
- **位置**：`data_provider/persistence/db.py:34` `get_connection()` 返回模块级单例 `_conn`（`check_same_thread=False`）
- **场景**：路由 handler 是同步 `def`，Starlette 用 40 线程池并发跑。多个线程拿到**同一个** Connection 对象。`with conn:` 只调 commit/rollback，不持锁；auto-BEGIN 事务是连接级而非线程级。线程 A 进入事务执行 DELETE，线程 B 也进入（无新 BEGIN）、执行自己的写、B 退出时 commit **提前提交了 A 未完成的 DELETE**，A 随后崩溃 → INSERT 永不执行 → 数据丢失。影响所有写路径：`update_cached_stocks` / `update_cached_boards` / `update_cached_board_stocks` / `save_pool` / `update_cached_calendar` / `upsert_membership_bulk`。
- **修复**：`threading.local()` 每线程连接 + WAL；或至少加一个模块级 `threading.Lock` 串行化所有写。并在 `get_connection()` 设 `PRAGMA journal_mode=WAL; PRAGMA busy_timeout=30000; PRAGMA synchronous=NORMAL`。

---

## 二、High

### H1. DNS-rebinding TOCTOU 绕过 SSRF IP 检查
- **位置**：`news_extractor.py:147-157`（`_is_private_ip`）+ `:506-514`（`requests.get`）
- **场景**：`_validate_url` 用 `socket.gethostbyname` 解析并校验，但 `requests.get` 会**独立再解析一次**。攻击者控制的 DNS 首次返回公网 IP（过校验）、二次返回 `127.0.0.1`/`169.254.169.254`（实际连接）。重定向后校验同样三次解析，与实际 TCP 连接 IP 不一致。现有 `test_rejects_dns_resolved_to_private_ip` 只 mock 成“始终私有”，未覆盖分裂解析。
- **修复**：解析一次得 IP，改写 URL 用该 IP 连接（pin）；或自定义 `HTTPAdapter` 在 connect 前重解析重校验。

### H2. `cache_endpoint` 忽略 `ENABLE_API_CACHE` 开关
- **位置**：`api/cache.py:311-358`
- **场景**：运维设 `ENABLE_API_CACHE=false` 调试 stale 数据，但只有 `cached_lookup`/`cached_store`（仅 /boards/.../pools 用）遵守。约 20 个 `@cache_endpoint` 装饰的路由（stocks 13、indices 2、data 3、news 4、cls 1）**继续命中缓存**——文档里的全局开关部分失效。
- **修复**：`wrapper` 首行加 `if not _ENABLE_CACHE: return func(*args, **kwargs)`。

### H3. 板块成分股陈旧行永不删除 — 幽灵成员累积
- **位置**：`persistence/board.py:1831`（`update_cached_board_stocks`）、`:1261`（`upsert_membership_bulk`）
- **场景**：两者用 `INSERT OR REPLACE`，从不 DELETE 已离开的股票。对比 `update_cached_stocks`/`save_pool` 都是 DELETE-then-INSERT。股票 X 离开板块 Y 后，旧行 `(Y, ths, X)` 永久残留。30 天后 `/boards/{code}/stocks` 返回 50 只（5 只陈旧）；`/stocks/{code}/boards` 返回该股几周前已退出的板块。
- **修复**：INSERT OR REPLACE 前在同事务内 `DELETE FROM stock_board_membership WHERE board_code=? AND source=?`。

### H4. 板块成分股上游失败时不回退陈旧缓存 — 有数据仍 5xx
- **位置**：`persistence/board.py:1046-1068`（`get_board_stocks` 非 quote 路径）
- **场景**：`needs_refresh=True` 时调 `fetch_board_stocks_with_zzshare_fallback` 打上游。THS 宕 10 分钟，期间每个 `/boards/{code}/stocks` 都 5xx，即使 SQLite 里有昨日成分股完全可用。对比 `pool_daily.get_pool`（`:327-336`）正确 catch `DataFetchError` 回退陈旧缓存——`get_board_stocks` 没学。
- **修复**：try/except `DataFetchError`，失败时回退 `_read_board_stocks_from_db(board_code, "ths")`。

### H5. Akshare 指数日线 volume 未换算成股 — 跨源 failover 100x 单位错配
- **位置**：`fetchers/akshare/index_norm.py:44-83`（`normalize_index_df` 无 `*100`）；对比 `akshare/fetcher.py:236`（股票日线有 `*100`）、`zhitu_fetcher.py:574`（指数有 `*100`）
- **场景**：指数 K 线经 Akshare(P3) 返回 volume 单位是“手”；failover 换到 Zhitu(P5) 是“股”。同一指数跨源出现 100x 跳变，`KLineData` 无 volume-unit 字段，客户端无法察觉。
- **修复**：`normalize_index_df` 加 `df["volume"] = df["volume"] * 100`（或核实 akshare 三家指数源单位并文档化）。

### H6. `_kline_with_index_dispatch` 透传 None — 静默打断 failover
- **位置**：`data_provider/base.py:414-421`；myquant `get_index_historical`(`:467-511`)、baostock/tushare 返回 `DataFrame | None`
- **场景**：dispatch helper 直接 `return index_fn(...)`。Myquant 在 SDK 不可用/空 df/异常时返回 `None`，该 `None` 直达 manager 调用方，绕过 `BaseFetcher.get_kline_data` 本会把 `raw_df is None` 转 `DataFetchError` 的逻辑。manager failover 期望 `DataFetchError` 才触发下一源；裸 `None` 不是异常 → failover 静默停止 → 调用方拿到 None → 下游 `.columns` 500。Tushare 的 `_fetch_index_kline` 正确 raise，唯独 Myquant 不一致。
- **修复**：`_kline_with_index_dispatch` 归一化 `df = index_fn(...); if df is None or df.empty: raise DataFetchError(...)`。

---

## 三、Medium

### M1. 空/None 结果被当失败计入熔断器
- **位置**：`manager.py:325-336`（`if _is_meaningful(result):` 在 325 行进入，empty 分支体在 330-336 行，`circuit_breaker.record_failure(...)` 在 335-336 行）
- **场景**：fetcher 返回 None/空 df（合理“无数据”：退市股、盘前查询）时，`record_failure` 把它当失败。3 次空结果就把该源对所有股票熔断 5 分钟。几次冷门股查询能让健康的 Tushare 全市场下线。
- **修复**：只在异常路径 record_failure，空结果不计。

### M2. `get_fetcher` 重复定义 — 首个是死代码
- **位置**：`manager.py:90-92`（被 `:133-166` 覆盖）
- **场景**：首个返回 `BaseFetcher|None` 不 raise 的版本不可达。维护者自上而下读，按首签名写 `if f is None:`，生产里却吃 `ValueError`。
- **修复**：删 `:90` 存根。

### M3. Manager ↔ 持久层双向依赖倒置
- **位置**：`manager.py:692,772` 懒导入 persistence；5 个 fetcher 也 import persistence
- **场景**：CLAUDE.md 声称“持久层依赖 manager，反之不行”。实际 manager 的 `get_trade_calendar`/`get_zt_pool` 反向懒导入 persistence；fetcher 底层也导入 persistence.board / trade_calendar。靠函数体内懒 import 避环，一旦有人改成顶层 import 或测试顺序变即 `ImportError`。换持久化后端（如 Postgres）需动 fetcher。
- **修复**：定义持久化 port/interface，manager 与 fetcher 依赖抽象；至少把 calendar/pool 缓存查询上移到路由层。

### M4. 装饰器顺序契约漂移 — 全部路由文件与文档相反
- **位置**：`stocks.py:86/95/100/101` 等所有路由文件；文档在 `errors.py:18-27`、`cache.py:336-341`
- **场景**：文档要求 `@endpoint_meta` 最内层（最靠近 def）。实际代码全部把 `@endpoint_meta` 放在 `@map_errors`/`@cache_endpoint` **之上**（即 endpoint_meta 是三者中最外）。当前“能用”是因为 `endpoint_meta.deco` 返回原 func——但文档与代码系统性不一致。
- **修复**：要么改文档匹配实际，要么改代码匹配文档。

### M5. 启动健全性检查与 manifest 的 `__wrapped__` 行走不一致
- **位置**：`explorer/__init__.py:100`（不 walk `__wrapped__`）vs `manifest.py:42-61`（walk）
- **场景**：当前因 M4 的实际顺序，`route.endpoint` 直接就是 REGISTRY key，两边都命中，不报错。但若有开发者按**文档**顺序写（endpoint_meta 最内），REGISTRY key 是原函数而 `route.endpoint` 是 map_errors wrapper → 健全性检查对每条这样的路由误报“缺 @endpoint_meta”，而 manifest 仍能解析。**文档顺序与健全性检查互斥**，是潜伏陷阱。
- **修复**：健全性检查改用 `_lookup_registry` / walk `__wrapped__`。

### M6. 板块持久化-only 路由违规
- **位置**：`api/routes/boards.py:944`（`get_board_history` 直接调 `manager.get_board_history`）、`:758`（`get_board_quote` 直接调 `manager.get_board_realtime`）、`:625,644`（`get_board_stocks` quote 子块直接调 manager）
- **场景**：契约要求板块路由 handler 走 `persistence.board`(`stock_board_cache.get_*`)，不直接调 manager。成分股 membership 块正确走 `stock_board_cache.get_board_stocks`(`:521`)，但 history/quote 的 payload 直达 manager。
- **修复**：把这三处也收口到 stock_board_cache（或明确文档豁免 history/quote）。

### M7. HTTPException 响应丢失 charset=utf-8 — 中文错误信息乱码
- **位置**：`server.py` 未注册 `HTTPException`/`StarletteHTTPException` handler
- **场景**：`_UTF8JSONResponse` 只覆盖 2xx 和 422。`map_errors` raise 的 503/400/500、以及路由级 404/422/400 全走 FastAPI 默认 handler，渲染成无 charset 的 `JSONResponse`。错误 detail 常含中文（`boards.py:547`、`cls.py:143` “No 财联社早报 article...”），客户端乱码。这正是当初修 mojibake 的初衷，422 补了、HTTPException 漏了。
- **修复**：注册 `StarletteHTTPException` handler 用 `_UTF8JSONResponse`。

### M8. Tencent 指数列映射 `amount→volume` 可疑
- **位置**：`fetchers/akshare/index_norm.py:28-31` `_INDEX_TX_MAP`
- **场景**：Sina/EM 映射 `volume→volume`，Tencent 映射 `amount→volume`，暗示腾讯源无 volume 列、用 amount 顶替。若 amount 实为成交额（元）而非成交量，经腾讯 fallback 路径的指数 K 线 volume 会填成货币值，量级差 1000x+，无错误信号。
- **修复**：探活 `stock_zh_index_daily_tx` 核实 amount 语义；若是额则丢弃或换算，并补真实 fixture。

### M9. ZZSHARE/THS 响应侧代码无防御性 normalize
- **位置**：`zzshare_fetcher.py:771/955/698/551`、`ths_fetcher.py:2455`（注：2116 是 `_normalize_hot_topic` 里的 `code` 字段——hot-topic **主题/概念代码**，非 stock_code，与 2455 的 `stock_code` 性质不同）
- **场景**：2026-06-25 修了不再加后缀，但这些方法仍**原样信任**上游返回裸 6 位。`get_all_stocks`(`:435`) 还在手动 `ts_code.split(".")[0]`，证明 SDK 某些端点会带后缀。上游改格式即静默复发。
- **修复**：响应侧每处代码 `normalize_stock_code()` 一行防御。

### M10. Zhitu 4 个方法 URL 插值前漏 normalize
- **位置**：`zhitu_fetcher.py:400,866,944,1026`（`get_stock_info`/`get_dividend`/`_fund_flow_records`/`get_holder_num_change`）
- **场景**：这些直接 `f"/hs/gs/gsjj/{stock_code}"` 插值，未 normalize。`/control/fetcher-test` 绕过路由层 normalize 传入 `600519.SH` → URL 404 → 误导性“malformed payload”。路由层目前安全，但不一致是潜伏 bug。
- **修复**：每方法首行 `code = normalize_stock_code(code)`。

### M11. 限流/反封禁部分实现 — 与文档契约不符
- **位置**：全 fetcher 层
- **场景**：CLAUDE.md 称“random 1.5-3.0s jitter, rotating UA pool”。实际：THS 直接 `requests.get` 用单一静态 UA、无 jitter；ZZSHARE/Akshare 是 SDK 无 UA 控制；Zhitu 仅 `json_get` 随机 UA；EastMoney curl_cffi 单一 UA + 仅 board clist 1-2s 页延迟。无任何 fetcher 有 1.5-3.0s 请求间 jitter。
- **修复**：要么改文档匹配实际，要么给 THS `_http_get` 加 jitter+UA 轮换（EastMoney curl_cffi 是金标准）。

### M12. `stock_board.platecode` 缺索引
- **位置**：`board.py:260-315` schema vs `:577` `_resolve_ths_cid_from_platecode`
- **场景**：热路径 `WHERE platecode=? AND source='ths'` 全表扫（~400-800 行），每次 THS 板块成分股 cache-miss 都打。启动 backfill 刷 380 板块时累积明显。
- **修复**：`CREATE INDEX idx_stock_board_platecode_source ON stock_board(platecode, source)`。

### M13. `to_tushare_format` 399xxx 指数 fallback 误后缀 `.SH`
- **位置**：`utils/code_converter.py:283-294`
- **场景**：未在 `CSI_INDEX_MAP` 的 CSI 指数 fallback 无条件返回 `.SH`。`399xxx`（创业板指 399006、深证成指 399001）是**深市**应为 `.SZ`。与已修的 Zhitu `000xxx→SZ` 同类 bug。Baostock/Myquant converter 都正确分流 00/399，唯独 Tushare fallback 错。主要 399xxx 在 map 内故少触发，但加新指数不扩 map 即静默路由到错 API 返回空。
- **修复**：mirror Baostock/Myquant：`00→.SH, 399→.SZ`。

### M14. Cninfo `_org_id` 误把北交所 920xxx 路由到深交所
- **位置**：`fetchers/cninfo_fetcher.py:36-43`
- **场景**：`startswith("6")→gssh0`、`startswith(("8","4"))→gsbj0`、else→`gssz0`。920 开头（北交所，`normalize.py:38` 声明）落到 else 变 `gssz0920xxx`，深交所 orgId 查北交所股票 → 公告静默空。
- **修复**：BJ 分支加 `"9"`：`startswith(("8","4","9"))→gsbj0`，或直接用 `code_to_exchange(code)` 派生。

### M15. SDK fetcher 共享全局 SDK 状态无并发守卫
- **位置**：`base.py:65-112` SDKFetcherMixin；`baostock_fetcher.py:56` bs.login 全局；`myquant_fetcher.py:159-166` gm.api.set_token 全局
- **场景**：`_init_lock` 只串行首次 init。之后所有 `bs.query_*`/`gm.api.history` 在模块全局 session 上无锁并发跑。Baostock 全局 query session 并发迭代有上游线程安全告警。无任何 `bs.logout()`（grep 确认），进程关闭泄漏 session。
- **修复**：每类 `threading.Lock` 串行化 SDK 调用，或文档限定单 worker 部署；加 shutdown hook `bs.logout()`。

### M16. ClsFetcher 无响应体大小上限
- **位置**：`cls_fetcher.py:300-321` `_http_get_text` 直接 `r.text` 全量入内存
- **场景**：news_extractor 有 5MiB 流式上限，CLS 没有。CLS 或 MITM 返回超大响应 → 无界内存增长。URL 内部构造非用户可控，故低于 news_extractor 面，但偏离项目自定的 bounded-read 约定。
- **修复**：`stream=True` + 上限（如 2MiB）。

### M17. Zhitu `get_holder_num_change` 符号逻辑反转
- **位置**：`zhitu_fetcher.py:1044-1048`
- **场景**：`"新增"→-change_num`、`"减少"→保持正`。股东数增加应为正、减少应为负，这里反了。“新增1702”→-1702，“减少28718”→+28718。
- **修复**：翻转：新增→正、减少→负；或核实 `bh` 真实语义并文档化。

### M18. `update_cached_board_stocks` TOCTOU — SELECT 在事务外
- **位置**：`board.py:1849-1877`
- **场景**：board 元数据 SELECT(`:1849`) 在 `with conn:`(`:1858`) 之外。另一线程在 SELECT 与 INSERT 间改/删 stock_board 行 → 写入陈旧 name/type。读时 LEFT JOIN(`:1417`) 缓解，但写时不一致。
- **修复**：SELECT 移入 `with conn:` 块。

---

## 四、Low（择要）

- **L1** TTLCache 单例在 FastAPI 线程池下非线程安全（`api/cache.py:23-66`）；cachetools TTLCache 非文档线程安全，GIL 下低概率非零。建议加锁。
- **L2** 无 cache-stampede 保护（无 singleflight）；TTL 到期 N 个并发同请求齐打上游。
- **L3** `_manager` 单例 init 无锁（`helpers.py:68-77`）；启动并发首请求可能双初始化 ~13 fetcher（浪费 SDK login）。
- **L4** `get_report_pdf` 全空时 raise 空 error 列的 DataFetchError（`manager.py:1203-1223`），503 无诊断行；应 `allow_none=True`→404。
- **L5** THS `get_hot_topics`/`get_north_flow` 吞所有异常返回 `[]`（`ths_fetcher.py:2110-2112,2156-2158`），被 failover 当成功空数据，下一源（ZZSHARE P2 可服务 HOT_TOPICS）永不被试。EastMoney fetcher 已重构为子包（`_boards_mixin`/`_news_mixin`/`_endpoints`/`_cffi_json`），原 `_datacenter_query` 函数名在当前代码中不存在；同等"吞异常→[]"模式可能存在于某个 mixin 的某个端点，需具体定位后再补。
- **L6** 死代码 `upsert_membership_for_stock_boards`（`board.py:1319-1384`）零运行时调用方。
- **L7** 持久层 import `fastapi.FastAPI`（`backfill.py:21`）—— 框架向上耦合，应 `TYPE_CHECKING`。
- **L8** `_schema_initialized_paths` check-then-add 轻微竞态（DDL 幂等故良性）。
- **L9** news_extractor 自定义单一 UA 而非用共享 `random_ua()` 池（`news_extractor.py:29-32`）。
- **L10** Yfinance 近似 `amount = volume * close`（`:174-175`），A 股 failover 到 Yfinance 时 amount 单位/量级与 Baostock/Akshare/Tushare 约定不同，跨源客户端会漂移。
- **L11** `is_hk_market` 把任意裸 5 位数字串当 HK（`normalize.py:123-131`），`to_tencent_prefix` 又说裸 5 位 0-4 开头是深市——两函数分类不一致，仅非规范输入触发。
- **L12** `test_utf8_charset_response.py::test_kline_serves_utf8_charset` 未标 live_network 却打真实 manager，无可用 fetcher 时会 F 而非 xfail。

---

## 五、与文档契约的偏离（汇总）

| 契约（CLAUDE.md） | 实际 | 来源 |
|---|---|---|
| `ENABLE_API_CACHE` 全局开关 | 仅 boards-pools 路径遵守，`@cache_endpoint` 路径忽略 | A-H2 |
| 持久层依赖 manager，反之不行 | 双向（manager 懒导入 persistence，fetcher 也导入） | A-M3 / B |
| `effective_source` = 实际服务上游的 fetcher | cache hit 时返回 `"ths"`（无上游调用） | B |
| 装饰器 `@endpoint_meta` 最内层 | 全部路由文件实际最外 | E-sub1-M4 |
| 限流 1.5-3.0s jitter + UA 轮换 | 仅部分实现，无任何 fetcher 达 1.5-3.0s | C-M11 |
| SSRF 拦截私有 IP 段 | 漏 `169.254.0.0/16` 等云元数据段 | D-C1 |

---

## 六、结构性技术债

1. **ths_fetcher.py 2494 行是最大 fetcher**，单类承载 7 个 capability。应效仿 eastmoney 的 mixin 拆分：`_board_mixin`(~900 行)、`_news_mixin`(~450)、`_signal_mixin`(~80)、`fetcher`(~200)。`_parse_ths_board_stocks_row` 的模块级函数 + `staticmethod` 挂载（`:2494`）是可测性 workaround，mixin 化后可消。
2. **无迁移框架**：schema 演进靠 `CREATE IF NOT EXISTS` + 临时 `ALTER TABLE`，无版本跟踪。`_migrate_zzshare_special_to_concept` 每次 `init_schema()` 全表扫。生产升级有风险。
3. **无外键 enforcement**：`PRAGMA foreign_keys=ON` 从未设，stock_board 与 stock_board_membership 无 FK。删 board 行留孤儿 membership，靠 LEFT JOIN 防御性掩盖。
4. **两套连接模式并存**：请求路径用单例、backfill 线程用独立连接。应统一为线程局部或连接池。
5. **无统一 HTTP 超时策略**：http.py 10s、cls/cninfo/baidu/news_extractor 15s、tencent 10s，全有界但无中心常量。建议 `DEFAULT_HTTP_TIMEOUT`。
6. **manager 1288 行**：多为薄 wrapper lambda，真正复杂度集中在 `_with_failover`/`_with_source`/`_candidates`。是宽而浅的 god-object，可接受，但 capability→method 派发表可压平。

---

## 七、测试策略评估

**优点**：xfail 自动降级 hook 优雅（`conftest.py` + `_network_guard.py` 单点演化上游错误分类）；indicator 测试数学严谨（warmup null、单调性、参数拒绝）；`test_manifest_resolve_fetchers.py` 环境隔离（patch 掉真实 fetcher）；fixture JSON 是真实上游形状（zhitu 测试注明探活日期）。live_network 仅 ~12%，离线 ~88%，默认 `not live_network` 快循环 ~1 分钟，平衡健康。

**缺口**：
1. 装饰器顺序反序回归无专门测试（靠启动健全性检查 mitigate）。
2. `/control/fetcher-test` localhost 强制未测（无测试发非 localhost Host 断言拒绝）。
3. `requires_token` marker 声明却无任何测试使用（token 门控靠 ad-hoc `is_available()`）。
4. 无中心 manager-mock fixture，各文件自 roll `FakeFetcher`/`_MockFetcher` 有重复。
5. SSRF 测试与代码共享 `169.254` 盲点。

---

## 八、建议修复优先级

| 优先级 | 项 | 工作量 |
|---|---|---|
| P0 立即 | C1 SSRF 云元数据、C2 SQLite 线程安全 | 各 0.5-1 天 |
| P1 本周 | H1 DNS-rebinding、H2 cache 开关、H3 陈旧行删除、H4 陈旧缓存回退 | 各 0.5 天 |
| P2 近期 | H5 akshare 指数 volume、H6 None→DataFetchError | 各 0.5 天 |
| P3 排期 | M1-M18（熔断计数、装饰器文档对齐、charset、限流、索引、converter 后缀、orgId、SDK 并发…） | 多为 1-3 行到半天 |
| P4 技术债 | ths mixin 拆分、迁移框架、统一连接/超时策略 | 各 1-3 天 |

---

---

## 九、本地个人项目前提下的修订（2026-07-16 补）

本节根据"**本地个人项目**"前提（server 默认绑 `127.0.0.1`、单用户、低并发、SQLite 文件可重建、无多 worker 部署）对前文定级重审。`server.py:261` 已确认默认 `SERVER_HOST=127.0.0.1`，外部攻击者默认无法触达任何端点。

### 定级调整

| 编号 | 原级 | 修订级 | 修订理由 |
|---|---|---|---|
| **C1 SSRF 云元数据** | critical | **low（条件性 medium）** | 默认 localhost 下攻击者无法触达 `/news/content`。仅当用户改 `SERVER_HOST=0.0.0.0` 暴露公网/局域网，或 OpenClaw agent 被诱导抓取不可信 URL 时才相关。仍是"一行修复"，顺手做即可，但不再是 critical。 |
| **C2 SQLite 线程安全** | critical | **medium** | 单用户低并发，并发写触发概率低；即便损坏，DB 有 `backfill.py`/`build_membership_index.py` 可重建。仍是真 bug，且 WAL+busy_timeout 是低成本健壮性提升，建议做。 |
| **H1 DNS-rebinding** | high | **low** | 同 C1 前提——localhost 不对外则无攻击面。随 C1 一起处理即可。 |
| **H2 cache 开关** | high | **medium** | 仅影响"自己调试时设了开关发现不生效"的体验，无数据风险。 |
| **H3 陈旧行永不删除** | high | **high（维持）** | 与是否本地**无关**——单用户长期跑更易中招（无人盯监控发现板块成分静默漂移）。反而更要紧。 |
| **H4 板块失败不回退缓存** | high | **medium** | 本地偶发上游宕时体验差，无生产 SLA 压力。 |
| **H5 akshare 指数 volume 单位** | high | **medium** | 数据正确性真问题，但需 akshare(P3)→zhitu(P5) 指数 K 线 failover 才触发，面窄。 |
| **H6 None 透传打断 failover** | high | **medium** | 仅 Myquant(P9 last-resort) 指数 K 线路径，触发面极窄。 |
| **M7 charset HTTPException** | medium | **low** | 本地自己看错误信息乱码，烦但不致命。 |
| **M11 限流部分实现** | medium | **medium（维持）** | 反而对个人更重要：单 IP 高频调 THS 直接封 IP，无多 IP 可换。THS 直连 `requests.get` 单一静态 UA 是最弱环节。 |
| **M15 SDK 并发守卫** | medium | **low** | 单用户低并发几乎不触发 Baostock 全局 session 并发告警。 |

### 反而更需要关注的（本地前提放大）

- **H3**（陈旧行累积）：个人长期运行、无监控，板块成分静默腐化最难发现。
- **M1**（空结果计熔断）：自己查退市/冷门股会把健康源（Tushare）整市场熔断 5 分钟，单用户场景更容易亲自踩到。
- **M13/M14**（converter 399xxx 后缀 / Cninfo 北交所 orgId）：个人扩展新股票/指数时静默返回空，最易在"为什么这个股没数据"上浪费调试时间。
- **文档契约偏离**（装饰器顺序、限流、持久层方向、effective_source）：误导"未来的自己"成本高，建议优先对齐文档（改文档零风险）。

### 降为"可选改进"的结构性债（YAGNI）

以下按公网生产标准算"债"，本地个人项目下属锦上添花，**不强求**：
- 迁移框架、外键 enforcement、统一连接池——个人 DB 可重建，schema 稳定后低风险。
- `ths_fetcher.py` mixin 拆分——纯可读性，2494 行能跑就先跑。
- 统一 HTTP 超时常量——各路径已分别有界（10-15s）。
- cache-stampede singleflight、`_manager` 单例加锁——单用户低并发下近乎无收益。

### 修订后建议优先级

| 优先级 | 项 | 理由 |
|---|---|---|
| **P0 顺手做** | C1 补 IP 段、M13/M14 converter/orgId 后缀、M1 空结果不计熔断 | 一行到几行；防"自己调试踩坑"与"静默空数据" |
| **P1 本周** | H3 陈旧行 DELETE、H2 cache 开关、文档契约对齐（装饰器/限流/方向） | 数据正确性 + 避免误导自己 |
| **P2 有空** | C2 SQLite WAL+锁、H5/H6 volume/None、M11 THS 限流 | 健壮性与反封 |
| **P3 可选** | 其余 M 项、结构性债 | YAGNI，按需 |

> **一句话修订**：critical 从 2 个降到 0 个（安全面随 localhost 默认绑定而消解，数据完整性面降为可重建的 medium）；真正仍需上心的不是"生产化"，而是**"静默数据错（H3/M1/M13/M14）"** 和**"文档误导自己"**——这两类对本地长期单用户反而最致命。

*报告由 5 路并行只读分析综合而成；所有发现均经阅读实际代码核实，附 file:line。第九节为本项目实际语境（本地个人项目）的定级修订。*
