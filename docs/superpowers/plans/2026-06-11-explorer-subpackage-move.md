# API Explorer 子包化重构 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 `docs/API.html` + `stock_data/control.py` + `stock_data/server.py` 中的 `/docs` 挂载和 `/control/*` 路由统一封装到 `stock_data/explorer/` 子包内,URL 从 `/docs/API.html` 改为 `/explorer/`。纯重构,零功能新增。

**Architecture:**
- 4 个新文件组成 `stock_data/explorer/` 子包(`__init__.py` 公开契约 + `routes.py` 控制路由 + `control.py` 子进程管理 + `static/index.html`)
- `server.py` 调一行 `mount_explorer(app)` 完成所有 explorer 相关挂载
- URL 改名 `/docs/API.html` → `/explorer/`,`/control/*` 保持不变
- PID 文件从 `docs/.server.pid` 移到 `stock_data/explorer/.server.pid`(与 `static/` 同级)
- 零新功能、零新 endpoint、零新依赖

**Tech Stack:** Python 3.11+, FastAPI (existing), StaticFiles (existing), pytest + BeautifulSoup (existing tests)

**Worktree note:** 此次重构跨 9 个文件,虽然本质是一次 commit,但建议在独立 worktree 中操作以隔离风险。命令:
```bash
git worktree add ../stock_data-explorer-move -b refactor/explorer-subpackage
cd ../stock_data-explorer-move
```
最终是否 squash 4 个 commit 为 1 个,见 Task 4 末尾的讨论。

---

## Task 1: 创建 `stock_data/explorer/` 子包(4 个新文件)

**Files:**
- Create: `stock_data/explorer/__init__.py`
- Create: `stock_data/explorer/routes.py`
- Create: `stock_data/explorer/control.py`
- Create: `stock_data/explorer/static/index.html`(从 `docs/API.html` 移动并修改 1 行)

- [ ] **Step 1.1: 创建 `stock_data/explorer/__init__.py`**

写入以下内容(完整文件,共 47 行):

```python
"""API Explorer subpackage: interactive HTML UI at /explorer/ and /control/* endpoints.

Mounts the static HTML frontend (formerly docs/API.html) at /explorer/ and
the Test Instance management endpoints at /control/*. Used by
stock_data.server via the single-line mount(app) entry point.
"""

from __future__ import annotations

import logging
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from .routes import build_control_router

logger = logging.getLogger(__name__)


def mount(app: FastAPI) -> None:
    """Mount the API Explorer static UI at /explorer/ and /control/* endpoints.

    Failure mode: if static/ is missing, log a warning and skip the static
    mount, but still register /control/* routes (they don't need the HTML).

    Reentrancy: NOT protected. FastAPI's app.mount() raises RuntimeError on
    duplicate mount, which is sufficient. Call exactly once per FastAPI app.
    """
    # Static mount (failure → warn + continue, data API still works)
    try:
        static_dir = Path(__file__).resolve().parent / "static"
        if static_dir.is_dir():
            app.mount(
                "/explorer",
                StaticFiles(directory=str(static_dir), html=True),
                name="explorer",
            )
            logger.info(f"[Explorer] Mounted /explorer → {static_dir}")
        else:
            logger.warning(
                f"[Explorer] static/ not found at {static_dir}, /explorer not mounted"
            )
    except Exception as e:
        logger.warning(f"[Explorer] Failed to mount /explorer: {e}")

    # Control router (any failure here is fatal — re-raise to abort server startup)
    app.include_router(build_control_router())
    logger.info("[Explorer] Mounted /control/* (5 endpoints)")
```

- [ ] **Step 1.2: 创建 `stock_data/explorer/routes.py`**

写入以下内容(完整文件,共 89 行):

```python
"""Control endpoints for the API Explorer (/control/*).

Exposes server config, server status, and Test Instance subprocess
management. Bound to 127.0.0.1 only — never expose on 0.0.0.0.
"""

from __future__ import annotations

import os
import time

from fastapi import APIRouter

from .. import __version__
from . import control as _control

_CONTROL_STARTED_AT = time.time()


def _read_server_port() -> int:
    try:
        return int(os.getenv("SERVER_PORT", "8888"))
    except ValueError:
        return 8888


def _read_server_host() -> str:
    return os.getenv("SERVER_HOST", "127.0.0.1")


def build_control_router() -> APIRouter:
    """Build the /control/* APIRouter. Called once by explorer.mount()."""
    router = APIRouter(prefix="/control", tags=["control"])

    @router.get("/config")
    def control_config() -> dict:
        """Static config used by the HTML explorer to initialize itself."""
        port = _read_server_port()
        test_port = int(os.getenv("STOCK_TEST_INSTANCE_PORT", str(port + 1)))
        return {
            "port": port,
            "host": _read_server_host(),
            "test_port": test_port,
            "version": __version__,
            "env_keys": [
                "TUSHARE_TOKEN", "BAOSTOCK_PRIORITY", "AKSHARE_PRIORITY",
                "YFINANCE_PRIORITY", "ZHITU_TOKEN", "ZHITU_PRIORITY",
                "MYQUANT_TOKEN", "MYQUANT_PRIORITY", "TENCENT_PRIORITY",
                "EASTMONEY_PRIORITY", "THS_PRIORITY", "CNINFO_PRIORITY",
                "ENABLE_API_CACHE", "STOCK_CACHE_DB_PATH", "STOCK_DB_INIT",
            ],
        }

    @router.get("/server/status")
    def control_server_status() -> dict:
        """Status of the main server (the one serving the HTML)."""
        return {
            "running": True,
            "pid": os.getpid(),
            "port": _read_server_port(),
            "uptime_sec": int(time.time() - _CONTROL_STARTED_AT),
        }

    @router.get("/test-instance/status")
    def control_test_instance_status() -> dict:
        """Status of the optional Test Instance subprocess."""
        status = _control.get_test_instance_status()
        port = int(os.getenv("STOCK_TEST_INSTANCE_PORT",
                             str(_read_server_port() + 1)))
        return {**status, "port": port}

    @router.post("/test-instance/start")
    def control_test_instance_start() -> dict:
        """Start the Test Instance subprocess. Idempotent."""
        port = int(os.getenv("STOCK_TEST_INSTANCE_PORT",
                             str(_read_server_port() + 1)))
        host = _read_server_host()
        return _control.start_test_instance(port=port, host=host, wait_seconds=1.0)

    @router.post("/test-instance/stop")
    def control_test_instance_stop() -> dict:
        """Stop the Test Instance subprocess. Idempotent."""
        return _control.stop_test_instance()

    return router
```

- [ ] **Step 1.3: 创建 `stock_data/explorer/control.py`**

将现有 `stock_data/control.py` 全部内容复制过来,然后修改 1 行 `DEFAULT_PID_PATH`:

```bash
# 复制文件保留 git history
git mv stock_data/control.py stock_data/explorer/control.py
```

然后编辑 `stock_data/explorer/control.py`,将:

```python
# 原 line 20-22
DEFAULT_PID_PATH = str(
    Path(__file__).resolve().parent.parent / "docs" / ".server.pid"
)
```

改为:

```python
# 新 line 20-22
DEFAULT_PID_PATH = str(
    Path(__file__).resolve().parent / ".server.pid"
)
```

`parent.parent`(从 stock_data/ 跳到项目根)→ `parent`(在 stock_data/explorer/ 内)。

文件其他 140 行**完全保持不变**。不需要其他修改。

- [ ] **Step 1.4: 创建 `stock_data/explorer/static/` 目录并移动 HTML**

```bash
# 创建目录并保留 git history
mkdir -p stock_data/explorer/static
git mv docs/API.html stock_data/explorer/static/index.html
```

- [ ] **Step 1.5: 编辑 banner 文本(`index.html` 第 120 行)**

在 `stock_data/explorer/static/index.html` 中找到第 120 行附近(在 `<div id="banner" class="banner">` 内):

原内容:
```html
Open via <code>http://localhost:8888/docs/API.html</code> instead.
```

新内容:
```html
Open via <code>http://localhost:8888/explorer/</code> instead.
```

用 Edit 工具精确替换(只此一处,文件其他内容**完全不变**)。

- [ ] **Step 1.6: 验证子包可以 import**

```bash
python -c "from stock_data.explorer import mount; print('OK', mount.__doc__[:60])"
```

预期输出:
```
OK Mount the API Explorer static UI at /explorer/ and /contr
```

如果报 `ModuleNotFoundError`,检查:
- `stock_data/explorer/__init__.py` 存在
- 文件中没有语法错误(`python -c "import ast; ast.parse(open('stock_data/explorer/__init__.py').read())"`)

- [ ] **Step 1.7: 提交**

```bash
git add stock_data/explorer/
git commit -m "feat(explorer): add new subpackage with HTML, control, routes

- stock_data/explorer/__init__.py: mount(app) entry point
- stock_data/explorer/routes.py: /control/* 5 endpoints (extracted from server.py)
- stock_data/explorer/control.py: Test Instance subprocess management (moved from stock_data/control.py)
- stock_data/explorer/static/index.html: interactive HTML UI (moved from docs/API.html)

Subpackage is unused at this point; server.py will switch to it in Task 2.
PID file path updated: docs/.server.pid → stock_data/explorer/.server.pid.
HTML banner URL updated: /docs/API.html → /explorer/.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 2: 重构 `stock_data/server.py` 使用 `explorer.mount()`

**Files:**
- Modify: `stock_data/server.py`(删除 ~95 行,新增 ~5 行)

- [ ] **Step 2.1: 阅读当前 `stock_data/server.py` 第 20-30、109-210 行**

确认要删除的代码块边界:
- **第 109-110 行**(`app.include_router(router, prefix="/api/v1")` 之上的注释和空行) **保留**
- **第 112-124 行**(注释 + `_DOCS_DIR` try/except 块):**整段删除**
- **第 127-208 行**(`/control/*` 5 端点 + helpers + `_CONTROL_STARTED_AT`):**整段删除**
- **第 20-21 行**(`import time as _time` 和 `from . import control as _control`):**删除**(如果存在)

参考原文片段(来自当前文件):
```python
# Data routes (unchanged)
app.include_router(router, prefix="/api/v1")

# --- API Explorer (new) -------------------------------------------------
# Mount docs/ as static resources. /docs/API.html is the interactive explorer.
# Failure mode: if docs/ is missing, log a warning and continue without the
# mount — the data API still works.
try:
    _DOCS_DIR = Path(__file__).resolve().parent.parent / "docs"
    if _DOCS_DIR.is_dir():
        app.mount("/docs", StaticFiles(directory=str(_DOCS_DIR), html=True), name="docs")
        logger.info(f"[Startup] Mounted /docs → {_DOCS_DIR}")
    else:
        logger.warning(f"[Startup] docs/ not found at {_DOCS_DIR}, /docs not mounted")
except Exception as e:
    logger.warning(f"[Startup] Failed to mount /docs: {e}")


# --- /control/* endpoints (new) -----------------------------------------
# Bound to 127.0.0.1 — never expose on 0.0.0.0. The control router gives the
# HTML explorer the ability to read config, query status, and start/stop
# an independent Test Instance subprocess.
import time as _time  # for uptime tracking  # noqa: E402

from . import control as _control  # noqa: E402

_CONTROL_STARTED_AT = _time.time()


def _read_server_port() -> int:
    ...
```

- [ ] **Step 2.2: 删除 _DOCS_DIR 块(行 112-124) + 紧接的空行**

使用 Edit 工具,将:

```python
# Data routes (unchanged)
app.include_router(router, prefix="/api/v1")

# --- API Explorer (new) -------------------------------------------------
# Mount docs/ as static resources. /docs/API.html is the interactive explorer.
# Failure mode: if docs/ is missing, log a warning and continue without the
# mount — the data API still works.
try:
    _DOCS_DIR = Path(__file__).resolve().parent.parent / "docs"
    if _DOCS_DIR.is_dir():
        app.mount("/docs", StaticFiles(directory=str(_DOCS_DIR), html=True), name="docs")
        logger.info(f"[Startup] Mounted /docs → {_DOCS_DIR}")
    else:
        logger.warning(f"[Startup] docs/ not found at {_DOCS_DIR}, /docs not mounted")
except Exception as e:
    logger.warning(f"[Startup] Failed to mount /docs: {e}")


# --- /control/* endpoints (new) -----------------------------------------
# Bound to 127.0.0.1 — never expose on 0.0.0.0. The control router gives the
# HTML explorer the ability to read config, query status, and start/stop
# an independent Test Instance subprocess.
import time as _time  # for uptime tracking  # noqa: E402

from . import control as _control  # noqa: E402

_CONTROL_STARTED_AT = _time.time()


def _read_server_port() -> int:
    try:
        return int(os.getenv("SERVER_PORT", "8888"))
    except ValueError:
        return 8888


def _read_server_host() -> str:
    return os.getenv("SERVER_HOST", "127.0.0.1")

_control_router = APIRouter(prefix="/control", tags=["control"])


@_control_router.get("/config")
def control_config() -> dict:
    """Static config used by the HTML explorer to initialize itself."""
    port = _read_server_port()
    test_port = int(os.getenv("STOCK_TEST_INSTANCE_PORT", str(port + 1)))
    return {
        "port": port,
        "host": _read_server_host(),
        "test_port": test_port,
        "version": __version__,
        "env_keys": [
            "TUSHARE_TOKEN", "BAOSTOCK_PRIORITY", "AKSHARE_PRIORITY",
            "YFINANCE_PRIORITY", "ZHITU_TOKEN", "ZHITU_PRIORITY",
            "MYQUANT_TOKEN", "MYQUANT_PRIORITY", "TENCENT_PRIORITY",
            "EASTMONEY_PRIORITY", "THS_PRIORITY", "CNINFO_PRIORITY",
            "ENABLE_API_CACHE", "STOCK_CACHE_DB_PATH", "STOCK_DB_INIT",
        ],
    }


@_control_router.get("/server/status")
def control_server_status() -> dict:
    """Status of the main server (the one serving the HTML)."""
    return {
        "running": True,
        "pid": os.getpid(),
        "port": _read_server_port(),
        "uptime_sec": int(_time.time() - _CONTROL_STARTED_AT),
    }


@_control_router.get("/test-instance/status")
def control_test_instance_status() -> dict:
    """Status of the optional Test Instance subprocess."""
    status = _control.get_test_instance_status()
    # Include the configured test port so the UI can show it
    port = int(os.getenv("STOCK_TEST_INSTANCE_PORT",
                         str(_read_server_port() + 1)))
    return {**status, "port": port}


@_control_router.post("/test-instance/start")
def control_test_instance_start() -> dict:
    """Start the Test Instance subprocess. Idempotent."""
    port = int(os.getenv("STOCK_TEST_INSTANCE_PORT",
                         str(_read_server_port() + 1)))
    host = _read_server_host()
    return _control.start_test_instance(port=port, host=host, wait_seconds=1.0)


@_control_router.post("/test-instance/stop")
def control_test_instance_stop() -> dict:
    """Stop the Test Instance subprocess. Idempotent."""
    return _control.stop_test_instance()


app.include_router(_control_router)
```

替换为:

```python
# Data routes (unchanged)
app.include_router(router, prefix="/api/v1")

# --- API Explorer (new) -------------------------------------------------
# stock_data/explorer/ subpackage owns the /explorer/ static UI and the
# /control/* management endpoints. See stock_data/explorer/__init__.py.
from .explorer import mount as mount_explorer  # noqa: E402

mount_explorer(app)
```

- [ ] **Step 2.3: 删除 `server.py` 顶部不再使用的 imports**

找到 `stock_data/server.py` 第 19-26 行(imports 区域)。删除(如果存在):
- `import time as _time`(已不再使用)
- `from fastapi import APIRouter, FastAPI` 改为 `from fastapi import FastAPI`(如果 `APIRouter` 在文件中已无其他用途)
- `from fastapi.staticfiles import StaticFiles`(已不再使用)

最终 imports 应该大致是:
```python
import os

os.environ.setdefault("PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION", "python")

import logging
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from . import __version__
from .api.routes import router
```

**注意**:仅删除确实无引用的 import。如果 `Path` 在文件中其他地方用到(在 lifespan 块中没有),也保留。

- [ ] **Step 2.4: 运行 `python -c` 验证 server.py 没有语法错误**

```bash
python -c "from stock_data.server import app; print('OK', len(app.routes), 'routes')"
```

预期输出形如:
```
OK 33 routes
```

(数字可能略有差异,关键是 `OK` 字样 + 没有 `ImportError` / `SyntaxError`)

- [ ] **Step 2.5: 启动 server 并验证 `/explorer/` 和 `/control/*` 工作**

```bash
# 启动 server(后台)
python -m stock_data.server > /tmp/server.log 2>&1 &
SERVER_PID=$!
sleep 3

# 验证
curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:8888/explorer/
# 预期: 200

curl -s http://127.0.0.1:8888/control/config | python -c "import json,sys; d=json.load(sys.stdin); print('port:', d['port']); assert d['port'] == 8888"
# 预期: port: 8888

# 验证旧 URL 404(契约破坏)
curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:8888/docs/API.html
# 预期: 404

# 关闭 server
kill $SERVER_PID 2>/dev/null
wait $SERVER_PID 2>/dev/null
```

如果 `/explorer/` 返回 404:检查 `stock_data/explorer/static/index.html` 是否存在
如果 `/control/*` 返回 404:检查 `stock_data/explorer/routes.py` 是否有语法错误

- [ ] **Step 2.6: 运行 pytest 既有测试**

```bash
pytest tests/ -v 2>&1 | tail -50
```

预期:
- `tests/test_api_html.py` 全部通过(它现在指向新路径 `stock_data/explorer/static/index.html`,但**注意**:Task 3 才会更新这条路径;Task 2 期间这个测试**仍指向旧路径 `docs/API.html`**,但因为 `docs/API.html` 已被 git mv 到新位置,该测试会失败)
- `tests/test_server_control_endpoints.py` 中 `TestDocsMount` 测试**会失败**(旧 URL 404)
- 其他 control 端点测试**全部通过**

如果出现上述预期失败,这是正常的——Task 3 会修复测试。

如果其他意外失败:停下来调查,不要继续。

- [ ] **Step 2.7: 提交**

```bash
git add stock_data/server.py
git commit -m "refactor(server): delegate /docs mount and /control/* to explorer.mount()

server.py loses ~95 lines of inline explorer code; gains one import
and one mount() call. The explorer subpackage now owns all
explorer-related code (HTML, control, /control/* routes).

URL change: /docs/API.html → /explorer/  (BREAKING — no redirect)
           /control/* unchanged

Tests in test_api_html.py and TestDocsMount still reference old paths
and will be fixed in the next commit.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 3: 更新测试使用新路径

**Files:**
- Modify: `tests/test_api_html.py`(1 行)
- Modify: `tests/test_server_control_endpoints.py`(类名 + URL + skip 文案,~5 行)

- [ ] **Step 3.1: 更新 `tests/test_api_html.py` 第 7 行的 `HTML_PATH`**

当前内容(行 7):
```python
HTML_PATH = Path(__file__).resolve().parent.parent / "docs" / "API.html"
```

新内容:
```python
HTML_PATH = Path(__file__).resolve().parent.parent / "stock_data" / "explorer" / "static" / "index.html"
```

文件其他 12 行测试方法**完全不变**。

- [ ] **Step 3.2: 更新 `tests/test_server_control_endpoints.py` 第 92-99 行**

当前内容:
```python
class TestDocsMount:
    def test_api_html_served(self, client):
        """GET /docs/API.html returns 200 and contains <html>."""
        response = client.get("/docs/API.html")
        if response.status_code == 404:
            pytest.skip("docs/API.html not yet created (Task 3)")
        assert response.status_code == 200
        assert "<html" in response.text.lower()
```

新内容:
```python
class TestExplorerMount:
    def test_explorer_index_served(self, client):
        """GET /explorer/ returns 200 and contains <html>."""
        response = client.get("/explorer/")
        if response.status_code == 404:
            pytest.skip("explorer not yet mounted")
        assert response.status_code == 200
        assert "<html" in response.text.lower()
```

文件其他 6 个测试方法(测试 `/control/*` 各端点)**完全不变**。

- [ ] **Step 3.3: 运行 pytest 验证**

```bash
pytest tests/ -v 2>&1 | tail -50
```

预期:**全部通过**(`test_api_html.py` 12 个 + `test_server_control_endpoints.py` 7 个 = 19 个测试)。

如果 `test_explorer_index_served` 失败并报 404:检查 Task 2 步骤 2.5 是否完成。
如果 `test_api_html.py` 失败并报 `FileNotFoundError`:检查 `HTML_PATH` 路径拼写。

- [ ] **Step 3.4: 提交**

```bash
git add tests/test_api_html.py tests/test_server_control_endpoints.py
git commit -m "test: point API.html and /docs tests at /explorer/

- test_api_html.py: HTML_PATH now points at stock_data/explorer/static/index.html
- test_server_control_endpoints.py: TestDocsMount → TestExplorerMount,
  URL /docs/API.html → /explorer/, skip message updated

No test logic changes; only path constants and class names.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 4: 删除遗留文件 + 更新 `.gitignore` + `CLAUDE.md`

**Files:**
- Delete: `stock_data/control.py`(已在 Task 1.3 通过 `git mv` 移到 `stock_data/explorer/control.py`,但旧路径仍是 `git mv` 不会产生删除——实际已经在新位置,本任务无操作)
- Modify: `.gitignore`(1 行)
- Modify: `CLAUDE.md`(1 段)

- [ ] **Step 4.1: 确认 `stock_data/control.py` 已不存在**

```bash
ls stock_data/control.py 2>&1
```

预期:
```
ls: cannot access 'stock_data/control.py': No such file or directory
```

(因为 Task 1.3 已经 `git mv` 到新位置)

如果文件存在(异常情况):`git rm stock_data/control.py` 后继续。

- [ ] **Step 4.2: 确认 `docs/API.html` 已不存在**

```bash
ls docs/API.html 2>&1
```

预期:
```
ls: cannot access 'docs/API.html': No such file or directory
```

(因为 Task 1.4 已经 `git mv` 到新位置)

如果文件存在(异常情况):`git rm docs/API.html` 后继续。

- [ ] **Step 4.3: 更新 `.gitignore` 第 100 行**

当前内容:
```
/docs/.server.pid
```

新内容:
```
/stock_data/explorer/.server.pid
```

- [ ] **Step 4.4: 更新 `CLAUDE.md` 第 598 行附近**

找到 "Interactive web docs live at `docs/API.html`..." 那一段(约第 598 行)。

当前内容:
```
Interactive web docs live at `docs/API.html` and are mounted at `/docs/API.html` when the server runs. After `python -m stock_data.server`, open `http://localhost:8888/docs/API.html`. The page supports Try-it, search, market/capability filtering, dark theme, and an optional Test Instance subprocess (controlled from the sidebar). The Markdown source remains at `docs/API.md` (do not edit that file — sync changes into `ENDPOINTS` in the HTML).
```

新内容:
```
Interactive web docs live at `stock_data/explorer/static/index.html` (the `stock_data/explorer/` subpackage) and are mounted at `/explorer/` when the server runs. After `python -m stock_data.server`, open `http://localhost:8888/explorer/`. The page supports Try-it, search, market/capability filtering, dark theme, and an optional Test Instance subprocess (controlled from the sidebar). The Markdown source remains at `docs/API.md` (do not edit that file — sync changes into `ENDPOINTS` in the HTML). The `/control/*` management endpoints live alongside at the same prefix. Note: as of 2026-06-11 the URL changed from `/docs/API.html` to `/explorer/` (breaking change, no redirect).
```

- [ ] **Step 4.5: 运行完整测试套件 + lint**

```bash
pytest tests/ -v
ruff check stock_data/explorer/ tests/
```

预期:
- pytest: 全部通过(19 个测试)
- ruff: 无 error(`stock_data/explorer/` 是新代码,需要符合项目 ruff 配置;从 `pyproject.toml` 继承)

如果 ruff 报错:修复后重跑。

- [ ] **Step 4.6: 提交**

```bash
git add .gitignore CLAUDE.md
git commit -m "chore: update .gitignore PID path and CLAUDE.md explorer docs

- .gitignore: /docs/.server.pid → /stock_data/explorer/.server.pid
- CLAUDE.md: update API Explorer description to reflect new
  subpackage location, /explorer/ URL, and 2026-06-11 breaking change

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 5: 端到端冒烟验证(人工)

**无文件修改**。仅运行手动验证步骤,确保重构无遗漏。

- [ ] **Step 5.1: 启动 server,观察启动日志**

```bash
python -m stock_data.server > /tmp/server.log 2>&1 &
SERVER_PID=$!
sleep 3
cat /tmp/server.log
```

预期日志中:
- ✅ 出现 `[Explorer] Mounted /explorer → .../stock_data/explorer/static`
- ✅ 出现 `[Explorer] Mounted /control/* (5 endpoints)`
- ❌ **不**应再出现 `[Startup] Mounted /docs → ...`(旧日志格式)

- [ ] **Step 5.2: 浏览器访问 `/explorer/`**

在浏览器打开 `http://127.0.0.1:8888/explorer/`,逐项确认:
- [ ] 顶部 topbar 显示 "◐ stock_data API Explorer"
- [ ] 左侧 sidebar 显示 13 个 section(`4.1` 到 `4.13`)
- [ ] 看到 ~27 个 endpoint 卡片
- [ ] 搜索框输入 "kline" 应该有 fuzzy match
- [ ] 切换主题按钮(🌗)能切换 light/dark
- [ ] capability 过滤器 6 个 group 都能勾选
- [ ] 任意 endpoint 卡片点 "Try it" 能调通(例如 `/stocks/600519/quote`)

- [ ] **Step 5.3: 测试 `/control/*` 端点**

```bash
# 状态查询
curl -s http://127.0.0.1:8888/control/config | python -m json.tool
curl -s http://127.0.0.1:8888/control/server/status | python -m json.tool
curl -s http://127.0.0.1:8888/control/test-instance/status | python -m json.tool
```

预期:三个端点都返回 200 + 有效 JSON。

- [ ] **Step 5.4: 测试 Test Instance 启停**

在浏览器 `/explorer/` sidebar 底部 Test Instance 卡片:
- [ ] 点击 "Start",status 变 running,显示 PID + port 18889
- [ ] 点击 "Stop",status 变 stopped
- [ ] 检查 `stock_data/explorer/.server.pid` 文件存在(Start 时)并被清理(Stop 后)

- [ ] **Step 5.5: 验证旧 URL 404(契约破坏已显式声明)**

```bash
curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:8888/docs/API.html
```

预期: `404`

- [ ] **Step 5.6: 关闭 server**

```bash
kill $SERVER_PID 2>/dev/null
wait $SERVER_PID 2>/dev/null
```

- [ ] **Step 5.7: 最终检查 git log 与状态**

```bash
git log --oneline master..HEAD
git status
```

预期:
- git log: 显示 4 个 commit(对应 Task 1-4)
- git status: 干净

**关于 squash 的决定**:此 PR 的 spec 假设是"纯重构 = 一次原子变更"。你可以选择:

| 选项 | 命令 | 适用场景 |
|------|------|---------|
| **保留 4 个 commit**(默认) | (无操作) | 想要清晰 review 痕迹;每个 commit 单独可 revert |
| **Squash 为 1 个 commit** | `git rebase -i HEAD~4` → 全部 squash | 想要真正原子的"纯重构"在 git log 中呈现 |

推荐:**保留 4 个 commit**,因为:
- Task 1 添加新代码(subpackage 存在但未使用)是可独立 revert 的安全回滚点
- Task 2 是功能切换点
- Task 3 是测试同步
- Task 4 是 cleanup

revert 时可以选 `git revert <task-2-commit>` 一次性回滚到原状,或者 `git revert <task-4-commit> <task-3-commit> <task-2-commit>` 同样达到效果。

---

## 自审检查(完成所有 task 后)

**Spec 覆盖**:
- [x] Section 1 目标:Task 1-4 实现
- [x] Section 2 当前状态:文档说明(无代码改动)
- [x] Section 3 目标结构:`stock_data/explorer/{__init__,routes,control,static/index.html}` — Task 1 创建
- [x] Section 4 URL 改名:`/docs/API.html` → `/explorer/` — Task 2 + Task 5.5 验证
- [x] Section 4 `/control/*` 不变:Task 1.2 端点契约与原版逐字对照
- [x] Section 4 HTML 内部改动 2 处:Task 1.5(banner)
- [x] Section 5 容错边界:Task 1.1 `mount()` 内 2 段独立 try/except
- [x] Section 5 PID 位置:Task 1.3 `DEFAULT_PID_PATH` 修改
- [x] Section 5 `pyproject.toml` 不改:未在 plan 中出现 ✓
- [x] Section 6 文件级动作清单:Task 1-4 全部覆盖
- [x] Section 7 测试策略:Task 3 改路径 + Task 5 冒烟
- [x] Section 8 部署影响:Task 5.5 验证契约破坏
- [x] Section 9 不变量:Task 5.1 验证启动日志、Task 5.5 验证 404、Task 4.4 验证 docs/ 文件系统目录不动
- [x] Section 9 严格不做清单:reentrancy 防护不加、SPA fallback 不实现、index.html 不拆分、API.md 不改

**类型一致性**:
- `mount(app: FastAPI) -> None` 在 Task 1.1 定义,Task 2.2 引用 ✓
- `build_control_router() -> APIRouter` 在 Task 1.2 定义,Task 1.1 引用 ✓
- `DEFAULT_PID_PATH` 在 Task 1.3 修改,后续在 control.py 其他地方引用保持不变 ✓
- `__version__` 在 Task 1.2 `from .. import __version__` 引用,与 server.py 原 `from . import __version__` 语义一致(从子包内 `..` 跳到顶层包)

**Placeholder 扫描**:
- 全文搜索无 "TBD"、"TODO"、"fill in"、"implement later"
- 所有 "类似" 引用都有具体内容(如 Task 1.3 "文件其他 140 行**完全保持不变**")
- 所有代码块都是完整可粘贴的
