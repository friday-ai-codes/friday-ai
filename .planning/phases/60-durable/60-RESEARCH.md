# Phase 60: durable 底座地基 - Research

**Researched:** 2026-06-20
**Domain:** Postgres-backed durable task queue（Procrastinate 3.8.1）+ Django 进程角色门禁 + leader 单例周期 rescue
**Confidence:** HIGH（核心 API 经官方文档 + changelog 核实；本仓版本已核对 `uv.lock`）

## Summary

本阶段是 v0.12.0 的地基：在不迁移任何现有业务任务的前提下，立起一个 **`DurableTaskService` 适配层**（业务代码永不直接 import Procrastinate）、**`FRIDAY_PROCESS_ROLE` 进程角色门禁**（收口三处 `AppConfig.ready()` 启动副作用）、**一条最小可验证的 stalled rescue 闭环**（`queueing_lock` 单例 leader 周期重投），以及 **Postgres 专项 CI**。

研究确认前置 PoC 结论与本仓实际版本一致：`uv.lock` 已锁 **Django 6.0.1 / psycopg 3.3.2 / Python ≥3.14**，与 PoC（Django 6.0 / psycopg 3.3 / Python 3.14）吻合；**Procrastinate 尚未进 `pyproject.toml`/`uv.lock`，本阶段需新增 `procrastinate[django]>=3.8.1,<3.9`**。Procrastinate 3.8.1（2026-04-08 发布）已含 worker heartbeat（3.1.0 引入）+ `JobManager.get_stalled_jobs(seconds_since_heartbeat=…)` + `retry_job()`，与 DURABLE-03 直接对应。Django 集成（`procrastinate.contrib.django`）通过 Django migrations 建表、`./manage.py procrastinate worker` 跑独立 worker（内部用 `get_worker_connector()` 生成异步 psycopg 连接器），三条硬前置全部可落地。

发现一处**与 CONTEXT 描述偏差但不影响范围**的事实：`.github/workflows/` 目录当前为空——**仓库没有任何现成 CI workflow**，DURABLE-04 的 Postgres CI 必须从零新建 GH Actions workflow 文件，而非"在既有 ci.yaml 上加 job"。

**Primary recommendation:** 新建 `server/durable/` app（镜像 `server/resumable/` 结构）；把 `procrastinate.contrib.django` 加进 `INSTALLED_APPS`（置于业务 app 之前）；`DurableTaskService` 用 `app.configure_task(name=…, queue=, priority=, queueing_lock=idempotency_key, schedule_at=run_at).defer_async(**payload)` 做后端无关入队；Postgres 且 `DURABLE_TASK_BACKEND=procrastinate` 走 Procrastinate，否则走 `background_runner` 包装的 in-process fallback；周期 `retry_stalled_durable_jobs` 用 `@app.periodic(cron=…)` + `@app.task(queueing_lock="retry_stalled_durable_jobs")`，并**必须捕获 `UniqueViolation`/`AlreadyEnqueued`**（已知 upstream 坑 #1446）。

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

**队列后端与适配层（DURABLE-01）**
- 采用 **Procrastinate 3.8.1**，藏在 `DurableTaskService` 适配层后；业务代码绝不直接 import Procrastinate。
- 后端选择点：`DATABASE_URL` 为 Postgres 且 `DURABLE_TASK_BACKEND=procrastinate` → Procrastinate；否则 → in-process 非 durable fallback。SQLite/无 `DATABASE_URL` 永远 fallback（dev 开箱即用，`make dev`/pytest 不需 Postgres）。
- 统一接口签名：`defer(task, payload, *, queue, priority, idempotency_key, run_at) / get / cancel / retry_stalled`。
- worker 必须**独立进程**：用 `get_worker_connector()` / 官方 management command，绝不直接拿 `DjangoConnector` 跑 worker（PoC 硬前置①）。
- 先 `listen_notify=False` polling（低延迟唤醒留 v2 DURABLEX-01）。
- 一个底座、多条逻辑队列（index/graph/crawl_ingest/page_index/maintenance），本阶段先定义队列命名常量，实际接入由后续阶段消费。

**进程角色门禁（DURABLE-02）**
- 新增 `FRIDAY_PROCESS_ROLE` 环境变量（默认 `web`，保持既有单进程部署零回归）。
- 收口 `repositories.apps` / `codegraph.apps` / `resumable.apps` 三处 `AppConfig.ready()` 的启动副作用：仅 `role in {web}`（或显式允许集）才执行 reconcile/sweep/startup jobs；worker/migrate/test 角色短路跳过。
- 收口必须先于 Phase 61 迁移（PoC 硬前置③）。
- 短路时记一条 info 级日志（角色 + 跳过的 job 名），不静默。

**周期 rescue 与 leader 单例（DURABLE-03）**
- 内置 `retry_stalled_durable_jobs` 周期任务，调 `get_stalled_jobs()` + `retry_job()`。
- 经 Procrastinate `queueing_lock` 实现单例 leader：多副本下只有一个 leader 执行周期 rescue 与单例 cron。
- 弃用 `runapscheduler` 的本地 `flock`。
- rescue 仅对真正 stalled（超租约/心跳）的 job 重投；执行语义明确 **at-least-once，不承诺 exactly-once**。

**测试与 CI（DURABLE-04）**
- 新增 pytest `postgres_queue` marker；标记的测试需真实 Postgres（GH Actions service container `postgres:17-alpine`）。
- 默认 job 仍走 SQLite（marker 分层，不强制本地装 Postgres）。
- Postgres CI 覆盖：defer / priority / retry-backoff / stalled rescue / 并发 worker 竞争 / SQLite fallback 退化路径。
- 复用 `server/tests/conftest.py` 既有 adrf monkeypatch + pytest-socket 约束。

### Claude's Discretion
- `DurableTaskService` 的具体模块落点（建议新建 `server/durable/` app，镜像 `server/resumable/` 结构：`service.py` / `apps.py` / `tasks.py` / `management/`）。
- 队列名常量、idempotency_key 冲突时的语义（Procrastinate `queueing_lock` vs 业务级 dedup）的精确实现。
- fallback in-process executor 的线程模型（建议复用 `server/services/background_runner.py` 既有 daemon-thread runner）。
- Procrastinate app/connector 的 Django settings 装配方式与 migration 注入顺序。

### Deferred Ideas (OUT OF SCOPE)
- `listen_notify=True` 低延迟唤醒 → v2 DURABLEX-01。
- exactly-once 语义 → 显式非目标。
- 迁移现有 index/graph/crawl 任务 → Phase 61/62。
- 部署硬化（优雅终止 / compose·helm 拆 workload / KEDA / PDB）→ Phase 63。
- 外部副作用 fencing/outbox → Phase 63（IDEMP-02）。
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| DURABLE-01 | `DurableTaskService` 适配层隔离队列实现（Postgres→Procrastinate 3.8.1 / SQLite→in-process fallback），统一接口 `defer/get/cancel/retry_stalled`（含 idempotency_key + queue/priority/run_at），worker 独立进程 | 见 §Standard Stack（procrastinate 装配）、§Architecture Patterns Pattern 1/2（适配层 + 后端选择）、§Code Examples（defer/configure_task 映射） |
| DURABLE-02 | `FRIDAY_PROCESS_ROLE=web\|worker\|scheduler\|migrate\|test` 进程角色门禁，收口三处 `AppConfig.ready()` 启动副作用 | 见 §Architecture Patterns Pattern 3（角色门禁 helper）、§Runtime State Inventory（三处 side-effect 清单）、§Code Examples |
| DURABLE-03 | 内置 `retry_stalled_durable_jobs` 周期任务，经 `queueing_lock` 单例 leader 调 `get_stalled_jobs()` + `retry_job()` | 见 §Standard Stack（periodic/queueing_lock）、§Common Pitfalls P-1（UniqueViolation）、§Code Examples |
| DURABLE-04 | Postgres 专项 CI（GH Actions `postgres:17-alpine` + `postgres_queue` marker），覆盖 defer/priority/retry-backoff/stalled rescue/并发 worker/SQLite fallback | 见 §Validation Architecture、§Environment Availability（无现成 CI workflow）、§Code Examples（marker + service container） |
</phase_requirements>

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| 任务入队 / 查询 / 取消（`defer/get/cancel`） | API / 后端 service 层 | Database（Postgres `procrastinate_jobs` 表 / SQLite fallback 内存） | 业务代码经适配层调用，状态真相源在 DB；与 `resumable` 同层 |
| durable job 执行（worker） | 独立 worker 进程 | Database（领取/心跳/终态） | PoC 硬前置①：worker 必须独立进程，不与 web 同进程 |
| 周期 stalled rescue / leader 选主 | scheduler/worker 进程（leader 单例） | Database（`queueing_lock` 去重 + `worker_heartbeats` 表） | DB leader 跨 Pod 有效，替代单机 flock |
| 进程角色门禁（启动副作用收口） | 各 `AppConfig.ready()`（进程级） | — | 进程职责由 `FRIDAY_PROCESS_ROLE` 决定，web-only 副作用不应在 worker/migrate 跑 |
| in-process fallback 执行 | web 进程内 daemon 线程（`background_runner`） | — | SQLite/dev 无 durable 保证，复用既有常驻 loop |
| Postgres 专项测试 | CI（GH Actions service container） | — | marker 分层，默认 SQLite 路径不受影响 |

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| `procrastinate[django]` | `>=3.8.1,<3.9` | Postgres-only durable 任务队列 + Django 原生集成 | PoC 已锁定；Postgres-only 契合"已有 Postgres、不引重运维组件"核心价值 [CITED: procrastinate.readthedocs.io] |
| `psycopg[binary]` | `3.3.2`（已装） | worker 异步连接器底座（`get_worker_connector()` 优先选 psycopg3） | 已在 `uv.lock`；Procrastinate worker 需要 psycopg3 或 aiopg [VERIFIED: uv.lock + 官方 commit abb121b] |
| `django` | `6.0.1`（已装） | Web 框架 + migrations（Procrastinate 复用 Django migrations 建表） | 已在 `uv.lock`，与 PoC Django 6.0 一致 [VERIFIED: uv.lock] |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| `services.background_runner`（本仓既有） | — | in-process 非 durable fallback 的 daemon-thread 执行器 | SQLite/无 `DATABASE_URL` 时 `DurableTaskService` 退化路径 |
| `structlog`（已装） | `>=25.5.0` | 结构化日志（角色短路 info、rescue 计数、worker 事件） | 全程 |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| Procrastinate | Celery / RQ / Temporal / Kafka | **Out of Scope（REQUIREMENTS 明令禁止）**：违背"开箱即用、自托管"；需额外 broker/运维组件 |
| `queueing_lock` 单例 leader | Redis `SET NX`（既有 `resumable/locks.py`）/ APScheduler flock | flock 仅单机有效（CONTEXT 明确弃用）；Redis 锁需额外依赖。`queueing_lock` 纯 DB、跨 Pod 有效、与 Procrastinate 原生集成 |
| `get_worker_connector()` / `manage.py procrastinate worker` | 直接拿 `DjangoConnector` 跑 worker | **PoC 硬前置①禁止**：`DjangoConnector` 是同步连接，不适合 worker 异步循环；官方明确不可用 [CITED: procrastinate.readthedocs.io/howto/django/scripts] |

**Installation:**
```bash
# server/ 目录下
uv add 'procrastinate[django]>=3.8.1,<3.9'
```

**Version verification:** Procrastinate 3.8.1 发布于 2026-04-08（changelog 核实存在）[CITED: procrastinate.readthedocs.io/changelog]。`procrastinate[django]` extra 拉入 Django 集成依赖；worker 异步连接器复用本仓已装 `psycopg[binary]==3.3.2`。本阶段执行时应运行 `uv add` 后核对 `uv.lock` 实锁版本落在 `>=3.8.1,<3.9`。

## Package Legitimacy Audit

> 本阶段仅新增 1 个外部包。研究环境网络受限（pip/PyPI 探测被沙箱拦截，shell 无法直连），slopcheck 未运行 → 按协议把该包标 `[ASSUMED]`，planner 应在 install 前加一个 `checkpoint:human-verify` 确认。但下列辅证强烈支持其合法性。

| Package | Registry | Age | Downloads | Source Repo | slopcheck | Disposition |
|---------|----------|-----|-----------|-------------|-----------|-------------|
| `procrastinate` | PyPI | 多年（3.8.1 @ 2026-04-08，3.1.0 @ 2025-03-22） | 高（成熟项目，~1K GitHub stars） | github.com/procrastinate-org/procrastinate | 未运行（沙箱无网络） | Approved（辅证充分）；planner 加 human-verify |

**辅证（非 slopcheck）：** 官方 ReadTheDocs 文档站、GitHub `procrastinate-org/procrastinate`、PoC 已实测 PASS、`pip install 'procrastinate[django]'` 为官方安装指令。`[django]` extra 与 `psycopg`/`aiopg` 可选连接器均见官方 commit/PR（#919/#960/#1344）。

**Packages removed due to slopcheck [SLOP] verdict:** none
**Packages flagged as suspicious [SUS]:** none

*slopcheck 在研究环境不可用，故 planner 应在新增 `procrastinate` 的 install 任务前加 `checkpoint:human-verify`（确认 PyPI 包名与版本），install 后 `./manage.py procrastinate healthchecks` 验证装配。*

## Architecture Patterns

### System Architecture Diagram

```
                         ┌──────────────────────────────────────────────┐
  业务代码（views/        │   DurableTaskService（server/durable/service） │  ← 唯一对外入口
  tasks/handlers，        │   defer / get / cancel / retry_stalled         │     业务永不 import procrastinate
  Phase 61+ 消费）────────▶   + 队列常量 DurableQueue / 后端选择 _backend() │
                         └───────────────┬───────────────┬──────────────┘
                                         │               │
                  DATABASE_URL=postgres  │               │  SQLite / 无 DATABASE_URL
                  且 DURABLE_TASK_BACKEND │               │  （永远 fallback）
                  =procrastinate         ▼               ▼
                  ┌──────────────────────────┐   ┌──────────────────────────────┐
                  │ Procrastinate App        │   │ InProcessBackend              │
                  │ procrastinate.contrib.   │   │ 包 services.background_runner │
                  │ django.app               │   │ (daemon-thread loop)          │
                  │ .configure_task(...)     │   │ run_in_background(factory)     │
                  │ .defer_async(**payload)  │   │ 非 durable：进程死即丢         │
                  └────────────┬─────────────┘   └──────────────────────────────┘
                               │ INSERT procrastinate_jobs (status=todo)
                               ▼
                  ┌─────────────────────────────────────────────┐
                  │ Postgres: procrastinate_jobs / _events /     │  ← 状态真相源
                  │ worker_heartbeats / periodic_defers          │
                  └────────────┬───────────────────┬─────────────┘
       领取/心跳/终态           │                   │  get_stalled_jobs() + retry_job()
                               ▼                   ▼
        ┌───────────────────────────────┐   ┌─────────────────────────────────────┐
        │ worker 进程（独立）            │   │ leader 单例（scheduler/worker 进程） │
        │ ./manage.py procrastinate      │   │ @app.periodic(cron) +                │
        │ worker --queues=index,graph... │   │ @app.task(queueing_lock=             │
        │ FRIDAY_PROCESS_ROLE=worker     │   │   "retry_stalled_durable_jobs")      │
        │ heartbeat 每 10s               │   │ → 多副本只有一个 leader 重投 stalled │
        └───────────────────────────────┘   └─────────────────────────────────────┘

  进程角色门禁（横切，进程启动时）：
  FRIDAY_PROCESS_ROLE ∈ {web, worker, scheduler, migrate, test}
  → repositories.apps / codegraph.apps / resumable.apps 的 ready() 仅 role∈允许集才跑副作用
```

### Recommended Project Structure
```
server/durable/                      # 新建 app，镜像 server/resumable/ 结构
├── __init__.py
├── apps.py                          # DurableConfig.ready()：注册 PROCRASTINATE_ON_APP_READY 产物 / 角色门禁不在此
├── app.py 或 procrastinate.py       # PROCRASTINATE_ON_APP_READY 目标（on_app_ready，可选）
├── service.py                       # DurableTaskService（对外唯一入口）+ DurableQueue 常量
├── backends.py                      # _ProcrastinateBackend / _InProcessBackend + 后端选择 select_backend()
├── tasks.py                         # @app.task 注册点（含 retry_stalled_durable_jobs 周期任务）
├── roles.py                         # FRIDAY_PROCESS_ROLE 解析 + should_run_startup_jobs(role) 门禁 helper
└── management/commands/
    └── (复用官方 manage.py procrastinate worker，无需自写 worker 命令)

server/friday/settings.py            # +procrastinate.contrib.django 进 INSTALLED_APPS；+PROCRASTINATE_* / DURABLE_* / FRIDAY_PROCESS_ROLE
server/repositories/apps.py          # 收口 _reset_stuck_indexing 于角色门禁
server/codegraph/apps.py             # 收口 galaxy warm + orphan graph reconcile 于角色门禁
server/resumable/apps.py             # 收口 _schedule_recovery 于角色门禁
.github/workflows/ci.yaml            # 新建（当前不存在）：含 SQLite 默认 job + Postgres service container job
```

### Pattern 1：适配层 + 后端无关入队（DURABLE-01）
**What:** `DurableTaskService` 暴露 `defer/get/cancel/retry_stalled`，内部按后端分派。Procrastinate 路径用 **`app.configure_task(name=…)`**（按 task name 入队，无需 import 具体 task 对象——天然满足"业务代码不直接 import Procrastinate"）。
**When to use:** 所有业务入队点（本阶段仅定义，Phase 61+ 消费）。
**统一接口 → Procrastinate 参数映射（关键决策）：**

| 适配层参数 | Procrastinate 映射 | 说明 |
|-----------|-------------------|------|
| `task`（str 名） | `configure_task(name=...)` | 用注册的 task 全名，如 `"durable.index_repo"` |
| `payload`（dict） | `.defer_async(**payload)` | 作为 task kwargs |
| `queue` | `configure_task(queue=...)` | 逻辑队列名（见 DurableQueue 常量） |
| `priority` | `configure_task(priority=...)` | int，越大越优先，默认 0 |
| `idempotency_key` | `configure_task(queueing_lock=...)` | **关键**：`queueing_lock` 保证 `todo` 态同 key 只一行；defer 冲突抛 `AlreadyEnqueued` |
| `run_at`（datetime） | `configure_task(schedule_at=...)` | 延迟执行；与 `schedule_in` 互斥 |

**Example:**
```python
# Source: procrastinate.readthedocs.io/howto/basics/defer + tasks.py ConfigureTaskOptions
from procrastinate.contrib.django import app
from procrastinate import exceptions

async def _defer_procrastinate(task, payload, *, queue, priority, idempotency_key, run_at):
    deferrer = app.configure_task(
        name=task,
        queue=queue,
        priority=priority,
        queueing_lock=idempotency_key,  # idempotency_key → queueing_lock
        schedule_at=run_at,
    )
    try:
        return await deferrer.defer_async(**payload)
    except exceptions.AlreadyEnqueued:
        # 幂等：同 key 已在 todo，视为成功（已有一份在排队）
        return None
```

### Pattern 2：后端选择点（DURABLE-01）
**What:** 启动期一次性判定后端，避免每次 defer 重复判断。
**When to use:** `DurableTaskService` 初始化 / 模块级单例。
**Example:**
```python
# Source: 本仓 settings.py:244 DATABASES 解析 + CONTEXT 决策
from django.conf import settings

def select_backend() -> str:
    engine = settings.DATABASES["default"]["ENGINE"]
    is_postgres = "postgresql" in engine  # django.db.backends.postgresql
    backend = settings.DURABLE_TASK_BACKEND  # env: "procrastinate" | "inprocess"
    if is_postgres and backend == "procrastinate":
        return "procrastinate"
    return "inprocess"  # SQLite / 无 DATABASE_URL 永远 fallback
```

### Pattern 3：进程角色门禁（DURABLE-02）
**What:** 单一 helper 判定当前进程是否应执行某 web-only 启动副作用，三处 `AppConfig.ready()` 统一调用。
**When to use:** `repositories/codegraph/resumable` 三处 `ready()` 内的 reconcile/sweep/startup-jobs 之前。
**Example:**
```python
# Source: 镜像 resumable/apps.py 既有 argv guard，叠加 FRIDAY_PROCESS_ROLE
import os
import structlog

logger = structlog.get_logger(__name__)

_STARTUP_JOB_ROLES = {"web"}  # 仅 web 跑 web-only 副作用；默认 role=web 零回归

def current_process_role() -> str:
    return os.environ.get("FRIDAY_PROCESS_ROLE", "web").strip().lower() or "web"

def should_run_startup_jobs(job_name: str, *, allowed=_STARTUP_JOB_ROLES) -> bool:
    role = current_process_role()
    if role in allowed:
        return True
    logger.info("startup_job_skipped_by_role", role=role, job=job_name)  # 不静默
    return False
```
**接入示例（repositories/apps.py）：**
```python
def ready(self) -> None:
    from durable.roles import should_run_startup_jobs
    if not should_run_startup_jobs("reset_stuck_indexing"):
        return
    thread = threading.Thread(target=self._reset_stuck_indexing, daemon=True)
    thread.start(); thread.join(timeout=5)
```

### Anti-Patterns to Avoid
- **业务代码 `from procrastinate... import` / 直接 `my_task.defer()`：** 违背适配层隔离。一律经 `DurableTaskService` + `configure_task(name=…)`。grep 守护：除 `server/durable/` 外不得出现 `import procrastinate`。
- **直接用 `DjangoConnector` 跑 worker：** PoC 硬前置①禁止。worker 必须 `./manage.py procrastinate worker`。
- **`retry_stalled_durable_jobs` 自身设 `lock`：** 会导致一个 stalled 的 rescue 任务永久阻塞所有解救（issue #1446）。只用 `queueing_lock`，不设 `lock`。
- **rescue 时用废弃的 `get_stalled_jobs(nb_seconds=…)`：** 该参数已 deprecated（基于 started_at，会误判"慢≠死"）。用默认的 `seconds_since_heartbeat`（基于 worker 心跳）。
- **角色门禁默认非 web：** 必须默认 `web`，否则现有单进程部署升级即回归（不再跑 reconcile）。

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| 多副本竞争领取、租约心跳、stalled 检测 | 自写 DB CAS claim + heartbeat 表（如 `resumable` 那套） | Procrastinate `procrastinate_jobs` + `worker_heartbeats` + `get_stalled_jobs()` | Procrastinate 已内置 SKIP LOCKED 领取 + 心跳；本阶段正是把自研 lease 让位给它 |
| leader 单例选主 | flock / 自写 Redis 锁 | `@app.task(queueing_lock="…")` | `queueing_lock` 纯 DB、跨 Pod、原生集成（CONTEXT 锁定） |
| 周期任务调度 | 自写 sleep-loop / 复用 APScheduler | `@app.periodic(cron="…")` | Procrastinate periodic 由 worker 进程驱动，落 `procrastinate_periodic_defers` 表，多副本去重 |
| 失败重试退避 | 自写 attempt 计数 + sleep | Procrastinate retry strategy（`@app.task(retry=…)` / `get_retry_decision`） | 内置 `retry_in/retry_at` + 指数退避，job 等待态存 DB 跨重启幸存 |
| 任务表 migration | 手写 SQL | Django migrations（`procrastinate.contrib.django` 自带） | `manage.py procrastinate schema` 在 Django 下不可用，迁移走 `migrate` |

**Key insight:** 本阶段的价值正是"**不再自研** durable 机制"——把 `resumable/` 的 lease/CAS/heartbeat 自研逻辑让位给 Procrastinate 的成熟实现，适配层只做"接口稳定 + 后端隔离 + 后端选择"。

## Runtime State Inventory

> 本阶段非 rename/migration，但 DURABLE-02 的核心是**收口启动副作用**——下表逐一登记三处 `AppConfig.ready()` 现有副作用（门禁对象），是 planner 必须覆盖的清单。

| 文件 | 启动副作用 | 现有 guard | 门禁后应 |
|------|-----------|-----------|---------|
| `repositories/apps.py` `RepositoriesConfig.ready()` | `_reset_stuck_indexing`：把 `INDEXING` 仓库 + RUNNING `IndexHistory` 标 FAILED（启动同步线程，join 5s） | 无 argv/role guard（**裸跑**） | 仅 `role∈{web}` 跑；worker/migrate 短路 + info 日志 |
| `codegraph/apps.py` `CodegraphConfig.ready()` | ① volar/gopls backend 注册（纯内存，**应保留不门禁**）；② `_schedule_galaxy_cache_warm`（daemon 线程 sleep 5s 预热）；③ `_schedule_orphan_graph_build_reconcile`（daemon 线程回收孤儿 RUNNING GraphBuildHistory） | ②③有 argv guard（pytest/runserver RUN_MAIN/管理命令跳过），**无 role guard** | ②③仅 `role∈{web}` 跑；①backend 注册保留（worker 执行 graph 任务也需要 extractor backend——**注意：planner 需判定 worker 是否需要 backend 注册，建议保留**） |
| `resumable/apps.py` `ResumableConfig.ready()` | ① `register_default_handlers`（纯注册，**应保留**）；② `_schedule_recovery`（daemon 线程多次补扫续跑 ResumableTask） | ②有 argv guard（pytest/runserver/管理命令跳过），**无 role guard** | ②仅 `role∈{web}` 跑；①handler 注册保留 |

**关键判定（planner 必须决策）：** 哪些副作用是"web-only reconcile/sweep"（需门禁）vs"任何进程都需要的注册"（不门禁）。建议：**reconcile/sweep/warm/startup-recovery 门禁；extractor backend 注册 + resumable handler 注册保留**（worker 跑实际任务时仍需它们）。CONTEXT 明确门禁对象是"reconcile/sweep/startup jobs"，不含纯注册。

**其他类别（greenfield，无遗留运行态）：**
- Stored data：本阶段不迁移任何 `resumable_tasks` 数据（Phase 61 才做）。Procrastinate 表由 migration 新建，无存量。**None — 不迁移。**
- Live service config / OS-registered state：本阶段不动 compose/helm/scheduler workload（Phase 63）。`runapscheduler` 的 flock 本阶段**不删除**——只新增 `queueing_lock` 周期 rescue，flock 的整体弃用随 Phase 63 scheduler workload 拆分落地。**None — 不动。**
- Secrets/env vars：新增 `FRIDAY_PROCESS_ROLE` / `DURABLE_TASK_BACKEND` / `PROCRASTINATE_*` 均为新键，无重命名。**None。**

## Common Pitfalls

### Pitfall 1：`retry_stalled_jobs` 在带 queueing_lock 的 job 上抛 UniqueViolation
**What goes wrong:** 周期 rescue 调 `retry_job(job)` 把 stalled job 重置为 `todo`；若该 job 带 `queueing_lock` 且同 key 已有另一 `todo` 行，会抛 `UniqueViolation`，导致整轮 rescue 中断、后续 stalled job 永不解救。
**Why it happens:** upstream 已知问题 [CITED: github.com/procrastinate-org/procrastinate/issues/1446]。`queueing_lock` 约束 `todo` 态唯一。
**How to avoid:** rescue 循环对每个 job `try/except UniqueViolation`——命中则 `finish_job(job, Status.FAILED, …)`（或忽略，因已有一份在排队）；逐 job 隔离，单个失败不中断整轮。
**Warning signs:** rescue 任务日志出现 UniqueViolation traceback；stalled job 一直不被重投。

### Pitfall 2：用废弃 `nb_seconds` 参数检测 stalled（"慢≠死"误判）
**What goes wrong:** `get_stalled_jobs(nb_seconds=N)` 按 `doing` 持续时长判定，长任务（索引）超 N 秒即被误判 stalled 重投 → 重复执行。
**Why it happens:** 旧 API（基于 started_at）；新机制基于 worker 心跳。
**How to avoid:** 用默认 `get_stalled_jobs(seconds_since_heartbeat=30)`（不传 `nb_seconds`），仅当 worker 心跳真停才判 stalled。与 worker 的 `update_heartbeat_interval=10`（默认）/ `stalled_worker_timeout=30`（默认）配套。
**Warning signs:** 长任务被反复重投；rescue 误杀活跃 worker 的任务。

### Pitfall 3：worker 用 DjangoConnector 直接跑 → 异步连接报错
**What goes wrong:** 直接 `app.run_worker()` 用默认 `DjangoConnector`（同步）报错或无法领取。
**How to avoid:** 用官方 `./manage.py procrastinate worker`（内部自动 `replace_connector(get_worker_connector())`）；若自写脚本需显式 `with app.replace_connector(app.connector.get_worker_connector()): app.run_worker()`。本阶段优先用官方命令。
**Warning signs:** worker 启动即报"connector not suitable"/同步连接异常。

### Pitfall 4：Procrastinate models 默认 readonly，测试写不进
**What goes wrong:** 集成测试想直接写 `ProcrastinateJob` 或 defer 后断言时，因 `PROCRASTINATE_READONLY_MODELS=True`（默认）写入被拒。
**How to avoid:** 单元测试用 `InMemoryConnector`（不碰 DB）；需写 model 的测试用 pytest-django `settings` fixture 设 `settings.PROCRASTINATE_READONLY_MODELS = False`。[CITED: procrastinate.readthedocs.io/howto/django/tests]
**Warning signs:** 测试中 model.save() 报 readonly。

### Pitfall 5：`procrastinate.contrib.django` 在 INSTALLED_APPS 顺序错误
**What goes wrong:** 放在业务 app 之后，app/连接器尚未就绪时业务 `ready()` 已尝试用它。
**How to avoid:** 放在 INSTALLED_APPS **业务 app 之前**（官方建议）。本阶段不在 `ready()` 里 defer 任务（仅注册），风险低，但仍按官方顺序放置。

### Pitfall 6：迁移注入与 SQLite 路径
**What goes wrong:** 加了 `procrastinate.contrib.django` 后，SQLite dev/pytest 跑 `migrate` 会尝试建 Procrastinate 表，而其 migration 含 Postgres 专属 SQL（函数/类型）→ 在 SQLite 上失败。
**How to avoid:** 研究待确认项（见 Open Questions Q1）。候选方案：(a) 仅当 Postgres 后端时把 `procrastinate.contrib.django` 加进 INSTALLED_APPS（settings 条件装配）；(b) 用 migration router 让 procrastinate 的 migration 仅在 Postgres 上 apply。**强烈建议**用 (a)：`if select_backend()=="procrastinate": INSTALLED_APPS += ["procrastinate.contrib.django"]`，SQLite/pytest 默认不装 → fallback 路径零 Procrastinate 依赖，pytest 默认 SQLite 不建 Procrastinate 表（与"默认 job 仍走 SQLite"一致）。
**Warning signs:** SQLite `migrate` 报未知函数/类型；pytest collection 期 DB 建表失败。

## Code Examples

### 周期 stalled rescue 任务（DURABLE-03，含坑 #1446 防御）
```python
# Source: procrastinate.readthedocs.io/howto/production/retry_stalled_jobs + issue #1446 workaround
# server/durable/tasks.py
from procrastinate.contrib.django import app
from procrastinate.jobs import Status
from procrastinate import exceptions
import structlog

logger = structlog.get_logger(__name__)

@app.periodic(cron="*/2 * * * *")  # 每 2 分钟；listen_notify=False polling
@app.task(queueing_lock="retry_stalled_durable_jobs")  # 单例 leader，绝不设 lock
async def retry_stalled_durable_jobs(timestamp: int) -> None:
    stalled = await app.job_manager.get_stalled_jobs()  # 默认 seconds_since_heartbeat=30
    recovered = 0
    for job in stalled:
        try:
            await app.job_manager.retry_job(job)
            recovered += 1
        except exceptions.UniqueViolation:
            # 同 queueing_lock 已有 todo 行：放弃重投，标失败避免永久 stalled（坑 #1446）
            await app.job_manager.finish_job(job, status=Status.FAILED)
    if recovered:
        logger.info("durable_stalled_rescued", recovered=recovered)
```

### worker 启动（独立进程，PoC 硬前置①）
```bash
# 官方命令内部自动 replace_connector(get_worker_connector())；多队列、polling
FRIDAY_PROCESS_ROLE=worker \
  uv run python manage.py procrastinate worker \
  --queues=index,graph,crawl_ingest,page_index,maintenance
# leader（周期 rescue + cron 单例）可作为 scheduler 角色单独起一个 worker：
FRIDAY_PROCESS_ROLE=scheduler \
  uv run python manage.py procrastinate worker --queues=maintenance
# 装配自检：
uv run python manage.py procrastinate healthchecks
```

### 队列常量（本阶段仅定义，Phase 61+ 消费）
```python
# server/durable/service.py
from enum import StrEnum

class DurableQueue(StrEnum):
    INDEX = "index"
    GRAPH = "graph"
    CRAWL_INGEST = "crawl_ingest"
    PAGE_INDEX = "page_index"
    MAINTENANCE = "maintenance"
```

### settings 装配（条件加 contrib app + Procrastinate settings）
```python
# server/friday/settings.py（DATABASES 之后）
DURABLE_TASK_BACKEND = env.str("DURABLE_TASK_BACKEND", default="procrastinate")
FRIDAY_PROCESS_ROLE = env.str("FRIDAY_PROCESS_ROLE", default="web")

_IS_POSTGRES = "postgresql" in DATABASES["default"]["ENGINE"]
if _IS_POSTGRES and DURABLE_TASK_BACKEND == "procrastinate":
    INSTALLED_APPS.insert(INSTALLED_APPS.index("resumable"), "procrastinate.contrib.django")
    PROCRASTINATE_AUTODISCOVER_MODULE_NAME = "tasks"  # 默认；durable/tasks.py 被发现
    PROCRASTINATE_READONLY_MODELS = True               # 生产只读，测试 fixture 翻 False
    PROCRASTINATE_WORKER_DEFAULTS = {"listen_notify": False}  # polling（DURABLEX-01 留 v2）
```

### in-process fallback（复用 background_runner）
```python
# server/durable/backends.py
from services.background_runner import run_in_background

def _defer_inprocess(coro_factory, *, name):
    # 非 durable：进程死即丢；仅 dev/SQLite。返回 concurrent.futures.Future
    return run_in_background(coro_factory, name=name)
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| `get_stalled_jobs(nb_seconds=N)`（基于 doing 时长） | `get_stalled_jobs(seconds_since_heartbeat=30)`（基于 worker 心跳） | Procrastinate 3.1.0（2025-03，PR #1344） | 避免"慢≠死"误判；`nb_seconds` 已 deprecated |
| 自写 DB lease/CAS/heartbeat（本仓 `resumable/`） | Procrastinate `procrastinate_jobs` + `worker_heartbeats` | 本阶段引入 | 让位成熟实现，适配层只隔离 |
| 单机 `flock` 选主（`runapscheduler`） | DB `queueing_lock` 单例 | 本阶段（rescue）/ Phase 63（整体 scheduler） | 跨 Pod 有效 |

**Deprecated/outdated:**
- `JobManager.get_stalled_jobs(nb_seconds=…)`：deprecated，下个 major 移除。
- 本仓 `resumable/locks.py` 的 Redis 选主：本阶段不删（Phase 61 收口 ResumableTask 时一并评估），但 durable 路径改用 `queueing_lock`。

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | `procrastinate[django]>=3.8.1,<3.9` 安装合法（slopcheck 未跑，沙箱无网络） | Package Legitimacy Audit | 低——官方文档/PoC/GitHub 充分辅证；planner human-verify 兜底 |
| A2 | 条件性把 `procrastinate.contrib.django` 加进 INSTALLED_APPS 可让 SQLite/pytest 默认路径不建 Procrastinate 表 | Pitfall 6 / settings 装配 | 中——若 Procrastinate 要求 contrib app 始终在场，需改用 migration router；执行期需 `migrate` 实测验证 |
| A3 | worker 仍需 codegraph extractor backend 注册（不门禁该注册） | Runtime State Inventory | 中——若 worker 不跑 graph 抽取则可门禁；建议保留注册（纯内存、无副作用），planner 据实判定 |
| A4 | `@app.periodic` 周期任务由运行中的 worker 进程驱动（需至少一个 worker 在线才会触发 rescue） | Code Examples | 低——这是 Procrastinate 设计；意味着"无 worker 在线时无 rescue"，但本阶段验收闭环有 worker |

## Open Questions

1. **Procrastinate migration 在 SQLite 下的注入策略**
   - What we know：Procrastinate 用 Django migrations 建表，SQL 含 Postgres 专属对象；CONTEXT 要求 pytest 默认 SQLite 不需 Postgres。
   - What's unclear：条件装配 INSTALLED_APPS（A2）是否完全够，还是需 migration router；`makemigrations --check` 在两种后端下是否都干净。
   - Recommendation：planner 安排一个 Wave 0 探针——本地分别用 SQLite 与 Postgres 跑 `migrate` + `makemigrations --check`，确认条件装配方案。优先条件装配（最简）。

2. **leader 进程归属（worker 还是独立 scheduler 角色）**
   - What we know：`@app.periodic` 由 worker 驱动；`queueing_lock` 保证多副本单例。
   - What's unclear：本阶段是否引入独立 `scheduler` 角色进程，还是让普通 worker 兼任 leader（`queueing_lock` 已保证单例）。
   - Recommendation：本阶段最小闭环——普通 worker 即可承载周期 rescue（`queueing_lock` 去重），无需强制独立 scheduler 进程；独立 scheduler workload 留 Phase 63。`FRIDAY_PROCESS_ROLE=scheduler` 枚举值本阶段先定义占位。

3. **`get`/`cancel` 适配层语义**
   - What we know：Procrastinate 有 `JobManager.get_job_status_async` 类查询、`cancel_job_by_id_async`。
   - What's unclear：适配层 `get`/`cancel` 的精确返回结构（统一 dataclass vs 透传）。
   - Recommendation：planner 定义中性 `DurableJobView` dataclass（id/status/queue/attempts），两后端各自映射；fallback 后端的 `get/cancel` 基于 `background_runner` 的 named future（`cancel_background_task(name)` 已有）。

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| Postgres | Procrastinate durable 路径 + `postgres_queue` CI | ✓（compose/helm 默认 `docker-compose.yaml:37`；CI 用 service container `postgres:17-alpine`） | 17 | SQLite in-process fallback（dev/pytest 默认） |
| psycopg[binary] | worker 异步连接器 | ✓ | 3.3.2（uv.lock） | — |
| Django | migrations + contrib.django | ✓ | 6.0.1（uv.lock） | — |
| procrastinate[django] | durable 后端 | ✗（**未安装，需 `uv add`**） | 目标 ≥3.8.1,<3.9 | in-process fallback（已有 `background_runner`） |
| GH Actions CI workflow | DURABLE-04 Postgres CI | ✗（**`.github/workflows/` 当前为空，无任何 workflow**） | — | 无——必须新建 `.github/workflows/ci.yaml`（含默认 SQLite job + Postgres service job） |
| `uv` / pytest / pytest-django / pytest-socket | 测试运行 | ✓ | 见 dev group | — |

**Missing dependencies with no fallback:**
- `.github/workflows/ci.yaml` 不存在——DURABLE-04 必须从零创建 GH Actions workflow（注意：CONTEXT/STACK 把它列为"既有集成点"实为不准确；planner 应按"新建"处理）。

**Missing dependencies with fallback:**
- `procrastinate` 未安装——`uv add` 后落地；未装时 `DurableTaskService` 走 in-process fallback（本阶段必须装以验收 Postgres 路径）。

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest 9.0.2 + pytest-django 4.8 + pytest-asyncio（`asyncio_mode = "auto"`） |
| Config file | `server/pyproject.toml` `[tool.pytest.ini_options]` |
| Quick run command | `cd server && uv run pytest tests/durable/ -x`（默认 SQLite，跳过 `postgres_queue`） |
| Full suite command | `cd server && uv run pytest`（默认 `-m 'not perf and not integration and not slow'`） |
| Postgres 专项命令 | `cd server && DATABASE_URL=postgres://... uv run pytest -m postgres_queue --no-header`（需先在 marker 层放行；见下） |

### marker 注册与分层（DURABLE-04）
- 在 `pyproject.toml` `[tool.pytest.ini_options] markers` 新增：`"postgres_queue: 需真实 Postgres 的 durable 队列测试（CI service container 跑，本地默认 skip）"`。
- 既有 `addopts` 含 `-m 'not perf and not integration and not slow'`——**默认不排除 `postgres_queue`**。为让默认 SQLite 路径不误跑 Postgres 测试，两选一（planner 决策）：(a) 把 `addopts` 改为 `... and not postgres_queue`，Postgres CI 显式 `-m postgres_queue` 覆盖；(b) `postgres_queue` 测试内用 fixture 在非 Postgres 后端时 `pytest.skip(...)`。**建议 (a)+(b) 双保险**。
- 复用 `server/tests/conftest.py` 既有 adrf monkeypatch（`patch_asyncio_iscoroutinefunction`）+ pytest-socket（`--disable-socket --allow-unix-socket`）——注意 Postgres 测试需 DB socket，`--allow-unix-socket` 已放行 unix socket；TCP 连 Postgres CI service 时需 `--allow-hosts` 或 service 用 localhost（pytest-django DB 连接通常豁免）。planner 在 Postgres CI job 显式放行连接。

### Phase Requirements → Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| DURABLE-01 | 适配层 `defer` 把任务入队（Procrastinate 路径，含 queue/priority/idempotency_key/run_at 映射） | unit（InMemoryConnector） | `pytest tests/durable/test_service_defer.py -x` | ❌ Wave 0 |
| DURABLE-01 | SQLite/无 DATABASE_URL → fallback 后端（select_backend 返 inprocess，不 import procrastinate） | unit | `pytest tests/durable/test_backend_select.py -x` | ❌ Wave 0 |
| DURABLE-01 | 业务代码无直接 `import procrastinate`（grep 守护，除 `server/durable/`） | unit（静态扫描） | `pytest tests/durable/test_no_direct_import_guard.py -x` | ❌ Wave 0 |
| DURABLE-01 | priority 高者先取；run_at 延迟入队 | postgres_queue | `pytest -m postgres_queue tests/durable/test_priority_schedule.py` | ❌ Wave 0 |
| DURABLE-01 | retry-backoff：失败任务按 retry strategy 重排队（attempts 累加、等待态存 DB） | postgres_queue | `pytest -m postgres_queue tests/durable/test_retry_backoff.py` | ❌ Wave 0 |
| DURABLE-02 | `should_run_startup_jobs`：role=worker/migrate 返 False + info 日志；role=web 返 True | unit | `pytest tests/durable/test_process_roles.py -x` | ❌ Wave 0 |
| DURABLE-02 | 三处 `ready()` 接入门禁：worker/migrate 角色不触发 reconcile/sweep（monkeypatch role + 断言副作用未跑） | unit | `pytest tests/durable/test_appconfig_role_gate.py -x` | ❌ Wave 0 |
| DURABLE-03 | stalled rescue：worker 心跳停 → `get_stalled_jobs` 命中 → `retry_job` 重投 | postgres_queue | `pytest -m postgres_queue tests/durable/test_stalled_rescue.py` | ❌ Wave 0 |
| DURABLE-03 | queueing_lock 单例：并发两 leader 调用同 `queueing_lock` task，只一个入队（AlreadyEnqueued） | postgres_queue | `pytest -m postgres_queue tests/durable/test_leader_singleton.py` | ❌ Wave 0 |
| DURABLE-03 | UniqueViolation 防御：rescue 对带 queueing_lock 的 stalled job 不中断整轮（坑 #1446） | postgres_queue / unit | `pytest -m postgres_queue tests/durable/test_rescue_unique_violation.py` | ❌ Wave 0 |
| DURABLE-04 | 并发 worker 竞争：两 worker 跑同队列，同一 job 只一个成功执行（不双跑） | postgres_queue | `pytest -m postgres_queue tests/durable/test_concurrent_workers.py` | ❌ Wave 0 |
| DURABLE-04 | SQLite fallback 退化路径：无 Postgres 时 defer 走 background_runner 执行 | unit | `pytest tests/durable/test_fallback_execution.py -x` | ❌ Wave 0 |

### 各验收点测试策略（针对 output 要求逐一）
- **defer / priority**：unit 用 `InMemoryConnector` 断言 `app.connector.jobs` 的 queue/priority/queueing_lock/scheduled_at；priority 实序需 Postgres（worker 取序），故 priority 顺序断言放 `postgres_queue`（起两个不同 priority job + `run_worker(wait=False)` 观察执行序）。
- **retry-backoff**：`postgres_queue`——defer 一个会抛异常的 task（配 retry 策略），`run_worker` 后断言 job 回到 `todo`/`scheduled_at` 在未来 + attempts 递增。
- **stalled-rescue**：`postgres_queue`——模拟 worker 心跳过期（直接写 `worker_heartbeats` 老时间或用低 `stalled_worker_timeout`），调 `get_stalled_jobs()` 断言命中，`retry_job` 后 job 回 `todo`。验收级闭环（kill worker → 另一 worker 接管）作 `integration` marker（需真起两 worker 进程）。
- **concurrent-worker**：`postgres_queue`——defer N 个 job，并发起两个 `run_worker_async`，断言每个 job 恰执行一次（用 side-effect 计数 + DB `succeeded` 计数）。验证 Procrastinate SKIP LOCKED 领取的 at-least-once 单轮唯一性。
- **SQLite-fallback**：unit——`settings.DATABASES` 为 SQLite + `DURABLE_TASK_BACKEND` 任意，断言 `select_backend()=="inprocess"`，且 `defer` 经 `background_runner` 真执行 side-effect（复用 `conftest.py` 既有 `_reset_background_runner` autouse fixture 等待落地）。

### Sampling Rate
- **Per task commit:** `uv run pytest tests/durable/ -x`（SQLite 快路径）
- **Per wave merge:** `uv run pytest`（全默认套件）+（若改了 Postgres 路径）本地或 CI 跑 `-m postgres_queue`
- **Phase gate:** 默认套件全绿 + Postgres CI job 全绿，再进 `/gsd-verify-work`

### Wave 0 Gaps
- [ ] `server/tests/durable/__init__.py` + `conftest.py`——`procrastinate_app` InMemoryConnector fixture（`replace_connector`）+ `procrastinate_writable_models`（`settings.PROCRASTINATE_READONLY_MODELS=False`）+ Postgres 后端判定 fixture（非 Postgres 时 skip `postgres_queue`）。
- [ ] `pyproject.toml` 新增 `postgres_queue` marker + 调整 `addopts`（`and not postgres_queue`）。
- [ ] `.github/workflows/ci.yaml`——**从零新建**：job A（默认 SQLite，`uv run pytest`）+ job B（`services: postgres:17-alpine`，`DATABASE_URL` 指向 service，`uv run pytest -m postgres_queue`）。
- [ ] 依赖安装：`uv add 'procrastinate[django]>=3.8.1,<3.9'`（Wave 0 前置，gate human-verify）。
- [ ] 探针：本地 SQLite + Postgres 各跑一次 `migrate` / `makemigrations --check` 验证条件装配（Open Q1）。

## Security Domain

> `security_enforcement` 配置未显式 false → 包含本节。本阶段为后端基础设施，无新对外端点/认证面。

### Applicable ASVS Categories
| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | no | 无新认证面（worker/scheduler 为内部进程） |
| V3 Session Management | no | — |
| V4 Access Control | no | 无新对外 API（`get/cancel` 本阶段不暴露 REST） |
| V5 Input Validation | partial | task payload 为内部产生；`FRIDAY_PROCESS_ROLE`/`DURABLE_TASK_BACKEND` env 取值需白名单校验（非法值 fail-safe 回 `web`/`inprocess`） |
| V6 Cryptography | no | 不处理凭证；DB 连接复用既有 `DATABASE_URL`（凭证不入 task payload） |
| V9/V10 Communication/Malicious | partial | `listen_notify=False` 纯 polling，无新网络监听；worker 经 Postgres 连接（复用既有 DB 凭证） |

### Known Threat Patterns for durable queue
| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| stalled rescue 误判活跃 worker 任务（"慢≠死"） | Denial of Service / 数据重复 | 用心跳判定（`seconds_since_heartbeat`）非时长；at-least-once + handler 幂等（Phase 61） |
| poison job 无限重投耗资源 | DoS | retry strategy `max_attempts` 上限；rescue 对 UniqueViolation 标 FAILED（坑 #1446） |
| worker/migrate 进程跑 web-only reconcile 误杀在途任务 | Tampering（数据完整性） | DURABLE-02 角色门禁——这是本阶段核心安全收口（PoC 硬前置③） |
| task payload 注入敏感凭证落 DB 明文 | Information Disclosure | 约定 payload 只放 deterministic key / id，不放凭证（凭证运行时经既有 `resolve_*` 解析）——planner 在 service docstring 明确该约束 |
| env `FRIDAY_PROCESS_ROLE` 注入非法值致门禁失效 | Tampering | 解析时白名单校验，未知值 fail-safe（默认 `web` 即最保守——跑全部副作用，不会漏门禁导致误删） |

## Sources

### Primary (HIGH confidence)
- procrastinate.readthedocs.io `/howto/django/configuration` `/basic_usage` `/settings` `/scripts` — Django 集成、INSTALLED_APPS、PROCRASTINATE_* settings、worker 启动、`get_worker_connector()`
- procrastinate.readthedocs.io `/howto/production/retry_stalled_jobs` + `/reference` — `get_stalled_jobs(seconds_since_heartbeat)` / `retry_job` / heartbeat 参数
- procrastinate.readthedocs.io `/howto/django/tests` `/howto/production/testing` — InMemoryConnector / PROCRASTINATE_READONLY_MODELS
- procrastinate.readthedocs.io `/changelog` — 3.8.1（2026-04-08）、3.1.0 heartbeat（2025-03-22）
- GitHub `procrastinate-org/procrastinate` commit abb121b / PR #919 #960 #1344 — get_worker_connector psycopg3、django 集成、heartbeat 实现
- 本仓代码：`server/uv.lock`（Django 6.0.1 / psycopg 3.3.2）、`server/resumable/*`、`server/services/background_runner.py`、`server/{repositories,codegraph,resumable}/apps.py`、`server/friday/settings.py`、`server/agents/management/commands/runapscheduler.py`、`server/tests/conftest.py`、`server/pyproject.toml`、`.github/workflows/`（空）

### Secondary (MEDIUM confidence)
- GitHub issue #1446 — `retry_stalled_jobs` + queueing_lock 的 UniqueViolation 已知坑及 workaround
- `procrastinate/tasks.py` `ConfigureTaskOptions` TypedDict — defer/configure 参数面（lock/queueing_lock/schedule_at/queue/priority）

### Tertiary (LOW confidence)
- engineering.leanix.net 博客 — lock vs queueing_lock 实践经验（用于佐证"自写 stalled 检测"动机，非 API 依据）

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — 版本经 uv.lock 实锁 + Procrastinate changelog 核实
- Architecture（适配层/角色门禁/leader）: HIGH — 官方 API + 本仓既有范式镜像清晰
- Pitfalls: HIGH — 坑 #1446 / nb_seconds 废弃 / readonly models 均有官方/issue 出处
- Migration（SQLite 注入策略）: MEDIUM — Open Q1 待执行期探针确认
- CI: HIGH（事实层：无现成 workflow）/ MEDIUM（具体 service container 配置待实测）

**Research date:** 2026-06-20
**Valid until:** 2026-07-20（Procrastinate 稳态；若跨 3.9 major 需复核 `nb_seconds` 移除与 API 变更）

## RESEARCH COMPLETE
