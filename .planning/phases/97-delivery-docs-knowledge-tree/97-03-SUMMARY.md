---
phase: 97-delivery-docs-knowledge-tree
plan: 03
subsystem: knowledge-frontend
tags: [vue, in-view-search, highlight, artifact-view, xss-safe]
requires: [97-02, DeliveryDocsTree.vue, artifactsApi.view, MarkdownRenderer]
provides: [tree-in-view-search, leaf-view-dialog, external-link-open]
affects: []
tech-stack:
  added: []
  patterns: [client-side-filter, segmented-highlight-no-vhtml, reuse-phase96-view-dialog]
key-files:
  created: []
  modified:
    - web/src/components/knowledge/DeliveryDocsTree.vue
    - web/src/locales/zh-CN.json
decisions:
  - "一次加载 + 纯客户端搜索/展开（数据规模小，避免懒加载复杂度——简单即优雅）"
  - "命中高亮用 <template v-for> + <mark> 分段渲染纯文本，禁用 v-html（防 XSS）"
  - "叶子查看复用 Phase 96 openArtifactView 范式 + 弹窗模板，跨视图观感统一"
metrics:
  duration: ~15min
  completed: 2026-07-01
---

# Phase 97 Plan 03: 树内搜索与叶子查看 Summary

交付文档树补齐树内即时搜索（客户端过滤 + 命中高亮 + 自动展开命中路径 + 无匹配空态）与叶子点击查看（external_link 新标签、文字载体 markdown 弹窗，复用 Phase 96 `artifactsApi.view` + `MarkdownRenderer`），KDEP-04/05/06 闭环。

## What was built

- **树内搜索**（`DeliveryDocsTree.vue`）：顶部搜索框（`searchQuery` ref，`icon-[lucide--search]` 前置，样式复用 KnowledgeTreePanel 令牌）；`filteredProjects` computed 纯客户端过滤（`title.toLowerCase().includes(q)`，仅保留有命中叶子的 type / 有命中 type 的 project，空分组不渲染）；搜索非空时 `isProjectOpen`/`isTypeOpen` 返回 `true`（命中路径祖先自动全展开，清空恢复手动展开态）。
- **命中高亮**：`highlightTitle()` 大小写不敏感切片成 `{text,hit}[]` 分段，用 `<template v-for>` + `<mark class="bg-amber-500/20 ...">` 渲染纯文本（**禁用 v-html**，防 XSS）。
- **空态双分支**：整树空（total===0）走 97-02 引导空态；搜索无命中（`isSearchEmpty`）走 `CompactEmptyState`（file-x，noMatch 文案）。
- **叶子查看**：`external_link` 载体渲染为 `<a target="_blank" rel="noopener noreferrer">`（防 tabnabbing）新标签打开；文字载体渲染为按钮 → `openLeafView(project.project_id, leaf)` 调 `artifactsApi.view` → `Dialog`+`DialogScrollContent` 按 `render_type` 分支（markdown→`MarkdownRenderer` 自带消毒 / text→`<pre>` / link→外链 / records→JSON / 兜底 unsupported），失败走 `useErrorHandler`。
- **i18n**：`knowledge.tree.docs` 补 `searchPlaceholder` + `noMatch.{title,body}`；查看弹窗复用既有 `knowledge.search.{view,openExternal,loading}` 与 `projects.artifacts.{viewDesc,viewFailed,recordCount,unsupported}`（不重复造键）。

## Verification

- `cd web && pnpm exec vue-tsc --noEmit` → **无类型错误**（修复 1 处未用 Button import）
- `pnpm exec eslint DeliveryDocsTree.vue` → **通过**
- `node -e JSON.parse zh-CN.json` → **valid**

## Deviations from Plan

**1. [Rule 1 - Bug] 移除未用 Button import**
- **Found during:** Task 2 verify
- **Issue:** 采用「整行叶子可点击」而非独立查看按钮，`Button` import 未使用触发 TS6133。
- **Fix:** 删除 `Button` import；叶子查看行为不变（文字载体整行按钮、外链整行锚点）。

**2. [Rule 3 - Scope] noMatch 图标用 file-x（已 safelist）**
- **Found during:** Task 1
- **Issue:** 计划首选 `search-x` 未在 safelist；`CompactEmptyState` 动态拼 `icon-[${icon}]` 需 safelist 命中。
- **Fix:** 按计划 fallback 用已 safelist 的 `lucide--file-x`，避免额外改 main.css（超出本 plan files_modified 范围）。

## Self-Check: PASSED
- FOUND: web/src/components/knowledge/DeliveryDocsTree.vue (artifactsApi + filteredProjects + highlightTitle)
- FOUND: web/src/locales/zh-CN.json (searchPlaceholder + noMatch)
