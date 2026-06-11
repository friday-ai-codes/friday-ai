# Quick Task 260611-ghb: 统一工作流列表卡片高度并收纳节点标签

用户反馈：工作流列表卡片“忽高忽低”，主要由节点标签换行数量、描述缺失、内容区自然高度导致卡片高度不一致。

## Task 1: 锁定等高卡片结构

- 修改 `web/src/components/__tests__/workflow-data-table.test.ts`
- 新增断言：
  - 卡片体存在 `.workflow-card-shell`
  - 缩略图区、内容区、标签区、操作区分别存在固定骨架类
  - 多节点类型时最多渲染 4 个 `.workflow-node-chip`
  - 多余节点类型汇总为 `.workflow-node-overflow`，展示 `+N`

验收：先运行目标测试看到失败，再实现通过。

## Task 2: 重构工作流卡片布局

- 修改 `web/src/components/workflow/WorkflowDataTable.vue`
- 卡片 shell 设定统一 `h-[380px]` 并使用 `flex flex-col`
- mini map 区固定高度，内容区 `flex-1`，操作区 `mt-auto`
- 标题一行截断，描述最多两行并保留固定高度
- 节点 chip 区固定高度，只显示前 4 个类型，剩余用 `+N`

## 验证

- `pnpm vitest run src/components/__tests__/workflow-data-table.test.ts`
- `pnpm eslint src/components/workflow/WorkflowDataTable.vue src/components/__tests__/workflow-data-table.test.ts`
- `pnpm type-check`
