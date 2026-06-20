# Phase 62: 爬取+入库 durable 队列 + PageIndex 接入 - Research

**Researched:** 2026-06-20
**Domain:** durable 任务队列接入（Procrastinate 适配层）+ delivery 摄取编排 + Vue 派发轮询面板 + PageIndex/能力树幂等生成
**Confidence:** HIGH（全部基于本仓库已落地代码 file:line + Phase 60/61 SUMMARY；无新外部依赖）

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

**爬取+入库 durable 化（CRAWL-01）**
- 复用 Phase 60 `DurableTaskService.defer`（新增 `QUEUE_CRAWL_INGEST` 逻辑队列，避免长任务 index 堵爬取/页面生成）。
- 真相源以 DB 为准：复用既有 `IngestRun` 模型承载队列项状态（queued/running/stopped/failed/completed）+ deterministic idempotency key（按 batch/url 集合），不再依赖前端内存 `batchId`/`ref`。
- 后端动作语义：入队（defer）/查询（list + detail）/开始（defer or resume）/停止（cancel → stopped 终态可重投）/重试（重新 defer 同 idempotency key）/断点恢复（DB 态 + durable job 续跑，Pod 重建后自动续）。
- 入库 at-least-once 幂等：复用现有 `json_ingest`/`ingest_orchestrator` upsert + `IngestRun` 去重范式（Phase 61 IDEMP-01 同款 checkpoint/deterministic key/upsert）。
- 沿用聊天/RAG 不进队列边界：仅爬取+入库后台任务进 durable。

**前端面板（CRAWL-02）**
- 改造既有 `web/src/components/knowledge/BatchIngestPanel.vue`：从后端拉队列列表（轮询/refetchInterval 范式，沿用既有 useMutation+条件 refetch），不再持组件内存 `batchId`/`ref`；刷新后从后端恢复。
- 列表展示：每项 url 集合/状态徽标/进度/时间；行内操作开始/停止/重试（调后端动作 API）。
- `feishu_not_configured` 引导深链保留（既有行为不回退）。
- i18n 默认中文，文案接入既有 `vue-i18n`（`zh-CN.json`）。
- UI 设计契约由 `/gsd-ui-phase` 产 `62-UI-SPEC.md`（reuse-first）。

**PageIndex 接入（PAGEIDX-01）**
- 收口 `repositories/tree_views.py` 等裸 `background_runner` 调用 → `DurableTaskService.defer`（`QUEUE_PAGE_INDEX`）。
- 按 target hash 幂等：hash 未变跳过（复用 Phase 60/61 deterministic key + checkpoint 范式）；重复执行安全（无重复树/重复 summary）。
- page_index handler 复用/扩展 Phase 61 占位 handler（IDEMP-01 已建幂等基线）。

### Claude's Discretion
- `IngestRun` 是否需新增列（durable_job_id / status 扩展 / idempotency key 列）vs 复用既有字段 + migration。
- 爬取/入库的动作 REST API 形状（独立 action 端点 vs 状态机 PATCH）——倾向独立 action 端点（对齐既有 reconcile/cleanup 派发范式）。
- 前端轮询间隔与状态归一（running→2s、终态停轮）。
- page_index target hash 的精确定义（tree 结构 hash / 文件集 hash）。

### Deferred Ideas (OUT OF SCOPE)
- 部署硬化（优雅终止 / compose·helm 拆 workload / KEDA / PDB）→ Phase 63。
- 外部副作用 fencing/outbox（飞书通知/建群、MR/PR）→ Phase 63 IDEMP-02。
- runner k8s Job executor → Phase 64。
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| CRAWL-01 | 链接爬取+入库改 durable 任务——入队/查询/开始/停止/重试/断点恢复；DB 真相源；刷新页面 + `docker compose up -d`/Pod 重建后任务不丢、自动续跑；入库 at-least-once 幂等 | `DurableTaskService.defer`（`service.py:82`）+ `QUEUE_CRAWL_INGEST`（`queues.py:15` 已存在）+ `IngestRun`（`ingest_run.py:42`，需扩 status/列）+ `ingest_from_refs`/`run_json_batch` 现有 upsert 幂等（§Architecture Patterns / §Don't Hand-Roll） |
| CRAWL-02 | 前端爬取任务队列面板——入队、队列列表 + 实时状态、行内开始/停止/重试、刷新后从后端恢复（不依赖组件内存 `batchId`/`ref`）；`feishu_not_configured` 深链保留；i18n 默认中文 | `reconcile.ts` 派发→轮询范式（`reconcile.ts:86`，`ReconcilePanel.vue` useI18n）+ 现 `BatchIngestPanel.vue:155` 内存 `batchId`（待移除）+ 新增 list 端点（§Runtime State Inventory / §Code Examples） |
| PAGEIDX-01 | PageIndex/TOC/summary/tree 生成接入 durable queue（收口 `tree_views.py` 裸 `background_runner`），按 target hash 幂等（hash 未变跳过），重复执行安全 | `run_page_index` 占位（`tasks_impl.py:63`）+ `_page_index` adapter（`handlers.py:32`）已注册 `durable_page_index`；`tree_views.py:182` 裸 `run_in_background(CorpusTreeService.build_full)` 待改 defer（`corpus_tree.py:86`）（§PageIndex 接入） |
</phase_requirements>

## Summary

本阶段是 v0.12.0 首个**用户可见垂直切片**，把「链接爬取 + 批量入库」从进程内 `run_in_background` 改造为 durable 任务，并把 PageIndex/能力树生成收口到 durable `page_index` 队列。**底座已经齐备**——Phase 60/61 已交付 `DurableTaskService`（`defer/get/cancel/has_active_by_key/retry_stalled`）、`QUEUE_CRAWL_INGEST` / `QUEUE_PAGE_INDEX` 队列常量、双后端任务体范式（`tasks_impl.py` keyword-only + `handlers.py` `**payload` adapter）、page_index 占位 handler 与幂等基线、以及 `has_active_by_key` 在途判定门面。本阶段几乎全是**接入与改造**，不需要新建队列机制或新增外部依赖。

三条工作线：(1) **后端 durable 化**——新建 `run_crawl_ingest` 任务体（薄封装现有 `ingest_from_refs` / `run_json_batch`，二者已天然幂等：`WorkItemService.upsert` 按三元组、文档按 content_hash、MR diff 按 `aarchive_exists`）、扩 `IngestRun`（加 `QUEUED`/`STOPPED` 状态 + `durable_job_id` + `idempotency_key` 列 + migration）、新增 delivery 动作 REST 端点（enqueue/list/detail/start/stop/retry，镜像 `RepositoryReconcileView` 的 dispatch→poll 派发范式）。(2) **前端面板**——重写 `BatchIngestPanel.vue` 移除内存 `batchId`/`ref`，改为从后端 list 端点拉队列、刷新后恢复、行内 start/stop/retry，文案接入 `zh-CN.json`（当前面板是硬编码中文，须迁 i18n）。(3) **PageIndex**——填充 `run_page_index` 做真实生成（`CorpusTreeService.build_full`），按 target hash 幂等跳过，并把 `tree_views.py:182` 裸 `run_in_background` 改 `DurableTaskService.defer(QUEUE_PAGE_INDEX)`。

**Primary recommendation:** 复用 Phase 61 的「薄任务体 + 双后端 adapter + deterministic idempotency_key + 业务 service 自带幂等」范式逐字照搬；后端动作端点镜像 `RepositoryReconcileView`（POST 派发立即 202 + GET 轮询真相源）；前端镜像 `reconcile.ts`/`ReconcilePanel.vue`（`refetchInterval: running→2s/终态 false` + useI18n 守护文案）。**关键不变量：绝不依赖前端内存 batchId/ref，一切状态从 `IngestRun`（DB）恢复。**

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| 爬取链接 → AI 抽条目（crawl） | API / Backend (`crawl_service.crawl_url`) | — | 同步秒级抓取 + 单次 LLM；**不进 durable 队列**（请求级，已有 `IngestCrawlView`），仅产编辑表条目；与「入库 durable 任务」是两个阶段 |
| 批量入库编排（ingest 三步） | Durable Worker (`QUEUE_CRAWL_INGEST`) | API (enqueue/查询) | 长后台任务、需 Pod 重建续跑 → durable；DB 真相源 `IngestRun` |
| 队列项状态真相源 | Database (`IngestRun` 表) | API (序列化回流) | CRAWL-01 命门：刷新/重启后从 DB 恢复，不靠内存 |
| 动作（enqueue/start/stop/retry） | API / Backend (delivery REST action 端点) | Durable (`defer`/`cancel`) | 镜像 reconcile/cleanup 独立 action 端点派发范式 |
| 队列列表 + 实时状态轮询 | Frontend (`BatchIngestPanel.vue`) | API (list/detail 端点) | TanStack Query `refetchInterval` 轮询；刷新从后端 list 恢复 |
| PageIndex/能力树生成 | Durable Worker (`QUEUE_PAGE_INDEX`) | Database (`CorpusTreeSnapshot` / `Repository.ai_summary_tree`) | 收口裸 `background_runner`；hash 未变跳过 |
| 任务持久化 + 跨副本竞争 + stalled rescue | Postgres (procrastinate_jobs) | Durable Worker 进程 | Phase 60 已交付；本阶段消费，不新建 |

## Standard Stack

### Core（全部既有，零新增依赖）

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| `procrastinate[django]` | 3.8.1 (`<3.9`) | durable 任务队列后端（藏在 `DurableTaskService` 后） | Phase 60 已落地，业务侧绝不直接 import（`test_no_direct_import.py` 守护） |
| `DurableTaskService` | 既有 (`durable/service.py`) | `defer/get/cancel/has_active_by_key/retry_stalled` 统一门面 | Phase 60/61 唯一入口，本阶段 crawl_ingest/page_index 经此入队 |
| `IngestRun` (Django model) | 既有 (`delivery/models/ingest_run.py`) | 队列项真相源 | CONTEXT 锁定复用 + migration 扩列 |
| `adrf` (async DRF) | `>=0.1.12` | delivery 动作端点（APIView async） | 既有 delivery REST 全走 adrf APIView |
| `@tanstack/vue-query` | 既有 (`web/package.json`) | 前端派发→轮询（`useMutation` + `useQuery` `refetchInterval`） | `reconcile.ts` / `ingest.ts` 既有范式 |
| `vue-i18n` | 既有 | 队列面板文案（zh-CN 默认） | CONTEXT 锁定接入既有 i18n |

### Supporting（既有摄取/树服务，作为任务体内核被复用）

| Symbol | File:Line | Purpose | When to Use |
|--------|-----------|---------|-------------|
| `ingest_from_refs` | `ingest_orchestrator.py:134` | 三步摄取（工作项/文档/MR diff）best-effort + 步级隔离 + 写 `IngestRun.steps` | crawl_ingest 任务体单项摄取内核 |
| `run_json_batch` | `json_ingest.py:101` | 有界并发跑多个 `ingest_from_refs`（每项 spec 含 run_id） | crawl_ingest 批量任务体内核 |
| `aresolve_items` | `json_ingest.py:60` | 空间解析 → 三元组（只读预览） | enqueue 前解析（已被 `JsonIngestBatchView` 用） |
| `crawl_url` | `crawl_service.py:480` | 单 URL 抓取 + AI 抽条目（请求级，非队列） | 保留现 `IngestCrawlView`，不改 |
| `CorpusTreeService.build_full` | `corpus_tree.py:86` | 全局业务域树 LLM 聚类 → `CorpusTreeSnapshot` | page_index 任务体内核（PAGEIDX-01 主目标） |
| `validate_and_assemble_tree` | `tree_schema.py:243` | 能力树结构/路径/monorepo 校验 | per-repo 树生成校验（callback 侧已用） |

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| 扩 `IngestRun` 加列 + migration | 复用既有字段、durable_job_id 不落库 | 不落 `durable_job_id` → stop/retry 无法定位 procrastinate job；不加 `QUEUED`/`STOPPED` → 无法表达入队待跑/已停可重投。**推荐扩列**（见 Open Questions OQ-1） |
| 独立 action 端点 | 状态机 PATCH `/ingest/<id>/` | CONTEXT 倾向独立端点（对齐 reconcile/cleanup 既有派发范式，前端心智一致）。**推荐独立 action 端点** |
| page_index 跑 `CorpusTreeService.build_full`（全局域树） | per-repo `dispatch_repo_summary`（容器 Runner） | per-repo summary 经 Runner 容器（DispatchTask，非本地 durable 任务），改造面大且跨进程；`build_full` 是纯本地 LLM 任务，最贴合 page_index 队列。**推荐先做 build_full**，per-repo dispatch 列 Open Questions |

**Installation:** 无新增包——`procrastinate[django]>=3.8.1,<3.9` 已在 `server/pyproject.toml`（Phase 60 落地，`uv.lock` 锁 3.8.1）。

**Version verification:** 本阶段不安装任何新外部包，故无需 `npm view` / `pip index versions`。所有依赖均为仓库内既有符号或 Phase 60 已锁定的 procrastinate 3.8.1。

## Package Legitimacy Audit

> **Not applicable** — 本阶段不安装任何新的外部包。全部工作是接入既有 `durable.DurableTaskService`、复用既有 delivery/repositories 服务、改造既有 Vue 组件与 zh-CN.json。procrastinate 3.8.1 已由 Phase 60 审计并锁定（`uv.lock`）。

| Package | Registry | Disposition |
|---------|----------|-------------|
| （无新增） | — | N/A — 零新依赖 |

**Packages removed due to slopcheck [SLOP] verdict:** none
**Packages flagged as suspicious [SUS]:** none

## Architecture Patterns

### System Architecture Diagram

```text
                  ┌─────────────────────────── Frontend (BatchIngestPanel.vue) ──────────────────────────┐
  贴链接 ─crawl─▶  │  IngestCrawlView (POST /ingest/crawl/)  ──同步──▶  CrawlResult.items ──▶ 编辑表(JSON)   │
  (请求级,不进队列) │                                                                                       │
                  │  [开始关联] ─enqueue─▶ POST /delivery/ingest/queue/        ┌── list 轮询恢复 (刷新安全) ─┐ │
                  │  [行内 start/stop/retry] ─▶ POST .../queue/<id>/<action>/  │ GET /delivery/ingest/queue/ │ │
                  └─────────────────────────────┬───────────────────────────┴─────────────▲──────────────┘
                                                 │ (202 立即返回)                            │ (refetchInterval 2s)
                                                 ▼                                          │ 真相源回流
              ┌──────────── delivery REST (adrf APIView, IsAuthenticated) ─────────────────┴───────────┐
              │  enqueue: 建/更新 IngestRun(QUEUED) → DurableTaskService.defer(durable_crawl_ingest,    │
              │           queue=QUEUE_CRAWL_INGEST, idempotency_key=crawl_ingest:{batch_id})            │
              │  stop:    DurableTaskService.cancel(durable_job_id) → IngestRun.status=STOPPED          │
              │  retry:   重新 defer 同 idempotency_key (queueing_lock 去重)                             │
              └──────────────────────────────────────┬─────────────────────────────────────────────────┘
                                                      │ defer
                            ┌─────────────────────────▼──────────────────────────┐
   ┌── Postgres ──┐         │  DurableTaskService.defer  (durable/service.py)      │
   │ procrastinate │◀───────│   ├ Postgres → ProcrastinateBackend (durable)        │
   │   _jobs 表    │ 持久化   │   └ SQLite  → InProcessBackend (非 durable, dev)     │
   │ delivery_     │        └─────────────────────────┬──────────────────────────┘
   │  ingest_run   │◀── DB 真相源                       │ 独立 worker 进程消费 (run_worker)
   └───────────────┘        ┌──────────────────────────▼──────────────────────────┐
        ▲ 重建后续跑          │  run_crawl_ingest(*, batch_id|run_ids, specs)         │ QUEUE_CRAWL_INGEST
        │ (worker 启动领 todo │   └▶ run_json_batch / ingest_from_refs (at-least-once  │
        │  + periodic rescue)│      幂等: upsert 三元组 / content_hash / aarchive_exists)│
        └────────────────────┤  run_page_index(*, target_id, target_hash)           │ QUEUE_PAGE_INDEX
                             │   └▶ hash 未变? skip : CorpusTreeService.build_full()  │
                             └───────────────────────────────────────────────────────┘
```

### Recommended Project Structure（接入点，全部已有文件）

```
server/durable/
├── tasks_impl.py        # + run_crawl_ingest(*, ...)；填充 run_page_index 真实生成
├── tasks.py             # + @app.task(name="durable_crawl_ingest") 包壳（procrastinate 路径）
├── handlers.py          # + _crawl_ingest adapter + register（in-process 路径）
└── queues.py            # QUEUE_CRAWL_INGEST/QUEUE_PAGE_INDEX 已存在（不改）
server/delivery/
├── models/ingest_run.py # + Status.QUEUED/STOPPED + durable_job_id + idempotency_key 列
├── migrations/00XX_*.py # 新 migration（加列 + 默认值）
├── api/views.py         # + IngestQueue{Dispatch,List,Action}View（镜像 RepositoryReconcileView）
├── api/serializers.py   # + 队列项序列化（含 durable_job_id/idempotency_key/状态）
└── urls.py              # + queue/ + queue/<uuid>/<action>/ 路由（字面段在 uuid 前）
server/repositories/
└── tree_views.py        # KnowledgeTreeRebuildView.post: run_in_background → defer(QUEUE_PAGE_INDEX)
web/src/
├── components/knowledge/BatchIngestPanel.vue  # 移除内存 batchId/ref → 后端 list 恢复 + 行内动作
├── api/ingest.ts                              # + queue 端点 (enqueue/list/action)
└── locales/zh-CN.json                         # + 队列面板文案 (knowledge.ingest.queue.*)
```

### Pattern 1: 双后端任务体 + `**payload` 展开 adapter（Phase 61 范式，逐字照搬）

**What:** 任务体放 `tasks_impl.py`（零 procrastinate 依赖、keyword-only 形参）；procrastinate 路径在 `tasks.py` 加 `@app.task(name=...)` 包壳；in-process 路径在 `handlers.py` 加 `**payload` 展开 adapter 并在 `register_business_handlers()` 注册。两后端入参一致（procrastinate `defer_async(**payload)` / in-process `handler(payload)` → `run_*(**payload)`）。
**When to use:** 所有新 durable 任务（crawl_ingest）。
**Example:**

```python
# Source: server/durable/tasks_impl.py:63 (run_page_index 现状) + handlers.py:32
# 新增 run_crawl_ingest 任务体（薄封装现有 run_json_batch / ingest_from_refs）
async def run_crawl_ingest(*, batch_id: str, specs: list[dict], concurrency: int = 3) -> dict:
    from delivery.services.json_ingest import run_json_batch
    await run_json_batch(specs, concurrency)  # 每项已建 IngestRun，幂等 upsert
    return {"status": "ok", "batch_id": batch_id, "count": len(specs)}
```
```python
# tasks.py 包壳（procrastinate 路径，显式 name= 与 backends.py 查找键一致）
# Source: server/durable/tasks.py (durable_index/durable_graph/durable_page_index 同款)
@app.task(name="durable_crawl_ingest")
async def durable_crawl_ingest(**payload):
    from durable.tasks_impl import run_crawl_ingest
    return await run_crawl_ingest(**payload)
```
```python
# handlers.py adapter + register（in-process 路径）
# Source: server/durable/handlers.py:32-46
async def _crawl_ingest(payload: dict) -> Any:
    from durable.tasks_impl import run_crawl_ingest
    return await run_crawl_ingest(**payload)
# 在 register_business_handlers(): register_handler("durable_crawl_ingest", _crawl_ingest)
```

### Pattern 2: 派发→轮询 action 端点（镜像 `RepositoryReconcileView`）

**What:** POST 先落/更新 `IngestRun(QUEUED→RUNNING)` 真相源行拿 id，再 `DurableTaskService.defer` 入队，立即 202 返回；GET 端点从 `IngestRun` 回流真实状态供前端轮询。stop = `cancel(durable_job_id)` → status=STOPPED；retry = 重 defer 同 idempotency_key。
**When to use:** crawl_ingest 动作端点。
**Example:** 见 `RepositoryReconcileView.post`（`repositories/views.py:1538`）—— 先 `CleanupRun.objects.acreate(status=RUNNING)` 拿 run_id，`run_in_background(run_cleanup, ...)` 派发，202 返回 `{run_id, dispatched}`。本阶段把 `run_in_background` 换成 `DurableTaskService.defer`，`CleanupRun` 换成 `IngestRun`。

### Pattern 3: deterministic idempotency_key + 业务自带幂等（Phase 61 IDEMP-01）

**What:** `idempotency_key=crawl_ingest:{batch_id}`（procrastinate `queueing_lock`：todo 唯一，重复 defer 命中 `AlreadyEnqueued` 幂等吞并返回既有 job id，见 `backends.py:261`）。任务体内核已天然幂等（at-least-once 重复执行安全）。
**Example:**
```python
# 入队: await DurableTaskService.defer("durable_crawl_ingest",
#           {"batch_id": str(batch_id), "specs": specs, "concurrency": c},
#           queue=QUEUE_CRAWL_INGEST, idempotency_key=f"crawl_ingest:{batch_id}")
# 在途判定（list/start 用）: await DurableTaskService.has_active_by_key(f"crawl_ingest:{batch_id}")
```

### Anti-Patterns to Avoid

- **依赖前端内存 batchId/ref 恢复队列**：`BatchIngestPanel.vue:155` 现 `const batchId = ref<string|null>(null)` + `runTriple = ref({...})`——刷新即丢、重启即丢。CRAWL-02 命门是从 DB（`IngestRun`）恢复，必须删除这条内存路径。
- **裸 `run_in_background` 跑 page_index**：`tree_views.py:182` 现 `run_in_background(CorpusTreeService.build_full, name="corpus_tree_full_rebuild")`——进程内、不持久、重启丢。PAGEIDX-01 要求改 `DurableTaskService.defer(QUEUE_PAGE_INDEX)`。
- **直接 import procrastinate**：业务代码（含 delivery/repositories）绝不直接 import procrastinate，只经 `DurableTaskService` + `durable.queues` 常量（`test_no_direct_import.py` 守护，允许清单仅 `durable/backends.py`/`tasks.py`/`management/`/`settings.py`/`tests/`）。
- **page_index 无 hash 跳过 → 重复树/重复 summary**：必须先算 target hash，未变即 `{"status": "skipped"}` 返回，不重跑 LLM 聚类（PAGEIDX-01 命门）。
- **长任务塞同一队列**：crawl_ingest 与 page_index 是**独立逻辑队列**，避免长索引堵爬取（REQUIREMENTS Out of Scope 明确）。

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| 任务持久化/重启续跑/跨副本竞争 | 自写 DB 轮询 worker | `DurableTaskService.defer` + procrastinate（Phase 60） | 已交付 lease/heartbeat/CAS/启动恢复/periodic rescue |
| 在途去重 | 自查「是否已在跑」 | `idempotency_key`(queueing_lock) + `has_active_by_key`（`service.py:137`） | Phase 61 已建按 queueing_lock 的正确判定门面 |
| 入库去重（at-least-once 幂等） | 新写去重逻辑 | `WorkItemService.upsert`（三元组 unique）+ 文档 content_hash + `aarchive_exists`（`ingest_orchestrator.py:332`） | 现有三步全部幂等，重复执行不产生重复数据 |
| 有界并发批量摄取 | 新写并发控制 | `run_json_batch`（`json_ingest.py:101`，`asyncio.Semaphore` 1–10） | 已有，每项 spec 带 run_id |
| 派发→轮询前端范式 | 新写 WS/SSE | `useMutation` + `useQuery refetchInterval`（`reconcile.ts:86` / `ingest.ts`） | 既有稳定范式，守护测试以真实 zh-CN.json 锁文案 |
| 能力树结构校验 | 新写校验 | `validate_and_assemble_tree`（`tree_schema.py:243`） | 结构/路径真实性/monorepo 对齐齐全 |
| 取消 todo job | 自写状态翻转 | `DurableTaskService.cancel`（`service.py:126`，procrastinate `cancel_job_by_id_async`） | 仅能取消 todo（未领取）；doing 不可中断（at-least-once 语义） |

**Key insight:** 本阶段 95% 是「把现有 best-effort `run_in_background` 调用替换为 `DurableTaskService.defer`，并把状态从内存搬到 `IngestRun` DB」，几乎不写新业务逻辑——所有摄取/树生成/并发/幂等内核已存在。

## Runtime State Inventory

> 本阶段是 refactor/migration（in-memory → DB 真相源；裸 background_runner → durable）。逐项核查：

| Category | Items Found | Action Required |
|----------|-------------|------------------|
| **Stored data** | `IngestRun`（`delivery_ingest_run` 表）已存在并落 status/steps/batch_id/board_url/mr_url。**缺** `QUEUED`/`STOPPED` 状态、`durable_job_id`、`idempotency_key` 列 | **migration**：加 `Status.QUEUED`/`STOPPED` choices（默认值兼容存量 RUNNING）+ `durable_job_id` (CharField, blank) + `idempotency_key` (CharField, db_index, blank)；存量行 status 不回退 |
| **Live service config** | 无外部 UI/DB-only 配置承载本阶段标识 | None — crawl_ingest/page_index 任务名是代码常量，procrastinate job 表由迁移自建（Phase 60 已注册条件 app） |
| **OS-registered state** | 无 OS 级注册（无 Task Scheduler / launchd / systemd 引用 batchId） | None — verified by grep（仅前端内存 `batchId` ref + URL path 参数） |
| **In-memory → DB 迁移（核心）** | `BatchIngestPanel.vue:155` `batchId = ref(null)` + `runTriple = ref({})` + `pollStartedAt`（仅内存）；后端 `JsonIngestBatchView` 仅返回 batch_id、无 list 端点 → 刷新/重启即丢队列视图 | **code edit**：前端删内存 batchId/ref 改后端 list 恢复；后端新增 `GET /delivery/ingest/queue/` 列表端点（按 batch_id 分组或按 run 列最近 N 条） |
| **裸 background_runner（page_index）** | `tree_views.py:182` `run_in_background(CorpusTreeService.build_full)`；`repositories/views.py:562` `_schedule_auto_summary` → `run_in_background(_auto_dispatch)`（→ `dispatch_repo_summary` 经 Runner 容器） | **code edit**：`tree_views.py` 改 `DurableTaskService.defer(QUEUE_PAGE_INDEX)`；per-repo summary dispatch 见 OQ-2（跨进程 Runner，建议本阶段先收口 `build_full`） |
| **Secrets/env vars** | 无 secret 名引用本阶段标识 | None — 飞书凭证经 `SystemSetting`、Claude 凭证经 `aget_claude_code_runtime_config`，均不含队列名/batchId |
| **Build artifacts / installed packages** | 无 egg-info / 编译产物引用 | None — 纯 Python 源 + Vue SFC 改动 |

**The canonical question — 文件全改完后还有什么运行时旧态？** procrastinate_jobs 表（Postgres）会持久化在途 crawl_ingest/page_index job——这正是「重启续跑」的来源：worker 进程重启后领 todo job，`retry_stalled_durable_jobs` periodic（DURABLE-03，`tasks.py`）扫 doing 但 worker 已死的 stalled job 重投。**SQLite/in-process fallback 不持久**（`backends.py:69` `_jobs` 进程内 dict，重启即丢）——明确为 dev 非 durable，不承诺恢复。

## Common Pitfalls

### Pitfall 1: 双后端入参不一致（Phase 61 Pitfall 1，已有解法）
**What goes wrong:** in-process 后端 `_run_job` 以 `await handler(payload)` 整传 dict，procrastinate 经 `defer_async(**payload)` 展开 kwargs；若把 keyword-only 任务体直接注册到 in-process 会炸。
**How to avoid:** crawl_ingest 必须在 `handlers.py` 加 `_crawl_ingest(payload)` → `run_crawl_ingest(**payload)` 的展开 adapter，并在 `register_business_handlers()`（`handlers.py:38`）注册——照搬 `_index`/`_graph`/`_page_index`。
**Warning sign:** `TypeError: run_crawl_ingest() takes 0 positional arguments but 1 was given`。

### Pitfall 2: stop 对 doing job 无效（at-least-once 真相）
**What goes wrong:** `cancel(job_id)` 仅能取消 todo（未领取）job（`backends.py:354` `cancel_job_by_id_async`）；已被 worker 领取（doing）的任务无法中断。
**How to avoid:** stop 语义 = `cancel`（若 todo）+ 标 `IngestRun.status=STOPPED`（终态可重投）；UI 文案明确「停止仅阻止尚未开始的项，进行中的项会跑完当前批」。绝不承诺中断在途。
**Warning sign:** 用户点 stop 后任务仍完成——这是 at-least-once 的预期，不是 bug。

### Pitfall 3: `has_active_by_key` 误用 `get(idempotency_key)`
**What goes wrong:** 传 deterministic key（`crawl_ingest:{batch_id}`）给 `get` 会走 `int(job_id)` 失败恒返 `unknown`（`backends.py:323`）。
**How to avoid:** 判定在途一律用 `DurableTaskService.has_active_by_key(key)`（`service.py:137`），按 queueing_lock 查活跃集（todo/doing/scheduled）。
**Warning sign:** list/start 端点把在途任务误判为「不存在/可重启」。

### Pitfall 4: page_index 无 hash 跳过导致重复树
**What goes wrong:** 直接每次 defer 都跑 `CorpusTreeService.build_full` → 重复 LLM 聚类、产生新 `CorpusTreeSnapshot`，浪费且可能漂移。
**How to avoid:** 任务体先算 target hash（见下 hash 定义），与上次构建 hash 比对，未变即 `return {"status": "skipped"}`。需一处存 last-built hash（推荐 `CorpusTreeSnapshot` 加 `source_hash` 列或写 `metadata`）。
**Warning sign:** 重复 defer 产生多个 active snapshot / 树内容相同但 version 递增。

### Pitfall 5: migration 默认值让存量 IngestRun 行为回退
**What goes wrong:** 加 `idempotency_key` NOT NULL 无默认 → 存量行迁移失败；改 status 默认 → 存量 RUNNING 行被改。
**How to avoid:** 新列 `blank=True`/`null` 或 `default=""`，不回填存量；`Status` 加枚举值不动现有行（兼容性约束：升级后已有部署行为不回退）。

### Pitfall 6: 同步入队点在 async view 事件循环线程上 `async_to_sync` 抛 RuntimeError（Phase 61 已踩）
**What goes wrong:** delivery 动作端点是 async（adrf），任务体/defer 是 async——可直接 `await DurableTaskService.defer(...)`，无需 `async_to_sync`。仅当从同步 helper 调用才需 `sync_to_async` 桥接（参考 `index_views._schedule_index` 修复，见 61-02 SUMMARY Deviation 1）。
**How to avoid:** delivery 端点内直接 `await defer(...)`。

## Code Examples

### 入队端点（镜像 RepositoryReconcileView.post + JsonIngestBatchView）
```python
# Source: 合成自 repositories/views.py:1538 (派发范式) + delivery/api/views.py:445 (JsonIngestBatchView)
class IngestQueueDispatchView(APIView):
    permission_classes = [IsAuthenticated]
    async def post(self, request):
        # 1) aresolve_items → 建/复用 IngestRun(QUEUED) 行 + 组 specs（含 run_id）
        # 2) batch_id = uuid4(); key = f"crawl_ingest:{batch_id}"
        # 3) job_id = await DurableTaskService.defer(
        #        "durable_crawl_ingest",
        #        {"batch_id": str(batch_id), "specs": specs, "concurrency": c},
        #        queue=QUEUE_CRAWL_INGEST, idempotency_key=key)
        # 4) 回写 IngestRun.durable_job_id / idempotency_key（真相源）
        # 5) return Response({"batch_id": ..., "runs": [...], "dispatched": True}, 202)
        ...
```

### stop / retry 动作（cancel + 重 defer）
```python
# Source: durable/service.py:126 (cancel) + 261 (AlreadyEnqueued 幂等)
# stop:  ok = await DurableTaskService.cancel(run.durable_job_id)
#        run.status = IngestRun.Status.STOPPED; await sync_to_async(run.save)(...)
# retry: 重新 defer 同 idempotency_key（queueing_lock 命中即幂等吞并；终态则建新 job）
```

### page_index 真实生成 + hash 跳过（填充 run_page_index）
```python
# Source: 替换 server/durable/tasks_impl.py:63 占位实现
async def run_page_index(*, target_id: str | None = None, target_hash: str = "", **kwargs):
    from codegraph.services.corpus_tree import CorpusTreeService
    current = await _compute_corpus_source_hash()      # sorted(repo_id, ai_summary, facets) 的 sha256
    if target_hash and target_hash == current:
        return {"status": "skipped", "reason": "hash_unchanged", "target_id": target_id}
    result = await CorpusTreeService.build_full()       # 已幂等：unassigned 兜底 + 沿用旧 pin
    return {"status": result.get("status"), "target_id": target_id, "source_hash": current}
```
```python
# tree_views.py:182 改造（KnowledgeTreeRebuildView.post）
# 旧: run_in_background(lambda: CorpusTreeService.build_full(), name="corpus_tree_full_rebuild")
# 新: from durable import DurableTaskService, QUEUE_PAGE_INDEX
#     key = "page_index:corpus_tree"
#     await DurableTaskService.defer("durable_page_index",
#         {"target_id": "corpus_tree", "target_hash": await _compute_corpus_source_hash()},
#         queue=QUEUE_PAGE_INDEX, idempotency_key=key)
```

### 前端：移除内存 batchId，改后端 list 恢复
```ts
// Source: 重写 web/src/components/knowledge/BatchIngestPanel.vue:155 + 镜像 reconcile.ts:86
// 删除: const batchId = ref<string|null>(null) / runTriple ref / pollStartedAt
// 新增 list query（刷新即从后端恢复）：
const queueQuery = useQuery({
  queryKey: ['ingest-queue'],
  queryFn: () => ingestApi.listQueue(),
  refetchInterval: q => (q.state.data?.some(r => r.status === 'running' || r.status === 'queued') ? 2000 : false),
})
// 行内动作: ingestApi.startRun(id) / stopRun(id) / retryRun(id) → invalidate ['ingest-queue']
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| `run_in_background` + 内存 batchId | `DurableTaskService.defer` + `IngestRun` DB 真相源 | Phase 62（本阶段） | 刷新/重启续跑 |
| index/graph 入队走 `run_in_background(wrap_resumable)` | 已迁 `DurableTaskService.defer`（Phase 61） | Phase 61 | 本阶段 crawl_ingest 照搬同范式 |
| `run_page_index` 占位 noop（`tasks_impl.py:63`） | 填充真实生成 + hash 跳过 | Phase 62（本阶段） | PAGEIDX-01 兑现 |
| `background_runner` 三套并存 | 降级为 dev fallback/轻任务；生产走 durable | Phase 61 (MIGRATE-02) | crawl/page_index 加入 durable 收口 |

**Deprecated/outdated:**
- 前端内存 `batchId`/`runTriple`/`pollStartedAt`（`BatchIngestPanel.vue:155-192`）：本阶段移除，改后端 list 恢复。
- `tree_views.py:182` 裸 `run_in_background`：本阶段改 durable defer。

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | page_index 主目标 = `CorpusTreeService.build_full`（全局域树），per-repo `dispatch_repo_summary`（Runner 容器）本阶段不强制收口 | Standard Stack / OQ-2 | 若 PAGEIDX-01 必须含 per-repo 树，则改造面更大（跨进程 Runner dispatch durable 化） |
| A2 | target hash 推荐定义 = 全部仓库 `(id, ai_summary, facets)` 排序后的 sha256（域树输入指纹）；per-repo 树用 `last_indexed_commit_sha`/FileIndex 集合 hash | Claude's Discretion / OQ-3 | hash 定义不当 → 该跳过时重跑或该重跑时跳过 |
| A3 | `IngestRun` 推荐扩列（`durable_job_id` + `idempotency_key` + `QUEUED`/`STOPPED` status）而非纯复用 | Runtime State Inventory / OQ-1 | 不扩列则 stop/retry 无法定位 job、无法表达待跑/已停态 |
| A4 | list 端点按 batch_id 分组返回最近 N 批（或扁平最近 N 条 run），无分页（内部团队工具，对齐既有 batch detail 范式） | Architecture Patterns | 大量历史 run 时需加分页/限制 |
| A5 | crawl_ingest 队列项 = 一批（batch）一个 durable job（包内多 spec 并发），非每 run 一个 job | Code Examples | 若需 per-run 独立 start/stop，则改为每 run 一个 job + idempotency_key=crawl_ingest:{run_id} |

**确认建议:** A1/A2/A3 应在 plan-phase 经 Claude's Discretion 决策落地（CONTEXT 已授权 Claude 决断这三项）。A5 影响动作端点粒度，建议 plan 时明确。

## Open Questions

1. **OQ-1: `IngestRun` 扩列范围**
   - What we know: 现模型有 status(RUNNING/COMPLETED/FAILED)/batch_id/steps/board_url/mr_url/project/error/时间戳（`ingest_run.py:50`）。
   - What's unclear: 加 `durable_job_id` + `idempotency_key` + `QUEUED`/`STOPPED` 是否够，是否需 `concurrency`/`source_url`/`crawl_url` 留痕列。
   - Recommendation: 最小扩列（durable_job_id/idempotency_key/2 状态）+ migration 兼容存量；其余按需。

2. **OQ-2: per-repo PageIndex（dispatch_repo_summary）是否本阶段收口**
   - What we know: `repositories/views.py:562` `_schedule_auto_summary` → `dispatch_repo_summary` 经 Runner 容器（DispatchTask，跨进程），与本地 durable 任务模型不同；CONTEXT 措辞「`tree_views.py` 等裸 background_runner」。
   - What's unclear: 「等」是否含 per-repo summary 的 `_schedule_auto_summary`。
   - Recommendation: 本阶段先收口 `tree_views.py`（`CorpusTreeService.build_full`，纯本地 LLM 任务）；per-repo summary dispatch 的 durable 化（让 dispatch 步骤本身可重启续跑）作为 stretch，若纳入需把「建 session + dispatch」封进 page_index 任务体并按 repo file-set hash 跳过。

3. **OQ-3: page_index target hash 精确定义**
   - What we know: 域树输入 = 全仓 `ai_summary` + `facets`（`corpus_tree.py:104`）；per-repo 树输入 = 仓库源码（FileIndex paths）。
   - What's unclear: hash 存哪（`CorpusTreeSnapshot.source_hash` 新列 vs `metadata` JSON）。
   - Recommendation: 加 `CorpusTreeSnapshot.source_hash` 列（或写入既有 metadata），构建后落值，下次 defer 前比对。

4. **OQ-4: 队列粒度（per-batch vs per-run job）** — 见 A5；建议 per-batch（与现 `run_json_batch` 批语义一致），行内 start/stop 作用于整批。

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| procrastinate[django] | durable 后端 | ✓ | 3.8.1 | in-process（SQLite，非 durable） |
| PostgreSQL | durable 真正持久化/重启续跑 | 部署依赖 | 17（compose） | SQLite in-process（dev，不承诺恢复） |
| Django ORM migration | IngestRun 扩列 | ✓ | Django 6.0 | — |
| 系统飞书凭证 / 默认 LLM provider | crawl + AI 抽条目 | 运行时配置 | — | `feishu_not_configured` 深链引导（保留）/ provider 缺失返可读错误 |
| @tanstack/vue-query + vue-i18n | 前端面板 | ✓ | 既有 | — |

**Missing dependencies with no fallback:** none（所有底座 Phase 60/61 已交付）。
**Missing dependencies with fallback:** Postgres 缺失时 → in-process fallback（dev 可跑入队语义，但不承诺重启恢复，明确非 durable）。

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | 后端 pytest 9.x + pytest-asyncio + pytest-django；前端 vitest 4 + @vue/test-utils + happy-dom |
| Config file | `server/pyproject.toml`（addopts 默认 `not postgres_queue`）；`web/vitest.config.*` |
| Quick run command | `cd server && uv run pytest tests/durable tests/delivery -q` |
| Full suite command | 后端 `cd server && uv run pytest -q`；前端 `cd web && pnpm test`；Postgres 专项 `DATABASE_URL=postgres://... DURABLE_TASK_BACKEND=procrastinate uv run pytest -m postgres_queue --allow-hosts=127.0.0.1,localhost -q` |

### Phase Requirements → Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| CRAWL-01 | enqueue → `IngestRun(QUEUED)` + `defer(QUEUE_CRAWL_INGEST, idempotency_key)` 入参契约 | unit | `uv run pytest tests/delivery/test_ingest_queue.py -x` | ❌ Wave 0 |
| CRAWL-01 | 重复 enqueue 同 batch → queueing_lock 幂等不双跑（in-process 单条 + postgres queueing_lock） | unit/postgres | `uv run pytest tests/durable/test_idempotency.py -x` | 🔶 扩既有（`test_idempotency.py` 已存在） |
| CRAWL-01 | 入库 at-least-once：重复执行 run_crawl_ingest 不产生重复 WorkItem/Document/Archive | unit | `uv run pytest tests/delivery/test_crawl_ingest_idempotent.py -x` | ❌ Wave 0 |
| CRAWL-01 | stop → cancel + status=STOPPED；retry → 重 defer 同 key | unit | `uv run pytest tests/delivery/test_ingest_queue.py::test_stop_retry -x` | ❌ Wave 0 |
| CRAWL-01 | 断点恢复：list 端点从 `IngestRun`（DB）重建队列（不依赖内存） | unit | `uv run pytest tests/delivery/test_ingest_queue.py::test_list_restores_from_db -x` | ❌ Wave 0 |
| CRAWL-02 | 面板刷新后从后端 list 恢复（无内存 batchId）；行内 start/stop/retry 调对应 API | component | `pnpm test BatchIngestPanel` | ❌ Wave 0 |
| CRAWL-02 | i18n 文案以真实 `zh-CN.json` 作 messages 守护（关键状态/动作措辞不被改空） | component | `pnpm test BatchIngestPanel`（createI18n 真实 messages） | ❌ Wave 0 |
| CRAWL-02 | `feishu_not_configured` 深链保留（既有行为不回退） | component | `pnpm test BatchIngestPanel::feishu_deeplink` | 🔶 现有行为，补守护 |
| PAGEIDX-01 | `tree_views.py` rebuild 改 `defer(QUEUE_PAGE_INDEX)`（grep/契约断言） | unit | `uv run pytest tests/repositories/test_knowledge_tree.py -x` | ❌ Wave 0 |
| PAGEIDX-01 | page_index hash 未变跳过（return skipped，不调 build_full）；hash 变则重建；重复执行无重复 snapshot | unit | `uv run pytest tests/durable/test_page_index.py -x` | ❌ Wave 0（扩 `test_idempotency.py` page_index 段） |

### Sampling Rate
- **Per task commit:** `cd server && uv run pytest tests/durable tests/delivery -q`（+ 改前端时 `pnpm test BatchIngestPanel`）
- **Per wave merge:** 后端全量 `uv run pytest -q` + 前端 `pnpm test`
- **Phase gate:** 后端 + 前端全绿；Postgres 专项 `-m postgres_queue`（CI，本地无 Postgres 默认 skip）；`manage.py makemigrations --check` 干净

### Wave 0 Gaps
- [ ] `server/tests/delivery/test_ingest_queue.py` — enqueue/list/detail/start/stop/retry 端点契约 + 从 DB 恢复（CRAWL-01）
- [ ] `server/tests/delivery/test_crawl_ingest_idempotent.py` — run_crawl_ingest 重复执行幂等（CRAWL-01）
- [ ] `server/tests/durable/test_page_index.py`（或扩 `test_idempotency.py` page_index 段）— hash 跳过/重建/无重复 snapshot（PAGEIDX-01）
- [ ] `server/tests/repositories/test_knowledge_tree.py` — rebuild 改 defer 契约（PAGEIDX-01）
- [ ] `web/.../BatchIngestPanel.spec.ts` — list 恢复 + 行内动作 + 真实 zh-CN.json i18n + feishu 深链守护（CRAWL-02）
- [ ] Framework install: none（pytest/vitest 既有）

## Security Domain

### Applicable ASVS Categories (Level 1)

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | yes | 全部 delivery 端点 `IsAuthenticated`（既有范式，`views.py:52` 等）；新动作端点同款 |
| V3 Session Management | no | 复用既有 cookie-JWT（client.ts refresh），本阶段不触 |
| V4 Access Control | yes | crawl_ingest 动作端点 `IsAuthenticated`；page_index rebuild 维持 `IsAdminUser`（`tree_views.py:178`，不放宽） |
| V5 Input Validation | yes | URL/三元组经既有 serializer 校验（http(s) 前缀 + 三元组正整数）；SSRF 边界在 `crawl_service._ais_safe_public_url`（`crawl_service.py:315`，禁私网/环回/不跟随跳转） |
| V6 Cryptography | yes（不新增） | 飞书凭证 Fernet 加密（`SystemSetting` + `decrypt_value`，既有）；不 hand-roll |
| V7 Errors/Logging | yes | `IngestRun.error`/`steps[*].error` 经 `_safe_error`（`_redact_secrets` + 截断，`ingest_orchestrator.py:70`）；durable payload 仅内部 id，绝不含凭证/明文 token |

### Known Threat Patterns for {Django adrf + Procrastinate + Vue}

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| SSRF（用户贴任意 URL 爬取） | Tampering/InfoDisclosure | 既有 `_ais_safe_public_url` 公网校验 + 不跟随跳转 + 大小/超时上限（`crawl_service.py:315-365`）——本阶段不放宽 |
| 凭证泄漏进 durable payload / IngestRun | InfoDisclosure | payload 仅放 batch_id/run_id/specs(三元组)，绝不放 token；error 经 `_safe_error` 脱敏 |
| 越权触发/取消他人队列项 | Elevation | 端点 `IsAuthenticated`；`IngestRun` 无 owner（内部团队工具 + 不可猜 UUIDv4，沿用 `IngestRunDetailView` 既有归属说明 `views.py:271`） |
| at-least-once 重复执行重复外部副作用 | — | 本阶段摄取为内部 upsert（无飞书通知/建群/PR 外部副作用）；外部副作用 fencing 是 Phase 63 IDEMP-02（明确不在范围） |
| page_index rebuild 滥用（重 LLM 聚类） | DoS | `IsAdminUser` + hash 跳过 + queueing_lock 去重（同 key 不堆积） |

## Sources

### Primary (HIGH confidence) — 本仓库代码 file:line
- `server/durable/service.py:82-166` — `DurableTaskService.defer/get/cancel/has_active_by_key/retry_stalled` 签名
- `server/durable/queues.py:15-17` — `QUEUE_CRAWL_INGEST="crawl_ingest"` / `QUEUE_PAGE_INDEX="page_index"`（确认存在）
- `server/durable/tasks_impl.py:63` — `run_page_index` 占位 noop（待填充）
- `server/durable/handlers.py:32-46` — `_page_index` adapter + `register_business_handlers()`（`durable_page_index` 已注册）
- `server/durable/backends.py:97-194,226-369` — in-process / procrastinate 后端 defer/cancel/has_active_by_key 实现 + 状态语义
- `server/durable/apps.py:15-47` — `ready()` 无条件注册 business handler + 条件 procrastinate 注册
- `server/delivery/models/ingest_run.py:42-95` — `IngestRun`（Status RUNNING/COMPLETED/FAILED、batch_id、steps、无 durable_job_id/idempotency_key）
- `server/delivery/services/ingest_orchestrator.py:134-394` — `ingest_from_refs` 三步 best-effort + 幂等（upsert/content/aarchive_exists）
- `server/delivery/services/json_ingest.py:60-124` — `aresolve_items` / `run_json_batch`（有界并发）
- `server/delivery/services/crawl_service.py:315-561` — SSRF 校验 + `crawl_url`（请求级，非队列）
- `server/delivery/api/views.py:220-510,52` — IngestDispatch/RunDetail/BatchDispatch/JsonIngestBatch 现状 + IsAuthenticated；`run_in_background` 派发
- `server/delivery/urls.py:24-83` — ingest 路由（字面段在 uuid 前范式）
- `server/repositories/views.py:1512-1614,535-562` — `RepositoryReconcileView`/`CleanupStatusView` 派发→轮询范式；`_schedule_auto_summary`
- `server/repositories/tree_views.py:175-188` — `KnowledgeTreeRebuildView` 裸 `run_in_background(CorpusTreeService.build_full)`
- `server/codegraph/services/corpus_tree.py:86-152` — `build_full` LLM 聚类（域树输入 = ai_summary+facets）
- `server/repositories/tree_schema.py:243` — `validate_and_assemble_tree`
- `web/src/components/knowledge/BatchIngestPanel.vue:155-205` — 内存 batchId/ref + refetchInterval 轮询（待重写）
- `web/src/api/ingest.ts` + `web/src/api/reconcile.ts:86-101` — API 客户端 + 派发→轮询范式
- `.planning/phases/60-durable/60-01-SUMMARY.md` / `60-03-SUMMARY.md` / `61-01-SUMMARY.md` / `61-02-SUMMARY.md` — durable API 契约 + 双后端范式 + 迁移范式

### Secondary (MEDIUM confidence)
- `.planning/REQUIREMENTS.md` / `STATE.md`（v0.12.0 约束、at-least-once 不变量、队列边界）

### Tertiary (LOW confidence)
- 无 — 本阶段全部基于已落地代码，无外部 WebSearch 依赖。

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — 零新依赖，全部 Phase 60/61 已落地 + file:line 确认
- Architecture: HIGH — 派发→轮询 / 双后端 adapter / deterministic key 均有逐字可照搬的既有实现
- Pitfalls: HIGH — 多数为 Phase 61 已踩并记录的同类陷阱
- Open Questions: MEDIUM — OQ-1/2/3 属 CONTEXT 已授权的 Claude's Discretion，需 plan 时决断

**Research date:** 2026-06-20
**Valid until:** 2026-07-20（稳定内部代码库；procrastinate 3.8.1 已锁）

## RESEARCH COMPLETE

**Phase:** 62 - 爬取+入库 durable 队列 + PageIndex 接入
**Confidence:** HIGH

### Key Findings
- 底座齐备：`DurableTaskService.defer`、`QUEUE_CRAWL_INGEST`/`QUEUE_PAGE_INDEX`、双后端任务体范式、`run_page_index` 占位 + `durable_page_index` 已注册、`has_active_by_key` 在途判定门面均已由 Phase 60/61 交付——本阶段几乎全是接入与改造，零新外部依赖。
- crawl_ingest 任务体可薄封装现有 `run_json_batch`/`ingest_from_refs`（已天然幂等：三元组 upsert / content_hash / `aarchive_exists`），满足 at-least-once。
- 动作端点镜像 `RepositoryReconcileView`（POST 派发 202 + GET 轮询 DB 真相源）；前端镜像 `reconcile.ts`/`ReconcilePanel.vue`（refetchInterval running→2s + useI18n）。
- CRAWL-02 命门 = 删除 `BatchIngestPanel.vue:155` 内存 `batchId`/`ref`，新增后端 list 端点从 `IngestRun` 恢复；面板当前是硬编码中文，须迁 `zh-CN.json`。
- PAGEIDX-01 = 填充 `run_page_index`（`CorpusTreeService.build_full` + target hash 跳过）+ `tree_views.py:182` 裸 `run_in_background` 改 `defer(QUEUE_PAGE_INDEX)`。

### File Created
`.planning/phases/62-crawl/62-RESEARCH.md`

### Confidence Assessment
| Area | Level | Reason |
|------|-------|--------|
| Standard Stack | HIGH | 零新依赖，全部既有 file:line 确认 |
| Architecture | HIGH | 逐字可照搬的既有派发→轮询/双后端范式 |
| Pitfalls | HIGH | 多为 Phase 61 已记录的同类陷阱 |

### Open Questions
- OQ-1 IngestRun 扩列范围（推荐加 durable_job_id/idempotency_key/QUEUED/STOPPED）
- OQ-2 per-repo PageIndex（dispatch_repo_summary，Runner 跨进程）是否本阶段收口（推荐先做 build_full）
- OQ-3 page_index target hash 精确定义 + 存放位置（推荐 CorpusTreeSnapshot.source_hash）
- OQ-4 队列粒度 per-batch vs per-run（推荐 per-batch）
（均属 CONTEXT 已授权的 Claude's Discretion，plan-phase 决断）

### Ready for Planning
Research complete. Planner can now create PLAN.md files.
