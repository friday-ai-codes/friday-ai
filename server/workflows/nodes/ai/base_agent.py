"""AIAgentBaseNode - Shared base class for AI agent workflow nodes.
Extracts common execution logic (session management, Agent construction,
result mapping) into a base class. Subclasses only need to override
5 hook methods to define specialized node behavior.
"""
from abc import abstractmethod
from typing import Any, ClassVar, Literal
import structlog
from agents.core.context import AgentContext
from agents.core.loop import AgentConfig, AgentLoop
from agents.core.result import AgentResult
from agents.llm.base import create_provider
from agents.models import AgentSession
from workflows.nodes.base import (
 BaseNode,
 ExecutionContext,
 NodeCategory,
 NodeResult,
)
logger = structlog.get_logger
class AIAgentBaseNode(BaseNode):
 """Base class for AI agent workflow nodes.
 Provides unified execute flow with 5 hook methods for subclass customization:
 1. get_system_prompt - Return system prompt (abstract)
 2. get_user_prompt - Return user prompt (abstract)
 3. get_enabled_tools - Return enabled tool names (default: from config)
 4. get_max_iterations - Return max iterations (default: from config)
 5. map_output - Map AgentResult to output dict (default implementation)
 Common infrastructure (session, provider, agent loop) is handled here.
 """
 category: ClassVar[NodeCategory] = NodeCategory.AI
 execution_mode: ClassVar[Literal["server_local", "runner_dispatched"]] = "server_local"
 is_blocking: ClassVar[bool] = True
 # Base config schema with common fields; subclasses extend via dict merge
 config_schema: ClassVar[dict[str, Any]] = {
 "type": "object",
 "properties": {
 "model": {
 "type": "string",
 "title": "模型",
 "description": "使用的 LLM 模型",
 "default": "",
 },
 "chat_id": {
 "type": "string",
 "title": "Chat ID",
 "description": "Feishu chat group ID for sending messages, supports template variables",
 "default": "",
 },
 "use_custom_api": {
 "type": "boolean",
 "title": "使用自定义 API",
 "description": "启用后可配置自定义的 API 地址和密钥",
 "default": False,
 },
 "api_base_url": {
 "type": "string",
 "title": "API Base URL",
 "description": "自定义 API 地址",
 "default": "",
 },
 "api_key": {
 "type": "string",
 "title": "API Key",
 "description": "API 密钥",
 "default": "",
 },
 "api_format": {
 "type": "string",
 "title": "API 格式",
 "description": "API 协议格式：anthropic（Claude 原生）或 openai（兼容格式）",
 "enum": ["anthropic", "openai"],
 "default": "anthropic",
 },
 "provider_type": {
 "type": "string",
 "title": "Provider 类型",
 "description": "LLM Provider 类型，为空时继承项目级或系统级配置",
 "default": "",
 },
 "timeout_hours": {
 "type": "integer",
 "title": "Suspension Timeout (hours)",
 "description": "Maximum wait time after agent suspension",
 "default": 24,
 },
 },
 "required":,
 }
 # ===== Hook methods (subclass overrides) =====
 @abstractmethod
 def get_system_prompt(self, context: ExecutionContext) -> str:
 """Return the system prompt for the agent.
 Args:
 context: Node execution context.
 Returns:
 System prompt string.
 """
 @abstractmethod
 def get_user_prompt(self, context: ExecutionContext) -> str:
 """Return the user prompt for the agent.
 Args:
 context: Node execution context.
 Returns:
 User prompt string.
 """
 def get_enabled_tools(self, context: ExecutionContext) -> list[str] | None:
 """Return list of enabled tool names, or None for all tools.
 Default: reads 'enabled_tools' from config. Empty list -> None (all tools).
 Args:
 context: Node execution context.
 Returns:
 List of tool name strings, or None to enable all tools.
 """
 tools: list[str] = context.node_config.get("enabled_tools", )
 return tools if tools else None
 def get_max_iterations(self, context: ExecutionContext) -> int:
 """Return maximum agent loop iterations.
 Default: reads 'max_iterations' from config, fallback 25.
 Args:
 context: Node execution context.
 Returns:
 Maximum iteration count.
 """
 value: int = context.node_config.get("max_iterations", 25)
 return value
 def map_output(self, result: AgentResult) -> dict[str, Any]:
 """Map AgentResult to node output dict.
 Default: returns final_answer, output, usage, metadata.
 Args:
 result: Completed agent result.
 Returns:
 Output dict for NodeResult.
 """
 return {
 "final_answer": result.final_answer,
 "output": result.output,
 "usage": result.usage,
 "metadata": result.metadata,
 }
 # ===== Common infrastructure methods =====
 async def _get_project(self, context: ExecutionContext) -> Any:
 """Get associated project via workflow_execution."""
 if context.workflow_execution:
 from workflows.models import WorkflowExecution
 we = await WorkflowExecution.objects.select_related(
 "workflow__project"
 ).aget(id=context.workflow_execution.id)
 if we.workflow:
 return we.workflow.project
 return None
 async def _get_user(self, context: ExecutionContext) -> Any:
 """Get triggering user via workflow_execution."""
 if context.workflow_execution:
 from workflows.models import WorkflowExecution
 we = await WorkflowExecution.objects.select_related(
 "triggered_by"
 ).aget(id=context.workflow_execution.id)
 return we.triggered_by
 return None
 async def _get_provider(
 self,
 project: Any,
 model: str = "",
 use_custom_api: bool = False,
 api_base_url: str = "",
 api_key: str = "",
 api_format: str = "",
 provider_type: str = "",
 ) -> Any:
 """Get LLM Provider, supporting provider_type, custom API, or system config.
 优先级：provider_type > use_custom_api > 系统/项目级默认配置。
 """
 from services.provider_config import ProviderConfigService
 # 分支 1: 有 provider_type → 走 ProviderConfigService
 if provider_type:
 resolved = await ProviderConfigService.aresolve(
 node_config={"provider_type": provider_type},
 project=project,
 )
 from services.claude_config import aget_claude_config
 config = await aget_claude_config(project)
 resolved_model = model or config.model
 if not resolved_model:
 raise ValueError("未配置默认模型，请在系统设置或项目设置中配置默认模型")
 return create_provider(
 resolved.provider_type,
 api_key=resolved.api_key,
 base_url=resolved.base_url,
 model=resolved_model,
 )
 # 分支 2: 有 use_custom_api → 保持现有逻辑（向后兼容）
 if use_custom_api and api_base_url:
 if not model:
 raise ValueError("使用自定义 API 时必须指定模型")
 pt = api_format or "anthropic"
 return create_provider(pt, api_key=api_key, base_url=api_base_url, model=model)
 # 分支 3: 两者都无 → 走 ProviderConfigService（无 node_config）
 resolved = await ProviderConfigService.aresolve(project=project)
 from services.claude_config import aget_claude_config
 config = await aget_claude_config(project)
 resolved_model = model or config.model
 if not resolved_model:
 raise ValueError("未配置默认模型，请在系统设置或项目设置中配置默认模型")
 return create_provider(
 resolved.provider_type,
 api_key=resolved.api_key,
 base_url=resolved.base_url,
 model=resolved_model,
 )
 def _build_session_id(self, context: ExecutionContext) -> str:
 """Generate unique session ID: wf-{execution_id}-{node_id}."""
 return f"wf-{context.execution_id}-{context.node_id}"
 async def _ensure_agent_session(
 self,
 session_id: str,
 project: Any,
 user: Any,
 chat_id: str,
 ) -> None:
 """Pre-create AgentSession with chat_id for ask_user_question tool."""
 if chat_id and project:
 await AgentSession.objects.aupdate_or_create(
 session_id=session_id,
 defaults={
 "project_id": project.id,
 "user_id": user.id if user else None,
 "status": AgentSession.Status.RUNNING,
 "temp_data": {"chat_id": chat_id},
 },
 )
 def _enhance_system_prompt(self, system_prompt: str, session_id: str) -> str:
 """Inject session_id into system prompt for tools that need it."""
 return (
 f"{system_prompt}\n\n"
 f"[System Info]\n"
 f"- session_id: {session_id}\n"
 f"When calling tools that require session_id, always use: {session_id}"
 )
 # ===== Unified execute method =====
 async def execute(self, context: ExecutionContext) -> NodeResult:
 """Execute the AI agent node using hook methods and common infrastructure."""
 config = context.node_config
 # 1. Call hook methods
 system_prompt = self.get_system_prompt(context)
 user_prompt = self.get_user_prompt(context)
 enabled_tools = self.get_enabled_tools(context)
 max_iterations = self.get_max_iterations(context)
 if not user_prompt:
 return NodeResult(
 status="failed",
 error="User Prompt cannot be empty",
 next_handle="error",
 )
 try:
 # 2. Common construction
 project = await self._get_project(context)
 user = await self._get_user(context)
 session_id = self._build_session_id(context)
 chat_id = context.render_template(config.get("chat_id", ""))
 model: str = config.get("model", "")
 use_custom_api: bool = config.get("use_custom_api", False)
 api_base_url: str = config.get("api_base_url", "")
 api_key: str = config.get("api_key", "")
 api_format: str = config.get("api_format", "")
 provider_type_cfg: str = config.get("provider_type", "")
 logger.info(
 "agent_node_start",
 session_id=session_id,
 project_id=project.id if project else None,
 user_id=user.id if user else None,
 max_iterations=max_iterations,
 enabled_tools_count=len(enabled_tools) if enabled_tools else "all",
 chat_id=chat_id,
 )
 await self._ensure_agent_session(session_id, project, user, chat_id)
 enhanced_prompt = self._enhance_system_prompt(system_prompt, session_id)
 # Build Agent context
 agent_context = AgentContext(
 session_id=session_id,
 project_id=project.id if project else 0,
 user_id=user.id if user else 0,
 metadata={"chat_id": chat_id} if chat_id else {},
 )
 # Build Agent configuration
 agent_config = AgentConfig(
 system_prompt=enhanced_prompt,
 max_iterations=max_iterations,
 tool_names=enabled_tools,
 )
 # Get LLM Provider
 provider = await self._get_provider(
 project, model, use_custom_api, api_base_url, api_key, api_format,
 provider_type=provider_type_cfg,
 )
 # 3. Execute Agent
 loop = AgentLoop(
 config=agent_config,
 context=agent_context,
 provider=provider,
 )
 result = await loop.run(user_prompt)
 # 4. Result mapping
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
 output=self.map_output(result),
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
