---
phase: 99-association-visualization-crosslink
plan: 03
subsystem: web/knowledge
tags: [KDEP-11, frontend, associations, bidirectional-nav, read-only]
requires: [99-02 反查端点 + entity_id, 98-03 正向端点, Phase 96 徽标, Phase 97 载体图标]
provides:
  - "knowledge.ts getArtifactAssociations / getRepositoryArtifacts + 类型"
  - "EntityAssociationsCard.vue（正向工件 + 反向仓库，双向可导航）"
  - "实体详情页条件挂载关联区块 + 锚点"
affects: [用户可见的关联知识图谱出口]
tech-stack:
  patterns: [useQuery enabled 条件查询, CompactEmptyState 优雅空态, RouterLink 双向导航]
key-files:
  created:
    - web/src/components/knowledge/EntityAssociationsCard.vue
  modified:
    - web/src/api/knowledge.ts
    - web/src/pages/knowledge/entities/[id].vue
    - web/src/locales/zh-CN.json
decisions:
  - "正向/反向用两个 useQuery，分别以 isForward/isReverse enabled 门控，避免无关请求"
  - "反查响应无 carrier，反向文档图标用 type_key 走 CARRIER_ICON 兜底（icon-[lucide--file]）"
  - "无关联走 CompactEmptyState 简洁空态，不渲染空块"
metrics:
  duration_min: 18
  completed: 2026-07-01
---

# Phase 99 Plan 03: 实体详情关联卡 Summary

让 Phase 98 关联「看得见、点得动」：新增 `EntityAssociationsCard.vue`，工件实体正向展示关联仓库/能力/关键词，仓库实体反向展示相关交付文档并可点回该文档知识实体，形成双向可导航闭环；徽标复用 Phase 96、载体图标复用 Phase 97；无关联走优雅空态。

## Tasks

1. **knowledge.ts**：新增类型 `ArtifactAssociationRepo`/`ArtifactAssociations`/`RepositoryArtifact`/`RepositoryArtifacts`；函数 `getArtifactAssociations`（正向）/`getRepositoryArtifacts`（反向，消费 99-02），加入 `knowledgeApi` barrel。字段严格对齐后端。
2. **EntityAssociationsCard.vue**：props `{sourceKind, sourceId, kind}`；`isForward`（sourceKind==='artifact'）→ 三小节仓库/能力/关键词（仓库 RouterLink → `/repositories/{id}`，能力/关键词 Badge）；`isReverse`（kind==='repository'）→ 相关文档列表（RouterLink → `/knowledge/entities/{entity_id}`，Phase 96 徽标 + Phase 97 载体图标兜底 + project_name）；loading→Skeleton、error→一行提示、empty→CompactEmptyState 不渲染空块。i18n `knowledge.entity.associations.*`。
3. **entities/[id].vue**：`showAssociations` 计算属性（工件或仓库实体）；条件追加 `entity-associations` section + 锚点；`entity-related` 后条件渲染 `<EntityAssociationsCard>`；非工件/仓库零回归。i18n `knowledge.entity.sections.associations`。

## Deviations from Plan

None - plan executed exactly as written.（反向文档徽标用 `type_key`，因反查响应无 `type_name` 字段——契约如此，非杜撰。）

## Verification

- `cd web && pnpm exec vue-tsc --noEmit` → 通过（零错误）
- `cd web && pnpm exec eslint <三文件>` → 无错误
- 人工 UAT 延后：工件实体见仓库/能力/关键词可点；仓库实体见相关文档可点回知识实体；无关联优雅空态。

## Self-Check: PASSED
- web/src/components/knowledge/EntityAssociationsCard.vue — FOUND
- web/src/api/knowledge.ts — FOUND（两函数 + 类型已导出）
- web/src/pages/knowledge/entities/[id].vue — FOUND（条件挂载）
- web/src/locales/zh-CN.json — FOUND（新键已加）
