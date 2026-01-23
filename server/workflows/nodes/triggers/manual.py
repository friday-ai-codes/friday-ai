"""Manual trigger node."""
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
class ManualTriggerNode(BaseNode):
 """手动触发节点
 工作流的入口点，由用户手动触发执行。
 """
 node_type = "manual_trigger"
 display_name = "手动触发"
 description = "手动触发工作流执行"
 icon = "play"
 category = NodeCategory.TRIGGER
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
 inputs: list[NodePort] = # 触发器没有输入
 outputs = [
 NodePort(
 name="default",
 label="输出",
 port_type=PortType.OBJECT,
 description="触发时传入的数据",
 )
 ]
 async def execute(self, context: ExecutionContext) -> NodeResult:
 """直接将触发数据作为输出"""
 return NodeResult(
 status="completed",
 output=context.input_data,
 )
