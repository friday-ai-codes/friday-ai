# Phase 60: durable 底座地基 - Research

**Researched:** 2026-06-20
**Domain:** Postgres-backed durable task queue (Procrastinate) + Django app/process-role gating + periodic leader rescue + Postgres CI
**Confidence:** HIGH

## Summary

本阶段在既有 `server/resumable/`（DB 真相源 + lease/heartbeat + CAS claim + 启动恢复）之上，立起 **`DurableTaskService` 适配层**：Postgres 走 **Procrastinate 3.8.1**，SQLite/无 `DATABASE_URL` 退化为复用 `services/background_runner.py` 的 in-process 非 durable fallback。研究核对结论：**仓库实际依赖版本与 PoC 完全一致**（Django 6.0.1 / psycopg 3.3.2 / Python ≥3.14，见 `server/uv.lock`），无版本漂移风险；**Procrastinate 尚未加入依赖**（仅出现在 `.planning/*` 文档，`server/pyproject.toml`/`uv.lock` 均无），需新增 `procrastinate[django]>=3.8.1,<3.9`。

Procrastinate 的 Django 集成是"自带 app + 自带迁移 + 自带 worker connector"：`procrastinate.contrib.django` 加进 `INSTALLED_APPS`，框架在 `procrastinate.contrib.django.app` 提供配置好的 `App`（`DjangoConnector` 复用 Django `DATABASES["default"]` 连接做 `defer`）；worker 必须独立进程，经 `./manage.py procrastinate worker` 或 `app.connector.get_worker_connector()`（psycopg3 在装 → 返回 `PsycopgConnector`）跑，**绝不能直接拿 `DjangoConnector` 跑 worker**（PoC 硬前置①，官方明确 DjangoConnector 不适合 worker）。周期 rescue 用官方 `retry_stalled_jobs` 范式：`@app.periodic(cron=...)` + `@app.task(queueing_lock="...", pass_context=True)` + `app.job_manager.get_stalled_jobs()` + `retry_job()`——periodic 机制由 DB 保证"每周期只 defer 一次"（多 worker 天然单例），queueing_lock 再保证不堆积，**这就是 DURABLE-03 要的"单例 leader"语义**。

**重大坐标修正（影响 DURABLE-04 规划）：** 仓库当前 **没有任何 GitHub Actions workflow**——三个 workflow（`ci.yaml`/`docs.yaml`/`release.yaml`）已于 commit `5579e45f2`（2026-06-19）整体删除。DURABLE-04"新增 Postgres 专项 CI"将是**从零（重新）创建 workflow**，而非"在现有 CI 上加 job"。规划须把"重建 CI workflow 骨架"纳入范围（可参考 git 历史 `5579e45f2^:.github/workflows/ci.yaml` 的结构）。

**Primary recommendation:** 新建 `server/durable/` app（镜像 `server/resumable/` 结构）承载 `DurableTaskService`/`tasks.py`/`apps.py`/`management/`；后端选择走 `DURABLE_TASK_BACKEND` + `DATABASE_URL` 引擎判定；`procrastinate.contrib.django` 加进 `INSTALLED_APPS`（自带迁移）；周期 rescue 用官方 `@app.periodic + queueing_lock` 范式；新增 `FRIDAY_PROCESS_ROLE` 收口三处 `AppConfig.ready()`；pytest 加 `postgres_queue` marker 并在 `addopts` 默认排除（默认/SQLite 跑不命中），从零建一个最小 Postgres CI workflow 跑 `-m postgres_queue`。

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
- 弃用 `runapscheduler` 的本地 `flock`（仅单机有效、跨 Pod 失效）。
- 执行语义明确 **at-least-once，不承诺 exactly-once**。

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
| DURABLE-01 | `DurableTaskService` 适配层隔离队列实现（Postgres→Procrastinate / SQLite→in-process fallback）；统一 `defer/get/cancel/retry_stalled` + idempotency_key + queue/priority；worker 独立进程 | Standard Stack（procrastinate[django]）、Architecture Pattern 1/2、`get_worker_connector()` 验证、`background_runner` fallback API（见 Don't Hand-Roll） |
| DURABLE-02 | `FRIDAY_PROCESS_ROLE` 门禁三处 `AppConfig.ready()` | 已逐一定位三处 startup 副作用（见 Component Responsibilities + Pattern 3）；新增 settings 解析点 |
| DURABLE-03 | 内置 `retry_stalled_durable_jobs` 周期任务 + `queueing_lock` 单例扫 stalled 重投，替代 flock | 官方 `retry_stalled_jobs` 范式逐字验证（Pattern 4 + Code Examples）；`runapscheduler` flock 现状定位 |
| DURABLE-04 | Postgres 专项 CI + `postgres_queue` marker，与 SQLite 默认共存 | **关键发现：当前无任何 CI workflow（已删除）**——须从零建；`addopts` marker 排除策略（见 Validation Architecture + Pitfall 4） |
</phase_requirements>

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| 任务入队（`defer`） | API/Backend（web 进程，async view 内经 adapter） | Database（Postgres procrastinate 表） | DjangoConnector 复用 Django DB 连接，defer 是 web 请求线程内的同步/异步 DB 写 |
| 任务执行（worker） | 独立 worker 进程（非 web） | Database | 官方明确 DjangoConnector 不适合 worker；worker 用 `get_worker_connector()` 独立 async 连接，独立事件循环 |
| 周期 rescue / cron | 独立 worker 进程（任一即可，DB 选举单例） | Database（periodic defer 去重 + queueing_lock） | Procrastinate periodic 由 DB 保证每周期只 defer 一次，无需指定 leader workload |
| 进程角色门禁 | Process bootstrap（`AppConfig.ready()` / settings） | — | 启动副作用是进程级行为，按 `FRIDAY_PROCESS_ROLE` 门禁 |
| SQLite fallback 执行 | 进程内 daemon thread（`background_runner`） | — | 非 durable，dev/pytest 用；无独立 worker 进程 |

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| `procrastinate[django]` | `>=3.8.1,<3.9` | Postgres-only durable task queue（defer/worker/periodic/retry/queueing_lock） | PoC PASS；Postgres-only 无需新增 broker（对齐"已有 Postgres、不引 Celery/Temporal/Kafka"核心价值）；官方一等 Django 集成 `[CITED: procrastinate.readthedocs.io/howto/django/configuration]` |

### Supporting（均已在仓库，无需新增）
| Library | Version (uv.lock) | Purpose | When to Use |
|---------|-------------------|---------|-------------|
| `django` | 6.0.1 | web 框架；procrastinate 复用其 DATABASES 连接 | 全程；**与 PoC 声明的 Django 6.0 一致** |
| `psycopg[binary]` | 3.3.2 | PostgreSQL 驱动；`get_worker_connector()` 检测到 psycopg3 → 返回 `PsycopgConnector` | Postgres 后端 + worker connector |
| `adrf` | 0.1.12 | async DRF；`defer_async` 在 async view 调用 | DURABLE-01 async 入队路径 |
| `structlog` | 25.5.x | 结构化日志（角色门禁短路日志、rescue 日志） | 全程 |
| `pytest`/`pytest-asyncio`/`pytest-django` | 9.0.2 / 1.3.0 / 4.8 | 测试框架 | DURABLE-04 |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| Procrastinate | Celery / Temporal / RQ / Kafka | 违背"开箱即用、自托管"核心价值，需额外 broker（Redis/RabbitMQ）；Out of Scope 明确排除 |
| `@app.periodic` + `queueing_lock`（DURABLE-03） | 继续 `runapscheduler` + `flock` | flock 仅单机、跨 Pod 失效；CONTEXT 锁定弃用 |
| 新建 `server/durable/` app | 把 service 塞进 `resumable/` | resumable 是不同范式（lease/CAS）且 Phase 61 要"收口"它；新 app 边界更清晰（Claude's Discretion 建议新建） |

**Installation:**
```bash
# 在 server/ 下
uv add 'procrastinate[django]>=3.8.1,<3.9'
```

**Version verification（已核对）：**
- `procrastinate` 3.8.1 — PyPI 发布 2026-04-08，状态 `5 - Production/Stable`，`Python >=3.10`，`PostgreSQL 13+` `[VERIFIED: pypi.org/project/procrastinate]`。
- `django` 6.0.1 / `psycopg` 3.3.2 / `psycopg-binary` 3.3.2 — 见 `server/uv.lock`（`rg "^version" -A1`）`[VERIFIED: server/uv.lock]`。
- **PoC 一致性结论：无版本漂移风险。** PoC 声明 Procrastinate 3.8.1 / Python 3.14 / Django 6.0 / psycopg 3.3，仓库实际 Django 6.0.1 / psycopg 3.3.2 / `requires-python = ">=3.14"`，逐项匹配。

## Package Legitimacy Audit

| Package | Registry | Age | Downloads | Source Repo | slopcheck | Disposition |
|---------|----------|-----|-----------|-------------|-----------|-------------|
| `procrastinate` | PyPI | 首版 2019，3.8.1 (2026-04-08) | 成熟（GitHub ~1K★，Production/Stable，3.x 系列多版本迭代） | github.com/procrastinate-org/procrastinate | 未运行（环境无 slopcheck） | Approved（官方文档 + PyPI 双验证；非 slopsquat） |

**Packages removed due to slopcheck [SLOP] verdict:** none
**Packages flagged as suspicious [SUS]:** none

*slopcheck 在研究环境不可用，但 `procrastinate` 经官方 readthedocs 文档 + PyPI Production/Stable + 6 年历史多版本交叉验证，合法性 HIGH。`[django]` extra 仅拉入 `django`（已在仓库）。规划阶段安装前仍建议 `uv run python -c "import procrastinate; print(procrastinate.__version__)"` 落地确认。*

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| PostgreSQL 13+ | durable 后端（生产）+ DURABLE-04 Postgres CI | dev 本地按需（compose 自带 postgres:17-alpine） | 部署默认 | SQLite in-process fallback（非 durable，dev/pytest）|
| psycopg3 | worker connector | ✓（uv.lock 3.3.2） | 3.3.2 | — |
| GitHub Actions CI | DURABLE-04 | ✗（**所有 workflow 已删除**） | — | **无 fallback——须从零建 workflow** |

**Missing dependencies with no fallback:**
- **GitHub Actions workflow 不存在**（`5579e45f2` 删除 `ci.yaml`/`docs.yaml`/`release.yaml`）。DURABLE-04 需重建一个 workflow（可只建一个聚焦 server 测试 + Postgres service 的最小 CI，或参考 `git show 5579e45f2^:.github/workflows/ci.yaml` 复原完整结构）。规划须明确这是创建而非修改。

**Missing dependencies with fallback:**
- 本地 Postgres：`make dev`/pytest 默认 SQLite，`postgres_queue` 标记测试本地缺 Postgres 时由 marker 分层跳过（见 Validation Architecture）。

## Architecture Patterns

### System Architecture Diagram

```text
                        ┌─────────────────────────────────────────────┐
   入队方（web 进程）     │  async/sync view → DurableTaskService.defer  │
   index/graph/crawl ──▶ │  （业务代码只见 adapter，不见 Procrastinate） │
                        └───────────────┬─────────────────────────────┘
                                        │ backend 选择
                          ┌─────────────┴──────────────┐
            DATABASE_URL=postgres &&            其它 / SQLite / 无 DATABASE_URL
            DURABLE_TASK_BACKEND=procrastinate            │
                          │                               ▼
                          ▼                    ┌──────────────────────────┐
            ┌──────────────────────────┐       │ in-process fallback       │
            │ Procrastinate App         │       │ services.background_runner │
            │ (contrib.django.app)      │       │ run_in_background(factory) │
            │ DjangoConnector.defer ───▶│       │ （非 durable，进程内 thread）│
            └──────────┬────────────────┘       └──────────────────────────┘
                       │ 写 procrastinate_jobs 表
                       ▼
            ┌──────────────────────────┐        ┌──────────────────────────┐
            │  Postgres (procrastinate  │◀───────│ worker 进程（独立）        │
            │  jobs / locks / heartbeat)│ poll   │ ./manage.py procrastinate │
            └──────────────────────────┘        │ worker（get_worker_connector│
                       ▲                         │  → PsycopgConnector）       │
                       │ periodic defer (DB 去重) └──────────────────────────┘
                       │  @app.periodic + queueing_lock
            ┌──────────┴────────────────────────────┐
            │ retry_stalled_durable_jobs（任一 worker  │
            │ 跑，DB 保证每周期单次）→ get_stalled_jobs  │
            │ + retry_job（替代 flock/启动补扫）         │
            └────────────────────────────────────────┘

   进程启动 ── FRIDAY_PROCESS_ROLE 门禁 ──▶ repositories/codegraph/resumable
              AppConfig.ready()：role∈{web} 才跑 reconcile/sweep/startup jobs
```

### Recommended Project Structure
```text
server/durable/                  # 新建 app（镜像 resumable/ 结构）
├── __init__.py
├── apps.py                      # DurableConfig.ready()：按 role 装配/短路
├── service.py                   # DurableTaskService：defer/get/cancel/retry_stalled + backend 选择
├── backends.py                  # ProcrastinateBackend / InProcessBackend（协议 + 两实现）
├── tasks.py                     # @app.task 定义 + retry_stalled_durable_jobs periodic
├── queues.py                    # 队列名常量（index/graph/crawl_ingest/page_index/maintenance）
├── roles.py                     # FRIDAY_PROCESS_ROLE 解析 + should_run_startup_side_effects()
└── management/commands/
    └── run_worker.py            # 可选：包一层 procrastinate worker（或直接用官方命令）

server/friday/settings.py        # +procrastinate.contrib.django、+DURABLE_TASK_BACKEND、+FRIDAY_PROCESS_ROLE
server/tests/durable/            # 单测（SQLite fallback + role gating）+ postgres_queue 标记测试
.github/workflows/ci.yaml        # 从零重建（含 postgres:17-alpine service job）
```

### Pattern 1: 适配层隔离队列实现（DURABLE-01）
**What:** `DurableTaskService` 暴露统一接口，内部按 `DATABASE_URL` 引擎 + `DURABLE_TASK_BACKEND` 选 backend。业务代码只 import `DurableTaskService`，绝不 import procrastinate。
**When to use:** 所有入队点。
**Backend 选择判定点：** `settings.DATABASES["default"]["ENGINE"]` 含 `postgresql` 且 `settings.DURABLE_TASK_BACKEND == "procrastinate"` → ProcrastinateBackend；否则 InProcessBackend（复用 `background_runner.run_in_background`）。
- 注意 `settings.py:244` 用 `env.db("DATABASE_URL", ...)` 解析，引擎字符串为 `django.db.backends.postgresql`/`...sqlite3`；判定读 ENGINE 比解析原始 URL 稳。

### Pattern 2: worker = 独立进程（PoC 硬前置①）
**What:** worker 经 `./manage.py procrastinate worker` 启动（来自 `procrastinate.contrib.django`），或自建命令内 `app.connector.get_worker_connector()` 拿独立 async 连接。
**Why:** 官方明确 `DjangoConnector` 仅适合 `defer`，不适合长跑 worker（worker 需 fully-async 连接）。`get_worker_connector()` 检测 psycopg3 → 返回 `PsycopgConnector`，psycopg2 → `AiopgConnector`，都没有 → `ImproperlyConfigured` `[VERIFIED: github.com/procrastinate-org/procrastinate commit abb121b]`。
**Example（worker 选项）：**
```bash
# 选项 A：官方命令（推荐，注意 -v 被 Django 占用，不可调 verbosity）
FRIDAY_PROCESS_ROLE=worker python manage.py procrastinate worker --queues index,graph,crawl_ingest

# 选项 B：自建命令内部
# connector = app.connector.get_worker_connector()
# async with app.replace_connector(connector) as worker_app: await worker_app.run_worker_async(...)
```

### Pattern 3: 进程角色门禁（DURABLE-02）
**What:** `FRIDAY_PROCESS_ROLE`（默认 `web`）决定 `AppConfig.ready()` 是否跑 web-only startup 副作用。
**实现要点：** 在 `durable/roles.py` 提供 `current_role()` + `should_run_startup_side_effects(allowed={"web"})`；三处 `apps.py` 在调度前先判 role，非允许集 → 记 info 日志短路。注意三处现有的"管理命令短路"逻辑（检查 `sys.argv[1] in {migrate, ...}` + `pytest in argv0`）应保留并叠加 role 判定（role 是显式入口，argv 嗅探是兜底）。
**三处现有副作用（已逐一定位，见 Component Responsibilities）：** repositories 的 `_reset_stuck_indexing`、codegraph 的 galaxy warm + `_schedule_orphan_graph_build_reconcile`、resumable 的 `_schedule_recovery`。

### Pattern 4: 周期 stalled rescue = periodic + queueing_lock（DURABLE-03）
**What:** 官方 `retry_stalled_jobs` 范式即 DURABLE-03 所需"单例 leader"。periodic 由 DB 保证每周期只 defer 一次（多 worker 天然单例，**无需指定 leader workload**）；`queueing_lock` 保证 todo 队列里同时只有一个该任务实例不堆积。
**关键澄清（对 CONTEXT "queueing_lock 单例 leader" 表述的精确化）：** Procrastinate 的"单例"由两层叠加——① periodic 机制：worker 负责 defer，DB 确保每个 cron 周期只 defer 一份（即便多 worker）；② queueing_lock：防止慢处理时 todo 累积。二者合一即"多副本只有一个 leader 执行周期 rescue/cron"的等价语义，**不需要单独的 leader 选举或专用 scheduler 进程**（专用 `scheduler` workload 是 Phase 63 的部署选择，非 Procrastinate 必需）。
**stalled 判定基于 worker heartbeat**：worker 每 10s（默认）更新 heartbeat，`get_stalled_jobs()` 取"心跳超过 `seconds_since_heartbeat`（默认 30s）的 worker 的 doing 任务"。**勿用 `nb_seconds` 参数**（已 deprecated，可能误杀仍在跑的慢任务——正对应 CONTEXT "慢≠死" 约束）`[CITED: procrastinate.readthedocs.io/howto/production/retry_stalled_jobs]`。

### Anti-Patterns to Avoid
- **直接拿 `DjangoConnector` 跑 worker**：官方明确不支持（PoC 硬前置①）。
- **用 `procrastinate` CLI 的 `schema` 子命令建表**：Django 集成下 schema 由 Django migrations 管理，`./manage.py procrastinate` 不提供 `schema` 子命令 `[CITED: procrastinate.readthedocs.io/howto/django/basic_usage]`。
- **业务代码直接 import procrastinate**：违反适配层隔离（DURABLE-01 核心约束）。
- **用 `get_stalled_jobs(nb_seconds=...)`**：deprecated 且会误杀慢任务。
- **在 web 进程跑 worker 或 reconcile**：DURABLE-02 收口对象。

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| durable 任务持久化/领取/重试 | 自写 Postgres 队列表 + SKIP LOCKED | Procrastinate（已 PoC PASS） | 边界条件多（NOTIFY、heartbeat、stalled、priority、queueing_lock），官方久经考验 |
| stalled rescue 周期任务 | 自写扫描 + 重投循环 | `@app.periodic` + `get_stalled_jobs/retry_job` | 官方范式逐字可抄，DB 保证单例 |
| 跨副本"只跑一次"的周期任务 | flock / Redis 锁 / 自选 leader | Procrastinate periodic（DB 去重） | flock 跨 Pod 失效；periodic 已内置 DB 级去重 |
| SQLite fallback 的线程模型 | 新写 daemon thread/loop | 复用 `services.background_runner.run_in_background` | 已解决 CurrentThreadExecutor 生命周期问题（见其 docstring），有 `cancel_background_task`/`wait_for_pending`/`_reset_for_tests` |
| 入队幂等 | 自写 dedup 表 | Procrastinate `queueing_lock`（todo 唯一）+ 业务级 deterministic key | 两层：queueing_lock 防排队堆积，业务 upsert 防重复副作用 |

**Key insight:** 本阶段几乎不需要"造"——Procrastinate 提供队列/worker/periodic/retry/queueing_lock 全套，`background_runner` 提供 fallback。真正的工作量在**适配层封装 + 后端选择 + 角色门禁 + CI 重建**，而非队列内核。

### `background_runner` fallback API（in-process 后端复用，逐一列出）
- `run_in_background(coro_factory: Callable[[], Awaitable[T]], *, name: str|None=None) -> concurrent.futures.Future[T]` — 必须传 **factory**（无参返回 coroutine），不可传 coroutine。
- `cancel_background_task(name: str) -> bool` — 按名取消（cancel = 标 CANCELLED 语义见 resumable）。
- `wait_for_pending(timeout=30.0)` / `_reset_for_tests()` — 仅测试/shutdown。
- 进程级单 daemon 线程 + 常驻 event loop；ORM `sync_to_async` 安全（脱离请求生命周期）。

## Common Pitfalls

### Pitfall 1: 默认 pytest 跑命中 `postgres_queue` 测试导致本地/SQLite CI 失败
**What goes wrong:** `server/pyproject.toml` 的 `addopts = "... -m 'not perf and not integration and not slow'"`。新增 `postgres_queue` marker 但不在排除集里 → `pytest`（默认 SQLite，无 Postgres）会**默认运行**这些测试并失败。
**Why:** addopts 的 `-m` 表达式是 allowlist 取反，新 marker 不自动排除。
**How to avoid:** 把默认表达式改为 `-m 'not perf and not integration and not slow and not postgres_queue'`；Postgres CI job 显式 `pytest -m postgres_queue`（覆盖 addopts 的 `-m`）。
**Warning signs:** 本地 `pytest` 突然冒出连接 Postgres 失败 / `pytest-socket` 拦截 DB 连接。

### Pitfall 2: pytest-socket 拦截 Postgres 连接
**What goes wrong:** `addopts` 含 `--disable-socket --allow-unix-socket`；`postgres_queue` 测试连 TCP Postgres 会被拦。
**Why:** 默认禁 socket 强制隔离外部 HTTP。
**How to avoid:** `postgres_queue` 测试用 `@pytest.mark.enable_socket`（pytest-socket 提供）或在 Postgres CI job 的命令里加 `--allow-hosts=127.0.0.1,localhost`（或 service host）；CI service 容器走 TCP（`127.0.0.1:5432`）。
**Warning signs:** `SocketBlockedError`。

### Pitfall 3: procrastinate 迁移与现有迁移顺序
**What goes wrong:** `procrastinate.contrib.django` 自带迁移；忘记 `makemigrations`/`migrate` 或 app 顺序导致表缺失 warning（正是 DURABLE-02 要消除的"只迁队列表时业务表不存在"类场景的镜像）。
**Why:** procrastinate 表由其自带迁移建，不是 `schema` 命令。
**How to avoid:** `INSTALLED_APPS` 加 `procrastinate.contrib.django`（建议靠前）；`migrate` 角色进程跑全量迁移；CI/部署文档明确"migrate 一次性建所有表"。
**Warning signs:** `relation "procrastinate_jobs" does not exist`。

### Pitfall 4: 误以为"在现有 CI 加 job"
**What goes wrong:** DURABLE-04 假设有 `ci.yaml` 可加 Postgres job，但**所有 workflow 已删除**。
**Why:** commit `5579e45f2`（2026-06-19）移除全部 GitHub Actions workflow。
**How to avoid:** 规划须把"创建 workflow"纳入范围；可参考 `git show 5579e45f2^:.github/workflows/ci.yaml`（413 行，含 changes/server-ci/web-ci 等 job）复原或建最小聚焦版。
**Warning signs:** PLAN 写"修改 ci.yaml"。

### Pitfall 5: worker 进程跑了 web-only 启动副作用（PoC 硬前置③）
**What goes wrong:** 不做 DURABLE-02，worker/migrate 进程启动也会跑 `_reset_stuck_indexing`/reconcile/recovery，误杀在途任务或在迁移期报业务表不存在。
**How to avoid:** DURABLE-02 必须先于任何 worker 部署（也先于 Phase 61）。

## Component Responsibilities（已逐一定位的现有副作用与 file:line）

| Component | File | 启动副作用 / 关键点 | 门禁方式（DURABLE-02） |
|-----------|------|----------------------|------------------------|
| repositories.apps | `server/repositories/apps.py:18-24` | `ready()` 起 daemon thread 调 `_reset_stuck_indexing`（join timeout=5） | role∉{web} 短路；`_reset_stuck_indexing`（`:26-83`）把 ININDEXING→FAILED + 孤儿 IndexHistory RUNNING→FAILED |
| codegraph.apps | `server/codegraph/apps.py:105-121` | `ready()`：volar/gopls backend 注册 + galaxy warm(`:123`) + `_schedule_orphan_graph_build_reconcile`(`:169`) | backend 注册保留（纯内存，无 DB）；galaxy warm + orphan reconcile 按 role 门禁。注意现有已用 argv 嗅探跳过管理命令(`:142-148/195-201`) |
| resumable.apps | `server/resumable/apps.py:18-28` | `ready()`：`register_default_handlers()`（保留，纯注册）+ `_schedule_recovery`(`:29`，3 次补扫 8/35/100s) | handler 注册保留；`_schedule_recovery` 按 role 门禁。**DURABLE-03 将以 periodic rescue 替代此"仅启动补扫"** |
| DATABASE_URL 解析 | `server/friday/settings.py:243-244` | `DEFAULT_DATABASE_URL` = SQLite；`env.db("DATABASE_URL", ...)` | 后端判定读 `DATABASES["default"]["ENGINE"]` |
| INSTALLED_APPS | `server/friday/settings.py:89-131` | 顺序：daphne→django.*→drf→`django_apscheduler`→业务 apps | 加 `procrastinate.contrib.django`（建议在业务 apps 前）+ 新 `durable` app |
| flock scheduler | `server/agents/management/commands/runapscheduler.py:260-287` | `handle()` 用 `fcntl.flock("/tmp/friday-scheduler.lock")` 强制单实例 + 注册 9 个 cron/interval job | DURABLE-03 用 periodic+queueing_lock 替代 flock 单例语义（本阶段先立 rescue 闭环，迁移既有 cron job 留后续/Phase 63） |
| 既有 resumable 范式 | `server/resumable/service.py:141-161` | `claim_expired` DB CAS（`filter(status=RUNNING, lease_expires_at__lt=now).update(...)`）；lease/heartbeat（`:103-113`）；`INSTANCE_ID`（`:34`） | DurableTaskService 镜像此 lease/CAS 心智模型，但 durable 路径由 Procrastinate 内部实现 |
| pytest markers | `server/pyproject.toml:110-118` | `addopts` 含 `-m 'not perf and not integration and not slow'` + markers 列表 | 加 `postgres_queue` marker + 改 addopts 排除（Pitfall 1） |
| conftest | `server/tests/conftest.py:7-9,36-72` | adrf patch（顶层）+ `_reset_background_runner`/`_disable_scheduler_in_tests` autouse | 复用；durable 测试可加专用 fixture |

## Code Examples

### DurableTaskService 适配层骨架（DURABLE-01）
```python
# server/durable/service.py  — 业务代码唯一入口；不泄漏 procrastinate
from __future__ import annotations
import datetime
from typing import Any
from django.conf import settings

def _use_procrastinate() -> bool:
    engine = settings.DATABASES["default"]["ENGINE"]
    return "postgresql" in engine and getattr(
        settings, "DURABLE_TASK_BACKEND", "auto"
    ) == "procrastinate"

class DurableTaskService:
    """durable 任务统一入口：Postgres→Procrastinate / 否则 in-process fallback。"""

    @staticmethod
    async def defer(
        task: str, payload: dict[str, Any], *, queue: str,
        priority: int = 0, idempotency_key: str | None = None,
        run_at: datetime.datetime | None = None,
    ) -> str:
        if _use_procrastinate():
            from durable.backends import procrastinate_backend  # 局部 import 隔离
            return await procrastinate_backend.defer(
                task, payload, queue=queue, priority=priority,
                idempotency_key=idempotency_key, run_at=run_at,
            )
        from durable.backends import in_process_backend
        return await in_process_backend.defer(task, payload, queue=queue)
```

### Procrastinate task + defer_async（DURABLE-01）
```python
# server/durable/tasks.py
from procrastinate.contrib.django import app  # 框架自带、已配置好的 App

@app.task(queue="index")
async def reindex_repository(repository_id: str, branch: str | None = None) -> None:
    ...

# defer（procrastinate backend 内部，仍藏在 adapter 后）:
#   await reindex_repository.configure(
#       queueing_lock=idempotency_key,   # todo 唯一，AlreadyEnqueued 可忽略
#       priority=priority,
#       schedule_at=run_at,
#   ).defer_async(repository_id=repo_id, branch=branch)
```

### retry_stalled_durable_jobs 周期单例（DURABLE-03，官方范式逐字）
```python
# server/durable/tasks.py  — Source: procrastinate.readthedocs.io/howto/production/retry_stalled_jobs
from procrastinate.contrib.django import app

@app.periodic(cron="*/10 * * * *")
@app.task(queueing_lock="retry_stalled_durable_jobs", pass_context=True)
async def retry_stalled_durable_jobs(context, timestamp: int) -> None:
    # 基于 worker heartbeat 判定 stalled（默认 30s 无心跳）；勿用 deprecated nb_seconds
    stalled_jobs = await app.job_manager.get_stalled_jobs()
    for job in stalled_jobs:
        await app.job_manager.retry_job(job)
```

### 进程角色门禁（DURABLE-02）
```python
# server/durable/roles.py
import os
import structlog
logger = structlog.get_logger(__name__)

def current_role() -> str:
    return os.environ.get("FRIDAY_PROCESS_ROLE", "web").strip().lower() or "web"

def should_run_startup_side_effects(*, job: str, allowed: set[str] = frozenset({"web"})) -> bool:
    role = current_role()
    if role in allowed:
        return True
    logger.info("startup_side_effect_skipped_by_role", role=role, job=job)
    return False

# 在 repositories/apps.py ready() 内：
#   from durable.roles import should_run_startup_side_effects
#   if should_run_startup_side_effects(job="reset_stuck_indexing"):
#       threading.Thread(target=self._reset_stuck_indexing, daemon=True).start()
```

### settings 装配
```python
# server/friday/settings.py
INSTALLED_APPS = [
    ...,
    "procrastinate.contrib.django",   # 建议在业务 app 前
    "durable",
    ...,
]
# 后端选择：auto（按引擎自动）/ procrastinate（强制，需 Postgres）/ in_process（强制 fallback）
DURABLE_TASK_BACKEND = env.str("DURABLE_TASK_BACKEND", default="auto")
FRIDAY_PROCESS_ROLE = env.str("FRIDAY_PROCESS_ROLE", default="web")  # web|worker|scheduler|migrate|test
```

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest 9.0.2 + pytest-asyncio 1.3.0 + pytest-django 4.8 |
| Config file | `server/pyproject.toml` `[tool.pytest.ini_options]` |
| Quick run command | `cd server && uv run pytest tests/durable/ -x`（SQLite，默认路径） |
| Full suite command | `cd server && uv run pytest`（SQLite 全量） |
| Postgres 专项 | `cd server && DATABASE_URL=postgres://... uv run pytest -m postgres_queue --allow-hosts=127.0.0.1,localhost` |

### Phase Requirements → Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| DURABLE-01 | SQLite fallback：无 Postgres 时 defer 走 in-process，不报错 | unit | `pytest tests/durable/test_backend_selection.py -x` | ❌ Wave 0 |
| DURABLE-01 | 适配层不泄漏 procrastinate（grep 守护业务代码无直接 import） | unit | `pytest tests/durable/test_no_procrastinate_leak.py -x` | ❌ Wave 0 |
| DURABLE-01 | defer/priority/run_at 在真实 Postgres 落 procrastinate_jobs | postgres_queue | `pytest -m postgres_queue tests/durable/test_defer_pg.py` | ❌ Wave 0 |
| DURABLE-01 | worker 用 `get_worker_connector()`（psycopg3→PsycopgConnector）| postgres_queue | `pytest -m postgres_queue tests/durable/test_worker_connector.py` | ❌ Wave 0 |
| DURABLE-02 | `FRIDAY_PROCESS_ROLE=worker/migrate` 时三处 ready() 短路 + info 日志 | unit | `pytest tests/durable/test_role_gating.py -x` | ❌ Wave 0 |
| DURABLE-02 | role=web 仍跑既有 reconcile（零回归） | unit | `pytest tests/durable/test_role_gating.py::test_web_role_runs -x` | ❌ Wave 0 |
| DURABLE-03 | stalled rescue：kill worker → 另一 worker periodic 重投 | postgres_queue | `pytest -m postgres_queue tests/durable/test_stalled_rescue.py` | ❌ Wave 0 |
| DURABLE-03 | retry-backoff / priority 顺序 | postgres_queue | `pytest -m postgres_queue tests/durable/test_retry_priority.py` | ❌ Wave 0 |
| DURABLE-03 | queueing_lock 单例：同 lock 重复 defer → AlreadyEnqueued/单实例 | postgres_queue | `pytest -m postgres_queue tests/durable/test_queueing_lock.py` | ❌ Wave 0 |
| DURABLE-04 | 并发 worker 竞争同一 job 仅一个成功 | postgres_queue | `pytest -m postgres_queue tests/durable/test_concurrent_workers.py` | ❌ Wave 0 |
| DURABLE-04 | CI workflow 存在且含 postgres:17-alpine service | manual/CI | workflow 文件 review + CI 绿 | ❌ Wave 0 |

### Sampling Rate
- **Per task commit:** `uv run pytest tests/durable/ -x`（SQLite，秒级）
- **Per wave merge:** `uv run pytest`（SQLite 全量，确认零回归）
- **Phase gate:** SQLite 全量绿 + Postgres CI job（`-m postgres_queue`）绿，再 `/gsd-verify-work`

### Wave 0 Gaps
- [ ] `server/pyproject.toml` — 注册 `postgres_queue` marker + 把它加入 addopts 默认排除集（Pitfall 1）
- [ ] `tests/durable/conftest.py` — Postgres 连接/`enable_socket`/procrastinate app fixture（复用顶层 adrf patch）
- [ ] `tests/durable/` — 上表全部测试文件
- [ ] `.github/workflows/ci.yaml`（或聚焦版） — 从零创建，含 postgres:17-alpine service（Pitfall 4）
- [ ] 真实 stalled rescue 的 kill-worker E2E 可能需 docker/真实进程——若 CI 内难复现，可用"伪造过期 heartbeat 行 + 调 get_stalled_jobs/retry_job"在 postgres_queue 测试里逼近（建议作 Open Question 与规划确认）

## Security Domain

### Applicable ASVS Categories (Level 1)
| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | no | 本阶段无新认证面（worker 不开新端口；入队在已认证 web 进程内） |
| V3 Session Management | no | — |
| V4 Access Control | partial | defer 仍在既有已认证 view 内触发，沿用既有 RBAC；本阶段不新增对外入队端点（CRAWL-02 才有面板） |
| V5 Input Validation | yes | payload 必须 JSON-serializable；deterministic idempotency_key 防注入式 lock 名（用受控前缀如 `index:{repo_id}`） |
| V6 Cryptography | no | durable 任务不存凭证；凭证仍走既有 `ProviderCredential`/Fernet（payload 只放 id/最小参数，不放明文 token） |

### Known Threat Patterns for durable queue
| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| 慢任务被误判 stalled 重复执行 | DoS/正确性 | 基于 worker heartbeat 判定（非固定 nb_seconds）；handler 幂等（Phase 61 IDEMP）；at-least-once 显式声明 |
| payload 携带明文凭证落 DB | Information Disclosure | payload 仅放 id/最小参数；凭证运行时按 scope 解析（CLAUDE.md 约束：凭证不走环境变量/不入 payload） |
| worker 进程跑 web-only reconcile 误杀在途 | Tampering | DURABLE-02 role 门禁（PoC 硬前置③） |
| at-least-once 重复外部副作用（通知/建 PR） | 正确性 | 本阶段不接业务任务；fencing/outbox 留 Phase 63 IDEMP-02 |

## State of the Art
| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| 启动一次性 reconcile + 3 次补扫（resumable）| periodic `get_stalled_jobs/retry_job`（持续）| 本阶段 | 多副本持续 rescue，不止启动窗口 |
| `runapscheduler` + `fcntl.flock` 单机单例 | Procrastinate periodic（DB 去重，跨 Pod）| 本阶段（rescue 部分）| flock 跨 Pod 失效问题消除 |
| `get_stalled_jobs(nb_seconds=...)` | heartbeat-based（`seconds_since_heartbeat`）| procrastinate 近版本 | `nb_seconds` deprecated，避免误杀慢任务 |

**Deprecated/outdated:**
- `procrastinate` `schema` 子命令在 Django 集成下不可用（用 Django migrations）。
- `JobManager.get_stalled_jobs(nb_seconds=...)`：deprecated，将在下个大版本移除。

## Assumptions Log
| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | 新建独立 `server/durable/` app（而非塞进 resumable）| Project Structure | 低——CONTEXT 已建议；落点是 Claude's Discretion |
| A2 | 后端判定读 `DATABASES["default"]["ENGINE"]` 含 `postgresql` | Pattern 1 | 低——Django 标准引擎串；若用自定义引擎需调整 |
| A3 | DURABLE-04 需从零建 CI workflow（无现有可改）| Environment / Pitfall 4 | 中——若 maintainer 另有 CI 计划（如外部 CI），范围需对齐；已用 git 历史确证 workflow 已删 |
| A4 | stalled rescue E2E 可用"伪造过期 heartbeat + get_stalled_jobs/retry_job"在 CI 逼近，无需真 kill 进程 | Validation Wave 0 | 中——若要求真实 kill-worker，CI 复杂度上升；建议规划确认 |
| A5 | `addopts` 的 `-m` 需手动追加 `and not postgres_queue` | Pitfall 1 | 低——pytest marker 语义明确 |

## Open Questions
1. **DURABLE-04 的 CI workflow 范围**
   - What we know: 所有 GitHub Actions workflow 已删（`5579e45f2`）；git 历史有完整 413 行 `ci.yaml` 可复原。
   - What's unclear: 是"复原完整 CI（server/web/runner/task/docs 多 job + security-scan + commit-message）"还是"只建一个聚焦 server+Postgres 的最小 workflow"。
   - Recommendation: 建最小聚焦 workflow（server-ci + postgres service），避免在本阶段顺带恢复无关的 web/runner/docs job；与 maintainer 确认是否要顺带恢复其余。

2. **stalled rescue 的 CI 可验证形态**
   - What we know: `get_stalled_jobs` 基于 worker heartbeat（30s 默认）。
   - What's unclear: CI 内能否真实 kill 一个 worker 并等心跳过期（耗时）。
   - Recommendation: postgres_queue 测试用受控 heartbeat 行 + 直接调 `get_stalled_jobs/retry_job` 验证语义；真实 kill-worker 留人工/容器 E2E（标 human_needed）。

3. **既有 `runapscheduler` 9 个 cron job 的去向**
   - What we know: 本阶段只立 rescue 闭环，不迁移业务任务。
   - What's unclear: 现有 cron（session timeout/cache/poll repo updates 等）是否本阶段就迁到 procrastinate periodic。
   - Recommendation: 本阶段**保留** `runapscheduler` 原样（仅新增 durable rescue），cron 迁移留 Phase 63（DEPLOY-02 scheduler workload）。CONTEXT 范围支持此解读。

## Sources

### Primary (HIGH confidence)
- procrastinate 官方文档 `procrastinate.readthedocs.io/en/stable/howto/django/configuration.html`、`.../django/basic_usage.html`、`.../advanced/cron.html`、`.../advanced/queueing_locks.html`、`.../production/retry_stalled_jobs.html` — Django 集成 / worker / periodic / queueing_lock / stalled rescue
- PyPI `pypi.org/project/procrastinate` — 3.8.1 版本/日期/Python·PG 约束
- GitHub `procrastinate-org/procrastinate` commit `abb121b`、release `3.8.1` — `get_worker_connector` 行为
- 仓库源码：`server/resumable/*`、`server/services/background_runner.py`、`server/friday/settings.py`、三处 `apps.py`、`server/agents/management/commands/runapscheduler.py`、`server/pyproject.toml`、`server/uv.lock`、`server/tests/conftest.py`
- git 历史 `5579e45f2`（CI workflow 删除证据）

### Secondary (MEDIUM confidence)
- WebSearch「procrastinate 3.8.1 Django connector get_worker_connector」聚合结果（已与官方 commit/docs 交叉验证）

### Tertiary (LOW confidence)
- 无

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — 版本经 PyPI + uv.lock 双验证，与 PoC 一致
- Architecture: HIGH — Procrastinate Django 集成 + 既有 resumable/background_runner 范式均经源码/官方文档确认
- Pitfalls: HIGH — addopts/socket/CI-deleted 均经仓库实证
- CI（DURABLE-04）: MEDIUM — workflow 须从零建，范围待与 maintainer 确认（Open Q1）

**Research date:** 2026-06-20
**Valid until:** 2026-07-20（procrastinate 稳定；若升级 3.9+ 复核 get_stalled_jobs/connector API）

