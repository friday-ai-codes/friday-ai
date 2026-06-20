---
phase: 60-durable
verified: 2026-06-20T02:40:00Z
status: human_needed
score: 12/12 must-have truths verified (code-level); 4 runtime behaviors require real Postgres / E2E
overrides_applied: 0
human_verification:
  - test: "Postgres 部署下经 -m postgres_queue 跑 test_procrastinate_backend.py（defer 落 procrastinate_jobs / priority 领取顺序 / run_at→scheduled_at / get_worker_connector→PsycopgConnector）"
    expected: "8 个 postgres_queue 用例全绿（本机无 Postgres，仅能 collect 8 项后 skip）"
    why_human: "需真实 Postgres（CI postgres:17-alpine service 或本地 DATABASE_URL=postgres + DURABLE_TASK_BACKEND=procrastinate），本验证环境无 Postgres，pytest-socket 默认禁 TCP"
  - test: "forged-heartbeat stalled rescue：伪造 worker 心跳过期后 retry_stalled() 把 doing job 重投回 todo（test_stalled_rescue.py）"
    expected: "stalled 被 get_stalled_jobs() 命中且重投回 TODO；queueing_lock 单例不堆积；并发 fetch 恰一个领取"
    why_human: "依赖真实 Postgres procrastinate_workers/procrastinate_jobs 表与 SKIP LOCKED 语义，无法在 SQLite/无 PG 环境执行"
  - test: "真实 kill-worker E2E：起两个活 worker 进程，kill 其一，另一 worker 经周期 retry_stalled_durable_jobs（queueing_lock 单 leader）接管在途 stalled 任务"
    expected: "被杀 worker 的在途任务在心跳过期后被另一 worker 重新领取并完成，多副本仅一个 leader 周期扫 stalled"
    why_human: "60-VALIDATION.md 已标 Manual-Only：需双活 worker 进程 + 真实 Postgres + 等待心跳过期，CI 昂贵/不稳；forged-heartbeat 已自动逼近"
  - test: "GitHub Actions postgres-queue job 推送后实跑为绿（server-ci SQLite 零回归 + postgres-queue durable 覆盖）"
    expected: "server-ci 绿（SQLite 默认）、postgres-queue 绿（migrate 建表后 -m postgres_queue 全覆盖 defer/priority/retry/stalled/并发/fallback）"
    why_human: "workflow YAML 已合法且 job 结构正确，但需推送到 GitHub 由 Actions runner 实跑确认绿灯，本地无法触发"
---

# Phase 60: durable 底座地基 Verification Report

**Phase Goal:** 立起统一 durable 任务底座——`DurableTaskService` 适配层隔离队列实现（Postgres→Procrastinate 3.8.1 / SQLite→in-process 非 durable fallback）+ 进程角色门禁（FRIDAY_PROCESS_ROLE）收口启动副作用 + 周期 rescue/leader 单例（queueing_lock）+ Postgres 专项 CI。

**Verified:** 2026-06-20T02:40:00Z
**Status:** human_needed
**Re-verification:** No — initial verification

## Goal Achievement

### Observable Truths

| #   | Truth | Status | Evidence |
| --- | ----- | ------ | -------- |
| 1 | 业务代码经 `DurableTaskService.defer/get/cancel/retry_stalled` 入队/查询/取消，无 Postgres 时退化 in-process fallback 不报错 | ✓ VERIFIED | `service.py:75-146` 四 staticmethod + `test_service_fallback.py` 14 用例全绿 |
| 2 | `DurableTaskService` 与队列常量经 `durable.__init__` 暴露，业务侧无需 import procrastinate | ✓ VERIFIED | `__init__.py:14-34` curated re-export；`test_no_direct_import.py` 绿 |
| 3 | make dev / pytest 默认 SQLite 路径不引入 Procrastinate 依赖即可跑通 fallback | ✓ VERIFIED | `pytest tests/durable -q` → 31 passed, 8 deselected；fallback 经 `background_runner` |
| 4 | grep 守护断言除 backends/tasks/management 外业务代码无直接 import procrastinate | ✓ VERIFIED | `test_no_direct_import.py` rg 扫 server/ 过滤允许清单后断言空，绿 |
| 5 | `_use_procrastinate(engine, backend)` 唯一权威判定，service 与 settings 共用 | ✓ VERIFIED | `service.py:22-45` 纯函数；`settings.py:271,273` `from durable.service import _use_procrastinate` 复用同一函数；真值表 5 分支测试绿 |
| 6 | FRIDAY_PROCESS_ROLE=worker\|migrate 不跑 repositories/_reset_stuck_indexing、codegraph galaxy warm+orphan reconcile、resumable _schedule_recovery | ✓ VERIFIED | 三 `apps.py` 均 `should_run_startup_side_effects` 门禁；`test_process_role.py` worker 短路/web 执行用例绿 |
| 7 | role 短路记 info 日志（含 role+job），不静默 | ✓ VERIFIED | `roles.py:48` `startup_side_effect_skipped_by_role`；`test_skip_logs_info_with_role_and_job` 绿 |
| 8 | role=web（默认）仍执行三处 reconcile/sweep/startup（零回归）+ handler/backend 注册与 role 无关 | ✓ VERIFIED | `test_repositories/resumable/codegraph_web_*` + handler/backend 注册断言绿 |
| 9 | Postgres+procrastinate 下 defer 落 procrastinate_jobs（queue/priority/run_at），get/cancel 生效 | ⚠ HUMAN | `backends.py:215-295` 实现完整（configure+defer_async/list_jobs_async/cancel_job_by_id_async）；`test_procrastinate_backend.py` 4 用例需真实 PG |
| 10 | worker 经独立进程用 get_worker_connector()→PsycopgConnector 消费，绝不用 DjangoConnector，listen_notify=False 显式 | ✓ VERIFIED (code) / ⚠ HUMAN (runtime) | `run_worker.py:65-69` get_worker_connector+listen_notify=False；`run_worker --help` 成功；PsycopgConnector 断言用例需真实 PG |
| 11 | retry_stalled_durable_jobs 为 @app.periodic+@app.task(queueing_lock=) 单例，基于 heartbeat（不用 nb_seconds）扫 stalled 重投 | ✓ VERIFIED (code) / ⚠ HUMAN (runtime) | `tasks.py:35-65` 装饰器叠放+queueing_lock+get_stalled_jobs/retry_job；grep 确认零 `nb_seconds=` 调用；运行态需真实 PG |
| 12 | Postgres 专项 CI job（postgres:17-alpine service + postgres_queue marker）与 SQLite 默认共存 | ✓ VERIFIED (artifact) / ⚠ HUMAN (green run) | `ci.yaml` server-ci+postgres-queue 两 job；YAML 合法、镜像/marker/migrate 命中；实跑绿需推送 Actions |

**Score:** 12/12 truths code-verified；其中 4 项的真实 Postgres / E2E 运行态确认转 human_needed（实现已就位，SQLite 路径全绿）。

### Required Artifacts

| Artifact | Expected | Status | Details |
| -------- | -------- | ------ | ------- |
| `server/durable/service.py` | DurableTaskService + `_use_procrastinate` 唯一判定 | ✓ VERIFIED | 顶层零 settings 访问（防循环 import），方法体局部 import 隔离 |
| `server/durable/backends.py` | DurableBackend 协议 + InProcessBackend + ProcrastinateBackend（真实实现） | ✓ VERIFIED | ProcrastinateBackend 四方法落地，无 NotImplementedError；procrastinate 仅此模块直 import |
| `server/durable/queues.py` | 5 队列常量 + ALL_QUEUES | ✓ VERIFIED | QUEUE_INDEX/GRAPH/CRAWL_INGEST/PAGE_INDEX/MAINTENANCE，ALL_QUEUES len=5 |
| `server/durable/roles.py` | current_role + should_run_startup_side_effects | ✓ VERIFIED | 独立读 env、零 Django 依赖 |
| `server/durable/__init__.py` | curated re-export | ✓ VERIFIED | DurableTaskService + 队列常量 |
| `server/durable/tasks.py` | retry_stalled_durable_jobs periodic + durable_ping | ✓ VERIFIED | @app.periodic+queueing_lock+pass_context |
| `server/durable/management/commands/run_worker.py` | 独立 worker 命令 | ✓ VERIFIED | get_worker_connector + listen_notify=False；非 PG CommandError |
| `server/{repositories,codegraph,resumable}/apps.py` | role 门禁三处启动副作用 | ✓ VERIFIED | 各 import 并调用 should_run_startup_side_effects；argv 兜底保留 |
| `server/friday/settings.py` | 条件注册 procrastinate.contrib.django | ✓ VERIFIED | `:273-274` 仅 `_use_procrastinate` 为真才 append；SQLite 不注册 |
| `server/pyproject.toml` | procrastinate[django]>=3.8.1,<3.9 + postgres_queue marker | ✓ VERIFIED | `:80` 依赖（实装 3.8.1）；`:111` addopts 排除；`:119` marker 注册 |
| `.github/workflows/ci.yaml` | server-ci + postgres-queue 两 job | ✓ VERIFIED | postgres:17-alpine + pg_isready + migrate + -m postgres_queue --allow-hosts |

### Key Link Verification

| From | To | Via | Status |
| ---- | -- | --- | ------ |
| service.py | backends.py | 方法体局部 import in_process_backend/procrastinate_backend | ✓ WIRED |
| backends.py (InProcess) | services.background_runner | run_in_background(factory, name) | ✓ WIRED (`:24,123`) |
| backends.py (Procrastinate) | procrastinate.contrib.django.app | configure().defer_async / job_manager | ✓ WIRED (`:226,243,245`) |
| tasks.py | app.job_manager.get_stalled_jobs/retry_job | periodic rescue | ✓ WIRED (`:54,57`) |
| apps.py (DurableConfig.ready) | durable.tasks | 条件 import 触发 @app.task 注册 | ✓ WIRED (`:37`) |
| 三处 *.apps | durable.roles.should_run_startup_side_effects | ready() 调度前判 role | ✓ WIRED |
| settings.py | durable.service._use_procrastinate | 条件注册复用同一判定 | ✓ WIRED (`:271,273`) |
| ci.yaml postgres-queue | test_procrastinate_backend/test_stalled_rescue | pytest -m postgres_queue | ✓ WIRED |

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
| -------- | ------- | ------ | ------ |
| durable 测试套件（SQLite 默认） | `uv run pytest tests/durable -q` | 31 passed, 8 deselected | ✓ PASS |
| procrastinate 依赖落地 | `python -c "import procrastinate; print(__version__)"` | 3.8.1 | ✓ PASS |
| run_worker 命令注册 | `manage.py run_worker --help` | 帮助输出，exit 0 | ✓ PASS |
| postgres_queue 用例可收集 | `pytest -m postgres_queue --co -q` | 8/5981 collected | ✓ PASS |
| postgres_queue 默认排除 | 默认 `pytest tests/durable` | 8 deselected | ✓ PASS |

### Requirements Coverage

| Requirement | Source Plan | Status | Evidence |
| ----------- | ----------- | ------ | -------- |
| DURABLE-01 | 60-01, 60-03 | ✓ SATISFIED (code) | DurableTaskService 适配层 + InProcess fallback + ProcrastinateBackend + run_worker；no-direct-import 守护绿 |
| DURABLE-02 | 60-02 | ✓ SATISFIED | FRIDAY_PROCESS_ROLE 门禁三处 apps.py；test_process_role.py 16 用例绿 |
| DURABLE-03 | 60-03 | ✓ SATISFIED (code) | retry_stalled_durable_jobs @app.periodic+queueing_lock 单例，heartbeat 判定；运行态需真实 PG |
| DURABLE-04 | 60-04 | ✓ SATISFIED (artifact) | ci.yaml postgres:17-alpine service + postgres_queue marker 分层；实跑绿需推送 |

无 orphaned requirements：REQUIREMENTS.md 映射 Phase 60 的 DURABLE-01..04 全部被各 plan `requirements` 字段认领。

### Anti-Patterns Found

| File | Pattern | Severity | Impact |
| ---- | ------- | -------- | ------ |
| — | 无 TODO/FIXME/XXX/TBD debt marker | ℹ️ Info | durable 全模块零未引用债务标记 |
| — | 无 NotImplementedError（ProcrastinateBackend stub 已被真实实现替换） | ℹ️ Info | 符合 60-03 acceptance |
| — | `nb_seconds` 仅出现在注释（"绝不传"），无实际调用 | ℹ️ Info | 符合"慢≠死" heartbeat 判定约束 |

### Human Verification Required

详见 frontmatter `human_verification`。四项均为运行态/E2E 确认，实现代码已就位且 SQLite 路径全绿：

1. **postgres_queue 后端测试实跑** — 需真实 Postgres，本机仅能 collect 8 项后 skip。
2. **forged-heartbeat stalled rescue** — 依赖 procrastinate_workers/jobs 表与 SKIP LOCKED。
3. **真实 kill-worker E2E** — 60-VALIDATION.md 已标 Manual-Only（双活 worker + 等心跳过期）。
4. **GitHub Actions postgres-queue job 绿灯** — YAML 合法，需推送由 Actions runner 实跑。

### Gaps Summary

无 gap。Phase 60 目标在代码层完整达成：`DurableTaskService` 适配层隔离队列实现、`_use_procrastinate` 唯一权威判定（service/settings 共用，无重复判据）、SQLite in-process fallback 开箱即用、FRIDAY_PROCESS_ROLE 门禁收口三处启动副作用、Procrastinate 后端 + 独立 worker（get_worker_connector + listen_notify=False）+ 周期 queueing_lock 单例 rescue（heartbeat 判定）、Postgres 专项 CI 双 job 分层均已落地，no-direct-import 守护与进程角色守护测试全绿（31 passed）。剩余四项为真实 Postgres / 真实 kill-worker / Actions 实跑的运行态确认，按既定约束（实现就位 + SQLite 绿）归为 human_needed 而非 gap。

---

_Verified: 2026-06-20T02:40:00Z_
_Verifier: Claude (gsd-verifier)_
