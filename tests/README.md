# 测试约定:网络/API 失败的分类

本项目对接 10 个上游股票数据 API。部分 pytest 用例会真实触网,而**网络/上游问题 ≠ 代码 bug**。本目录约定了一套机制,把这两类失败分开,让 agent / CI 不会把上游抖动误判为回归。

## 输出字符图例

```
.   passed           通过,无动作
F   failed           真 bug,需要修
s   skipped          环境/token 缺失,不是回归
x   xfailed          上游/网络问题,预期之内,不是回归
X   xpassed          上游居然通了,值得扫一眼
E   error            setup/teardown 异常,可能是测试 bug
```

**只有 `F`(以及可能的 `E`)应当触发"这是代码 bug"的反应。`s`/`x` 是正常输出。**

## 实现机制

1. **标记**:任何可能触网(直接或间接透过 fetcher)的测试加 `@pytest.mark.live_network`。
   - 通常在模块顶部用 `pytestmark = pytest.mark.live_network` 一行覆盖所有用例
   - 也可在单个类/方法上单独加

2. **Hook**:`tests/conftest.py` 注册了 `pytest_runtest_makereport` hook,对 `live_network` 测试:
   - 若 `call` 阶段失败 → 检查异常
   - 若异常属于 `_network_guard.UPSTREAM_ERRORS`(`ConnectionError` / `Timeout` / `HTTPError` / `socket.gaierror` / …)→ 把 report 改写为 `outcome="skipped"` + `wasxfail=True`,在输出里显示为 `x`
   - 若异常是 `AssertionError` / `ValueError` / `TypeError` / … → 保持 `F`,这是真 bug

3. **白名单**:`tests/_network_guard.py` 集中维护 `UPSTREAM_ERRORS` 异常列表。需要新增例外时改这里,不要在测试用例里散落 `try/except`。

## 使用

### 日常开发跑测

```bash
# 默认行为:遇到 live_network 测试不会因为上游抖动而失败
.venv/Scripts/python.exe -m pytest
```

输出形如:
```
tests/test_providers.py::TestBaostockFetcher::test_fetch_daily_data x  # 上游抽风,预期
tests/test_routes.py::TestHistory::test_history_with_adjust .          # 正常
tests/test_zhitu_fetcher.py::TestGetStockInfo::test_normalizes_full_payload .  # mock,无网
```

### 只跑纯单元测试(快,无网)

```bash
.venv/Scripts/python.exe -m pytest -m "not live_network"
```

### 全量联调(含 live_network)

```bash
# 注意:此时 x 输出可能增加,这是正常的上游抖动
.venv/Scripts/python.exe -m pytest -m "live_network" -v
```

### 重跑上次失败的

```bash
.venv/Scripts/python.exe -m pytest --lf
```

## 添加新 L2 测试的 checklist

当新增一个会触网(经 fetcher 间接或直接调上游)的测试时:

- [ ] 加 `@pytest.mark.live_network`(模块级 `pytestmark` 一行最省事)
- [ ] 不要在测试体里手写 `try/except requests.ConnectionError` 之类
- [ ] 如果需要 token 校验,在 setup 阶段用 `if not fetcher.is_available(): pytest.skip(...)`
- [ ] 在 docstring 里简述一句"hits real upstream, marked live_network"

## 相关文件

| 文件 | 作用 |
|-----|------|
| `tests/_network_guard.py` | 异常白名单 + `classify()` / `short_reason()` helpers |
| `tests/conftest.py` | 注册 `pytest_runtest_makereport` hook,做失败→xfail 的转换 |
| `pyproject.toml` | `[tool.pytest.ini_options].markers` 注册 `live_network` / `requires_token` |

## 与 `verify_converters_live.py` 的关系

`verify_converters_live.py` 是独立的手动脚本,采用相同的 PASS / FAIL / NET 三态分类,只是用 `print` 输出而非 pytest。它是**新方案的参考实现**:把"网络错"剥离为第三种状态,而不是当成 fail。

日常测试用 pytest,联调 / 验证转换器格式时跑 `python tests/verify_converters_live.py`。
