"""send_plan_card tool - sends technical plan summary to Feishu chat.

Builds and sends/updates an interactive card with plan summary, document link,
approve/revise buttons, and feedback input. Supports multi-round iteration
by updating the same card message.
"""

import structlog

from agents.models import AgentSession
from agents.tools.base import ToolResult, tool
from agents.tools.feishu_im_tools import create_feishu_im_client_for_project
from feishu.cards.plan_card import build_plan_card

logger = structlog.get_logger(__name__)


@tool(
    name="send_plan_card",
    description="将技术方案摘要发送到飞书群，附带飞书文档链接和确认/修改按钮。支持多轮迭代更新同一张卡片。",
    category="GENERAL",
    parameters={
        "type": "object",
        "properties": {
            "session_id": {
                "type": "string",
                "description": "Agent 会话 ID（由系统自动提供）",
            },
            "plan_summary": {
                "type": "string",
                "description": "方案摘要（任务数、仓库分配概览，建议 work-item 字）",
            },
            "document_url": {
                "type": "string",
                "description": "飞书文档链接（完整方案）",
            },
            "iteration": {
                "type": "integer",
                "description": "当前迭代轮次，默认 1",
            },
            "iteration_history": {
                "type": "array",
                "items": {"type": "string"},
                "description": "迭代历史摘要，如 ['v1: 初始方案', 'v2: 增加缓存策略']",
            },
        },
        "required": ["session_id", "plan_summary", "document_url"],
    },
    requires_suspension=True,
)
async def send_plan_card(
    session_id: str,
    plan_summary: str,
    document_url: str,
    iteration: int = 1,
    iteration_history: list[str] | None = None,
) -> ToolResult:
    """Send a plan review card to Feishu and suspend waiting for user response.

    Builds an interactive card with plan summary, document link, and
    approve/revise buttons. On subsequent iterations, updates the existing
    card instead of sending a new one.

    Args:
        session_id: Agent session ID for callback matching
        plan_summary: Brief plan summary text
        document_url: URL to full plan document on Feishu
        iteration: Current iteration number (1-based)
        iteration_history: List of previous iteration summaries

    Returns:
        ToolResult with suspension metadata
    """
    log = logger.bind(session_id=session_id, iteration=iteration)

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

    # Get chat_id and existing message_id from temp_data
    temp_data = session.temp_data or {}
    chat_id: str | None = temp_data.get("chat_id")
    message_id: str | None = temp_data.get("plan_card_message_id")

    if not chat_id:
        log.error("chat_id_missing")
        return ToolResult(
            success=False,
            error="无法发送方案卡片：缺少 chat_id，请确保会话已正确配置",
        )

    # Build plan card
    card = build_plan_card(
        plan_summary=plan_summary,
        document_url=document_url,
        session_id=session_id,
        iteration=iteration,
        iteration_history=iteration_history,
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
            # Multi-round: update existing card
            success = await client.update_card(message_id, card)
            if not success:
                # Update failed, send new card
                log.warning("plan_card_update_failed_sending_new")
                message_id = await client.send_card(
                    receive_id=chat_id,
                    receive_id_type="chat_id",
                    card=card,
                )
        else:
            # First iteration: send new card
            message_id = await client.send_card(
                receive_id=chat_id,
                receive_id_type="chat_id",
                card=card,
            )

        log.info("plan_card_sent", message_id=message_id, iteration=iteration)

    except Exception as e:
        log.error("send_plan_card_failed", error=str(e))
        return ToolResult(
            success=False,
            error=f"发送方案卡片失败: {e}",
        )

    # Save message_id and plan context to temp_data for callback handler
    session.temp_data["plan_card_message_id"] = message_id
    session.temp_data["plan_summary"] = plan_summary
    session.temp_data["plan_document_url"] = document_url
    session.temp_data["plan_iteration"] = iteration
    await session.asave(update_fields=["temp_data"])

    return ToolResult(
        success=True,
        output={
            "plan_summary": plan_summary,
            "document_url": document_url,
            "message_id": message_id,
            "iteration": iteration,
            "awaiting_response": True,
        },
        metadata={
            "suspension": True,
            "suspension_reason": "plan_review",
            "message_id": message_id,
        },
    )
