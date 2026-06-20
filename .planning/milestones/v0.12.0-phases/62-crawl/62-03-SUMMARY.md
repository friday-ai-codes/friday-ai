---
phase: 62-crawl
plan: 03
subsystem: ui
tags: [frontend, vue, vue-query, i18n, crawl, ingest, durable-queue]

# Dependency graph
requires:
  - phase: 62-crawl (62-01)
    provides: delivery 队列动作端点 IngestQueueView(list/enqueue)/IngestQueueDetailView/IngestQueueActionView(start/stop/retry) + IngestQueueItemSerializer 字段形状
provides:
  - ingestApi 队列客户端：listQueue/enqueueQueue/startRun/stopRun/retryRun + CrawlQueueItem/CrawlQueueStatus 类型
  - 后端恢复的 durable 队列面板 BatchIngestPanel（刷新即从 DB list 端点恢复，无内存 batchId 依赖）
  - crawlQueue.* zh-CN 命名空间文案
  - BatchIngestPanel.spec.ts 守护（真实 zh-CN.json 锁文案 + 行内动作 + 停止确认 + feishu 深链）
affects: [62-VALIDATION 人工抽验, 后续 ingest UI 迭代]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "队列状态前端零内存态：列表/状态一律来自 useQuery(listQueue)，refetchInterval running/queued→2000 否则 false，刷新/重建即恢复（镜像 ReconcilePanel）"
    - "入队前预处理：crawlUrl 抽取条目 → enqueueQueue 入队，feishu_not_configured 走引导深链分支不入队（既有行为不回退）"
    - "行内破坏性动作经 useConfirmDialog().confirm({variant:'destructive'}) + 全局 GlobalConfirmDialog；守护测试以真实 zh-CN.json 锁文案（T-62-08）"

key-files:
  created:
    - web/src/components/knowledge/__tests__/BatchIngestPanel.spec.ts
  modified:
    - web/src/api/ingest.ts
    - web/src/components/knowledge/BatchIngestPanel.vue
    - web/src/locales/zh-CN.json

key-decisions:
  - "listQueue 解包后端 {items} 信封为裸 CrawlQueueItem[]（端点 GET /ingest/queue/ 返回 {items:[...]}，前端 .then(r => r.items ?? [])）"
  - "按 62-UI-SPEC 契约重写面板为「URL 爬取入队 + 后端恢复队列列表」单卡片，移除旧 JSON 编辑器/resolve 编辑表/dispatchJsonBatch 派发/artifacts 实时展开（属旧内存 batchId 流，UI-SPEC scope 外）；crawlUrl 保留为入队前预处理"
  - "行内动作用 actingKey=`${batchId}:${action}` 标记承载 per-row spinner + disabled（单一 async 函数，stop 前置 confirm），而非每行独立 useMutation"

patterns-established:
  - "爬取队列前端：useQuery 恢复 + invalidate 重拉 + 行内 start/stop/retry，状态徽标复用 ui/badge variant（muted/info/warning/destructive/success）+ 图标+文字"
  - "i18n 守护：vitest 以真实 zh-CN.json 作 createI18n messages，断言关键状态/确认措辞不被改空"

requirements-completed: [CRAWL-02]

# Metrics
duration: 8min
completed: 2026-06-21
---

# Phase 62 Plan 03: 前端 BatchIngestPanel 后端恢复 durable 队列面板 Summary

**BatchIngestPanel 重写为「URL 爬取入队 + 从后端 list 端点恢复的 durable 队列列表」：状态一律来自 ingestApi.listQueue（DB 真相源），useQuery refetchInterval running/queued→2s，行内开始/停止/重试调队列动作端点、停止经破坏性确认，文案接入 crawlQueue.* 中文，crawl-* data-testid + 真实 zh-CN.json 守护**

## Performance

- **Duration:** ~8 min
- **Started:** 2026-06-20T16:52Z
- **Completed:** 2026-06-20T17:00Z
- **Tasks:** 2
- **Files modified:** 4（1 created, 3 modified）

## Accomplishments
- `ingest.ts` 队列客户端：新增 `CrawlQueueItem`/`CrawlQueueStatus`（字段对齐 62-01 `IngestQueueItemSerializer`：batch_id/status/total/done/url_count/durable_job_id/idempotency_key/started_at/updated_at/error）+ `listQueue`（解包 `{items}`）/`enqueueQueue`/`startRun`/`stopRun`/`retryRun`；`crawlUrl` 与既有 JSON 批量摄取方法保留不动。
- `BatchIngestPanel.vue` 按 62-UI-SPEC 契约重写：单卡片 = URL 入队区 + 后端恢复队列列表。`useQuery(['crawl-ingest-queue'], listQueue)`，`refetchInterval: q => q.data?.some(running||queued) ? 2000 : false`——**移除内存 batchId/runTriple/pollStartedAt 作为列表来源**，刷新/重建即恢复。
- 行内动作按 status 条件渲染：queued/stopped/failed→开始，running/queued→停止（经 `useConfirmDialog().confirm({variant:'destructive'})`），failed/stopped/completed→重试；动作后 invalidate 队列 key，进行中按钮 disabled + spinner。
- Component States 全落地：loading→`Skeleton`×3、empty→`CompactEmptyState`(lucide--inbox)、error→`crawlQueue.loadError` + 重试加载、failed 项展开后端 error 红字；状态徽标复用 `ui/badge` variant（muted/info/warning/destructive/success）+ 图标+文字。
- `feishu_not_configured` 引导深链保留（黄框 + 去配置飞书应用按钮 → `router.push`），文案接 i18n，行为不回退。
- `zh-CN.json` 新增 `crawlQueue.*` 命名空间（逐键对齐 UI-SPEC i18n 段，中文优先），JSON 合法。
- 守护测试 `BatchIngestPanel.spec.ts`（6 用例）：以真实 zh-CN.json 锁文案 + 列表后端恢复 + 行内 start/stop/retry 调对应 API + 停止破坏性确认（含取消分支）+ feishu 深链。

## Task Commits

每个任务原子提交（Conventional Commits，中文 subject）：

1. **Task 1: ingest.ts 队列 API + crawlQueue.* 文案** - `8dc206bac` (feat)
2. **Task 2: BatchIngestPanel 改造为后端恢复 durable 队列面板 + vitest 守护** - `b7214ddd7` (feat)

## Files Created/Modified
- `web/src/api/ingest.ts`（改）- 新增 CrawlQueueItem/CrawlQueueStatus 类型 + listQueue/enqueueQueue/startRun/stopRun/retryRun 方法
- `web/src/components/knowledge/BatchIngestPanel.vue`（改/重写）- 后端恢复 durable 队列面板（UI-SPEC 契约 + crawl-* data-testid）
- `web/src/locales/zh-CN.json`（改）- 新增 crawlQueue.* 命名空间（additive，未触动既有键）
- `web/src/components/knowledge/__tests__/BatchIngestPanel.spec.ts`（新）- 真实 zh-CN.json i18n 锁文案守护（6 用例）

## Decisions Made
- 见 frontmatter key-decisions：listQueue 解包 `{items}` 信封；按 UI-SPEC scope 重写面板（移除旧 JSON 编辑器/resolve 表/dispatchJsonBatch/artifacts 内存流，crawlUrl 保留为入队前预处理）；行内动作用 actingKey 承载 per-row spinner（非每行 useMutation）。

## Deviations from Plan

None - plan executed exactly as written（plan 明确要求按 62-UI-SPEC 改造、移除内存 batchId/runTriple/pollStartedAt 作为列表来源；旧 JSON 编辑器/dispatch/artifacts 流为该内存流的一部分，随之移除属契约范围内，非 scope creep）。

## Issues Encountered
- Task 2 首次 eslint 报 `style/operator-linebreak`（EnqueueOutcome 联合类型 `=` 位置），经 `eslint --fix` 自动修复（纯样式，不改行为），修复后 6 用例仍全绿、vue-tsc 无新增错误。

## Known Stubs
None - 面板全部接入真实队列端点（listQueue/enqueueQueue/startRun/stopRun/retryRun）+ DB 真相源；无占位/硬编码空值流向 UI。

## Verification
- `cd web && pnpm vitest run src/components/knowledge` → 2 files / 8 tests passed（含本 plan 6 用例 + 既有 entity-components 2）。
- `cd web && pnpm vue-tsc --noEmit -p tsconfig.json` → 本 plan 文件（ingest.ts / BatchIngestPanel.vue / spec）零类型错误（过滤确认 NO_ERRORS_IN_MY_FILES）。
- `cd web && pnpm eslint src/components/knowledge/BatchIngestPanel.vue src/api/ingest.ts src/components/knowledge/__tests__/BatchIngestPanel.spec.ts` → clean。
- `node -e JSON.parse(zh-CN.json)` → valid。
- 人工抽验（里程碑级，需真实 Postgres 部署）：贴链接入队 → 刷新页面 → 队列从后端恢复（见 62-VALIDATION Manual-Only）。

## Next Phase Readiness
- CRAWL-02 闭环：面板贴链接入队、队列列表 + 实时状态、行内开始/停止/重试、刷新后从后端恢复（不依赖内存 batchId/ref）；feishu_not_configured 深链保留；i18n 默认中文。
- 旧 ingest.ts 的 dispatchJsonBatch/resolveItems/getWorkItemArtifacts 等方法仍保留（其他调用方未受影响），如后续无消费方可在独立清理 plan 评估移除。

## Self-Check: PASSED

- 所有文件存在：ingest.ts / BatchIngestPanel.vue / BatchIngestPanel.spec.ts / zh-CN.json / 62-03-SUMMARY.md。
- 两个任务提交均存在：`8dc206bac`（Task 1 feat）/ `b7214ddd7`（Task 2 feat）。

---
*Phase: 62-crawl*
*Completed: 2026-06-21*
