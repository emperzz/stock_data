# EastMoney / THS 新闻正文提取增强设计

> 日期：2026-07-15
> 状态：待用户审阅
> 范围：增强 `GET /api/v1/news/content` 对 EastMoney、THS 等新闻 URL 的正文提取、状态诊断和低频访问保护

## 1. 背景

当前项目已经提供以下新闻列表能力：

- EastMoney：新闻搜索、个股新闻、快讯、公告；
- THS：新闻搜索、个股新闻、快讯、公告；
- `GET /api/v1/news/content?url=...`：对列表返回的 URL 抓取详情页并提取正文。

列表接口返回的 URL 来源并不统一：

| 来源 | 常见域名 / URL | 当前 content 行为 |
|---|---|---|
| EastMoney 新闻搜索/快讯 | `finance.eastmoney.com` | 有专用 handler，覆盖较好 |
| EastMoney 个股新闻 | `caifuhao.eastmoney.com`、其他公开来源 URL | 通常走通用 handler |
| EastMoney 公告 | `data.eastmoney.com` | 常为公告索引、跳转页或附件入口 |
| THS 个股新闻/快讯 | `news.10jqka.com.cn` | 目前主要走通用 handler |
| 问财搜索 | 聚合搜索接口；详情 URL 目前没有稳定的现有调用来源 | 不作为本阶段专用 handler |

现有通用 handler 在遇到不同站点的导航结构、登录页、验证码页、JS 壳或公告索引页时，可能出现两类问题：

1. 明明可访问，但正文为空或误判为提取失败；
2. 把导航、推荐、广告或风控提示误当成正文返回。

本设计只改进内容提取层，不改变新闻列表上游接口的路由、failover 和现有字段含义。

## 2. 目标与非目标

### 2.1 目标

1. 增强 EastMoney、THS 常见新闻 URL 的正文提取覆盖率；
2. 保留现有 EastMoney 专用解析器，并扩展到经过 fixture/低频 probe 验证的页面结构；
3. 对访问成功但无法抽取正文的页面返回结构化诊断结果；
4. 保持旧响应字段兼容；
5. 保留 SSRF、非法协议和 DNS rebinding 防护；
6. 不因解析失败产生额外上游请求；
7. 通过 fixture、API 集成测试和低频真实 probe 验证实际效果；
8. 对 THS 等可能使用非 UTF-8 编码的页面正确解码。

### 2.2 非目标

- 不新增 `NEWS_CONTENT` capability；
- 不把 `NewsContentExtractor` 变成 fetcher；
- 不修改 EastMoney/THS 新闻列表接口的请求参数或 failover 关系；
- 不让 content endpoint 反向调用新闻 fetcher 的内部方法；
- 不引入浏览器渲染；
- 不自动请求 canonical URL；
- 不批量遍历新闻列表并逐条抓正文；
- 不绕过验证码、登录、访问频率限制或其他反爬措施；
- 不为了正文提取新增来源 API 二次调用；
- 本阶段不为 `www.iwencai.com` 增加专用 handler。若未来实际新闻列表开始返回该域名，再单独增加 fixture 和设计变更；静态问财页面仍可通过通用 handler 尝试解析。

## 3. 整体架构

```text
GET /api/v1/news/content?url=...
        │
        ├─ URL 安全校验
        │    ├─ 非 http(s)、localhost、私网地址 → HTTP 400
        │    └─ 合法公网地址 → 继续
        │
        ├─ 单次 HTTP 抓取
        │    ├─ 沿用现有超时、UA、重定向和 DNS rebinding 防护
        │    └─ 不因解析失败重试或切换 URL
        │
        ├─ 读取最终 URL、canonical / OpenGraph / JSON-LD 元数据
        │
        ├─ 域名专用 handler
        │    ├─ finance.eastmoney.com
        │    ├─ stock.eastmoney.com
        │    ├─ caifuhao.eastmoney.com（fixture 验证后）
        │    ├─ data.eastmoney.com
        │    └─ news.10jqka.com.cn
        │
        ├─ 增强通用 handler
        │
        ├─ 正文状态判定
        │
        └─ 统一 NewsContentResponse
```

`NewsContentExtractor` 继续通过域名 registry 分发 handler。域名匹配需要统一处理：

- 大小写；
- `www.` 前缀；
- 端口；
- 重定向后的最终域名。

`canonical_url` 只作为识别和返回信息，不自动跟随抓取，避免单次客户端请求变成多次上游访问。

## 4. 响应契约

### 4.1 现有字段

保留当前字段：

- `url`：客户端请求的原始 URL，保持现有兼容语义；
- `title`；
- `body`；
- `publish_date`；
- `author`；
- `source_domain`；
- `extractor`；
- `byte_size`。

`source_domain` 对 content 响应使用最终响应 URL 的 hostname 推导，而不是仅相信客户端传入的 host。

### 4.2 新增字段

`NewsContent` 和 `NewsContentResponse` 增加：

```python
content_status: Literal[
    "ok",
    "empty",
    "unsupported",
    "javascript_required",
    "blocked",
    "fetch_error",
] = "ok"

reason: str | None = None
canonical_url: str | None = None
http_status: int | None = None
```

字段含义：

- `ok`：成功抽取到可信正文；
- `empty`：识别到正文区域，但清洗后正文过短或为空；
- `unsupported`：页面可访问，但没有当前解析器支持的正文结构；
- `javascript_required`：页面明显是客户端渲染壳，没有可用服务端正文；
- `blocked`：验证码、访问频繁、登录或风控页面；
- `fetch_error`：抓取阶段超时、连接失败、解码失败或 HTTP 上游错误。URL 安全校验阶段的 DNS 失败仍按现有 fail-closed SSRF 规则返回 HTTP 400。

### 4.3 字段传递边界

新字段必须完整经过以下三层：

| 层 | 文件 | 要求 |
|---|---|---|
| 抓取结果 | `data_provider/utils/news_extractor.py` | `NewsContent` dataclass 增加字段；`_build()` 支持关键字参数；所有 handler 和结构化失败路径都填充状态 |
| API schema | `api/schemas.py` | `NewsContentResponse` 增加字段并提供兼容默认值 |
| 路由响应 | `api/routes/news.py` | 将 `NewsContent` 的新字段逐一透传到 Pydantic 响应 |

`NewsContent._build()` 和 handler 应使用关键字参数，不依赖新增字段的 positional 顺序。

`reason` 是人类可读诊断信息，客户端只应依赖 `content_status` 做机器判断，不把 `reason` 当作稳定枚举。

`canonical_url` 的优先级为：

1. 页面中的 `<link rel="canonical">`，如果是合法 `http(s)` URL；
2. 否则使用 `resp.url`（重定向后的最终 URL）；
3. 两者都不可用时为 `null`。

`http_status` 使用最终响应的 `resp.status_code`；请求未获得 HTTP 响应时为 `null`。

`byte_size` 继续表示清洗后 `body` 的 UTF-8 字节数。非 `ok` 状态的 `body` 为空，因此 `byte_size` 为 0；不把原始 HTML 大小混入该字段。

### 4.4 HTTP 与异常边界

`NewsContentExtractor.extract()` 的异常边界必须明确：

- URL 安全校验错误继续抛出 `ValueError`，包括非法协议、localhost、私网地址、私网 DNS 解析失败和重定向到私网；路由通过现有 `map_errors` 返回 HTTP 400；
- 抓取阶段的 `requests.RequestException`、明确的解码错误以及 HTTP 错误不抛出给路由，而是返回 `NewsContent`，分别设置 `fetch_error` 或 `blocked`；
- 解析结果为空、结构不支持或 JS 壳返回结构化 `NewsContent`；
- 不使用宽泛的 `except Exception` 吞掉解析器编程错误，未预期的程序错误仍应暴露为 500，便于发现缺陷。

因此：

- `content_status == "ok"`：HTTP 200，返回正文；
- 其他内容访问/解析状态：仍返回 HTTP 200，`body` 为 `""`，尽可能保留标题、来源、canonical URL 和上游状态码；
- 非法协议、localhost、私网地址、私网重定向等安全错误：继续返回 HTTP 400；
- 参数缺失或参数格式非法：继续使用现有参数错误语义。

`news/content` 路由当前 OpenAPI 中的“提取失败 502”声明应删除，因为普通抓取/解析失败不再使用该响应路径。

## 5. 来源专用 handler

### 5.1 EastMoney

保留现有 `finance.eastmoney.com` / `stock.eastmoney.com` handler：

- `div.topbox`：标题、作者、日期；
- `div.contentbox`：正文段落；
- 过滤推广段落；
- 在“文章来源”“责任编辑”“郑重声明”“网友评论”等边界停止。

在其基础上增加经过 fixture 验证的候选结构：

- `article`；
- `.article-content`；
- `.article-body`；
- `#ContentBody`；
- JSON-LD / OpenGraph 元数据。

新增 `caifuhao.eastmoney.com` 的处理以真实结果为准：

1. 从现有测试数据或一次受控 live probe 获取一个代表性 URL；
2. 如果增强后的通用 handler 已能稳定抽取正文，保留通用路径，并在 live probe/合同测试中记录该结果，不再为了域名数量新增重复 handler；
3. 只有当通用 handler 失败且页面存在稳定、可验证的专用正文结构时，才保存脱敏 HTML fixture、确定 selector 并增加 `_eastmoney_caifuhao_handler`；
4. 如果页面被阻断、不可用或只是 shell/index 页面，不添加猜测 selector，使用结构化 `blocked`、`fetch_error`、`javascript_required` 或 `unsupported` 状态。

本次低频 probe 已验证 `caifuhao.eastmoney.com` 可由 `generic_content` 抽取，故本阶段不新增重复的财经号专用 handler。

对 `data.eastmoney.com` 公告页：

- 抽取可识别的标题、日期和正文；
- 如果页面只是公告索引、跳转页、登录页或 PDF/附件入口，返回 `unsupported` 或 `javascript_required`；
- 不把附件下载 URL 当成 HTML 正文；
- 不新增 PDF 下载或 OCR 逻辑。

### 5.2 THS

增加 `news.10jqka.com.cn` 专用 handler，优先尝试经 fixture 或低频 probe 验证的结构；初始候选顺序为：

1. `.article-detail`；
2. `.article-content`；
3. `.news-content`；
4. `.txt`；
5. `article`；
6. `main`。

同时提取：

- 标题；
- 发布时间；
- 来源；
- 正文段落；
- 图片说明和表格中的可读文本。

清理脚本、广告、推荐、评论和登录提示，避免把快讯页面外围模板当作正文。

THS 页面如果声明 GBK/GB18030 或 `requests` 的默认推断明显不可信，抓取层应在解析前使用响应声明或 `apparent_encoding` 选择编码；UTF-8 页面仍优先使用明确的 UTF-8 声明。

### 5.3 问财

本阶段不增加 `www.iwencai.com` 专用 handler，因为当前新闻列表数据流没有稳定地产生该域名的详情 URL。

如果未来实际返回静态问财详情页，增强后的通用 handler 仍会尝试：

- `article` / `main`；
- JSON-LD、OpenGraph；
- `__NEXT_DATA__` 中的标题和发布时间；
- `<noscript>` 中的可读正文。

如果只有搜索壳、结果列表或客户端渲染标记而没有正文，则返回 `javascript_required`。不启动浏览器，不追加问财 API 请求。

## 6. 通用正文抽取

专用 handler 未得到可信正文时，进入增强后的通用 handler：

1. 移除 `script`、`style`、`nav`、`aside`、`header`、`footer`、`iframe`、`form`；保留并单独检查 `noscript`；
2. 按优先级尝试 `article`、`main` 和经过验证的常见 content class/id；
3. 对候选块做确定性过滤：
   - 去除明显广告、推荐、评论和登录提示；
   - 过滤链接文本占比明显过高的候选块；
   - 选择通过过滤后的最长候选正文，不引入多维度质量评分系统；
4. 对正文长度做明确阈值判断：
   - 已知来源专用正文容器：清洗后至少 20 个非空白字符；
   - 通用 handler：清洗后至少 80 个字符，或至少两个段落且合计至少 40 个字符；
   - EastMoney 现有 `.contentbox` 的 100 字节下限继续保留，除非对应测试明确调整；
5. 低于阈值时不判定为 `ok`。

状态判定优先级：

```text
HTTP 403/429 或明显验证码/风控页 -> blocked
明显 JS 壳且没有正文            -> javascript_required
存在候选容器但正文太短            -> empty
页面有内容但没有支持结构          -> unsupported
抽取结果通过长度和内容过滤        -> ok
```

`blocked` 的初始判断规则必须具体且保守：

- 最终 HTTP 状态为 403 或 429；或
- 页面正文很短且包含明显标记，例如“请输入验证码”“访问频繁”“请求过于频繁”“人机验证”“安全验证”“登录后查看”“Access Denied”“captcha”“challenge”。

如果长正文中仅偶然出现这些词，不应单独判定为 blocked。

`extractor` 记录最后实际尝试的路径，包括失败路径，例如：

- `eastmoney_v1`
- `eastmoney_caifuhao`
- `eastmoney_notice`
- `ths_news_v1`
- `generic_article`
- `generic_main`
- `none`

## 7. 错误和安全处理

抓取/解析失败转为 `NewsContent` 结构化结果；只有 URL 安全校验和参数错误继续抛出异常。

| 情况 | HTTP | 状态 |
|---|---:|---|
| 非法协议、localhost、私网地址 | 400 | 不返回内容响应 |
| 私网 DNS rebinding 重定向 | 400 | 不返回内容响应 |
| 连接超时或网络失败 | 200 | `fetch_error` |
| HTTP 403/429 | 200 | `blocked` |
| HTTP 404/5xx | 200 | `fetch_error` |
| 验证码/访问频繁页面 | 200 | `blocked` |
| JS 壳页面 | 200 | `javascript_required` |
| 无正文 | 200 | `empty` 或 `unsupported` |

重定向后的最终 URL仍需进行现有私网校验。canonical URL不自动抓取，也不改变 SSRF 校验范围。

## 8. 缓存与 rate limit

沿用现有内容缓存：

- cache key：URL 的 SHA-256 前缀；
- TTL：3600 秒；
- 成功和结构化失败结果都可缓存；
- 缓存命中不触发网络请求。

缓存 miss 时：

- 每个 URL 只进行一次 HTTP 请求；
- 使用流式读取并限制响应正文不超过 5 MiB，超限返回 `fetch_error`，不进入 HTML parser 或缓存；
- 单个 JSON-LD script 不超过 256 KiB，超限跳过该 script；
- 不因解析失败重试；
- 不跟随 canonical URL 再次抓取；
- 不调用 EastMoney/THS 新闻列表或正文 API 作为 fallback。

本阶段不增加新的进程内 host cooldown。原因是该机制会引入线程同步、worker 隔离和测试时钟等额外复杂度；现有 1 小时 URL 缓存、单次请求和不重试已经满足内容 endpoint 的基本低频约束。若后续生产监控显示不同 URL 的突发访问仍然触发上游限制，再单独设计 host 级限流。

真实上游验证按 host 串行执行，每个 host 最多一个代表 URL，不并发、不循环、不强制绕过缓存。

## 9. 测试设计

### 9.1 单元 fixture

在 `tests/fixtures/` 增加最小化、脱敏 HTML：

- EastMoney 标准新闻页；
- EastMoney 财经号页（先确认真实结构，再添加）；
- EastMoney 公告索引/附件入口；
- THS 个股新闻页；
- THS 快讯页；
- 通用 `article` / `main` 页；
- JSON-LD / OpenGraph 元数据页；
- `<noscript>` 可读正文页；
- 验证码/访问频繁页；
- JS 壳页。

验证标题、日期、作者、正文、过滤结果、canonical URL、状态和 extractor。所有阈值测试使用明确超过/低于阈值的 fixture，避免测试依赖模糊长度。

### 9.2 API 集成测试

验证：

- 成功内容仍返回 HTTP 200；
- 无正文、JS 壳、403 页面返回 HTTP 200 + 结构化状态；
- 非 `ok` 状态的 body 为空且 `byte_size == 0`；
- `http_status` 正确保留；
- `canonical_url` 优先使用页面声明值，否则使用最终响应 URL；
- 内容缓存命中时新字段不丢失；
- 非法 URL、localhost、私网重定向仍返回 HTTP 400；
- 原有响应字段保持兼容；
- 删除/更新路由现有“提取失败 502”的 OpenAPI 声明。

现有 `test_content_extraction_failure_returns_400` 应改为覆盖安全错误，另增：

- `test_content_403_returns_200_with_blocked_status`；
- `test_content_parse_failure_returns_200_with_empty_or_unsupported_status`；
- `test_content_unexpected_parser_error_is_not_silenced`（如果保留 500 可观测性约定）。

### 9.3 rate limit 和请求次数测试

使用 mock 或 fake clock 验证：

- 同一 URL 的缓存命中不发起网络请求；
- 解析失败不会自动发起第二次请求；
- canonical URL 不会触发第二次请求；
- 403/429 不触发自动 retry/backoff；
- 单次 extractor 调用最多执行一次页面请求。

### 9.4 新闻 URL 合同测试

沿用 EastMoney/THS 现有 fetcher fixtures，增加轻量合同断言：

- 新闻条目的 `url` 非空且为 HTTP(S)；
- `source_domain` 与 URL hostname 一致；
- EastMoney/THS 返回的 URL 可以直接作为 `news/content` 输入；
- 不改变列表接口的 `title`、`snippet`、`publish_date` 等现有字段语义。

该测试不要求所有新闻 URL 都能成功提取正文；不可访问或结构不支持的页面应由 `content_status` 正确说明。

### 9.5 低频 live probe

默认测试不触网。单独运行 live probe 时：

1. 从已有新闻 fixture 或一次受控列表结果中选一个 EastMoney URL；
2. 选一个 THS 个股新闻或快讯 URL；
3. 若未来观察到实际问财详情 URL，再单独增加 probe；
4. 每个 host 只访问一次，串行执行；
5. 测试必须使用 `@pytest.mark.live_network`，沿用项目的网络失败降级机制。

记录 HTTP 状态、最终 URL、正文长度、命中 extractor、content_status 和是否出现风控/JS 壳。不把完整真实正文写入普通 fixture。

## 10. 实施文件范围

预计修改：

- `stock_data/data_provider/utils/news_extractor.py`
- `stock_data/api/schemas.py`
- `stock_data/api/routes/news.py`
- `tests/test_news_content_extractor.py`
- `tests/test_news_endpoints.py`
- 现有新闻 fetcher 测试中必要的 URL/source_domain 合同断言
- `tests/fixtures/` 下的新闻 HTML fixture

不预计修改：

- `DataCapability`；
- `data_provider/manager.py` 的新闻 failover；
- EastMoney/THS 新闻列表的上游请求方式；
- `.env.example`，因为本阶段不新增 cooldown 配置。

## 11. 验收标准

1. EastMoney、THS 常见新闻 URL 至少能命中专用或增强通用解析器；
2. 页面可访问但正文不可提取时返回 HTTP 200 和明确 `content_status`；
3. 403、429、验证码和 JS 壳不会被判定为 `ok`；
4. URL 安全校验和 SSRF 测试继续返回 HTTP 400；
5. 原有 EastMoney 正文测试继续通过，失败语义按新 HTTP 200 契约更新；
6. 缓存命中保留所有新增字段且不发起网络请求；
7. canonical URL 不会引起额外抓取；
8. source_domain 与 content 响应的最终 URL 一致；
9. 单元测试不触网；
10. live probe 每个 host 最多一次且串行；
11. 解析失败不会造成重复上游请求或自动重试；
12. 运行相关测试和低频真实验证后，报告 EastMoney/THS 各 URL 类型实际成功、空正文、JS 壳和被拦截的情况。

## 12. 评审后范围收紧说明

本版本根据审阅意见做了以下调整：

- 明确了 SSRF 异常与普通抓取/解析状态的边界；
- 明确了 dataclass、Pydantic schema 和路由三层字段传递；
- 删除了不再使用的 502 提取失败契约；
- 移除了本阶段的 host cooldown，避免过度设计；
- 将 `www.iwencai.com` 专用 handler 移出本阶段；
- 将 `caifuhao.eastmoney.com` handler 改为 fixture-first，禁止凭猜测堆 selector；
- 用确定性候选选择和明确阈值替代未定义的多维质量评分；
- 补充了 HTTP 编码、canonical URL、blocked 关键词、`noscript`、live marker 和 URL 合同测试要求。
