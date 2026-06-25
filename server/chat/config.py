"""Chat 运行配置构建。"""

from __future__ import annotations

import uuid

from agents.chat_runner import ChatRunnerConfig
from agents.models import AgentSession
from chat.conversation_service import _build_system_prompt
from chat.models import Conversation
from chat.services import aget_setting_value
from services.model_capabilities import ModelCapabilities
from services.provider_config import (
    ProviderConfigError,
    ProviderConfigService,
    _fetch_credential_by_id,
    aget_legacy_anthropic_config,
)
from system.models import SettingKeys

# 无空间对话的上下文指引：替代「当前空间：xxx」行。
# 关键行为契约：检测到任务依赖空间知识时必须引导用户先选择空间，而不是凭空作答。
_NO_SPACE_CONTEXT_LINE = (
    "当前对话未绑定任何空间：你无法访问代码库、仓库结构或空间内的文档/知识，"
    "所有空间检索与编码工具均不可用。\n"
    "如果用户的问题需要查阅具体代码、仓库、空间文档等空间相关知识，"
    "请明确告知用户：本对话未绑定空间，需要在页面右上角选择一个空间后再新建对话提问；"
    "若尚未创建空间，请先到「空间」页面创建。\n"
    "与空间无关的通用问题（编程概念、方案讨论、写作等）可以直接回答。"
)


async def _maybe_pack_project_context(conversation: Conversation) -> str:
    """会话绑定项目聚合根时打包项目上下文（RECALL-02/03，fail-closed + best-effort）。

    - 无绑定项目 / 无会话 owner → 返回空串（无法判定成员，fail-closed）。
    - 非项目成员 → packer 内部 fail-closed 返回空（零召回零泄漏）。
    - 任何异常 best-effort 吞掉返回空串，绝不阻断 chat 主流程。
    """
    project_id = getattr(conversation, "bound_project_id", None)
    user_id = getattr(conversation, "created_by_id", None)
    if not project_id or not user_id:
        return ""
    try:
        from django.contrib.auth import get_user_model

        from initiatives.models import Project
        from services.project_context_packer import pack_project_context

        project = await Project.objects.select_related("space").filter(pk=project_id).afirst()
        if project is None:
            return ""
        user_model = get_user_model()
        user = await user_model.objects.filter(pk=user_id).afirst()
        if user is None:
            return ""
        packed = await pack_project_context(
            project, user, conversation_id=str(conversation.id)
        )
        return packed.text
    except Exception:  # noqa: BLE001 — 项目上下文注入 best-effort，绝不反噬 chat
        return ""


async def build_sdk_config(
    conversation: Conversation,
    role: str = "developer",
    notification_user_id: str | None = None,
    force_deep_analysis: bool = False,
    project_context_line: str | None = None,
) -> tuple[ChatRunnerConfig, AgentSession]:
    """从 Conversation 实例构建 ChatRunnerConfig 和 AgentSession。

    提取自 ConversationService.send_message_stream() 的配置构建段，
    将散落在 40+ 行中的 API key 解析、model 解析、session 创建等逻辑
    收敛为单一函数。调用方需确保 conversation 已 select_related("space")。

    Returns:
        (ChatRunnerConfig, AgentSession) 元组

    Raises:
        ValueError: provider 配置解析失败（API key 缺失等）
    """
    try:
        resolved = await ProviderConfigService.aresolve(
            conversation=conversation,
            project=conversation.space,
        )
    except ProviderConfigError as e:
        raise ValueError(str(e)) from e

    # implementation（contract/contract）：SettingKeys.ANTHROPIC_MODEL 硬删后走
    # ProviderCredential.default_model（通过 legacy helper 保证调用点最小变更）
    legacy = await aget_legacy_anthropic_config()
    system_model = legacy["default_model"]
    model = conversation.model or system_model

    # 凭证级能力解析：用户在凭证模型条目上配置的 context_length 优先于
    # 静态 fixture（ModelCapabilities），未配置时 resolver 内部回退 fixture。
    credential = None
    if resolved.credential_id is not None:
        credential = await _fetch_credential_by_id(resolved.credential_id)
    capabilities = ModelCapabilities.resolve_for_credential(
        credential, str(resolved.provider_type), model
    )

    session_id = f"chat-{conversation.id}-{uuid.uuid4().hex[:8]}"
    # 无空间对话：project 可空。space_id 传空串 → chat_runner 不注入任何
    # 空间工具；context line 引导 LLM 在任务涉及空间知识时要求用户先选空间。
    has_project = conversation.space_id is not None
    project_name = conversation.space.name if has_project else ""
    project_id = str(conversation.space_id) if has_project else ""
    effective_project_context_line = project_context_line
    if effective_project_context_line is None:
        if has_project:
            effective_project_context_line = f"当前空间：{project_name}"
        else:
            effective_project_context_line = _NO_SPACE_CONTEXT_LINE

    agent_session = await AgentSession.objects.acreate(
        session_id=session_id,
        space=conversation.space,
        user=None,
        status=AgentSession.Status.RUNNING,
        metadata={
            "conversation_id": str(conversation.id),
            "notification_user_id": notification_user_id or "",
        },
    )

    budget_str = await aget_setting_value(SettingKeys.MAX_BUDGET_USD)
    max_budget_usd = float(budget_str) if budget_str else None

    # implementation Task 7: _build_system_prompt 改为 async，调用处必须 await
    system_prompt = await _build_system_prompt(
        project_name, project_id, role=role, force_deep_analysis=force_deep_analysis,
        project_context_line=effective_project_context_line,
    )

    # RECALL-02（v0.15.0 Phase 80）：会话绑定项目聚合根时，经 context packer 自动加载项目
    # 完整上下文（需求/工件/记忆/关联知识），按成员权限 fail-closed（非成员零注入）。
    project_context = await _maybe_pack_project_context(conversation)
    if project_context:
        system_prompt = f"{system_prompt}\n\n{project_context}"

    config = ChatRunnerConfig(
        system_prompt=system_prompt,
        model=model,
        space_id=project_id,
        session_id=session_id,
        provider_type=resolved.provider_type,
        conversation_id=str(conversation.id),
        api_key=resolved.api_key,
        api_base_url=resolved.base_url,
        # CONC-02：凭证级 LLM 并发限流入参（astream 前按凭证申请槽位）
        credential_id=resolved.credential_id,
        max_concurrency=resolved.max_concurrency,
        # Phase P15：30 偏低，跨仓库追踪 / 大型 monorepo 场景容易撞顶。
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
        # 凭证级上下文窗口（含用户配置的 context_length override）
        max_input_tokens=capabilities.max_input_tokens,
        # 凭证绑定模型清单：让 runner 的图片块能力门控与发送入口
        # （send_message_stream 的 ensure_image_input_supported）判定一致，
        # 避免全局推断误判已配置 vision 的自定义模型。
        available_models=getattr(credential, "available_models", None),
    )

    return config, agent_session
