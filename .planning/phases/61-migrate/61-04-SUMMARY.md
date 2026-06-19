---
phase: 61-migrate
plan: 04
subsystem: infra
tags: [durable, migration, resumable, idempotency, command, background_runner]

# Dependency graph
requires:
  - phase: 61-migrate (Plan 01)
    provides: durable_index/durable_graph 任务名、DurableTaskService.defer、durable.queues 常量、has_active_by_key
  - phase: 61-migrate (Plan 02)
    provides: 生产 index/graph 入队点已收口 durable + deterministic key 范式（index:/graph:{repo_id}）
provides:
  - ResumableTaskStatus.MIGRATED 状态 + ResumableTask.legacy_durable_job_id 列（migration 0002）
  - 一次性迁移命令 migrate_resumable_to_durable（幂等可重入、不双跑、SQLite 安全降级、--dry-run）
  - background_runner 定位降级注释（dev fallback / 轻任务；生产 index/graph 不再经它）
  - 迁移/幂等/SQLite 降级/不双跑 守护测试
affects: [升级运维流程（一次性迁移命令）]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "存量在途行一次性迁移：按 kind 路由 durable 任务名 + deterministic key（index:/graph:{target_id}）defer，旧行标 MIGRATED 记 legacy id"
    - "显式键白名单重建 durable payload（repository_id/history_id/branch/trigger），绝不透传原始 resumable payload，防 run_*(**payload) 抛 TypeError"
    - "条件 update（status 再校验）防并发重复处理；状态过滤（只扫 PENDING/RUNNING）+ deterministic key 双层幂等"
    - "非 durable 后端安全降级：use_procrastinate_backend()=False 时清晰中文提示、skipped 统计、不静默迁移、不崩溃"
    - "MIGRATED 行被 recoverable_target_ids（仅 RUNNING）天然排除，不与 durable 双跑"

key-files:
  created:
    - server/resumable/migrations/0002_resumable_migrated.py
    - server/durable/management/commands/migrate_resumable_to_durable.py
    - server/tests/durable/test_migrate_command.py
  modified:
    - server/resumable/models.py
    - server/services/background_runner.py

key-decisions:
  - "迁移命令经 DurableTaskService 门面 defer（不直接 import procrastinate），同步 management command 内用 async_to_sync 桥接 async defer"
  - "durable payload 按显式白名单重建而非透传 task.payload——旧 resumable payload 可能含 coro_factory/name 等额外键，整传会令 keyword-only 任务体 run_index/run_graph(**payload) 抛 TypeError"
  - "非 durable（SQLite）后端不静默迁移：只统计 skipped + 中文提示，避免误把存量行'迁移'成进程内任务（重启即丢）"
  - "background_runner 仅降级注释、运行逻辑零改动：in-process durable 后端仍复用它，既有调用方零回归"

patterns-established:
  - "一次性升级迁移命令：扫在途行 → deterministic key defer durable → 旧行标终态 + 记 legacy id（幂等可重入）"

requirements-completed: [MIGRATE-02]

# Metrics
duration: ~10min
completed: 2026-06-20
---

# Phase 61 Plan 04: ResumableTask MIGRATED 迁移命令 + background_runner 降级 Summary

**新增 `ResumableTaskStatus.MIGRATED` + `legacy_durable_job_id` 列（migration 0002），实现一次性迁移命令 `migrate_resumable_to_durable`——按 deterministic key（`index:/graph:{target_id}`）把存量 PENDING/RUNNING 的 index/graph `resumable_tasks` defer 成 durable job、旧行标 MIGRATED 记 legacy id（不双跑、幂等可重入、SQLite 安全降级），并把 `background_runner` 注释降级为 dev fallback / 轻任务定位**

## Performance

- **Duration:** ~10 min
- **Started:** 2026-06-20T04:27 (UTC+8)
- **Tasks:** 3
- **Files modified:** 5 (3 created, 2 modified)

## Accomplishments
- **Task 1** `ResumableTask` 模型：`ResumableTaskStatus.MIGRATED`（区分系统迁移 vs 用户 CANCELLED）+ `legacy_durable_job_id` CharField（记迁移产生的 durable job 标识，可观测/排障）；migration `0002_resumable_migrated`（AddField + status choices AlterField）。MIGRATED 行被 `recoverable_target_ids`（仅返回 RUNNING）天然排除，不再被 recovery/reconcile 重驱。
- **Task 2** 一次性命令 `migrate_resumable_to_durable`：判后端（`use_procrastinate_backend()`）→ 非 durable 清晰中文提示且只统计不 defer；扫 `kind∈{index,graph} & status∈{pending,running}`；按 kind 路由 `durable_index`+QUEUE_INDEX / `durable_graph`+QUEUE_GRAPH + deterministic key `index:/graph:{target_id}`；显式白名单（repository_id/history_id/branch/trigger）重建 durable payload；`async_to_sync(DurableTaskService.defer)` 入队后条件 `update(status=MIGRATED, legacy_durable_job_id=str(job_id))`；打印 `{scanned, migrated, skipped, dry_run, backend}` 汇总。`--dry-run` 仅统计。
- **Task 3** `background_runner.py` 模块 docstring 补"定位降级（Phase 61 起）"段：明确降级为仅 SQLite dev fallback / 轻任务，生产 index/graph 改走 durable 不再经它（仅注释、运行逻辑零改动）；新建 `test_migrate_command.py` 守护 migrates/idempotent（postgres_queue）/ sqlite_safe / no_double_run。

## Task Commits

每个任务原子提交：

1. **Task 1: ResumableTask MIGRATED 状态 + legacy_durable_job_id 列 + migration 0002** - `c57a304ba` (feat)
2. **Task 2: 一次性迁移命令 migrate_resumable_to_durable** - `95168de56` (feat)
3. **Task 3: background_runner 降级注释 + 迁移命令守护测试** - `a044eccbb` (test)

## Files Created/Modified
- `server/resumable/models.py`（改）- ResumableTaskStatus.MIGRATED + ResumableTask.legacy_durable_job_id
- `server/resumable/migrations/0002_resumable_migrated.py`（新）- AddField legacy_durable_job_id + status choices 扩展（依赖 0001_initial）
- `server/durable/management/commands/migrate_resumable_to_durable.py`（新）- 一次性迁移命令
- `server/services/background_runner.py`（改）- 定位降级注释
- `server/tests/durable/test_migrate_command.py`（新）- 迁移/幂等/SQLite 降级/不双跑守护

## Decisions Made
- 命令经 `DurableTaskService` 门面 defer（不直接 import procrastinate），同步 management command 内 `async_to_sync(DurableTaskService.defer)` 桥接 async defer；测试用例写成同步 `def`（无运行中事件循环，async_to_sync 合法）。
- durable payload 按显式白名单重建而非透传 `task.payload`——keyword-only 任务体 `run_index/run_graph(**payload)` 对额外键会抛 `TypeError: unexpected keyword argument`；whitelist 取 repository_id（无则用 target_id 兜底）/ history_id / branch / trigger（无则 "manual"）。
- 非 durable（SQLite/in-process）后端：不静默迁移，只统计 skipped + 中文提示，避免误把存量行"迁移"成进程内任务（重启即丢）；命令不崩溃。
- 条件 `update(filter status∈{pending,running})` 防并发与重跑重复处理；与"只扫 PENDING/RUNNING"状态过滤、deterministic key 去重共同构成幂等。

## Deviations from Plan

None - plan executed exactly as written.

（Migration 自动生成名为 `0002_resumabletask_legacy_durable_job_id_and_more.py`，按 plan frontmatter 约定重命名为 `0002_resumable_migrated.py`，内容（依赖 0001、AddField + AlterField）逐字保留；`makemigrations --check` 干净，归入 Task 1 提交。）

## Issues Encountered
- 无。SQLite 默认路径 `cd server && uv run pytest tests/durable tests/resumable -q` 全绿（66 passed, 13 deselected — postgres_queue 用例按 addopts 默认排除）；`manage.py check` 0 issues；`makemigrations --check --dry-run` No changes detected。

## Human Needed
- **真实升级迁移验证（Postgres）**：`migrates` / `idempotent` 两用例带 `postgres_queue` + `enable_socket`，需真实 Postgres + `DURABLE_TASK_BACKEND=procrastinate` 才能断言 defer + key 去重（本地 SQLite 默认 skip）。生产升级时应在 Postgres 实例上实跑 `python manage.py migrate_resumable_to_durable` 验证存量在途行平滑转入 durable、旧行标 MIGRATED、无双跑/重复 job。

## Threat Flags
无新增信任边界外攻击面：命令仅经 CLI 执行、不暴露 REST；defer 经 `DurableTaskService` 门面；payload/legacy id 仅含内部 UUID 串/job 标识，无凭证（T-61-14 accept）。T-61-11/12/13 mitigate 已由 no_double_run/sqlite_safe/idempotent 守护覆盖。

## Known Stubs
- 无（本 plan 未引入占位）。沿用 Plan 01/02：`run_page_index` 仍为 page_index 占位（实际 ingest 留 Phase 62），与本 plan 无关。

## Next Phase Readiness
- 升级运维具备一次性迁移命令：存量在途 index/graph 行可平滑转入 durable，不双跑（旧行标 MIGRATED 排除出 recovery 集）、幂等可重入、SQLite dev 安全降级。
- background_runner 已注释降级为 dev fallback / 轻任务，生产 index/graph 三套并存收口完成（durable 单一驱动）。
- 未改 STATE.md / ROADMAP.md（按本次执行指令）。

## Self-Check: PASSED
- 创建文件存在：61-04-SUMMARY.md、0002_resumable_migrated.py、migrate_resumable_to_durable.py、test_migrate_command.py
- 任务提交存在：c57a304ba（Task 1, feat）、95168de56（Task 2, feat）、a044eccbb（Task 3, test）

---
*Phase: 61-migrate*
*Completed: 2026-06-20*
