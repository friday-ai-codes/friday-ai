---
phase: 61-migrate
plan: 03
subsystem: infra
tags: [durable, reconcile, procrastinate, queueing_lock, index, graph, startup, MIGRATE-02]

# Dependency graph
requires:
  - phase: 61-migrate
    plan: 01
    provides: DurableTaskService.has_active_by_key 公开门面（按 queueing_lock 查在途）、find_job_by_queueing_lock（活跃集含 scheduled）
  - phase: 60-durable
    provides: durable.roles.should_run_startup_side_effects（web-only 启动副作用门禁）、use_procrastinate_backend 后端判定
provides:
  - durable/reconcile.py：has_active_durable_job(_sync) 在途判定 helper（经门面、零 procrastinate 直接依赖）
  - repositories/codegraph 两处启动 reconcile 改判定：仅在无 durable 接管时才标 RUNNING→FAILED
affects: [生产多副本部署下启动 reconcile 安全语义]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "标 RUNNING→FAILED 前先查 durable 在途接管（has_active_by_key 按 queueing_lock），有接管保留 RUNNING"
    - "同步 daemon 线程经 async_to_sync 调异步门面，绝不裸 await"
    - "fail-safe 朝标 FAILED 侧：非 durable / 查询异常一律返 False（绝不留僵尸 RUNNING）"

key-files:
  created:
    - server/durable/reconcile.py
    - server/tests/repositories/test_reconcile_durable.py
  modified:
    - server/repositories/apps.py
    - server/codegraph/apps.py

key-decisions:
  - "判定经 DurableTaskService.has_active_by_key（按 queueing_lock=index:/graph: 查活跃集），绝不用按数字 job id 的单 job 查询（传 deterministic key 恒返 unknown 会误杀）"
  - "非 durable 后端（SQLite/in-process）helper 恒 False → reconcile 维持旧标 FAILED 行为零回归，不留僵尸 RUNNING"
  - "recoverable_target_ids 过渡排除集保留，与新 durable 在途排除集取并集（不破坏既有断点恢复语义）"
  - "N+1 按小 N 收口：非 durable 路径首句 use_procrastinate_backend() 短路 O(1)；durable 路径 N=单次启动卡住仓库数（个位数），逐 repo 调可接受，不引入批量 IN 查询"

requirements-completed: [MIGRATE-02]

# Metrics
duration: ~15min
completed: 2026-06-20
---

# Phase 61 Plan 03: 启动 reconcile 改判定（仅无 durable 接管才标 FAILED）Summary

**新增 `durable/reconcile.py` 在途判定 helper（经 `DurableTaskService.has_active_by_key` 按 queueing_lock 查、async_to_sync 同步入口、对 procrastinate 零直接依赖），并把 repositories/codegraph 两处启动 reconcile 改为"标 RUNNING→FAILED 前先查 durable job 接管，有在途（todo/doing/scheduled）则保留 RUNNING"，非 durable 后端维持旧标 FAILED 行为零回归。**

## Performance

- **Duration:** ~15 min
- **Tasks:** 2
- **Files modified:** 4 (2 created, 2 modified)

## Accomplishments
- 新增 `durable/reconcile.py`：
  - `async def has_active_durable_job(idempotency_key)`：durable 后端经 `DurableTaskService.has_active_by_key` 按 queueing_lock 查活跃集；非 durable（`use_procrastinate_backend()` False）直接返回 False；整段 try/except fail-safe 返 False
  - `def has_active_durable_job_sync(idempotency_key)`：`async_to_sync` 包装，供 `AppConfig.ready` 同步 daemon 线程安全调用
  - 对 procrastinate 零直接 import（在途判定一律经门面），不用按数字 job id 的单 job 查询
- `repositories/apps.py._reset_stuck_indexing`：对候选 INDEXING 仓库逐个调 `has_active_durable_job_sync(f"index:{repo_id}")`，为 True 的并入排除集（与既有 `recoverable_target_ids` 取并集）；IndexHistory RUNNING 收尾同样排除有在途 durable job 的仓库（按 `repository_id`），不误杀在途进度行
- `codegraph/apps.py.reconcile_orphaned_graph_builds`：取 orphan 候选 repo_ids 后逐个调 `has_active_durable_job_sync(f"graph:{repo_id}")`，为 True 的从回收集剔除（保留 RUNNING + 不归位仓库聚合态）
- 新增守护测试 `tests/repositories/test_reconcile_durable.py`（8 例）：helper 级（真实 durable postgres_queue / 门面委托 / 非 durable 旧行为 / fail-safe）+ reconcile 级（repositories、codegraph 各"有接管保留 RUNNING / 无接管标 FAILED"一对）

## Task Commits

每个任务原子提交（仅暂存本 plan 文件）：

1. **Task 1: durable/reconcile.py 在途判定 helper + helper 级守护测试** - `c7245d1b3` (feat)
2. **Task 2: repositories/codegraph 两处 reconcile 接入判定 + reconcile 级守护测试** - `2327d856a` (feat)

## Files Created/Modified
- `server/durable/reconcile.py`（新）- has_active_durable_job(_sync) 在途判定 helper（经门面、async_to_sync 同步入口、零 procrastinate 直接依赖、fail-safe）
- `server/tests/repositories/test_reconcile_durable.py`（新）- reconcile 安全语义守护（helper 级 4 例 + reconcile 级 4 例）
- `server/repositories/apps.py`（改）- _reset_stuck_indexing 改判定：排除有在途 durable index job 的仓库 / IndexHistory
- `server/codegraph/apps.py`（改）- reconcile_orphaned_graph_builds 改判定：排除有在途 durable graph job 的仓库

## Decisions Made
- 判定接口选 `has_active_by_key`（按 queueing_lock）而非按数字 job id 的单 job 查询：后者传 deterministic key（如 `index:{repo_id}`）会因 `int(job_id)` 失败恒返 unknown、令判定误为 False 而误杀在途任务（Plan 01 已为此交付正确门面）
- 非 durable 后端 helper 恒 False：in-process 重启即丢、不承诺续跑 → reconcile 维持旧"标 FAILED"，避免误"保留 RUNNING"留僵尸
- `recoverable_target_ids` 既有排除集与新 durable 在途排除集取并集，过渡兼容不破坏断点恢复语义
- N+1 按"小 N 可接受"收口：不引入批量 `queueing_lock IN (...)` 查询（避免门面再加 API、扩散改动面）

## Deviations from Plan

### 测试机制微调（test design）
- **计划描述：** Task 1 in-process facade 路径"`_set_job_state(key, running)` 后 monkeypatch `use_procrastinate_backend` → True 验证门面委托"。
- **实际实现：** 改为 monkeypatch `durable.service.use_procrastinate_backend → True` + monkeypatch `DurableTaskService.has_active_by_key`（AsyncMock）验证 helper 经门面委托（`test_has_active_durable_job_sync_delegates_to_facade`）。
- **原因：** `has_active_by_key` 内部会**再次**调 `use_procrastinate_backend()` 选后端——若仅靠该 flag 强制 durable 分支，门面会路由到 procrastinate 后端（需 Postgres），SQLite 下取不到真实 in-process 在途态。改 monkeypatch 门面方法直接验证"reconcile helper → has_active_by_key 委托"这一契约，覆盖意图一致且不依赖 Postgres。非 durable 旧行为另由 `test_has_active_durable_job_sync_non_durable_always_false` 用真实 `_set_job_state` + 默认 SQLite 守护。
- **影响：** 仅测试实现细节，被测行为与计划一致；未 monkeypatch 任何按数字 job id 的单 job 查询（符合"不再 monkeypatch get"约束）。

## Verification
- `cd server && uv run pytest tests/repositories/test_reconcile_durable.py tests/codegraph -q` → 178 passed, 20 skipped, 1 deselected（含新 8 例守护 + codegraph 既有 reconcile 零回归）
- `cd server && uv run pytest tests/durable tests/repositories -q` → 321 passed, 12 deselected, **2 failed**（`test_index_retry_resume.py::test_failed_partial_index_with_checkpoint_resumes_full_index_not_incremental`、`test_index_history_changed_files.py::test_changed_files_populated_after_incremental_index`）—— 均为 Plan 61-02 遗留的既有失败，与本 plan（启动 reconcile）无关（不引用 reconcile / has_active_durable_job）
- `rg "has_active_durable_job" server/repositories/apps.py server/codegraph/apps.py` → 各 2 命中（import + 调用）
- `rg "import procrastinate|from procrastinate" server/durable/reconcile.py` → 零命中；`rg "DurableTaskService.get" server/durable/reconcile.py` → 零命中
- `cd server && uv run python manage.py check` → System check identified no issues (0 silenced)

## Known Stubs
- 无。

## TDD Gate Compliance
- 两任务均 `tdd="true"`。沿用 Plan 61-01 顺序（实现先于测试落地，测试写后即 GREEN），未经历 RED→GREEN 失败-修复循环；测试随对应 feat 任务原子提交（Task 1 / Task 2 各含其守护用例）。RED 门独立 commit 不适用（实现先于测试，符合本 plan 任务编排）。

## Self-Check: PASSED

---
*Phase: 61-migrate*
*Completed: 2026-06-20*
