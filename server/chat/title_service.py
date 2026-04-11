"""异步对话标题自动生成服务。
首条 AI 回复完成后 fire-and-forget 调用，
使用小模型生成简短中文标题。
"""
from __future__ import annotations
from typing import Final
import anthropic
import structlog
from chat.models import Conversation, Message
from chat.services import aget_setting_value
from prompts.keys import PromptSlugs
from prompts.services import render_prompt
from system.models import SettingKeys
logger = structlog.get_logger(__name__)
# 标题生成使用系统配置的默认模型（与对话模型一致）
TITLE_MODEL_FALLBACK: Final[str] = "claude-sonnet-4-20250514"
# Phase: 占位符 {user_message} → {{user_message}}（Jinja2 语法对齐）
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
 ).acount
 return user_msg_count == 1
async def generate_title(
 conversation_id: str,
 user_message: str,
) -> str | None:
 """异步生成对话标题并更新到数据库。
 使用 anthropic.AsyncAnthropic 直接调用 API 生成简短中文标题，
 失败时静默处理。此函数设计为 fire-and-forget 调用。
 Args:
 conversation_id: 对话 UUID
 user_message: 用户首条消息内容
 Returns:
 生成的标题字符串，失败时返回 None
 """
 try:
 # 获取 API 配置
 api_key = await aget_setting_value(SettingKeys.ANTHROPIC_API_KEY)
 base_url = await aget_setting_value(SettingKeys.ANTHROPIC_BASE_URL)
 if not api_key:
 logger.warning("title_generation_skipped", reason="no_api_key")
 return None
 # 使用系统配置的模型，回退到轻量默认值
 model = await aget_setting_value(SettingKeys.ANTHROPIC_MODEL) or TITLE_MODEL_FALLBACK
 # 直接使用 Anthropic SDK 调用
 client_kwargs: dict[str, str] = {"api_key": api_key}
 if base_url:
 client_kwargs["base_url"] = base_url
 client = anthropic.AsyncAnthropic(**client_kwargs)
 # Phase: 走 Prompt Center 渲染，fallback 保留原常量（ 双轨）
 rendered_prompt = await render_prompt(
 PromptSlugs.AUX_TITLE_GENERATION,
 project_id=None, # title_service 无项目上下文
 variables={"user_message": user_message[:500]},
 fallback=TITLE_PROMPT,
 )
 response = await client.messages.create(
 model=model,
 max_tokens=50,
 messages=[{
 "role": "user",
 "content": rendered_prompt,
 }],
 )
 # 确保首个内容块是文本块
 first_content = response.content[0]
 if hasattr(first_content, 'text'):
 title = first_content.text.strip[:200]
 else:
 logger.warning("title_generation_non_text_content", conversation_id=conversation_id)
 return None
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
