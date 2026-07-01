---
phase: 99-association-visualization-crosslink
plan: 04
subsystem: web/warroom + web/knowledge
tags: [KDEP-10, KDEP-12, galaxy-render, cross-entry, read-only]
requires: [99-01 galaxy artifact/capability payload, 99-02 ArtifactSerializer.entity_id]
provides:
  - "星图 artifact/capability 节点语义色 + 图例 + i18n"
  - "作战室外部依赖区工件行『知识』跨入口（→ /knowledge/entities/{entity_id}）"
affects: [里程碑 v0.16.3 收官闭环]
tech-stack:
  patterns: [TYPE_COLOR/TYPE_LABEL 映射扩展, RouterLink 次级操作, 复用已 safelist lucide 图标]
key-files:
  modified:
    - web/src/api/projectGalaxy.ts
    - web/src/components/project/warroom/ProjectGalaxyCard.vue
    - web/src/api/artifacts.ts
    - web/src/components/project/workbench/DependenciesSection.vue
    - web/src/locales/zh-CN.json
decisions:
  - "artifact=amber #f59e0b、capability=rose #ec4899 语义色（遵循 99-CONTEXT Claude 裁量）"
  - "跨入口用 RouterLink 仅图标 icon-[lucide--brain]（已 safelist）+ tooltip，低调不喧宾夺主"
metrics:
  duration_min: 15
  completed: 2026-07-01
---

# Phase 99 Plan 04: 星图渲染 + 作战室跨入口 Summary

收官前端：把 99-01 galaxy payload 的 `artifact`/`capability` 新节点渲染出来（语义色 + 图例 + 兜底列表 + 节点详情自动纳入），并在作战室「外部依赖」区为每个工件加一个跳知识实体的低调次级入口（消费 99-02 `entity_id`），闭合「作战室 ↔ 知识」双向环。

## Tasks

1. **星图渲染**：`projectGalaxy.ts` `ProjectGalaxyNodeType` 扩 `'artifact' | 'capability'`；`ProjectGalaxyCard.vue` `TYPE_COLOR` 增 artifact(amber)/capability(rose)、`TYPE_LABEL` 增映射（`legend`/兜底列表/节点详情遍历 TYPE_COLOR keys 自动纳入，nodeColor `?? '#94a3b8'` 兜底保持）；i18n `projects.warroom.galaxy.type.artifact`「工件」/`.capability`「能力」。
2. **作战室跨入口**：`artifacts.ts` `Artifact` 增 `entity_id: string`；`DependenciesSection.vue` 工件行操作区新增 `RouterLink :to="/knowledge/entities/{entity_id}"`（`v-if="a.entity_id"`，`icon-[lucide--brain]` + tooltip，`data-testid="deps-view-knowledge-btn"`），样式对齐既有次级按钮；i18n `projects.workbench.deps.viewKnowledge`「知识实体」。

## Deviations from Plan

- **[Rule 1 - 样式修复] artifacts.ts 预存 operator-linebreak lint**：eslint 报 `ArtifactCarrier` 联合类型 `=` 位置（pre-existing）。因该文件在本 plan 修改范围且验证要求 eslint 干净，`--fix` 归一为 `=` 行首风格（与 `projectGalaxy.ts` 一致），零语义变更。

## Verification

- `cd web && pnpm exec vue-tsc --noEmit` → 通过（零错误）
- `cd web && pnpm exec eslint <4 文件 + zh-CN.json>` → 无错误
- `pnpm exec vitest run DependenciesSection.spec.ts` → 4 passed（零回归）
- 人工 UAT 延后：星图见工件/能力彩色节点 + 图例；作战室工件行点『知识』跳该工件知识实体。

## Self-Check: PASSED
- web/src/api/projectGalaxy.ts — FOUND（node type 已扩）
- web/src/components/project/warroom/ProjectGalaxyCard.vue — FOUND（语义色/label 已补）
- web/src/api/artifacts.ts — FOUND（entity_id 已加）
- web/src/components/project/workbench/DependenciesSection.vue — FOUND（知识入口已加）
- web/src/locales/zh-CN.json — FOUND（galaxy type + viewKnowledge 文案已加）
