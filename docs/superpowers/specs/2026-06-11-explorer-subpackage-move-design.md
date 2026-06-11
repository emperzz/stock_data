# API Explorer 子包化重构 — 设计文档

> 日期: 2026-06-11
> 范围: 将 `docs/API.html` + `stock_data/control.py` + `stock_data/server.py` 中的 `/docs` 挂载和 `/control/*` 路由统一封装到 `stock_data/explorer/` 子包内,URL 从 `/docs/API.html` 改为 `/explorer/`。
> 性质: **纯重构 + URL 改名**,零功能新增。

---

## 1. 目标与动机

**目标**: 把"前端 API Explorer 展示 + 后端 Test Instance 控制"这套与 stock_data 核心数据 API 解耦的功能,从根目录的 `docs/` 和 `stock_data/server.py` 中物理抽离,统一到 `stock_data/explorer/` 子包内,实现:

1. **物理内聚**:HTML、控制逻辑、路由注册在同一个子包内,后端开发者只需读一个目录就能理解整套 explorer 机制
2. **职责解耦**:`stock_data/server.py` 不再内嵌 ~80 行 explorer 相关代码,回到"只负责 lifespan + 数据路由挂载"的单一职责
3. **URL 语义准确**:`/docs/` URL 名字暗示"项目文档",实际是"交互式 API Explorer"——改名 `/explorer/` 后语义对齐

**非目标**:
- 不修改 `docs/API.md`(延续 "do not edit API.md" 约定,API.html 仍以它为源头)
- 不修改 `docs/` 文件系统目录里的任何内容(API.md、superpowers/、baostock/、zhitu/、myquant/、architecture-review-*.md 全部保留)
- 不修改 explorer 的功能、UI、ENDPOINTS 数据、CSS、JS 任何渲染逻辑
- 不新增任何 endpoint、不修改任何 API 响应 schema
- 不做 `/docs/API.html` → `/explorer/` 的重定向(用户明确)

---

## 2. 当前状态

```
stock_data/                              # 项目根
├── stock_data/                          # Python 包
│   ├── api/                             # 数据路由
│   ├── data_provider/                   # 抓取层
│   ├── server.py                        # 233 行,内嵌 /docs 挂载 + 5 个 /control/* 路由
│   └── control.py                       # 142 行,Test Instance 子进程管理
├── docs/
│   ├── API.html                         # 57 KB 交互式 Explorer
│   ├── API.md                           # ENDPOINTS 源头(不动)
│   ├── architecture-review-2026-06-09.md
│   ├── baostock/  zhitu/  myquant/      # 上游原始文档
│   └── superpowers/                     # 规范与计划
└── tests/
    ├── test_api_html.py                 # BeautifulSoup 静态结构测试
    └── test_server_control_endpoints.py # 含 TestDocsMount 类
```

**引用 docs/ 与 control.py 的位置**:
- `stock_data/server.py:117` — `_DOCS_DIR = ...parent.parent / "docs"`,然后 `app.mount("/docs", StaticFiles(...))`
- `stock_data/server.py:131-208` — `_control_router`(5 个 control 端点 + 2 个 helper)
- `stock_data/control.py:20-22` — `DEFAULT_PID_PATH = ...parent.parent / "docs" / ".server.pid"`
- `tests/test_api_html.py:7` — `HTML_PATH = ...parent.parent / "docs" / "API.html"`
- `tests/test_server_control_endpoints.py:92-99` — `TestDocsMount` 类
- `CLAUDE.md:598` — 文档说明
- `.gitignore:100` — `/docs/.server.pid`

---

## 3. 目标结构

```
stock_data/
├── stock_data/
│   ├── server.py                        # 缩减到 ~135 行(净减约 95 行)
│   └── explorer/                        # 新建子包
│       ├── __init__.py                  # 公开 mount(app) 接口
│       ├── routes.py                    # /control/* 5 个端点(从 server.py 抽出)
│       ├── control.py                   # 子进程管理(从 stock_data/control.py 搬入)
│       └── static/
│           └── index.html               # 从 docs/API.html 搬入并 rename
├── docs/                                # 完全不动
└── tests/
    └── (test 文件平铺,不改目录结构)
```

**`stock_data/explorer/__init__.py` 公开契约**:
```python
def mount(app: FastAPI) -> None:
    """Mount the API Explorer static UI at /explorer/ and the
    /control/* management endpoints on the given FastAPI app.

    Failure mode: if static/ is missing, log a warning and skip the
    static mount, but still register /control/* routes (they don't
    need the HTML).

    Reentrancy: NOT protected. FastAPI's app.mount() raises
    RuntimeError on duplicate mount, which is sufficient. Call
    exactly once per FastAPI app instance.
    """
```

**`server.py` 集成点**:
```python
# 替换现有的 30+ 行(_DOCS_DIR block + _control_router block)
from .explorer import mount as mount_explorer
...
mount_explorer(app)  # 在 app.include_router(router, prefix="/api/v1") 之后
```

---

## 4. URL 与 API 契约

### 公开 URL 变更

| 旧 URL | 新 URL | 状态 |
|--------|--------|------|
| `GET /docs/API.html` | `GET /explorer/` | 改名 + 默认 index 渲染 |
| `GET /control/config` | **保持** | 不变 |
| `GET /control/server/status` | **保持** | 不变 |
| `GET /control/test-instance/status` | **保持** | 不变 |
| `POST /control/test-instance/start` | **保持** | 不变 |
| `POST /control/test-instance/stop` | **保持** | 不变 |
| `GET /docs/{其他}` | — | 直接 404(本来就 404,契约破坏需在 commit message 注明) |

**`/control/*` 前缀保留**:它语义上属于"服务器管理面",与"API Explorer UI"是两个不同概念,放同一前缀下反而让边界模糊。Explorer 子包只负责把这两组路由都注册到 app 上。

**重定向**:不做。`/docs/API.html` 直接 404,这是契约破坏,需要在 commit message 和 release notes 显式说明。

### 静态资源服务

`/explorer/` 由 `StaticFiles(directory=STATIC_DIR, html=True)` 挂载:
- `GET /explorer/` → `static/index.html`(FastAPI StaticFiles 默认行为)
- `GET /explorer/index.html` → 同上
- `GET /explorer/{未知资源}` → 404(无 fallback to index.html,因为这是工具页不是 SPA)

未来若需要拆 CSS/JS 到独立文件,直接放进 `static/` 即可,无需改 mount 代码。

### `/control/*` 端点契约(从 server.py 照搬,语义零变化)

```
GET  /control/config
  → {port, host, test_port, version, env_keys}

GET  /control/server/status
  → {running: true, pid, port, uptime_sec}

GET  /control/test-instance/status
  → {running, pid, port, error}

POST /control/test-instance/start
  → {running, pid, port, error}      (idempotent)

POST /control/test-instance/stop
  → {running, pid, error}            (idempotent)
```

约束不变:仅 `127.0.0.1`,**永远不** 在 `0.0.0.0` 上暴露。

### HTML 内部改动(`static/index.html`)

文件本身**几乎不动**,只改 2 处文案:
1. 第 5 行注释:`Source of truth: docs/API.md` → **不变**(源头仍是 API.md)
2. 第 120 行的 file:// 提示 banner:`Open via http://localhost:8888/docs/API.html` → `Open via http://localhost:8888/explorer/`
3. 第 153 行的 caption 文案:`All Try-it calls hit` 后面那个 base URL 占位符是 JS 动态填的(`/control/config` 决定),**不变**

ENDPOINTS 数据、JS 代码、CSS 一律不动。

---

## 5. 容错与边界

### `mount()` 内部两段独立 try/except

```python
def mount(app: FastAPI) -> None:
    # 第一段: 挂载 /explorer/ 静态资源
    try:
        static_dir = Path(__file__).resolve().parent / "static"
        if static_dir.is_dir():
            app.mount("/explorer", StaticFiles(directory=str(static_dir), html=True), name="explorer")
            logger.info(f"[Explorer] Mounted /explorer → {static_dir}")
        else:
            logger.warning(f"[Explorer] static/ not found at {static_dir}, /explorer not mounted")
    except Exception as e:
        logger.warning(f"[Explorer] Failed to mount /explorer: {e}")

    # 第二段: 注册 /control/* 路由(无 HTML 也能用)
    try:
        app.include_router(build_control_router())
        logger.info("[Explorer] Mounted /control/* (5 endpoints)")
    except Exception as e:
        # /control/* 注册失败 = server 启动失去诊断入口,比 HTML 挂载失败严重
        raise
```

**设计意图**:
- 静态资源挂载失败 → WARN + 跳过,**不阻塞** server 启动(数据 API 仍可用,运维通过 `/control/*` 仍能诊断)
- `/control/*` 注册失败 → 抛异常,server 启动失败(数据 API 启动但失去诊断入口无意义)

### PID 文件位置

`stock_data/explorer/.server.pid`(子包根,非 `static/` 内):
- 优点:`static/` 目录只装发布资产,边界清晰
- 缺点:仅多改 `control.py` 1 行(`DEFAULT_PID_PATH`)
- `.gitignore` 同步更新为 `/stock_data/explorer/.server.pid`

### `pyproject.toml` 配置

**不修改**。当前项目不打包 wheel 分发(`pip install -e .` 走 develop 模式,直接从源码读),`static/index.html` 通过 `Path(__file__).resolve().parent / "static"` 路径访问,无需 `package-data` 声明。

如果未来项目开始打包 wheel,届时加一行即可:
```toml
[tool.setuptools.package-data]
stock_data = ["explorer/static/*.html"]
```

本次不包含此改动,避免引入当前不需要的能力。

---

## 6. 文件级动作清单

| 来源 | 目标 | 操作 | 代码改动量 |
|------|------|------|-----------|
| `docs/API.html` | `stock_data/explorer/static/index.html` | `git mv` + 文件内 1 行文案改 | ~1 行 |
| `stock_data/control.py` | `stock_data/explorer/control.py` | `git mv` + 改 `DEFAULT_PID_PATH` 常量 | ~1 行 |
| `stock_data/server.py` 中 `_DOCS_DIR` + `app.mount` + `_control_router` + 5 端点 + `_CONTROL_STARTED_AT` + 2 个 helper | `stock_data/explorer/__init__.py` 的 `mount()` + `routes.py` | 提取并改 URL 前缀 | server.py 净减 ~95 行,新文件净增 ~110 行(分布在 `__init__.py`、`routes.py`、搬入的 `control.py`)|
| `tests/test_api_html.py` | 保持文件名,改 `HTML_PATH` | 改 1 行 | 1 行 |
| `tests/test_server_control_endpoints.py` 中 `TestDocsMount` | 同文件,改名为 `TestExplorerMount` + URL `/explorer/` | 改 ~3 行 | ~3 行 |
| `.gitignore` 中 `/docs/.server.pid` | `/stock_data/explorer/.server.pid` | 改 1 行 | 1 行 |
| `CLAUDE.md:598` | 更新路径与子包说明 | 改 1 段 | 1 段 |

**净代码量变化**:server.py 减少约 95 行,新子包 3 个 .py 文件净增约 110 行(包含搬入的 control.py),测试减少约 1 行,文档 +1 段。**总体 ~+15 行**,全部为子包结构代码与文档,无任何新功能代码。

---

## 7. 测试策略

### 既有测试的最小调整

| 测试文件 | 改动 |
|----------|------|
| `tests/test_api_html.py` | `HTML_PATH` 常量:`docs/API.html` → `stock_data/explorer/static/index.html`。其他 12 个测试方法**零改动**。 |
| `tests/test_server_control_endpoints.py` | `TestDocsMount` → `TestExplorerMount`;类内 `client.get("/docs/API.html")` → `client.get("/explorer/")`;`pytest.skip("...not yet created")` 文案更新。其他 control 端点测试不动。 |

### 不新增测试

**理由**:这次重构**不引入新行为**——所有端点、HTML 结构、control 行为都已经有测试覆盖。只需要把"指向旧路径"的测试指向新路径即可。**新增测试 = 给不存在的功能写测试 = 违反 YAGNI**。

### 端到端冒烟(人工)

1. `python -m stock_data.server` 启动,确认日志出现:
   - `[Startup] Mounted /docs → ...` 不再出现
   - `[Explorer] Mounted /explorer → ...` 出现
   - `[Explorer] Mounted /control/* (5 endpoints)` 出现
2. 浏览器访问 `http://127.0.0.1:8888/explorer/`,看到完整布局(侧边栏 + 27 个 endpoint 卡片 + 搜索 + 主题切换 + Test Instance 卡片)
3. 点击任意 endpoint 的 "Try it",确认能调通
4. 点 Test Instance "Start",确认子进程起来,status 变 running
5. 访问 `http://127.0.0.1:8888/docs/API.html`,确认 404(契约破坏已显式声明)

### `pytest` 全量回归

```bash
pytest tests/  # 预期: 既有测试全部通过(只改了路径)
```

---

## 8. 部署影响与回滚

### 部署影响

- **pip 安装**:`pip install -e .` / `pip install .` 不受影响
- **启动行为**:`python -m stock_data.server` 后浏览器访问 `http://127.0.0.1:8888/explorer/`
- **唯一破坏性变更**:浏览器书签、`./server.log` 里的旧 URL 引用、外部文档里写 `/docs/API.html` 的地方全部 404

### 回滚路径

`git revert` 一次提交即可,所有改动局限在:
- 新增 4 个文件(`__init__.py`、`routes.py`、`control.py`、`static/index.html`)
- 改动 5 个文件(`server.py`、`tests/test_api_html.py`、`tests/test_server_control_endpoints.py`、`.gitignore`、`CLAUDE.md`)

无数据库迁移、无配置变更、无新依赖、无 `pyproject.toml` 改动。

### Commit 消息模板

```
refactor(explorer): extract API Explorer + control into stock_data/explorer subpackage

Move docs/API.html → stock_data/explorer/static/index.html
Move stock_data/control.py → stock_data/explorer/control.py
Extract /docs mount + /control/* routes from server.py into explorer.mount()

URL change: /docs/API.html → /explorer/  (BREAKING — no redirect)
           /control/* unchanged

Pure refactor: zero new features, zero new endpoints, zero schema changes.
PID file moved to explorer/ root (no longer mixed with shipped static assets).
```

---

## 9. 范围检查与不变量

**完成后,以下不变量必须成立**:

1. `docs/` 文件系统目录**完全不动**(API.md、superpowers/、baostock/、zhitu/、myquant/、architecture-review-*.md)
2. `/docs/*` HTTP 路径**全部 404**(契约破坏,显式声明)
3. `/explorer/` 静态资源 + `/control/*` 5 个端点行为**与重构前完全一致**
4. `stock_data/server.py` 不再 import `fastapi.staticfiles.StaticFiles`、不再含 `_control_router`、不再含 `_DOCS_DIR` 常量
5. `stock_data/explorer/` 是**自包含单元**:`mount(app)` 一行集成,server.py 不知道 PID 路径、不知道 static 目录
6. 所有既有测试通过(只改路径,不改测试逻辑)

**严格不做的清单**:
- 不实现 SPA fallback(`/explorer/{未知}` → `index.html`)
- 不实现 `/docs/*` → `/explorer/` 重定向
- 不拆分 `index.html` 为独立 CSS/JS 文件(保持单文件 HTML 约定)
- 不修改 ENDPOINTS 数据、CSS、JS 任何渲染逻辑
- 不修改 `/control/*` 5 个端点的 URL、请求方法、响应 schema
- 不修改 `docs/API.md`
- 不修改任何 fetcher、indicator、persistence 代码
- 不在 `mount()` 内加 reentrancy flag(FastAPI 框架已提供)
