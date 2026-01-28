# Design: Workflow Event Trigger and Context Management System
## Context
当前 Friday 工作流系统具备完整的 DAG 执行引擎，但缺乏与外部系统的事件驱动集成能力。飞书项目管理系统可以发送 Webhook 事件，需要建立桥接机制实现自动触发工作流。
### Stakeholders
- 产品团队: 需要自动化需求到代码的流程
- 开发团队: 需要 AI 辅助编码任务分派
### Constraints
- 必须兼容现有的 WorkflowExecution 模型
- 必须复用现有的 FeishuClient 和 NodeRegistry 机制
- 前端必须遵循 Vue 3 + shadcn-vue 设计规范
## Goals / Non-Goals
### Goals
- 实现飞书 Webhook 事件驱动的工作流触发
- 支持手动触发（模拟事件）
- 实现节点间数据传递的管道机制
- 提供全局参数/上下文的可视化展示
- 创建 AI 编码任务指派器节点
### Non-Goals
- 不实现定时触发（已有 schedule 类型）
- 不实现工作流编排的可视化拖拽（已有）
- 不实现 AI 编码任务的实际执行（仅创建任务）
## Decisions
### D1: 触发器配置存储位置
**决定**: 创建独立的 `WorkflowTrigger` 模型，与 Workflow 一对多关联。
**原因**:
- 一个工作流可能需要监听多种事件
- 触发器配置独立于工作流定义
- 便于管理触发器的启用/禁用状态
**替代方案**:
- 存储在 Workflow.trigger_config JSON 字段 → 不够灵活，难以管理多个触发器
### D2: 全局参数存储位置
**决定**: 在 `WorkflowExecution` 模型中新增 `global_params` JSON 字段。
**原因**:
- 全局参数与执行实例绑定，而非工作流定义
- 便于节点读写和前端查询
- 与现有的 `context` 字段分离，职责清晰
**替代方案**:
- 存储在 context 字段内 → 职责混乱，context 用于引擎内部状态
### D3: 变量引用语法
**决定**: 扩展现有模板语法，新增 `{{global.key}}` 和 `{{trigger.key}}`。
**语法规范**:
```
{{input.key}} - 执行输入数据
{{context.key}} - 工作流上下文
{{global.key}} - 全局参数 (新增)
{{nodes.node_id.key}} - 上游节点输出
{{trigger.key}} - 触发器数据 (新增)
```
**原因**:
- 与现有语法保持一致
- 语义清晰，易于理解
### D4: AI 编码任务模型位置
**决定**: 在 `workflows` 模块下创建 `CodingTask` 模型。
**原因**:
- `tasks` 模块已标记为废弃
- CodingTask 与 WorkflowExecution 强关联
- 保持新功能在 workflows 模块内
### D5: 节点目录结构
**决定**: 按功能分类创建子目录:
```
server/workflows/nodes/
├── triggers/
│ └── feishu_event.py
├── integrations/
│ └── feishu_workitem.py
└── ai/
 ├── prompt.py
 └── coding_dispatcher.py
```
**原因**:
- 与现有 NodeCategory 枚举对应
- 便于节点自动发现和注册
## Data Flow
### Webhook 触发流程
```
飞书 Webhook → FeishuWebhookView → FeishuWorkflowBridge.dispatch_event
 │
 ▼
 查询 WorkflowTrigger
 │
 ▼
 校验 filter_config + input_schema
 │
 ▼
 WorkflowEngine.start_execution
 │
 ▼
 创建 WorkflowExecution
 设置 input_data, trigger_data
 │
 ▼
 执行节点 DAG
```
### 上下文数据流
```
┌─────────────────────────────────────────────────────────────────┐
│ WorkflowExecution │
│ ┌─────────────┐ ┌─────────────┐ ┌─────────────────────────┐ │
│ │ input_data │ │trigger_data │ │ context │ │
│ │ (不可变) │ │ (不可变) │ │ ┌───────────────────┐ │ │
│ │ │ │ │ │ │ global_params │ │ │
│ │ work_item_id│ │ event_type │ │ │ (节点可写入) │ │ │
│ │ project_key │ │trigger_log_id│ │ ├───────────────────┤ │ │
│ └─────────────┘ └─────────────┘ │ │ node_outputs │ │ │
│ │ │ (引擎自动记录) │ │ │
│ │ └───────────────────┘ │ │
│ └─────────────────────────┘ │
└─────────────────────────────────────────────────────────────────┘
```
## Risks / Trade-offs
### R1: Webhook 处理阻塞风险
**风险**: 工作流执行时间长，可能导致 Webhook 响应超时。
**缓解**:
- 飞书 Webhook 超时 6 秒，最多重试 3 次
- 使用幂等串 (header.uuid) 防止重复处理
- 工作流启动后立即返回，异步执行
### R2: 全局参数并发写入
**风险**: 多个节点并发写入 global_params 可能导致数据丢失。
**缓解**:
- DAG 执行保证节点顺序
- 写入时使用 update_fields 减少冲突
- 未来可考虑添加锁机制
### R3: LLM 调用失败
**风险**: AI 节点依赖外部 LLM 服务，可能失败。
**缓解**:
- 节点支持重试 (supports_retry = True)
- 失败时输出到 error 端口
- 记录详细错误日志
## API Endpoints Summary
| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/workflows/{id}/triggers/` | GET, POST | 触发器列表和创建 |
| `/api/workflows/{id}/triggers/{tid}/` | PUT, DELETE | 触发器更新和删除 |
| `/api/workflows/{id}/execute/` | POST | 手动触发执行 |
| `/api/workflows/executions/{id}/context/` | GET | 获取执行上下文 |
| `/api/workflows/nodes/schemas/` | GET | 获取所有节点 Schema |
| `/api/workflows/executions/{id}/coding-tasks/` | GET | 获取编码任务列表 |
| `/api/workflows/coding-tasks/{id}/` | GET, PATCH | 编码任务详情和更新 |
## Open Questions
- 是否需要支持触发器的优先级排序？
- 是否需要限制单个工作流的并发执行数量？
- AI 编码任务创建后如何触发实际执行？
