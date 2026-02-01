# Change: 统一触发器调度器重构
## Why
当前触发器架构存在三个问题：
1. **多入口分散**：飞书走 `FeishuWebhookView` → `workflow_bridge`，手动执行走 `WorkflowViewSet.execute`，通用 Webhook 走 `WebhookTriggerView`
2. **数据格式不一致**：`workflow_bridge._start_workflow` 会预处理飞书数据（提取 `event_type`, `work_item_id`），但手动触发直接透传原始数据，导致触发器节点需要兼容多种格式
3. **`workflow_bridge` 职责不清**：既处理飞书特有逻辑（审批、评论），又包含通用工作流启动逻辑
## What Changes
- **ADDED** `TriggerDispatcher` 统一调度器，所有触发方式通过它进入工作流
- **ADDED** `TriggerContext` 数据类，携带原始 payload（不预处理）
- **ADDED** `TriggerHandler` 接口和具体实现（Feishu、Webhook、Manual）
- **ADDED** `BaseTriggerNode` 触发器节点基类，节点自己实现 `parse_payload` 解析原始数据
- **MODIFIED** 现有触发器节点继承 `BaseTriggerNode`
- **MODIFIED** View 层使用 `TriggerDispatcher` 替代直接调用 `WorkflowEngine`
- **REMOVED** `workflow_bridge` 中的数据预处理逻辑（保留审批处理）
## Impact
- Affected specs: `workflow-trigger`
- Affected code:
 - `server/workflows/triggers/` (新建)
 - `server/workflows/nodes/triggers/` (重构)
 - `server/feishu/views.py` (改造)
 - `server/workflows/api/views.py` (改造)
 - `server/feishu/workflow_bridge.py` (废弃部分逻辑)
