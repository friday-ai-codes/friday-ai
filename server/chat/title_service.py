"""异步对话标题自动生成服务。

首条 AI 回复完成后 fire-and-forget 调用，
使用小模型生成简短中文标题。

implementation contract（implementation plan）：调用链从旧 Anthropic SDK 直调迁至
``agents.llm_factory.build_chat_model(resolved).ainvoke(...)`` 统一 seam 层。
原因 / 收益：
- 与 LangChainAgentRunner / AIAgentBaseNode 共享同一工厂入口，Provider 切换零改动
- 测试 mock 点从旧 SDK 客户端收敛到 ``build_chat_model`` 单点
- 凭证解析走 ``ProviderConfigService.aresolve_or_error``（contract Result 模式），
  四层优先级 + SystemSetting 兼容降级自理
- rendered_prompt 继续通过 ``HumanMessage(content=...)`` 单路径透传，work item
  字节级 hash 等价契约不变
"""

from __future__ import annotations

from typing import Final

import structlog
from langchain_core.messages import HumanMessage

from agents.llm_factory import build_chat_model
from chat.models import Conversation, Message
from prompts.keys import PromptSlugs
from prompts.services import render_prompt
from services.provider_config import (
    ProviderConfigService,
    ProviderMissingError,
    ProviderType,
    aget_legacy_anthropic_config,
)

logger = structlog.get_logger(__name__)

# 标题生成使用系统配置的默认模型（与对话模型一致）
TITLE_MODEL_FALLBACK: Final[str] = "claude-sonnet-4-20250514"

# implementation contract: 占位符 {user_message} → {{user_message}}（Jinja2 语法对齐）
TITLE_PROMPT: Final[str] = (
    "根据以下用户消息，生成一个简短的中文对话标题（10字以内），"
    "描述用户的核心意图。只输出标题文字，不要引号、标点或解释。\n\n"
    "用户消息：{{user_message}}"
)


async def should_generate_title(conversation_id: str) -> bool:
    """检查是否应该生成标题（仅首条消息时触发）。

    Args:
        conversation_id: 对话 UUID

    Returns:
        True if conversation has exactly 1 user message (first message)
    """
    user_msg_count = await Message.objects.filter(
        conversation_id=conversation_id,
        role=Message.Role.USER,
    ).acount()
    return user_msg_count == 1


async def generate_title(
    conversation_id: str,
    user_message: str,
) -> str | None:
    """异步生成对话标题并更新到数据库。

    使用 ``build_chat_model(resolved).ainvoke(...)`` 统一 seam 层生成简短中文标题，
    失败时静默处理。此函数设计为 fire-and-forget 调用。

    Args:
        conversation_id: 对话 UUID
        user_message: 用户首条消息内容

    Returns:
        生成的标题字符串，失败时返回 None
    """
    try:
        # implementation contract：走 ProviderConfigService.aresolve_or_error（contract Result 模式）
        # 四层优先级（node/conversation/project/system）+ SystemSetting 兼容降级自理
        resolved = await ProviderConfigService.aresolve_or_error()
        if isinstance(resolved, ProviderMissingError):
            logger.warning(
                "title_generation_skipped",
                reason="no_credential",
                missing_provider=resolved.missing_provider,
            )
            return None

        # title_service 场景强制走 Anthropic 小模型；若 resolve 结果非 Anthropic，走 fallback
        if resolved.provider_type != ProviderType.ANTHROPIC:
            logger.warning(
                "title_generation_skipped",
                reason="non_anthropic_provider",
                provider_type=str(resolved.provider_type),
            )
            return None

        # implementation（contract/contract）：SettingKeys.ANTHROPIC_MODEL 硬删后走
        # ProviderCredential.default_model，回退到轻量默认值
        legacy = await aget_legacy_anthropic_config()
        model = legacy["default_model"] or TITLE_MODEL_FALLBACK

        # 走 Prompt Center 渲染，fallback 保留原常量（contract 双轨）
        # rendered_prompt 字节级 hash 等价契约不变（work item implementation 会再验一次）
        rendered_prompt = await render_prompt(
            PromptSlugs.AUX_TITLE_GENERATION,
            project_id=None,  # title_service 无空间上下文（contract）
            variables={"user_message": user_message[:500]},
            fallback=TITLE_PROMPT,
        )

        # implementation contract：build_chat_model seam + 单 turn ainvoke（非 streaming）
        # max_output_tokens 不能太小：推理（reasoning）模型（如 mimo-v2.5-pro）会先产出
        # reasoning 块再输出正文，50 token 会被思考过程全部吃掉（stop_reason=max_tokens）
        # 导致没有 text 块、标题恒为空。给到 1024 让 reasoning 后仍有余量产出标题文字。
        chat_model = build_chat_model(
            resolved,
            model,
            max_output_tokens=1024,
            streaming=False,
        )
        ai_msg = await chat_model.ainvoke([HumanMessage(content=rendered_prompt)])

        # ai_msg.content 可能是 str 或 content_blocks 列表；统一转 str 后 strip
        content = ai_msg.content
        if isinstance(content, list):
            # content_blocks 列表 → 拼接首个 text block
            text_parts: list[str] = []
            for block in content:
                if isinstance(block, dict) and block.get("type") == "text":
                    text_parts.append(str(block.get("text", "")))
            title_raw = "".join(text_parts)
        else:
            title_raw = str(content) if content else ""

        title = title_raw.strip()[:200]

        if not title:
            logger.warning("title_generation_empty", conversation_id=conversation_id)
            return None

        # 更新数据库
        await Conversation.objects.filter(id=conversation_id).aupdate(title=title)

        logger.info(
            "title_generated",
            conversation_id=conversation_id,
            title=title,
        )
        return title

    except Exception:
        logger.exception(
            "title_generation_failed",
            conversation_id=conversation_id,
        )
        return None
