# board source 拆分设计 (2026-09-11)

将 `ths` / `zzshare` 从"一个 source 内部按板块名硬拼两个 fetcher"改为**两个严格隔离的一等公民 source**，并把 THS 的 `platecode` / `cid` 两套标识符的对应关系变成显式、可本地备份的工件。

本文档记录问题、实测证据、决策与实施顺序。所有实测数字来自 2026-09-11 对本地 server（:8888）与 SQLite (`stock_data/stock_cache.db`) 的取证。

---

## 1. 背景

### 1.1 历史成因

1. 最初只有 zzshare 提供"ths 板块"，落库时标 `source='ths'`。
2. 后 ThsFetcher 增加了板块清单 / 板块成分股的上游能力，但**缺少 stock→boards 反向能力**，于是用 CSV backfill 支撑反向索引。
3. 再后来 ThsFetcher 补齐了 `get_stock_boards`，但 `ths` 的"双 fetcher 对应 + 拼接"逻辑被保留至今。

### 1.2 问题的机械根因

`_merge_ths_zzshare_by_name`（`persistence/board.py:811`）**按板块名**把两个**互不相交的 code space** 拼进同一个 `source='ths'` 命名空间：

| 来源 | 概念 id | 行业 id |
|---|---|---|
| THS `gnSection`（`GET /gn/`） | `cid` = 3xxxxx **且** `platecode` = 885xxx/886xxx（同一次响应内两个都有） | 881xxx（`cid == platecode`） |
| zzshare `plates_rank` | `plate_code` = 801xxx / 803xxx / 710xxx / 883xxx | 801xxx |

两者**没有任何一个 code 共用**，而拼接依据只有板块名。更根本的是**同一个 dict key `code` 在管道边界上语义反转**：

- `ThsFetcher._parse_gn_section` 里 `code` = **cid**
- `update_cached_boards` 里 `code` = **platecode**

所以"什么时候用哪个 id"会搞混，是命名反转导致的，不是记忆问题。

### 1.3 实测证据（2026-09-11）

`stock_board` 中 `source='ths'` 共 967 行 / 766 个 distinct name：

| 命名空间 | 行数 | 说明 |
|---|---|---|
| THS platecode（881/885/886） | 589 | 合法 |
| zzshare code（801/803/710/883） | 240 | **被误标为 ths**（其中 3 行 `ths_cid` 亦为 NULL） |
| cid-only（`board_code` 为 3xxxxx） | 138 | 侧栏行，`platecode` 缺失 |

> 数字口径：按 code 前缀分组得 138 行 cid-only；按 `ths_cid IS NULL` 过滤得 **141 行**（= 138 + zzshare 分组中 3 行）。后文 §3 的映射覆盖率以 141 为分母。

由此产生四类重复/污染，实测规模：

| # | 机制 | 实测 |
|---|---|---|
| 1 | `_merge_ths_zzshare_by_name` 跨源按名硬拼 | 240 行 zzshare code 混入 ths |
| 2 | 同一 name 多 code（THS platecode + THS cid + zzshare code） | 167 个 name，例「智能电网」= `885311` + `300037` + `801346` |
| 3 | `code = platecode or code` 兜底 + `update_cached_boards` **从不 purge** | cid 与 platecode 双行并存，永不合并 |
| 4 | `cid` 列被写入非 cid 的值（活库探测） | **202 行**，例 `801001`(芯片) 的 `cid='801001'`；另有 110 行是 `cid='885xxx/886xxx'`（platecode 形态，见 §3.1） |

线上后果（均为实测，非推演）：

1. **合法 THS 板块码被 422**。`GET /boards/885300/stocks?source=ths` 与 `/boards/300188/stocks?source=ths` 均返回 `422 cid_unresolved`；而 `300188` 正是 `/boards?source=ths` 在冷路径下自己吐出来的 `code`。
2. **同一 endpoint 的 `code` 随缓存状态变脸**。冷路径 fetcher 行 `code=cid`（响应出现 `300188`/移动支付）；缓存命中时 `update_cached_boards` 存的是 `platecode`（响应变成 `885333`）。
3. **`?source=zzshare` 是空头承诺**。`/stocks/600519/boards?source=ths` 与 `?source=zzshare` 返回**逐字节相同**的 10 行（alias 生效），其中 5 个 801xxx + 885/886/881 混在一起。
4. **`?source=ths` 实际由 zzshare 服务**。`/boards/801001/stocks?source=ths&include_quote=false` → `effective_source='zzshare'`。
5. **cid 解析被污染**。`_resolve_ths_cid_from_code('801001')` 返回 `801001`（因为 merge 把 `platecode = code`，`update_cached_boards` 再写进 `cid`），随后作为 THS 内部 cid 喂给 THS。

### 1.4 backfill 数据的真实身份

`stock_data/stock_data_backup/`（`server.py:93` 硬编码路径，CSV 已 force-add 进版本库）：

- `stock_board_membership_ths.csv`：115,081 行全部标 `source='ths'`，但生成方式是 `manager.get_board_stocks(source="zzshare")` → `upsert_membership_bulk(source="ths")`（见 `docs/superpowers/specs/2026-07-10-ths-board-backfill-on-startup-design.md:69-71`）。其中 **52,010 行 board_code 是 801xxx**（zzshare pt=17 区间）。
- `stock_board_ths.csv`：797 行，混有 885/886/881（THS 原生）与 801/803/710（zzshare）。`tools/fix_stock_board_ths_csv.py:144-145` 明确以 zzshare 为准：`pc = zz_truth.get(nm) or ths_pc.get(nm)`。

**结论：这些数据本来就是 zzshare 数据，只是被贴了 `ths` 标签。** 改为 `source='zzshare'` 不是重新分类，而是还原身份。

### 1.5 THS 两套 id 的正确用法

| id | 形态 | 唯一正确用途 |
|---|---|---|
| 概念 `cid` | 3xxxxx | 仅 `q.10jqka.com.cn/gn/detail/code/{cid}/.../ajax/1/` 拉成分股 |
| 概念 `platecode` | 885xxx / 886xxx | 公开身份；F10 全量页 `basic.10jqka.com.cn/48/{platecode}/`；`stock_concept_list` 返回的 `quote_code`；板块 K 线 |
| 行业 | 881xxx | `cid == platecode`，同值，无歧义 |
| zzshare `plate_code` | 801xxx… | 仅 zzshare `plates_rank` / `plates_stocks` |

现状最易踩雷处：`fetch_board_stocks_with_zzshare_fallback` 里**同一个板块的三条腿用三种 id** —— F10 腿传 platecode、zzshare 腿传 801xxx、THS-AJAX 腿传 cid；而调用方手里只有 route 给的 code（冷/热路径还不一样）。

---

## 2. 决策记录

| # | 决策 | 结论 |
|---|---|---|
| D1 | zzshare 在公开 API 的身份 | **一等公民 source**（`?source=zzshare` 由 422 变为合法） |
| D2 | 跨源兜底 | **完全去掉**，严格隔离；`?source=ths` 失败即 5xx，不再下沉 zzshare |
| D3 | THS 侧栏 cid-only 行 | **用 cid→platecode 映射解析**；**map miss 时运行期抓一次 gn 详情页解析并回写**（已探测可行，见 §3；成本论证见 §6 末段） |
| D4 | 落地方式 | **A：拆干净 + 存量重建**（不做增量迁移，不做逐行判定） |
| D5 | `include_quote=true` | 改为 **THS 单源两层**：`top_n≤50` 走 AJAX，`>50` 走 F10 + 行情缓存 union |
| D6 | 命名收敛范围 | **只做第 1+2 层**（board 标识符组 + 同文件冗余）；跨层命名（`turnover_rate`/`prev_close` 等）单独立项 |
| D7 | zzshare `amount` 单位 | **在 zzshare fetcher 边界换算成亿元**（与 THS 原生同 scale，对外单值）；`amount_unit` 声明保留、恒为 `"yi"`；merge 期的隐式换算随 merge 一起删除 |
| D8 | cid→platecode 映射本地备份 | **做**：独立表 + 窄 CSV，定位为 seed / 观测缓存，**非权威**（live 优先） |

---

## 3. cid → platecode 映射（D3 / D8）

### 3.1 探测结论

`GET /gn/` 的 HTML 同时含两份数据，此前只用了其中一份：

1. `gnSection` JSON（今日 292 条）：`platecode` + `platename` + `cid` 三元组齐全
2. 侧栏 `cate_items` 的 `<a href=".../gn/detail/code/{cid}/">名称</a>` 列表：**只有 cid**

二者在**同一次响应**内，按 cid join 即可得到 platecode：

```
侧栏:       <a href="http://q.10jqka.com.cn/gn/detail/code/309121/">AI PC</a>
gnSection:  {"358":{"platecode":"886071","platename":"AI PC","cid":"309121",...}}
```

**实测（活库探测）：141 个 `cid IS NULL` 行中，47 个当天即可用此方式解出。**

兜底路径：`GET /gn/detail/code/{cid}/` 的 HTML 含且仅含一个 886 码（`309121` → `886071`），可逐板补齐冷门板块。

**实测 CSV 覆盖**（按 `board_type` 精确过滤，2026-09-11 复算）：

| CSV 内容 | 行数 | 处置 |
|---|---|---|
| concept 行 + 真 3xxxxx cid = **genuine 映射** | **376 行 / 376 distinct cid（0 重复）** | 导入 `ths_board_id_map`（cid 主键，实测无折叠） |
| concept 行但 `cid == code`（旧版布局把 platecode 写进了 cid 列） | 118 | **必须排除**（不是映射） |
| industry 行（`cid == code`，identity） | 104 | 导入（identity，使 `resolve` 无启发式） |

行数守恒（2026-09-11 按 Plan 1 Task 2 Step 1 的脚本复算）：797 = 192（`cid` 空）+ 118（`cid == code`）+ 104（industry）+ 376（genuine concept）+ 7（`code` **空**的行）。**最终 seed 产物 = 480 条**（376 + 104）。

那 118 行的 `cid` 组成是 **885×98 / 886×12 / 883×1 / 803×6 / 710×1** —— 只有 **8 行**真是 zzshare code，其余 **110 行是 THS 自己的 platecode 被写进了 cid 列**。（早前版本把这整组说成 "zzshare code 被写进 cid 列"，是错的。）这些值都不与真 3xxxxx 碰撞，故不影响查表；但生成器与 loader 仍必须按 `cid` 首字符/长度校验，禁止把它们当作映射导入。

**这 110 行在 §10.1 的 CSV 拆分时必须把 `cid` 置空**：它们的 `code` 前缀是 885/886，前缀拆分规则会把它们留在 `stock_board_ths.csv`；若 `cid` 原样保留，入库后就会出现 "ths 行的 `ths_cid` = 885xxx"，违反 §4 硬规则 6，并使 `resolve_ths_cid` 把一个 platecode 当作 cid 喂给 AJAX 腿——正是本 spec 要消灭的那类错配。

**覆盖率口径（活库探测，不可由 in-tree artifact 复现）**：`stock_board` 中 `source='ths' AND cid IS NULL` 有 141 行，seed 的 480 条可解出其中 138 条（98%）；未覆盖的 3 条是 CSV 快照（2026-07-22）之后新建的板块。备份 CSV 里没有 3xxxxx 形状的 `board_code`（membership 备份 0 行、`stock_board` 备份 0 行），所以这组数字只能在活库上复算。

### 3.2 设计

新增窄表，作为"两套 id 关系"的唯一查询点：

```sql
CREATE TABLE IF NOT EXISTS ths_board_id_map (
    cid        TEXT PRIMARY KEY,   -- 3xxxxx（THS 概念的稳定内部 id）
    platecode  TEXT NOT NULL,      -- 885xxx / 886xxx（公开身份）
    name       TEXT,
    board_type TEXT,               -- 目前仅 concept 需要；industry 的 cid==platecode 也登记以便统一查询
    observed_at DATETIME
);
```

**优先级必须是 live 覆盖 seed，不可反向**：

```
启动 seed（CSV）
  → 运行时 live gn sweep upsert（冲突以 live 为准 + 告警）
  → map miss 时走 gn detail 页单次解析，回写 map
```

理由：CSV 只含**历史上被 THS 展示过**的映射。若让 CSV 覆盖 live，THS 改号将永远无法被发现，直到某天 404 才爆。

**未验证项（必须诚实标注）**：已验证同一天内 `gnSection` 与 gn 详情页对 `309121` 一致给出 `886071`；**未验证**长期稳定性（THS 是否改号/回收 platecode）。这正是"live 优先"不可省略的原因。

### 3.3 生成器

`stock_data/tools/refresh_ths_board_id_map.py`（放在 `stock_data/tools/` 而非顶层 `tools/`：前者是有 `__init__.py` 的真包、已被 `tests/test_build_membership_index.py` 以 `from stock_data.tools import ...` 引用；顶层 `tools/` 只能靠 PEP 420 命名空间包在 repo 根为 CWD 时侥幸可导入）：限速扫 gn（沿用 `ThsFetcher._THS_PAGING_JITTER_S`，`ths_fetcher.py:1740`），对未覆盖的 cid 走详情页；输出 CSV 并对**上一版做 diff，分「新增 / 改号 / 消失」三类**——这是发现 THS 改号的唯一探测点。

生成器是**工具期**的批量补齐；运行期（`ThsFetcher._merge_concept_sources`）另有一个**单板**兜底：map miss 时抓一次 gn 详情页并回写（D3 原始设计，见 §6）。两者共用 `ThsFetcher.extract_platecode_from_detail`，回写都走 `upsert_ths_board_id_map`（后写覆盖 ⇒ live 恒优先）。

---

## 4. id 契约（D1 / D3）

| source | 公开标识 `board_code` | `ths_cid` 列 | 取值域 |
|---|---|---|---|
| `ths` | THS platecode | 仅 THS 内部 cid | 概念 885xxx / 886xxx，行业 881xxx |
| `zzshare` | zzshare plate_code | **恒为 NULL** | 801xxx / 803xxx / 710xxx / 883xxx |
| `eastmoney` | BKxxxx | NULL | — |
| `zhitu` | sw_xxx | NULL | — |

硬规则（docstring + 不变量测试双钉）：

1. 非 THS 来源的 code 不得写入 `ths_cid`。
2. `ths_cid` 不得写入 `board_code`。
3. `zzshare` 行 `ths_cid` 必须为 NULL。
4. 删除 `code = platecode or code` 兜底（`update_cached_boards:2227`）：ths 行以 `ths_cid` 为稳定键、platecode 为公开键。
5. `stock_board` 增加 purge：`update_cached_boards` 改为 `(board_type, source)` 的 snapshot replace（DELETE-then-INSERT），消除第 3 类双行残留。
6. `ths_cid` **只接受 THS cid 形态**（概念 3xxxxx / 行业 881xxx），其余一律 NULL —— 尤其 **platecode 不得写入 `ths_cid`**。写入口由 `_is_ths_cid()` 校验（`upsert_ths_board_id_map` 同一守卫）；历史遗留的 `cid == code == 885/886` 行（110 行）在 §10.1 CSV 拆分时置空，并在 §11 的不变量测试里钉住。

---

## 5. 命名契约（D6，第 1+2 层）

### 5.1 第 1 层：本次必做

| 语义 | 唯一名 | 淘汰 |
|---|---|---|
| 板块公开标识 | `board_code` | 行 key `code`、行 key `platecode` |
| THS 内部概念 id | `ths_cid` | `cid`、`_resolve_ths_cid_from_code` |
| 板块类型 | `board_type` | `type` |

配套硬规则：**board 路径上禁止裸 `code`** —— 必须带限定（`board_code` / `stock_code` / `ths_cid`），用测试扫 dict key 钉住。

### 5.2 第 2 层：同文件顺手收敛

- 删除 `_resolve_ths_cid_from_platecode` 别名层（`board.py:808`，同一函数两个名字，`ths_fetcher.py:1444` 仍在用旧名）。
- `_read_boards_from_db` 不再同时返回 `type` 与 `board_type`。

### 5.3 明确不在本次范围（单独立项）

`turnover_rate`/`turnover_pct`、`amplitude`/`amplitude_pct`、`pre_close`/`prev_close`、quote 对象的 `code`/`stock_code`。理由：跨 K 线 / quote / indicator / 全部 13 fetcher（150 处 `"code"`、521 处 `stock_code`），混入会让 diff 与测试范围失控；且需先定"以 `schemas.py` 为规范名"还是"以内部为规范名"。

已知现场（留作立项依据）：`boards.py:91/431/1366` 手工 `turnover_pct=s.get("turnover_rate")`；`boards.py:99` 手工 `amplitude_pct=s.get("amplitude")`；`board.py:1321` 靠 `("prev_close","pre_close")` 映射表桥接，而 `board.py:1307` 注释记着该 key 曾写错导致"路由永远读不到值"的事故。

---

## 6. ThsFetcher

- `get_all_boards`：统一输出 `board_code=platecode` / `ths_cid=cid`；**不做任何按名匹配**。侧栏行解析顺序：`platecode 已知 → 直接用` → `查 ths_board_id_map` → `miss 时 gn detail 页单次解析并回写` → 仍失败则该行不进列表并记 debug。
- 删除 `_merge_concept_sources` 中 `platecode: None` 的中间态（`ths_fetcher.py:2015`）。
- 运行期兜底 `ThsFetcher._resolve_platecode_from_detail(ths_cid)`：`resolve_ths_platecode` miss 时抓一次 `/gn/detail/code/{cid}/`，解析到就 `upsert_ths_board_id_map` 回写。**放在 fetcher 而非 persistence**，保持持久层"不发网络"的性质。
- `get_board_stocks`（AJAX）继续接收 `ths_cid`；`get_board_stocks_full`（F10）继续接收 `platecode`。
- 删除 zzshare 相关的全部注释/兜底说明（`ths_fetcher.py:1609, 2300, 2310, 2337, 2377, 2455, 3176`）。

净效果：`ths_fetcher.py` 内对 zzshare 的依赖归零（当前 7 处均为注释/日志，无运行期依赖）。

**运行期兜底的成本论证（2026-09-11 修订）**：`ths_fetcher.py:1784-1790` 的既有注释论证过"每次 refresh 多 88 个请求"必须避免——但那是在**没有 seed** 的前提下测得的 88。seed 落地后，侧栏 miss 的残余只有个位数，且回写使**每个板块一辈子只花 1 个请求**。更关键的是存在性论证：能从侧栏看到 = 板块在 THS 存在 = 它的详情页一定带 platecode（实测 `309121 → 886071`），所以 **miss 不等于"解不出"，只等于"seed 快照之后新建的、且刷新工具尚未跑过"**。因此运行期兜底把"记得跑刷新工具"这个运维依赖换成了自愈，代价近零。工具期生成器（§3.3）仍保留，负责批量补齐与改号 diff。

---

## 7. Persistence

**删除**（净值约 -400 行）：

- `fetch_boards_with_zzshare_backfill`（`board.py:913-1003`）
- `fetch_board_stocks_with_zzshare_fallback`（`board.py:1006-1252`）
- `_merge_ths_zzshare_by_name`（`board.py:811-883`）
- `_normalize_zzshare_list_quote_units`（`board.py:886-910`；由 D7 的显式单位声明取代）
- `_STOCK_BOARDS_SOURCE_ALIAS`（`board.py:177`）

**改为**：

- `get_board_list(source=X)` 直调 `manager.get_all_boards(source=X)`，无 merge 分支。
- 缓存 key 全部带 source：`_read_board_stocks_from_db(board_code, source)`、refresh tracker `f"{board_code}:{source}"`（现为硬编码 `:ths`，`board.py:1454`）、`update_cached_board_stocks(board_code, source, ...)`（现为硬编码 `"ths"`，`board.py:1503/1617`）。
- `_resolve_ths_cid_from_code` 限定 `source='ths'`（已是），改名 `resolve_ths_cid(board_code)`，并**删除 `row["code"]` 回退**（该回退正是"801xxx 被当成 THS cid"的入口，§1.3 机制 5）。行业行 `cid == code`（881xxx）由构造保证，不受影响。
- `VALID_SOURCES` / `VALID_SUBTYPES_BY_SOURCE` / `_BOARD_STOCKS_VALID_SOURCES` / `_STOCK_BOARDS_VALID_SOURCES` 收录 `zzshare`。
- `_validate_type_for_source` 的 zzshare special 提示文案更新（不再说"用 type=concept&subtype=同花顺题材 代替 type=special"以外的旧口径）。
- `update_cached_boards` 增加按 `(board_type, source)` 的 purge。
- zzshare 板块行在 **fetcher 边界**把 `amount` 由元换算成亿元（`/1e8`），并携带 `amount_unit = "yi"`；THS 行同样声明 `"yi"`。`_normalize_zzshare_list_quote_units` 的 merge 期隐式换算随 merge 一起删除（D7）。两个 fetcher 都只在 `include_quote=True` 时打 `amount_unit`（`include_quote=False` 无 amount，单位声明无意义，留 `None`）。
- **缓存命中路径的 `effective_source` 不再硬编码 `"ths"`**（`board.py:1464`），改为该行的 `source`。原先 zzshare 请求走缓存时会被署名成 ths。

---

## 8. include_quote=true 路径（D5）

**THS 单源两层，按 `top_n` 分流：**

| 层 | 触发 | 上游 | 字段覆盖 |
|---|---|---|---|
| AJAX | `top_n ≤ 50` | `q.10jqka.com.cn/{gn\|thshy}/detail/code/{ths_cid}/...` | 18/18（`open/high/low/prev_close/volume` 由行情缓存 union 补） |
| F10 | `top_n > 50` | `basic.10jqka.com.cn/48/{platecode}/` | 15/18 |

**F10 层缺 `change_speed` / `free_float_shares` / `float_market_cap`，且这是字段级等价而非降级。**

实测依据（2026-09-11）：

- `get_board_stocks_full` 在概念（78 行）与行业（157 行）两条路径上，`speed_current` / `speed_change_pct` / `float_share_yi` / `float_mv_yi` / `eps` / `ls_based_ratio` / `rise_speed` **全部 0 非空**（模板占位符，从不填充）；仅 `rank` 在概念路径 78/78 有值。
- 今日 `top_n>50` 的行来自 zzshare suffix，而 `_enrich_rows_with_market_quote` 明确 **NEVER set** 这三个字段（`board.py:1276-1277`）——**今天的后缀行本来就没有它们**。

因此该切换为严格改进：字段覆盖不降，去掉对 zzshare 的依赖，并额外获得 `rank`（概念）。

**契约变更**：`top_n>50` 路径下 `change_speed` / `free_float_shares` / `float_market_cap` 恒为 `None`，写入 `BoardStockInfo` 字段说明与 api-reference。

**并存收益**：两层互为同源兜底（AJAX 瞬时 401 时 F10 可服务，反之亦然），不再是跨源兜底。

---

## 9. 路由 / schema

- `/boards`、`/boards/{board_code}/stocks`、`/stocks/{stock_code}/boards` 的 `source` Literal 增加 `zzshare`。
- `/stocks/{stock_code}/boards?source=zzshare`：仅读持久化（zzshare 无反向上游 API）→ 冷源经 `cold_sources` 暴露，沿用现有契约。
- `/boards/{board_code}/history?source=zzshare` → 400（zzshare `plate_kline` 仅支持 `883957`，已无实现）。
- `/boards/{board_code}/quote` **本来就没有 `?source=` 参数**（`boards.py:745-798`，内部硬编码 `source="ths"`，docstring 764-775 与 `BoardQuoteResponse.source` 的说明都已写明）。因此 `?source=zzshare` 会被 FastAPI 静默忽略并照常返回 THS 数据 —— 不是 400/422。本次不新增该参数（THS 是唯一实现 `get_board_realtime` 的 fetcher），但要在 `api-reference.md` 写明"该参数不存在且被忽略"，并加一条测试钉住，免得客户端误以为它生效。
- `effective_source` 保留（同源多腿仍有意义），但跨源语义消失；`query_source != effective_source` 将只反映同源换腿。
- `agent.py` 中硬编码 `source="ths"` 的 8 组（`334-336, 420-422, 447, 752-758, 1260-1262, 1572, 1584-1586, 1610`，另 `1497` 引用被删的 `_normalize_zzshare_list_quote_units`）逐一确认语义：聚合端点默认 THS 可保留，但需确认无"本意想要 zzshare 补全"的残留。
- `/boards` 的 `sort_by` / `limit` 保持现状（路由层单点后处理）。

---

## 10. 数据迁移（D4：纯重建）

不做逐行判定（无法区分 885/886 行的真实来源），走全量重建：

1. CSV 拆三份：
   - `stock_board_ths.csv`：仅 THS 原生行（platecode 885/886/881）+ **合法 cid**。**`cid` 必须按 `_is_ths_cid` 过滤后再写**：非 THS cid 形态的一律置空。实测需要置空的是 **110 行**（`cid == code == 885xxx/886xxx`，见 §3.1），另 8 行 `cid == code` 属 803/710/883 前缀、随前缀规则进 zzshare 文件（该文件 `cid` 一律留空）。
   - `stock_board_zzshare.csv`：原 801/803/710/883 行 relabel 为 `source='zzshare'`；`cid` 列一律置空（spec §4 硬规则 3）。
   - `ths_board_id_map.csv`：新，**480 条**（376 concept cid + 104 industry identity）`(cid, platecode, name)`，可独立 diff / 回归。
2. `stock_board_membership_ths.csv` → **整体 relabel 为 `source='zzshare'`**（新增 `stock_board_membership_zzshare.csv`），因其数据本就是 zzshare 抓取；**原文件删除**（保留原名会让每次 `STOCK_DB_INIT=true` 都把 zzshare 数据灌回 `source='ths'`）。代价：`source='ths'` 的反向索引冷启动为空，首次走既有 cold-fallback。
3. `board_csv.py`：`_SUPPORTED_STOCK_BOARD_SOURCES` 增加 `zzshare`；`seed_all_from_backup_dir` 增加映射 CSV 的 seed，且**顺序在 board 之前**（侧栏行解析依赖 map）。
4. 重建流程：`STOCK_DB_INIT=true` → seed CSV →（可选）`BOARD_BACKFILL_ON_STARTUP=true` 重灌 ths。
5. `persistence/backfill.py` 两阶段改为 source-specific，不再调用被删除的 merge 函数。
6. `tools/fix_stock_board_ths_csv.py` 退役（其职责由 §3.3 生成器承接）。
7. `_migrate_zzshare_special_to_concept` 保留（历史数据仍可能带 `special`）。

---

## 11. 测试

**重写**（约 10 文件 / 40 用例）：`test_persistence_board_merge.py`（删 merge 相关全部）、`test_persistence_board_f10_fallback.py`、`test_boards.py::TestBoardsSourceUnification`、`test_persistence_board_topn.py`、`test_persistence_zzshare_fallback_live.py`、`test_stock_boards_reverse_route.py` 的 alias 用例、`test_boards_api.py` 的 alias/422 用例、`test_boards_history_route.py::TestSourceExpansion`、`test_board_backfill.py`、`test_persistence_origin.py` 的 effective_source 断言。

**新增**：

- id 契约不变量测试：`ths_cid` 非 NULL ⇒ `source=='ths'` **且必为 3xxxxx/881xxx**（禁止 platecode 形态，§4 硬规则 6）；`zzshare` 行 `ths_cid IS NULL`；`board_code` 不得为裸 cid（非 881xxx 的 3xxxxx）；`ths_cid` 非 NULL 的 ths 行满足 `resolve_ths_platecode(cid) == board_code`（已在 479 行上实测成立）。
- 命名契约测试：扫 board 路径的 dict key，禁止裸 `code`。
- 严格隔离测试：spy 断言 `?source=ths` 全程不触发任何 zzshare 调用（反例即 D2 回归）。
- 映射优先级测试：CSV seed 与 live 冲突时以 live 为准 + 告警。
- 分层契约测试：`top_n>50` 路径三字段为 None；`top_n≤50` 路径 18/18。

---

## 12. 文档

- `docs/board-source-semantics.md`：cache-key 段现为"post-unification 共享 ths"，需改为 per-source；`effective_source` 段改写（跨源 fallback 语义消失）。
- `CLAUDE.md`：Source Tracking 矩阵、board 路由表、Fetcher overview 的 ZzshareFetcher 行（"Board endpoints: not a public source label" 失效）、`fetcher_method` 表、anti-patterns（删 `effective_source` 跨源检测条目，增裸 `code` 禁用条目）。
- `api-reference.md`：source 取值、`effective_source` 语义、`top_n>50` 三字段为 None、`amount_unit` 新字段。
- `.env.example`：如引入映射 CSV 路径 env，同步补注释。

---

## 13. 已知行为变化（breaking）

| # | 变化 | 影响 |
|---|---|---|
| 1 | `?source=ths` 结果集变小 | `/boards?source=ths` 概念板块约 863 → 约 485 行（240 行 zzshare 板块移出） |
| 2 | `?source=zzshare` 由 422 变 200 | 加法；但客户端此前用它探测"非法 source"会失效 |
| 3 | `/stocks/{code}/boards` 的 ths/zzshare 不再返回相同结果 | 原来靠 alias 拿到相同数据者需改 |
| 4 | `data_source='persistence'` 之外，`effective_source` 不再表示跨源 fallback | 文档与客户端解析逻辑需更新 |
| 5 | 缓存 key 含 source | 旧行（全 `source='ths'`）在重建后失效，**必须重建**，不可只发代码 |
| 6 | zzshare 板块 `amount` 由「merge 期隐式换算」改为「fetcher 边界换算」，并新增 `amount_unit`（恒 `"yi"`） | 数值口径**不变**（仍是亿元），只是换算位置与可读声明变了；`amount_unit` 缺失（`include_quote=false`）即无 amount |
| 7 | `/stocks/{code}/boards` 省略 `?source=` 时的默认集合由 3 源扩到 4 源（含 zzshare） | 默认响应内容变化；否则会静默丢弃 11.5 万行 zzshare membership（D1 已定 zzshare 为一等公民） |
| 8 | `/boards/{code}/stocks` 的 `top_n` 上限由 50 放宽到 800 | `>50` 走 F10 层，该层 `change_speed` / `free_float_shares` / `float_market_cap` 恒为 `None`（§8） |
| 9 | 缓存命中路径的 `effective_source` 由硬编码 `"ths"` 改为该行实际 source | 原先 zzshare 请求命中缓存会被署名成 ths；改后 `query_source == effective_source` 在命中时也成立（`data_source` 仍为 `"persistence"`） |
| 10 | `stock_board.ths_cid` 语义收紧：非 THS cid 形态一律 NULL | 历史 110 行 `cid == 885xxx/886xxx` 在重建后变 NULL；这些行仍可经 platecode 定位，只是不再提供（错误的）cid |

---

## 14. 风险与缓解

| 风险 | 缓解 |
|---|---|
| 存量 967 行无法逐行判定来源 | 纯重建（D4），不做逐行迁移；CSV 按 code space 规则拆分 |
| CSV 映射过期 / THS 改号 | live 优先于 seed；生成器 diff 输出「新增/改号/消失」；不一致时告警 |
| 侧栏 cid 在 map 与 live 都解不出（新板块） | 该行不进 board 列表 + debug 日志；生成器下次运行补齐 |
| THS 两腿可用性波动（本次实测到瞬时 401） | 两层同为 THS 单源，互为兜底；不再依赖 zzshare |
| 公开契约变化面较大（§13 共 10 项 breaking） | 分阶段提交（§15），每阶段可独立回滚；文档同批更新 |
| 重建后反向索引（115,081 行）只有 zzshare 一份 | zzshare 无反向上游 API，反向数据依赖 CLI/启动期重建；在 `cold_sources` 与运维文档中显式说明 |

---

## 15. 分阶段实施（每步独立提交 / 可回滚）

| 阶段 | 内容 | 依赖 |
|---|---|---|
| 1 | `ths_board_id_map` 表 + seed + `tools/refresh_ths_board_id_map.py`；CSV 拆三份 | — |
| 2 | ThsFetcher：统一 `board_code`/`ths_cid`，侧栏行走 map，删 zzshare 注释 | 1 |
| 3 | id 契约 + 命名契约（第 1+2 层）+ 不变量测试 | 2 |
| 4 | Persistence：删 merge/fallback，cache key 带 source，`update_cached_boards` 加 purge | 3 |
| 5 | 路由 / schema 放开 zzshare，收紧 history/quote；agent.py 逐一确认 | 4 |
| 6 | include_quote 两层（AJAX ≤50 / F10 >50 + union + 显式单位） | 4 |
| 7 | 测试重写 + 新增五类测试 | 3-6 |
| 8 | 文档更新（4 份） | 5-6 |
| 9 | `STOCK_DB_INIT=true` 重建 + 端到端验证（含 422/200 回归清单） | 全部 |

### 实施计划（3 份，每份可独立交付、每次 commit 后测试为绿）

| 计划 | 覆盖阶段 | 交付物 | 公开影响 |
|---|---|---|---|
| `docs/superpowers/plans/2026-09-11-board-id-map-plan.md` | 阶段 1（映射部分）+ 阶段 2（侧栏解析半部分） | `ths_board_id_map` 表 + seed CSV + 刷新工具 + ThsFetcher 侧栏解析（查表 + 运行期详情页兜底 + 回写） | **无** |
| `docs/superpowers/plans/2026-09-11-board-source-split-plan-2-internal.md` | 阶段 3-4 | id/命名契约、删 merge/fallback、cache key per-source、`update_cached_boards` purge、`backfill.py` ths-only | 公开**行为**变化（breaking #1），API 参数面不变 |
| `docs/superpowers/plans/2026-09-11-board-source-split-plan-3-cutover.md` | 阶段 5-9 | zzshare 转正、include_quote 两层、5 类新测试、4 份文档、重建验收 | 公开**接口**变化（breaking #2-#8） |

两处切分调整（相对上面的阶段表）：
- **阶段 1 的"CSV 拆三份"**移到 Plan 3 的 Task 3 —— CSV 拆分必须与 zzshare 转正同批落地，否则中间态会出现 `source='zzshare'` 的 CSV 行而 CSV loader 尚不认 zzshare。
- **被测代码一旦被删，它的测试必须在同一份计划里删掉**，否则该 commit 后测试是红的。因此 Plan 2 内联了 24 个 DELETE，Plan 3 内联了其余 REWRITE。

---

## 16. 附：实测取证清单

| 结论 | 取证方式 |
|---|---|
| code space 不相交 | `stock_board` 按 code 前缀分组（885/886/881 vs 801/803/710/883） |
| 167 个 name 多 code | SQL group by name having count(distinct code) > 1 |
| 202 行 bogus cid | SQL 扫 `ths_cid` 落在 zzshare 前缀区间的行 |
| 141 行 `ths_cid IS NULL` / 138 行可由 seed 解出（98%） | 活库 SQL JOIN；**不可由 in-tree artifact 复现**（见 §3.1 末段） |
| 47/141 可同响应解出 | `GET /gn/` 内 `gnSection` cid ∩ 侧栏 cid |
| `gn/detail/code/309121/` 含 886071 | 正则扫详情页 HTML 的 886 码 |
| F10 三字段恒空 | `get_board_stocks_full` concept(78)/industry(157) 非空计数 = 0 |
| `top_n≤50` 与 `>50` 字段等价 | AJAX 50 行与 F10 78 行字段集对比 |
| `effective_source='zzshare'` 出现在 `?source=ths` | `curl /boards/801001/stocks?source=ths&include_quote=false` |
| ths/zzshare 反向结果逐字节相同 | `curl /stocks/600519/boards?source=ths\|zzshare` 对比 |
</content>
</invoke>
