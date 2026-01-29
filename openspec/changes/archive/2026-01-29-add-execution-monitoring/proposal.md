# Change: 添加工作流执行监控系统
## Why
当前工作流列表页只展示模板配置，用户无法查看正在运行或已完成的工作流执行记录。顶部导航的"任务"功能基于已废弃的 `tasks` 系统（sunset date: 2025-06-01），需要替换为基于新 `workflows` 系统的执行监控功能。
## What Changes
- **新增** `/executions` 全局执行监控页面，替代废弃的 `/tasks`
- **新增** `/executions/[id]` 执行详情页（迁移自 `/workflows/executions/[id]`）
- **新增** 执行状态徽章组件 `ExecutionStatusBadge`
- **修改** 导航栏：将"任务"替换为"执行"
- **增强** `useExecutionsStore`：添加统计计算和自动刷新功能
- **增强** 工作流卡片：显示最近执行状态和执行次数
## Impact
- Affected specs: `frontend-architecture`
- Affected code:
 - **后端**: `server/workflows/api/serializers.py` (为列表添加 `last_execution` 字段)
 - **前端**: `web/src/pages/executions/` (新建)
 - **前端**: `web/src/components/execution/` (新建)
 - **前端**: `web/src/layouts/default.vue` (导航栏修改)
 - **前端**: `web/src/stores/useExecutionsStore.ts` (增强)
 - **前端**: `web/src/pages/workflows/index.vue` (卡片增强)
