"""系统公告用户端 REST 视图（adrf 异步，owner-scoped 可见性）。

仅暴露「展示中且对当前用户可见」的公告：
- ``AnnouncementListView``：列表（``?unread_only=true`` 过滤）。
- ``AnnouncementUnreadCountView``：未读数。
- ``AnnouncementPopupView``：登录后需弹窗的公告（popup 模式 + 未读）。
- ``AnnouncementReadView``：标记单条已读。
"""

from __future__ import annotations

from adrf.views import APIView
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from notifications.services import AnnouncementService


def _is_truthy(value) -> bool:
    return str(value).lower() in ("1", "true", "yes", "y", "on")


class AnnouncementListView(APIView):
    """当前用户可见的公告列表。"""

    permission_classes = [IsAuthenticated]

    async def get(self, request: Request) -> Response:
        unread_only = _is_truthy(request.query_params.get("unread_only"))
        items = await AnnouncementService.list_for_user(request.user.id, unread_only=unread_only)
        unread = len([it for it in items if not it["is_read"]])
        return Response({"items": items, "total": len(items), "unread": unread})


class AnnouncementUnreadCountView(APIView):
    """当前用户未读公告数。"""

    permission_classes = [IsAuthenticated]

    async def get(self, request: Request) -> Response:
        count = await AnnouncementService.unread_count_for_user(request.user.id)
        return Response({"unread": count})


class AnnouncementPopupView(APIView):
    """登录后需弹窗的公告（popup 模式 + 未读）。"""

    permission_classes = [IsAuthenticated]

    async def get(self, request: Request) -> Response:
        items = await AnnouncementService.popup_for_user(request.user.id)
        return Response({"items": items})


class AnnouncementReadView(APIView):
    """标记单条公告为已读。"""

    permission_classes = [IsAuthenticated]

    async def post(self, request: Request, announcement_id: str) -> Response:
        ok = await AnnouncementService.mark_read(request.user.id, announcement_id)
        if not ok:
            return Response(
                {"code": "not_visible", "error": "公告不存在或对你不可见"},
                status=status.HTTP_404_NOT_FOUND,
            )
        return Response({"ok": True})
