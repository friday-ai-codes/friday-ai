"""站内信 WebSocket consumer。

客户端连接 ``ws/notifications/``。鉴权由 ``JWTCookieAuthMiddleware`` 完成（填充
``scope["user"]``）；已认证用户加入 ``notifications_user_{user_id}`` 分组，连接建立时
立即下发当前未读数。``NotificationService`` 落库新通知后通过 ``group_send`` 推送，
经 ``notification_message`` handler 转发给前端。
"""

from __future__ import annotations

import json

import structlog
from channels.generic.websocket import AsyncWebsocketConsumer

from notifications.services import (
    NotificationService,
    broadcast_group_name,
    notification_group_name,
)

logger = structlog.get_logger(__name__)


class NotificationConsumer(AsyncWebsocketConsumer):
    """用户级站内信实时推送 consumer。"""

    async def connect(self) -> None:
        user = self.scope.get("user")
        if user is None or not getattr(user, "is_authenticated", False):
            await self.close(code=4401)
            return

        self.user_id = str(user.id)
        self.group_name = notification_group_name(self.user_id)
        await self.channel_layer.group_add(self.group_name, self.channel_name)
        # 全体广播分组（audience=all 系统公告实时下发）
        self.broadcast_group = broadcast_group_name()
        await self.channel_layer.group_add(self.broadcast_group, self.channel_name)
        await self.accept()

        # 连接建立即下发当前未读数，避免前端首屏角标延迟
        try:
            unread = await NotificationService.aunread_count(self.user_id)
            await self.send(text_data=json.dumps({"type": "unread_count", "unread_count": unread}))
        except Exception as exc:  # noqa: BLE001
            logger.warning("notification_ws_initial_unread_failed", error=str(exc))

    async def disconnect(self, close_code: int) -> None:
        group_name = getattr(self, "group_name", None)
        if group_name:
            await self.channel_layer.group_discard(group_name, self.channel_name)
        broadcast_group = getattr(self, "broadcast_group", None)
        if broadcast_group:
            await self.channel_layer.group_discard(broadcast_group, self.channel_name)

    async def notification_message(self, event: dict) -> None:
        """转发 channel layer 广播的新通知给前端。"""
        await self.send(
            text_data=json.dumps(
                {
                    "type": "notification",
                    "notification": event.get("notification"),
                    "unread_count": event.get("unread_count"),
                }
            )
        )

    async def announcement_message(self, event: dict) -> None:
        """转发 channel layer 广播的系统公告给前端。"""
        await self.send(
            text_data=json.dumps(
                {
                    "type": "announcement",
                    "announcement": event.get("announcement"),
                }
            )
        )
