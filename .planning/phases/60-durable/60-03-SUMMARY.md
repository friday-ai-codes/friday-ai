---
phase: 60-durable
plan: 03
subsystem: infra
tags: [procrastinate, postgres, durable-task-queue, periodic, queueing-lock, worker, pytest-postgres-marker]

# Dependency graph
requires:
  - phase: 60-01
    provides: DurableTaskService 门面 + _use_procrastinate 唯一判定 + ProcrastinateBackend stub + queues.py + postgres_queue marker
provides:
  - ProcrastinateBackend 真实实现（defer/get/cancel/retry_stalled 委托 procrastinate.contrib.django.app）
  - settings.py 条件注册 procrastinate.contrib.django（复用 _use_procrastinate，仅 Postgres+backend∈{auto,procrastinate}）
  - tasks.py：durable_ping 烟囱任务 + retry_stalled_durable_jobs（@app.periodic + queueing_lock 单例 leader）
  - run_worker 管理命令（get_worker_connector → PsycopgConnector，显式 listen_notify=False）
  - DurableConfig.ready() 条件 import tasks 触发 @app.task/@app.periodic 注册
  - postgres_queue 测试（defer/priority/run_at/worker-connector + forged-heartbeat rescue/queueing_lock/并发竞争）
affects: [60-04 Postgres CI, 61 index/graph 迁移, 62 爬取队列, 63 部署硬化]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "settings 与 service 共用同一 _use_procrastinate 纯函数做 procrastinate.contrib.django 条件注册（无 orphan procrastinate 表）"
    - "周期单例 leader = @app.periodic（DB 每周期单次 defer）+ queueing_lock（todo 不堆积），无自写 leader 选举/flock"
    - "worker = 独立进程经 get_worker_connector()（PsycopgConnector），绝不用 DjangoConnector 跑 worker"
    - "stalled 判定基于 worker heartbeat（get_stalled_jobs），零 deprecated nb_seconds"
    - "postgres_queue 测试用 forged-heartbeat（回拨 procrastinate_workers.last_heartbeat）逼近 stalled rescue，不真 kill 进程"

key-files:
  created:
    - server/durable/tasks.py
    - server/durable/management/__init__.py
    - server/durable/management/commands/__init__.py
    - server/durable/management/commands/run_worker.py
    - server/tests/durable/test_procrastinate_backend.py
    - server/tests/durable/test_stalled_rescue.py
  modified:
    - server/durable/backends.py
    - server/durable/apps.py
    - server/friday/settings.py
    - server/tests/durable/conftest.py

key-decisions:
  - "settings.py 经 from durable.service import _use_procrastinate 复用同一判定，禁止内联等价判据"
  - "run_worker 固定 listen_notify=False（v1 polling，NOTIFY 唤醒 deferred 到 v2 DURABLEX-01）；非 Postgres 时 CommandError 退出，绝不退化 DjangoConnector"
  - "retry_stalled_durable_jobs 与 ProcrastinateBackend.retry_stalled 同算法（heartbeat 判定）；periodic 是多副本 leader 路径，后端方法服务手动/运维直接路径"
  - "真实 kill-worker E2E 标 human_needed（VALIDATION Manual-Only），自动化以 forged-heartbeat 逼近"

patterns-established:
  - "durable 业务代码仅 backends.py / tasks.py / management/ 三处允许直接 import procrastinate（no-direct-import 守护允许清单）"
  - "postgres_queue 测试模块级标记叠加：postgres_queue + enable_socket + django_db(transaction=True)"

requirements-completed: [DURABLE-01, DURABLE-03]

# Metrics
duration: ~30min
completed: 2026-06-20
---

# Phase 60 Plan 03: Procrastinate 后端 + periodic rescue 单例 Summary

**ProcrastinateBackend 落地 Postgres durable 路径（defer/get/cancel/retry_stalled 委托 procrastinate.contrib.django.app），独立 worker 进程命令（get_worker_connector → PsycopgConnector，listen_notify=False），retry_stalled_durable_jobs 周期单例 leader（@app.periodic + queueing_lock + heartbeat 判定），settings 复用 _use_procrastinate 条件注册 procrastinate.contrib.django，并以 postgres_queue 测试覆盖 defer/priority/run_at/worker-connector/forged-heartbeat rescue/queueing_lock/并发竞争。**

## Performance

- **Duration:** ~30 min（含 Wave 1/2 前序实现 + Task 3 测试收尾）
- **Started:** 2026-06-20T01:56Z (approx)
- **Completed:** 2026-06-20T02:25Z (approx)
- **Tasks:** 3
- **Files modified:** 10 (6 created, 4 modified)

## Accomplishments
- `ProcrastinateBackend` 四方法全部落地委托 `procrastinate.contrib.django.app`：`defer` 经 `task.configure(queueing_lock=idempotency_key, priority, schedule_at=run_at).defer_async(**payload)`，`AlreadyEnqueued` 按幂等吞并返回既有 job 标识；`retry_stalled` 基于 `get_stalled_jobs()`（heartbeat）+ `retry_job()`，源码零 `nb_seconds`。
- `settings.py` 经 `from durable.service import _use_procrastinate` 复用同一权威判定，仅在 Postgres + backend∈{auto,procrastinate} 时 `INSTALLED_APPS.append("procrastinate.contrib.django")`；SQLite/auto+sqlite 永不追加，无 orphan procrastinate 表，迁移在 SQLite 安全（Pitfall 3）。
- `tasks.py`：`durable_ping` 烟囱任务 + `retry_stalled_durable_jobs`（`@app.periodic(cron="*/10 * * * *")` + `@app.task(queueing_lock="retry_stalled_durable_jobs", pass_context=True)`），双层叠加实现单例 leader（DB 每周期单次 defer + queueing_lock 不堆积），无自写 leader/flock。
- `run_worker` 管理命令：经 `app.connector.get_worker_connector()` 拿 `PsycopgConnector` 独立进程消费，`run_worker_async(..., listen_notify=False)` 显式锁定；非 Postgres 时 `CommandError` 明确中文退出，绝不退化 DjangoConnector 跑 worker（PoC 硬前置①）。
- `DurableConfig.ready()` 仅在 procrastinate 后端启用且 role∈{web,worker,scheduler} 时 import `durable.tasks` 触发注册；SQLite/migrate/test 短路零副作用。
- postgres_queue 测试两文件 8 用例：`test_procrastinate_backend.py`（defer 落库/priority 领取顺序/run_at→scheduled_at/get_worker_connector→PsycopgConnector）、`test_stalled_rescue.py`（forged-heartbeat rescue/重投保留 priority/queueing_lock 单例不堆积/并发竞争恰一领取）；模块级 `postgres_queue + enable_socket + django_db(transaction=True)`，无 Postgres 时经 `procrastinate_app` fixture `pytest.skip`。

## Task Commits

Each task was committed atomically:

1. **Task 1: settings 条件注册 + ProcrastinateBackend 实现** - `505277eca` (feat)
2. **Task 2: periodic 单例 rescue + 独立 worker 命令 + tasks 条件注册** - `351d07255` (feat)
3. **Task 3: postgres_queue 测试（defer/priority/run_at/worker-connector + stalled rescue）** - `9c86d0f50` (test)

_注：本 plan 不写 STATE.md / ROADMAP.md（由 orchestrator 负责）；无 plan-metadata 提交。_

## Files Created/Modified
- `server/durable/backends.py` — `ProcrastinateBackend` 四方法真实实现（stub→委托 procrastinate.contrib.django.app）
- `server/durable/tasks.py` — `durable_ping` + `retry_stalled_durable_jobs`（periodic + queueing_lock 单例）
- `server/durable/apps.py` — `DurableConfig.ready()` 条件 import tasks 注册
- `server/durable/management/{__init__,commands/__init__}.py` — 空包标记
- `server/durable/management/commands/run_worker.py` — 独立 worker 进程命令（get_worker_connector / listen_notify=False）
- `server/friday/settings.py` — 复用 `_use_procrastinate` 条件 `INSTALLED_APPS.append("procrastinate.contrib.django")`
- `server/tests/durable/conftest.py` — Postgres 专用 fixture（`procrastinate_app` skip-if-not-postgres / `backdate_worker_heartbeat` forged-heartbeat）
- `server/tests/durable/test_procrastinate_backend.py` — defer/priority/run_at/worker-connector（postgres_queue）
- `server/tests/durable/test_stalled_rescue.py` — forged-heartbeat rescue/queueing_lock/并发竞争（postgres_queue）

## Decisions Made
- **settings 复用 service 同一 `_use_procrastinate`（不内联）**：保证后端判据 single source of truth，procrastinate 表仅在后端真正启用时由迁移创建。
- **`listen_notify=False` 显式锁定**：v1 走 polling，低延迟 NOTIFY 唤醒 deferred 到 v2（DURABLEX-01）；`run_worker` 与 docstring 双处标注。
- **periodic + backend.retry_stalled 同算法、双入口**：periodic（`retry_stalled_durable_jobs`）是多副本持续 rescue 的 leader 路径；`ProcrastinateBackend.retry_stalled` 服务 `DurableTaskService.retry_stalled` 的手动/运维直接路径；二者均 heartbeat 判定、零 nb_seconds。
- **forged-heartbeat 自动化逼近 stalled rescue**：回拨 `procrastinate_workers.last_heartbeat` 至 1 小时前，使其 doing job 在默认 `seconds_since_heartbeat=30` 下判为 stalled；真实 kill-worker E2E 标 human_needed。

## Deviations from Plan

None - plan executed exactly as written. 无 Rule 1/2/3 自动修复触发；无 Rule 4 架构变更。

## Issues Encountered
None — 三个任务的 acceptance 与 verify 命令全部通过；Tasks 1/2 在前序 wave 已提交实现，Task 3 完成测试收尾后提交。

## Verification Results
- `cd server && uv run python manage.py check`（SQLite 默认）→ **0 issues**，未尝试建 procrastinate 表。
- `cd server && uv run pytest tests/durable -q`（SQLite）→ **31 passed, 8 deselected**（postgres_queue 两文件 8 用例被 addopts `not postgres_queue` 默认排除，非 errored）。
- `cd server && uv run ruff check durable tests/durable` → All checks passed。
- `cd server && uv run python manage.py run_worker --help` → 帮助正常打印。
- `grep -n "listen_notify=False" durable/management/commands/run_worker.py` → 命中（实参与 docstring）。
- `grep -n "_use_procrastinate" friday/settings.py` → 命中 import 与调用（settings 无另写等价判据）。
- no-direct-import 守护：`test_no_direct_import.py` 绿（durable/tasks.py、durable/management/、friday/settings.py、tests/ 在允许清单内）。
- Postgres 专项（本地无 Postgres，未执行；CI 在 Plan 60-04 强制）：`DATABASE_URL=postgres://... DURABLE_TASK_BACKEND=procrastinate uv run pytest -m postgres_queue --allow-hosts=127.0.0.1,localhost -q`。

## Manual-Only / Deferred Verifications
- **真实 kill-worker E2E**（kill 一个活 worker → 另一 worker 经周期 leader rescue 接管在途 stalled 重投）：需两个活 worker 进程 + 真实 Postgres + 等心跳过期，CI 昂贵/不稳，标 **human_needed**（见 60-VALIDATION.md「Manual-Only Verifications」），不在本自动化范围；自动化以 forged-heartbeat 逼近。
- **Postgres CI job**（postgres:17-alpine service 跑 `-m postgres_queue`）：由 Plan 60-04 落地。

## User Setup Required
None — SQLite 默认路径无需外部服务。Postgres durable 后端 / worker 进程需部署侧配置 `DATABASE_URL=postgres://...`（+ 可选 `DURABLE_TASK_BACKEND=procrastinate`、worker 进程 `FRIDAY_PROCESS_ROLE=worker`），由后续部署阶段消费。

## Next Phase Readiness
- ✅ Postgres durable 入队/消费 + 周期单例 rescue 内核就位，Plan 60-04 可在此之上建最小聚焦 Postgres CI（server-ci SQLite + postgres-queue service 两 job）跑 `-m postgres_queue`。
- ✅ `durable_ping` 烟囱任务 + queues 常量就位，Phase 61/62 迁移 index/graph/crawl 业务任务可经 `@app.task` 注册 + `DurableTaskService.defer` 入队。
- ⚠️ 真实 kill-worker E2E 留人工验证；postgres_queue 套件本地未跑（无 Postgres），CI 强制在 Plan 60-04。

## Self-Check: PASSED
- 6 个新建文件 + 4 个修改文件全部存在并落地。
- 3 个 task 提交（505277eca / 351d07255 / 9c86d0f50）经 git log 确认存在。
- Task 3 提交 `9c86d0f50` 仅含 conftest.py + test_procrastinate_backend.py + test_stalled_rescue.py 三文件（无不相关文件混入）。
- 未修改 STATE.md / ROADMAP.md（由 orchestrator 负责）。

---
*Phase: 60-durable*
*Completed: 2026-06-20*
