"""AIAgentBaseNode - Shared base class for AI agent workflow nodes.
Extracts common execution logic (session management, SDKAgentRunner construction,
result mapping) into a base class. Subclasses only need to override
5 hook methods to define specialized node behavior.
"""
from abc import abstractmethod
from typing import Any, ClassVar, Literal
import structlog
from agents.core.result import AgentResult
from agents.models import AgentSession
from agents.sdk.runner import SDKAgentRunner, SdkRunnerConfig
from services.provider_config import ProviderConfigService
from workflows.nodes.ai.sub_step_mixin import SubStepMixin
from workflows.nodes.base import (
 BaseNode,
 ExecutionContext,
 NodeCategory,
 NodeResult,
)
logger = structlog.get_logger
class AIAgentBaseNode(SubStepMixin, BaseNode):
 """Base class for AI agent workflow nodes.
 Provides unified execute flow with 5 hook methods for subclass customization:
 1. get_system_prompt - Return system prompt (abstract)
 2. get_user_prompt - Return user prompt (abstract)
 3. get_enabled_tools - Return enabled tool names (default: from config)
 4. get_max_iterations - Return max iterations (default: from config)
 5. map_output - Map AgentResult to output dict (default implementation)
 Common infrastructure (session, SDKAgentRunner) is handled here.
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
 # 高级设置
 "max_thinking_tokens": {
 "type": "integer",
 "title": "最大思考 Token 数",
 "description": "Claude 扩展思考的 token 上限，仅 Claude 模型支持。留空使用默认值",
 "minimum": 1024,
 "maximum": 128000,
 },
 "max_budget_usd": {
 "type": "number",
 "title": "预算上限 (USD)",
 "description": "单次调用的美元成本上限，留空不限制",
 "minimum": 0.01,
 "maximum": 100.0,
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
 """Return maximum agent turns.
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
 async def _resolve_api_key_and_model(
 self,
 project: Any,
 config_model: str = "",
 use_custom_api: bool = False,
 api_base_url: str = "",
 api_key: str = "",
 provider_type: str = "",
 ) -> tuple[str, str, str]:
 """Resolve API key, model, and base URL from config hierarchy.
 优先级：use_custom_api > provider_type > 系统/项目级默认配置。
 Returns:
 (api_key, model, base_url) 元组
 """
 # 分支 1: 自定义 API
 if use_custom_api and api_base_url and api_key:
 if not config_model:
 raise ValueError("使用自定义 API 时必须指定模型")
 return api_key, config_model, api_base_url
 # 分支 2: 通过 ProviderConfigService 解析
 node_config = {"provider_type": provider_type} if provider_type else None
 resolved = await ProviderConfigService.aresolve(
 node_config=node_config,
 project=project,
 )
 from services.claude_config import aget_claude_config
 claude_config = await aget_claude_config(project)
 resolved_model = config_model or claude_config.model
 if not resolved_model:
 raise ValueError("未配置默认模型，请在系统设置或项目设置中配置默认模型")
 resolved_base_url = getattr(resolved, "base_url", "") or ""
 return resolved.api_key, resolved_model, resolved_base_url
 def _build_session_id(self, context: ExecutionContext) -> str:
 """Generate unique session ID: wf-{execution_id}-{node_id}."""
 return f"wf-{context.execution_id}-{context.node_id}"
 async def _ensure_agent_session(
 self,
 session_id: str,
 project: Any,
 user: Any,
 chat_id: str,
 ) -> AgentSession | None:
 """Pre-create AgentSession with chat_id for ask_user_question tool.
 Returns:
 AgentSession 实例（用于 SDKAgentRunner hooks），
 或 None（无 project/chat_id 时）。
 """
 if chat_id and project:
 session, _created = await AgentSession.objects.aupdate_or_create(
 session_id=session_id,
 defaults={
 "project_id": project.id,
 "user_id": user.id if user else None,
 "status": AgentSession.Status.RUNNING,
 "temp_data": {"chat_id": chat_id},
 },
 )
 return session
 return None
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
 """Execute the AI agent node using SDKAgentRunner."""
 config = context.node_config
 # 1. Call hook methods
 system_prompt = self.get_system_prompt(context)
 user_prompt = self.get_user_prompt(context)
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
 model_cfg: str = config.get("model", "")
 use_custom_api: bool = config.get("use_custom_api", False)
 api_base_url: str = config.get("api_base_url", "")
 api_key_cfg: str = config.get("api_key", "")
 provider_type_cfg: str = config.get("provider_type", "")
 logger.info(
 "agent_node_start",
 session_id=session_id,
 project_id=project.id if project else None,
 user_id=user.id if user else None,
 max_iterations=max_iterations,
 chat_id=chat_id,
 )
 agent_session = await self._ensure_agent_session(session_id, project, user, chat_id)
 enhanced_prompt = self._enhance_system_prompt(system_prompt, session_id)
 # Resolve API key, model, and base URL
 api_key, resolved_model, resolved_base_url = await self._resolve_api_key_and_model(
 project, model_cfg, use_custom_api, api_base_url, api_key_cfg,
 provider_type=provider_type_cfg,
 )
 # 3. Build and run SDKAgentRunner
 runner_config = SdkRunnerConfig(
 system_prompt=enhanced_prompt,
 model=resolved_model,
 project_id=str(project.id) if project else "",
 session_id=session_id,
 api_key=api_key,
 api_base_url=resolved_base_url,
 max_turns=max_iterations,
 agent_session=agent_session,
 max_thinking_tokens=config.get("max_thinking_tokens"),
 max_budget_usd=config.get("max_budget_usd"),
 )
 runner = SDKAgentRunner(runner_config)
 # 消费完整 stream 以获取结果（workflow 节点不需要 SSE 流式输出）
 async for _event in runner.stream(user_prompt):
 pass
 result = runner.result
 if result is None:
 return NodeResult(
 status="failed",
 error="SDKAgentRunner returned no result",
 next_handle="error",
 )
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
 )
 return NodeResult(
 status="completed",
 output=self.map_output(result),
 next_handle="default",
 )
 # error or other non-complete status
 error_detail = result.error or ""
 logger.warning(
 "agent_node_incomplete",
 session_id=session_id,
 status=result.status,
 error=error_detail,
 )
 error_msg = f"Agent execution incomplete: {result.status}"
 if error_detail:
 error_msg += f"\n{error_detail}"
 return NodeResult(
 status="failed",
 error=error_msg,
 next_handle="error",
 )
 except Exception as e:
 logger.exception("agent_node_error", error=str(e))
 return NodeResult(
 status="failed",
 error=str(e),
 next_handle="error",
 )
