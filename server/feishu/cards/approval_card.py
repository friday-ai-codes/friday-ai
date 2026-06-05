"""Approval card templates for plan approval workflow node.

Builds interactive cards for plan approval/rejection,
with approve button and reject form (reason required).
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


def build_approval_card(
    plan_title: str,
    plan_summary: str,
    document_url: str,
    execution_id: str,
    node_id: str,
) -> dict[str, Any]:
    """Build interactive approval card for plan review.

    Creates a Feishu card with:
    - Plan title and truncated summary
    - Link to full plan document
    - Approve button (primary/green)
    - Reject form with required reason input

    Args:
        plan_title: Title of the technical plan
        plan_summary: Plan summary text (will be truncated if > 2000 chars)
        document_url: URL to the full plan document on Feishu
        execution_id: Workflow execution ID for callback matching
        node_id: Node execution ID for callback matching

    Returns:
        Feishu card JSON structure ready for sending
    """
    elements: list[dict[str, Any]] = []

    # Plan title and summary
    truncated_summary = _truncate_summary(plan_summary)
    elements.append({
        "tag": "markdown",
        "content": f"**{plan_title}**\n\n{truncated_summary}",
    })

    # Document link
    if document_url:
        elements.append({
            "tag": "markdown",
            "content": f"📄 [查看完整技术方案]({document_url})",
        })

    elements.append({"tag": "hr"})

    # Approve button
    elements.append({
        "tag": "action",
        "actions": [
            {
                "tag": "button",
                "text": {"tag": "plain_text", "content": "✅ 通过"},
                "type": "primary",
                "value": {
                    "action": "approval_approve",
                    "execution_id": execution_id,
                    "node_id": node_id,
                },
            },
        ],
    })

    elements.append({"tag": "hr"})

    # Reject form (reason required)
    elements.append({
        "tag": "form",
        "name": "approval_reject_form",
        "elements": [
            {
                "tag": "input",
                "name": "reject_reason",
                "placeholder": {"tag": "plain_text", "content": "请输入驳回理由（必填）..."},
                "required": True,
            },
            {
                "tag": "button",
                "text": {"tag": "plain_text", "content": "❌ 驳回"},
                "type": "danger",
                "action_type": "form_submit",
                "value": {
                    "action": "approval_reject",
                    "execution_id": execution_id,
                    "node_id": node_id,
                },
            },
        ],
    })

    return {
        "config": {"wide_screen_mode": True},
        "header": {
            "title": {"tag": "plain_text", "content": "📋 技术方案审批"},
            "template": "indigo",
        },
        "elements": elements,
    }


def build_approval_approved_card(
    plan_title: str,
    document_url: str,
) -> dict[str, Any]:
    """Build card showing approved state (replaces interactive card).

    Args:
        plan_title: Title of the approved plan
        document_url: Link to full plan document

    Returns:
        Feishu card JSON showing approved state
    """
    elements: list[dict[str, Any]] = [
        {"tag": "markdown", "content": f"**{plan_title}**"},
    ]
    if document_url:
        elements.append({"tag": "markdown", "content": f"📄 [查看完整方案]({document_url})"})
    elements.append({"tag": "hr"})
    elements.append({"tag": "markdown", "content": "✅ **方案已通过**"})

    return {
        "config": {"wide_screen_mode": True},
        "header": {
            "title": {"tag": "plain_text", "content": "✅ 技术方案 - 已通过"},
            "template": "green",
        },
        "elements": elements,
    }


def build_approval_rejected_card(
    plan_title: str,
    document_url: str,
    reject_reason: str,
) -> dict[str, Any]:
    """Build card showing rejected state (replaces interactive card).

    Args:
        plan_title: Title of the rejected plan
        document_url: Link to full plan document
        reject_reason: Reason for rejection

    Returns:
        Feishu card JSON showing rejected state with reason
    """
    reason_display = reject_reason[:200] + "..." if len(reject_reason) > 200 else reject_reason
    elements: list[dict[str, Any]] = [
        {"tag": "markdown", "content": f"**{plan_title}**"},
    ]
    if document_url:
        elements.append({"tag": "markdown", "content": f"📄 [查看完整方案]({document_url})"})
    elements.append({"tag": "hr"})
    elements.append({
        "tag": "markdown",
        "content": f"❌ **方案已驳回**\n\n**理由:** {reason_display}",
    })

    return {
        "config": {"wide_screen_mode": True},
        "header": {
            "title": {"tag": "plain_text", "content": "❌ 技术方案 - 已驳回"},
            "template": "red",
        },
        "elements": elements,
    }
