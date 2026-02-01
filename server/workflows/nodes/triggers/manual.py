"""Manual trigger node."""
import structlog
from workflows.nodes.base import ExecutionContext, NodePort, PortType
from workflows.nodes.registry import register_node
from workflows.nodes.triggers.base import BaseTriggerNode
logger = structlog.get_logger
@register_node
class ManualTriggerNode(BaseTriggerNode):
 """手动触发节点
 工作流的入口点，由用户手动触发执行。
 """
 node_type = "manual_trigger"
 display_name = "手动触发"
 description = "手动触发工作流执行"
 icon = "play"
 config_schema = {
 "type": "object",
 "properties": {
 "input_schema": {
 "type": "object",
 "title": "输入参数定义",
 "description": "定义用户触发时需要输入的参数",
 "default": {},
 },
 },
 }
 outputs = [
 NodePort(
 name="default",
 label="输出",
 port_type=PortType.OBJECT,
 description="触发时传入的数据",
 )
 ]
 async def parse_payload(self, context: ExecutionContext) -> dict:
 """Extract user input parameters and executor info.
 Manual trigger payload structure:
 - raw_payload: User-provided parameters
 - triggered_by info from context (if available)
 """
 raw_payload = context.input_data.get("raw_payload", context.input_data)
 # Extract user parameters (all optional for manual trigger)
 user_params = {}
 if isinstance(raw_payload, dict):
 user_params = {k: v for k, v in raw_payload.items if k != "raw_payload"}
 # Get executor info if available
 executor_id = None
 executor_name = None
 if context.workflow_execution:
 triggered_by = getattr(context.workflow_execution, "triggered_by", None)
 if triggered_by:
 executor_id = str(triggered_by.id)
 executor_name = getattr(triggered_by, "username", None)
 return {
 "data": {
 "user_params": user_params,
 "executor_id": executor_id,
 "executor_name": executor_name,
 },
 # Backward compatibility: also include flat user params
 **user_params,
 }
