"""系统公告管理端 REST 视图（adrf 异步，IsSuperUser）。

挂载在 ``/api/admin/announcements/``（与用户端 ``/api/announcements/`` 物理分离）：
- ``AdminAnnouncementListCreateView``：列表（status/search 过滤 + 分页）/ 创建。
- ``AdminAnnouncementDetailView``：详情（GET）/ 更新（PUT/PATCH）/ 删除（DELETE）。
- ``AdminAnnouncementReadStatusView``：某公告的按用户已读状态（分页 + 搜索）。

创建/发布会通过 ``AnnouncementService`` 在「展示中」时实时推送给受众。
"""

from __future__ import annotations

from adrf.views import APIView
from asgiref.sync import sync_to_async
from django.shortcuts import aget_object_or_404
from rest_framework import status
from rest_framework.request import Request
from rest_framework.response import Response

from notifications.models import Announcement
from notifications.services import AnnouncementService
from permissions.api_permissions import IsSuperUser

from .serializers import AdminAnnouncementSerializer

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
    return max(1, min(limit, MAX_LIMIT)), max(0, offset)


class AdminAnnouncementListCreateView(APIView):
    """公告列表（过滤 + 分页）/ 创建，仅 superuser。"""

    permission_classes = [IsSuperUser]

    async def get(self, request: Request) -> Response:
        qs = Announcement.objects.all()
        status_filter = request.query_params.get("status")
        if status_filter:
            qs = qs.filter(status=status_filter)
        search = request.query_params.get("search")
        if search:
            qs = qs.filter(title__icontains=search)

        limit, offset = _parse_pagination(request.query_params)
        total = await qs.acount()
        items = [item async for item in qs[offset : offset + limit]]
        data = await sync_to_async(lambda: AdminAnnouncementSerializer(items, many=True).data)()
        return Response({"items": data, "total": total, "limit": limit, "offset": offset})

    async def post(self, request: Request) -> Response:
        serializer = AdminAnnouncementSerializer(data=request.data)
        await sync_to_async(serializer.is_valid)(raise_exception=True)
        v = serializer.validated_data
        announcement = await AnnouncementService.create(
            title=v["title"],
            body=v["body"],
            link=v.get("link", ""),
            status=v.get("status", Announcement.Status.DRAFT),
            notify_mode=v.get("notify_mode", Announcement.NotifyMode.POPUP),
            audience=v.get("audience", Announcement.Audience.ALL),
            target_user_ids=v.get("target_user_ids", []),
            starts_at=v.get("starts_at"),
            ends_at=v.get("ends_at"),
            created_by_id=request.user.id,
        )
        data = await sync_to_async(lambda: AdminAnnouncementSerializer(announcement).data)()
        return Response(data, status=status.HTTP_201_CREATED)


class AdminAnnouncementDetailView(APIView):
    """公告详情 / 更新 / 删除，仅 superuser。"""

    permission_classes = [IsSuperUser]

    async def get(self, request: Request, announcement_id: str) -> Response:
        announcement = await aget_object_or_404(Announcement, id=announcement_id)
        data = await sync_to_async(lambda: AdminAnnouncementSerializer(announcement).data)()
        return Response(data)

    async def put(self, request: Request, announcement_id: str) -> Response:
        return await self._update(request, announcement_id, partial=False)

    async def patch(self, request: Request, announcement_id: str) -> Response:
        return await self._update(request, announcement_id, partial=True)

    async def _update(self, request: Request, announcement_id: str, *, partial: bool) -> Response:
        announcement = await aget_object_or_404(Announcement, id=announcement_id)
        serializer = AdminAnnouncementSerializer(announcement, data=request.data, partial=partial)
        await sync_to_async(serializer.is_valid)(raise_exception=True)
        announcement = await AnnouncementService.update(
            announcement, fields=dict(serializer.validated_data)
        )
        data = await sync_to_async(lambda: AdminAnnouncementSerializer(announcement).data)()
        return Response(data)

    async def delete(self, request: Request, announcement_id: str) -> Response:
        announcement = await aget_object_or_404(Announcement, id=announcement_id)
        await AnnouncementService.delete(announcement)
        return Response(status=status.HTTP_204_NO_CONTENT)


class AdminAnnouncementReadStatusView(APIView):
    """某公告的按用户已读状态（分页 + 搜索），仅 superuser。"""

    permission_classes = [IsSuperUser]

    async def get(self, request: Request, announcement_id: str) -> Response:
        announcement = await aget_object_or_404(Announcement, id=announcement_id)
        limit, offset = _parse_pagination(request.query_params)
        search = (request.query_params.get("search") or "").strip()
        result = await AnnouncementService.read_status(
            announcement, search=search, limit=limit, offset=offset
        )
        return Response(result)
