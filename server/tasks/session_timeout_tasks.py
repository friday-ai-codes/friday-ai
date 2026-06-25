"""Session timeout handling tasks.

Provides periodic tasks for:
- Sending timeout reminders for sessions suspended > 22 hours
- Cleaning up sessions suspended > 30 days
"""

from datetime import timedelta
from typing import Any

import structlog
from django.utils import timezone

from agents.models import AgentSession
from agents.tools.feishu_im_tools import create_feishu_im_client_for_project
from services.feishu_im import CardTemplate

logger = structlog.get_logger(__name__)

# Configuration constants
TIMEOUT_HOURS = 24
REMINDER_HOURS = 22  # Reminder sent 2 hours before timeout
CLEANUP_DAYS = 30


def _build_timeout_reminder_card(
    question: str,
    hours_remaining: int,
    session_id: str,
) -> dict[str, Any]:
    """Build orange-themed timeout reminder card.

    Args:
        question: The pending question text
        hours_remaining: Hours until timeout
        session_id: Session ID for callback matching

    Returns:
        Card JSON structure
    """
    card = CardTemplate(
        title="Friday - 问题即将超时",
        content=(
            f"**您有一个问题等待回复，将在 {hours_remaining} 小时后超时**\n\n"
            f"---\n\n"
            f"**问题内容：**\n{question}\n\n"
            f"请尽快回复以继续任务执行。"
        ),
        color="orange",
        buttons=[
            {
                "text": "查看详情",
                "value": f"view_session:{session_id}",
                "type": "primary",
            }
        ],
    )
    return card.to_card_json()


async def check_timeout_reminders() -> dict[str, Any]:
    """Check for sessions needing timeout reminders.

    Finds sessions that:
    - Are in SUSPENDED status
    - Have been suspended for > 22 hours but < 24 hours
    - Have not already received a reminder

    Sends orange-themed reminder cards to the associated chat.

    Returns:
        Dict with count of reminders sent and any errors
    """
    log = logger.bind(task="check_timeout_reminders")
    log.info("task_start")

    now = timezone.now()
    reminder_cutoff = now - timedelta(hours=REMINDER_HOURS)
    timeout_cutoff = now - timedelta(hours=TIMEOUT_HOURS)

    # Calculate hours remaining for reminder message
    hours_remaining = TIMEOUT_HOURS - REMINDER_HOURS

    sent_count = 0
    error_count = 0
    errors: list[str] = []

    # Query sessions needing reminders
    # Using async iterator for memory efficiency
    sessions = AgentSession.objects.filter(
        status=AgentSession.Status.SUSPENDED,
        suspended_at__lt=reminder_cutoff,
        suspended_at__gte=timeout_cutoff,
    ).select_related("space")

    async for session in sessions.aiterator():
        session_log = log.bind(session_id=session.session_id)

        # Check if reminder already sent
        temp_data = session.temp_data or {}
        if temp_data.get("reminder_sent"):
            session_log.debug("reminder_already_sent")
            continue

        try:
            # Get chat_id from temp_data (stored when question was sent)
            chat_id = temp_data.get("chat_id")
            if not chat_id:
                session_log.warning("no_chat_id_in_temp_data")
                continue

            # Get project credentials for Feishu client
            project = session.space
            if project is None:
                session_log.warning("no_project_in_session")
                continue
            try:
                client = await create_feishu_im_client_for_project(project)
            except ValueError:
                session_log.warning("missing_feishu_credentials")
                continue

            # Get current question from temp_data
            current_question = temp_data.get("current_question", "")
            if not current_question:
                # Try to get from last question in history
                history = temp_data.get("question_history", [])
                if history:
                    current_question = history[-1].get("question", "待回复的问题")
                else:
                    current_question = "待回复的问题"

            # Build and send reminder card
            card = _build_timeout_reminder_card(
                question=current_question,
                hours_remaining=hours_remaining,
                session_id=session.session_id,
            )

            await client.send_card(
                receive_id=chat_id,
                receive_id_type="chat_id",
                card=card,
            )

            # Mark reminder as sent
            temp_data["reminder_sent"] = True
            session.temp_data = temp_data
            await session.asave(update_fields=["temp_data"])

            sent_count += 1
            session_log.info("reminder_sent")

        except Exception as e:
            error_count += 1
            errors.append(f"{session.session_id}: {e!s}")
            session_log.exception("reminder_send_error", error=str(e))

    log.info(
        "task_complete",
        sent_count=sent_count,
        error_count=error_count,
    )

    return {
        "sent_count": sent_count,
        "error_count": error_count,
        "errors": errors,
    }


async def cleanup_expired_sessions() -> dict[str, Any]:
    """Clean up sessions that have been suspended too long.

    Finds sessions that:
    - Are in SUSPENDED status
    - Have been suspended for > 30 days

    Marks them as ERROR with appropriate message.

    Returns:
        Dict with count of cleaned sessions
    """
    log = logger.bind(task="cleanup_expired_sessions")
    log.info("task_start")

    now = timezone.now()
    cleanup_cutoff = now - timedelta(days=CLEANUP_DAYS)

    # Batch update expired sessions
    updated = await AgentSession.objects.filter(
        status=AgentSession.Status.SUSPENDED,
        suspended_at__lt=cleanup_cutoff,
    ).aupdate(
        status=AgentSession.Status.ERROR,
        error_message=f"会话因超过 {CLEANUP_DAYS} 天未回复而被取消",
    )

    log.info("task_complete", cleaned_count=updated)

    return {
        "cleaned_count": updated,
    }
