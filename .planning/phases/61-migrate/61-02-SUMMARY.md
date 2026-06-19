---
phase: 61-migrate
plan: 02
subsystem: infra
tags: [durable, procrastinate, in-process, idempotency, index, graph, enqueue, migration]

# Dependency graph
requires:
  - phase: 61-migrate (Plan 01)
    provides: durable_index/durable_graph 任务名、DurableTaskService.defer、durable.queues 常量、register_business_handlers in-process adapter、has_active_by_key
provides:
  - 全部 5 处生产 index/graph 入队点改 DurableTaskService.defer（queue + deterministic idempotency_key）
  - 生产入队路径零 wrap_resumable/submit_resumable 残留（三套并存对 index/graph 收口）
  - recovery resume handler 改 durable 单一驱动入口（不与 stalled rescue 双跑）
  - 重复投递/重复执行/page_index 幂等守护测试
affects: [61-03 reconcile, 62 page_index ingest]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "同步入队点经 async_to_sync(DurableTaskService.defer) 桥接；async 点直接 await defer"
    - "deterministic idempotency_key 派生：index:{repo_id} / graph:{repo_id}（队列层在途去重）"
    - "业务防抖（select_for_update / already_indexing / _is_duplicate）+ 队列层 key 去重双层互补"
    - "recovery resume 经 defer 单一驱动入口 + deterministic key 命中在途去重，避免双跑"

key-files:
  created:
    - server/tests/durable/test_index_graph_migration.py
    - server/tests/durable/test_idempotency.py
  modified:
    - server/repositories/index_views.py
    - server/repositories/views.py
    - server/tasks/index_trigger_tasks.py
    - server/codegraph/views.py
    - server/resumable/handlers.py
    - server/tests/repositories/test_index_progress_reset.py
    - server/tests/repositories/test_codegraph_rebuild_view.py
    - server/tests/test_branch_lifecycle.py

key-decisions:
  - "#1 _schedule_index 保持同步 helper（async_to_sync 桥接 defer），调用方 IndexTriggerView 以 sync_to_async(_schedule_index) 包裹后 await，避免在事件循环线程上直接 async_to_sync 抛 RuntimeError（沿用 _acquire_index_lock_async 范式）"
  - "迁移后 durable 任务体 run_index/run_graph 从 services.indexer/graph_builder 直接 import 重活，patch seam 从入队点模块上移到 services 层——同步既有 3 个测试的 patch 目标"
  - "resume handler 续跑无既有 history → 传 history_id=None，由任务体 service 自建 RUNNING 行；删除 _run_index_resume/_run_graph_resume 内联 History/续跑逻辑（durable 任务体已覆盖）"

patterns-established:
  - "生产 index/graph 入队统一 DurableTaskService.defer(task, payload, queue=, idempotency_key=)"
  - "守护测试：rg 子进程 grep 残留 + 源码静态断言 defer 契约 + monkeypatch 捕获纯 helper defer 入参"

requirements-completed: [MIGRATE-01, IDEMP-01]

# Metrics
duration: ~24min
completed: 2026-06-20
---

# Phase 61 Plan 02: 迁移全部 5 处 index/graph 入队点至 DurableTaskService.defer Summary

**5 处生产 index/graph 入队点（含 CONTEXT 漏列的 index_views/codegraph）全部从 `run_in_background(wrap_resumable(...))` / `submit_resumable(...)` 改为 `DurableTaskService.defer`，统一 queue 常量 + deterministic idempotency_key（index:/graph:{repo_id}），recovery resume 收敛为 durable 单一驱动入口，生产入队路径零 resumable 提交残留**

## Performance

- **Duration:** ~24 min
- **Started:** 2026-06-19T19:50Z
- **Completed:** 2026-06-19T20:14Z
- **Tasks:** 3
- **Files modified:** 10 (2 created, 8 modified)

## Accomplishments
- **入队点 #1** `repositories.index_views._schedule_index`（同步）：经 `async_to_sync(DurableTaskService.defer)("durable_index", ..., queue=QUEUE_INDEX, idempotency_key=index:{repo_id})` 投递；调用方 `IndexTriggerView.post` 改 `await sync_to_async(_schedule_index)(...)` 桥接
- **入队点 #2** `repositories.views._schedule_default_branch_rolling_index`（async）：`await defer("durable_index", ..., index:{repo_id})`，保留 Repository/RepositoryBranchIndex/IndexHistory 写入（真相源不变）
- **入队点 #3** `tasks.index_trigger_tasks.trigger_auto_index`（async）：`await defer(...)`，保留 `already_indexing` / `_is_duplicate` 业务防抖
- **入队点 #4** `codegraph.CodegraphRebuildView`（async）：`await defer("durable_graph", ..., queue=QUEUE_GRAPH, idempotency_key=graph:{repo_id})`，保留锁内 GraphBuildHistory 创建与 202（history_id）响应契约
- **入队点 #5** `resumable.handlers.resume_index/resume_graph`（同步）：改 `async_to_sync(defer)` 单一驱动入口，删除 `submit_resumable` 内联 History/续跑逻辑；deterministic key 命中在途 durable job 去重避免双跑（T-61-04）
- 5 个文件清理无用 `wrap_resumable`/`ResumableTaskKind`/`submit_resumable`/`run_in_background`/`build_graph_for_repository` import；生产入队路径 grep 零残留
- 守护测试：迁移 grep/key 守护 + 重复投递（in-process 单条 + postgres queueing_lock）/ 重复执行（FileIndex/GraphFileIndex uq + history_id 复用）/ page_index 幂等

## Task Commits

每个任务原子提交：

1. **Task 1: 迁移 3 处 index 入队点 #1/#2/#3 → defer** - `fa797b295` (feat)
2. **Task 2: graph 入队点 #4 + recovery resume #5 → defer** - `d1a3e8a36` (feat)
3. **Task 3: 入队迁移 grep/key 守护 + 重复投递/执行/page_index 幂等守护测试** - `81be5c4cf` (test)

## Files Created/Modified
- `server/repositories/index_views.py`（改）- 入队点#1 `_schedule_index` → async_to_sync(defer)；调用方 sync_to_async 桥接；module-level `from durable import QUEUE_INDEX, DurableTaskService`
- `server/repositories/views.py`（改）- 入队点#2 → await defer（局部 import durable）
- `server/tasks/index_trigger_tasks.py`（改）- 入队点#3 → await defer（局部 import durable）
- `server/codegraph/views.py`（改）- 入队点#4 graph → await defer；module import 去 run_in_background
- `server/resumable/handlers.py`（改）- 入队点#5 resume_index/resume_graph → async_to_sync(defer) 单一驱动入口
- `server/tests/durable/test_index_graph_migration.py`（新）- 5 点迁移 grep + defer 契约静态断言 + 纯 helper defer 入参守护
- `server/tests/durable/test_idempotency.py`（新）- 重复投递/重复执行/page_index 幂等守护
- `server/tests/repositories/test_index_progress_reset.py`（改）- patch seam 上移到 services.indexer
- `server/tests/repositories/test_codegraph_rebuild_view.py`（改）- rebuild 派发断言改 DurableTaskService.defer（durable_graph/queue/key）
- `server/tests/test_branch_lifecycle.py`（改）- patch seam 上移到 services.indexer

## Decisions Made
- #1 同步点不改 async：保留 `_schedule_index` 同步 helper（`async_to_sync(defer)` 内桥接），由调用方 `await sync_to_async(_schedule_index)(...)`——直接在 async view 事件循环线程上 `async_to_sync` 会抛 `RuntimeError`，故沿用既有 `_acquire_index_lock_async` 的"同步 helper + sync_to_async"范式
- durable 模块导入位置因文件而异：index_views 因既有 import 块前置一个类（已有 E402），把 durable import 放到类之前的 module 顶部避免新增 E402；views/index_trigger/codegraph/handlers 沿用各自既有"函数内局部 import"风格
- resume handler 保留注册但改 defer：入队点 1-4 改 durable 后生产不再产新 index/graph ResumableTask 行，recovery 续驱自然枯竭；单一入口 + deterministic key 去重即可不双跑

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] #1 同步 helper 在 async 事件循环线程上 async_to_sync 会抛 RuntimeError**
- **Found during:** Task 1（入队点 #1）
- **Issue:** Plan 要求 `_schedule_index` 同步点用 `async_to_sync(defer)`，但其唯一调用方 `IndexTriggerView.post` 是 async view，直接同步调用 `_schedule_index` 会在事件循环线程执行 `async_to_sync` → `RuntimeError: You cannot use AsyncToSync in the same thread as an async event loop`
- **Fix:** 调用方改 `await sync_to_async(_schedule_index)(...)`（在工作线程执行，线程内无运行中 loop），保持 helper 同步 + async_to_sync 契约不变
- **Files modified:** server/repositories/index_views.py
- **Verification:** `tests/repositories/test_index_progress_reset.py::test_trigger_index_resets_progress_counters` 绿
- **Committed in:** `fa797b295`（Task 1 提交）

**2. [Rule 1 - Bug] 迁移后既有测试 patch seam 失效（4 个用例）**
- **Found during:** Task 1 / Task 2（验证既有索引/图谱触发测试）
- **Issue:** 入队改 durable 后，重活由 durable 任务体 `run_index`/`run_graph` 从 `services.indexer`/`services.graph_builder` 直接 import，旧测试在入队点模块层（`repositories.index_views.clone_and_index_repository` / `tasks.index_trigger_tasks.clone_and_index_repository` / `codegraph.views.run_in_background`）的 patch 不再拦截后台续跑路径，导致真实 clone 触发或 patch 目标缺失（AttributeError）
- **Fix:** 把 patch seam 上移到实际执行层：`test_index_progress_reset` / `test_branch_lifecycle` 改 patch `services.indexer.clone_and_index_repository`；`test_codegraph_rebuild_view` rebuild 派发断言改 `durable.service.DurableTaskService.defer`（断言 durable_graph + queue=graph + idempotency_key=graph:{repo_id}）
- **Files modified:** server/tests/repositories/test_index_progress_reset.py, server/tests/test_branch_lifecycle.py, server/tests/repositories/test_codegraph_rebuild_view.py
- **Verification:** 三文件相关用例全绿（test_codegraph_rebuild_view 22 passed）
- **Committed in:** `fa797b295`（Task 1）/ `d1a3e8a36`（Task 2）

---

**Total deviations:** 2 auto-fixed（2 bug，均为迁移 seam 变更的直接后果）
**Impact on plan:** 均为达成"既有测试零回归"验收所必需的 seam 同步，无范围蔓延。Plan 任务体（5 入队点 + 2 测试模块）逐字落地。

## Issues Encountered
- 无（与本 plan 相关）。SQLite 默认路径 `cd server && uv run pytest tests/durable -q` 全绿（49 passed, 11 deselected — postgres_queue 用例按 addopts 默认排除）；`manage.py check` 0 issues。

## Deferred Issues（pre-existing，与本 plan 无关）
两处 **pre-existing** 失败，均**不触达**本 plan 改动的入队路径、且不引用任何被改符号（grep 确认），系工作树既有未提交 `server/services/*` 改动 / Py3.14·Django6 环境所致，超出本 plan 范围（未修改）：
- `tests/repositories/test_index_retry_resume.py::test_failed_partial_index_with_checkpoint_resumes_full_index_not_incremental` —— 直接调 `services.indexer.clone_and_index_repository`，断言 status 'success' 实得 'error'（services.indexer 行为）
- `tests/repositories/test_index_history_changed_files.py::test_changed_files_populated_after_incremental_index` —— 无 `django_db` mark 直接调 `IndexerService.run_incremental_index`，报 "Database access not allowed"（测试/环境问题）

## Threat Flags
无新增信任边界外的攻击面（入队点沿用既有 IsAuthenticated/AllowAny+webhook 鉴权，未改权限；defer payload 仅含内部 repository_id/history_id，无凭证）。

## Known Stubs
- 沿用 Plan 01：`run_page_index` 仍为 page_index 占位（实际 ingest 留 Phase 62）。本 plan 仅补 page_index 幂等基线守护，未改其占位语义。

## Next Phase Readiness
- 生产 index/graph 仅走 durable，三套并存对 index/graph 收口；Plan 61-03 reconcile 可基于 `has_active_by_key`（Plan 01）+ deterministic key 正确判定在途、不误杀
- postgres_queue 专项（duplicate_dispatch procrastinate queueing_lock）需真实 Postgres CI 跑（本地 SQLite 默认 deselect）
- 未改 STATE.md / ROADMAP.md（按本次执行指令）

## Self-Check: PASSED
- 创建文件存在：61-02-SUMMARY.md、tests/durable/test_index_graph_migration.py、tests/durable/test_idempotency.py
- 任务提交存在：fa797b295（Task 1, feat）、d1a3e8a36（Task 2, feat）、81be5c4cf（Task 3, test）

---
*Phase: 61-migrate*
*Completed: 2026-06-20*
