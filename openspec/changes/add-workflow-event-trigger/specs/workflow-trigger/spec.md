## ADDED Requirements
### Requirement: Workflow Trigger Configuration
系统 SHALL 支持为工作流配置事件触发器，触发器定义了哪些飞书事件可以自动启动工作流执行。
#### Scenario: Create trigger for WorkitemStatusEvent
- **GIVEN** 用户已创建一个工作流
- **WHEN** 用户为该工作流添加触发器，配置监听 `WorkitemStatusEvent` 事件
- **THEN** 系统创建 WorkflowTrigger 记录
- **AND** 触发器状态为 `is_active=True`
#### Scenario: Filter trigger by project_key
- **GIVEN** 触发器配置了 `filter_config.project_key = "abc123"`
- **WHEN** 飞书发送 Webhook，payload 中 `project_key = "abc123"`
- **THEN** 触发器匹配成功，工作流被触发
#### Scenario: Filter trigger by status change
- **GIVEN** 触发器配置了 `filter_config.cur_work_item_status.state_key = "sprint_planning"`
- **WHEN** 工作项状态变更为 "Sprint 计划"
- **THEN** 触发器匹配成功，工作流被触发
#### Scenario: Trigger validation with input_schema
- **GIVEN** 触发器配置了 `input_schema` 要求 `work_item_id` 为必填
- **WHEN** 飞书 Webhook payload 缺少 `work_item_id`
- **THEN** 触发器校验失败，工作流不被触发
- **AND** 系统记录校验错误日志
---
### Requirement: Event Types Support
系统 SHALL 支持以下飞书事件类型作为触发器:
- `WorkitemCreateEvent` - 工作项创建
- `WorkitemStatusEvent` - 状态变更
- `WorkitemCommentEvent` - 评论事件
- `WorkitemUpdateEvent` - 字段更新
- `WorkFlowNodeStatusEvent` - 节点流转
#### Scenario: Handle WorkitemStatusEvent
- **WHEN** 飞书发送 `WorkitemStatusEvent` Webhook
- **THEN** 系统解析 payload 中的 `pre_work_item_status` 和 `cur_work_item_status`
- **AND** 查找匹配的触发器并启动工作流
#### Scenario: Handle WorkitemCreateEvent
- **WHEN** 飞书发送 `WorkitemCreateEvent` Webhook
- **THEN** 系统解析 payload 中的工作项信息
- **AND** 查找匹配的触发器并启动工作流
---
### Requirement: Manual Trigger Execution
系统 SHALL 支持手动触发工作流执行，模拟飞书事件。
#### Scenario: Manual trigger with simulated event
- **GIVEN** 工作流配置了 `WorkitemStatusEvent` 触发器
- **WHEN** 用户调用手动触发 API，传入 `event_type` 和 `input_data`
- **THEN** 系统创建 WorkflowExecution，`is_manual_trigger = True`
- **AND** `input_data` 包含 `_manual_trigger`, `_triggered_by`, `_triggered_at` 标识
#### Scenario: Manual trigger input validation
- **GIVEN** 触发器配置了 `input_schema`
- **WHEN** 用户手动触发时 `input_data` 不符合 schema
- **THEN** 系统返回 400 错误，说明校验失败原因
---
### Requirement: Trigger Management API
系统 SHALL 提供触发器管理的 RESTful API。
#### Scenario: List triggers for workflow
- **WHEN** 调用 `GET /api/workflows/{id}/triggers/`
- **THEN** 返回该工作流的所有触发器列表
#### Scenario: Create trigger
- **WHEN** 调用 `POST /api/workflows/{id}/triggers/` 传入触发器配置
- **THEN** 创建新触发器并返回
#### Scenario: Update trigger
- **WHEN** 调用 `PUT /api/workflows/{id}/triggers/{tid}/` 传入更新数据
- **THEN** 更新触发器配置
#### Scenario: Delete trigger
- **WHEN** 调用 `DELETE /api/workflows/{id}/triggers/{tid}/`
- **THEN** 删除触发器
#### Scenario: Toggle trigger active status
- **WHEN** 调用 `PATCH /api/workflows/{id}/triggers/{tid}/` 传入 `is_active: false`
- **THEN** 禁用触发器，不再响应事件
