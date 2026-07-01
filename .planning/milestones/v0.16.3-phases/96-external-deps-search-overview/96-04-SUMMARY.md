---
phase: 96-external-deps-search-overview
plan: 04
subsystem: web-knowledge
tags: [web, knowledge, search, artifact, badge, i18n, KDEP-02]
requires: [96-02]
provides:
  - KnowledgeSearchResultItem 扩展 origin/source_kind/artifact
  - 搜索结果工件类型徽标 + 所属项目名 + 一键查看
affects:
  - web/src/api/knowledge.ts
  - web/src/pages/knowledge/index.vue
  - web/src/locales/zh-CN.json
tech-stack:
  added: []
  patterns: [reuse-artifact-view-dialog, reka-ui-badge, rel-noopener-external]
key-files:
  created: []
  modified:
    - web/src/api/knowledge.ts
    - web/src/pages/knowledge/index.vue
    - web/src/locales/zh-CN.json
decisions:
  - 工件类型徽标复用 reka-ui Badge variant=outline + amber 令牌，与 EntityKindBadge 视觉一致
  - external_link → 新标签打开（rel=noopener noreferrer）；其余文字载体 → 复用 ArtifactView 查看弹窗
  - 复用既有 i18n（projects.artifacts.viewDesc/recordCount/unsupported）+ 新增 knowledge.search.{owningProject,view,openExternal}
metrics:
  duration: ~25min
  completed: 2026-07-01
---

# Phase 96 Plan 04: 搜索结果工件徽标 + 一键查看 Summary

消费 96-02 后端补的 `origin/source_kind/artifact` 字段：`/knowledge` 搜索结果命中工件时加工件类型徽标 + 所属项目名，并提供一键查看（文字载体走 markdown 弹窗复用 `ArtifactView`，external_link 新标签打开），闭合「搜到 → 看懂 → 打开」。

## What Changed

### Task 1 — knowledge.ts 类型扩展
- 新增 `KnowledgeSearchArtifactMeta`（type_key/type_name/carrier/url/artifact_id/project_id/project_name，对齐 96-02 序列化）。
- `KnowledgeSearchResultItem` 追加可选 `origin?/source_kind?/artifact?`。`searchDeliveryKnowledge` 请求签名不变（后端已默认 include_document_kind）。

### Task 2 — index.vue 搜索结果增强 + i18n
- script：import `artifactsApi`、`MarkdownRenderer`、`Badge`、Dialog 系列、`useErrorHandler`；新增查看弹窗状态（viewOpen/viewLoading/viewData/viewTitle）+ `openArtifactView(item)`（调 `artifactsApi.view(project_id, artifact_id)`，fail-soft `handleError`）+ `isExternalArtifact` 判定。
- 结果卡片：`item.artifact` 存在时——`EntityKindBadge` 旁加工件类型徽标（amber 令牌）；score 行旁加所属项目名（`lucide--folder` muted 小字）；主操作按载体自适应（external_link → `<a target="_blank" rel="noopener noreferrer">` 打开外链；其余 → 「查看」按钮弹窗）。非工件项渲染不变。
- 查看弹窗：`Dialog + DialogScrollContent`，按 `ArtifactView.render_type`（markdown→MarkdownRenderer / text→pre / records→JSON / link→链接 / error→提示）渲染，复用 DependenciesSection 范式。
- i18n：`zh-CN.json` 新增 `knowledge.search.{owningProject,view,openExternal}`（仅新增，默认中文）。

## Verification Results
- `pnpm exec vue-tsc --noEmit` → **通过（exit 0，无错误）**
- `pnpm exec eslint src/pages/knowledge/index.vue src/api/knowledge.ts` → 通过（auto-fix import 排序 + 注释空格后无残留）
- 手工核对：工件命中项展示类型徽标 + 项目名；文字载体点「查看」弹 markdown、external_link 新标签打开；非工件项无回归。

## Deviations from Plan
None —— 计划按原样执行（徽标配色令牌按「优雅、好用」选 amber outline，与 EntityKindBadge 一致）。

## Known Stubs
None。

## Self-Check: PASSED
- `web/src/api/knowledge.ts` 含 artifact 字段（FOUND）
- `web/src/pages/knowledge/index.vue` 含 artifactsApi + 徽标 + 查看弹窗（FOUND）
- `web/src/locales/zh-CN.json` 新增文案键（FOUND）
- vue-tsc 通过（FOUND）
