"""容器提问处理器（Phase, 增强于 Phase）。

负责：
1. 发送 Feishu 提问卡片
2. 接收用户回复后写入 answer.json 到共享卷
3. 创建和更新 InteractionLog 记录
4. 更新飞书卡片状态

Phase 增强：
- 支持代码片段和 diff 视图
- 集成 InteractionLog 记录
- 支持更新卡片为已回复状态
"""

import json
import os
from typing import Any

import structlog
from django.conf import settings
from django.utils import timezone

from feishu.cards.container_question_card import (
    build_container_answered_card,
    build_container_question_card,
)
from services.protocols import ANSWER_FILE
from subagent.models import InteractionLog, SubAgentSession

logger = structlog.get_logger()


# === 异步增强版函数 (Phase) ===


async def send_question_card_enhanced(
    session: SubAgentSession,
    question: str,
    options: list[str] | None = None,
    context: str = "",
    code_snippet: str = "",
    question_id: str = "",
) -> str | None:
    """发送增强版 Feishu 提问卡片（异步）。

    Args:
        session: SubAgentSession 实例
        question: 问题内容
        options: 可选的快捷选项
        context: 问题上下文
        code_snippet: 代码片段或 diff
        question_id: 问题唯一标识

    Returns:
        Feishu message_id，发送失败返回 None
    """
    from services.feishu_im import FeishuIMClient

    log = logger.bind(session_id=session.session_id, question_id=question_id)

    # 获取 chat_id
    chat_id = ""
    if session.main_session and session.main_session.metadata:
        chat_id = session.main_session.metadata.get("chat_id", "")

    if not chat_id:
        log.warning("question_no_chat_id")
        return None

    # 从 settings 获取飞书配置
    app_id = getattr(settings, "FEISHU_APP_ID", "")
    app_secret = getattr(settings, "FEISHU_APP_SECRET", "")

    if not app_id or not app_secret:
        log.warning("feishu_config_missing")
        return None

    # 构建增强版卡片
    card = build_container_question_card(
        question=question,
        options=options,
        session_id=session.session_id,
        context=context,
        code_snippet=code_snippet,
        question_id=question_id,
    )

    # 发送卡片并获取 message_id
    try:
        im_client = FeishuIMClient(app_id=app_id, app_secret=app_secret)
        message_id = await im_client.send_card(
            receive_id=chat_id,
            receive_id_type="chat_id",
            card=card,
        )
        log.info("question_card_sent", chat_id=chat_id, message_id=message_id)
        return message_id
    except Exception as e:
        log.error("question_card_send_failed", error=str(e))
        return None


async def handle_container_answer_enhanced(
    session_id: str,
    question_id: str,
    answer: str,
    answer_source: str = "text",
) -> bool:
    """处理容器提问的用户回复（增强版）。

    1. 查找 InteractionLog
    2. 更新回复内容和时间
    3. 写入 answer.json
    4. 更新飞书卡片状态

    Args:
        session_id: SubAgentSession.session_id
        question_id: 问题 ID
        answer: 用户回复
        answer_source: 回复来源 (button/text)

    Returns:
        True 处理成功
    """
    log = logger.bind(session_id=session_id, question_id=question_id)

    try:
        session = await SubAgentSession.objects.aget(session_id=session_id)
    except SubAgentSession.DoesNotExist:
        log.warning("answer_session_not_found")
        return False

    # 查找 InteractionLog
    interaction_log = await InteractionLog.objects.filter(
        session=session,
        question_id=question_id,
    ).afirst()

    if interaction_log:
        # 更新回复
        interaction_log.answer_text = answer
        interaction_log.answer_source = answer_source
        interaction_log.answered_at = timezone.now()
        await interaction_log.asave(update_fields=[
            "answer_text", "answer_source", "answered_at"
        ])
        log.info("interaction_log_updated")

        # 更新飞书卡片状态
        if interaction_log.feishu_message_id:
            await _update_card_to_answered(
                message_id=interaction_log.feishu_message_id,
                question=interaction_log.question_text,
                answer=answer,
                context=interaction_log.question_context,
            )
    else:
        log.warning("interaction_log_not_found")

    # 回答链路：优先直达容器 HTTP 服务，回退到共享卷 answer.json
    answer_sent = False
    answer_endpoint = ""
    if session.last_output and isinstance(session.last_output, dict):
        answer_endpoint = session.last_output.get("answer_endpoint", "")

    if answer_endpoint:
        answer_sent = await _send_answer_to_container(
            answer_endpoint, question_id, answer, log
        )

    if not answer_sent:
        write_answer_to_volume(session, answer)

    # 清除 pending_question
    if session.last_output and isinstance(session.last_output, dict):
        session.last_output.pop("pending_question", None)
        await session.asave(update_fields=["last_output", "updated_at"])

    log.info("container_answer_processed", answer_preview=answer[:50], via="http" if answer_sent else "volume")
    return True


async def _send_answer_to_container(
    answer_endpoint: str,
    question_id: str,
    answer: str,
    log: Any,
) -> bool:
    """通过 HTTP POST 直达容器内 HTTP 服务发送回答。"""
    import aiohttp

    try:
        async with aiohttp.ClientSession() as client:
            async with client.post(
                answer_endpoint,
                json={"question_id": question_id, "answer": answer},
                timeout=aiohttp.ClientTimeout(total=15),
            ) as resp:
                if resp.status == 200:
                    log.info("answer_sent_to_container", endpoint=answer_endpoint)
                    return True
                log.warning("answer_container_http_error", status=resp.status)
                return False
    except Exception as e:
        log.warning("answer_container_unreachable", endpoint=answer_endpoint, error=str(e))
        return False


async def _update_card_to_answered(
    message_id: str,
    question: str,
    answer: str,
    context: str = "",
) -> None:
    """更新飞书卡片为已回复状态。"""
    from services.feishu_im import FeishuIMClient

    log = logger.bind(message_id=message_id)

    # 从 settings 获取飞书配置
    app_id = getattr(settings, "FEISHU_APP_ID", "")
    app_secret = getattr(settings, "FEISHU_APP_SECRET", "")

    if not app_id or not app_secret:
        log.warning("feishu_config_missing")
        return

    card = build_container_answered_card(
        question=question,
        answer=answer,
        context=context,
    )

    try:
        im_client = FeishuIMClient(app_id=app_id, app_secret=app_secret)
        await im_client.update_card(message_id=message_id, card=card)
        log.info("card_updated_to_answered")
    except Exception as e:
        log.warning("card_update_failed", error=str(e))


def write_answer_to_volume(session: SubAgentSession, answer: str) -> bool:
    """将用户回复写入容器共享卷的 answer.json。

    路径: server/data/transfers/{session_id}/.friday/answer.json

    Args:
        session: SubAgentSession 实例
        answer: 用户回复内容

    Returns:
        True 写入成功，False 写入失败
    """
    log = logger.bind(session_id=session.session_id)

    transfers_dir = os.path.join(settings.BASE_DIR, "data", "transfers")
    protocol_dir = os.path.join(transfers_dir, session.session_id, ".friday")
    answer_path = os.path.join(protocol_dir, ANSWER_FILE)

    # 从 last_output 获取问题 ID（如果有）
    question_id = ""
    if session.last_output and isinstance(session.last_output, dict):
        pending = session.last_output.get("pending_question", {})
        question_id = pending.get("question_id", "")

    answer_data = {
        "question_id": question_id,
        "answer": answer,
        "answered_at": timezone.now().isoformat(),
    }

    try:
        os.makedirs(protocol_dir, exist_ok=True)
        with open(answer_path, "w", encoding="utf-8") as f:
            json.dump(answer_data, f, ensure_ascii=False, indent=2)
        log.info("answer_written", path=answer_path)
        return True
    except OSError as e:
        log.error("answer_write_failed", path=answer_path, error=str(e))
        return False
