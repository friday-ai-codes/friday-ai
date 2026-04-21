"""AIAgentBaseNode - Shared base class for AI agent workflow nodes.
Extracts common execution logic (session management, LangChainAgentRunner
construction, result mapping) into a base class. Subclasses only need to
override 5 hook methods to define specialized node behavior.
Phase Wave：AIAgentBaseNode.execute 从 SDKAgentRunner 切换到
LangChainAgentRunner；`_resolve_api_key_and_model` 签名由三元组
`(api_key, model, base_url)` 调整为二元组
`(ResolvedProviderConfig, model)`；use_custom_api 路径构造临时
ResolvedProviderConfig(source="node", extra={"custom_api": True, ...})
（分歧 A 覆盖 ）；None -> 工具映射（分歧 B 覆盖 ）。
"""
import asyncio
from abc import abstractmethod
from typing import Any, ClassVar, Literal
import structlog
from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage
from agents.core.result import AgentResult
from agents.langchain_runner import (
 ContextWindowExceededError,
 LangChainAgentRunner,
 LangChainRunnerConfig,
)
from agents.models import AgentSession
from agents.tools.langchain_adapter import build_langchain_tools
from services.provider_config import (
 ProviderConfigService,
 ProviderMissingError,
 ProviderType,
 ResolvedProviderConfig,
)
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
 "max_output_tokens": {
 "type": "integer",
 "title": "最大输出 Token 数",
 "description": "LLM 单次响应的最大 token 数。留空使用模型 capabilities 默认值。",
 "minimum": 100,
 "maximum": 200000,
 },
 "max_budget_usd": {
 "type": "number",
 "title": "预算上限 (USD)",
 "description": "单次调用的美元成本上限，留空不限制",
 "minimum": 0.01,
 "maximum": 100.0,
 },
 "timeout_minutes": {
 "type": "integer",
 "title": "超时时间 (分钟)",
 "description": "Agent 执行的最大超时时间，超时后自动终止。留空使用默认值（10 分钟）",
 "minimum": 1,
 "maximum": 120,
 },
 "provider_credential_id": {
 "type": "string",
 "format": "uuid",
 "title": "Provider 凭证（节点级）",
 "description": "指定本节点使用的凭证 ID，空则按项目/系统默认解析。",
 "default": "",
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
 provider_credential_id: str = "",
 ) -> tuple[ResolvedProviderConfig, str]:
 """四层优先级解析 Provider 凭证 + 模型（Phase 二元组新签名）。
 优先级：use_custom_api > provider_credential_id(节点 FK) > provider_type(节点类型)
 > conversation > project > system。
 分歧 A（覆盖 CONTEXT ）：use_custom_api=True 路径构造临时
 ResolvedProviderConfig(source="node", extra={"custom_api": True,
 "source_detail": "node_custom_api"})；source 仍为四态 ("node")，
 不新增第 5 种枚举值（严禁 D）。
 Args:
 project: 关联的项目对象（可能为 None）。
 config_model: 节点 config.model 字段值。
 use_custom_api: 节点是否启用自定义 API 分支。
 api_base_url: 自定义 API 地址（仅 use_custom_api=True 生效）。
 api_key: 自定义 API Key（仅 use_custom_api=True 生效）。
 provider_type: 节点级 provider_type 字段（兼容老字段）。
 provider_credential_id: 节点级凭证 FK（， Task 1 传真值；
 本 plan 默认空字符串保持兼容）。
 Returns:
 (resolved, model) 二元组。``resolved`` 可传给
 ``LangChainRunnerConfig.resolved`` 或 ``build_chat_model``。
 Raises:
 ValueError: 凭证缺失（ProviderMissingError 转发）或 model 未配置。
 """
 # 分支 1：自定义 API（分歧 A：source="node" + extra.custom_api=True）
 if use_custom_api and api_base_url:
 if not config_model:
 raise ValueError("使用自定义 API 时必须指定模型")
 resolved = ResolvedProviderConfig(
 provider_type=ProviderType.OPENAI_CHAT,
 api_key=api_key,
 base_url=api_base_url,
 source="node", # 四态之一；严禁 D 守护
 credential_id=None,
 extra={"custom_api": True, "source_detail": "node_custom_api"},
 )
 return resolved, config_model
 # 分支 2：四层解析（ Result 模式）
 node_config: dict[str, Any] = {}
 if provider_credential_id:
 node_config["provider_credential_id"] = provider_credential_id
 if provider_type:
 node_config["provider_type"] = provider_type
 result = await ProviderConfigService.aresolve_or_error(
 node_config=node_config or None,
 project=project,
 )
 if isinstance(result, ProviderMissingError):
 raise ValueError(
 f"未配置 {result.missing_provider} Provider 凭证："
 f"{result.recommended_action}"
 )
 resolved = result
 # 模型 fallback：config_model 为空时读 claude_config.model
 if config_model:
 resolved_model = config_model
 else:
 from services.claude_config import aget_claude_config
 cc = await aget_claude_config(project)
 resolved_model = cc.model or ""
 if not resolved_model:
 raise ValueError("未配置默认模型，请在系统设置或项目设置中配置默认模型")
 return resolved, resolved_model
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
 timeout_minutes = config.get("timeout_minutes")
 timeout_seconds = timeout_minutes * 60.0 if timeout_minutes else 600.0
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
 timeout_seconds=timeout_seconds,
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
