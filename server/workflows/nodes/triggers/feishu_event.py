"""Feishu event trigger node."""
from workflows.models.trigger import TriggerEventType
from workflows.nodes.base import (
 BaseNode,
 ExecutionContext,
 NodeCategory,
 NodePort,
 NodeResult,
 PortType,
)
from workflows.nodes.registry import register_node
@register_node
class FeishuEventTriggerNode(BaseNode):
 """飞书事件触发节点
 通过飞书 Webhook 事件触发工作流执行。
 支持多种事件类型和过滤条件。
 """
 node_type = "feishu_event_trigger"
 display_name = "飞书事件触发"
 description = "监听飞书 Webhook 事件触发工作流"
 icon = "webhook"
 category = NodeCategory.TRIGGER
 config_schema = {
 "type": "object",
 "properties": {
 "event_types": {
 "type": "array",
 "title": "事件类型",
 "description": "要监听的飞书事件类型",
 "items": {
 "type": "string",
 "enum": [choice.value for choice in TriggerEventType],
 },
 "default": [TriggerEventType.WORKITEM_STATUS.value],
 },
 "filter_project_key": {
 "type": "string",
 "title": "项目 Key",
 "description": "可选，仅处理指定项目的事件",
 "default": "",
 },
 "filter_work_item_type": {
 "type": "string",
 "title": "工作项类型",
 "description": "可选，仅处理指定类型的工作项",
 "enum": ["", "story", "task", "bug", "epic", "feature"],
 "default": "",
 },
 "filter_status": {
 "type": "string",
 "title": "状态过滤",
 "description": "可选，仅处理指定状态的事件",
 "default": "",
 },
 },
 "required": ["event_types"],
 }
 # 触发器节点无输入端口
 inputs: list[NodePort] =
 outputs = [
 NodePort(
 name="default",
 label="事件数据",
 port_type=PortType.OBJECT,
 description="包含 event_type, work_item_id, project_key, payload",
 ),
 ]
 async def execute(self, context: ExecutionContext) -> NodeResult:
 """提取并输出事件数据
 从 input_data 和 trigger_data 中提取飞书事件相关信息。
 """
 # 从 input_data 获取事件基本信息
 event_type = context.get_input("event_type", "")
 work_item_id = context.get_input("work_item_id", "")
 project_key = context.get_input("project_key", "")
 payload = context.get_input("payload", {})
 # 如果 input_data 中没有，尝试从 trigger_data 获取
 if not event_type:
 event_type = context.get_trigger_data("event_type", "")
 if not work_item_id:
 work_item_id = context.get_trigger_data("work_item_id", "")
 if not project_key:
 project_key = context.get_trigger_data("project_key", "")
 if not payload:
 payload = context.get_trigger_data("payload", {})
 # 提取更多有用信息
 work_item_type = payload.get("work_item_type_key", "")
 work_item_name = payload.get("name", "")
 # 状态信息（适用于状态变更事件）
 cur_status = payload.get("cur_work_item_status", {})
 prev_status = payload.get("pre_work_item_status", {})
 output = {
 "event_type": event_type,
 "work_item_id": work_item_id,
 "project_key": project_key,
 "work_item_type": work_item_type,
 "work_item_name": work_item_name,
 "current_status": cur_status.get("state_key", ""),
 "current_status_name": cur_status.get("name", ""),
 "previous_status": prev_status.get("state_key", ""),
 "previous_status_name": prev_status.get("name", ""),
 "payload": payload,
 }
 return NodeResult(
 status="completed",
 output=output,
 )
