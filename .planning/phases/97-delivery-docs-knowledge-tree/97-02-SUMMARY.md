---
phase: 97-delivery-docs-knowledge-tree
plan: 02
subsystem: knowledge-frontend
tags: [vue, tree-view, url-sync, i18n]
requires: ["GET /api/knowledge/artifacts/tree/", 97-01]
provides: [DeliveryDocsTree.vue, fetchArtifactTree, ArtifactTree-types, tree-view-switch]
affects: [web/src/pages/knowledge/index.vue]
tech-stack:
  added: []
  patterns: [vue-query-single-load, segmented-control, url-query-sync, literal-icon-map]
key-files:
  created:
    - web/src/components/knowledge/DeliveryDocsTree.vue
  modified:
    - web/src/api/knowledge.ts
    - web/src/pages/knowledge/index.vue
    - web/src/locales/zh-CN.json
decisions:
  - "交付文档树为并行视图，不塞进 PageIndex 能力树；KnowledgeTreePanel.vue 零改动"
  - "固定三层嵌套 v-for（非递归组件）+ 默认全展开（数据规模小，直接可见更好用）"
  - "载体图标用字面量完整 class 映射，Tailwind 源扫描命中，无需改 safelist"
metrics:
  duration: ~20min
  completed: 2026-07-01
---

# Phase 97 Plan 02: 交付文档并行树视图 Summary

`/knowledge` tree Tab 新增「代码能力树｜交付文档」视图切换（默认代码能力树、`?view=` URL 同步），交付文档视图渲染并行三级树（项目→类型→工件，计数 + 类型徽标 + 载体图标 + 更新时间），PageIndex 能力树零改动。

## What was built

- **`knowledge.ts`**：新增 `ArtifactTreeLeaf/ArtifactTreeTypeGroup/ArtifactTreeProject/ArtifactTree` 类型（对齐 97-01 契约，`ArtifactCarrier` 复用 `~/api/artifacts`）+ `fetchArtifactTree()`（`GET /knowledge/artifacts/tree/`，无参），挂到 `knowledgeApi`。
- **`DeliveryDocsTree.vue`**（新组件，`data-testid="artifact-tree"`）：`useQuery(['knowledge','artifact-tree'], staleTime 60s)` 一次加载整棵树；固定三层嵌套 `v-for` 渲染；项目/类型节点可展开（默认全展开——数据到达时用全部 key 初始化 `expandedProjects`/`expandedTypes` 两个 Set，用户可折叠/展开）；项目节点 folder 图标 + 计数徽标、类型节点复用 `ARTIFACT_BADGE_CLASS` 徽标 + 计数、叶子 `CARRIER_ICON` 字面量图标 + 标题 + 更新时间（`toLocaleDateString`）；加载态 loader-2、整树空态 `CompactEmptyState`（folder-tree，指向作战室外部依赖）、`truncated` 顶部 info 提示条；query 错误经 `useErrorHandler`。
- **`index.vue`**：`type TreeView = 'capability' | 'docs'` + `normalizeTreeView`（白名单归一，非法回退 capability）+ `treeView` ref 与 `route.query.view` 双向同步（保留既有 `?tab=` 不丢）；tree TabsContent 顶部 segmented control（复用工具栏令牌），`v-if treeView==='capability'` 渲染 `KnowledgeTreePanel`（默认，本体零改动）否则 `DeliveryDocsTree`。
- **`zh-CN.json`**：`knowledge.tree.viewSwitch.{capability,docs}` + `knowledge.tree.docs.{loading,loadFailed,truncated,empty.{title,body}}`。

## Verification

- `cd web && pnpm exec vue-tsc --noEmit` → **无类型错误**
- `pnpm exec eslint`（3 改动文件）→ **通过**（修复 1 处 import 排序）
- `KnowledgeTreePanel.vue` 未在改动列表 → 能力树数据/组件未被触碰

## Deviations from Plan

**1. [Rule 3 - Blocking] import 排序 lint**
- **Found during:** Task 3 verify
- **Issue:** `DeliveryDocsTree` import 插入位置触发 `perfectionist/sort-imports`。
- **Fix:** `eslint --fix` 归位（DeliveryDocsTree 移到 EntityDetailToolbar 之前）。

**2. [Rule 2 - Missing] 补 loading/loadFailed 文案键**
- **Found during:** Task 2
- **Issue:** 计划 zh-CN 块只列 truncated/empty，但组件需加载态与错误提示文案。
- **Fix:** 在 `knowledge.tree.docs` 补 `loading`/`loadFailed`（与 97-03 的 searchPlaceholder/noMatch 不冲突）。

## Self-Check: PASSED
- FOUND: web/src/components/knowledge/DeliveryDocsTree.vue
- FOUND: web/src/api/knowledge.ts (fetchArtifactTree)
- FOUND: web/src/pages/knowledge/index.vue (DeliveryDocsTree + treeView)
- FOUND: web/src/locales/zh-CN.json (knowledge.tree.*)
