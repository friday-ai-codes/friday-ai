"""AI Plan Generation node - generates technical plans from requirements.
Placeholder for Phase implementation. Inherits AIAgentBaseNode and
will use specialized system/user prompts for plan generation.
"""
from typing import Any, ClassVar
from workflows.nodes.ai.base_agent import AIAgentBaseNode
from workflows.nodes.base import (
 ExecutionContext,
 NodePort,
 PortType,
)
from workflows.nodes.registry import register_node
@register_node
class AIPlanGenerationNode(AIAgentBaseNode):
 """AI Plan Generation node.
 Generates technical plans from requirements using AI agent capabilities.
 Implementation deferred to Phase.
 """
 node_type: ClassVar[str] = "ai_plan_generation"
 display_name: ClassVar[str] = "AI 方案生成"
 description: ClassVar[str] = "AI 自动生成技术方案"
 icon: ClassVar[str] = "file-code"
 config_schema: ClassVar[dict[str, Any]] = {
 "type": "object",
 "properties": {
 **AIAgentBaseNode.config_schema["properties"],
 },
 "required":,
 }
 inputs: ClassVar[list[NodePort]] = [
 NodePort(
 name="default",
 label="需求输入",
 port_type=PortType.OBJECT,
 required=False,
 description="上游节点输出，可在模板中引用",
 ),
 ]
 outputs: ClassVar[list[NodePort]] = [
 NodePort(
 name="default",
 label="技术方案",
 port_type=PortType.OBJECT,
 description="生成的技术方案",
 ),
 NodePort(
 name="error",
 label="错误",
 port_type=PortType.OBJECT,
 description="失败时的错误信息",
 ),
 ]
 def get_system_prompt(self, context: ExecutionContext) -> str:
 """Return system prompt for plan generation."""
 raise NotImplementedError("AIPlanGenerationNode will be implemented in Phase")
 def get_user_prompt(self, context: ExecutionContext) -> str:
 """Return user prompt for plan generation."""
 raise NotImplementedError("AIPlanGenerationNode will be implemented in Phase")
