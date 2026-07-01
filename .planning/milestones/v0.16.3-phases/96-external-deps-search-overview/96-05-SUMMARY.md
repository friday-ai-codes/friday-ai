---
phase: 96-external-deps-search-overview
plan: 05
subsystem: web-knowledge
tags: [web, knowledge, dashboard, artifact, overview, i18n, KDEP-03]
requires: [96-03, 96-04]
provides:
  - knowledgeApi.getArtifactOverview() + 聚合类型
  - KnowledgeDashboard「交付文档 / 外部依赖」区块
affects:
  - web/src/api/knowledge.ts
  - web/src/components/knowledge/KnowledgeDashboard.vue
  - web/src/locales/zh-CN.json
tech-stack:
  added: []
  patterns: [useQuery-single-request, client-side-instant-filter, compact-empty-state, tile-grid]
key-files:
  created: []
  modified:
    - web/src/api/knowledge.ts
    - web/src/components/knowledge/KnowledgeDashboard.vue
    - web/src/locales/zh-CN.json
decisions:
  - 数据走 96-03 单次聚合接口（access_scope 过滤），不逐项目拉全量
  - 即时搜索为客户端过滤已加载条目（沿用 Dashboard 现有模式，无额外请求）
  - 区块插在「运行状态」之后，复用核心指标磁贴样式令牌 + 区块 header 范式
metrics:
  duration: ~25min
  completed: 2026-07-01
---

# Phase 96 Plan 05: Dashboard 交付文档区块 Summary

在 `KnowledgeDashboard.vue` 新增「交付文档 / 外部依赖」区块，与现有仓库/域指标并列、风格一致：按 `ArtifactType` 分组计数磁贴 + 每类入口（点击进搜索预筛）+ 区块内即时搜索 + 优雅空态 + 加载骨架。数据走 96-03 单次 access_scope 过滤聚合接口。

## What Changed

### Task 1 — knowledge.ts 聚合方法
- 新增类型 `ArtifactTypeCount` / `ArtifactOverviewItem` / `ArtifactOverview`（对齐 96-03 契约）。
- 新增 `getArtifactOverview(params?: { typeKey?: string })` → `GET /knowledge/artifacts/overview/`，挂到默认导出 `knowledgeApi`。仅新增，不改既有方法。

### Task 2 — KnowledgeDashboard 交付文档区块 + i18n
- script：`overviewQuery = useQuery({ queryKey:['knowledge','artifact-overview'], queryFn: knowledgeApi.getArtifactOverview, staleTime: 60_000 })`；派生 `depTypes/depItems/depTotal/depTruncated/depLoading/depEmpty`。客户端即时搜索 `depSearch` + `filteredDepItems`（title/type_name/project_name 包含匹配）。载体图标映射 + `goToDepType`（跳 `?tab=search&dep_type=`）+ `openDepItem`（external_link 新标签打开、其余 `emit('navigate','search')`）。
- template：在「运行状态」区之后插入 `<section class="card p-5">`——区块 header 复用 `<span class="h-4 w-1 rounded-full bg-primary"/> + <h3>` 范式；加载 `Skeleton` 骨架；空态 `CompactEmptyState`（icon `lucide--package` + 指向作战室外部依赖维护入口）；类型计数磁贴（复用核心指标磁贴圆角/渐变/ring 令牌，点击跳搜索预筛）；区块内 `Input` 即时搜索 + 条目列表（载体图标 + 标题 + 类型徽标 + 项目名，点击按载体跳转/打开）；`truncated` 提示。
- i18n：`zh-CN.json` 新增 `knowledge.overview.deps.{title,hint,searchPlaceholder,noMatch,truncated,empty.title,empty.body}`（仅新增，默认中文）。

## Verification Results
- `pnpm exec vue-tsc --noEmit` → **通过（exit 0）**
- `pnpm exec eslint src/components/knowledge/KnowledgeDashboard.vue src/api/knowledge.ts` → 通过（无残留）
- JSON 合法性校验通过。
- 手工核对：`/knowledge?tab=overview` 出现「交付文档/外部依赖」区块（计数磁贴 + 即时搜索 + 条目列表）；无交付文档账户显示优雅空态（非空网格）；加载显示骨架。

## Deviations from Plan
- 类型入口预筛参数取 `?tab=search&dep_type=<type_key>`（planner 授权执行者自定并注明）——搜索侧可后续消费该 query 预填类型筛选（本阶段前端仅负责跳转预填，搜索侧筛选实现可留后续）。

## Known Stubs
None —— 区块数据来自真实聚合接口；`dep_type` 预筛参数已随跳转传递，搜索页消费为后续增强（不影响本区块计数/入口/即时搜索的完整可用）。

## Self-Check: PASSED
- `web/src/api/knowledge.ts` 含 `getArtifactOverview`（FOUND）
- `web/src/components/knowledge/KnowledgeDashboard.vue` 含 `getArtifactOverview` + 区块（FOUND）
- `web/src/locales/zh-CN.json` 含 `overview.deps.*`（FOUND）
- vue-tsc 通过（FOUND）
