"""Chat 运行配置构建。"""
from __future__ import annotations
import uuid
from agents.chat_runner import ChatRunnerConfig
from agents.models import AgentSession
from chat.conversation_service import _build_system_prompt
from chat.models import Conversation
from chat.services import aget_setting_value
from services.provider_config import ProviderConfigError, ProviderConfigService
from system.models import SettingKeys
async def build_sdk_config(
 conversation: Conversation,
 role: str = "developer",
 notification_user_id: str | None = None,
 force_deep_analysis: bool = False,
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
 system_model = await aget_setting_value(SettingKeys.ANTHROPIC_MODEL) or ""
 model = conversation.model or system_model
 session_id = f"chat-{conversation.id}-{uuid.uuid4.hex[:8]}"
 project_name = conversation.project.name
 project_id = str(conversation.project_id)
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
 )
 config = ChatRunnerConfig(
 system_prompt=system_prompt,
 model=model,
 project_id=project_id,
 session_id=session_id,
 conversation_id=str(conversation.id),
 api_key=resolved.api_key,
 api_base_url=resolved.base_url,
 max_turns=30,
 timeout_seconds=0,
 agent_session=agent_session,
 max_budget_usd=max_budget_usd,
 )
 return config, agent_session
