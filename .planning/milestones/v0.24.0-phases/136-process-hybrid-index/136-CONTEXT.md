# Phase 136 Context：Process 一等混合索引

## Smart Discuss 自动决策

| 灰区 | ✅ Recommended 决策 |
|---|---|
| 事实源 | `ProcessTrace` 唯一事实源；Qdrant 仅可重建投影 |
| collection | 独立 per-repository Process collection，payload 强制 branch/generation/commit |
| generation | 由 repository/branch/built_at_sha/index schema version 确定性哈希，重跑幂等 |
| 双 lane | 每点写 dense + sparse；查询使用 hybrid 并显式返回 `lane=hybrid` |
| 旧 generation | 查询必须传当前 generation 精确过滤，旧点绝不混排；清理可异步 |
| steps | payload 保留完整有序 steps，标准化 `start_line/end_line` 为 1-based |
| 后台归因 | rebuild 参数显式携带 `initiated_by_user_id`，入口使用 `bind_task_context` |

## 边界

不把 Qdrant 变成事实源，不创建图数据库，不改现有 Symbol collection。
