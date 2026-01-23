# Change: Add Dynamic Workflow Engine
## Why
当前 Friday 的任务流水线是固定的线性流程（Pending → Planning → Plan Review → Executing → Code Review → Merged），无法灵活组合不同的自动化步骤。用户需要一个类似 n8n 的可视化工作流系统，能够自由编排多种节点（创建分支、需求分析、Bug 分析、方案修改、代码实现、MCP 部署等），实现真正的流程自动化。
## What Changes
### 后端新增
- **BREAKING**: 新增 `workflows` Django App，包含完整的工作流数据模型
- 新增 DAG 执行引擎，支持节点并行/串行执行
- 新增可扩展的节点类型注册系统
- 新增 WebSocket 支持（Django Channels）用于实时状态推送
- 新增工作流相关 API 端点
### 前端新增
- 新增工作流可视化编辑器（基于 Vue Flow）
- 新增工作流列表和执行监控页面
- 新增节点拖拽、连接、配置交互
### 与现有系统集成
- 保留现有 Task 模型作为"简单任务"模式
- 复用现有 `TaskScheduler` 的 Docker 执行能力
- 将现有固定流程转换为默认工作流模板
## Impact
- Affected specs: `ai-dev-automation`（扩展执行模式）
- Affected code:
 - `server/workflows/` - 新增 Django App
 - `server/services/scheduler.py` - 扩展支持节点执行
 - `web/src/pages/workflows/` - 新增页面
 - `web/src/components/workflow/` - 新增组件
- New dependencies:
 - 后端: `channels`, `channels-redis`
 - 前端: `@vue-flow/core`, `@vue-flow/background`, `@vue-flow/controls`
