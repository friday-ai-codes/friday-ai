"""User interaction tools for the Agent.

Provides tools for asking users questions and waiting for responses.
Uses Feishu interactive cards for rich interaction experience.
"""

import structlog

from agents.models import AgentSession
from agents.tools.base import ToolResult, tool
from agents.tools.feishu_im_tools import create_feishu_im_client_for_project
from feishu.cards.question_card import build_question_card

logger = structlog.get_logger(__name__)


@tool(
    name="ask_user_question",
    description="向用户提问并等待回复。Agent 会暂停执行直到用户回复。",
    category="GENERAL",
    parameters={
        "type": "object",
        "properties": {
            "question": {
                "type": "string",
                "description": "要问用户的问题",
            },
            "options": {
                "type": "array",
                "items": {"type": "string"},
                "description": "可选的选项列表，用户可以点击选择",
            },
            "session_id": {
                "type": "string",
                "description": "Agent 会话 ID（由系统自动提供）",
            },
        },
        "required": ["question", "session_id"],
    },
    requires_suspension=True,
)
async def ask_user_question(
    question: str,
    session_id: str,
    options: list[str] | None = None,
) -> ToolResult:
    """Ask the user a question and suspend waiting for response.

    Sends an interactive Feishu card message with the question,
    optional selection buttons, and a text input form.
    The agent will suspend until the user responds via the card.

    Args:
        question: The question to ask the user
        session_id: Agent session ID for callback matching
        options: Optional list of quick-select options

    Returns:
        ToolResult with suspension metadata
    """
    log = logger.bind(session_id=session_id, question=question[:50])

    # Load session
    try:
        session = await AgentSession.objects.select_related("space").aget(
            session_id=session_id
        )
    except AgentSession.DoesNotExist:
        log.error("session_not_found")
        return ToolResult(
            success=False,
            error=f"会话不存在: {session_id}",
        )

    project = session.space
    if project is None:
        log.error("project_not_set")
        return ToolResult(
            success=False,
            error="会话未关联项目",
        )

    # Get question history and message_id from temp_data
    temp_data = session.temp_data or {}
    history: list[dict[str, str]] = temp_data.get("question_history", [])
    message_id: str | None = temp_data.get("question_message_id")
    chat_id: str | None = temp_data.get("chat_id")

    if not chat_id:
        log.error("chat_id_missing")
        return ToolResult(
            success=False,
            error="无法发送问题：缺少 chat_id，请确保会话已正确配置",
        )

    # Build question card
    card = build_question_card(
        question=question,
        options=options,
        session_id=session_id,
        history=history,
    )

    # Create IM client
    try:
        client = await create_feishu_im_client_for_project(project)
    except ValueError as e:
        log.error("feishu_im_not_configured", error=str(e))
        return ToolResult(
            success=False,
            error=str(e),
        )

    # Send or update card
    try:
        if message_id:
            # Multi-turn: update existing card
            success = await client.update_card(message_id, card)
            if not success:
                # Update failed, send new card
                log.warning("card_update_failed_sending_new")
                message_id = await client.send_card(
                    receive_id=chat_id,
                    receive_id_type="chat_id",
                    card=card,
                )
        else:
            # First question: send new card
            message_id = await client.send_card(
                receive_id=chat_id,
                receive_id_type="chat_id",
                card=card,
            )

        log.info("question_card_sent", message_id=message_id)

    except Exception as e:
        log.error("send_question_card_failed", error=str(e))
        return ToolResult(
            success=False,
            error=f"发送问题卡片失败: {e}",
        )

    # Update temp_data with message_id and current question
    session.temp_data["question_message_id"] = message_id
    session.temp_data["current_question"] = question
    await session.asave(update_fields=["temp_data"])

    return ToolResult(
        success=True,
        output={
            "question": question,
            "message_id": message_id,
            "awaiting_response": True,
        },
        metadata={
            "suspension": True,
            "suspension_reason": "user_question",
            "message_id": message_id,
        },
    )
