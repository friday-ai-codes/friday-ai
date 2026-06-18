"""站内信通知 REST 视图（adrf 异步，owner-scoped）。

所有端点仅作用于 ``request.user`` 本人的通知：
- ``NotificationListView``：列表（offset/limit 分页，支持 ``?unread=true`` 过滤）。
- ``NotificationUnreadCountView``：未读数。
- ``NotificationReadView``：标记单条已读。
- ``NotificationReadAllView``：全部标记已读。
"""

from __future__ import annotations

from adrf.views import APIView
from asgiref.sync import sync_to_async
from django.shortcuts import aget_object_or_404
from django.utils import timezone
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from notifications.models import Notification

from .serializers import NotificationSerializer

DEFAULT_LIMIT = 20
MAX_LIMIT = 100


def _parse_pagination(query_params) -> tuple[int, int]:
    try:
        limit = int(query_params.get("limit", DEFAULT_LIMIT))
    except (TypeError, ValueError):
        limit = DEFAULT_LIMIT
    try:
        offset = int(query_params.get("offset", 0))
    except (TypeError, ValueError):
        offset = 0
    limit = max(1, min(limit, MAX_LIMIT))
    offset = max(0, offset)
    return limit, offset


class NotificationListView(APIView):
    """当前用户的通知列表（分页 + 未读过滤）。"""

    permission_classes = [IsAuthenticated]

    async def get(self, request: Request) -> Response:
        qs = Notification.objects.filter(recipient_id=request.user.id)
        if request.query_params.get("unread") in ("1", "true", "True"):
            qs = qs.filter(read_at__isnull=True)

        limit, offset = _parse_pagination(request.query_params)
        total = await qs.acount()
        unread = await Notification.objects.filter(
            recipient_id=request.user.id, read_at__isnull=True
        ).acount()
        items = [item async for item in qs[offset : offset + limit]]
        data = await sync_to_async(lambda: NotificationSerializer(items, many=True).data)()
        return Response(
            {
                "items": data,
                "total": total,
                "unread": unread,
                "limit": limit,
                "offset": offset,
            }
        )


class NotificationUnreadCountView(APIView):
    """当前用户的未读通知数。"""

    permission_classes = [IsAuthenticated]

    async def get(self, request: Request) -> Response:
        unread = await Notification.objects.filter(
            recipient_id=request.user.id, read_at__isnull=True
        ).acount()
        return Response({"unread": unread})


class NotificationReadView(APIView):
    """标记单条通知为已读。"""

    permission_classes = [IsAuthenticated]

    async def post(self, request: Request, notification_id: str) -> Response:
        notification = await aget_object_or_404(
            Notification, id=notification_id, recipient_id=request.user.id
        )
        if notification.read_at is None:
            notification.read_at = timezone.now()
            await notification.asave(update_fields=["read_at"])
        data = await sync_to_async(lambda: NotificationSerializer(notification).data)()
        return Response(data)


class NotificationReadAllView(APIView):
    """把当前用户全部未读通知标记为已读。"""

    permission_classes = [IsAuthenticated]

    async def post(self, request: Request) -> Response:
        updated = await Notification.objects.filter(
            recipient_id=request.user.id, read_at__isnull=True
        ).aupdate(read_at=timezone.now())
        return Response({"updated": updated}, status=status.HTTP_200_OK)
