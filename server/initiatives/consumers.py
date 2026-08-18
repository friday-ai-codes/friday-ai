"""项目实时推送 WebSocket consumer（MEMBER-03）。

客户端连接 ``ws/projects/{project_id}/``。鉴权由 ``JWTCookieAuthMiddleware``（复用
``notifications.middleware``）完成（填充 ``scope["user"]``）；连接时 fail-closed 校验当前用户
对该项目的可见性（Space 成员或项目成员），通过则加入 ``project_{id}`` 分组。
``ProjectService`` 写库后经 ``apush_project_event`` group_send，``project_event`` handler 转发前端。
"""

from __future__ import annotations

import json

import structlog
from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncWebsocketConsumer

from common.channel_groups import safe_group_add, safe_group_discard
from initiatives.services.realtime import project_group_name

logger = structlog.get_logger(__name__)


class ProjectConsumer(AsyncWebsocketConsumer):
    """项目级成员/状态变更实时推送 consumer。"""

    async def connect(self) -> None:
        user = self.scope.get("user")
        if user is None or not getattr(user, "is_authenticated", False):
            await self.close(code=4401)
            return

        self.project_id = self.scope["url_route"]["kwargs"]["project_id"]
        if not await self._can_view(user, self.project_id):
            await self.close(code=4403)
            return

        self.group_name = project_group_name(self.project_id)
        if not await safe_group_add(
            self.channel_layer,
            self.group_name,
            self.channel_name,
            component="initiatives",
            initiated_by_user_id=str(user.id),
        ):
            await self.close(code=1013)
            return
        await self.accept()

    async def disconnect(self, close_code: int) -> None:
        group_name = getattr(self, "group_name", None)
        if group_name:
            await safe_group_discard(
                self.channel_layer,
                group_name,
                self.channel_name,
                component="initiatives",
            )

    async def project_event(self, event: dict) -> None:
        """转发 channel layer 广播的项目事件给前端。"""
        await self.send(
            text_data=json.dumps(
                {
                    "type": "project_event",
                    "event": event.get("event"),
                    "project_id": event.get("project_id"),
                    "data": event.get("data"),
                }
            )
        )

    @database_sync_to_async
    def _can_view(self, user, project_id) -> bool:
        """fail-closed 可见性：superuser / 项目所属 Space 成员 / 项目成员。"""
        if getattr(user, "is_superuser", False):
            return True
        from initiatives.models import Project, ProjectMember
        from permissions.models import SpaceMembership

        project = (
            Project.objects.filter(pk=project_id).values_list("space_id", flat=True).first()
        )
        if project is None:
            return False
        if SpaceMembership.objects.filter(space_id=project, user=user).exists():
            return True
        return ProjectMember.objects.filter(project_id=project_id, user=user).exists()
