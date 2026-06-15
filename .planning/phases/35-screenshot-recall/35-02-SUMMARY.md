---
phase: 35-screenshot-recall
plan: 02
subsystem: frontend
tags: [vision, screenshot-recall, upload, vue3, i18n, vitest, delivery-knowledge]
requires:
  - "REST: POST /delivery/screenshot-recall/"
  - api.client.post
  - components.knowledge.IngestPanel
  - components.common.CompactEmptyState
provides:
  - api.screenshotRecall.screenshotRecallApi
  - components.knowledge.ScreenshotRecallPanel
  - "route: /knowledge/screenshot"
affects:
  - web/src/api/index.ts
  - web/src/locales/zh-CN.json
  - web/src/components/layout/AppSidebar.vue
tech-stack:
  added: []
  patterns:
    - "三入口上传（点击/拖拽/粘贴）汇入单一 handleFile（校验→预览）"
    - "同步 useMutation 提交 multipart，结果区 6 态状态机（degraded 独立于 error）"
    - "objectURL 预览 + 替换/卸载 revokeObjectURL（防内存泄漏）"
    - "vitest 注入真实 zh-CN.json 锁文案 + mock api 守护分支"
key-files:
  created:
    - web/src/api/screenshotRecall.ts
    - web/src/pages/knowledge/screenshot.vue
    - web/src/components/knowledge/ScreenshotRecallPanel.vue
    - web/src/components/knowledge/__tests__/ScreenshotRecallPanel.spec.ts
  modified:
    - web/src/api/index.ts
    - web/src/locales/zh-CN.json
    - web/src/components/layout/AppSidebar.vue
decisions:
  - "降级态用 <a href=\"/admin\"> 而非 RouterLink，避免测试需装配 vue-router；UI-SPEC 允许 RouterLink/a 二选一"
  - "result 仅在 onSuccess 写入，mutation rejected 不清空（保留上次成功/降级结果），符合 error 态契约"
  - "校验阈值前端常量（10MB / png|jpeg|webp）与后端 35-01 SCREENSHOT_RECALL_MIME_TYPES 语义对齐，前端为体验前置、后端权威"
metrics:
  duration: ~7m
  completed: 2026-06-15T15:50Z
  tasks: 3
  files: 7
---

# Phase 35 Plan 02: 截图识需求前端面板 Summary

按 35-UI-SPEC 实现「截图识需求」前端闭环：截图三入口上传（拖拽/点击/粘贴）+ 前端双校验 + objectURL 预览 → 同步 `useMutation` 提交 `POST /delivery/screenshot-recall/` multipart → 渲染 6 态状态机（empty/loading/error/degraded/success/no-results，degraded 以 amber 卡片 + 前往系统设置链接明确区分于 error）+ 语义卡（可折叠）+ 召回需求列表；复用 Phase 32 IngestPanel 既有组件/令牌/范式，零新依赖、零新字体/色。

## What Was Built

- **`web/src/api/screenshotRecall.ts`**：逐字落 35-UI-SPEC「API Contract」的 `ExtractedSemantics` / `RecalledRequirement` / `ScreenshotRecallResult` 接口与 `screenshotRecallApi.recall(file)`（构造 `FormData.append('screenshot', file)` → `post<ScreenshotRecallResult>('/delivery/screenshot-recall/', fd)`；client.ts 对 FormData 自动跳过 JSON 头）。barrel 导出补入 `web/src/api/index.ts`。
- **`web/src/locales/zh-CN.json`**：新增 `screenshotRecall` 顶层块（title/subtitle/upload.*/validation.*/empty.*/loading/error/degraded.*/noResults.*/semantics.*/results.*），与 UI-SPEC「i18n Keys」逐字一致，JSON 合法。
- **`web/src/components/layout/AppSidebar.vue`**：`mainNavItems` 紧随「一键摄取」追加 `{ to: '/knowledge/screenshot', label: '截图识需求', icon: 'lucide--scan-search' }`（沿用既有硬编码中文 label 范式）。
- **`web/src/pages/knowledge/screenshot.vue`**：镜像 `ingest.vue` 路由页骨架（PageContainer + `max-w-3xl` + h1 + `<ScreenshotRecallPanel />`），unplugin-vue-router 自动出 `/knowledge/screenshot`。
- **`web/src/components/knowledge/ScreenshotRecallPanel.vue`**：上传+提交+结果编排面板。
  - 三入口上传：dropzone（`role="button"` + `tabindex=0` + `aria-describedby` hint + Enter/Space 触发隐藏 `sr-only` file input）、`@dragover/@dragleave/@drop` 拖拽（高亮 `border-primary bg-primary/5`）、`onMounted/onBeforeUnmount` 成对的 window `paste` 监听，全部汇入 `handleFile`。
  - 前端双校验：MIME ∈ {png,jpeg,webp} 否则 `invalidType`，>10MB → `tooLarge`，提交无文件 → `required`；失败内联红字 + toast、不发请求、焦点回 dropzone。
  - 预览/移除：`URL.createObjectURL` 预览（`max-h-48 object-contain`），替换/卸载 `revokeObjectURL`；移除回 empty 态。
  - 6 态状态机：empty（CompactEmptyState `lucide--image`）/ loading（Skeleton + spinner + `aria-busy`）/ error（`text-destructive`，保留上次结果）/ degraded（amber `alert-triangle` 卡片 + 「前往系统设置」`/admin` 链接，不弹 error toast）/ success（可折叠语义卡 + 召回列表 `recall-item-{idx}`：title + work_item_id `font-mono` + relevance `text-emerald-600` + 外链 `rel=noopener`）/ no-results（CompactEmptyState `lucide--search-x`）。
- **`__tests__/ScreenshotRecallPanel.spec.ts`**：vitest + @vue/test-utils + happy-dom，注入真实 zh-CN.json + mock `screenshotRecallApi`/toast/errorHandler + VueQueryPlugin（retry:false）。

## Tasks Completed

| Task | Name | Commit | Files |
| ---- | ---- | ------ | ----- |
| 1 | API 模块 + i18n + 侧边栏 + 路由页 | 3198b721 | api/screenshotRecall.ts, api/index.ts, locales/zh-CN.json, layout/AppSidebar.vue, pages/knowledge/screenshot.vue |
| 2 | ScreenshotRecallPanel 上传 + 6 态状态机 + 结果渲染 | 13691f0d | components/knowledge/ScreenshotRecallPanel.vue |
| 3 | vitest 守护（真实 zh-CN.json + mock api） | 428aaadb | components/knowledge/__tests__/ScreenshotRecallPanel.spec.ts |

## Deviations from Plan

**1. [选型] 降级卡片「前往系统设置」用 `<a href="/admin">` 而非 `RouterLink`。**
- 原因：UI-SPEC 明确允许 `RouterLink/a` 二选一；用原生 `<a>` 使 vitest 无需装配 vue-router 即可挂载面板，降低测试耦合。
- 影响：无功能差异（导航至 `/admin`），SPA 内仍由路由接管（同源相对路径）。

其余按计划执行。

## Verification

- `pnpm exec vitest run src/components/knowledge/__tests__/ScreenshotRecallPanel.spec.ts`：**7 passed**（a 真实文案锁 / b 非图片拒绝不发请求 / c >10MB 拒绝 / d success 召回渲染 / e degraded amber 卡片且不弹 error toast / f no-results / g error + handleError）。
- `pnpm exec vue-tsc --noEmit -p tsconfig.json`：no TS errors（全量）。
- `pnpm exec eslint`（改动文件：panel / api / 路由页 / index / sidebar / spec）：全部通过。
- `node -e JSON.parse(zh-CN.json)`：valid。

## Threat Surface

- T-35F-01（DoS）：前端 ≤10MB + MIME 白名单，超限/非图片不发请求（后端 35-01 权威兜底）。✅
- T-35F-02（信息泄露）：召回外链 `a[target=_blank]` 强制 `rel="noopener"`。✅
- T-35F-03（objectURL 内存）：替换/卸载 `revokeObjectURL`。✅
- T-35F-04（degraded/error 文案）：仅渲染固定 i18n 文案，无前端敏感拼接。✅

无新增安全面（无新 endpoint / 无 npm 新依赖）。

## Self-Check: PASSED
- FOUND: web/src/api/screenshotRecall.ts
- FOUND: web/src/pages/knowledge/screenshot.vue
- FOUND: web/src/components/knowledge/ScreenshotRecallPanel.vue
- FOUND: web/src/components/knowledge/__tests__/ScreenshotRecallPanel.spec.ts
- FOUND commits: 3198b721, 13691f0d, 428aaadb
