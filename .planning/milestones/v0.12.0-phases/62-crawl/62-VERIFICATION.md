---
phase: 62-crawl
verified: 2026-06-20T17:10:00Z
status: human_needed
score: 13/13 must-haves verified (code-level)
overrides_applied: 0
re_verification:
  previous_status: null
human_verification:

  - test: "在真实 Postgres 部署上：贴链接入队爬取批次 → `docker compose up -d` / Pod 重建 worker+web 容器 → 确认队列从 DB 恢复且 durable job 自动续跑"
    expected: "刷新页面 + 容器重建后队列列表从 IngestRun(DB) 恢复，未完成批次 worker 重启后领 todo 续跑、不丢任务"
    why_human: "需真实 Postgres + 容器/Pod 重启，本环境为 SQLite in-process 后端、无法重启容器（DB-truth-source list 恢复已由 SQLite 自动化覆盖，仅 restart-resume 为人工）"

  - test: "在真实 Postgres 上运行 `cd server && uv run pytest -m postgres_queue` 验证同 batch 重复 enqueue 经 queueing_lock 真实去重 + 并发重复执行 at-least-once 幂等不产生重复数据"
    expected: "同 idempotency_key=crawl_ingest:{batch_id} 重复 defer 命中 queueing_lock 不堆积/不双跑；重复执行 run_crawl_ingest 不产生重复 WorkItem/Document/Archive"
    why_human: "queueing_lock 真实去重依赖 Postgres procrastinate_jobs（SQLite 默认 skip postgres_queue 标记用例）；代码层幂等键与 COMPLETED 排除已由 SQLite 守护测试覆盖"
audit_acknowledged:
  milestone: v0.25.0
  at: 2026-08-31
  status: human_needed
---

# Phase 62: 爬取+入库 durable 队列 + PageIndex 接入 — Verification Report

**Phase Goal:** 把链接爬取+入库改造为 durable 任务（DB 真相源、刷新+容器/Pod 重建后自动续跑、at-least-once 幂等复用 IngestRun/upsert）；前端 BatchIngestPanel 由内存 batchId/ref → 后端恢复的队列列表+实时状态+行内 start/stop/retry；PageIndex/TOC/tree 生成接入 durable 队列（收口 tree_views.py 裸 background_runner），按 target hash 幂等跳过。
**Verified:** 2026-06-20T17:10:00Z
**Status:** human_needed
**Re-verification:** No — initial verification

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | 用户入队爬取批次作为 durable 任务进 QUEUE_CRAWL_INGEST，IngestRun 是 DB 真相源 | ✓ VERIFIED | `tasks_impl.py:63` `run_crawl_ingest` 按 batch_id 从 `IngestRun.objects.filter` 重建 specs；`views.py:597` enqueue 建 `IngestRun(QUEUED)` + `defer(QUEUE_CRAWL_INGEST)`；payload 仅 batch_id/concurrency |
| 2 | 队列列表端点从 IngestRun(DB) 重建，不依赖内存——刷新/重启可恢复 | ✓ VERIFIED | `views.py:555` `IngestQueueView.get` `IngestRun.objects.filter(batch_id__isnull=False)` 按 batch_id 分组聚合，无任何内存态 |
| 3 | stop=cancel(durable_job_id)+STOPPED 终态；start/retry=同 idempotency_key 重新 defer | ✓ VERIFIED | `views.py:716` `IngestQueueActionView`：stop `DurableTaskService.cancel(job_id)`+置 STOPPED（line 785/793）；start/retry `defer(...idempotency_key=key)`（line 753） |
| 4 | run_crawl_ingest 重复执行不产生重复 WorkItem/Document/Archive (at-least-once 幂等) | ✓ VERIFIED | 薄封装天然幂等 `ingest_from_urls`（三元组 upsert/content_hash/aarchive_exists），排除 COMPLETED 行（`tasks_impl.py:84-89`）；`test_crawl_ingest_idempotent.py` 3 用例绿 |
| 5 | 重复 enqueue 同 batch 命中 queueing_lock 幂等不双跑 | ✓ VERIFIED (code) / human | deterministic `idempotency_key="crawl_ingest:{batch_id}"`（`views.py:631`）；真实 queueing_lock 去重需 Postgres `-m postgres_queue`（见 human_verification #2） |
| 6 | 知识树重建经 DurableTaskService.defer(QUEUE_PAGE_INDEX)，不再裸 run_in_background | ✓ VERIFIED | `tree_views.py:180` `KnowledgeTreeRebuildView.post` `defer("durable_page_index", queue=QUEUE_PAGE_INDEX, idempotency_key="page_index:corpus_tree")`；无 run_in_background 残留 |
| 7 | run_page_index 先算 target hash，未变即 skipped 不调 build_full | ✓ VERIFIED | `tasks_impl.py:146-151` `current=compute_source_hash()`，`target_hash==current` → `{"status":"skipped"}` 不调 build_full；`test_page_index.py` 5 用例绿 |
| 8 | hash 变化则真实 build_full 重建，落 source_hash 供下次比对 | ✓ VERIFIED | `tasks_impl.py:153` 调 `build_full()`；`corpus_tree.py:174-176` build_full 算 hash 经 `_activate_new_snapshot(source_hash=...)` 落库 |
| 9 | 面板队列列表+状态一律从后端 list 恢复，移除内存 batchId/runTriple/pollStartedAt 作列表来源 | ✓ VERIFIED | `BatchIngestPanel.vue:28` `useQuery(['crawl-ingest-queue'], listQueue)`；无 runTriple/pollStartedAt（grep 0 命中）；batchId 仅作行内动作 spinner key 非列表来源 |
| 10 | 行内开始/停止/重试调对应队列动作 API；停止经 useConfirmDialog 破坏性确认 | ✓ VERIFIED | `BatchIngestPanel.vue:140-144` startRun/stopRun/retryRun；`:17` `useConfirmDialog()` stop 前置 confirm |
| 11 | running/queued 项触发 refetchInterval=2s 轮询，全终态停轮 | ✓ VERIFIED | `BatchIngestPanel.vue:31` `refetchInterval: q => some(running||queued) ? 2000 : false` |
| 12 | feishu_not_configured 引导深链保留（既有行为不回退） | ✓ VERIFIED | `BatchIngestPanel.vue:57` feishu_not_configured 分支 + `:241` `data-testid="crawl-feishu-deeplink"` |
| 13 | 新增文案接入 zh-CN.json crawlQueue.*，守护测试以真实 zh-CN.json 锁文案 | ✓ VERIFIED | `zh-CN.json:610` `"crawlQueue"` 命名空间；`BatchIngestPanel.spec.ts` 6 用例以真实 zh-CN.json 作 messages 绿 |

**Score:** 13/13 truths verified at code level (truths #1 & #5 runtime confirmation on real Postgres routed to human verification)

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `server/durable/tasks_impl.py` | run_crawl_ingest + run_page_index 真实生成 | ✓ VERIFIED | run_crawl_ingest (line 63, 薄封装 ingest_from_urls)；run_page_index (line 130, build_full + hash 跳过) |
| `server/delivery/models/ingest_run.py` | QUEUED/STOPPED + durable_job_id + idempotency_key | ✓ VERIFIED | Status.QUEUED/STOPPED (line 58/62)；durable_job_id (91)；idempotency_key db_index (94) |
| `server/delivery/migrations/0024_ingestrun_durable_queue.py` | 加列迁移 | ✓ VERIFIED | 存在；`makemigrations --check` 干净（SUMMARY） |
| `server/delivery/api/views.py` | IngestQueueView/DetailView/ActionView | ✓ VERIFIED | 三 view (line 536/682/716) + `_aggregate_queue_status` (514) |
| `server/delivery/urls.py` | queue/ + queue/<uuid>/ + queue/<uuid>/<action>/ | ✓ VERIFIED | line 70-84，字面段在 uuid 前 |
| `server/durable/handlers.py` | durable_crawl_ingest in-process 注册 | ✓ VERIFIED | `_crawl_ingest` adapter (line 38) + register (53) |
| `server/durable/tasks.py` | durable_crawl_ingest procrastinate 包壳 | ✓ VERIFIED | `@app.task(name="durable_crawl_ingest", queue=QUEUE_CRAWL_INGEST)` (line 83) |
| `server/repositories/models.py` | CorpusTreeSnapshot.source_hash | ✓ VERIFIED | source_hash CharField (line 805) |
| `server/repositories/migrations/0038_corpustreesnapshot_source_hash.py` | AddField 迁移 | ✓ VERIFIED | 存在；`makemigrations --check` 干净（SUMMARY） |
| `server/repositories/tree_views.py` | KnowledgeTreeRebuildView 改 durable defer | ✓ VERIFIED | line 175-196 |
| `server/codegraph/services/corpus_tree.py` | compute_source_hash + build_full 落 hash | ✓ VERIFIED | compute_source_hash (83)，build_full (115/174)，_activate_new_snapshot source_hash 形参 (317/329) |
| `web/src/api/ingest.ts` | listQueue/enqueueQueue/startRun/stopRun/retryRun + CrawlQueueItem | ✓ VERIFIED | 类型 (165/173) + 5 方法 (252-271) |
| `web/src/components/knowledge/BatchIngestPanel.vue` | 后端恢复队列面板 + 行内动作 | ✓ VERIFIED | crawl-queue-panel (193) + 全 data-testid 钩子 |
| `web/src/locales/zh-CN.json` | crawlQueue.* 命名空间 | ✓ VERIFIED | line 610 |

### Key Link Verification

| From | To | Via | Status | Details |
|------|-----|-----|--------|---------|
| delivery/api/views.py | DurableTaskService.defer | enqueue/start/retry → defer(QUEUE_CRAWL_INGEST) | ✓ WIRED | views.py:659/753 |
| durable/tasks_impl.py | ingest_from_urls | run_crawl_ingest 逐 IngestRun 调用 | ✓ WIRED | tasks_impl.py:117 |
| durable/handlers.py | durable_crawl_ingest | register_handler in-process adapter | ✓ WIRED | handlers.py:53 |
| repositories/tree_views.py | DurableTaskService.defer | KnowledgeTreeRebuildView.post → defer(QUEUE_PAGE_INDEX) | ✓ WIRED | tree_views.py:187 |
| durable/tasks_impl.py | CorpusTreeService.build_full | run_page_index hash 变化时调用 | ✓ WIRED | tasks_impl.py:153 |
| BatchIngestPanel.vue | ingestApi.listQueue | useQuery refetchInterval running/queued→2000 | ✓ WIRED | BatchIngestPanel.vue:28-31 |
| BatchIngestPanel.vue | useConfirmDialog | stop 行内动作破坏性确认 | ✓ WIRED | BatchIngestPanel.vue:17 |

### Data-Flow Trace (Level 4)

| Artifact | Data Variable | Source | Produces Real Data | Status |
|----------|---------------|--------|--------------------|--------|
| IngestQueueView.get | items | `IngestRun.objects.filter(batch_id__isnull=False)` 真实 ORM 查询 + 分组聚合 | Yes | ✓ FLOWING |
| BatchIngestPanel.vue 列表 | queueQuery.data | `ingestApi.listQueue()` → GET /delivery/ingest/queue/ → 解包 {items} | Yes | ✓ FLOWING |
| run_page_index | source_hash | `compute_source_hash()` 读全仓 (id, ai_summary, facets) sha256 | Yes | ✓ FLOWING |

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
|----------|---------|--------|--------|
| 后端 durable+delivery 套件 | `uv run pytest tests/durable tests/delivery -q` | 495 passed, 1 failed (预存 INV-6 误报), 13 deselected | ✓ PASS (Phase 62 用例全绿) |
| 前端 knowledge 面板套件 | `pnpm vitest run src/components/knowledge` | 2 files / 8 tests passed | ✓ PASS |

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
|-------------|-------------|-------------|--------|----------|
| CRAWL-01 | 62-01 | 爬取入库 durable 任务（enqueue/list/detail/start/stop/retry/resume，DB 真相源，at-least-once 幂等） | ✓ SATISFIED | run_crawl_ingest 双后端 + IngestRun 扩列 + 4 端点 + test_ingest_queue (13) + test_crawl_ingest_idempotent (3) 绿；container-restart resume 见 human_verification #1 |
| CRAWL-02 | 62-03 | 前端 BatchIngestPanel 后端恢复队列 + 行内动作 + i18n | ✓ SATISFIED | ingest.ts 队列 API + 面板重写 + crawlQueue.* + BatchIngestPanel.spec (6) 绿 |
| PAGEIDX-01 | 62-02 | PageIndex/tree 接入 durable queue + target-hash 幂等 | ✓ SATISFIED | run_page_index 真实生成 + source_hash 列 + tree_views 收口 + test_page_index (5) + test_knowledge_tree (4) 绿 |

所有 3 个声明的 requirement ID 均被 plan 认领且实现验证；REQUIREMENTS.md 映射到 Phase 62 的 ID（CRAWL-01/02、PAGEIDX-01）无遗漏，无 ORPHANED。

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
|------|------|---------|----------|--------|
| — | — | 未发现 stub/占位/TBD/FIXME/XXX 等阻断标记于 Phase 62 改动文件 | — | run_crawl_ingest/run_page_index 均为真实接入；SUMMARY「Known Stubs: None」与代码一致 |

### Human Verification Required

#### 1. 真实 Postgres 容器重启续跑（CRAWL-01）

**Test:** 在真实 Postgres 部署上：贴链接入队爬取批次 → `docker compose up -d` / Pod 重建 worker+web 容器 → 确认队列从 DB 恢复且 durable job 自动续跑。
**Expected:** 刷新页面 + 容器重建后队列列表从 IngestRun(DB) 恢复，未完成批次 worker 重启后领 todo 续跑、不丢任务。
**Why human:** 需真实 Postgres + 容器/Pod 重启；本环境为 SQLite in-process 后端、无法重启容器。DB-truth-source list 恢复逻辑已由 SQLite 自动化覆盖（list 端点读 IngestRun），仅 real container-restart resume 为人工（与 62-VALIDATION Manual-Only 一致）。

#### 2. Postgres queueing_lock 真实去重 + 并发 at-least-once 幂等（CRAWL-01）

**Test:** 在真实 Postgres 上 `cd server && uv run pytest -m postgres_queue`，验证同 batch 重复 enqueue 经 queueing_lock 真实去重 + 并发重复执行不产生重复数据。
**Expected:** 同 idempotency_key 重复 defer 命中 queueing_lock 不堆积/不双跑；重复执行 run_crawl_ingest 不产生重复 WorkItem/Document/Archive。
**Why human:** queueing_lock 真实去重依赖 Postgres procrastinate_jobs（SQLite 默认 skip postgres_queue 用例）；幂等键派生与 COMPLETED 排除的代码逻辑已由 SQLite 守护覆盖。

### Gaps Summary

无阻断性 gap。全部 13 条 must-have truth + 14 项 artifact + 7 条 key link 在代码层验证通过，3 个 requirement ID（CRAWL-01/02、PAGEIDX-01）全部满足，Phase 62 用例（后端 16 新增 + 前端 6 + 既有套件）全绿。

**关于唯一 1 个失败用例（已评估为非 Phase 62 回归）：**
`tests/delivery/test_plan_session_inv6_guard.py::test_inv6_no_bypass_plan_session_write` 失败，经核实为**预存误报**，**非 Phase 62 引入**：

- 根因：INV-6 守护正则 `\bPlanSession\s*\(` 误命中 `server/chat/conversation_service.py:1922` 的**中文注释** `# SDD spec 反查：conversation → PlanSession(软引用会话) ...`（注释而非实例化/写表）。
- 证据：`conversation_service.py` 最近一次提交为 `1350f6b13 feat(config): add use_worktrees option`（**不在** Phase 62 提交集 c6bdc249e/c7716bdb8/4a54ae9c4/e51b3927b/7b86655e4/f55ba115e/8dc206bac/b7214ddd7 内）；工作树对该文件无 diff（`git status` 空）；该文件不在任何 62 plan 的 files_modified 列表。
- 结论：守护测试质量问题（正则未剥离注释行），与本阶段爬取/入库/PageIndex 改动无关。按用户指示，**记录但不据此判定 Phase 62 失败**（已存档于 `deferred-items.md`，建议后续修复守护跳过注释行）。

**状态判定（human_needed）：** 无 FAILED truth / 无 missing artifact / 无 NOT_WIRED link / 无 blocker，但存在 2 项需真实 Postgres + 容器重启的运行时行为人工确认（实现齐备、SQLite/vitest 自动化覆盖通过），故状态为 human_needed 而非 passed。

---

_Verified: 2026-06-20T17:10:00Z_
_Verifier: Claude (gsd-verifier)_
