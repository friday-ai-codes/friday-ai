# Phase 69: 批量加仓 + 全部更新索引（超管） - Context

**Gathered:** 2026-06-23
**Status:** Ready for planning
**Mode:** Smart discuss (autonomous)

<domain>
## Phase Boundary

支持经 CSV 批量导入数百仓库，并给超管一键「全部更新索引」，批量入队受 Phase 67 索引槽位锁池排队消费、不打爆资源。
</domain>

<decisions>
## Implementation Decisions

### BATCH-01 全部更新索引（超管）
- `ReindexAllView`（`POST /api/repositories/reindex-all/`，`IsSuperUser` fail-closed）：遍历全部未删除仓库，跳过已 INDEXING 的，其余 reset 进度 + 建 RUNNING IndexHistory + 置 INDEXING + 经 `_schedule_index`（Phase 67 索引槽位锁）入队；返回 `{queued, skipped, total}`。
- 受 `CONCURRENCY_INDEX_MAX` 槽位锁排队消费（Phase 67 自动生效，无需本 phase 额外限流）。
- 前端仓库列表页超管可见「全部更新索引」按钮（`isAdmin` 才渲染，后端 IsSuperUser 兜底）+ 确认对话框 + 「已排队 N 个（跳过 M 个）」toast。

### BATCH-02 批量建仓 / CSV 导入
- `RepositoryBatchCreateView`（`POST /api/repositories/batch/`）：接受 `{repositories:[...]}` 数组，逐项复用单仓建仓核心 `_acreate_repository_core`（从 acreate 抽取，单仓/批量共用，DRY）；单项失败隔离，返回 `created/failed`（含 index/name/error）+ 计数；单次上限 500。
- 前端「CSV 批量建仓」按钮 → 文件选择 → 解析 CSV（列 name,git_url,git_platform,access_token,space_id，自动跳表头）→ batchCreate → 结果 toast + 刷新列表。

### Claude's Discretion
- CSV 列顺序与表头识别（含 git_url 视为表头）。
- 批量上限 500。
</decisions>

<code_context>
## Existing Code Insights
- `repositories/views.py` `RepositoryViewSet.acreate`（重构抽取 `_acreate_repository_core` 模块 helper）、`IsSuperUser`（permissions.api_permissions）、`IndexTriggerView` reset+history+`_schedule_index` 范式。
- `repositories/index_views.py` `_schedule_index`（Phase 67 已带索引槽位锁）。
- 前端 `web/src/pages/repositories/index.vue`（列表页 actions）、`api/repositories.ts`、`useToast`/`useConfirmDialog`/`useAuthStore().isAdmin`。
</code_context>

<specifics>
## Specific Ideas
- 批量入队的并发上限由 Phase 67 槽位锁池保证，本 phase 不另设限流。
</specifics>

<deferred>
## Deferred Ideas
- 富 CSV 校验/预览 UI、列映射向导（本 phase 提供可用最简 CSV 导入）。
</deferred>
