---
phase: 60-durable
plan: 03
subsystem: infra
tags: [procrastinate, durable-task-queue, postgres, worker, periodic, queueing-lock, stalled-rescue, pytest-marker]

# Dependency graph
requires:
  - phase: 60-01
    provides: DurableTaskService 门面 + _use_procrastinate 唯一判定 + ProcrastinateBackend stub + queues.py + roles.py + postgres_queue marker + no-direct-import 守护
provides:
  - ProcrastinateBackend 真实实现（defer/get/cancel/retry_stalled 委托 procrastinate.contrib.django.app）
  - settings.py 条件注册 procrastinate.contrib.django（复用 _use_procrastinate，仅 Postgres+procrastinate）
  - durable.tasks：durable_ping 烟囱任务 + retry_stalled_durable_jobs（@app.periodic + queueing_lock 单例 leader rescue）
  - run_worker 管理命令（get_worker_connector → PsycopgConnector，独立 worker 进程，listen_notify=False）
  - DurableConfig.ready() 条件 import tasks 触发 @app.task/@app.periodic 注册
  - postgres_queue 测试（test_procrastinate_backend / test_stalled_rescue）+ Postgres conftest fixtures
affects: [60-04 Postgres CI, 61 index/graph 迁移, 62 爬取队列, 63 部署硬化]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "ProcrastinateBackend 全程仅在 backends.py 内 import procrastinate（适配层隔离命门），service 经局部 import 委托"
    - "settings 与 service 共用 _use_procrastinate 纯函数做条件注册（无 orphan procrastinate 表）"
    - "周期 stalled rescue = @app.periodic（DB 每周期单次 defer）+ queueing_lock（todo 不堆积）双层单例 leader，无自写 leader 选举/flock"
    - "stalled 判定基于 worker heartbeat（get_stalled_jobs 默认 seconds_since_heartbeat=30），零 deprecated nb_seconds"
    - "worker = 独立进程，get_worker_connector() → PsycopgConnector，绝不用 DjangoConnector 跑 worker"

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
  - "periodic rescue 体内直接调 get_stalled_jobs()/retry_job()（与 ProcrastinateBackend.retry_stalled 同算法、同 heartbeat 判定），保留 key_link 可 grep 性；两路径均零 nb_seconds"
  - "settings 条件 INSTALLED_APPS.append('procrastinate.contrib.django') 放在 DATABASES + DURABLE_TASK_BACKEND 定义之后（二者均为 append 所需），复用 _use_procrastinate"
  - "DurableConfig.ready() 任务注册角色门禁 allowed={web,worker,scheduler}，migrate/test 短路（复用 durable.roles）"
  - "run_worker 非 Postgres 后端 CommandError 明确退出，绝不退化 DjangoConnector/in-process 跑 worker"
  - "forged-heartbeat rescue 自动化：register_worker+fetch_job 占 doing → SQL 回拨 last_heartbeat → get_stalled_jobs/retry_job；真实 kill-worker E2E 标 manual-only（human_needed）"

patterns-established:
  - "postgres_queue 测试模块级 pytestmark=[postgres_queue, enable_socket, django_db(transaction=True)]，procrastinate_app fixture 非 Postgres pytest.skip（不报错）"
  - "Postgres 专用 fixture（procrastinate_app / backdate_worker_heartbeat）集中在 tests/durable/conftest.py，仅 postgres_queue 测试消费"

requirements-completed: [DURABLE-01, DURABLE-03]

# Metrics
duration: 18min
completed: 2026-06-20
---

# Phase 60 Plan 03: Procrastinate 后端 + periodic 单例 rescue Summary

**ProcrastinateBackend 落地（defer/get/cancel/retry_stalled 委托 procrastinate.contrib.django.app）+ 独立 worker 进程命令（get_worker_connector → PsycopgConnector，listen_notify=False）+ retry_stalled_durable_jobs 周期单例 leader（@app.periodic + queueing_lock，heartbeat 判定 stalled）+ settings 复用 _use_procrastinate 条件注册 + postgres_queue 测试覆盖 defer/priority/run_at/worker-connector/forged-heartbeat rescue/queueing_lock/并发竞争。**

## Performance

- **Duration:** ~18 min
- **Started:** 2026-06-20T18:14Z (approx)
- **Completed:** 2026-06-20T18:32Z (approx)
- **Tasks:** 3
- **Files modified:** 10 (6 created, 4 modified)

## Accomplishments
- `ProcrastinateBackend` 四方法真实实现：`defer` 经 `task.configure(queueing_lock=idempotency_key, priority, schedule_at=run_at).defer_async(**payload)`（`AlreadyEnqueued` 幂等吞并返回既有 job 标识）；`get`/`cancel`/`retry_stalled` 委托 `app.job_manager`。仍**仅在 backends.py 内** import procrastinate。
- `settings.py` 复用 `durable.service._use_procrastinate` 同一权威判定条件注册 `procrastinate.contrib.django`：SQLite/auto+sqlite 永不追加（无 orphan `procrastinate_jobs` 表，规避 Pitfall 3），仅 Postgres+backend∈{auto,procrastinate} 时追加。
- `durable.tasks`：`durable_ping` 烟囱任务 + `retry_stalled_durable_jobs`（`@app.periodic(cron="*/10 * * * *")` + `@app.task(queueing_lock="retry_stalled_durable_jobs", pass_context=True)`），基于 worker heartbeat 判定 stalled，**零 nb_seconds**（慢≠死）。
- `run_worker` 管理命令：`get_worker_connector()` 拿 `PsycopgConnector` 独立 async 连接跑 worker，**显式 `listen_notify=False`**（v1 polling，NOTIFY 唤醒 deferred 到 v2 DURABLEX-01）；非 Postgres 后端明确中文 `CommandError` 退出，绝不退化 DjangoConnector。
- `DurableConfig.ready()` 仅在 procrastinate 后端启用且角色∈{web,worker,scheduler} 时 `from durable import tasks` 触发注册；SQLite/migrate/test 短路零副作用。
- `postgres_queue` 测试（8 例）覆盖 DURABLE-01 Postgres 半 + DURABLE-03 rescue/queueing_lock/并发；默认 SQLite 套件不命中（8 deselected），强制 `-m postgres_queue` 在无 Postgres 时优雅 skip（非 error）。

## Task Commits

Each task was committed atomically:

1. **Task 1: ProcrastinateBackend + settings 条件注册** - `505277eca` (feat)
2. **Task 2: periodic 单例 rescue + run_worker 命令 + apps.py 任务注册** - `351d07255` (feat)
3. **Task 3: postgres_queue 测试 + conftest postgres fixtures** - `9c86d0f50` (test)

**Plan metadata:** 由 orchestrator 负责 STATE/ROADMAP；本 plan 不写。SUMMARY 单独提交。

_Note: TDD 非本 plan 模式（后端 API 在 RESEARCH 已逐字锁定）。_

## Files Created/Modified
- `server/durable/backends.py` — `ProcrastinateBackend` 四方法真实实现（defer/get/cancel/retry_stalled），`AlreadyEnqueued` 幂等处理 + `_find_job_by_queueing_lock` 辅助
- `server/durable/tasks.py` — `durable_ping` + `retry_stalled_durable_jobs`（periodic + queueing_lock 单例）
- `server/durable/management/commands/run_worker.py` — 独立 worker 进程命令（`get_worker_connector`，`listen_notify=False`）
- `server/durable/management/__init__.py`、`server/durable/management/commands/__init__.py` — 空包标记
- `server/durable/apps.py` — `DurableConfig.ready()` 条件 import tasks（procrastinate 后端 + 角色门禁）
- `server/friday/settings.py` — `_use_procrastinate` 条件 `INSTALLED_APPS.append("procrastinate.contrib.django")`
- `server/tests/durable/conftest.py` — `procrastinate_app`（非 Postgres skip）+ `backdate_worker_heartbeat`（伪造心跳过期）fixtures
- `server/tests/durable/test_procrastinate_backend.py` — defer 落库/priority 领取顺序/run_at 调度/get_worker_connector
- `server/tests/durable/test_stalled_rescue.py` — forged-heartbeat 重投/priority 保留/queueing_lock 单例/并发竞争

## Decisions Made
- **periodic 任务体内直接调 `get_stalled_jobs()`/`retry_job()`**（而非委托 `procrastinate_backend.retry_stalled()`）：满足 Task 2 acceptance 字面"体内调 get_stalled_jobs()/retry_job()"与 frontmatter key_link 的 `pattern: get_stalled_jobs|retry_job`（tasks.py 可直接 grep 命中），同时与 `ProcrastinateBackend.retry_stalled`（服务 `DurableTaskService.retry_stalled` 直接路径）保持**完全相同的算法**（heartbeat 判定、零 nb_seconds）；两者算法一致，差异仅为调用入口（手动/运维 vs 多副本周期 leader）。"复用同一实现"按"同算法/同判据"解读。
- **settings 条件块落点**：放在 `DATABASES`（line 245）+ `DURABLE_TASK_BACKEND`（line 254）定义之后——append 需读引擎串与 backend 值，二者均在 `INSTALLED_APPS` 之后定义，故条件块紧跟 durable 设置段。仍满足 plan "在 INSTALLED_APPS 定义之后" 要求。
- **`get` 经 `list_jobs_async(id=...)` 拼结构化 dict**（status/queue/priority/queueing_lock/scheduled_at/attempts）；未知 job 返回 `{"status": "unknown"}`（与 in-process 后端一致，不抛）。

## Deviations from Plan

None - 三个任务的 acceptance 与 verify 命令全部一次通过，无 Rule 1/2/3 自动修复触发，无 Rule 4 架构变更。

唯一需记录的取舍是上节「Decisions Made」第一条（periodic 体内直接调 vs 委托后端）——这是对 Task 1「供 periodic 复用同一实现」与 Task 2「体内调 get_stalled_jobs()/retry_job()」两处措辞张力的有意调和，按"同算法"而非"同代码对象"落地，无范围扩张、无架构变更。

---

**Total deviations:** 0 自动修复（仅 1 处措辞调和，已记录）。
**Impact on plan:** 完全按计划落地，SQLite 默认套件零回归。

## Issues Encountered
- **Procrastinate 3.8.1 API 确认**：`get_stalled_jobs`/`retry_job`/`cancel_job_by_id_async`/`list_jobs_async`/`defer_job_async` 均为 async；`get_stalled_jobs(seconds_since_heartbeat=30)` 为 heartbeat 判定（`nb_seconds` 已 deprecated）；`get_worker_connector()` 在 DjangoConnector 上存在 → 返回 `PsycopgConnector`；`procrastinate.contrib.django` 用 blueprint 模式（`@app.task` 在其 `ready()` 前注册到 blueprint，由 `create_app` 并入真实 App）——故 durable 在 INSTALLED_APPS 中先于（append 在末尾的）procrastinate.contrib.django，`durable.ready()` 的 `@app.task` 注册仍正确被并入。逐项经 `uv run python` 实测确认后再编码。

## Manual-Only Verification (human_needed)
- **真实 kill-worker → 另一 worker 经周期 leader rescue 接管在途 stalled 任务重投**（DURABLE-03）：需两个活 worker 进程 + 真实 Postgres + 等心跳过期，CI 昂贵/不稳。见 `60-VALIDATION.md`「Manual-Only Verifications」，标 human_needed。本 plan 的 `test_stalled_rescue.py` 用 forged-heartbeat（register_worker + fetch_job 占 doing → SQL 回拨 `last_heartbeat` → `get_stalled_jobs`/`retry_job`）自动化逼近，不真 kill 进程。

## User Setup Required
None — SQLite 默认路径无需外部服务。Postgres durable 后端 / worker 进程的实际运行验证由 Plan 60-04（Postgres CI，postgres:17-alpine service 跑 `-m postgres_queue`）落地；`postgres_queue` 测试在无 Postgres 的本地默认套件被 deselect（不影响 dev/pytest）。

## Verification Results
- `uv run python manage.py check`（SQLite 默认）→ System check identified no issues，未注册 procrastinate.contrib.django。
- `uv run pytest tests/durable/test_no_direct_import.py -q` → 1 passed（import 隔离守护绿，新增 tasks.py/management/ 在允许清单内）。
- `uv run python manage.py run_worker --help` → 打印帮助（SQLite 下不触达 procrastinate）；`grep -n "listen_notify=False" run_worker.py` 命中。
- `uv run pytest tests/durable -q` → **31 passed, 8 deselected**（postgres_queue 默认排除，SQLite 套件零回归）。
- `uv run pytest tests/durable -m postgres_queue -q`（无 Postgres）→ **8 skipped, 31 deselected**（collected-but-skipped，非 error）。
- `uv run pytest tests/durable -m postgres_queue --co -q` → 8 tests collected，无收集错误。
- `uv run ruff check durable friday/settings.py tests/durable` → All checks passed。
- `grep -rn "nb_seconds=" durable/` → 无命中（heartbeat 判定，绝不用 deprecated nb_seconds）。
- `grep -n "_use_procrastinate" friday/settings.py` → import（line 271）+ 调用（line 273）命中，settings 内无另写等价判据。

## Next Phase Readiness
- ✅ Procrastinate durable 后端 + 独立 worker 命令 + periodic 单例 rescue 就位，DURABLE-01 Postgres 半 + DURABLE-03 闭环达成。
- ✅ `postgres_queue` 测试就位，Plan 60-04 可直接建 postgres:17-alpine service CI job 跑 `-m postgres_queue --allow-hosts=127.0.0.1,localhost`。
- ✅ `durable_ping` 烟囱任务 + 队列常量就位，Phase 61/62 在此之上接业务任务（index/graph/crawl 迁移）。
- ⚠️ Postgres 路径未在本地实测（无本地 Postgres）；测试按 Procrastinate 3.8.1 公开 API 设计、SQLite 下 collected-but-skipped 已验证，真实 Postgres 全绿由 Plan 60-04 CI 强制。
- ⚠️ 真实 kill-worker E2E 留人工（manual-only / human_needed）。

## Self-Check: PASSED
- 6 个新增交付文件 + SUMMARY.md 全部存在（durable/tasks.py、management/commands/run_worker.py、两个空包 `__init__.py`、两个 postgres_queue 测试文件、60-03-SUMMARY.md）。
- 3 个 task 提交（505277eca / 351d07255 / 9c86d0f50）经 `git cat-file -e` 确认存在。
- 未修改 / 未 staging STATE.md / ROADMAP.md（仅提交各 task 文件 + SUMMARY；STATE/ROADMAP 的工作树改动为 plan 前既有，非本 plan 产生）。

---
*Phase: 60-durable*
*Completed: 2026-06-20*
