---
phase: 62-crawl
plan: 01
subsystem: infra
tags: [durable, procrastinate, crawl, ingest, delivery, idempotency, rest]

# Dependency graph
requires:
  - phase: 60-durable
    provides: DurableTaskService 门面、durable.queues（QUEUE_CRAWL_INGEST）、In/Procrastinate 双后端
  - phase: 61-migrate
    provides: tasks_impl keyword-only 任务体范式、@app.task 显式 name 包壳、handlers **payload 展开 adapter、双后端无条件注册
provides:
  - run_crawl_ingest durable 任务体（薄封装天然幂等的 ingest_from_urls，DB 驱动）
  - durable_crawl_ingest 双后端注册（procrastinate 包壳 + in-process adapter，入参对齐）
  - IngestRun.Status.QUEUED/STOPPED + durable_job_id + idempotency_key(db_index) 列 + 迁移 0024
  - delivery 队列动作端点 IngestQueueView(get=list/post=enqueue)/IngestQueueDetailView/IngestQueueActionView + IngestQueueItemSerializer + 路由
affects: [62-02 page_index ingest 接入, 62-03 前端 BatchIngestPanel 改造]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "durable 任务体薄封装既有幂等内核：payload 仅 batch_id/concurrency（绝不落凭证），DB(IngestRun) 为唯一 specs 真相源，重复执行由内核 upsert 承载 at-least-once 幂等"
    - "队列状态 DB 真相源重建：list 端点从 IngestRun 按 batch_id 分组聚合，不依赖任何内存态（刷新/容器重建可恢复）"
    - "动作端点镜像 RepositoryReconcileView 派发范式：enqueue/start/retry → defer(同 idempotency_key)、stop → cancel + STOPPED 终态可重投"

key-files:
  created:
    - server/delivery/migrations/0024_ingestrun_durable_queue.py
    - server/tests/delivery/test_crawl_ingest_idempotent.py
    - server/tests/delivery/test_ingest_queue.py
  modified:
    - server/delivery/models/ingest_run.py
    - server/durable/tasks_impl.py
    - server/durable/tasks.py
    - server/durable/handlers.py
    - server/delivery/api/views.py
    - server/delivery/api/serializers.py
    - server/delivery/urls.py
    - server/tests/delivery/test_ingest_run_model.py

key-decisions:
  - "OQ-1 最小扩列：Status 增 QUEUED/STOPPED + durable_job_id/idempotency_key 两列，迁移仅加列/改 choices（兼容存量不回填、不回退）"
  - "run_crawl_ingest 处理 status ∈ {QUEUED,RUNNING,FAILED,STOPPED}、排除 COMPLETED：重复执行/断点恢复不重做已完成行（resume 安全）"
  - "enqueue 复用 JsonIngestRequestSerializer + aresolve_items（不另造入参）；单 view 承载 list+enqueue（同 path 两 view 不可，故合并）"
  - "list 按最近 N=50 批聚合（A4 内部工具无分页）；聚合 status 优先级 running>queued>stopped>failed>completed"

patterns-established:
  - "durable 队列动作端点：DB 真相源 list 重建 + defer/cancel 经 DurableTaskService 门面（零直接 procrastinate import）"
  - "deterministic idempotency_key=crawl_ingest:{batch_id}：enqueue/start/retry 同 key 重 defer（queueing_lock 幂等吞并）"

requirements-completed: [CRAWL-01]

# Metrics
duration: 13min
completed: 2026-06-21
---

# Phase 62 Plan 01: 爬取+入库 durable 队列 + IngestRun 扩列 + 动作端点 Summary

**run_crawl_ingest 双后端 durable 任务（薄封装天然幂等的 ingest_from_urls）+ IngestRun 扩 QUEUED/STOPPED 状态与 durable_job_id/idempotency_key 列 + delivery 队列动作端点（enqueue/list/detail/start/stop/retry），状态以 IngestRun(DB) 为唯一真相源、刷新/重建可恢复**

## Performance

- **Duration:** ~13 min
- **Started:** 2026-06-20T16:22Z
- **Completed:** 2026-06-20T16:38Z
- **Tasks:** 2（+1 Rule 1 守护修复）
- **Files modified:** 11（3 created, 8 modified）

## Accomplishments
- `run_crawl_ingest`（`durable/tasks_impl.py`）：keyword-only、按 batch_id 从 IngestRun 重建 specs、`asyncio.Semaphore(clamp_concurrency)` 有界并发、排除 COMPLETED、单行 try/except 隔离 + structlog warning；薄封装既有天然幂等的 `ingest_from_urls`（三元组 upsert / 文档 content_hash / MR diff aarchive_exists），payload 仅 batch_id/concurrency（绝不落凭证）
- `durable_crawl_ingest` 双后端注册：`tasks.py` 显式 `@app.task(name="durable_crawl_ingest", queue=QUEUE_CRAWL_INGEST)` procrastinate 包壳 + `handlers.py` in-process `**payload` 展开 adapter（入参对齐不抛 TypeError）
- `IngestRun` 扩列：Status 增 QUEUED/STOPPED，新增 `durable_job_id`(CharField64) + `idempotency_key`(CharField128, db_index) 列 + 迁移 0024（依赖 0023，加列/改 choices、兼容存量不回退）
- delivery 队列动作端点（全 IsAuthenticated）：`IngestQueueView`(GET=list/POST=enqueue)、`IngestQueueDetailView`、`IngestQueueActionView` + `IngestQueueItemSerializer` + 路由（字面段在 uuid 前）；enqueue 经 `DurableTaskService.defer(QUEUE_CRAWL_INGEST, idempotency_key="crawl_ingest:{batch_id}")` 回写 durable_job_id/idempotency_key；list 从 IngestRun(DB) 按 batch_id 分组重建（断点恢复命门）；stop=cancel+STOPPED、start/retry=同 key 重 defer
- 守护测试：`test_crawl_ingest_idempotent.py`（3）+ `test_ingest_queue.py`（13）全绿

## Task Commits

每个任务原子提交（Conventional Commits，中文 subject）：

1. **Task 1: IngestRun 扩列 + run_crawl_ingest 双后端任务体** - `c6bdc249e` (feat)
2. **Task 2: 爬取入库 durable 队列动作端点** - `c7716bdb8` (feat)
3. **Rule 1 守护修复: IngestRun status 枚举守护补 QUEUED/STOPPED** - `4a54ae9c4` (test)

_注：Task 1/2 标 tdd=true，但实现与测试同一提交内落地、测试编写后即 GREEN（未经历 RED→GREEN 失败循环，符合本 plan 任务顺序）。_

## Files Created/Modified
- `server/delivery/models/ingest_run.py`（改）- Status 增 QUEUED/STOPPED + durable_job_id/idempotency_key 列
- `server/delivery/migrations/0024_ingestrun_durable_queue.py`（新）- 加列 + 改 status choices
- `server/durable/tasks_impl.py`（改）- 新增 run_crawl_ingest 任务体
- `server/durable/tasks.py`（改）- 新增 durable_crawl_ingest procrastinate 包壳
- `server/durable/handlers.py`（改）- 新增 _crawl_ingest in-process adapter + 注册
- `server/delivery/api/views.py`（改）- 三个队列动作 view + _aggregate_queue_status helper
- `server/delivery/api/serializers.py`（改）- IngestQueueItemSerializer
- `server/delivery/urls.py`（改）- queue/ + queue/<uuid>/ + queue/<uuid>/<action>/ 路由
- `server/tests/delivery/test_crawl_ingest_idempotent.py`（新）- 重复执行幂等 + COMPLETED 跳过 + 双后端契约
- `server/tests/delivery/test_ingest_queue.py`（新）- enqueue/list/detail/action 端点守护（13 用例）
- `server/tests/delivery/test_ingest_run_model.py`（改）- status 枚举守护补 QUEUED/STOPPED

## Decisions Made
- 见 frontmatter key-decisions（OQ-1 最小扩列、排除 COMPLETED、单 view 承载 list+enqueue、list N=50 聚合优先级）。
- enqueue 创建 IngestRun 时不写 project（与既有 `JsonIngestBatchView` 保持一致、少查询），归属说明沿用 `IngestRunDetailView`（无 owner + 不可猜 UUIDv4）。

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] IngestRun status 枚举守护测试同步**
- **Found during:** Task 1 后全量套件验证（`test_ingest_run_model.py::test_ingest_run_status_choices`）
- **Issue:** 既有守护断言 `Status.choices == {running, completed, failed}`，Task 1 扩列新增 QUEUED/STOPPED 后该断言必然失败（由本 plan 模型改动直接引发）。
- **Fix:** 更新断言为五态集合（running/completed/failed/queued/stopped），补 QUEUED/STOPPED 值断言。
- **Files modified:** server/tests/delivery/test_ingest_run_model.py
- **Verification:** `uv run pytest tests/delivery/test_ingest_run_model.py -q` → 6 passed。
- **Committed in:** `4a54ae9c4`

---

**Total deviations:** 1 auto-fixed（1 bug，本 plan 改动直接引发的守护同步）。
**Impact on plan:** 守护与模型保持一致，无 scope creep。

## Issues Encountered
- **预存（out-of-scope）失败**：`tests/delivery/test_plan_session_inv6_guard.py::test_inv6_no_bypass_plan_session_write` 在本 plan 执行前即失败，根因为 INV-6 守护正则 `\bPlanSession\s*\(` 误命中**中文注释** `server/chat/conversation_service.py:1922`（已提交基线代码、工作树无 diff、与 62-01 无关）。按 SCOPE BOUNDARY 不在本 plan 修复，已记录至 `.planning/phases/62-crawl/deferred-items.md`。本 plan 全部 16 个新测试 + 既有 delivery/durable 套件其余 490 passed。

## User Setup Required
None - 零新依赖、零外部服务配置（procrastinate 由 Phase 60 锁定；SQLite 默认 in-process 后端开箱即用）。

## Verification
- `cd server && uv run pytest tests/durable tests/delivery -q` → 490 passed, 1 failed（仅预存 plan_session 守护误报，详见 Issues）, 13 deselected。
- `cd server && uv run python manage.py makemigrations --check --dry-run` → No changes detected（干净）。
- `tests/durable/test_no_direct_import.py` → passed（delivery 视图零直接 import procrastinate，经 DurableTaskService + durable.queues 常量）。
- ruff check 本 plan 所有改动文件 → All checks passed。

## Known Stubs
None - run_crawl_ingest 为真实接入（非占位），薄封装既有摄取编排；端点全部接入 DB + DurableTaskService 真实路径。

## Next Phase Readiness
- 62-02（PageIndex）可复用本 plan 的 tasks_impl 双后端注册范式；62-03（前端 BatchIngestPanel）可消费 `ingest/queue/`（list/enqueue）+ `ingest/queue/<batch_id>/`（detail）+ `ingest/queue/<batch_id>/<action>/`（start/stop/retry）端点，刷新后从 DB 恢复队列（不再依赖组件内存 batchId）。
- Postgres 专项（queueing_lock 真实去重）需真实 Postgres CI 跑（`-m postgres_queue`，本地 SQLite 默认 skip）。

## Self-Check: PASSED

- 所有创建文件存在（迁移 0024、tasks_impl、views、两测试文件、SUMMARY）。
- 三个任务提交均存在（c6bdc249e / c7716bdb8 / 4a54ae9c4）。

---
*Phase: 62-crawl*
*Completed: 2026-06-21*
