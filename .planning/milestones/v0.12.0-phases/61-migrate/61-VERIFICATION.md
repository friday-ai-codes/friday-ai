---
phase: 61-migrate
verified: 2026-06-19T20:40:00Z
status: human_needed
score: 5/5 must-have truths verified (SQLite path); 3/3 requirements satisfied
overrides_applied: 0
human_verification:

  - test: "在真实 Postgres + DURABLE_TASK_BACKEND=procrastinate 实例上跑一次性迁移命令 `python manage.py migrate_resumable_to_durable`（先 seed 若干 PENDING/RUNNING 的 index/graph resumable_tasks）"
    expected: "存量在途行平滑转入 durable（按 deterministic key defer）、旧行 status=MIGRATED 且 legacy_durable_job_id 非空；重跑命令 migrated=0、无重复 durable job（queueing_lock 唯一）"
    why_human: "postgres_queue 用例需真实 Postgres + procrastinate 队列，本地 SQLite 默认 deselect（13 deselected）；procrastinate queueing_lock 去重语义只能在真实队列断言"

  - test: "在真实 Postgres 上验证 5 处 index/graph 入队点的 procrastinate 路径去重（同 repo 重复触发索引/图谱重建）"
    expected: "同一 idempotency_key（index:{repo_id}/graph:{repo_id}）的重复投递在 todo 唯一，不产生重复 durable job；IndexHistory/GraphBuildHistory 仍按入队点创建"
    why_human: "procrastinate queueing_lock todo 唯一是 Postgres 侧 DB 约束，SQLite in-process 后端为同名覆盖近似，需真实队列确认"

  - test: "多副本部署下启动 reconcile 不误杀在途 durable 任务：A 进程跑 durable_index/durable_graph 在途时，B 进程启动 reconcile"
    expected: "has_active_by_key 命中在途（todo/doing/scheduled）→ 对应 Repository 保留 INDEXING、IndexHistory/GraphBuildHistory 保留 RUNNING，不被标 FAILED"
    why_human: "需真实 Postgres procrastinate 后端 + 多进程并发，has_active_by_key 的 procrastinate queueing_lock 查询路径无法在 SQLite 下端到端验证"
notes_preexisting_failures:

  - test: "tests/repositories/test_index_retry_resume.py::test_failed_partial_index_with_checkpoint_resumes_full_index_not_incremental"
    classification: pre-existing (NOT a Phase 61 regression)
    evidence: "测试零引用 durable/defer/reconcile/wrap_resumable；直接调 services.indexer.clone_and_index_repository（Phase 61 未改 services/indexer.py，其最后提交 9be453f06 远早于 Phase 61 提交）。失败为 indexer 返回 status='error'（services 层行为 / Py3.14·Django6 环境），不触达本相迁移的入队/reconcile/迁移命令路径"

  - test: "tests/repositories/test_index_history_changed_files.py::test_changed_files_populated_after_incremental_index"
    classification: pre-existing (NOT a Phase 61 regression)
    evidence: "失败为 'Database access not allowed, use the django_db mark'——该用例未挂 @pytest.mark.django_db（文件内注释 line 76 明确说明），纯测试基建问题；Phase 61 未修改此测试文件，亦零引用 Phase 61 符号"
audit_acknowledged:
  milestone: v0.25.0
  at: 2026-08-31
  status: human_needed
---

# Phase 61: 迁移 index/graph + 收口 ResumableTask Verification Report

**Phase Goal:** 把 index/graph 后台任务从 ResumableTask/background_runner 迁移到 `DurableTaskService.defer`（queue=index/graph, idempotency_key=index:{repo_id}/graph:{repo_id}）；一次性迁移在途 resumable_tasks（不双跑，旧行标 MIGRATED + legacy id）；启动 reconcile 仅在无 durable job 接管时才标 RUNNING→FAILED；handler 幂等基线（IDEMP-01）。IndexHistory/GraphBuildHistory 保持真相源；FileIndex/GraphFileIndex checkpoint 保留。
**Verified:** 2026-06-19T20:40:00Z
**Status:** human_needed
**Re-verification:** No — initial verification

## Goal Achievement

### Observable Truths

| #   | Truth | Status | Evidence |
| --- | ----- | ------ | -------- |
| 1 | 全部 5 处生产 index/graph 入队点改 `DurableTaskService.defer`（queue + deterministic key），不再 `wrap_resumable`/`submit_resumable`（SC1） | ✓ VERIFIED | `index_views.py:161`(async_to_sync defer, QUEUE_INDEX, key=index:{repo_id})、`views.py:392`(await defer)、`index_trigger_tasks.py:177`(await defer)、`codegraph/views.py:710`(await defer, QUEUE_GRAPH, key=graph:{repo_id})、`resumable/handlers.py:41/68`(resume_index/resume_graph→async_to_sync defer)。grep：5 个生产文件零 `wrap_resumable`/`submit_resumable`（仅 `resumable/service.py` 保留 fallback 定义、`recovery.py` 注释引用） |
| 2 | IndexHistory/GraphBuildHistory 仍在入队点创建作真相源；FileIndex/GraphFileIndex checkpoint 保留（SC1） | ✓ VERIFIED | 入队点均保留 `IndexHistory.objects.acreate(...RUNNING)`（views.py:380, index_trigger:163）/ GraphBuildHistory 锁内创建（codegraph/views）；任务体 `tasks_impl.run_index/run_graph` 仅委托既有 `clone_and_index_repository`/`build_graph_for_repository`，checkpoint 零改动（tasks_impl.py:38/56 注释 + 复用 service） |
| 3 | 一次性迁移命令把存量 PENDING/RUNNING index/graph 行 defer durable、标 MIGRATED 记 legacy id、不双跑、幂等可重入、SQLite 安全降级（SC2） | ✓ VERIFIED | `migrate_resumable_to_durable.py`：扫 kind∈{index,graph}&status∈{pending,running}（line 67-72）、deterministic key（line 85）、白名单重建 payload（line 96-101）、`async_to_sync(defer)`（line 103）、条件 update→MIGRATED+legacy_durable_job_id（line 111-117）、非 durable 中文提示只统计不 defer（line 58-65, 88-90）。test_migrate_command.py 2 passed（sqlite_safe + no_double_run） |
| 4 | 启动 reconcile 仅在无 durable job 接管时标 RUNNING→FAILED（不误杀在途），background_runner 降级（SC3） | ✓ VERIFIED | `repositories/apps.py:65-99`、`codegraph/apps.py:78-91` 经 `has_active_durable_job_sync(index:/graph:{repo_id})` 并入排除集；helper（reconcile.py）非 durable 短路 False + fail-safe；`background_runner.py:6` docstring「降级为仅 SQLite dev fallback / 少量非持久轻任务」。test_reconcile_durable.py 全绿 |
| 5 | index/graph/page_index handler 在 at-least-once 重复投递/执行下幂等（IDEMP-01）（SC4） | ✓ VERIFIED | `has_active_by_key` 两后端（backends.py:185 in-process / 301 procrastinate）+ deterministic key 去重；run_page_index 占位恒等零副作用（tasks_impl.py:63）；test_idempotency.py（duplicate_dispatch/duplicate_execution/page_index）全绿、test_business_tasks.py 4 passed |

**Score:** 5/5 truths verified (SQLite path)

### Required Artifacts

| Artifact | Expected | Status | Details |
| -------- | -------- | ------ | ------- |
| `server/durable/tasks_impl.py` | run_index/run_graph/run_page_index 共用任务体 | ✓ VERIFIED | 零 procrastinate import；keyword-only 形参；复用既有 service |
| `server/durable/tasks.py` | @app.task 显式 name 包壳 | ✓ VERIFIED | durable_index/durable_graph/durable_page_index 显式 name + queue 常量 |
| `server/durable/handlers.py` | register_business_handlers in-process adapter | ✓ VERIFIED | 3 任务 **payload 展开 adapter |
| `server/durable/apps.py` | ready() 双后端无条件注册 | ✓ VERIFIED | register_business_handlers() 在 role/procrastinate 门禁之外无条件调用（line 23） |
| `server/durable/backends.py` | find_job_by_queueing_lock 公开 + 两后端 has_active_by_key | ✓ VERIFIED | line 185/276/301，活跃集补 scheduled |
| `server/durable/service.py` | DurableTaskService.has_active_by_key 门面 | ✓ VERIFIED | line 138，按后端委托 |
| `server/durable/reconcile.py` | has_active_durable_job(_sync) 判定 helper | ✓ VERIFIED | 经门面、async_to_sync 同步入口、零 procrastinate、fail-safe |
| `server/repositories/index_views.py` 等 5 入队点 | defer 迁移 | ✓ VERIFIED | 见 Truth #1 |
| `server/repositories/apps.py` / `codegraph/apps.py` | reconcile 改判定 | ✓ VERIFIED | 见 Truth #4 |
| `server/resumable/models.py` | MIGRATED 枚举 + legacy_durable_job_id 列 | ✓ VERIFIED | line 38/68 |
| `server/resumable/migrations/0002_resumable_migrated.py` | AddField + status choices | ✓ VERIFIED | 依赖 0001，AddField legacy_durable_job_id + AlterField status（含 migrated） |
| `server/durable/management/commands/migrate_resumable_to_durable.py` | 一次性命令 | ✓ VERIFIED | 见 Truth #3 |
| `server/services/background_runner.py` | 降级注释 | ✓ VERIFIED | line 6「降级为仅 SQLite dev fallback / 少量非持久轻任务」 |
| tests/durable/*, tests/repositories/test_reconcile_durable.py | 守护测试 | ✓ VERIFIED | 见 Behavioral Spot-Checks |

### Key Link Verification

| From | To | Via | Status |
| ---- | -- | --- | ------ |
| 5 入队点 | durable.DurableTaskService | defer(queue, idempotency_key) | ✓ WIRED |
| tasks.py / handlers.py | tasks_impl.py | @app.task 包壳 / in-process adapter import run_* | ✓ WIRED |
| apps.py(durable) | handlers.py | register_business_handlers() 无条件调用 | ✓ WIRED |
| repositories/apps.py & codegraph/apps.py | durable/reconcile.py | has_active_durable_job_sync(index:/graph:{repo_id}) | ✓ WIRED |
| reconcile.py | DurableTaskService.has_active_by_key | await 门面（非 get+deterministic key） | ✓ WIRED |
| migrate command | resumable.models | .update(status=MIGRATED, legacy_durable_job_id) | ✓ WIRED |

### Requirements Coverage

| Requirement | Source Plan | Status | Evidence |
| ----------- | ----------- | ------ | -------- |
| MIGRATE-01 | 61-01, 61-02 | ✓ SATISFIED | 5 入队点改 defer + queue/key + 真相源/checkpoint 保留（Truth #1/#2） |
| MIGRATE-02 | 61-02, 61-03, 61-04 | ✓ SATISFIED | 一次性迁移命令 + MIGRATED/legacy id + reconcile 改判定 + background_runner 降级（Truth #3/#4）。**真实 Postgres 升级 E2E 见 Human Verification** |
| IDEMP-01 | 61-01, 61-02 | ✓ SATISFIED | 重复投递/执行/page_index 幂等守护测试全绿（Truth #5） |

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
| -------- | ------- | ------ | ------ |
| durable+resumable 套件 SQLite 路径 | `uv run pytest tests/durable tests/resumable -q` | 66 passed, 13 deselected | ✓ PASS |
| 迁移命令守护 | test_migrate_command.py | 2 passed (sqlite_safe, no_double_run) | ✓ PASS |
| 幂等守护 | test_idempotency.py | 5 passed (duplicate_dispatch/execution/page_index) | ✓ PASS |
| 5 点迁移 grep + key 守护 | test_index_graph_migration.py | 9 passed | ✓ PASS |
| 双后端契约 + has_active_by_key | test_business_tasks.py | 4 passed | ✓ PASS |
| reconcile 安全语义 | test_reconcile_durable.py | passed（含 helper + reconcile 级） | ✓ PASS |
| procrastinate 路径专项（postgres_queue） | deselected | 需真实 Postgres | ? SKIP → Human Verification |

### Anti-Patterns Found

| File | Pattern | Severity | Impact |
| ---- | ------- | -------- | ------ |
| `durable/tasks_impl.py:run_page_index` | 占位 handler（恒等返回、零副作用） | ℹ️ Info | **有意为之** —— page_index 实际 ingest 接入按 CONTEXT 计划留 Phase 62；当前幂等占位满足 IDEMP-01 page_index 基线，不阻碍本相目标。无 TBD/FIXME/XXX 调试标记 |

### Human Verification Required

本相实现完整、SQLite 路径全部守护测试通过。以下 3 项需真实 Postgres + `DURABLE_TASK_BACKEND=procrastinate` 端到端验证（postgres_queue 用例本地默认 deselect）：

1. **一次性升级迁移（Postgres）** — 实跑 `migrate_resumable_to_durable`，确认存量在途行平滑转入 durable、旧行 MIGRATED + legacy id、重跑无重复 job。
2. **5 入队点 procrastinate 去重** — 同 repo 重复触发，确认 queueing_lock todo 唯一、无重复 durable job。
3. **多副本启动 reconcile 不误杀** — A 进程在途时 B 进程启动 reconcile，确认 has_active_by_key 命中保留 RUNNING。

### Pre-existing Failures (NOT Phase 61 Regressions)

跑 `tests/repositories/test_index_retry_resume.py` + `test_index_history_changed_files.py` → 2 failed, 3 passed。两失败经核查均**与 Phase 61 无关、非本相回归**，不应据此 fail 本相：

1. `test_failed_partial_index_with_checkpoint_resumes_full_index_not_incremental` —— 零引用 durable/defer/reconcile/wrap_resumable，直接调 `services.indexer.clone_and_index_repository`（Phase 61 未改 `services/indexer.py`，其最后提交 `9be453f06` 远早于 Phase 61）；失败为 indexer 返回 status='error'（services 层 / Py3.14·Django6 环境）。
2. `test_changed_files_populated_after_incremental_index` —— 失败为 "Database access not allowed, use the django_db mark"：该用例未挂 `@pytest.mark.django_db`（文件内注释明确），纯测试基建问题；Phase 61 未修改此测试文件。

### Gaps Summary

无阻断性 gap。Phase 61 的目标在代码与 SQLite 路径守护测试中均已达成：5 处入队点收口 durable、一次性迁移命令、reconcile 安全改判定、background_runner 降级、IDEMP-01 幂等基线。剩余仅为需真实 Postgres 才能端到端验证的升级/去重/多副本 reconcile 场景（实现已在位），归为 human_needed。

---

_Verified: 2026-06-19T20:40:00Z_
_Verifier: Claude (gsd-verifier)_
