# slug 词汇表

> **参考资料，非 skill**。配套 `market-principles §10` 附录 A 使用——agent 创建主线 / 龙头 / 板块 / 事件 / 假设的稳定标识符（`标识` 字段）时，优先查本表。
>
> **必读内容**：slug 硬规则 + 创建工作流见 [market-principles §10 附录 A](./market-principles.md#附录-aslug-命名约束强制)。
>
> **本表定位**：L1/L2/L3/L4 词汇表 + 派生规则 + 反模式 + 维护规则。按需查阅，不需要主动触发。

> **核心约束**：slug 一旦创建永不修改（即使主线改名 / 合并 / 强度变化）。改名 / 合并通过 `MERGED → 新slug` 处理，原 slug 保留作 `已归档`。

---

## 1. 词汇表分级规则

| 级别 | 命名来源 | 优先级 | 使用场景 |
|---|---|---|---|
| **L1** | 行业缩写（CPO / NPO / PCB / eVTOL 等） | 最高 | 行业惯用，直接用 |
| **L2** | 核心词映射（中文核心词 → 英文） | 次高 | 单一板块或板块复合 |
| **L3** | 驱动因素（跨板块主题） | 中 | 跨板块主题（如"地缘避险"） |
| **L4** | pinyin 兜底 | 最低 | L1/L2/L3 都查不到时使用，必须标注 `[fallback: pinyin]` |

**派生规则**：
- **单一板块** → L2（查核心词映射）
- **板块复合** → L2 取核心驱动 + 修饰词（如 `compute-super-node`）
- **跨板块主题** → L3（按驱动因素命名）
- **生僻概念** → L4（pinyin）+ 备注待优化

**复合主线长度限制**：slug 最多 3 段（如 `compute-super-node`），多了只取核心驱动，其他修饰通过 `触发条件` 字段描述。

---

## 2. slug 创建工作流

> 完整工作流见 [market-principles §10 附录 A](./market-principles.md#附录-aslug-命名约束强制) 第 3 节"slug 创建工作流"。本节只是简版速查。

```
1. 识别主线范围（单一板块 / 板块复合 / 跨板块主题 / 生僻）
2. 查本词汇表（L1 → L2 → L3 → L4）
3. 全局查重（grep 已用 slug）
4. 写 slug 命名说明
5. changelog 记录派生来源
```

---

## 3. L1 行业缩写（最高优先级，直接用）

| 中文 | slug | 适用实体 |
|---|---|---|
| 共封装光学 | `cpo` | 板块 / 主线 |
| 近封装光学 | `npo` | 板块 / 主线 |
| 印制电路板 | `pcb` | 板块 |
| 电动垂直起降 | `evtol` | 板块 / 主题 |
| 交易所交易基金 | `etf` | 板块 |
| 涨停 | `zt` | 池类型 |
| 跌停 | `dt` | 池类型 |
| 大语言模型 | `llm` | 板块 |
| 首次公开募股 | `ipo` | 事件 |

**派生示例**：
- "CPO / 光通信板块" → `ml:cpo` 或 `ml:optical-cpo`
- "超节点（算力硬件链）" → 含 `super-node`（L1/L2 复合）

---

## 4. L2 核心词映射（板块名清晰时）

### 4.1 单一板块核心词

| 中文核心词 | slug 映射 | 备注 |
|---|---|---|
| 半导体 | `semi` | 行业惯用 |
| 半导体设备 | `semi-equipment` | 复合 |
| 半导体材料 | `semi-material` | 复合 |
| 半导体封测 | `semi-packaging` | 复合 |
| 算力 / 算力链 | `compute` | 字面翻译 |
| 存储 | `storage` | 字面翻译 |
| 光通信 / 光模块 | `optical` | 字面翻译 |
| 电力 / 绿电 | `power` | 字面翻译 |
| 电网 | `grid` | 字面翻译 |
| 黄金 / 贵金属 | `gold` | 行业惯用 |
| 油气 | `oil-gas` | 双词 |
| 军工 | `military` | 字面翻译 |
| 资源 | `resource` | 字面翻译 |
| 煤炭 | `coal` | 字面翻译 |
| 白酒 / 酒 | `liquor` | 字面翻译 |
| 消费 | `consumer` | 字面翻译 |
| 食品饮料 | `food-beverage` | 双词 |
| 创新药 | `innovative-drug` | 复合 |
| 医药 / 医药板块 | `medicine` | 字面翻译 |
| 医疗器械 | `medical-device` | 复合 |
| 银行 | `bank` | 字面翻译 |
| 金融 | `finance` | 字面翻译 |
| 保险 | `insurance` | 字面翻译 |
| 地产 / 房地产 | `real-estate` | 字面翻译 |
| 新能源车 | `nev` | 行业惯用 |
| 锂电池 / 锂电材料 | `lithium` | 字面翻译 |
| 储能 | `energy-storage` | 复合 |
| 钢铁 | `steel` | 字面翻译 |
| 化工 | `chemical` | 字面翻译 |
| 影视 / 影视院线 | `media` | 字面翻译 |
| 游戏 | `game` | 字面翻译 |
| 教育 | `education` | 字面翻译 |

### 4.2 复合主线派生（最多 3 段）

| 主线场景 | slug 派生 | 说明 |
|---|---|---|
| 超节点 / 算力新基座 | `compute-super-node` | 核心驱动 `compute` + 关键术语 |
| 半导体 + 算力（板块复合） | `semi-compute` | 取核心驱动 |
| CPO + 光通信（板块复合） | `cpo-optical` | L1 + L2 复合 |
| 半导体设备 + 封测 | `semi-equipment-packaging` | 复合 |
| 锂电池 + 上游材料 | `lithium-upstream` | 板块 + 方向 |

---

## 5. L3 驱动因素（跨板块主题）

| 中文驱动因素 | slug 派生 | 实战示例 |
|---|---|---|
| 地缘避险 | `geo-safe-haven` | 主线 3（黄金 + 油气 + 资源） |
| 政策刺激 | `policy-stimulus` | 未来"六张网"类政策主线 |
| 涨价 / 提价 | `price-hike` | 主线 8 涨价上游 |
| 资金回流 | `fund-inflow` | 增量资金主线 |
| 业绩兑现 | `earnings-realize` | 半年报披露主线 |
| 资金减仓 | `fund-outflow` | 机构减仓警示主线 |
| 高位分歧 | `high-divergence` | 高标股首阴主线 |

**L3 vs L2 边界**：
- L2：单一板块或板块复合（半导体 + 算力是相关板块）
- L3：跨板块的驱动因素（地缘避险触发黄金 + 油气 + 资源等不相关板块）

---

## 6. L4 兜底（pinyin）

仅当 L1/L2/L3 都查不到时使用。**强制标注** `[fallback: pinyin]` 并 changelog 记录派生来源。

| 实战场景 | L4 slug | 备注 |
|---|---|---|
| 可控核聚变（未来可能） | `ml:ke-kong-ju-bian` | 待词汇表升级时改 L1/L2 |
| 脑机接口 | `ml:nao-ji-jie-kou` | 中信建投 7-22 提到 |

**L4 缺陷**：pinyin 难读，agent grep 容易出错。**尽量避免 L4**——L1/L2/L3 应覆盖 90%+ 场景。

---

## 7. 实战样本 slug 映射（基于 2026-07-22 market_tracking.md）

> 本节仅供参考。实战文档改造是另一个独立任务，本词汇表只列出 slug 映射供参考。

| 主线名称 | 标识 | 状态 | slug 命名说明 |
|---|---|---|---|
| 主线 0：超节点 / 算力新基座 | `ml:compute-super-node` | 活跃 | L2 派生：核心驱动 compute + 关键术语 super-node（WAIC 2026 提出） |
| 主线 1：半导体 / 算力 / 存储 / 光通信 | `ml:semi-compute` | 活跃 | L2 复合：semi + compute，取核心驱动 |
| 主线 2：国产 AI / Kimi 概念 / 算力应用 | `ml:llm-kimi` | 减弱 | L1 llm + L2 缩写 Kimi（核心驱动） |
| 主线 3：地缘避险（黄金 / 油气 / 军工 / 资源） | `ml:geo-safe-haven` | 活跃 | L3 跨板块驱动 |
| 主线 4：电力 / 新型电网 | `ml:power-grid` | 活跃 | L2 双关键词 |
| 主线 5：消费 / 白酒 | `ml:consumer-liquor` | 减弱 | L2 双关键词 |
| 主线 6：创新药 / 医药 / 医疗器械 | `ml:innovative-drug` | 减弱 | L2 复合 |
| 主线 7：低空经济 | `ml:evtol` | 减弱 | L1 行业缩写（eVTOL 是低空经济核心标的） |
| 主线 8：涨价上游 / 锂电材料 / 资源 | `ml:price-hike` | 减弱 | L3 驱动因素 |
| ~~主线 9：贵金属 / 资源~~ | `ml:gold-resource` | 已归档 | 已合并入 `ml:geo-safe-haven`（2026-07-22 12:00） |

---

## 8. 已废弃 slug（已归档，保留作审计）

| slug | 原状态 | 合并入 | 合并时间 | 合并原因 |
|---|---|---|---|---|
| `ml:gold-resource` | 已归档 | `ml:geo-safe-haven` | 2026-07-22 12:00 | 主线 9（贵金属 / 资源）已合并入主线 3（地缘避险），按 L3 驱动因素统一 |

---

## 9. 词汇表维护规则

- **更新时机**：每年一次词汇表 review（建议每年 12 月）
- **清理已归档 slug**：合并超过 1 年的 slug 可从"已废弃"区删除（保留变更轨迹在 git 历史）
- **补充新 L1/L2/L3**：实战中出现的新行业缩写 / 核心词映射 / 驱动因素，及时加入本表
- **changelog 同步**：词汇表变更时，agent 在 tracking changelog 追加 `[glossary_update]` 记录

---

## 10. 反模式（不要做）

- ❌ **不要** 自由命名 slug（如"我觉得这个叫 compute-power 比较好"）— 必须按本表规则派生
- ❌ **不要** 创建 `xxx-v2` / `xxx-new` / `xxx-latest` 版本后缀 — 区分通过 `状态起始` 和 `当日引用` 实现
- ❌ **不要** 用通用词（`policy` / `news` / `market` / `industry` / `theme`）
- ❌ **不要** 直接用中文做 slug（如 `ml:超节点`）— 必须英文
- ❌ **不要** 重复创建已存在 slug（如已用 `ml:compute-super-node`，不要再创建 `ml:super-node-compute`）— 全局查重必须执行
- ❌ **不要** 修改已存在的 slug（即使主线改名 / 合并）— 通过 `MERGED → 新slug` 处理