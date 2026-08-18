"""chat 会话实时同步 WebSocket consumer。

客户端连接 ``ws/chat/``，鉴权由 ``JWTCookieAuthMiddleware`` 完成（填充 ``scope["user"]``）。
连接即加入 ``chat_user_{user_id}`` 分组（本人个人/自建共享会话事件）。客户端可发送
``{"action":"subscribe_project","project_id":"..."}`` 订阅项目共享分组——服务端校验
该用户确为项目成员后才加入 ``chat_project_{project_id}``（fail-closed，防越权偷看他人共享会话）。

广播由 ``chat.realtime`` 在会话新建 / 状态变更 / 新消息时经 ``group_send`` 下发，
经 ``chat_conversation`` / ``chat_message`` handler 转发给前端。
"""

from __future__ import annotations

import json

import structlog
from channels.generic.websocket import AsyncWebsocketConsumer

from chat.realtime import chat_project_group, chat_user_group
from common.channel_groups import safe_group_add, safe_group_discard

logger = structlog.get_logger(__name__)


class ChatConsumer(AsyncWebsocketConsumer):
    """项目/全局会话实时同步 consumer。"""

    async def connect(self) -> None:
        user = self.scope.get("user")
        if user is None or not getattr(user, "is_authenticated", False):
            await self.close(code=4401)
            return

        self.user_id = str(user.id)
        self.groups_joined: set[str] = set()
        user_group = chat_user_group(self.user_id)
        if not await safe_group_add(
            self.channel_layer,
            user_group,
            self.channel_name,
            component="chat",
            initiated_by_user_id=self.user_id,
        ):
            await self.close(code=1013)
            return
        self.groups_joined.add(user_group)
        await self.accept()
        logger.info(
            "chat_ws_connected",
            user_id=self.user_id,
            category="caller",
            component="chat_realtime",
        )

    async def disconnect(self, close_code: int) -> None:
        for group in getattr(self, "groups_joined", set()):
            await safe_group_discard(
                self.channel_layer,
                group,
                self.channel_name,
                component="chat",
                initiated_by_user_id=getattr(self, "user_id", "system"),
            )

    async def receive(self, text_data: str | None = None, bytes_data: bytes | None = None) -> None:
        try:
            data = json.loads(text_data or "{}")
        except (ValueError, TypeError):
            return
        action = data.get("action")
        if action == "subscribe_project":
            await self._subscribe_project(str(data.get("project_id") or ""))

    async def _subscribe_project(self, project_id: str) -> None:
        if not project_id:
            return
        if not await self._can_access_project(project_id):
            logger.info(
                "chat_ws_subscribe_project_denied",
                user_id=self.user_id,
                project_id=project_id,
                category="caller",
                component="chat_realtime",
            )
            return
        group = chat_project_group(project_id)
        if group in self.groups_joined:
            return
        # 订阅失败只放弃本次项目订阅、保持连接：用户组仍在，客户端可再发 subscribe_project 重试。
        if not await safe_group_add(
            self.channel_layer,
            group,
            self.channel_name,
            component="chat",
            initiated_by_user_id=self.user_id,
        ):
            return
        self.groups_joined.add(group)
        logger.info(
            "chat_ws_subscribed_project",
            user_id=self.user_id,
            project_id=project_id,
            category="caller",
            component="chat_realtime",
        )

    async def _can_access_project(self, project_id: str) -> bool:
        """fail-closed：仅项目成员可订阅项目共享分组。"""
        from initiatives.models.member import ProjectMember

        try:
            return await ProjectMember.objects.filter(
                project_id=project_id, user_id=self.user_id
            ).aexists()
        except Exception:  # noqa: BLE001 — 校验异常按拒绝处理
            return False

    # ── channel layer 广播 handler ───────────────────────────────────────
    async def chat_conversation(self, event: dict) -> None:
        await self.send(
            text_data=json.dumps(
                {
                    "type": "conversation",
                    "event": event.get("event"),
                    "conversation": event.get("conversation"),
                }
            )
        )

    async def chat_message(self, event: dict) -> None:
        await self.send(
            text_data=json.dumps(
                {
                    "type": "message",
                    "conversation_id": event.get("conversation_id"),
                    "conversation_status": event.get("conversation_status"),
                    "message": event.get("message"),
                }
            )
        )

    async def chat_stream(self, event: dict) -> None:
        """转发逐 token SSE 流事件给旁观者（打字机）。"""
        await self.send(
            text_data=json.dumps(
                {
                    "type": "stream",
                    "conversation_id": event.get("conversation_id"),
                    "payload": event.get("payload"),
                }
            )
        )
