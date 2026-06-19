# Phase 62: 爬取+入库 durable 队列 + PageIndex 接入 - Context

**Gathered:** 2026-06-20
**Status:** Ready for planning
**Mode:** Smart discuss (autonomous — 灰区默认值按里程碑锁定约束自动采纳)

<domain>
## Phase Boundary

把链接爬取+入库改为 durable 任务（v0.12.0 首个用户可见垂直切片，前后端贯通），并把 PageIndex/TOC/summary/tree 生成按 hash 幂等接入 durable queue。交付：

1. **爬取+入库 durable 化（CRAWL-01）**：后端支持入队/查询/开始/停止/重试/断点恢复；状态以 DB 为真相源，刷新页面 + `docker compose up -d`/Pod 重建后任务不丢、自动续跑；入库 at-least-once 幂等（复用现有 upsert/`IngestRun` 范式）。
2. **前端爬取任务队列面板（CRAWL-02）**：`BatchIngestPanel` 贴链接入队、队列列表 + 实时状态、行内开始/停止/重试、刷新后从后端恢复（不再依赖组件内存 `batchId`/`ref`）；`feishu_not_configured` 引导深链保留；i18n 默认中文。
3. **PageIndex 接入 durable queue（PAGEIDX-01）**：PageIndex/TOC/summary/tree 生成接入 durable queue（收口 `repositories/tree_views.py` 等裸 `background_runner` 路径），按 target hash 幂等（hash 未变跳过），重复执行安全。

**不在范围内**：部署硬化/优雅终止/KEDA（Phase 63）、外部副作用 fencing（Phase 63 IDEMP-02）、runner k8s（Phase 64）。

</domain>

<decisions>
## Implementation Decisions

### 爬取+入库 durable 化（CRAWL-01）
- 复用 Phase 60 `DurableTaskService.defer`（新增 `QUEUE_CRAWL_INGEST` 逻辑队列，避免长任务 index 堵爬取/页面生成）。
- 真相源以 DB 为准：复用既有 `IngestRun` 模型承载队列项状态（queued/running/stopped/failed/completed）+ deterministic idempotency key（按 batch/url 集合），不再依赖前端内存 `batchId`/`ref`。
- 后端动作语义：入队（defer）/查询（list + detail）/开始（defer or resume）/停止（cancel → stopped 终态可重投）/重试（重新 defer 同 idempotency key）/断点恢复（DB 态 + durable job 续跑，Pod 重建后自动续）。
- 入库 at-least-once 幂等：复用现有 `json_ingest`/`ingest_orchestrator` upsert + `IngestRun` 去重范式（Phase 61 IDEMP-01 同款 checkpoint/deterministic key/upsert）。
- 沿用聊天/RAG 不进队列边界：仅爬取+入库后台任务进 durable。

### 前端面板（CRAWL-02）
- 改造既有 `web/src/components/knowledge/BatchIngestPanel.vue`：从后端拉队列列表（轮询/refetchInterval 范式，沿用既有 useMutation+条件 refetch），不再持组件内存 `batchId`/`ref`；刷新后从后端恢复。
- 列表展示：每项 url 集合/状态徽标/进度/时间；行内操作开始/停止/重试（调后端动作 API）。
- `feishu_not_configured` 引导深链保留（既有行为不回退）。
- i18n 默认中文，文案接入既有 `vue-i18n`（`zh-CN.json`）。
- UI 设计契约由 `/gsd-ui-phase` 产 `62-UI-SPEC.md`（reuse-first：复用既有面板组件/徽标/确认弹窗范式）。

### PageIndex 接入（PAGEIDX-01）
- 收口 `repositories/tree_views.py` 等裸 `background_runner` 调用 → `DurableTaskService.defer`（`QUEUE_PAGE_INDEX`）。
- 按 target hash 幂等：hash 未变跳过（复用 Phase 60/61 deterministic key + checkpoint 范式）；重复执行安全（无重复树/重复 summary）。
- page_index handler 复用/扩展 Phase 61 占位 handler（IDEMP-01 已建幂等基线）。

### Claude's Discretion
- `IngestRun` 是否需新增列（durable_job_id / status 扩展 / idempotency key 列）vs 复用既有字段 + migration。
- 爬取/入库的动作 REST API 形状（独立 action 端点 vs 状态机 PATCH）——倾向独立 action 端点（对齐既有 reconcile/cleanup 派发范式）。
- 前端轮询间隔与状态归一（running→2s、终态停轮）。
- page_index target hash 的精确定义（tree 结构 hash / 文件集 hash）。

</decisions>

<code_context>
## Existing Code Insights

### Reusable Assets
- Phase 60 `server/durable/`（`DurableTaskService` / `queues.py` — 新增 crawl_ingest/page_index 队列常量已预留）。
- `server/delivery/services/crawl_service.py` / `json_ingest.py` / `ingest_orchestrator.py` — 爬取+入库现有逻辑（被 durable 化对象）。
- `server/delivery/models/ingest_run.py`（`IngestRun` 模型）+ `migrations/0008_ingestrun.py` — 队列项真相源。
- `server/delivery/api/views.py` / `serializers.py` / `urls.py` — 入库 REST API（扩动作端点）。
- `web/src/components/knowledge/BatchIngestPanel.vue` + `web/src/api/ingest.ts` + `web/src/pages/knowledge/index.vue` — 前端面板（改造对象）。
- `server/repositories/tree_views.py` / `tree_schema.py` / `management/commands/backfill_repo_trees.py` — PageIndex/tree 生成（收口裸 background_runner）。
- Phase 61 `durable/handlers.py` / `tasks_impl.py`（page_index 占位 handler + 幂等范式）。

### Established Patterns
- 派发→轮询前端范式（useMutation + 条件 refetchInterval），守护测试以真实 zh-CN.json 锁文案（参考 Phase 23 ReconcilePanel / Phase 24 SensitiveSuggestionsPanel）。
- DurableTaskService.defer + deterministic idempotency_key + IngestRun 真相源。
- at-least-once 幂等：upsert + checkpoint + deterministic key。

### Integration Points
- `DurableTaskService.defer`（crawl_ingest + page_index 队列）。
- `IngestRun` 模型（可能 migration）+ delivery REST 动作端点。
- `BatchIngestPanel.vue` 改造 + `ingest.ts` API + `zh-CN.json` 文案。
- `tree_views.py` 裸 background_runner → durable defer。

</code_context>

<specifics>
## Specific Ideas

- 用户可见验收：贴链接 → 入队 → 刷新页面/重启容器后任务仍在、自动续跑（DB 真相源），行内可开始/停止/重试。
- 不再依赖前端内存 batchId/ref —— 这是本阶段"前后端贯通"的核心目标。
- PageIndex hash 未变跳过 —— 重复执行不产生重复树/summary。

</specifics>

<deferred>
## Deferred Ideas

- 部署硬化（优雅终止 / compose·helm 拆 workload / KEDA / PDB）→ Phase 63。
- 外部副作用 fencing/outbox（飞书通知/建群、MR/PR）→ Phase 63 IDEMP-02。
- runner k8s Job executor → Phase 64。

</deferred>

---

*Phase: 62-crawl*
*Context gathered: 2026-06-20 via smart discuss (autonomous)*
