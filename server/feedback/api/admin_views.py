"""管理端反馈视图（adrf 异步，IsSuperUser）。

挂载在 ``/api/admin/feedback/``（与用户端 ``/api/feedback/`` 物理分离）：
- ``AdminFeedbackListView``：全量列表 + status/category 过滤 + 关键词搜索 + 分页。
- ``AdminFeedbackDetailView``：详情（GET）/ 改状态（PATCH，可触发站内信）。
- ``AdminFeedbackReplyView``：管理员回复（触发站内信给提交者）。
"""

from __future__ import annotations

from adrf.views import APIView
from asgiref.sync import sync_to_async
from django.db.models import Q
from django.shortcuts import aget_object_or_404
from rest_framework import status
from rest_framework.request import Request
from rest_framework.response import Response

from feedback.models import Feedback
from feedback.services import FeedbackService
from permissions.api_permissions import IsSuperUser

from .serializers import FeedbackSerializer

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


def _actor_repr(user) -> str:
    name = getattr(user, "username", "") or getattr(user, "email", "") or str(user.id)
    return f"{name} (superuser)" if getattr(user, "is_superuser", False) else name


class AdminFeedbackListView(APIView):
    """全量反馈列表（过滤 + 搜索 + 分页），仅 superuser。"""

    permission_classes = [IsSuperUser]

    async def get(self, request: Request) -> Response:
        qs = Feedback.objects.all().prefetch_related("replies")

        status_filter = request.query_params.get("status")
        if status_filter:
            qs = qs.filter(status=status_filter)
        category_filter = request.query_params.get("category")
        if category_filter:
            qs = qs.filter(category=category_filter)
        search = request.query_params.get("search")
        if search:
            qs = qs.filter(Q(title__icontains=search) | Q(content__icontains=search))

        limit, offset = _parse_pagination(request.query_params)
        total = await qs.acount()
        items = [item async for item in qs[offset : offset + limit]]
        data = await sync_to_async(lambda: FeedbackSerializer(items, many=True).data)()
        return Response({"items": data, "total": total, "limit": limit, "offset": offset})


class AdminFeedbackDetailView(APIView):
    """反馈详情（GET）/ 改状态（PATCH），仅 superuser。"""

    permission_classes = [IsSuperUser]

    async def get(self, request: Request, feedback_id: str) -> Response:
        feedback = await aget_object_or_404(
            Feedback.objects.prefetch_related("replies"), id=feedback_id
        )
        data = await sync_to_async(lambda: FeedbackSerializer(feedback).data)()
        return Response(data)

    async def patch(self, request: Request, feedback_id: str) -> Response:
        feedback = await aget_object_or_404(Feedback, id=feedback_id)
        new_status = request.data.get("status")
        valid = {choice[0] for choice in Feedback.Status.choices}
        if new_status not in valid:
            return Response(
                {"code": "invalid_status", "error": "无效的反馈状态"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        notify = request.data.get("notify", True)
        feedback = await FeedbackService.update_status(
            feedback=feedback, status=new_status, notify=bool(notify)
        )
        feedback = await aget_object_or_404(
            Feedback.objects.prefetch_related("replies"), id=feedback_id
        )
        data = await sync_to_async(lambda: FeedbackSerializer(feedback).data)()
        return Response(data)


class AdminFeedbackReplyView(APIView):
    """管理员回复反馈（触发站内信），仅 superuser。"""

    permission_classes = [IsSuperUser]

    async def post(self, request: Request, feedback_id: str) -> Response:
        feedback = await aget_object_or_404(Feedback, id=feedback_id)
        content = (request.data.get("content") or "").strip()
        if not content:
            return Response(
                {"code": "empty_content", "error": "回复内容不能为空"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        await FeedbackService.add_admin_reply(
            feedback=feedback,
            author_id=request.user.id,
            author_repr=_actor_repr(request.user),
            content=content,
        )
        feedback = await aget_object_or_404(
            Feedback.objects.prefetch_related("replies"), id=feedback_id
        )
        data = await sync_to_async(lambda: FeedbackSerializer(feedback).data)()
        return Response(data, status=status.HTTP_201_CREATED)
