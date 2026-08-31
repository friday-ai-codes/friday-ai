---
audit_acknowledged:
  milestone: v0.25.0
  at: 2026-08-31
  status: unknown
---

# Quick Task 260611-ghb Summary: 统一工作流卡片高度

## 结果

- 将工作流卡片改为固定 `h-[380px]` 的纵向 flex 骨架，缩略图、正文、节点标签区、底部操作区高度稳定。
- 描述区改为两行保留空间，空描述不会再把卡片压矮。
- 节点类型标签最多显示 4 个，多余类型收纳为 `+N`，避免标签换行撑高卡片。
- loading skeleton 同步改为等高结构，加载中和加载后的版式不会跳变。

## 验证

- RED: `pnpm vitest run src/components/__tests__/workflow-data-table.test.ts`
  - 新增测试先失败，缺少 `.workflow-card-shell` 等等高骨架类。
- GREEN: `pnpm vitest run src/components/__tests__/workflow-data-table.test.ts`
  - 3 tests passed。
- `pnpm eslint src/components/workflow/WorkflowDataTable.vue src/components/__tests__/workflow-data-table.test.ts`
  - passed。
- `pnpm type-check`
  - passed。
- Browser: `http://127.0.0.1:10240/workflows`
  - 页面可加载，但未登录态重定向到 `/login?redirect=/workflows`；无前端 error/warn 日志。

## Commit

- `c7af69b6 fix(web): normalize workflow card heights`
