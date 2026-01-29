# workflow-context Specification
## Purpose
TBD - created by archiving change add-workflow-event-trigger. Update Purpose after archive.
## Requirements
### Requirement: Global Parameters Management
系统 SHALL 支持工作流执行级别的全局参数，允许节点写入和读取共享数据。
#### Scenario: Node sets global parameter
- **GIVEN** FetchWorkItemNode 配置 `set_global_params: true`
- **WHEN** 节点执行成功
- **THEN** 调用 `context.set_global_param("prd_url", value)`
- **AND** 参数存储在 `WorkflowExecution.global_params`
#### Scenario: Node reads global parameter
- **GIVEN** 前序节点已设置 `global_params.prd_url`
- **WHEN** 后续节点配置 `user_prompt: "{{global.prd_url}}"`
- **THEN** 模板变量被替换为实际值
#### Scenario: Global params persist across nodes
- **GIVEN** 工作流包含多个节点
- **WHEN** 节点 A 设置 `global_params.key = value`
- **THEN** 节点 B, C, D... 都可以读取该值
---
### Requirement: Template Variable Syntax
系统 SHALL 支持以下模板变量语法用于节点配置:
| 语法 | 说明 |
|-----|-----|
| `{{input.key}}` | 执行输入数据 |
| `{{context.key}}` | 工作流上下文 |
| `{{global.key}}` | 全局参数 |
| `{{nodes.node_id.key}}` | 上游节点输出 |
| `{{trigger.key}}` | 触发器数据 |
#### Scenario: Render input variable
- **GIVEN** `WorkflowExecution.input_data = {"work_item_id": "12345"}`
- **WHEN** 渲染模板 `"ID: {{input.work_item_id}}"`
- **THEN** 结果为 `"ID: 12345"`
#### Scenario: Render global variable
- **GIVEN** `WorkflowExecution.global_params = {"prd_url": "https://..."}`
- **WHEN** 渲染模板 `"{{global.prd_url}}"`
- **THEN** 结果为 `"https://..."`
#### Scenario: Render node output variable
- **GIVEN** 节点 `fetch_1` 输出 `{"description": "需求描述"}`
- **WHEN** 渲染模板 `"{{nodes.fetch_1.description}}"`
- **THEN** 结果为 `"需求描述"`
#### Scenario: Render trigger variable
- **GIVEN** `trigger_data = {"event_type": "WorkitemStatusEvent"}`
- **WHEN** 渲染模板 `"{{trigger.event_type}}"`
- **THEN** 结果为 `"WorkitemStatusEvent"`
#### Scenario: Undefined variable handling
- **GIVEN** 变量 `{{global.undefined_key}}` 不存在
- **WHEN** 渲染模板
- **THEN** 返回空字符串 `""`
---
### Requirement: Execution Context API
系统 SHALL 提供 API 查询工作流执行的上下文信息。
#### Scenario: Get execution context
- **WHEN** 调用 `GET /api/workflows/executions/{id}/context/`
- **THEN** 返回:
 ```json
 {
 "execution_id": "uuid",
 "status": "running",
 "progress": 45.5,
 "is_manual_trigger": false,
 "trigger_data": {
 "event_type": "WorkitemStatusEvent",
 "trigger_log_id": "uuid"
 },
 "global_params": {
 "prd_url": "https://...",
 "description": "...",
 "repositories": [...]
 },
 "node_outputs": {
 "trigger_1": {"event_type": "..."},
 "fetch_1": {"name": "...", "description": "..."}
 }
 }
 ```
#### Scenario: Context updates during execution
- **GIVEN** 工作流正在执行
- **WHEN** 节点完成并设置全局参数
- **THEN** 下一次调用 context API 返回更新后的数据
---
### Requirement: Node Output Storage
系统 SHALL 自动存储每个节点的输出，供后续节点和前端查询。
#### Scenario: Store node output
- **GIVEN** 节点执行完成
- **WHEN** 返回 `NodeResult(status="completed", output={...})`
- **THEN** 输出存储在 `WorkflowExecution.context["node_outputs"][node_id]`
#### Scenario: Access node output from downstream
- **GIVEN** 节点 A 输出 `{"key": "value"}`
- **WHEN** 节点 B 使用 `context.get_previous_output("node_a", "key")`
- **THEN** 返回 `"value"`
---
### Requirement: Context Visibility Rules
系统 SHALL 遵循以下上下文可见性规则:
| 节点位置 | 可访问的上下文 |
|---------|--------------|
| 触发器节点 | `input`, `trigger` |
| 触发器之后的节点 | `input`, `trigger`, `global_params`, 前序节点 `outputs` |
| 任意节点 | 可设置 `global_params`，后续节点可读取 |
#### Scenario: Trigger node limited context
- **GIVEN** 触发器节点正在执行
- **WHEN** 尝试访问 `{{global.key}}`
- **THEN** 返回空字符串（全局参数尚未设置）
#### Scenario: Downstream node full context
- **GIVEN** 非触发器节点正在执行
- **WHEN** 访问 `{{global.key}}`, `{{input.key}}`, `{{trigger.key}}`
- **THEN** 所有变量都可正确解析
---
### Requirement: CodingTask Model
系统 SHALL 提供 CodingTask 模型存储 AI 编码任务。
#### Scenario: Create coding task
- **GIVEN** AICodingDispatcherNode 分析完成
- **WHEN** 为仓库 repo-1 生成编码任务
- **THEN** 创建 CodingTask 记录:
 - `workflow_execution`: 关联当前执行
 - `repository`: 关联 repo-1
 - `name`: 任务名称
 - `prompt`: AI 编码 Prompt
 - `status`: "pending"
#### Scenario: CodingTask status lifecycle
- **GIVEN** CodingTask 创建后
- **WHEN** 任务经历各阶段
- **THEN** 状态可流转:
 - `pending` → `planning` → `plan_review` → `executing` → `code_review` → `merged`
 - 任意阶段可转为 `failed`
#### Scenario: CodingTask API
- **WHEN** 调用 `GET /api/workflows/executions/{id}/coding-tasks/`
- **THEN** 返回该执行创建的所有编码任务列表
---
### Requirement: Frontend Context Inspector
前端 SHALL 提供上下文检查器组件，可视化展示执行上下文。
#### Scenario: Display global params
- **GIVEN** 执行详情页面
- **WHEN** 渲染 ContextInspector 组件
- **THEN** 显示全局参数区块，包含所有键值对
#### Scenario: Display node outputs
- **GIVEN** 工作流已执行若干节点
- **WHEN** 渲染 ContextInspector 组件
- **THEN** 按节点分组显示输出
- **AND** 显示节点名称和类型图标
#### Scenario: Copy variable path
- **GIVEN** 用户查看节点 fetch_1 的 prd_url 输出
- **WHEN** 点击复制按钮
- **THEN** 复制 `{{nodes.fetch_1.prd_url}}` 到剪贴板
#### Scenario: Real-time update
- **GIVEN** 工作流正在执行
- **WHEN** 新节点完成执行
- **THEN** 上下文检查器自动更新显示新数据
