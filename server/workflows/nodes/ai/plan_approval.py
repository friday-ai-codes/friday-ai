"""Plan Approval node - reviews and approves/rejects technical plans.
Placeholder for Phase implementation. Inherits BaseNode (not AIAgentBaseNode)
because it doesn't need Agent capabilities - it uses the existing
waiting_approval mechanism.
"""
from typing import Any, ClassVar
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
class PlanApprovalNode(BaseNode):
 """Plan Approval node.
 Reviews technical plans and routes to approved/rejected outputs.
 Uses existing waiting_approval mechanism, not AgentLoop.
 Implementation deferred to Phase.
 """
 node_type: ClassVar[str] = "ai_plan_approval"
 display_name: ClassVar[str] = "方案审批"
 description: ClassVar[str] = "审批技术方案"
 icon: ClassVar[str] = "check-circle"
 category: ClassVar[NodeCategory] = NodeCategory.AI
 is_blocking: ClassVar[bool] = True
 config_schema: ClassVar[dict[str, Any]] = {
 "type": "object",
 "properties": {
 "chat_id": {
 "type": "string",
 "title": "Chat ID",
 "description": "飞书群 ID，用于发送审批通知",
 "default": "",
 },
 },
 "required":,
 }
 inputs: ClassVar[list[NodePort]] = [
 NodePort(
 name="default",
 label="方案输入",
 port_type=PortType.OBJECT,
 required=True,
 description="待审批的技术方案",
 ),
 ]
 outputs: ClassVar[list[NodePort]] = [
 NodePort(
 name="approved",
 label="通过",
 port_type=PortType.OBJECT,
 description="审批通过后的输出",
 ),
 NodePort(
 name="rejected",
 label="驳回",
 port_type=PortType.OBJECT,
 description="审批驳回后的输出",
 ),
 ]
 async def execute(self, context: ExecutionContext) -> NodeResult:
 """Execute plan approval node."""
 raise NotImplementedError("PlanApprovalNode will be implemented in Phase")
