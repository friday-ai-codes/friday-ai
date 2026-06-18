"""用户端反馈视图（adrf 异步，owner-scoped）。

- ``FeedbackListCreateView``：列出本人反馈 / 创建反馈。
- ``FeedbackDetailView``：本人反馈详情（含回复线程）。
- ``FeedbackAttachmentUploadView``：上传图片/视频附件，返回 storage_ref。
- ``FeedbackAttachmentView``：读取附件（owner 无关，引用即可读，靠随机 uuid 文件名防猜测）。
"""

from __future__ import annotations

from pathlib import Path

from adrf.views import APIView
from asgiref.sync import sync_to_async
from django.http import HttpResponse
from django.shortcuts import aget_object_or_404
from rest_framework import status
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from feedback.attachments import (
    AttachmentValidationError,
    content_type_for,
    read_attachment_bytes,
    store_attachment_bytes,
)
from feedback.models import Feedback
from feedback.services import FeedbackService

from .serializers import FeedbackCreateSerializer, FeedbackSerializer

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


class FeedbackListCreateView(APIView):
    """列出本人反馈 / 提交新反馈。"""

    permission_classes = [IsAuthenticated]

    async def get(self, request: Request) -> Response:
        qs = Feedback.objects.filter(created_by_id=request.user.id).prefetch_related("replies")
        limit, offset = _parse_pagination(request.query_params)
        total = await qs.acount()
        items = [item async for item in qs[offset : offset + limit]]
        data = await sync_to_async(lambda: FeedbackSerializer(items, many=True).data)()
        return Response({"items": data, "total": total, "limit": limit, "offset": offset})

    async def post(self, request: Request) -> Response:
        serializer = FeedbackCreateSerializer(data=request.data)
        await sync_to_async(serializer.is_valid)(raise_exception=True)
        data = serializer.validated_data

        feedback = await FeedbackService.create_feedback(
            user_id=request.user.id,
            category=data["category"],
            content=data["content"],
            title=data.get("title", ""),
            attachments=data.get("attachments") or [],
            page_url=data.get("page_url", ""),
            conversation_id=data.get("conversation_id"),
            message_id=data.get("message_id"),
        )
        payload = await sync_to_async(lambda: FeedbackSerializer(feedback).data)()
        return Response(payload, status=status.HTTP_201_CREATED)


class FeedbackDetailView(APIView):
    """本人反馈详情。"""

    permission_classes = [IsAuthenticated]

    async def get(self, request: Request, feedback_id: str) -> Response:
        feedback = await aget_object_or_404(
            Feedback.objects.prefetch_related("replies"),
            id=feedback_id,
            created_by_id=request.user.id,
        )
        data = await sync_to_async(lambda: FeedbackSerializer(feedback).data)()
        return Response(data)


class FeedbackAttachmentUploadView(APIView):
    """上传单个反馈附件（图片/视频），返回 storage_ref 引用。"""

    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser]

    async def post(self, request: Request) -> Response:
        uploaded = request.FILES.get("file") or request.FILES.get("attachment")
        if uploaded is None:
            return Response(
                {"code": "missing_file", "error": "请上传附件文件"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            raw = await sync_to_async(uploaded.read)()
            stored = await sync_to_async(store_attachment_bytes)(
                raw,
                declared_mime_type=getattr(uploaded, "content_type", "") or "",
            )
        except AttachmentValidationError as exc:
            return Response(
                {"code": exc.code, "error": exc.message},
                status=status.HTTP_400_BAD_REQUEST,
            )

        file_name = Path(stored.storage_ref).name
        return Response(
            {
                "storage_ref": stored.storage_ref,
                "kind": stored.kind,
                "mime": stored.mime_type,
                "size": stored.size_bytes,
                "name": getattr(uploaded, "name", "") or file_name,
                "url": f"/api/feedback/attachments/{file_name}/",
            },
            status=status.HTTP_201_CREATED,
        )


class FeedbackAttachmentView(APIView):
    """读取已上传的反馈附件。"""

    permission_classes = [IsAuthenticated]

    async def get(self, request: Request, file_name: str) -> HttpResponse:
        storage_ref = f"feedback_attachments/{file_name}"
        try:
            data = await sync_to_async(read_attachment_bytes)(storage_ref)
        except AttachmentValidationError as exc:
            return Response(
                {"code": exc.code, "error": exc.message},
                status=status.HTTP_404_NOT_FOUND,
            )
        return HttpResponse(data, content_type=content_type_for(file_name))
