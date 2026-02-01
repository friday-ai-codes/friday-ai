## ADDED Requirements
### Requirement: Unified Trigger Dispatcher
系统 SHALL 提供统一的触发器调度器 `TriggerDispatcher`，所有触发方式（飞书 Webhook、通用 Webhook、手动触发）通过它进入工作流执行。
#### Scenario: Feishu webhook triggers workflow via dispatcher
- **GIVEN** 工作流配置了 `WorkitemStatusEvent` 触发器
- **WHEN** 飞书发送 Webhook 到 `/api/feishu/webhook/`
- **THEN** 系统构建 `TriggerContext`，`trigger_type = "feishu"`
- **AND** `raw_payload` 包含原始飞书数据（不预处理）
- **AND** `TriggerDispatcher.dispatch` 查找匹配的工作流并启动执行
#### Scenario: Manual trigger via dispatcher
- **GIVEN** 用户在前端点击执行工作流
- **WHEN** 调用 `POST /api/workflows/{id}/execute/` 传入 `input_data`
- **THEN** 系统构建 `TriggerContext`，`trigger_type = "manual"`
- **AND** `raw_payload` 包含用户输入的原始数据
- **AND** `TriggerDispatcher.dispatch_single` 启动指定工作流
#### Scenario: Generic webhook triggers workflow via dispatcher
- **GIVEN** 工作流配置了 Webhook 触发器，path = "my-hook"
- **WHEN** 外部系统调用 `POST /api/webhooks/trigger/my-hook/`
- **THEN** 系统构建 `TriggerContext`，`trigger_type = "webhook"`
- **AND** `TriggerDispatcher.dispatch` 查找并启动匹配的工作流
---
### Requirement: Trigger Handler Registry
系统 SHALL 提供 `TriggerHandlerRegistry` 注册表，支持动态注册和查找触发处理器。
#### Scenario: Register handler with decorator
- **GIVEN** 定义了 `@register_handler` 装饰器
- **WHEN** 使用装饰器标注 `FeishuEventHandler` 类
- **THEN** Handler 自动注册到 `TriggerHandlerRegistry`
- **AND** 可通过 `TriggerHandlerRegistry.get("feishu")` 获取
#### Scenario: Get handler by trigger type
- **WHEN** 调用 `TriggerHandlerRegistry.get("feishu")`
- **THEN** 返回 `FeishuEventHandler` 实例
- **AND** 调用不存在的 trigger_type 返回 `None`
---
### Requirement: Trigger Context Data Structure
系统 SHALL 使用 `TriggerContext` 数据类封装所有触发相关信息，原始数据透传不预处理。
#### Scenario: Build context from Feishu webhook
- **GIVEN** 飞书 Webhook 携带 `header` 和 `payload`
- **WHEN** 构建 `TriggerContext`
- **THEN** `trigger_type = "feishu"`
- **AND** `event_type` 从 `header.event_type` 提取
- **AND** `raw_payload` 等于原始 `payload`（不做字段提取）
- **AND** `idempotency_key` 等于 `header.uuid`
#### Scenario: Build context from manual trigger
- **GIVEN** 用户传入 `input_data = {"id": 123, "name": "test"}`
- **WHEN** 构建 `TriggerContext`
- **THEN** `trigger_type = "manual"`
- **AND** `raw_payload = {"id": 123, "name": "test"}`
- **AND** `triggered_by` 等于当前用户
---
### Requirement: Trigger Handler Interface
每种触发类型 SHALL 实现 `TriggerHandler` 接口，负责验证请求、查找匹配工作流、准备执行上下文。
#### Scenario: FeishuEventHandler finds matching workflows
- **GIVEN** 项目有多个工作流，其中一个配置了 `WorkitemStatusEvent` 触发器
- **WHEN** `FeishuEventHandler.find_matching_workflows` 被调用
- **THEN** 返回匹配 `event_type` 和 `filter_config` 的工作流列表
#### Scenario: ManualHandler validates workflow is active
- **GIVEN** 工作流 `is_active = False`
- **WHEN** `ManualHandler.validate` 被调用
- **THEN** 返回 `(False, "Workflow is disabled")`
#### Scenario: WebhookHandler validates authentication
- **GIVEN** WebhookConfig 配置了 `require_auth = True`
- **WHEN** 请求缺少正确的 `Authorization` header
- **THEN** `WebhookHandler.validate` 返回 `(False, "Unauthorized")`
---
### Requirement: Base Trigger Node
触发器节点 SHALL 继承 `BaseTriggerNode` 基类，实现 `parse_payload` 方法从原始数据中提取结构化信息。
#### Scenario: FeishuEventTriggerNode parses raw payload
- **GIVEN** `context.input_data["raw_payload"]` 包含飞书原始事件数据
- **WHEN** `FeishuEventTriggerNode.parse_payload` 被调用
- **THEN** 返回结构化数据：`work_item_id`, `project_key`, `work_item_name`, `current_status` 等
#### Scenario: WebhookTriggerNode extracts configured fields
- **GIVEN** 节点配置 `extract_fields = ["user.id", "action"]`
- **WHEN** `raw_payload = {"user": {"id": 123}, "action": "create"}`
- **THEN** `parse_payload` 返回 `{"extracted": {"user_id": 123, "action": "create"}}`
#### Scenario: Trigger node validates input
- **GIVEN** 触发器节点配置监听 `WorkitemStatusEvent`
- **WHEN** `input_data["event_type"] = "WorkitemCreateEvent"`
- **THEN** `validate_input` 返回错误 "Event type not in allowed list"
---
## MODIFIED Requirements
### Requirement: Manual Trigger Execution
系统 SHALL 支持手动触发工作流执行，通过统一的 `TriggerDispatcher` 处理。
#### Scenario: Manual trigger with simulated event
- **GIVEN** 工作流配置了 `feishu_event_trigger` 节点
- **WHEN** 用户调用手动触发 API，传入飞书原始事件数据
- **THEN** 系统构建 `TriggerContext`，`trigger_type = "manual"`
- **AND** `raw_payload` 包含用户输入的原始数据
- **AND** 触发器节点通过 `parse_payload` 解析数据
- **AND** 创建 `WorkflowExecution`，`is_manual_trigger = True`
#### Scenario: Manual trigger input validation
- **GIVEN** 触发器节点定义了必填字段
- **WHEN** 用户手动触发时 `raw_payload` 缺少必填字段
- **THEN** 触发器节点 `validate_input` 返回错误
- **AND** 节点执行失败，返回验证错误信息
