"""AI Agent workflow node.
Wraps the Agent system as a workflow node, enabling:
- Custom System Prompt configuration
- Tool selection
- Suspension/resumption (linked with workflow state)
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
class AIAgentNode(AIAgentBaseNode):
 """AI Agent workflow node.
 Wraps Agent capabilities as a workflow node, supporting:
 - Custom System Prompt
 - Tool set selection
 - Suspension/resumption (linked with workflow state)
 """
 node_type: ClassVar[str] = "ai_agent"
 display_name: ClassVar[str] = "AI Agent"
 description: ClassVar[str] = "Autonomous AI agent that can invoke tools to complete complex tasks"
 icon: ClassVar[str] = "bot"
 config_schema: ClassVar[dict[str, Any]] = {
 "type": "object",
 "properties": {
 **AIAgentBaseNode.config_schema["properties"],
 "system_prompt": {
 "type": "string",
 "title": "System Prompt",
 "description": "Define the agent's role and behavior",
 "default": "You are a professional software development assistant.",
 },
 "user_prompt": {
 "type": "string",
 "title": "User Prompt",
 "description": "Initial task instruction, supports template variables",
 },
 "enabled_tools": {
 "type": "array",
 "title": "Enabled Tools",
 "description": "Leave empty to enable all tools",
 "items": {"type": "string"},
 "default":,
 },
 "max_iterations": {
 "type": "integer",
 "title": "Max Iterations",
 "default": 25,
 "minimum": 1,
 "maximum": 100,
 },
 },
 "required": ["user_prompt"],
 }
 inputs: ClassVar[list[NodePort]] = [
 NodePort(
 name="default",
 label="Input",
 port_type=PortType.OBJECT,
 required=False,
 description="Upstream node output, can be referenced in templates",
 ),
 ]
 outputs: ClassVar[list[NodePort]] = [
 NodePort(
 name="default",
 label="Agent Output",
 port_type=PortType.OBJECT,
 description="Agent execution result",
 schema={
 "type": "object",
 "properties": {
 "final_answer": {"type": "string"},
 "output": {"type": "array"},
 "usage": {"type": "object"},
 },
 },
 ),
 NodePort(
 name="error",
 label="Error",
 port_type=PortType.OBJECT,
 description="Error information on failure",
 ),
 ]
 def get_system_prompt(self, context: ExecutionContext) -> str:
 """Return system prompt from node config."""
 return context.render_template(
 context.node_config.get("system_prompt", "You are a professional software development assistant.")
 )
 def get_user_prompt(self, context: ExecutionContext) -> str:
 """Return user prompt from node config."""
 return context.render_template(context.node_config.get("user_prompt", ""))
