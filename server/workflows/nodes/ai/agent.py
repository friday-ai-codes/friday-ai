"""AI Agent workflow node.
Wraps the Agent system as a workflow node, enabling:
- Custom System Prompt configuration
- Tool selection
- Suspension/resumption (linked with workflow state)
"""
from typing import Any, ClassVar
import structlog
from asgiref.sync import sync_to_async
from agents.core.context import AgentContext
from agents.core.loop import AgentConfig, AgentLoop
from agents.llm.claude import ClaudeProvider
from workflows.nodes.base import (
 BaseNode,
 ExecutionContext,
 NodeCategory,
 NodePort,
 NodeResult,
 PortType,
)
from workflows.nodes.registry import register_node
logger = structlog.get_logger
@register_node
class AIAgentNode(BaseNode):
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
 category: ClassVar[NodeCategory] = NodeCategory.AI
 is_blocking: ClassVar[bool] = True
 config_schema: ClassVar[dict[str, Any]] = {
 "type": "object",
 "properties": {
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
 "timeout_hours": {
 "type": "integer",
 "title": "Suspension Timeout (hours)",
 "description": "Maximum wait time after agent suspension",
 "default": 24,
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
 async def execute(self, context: ExecutionContext) -> NodeResult:
 """Execute the AI Agent node."""
 config = context.node_config
 # Parse configuration
 system_prompt = context.render_template(
 config.get("system_prompt", "You are a professional software development assistant.")
 )
 user_prompt = context.render_template(config.get("user_prompt", ""))
 enabled_tools = config.get("enabled_tools", )
 max_iterations = config.get("max_iterations", 25)
 if not user_prompt:
 return NodeResult(
 status="failed",
 error="User Prompt cannot be empty",
 next_handle="error",
 )
 try:
 # Get project and user
 project = await self._get_project(context)
 user = await self._get_user(context)
 # Create unique session ID
 session_id = f"wf-{context.execution_id}-{context.node_id}"
 logger.info(
 "agent_node_start",
 session_id=session_id,
 project_id=project.id if project else None,
 user_id=user.id if user else None,
 max_iterations=max_iterations,
 enabled_tools_count=len(enabled_tools) if enabled_tools else "all",
 )
 # Build Agent context
 agent_context = AgentContext(
 session_id=session_id,
 project_id=project.id if project else 0,
 user_id=user.id if user else 0,
 )
 # Build Agent configuration
 agent_config = AgentConfig(
 system_prompt=system_prompt,
 max_iterations=max_iterations,
 tool_names=enabled_tools if enabled_tools else None,
 )
 # Get LLM Provider
 provider = await self._get_provider(project)
 # Execute Agent
 loop = AgentLoop(
 config=agent_config,
 context=agent_context,
 provider=provider,
 )
 result = await loop.run(user_prompt)
 # Handle result
 if result.status == "suspended":
 logger.info(
 "agent_node_suspended",
 session_id=session_id,
 suspension=result.metadata.get("suspension"),
 )
 return NodeResult(
 status="waiting_event",
 output={
 "session_id": session_id,
 "suspension": result.metadata.get("suspension"),
 "partial_output": result.output,
 },
 )
 if result.status == "completed":
 logger.info(
 "agent_node_completed",
 session_id=session_id,
 iterations=result.metadata.get("iterations"),
 tool_calls_count=result.metadata.get("tool_calls_count"),
 )
 return NodeResult(
 status="completed",
 output={
 "final_answer": result.final_answer,
 "output": result.output,
 "usage": result.usage,
 "metadata": result.metadata,
 },
 next_handle="default",
 )
 # max_iterations or other non-complete status
 logger.warning(
 "agent_node_incomplete",
 session_id=session_id,
 status=result.status,
 )
 return NodeResult(
 status="failed",
 error=f"Agent execution incomplete: {result.status}",
 next_handle="error",
 )
 except Exception as e:
 logger.exception("agent_node_error", error=str(e))
 return NodeResult(
 status="failed",
 error=str(e),
 next_handle="error",
 )
 async def _get_project(self, context: ExecutionContext) -> Any:
 """Get associated project."""
 if context.workflow_execution:
 workflow = await sync_to_async(lambda: context.workflow_execution.workflow)
 if workflow:
 return await sync_to_async(lambda: workflow.project)
 return None
 async def _get_user(self, context: ExecutionContext) -> Any:
 """Get triggering user."""
 if context.workflow_execution:
 return await sync_to_async(lambda: context.workflow_execution.triggered_by)
 return None
 async def _get_provider(self, project: Any) -> ClaudeProvider:
 """Get LLM Provider."""
 from services.claude_config import get_claude_config
 config = await sync_to_async(get_claude_config)(project)
 return ClaudeProvider(api_key=config.api_key, base_url=config.base_url)
