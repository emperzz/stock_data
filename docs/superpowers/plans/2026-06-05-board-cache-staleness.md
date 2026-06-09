# stock_board_cache 决策树

```
请求: GET /boards?type=concept
        ↓
get_board_list("concept", "eastmoney", refresh=False, include_quote=False)
        ↓
needs_refresh = refresh OR include_quote OR _is_first_call_of_day(...)
        ↓
   ┌────┴────┐
   │         │
 False     True
   │         │
   ↓         ↓
读 SQLite    调 manager.get_all_concept_boards(...)
cache 表      (akshare 上游)
   │         │
   ↓         ↓
返回         ┌── 成功 ──→ update_cached_boards → 返回新数据
旧数据       │
   │         │
   │         └── 失败 ──→ 异常冒到 routes.py → 500
   ↓                   (❌ cache 不被读)
   ❌ 17天前的
   旧数据
   直接返回
```

## 关键问题：成功路径 vs 失败路径不对称

- **上游成功** → 立刻 update_cached_boards，cache 更新
- **上游失败** → 异常抛出，cache **完全没被读**——即使里面有 17 天前的"过期但可用"数据

## 三个分支的失败模式

| 触发条件 | `_is_first_call_of_day` 返回 | needs_refresh | 行为 |
|---------|----------------------------|---------------|------|
| 同一日内的重复调用 | False | False | 直接读 cache（17天前的） |
| 新一天第一次调用 + 上游成功 | True | True | 写新 cache，返回新数据 |
| 新一天第一次调用 + 上游失败 | True | True | **不读 cache，直接 500** |

注意第三种情况——cache 表里有 486 条 concept 数据（5/19 的），但因为"新一天第一次"这个条件，整个 cache 分支被跳过了。
