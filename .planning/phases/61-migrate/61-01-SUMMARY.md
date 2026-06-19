---
phase: 61-migrate
plan: 01
subsystem: infra
tags: [durable, procrastinate, in-process, idempotency, index, graph, page_index]

# Dependency graph
requires:
  - phase: 60-durable
    provides: DurableTaskService 门面、durable.queues 队列常量、InProcessBackend/ProcrastinateBackend、@app.task 显式 name 范式
provides:
  - durable_index / durable_graph / durable_page_index 三个 durable 任务（两后端入参一致）
  - durable/tasks_impl.py 共用任务体（零 procrastinate 依赖）
  - register_business_handlers() in-process **payload 展开 adapter
  - DurableConfig.ready() 双后端无条件注册业务 handler 修复
  - DurableTaskService.has_active_by_key 公开门面（按 queueing_lock 查在途）
  - find_job_by_queueing_lock 公开化（活跃集补 scheduled）
affects: [61-02 入队点改 defer, 61-03 reconcile, 62 page_index ingest 接入]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "双后端入参对齐：任务体 keyword-only 形参 + 调用方一律 **payload 展开（procrastinate defer_async(**payload) / in-process adapter run_*(**payload)）"
    - "占位幂等 handler：零写库 / 零副作用 + 恒等返回（page_index）"
    - "按 queueing_lock 的在途判定门面，区别于按数字 job id 的 get"

key-files:
  created:
    - server/durable/tasks_impl.py
    - server/durable/handlers.py
    - server/tests/durable/test_business_tasks.py
  modified:
    - server/durable/tasks.py
    - server/durable/apps.py
    - server/durable/backends.py
    - server/durable/service.py

key-decisions:
  - "任务体集中在 tasks_impl.py（零 procrastinate 依赖），@app.task 包壳与 in-process adapter 共用同一任务体，避免双注册不一致"
  - "register_business_handlers() 放在 DurableConfig.ready() 的 role 门禁与 procrastinate 判定之外无条件调用，修复 SQLite/in-process 路径业务 handler 未注册"
  - "has_active_by_key 活跃集 procrastinate={todo,doing,scheduled}、in-process={pending,running}；fail-safe 吞异常返 False"

patterns-established:
  - "双后端 payload 契约：keyword-only 任务体 + **payload 展开"
  - "占位 handler 幂等：恒等返回 + 零副作用"

requirements-completed: [MIGRATE-01, IDEMP-01]

# Metrics
duration: 11min
completed: 2026-06-20
---

# Phase 61 Plan 01: 迁移 index/graph 任务底座 + 收口 ResumableTask 接口 Summary

**index/graph/page_index 三个 durable 任务在 procrastinate（defer_async(**payload)）与 in-process（**payload 展开 adapter）两后端入参一致，DurableConfig.ready() 双后端注册业务 handler，并新增按 queueing_lock 查在途的 has_active_by_key 公开门面**

## Performance

- **Duration:** ~11 min
- **Started:** 2026-06-19T19:33Z
- **Completed:** 2026-06-19T19:44Z
- **Tasks:** 4
- **Files modified:** 7 (3 created, 4 modified)

## Accomplishments
- 新增 `durable/tasks_impl.py`：`run_index` / `run_graph` / `run_page_index` 共用任务体，复用既有 `clone_and_index_repository` / `build_graph_for_repository`，IndexHistory/GraphBuildHistory 仍为真值源、FileIndex/GraphFileIndex checkpoint 零改动
- `durable/tasks.py` 新增三个显式 `name=` 的 `@app.task` 包壳（procrastinate 路径），委托共用任务体
- 新增 `durable/handlers.py`：`register_business_handlers()` 为三任务注册 `**payload` 展开 adapter，对齐 procrastinate kwargs 入参，消除研究 Pitfall 1
- 修复 `DurableConfig.ready()`：业务 handler 注册移到 role 门禁与 procrastinate 判定之外无条件执行，SQLite dev/pytest 不再因提前 return 而走 no-op
- `has_active_by_key` 公开门面（两后端）+ `find_job_by_queueing_lock` 公开化（活跃集补 scheduled），替代 `get`+deterministic-key 误判路径，为 Plan 03 reconcile 提供正确判定接口
- page_index 占位 handler 幂等（恒等返回、零副作用），实际 ingest 接入留 Phase 62

## Task Commits

每个任务原子提交：

1. **Task 1: 任务体模块 + @app.task 包壳** - `2cb55ea39` (feat)
2. **Task 2: in-process adapter 注册 + ready() 双后端注册修复** - `260ba9040` (feat)
3. **Task 3: has_active_by_key 公开门面** - `8be3a0024` (feat)
4. **Task 4: 双后端契约 + page_index 幂等 + has_active_by_key 守护测试** - `b3c14fb94` (test)

## Files Created/Modified
- `server/durable/tasks_impl.py`（新）- run_index/run_graph/run_page_index 共用任务体（零 procrastinate 依赖）
- `server/durable/handlers.py`（新）- register_business_handlers() in-process **payload 展开 adapter
- `server/tests/durable/test_business_tasks.py`（新）- 双后端入参契约 + page_index 占位幂等 + has_active_by_key 两后端守护
- `server/durable/tasks.py`（改）- +3 个显式 name 的 @app.task 包壳
- `server/durable/apps.py`（改）- ready() 无条件注册业务 handler（双后端修复）
- `server/durable/backends.py`（改）- find_job_by_queueing_lock 公开化（+scheduled）+ 两后端 has_active_by_key
- `server/durable/service.py`（改）- DurableTaskService.has_active_by_key 公开门面

## Decisions Made
- 任务体与 procrastinate 解耦：`tasks_impl.py` 不 import procrastinate，由 `@app.task` 包壳与 in-process adapter 双方 import，两后端共用单一任务体
- `register_business_handlers()` 纯注册无 IO，无条件调用以保证两后端路径都有业务 handler
- `has_active_by_key` 按 queueing_lock（=idempotency_key）判定在途，明确区别于按数字 job id 的 `get`，并对 procrastinate 路径 fail-safe 吞异常返 False

## Deviations from Plan

None - plan executed exactly as written.

（Task 1 验证期发现任务体 docstring 含字面量 "import procrastinate" 会触发计划验收命令的纯字符串 grep；已改写为"对 procrastinate 零直接依赖"，真正的 no-direct-import 守护用锚定正则、本就不受影响。非行为变更，归入 Task 1 提交。）

## Issues Encountered
- 无。SQLite 默认路径下 `cd server && uv run pytest tests/durable -q` 全绿（35 passed, 10 deselected — postgres_queue 用例按 addopts 默认排除）；`manage.py check` 0 issues。

## TDD Gate Compliance
- Task 4 为 `tdd="true"`，但实现（Task 1-3）按计划顺序先行落地，测试编写后即 GREEN（4 passed），未经历 RED→GREEN 失败-修复循环。RED 门 commit 不适用（实现先于测试，符合本 plan 任务顺序）；测试以 `test(...)` 提交（`b3c14fb94`）。

## Known Stubs
- `run_page_index`（`server/durable/tasks_impl.py`）：page_index 占位 handler，仅记 debug 并返回 `{"status": "noop", "target_id": ...}`，零副作用。**有意为之**——实际 ingest 接入按 CONTEXT 计划留 Phase 62；当前幂等占位不阻碍本 plan 目标（建立任务底座 + 注册契约）。

## Next Phase Readiness
- 三任务可被 `DurableTaskService.defer("durable_index"/"durable_graph"/"durable_page_index", {...}, queue=..., idempotency_key=...)` 调用，Plan 61-02 可据此把 5 处入队点改 `DurableTaskService.defer`
- `has_active_by_key` 公开门面就位，Plan 61-03 reconcile 可按 key 正确判定在途、不误杀
- postgres_queue 用例（Test 4 / Test 6）需真实 Postgres CI 跑（本地 SQLite 默认 skip）

## Self-Check: PASSED

---
*Phase: 61-migrate*
*Completed: 2026-06-20*
