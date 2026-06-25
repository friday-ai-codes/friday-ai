"""项目实时推送 helper（MEMBER-03）。

复用既有 channels 范式（参照 ``notifications.services.notification_service``）：per-project
分组 ``project_{id}``，``ProjectService`` 写库后经 ``group_send`` 推送成员/状态变更事件。
**best-effort**——channel layer 缺失或推送失败仅 warning，绝不反噬主写入（观测/推送不反噬业务）。
"""

from __future__ import annotations

from typing import Any

import structlog
from channels.layers import get_channel_layer

logger = structlog.get_logger(__name__)


def project_group_name(project_id: Any) -> str:
    """项目专属 channel 分组名。"""
    return f"project_{project_id}"


async def apush_project_event(
    project_id: Any, event_type: str, payload: dict[str, Any]
) -> None:
    """向 ``project_{id}`` 分组推送一条事件（best-effort，失败不抛）。

    Args:
        project_id: 目标项目 id。
        event_type: 业务事件类型（如 ``status_changed`` / ``member_changed``）。
        payload: 事件数据（应已为可 JSON 序列化的标量 dict，不含凭证）。
    """
    channel_layer = get_channel_layer()
    if channel_layer is None:
        return
    try:
        await channel_layer.group_send(
            project_group_name(project_id),
            {
                "type": "project.event",
                "event": event_type,
                "project_id": str(project_id),
                "data": payload,
            },
        )
    except Exception as exc:  # noqa: BLE001 — 推送失败绝不反噬主写入
        logger.warning(
            "project_event_push_failed",
            project_id=str(project_id),
            event=event_type,
            error=str(exc),
            error_type=type(exc).__name__,
            component="initiatives",
            category="sampling",
        )
