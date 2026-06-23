---
phase: 69-batch
plan: 01
subsystem: repositories-batch
tags: [batch-create, reindex-all, csv-import, superuser, durable]
requires:
  - phase: "67-concurrency"
    provides: "索引槽位锁池（批量入队受并发上限排队消费）"
provides:
  - "ReindexAllView 超管全部更新索引（BATCH-01）"
  - "RepositoryBatchCreateView 批量建仓（BATCH-02）"
  - "_acreate_repository_core 单仓/批量共享建仓核心"
affects: [仓库列表页, 索引入队]
tech-stack:
  added: []
  patterns:
    - "批量入队复用单仓 _schedule_index（Phase 67 槽位锁），并发上限由槽位池保证，不另设限流"
    - "批量建仓单项失败隔离 + 复用 _acreate_repository_core（DRY，acreate 与 batch 共用）"
key-files:
  created:
    - server/tests/repositories/test_batch_and_reindex.py
  modified:
    - server/repositories/views.py
    - server/repositories/urls.py
    - web/src/api/repositories.ts
    - web/src/pages/repositories/index.vue
status: complete
---

# Phase 69 Plan 01 Summary — 批量加仓 + 全部更新索引（超管）

- **BATCH-01**：`ReindexAllView`（`POST /api/repositories/reindex-all/`，`IsSuperUser` fail-closed）遍历全部未删除仓库，跳过已 `INDEXING` 的，其余 reset 进度残留 + 建 RUNNING `IndexHistory` + 置 `INDEXING` + 经 `_schedule_index`（Phase 67 索引槽位锁，超 `CONCURRENCY_INDEX_MAX` 原生 todo 排队）入队；单仓入队失败隔离（标 FAILED 不中断）；返回 `{queued, skipped, total}`。
- **BATCH-02**：`RepositoryBatchCreateView`（`POST /api/repositories/batch/`）接受 `{repositories:[...]}`，逐项 `RepositoryCreateSerializer` 校验 + 复用从 `acreate` 抽取的模块级 `_acreate_repository_core`（单仓/批量共用，DRY；含 access_token/空间/base_branch 校验 + 建仓+空间关联+凭证+审计+AI 描述派发）；单项失败隔离，返回 `created/failed`（index/name/error）+ 计数；单次上限 500。
- **urls**：`batch/` + `reindex-all/` 注册在 router include 之前（避免被当作 `<uuid>` repo id）。
- **前端**：仓库列表页 actions 新增「CSV 批量建仓」（文件选择 → `parseReposCsv` 解析列 name,git_url,git_platform,access_token,space_id + 自动跳表头 → `batchCreate` → 结果 toast + 刷新）与超管专属「全部更新索引」（`isAdmin` 才渲染，确认对话框 + `已排队 N 个（跳过 M 个）` toast）；`api/repositories.ts` 增 `batchCreate`/`reindexAll` + 响应类型。

验收：`test_batch_and_reindex.py` 5 例（reindex 403/queued-skipped-total、batch 创建/单项隔离/空拒绝）；`test_repositories.py` 31 acreate 重构零回归；前端 eslint clean + 列表页既有测试零回归。
