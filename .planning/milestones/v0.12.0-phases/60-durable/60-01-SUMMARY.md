---
phase: 60-durable
plan: 01
subsystem: infra
tags: [procrastinate, durable-task-queue, background-runner, django-app, pytest-marker]

# Dependency graph
requires:
  - phase: resumable (既有)
    provides: lease/CAS/recovery 范式 + services.background_runner 常驻 worker loop
provides:
  - DurableTaskService 统一门面（defer/get/cancel/retry_stalled + queue/priority/idempotency_key/run_at）
  - _use_procrastinate(engine, backend) 唯一权威后端判定（service 与 settings 共用）
  - InProcessBackend 进程内非 durable fallback（复用 background_runner，无需 Postgres）
  - 队列命名常量 queues.py（index/graph/crawl_ingest/page_index/maintenance + ALL_QUEUES）
  - roles.py 进程角色判定（current_role + should_run_startup_side_effects，供 Plan 02 消费）
  - no-direct-import grep 守护 + postgres_queue pytest marker（默认排除）
  - procrastinate[django]>=3.8.1,<3.9 依赖落地
affects: [60-02 进程角色门禁, 60-03 Procrastinate 后端/periodic rescue, 60-04 Postgres CI, 61 index/graph 迁移, 62 爬取队列]

# Tech tracking
tech-stack:
  added: ["procrastinate[django]>=3.8.1,<3.9 (+croniter, psycopg-pool 传递依赖)"]
  patterns:
    - "适配层隔离：业务侧只 import durable.DurableTaskService，后端经方法体内局部 import 选择"
    - "唯一权威判定纯函数 _use_procrastinate：service 与 settings 共用，零 Django 顶层依赖避免循环 import"
    - "in-process fallback 复用 services.background_runner（不自写线程模型）"

key-files:
  created:
    - server/durable/__init__.py
    - server/durable/apps.py
    - server/durable/service.py
    - server/durable/backends.py
    - server/durable/queues.py
    - server/durable/roles.py
    - server/tests/durable/__init__.py
    - server/tests/durable/conftest.py
    - server/tests/durable/test_service_fallback.py
    - server/tests/durable/test_no_direct_import.py
  modified:
    - server/friday/settings.py
    - server/pyproject.toml
    - server/uv.lock

key-decisions:
  - "_use_procrastinate 采用 amended 语义：postgresql + backend∈{auto,procrastinate} → True（auto+Postgres 即 durable，production 开箱即用）"
  - "service.py 顶层零 Django import；settings 读取一律函数体内局部，保证 settings.py 可安全 import 该函数"
  - "in-process fallback 未注册任务记 no-op 成功（debug 日志），保证无 Postgres + 未接任务时 dev/pytest 不报错"
  - "no-direct-import 守护允许清单：durable/backends.py、durable/tasks.py、durable/management/、friday/settings.py、tests/、migrations、.venv"

patterns-established:
  - "队列名走 durable.queues 常量，禁止业务侧裸写字符串"
  - "进程角色门禁判据集中在 durable.roles（独立读 env，不依赖 settings）"

requirements-completed: [DURABLE-01]

# Metrics
duration: 13min
completed: 2026-06-20
---

# Phase 60 Plan 01: durable 底座地基 Summary

**DurableTaskService 适配层立起：唯一权威 `_use_procrastinate` 后端判定 + 复用 background_runner 的 SQLite in-process fallback + 队列常量/进程角色 helper + no-direct-import 守护与 postgres_queue marker，procrastinate[django] 3.8.1 落地。**

## Performance

- **Duration:** ~13 min
- **Started:** 2026-06-20T01:43Z (approx)
- **Completed:** 2026-06-20T01:56Z (approx)
- **Tasks:** 3
- **Files modified:** 13 (10 created, 3 modified)

## Accomplishments
- 新建 `server/durable/` Django app（镜像 `resumable/` 结构），业务侧经 `from durable import DurableTaskService` 单点导入，看不见队列实现。
- `_use_procrastinate(engine, backend)` 唯一权威判定纯函数：真值表全分支验证，service 与 settings.py 可共用同一判据（顶层零 Django 依赖，避免循环 import）。
- `InProcessBackend` 复用 `services.background_runner.run_in_background`：`defer/get/cancel/retry_stalled` 在 SQLite/无 DATABASE_URL 下全部可用且不触达 Postgres（pytest-socket 无 SocketBlockedError）。
- 队列命名常量 + `roles.py`（`current_role` / `should_run_startup_side_effects`，供 Plan 02 三处 apps.py 消费）。
- `postgres_queue` marker 注册并在 addopts 默认排除；`test_no_direct_import.py` rg 守护断言业务代码零直接 import procrastinate。
- `procrastinate[django]>=3.8.1,<3.9` 落入依赖（实测 import 版本 3.8.1）。

## Task Commits

1. **Task 1: durable app 骨架 + 队列常量 + roles + settings/pyproject 注册** - `23acb864d` (feat)
2. **Task 2: DurableTaskService + InProcessBackend SQLite fallback 测试** - `c86f9b4ce` (test)
3. **Task 3: no-direct-import 守护 + postgres_queue marker + test 基础设施** - `8c74491cd` (test)

_注：本 plan 不写 STATE.md / ROADMAP.md（由 orchestrator 负责）；无 plan-metadata 提交。_

## Files Created/Modified
- `server/durable/__init__.py` — curated re-export（DurableTaskService + 队列常量）
- `server/durable/service.py` — `_use_procrastinate` 唯一判定 + `use_procrastinate_backend` fail-soft 封装 + `DurableTaskService` 门面
- `server/durable/backends.py` — `DurableBackend`(Protocol) + `InProcessBackend`(复用 background_runner) + `ProcrastinateBackend`(stub) + 单例
- `server/durable/queues.py` — 5 个队列常量 + `ALL_QUEUES`
- `server/durable/roles.py` — `current_role` / `should_run_startup_side_effects`
- `server/durable/apps.py` — `DurableConfig`（ready() 本 plan 空）
- `server/tests/durable/{__init__,conftest,test_service_fallback,test_no_direct_import}.py` — fallback + 守护测试
- `server/friday/settings.py` — INSTALLED_APPS +`durable`、新增 `DURABLE_TASK_BACKEND` / `FRIDAY_PROCESS_ROLE`
- `server/pyproject.toml` — procrastinate 依赖 + `postgres_queue` marker + addopts 排除
- `server/uv.lock` — 锁定 procrastinate 3.8.1 + croniter/psycopg-pool

## Decisions Made
- **后端判定语义采纳 CONTEXT amended 版**：`postgresql + backend∈{auto,procrastinate}` → durable，`auto`+Postgres 即开箱 durable；`inprocess`/非 Postgres → fallback。
- **`run_at` 在 fallback 用进程内 sleep 逼近** schedule_at（明确非 durable，进程重启即丢）。
- **`idempotency_key` 直接用作 background_runner 的 name**：同 key 二次 defer 覆盖同名注册（可预期、可观测），无 key 时派生 `durable:{queue}:{uuid4}`。

## Deviations from Plan

### 计划内任务边界微调（非自动修复，记录以备审阅）

**1. service.py / backends.py 在 Task 1 落地（而非 Task 2）**
- **原因：** Task 1 验收命令要求 `from durable import DurableTaskService` 可导入；`__init__.py` 的 curated re-export 必须 import 到 `durable.service`，故 service.py + backends.py 的完整实现随 Task 1 一并提交，保证每个 task 提交后验收即绿。
- **影响：** Task 2 聚焦补齐行为测试套件（`test_service_fallback.py`），实现已就位。无范围扩张。

**2. `tests/durable/__init__.py` 在 Task 2 落地（计划列在 Task 3）**
- **原因：** 本仓库测试子目录均带 `__init__.py`（tests/delivery、tests/audit、tests/chat 同例）；Task 2 的 `pytest tests/durable/test_service_fallback.py` 需要包标记才能被正确收集，故随 Task 2 提交。
- **影响：** 仅文件提交时点前移一格，内容与计划一致。

### TDD Gate Compliance（Task 2 tdd="true"）
本 plan 后端判定与签名在 CONTEXT/RESEARCH 已逐字锁定，且 Task 1 验收（import 门面）强制要求实现先于测试存在，故未严格走 RED→GREEN（实现先于测试提交，测试提交即 GREEN）。所有行为断言（真值表、fallback 不报错、fail-soft 告警）均已落测并通过。

---

**Total deviations:** 2 任务边界微调（无自动修复 Rule 1/2/3 触发）。
**Impact on plan:** 全部为满足"每 task 提交后验收即绿"的必要前移，无范围扩张、无架构变更。

## Issues Encountered
None — 三个任务的 acceptance 与 verify 命令全部一次通过。

## Verification Results
- `uv run python manage.py check` → 0 issues。
- `uv run ruff check durable && ruff format --check durable` → 全绿。
- `uv run python -c "import durable; ... QUEUE_INDEX, len(ALL_QUEUES)"` → `index 5`。
- `uv run python -c "import procrastinate; print(...)"` → `3.8.1`。
- `grep procrastinate.contrib.django friday/settings.py` → 无命中（SQLite migrate 安全）。
- `uv run pytest tests/durable -q` → **15 passed**。
- `uv run pytest -m postgres_queue -q` → 5957 deselected / 0 executed（无 Postgres 连接错误）。
- 全量 `pytest` 收集阶段无 import 错误（postgres_queue 选择运行时确认 5957 项可正常收集，新增 durable app 未破坏既有套件收集）。

## User Setup Required
None — 本 plan 仅 SQLite fallback 路径消费 procrastinate 依赖，无需外部服务配置。Postgres durable 后端 / worker 进程 / CI 由后续 Plan 60-03/60-04 落地。

## Next Phase Readiness
- ✅ `DurableTaskService` 门面 + `_use_procrastinate` 单一判据就位，Plan 60-03 可直接 `from durable.service import _use_procrastinate` 做 `procrastinate.contrib.django` 条件注册。
- ✅ `durable.roles` 就位，Plan 60-02 可在 repositories/codegraph/resumable 三处 `apps.py` 接入门禁。
- ✅ 队列常量、`ProcrastinateBackend` 占位、`postgres_queue` marker 已备好，Plan 60-03/60-04 在此之上叠加真实后端与 Postgres CI。
- ⚠️ 未在本 plan 跑完整 SQLite 全量套件（耗时）；已确认收集无错且 durable 子套件全绿，全量回归留 wave/phase gate。

## Self-Check: PASSED
- 10 个交付文件全部存在（6 durable 源 + 4 测试/SUMMARY）。
- 3 个 task 提交（23acb864d / c86f9b4ce / 8c74491cd）经 `git cat-file -e` 确认存在。
- 未修改 STATE.md / ROADMAP.md（由 orchestrator 负责）。

---
*Phase: 60-durable*
*Completed: 2026-06-20*
