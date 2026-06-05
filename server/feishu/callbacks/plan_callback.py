"""Plan card callback handler for Feishu interactive card actions.

Handles approve/revise/feedback callbacks from plan review cards,
resuming the agent session with the user's response.
"""

import json
from typing import Any

import structlog

from feishu.cards.plan_card import (
    build_plan_approved_card,
    build_plan_feedback_card,
    build_plan_revising_card,
)
from feishu.views import CardCallback, register_card_callback
from tasks.agent_tasks import schedule_resume_agent_session

logger = structlog.get_logger(__name__)


@register_card_callback("plan_approve")
def handle_plan_approve(callback: CardCallback) -> dict[str, Any] | None:
    """Handle plan approval button click.

    Resumes agent session with approve action and returns
    a green "confirmed" card replacing the interactive one.
    """
    session_id = _extract_session_id(callback)
    if not session_id:
        return None

    logger.info("plan_approved", session_id=session_id)

    user_response = json.dumps({"action": "approve", "message": "用户确认方案"})
    schedule_resume_agent_session(session_id, user_response)

    return build_plan_approved_card(
        plan_summary="",
        document_url="",
        iteration=1,
    )


@register_card_callback("plan_revise")
def handle_plan_revise(callback: CardCallback) -> dict[str, Any] | None:
    """Handle plan revision button click.

    Resumes agent session with revise action and returns
    an orange "revising" card.
    """
    session_id = _extract_session_id(callback)
    if not session_id:
        return None

    logger.info("plan_revision_requested", session_id=session_id)

    user_response = json.dumps({"action": "revise", "message": "用户请求修改"})
    schedule_resume_agent_session(session_id, user_response)

    return build_plan_revising_card(
        plan_summary="",
        document_url="",
        iteration=1,
    )


@register_card_callback("plan_feedback")
def handle_plan_feedback(callback: CardCallback) -> dict[str, Any] | None:
    """Handle plan feedback form submission.

    Extracts user's text feedback from the form, resumes agent session
    with feedback action, and returns a "feedback received" card.
    """
    session_id = _extract_session_id(callback)
    if not session_id:
        return None

    # Extract feedback text from form submission
    feedback_text = _extract_feedback_text(callback)
    if not feedback_text:
        logger.warning("plan_feedback_empty", session_id=session_id)
        return None

    logger.info(
        "plan_feedback_received",
        session_id=session_id,
        feedback_preview=feedback_text[:50],
    )

    user_response = json.dumps({"action": "feedback", "message": feedback_text})
    schedule_resume_agent_session(session_id, user_response)

    return build_plan_feedback_card(
        plan_summary="",
        document_url="",
        feedback=feedback_text,
        iteration=1,
    )


def _extract_session_id(callback: CardCallback) -> str:
    """Extract session_id from callback action_value.

    The action_value may be a dict (parsed by CardCallbackView) or a string.
    """
    action_value = callback.action_value
    if isinstance(action_value, dict):
        session_id: str = action_value.get("session_id", "")
    elif isinstance(action_value, str):
        try:
            data = json.loads(action_value)
            session_id = data.get("session_id", "") if isinstance(data, dict) else ""
        except json.JSONDecodeError:
            session_id = ""
    else:
        session_id = ""

    if not session_id:
        logger.warning(
            "plan_callback_missing_session_id",
            action_value=str(action_value)[:100],
        )

    return session_id


def _extract_feedback_text(callback: CardCallback) -> str:
    """Extract feedback text from form submission callback.

    Form values are typically in action_value or a separate form_value field.
    The exact structure depends on Feishu card callback format.
    """
    action_value = callback.action_value
    if isinstance(action_value, dict):
        # Check for form input value
        feedback: str = action_value.get("feedback_input", "")
        if not feedback:
            # Fallback: check nested form_value
            form_value = action_value.get("form_value", {})
            if isinstance(form_value, dict):
                feedback = form_value.get("feedback_input", "")
        return feedback

    return ""
