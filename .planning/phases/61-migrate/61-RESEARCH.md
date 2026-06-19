# Phase 61: 迁移 index/graph + 收口 ResumableTask - Research

**Researched:** 2026-06-20
**Domain:** durable 任务队列迁移（适配层接入）、一次性数据迁移命令、at-least-once 幂等、启动 reconcile 安全语义
**Confidence:** HIGH（全部基于 Phase 60 已交付源码 + 既有 resumable/index/graph 代码实读，零外部依赖新增）

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

**接入 durable queue（MIGRATE-01）**
- 入队入口统一改 `DurableTaskService.defer`，queue 用 Phase 60 的 `queues.QUEUE_INDEX` / `QUEUE_GRAPH` 常量；`idempotency_key` 用 deterministic `index:{repo_id}` / `graph:{repo_id}`（同 repo 在途去重，避免重复入队）。
- `IndexHistory` / `GraphBuildHistory` 继续作进度/结果真相源——durable job 只负责"驱动执行"，进度/状态仍写既有 History 表（不另造状态源）。
- FileIndex / GraphFileIndex 的 checkpoint「已处理跳过」逻辑原样保留（at-least-once 重跑的幂等基础）。
- 三处入队点（`repositories/views.py`、`tasks/index_trigger_tasks.py`、`resumable/handlers.py`）全部收口；保留 chat/RAG 流式问答不进队列的边界（仅迁 index/graph 后台任务）。

**一次性迁移（MIGRATE-02）**
- 新增一次性 management command（如 `migrate_resumable_to_durable`）：扫描 PENDING/RUNNING 的 index/graph `resumable_tasks`，按 deterministic idempotency key `defer` 成 durable job，旧行标 `migrated`（或 cancelled）并记 `legacy_durable_job_id`——**不双跑**（迁过的旧行不再被 background_runner/recovery 重驱）。
- 幂等可重入：command 重复执行不产生重复 durable job（deterministic key + 旧行状态判定）。
- 命令 SQLite dev 下安全降级（无 durable 后端时给清晰提示或转 in-process，不报错崩溃）。

**启动 reconcile 安全语义（MIGRATE-02）**
- `repositories.apps` / `codegraph.apps` 的启动 reconcile（Phase 60 已加角色门禁）进一步改判定：RUNNING 行**仅当确认无 durable job 接管**时才标 FAILED；有对应在途 durable job 则保留 RUNNING，绝不误杀。
- `background_runner` 降级为仅 SQLite dev fallback / 少量非持久轻任务——生产 durable 任务不再 ResumableTask/background_runner/Procrastinate 三套并存。

**handler 幂等基线（IDEMP-01）**
- index / graph（+ page_index 占位 handler）实现 at-least-once 幂等：checkpoint（已处理跳过）+ deterministic key + upsert，重复执行结果一致。
- 守护测试：同一任务重复投递 → 单次有效执行；重复执行 → 不产生重复数据 / 重复副作用（断言 History 行数、索引产物去重）。

### Claude's Discretion
- migration command 的精确名称、旧行终态枚举（migrated vs cancelled）、legacy id 字段落点（resumable_tasks 既有列 vs metadata JSON）。
- reconcile「确认无 durable job 接管」的查询实现（按 idempotency_key 查 durable job 状态）。
- page_index 幂等基线在本阶段做到何种程度（占位 handler + 测试 vs 仅接口预留）——倾向占位 handler + 幂等测试，实际接入留 Phase 62。

### Deferred Ideas (OUT OF SCOPE)
- 爬取+入库 durable 队列 + 前端面板 → Phase 62。
- PageIndex/TOC/summary/tree 实际接入 durable queue → Phase 62 PAGEIDX-01（本阶段仅幂等基线）。
- 外部副作用（飞书通知/建群、MR/PR）fencing/outbox → Phase 63 IDEMP-02。
- runapscheduler cron 迁移 → Phase 63。
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| MIGRATE-01 | index/graph 入队点改 `DurableTaskService.defer`（queue=index/graph，`idempotency_key=index:{repo_id}`/`graph:{repo_id}`），History 仍为真相源，FileIndex/GraphFileIndex checkpoint 保留 | §"接入点全清单"（**5 处**实际入队点，CONTEXT 仅列 3）+ §"durable 任务注册双后端契约" + §"幂等基础已就位" |
| MIGRATE-02 | 一次性 migration command 把存量 PENDING/RUNNING resumable_tasks 转 durable job（不双跑，旧行标 migrated/cancelled 记 legacy id）；reconcile 改"仅无 durable 接管才标 FAILED"；background_runner 降级 | §"迁移命令设计" + §"reconcile 安全语义改造" + §"三系统收口" |
| IDEMP-01 | index/graph/page_index handler at-least-once 幂等（checkpoint/deterministic key/upsert），守护测试覆盖重复投递/重复执行不产生重复数据/副作用 | §"at-least-once 幂等分层" + §"Validation Architecture" |
</phase_requirements>

## Summary

Phase 60 已交付完整的 `DurableTaskService` 适配层（`server/durable/`）：`defer/get/cancel/retry_stalled` 门面、Postgres→Procrastinate / SQLite→in-process 双后端、队列常量、进程角色门禁、周期 stalled rescue、Postgres CI。**本阶段是纯"消费 + 迁移"工作，不引入任何新外部依赖、不新增 Django 模型**（除非选择给 `ResumableTask` 加 `legacy_durable_job_id` 列——可用既有 `payload` JSON 列规避 migration）。

核心是把 index/graph 后台任务从 `wrap_resumable + run_in_background` 范式切到 `DurableTaskService.defer(task=<逻辑名>, payload, queue=..., idempotency_key=...)`，并新建一次性迁移命令把存量在途行平滑转入 durable 队列。**幂等基础大部分已就位**：`FileIndex`（`uq_repo_file_path`）/ `GraphFileIndex`（`uq_graph_repo_branch_file`）的文件级 hash checkpoint、`build_graph_for_repository(skip_unchanged=True)`、`_acreate_auto_graph_history` 的并发去重，都已是 at-least-once 安全设计。本阶段主要补"deterministic idempotency_key 入队去重"+"守护测试证明重复投递/执行不产生重复数据"。

**三个最高风险点**（全部源自"不三套并存"目标）：① 迁移命令必须 deterministic-key + 旧行终态判定确保**不双跑**；② reconcile 改判定必须在标 FAILED 前查 durable job 状态，确保**不误杀在途**；③ 两个后端（procrastinate `defer_async(**payload)` 展开 vs in-process `handler(payload)` 整体传参）的**入参约定不一致**——这是实读源码发现的、CONTEXT 未提及的关键陷阱，必须用 adapter 统一。

**Primary recommendation:** 在 `durable/tasks.py` 新增 `@app.task(name="durable_index"/"durable_graph"/"durable_page_index", queue=...)` 三个任务（procrastinate 路径），同时在 `durable/backends.py` 用 `register_handler` 注册**展开 adapter**（in-process 路径），令两后端入参一致；入队点全部改 `DurableTaskService.defer`；migration command + reconcile 改判定按 deterministic key `index:{repo_id}`/`graph:{repo_id}` 收口。

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| index/graph 入队 | API/Backend（views/trigger） | — | REST/webhook/scheduler 触发，请求级薄入队后立即返回 |
| 任务执行驱动 | Worker（durable）/ background_runner（dev fallback） | — | 长任务，多副本竞争消费；dev 无 Postgres 退化 in-process |
| 进度/状态真相源 | Database（IndexHistory/GraphBuildHistory） | — | CONTEXT 锁定：durable job 只驱动，状态写既有 History 表 |
| 文件级 checkpoint（幂等基础） | Database（FileIndex/GraphFileIndex） | — | 已处理 hash 未变跳过，at-least-once 重跑安全 |
| 一次性存量迁移 | Migrate role（management command） | — | 升级期单次执行，幂等可重入，SQLite dev 安全降级 |
| 启动 reconcile（误杀防护） | Web role（AppConfig.ready） | Database（durable job 查询） | Phase 60 已角色门禁；本阶段改判定逻辑 |

## Standard Stack

**本阶段不新增任何外部库。** 全部基于 Phase 60 已落地的 durable 适配层 + 既有 resumable/repositories/codegraph 代码。

### Core（已存在，本阶段消费）
| 组件 | 位置 | 用途 | 现状 |
|------|------|------|------|
| `DurableTaskService` | `server/durable/service.py:75` | 统一入队门面 `defer/get/cancel/retry_stalled` | ✅ 已交付（Phase 60） |
| 队列常量 `QUEUE_INDEX`/`QUEUE_GRAPH`/`QUEUE_PAGE_INDEX` | `server/durable/queues.py:11-17` | 逻辑队列命名 | ✅ 已声明 |
| `@app.task` 任务注册 | `server/durable/tasks.py` | procrastinate 路径任务定义（仅 `durable_ping`/`retry_stalled_durable_jobs`） | ⚠️ 需新增 index/graph/page_index 任务 |
| `register_handler` | `server/durable/backends.py:75` | in-process fallback 任务注册表（`_handlers`） | ⚠️ 当前无业务任务注册，需补 |
| `DurableConfig.ready()` | `server/durable/apps.py:15` | 条件 import `durable.tasks` 触发注册 | ✅ 已就位（需确保新任务被同一路径注册） |
| `IndexHistory`/`GraphBuildHistory` | `server/repositories/models.py:378,494` | 进度/结果真相源 | ✅ 保持不变 |
| `FileIndex`/`GraphFileIndex` | `server/repositories/models.py:557,600` | 文件级 hash checkpoint（幂等基础） | ✅ 保持不变 |
| `ResumableTask` | `server/resumable/models.py:38` | 迁移源（存量在途行） | ✅ 迁移后旧行标终态 |

### Supporting（迁移源 / 参考范式）
| 组件 | 位置 | 用途 |
|------|------|------|
| `wrap_resumable` / `submit_resumable` | `server/resumable/service.py:195,256` | **被替换对象**——心跳/租约/终态收尾范式（durable 自带 heartbeat，无需移植） |
| `recoverable_target_ids` | `server/resumable/recovery.py:94` | 现 reconcile 排除集来源——本阶段改为"查 durable job" |
| `recover_tasks` command | `server/resumable/management/commands/recover_tasks.py` | management command 写法参考 |
| `clone_and_index_repository` | `server/services/indexer.py:3622` | index handler 实体（durable 任务体调用） |
| `build_graph_for_repository` | `server/services/graph_builder.py:323` | graph handler 实体 |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| 给 `ResumableTask` 加 `legacy_durable_job_id` 列（migration 0002） | 复用既有 `payload` JSON 列写 `{"migrated_durable_job_id": ...}` | 加列更清晰可查、可加索引；JSON 列零 migration、SQLite dev 更省事。CONTEXT 列为 Claude's Discretion。**建议加列**（migration 简单、可观测性强，且本阶段反正要动 status 语义） |
| 新建 `ResumableTaskStatus.MIGRATED` 枚举值 | 复用既有 `CANCELLED` | 新枚举语义清晰（区分"用户取消"vs"系统迁移"），但需 migration 改 choices（choices 改不强制 migration，仅 DB CharField 无约束）。**建议加 `MIGRATED`**——审计/排障可区分 |
| 在 `durable/tasks.py` 写 index/graph 任务体 | 在 `repositories`/`codegraph` 各自模块写任务、durable 仅注册 | procrastinate `@app.task` 必须在 `durable.tasks`（no-direct-import 守护允许清单仅 `backends.py`/`tasks.py`/`management/`）。**任务壳放 `durable/tasks.py`，任务体 import 既有 service 函数**（最小耦合） |

**Installation:** 无（procrastinate 已于 Phase 60 落 `server/pyproject.toml`，`uv.lock` 锁 3.8.1）。

## Package Legitimacy Audit

> **本阶段不安装任何外部包**——纯内部代码迁移。`procrastinate[django]>=3.8.1,<3.9` 已于 Phase 60 Plan 01 落地并锁定（`server/uv.lock`），无新增/变更依赖。

| Package | Registry | Disposition |
|---------|----------|-------------|
| （无新增） | — | N/A — 本阶段零依赖变更 |

**Packages removed due to slopcheck [SLOP] verdict:** none
**Packages flagged as suspicious [SUS]:** none

## Architecture Patterns

### System Architecture Diagram

```text
                          ┌─────────────────── 触发入口（5 处入队点）───────────────────┐
  REST 手动索引 ──────────►│ index_views._schedule_index (index_views.py:141)            │
  默认分支滚动 ───────────►│ views._schedule_default_branch_rolling_index (views.py:357) │
  webhook/scheduled ─────►│ index_trigger_tasks.trigger_auto_index (tasks/...:123)      │ kind=INDEX
  REST 手动图谱 ──────────►│ codegraph/views CodegraphRebuildView (views.py:712)         │ kind=GRAPH
  recovery 续驱 ──────────►│ resumable/handlers.resume_index/resume_graph (handlers.py)  │
                          └────────────────────────────┬───────────────────────────────┘
                                                        │ 现状: run_in_background(wrap_resumable(...))
                                                        │ 改造: DurableTaskService.defer(
                                                        │         task="durable_index"/"durable_graph",
                                                        │         payload={repository_id, branch, trigger, history_id},
                                                        │         queue=QUEUE_INDEX/QUEUE_GRAPH,
                                                        │         idempotency_key="index:{repo_id}"/"graph:{repo_id}")
                                                        ▼
                          ┌──────────── DurableTaskService.defer (service.py:82) ────────────┐
                          │  use_procrastinate_backend()?                                     │
                          │    Postgres + backend∈{auto,procrastinate}  ──► ProcrastinateBackend
                          │    SQLite / 无 DATABASE_URL                  ──► InProcessBackend  │
                          └───────────────┬───────────────────────────────────┬──────────────┘
                                          │ (Postgres)                         │ (SQLite dev)
                                          ▼                                    ▼
                  procrastinate_jobs 表（durable）              background_runner daemon loop（非 durable）
                  worker 独立进程消费 (run_worker)              _handlers[task](payload) 进程内执行
                                          │                                    │
                                          │  defer_async(**payload) 展开        │  handler(payload) 整体传
                                          │  ⚠️ 入参约定不一致 → adapter 统一    │
                                          ▼                                    ▼
                          ┌──────── 任务体（durable/tasks.py @app.task name=...）────────┐
                          │  durable_index  → clone_and_index_repository(history_id=...)  │
                          │  durable_graph  → build_graph_for_repository(skip_unchanged)  │
                          │  durable_page_index → 占位 handler（Phase 62 实接）            │
                          └──────────────────────────┬───────────────────────────────────┘
                                                     │ 写进度/结果（真相源不变）
                                                     ▼
                  IndexHistory / GraphBuildHistory (RUNNING→COMPLETED/FAILED)
                  FileIndex / GraphFileIndex (hash checkpoint：已处理跳过 ← 幂等基础)

  ┌───────────── 启动 reconcile（仅 web role，apps.ready）────────────┐
  │ repositories.apps._reset_stuck_indexing (apps.py:34)              │
  │ codegraph.apps.reconcile_orphaned_graph_builds (apps.py:10)       │
  │ 现状: 排除 recoverable_target_ids(kind) 的 RUNNING 行             │
  │ 改造: 排除"有在途 durable job (DurableTaskService.get by key)"的行 │ ← 不误杀在途
  └──────────────────────────────────────────────────────────────────┘

  ┌───────────── 一次性迁移命令（migrate role / 运维）────────────────┐
  │ migrate_resumable_to_durable (新建 management command)            │
  │  扫 PENDING/RUNNING resumable_tasks(kind∈{index,graph})           │
  │  → DurableTaskService.defer(deterministic key) → 旧行标 MIGRATED  │
  │  → 记 legacy_durable_job_id；幂等可重入；SQLite 安全降级          │ ← 不双跑
  └──────────────────────────────────────────────────────────────────┘
```

### 接入点全清单（⚠️ CONTEXT 列 3 处，实读源码为 5 处）

> **关键发现：planner 必须迁移全部 5 处入队点，否则残留旁路 = 三套并存未真正收口。** CONTEXT/REQUIREMENTS 文案只点了 `repositories/views.py`、`tasks/index_trigger_tasks.py`、`resumable/handlers.py`，但 grep `wrap_resumable|submit_resumable` 实测命中 5 个生产入队点（外加 recovery 续驱）。

| # | 文件:行 | 函数 | kind | 现状调用 | payload 现状 | 触发场景 |
|---|---------|------|------|----------|-------------|----------|
| 1 | `repositories/index_views.py:141` `_schedule_index` | `_schedule_index` | INDEX | `run_in_background(wrap_resumable(...))` | `{repository_id, branch, trigger}` + `coro_factory=clone_and_index_repository(history_id, branch)` | REST 手动索引 |
| 2 | `repositories/views.py:393` `_schedule_default_branch_rolling_index` | 默认分支滚动重索引 | INDEX | `run_in_background(wrap_resumable(...))` | `{repository_id, branch:None, trigger:"manual"}` + `coro_factory=clone_and_index_repository(history_id)` | 默认分支变更 |
| 3 | `tasks/index_trigger_tasks.py:174` `trigger_auto_index` | webhook/scheduled 自动索引 | INDEX | `run_in_background(wrap_resumable(...))` | `{repository_id, branch:None, trigger:tt}` + `coro_factory=clone_and_index_repository(history_id)` | webhook push / 定时轮询 |
| 4 | `codegraph/views.py:712` `CodegraphRebuildView` | 手动图谱重建 | GRAPH | `run_in_background(wrap_resumable(...))` | `{repository_id, branch, trigger:MANUAL}` + `coro_factory=build_graph_for_repository(history_id, branch)` | REST 手动图谱 |
| 5 | `resumable/handlers.py:58,108` `resume_index`/`resume_graph` | recovery 续驱 | INDEX/GRAPH | `submit_resumable(...)` | 从 `ResumableTask.payload` 重建 | RecoveryScheduler 启动续跑 |

**说明：**
- **#5（resumable/handlers.py）的处置取决于"三套收口"策略**：迁移后生产 index/graph 不再产生新的 `ResumableTask` 行（入队点 1-4 改走 durable），故 recovery 续驱路径会自然枯竭。建议：保留 `register_default_handlers` 但让 resume handler 改走 `DurableTaskService.defer`（与入队点同源），或干脆在 reconcile 改判定后让 recovery 对 index/graph kind 短路（durable 自有 stalled rescue 接管续跑职责）。**推荐前者**——resume handler 也改 defer，单一驱动入口。
- **auto_after_index 图谱不是独立入队点**：图谱在索引完成后由 `indexer` **进程内同步**触发（`_acreate_auto_graph_history` `services/indexer.py:832`，非 `submit_resumable`）。一旦 index 成为 durable 任务，auto_after_index 图谱在该 durable 任务体内执行，**无需单独迁移**。graph 队列主要承接入队点 #4（手动重建）与 #5（graph resume）。
- **chat/RAG 流式问答不在此列**（CONTEXT 锁定边界，请求级不进队列）。

### Pattern 1: durable 任务注册——双后端入参契约统一（⚠️ 实读源码发现的关键陷阱）

**What:** procrastinate 后端与 in-process 后端对 payload 的传参约定**不一致**，必须用 adapter 抹平。

**证据（实读源码）：**
- ProcrastinateBackend.defer：`await deferrer.defer_async(**payload)`（`backends.py:249`）——payload **展开为 kwargs**。测试印证：`defer("durable_ping", {"payload": {"k":"v"}})` → 任务 `durable_ping(payload={"k":"v"})`（`test_procrastinate_backend.py:38`，任务签名 `tasks.py:25` `durable_ping(payload=None)`）。
- InProcessBackend._run_job：`result = await handler(payload)`（`backends.py:151`）——payload **整体作单个 dict 传入**。

**结论：** 若同一个 async 函数既注册为 `@app.task` 又注册为 in-process `register_handler`，两后端调用方式不同会炸。

**When to use:** 每个新 durable 业务任务（index/graph/page_index）都必须处理。

**推荐做法（adapter 统一为"显式 kwargs"约定）：**
```python
# durable/tasks.py —— procrastinate 路径（仅 Postgres+backend 启用时 import）
@app.task(name="durable_index", queue=QUEUE_INDEX)
async def durable_index(
    *, repository_id: str, history_id: str | None = None,
    branch: str | None = None, trigger: str = "manual",
) -> dict:
    from services.indexer import clone_and_index_repository
    # History 真相源不变；checkpoint 由 FileIndex 跳过已处理文件
    return await clone_and_index_repository(repository_id, history_id=history_id, branch=branch)

# durable/backends.py 或一个被所有路径 import 的模块 —— in-process 注册 adapter
# 关键：用 **payload 展开，与 procrastinate defer_async(**payload) 对齐
def _register_business_handlers() -> None:
    async def _index_adapter(payload: dict):
        from durable.tasks_impl import run_index  # 任务体抽到不依赖 procrastinate 的模块
        return await run_index(**payload)
    register_handler("durable_index", _index_adapter)
```
- **defer 调用方统一传"显式 kwargs payload"**：`defer("durable_index", {"repository_id": rid, "history_id": hid, "branch": None, "trigger": "manual"}, queue=QUEUE_INDEX, idempotency_key=f"index:{rid}")`。
- procrastinate：`defer_async(repository_id=rid, ...)` ✓；in-process adapter：`run_index(**payload)` ✓ —— 一致。
- **任务体（实际业务逻辑）建议抽到一个不 import procrastinate 的模块**（如 `durable/tasks_impl.py`），`durable/tasks.py` 的 `@app.task` 与 in-process adapter 都 import 它——单一实现，no-direct-import 守护放行（impl 不碰 procrastinate）。⚠️ planner 须确认该新模块是否需进 no-direct-import 允许清单（不需要，因为它不 import procrastinate）。

### Pattern 2: deterministic idempotency_key 去重入队

**What:** 同一 repo 在途任务用 `index:{repo_id}` / `graph:{repo_id}` 作 `idempotency_key`，重复入队自动去重。

**机制（已就位）：**
- Procrastinate：`idempotency_key` → `queueing_lock`（`backends.py:243`），同 key 在 `todo` 状态唯一；命中 `AlreadyEnqueued` 按幂等吞并返回既有 job id（`backends.py:250-261`）。
- In-process：`idempotency_key` 直接用作 `background_runner` 的 `name`，同 key 覆盖同名注册（`backends.py:109`）。

**When to use:** 全部 5 处入队点。注意现有"防重复入队"逻辑（`trigger_auto_index` 的 `already_indexing` 检查 `tasks/index_trigger_tasks.py:143`、`_acquire_index_lock` `select_for_update` `index_views.py:131`）与 deterministic key 是**互补**——前者业务层防抖、后者队列层去重；保留前者，叠加后者。

### Pattern 3: reconcile 改"查 durable job 接管"判定

**What:** 启动 reconcile 标 RUNNING→FAILED 前，先查该 repo 是否有在途 durable job；有则保留 RUNNING。

**现状（Phase 60 已加 role 门禁 + recoverable 排除）：**
- `repositories/apps.py:48-59`：排除 `recoverable_target_ids(ResumableTaskKind.INDEX)` 的 repo。
- `codegraph/apps.py:52-66`：排除 `recoverable_target_ids(ResumableTaskKind.GRAPH)` 的 repo。

**改造方向：** 把"查 ResumableTask RUNNING"换成"查 durable job 状态"。判定 helper（建议放 `durable/service.py` 或新 `durable/reconcile.py`）：
```python
async def has_active_durable_job(idempotency_key: str) -> bool:
    """idempotency_key 对应 durable job 是否在途（todo/doing/scheduled）。"""
    # Procrastinate: list_jobs_async(queueing_lock=key, status in {todo,doing})
    # In-process: get(job_id=key) status in {pending,running}
```
- ⚠️ **同步上下文问题**：reconcile 跑在 `AppConfig.ready()` 的 daemon 线程（同步），而 `DurableTaskService` 全异步。需 `async_to_sync` 包装，或提供同步查询入口。`recoverable_target_ids` 当前是同步 ORM（`recovery.py:100`）。建议给判定 helper 同步 + 异步双版本（对齐 resumable/service.py 范式 `service.py:168`）。
- ⚠️ **`get()` 对 in-process 的局限**：in-process job 状态仅进程内可见、重启即丢（`backends.py:70`）。SQLite dev 下重启后 `get()` 返回 `unknown`——此时 reconcile 标 FAILED 是正确的（非 durable，本就不承诺续跑）。Postgres 下 `procrastinate_jobs` 持久，查询可靠。判定语义：**仅 durable 后端（Postgres）才"保留 RUNNING"，in-process fallback 维持旧"标 FAILED"行为**——与"SQLite 非 durable"约束一致。

### Pattern 4: 一次性迁移命令（不双跑 + 幂等可重入）

**What:** 扫描存量 `ResumableTask(kind∈{index,graph}, status∈{PENDING,RUNNING})`，按 deterministic key defer durable job，旧行标终态记 legacy id。

**幂等可重入设计：**
1. deterministic key `index:{target_id}`/`graph:{target_id}` → 重复 defer 命中 `AlreadyEnqueued` 自动去重（不产生重复 durable job）。
2. 旧行状态判定：只处理 `status∈{PENDING,RUNNING}` 的行；处理后置 `MIGRATED`（或 `CANCELLED`）。重跑命令时已 MIGRATED 的行不再进扫描集 → 不重复 defer。
3. **不双跑保障**：旧行标 MIGRATED 后，`recoverable_target_ids` 只返回 `status=RUNNING` 的行（`recovery.py:102`），MIGRATED 行天然被排除，recovery/reconcile 都不再驱动它。

**SQLite dev 安全降级：** 命令开头判 `use_procrastinate_backend()`：
- Postgres → 正常 defer durable job。
- SQLite/无 DATABASE_URL → in-process fallback 非 durable，迁移意义有限。**建议给清晰提示**（"当前为非 durable 后端，存量行将转 in-process（重启即丢）/ 或跳过"），不报错崩溃（对齐 `use_procrastinate_backend` fail-soft 范式 `service.py:48`）。

**命令骨架（参考 `recover_tasks.py` 风格 + `async_to_sync`）：**
```python
class Command(BaseCommand):
    help = "一次性把存量 PENDING/RUNNING index/graph resumable_tasks 迁移到 durable 队列"
    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true")
    def handle(self, *args, **opts):
        # 1. 判后端；非 Postgres 给提示
        # 2. 扫 ResumableTask(kind in [index,graph], status in [pending,running])
        # 3. async_to_sync(DurableTaskService.defer)(task, payload, queue, idempotency_key=key)
        # 4. 旧行 .update(status=MIGRATED, payload={**payload, "legacy_durable_job_id": job_id})
        # 5. 打印 {scanned, migrated, skipped, dry_run}
```

### Recommended Project Structure（增量）
```
server/durable/
├── tasks.py            # 既有 + 新增 @app.task(name="durable_index"/"durable_graph"/"durable_page_index")
├── tasks_impl.py       # 新建：任务体（不 import procrastinate），@app.task 与 in-process adapter 共用
├── handlers.py         # 新建（或并入 backends/apps）：register_handler 注册 in-process adapter
├── reconcile.py        # 新建：has_active_durable_job 同步/异步判定 helper
└── management/commands/
    └── migrate_resumable_to_durable.py   # 新建：一次性迁移命令
server/resumable/
└── migrations/0002_*.py  # 可选：ResumableTask 加 legacy_durable_job_id 列 + MIGRATED 枚举
```

### Anti-Patterns to Avoid
- **只迁 CONTEXT 点名的 3 文件**：会漏 `index_views.py`、`codegraph/views.py` 两个生产入队点 → 三套并存未真正收口。**必须迁全 5 处**。
- **同一 async 函数直接双注册**（@app.task + register_handler）：两后端入参不一致会炸（见 Pattern 1）。必须用 adapter。
- **reconcile 用异步 `DurableTaskService.get` 而不包 `async_to_sync`**：`AppConfig.ready` daemon 线程是同步上下文，裸 await 会炸 / 拿不到结果。
- **迁移命令不判后端就 defer**：SQLite dev 下 in-process 非 durable，静默"迁移"成进程内任务重启即丢，误导运维。必须显式提示。
- **把进度状态写到 durable job payload/result 而非 History 表**：违反 CONTEXT"History 仍为真相源"。durable job 只驱动。
- **删掉 FileIndex/GraphFileIndex checkpoint 逻辑**：这是 at-least-once 幂等的命门，必须原样保留。

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| 任务重试 / stalled 重投 | 自写 lease/heartbeat/CAS（resumable 那套） | durable 后端自带（procrastinate heartbeat + `retry_stalled_durable_jobs` periodic，`tasks.py:41`） | Phase 60 已交付，多副本 leader 单例；移植 resumable 心跳=造第二套 |
| 入队去重 | 自写 in-flight set / DB 唯一约束 | `idempotency_key`→`queueing_lock`（`backends.py:243`） | 队列层原生去重 + `AlreadyEnqueued` 幂等吞并 |
| 文件级"已处理跳过" | 重写 hash 比较 | 既有 `FileIndex`/`GraphFileIndex` + `skip_unchanged=True`（`graph_builder` / `indexer`） | 已是 unique_together hash checkpoint，本就 at-least-once 安全 |
| 后端选择（Postgres/SQLite） | 在迁移命令/reconcile 内重判 engine | `use_procrastinate_backend()`（`service.py:48`，单一权威判定） | 禁止另写等价判据（Phase 60 锁定） |
| job 状态查询 | 直查 procrastinate_jobs 表 | `DurableTaskService.get(job_id)`（`service.py:115`） | 业务侧绝不直接 import procrastinate（no-direct-import 守护） |

**Key insight:** 本阶段几乎所有"难"问题（重试/心跳/去重/leader）Phase 60 已解决；真正要建的只是"接线 + 一次性迁移 + 守护测试"，切忌重造 durable 能力。

## Runtime State Inventory

> 本阶段含"迁移/收口"语义，需盘点存量运行态。

| Category | Items Found | Action Required |
|----------|-------------|------------------|
| Stored data（DB 行） | `resumable_tasks` 表中 `kind∈{index,graph}` 的 PENDING/RUNNING 行（升级前在途任务）；`db_table="resumable_tasks"` (`models.py:68`) | **数据迁移**：一次性命令 defer durable + 标 MIGRATED 记 legacy id（不双跑） |
| Stored data（checkpoint） | `file_indexes`（`uq_repo_file_path`）/ `graph_file_indexes`（`uq_graph_repo_branch_file`）；index/graph 进度真相 `IndexHistory`/`GraphBuildHistory` RUNNING 行 | **保留**：checkpoint 是幂等基础；孤儿 RUNNING History 行由改造后的 reconcile 安全收尾 |
| Live service config | 无外部服务存 index/graph 任务态（任务态全在 DB） | 无 |
| OS-registered state | `background_runner` 进程内 daemon 线程注册的任务（进程内存，重启即丢——这正是迁移动因） | **代码改造**：入队点改 defer，不再向 background_runner 注册生产 index/graph |
| Secrets/env vars | `DURABLE_TASK_BACKEND`（auto/procrastinate/inprocess）、`DATABASE_URL`、`FRIDAY_PROCESS_ROLE`（迁移命令建议 `migrate` role 跑）—— 全 Phase 60 已建，本阶段不改 | 无（消费既有） |
| Build artifacts | 无（纯 Python 代码改动，无编译产物） | 无 |

**The canonical question:** 升级后所有文件改完，仍有"旧 string/旧驱动器缓存/注册"的运行态？→ **存量 `resumable_tasks` 在途行**（迁移命令处理）+ **进程内 background_runner 注册的旧任务**（重启后自然消失，但升级窗口内可能有在途——故迁移命令 + reconcile 改判定双保险）。

## Common Pitfalls

### Pitfall 1: 双后端 payload 入参约定不一致
**What goes wrong:** index/graph 任务在 Postgres 下能跑、SQLite dev 下 `handler(payload)` 收到整个 dict 当单参，`run_index(**payload)` 反之——一边炸。
**Why it happens:** `defer_async(**payload)` 展开 vs `handler(payload)` 整传（`backends.py:249` vs `:151`）。
**How to avoid:** in-process 注册 adapter 用 `**payload` 展开调任务体（Pattern 1）。
**Warning signs:** SQLite 测试 `TypeError: run_index() takes ... positional argument` 或 Postgres 测试 `unexpected keyword argument`。

### Pitfall 2: reconcile 在同步 daemon 线程裸 await 异步 DurableTaskService
**What goes wrong:** `AppConfig.ready()` daemon 线程是同步上下文，调异步 `get()` 拿不到结果 / 抛 `SynchronousOnlyOperation` 链路异常。
**Why it happens:** durable 门面全异步；reconcile 历史是同步 ORM（`recovery.py:100`）。
**How to avoid:** 判定 helper 提供同步版（`async_to_sync` 包，对齐 `resumable/service.py:168` 同步+异步双版本）。
**Warning signs:** 启动期 reconcile 日志报 event loop / 协程未 await。

### Pitfall 3: 迁移命令在 SQLite dev 误"迁移"成进程内任务
**What goes wrong:** SQLite 下 defer 走 in-process，"迁移"出的任务重启即丢，运维误以为已转 durable。
**Why it happens:** 未判 `use_procrastinate_backend()` 就 defer。
**How to avoid:** 命令开头判后端，非 Postgres 给清晰中文提示（CONTEXT 锁定）。
**Warning signs:** SQLite 跑命令"成功迁移 N 条"但重启后任务全无。

### Pitfall 4: 漏迁 index_views.py / codegraph/views.py 两处入队点
**What goes wrong:** REST 手动索引/手动图谱仍走 wrap_resumable → 三套并存，生产仍产生 ResumableTask 行，迁移目标落空。
**Why it happens:** CONTEXT 只点名 3 文件，实际 5 处。
**How to avoid:** 按本研究"接入点全清单"迁全 5 处；用 grep `wrap_resumable|submit_resumable` 守护测试断言生产路径零残留。
**Warning signs:** 迁移后 grep 仍命中 index/graph 的 `wrap_resumable`。

### Pitfall 5: 重复投递产生重复 IndexHistory/GraphBuildHistory RUNNING 行
**What goes wrong:** at-least-once 下任务被重投，每次都 `IndexHistory.objects.acreate(RUNNING)` → 历史列表多条转圈僵尸行。
**Why it happens:** History 行在入队点/handler 创建，重投未去重。
**How to avoid:** index 入队前已有 `already_indexing` 防抖（`tasks:143`）；graph 已有 `_acreate_auto_graph_history` 并发去重（`indexer.py:832`，行锁内 get-or-create RUNNING）。**手动/durable 重投路径需同样：先查在途 RUNNING History 复用，不盲建**。守护测试断言"重复投递后 History RUNNING 行数==1"。
**Warning signs:** 同 repo 同毫秒多条 RUNNING History。

### Pitfall 6: idempotency_key 命中后 background_runner 覆盖在跑任务
**What goes wrong:** in-process 下同 key 二次 defer 覆盖同名注册（`backends.py:107` 注释），可能打断在跑任务。
**Why it happens:** in-process 用 key 作 name，同 name 覆盖。
**How to avoid:** 这是 in-process（dev）的已知非 durable 行为；生产 Postgres 走 `queueing_lock`（todo 唯一，doing 中的不被覆盖）。dev 可接受。**测试时区分两后端断言**。
**Warning signs:** dev 下快速重复触发同 repo 索引，前一个被中断。

## Code Examples

### 现状入队（被替换）——index_views._schedule_index
```python
# server/repositories/index_views.py:160 （current）
wrapped = wrap_resumable(
    kind=ResumableTaskKind.INDEX,
    target_id=str(repository_id),
    payload={"repository_id": str(repository_id), "branch": branch, "trigger": trigger},
    name=f"index-{repository_id}",
    coro_factory=lambda: clone_and_index_repository(repository_id, history_id=history_id, branch=branch),
)
return run_in_background(wrapped, name=f"index-{repository_id}")
```

### 改造后入队（推荐范式）
```python
# 改造目标（async 上下文直接 await；同步上下文用 async_to_sync）
from durable import DurableTaskService, QUEUE_INDEX

await DurableTaskService.defer(
    "durable_index",
    {"repository_id": str(repository_id), "history_id": history_id,
     "branch": branch, "trigger": trigger},
    queue=QUEUE_INDEX,
    idempotency_key=f"index:{repository_id}",
)
```
> ⚠️ 入队点 #1/#4 当前在同步 helper（`_schedule_index` 同步、`run_in_background` 内）或 async view 内调用——planner 须逐点核对调用上下文，async 直接 await，sync 用 `asgiref.sync.async_to_sync`。

### durable 任务注册（procrastinate 路径）—— Source: durable/tasks.py 既有范式（`tasks.py:24`）
```python
# server/durable/tasks.py （新增；@app.task 必须显式 name=，见 60-REVIEW CR-01）
from durable.queues import QUEUE_INDEX, QUEUE_GRAPH

@app.task(name="durable_index", queue=QUEUE_INDEX)
async def durable_index(*, repository_id: str, history_id: str | None = None,
                        branch: str | None = None, trigger: str = "manual") -> dict:
    from durable.tasks_impl import run_index
    return await run_index(repository_id=repository_id, history_id=history_id,
                           branch=branch, trigger=trigger)
```
> **必须显式 `name=`**：procrastinate 默认按函数全路径注册（`durable.tasks.durable_index`），但 `backends.defer` 按 `app.tasks.get(task)` 裸名查找（`backends.py:231`）。Phase 60 review CR-01 已为 `durable_ping`/`retry_stalled_durable_jobs` 修过同一 bug（`60-REVIEW.md:230`）——新任务必须沿用显式 name。

### in-process adapter 注册（fallback 路径）
```python
# 被所有后端路径 import 的模块（如 durable/handlers.py），由 DurableConfig.ready 无条件调用
from durable.backends import register_handler

def register_business_handlers() -> None:
    async def _index(payload: dict):
        from durable.tasks_impl import run_index
        return await run_index(**payload)   # **展开，与 defer_async(**payload) 对齐
    register_handler("durable_index", _index)
    # graph / page_index 同理
```
> ⚠️ 注意 `DurableConfig.ready()` 当前只在 `use_procrastinate_backend()` True 时 import tasks（`apps.py:24`）。in-process handler 注册必须在**两个分支都执行**（SQLite dev 也要能跑任务），故 `register_business_handlers()` 应放在 role 门禁内但**不**包在 procrastinate-only 分支里。planner 须调整 `apps.ready` 结构。

### reconcile 改判定 helper（同步入口）
```python
# server/durable/reconcile.py （新建）
from asgiref.sync import async_to_sync
from durable.service import DurableTaskService, use_procrastinate_backend

def has_active_durable_job_sync(idempotency_key: str) -> bool:
    if not use_procrastinate_backend():
        return False   # 非 durable：维持旧"标 FAILED"行为（SQLite 不承诺续跑）
    state = async_to_sync(DurableTaskService.get)(idempotency_key)
    return state.get("status") in {"todo", "doing", "scheduled"}
```
> reconcile 处把 `recoverable_target_ids(kind)` 排除集换/叠加为"`has_active_durable_job_sync(f"index:{repo_id}")` 为真"的 repo。

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| `ResumableTask` + `wrap_resumable` + `background_runner`（进程内 daemon，lease/CAS/recovery） | `DurableTaskService.defer`（Postgres durable + 多副本 worker） | Phase 60→61 | 生产 index/graph 重启/Pod 重建不丢、多副本竞争消费 |
| 启动 reconcile 无脑标 RUNNING→FAILED | role 门禁（P60）+ 查 durable job 接管才标 FAILED（P61） | Phase 60→61 | 不误杀在途任务 |
| 三套并存（ResumableTask / background_runner / Procrastinate） | 单一 durable 驱动 + background_runner 仅 dev fallback | Phase 61 | 消除并发驱动互踩 |

**Deprecated/即将退役（本阶段后）：**
- 生产 index/graph 的 `wrap_resumable`/`submit_resumable` 路径（迁移后枯竭；`resumable` app 保留用于 dev fallback / workflow·chat kind / 历史兼容）。
- `recoverable_target_ids` 作为 reconcile 排除源（被"查 durable job"取代；函数可保留供过渡）。

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | auto_after_index 图谱在 index durable 任务体内执行、无需独立 graph 入队迁移 | 接入点全清单 | 若实际有独立 auto graph 入队（实读为进程内 `_acreate_auto_graph_history`，非 submit_resumable，故判定 LOW risk） |
| A2 | in-process `get(key)` 在 SQLite 重启后返回 unknown，故 reconcile 在非 durable 下应维持旧标 FAILED | Pattern 3 | 若误让 SQLite 也"保留 RUNNING" → 僵尸 RUNNING 永不收尾（已用"非 durable 维持旧行为"规避） |
| A3 | 给 ResumableTask 加 `legacy_durable_job_id` 列 + `MIGRATED` 枚举（vs 复用 payload/CANCELLED）是更优落点 | Standard Stack Alternatives | Claude's Discretion；选 JSON 列也可，无功能风险 |
| A4 | resume_index/resume_graph（入队点#5）迁移策略为"resume handler 也改 defer" | 接入点全清单 | 若选"recovery 对 index/graph 短路"亦可——二者都能达成不双跑 |

## Open Questions

1. **`DurableConfig.ready()` 重构以支持 in-process handler 注册**
   - What we know: 当前 `ready()` 在 `not use_procrastinate_backend()` 时直接 `return`（`apps.py:24`），SQLite dev 不注册任何业务 handler。
   - What's unclear: in-process 业务 handler 须在 SQLite 路径也注册才能跑——`ready()` 结构需调整（procrastinate-only 段 import tasks；通用段无条件 register_business_handlers）。
   - Recommendation: planner 在 `ready()` 中把 `register_business_handlers()`（in-process adapter）放在 role 门禁通过后、procrastinate 判定**之外**无条件执行；`import durable.tasks`（@app.task）仍只在 procrastinate 分支。

2. **同步入队点的 async_to_sync 包装**
   - What we know: 入队点 #1（`_schedule_index` 同步函数）、#5（`resume_index` 同步函数）当前同步调 `run_in_background`；#2/#3 在 async 函数内；#4 在 async view 内。
   - What's unclear: 逐点确认调用上下文，避免 async/sync 误用。
   - Recommendation: async 上下文直接 `await DurableTaskService.defer(...)`；sync 上下文 `async_to_sync(DurableTaskService.defer)(...)`。

3. **graph 队列是否需要承接 auto_after_index**
   - What we know: auto graph 在 indexer 进程内同步执行，非独立入队。
   - What's unclear: 是否希望把 auto graph 也拆成独立 durable graph job（更细粒度恢复）。
   - Recommendation: 本阶段**保持现状**（auto graph 在 index durable 任务体内），拆分留 backlog——避免范围蔓延。

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| PostgreSQL | durable 真实持久化路径（生产/Postgres CI） | ✓（部署默认；`docker-compose.yaml`/`settings.py`） | 17（compose）| SQLite in-process 非 durable fallback（dev/pytest） |
| procrastinate[django] | durable 后端 | ✓（Phase 60 落地，`uv.lock` 锁 3.8.1） | 3.8.1 | in-process（无 procrastinate 调用） |
| worker 进程（run_worker） | durable 任务消费 | ✓（`durable/management/commands/run_worker.py`，Phase 60） | — | dev：background_runner daemon |

**Missing dependencies with no fallback:** 无——所有依赖 Phase 60 已就位，本阶段零新增。
**Missing dependencies with fallback:** SQLite dev 无 Postgres → in-process 非 durable（明确非目标，dev 可接受）。

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest 9.x + pytest-django 4.8 + pytest-asyncio + pytest-socket（默认 `--disable-socket`） |
| Config file | `server/pyproject.toml`（`[tool.pytest.ini_options]`，含 `postgres_queue` marker 默认排除） |
| Quick run command | `cd server && uv run pytest tests/durable tests/repositories -q` |
| Full suite command | `cd server && uv run pytest -q`（SQLite 默认；Postgres 专项 `-m postgres_queue --allow-hosts=127.0.0.1,localhost`） |

### Phase Requirements → Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| MIGRATE-01 | 5 处入队点改 defer（grep 守护：生产路径零 wrap_resumable 残留） | unit/guard | `uv run pytest tests/durable/test_index_graph_migration.py -k enqueue -x` | ❌ Wave 0 |
| MIGRATE-01 | defer 用正确 queue + deterministic key | unit | `uv run pytest tests/durable/test_index_graph_migration.py -k idempotency_key -x` | ❌ Wave 0 |
| MIGRATE-01 | index/graph 任务双后端入参一致（procrastinate kwargs / in-process adapter） | unit | `uv run pytest tests/durable/test_business_tasks.py -x` | ❌ Wave 0 |
| MIGRATE-02 | 迁移命令：存量行 defer + 标 MIGRATED 记 legacy id | integration | `uv run pytest tests/durable/test_migrate_command.py -k migrates -x` | ❌ Wave 0 |
| MIGRATE-02 | 迁移命令幂等可重入（重跑不产生重复 durable job / 不重处理已迁行） | integration | `uv run pytest tests/durable/test_migrate_command.py -k idempotent -x` | ❌ Wave 0 |
| MIGRATE-02 | 迁移命令 SQLite 安全降级（给提示不崩） | unit | `uv run pytest tests/durable/test_migrate_command.py -k sqlite_safe -x` | ❌ Wave 0 |
| MIGRATE-02 | reconcile：有在途 durable job → 保留 RUNNING（不误杀） | unit | `uv run pytest tests/repositories/test_reconcile_durable.py -x` | ❌ Wave 0 |
| IDEMP-01 | 重复投递 → 单次有效执行（History RUNNING 行数==1） | integration | `uv run pytest tests/durable/test_idempotency.py -k duplicate_dispatch -x` | ❌ Wave 0 |
| IDEMP-01 | 重复执行 → 无重复数据（FileIndex/GraphFileIndex 去重、产物不翻倍） | integration | `uv run pytest tests/durable/test_idempotency.py -k duplicate_execution -x` | ❌ Wave 0 |
| IDEMP-01 | page_index 占位 handler 幂等基线 | unit | `uv run pytest tests/durable/test_idempotency.py -k page_index -x` | ❌ Wave 0 |

### Sampling Rate
- **Per task commit:** `cd server && uv run pytest tests/durable -q`（含双后端 SQLite 路径）
- **Per wave merge:** `cd server && uv run pytest tests/durable tests/repositories tests/codegraph -q`
- **Phase gate:** 全量 `uv run pytest -q` 绿 + Postgres 专项 `-m postgres_queue`（CI postgres-queue job）绿 → `/gsd-verify-work`

### Wave 0 Gaps
- [ ] `tests/durable/test_business_tasks.py` — durable_index/durable_graph/durable_page_index 双后端入参契约（IDEMP-01/MIGRATE-01）
- [ ] `tests/durable/test_index_graph_migration.py` — 入队点改 defer + queue/key 正确 + grep 守护无残留（MIGRATE-01）
- [ ] `tests/durable/test_migrate_command.py` — 一次性迁移命令幂等/不双跑/SQLite 降级（MIGRATE-02）
- [ ] `tests/durable/test_idempotency.py` — 重复投递/执行守护（IDEMP-01）
- [ ] `tests/repositories/test_reconcile_durable.py` — reconcile 查 durable job 接管（MIGRATE-02）
- [ ] postgres_queue 标记的 index/graph durable 端到端用例（叠加现有 `tests/durable/conftest.py` 的 `procrastinate_app` fixture）
- [ ] 复用既有 `tests/durable/conftest.py`（`_reset_for_tests` `backends.py:186`、`procrastinate_app` skip-if-not-postgres、forged-heartbeat）——无需新建框架

## Security Domain

> `security_enforcement: true`, `security_asvs_level: 1`（config.json）。本阶段为后端任务迁移，无新用户输入面 / 无新外部副作用（外部副作用 fencing 是 Phase 63 IDEMP-02）。

### Applicable ASVS Categories
| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | no | 入队点沿用既有 REST 鉴权（IsAuthenticated/IsSuperUser），本阶段不动权限 |
| V3 Session Management | no | — |
| V4 Access Control | yes（间接） | 迁移命令仅运维/CLI（migrate role）执行，不暴露 REST；入队点权限不回退 |
| V5 Input Validation | yes（轻） | payload 为内部构造（repository_id 等 UUID 字符串），非用户自由输入；deterministic key 由 repo_id 派生，无注入面 |
| V6 Cryptography | no | 不涉密 |

### Known Threat Patterns for durable 迁移
| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| 双跑（迁移 + recovery 同时驱动同 repo）| Tampering（数据重复）| deterministic key 去重 + 旧行标 MIGRATED 排除出 recovery 集 |
| 误杀在途（reconcile 标 FAILED 活任务）| Denial of Service（任务丢失）| reconcile 改"查 durable job 接管才标 FAILED" |
| 重复执行产生重复产物 | Tampering | FileIndex/GraphFileIndex hash checkpoint + History RUNNING 复用 + upsert |
| 迁移命令在 SQLite 误转进程内 | Repudiation（运维误判）| 命令判后端 + 清晰提示，不静默 |

## Sources

### Primary (HIGH confidence) — 全部实读源码
- `server/durable/service.py`、`backends.py`、`tasks.py`、`queues.py`、`roles.py`、`apps.py`、`__init__.py` — durable 适配层完整 API
- `server/resumable/service.py`、`handlers.py`、`recovery.py`、`models.py`、`apps.py`、`management/commands/recover_tasks.py` — 迁移源 + 范式
- `server/repositories/views.py`、`index_views.py`、`tasks/index_trigger_tasks.py`、`codegraph/views.py` — 5 处入队点实读
- `server/repositories/apps.py`、`server/codegraph/apps.py` — reconcile 现状
- `server/repositories/models.py`（IndexHistory/GraphBuildHistory/FileIndex/GraphFileIndex）、`server/services/indexer.py`（auto_after_index）、`server/services/graph_builder.py`
- `server/tests/durable/test_procrastinate_backend.py` — defer payload 契约印证
- `.planning/phases/60-durable/60-0{1,2,3,4}-SUMMARY.md`、`60-REVIEW.md`（CR-01 task name fix）
- `.planning/phases/61-migrate/61-CONTEXT.md`、`.planning/REQUIREMENTS.md`、`.planning/STATE.md`、`.planning/config.json`

### Secondary (MEDIUM confidence)
- 无外部检索——本阶段纯内部代码迁移，结论全部源于本仓库源码

### Tertiary (LOW confidence)
- 无

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — 全部 Phase 60 已交付符号实读，零新依赖
- Architecture: HIGH — 5 处入队点 / reconcile / 双后端契约全部源码核实（修正了 CONTEXT 的 3 处计数）
- Pitfalls: HIGH — 双后端 payload 不一致、同步 reconcile 调异步、SQLite 误迁均为实读源码推导
- 关键修正：CONTEXT 列 3 处入队点，实读为 **5 处**（漏 `index_views.py`、`codegraph/views.py`）——planner 必须迁全

**Research date:** 2026-06-20
**Valid until:** 2026-07-20（内部代码，稳定；若 Phase 60 durable API 变动则需复核）

## RESEARCH COMPLETE
