"""Plan card templates for Agent plan review interaction.

Builds interactive cards for presenting technical plan summaries,
with approve/revise buttons and feedback input for iterative refinement.
"""

from typing import Any

# Maximum summary length to keep card under 30KB Feishu limit
_MAX_SUMMARY_LENGTH = 2000


def _truncate_summary(summary: str) -> str:
    """Truncate plan summary to fit within card size limits.

    Args:
        summary: The full plan summary text

    Returns:
        Truncated summary with indicator if truncated
    """
    if len(summary) <= _MAX_SUMMARY_LENGTH:
        return summary
    return summary[:_MAX_SUMMARY_LENGTH] + "\n\n_...内容过长已截断，请查看完整方案文档_"


def build_plan_card(
    plan_summary: str,
    document_url: str,
    session_id: str,
    iteration: int = 1,
    iteration_history: list[str] | None = None,
) -> dict[str, Any]:
    """Build an interactive plan review card for user approval.

    Creates a Feishu card with:
    - Header with iteration version (blue theme)
    - Truncated plan summary (max 2000 chars to stay under 30KB)
    - Link to full plan document
    - Iteration history (if multi-round)
    - Approve/Revise action buttons
    - Text input form for detailed feedback

    Args:
        plan_summary: Plan summary text (will be truncated if > 2000 chars)
        document_url: URL to the full plan document on Feishu
        session_id: Agent session ID for callback matching
        iteration: Current iteration number (1-based)
        iteration_history: List of previous iteration summaries (e.g. "v1: initial")

    Returns:
        Feishu card JSON structure ready for sending

    Example:
        >>> card = build_plan_card(
        ...     plan_summary="This plan covers...",
        ...     document_url="https://feishu.cn/docx/xxx",
        ...     session_id="wf-123",
        ...     iteration=2,
        ...     iteration_history=["v1: initial draft"],
        ... )
    """
    elements: list[dict[str, Any]] = []

    # Plan summary (truncated to stay within 30KB card limit)
    truncated_summary = _truncate_summary(plan_summary)
    elements.append({
        "tag": "markdown",
        "content": truncated_summary,
    })

    # Document link
    elements.append({
        "tag": "markdown",
        "content": f"📄 [查看完整方案]({document_url})",
    })

    # Divider
    elements.append({"tag": "hr"})

    # Iteration history (only shown for multi-round iterations)
    if iteration > 1 and iteration_history:
        history_lines = "**迭代历史:**\n"
        for entry in iteration_history:
            history_lines += f"- {entry}\n"
        elements.append({
            "tag": "markdown",
            "content": history_lines.strip(),
        })
        elements.append({"tag": "hr"})

    # Action buttons: approve and revise
    elements.append({
        "tag": "action",
        "actions": [
            {
                "tag": "button",
                "text": {"tag": "plain_text", "content": "✅ 确认方案"},
                "type": "primary",
                "value": {
                    "action": "plan_approve",
                    "session_id": session_id,
                },
            },
            {
                "tag": "button",
                "text": {"tag": "plain_text", "content": "📝 需要修改"},
                "type": "default",
                "value": {
                    "action": "plan_revise",
                    "session_id": session_id,
                },
            },
        ],
    })

    # Feedback form: text input + submit
    elements.append({
        "tag": "form",
        "name": "plan_feedback_form",
        "elements": [
            {
                "tag": "input",
                "name": "feedback_input",
                "placeholder": {"tag": "plain_text", "content": "请输入修改意见..."},
            },
            {
                "tag": "button",
                "text": {"tag": "plain_text", "content": "提交反馈"},
                "type": "primary",
                "action_type": "form_submit",
                "value": {
                    "action": "plan_feedback",
                    "session_id": session_id,
                },
            },
        ],
    })

    return {
        "config": {"wide_screen_mode": True},
        "header": {
            "title": {
                "tag": "plain_text",
                "content": f"📋 技术方案 v{iteration}",
            },
            "template": "blue",
        },
        "elements": elements,
    }


def build_plan_approved_card(
    plan_summary: str,
    document_url: str,
    iteration: int = 1,
) -> dict[str, Any]:
    """Build a card showing the approved state.

    Replaces the interactive card after user approves the plan.

    Args:
        plan_summary: Brief plan summary
        document_url: Link to full plan document
        iteration: Final iteration number

    Returns:
        Feishu card JSON showing approved state
    """
    truncated_summary = _truncate_summary(plan_summary)

    return {
        "config": {"wide_screen_mode": True},
        "header": {
            "title": {
                "tag": "plain_text",
                "content": f"✅ 技术方案 v{iteration} - 已确认",
            },
            "template": "green",
        },
        "elements": [
            {
                "tag": "markdown",
                "content": truncated_summary,
            },
            {
                "tag": "markdown",
                "content": f"📄 [查看完整方案]({document_url})",
            },
            {"tag": "hr"},
            {
                "tag": "markdown",
                "content": "✅ **方案已确认，AI 正在继续执行...**",
            },
        ],
    }


def build_plan_revising_card(
    plan_summary: str,
    document_url: str,
    iteration: int = 1,
) -> dict[str, Any]:
    """Build a card showing the revising state.

    Replaces the interactive card after user requests revision.

    Args:
        plan_summary: Brief plan summary
        document_url: Link to full plan document
        iteration: Current iteration number

    Returns:
        Feishu card JSON showing revision in progress
    """
    truncated_summary = _truncate_summary(plan_summary)

    return {
        "config": {"wide_screen_mode": True},
        "header": {
            "title": {
                "tag": "plain_text",
                "content": f"📝 技术方案 v{iteration} - 修改中",
            },
            "template": "orange",
        },
        "elements": [
            {
                "tag": "markdown",
                "content": truncated_summary,
            },
            {
                "tag": "markdown",
                "content": f"📄 [查看完整方案]({document_url})",
            },
            {"tag": "hr"},
            {
                "tag": "markdown",
                "content": "📝 **用户请求修改，AI 正在优化方案...**",
            },
        ],
    }


def build_plan_feedback_card(
    plan_summary: str,
    document_url: str,
    feedback: str,
    iteration: int = 1,
) -> dict[str, Any]:
    """Build a card showing feedback received state.

    Replaces the interactive card after user submits feedback.

    Args:
        plan_summary: Brief plan summary
        document_url: Link to full plan document
        feedback: The user's feedback text
        iteration: Current iteration number

    Returns:
        Feishu card JSON showing feedback received
    """
    truncated_summary = _truncate_summary(plan_summary)
    # Truncate feedback display to avoid card bloat
    feedback_display = feedback[:200] + "..." if len(feedback) > 200 else feedback

    return {
        "config": {"wide_screen_mode": True},
        "header": {
            "title": {
                "tag": "plain_text",
                "content": f"💬 技术方案 v{iteration} - 收到反馈",
            },
            "template": "orange",
        },
        "elements": [
            {
                "tag": "markdown",
                "content": truncated_summary,
            },
            {
                "tag": "markdown",
                "content": f"📄 [查看完整方案]({document_url})",
            },
            {"tag": "hr"},
            {
                "tag": "markdown",
                "content": f"💬 **反馈内容:** {feedback_display}",
            },
            {
                "tag": "markdown",
                "content": "_AI 正在根据反馈优化方案..._",
            },
        ],
    }
