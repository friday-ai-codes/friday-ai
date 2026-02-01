"""Feishu event trigger node."""
import structlog
from workflows.models.trigger import TriggerEventType
from workflows.nodes.base import ExecutionContext, NodePort, PortType
from workflows.nodes.registry import register_node
from workflows.nodes.triggers.base import BaseTriggerNode
logger = structlog.get_logger
@register_node
class FeishuEventTriggerNode(BaseTriggerNode):
 """飞书事件触发节点
 通过飞书 Webhook 事件触发工作流执行。
 支持多种事件类型和过滤条件。
 """
 node_type = "feishu_event_trigger"
 display_name = "飞书事件触发"
 description = "监听飞书 Webhook 事件触发工作流"
 icon = "webhook"
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
 outputs = [
 NodePort(
 name="default",
 label="事件数据",
 port_type=PortType.OBJECT,
 description="包含 event_type, work_item_id, project_key, payload",
 ),
 ]
 async def parse_payload(self, context: ExecutionContext) -> dict:
 """Extract Feishu event data with flattening.
 Feishu payload: transparent passthrough with flattening.
 Critical fields: work_item_id (from id field)
 Optional fields: project_key, work_item_type, name, status info
 """
 raw_payload = context.input_data.get("raw_payload", context.input_data)
 input_data = context.input_data
 # Get event_type from multiple sources
 event_type = input_data.get("event_type") or context.trigger_data.get(
 "event_type", ""
 )
 # Critical: work_item_id
 work_item_id = (
 input_data.get("work_item_id")
 or context.trigger_data.get("work_item_id")
 or raw_payload.get("id")
 )
 if work_item_id:
 work_item_id = str(work_item_id)
 # Optional: project_key
 project_key = (
 input_data.get("project_key")
 or context.trigger_data.get("project_key")
 or raw_payload.get("project_key")
 or raw_payload.get("project_simple_name", "")
 )
 if not project_key:
 logger.debug(
 "optional_field_missing", field="project_key", trigger_type=self.node_type
 )
 # Optional: work item details
 work_item_type = raw_payload.get("work_item_type_key", "")
 work_item_name = raw_payload.get("name", "")
 # Optional: status info (for status change events)
 cur_status = raw_payload.get("cur_work_item_status", {})
 prev_status = raw_payload.get("pre_work_item_status", {})
 current_status = cur_status.get("state_key", "")
 current_status_name = cur_status.get("name", "")
 previous_status = prev_status.get("state_key", "")
 previous_status_name = prev_status.get("name", "")
 return {
 "data": {
 "event_type": event_type,
 "work_item_id": work_item_id,
 "project_key": project_key,
 "work_item_type": work_item_type,
 "work_item_name": work_item_name,
 "current_status": current_status,
 "current_status_name": current_status_name,
 "previous_status": previous_status,
 "previous_status_name": previous_status_name,
 },
 # Backward compatibility: flat fields at root
 "event_type": event_type,
 "work_item_id": work_item_id,
 "project_key": project_key,
 "work_item_type": work_item_type,
 "work_item_name": work_item_name,
 "current_status": current_status,
 "current_status_name": current_status_name,
 "previous_status": previous_status,
 "previous_status_name": previous_status_name,
 "payload": raw_payload, # Legacy compatibility
 }
