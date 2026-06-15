---
phase: 32-one-click-ingest
plan: 03
subsystem: web
tags: [ingest, frontend, vue, tanstack-query, i18n, knowledge]
requires:
  - delivery REST：POST /delivery/ingest/（202 + run_id）、GET /delivery/ingest/{run_id}/（32-02）
  - web/src/api/client.ts（get/post + cookie-JWT 刷新）
  - web/src/components/ui/{input,button,label}（既有 shadcn-vue 封装）
  - web/src/components/common/CompactEmptyState.vue
  - web/src/components/layout/PageContainer.vue
  - web/src/composables/{useToast,useErrorHandler}
provides:
  - web/src/api/ingest.ts（ingestApi.dispatch / getRun + 5 类型）
  - web/src/components/knowledge/IngestPanel.vue（表单 + 派发→2s 轮询 + 三步结果）
  - web/src/pages/knowledge/ingest.vue（/knowledge/ingest 薄壳页）
  - AppSidebar「一键摄取」导航入口
  - zh-CN.json `ingest` 命名空间
affects: []
tech-stack:
  added: []
  patterns:
    - 派发→轮询（useMutation dispatch + useQuery 条件 refetchInterval，沿用 ReconcilePanel）
    - 输入值与提交分离 + 内联 http(s) 校验（不发非法请求）
    - 固定三步结果渲染（始终三行，无值步 pending）+ 状态语义色 + 文字（WCAG 1.4.1）
    - 守护测试以真实 zh-CN.json 锁关键文案（防 copy 被改空）
    - 仅复用既有 ~/components/ui/* 与设计令牌（无新增 registry/字体/颜色变量）
key-files:
  created:
    - web/src/api/ingest.ts
    - web/src/components/knowledge/IngestPanel.vue
    - web/src/pages/knowledge/ingest.vue
    - web/src/components/knowledge/__tests__/IngestPanel.spec.ts
  modified:
    - web/src/api/index.ts
    - web/src/locales/zh-CN.json
    - web/src/components/layout/AppSidebar.vue
decisions:
  - "URL 校验仅做 http(s) 前缀字符串校验，真实解析交后端（前端不直连飞书/git，T-32-05）"
  - "外链统一 target=_blank + rel=noopener，identifier/error 走模板插值默认转义，不用 v-html（T-32-05）"
  - "run.status==='failed' 与 partial 复用同一「部分步骤未完成」amber 提示文案（UI-SPEC 未单列 failed 顶部文案，避免新增未契约 copy）"
  - "顺手修正 api/index.ts 既有 perfectionist/sort-exports 报错（编辑该文件触发，--fix 排序）"
metrics:
  duration: ~12m
  completed: 2026-06-15
---

# Phase 32 Plan 03: 一键摄取前端面板 Summary

实装 ING-01 的用户可见闭环——`/knowledge/ingest` 页 + `IngestPanel` 组件：输入看板 URL + MR URL → `POST /delivery/ingest/`（202 + run_id）→ TanStack Query 2s 轮询 `GET /delivery/ingest/{run_id}/` → 固定渲染三步（工作项 / PRD·技术方案文档 / MR diff）的 ok/failed/skipped/pending 语义色结果（identifier + 「查看」外链 + error）。沿用既有「派发→轮询」范式（参照 `ReconcilePanel`），i18n 默认中文，守护测试以真实 `zh-CN.json` 锁关键文案。纯复用既有 UI 组件 / 设计令牌，无新增设计资产。

## What Was Built

### Task 1 — ingest API client + barrel + i18n（commit `d2b6809a` feat）
- `web/src/api/ingest.ts`：从 `./client` import `get/post`，定义并导出 `StepStatus`/`RunStatus`/`IngestStep`/`IngestRun`/`IngestDispatch` 五类型 + `ingestApi`（`dispatch(boardUrl, mrUrl)` → `post('/delivery/ingest/', { board_url, mr_url })`；`getRun(runId)` → `get('/delivery/ingest/${runId}/')`）。字段名严格对齐 32-02 后端 `IngestRunSerializer`（`run_id`/`status`/`steps.{work_item,document,mr_diff}`/`started_at`/`completed_at`）。
- `web/src/api/index.ts`：追加 `export * from './ingest'`。
- `web/src/locales/zh-CN.json`：顶层新增 `ingest` 命名空间，逐字落 UI-SPEC「i18n Keys」全部 key（title/subtitle/form.*/empty.*/dispatch.*/run.*/steps.*/status.*）。

### Task 2 — IngestPanel + 页薄壳 + 侧边栏（commit `b0b2df28` feat）
- `web/src/components/knowledge/IngestPanel.vue`（`<script setup lang="ts">`）：
  - 表单态 `boardUrl`/`mrUrl` + 内联校验（空 → `errorRequired`；非 http(s) → `errorInvalidUrl`），失败聚焦首个错误字段且不派发；字段含 `<Label :for>` + `data-testid`，CTA `data-testid="ingest-submit"` 带 `:disabled`/spinner/文案切换。
  - 派发用 `useMutation(ingestApi.dispatch)`，成功取 `run_id` 存 `runId` + `useToast` 成功提示 + 开启轮询；失败 `useErrorHandler`。
  - 轮询用 `useQuery(getRun)`，`enabled = !!runId`，`refetchInterval: q => q.state.data?.status === 'running' ? 2000 : false`（completed/failed 停轮）。
  - 结果区 `aria-live="polite"`：getRun 失败 → `loadError` 行（不清空）；无 run → `CompactEmptyState`；有 run → 顶部状态行（running spinner / 全 ok 绿「完成可检索」/ partial·failed amber「部分未完成」）+ 固定三行 StepRow（语义色图标 + 状态文字 + identifier code + 「查看」外链 rel=noopener + error）。
- `web/src/pages/knowledge/ingest.vue`：`PageContainer` → `space-y-4 max-w-3xl` → 标题 → `<IngestPanel />`。
- `web/src/components/layout/AppSidebar.vue`：`mainNavItems` 追加 `{ to: '/knowledge/ingest', label: '一键摄取', icon: 'lucide--download' }`（紧邻「交付知识」）。

### Task 3 — IngestPanel 守护测试（commit `e5db8cbc` test）
- `web/src/components/knowledge/__tests__/IngestPanel.spec.ts`（vitest + @vue/test-utils + happy-dom）：真实 `zh-CN.json` 注入 i18n + mock `ingestApi` + 装配 vue-query。5 例：
  - (a) 真实 messages 锁定标题/CTA/三步骤名/四状态文案（被改空即红）+ 渲染层标题/CTA/空态文案。
  - (b) 空提交 → 内联 `errorRequired`，未调 `dispatch`。
  - (c) 合法提交 → `dispatch(board, mr)`，run_id 后轮询 `getRun` 三步 ok → 完成提示 + 三步名 + 成功。
  - (d) completed + failed/skipped 步 → partial 提示 + 失败/已跳过 + 各步 error。
  - (e) getRun 报错 → loadError 行。

## Verification Results

- `pnpm vue-tsc --noEmit -p tsconfig.json` → 通过（含 i18n messages 类型门禁，exit 0）。
- `pnpm vitest run src/components/knowledge/__tests__/IngestPanel.spec.ts` → **5 passed**。
- `pnpm eslint`（仅改动文件：api/ingest.ts / IngestPanel.vue / ingest.vue / AppSidebar.vue / api/index.ts / IngestPanel.spec.ts）→ All checks passed（无新增错误）。
- 人工确认：仅复用既有 `~/components/ui/*`、`.card`、`CompactEmptyState`、`PageContainer` 与状态语义色，无新增字体/颜色变量/第三方 registry（UI-SPEC AC 第 10 条）。

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] 修正 `web/src/api/index.ts` 既有 perfectionist/sort-exports 报错**
- **Found during:** Task 2（编辑 index.ts 追加 ingest 导出后 `pnpm eslint` 报既有 `./dashboard` 应在 `./gitInstanceCredentials` 之前）。
- **Issue:** 该排序错误是文件既有问题，但因本次编辑触及该文件而被 lint 暴露，会使「改动文件无新增错误」门禁失败。
- **Fix:** `pnpm eslint --fix src/api/index.ts` 让导出按字母序重排（ingest 落在 dashboard 与 knowledge 之间）。
- **Files modified:** `web/src/api/index.ts`。
- **Commit:** `b0b2df28`。

### Discretionary copy decision

- UI-SPEC 未为 `run.status==='failed'`（编排级失败）单列顶部文案；为避免新增未在契约内的 copy，failed 顶部复用 `ingest.run.partial`「部分步骤未完成…」amber 提示（各步骤详情仍如实展示 failed + error）。

## Threat Model Compliance

- **T-32-05（Tampering/XSS）**：StepRow `identifier`/`error` 走 Vue 模板插值默认转义；外链 `<a>` 仅以 `link` 作 href 且 `target="_blank" rel="noopener"`，全程不使用 `v-html`。
- **T-32-06（信息泄露）**：后端已脱敏文本（32-02 T-32-02）前端如实回显，不额外存储。
- 无新增 npm 依赖（全部 `catalog:` 既有）/ 无第三方 registry / 无新字体或颜色变量（UI-SPEC Registry Safety 不适用）。

## Self-Check: PASSED

- FOUND: web/src/api/ingest.ts
- FOUND: web/src/components/knowledge/IngestPanel.vue
- FOUND: web/src/pages/knowledge/ingest.vue
- FOUND: web/src/components/knowledge/__tests__/IngestPanel.spec.ts
- FOUND commit: d2b6809a（feat Task 1）
- FOUND commit: b0b2df28（feat Task 2）
- FOUND commit: e5db8cbc（test Task 3）
