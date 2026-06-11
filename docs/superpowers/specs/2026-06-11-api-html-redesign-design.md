# API 文档 HTML 化设计文档

> 日期：2026-06-11
> 状态：待用户审阅
> 范围：将 `docs/API.md` 的内容改造成一个独立的交互式 HTML 文档；后端最小改动以支持挂载与启停测试实例。

## 1. 目标与范围

**目标**：在不修改 `docs/API.md` 的前提下，新增一个同源的、可交互的 API Explorer 网页，方便开发者、Agent（如 OpenClaw）浏览与试调 stock_data 服务。

**核心约束**：
- `docs/API.md` 文件本身**完全不修改**（用户明确要求）
- 维持现有 `python -m stock_data.server` 启动方式不变
- HTML 文件可独立双击打开阅读（即使动态功能失效，内容仍可读）

**不在范围内**：
- 自动从 `routes.py` / `schemas.py` 抽取元数据（手工录入 + 标注 LAST_SYNCED）
- 鉴权（项目本身无鉴权，保持一致）
- 多语言切换（中英双语仍是未来 work）
- `docs/API.md` 内容之外的新功能文档

## 2. 文件清单

| 路径 | 动作 | 说明 |
|---|---|---|
| `docs/API.html` | 新建 | 单文件 HTML：内联 CSS + JS，零外部依赖 |
| `stock_data/control.py` | 新建 | 测试实例的 start / stop / status 封装 |
| `stock_data/server.py` | 修改（小） | 挂载 `/docs` 静态资源 + 注册 4 个 `/control/*` 端点 |
| `tests/test_control.py` | 新建 | `control.py` 单元测试 |
| `tests/test_server_control_endpoints.py` | 新建 | `server.py` 新增端点的 FastAPI TestClient 集成测试 |
| `tests/test_api_html.py` | 新建 | BeautifulSoup 解析 HTML，验证锚点 id、ENDPOINTS JSON 完整性 |
| `docs/API.md` | **不修改** | 严格遵守 |
| `pyproject.toml` | 可能需要 | 若 `psutil` 未在 `dependencies`，则新增 |
| `CLAUDE.md` | 增量更新 | 在合适章节补一句"API 文档网页位于 `docs/API.html`" |

## 3. 架构总览

```
┌────────────────────────────────────────────────────────┐
│                  浏览器 (单页)                          │
│  ┌─────────┐  ┌─────────────────────┐  ┌────────────┐  │
│  │ 侧边栏   │  │   主内容 (endpoint  │  │ Test       │  │
│  │ - 章节   │  │   卡片 / Try it)    │  │ Instance   │  │
│  │ - 过滤   │  │                     │  │ 卡片       │  │
│  └─────────┘  └─────────────────────┘  └────────────┘  │
│       │                │                     │          │
│       └────────────────┴─────────────────────┘          │
│                │  fetch (同源)                         │
└────────────────┼────────────────────────────────────────┘
                 ▼
┌────────────────────────────────────────────────────────┐
│  FastAPI app (stock_data/server.py)                    │
│  - 静态挂载 /docs  (docs/API.html)                     │
│  - 控制路由  /control/config                            │
│            /control/server/status                      │
│            /control/test-instance/start|stop|status    │
│  - 数据路由  /stocks/...   /indices/...   /boards/... │
└────────────────────────────────────────────────────────┘
                 │
                 ├──→ DataFetcherManager (已有)
                 │
                 └──→ subprocess (Test Instance)
                       监听 127.0.0.1:<TEST_PORT>
                       端口默认 = STOCK_SERVER_PORT + 1
```

## 4. 关键设计决策

### 4.1 产出方式：单文件手工编写

- **决策**：直接生成一个独立的 `docs/API.html`，内联 CSS + JS，不引入打包工具
- **理由**：文档量适中（约 25 个 endpoint），改动频率不高；不引入 React/Vue/webpack 等工具链
- **后续演进**：若未来内容膨胀或变更频繁，可考虑用 `mkdocs` / 自研脚本自动生成

### 4.2 集成方式：在 stock_data server 内挂载

- **决策**：在 `server.py` 中用 `app.mount("/docs", StaticFiles(...))` 挂载 `docs/` 目录
- **理由**：
  - 满足"同源"前提，避免 CORS 配置
  - 不引入新的服务入口
  - 现有启动方式 `python -m stock_data.server` 不变
- **静态挂载的容错**：`docs/` 目录不存在时，server 启动时打印 WARN 但不阻塞（保留 `try/except` 在 `lifespan` 中）

### 4.3 Test Instance 子进程

- **决策**：HTML 页面控制一个**独立的子进程 stock_data 实例**（不同端口，默认 `:8001`），用于手动测 failover、对比数据
- **理由**：
  - 主服务是 HTML 的"宿主"，不能停止自己（页面会失联）
  - 子进程是常规 stock_data 进程，行为完全一致
  - 用户可手动切换 "Base URL" 在主服务与 Test Instance 之间
- **生命周期**：
  - 默认不启动；用户通过 UI 显式 Start
  - PID 写入 `docs/.server.pid`（gitignore 已包含 `.pid`）
  - 进程崩溃后下次 status 查询返回 `running: false, exit_code: <n>`

### 4.4 控制端点（仅监听 127.0.0.1）

| 端点 | 方法 | 响应 | 说明 |
|---|---|---|---|
| `/control/config` | GET | `{port, host, version, test_port, env_keys: [...]}` | 给 HTML 初始化使用 |
| `/control/server/status` | GET | `{running, pid, uptime_sec, port}` | 主服务自身状态（用于 UI 显示） |
| `/control/test-instance/start` | POST | `{running, pid, port, error?}` | 启动子进程，幂等 |
| `/control/test-instance/stop` | POST | `{running: false, error?}` | 停止子进程，幂等 |
| `/control/test-instance/status` | GET | `{running, pid?, port?, uptime_sec?, exit_code?}` | 轮询用 |

**安全**：所有 `/control/*` 端点不接收任意命令；`start` 内固定调用 `python -m stock_data.server --port {test_port} --host 127.0.0.1`，不暴露 shell。

### 4.5 端口与配置

- 主服务端口：从 `STOCK_SERVER_PORT` 环境变量读（默认 8000），host 限制 127.0.0.1
- Test Instance 端口：`STOCK_TEST_INSTANCE_PORT`（默认 `STOCK_SERVER_PORT + 1`）
- 端口冲突时 `start_test_instance()` 返回 `{running: false, error: "port_in_use"}`，不抛异常

### 4.6 端点元数据 Schema（HTML 内嵌 JSON）

见设计 §4（已确定）：

```js
const ENDPOINTS = {
  meta: { version, generated },
  capabilities: { HISTORICAL_DWM: { label, icon }, ... },
  fetcher_meta: { Tushare: { priority, color }, ... },
  sections: [
    { id, title, endpoints: [
        { id, method, path, summary, markets, capabilities,
          params, response_fields, cache, sources }
    ]}
  ]
}
```

**录入工作量**：约 25 个 endpoint × 5-10 个字段，预计 800-1200 行 JSON。

**同步策略**：HTML 顶部注释 `LAST_SYNCED: <date>`，每次 `docs/API.md` 改后手工同步，并在 PR 描述中提示。

## 5. UI 设计

### 5.1 布局

- **桌面（≥1200px）**：三栏 — 侧边栏 280px + 主内容 max-width 920px 居中 + 右侧 endpoint 元信息卡片（可选）
- **平板（768-1199px）**：两栏 — 侧边栏 + 主内容
- **手机（<768px）**：单栏 + 顶栏 hamburger 菜单

### 5.2 配色

CSS 变量驱动，支持 light / dark 主题切换，主题状态持久到 `localStorage`。

**Light 主题**：
- `--bg: #fafafa` / `--bg-card: #ffffff` / `--bg-sidebar: #f5f5f7`
- `--text: #1d1d1f` / `--text-muted: #6e6e73`
- `--accent: #0071e3` / `--accent-post: #34c759` / `--accent-warn: #ff9500`
- `--border: #e5e5ea` / `--code-bg: #f5f5f7`

**Dark 主题**：相同变量切换为深色版（`--bg: #0d0d0f` 等）

### 5.3 字体

- 系统字体栈：`-apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif`
- 代码：`"SF Mono", "JetBrains Mono", Menlo, Consolas, monospace`
- 字号：H1 32px / H2 24px / H3 18px / body 15px / caption 13px

### 5.4 关键交互

| 功能 | 触发 | 行为 |
|---|---|---|
| 全文搜索 | Ctrl+K / 顶栏搜索框 | fuse.js 内联，模糊匹配 path / summary / 字段名 / upstream；上下方向键导航；Enter 跳转 |
| Market 过滤 | 侧边栏 checkbox | 勾选 csi/hk/us → endpoint 卡片显隐；持久 localStorage |
| Capability 过滤 | 侧边栏多选 | 按 `DataCapability` 标志过滤；持久 localStorage |
| 主题切换 | 顶栏月亮/太阳图标 | 切换 `<html data-theme>`；持久 localStorage |
| 代码复制 | 代码块右上角图标 | `navigator.clipboard.writeText()` |
| Try it | endpoint 卡片按钮 | 收集表单 → fetch → 渲染响应（JSON 高亮 / 错误卡片） |
| Test Instance 启停 | 侧边栏 Test Instance 卡片 | start / stop / status 轮询（5s 间隔） |
| Base URL 切换 | 顶栏输入框 | 持久 localStorage；影响所有 Try it |
| file:// 降级提示 | 页面加载检测 | 顶部黄色横幅，部分功能不可用 |

### 5.5 响应设计

- endpoint 卡片默认折叠详细字段，hover 抬升阴影
- fetch chain 每个 fetcher 名用胶囊样式，可点击展开
- 响应 JSON 自动格式化、键名排序，附 "Copy / Raw / Pretty" 切换
- 侧边栏章节 IntersectionObserver 滚动高亮

## 6. 错误处理

| 场景 | 行为 |
|---|---|
| 启动时主服务端口占用 | uvicorn 抛 `OSError: [Errno 48]`；HTML 启动按钮 fallback 提示用户换端口 |
| `.env` 未设 `STOCK_SERVER_PORT` | 默认 8000 |
| `docs/` 目录不存在 | server 启动时打印 WARN；不挂载 `/docs`；主功能不受影响 |
| Test Instance 启动失败（端口冲突） | `/control/test-instance/start` 返回 `{running: false, error: "port_in_use"}`；UI 红色提示 |
| Test Instance 崩溃 | 下次 status 查询返回 `running: false, exit_code: <n>`；UI 变红 |
| Try it 收到 5xx | 响应卡片显示状态码 + body + "是否查看 Server Status？" |
| Try it 网络错误 | 灰色卡片 "无法连接 <baseUrl>，请检查 Server Status" |
| Base URL 改动 | 持久 localStorage；下次加载回填 |
| `file://` 打开 HTML | 顶部黄色横幅，部分功能（同源 Try it、Start/Stop）不可用 |
| 主题切换持久化失败 | 静默失败，回到 `prefers-color-scheme` |
| 搜索无结果 | "No endpoints match '<query>'" + 清除按钮 |
| 子进程 PID 文件丢失但进程仍在 | `psutil.pid_exists` 二次确认；不存在则从 `lsof` / `netstat` 重新发现 |

## 7. 测试策略

### 7.1 自动化测试

| 模块 | 测试文件 | 覆盖 |
|---|---|---|
| `control.py` | `tests/test_control.py` | `start` / `stop` / `status` 正常路径；PID 文件存在但进程已死；端口占用；幂等性 |
| `server.py` 新增端点 | `tests/test_server_control_endpoints.py` | FastAPI `TestClient` 调 4 个端点；断言响应 schema |
| `docs/API.html` 静态结构 | `tests/test_api_html.py` | BeautifulSoup 验证锚点 id（`#4.2`、`#stocks-quote`）、CSS 变量定义、`ENDPOINTS` ≥ 25 项、fuse 索引存在 |

### 7.2 手工 smoke test（实施完成时跑）

详见 brainstorm §6 检查表 12 项：
1. 启动 server，浏览器打开 `/docs/API.html`
2. Server Status 卡片显示 `Running on :8000`
3. 侧边栏点击章节 → 滚动到位
4. Try it 600519 行情 → 看到 JSON
5. 换 Base URL → 错误卡片
6. Ctrl+K 搜索 "dragon"
7. 勾选 us market 过滤
8. 切 dark 主题
9. Start Test Instance → 状态变 Running on :8001
10. 关闭 Test Instance → 状态回 Stopped
11. `file://` 打开 → 黄色横幅
12. 移动端宽度 → hamburger 菜单

## 8. 实施步骤

按依赖顺序，每步可独立验证：

### Phase 1 — 后端基础设施
1. 新建 `stock_data/control.py`：`start_test_instance` / `stop_test_instance` / `get_test_instance_status` + PID 写入 `docs/.server.pid`
2. 修改 `stock_data/server.py`：
   - import 新模块
   - `app.mount("/docs", StaticFiles(directory=PROJECT_ROOT / "docs", html=True), name="docs")`
   - 注册 5 个 control 路由
   - host 限制 127.0.0.1（检查现有 `server.py` 的 uvicorn 启动方式）
3. 新建 `tests/test_control.py` + `tests/test_server_control_endpoints.py`

### Phase 2 — HTML 骨架
4. 新建 `docs/API.html`：内联 CSS（主题变量）+ 内联 JS（IIFE 模块）+ 空 ENDPOINTS 字典
5. 跑通启动 + 浏览器打开 `/docs/API.html`，确认布局、主题切换、sidebar 渲染

### Phase 3 — 元数据填充
6. 从 `docs/API.md` 转写 ENDPOINTS JSON：25 个 endpoint 逐个录入
7. 新建 `tests/test_api_html.py`，验证 HTML 结构

### Phase 4 — 交互层
8. Try it 表单 + fetch + 响应渲染
9. 搜索（fuse.js 内联）+ market / capability 过滤 + localStorage 持久化
10. Test Instance 控制卡片 + 状态轮询

### Phase 5 — 收尾
11. 移动端响应式
12. `file://` 降级提示横幅
13. CLAUDE.md 增量更新

## 9. 风险与缓解

| 风险 | 缓解 |
|---|---|
| ENDPOINTS 手工录入与 API.md 漂移 | 顶部 `LAST_SYNCED: <date>` 注释 + 提醒用户在 PR 中同步 |
| 子进程管理跨平台（Windows 杀进程） | 优先用 `psutil`；如未在 `pyproject.toml` 则补 `dependencies` |
| 静态挂载与现有路由冲突 | 检查 `routes.py` 是否有 `/docs/*`；若有则改用 `/api-explorer` |
| HTML 体积膨胀 | 当前估算 ~130KB（CSS 10 + JS 30 + JSON 80 + HTML 10）；远低于警戒线 |
| fuse.js 内联增大 JS 体积 | 内联 minified 版本约 10KB；可接受 |
| Test Instance 端口被第三方占用 | 暴露 env 变量 `STOCK_TEST_INSTANCE_PORT`，让用户改 |
| control 端点被远程访问 | 强制监听 127.0.0.1，不暴露 0.0.0.0 |

## 10. 不在本次范围

- 鉴权 / 用户登录
- 自动从 `routes.py` 生成元数据
- 国际化（中英双语）
- 移动端原生 App
- 离线缓存（Service Worker）
- E2E Playwright 测试（仅手工 smoke test）

## 11. 附录 A — ENDPOINTS JSON 录入样例

```js
{
  id: "stocks-quote",
  method: "GET",
  path: "/stocks/{stock_code}/quote",
  summary: "实时行情",
  markets: ["csi", "hk", "us"],
  capabilities: ["REALTIME_QUOTE"],
  params: [
    { name: "stock_code", in: "path", required: true,
      type: "string", desc: "例 600519 / AAPL / HK00700（不支持指数代码）" }
  ],
  response_fields: [
    { group: "基础", fields: [
      "code", "stock_name", "source", "current_price", "change",
      "change_percent", "open", "high", "low", "prev_close",
      "volume", "amount", "update_time"
    ]},
    { group: "估值增强", fields: [
      "pe_ttm", "pe_static", "pb", "mcap_yi", "float_mcap_yi",
      "turnover_pct", "amplitude_pct", "limit_up", "limit_down", "vol_ratio"
    ]}
  ],
  cache: { ttl_sec: 60, env: "CACHE_TTL_QUOTE" },
  sources: [
    { fetcher: "Tushare",   method: "get_realtime_quote",
      upstream: "tushare.realtime_quote(ts_code=...)", notes: "需 TUSHARE_TOKEN" },
    { fetcher: "Baostock",  method: "get_realtime_quote",
      upstream: "永远返回 None（无实时 API）" },
    { fetcher: "Myquant",   method: "get_realtime_quote",
      upstream: "gm.api.current_price(symbols=...)", notes: "需 MYQUANT_TOKEN" },
    { fetcher: "Akshare",   method: "get_realtime_quote",
      upstream: "ak.stock_zh_a_spot_em() / ak.stock_hk_spot_em()" },
    { fetcher: "Yfinance",  method: "get_realtime_quote",
      upstream: "yf.Ticker(...).fast_info" },
    { fetcher: "Zhitu",     method: "get_realtime_quote",
      upstream: "https://api.zhituapi.com/hs/real/ssjy/{code}?token=...", notes: "需 ZHITU_TOKEN" },
    { fetcher: "Tencent",   method: "get_realtime_quote",
      upstream: "https://qt.gtimg.cn/q={prefix}（GBK 88 字段）" }
  ]
}
```

## 12. 附录 B — 任务拆分（给 writing-plans 阶段使用）

每个任务 = 一个 PR / 一次提交：

1. `control.py` 模块 + 单元测试
2. `server.py` 挂载 `/docs` + 5 个 control 端点 + 集成测试
3. `docs/API.html` 骨架（CSS + JS 框架 + 空 ENDPOINTS）
4. `docs/API.html` 录入 §4.1-4.2 的 endpoint 元数据（健康 + 股票 + 指数）
5. `docs/API.html` 录入 §4.3-4.6 的 endpoint 元数据（列表/日历/板块/涨跌停）
6. `docs/API.html` 录入 §4.7-4.9 的 endpoint 元数据（龙虎榜/融资融券/资金流）
7. `docs/API.html` 录入 §4.10-4.13 的 endpoint 元数据（热点北向/研报/公告/指标）
8. `docs/API.html` Try it 交互实现
9. `docs/API.html` 搜索 + 过滤 + 主题 + localStorage
10. `docs/API.html` Test Instance 控制卡片
11. 移动端响应式 + file:// 降级横幅
12. CLAUDE.md 增量更新
