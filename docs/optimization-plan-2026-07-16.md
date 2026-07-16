# 优化建议方案

> 基于《项目架构审查报告》第九节（本地个人项目修订）的 P0–P2 项
> 日期：2026-07-16
> 前提：本地个人项目，server 默认 `SERVER_HOST=127.0.0.1`，单用户低并发，SQLite 可重建

每项给出：**现状代码（核实过 file:line）→ 问题 → 建议改法 → 验证方式**。所有"建议代码"为可直接落地的 diff 级片段，非伪码。

---

## P0 · 顺手做（一行到几行，防自己踩坑）

### P0-1 · SSRF 补云元数据 IP 段（原 C1）

**现状** `data_provider/utils/news_extractor.py:136-144`

```python
_PRIVATE_IP_RANGES = [
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("0.0.0.0/8"),
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("fc00::/7"),
]
```

**问题**：漏 `169.254.0.0/16`（云元数据）、`100.64.0.0/10`（CGNAT）、`198.18.0.0/15`（benchmark）、IPv6 `fe80::/10`（link-local）。默认 localhost 下攻击者打不到，但若改 `SERVER_HOST=0.0.0.0` 或 OpenClaw agent 被诱导抓不可信 URL，`169.254.169.254` 可泄实例凭据。

**建议**：

```python
_PRIVATE_IP_RANGES = [
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("169.254.0.0/16"),   # link-local / cloud metadata
    ipaddress.ip_network("100.64.0.0/10"),     # CGNAT
    ipaddress.ip_network("198.18.0.0/15"),     # benchmarking
    ipaddress.ip_network("0.0.0.0/8"),
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("fc00::/7"),
    ipaddress.ip_network("fe80::/10"),         # IPv6 link-local
]
```

**验证**：在 `tests/test_news_content_ssrf.py` 补 `test_rejects_cloud_metadata`（断言 `169.254.169.254` 被拒），与现有 `test_rejects_10_dot` 同构。

---

### P0-2 · Tushare 399xxx 指数 fallback 后缀修正（原 M13）

**现状** `data_provider/utils/code_converter.py:283-294`

```python
    if is_index_code(code):
        from ..fetchers.index_symbols import CSI_INDEX_MAP, get_index_type
        index_type = get_index_type(code)
        if index_type != "csi":
            raise ValueError(f"Tushare does not support {index_type} index {code}")
        entry = CSI_INDEX_MAP.get(code)
        if entry is not None:
            bs_symbol = entry[0]
            parts = bs_symbol.split(".")
            return f"{parts[1]}.{parts[0].upper()}"
        return f"{code}.SH"          # ← 399xxx 深市指数被误后缀 .SH
```

**问题**：未在 `CSI_INDEX_MAP` 的 CSI 指数 fallback 无条件 `.SH`。`399xxx`（创业板指 399006、深证成指 399001）是深市应为 `.SZ`。与已修的 Zhitu `000xxx→SZ` 同类 bug。Baostock/Myquant converter 已正确分流 00/399，唯独 Tushare fallback 错。加新指数不扩 map 即静默路由到错 API 返回空。

**建议**（mirror `to_baostock_format:83-86` 的分流逻辑）：

```python
        entry = CSI_INDEX_MAP.get(code)
        if entry is not None:
            bs_symbol = entry[0]
            parts = bs_symbol.split(".")
            return f"{parts[1]}.{parts[0].upper()}"
        # 未在 map 的 CSI 指数：00 开头→上交所, 399 开头→深交所
        if code.startswith("399"):
            return f"{code}.SZ"
        return f"{code}.SH"
```

**验证**：在 `tests/test_code_converter.py` 补 `test_tushare_unmapped_399_is_sz` 断言 `to_tushare_format("399006") == "399006.SZ"`。

---

### P0-3 · Cninfo 北交所 920xxx orgId 修正（原 M14）

**现状** `data_provider/fetchers/cninfo_fetcher.py:36-43`

```python
    def _org_id(self, code: str) -> str:
        """Build orgId for cninfo API."""
        if code.startswith("6"):
            return f"gssh0{code}"
        elif code.startswith(("8", "4")):
            return f"gsbj0{code}"
        else:
            return f"gssz0{code}"          # ← 920xxx 北交所落到这里变 gssz0
```

**问题**：北交所 920 开头（`normalize.py:38` 声明的 `A_SHARE_STOCK_PREFIXES`）走 else 变 `gssz0920xxx`，深交所 orgId 查北交所股票 → 公告静默空。

**建议**（最小改）：

```python
        elif code.startswith(("8", "4", "9")):
            return f"gsbj0{code}"
```

**更稳的改法**（推荐，用已有的 `code_to_exchange` 派生，消除前缀硬编码漂移）：

```python
    def _org_id(self, code: str) -> str:
        """Build orgId for cninfo API."""
        ex = code_to_exchange(code)  # 'SH' | 'SZ' | 'BJ' | None
        if ex == "SH":
            return f"gssh0{code}"
        if ex == "BJ":
            return f"gsbj0{code}"
        return f"gssz0{code}"  # SZ 及未知
```

需 `from ..utils.normalize import code_to_exchange`（确认该函数存在；若名为 `code_to_exchange` 不可用则用前缀法）。

**验证**：补 `tests/test_cninfo_fetcher.py::test_org_id_bj_920` 断言 920xxx → `gsbj0...`。

---

### P0-4 · 空结果不计熔断（原 M1，改设计权衡）

**现状** `data_provider/manager.py:325-336`

```python
            if _is_meaningful(result):
                logger.info(f"[Manager] {fetcher.name} succeeded for {op_label}")
                if circuit_breaker is not None:
                    circuit_breaker.record_success(fetcher.name)
                return (result, fetcher.name) if return_source else result
            # Result is None/empty — remember the last empty result (prefer
            # [] over None for downstream compatibility) and treat as soft
            # failure for circuit breaker.
            if result is not None:
                last_empty_result = result
            if circuit_breaker is not None:
                circuit_breaker.record_failure(fetcher.name)   # ← 空结果也算失败
```

**问题（设计权衡，非笔误）**：当前注释明确"treat as soft failure"——意图是防"上游持续返回空但无异常"的僵死。代价：查退市/冷门股，该 fetcher 合理返回空，却 `record_failure`。3 次空结果就把该源（如 Tushare）整市场熔断 5 分钟。**单用户更容易亲自踩到**（无监控发现"怎么 Tushare 全挂了"）。

**权衡分析**：
- 保留当前行为：防上游静默僵死，但误伤冷门股查询。
- 空结果不计熔断：冷门股查询不再误伤整市场；但若上游真的"静默返回空"则不会被熔断保护（靠 failover 自然换源 + 路由层 TTL 缓存兜底）。

对本地单用户，**空结果不计熔断更合理**——静默僵死的概率低于冷门股查询频率，且 failover 已能换源。

**建议**：

```python
            # Result is None/empty — remember the last empty result (prefer
            # [] over None for downstream compatibility). Do NOT record a
            # circuit-breaker failure: an empty result usually means "this
            # fetcher has no data for this symbol" (delisted / illiquid /
            # pre-market), not "the source is broken". Recording it would
            # trip the breaker for the whole market after a few cold-stock
            # queries. Genuine upstream failures raise exceptions, which the
            # except branch above records.
            if result is not None:
                last_empty_result = result
            # (no record_failure here — see comment)
```

即删除 `if circuit_breaker is not None: circuit_breaker.record_failure(fetcher.name)` 这两行（:335-336）。

**验证**：`tests/test_manager_two_stage_filter.py` 或新增 `test_empty_result_does_not_trip_breaker`——构造一个 fetcher 返回 `[]`，断言 `breaker.is_available(name)` 仍为 True。

> 注意：审查报告里对 M1 还有"`get_report_pdf` 全空 raise 空 error"（L4）等关联项，本次 P0 只动空结果熔断这一处；其余见 P2/P3。

---

## P1 · 本周（数据正确性 + 文档对齐）

### P1-1 · 板块成分股陈旧行 DELETE（原 H3，维持 high）

**现状** `data_provider/persistence/board.py:1858-1877`（`update_cached_board_stocks`）与 `:1261`（`upsert_membership_bulk`）均用 `INSERT OR REPLACE`，无 DELETE。

```python
    try:
        with conn:
            cursor = conn.cursor()
            cursor.executemany(
                """INSERT OR REPLACE INTO stock_board_membership
                   (board_code, source, stock_code, stock_name,
                    board_name, board_type, subtype, refreshed_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)""",
                [...]
            )
```

**问题**：股票 X 离开板块 Y 后，旧行 `(Y, ths, X)` 永不删除。30 天后 `/boards/{code}/stocks` 返回 50 只（5 只陈旧）；`/stocks/{code}/boards` 返回几周前已退出的板块。单用户长期跑无监控，最难发现。

**建议**（`update_cached_board_stocks`，在 executemany 前加 DELETE，同事务）：

```python
    try:
        with conn:
            cursor = conn.cursor()
            # Purge stale members that left the board upstream, so the cache
            # reflects the current snapshot rather than a monotonic union of
            # all historical members.
            cursor.execute(
                "DELETE FROM stock_board_membership WHERE board_code = ? AND source = ?",
                (board_code, source),
            )
            cursor.executemany(
                """INSERT OR REPLACE INTO stock_board_membership ...""",
                [...]
            )
```

`upsert_membership_bulk`（:1261）同理，在 executemany 前加同 board_code+source 的 DELETE。

**注意**：`upsert_membership_bulk` 用于 backfill 全量重建（一次写一个 board 的全部成员），DELETE-then-INSERT 语义正确；但要确认调用方不会"分批增量"调用它（若分批，DELETE 会误删前批）。grep 确认调用方为 backfill.py / build_membership_index.py 的"每 board 全量"路径即可。

**验证**：新增 `tests/test_board_purge_stale_members.py`——先写 3 成员，再 refresh 写 2 成员（含 1 个新、1 个旧离开），断言表里只剩 refresh 的 2 行。

---

### P1-2 · `cache_endpoint` 遵守 `ENABLE_API_CACHE`（原 H2）

**现状** `api/cache.py:345-357`（注意：是 `api/` 目录而非 `data_provider/` 目录）

```python
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            cache = cache_fn(*args, **kwargs)
            cache_key = key_builder(*args, **kwargs)
            if cache_key in cache:
                logger.info(f"[APICache] {hit_label} hit: {cache_key}")
                return cache[cache_key]
            result = func(*args, **kwargs)
            cache[cache_key] = result
            return result
        return wrapper
```

`_ENABLE_CACHE`（cache.py:20）已被 `cached_lookup`/`cached_store`（:291,:305）用，但 `cache_endpoint` 的 wrapper 漏了。

**问题**：设 `ENABLE_API_CACHE=false` 调试 stale 数据时，约 20 个 `@cache_endpoint` 路由仍命中缓存。

**建议**（首行加守卫，与 cached_lookup 同构）：

```python
        @wraps(func)
        def wrapper(*args, **kwargs):
            if not _ENABLE_CACHE:
                return func(*args, **kwargs)
            cache = cache_fn(*args, **kwargs)
            cache_key = key_builder(*args, **kwargs)
            ...
```

**验证**：`tests/test_api_cache.py` 补 `test_cache_endpoint_respects_disable`——monkeypatch `_ENABLE_CACHE=False`，断言路由实际调用下层（用 spy 计数）。

---

### P1-3 · 文档契约对齐（原 M4 / M5 / M11 / 持久层方向）

文档与代码系统性不符，**改文档零风险**，避免误导"未来的自己"。逐项：

**a. 装饰器顺序（M4/M5）**

`CLAUDE.md` + `api/routes/errors.py:18-27` + `api/cache.py:336-341` 称 `@endpoint_meta` 最内层。实际全部路由文件把它放最外（`@router.get` 外、`@map_errors`/`@cache_endpoint` 内）。当前靠 `endpoint_meta.deco` 返回原 func 才没爆。

建议二选一：
- **改文档**（推荐，零代码风险）：把 `errors.py`/`cache.py` 的 Usage 示例和 CLAUDE.md "Anti-patterns" 那条改成"实际顺序"——`@endpoint_meta` 在 `@map_errors`/`@cache_endpoint` 之上。
- 同时（M5）让 `explorer/__init__.py:100` 的启动健全性检查也走 `manifest._lookup_registry` 的 `__wrapped__` walk，消除"按文档写就误报"的潜伏陷阱。

**b. 限流（M11）**

CLAUDE.md 称"random 1.5-3.0s jitter, rotating UA pool"。实际仅部分实现。建议改文档为："限流为部分实现：EastMoney 用 curl_cffi 浏览器指纹 + board clist 1-2s 页延迟；THS 直连 `requests.get` 单一静态 UA；SDK 源（Tushare/Baostock/Myquant/Akshare）无 UA 控制。统一 1.5-3.0s 全局 jitter 为待办。"

**c. 持久层依赖方向（M3）**

CLAUDE.md 称"persistence depends on manager, not vice versa"。实际双向（manager.py:692,772 懒导入 persistence；5 个 fetcher 也导入 persistence）。建议改文档为："persistence 与 manager 双向耦合（manager 懒导入 persistence 的 calendar/pool 缓存查询；fetcher 也导入 persistence.board/trade_calendar）。靠函数体内懒 import 避环。若未来换持久化后端，需一并改 fetcher。"

**d. effective_source on cache hit（B 报告偏离）**

CLAUDE.md 称 effective_source = "实际服务上游的 fetcher"。cache hit 时返回 `"ths"`（无上游调用）。建议文档补注："cache hit 时 effective_source 返回缓存 key 的源标签 `ths`（非真实上游调用）；用 `data_source=='persistence'` 区分 cache hit。"

---

## P2 · 有空（健壮性与反封）

### P2-1 · SQLite WAL + busy_timeout（原 C2 降级）

**现状** `data_provider/persistence/db.py:34` 单例 `_conn = sqlite3.connect(get_db_path(), timeout=30, check_same_thread=False)`，FastAPI 40 线程池下共享。

**问题**：`with conn:` 不持锁，事务连接级。并发写时线程 B 的 commit 可能提前提交线程 A 未完成的 DELETE（数据丢失）。本地单用户触发概率低，但低成本提升。

**建议**（最小改，渐进）：

```python
# db.py get_connection()
_conn = sqlite3.connect(get_db_path(), timeout=30, check_same_thread=False)
_conn.execute("PRAGMA journal_mode=WAL")
_conn.execute("PRAGMA busy_timeout=30000")
_conn.execute("PRAGMA synchronous=NORMAL")
_conn.row_factory = sqlite3.Row
```

WAL 让读写不互斥（读不阻塞写、写不阻塞读），显著降并发冲突。但 WAL 不解决"同连接多线程事务交错"——彻底解决需**每线程独立连接**：

```python
import threading
_local = threading.local()

def get_connection() -> sqlite3.Connection:
    conn = getattr(_local, "conn", None)
    if conn is None:
        conn = sqlite3.connect(get_db_path(), timeout=30, check_same_thread=False)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=30000")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.row_factory = sqlite3.Row
        _local.conn = conn
    return conn
```

> 注意：改 `threading.local` 后，`init_schema` 的 `_schema_initialized_paths` 守卫仍有效（per-path 而非 per-conn），但每个线程首次写会各自建连。`STOCK_DB_INIT=true` 的 DROP+recreate 仍只在主线程 lifespan 跑。落地前跑全套测试确认无回归。

**验证**：`tests/test_board_membership_double_write.py` 已存在——确认改后仍绿；补一个并发写测试（两线程同时 update 不同 board，断言无 "database is locked" 且数据正确）。

---

### P2-2 · Akshare 指数 volume 换算（原 H5）

**现状** `data_provider/fetchers/akshare/index_norm.py:44-83` `normalize_index_df` 无 `*100`；对比股票日线（`akshare/fetcher.py:236` 有 `*100`）和 Zhitu 指数（`zhitu_fetcher.py:574` 有 `*100`）。

**问题**：Akshare(P3) 指数 volume 单位"手"，failover 到 Zhitu(P5) 是"股"，跨源 100x 跳变，无 volume-unit 字段客户端无法察觉。

**建议**：

```python
# normalize_index_df, 数值列 coerce 之后
if "volume" in df.columns:
    df["volume"] = df["volume"] * 100  # 手 → 股，与 zhitu/股票日线统一
```

**前置核实**：akshare `stock_zh_index_daily` 三家源（Sina/Tencent/EM）单位是否一致为"手"。先写一个 `live_network` 探活脚本取 `000300` 日线，打印 volume 量级确认（应与 Tushare 同指数手数一致）。若某家源已是"股"则只对该源换算。

**验证**：`tests/test_volume_unit_unification.py` 已存在——补指数 K 线 case，断言 akshare 与 zhitu 同指数 volume 量级一致。

---

### P2-3 · None → DataFetchError 归一化（原 H6）

**现状** `data_provider/base.py:414-421` `_kline_with_index_dispatch` 直接 `return index_fn(...)`；Myquant `get_index_historical`（`myquant_fetcher.py:467-511`）在 SDK 不可用/空 df/异常时返回 `None`。

**问题**：裸 `None` 直达 manager 调用方，绕过 `BaseFetcher.get_kline_data` 本会把 `raw_df is None` 转 `DataFetchError` 的逻辑。failover 期望 `DataFetchError` 才换源；`None` 非异常 → failover 静默停止 → 下游 `.columns` 500。

**建议**（`base.py:_kline_with_index_dispatch` 归一化）：

```python
    def _kline_with_index_dispatch(self, stock_code, ...):
        index_fn = self.get_index_historical  # 或具体方法
        df = index_fn(stock_code, ...)
        if df is None or (hasattr(df, "empty") and df.empty):
            raise DataFetchError(
                f"[{self.name}] index kline returned no data for {stock_code}"
            )
        return df
```

> 优先改这一处（归一化所有 index fetcher 的 None）。若不想动 base，则改 myquant `get_index_historical` 在返回 None 处 raise DataFetchError（与 Tushare `_fetch_index_kline` 一致）。后者更局部、风险更低，推荐。

**验证**：`tests/test_myquant_fetcher.py` 补 `test_index_kline_unavailable_raises`——mock SDK 不可用，断言 raise DataFetchError 而非返回 None。

---

### P2-4 · THS 限流加固（原 M11 局部）

**现状** `ths_fetcher.py` 直连 `requests.get` 用单一静态 `THS_UA`，无请求间 jitter。个人单 IP 高频调 THS board 端点易被封。

**建议**：

1. THS `_http_get` 改用 `utils/http.py` 的 `json_get`（已有 UA 轮换 + timeout + DataFetchError 映射）。
2. board 分页（`get_board_stocks` 翻 5 页）页间加 `time.sleep(random.uniform(1.5, 3.0))`。

```python
import time, random
# 每页之间
time.sleep(random.uniform(1.5, 3.0))
```

**验证**：`tests/test_ths_fetcher.py` 现有测试用 mock，jitter 不影响断言（mock 不真 sleep）。补一个断言"调了 5 页则 sleep 被调 4 次"。

---

## P3 · 可选（YAGNI，按需）

以下按公网生产标准算"债"，本地个人项目属锦上添花。**默认不主动做**——按"遇到再修"或重构顺带做。分四类，每条给出现状依据、最小改法、为何仍属 P3。

### P3-a · 数据正确性（面窄但偶发踩坑，遇再说）

#### P3-a1 · 板块上游失败回退陈旧缓存（原 H4，降 medium）

**现状** `persistence/board.py:1051-1068`（`get_board_stocks` 非 quote 路径）直接调 `fetch_board_stocks_with_zzshare_fallback`，无 try/except。该 helper 内部已有 ZZSHARE→THS fallback，both-fail 时 raise `DataFetchError` → 路由层 503。对比 `pool_daily.get_pool`（`:327-336`）正确 catch 后回退陈旧缓存。

**问题**：THS 宕 10 分钟，期间每个 `/boards/{code}/stocks` 都 5xx，即使 SQLite 有昨日成分股可用。本地偶发上游宕时体验差，但无生产 SLA 压力。

**建议**：

```python
# board.py get_board_stocks, :1051 处
try:
    stocks, origin, effective_source, reason = fetch_board_stocks_with_zzshare_fallback(
        board_code=board_code, source=source, include_quote=False, manager=manager,
    )
except DataFetchError as e:
    if cached_full:
        logger.warning(
            f"[BoardCache] upstream failed for {board_code}, serving stale cache: {e}"
        )
        return cached_full, "persistence", "ths", "stale_after_upstream_failure", False, cached_count
    raise
```

> 仍属 P3：本地用户可手动 `?refresh=true` 重试，陈旧数据也未必有害；非"静默错"而是"明确 5xx"。优先级低于 H3（H3 是静默错）。

---

#### P3-a2 · ZZSHARE/THS 响应侧代码防御性 normalize（原 M9，medium）

**现状**（据子审查核实）`zzshare_fetcher.py:771/955/698/551`、`ths_fetcher.py:2455`（注意：2116 是 `_normalize_hot_topic` 里的主题 code，不是 stock_code）响应侧代码原样信任上游返回裸 6 位，无 `normalize_stock_code()`。`get_all_stocks`(`zzshare_fetcher.py:435`) 还在手动 `ts_code.split(".")[0]`，证明 SDK 某些端点会带后缀。

**问题**：上游改格式即静默复发 2026-06-25 修过的后缀泄漏 bug。但当前上游确实返回裸码，非现行故障。

**建议**：每个响应侧 code 一行 `normalize_stock_code(...)`。

```python
# zzshare_fetcher.py:771 等
stock_code = normalize_stock_code(str(row.get("stock_code", "")).strip())
```

> 仍属 P3：现行无触发；纯防御性。若 P0-2/P0-3 一起做 fetcher 边界加固时顺带扫一遍即可。

---

#### P3-a3 · Zhitu 4 方法 URL 插值前漏 normalize（原 M10，medium）

**现状**（据子审查）`zhitu_fetcher.py:400,866,944,1026`（`get_stock_info`/`get_dividend`/`_fund_flow_records`/`get_holder_num_change`）直接 `f"/hs/gs/gsjj/{stock_code}"` 插值，未 normalize。对比 `get_realtime_quote`(:140) 用 `_convert_code`、index 方法(:467,531) 用 `normalize_stock_code`。

**问题**：`/control/fetcher-test` 绕过路由层 normalize 传 `600519.SH` → URL 404 → 误导性"malformed payload"。路由层目前安全。

**建议**：每方法首行 `code = normalize_stock_code(code)`。

> 仍属 P3：生产路由层已 normalize，仅影响 debug 端点体验。

---

#### P3-a4 · Zhitu holder_num_change 符号反转（原 M17，medium）

**现状**（据子审查）`zhitu_fetcher.py:1044-1048`：`"新增"→-change_num`、`"减少"→保持正`。docstring 称"matches the docs example"。

**问题**：股东数增加应为正、减少应为负，这里反了。但 docstring 暗示可能有意（与某文档示例对齐）。

**建议**：**先核实上游 `bh` 字段真实语义**（live 探活取一只"新增"/"减少"股票，对比其他源如 EastMoney 的同字段符号），再决定翻转与否。不要盲改——可能 docstring 记录的"docs example"是上游约定。

```python
# 待核实后，若确认应翻转：
if "新增" in bh_raw and change_num > 0:
    pass  # 新增为正
elif "减少" in bh_raw and change_num > 0:
    change_num = -change_num  # 减少为负
```

> 仍属 P3：holder_num 是低频查询，且需先核实语义，不能盲改。

---

#### P3-a5 · Tencent 指数 `amount→volume` 映射可疑（原 M8，medium）

**现状**（据子审查）`akshare/index_norm.py:28-31` `_INDEX_TX_MAP` 把上游 `amount` 映射到标准 `volume`，而 Sina/EM 都是 `volume→volume`。

**问题**：若腾讯 `amount` 实为成交额（元）而非成交量，经腾讯 fallback 的指数 K 线 volume 填成货币值，量级差 1000x+。但需 failover 走到腾讯第二 fallback 才触发。

**建议**：**先 live 探活** `stock_zh_index_daily_tx` 取 `000300`，核实 `amount` 列语义。若是额：丢弃 volume 或改用其他字段；若是量：加注释说明。

> 仍属 P3：触发路径窄（需 Sina 失败 + 腾讯被选）；需先探活不能盲改。

---

### P3-b · 健壮性/防御（明确非静默错，体验性）

#### P3-b1 · HTTPException 响应补 charset（原 M7，降 low）

**现状** `server.py:214-216` 只注册了 `RequestValidationError`(422) handler。`errors.py` map_errors raise 的 503/400/500（`:49,55,63`）及路由级 404/422/400 全走 FastAPI 默认 `http_exception_handler`，渲染成无 charset 的 `JSONResponse`。

**问题**：错误 `detail` 常含中文（`cls.py:143` "No 财联社早报 article..."），客户端乱码。这正是当初修 mojibake 的初衷，422 补了、HTTPException 漏了。

**建议**：

```python
# server.py, 在 _validation_exception_handler 旁
from starlette.exceptions import HTTPException as StarletteHTTPException

@app.exception_handler(StarletteHTTPException)
async def _http_exception_handler(request, exc):
    return _UTF8JSONResponse(
        status_code=exc.status_code,
        content={"detail": exc.detail},
    )
```

> 仍属 P3-low：本地自己看错误乱码，烦但不致命。一行的事，顺带可做。

---

#### P3-b2 · ClsFetcher 响应体大小上限（原 M16，medium）

**现状**（据子审查）`cls_fetcher.py:300-321` `_http_get_text` 直接 `r.text` 全量入内存，对比 `news_extractor._read_response_bytes` 有 5 MiB 流式上限。

**问题**：CLS 或 MITM 返回超大响应 → 无界内存增长。URL 内部构造非用户可控，故低于 news_extractor 面。

**建议**：`stream=True` + 上限（如 2 MiB），mirror `_read_response_bytes`。

> 仍属 P3：URL 非用户可控，溢出需上游/中间人主动作恶。

---

#### P3-b3 · 删除死代码（原 M2 / L6，low）

**现状**：
- `manager.py:90-92` `get_fetcher` 第一定义被 `:133-166` 覆盖，死代码，签名（返回 `None` on miss）与实际（raise `ValueError`）矛盾，误导维护者。
- `persistence/board.py:1319-1384` `upsert_membership_for_stock_boards` 零运行时调用方（grep 仅命中 `docs/superpowers/plans/`），`get_stock_memberships` docstring 明言"cold-fill 已移除"。

**建议**：直接删两处。

> 仍属 P3：死代码无运行时风险，纯维护负担。重构时清。

---

#### P3-b4 · 持久层去 fastapi 依赖（原 L7，low）

**现状**（据子审查）`persistence/backfill.py:21` `from fastapi import FastAPI`，仅用于 `schedule_ths_board_backfill_on_startup(app: FastAPI)` 类型注解。

**问题**：持久层向上耦合 web 框架。

**建议**：

```python
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from fastapi import FastAPI
```

> 仍属 P3：纯耦合洁癖，无功能影响。

---

#### P3-b5 · `get_report_pdf` 空 error 归一化（原 L4，low）

**现状**（据子审查）`manager.py:1203-1223`，所有 RESEARCH_REPORT fetcher 的 `download_report_pdf` 返回 `None`（base 默认）时，`_with_failover` 走 `raise DataFetchError(prefix + "\n" + "")`（空 error 列），503 无诊断行。对比 CLS 用 `_fetch_cls_optional`（all-failed raise，all-empty 返回 `(None,"")`）。

**建议**：`get_report_pdf` 用 `allow_none=True`，路由层把 `None` 映射 404。

> 仍属 P3：仅影响"无 PDF 时的错误信息观感"。

---

#### P3-b6 · THS hot_topics/north_flow 吞异常（原 L5，low）

**现状**（据子审查）`ths_fetcher.py:2110-2112,2156-2158` 吞所有 `Exception` 返回 `[]`，被 failover 当成功空数据，ZZSHARE(P2 可服务 HOT_TOPICS) 永不被试。EastMoney `_datacenter_query` 同病。

**问题**：上游真宕时静默返回空而非换源。但 THS 是 HOT_TOPICS 的 P2，前面只有 ZZSHARE P2——实际 failover 链短。

**建议**：区分网络/解析错误（raise `DataFetchError`）与业务级空（return `[]`）。

> 仍属 P3：failover 链短，实际影响小；且改成 raise 可能引入新 failover 行为，需谨慎。

---

### P3-c · 并发/缓存微优化（本地单用户近乎无收益）

#### P3-c1 · TTLCache 线程安全（原 L1，low）

**现状** `api/cache.py:23-66` 模块级 `TTLCache` 单例，FastAPI 同步 handler 在 40 线程池并发访问。cachetools `TTLCache` 非文档线程安全，`__getitem__` 的 TTL eviction 跨多 dict 操作。GIL 下低概率非零。

**建议**：每个 cache 包 `threading.Lock`，或 `cache_endpoint` wrapper 内加锁。

> 仍属 P3：单用户低并发，GIL 兜底，触发概率极低；加锁反而增开销。

---

#### P3-c2 · cache-stampede singleflight（原 L2，low）

**现状** `cache.py:345-357` 无 per-key 锁，TTL 到期 N 并发同请求齐打上游。

**建议**：per-key lock 或接受 trade-off（小 TTL + GIL）。

> 仍属 P3：单用户 stampede 几乎不存在；P2-1 加固 THS 限流后更无关。

---

#### P3-c3 · `_manager` 单例 init 加锁（原 L3，low）

**现状** `api/routes/helpers.py:68-77` `_manager is None` 检查无锁，启动并发首请求可能双初始化 ~13 fetcher（浪费 SDK login）。

**建议**：模块级 `threading.Lock` 包 init。

> 仍属 P3：一次性浪费，非 corrupting；单用户启动并发首请求概率低。

---

### P3-d · 结构性重构（YAGNI，重构顺带）

#### P3-d1 · `ths_fetcher.py` mixin 拆分

**现状** `ths_fetcher.py` 2494 行单类 7 capability（HOT_TOPICS / NORTH_FLOW / NEWS_FLASH / NEWS_SEARCH / STOCK_BOARD / STOCK_NEWS / ANNOUNCEMENT）。`_parse_ths_board_stocks_row` 模块级函数 + `staticmethod` 挂载（`:2494`）是可测性 workaround。EastMoney 已用 mixin 拆分（`_boards_mixin`/`_news_mixin`/`_endpoints`）。

**建议拆分**：
- `_board_mixin.py`（~900 行，board K 线 / stocks / realtime / all_boards / stock_boards，lines 725-2084）
- `_news_mixin.py`（~450 行，flash / search / stock_news / announcements，lines 2160-2414）
- `_signal_mixin.py`（~80 行，hot_topics / north_flow）
- `fetcher.py`（~200 行，类定义 / v-token / 共享 HTTP）

> 仍属 P3：能跑先跑；纯可读性，无功能/正确性收益。下次大改 THS 时顺带。

---

#### P3-d2 · SQLite 迁移框架 / 外键 enforcement

**现状** schema 演进靠 `CREATE IF NOT EXISTS` + 临时 `ALTER TABLE`（仅 `_add_platecode_column_if_missing`），无版本跟踪；`PRAGMA foreign_keys=ON` 从未设，`stock_board` 与 `stock_board_membership` 无 FK，删 board 行留孤儿 membership（靠 LEFT JOIN 防御性掩盖）。`_migrate_zzshare_special_to_concept`（`board.py:349-382`）每次 `init_schema()` 全表扫。

**建议**（按需，非现在）：
- 引入 schema_version 表 + 版本化迁移脚本（如 alembic 或自写轻量）。
- `PRAGMA foreign_keys=ON` + FK 约束（需先确认无现有孤儿数据违反）。

> 仍属 P3：个人 DB 可重建，schema 稳定后低风险；迁移框架是生产化诉求，YAGNI。

---

#### P3-d3 · 统一 HTTP 超时常量

**现状** `utils/http.py` 默认 10s；`cls_fetcher`/`cninfo`/`baidu`/`news_extractor` 15s；`tencent` 10s。全有界但无中心常量。

**建议**：`http.py` 加 `DEFAULT_HTTP_TIMEOUT = 10`，各 fetcher 引用；ops 可 env 调。

> 仍属 P3：各路径已分别有界，无现行故障；纯一致性。

---

#### P3-d4 · 统一连接模式

**现状** 请求路径用单例（`db.py:_conn`），backfill 线程用独立连接（`backfill.py:142`），两套并存。

**建议**：统一为 `threading.local` 每线程连接（见 P2-1）或连接池。

> 仍属 P3：P2-1 落地后自然统一；不单独做。

---

#### P3-d5 · news_extractor 用共享 UA 池（原 L9，low）

**现状** `news_extractor.py:29-32` 硬编码单一 `_EM_USER_AGENT`，对比 `utils/http.py:56-70` 有 `_UA_POOL` + `random_ua()`。

**建议**：`from .http import random_ua`，header 用 `random_ua()`。

> 仍属 P3：固定 UA 在反-bot 敏感域名更可指纹化，但 news_extractor 默认 localhost 不对外，收益微小。

---

#### P3-d6 · `is_hk_market` 裸 5 位歧义（原 L10，low）

**现状** `utils/normalize.py:123-131` 末尾 `return bool(code.isdigit() and len(code) == 5)`，任意裸 5 位数字串当 HK；而 `to_tencent_prefix` 文档说裸 5 位 0-4 开头是深市。两函数分类不一致。

**问题**：仅非规范输入（绕过 `normalize_stock_code`）触发。实际调用方都传规范 `HK00700`。

**建议**：统一约定（裸 5 位 0-4 → SZ，5 → HK，或要求 HK 必须前缀），并在两函数对齐 + 加测试。

> 仍属 P3：现行输入都规范，无触发；属边界语义洁癖。

---

#### P3-d7 · Yfinance amount 近似（原 L11，low）

**现状** `yfinance_fetcher.py:174-175` `_normalize_data` 合成 `amount = volume * close`（Yfinance 无 turnover）。

**问题**：A 股 failover 到 Yfinance(P4) 时 amount 单位/量级与 Baostock/Akshare/Tushare 约定（真实成交额，元）不同，跨源客户端会漂移。

**建议**：文档化 Yfinance amount 为近似（注释已说明），或在 response 加 `amount_approximate` 标记。不建议改算法（无上游数据源）。

> 仍属 P3：Yfinance 是 P4 backup，A 股 failover 到此概率低；属已知局限。

---

## 落地顺序建议

1. **一次性 PR 做 P0 全部**（4 项，都是几行，互不冲突，各有测试）。
2. **P1-1 单独 PR**（board 陈旧行 DELETE，需确认 `upsert_membership_bulk` 调用方语义，风险略高）。
3. **P1-2 + P1-3 一组**（cache 守卫 + 文档对齐，文档零风险）。
4. P2 按需，每项独立。
5. **P3 默认不做**——按"遇再说"或"重构顺带"触发：
   - P3-a（数据正确性面窄项）只在**实际踩到**或做 fetcher 边界加固（P0-2/P0-3）时顺带扫；
   - P3-a4 / P3-a5（符号 / 映射可疑）**必须先 live 探活核实语义**，不可盲改；
   - P3-b（健壮性）做 charset/死代码清理时顺手，零风险；
   - P3-c（并发微优化）单用户下**几乎不做**，除非 P2-1 落地后并发写实际出现 "database is locked"；
   - P3-d（结构性重构）只在下次大改对应模块时顺带，不为此单独开 PR。

每项改完跑相关单测（默认 `not live_network` 即可，~1 分钟），P2-2 / P3-a4 / P3-a5 需先 `live_network` 探活确认。

---

*本方案所有"现状代码"均经阅读实际文件核实（file:line 见各节）。建议代码为可直接落地的 diff 级片段。*
