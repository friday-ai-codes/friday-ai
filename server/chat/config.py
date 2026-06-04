"""Chat 运行配置构建。"""
from __future__ import annotations
import uuid
from agents.chat_runner import ChatRunnerConfig
from agents.models import AgentSession
from chat.conversation_service import _build_system_prompt
from chat.models import Conversation
from chat.services import aget_setting_value
from services.provider_config import (
 ProviderConfigError,
 ProviderConfigService,
 aget_legacy_anthropic_config,
)
from system.models import SettingKeys
async def build_sdk_config(
 conversation: Conversation,
 role: str = "developer",
 notification_user_id: str | None = None,
 force_deep_analysis: bool = False,
 project_context_line: str | None = None,
) -> tuple[ChatRunnerConfig, AgentSession]:
 """从 Conversation 实例构建 ChatRunnerConfig 和 AgentSession。
 提取自 ConversationService.send_message_stream 的配置构建段，
 将散落在 40+ 行中的 API key 解析、model 解析、session 创建等逻辑
 收敛为单一函数。调用方需确保 conversation 已 select_related("project")。
 Returns:
 (ChatRunnerConfig, AgentSession) 元组
 Raises:
 ValueError: provider 配置解析失败（API key 缺失等）
 """
 try:
 resolved = await ProviderConfigService.aresolve(
 conversation=conversation,
 project=conversation.project,
 )
 except ProviderConfigError as e:
 raise ValueError(str(e)) from e
 # Phase Plan：SettingKeys.ANTHROPIC_MODEL 硬删后走
 # ProviderCredential.default_model（通过 legacy helper 保证调用点最小变更）
 legacy = await aget_legacy_anthropic_config
 system_model = legacy["default_model"]
 model = conversation.model or system_model
 session_id = f"chat-{conversation.id}-{uuid.uuid4.hex[:8]}"
 project_name = conversation.project.name
 project_id = str(conversation.project_id)
 effective_project_context_line = project_context_line
 if effective_project_context_line is None:
 effective_project_context_line = f"当前空间：{project_name}"
 agent_session = await AgentSession.objects.acreate(
 session_id=session_id,
 project=conversation.project,
 user=None,
 status=AgentSession.Status.RUNNING,
 metadata={
 "conversation_id": str(conversation.id),
 "notification_user_id": notification_user_id or "",
 },
 )
 budget_str = await aget_setting_value(SettingKeys.MAX_BUDGET_USD)
 max_budget_usd = float(budget_str) if budget_str else None
 # Phase Task 7: _build_system_prompt 改为 async，调用处必须 await
 system_prompt = await _build_system_prompt(
 project_name, project_id, role=role, force_deep_analysis=force_deep_analysis,
 project_context_line=effective_project_context_line,
 )
 config = ChatRunnerConfig(
 system_prompt=system_prompt,
 model=model,
 space_id=project_id,
 session_id=session_id,
 provider_type=resolved.provider_type,
 conversation_id=str(conversation.id),
 api_key=resolved.api_key,
 api_base_url=resolved.base_url,
 # Phase：30 偏低，跨仓库追踪 / 大型 monorepo 场景容易撞顶。
 # 配合 ChatAnthropicRunner._ToolBudget 的去重 + 单文件硬上限 + 强制
 # final-turn fallback，50 轮足够覆盖绝大多数 chat 流，且单 LLM call
 # 成本可控。详见 agents/tool_budget.py 模块 docstring。
 max_turns=50,
 timeout_seconds=0,
 agent_session=agent_session,
 max_budget_usd=max_budget_usd,
 # 同时透传给 ChatAnthropicRunner，使 _get_tool_names 能据此闸门 deep_analysis 工具。
 # 历史上该开关只影响 system prompt，导致 LLM 即使在普通模式也能看到 deep_analysis。
 force_deep_analysis=force_deep_analysis,
 )
 return config, agent_session
