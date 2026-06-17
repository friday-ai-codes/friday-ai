---
phase: 55-query-ui
plan: 03
subsystem: frontend
tags: [audit, vue, admin, i18n, export, readonly]
requirements-completed: [AUDITUI-02]
key-files:
  created:
    - web/src/api/audit.ts
    - web/src/pages/admin/audit/index.vue
    - web/src/pages/admin/__tests__/audit.spec.ts
  modified:
    - web/src/locales/zh-CN.json
    - web/src/components/layout/AppSidebar.vue
key-decisions:
  - "导出走 fetch blob + a[download]（cookie-JWT 自动携带），错误体含后端 detail（max_rows 超限提示）"
  - "过滤点「查询」才刷新 appliedQuery（避免边输入边请求）；keepPreviousData 平滑翻页"
  - "只读页：无任何编辑/删除入口（呼应 append-only）"
completed: 2026-06-17
---

# Phase 55 Plan 03 — 前端审计视图 Summary

**`/admin/audit` superuser 审计页：过滤 + 表格 + 分页 + before/after 详情弹窗 + CSV/JSON 导出 + 侧栏入口 + i18n。**

## Accomplishments
- `api/audit.ts`：`auditApi.list/detail/exportFile`，类型与后端序列化器对齐；导出 fetch blob 下载。
- `pages/admin/audit/index.vue`：`definePage({ meta: { requiresAdmin: true } })`；动作/来源下拉 + actor/target/时间/q 过滤、查询/重置、表格、分页(每页 20/50/100 + 上下页 + 区间计数)、行点击详情弹窗(before/after 并排 + metadata)、CSV/JSON 导出按钮。复用 vue-query/useToast/useErrorHandler/PageContainer/ui 组件。
- `zh-CN.json` 增 `audit.*` 命名空间；`AppSidebar` admin 区增「操作审计」(lucide--shield-check)。
- `audit.spec.ts`：列表渲染 / 查询带参 / 导出调用 / 只读无删除 4 例全绿。

## Acceptance
- `pnpm vitest run audit.spec.ts` 4 passed；`eslint` clean；`vue-tsc --noEmit` exit 0（无 audit 相关类型错误）。
