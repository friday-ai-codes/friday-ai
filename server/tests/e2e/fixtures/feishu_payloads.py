"""Feishu webhook payload factories for E2E testing.

These factories create realistic Feishu webhook payloads matching
the actual payload structure received from Feishu Space webhooks.
"""

import uuid
from typing import TYPE_CHECKING, Any, Protocol


class FeishuProjectProtocol(Protocol):
    """Protocol for objects with Feishu project attributes."""

    feishu_project_key: str | None
    feishu_webhook_token: str | None


if TYPE_CHECKING:
    from projects.models import Space


def create_workitem_create_payload(
    project: "Space | FeishuProjectProtocol",
    work_item_id: str,
    name: str,
    description: str = "",
    work_item_type: str = "story",
    extra_fields: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Create a WorkitemCreateEvent webhook payload.

    Args:
        project: Space with feishu_project_key and feishu_webhook_token
        work_item_id: The Feishu work item ID
        name: Work item name/title
        description: Work item description
        work_item_type: Type of work item (story, task, bug, etc.)
        extra_fields: Additional fields to include in the payload

    Returns:
        Dictionary matching Feishu WorkitemCreateEvent structure
    """
    payload: dict[str, Any] = {
        "header": {
            "uuid": str(uuid.uuid4()),
            "event_type": "WorkitemCreateEvent",
            "token": project.feishu_webhook_token or "",
            "create_time": "2026-02-03T12:00:00Z",
        },
        "payload": {
            "id": work_item_id,
            "project_key": project.feishu_project_key or "",
            "work_item_type_key": work_item_type,
            "name": name,
            "description": description,
            "current_status_key": "created",
            "created_at": "2026-02-03T12:00:00Z",
            "updated_at": "2026-02-03T12:00:00Z",
            "fields": {
                "name": name,
                "description": description,
                **(extra_fields or {}),
            },
        },
    }

    return payload


def create_workitem_update_payload(
    project: "Space | FeishuProjectProtocol",
    work_item_id: str,
    changed_fields: dict[str, Any],
    work_item_type: str = "story",
    current_status: str = "in_progress",
) -> dict[str, Any]:
    """Create a WorkitemUpdateEvent webhook payload.

    Args:
        project: Space with feishu_project_key and feishu_webhook_token
        work_item_id: The Feishu work item ID
        changed_fields: Dictionary of changed field keys and their new values
        work_item_type: Type of work item
        current_status: Current status of the work item

    Returns:
        Dictionary matching Feishu WorkitemUpdateEvent structure
    """
    # Build field changes array
    field_changes = [
        {
            "field_key": key,
            "field_value": value,
            "field_type": _infer_field_type(value),
        }
        for key, value in changed_fields.items()
    ]

    payload: dict[str, Any] = {
        "header": {
            "uuid": str(uuid.uuid4()),
            "event_type": "WorkitemUpdateEvent",
            "token": project.feishu_webhook_token or "",
            "create_time": "2026-02-03T12:00:00Z",
        },
        "payload": {
            "id": work_item_id,
            "project_key": project.feishu_project_key or "",
            "work_item_type_key": work_item_type,
            "current_status_key": current_status,
            "field_changes": field_changes,
            "updated_at": "2026-02-03T12:00:00Z",
        },
    }

    return payload


def create_workitem_comment_payload(
    project: "Space | FeishuProjectProtocol",
    work_item_id: str,
    comment: str,
    work_item_type: str = "story",
) -> dict[str, Any]:
    """Create a WorkitemCommentEvent webhook payload.

    Args:
        project: Space with feishu_project_key and feishu_webhook_token
        work_item_id: The Feishu work item ID
        comment: Comment text
        work_item_type: Type of work item

    Returns:
        Dictionary matching Feishu WorkitemCommentEvent structure
    """
    return {
        "header": {
            "uuid": f"test-uuid-{work_item_id}-{hash(comment) % 10000}",
            "event_type": "WorkitemCommentEvent",
            "token": project.feishu_webhook_token or "",
        },
        "payload": {
            "id": work_item_id,
            "project_key": project.feishu_project_key or "",
            "comment": comment,
            "work_item_type_key": work_item_type,
        },
    }


def create_status_change_payload(
    project: "Space | FeishuProjectProtocol",
    work_item_id: str,
    from_status: str,
    to_status: str,
    work_item_type: str = "story",
) -> dict[str, Any]:
    """Create a WorkitemUpdateEvent payload for status change.

    Args:
        project: Space with feishu_project_key and feishu_webhook_token
        work_item_id: The Feishu work item ID
        from_status: Previous status key
        to_status: New status key
        work_item_type: Type of work item

    Returns:
        Dictionary matching Feishu WorkitemUpdateEvent structure for status changes
    """
    return {
        "header": {
            "uuid": str(uuid.uuid4()),
            "event_type": "WorkitemUpdateEvent",
            "token": project.feishu_webhook_token or "",
            "create_time": "2026-02-03T12:00:00Z",
        },
        "payload": {
            "id": work_item_id,
            "project_key": project.feishu_project_key or "",
            "work_item_type_key": work_item_type,
            "current_status_key": to_status,
            "previous_status_key": from_status,
            "field_changes": [
                {
                    "field_key": "status",
                    "field_value": to_status,
                    "field_type": "status",
                }
            ],
            "updated_at": "2026-02-03T12:00:00Z",
        },
    }


def _infer_field_type(value: Any) -> str:
    """Infer Feishu field type from Python value."""
    if isinstance(value, bool):
        return "boolean"
    elif isinstance(value, int):
        return "number"
    elif isinstance(value, float):
        return "number"
    elif isinstance(value, list):
        return "multi_select"
    elif isinstance(value, dict):
        return "object"
    else:
        return "text"
