# Phase 60: durable 底座地基 - Context

**Gathered:** 2026-06-20
**Status:** Ready for planning
**Mode:** Smart discuss (autonomous — 灰区默认值已按里程碑锁定约束自动采纳)

<domain>
## Phase Boundary

立起统一 durable 任务底座，作为 v0.12.0 所有后续阶段的地基。本阶段交付三件事：

1. **`DurableTaskService` 适配层**：隔离队列实现，业务代码不直接 import Procrastinate。Postgres → Procrastinate 3.8.1；SQLite / 无 `DATABASE_URL` → in-process 非 durable fallback。统一接口 `defer / get / cancel / retry_stalled`（含 `idempotency_key` + `queue` + `priority` + `run_at`）。
2. **进程角色门禁**：`FRIDAY_PROCESS_ROLE=web|worker|scheduler|migrate|test`，收口 `repositories.apps` / `codegraph.apps` / `resumable.apps` 的 `AppConfig.ready()` 启动副作用，避免 worker/migrate 进程跑 web-only reconcile/sweep。
3. **周期 rescue / leader 单例**：内置 `retry_stalled_durable_jobs`，经 `queueing_lock` 单例 leader 扫 stalled 重投，替代 flock 与"仅启动补扫"。
4. **Postgres 专项 CI**：GH Actions service container + `postgres_queue` marker，与默认 SQLite 路径共存。

**不在本阶段范围内**：迁移 index/graph（Phase 61）、爬取队列（Phase 62）、部署硬化/fencing（Phase 63）、runner k8s（Phase 64）。本阶段只立底座 + 一条最小可验证的 stalled rescue 闭环，不迁移任何现有业务任务。

</domain>

<decisions>
## Implementation Decisions

### 队列后端与适配层（DURABLE-01）
- 采用 **Procrastinate 3.8.1**，藏在 `DurableTaskService` 适配层后；业务代码绝不直接 import Procrastinate。
- 后端选择点（**唯一权威判定** `durable.service._use_procrastinate(engine, backend)`，service 与 settings 共用同一函数）：当且仅当 默认 DB 引擎含 `postgresql` 且 `DURABLE_TASK_BACKEND ∈ {auto, procrastinate}` → Procrastinate（durable）；否则 → in-process 非 durable fallback。默认 `DURABLE_TASK_BACKEND=auto`。真值表：`auto`+Postgres → Procrastinate（**production 默认即 durable，开箱即用**）；`auto`+SQLite/无 `DATABASE_URL` → fallback（dev 开箱即用，`make dev`/pytest 不需 Postgres）；`procrastinate`+Postgres → Procrastinate；`procrastinate`+非 Postgres → fail-soft 回退 fallback + warning（不启动期 raise）；`inprocess`/`fallback` → 强制 fallback（即便 Postgres）。
  - **Amended note（autonomous reconciliation）：** 原讨论稿曾写"`auto` 仅在显式 `=procrastinate` 时才启用"，与"production 默认 Postgres 应开箱即 durable"矛盾；规划阶段自主校正为上述 `auto`+Postgres→durable 语义，并令 settings.py 的 `procrastinate.contrib.django` 条件注册复用同一 `_use_procrastinate`，确保 procrastinate 表仅在后端真正启用时创建（无 orphan `procrastinate_jobs` 表）。CONTEXT 与 Plan 60-01/60-03 据此一致。
- 统一接口签名：`defer(task, payload, *, queue, priority, idempotency_key, run_at) / get / cancel / retry_stalled`。
- worker 必须**独立进程**：用 `get_worker_connector()` / 官方 management command，绝不直接拿 `DjangoConnector` 跑 worker（PoC 硬前置①）。
- 先 `listen_notify=False` polling（低延迟唤醒留 v2 DURABLEX-01）。
- 一个底座、多条逻辑队列（index/graph/crawl_ingest/page_index/maintenance），本阶段先定义队列命名常量，实际接入由后续阶段消费。

### 进程角色门禁（DURABLE-02）
- 新增 `FRIDAY_PROCESS_ROLE` 环境变量（默认 `web`，保持既有单进程部署零回归）。
- 收口 `repositories.apps` / `codegraph.apps` / `resumable.apps` 三处 `AppConfig.ready()` 的启动副作用：仅 `role in {web}`（或显式允许集）才执行 reconcile/sweep/startup jobs；worker/migrate/test 角色短路跳过。
- 收口必须先于 Phase 61 迁移（PoC 硬前置③：否则 worker/migrate 进程会跑业务 reconcile 误杀在途任务）。
- 短路时记一条 info 级日志（角色 + 跳过的 job 名），不静默。

### 周期 rescue 与 leader 单例（DURABLE-03）
- 内置 `retry_stalled_durable_jobs` 周期任务，调 `get_stalled_jobs()` + `retry_job()`。
- 经 Procrastinate `queueing_lock` 实现单例 leader：多副本下只有一个 leader 执行周期 rescue 与单例 cron。
- 弃用 `runapscheduler` 的本地 `flock`（仅单机有效、跨 Pod 失效）。
- "慢≠死" 误判风险：rescue 仅对真正 stalled（超租约/心跳）的 job 重投；执行语义明确 **at-least-once，不承诺 exactly-once**。

### 测试与 CI（DURABLE-04）
- 新增 pytest `postgres_queue` marker；标记的测试需真实 Postgres（GH Actions service container `postgres:17-alpine`）。
- 默认 job 仍走 SQLite（marker 分层，不强制本地装 Postgres）。
- Postgres CI 覆盖：defer / priority / retry-backoff / stalled rescue / 并发 worker 竞争 / SQLite fallback 退化路径。
- 复用 `server/tests/conftest.py` 既有 adrf monkeypatch + pytest-socket 约束。

### Claude's Discretion
- `DurableTaskService` 的具体模块落点（建议新建 `server/durable/` app，镜像 `server/resumable/` 结构：`service.py` / `apps.py` / `tasks.py` / `management/`）。
- 队列名常量、idempotency_key 冲突时的语义（Procrastinate `queueing_lock` vs 业务级 dedup）的精确实现。
- fallback in-process executor 的线程模型（建议复用 `server/services/background_runner.py` 既有 daemon-thread runner）。
- Procrastinate app/connector 的 Django settings 装配方式与 migration 注入顺序。

</decisions>

<code_context>
## Existing Code Insights

### Reusable Assets
- `server/resumable/`（`service.py` / `models.py` / `locks.py` / `recovery.py` / `handlers.py` / `apps.py` / `management/`）— lease/CAS/recovery 范式，`DurableTaskService` 结构镜像此 app。
- `server/services/background_runner.py` — 既有 daemon-thread 后台 runner，作 in-process fallback 基础。
- `server/friday/settings.py:243` 附近 — `DATABASE_URL` / 数据库配置解析点（后端选择判定）。
- `docker-compose.yaml:37` 附近 — Postgres 默认部署声明（worker workload 拆分由 Phase 63 做，本阶段不动 compose）。
- `server/tests/conftest.py` — adrf patch + pytest 约束；新 `postgres_queue` marker 注册点。

### Established Patterns
- Django app = bounded context，各自 `apps.py` `AppConfig.ready()` 装配启动副作用（本阶段收口对象）。
- 异步 ORM 经 `asgiref.sync_to_async` 桥接；worker 进程独立事件循环。
- 凭证/设置经 `SystemSetting`/`SettingKeys`，env 经 `django-environ`。

### Integration Points
- `INSTALLED_APPS`（注册新 `durable` app）。
- `AppConfig.ready()` × 3（repositories/codegraph/resumable 角色门禁）。
- pytest marker 注册（`pyproject.toml [tool.pytest.ini_options] markers` + conftest）。
- GH Actions `.github/workflows/ci.yaml`（新增 Postgres service job）。

</code_context>

<specifics>
## Specific Ideas

- PoC 已 PASS（Procrastinate 3.8.1 / Python 3.14 / Django 6.0 / psycopg 3.3，adrf `defer_async`、worker queue/priority/periodic/retry/stalled rescue 实测 PASS）— 研究阶段应核对当前仓库实际 Django/psycopg 版本与 PoC 一致性。
- 本阶段验收的 stalled rescue 闭环：kill 一个 worker → 另一 worker 经周期 leader rescue 接管在途 stalled 任务重投。
- 进程角色门禁验收：`FRIDAY_PROCESS_ROLE=worker|migrate` 进程启动无"业务表不存在"warning、不误杀在途任务。

</specifics>

<deferred>
## Deferred Ideas

- `listen_notify=True` 低延迟唤醒 → v2 DURABLEX-01。
- exactly-once 语义 → 显式非目标。
- 迁移现有 index/graph/crawl 任务 → Phase 61/62。
- 部署硬化（优雅终止 / compose·helm 拆 workload / KEDA / PDB）→ Phase 63。
- 外部副作用 fencing/outbox → Phase 63（IDEMP-02）。

</deferred>

---

*Phase: 60-durable*
*Context gathered: 2026-06-20 via smart discuss (autonomous)*
