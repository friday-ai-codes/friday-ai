# Phase 61: 迁移 index/graph + 收口 ResumableTask - Context

**Gathered:** 2026-06-20
**Status:** Ready for planning
**Mode:** Smart discuss (autonomous — 灰区默认值按里程碑锁定约束自动采纳)

<domain>
## Phase Boundary

把现有 index/graph 后台任务从 `ResumableTask`/`background_runner` 迁到 Phase 60 的 `DurableTaskService`，一次性迁移存量在途行（不三套并存），并建立 handler 幂等基线。交付：

1. **index/graph 接入 durable queue**：`repositories/views.py`、`tasks/index_trigger_tasks.py`、`resumable/handlers.py` 的 `run_in_background(wrap_resumable(...))` 改 `DurableTaskService.defer`（queue=index/graph，`idempotency_key=index:{repo_id}` / `graph:{repo_id}`）。`IndexHistory`/`GraphBuildHistory` 仍为进度/结果真相源，FileIndex/GraphFileIndex checkpoint 跳过保留。
2. **一次性迁移 command**：升级时把存量 PENDING/RUNNING `resumable_tasks`（index/graph）按 deterministic idempotency key 转 durable job，旧行标 migrated/cancelled 记 legacy id（不双跑）。
3. **启动 reconcile 改安全语义**：`repositories.apps`/`codegraph.apps` 启动 reconcile 改为"仅确认无 durable job 接管时才把 RUNNING 标 FAILED"，不再误杀在途任务。`background_runner` 降级为仅 SQLite dev fallback / 轻任务。
4. **handler 幂等基线（IDEMP-01）**：index/graph（+ page_index 占位）在 at-least-once 重复投递/重复执行下经 checkpoint/deterministic key/upsert 结果一致；守护测试覆盖"重复投递/重复执行不产生重复数据或副作用"。

**不在范围内**：爬取队列（Phase 62）、PageIndex 实际接入（Phase 62 PAGEIDX-01，本阶段仅幂等基线占位）、外部副作用 fencing（Phase 63 IDEMP-02）、部署硬化（Phase 63）。

</domain>

<decisions>
## Implementation Decisions

### 接入 durable queue（MIGRATE-01）
- 入队入口统一改 `DurableTaskService.defer`，queue 用 Phase 60 的 `queues.QUEUE_INDEX` / `QUEUE_GRAPH` 常量；`idempotency_key` 用 deterministic `index:{repo_id}` / `graph:{repo_id}`（同 repo 在途去重，避免重复入队）。
- `IndexHistory` / `GraphBuildHistory` 继续作进度/结果真相源——durable job 只负责"驱动执行"，进度/状态仍写既有 History 表（不另造状态源）。
- FileIndex / GraphFileIndex 的 checkpoint「已处理跳过」逻辑原样保留（at-least-once 重跑的幂等基础）。
- 三处入队点（`repositories/views.py`、`tasks/index_trigger_tasks.py`、`resumable/handlers.py`）全部收口；保留 chat/RAG 流式问答不进队列的边界（仅迁 index/graph 后台任务）。

### 一次性迁移（MIGRATE-02）
- 新增一次性 management command（如 `migrate_resumable_to_durable`）：扫描 PENDING/RUNNING 的 index/graph `resumable_tasks`，按 deterministic idempotency key `defer` 成 durable job，旧行标 `migrated`（或 cancelled）并记 `legacy_durable_job_id`——**不双跑**（迁过的旧行不再被 background_runner/recovery 重驱）。
- 幂等可重入：command 重复执行不产生重复 durable job（deterministic key + 旧行状态判定）。
- 命令 SQLite dev 下安全降级（无 durable 后端时给清晰提示或转 in-process，不报错崩溃）。

### 启动 reconcile 安全语义（MIGRATE-02）
- `repositories.apps` / `codegraph.apps` 的启动 reconcile（Phase 60 已加角色门禁）进一步改判定：RUNNING 行**仅当确认无 durable job 接管**时才标 FAILED；有对应在途 durable job 则保留 RUNNING，绝不误杀。
- `background_runner` 降级为仅 SQLite dev fallback / 少量非持久轻任务——生产 durable 任务不再 ResumableTask/background_runner/Procrastinate 三套并存。

### handler 幂等基线（IDEMP-01）
- index / graph（+ page_index 占位 handler）实现 at-least-once 幂等：checkpoint（已处理跳过）+ deterministic key + upsert，重复执行结果一致。
- 守护测试：同一任务重复投递 → 单次有效执行；重复执行 → 不产生重复数据 / 重复副作用（断言 History 行数、索引产物去重）。

### Claude's Discretion
- migration command 的精确名称、旧行终态枚举（migrated vs cancelled）、legacy id 字段落点（resumable_tasks 既有列 vs metadata JSON）。
- reconcile「确认无 durable job 接管」的查询实现（按 idempotency_key 查 durable job 状态）。
- page_index 幂等基线在本阶段做到何种程度（占位 handler + 测试 vs 仅接口预留）——倾向占位 handler + 幂等测试，实际接入留 Phase 62。

</decisions>

<code_context>
## Existing Code Insights

### Reusable Assets
- Phase 60 `server/durable/`（`DurableTaskService` / `queues.py` / `service.py` / `backends.py`）— 本阶段消费入口。
- `server/resumable/`（`handlers.py` / `recovery.py` / `service.py` / `models.py` / `management/`）— 迁移源 + recovery 范式 + 迁移 command 参考。
- `server/repositories/views.py`、`server/tasks/index_trigger_tasks.py` — index/graph 入队点。
- `server/repositories/apps.py`、`server/codegraph/apps.py` — Phase 60 已加角色门禁的启动 reconcile（本阶段改判定语义）。
- `IndexHistory` / `GraphBuildHistory` / `FileIndex` / `GraphFileIndex` 模型 — 进度真相源 + checkpoint。
- `server/services/background_runner.py` — 降级为 dev fallback。

### Established Patterns
- `run_in_background(wrap_resumable(...))` 现有入队范式（被替换对象）。
- management command + migration 的既有写法（`resumable/management/`）。
- INV-6 单一写入入口精神（迁移/状态写入收口，禁旁路）。
- 守护测试以 grep/行为断言锁幂等。

### Integration Points
- `DurableTaskService.defer` 调用点（3 处入队）。
- 新增 migration management command。
- `apps.py` reconcile 判定（2 处）。
- handler 幂等改造 + tests/durable 或 tests/repositories 守护测试。

</code_context>

<specifics>
## Specific Ideas

- 严格"不三套并存"：迁移后 production index/graph 只走 durable；ResumableTask/background_runner 不再驱动生产 index/graph。
- 升级安全：存量在途行一次性迁移，绝不双跑、绝不误杀。
- at-least-once：重复执行靠 checkpoint/deterministic key/upsert 幂等，不承诺 exactly-once。

</specifics>

<deferred>
## Deferred Ideas

- 爬取+入库 durable 队列 + 前端面板 → Phase 62。
- PageIndex/TOC/summary/tree 实际接入 durable queue → Phase 62 PAGEIDX-01（本阶段仅幂等基线）。
- 外部副作用（飞书通知/建群、MR/PR）fencing/outbox → Phase 63 IDEMP-02。
- runapscheduler cron 迁移 → Phase 63。

</deferred>

---

*Phase: 61-migrate*
*Context gathered: 2026-06-20 via smart discuss (autonomous)*
