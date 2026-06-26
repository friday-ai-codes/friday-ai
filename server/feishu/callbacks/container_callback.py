"""容器提问卡片回调处理器。

用户在飞书卡片上点击选项按钮或提交文本后，
立即返回已回复状态的灰色卡片，并异步处理回复写入。
"""

import json
from typing import Any

import structlog

from feishu.cards.container_question_card import build_container_answered_card
from feishu.views import CardCallback, register_card_callback

logger = structlog.get_logger()


@register_card_callback("container_answer")
async def handle_container_answer(callback: CardCallback) -> dict[str, Any] | None:
    """处理容器提问卡片的用户回复。

    按钮点击: action_value 包含 answer 字段
    表单提交: action_value 包含 custom_answer 字段
    """
    action_data = callback.action_value
    if isinstance(action_data, str):
        try:
            action_data = json.loads(action_data)
        except json.JSONDecodeError:
            action_data = {}

    if not isinstance(action_data, dict):
        return None

    session_id = action_data.get("session_id", "")
    question_id = action_data.get("question_id", "")
    answer = action_data.get("answer", "") or action_data.get("custom_answer", "")

    if not session_id or not answer:
        logger.warning(
            "container_answer_missing_data",
            session_id=session_id,
            has_answer=bool(answer),
        )
        return None

    logger.info(
        "container_answer_received",
        session_id=session_id,
        question_id=question_id,
        answer_preview=answer[:50],
    )

    # 异步处理回复（写入 answer.json、更新 InteractionLog 等）
    from subagent.question_handler import handle_container_answer_enhanced

    answer_source = "button" if action_data.get("answer") else "text"
    await handle_container_answer_enhanced(
        session_id=session_id,
        question_id=question_id,
        answer=answer,
        answer_source=answer_source,
    )

    # PLAN-03：取消 5min 挂起计时 + （仅挂起态）经 SessionStore resume 续跑容器。
    # 后台线程处理（飞书回调须 3s 内响应）+ bind_task_context 归因；全段 fail-soft
    # 绝不反噬回调（未挂起则 no-op，答复已由上方 answer.json/HTTP 直达活容器）。
    try:
        from chat.container_suspend_service import schedule_container_resume

        schedule_container_resume(
            session_id=session_id,
            user_reply=answer,
            responder_id=callback.user_open_id,
        )
    except Exception as exc:  # noqa: BLE001 — resume 调度 best-effort，绝不反噬回调
        logger.warning(
            "container_resume_schedule_failed",
            session_id=session_id,
            error_type=type(exc).__name__,
        )

    # 立即返回灰色已回复卡片
    return build_container_answered_card(
        question="",
        answer=answer,
    )
