# Change: Add Workflow Event Trigger and Context Management System
## Why
当前工作流系统仅支持手动触发，无法与飞书项目管理系统自动联动。需要实现事件驱动的工作流触发机制，使工作项状态变更时能自动触发对应工作流，并通过上下文管理系统在节点间传递数据。
## What Changes
### Backend (Django)
- **ADDED** `WorkflowTrigger` 模型 - 存储触发器配置，支持事件类型过滤和 JSON Schema 校验
- **ADDED** `CodingTask` 模型 - 存储 AI 编码任务，关联工作流执行和仓库
- **MODIFIED** `WorkflowExecution` 模型 - 新增 `is_manual_trigger`, `trigger_log`, `global_params` 字段
- **ADDED** 4 个新节点类型:
 - `feishu_event_trigger` - 飞书事件触发器
 - `fetch_work_item` - 获取工作项详情
 - `ai_prompt` - AI Prompt 调用
 - `ai_coding_dispatcher` - AI 编码任务指派器
- **MODIFIED** `FeishuWorkflowBridge` - 扩展事件分发逻辑
- **MODIFIED** `ExecutionContext` - 扩展模板变量支持 `{{global.key}}` 和 `{{trigger.key}}`
- **ADDED** API 端点: 触发器管理、手动触发、上下文查询、编码任务管理
### Frontend (Vue 3)
- **ADDED** 4 个节点组件: `FeishuEventTriggerNode`, `FetchWorkItemNode`, `AIPromptNode`, `AICodingDispatcherNode`
- **ADDED** 4 个配置面板组件: 对应每个新节点的配置 UI
- **ADDED** `ContextInspector` - 上下文检查器，显示全局参数和节点输出
- **ADDED** `VariablePicker` - 变量选择器，支持插入模板变量
- **ADDED** `TriggerConfigPanel` + `TriggerEditDialog` - 触发器管理 UI
- **ADDED** `ManualTriggerDialog` - 手动触发对话框
- **ADDED** `CodingTaskList` + `CodingTaskDetail` - 编码任务展示
- **MODIFIED** `NodePalette` - 添加新节点到面板
- **MODIFIED** `ExecutionDetail` - 集成上下文展示
## Impact
- Affected specs: `workflow-trigger`, `workflow-nodes`, `workflow-context`
- Affected code:
 - Backend: `server/workflows/`, `server/feishu/`
 - Frontend: `web/src/components/workflow/`, `web/src/stores/`, `web/src/api/`
- Database: 需要执行迁移添加新表和字段
