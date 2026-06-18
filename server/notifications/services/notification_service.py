"""站内信通知服务：落库 + WebSocket 实时推送。

写入单一入口归本服务：先 ``acreate`` 落库，再通过 channel layer ``group_send`` 把通知
推送到 ``notifications_user_{recipient_id}`` 分组（``NotificationConsumer`` 监听该分组）。
推送 payload 同时带上收件人当前未读数，便于前端铃铛直接更新角标。
"""

from __future__ import annotations

from typing import Any

import structlog
from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer

from notifications.models import Notification

logger = structlog.get_logger(__name__)


def notification_group_name(recipient_id: Any) -> str:
    """收件人专属 channel 分组名。"""
    return f"notifications_user_{recipient_id}"


def serialize_notification(notification: Notification) -> dict[str, Any]:
    """把 Notification 序列化为 WS / REST 可直接下发的 dict（不依赖 DRF）。"""
    return {
        "id": str(notification.id),
        "type": notification.type,
        "title": notification.title,
        "body": notification.body,
        "link": notification.link,
        "metadata": notification.metadata or {},
        "read_at": notification.read_at.isoformat() if notification.read_at else None,
        "is_read": notification.read_at is not None,
        "created_at": notification.created_at.isoformat() if notification.created_at else None,
    }


class NotificationService:
    """站内信通知领域服务（落库 + 实时推送）。"""

    @staticmethod
    async def create_and_push(
        *,
        recipient_id: Any,
        type: str = Notification.Type.SYSTEM,
        title: str,
        body: str = "",
        link: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> Notification:
        """创建通知并实时推送给收件人。"""
        notification = await Notification.objects.acreate(
            recipient_id=recipient_id,
            type=type,
            title=title,
            body=body or "",
            link=link or "",
            metadata=metadata or {},
        )
        await NotificationService._push(notification)
        return notification

    @staticmethod
    async def aunread_count(recipient_id: Any) -> int:
        """收件人未读通知数。"""
        return await Notification.objects.filter(
            recipient_id=recipient_id, read_at__isnull=True
        ).acount()

    @staticmethod
    async def _push(notification: Notification) -> None:
        """通过 channel layer 把通知推送到收件人分组（失败仅告警，不影响落库）。"""
        channel_layer = get_channel_layer()
        if channel_layer is None:
            return
        try:
            unread = await NotificationService.aunread_count(notification.recipient_id)
            await channel_layer.group_send(
                notification_group_name(notification.recipient_id),
                {
                    "type": "notification.message",
                    "notification": serialize_notification(notification),
                    "unread_count": unread,
                },
            )
        except Exception as exc:  # noqa: BLE001 — 推送失败不阻断业务
            logger.warning(
                "notification_push_failed",
                notification_id=str(notification.id),
                error=str(exc),
            )

    @staticmethod
    def push_sync(notification: Notification) -> None:
        """同步上下文推送（供 signal / 非 async 调用方使用）。"""
        async_to_sync(NotificationService._push)(notification)
